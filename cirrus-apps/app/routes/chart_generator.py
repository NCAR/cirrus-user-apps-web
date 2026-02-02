import os
import io
import zipfile
import tempfile
from flask import Blueprint, render_template, request, send_file, jsonify
from github import Github, GithubException
from jinja2 import Template
from .helm_helpers import generate_helpers_tpl

chart_generator_bp = Blueprint('chart_generator', __name__)

CHART_TEMPLATES = {
    'web-app': {
        'name': 'Simple Web Application',
        'description': 'Basic containerized web application with optional ingress',
        'fields': ['app_name', 'image', 'replicas', 'port', 'enable_ingress', 'domain']
    },
    'autoscale': {
        'name': 'Autoscaling Web Application',
        'description': 'Web app with horizontal pod autoscaling based on CPU/memory',
        'fields': ['app_name', 'image', 'min_replicas', 'max_replicas', 'target_cpu', 'port', 'enable_ingress', 'domain']
    },
    'postgres': {
        'name': 'Web App with PostgreSQL',
        'description': 'Application with dedicated PostgreSQL database and persistent storage',
        'fields': ['app_name', 'image', 'replicas', 'port', 'db_name', 'db_user', 'storage_size', 'enable_ingress', 'domain']
    },
    'dask': {
        'name': 'Dask Cluster',
        'description': 'Dask scheduler and workers for distributed computing',
        'fields': ['app_name', 'image', 'scheduler_port', 'worker_replicas', 'worker_threads', 'worker_memory', 'enable_ingress', 'domain']
    },
    'nfs-volume': {
        'name': 'App with NFS Volume',
        'description': 'Mount existing NFS storage into your application',
        'fields': ['app_name', 'image', 'replicas', 'port', 'nfs_server', 'nfs_path', 'mount_path', 'enable_ingress', 'domain']
    },
    'cirrus-volume': {
        'name': 'App with Persistent Volume',
        'description': 'Application with CIRRUS persistent storage (RWO)',
        'fields': ['app_name', 'image', 'replicas', 'port', 'storage_size', 'mount_path', 'enable_ingress', 'domain']
    },
    'external-secret': {
        'name': 'App with External Secrets',
        'description': 'Inject secrets from Vault (bao.k8s.ucar.edu) as environment variables',
        'fields': ['app_name', 'image', 'replicas', 'port', 'secret_path', 'enable_ingress', 'domain']
    }
}


@chart_generator_bp.route('/helm-generator')
def helm_generator():
    """Render the Helm chart generator form"""
    return render_template('helm_generator.html', templates=CHART_TEMPLATES)


@chart_generator_bp.route('/api/generate-helm', methods=['POST'])
def generate_helm():
    """Generate Helm chart based on form input"""
    data = request.json
    chart_type = data.get('chart_type')
    output_format = data.get('output_format', 'zip')
    
    # Extract values - frontend sends flat structure
    values = {k: v for k, v in data.items() if k not in ['chart_type', 'output_format']}
    values['chart_type'] = chart_type  # Add back for use in generation
    
    if chart_type not in CHART_TEMPLATES:
        return jsonify({'error': 'Invalid chart type'}), 400
    
    # Generate Helm chart files
    chart_files = generate_chart_files(chart_type, values)
    
    if output_format == 'zip':
        # Create ZIP file
        zip_buffer = create_zip(chart_files, values['app_name'])
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{values['app_name']}-helm-chart.zip"
        )
    
    elif output_format == 'github_pr':
        # Create GitHub PR
        try:
            pr_url = create_github_pr(
                values.get('github_token'),
                values.get('github_repo'),
                values.get('github_branch', 'main'),
                chart_files,
                values
            )
            return jsonify({'success': True, 'pr_url': pr_url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid output format'}), 400


def generate_chart_files(chart_type, values):
    """Generate Helm chart files based on template type"""
    files = {}
    app_name = values.get('app_name', 'my-app')
    
    # Chart.yaml
    files['Chart.yaml'] = generate_chart_yaml(app_name, chart_type)
    
    # values.yaml
    files['values.yaml'] = generate_values_yaml(chart_type, values)
    
    # templates/_helpers.tpl
    files['templates/_helpers.tpl'] = generate_helpers_tpl()
    
    # templates/deployment.yaml
    files['templates/deployment.yaml'] = generate_deployment(chart_type, values)
    
    # templates/service.yaml
    files['templates/service.yaml'] = generate_service(values)
    
    # Conditional templates
    if values.get('enable_ingress'):
        files['templates/ingress.yaml'] = generate_ingress(values)
    
    if chart_type == 'autoscale':
        files['templates/hpa.yaml'] = generate_hpa(values)
    
    if chart_type == 'postgres':
        files['templates/postgres-statefulset.yaml'] = generate_postgres(values)
        files['templates/postgres-service.yaml'] = generate_postgres_service()
        files['templates/postgres-pvc.yaml'] = generate_postgres_pvc(values)
    
    if chart_type == 'dask':
        files['templates/dask-scheduler.yaml'] = generate_dask_scheduler(values)
        files['templates/dask-workers.yaml'] = generate_dask_workers(values)
    
    if chart_type == 'nfs-volume':
        files['templates/pv.yaml'] = generate_nfs_pv(values)
        files['templates/pvc.yaml'] = generate_nfs_pvc(values)
    
    if chart_type == 'cirrus-volume':
        files['templates/pvc.yaml'] = generate_cirrus_pvc(values)
    
    if chart_type == 'external-secret':
        files['templates/external-secret.yaml'] = generate_external_secret(values)
    
    # README
    files['README.md'] = generate_readme(chart_type, values)
    
    return files


def generate_chart_yaml(app_name, chart_type):
    """Generate Chart.yaml"""
    return f"""apiVersion: v2
name: {app_name}
description: A Helm chart for {CHART_TEMPLATES[chart_type]['name']}
type: application
version: 0.1.0
appVersion: "1.0"
"""


def generate_values_yaml(chart_type, values):
    """Generate values.yaml"""
    app_name = values.get('app_name', 'my-app')
    image = values.get('image', 'hub.k8s.ucar.edu/library/nginx:latest')
    
    base_values = f"""# Default values for {app_name}
replicaCount: {values.get('replicas', values.get('min_replicas', 1))}

image:
  repository: {image.rsplit(':', 1)[0] if ':' in image else image}
  tag: "{image.rsplit(':', 1)[1] if ':' in image else 'latest'}"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: {values.get('port', values.get('scheduler_port', 80))}

resources:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 100m
    memory: 128Mi
"""
    
    if chart_type == 'autoscale':
        base_values += f"""
autoscaling:
  enabled: true
  minReplicas: {values.get('min_replicas', 1)}
  maxReplicas: {values.get('max_replicas', 10)}
  targetCPUUtilizationPercentage: {values.get('target_cpu', 80)}
"""
    
    if chart_type == 'postgres':
        base_values += f"""
postgresql:
  enabled: true
  auth:
    database: {values.get('db_name', 'app_db')}
    username: {values.get('db_user', 'app_user')}
  persistence:
    size: {values.get('storage_size', '10Gi')}
"""
    
    if chart_type == 'dask':
        base_values += f"""
dask:
  worker:
    replicas: {values.get('worker_replicas', 3)}
    threads: {values.get('worker_threads', 4)}
    memory: {values.get('worker_memory', '4Gi')}
"""
    
    if chart_type == 'nfs-volume':
        base_values += f"""
persistence:
  nfs:
    server: {values.get('nfs_server', 'nfs.example.com')}
    path: {values.get('nfs_path', '/export/data')}
    mountPath: {values.get('mount_path', '/data')}
"""
    
    if chart_type == 'cirrus-volume':
        base_values += f"""
persistence:
  enabled: true
  storageClass: managed-nfs-storage
  size: {values.get('storage_size', '10Gi')}
  mountPath: {values.get('mount_path', '/data')}
"""
    
    if chart_type == 'external-secret':
        base_values += f"""
externalSecret:
  enabled: true
  secretPath: {values.get('secret_path', 'secret/data/myapp')}
  backend: vault
  vaultUrl: https://bao.k8s.ucar.edu
"""
    
    if values.get('enable_ingress'):
        base_values += f"""
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: {values.get('domain', f"{app_name}.k8s.ucar.edu")}
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: {app_name}-tls
      hosts:
        - {values.get('domain', f"{app_name}.k8s.ucar.edu")}
"""
    
    return base_values


def generate_deployment(chart_type, values):
    """Generate deployment.yaml template"""
    volume_mounts = ""
    volumes = ""
    
    if chart_type in ['nfs-volume', 'cirrus-volume']:
        mount_path = values.get('mount_path', '/data')
        volume_mounts = f"""
        volumeMounts:
        - name: data
          mountPath: {mount_path}"""
        volumes = """
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: {{ include "chart.fullname" . }}-pvc"""
    
    env_vars = ""
    if chart_type == 'postgres':
        env_vars = """
        env:
        - name: DATABASE_URL
          value: "postgresql://{{ .Values.postgresql.auth.username }}:$(DB_PASSWORD)@{{ include "chart.fullname" . }}-postgresql:5432/{{ .Values.postgresql.auth.database }}"
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ include "chart.fullname" . }}-postgresql
              key: password"""
    
    if chart_type == 'external-secret':
        env_vars = """
        envFrom:
        - secretRef:
            name: {{ include "chart.fullname" . }}-external-secret"""
    
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{{{ include "chart.fullname" . }}}}
  labels:
    {{{{- include "chart.labels" . | nindent 4 }}}}
spec:
  {{{{- if not .Values.autoscaling.enabled }}}}
  replicas: {{{{ .Values.replicaCount }}}}
  {{{{- end }}}}
  selector:
    matchLabels:
      {{{{- include "chart.selectorLabels" . | nindent 6 }}}}
  template:
    metadata:
      labels:
        {{{{- include "chart.selectorLabels" . | nindent 8 }}}}
    spec:
      containers:
      - name: {{{{ .Chart.Name }}}}
        image: "{{{{ .Values.image.repository }}}}:{{{{ .Values.image.tag }}}}"
        imagePullPolicy: {{{{ .Values.image.pullPolicy }}}}
        ports:
        - name: http
          containerPort: {{{{ .Values.service.port }}}}
          protocol: TCP{env_vars}{volume_mounts}
        resources:
          {{{{- toYaml .Values.resources | nindent 10 }}}}{volumes}
"""


def generate_service(values):
    """Generate service.yaml template"""
    return """apiVersion: v1
kind: Service
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
  - port: {{ .Values.service.port }}
    targetPort: http
    protocol: TCP
    name: http
  selector:
    {{- include "chart.selectorLabels" . | nindent 4 }}
"""


def generate_ingress(values):
    """Generate ingress.yaml template"""
    return """{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  {{- if .Values.ingress.tls }}
  tls:
    {{- range .Values.ingress.tls }}
    - hosts:
        {{- range .hosts }}
        - {{ . | quote }}
        {{- end }}
      secretName: {{ .secretName }}
    {{- end }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType }}
            backend:
              service:
                name: {{ include "chart.fullname" $ }}
                port:
                  number: {{ $.Values.service.port }}
          {{- end }}
    {{- end }}
{{- end }}
"""


def generate_hpa(values):
    """Generate HPA for autoscaling"""
    return """{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "chart.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
"""


def generate_postgres(values):
    """Generate PostgreSQL StatefulSet"""
    return """apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "chart.fullname" . }}-postgresql
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: database
spec:
  serviceName: {{ include "chart.fullname" . }}-postgresql
  replicas: 1
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: database
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: database
    spec:
      containers:
      - name: postgresql
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: {{ .Values.postgresql.auth.database }}
        - name: POSTGRES_USER
          value: {{ .Values.postgresql.auth.username }}
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ include "chart.fullname" . }}-postgresql
              key: password
        ports:
        - containerPort: 5432
          name: postgresql
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
          subPath: postgres
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: {{ include "chart.fullname" . }}-postgresql-pvc
"""


def generate_postgres_service():
    """Generate PostgreSQL service"""
    return """apiVersion: v1
kind: Service
metadata:
  name: {{ include "chart.fullname" . }}-postgresql
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: database
spec:
  type: ClusterIP
  ports:
  - port: 5432
    targetPort: postgresql
    protocol: TCP
    name: postgresql
  selector:
    {{- include "chart.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: database
"""


def generate_postgres_pvc(values):
    """Generate PostgreSQL PVC"""
    return """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "chart.fullname" . }}-postgresql-pvc
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.postgresql.persistence.size }}
  storageClassName: managed-nfs-storage
"""


def generate_dask_scheduler(values):
    """Generate Dask scheduler deployment"""
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "chart.fullname" . }}-scheduler
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: scheduler
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: scheduler
    spec:
      containers:
      - name: scheduler
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        command:
        - dask-scheduler
        ports:
        - containerPort: 8786
          name: scheduler
        - containerPort: 8787
          name: dashboard
"""


def generate_dask_workers(values):
    """Generate Dask workers deployment"""
    return """apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "chart.fullname" . }}-workers
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: worker
spec:
  replicas: {{ .Values.dask.worker.replicas }}
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: worker
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: worker
    spec:
      containers:
      - name: worker
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        command:
        - dask-worker
        - {{ include "chart.fullname" . }}-scheduler:8786
        - --nthreads
        - "{{ .Values.dask.worker.threads }}"
        - --memory-limit
        - "{{ .Values.dask.worker.memory }}"
        resources:
          limits:
            memory: {{ .Values.dask.worker.memory }}
"""


def generate_nfs_pv(values):
    """Generate NFS PersistentVolume"""
    return """apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ include "chart.fullname" . }}-nfs-pv
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  capacity:
    storage: 100Gi
  accessModes:
  - ReadWriteMany
  nfs:
    server: {{ .Values.persistence.nfs.server }}
    path: {{ .Values.persistence.nfs.path }}
  mountOptions:
  - vers=4
  - minorversion=1
"""


def generate_nfs_pvc(values):
    """Generate NFS PersistentVolumeClaim"""
    return """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "chart.fullname" . }}-pvc
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  accessModes:
  - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  volumeName: {{ include "chart.fullname" . }}-nfs-pv
"""


def generate_cirrus_pvc(values):
    """Generate CIRRUS PVC"""
    return """apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "chart.fullname" . }}-pvc
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.persistence.size }}
  storageClassName: {{ .Values.persistence.storageClass }}
"""


def generate_external_secret(values):
    """Generate ExternalSecret"""
    return """apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ include "chart.fullname" . }}-external-secret
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: {{ include "chart.fullname" . }}-external-secret
  data:
  - secretKey: credentials
    remoteRef:
      key: {{ .Values.externalSecret.secretPath }}
"""


def generate_readme(chart_type, values):
    """Generate README.md"""
    app_name = values.get('app_name', 'my-app')
    template_name = CHART_TEMPLATES[chart_type]['name']
    
    return f"""# {app_name}

Generated Helm chart for **{template_name}** using CIRRUS Helm Chart Generator.

## Prerequisites

- Access to CIRRUS Kubernetes cluster
- Docker image built and pushed to Harbor: `{values.get('image', 'hub.k8s.ucar.edu/...')}`
- kubectl configured with CIRRUS context

## Installation

```bash
helm install {app_name} .
```

## Configuration

Edit `values.yaml` to customize your deployment.

## Accessing Your Application

{f"Your application will be available at: https://{values.get('domain', f'{app_name}.k8s.ucar.edu')}" if values.get('enable_ingress') else "Configure an Ingress to expose your application externally."}

## Support

For issues or questions, create a ticket in the CIRRUS Jira project.

Generated by CIRRUS Helm Chart Generator - {CHART_TEMPLATES[chart_type]['description']}
"""


def create_zip(files, app_name):
    """Create a ZIP file containing all Helm chart files"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filepath, content in files.items():
            zip_file.writestr(f"{app_name}/{filepath}", content)
    
    zip_buffer.seek(0)
    return zip_buffer


def create_github_pr(token, repo_url, base_branch, files, values):
    """Create a GitHub PR with the generated Helm chart"""
    if not token or not repo_url:
        raise ValueError("GitHub token and repository URL are required")
    
    # Parse repo URL
    if repo_url.startswith('https://github.com/'):
        repo_path = repo_url.replace('https://github.com/', '').rstrip('.git')
    else:
        raise ValueError("Invalid GitHub repository URL")
    
    g = Github(token)
    repo = g.get_repo(repo_path)
    
    # Create a new branch
    app_name = values['app_name']
    new_branch = f"add-helm-chart-{app_name}"
    
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    repo.create_git_ref(f"refs/heads/{new_branch}", base_ref.object.sha)
    
    # Create/update files in the new branch
    for filepath, content in files.items():
        full_path = f"helm/{app_name}/{filepath}"
        try:
            # Try to get existing file
            existing_file = repo.get_contents(full_path, ref=new_branch)
            repo.update_file(
                full_path,
                f"Update {filepath}",
                content,
                existing_file.sha,
                branch=new_branch
            )
        except GithubException:
            # File doesn't exist, create it
            repo.create_file(
                full_path,
                f"Add {filepath}",
                content,
                branch=new_branch
            )
    
    # Create pull request
    pr = repo.create_pull(
        title=f"Add Helm chart for {app_name}",
        body=f"Generated Helm chart for {CHART_TEMPLATES[values['chart_type']]['name']}\n\nGenerated using CIRRUS Helm Chart Generator",
        head=new_branch,
        base=base_branch
    )
    
    return pr.html_url