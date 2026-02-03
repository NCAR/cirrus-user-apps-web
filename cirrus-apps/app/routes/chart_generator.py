import os
import io
import zipfile
from flask import Blueprint, render_template, request, send_file, jsonify
from github import Github, GithubException
from .helm_helpers import generate_helpers_tpl

chart_generator_bp = Blueprint('chart_generator', __name__)

# Add-on components that can be enabled
AVAILABLE_ADDONS = {
    'cnpg': {
        'name': 'CloudNativePG Cluster',
        'description': 'Production-grade PostgreSQL cluster with HA and backups',
        'fields': ['cnpg_instances', 'cnpg_storage_size', 'cnpg_backup_enabled', 
                   'cnpg_enable_superuser', 'cnpg_superuser_secret_path', 'cnpg_superuser_username_key', 'cnpg_superuser_password_key',
                   'cnpg_app_owner', 'cnpg_app_secret_path', 'cnpg_app_password_key']
    },
    'dask': {
        'name': 'Dask Cluster',
        'description': 'Distributed computing with Dask scheduler and workers',
        'fields': ['worker_replicas', 'worker_threads', 'worker_memory']
    },
    'persistence': {
        'name': 'Persistent Volume',
        'description': 'CIRRUS storage',
        'fields': ['pv_access_mode', 'pv_storage_size', 'pv_mount_path']
    },
    'nfs': {
        'name': 'NFS Volume',
        'description': 'Shared NFS storage - for external servers or Glade (contact cirrus-admin@ucar.edu for Glade access)',
        'fields': ['nfs_server', 'nfs_path', 'nfs_mount_path', 'nfs_readonly']
    },
    'external_secrets': {
        'name': 'External Secrets (Vault)',
        'description': 'Inject secrets from bao.k8s.ucar.edu',
        'fields': ['secret_path']
    }
}


@chart_generator_bp.route('/helm-generator')
def helm_generator():
    """Render the modular Helm chart generator form"""
    return render_template('helm_generator.html', addons=AVAILABLE_ADDONS)


@chart_generator_bp.route('/api/generate-helm', methods=['POST'])
def generate_helm():
    """Generate modular Helm chart based on selected add-ons"""
    data = request.json
    output_format = data.get('output_format', 'zip')
    
    # Extract base app config
    app_config = {
        'app_name': data.get('app_name'),
        'image': data.get('image'),
        'replicas': int(data.get('replicas', 2)),
        'port': int(data.get('port', 8080)),
        'enable_ingress': data.get('enable_ingress', False),
        'ingress_type': data.get('ingress_type', 'external'),
        'domain': data.get('domain', '')
    }
    
    # Extract enabled add-ons
    enabled_addons = data.get('enabled_addons', [])
    
    # Extract all field values
    addon_config = {}
    for k, v in data.items():
        if k not in ['app_name', 'image', 'replicas', 'port', 
                     'enable_ingress', 'ingress_type', 'domain', 'enabled_addons', 
                     'output_format', 'github_token', 'github_repo', 'github_branch']:
            # Convert numeric fields to int
            if k in ['cnpg_instances', 'worker_replicas', 'worker_threads']:
                addon_config[k] = int(v) if v else None
            # Convert boolean fields
            elif k in ['cnpg_backup_enabled', 'nfs_readonly', 'cnpg_enable_superuser']:
                addon_config[k] = v == 'true' if isinstance(v, str) else bool(v)
            else:
                addon_config[k] = v
    
    # Validate required fields
    if not app_config['app_name'] or not app_config['image']:
        return jsonify({'error': 'App name and image are required'}), 400
    
    # Generate Helm chart files
    chart_files = generate_modular_chart(app_config, enabled_addons, addon_config)
    
    if output_format == 'zip':
        # Create ZIP file
        zip_buffer = create_zip(chart_files, app_config['app_name'])
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{app_config['app_name']}-helm-chart.zip"
        )
    
    elif output_format == 'github_pr':
        # Create GitHub PR
        try:
            pr_url = create_github_pr(
                data.get('github_token'),
                data.get('github_repo'),
                data.get('github_branch', 'main'),
                chart_files,
                app_config,
                enabled_addons
            )
            return jsonify({'success': True, 'pr_url': pr_url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid output format'}), 400


def generate_modular_chart(app_config, enabled_addons, addon_config):
    """Generate modular Helm chart with base app + selected add-ons"""
    files = {}
    app_name = app_config['app_name']
    
    # Chart.yaml
    files['Chart.yaml'] = generate_chart_yaml(app_name)
    
    # values.yaml with all enabled components
    files['values.yaml'] = generate_modular_values(app_config, enabled_addons, addon_config)
    
    # templates/_helpers.tpl
    files['templates/_helpers.tpl'] = generate_helpers_tpl()
    
    # Base templates (always included)
    files['templates/deployment.yaml'] = generate_base_deployment(app_config, enabled_addons, addon_config)
    files['templates/service.yaml'] = generate_service()
    
    # Conditional templates based on enabled add-ons
    if app_config['enable_ingress']:
        files['templates/ingress.yaml'] = generate_ingress()
    
    if 'cnpg' in enabled_addons:
        files['templates/cnpg-cluster.yaml'] = generate_cnpg_cluster()
        files['templates/cnpg-app-user-secret.yaml'] = generate_cnpg_app_user_secret()
        files['templates/cnpg-superuser-secret.yaml'] = generate_cnpg_superuser_secret()
    
    if 'dask' in enabled_addons:
        files['templates/dask-scheduler-deployment.yaml'] = generate_dask_scheduler()
        files['templates/dask-scheduler-service.yaml'] = generate_dask_scheduler_service()
        files['templates/dask-workers-deployment.yaml'] = generate_dask_workers()
    
    if 'persistence' in enabled_addons:
        files['templates/pvc.yaml'] = generate_pvc()
    
    if 'nfs' in enabled_addons:
        files['templates/nfs-pv.yaml'] = generate_nfs_pv()
        files['templates/nfs-pvc.yaml'] = generate_nfs_pvc()
    
    if 'external_secrets' in enabled_addons:
        files['templates/external-secret.yaml'] = generate_external_secret()
    
    # README
    files['README.md'] = generate_modular_readme(app_config, enabled_addons, addon_config)
    
    return files


def generate_chart_yaml(app_name):
    """Generate Chart.yaml"""
    return f"""apiVersion: v2
name: {app_name}
description: A modular Helm chart for {app_name} on CIRRUS
type: application
version: 0.1.0
appVersion: "1.0"
"""


def generate_modular_values(app_config, enabled_addons, addon_config):
    """Generate values.yaml with only enabled components"""
    image_parts = app_config['image'].rsplit(':', 1)
    image = image_parts[0]
    tag = image_parts[1] if len(image_parts) > 1 else 'latest'
    
    # Extract FQDN for secret name (everything before .k8s.ucar.edu)
    fqdn = app_config['domain']
    host = fqdn.replace('.k8s.ucar.edu', '') if '.k8s.ucar.edu' in fqdn else fqdn.split('.')[0]
    
    values = f"""# Modular Helm Chart for {app_config['app_name']}
# Generated by CIRRUS Helm Chart Generator

# Number of pod replicas
# We recommend 2+ for zero-downtime deployments during server maintenance
replicaCount: {app_config['replicas']}

webapp:
  name: {app_config['app_name']}
  group: {app_config['app_name']}
  path: /  # URL path - typically just / unless your app uses a different base path
  tls:
    fqdn: {fqdn}
    secretName: incommon-cert-{host}
  container:
    image: {image}:{tag}
    port: {app_config['port']}
    memory: 1G
    cpu: 2
"""
    
    # Add ingress config
    if app_config['enable_ingress']:
        access_type = app_config.get('ingress_type', 'external')
        values += f"""
ingress:
  enabled: true
  access: {access_type}  # 'external' for public access, 'internal' for UCAR network only
"""
    
    # Add CNPG config
    if 'cnpg' in enabled_addons:
        values += f"""
cnpg:
  enabled: true
  instances: {addon_config.get('cnpg_instances', 3)}
  storage:
    size: {addon_config.get('cnpg_storage_size', '20Gi')}
  backup:
    enabled: {str(addon_config.get('cnpg_backup_enabled', False)).lower()}
    retentionPolicy: "30d"
  
  # App user credentials from External Secrets
  appUser:
    owner: {addon_config.get('cnpg_app_owner', 'app_user')}
    secretPath: {addon_config.get('cnpg_app_secret_path', 'secret/data/myapp/db')}
    passwordKey: {addon_config.get('cnpg_app_password_key', 'password')}
  
  # Superuser credentials from External Secrets (optional)
  superUser:
    enabled: {str(addon_config.get('cnpg_enable_superuser', False)).lower()}
    secretPath: {addon_config.get('cnpg_superuser_secret_path', 'secret/data/myapp/db-superuser')}
    usernameKey: {addon_config.get('cnpg_superuser_username_key', 'username')}
    passwordKey: {addon_config.get('cnpg_superuser_password_key', 'password')}
"""
    
    # Add Dask config
    if 'dask' in enabled_addons:
        values += f"""
dask:
  enabled: true
  scheduler:
    port: 8786
    dashboardPort: 8787
  worker:
    replicas: {addon_config.get('worker_replicas', 3)}
    threads: {addon_config.get('worker_threads', 4)}
    memory: {addon_config.get('worker_memory', '4Gi')}
"""
    
    # Add Persistence config
    if 'persistence' in enabled_addons:
        values += f"""
persistence:
  enabled: true
  storageClass: ceph-kubepv
  accessMode: {addon_config.get('pv_access_mode', 'ReadWriteOnce')}
  size: {addon_config.get('pv_storage_size', '10Gi')}
  mountPath: {addon_config.get('pv_mount_path', '/data')}
"""
    
    # Add NFS config
    if 'nfs' in enabled_addons:
        readonly = addon_config.get('nfs_readonly', False)
        values += f"""
nfs:
  enabled: true
  server: {addon_config.get('nfs_server', 'nfs.example.com')}
  path: {addon_config.get('nfs_path', '/export/data')}
  mountPath: {addon_config.get('nfs_mount_path', '/mnt/nfs')}
  readOnly: {str(readonly).lower()}
"""
    
    # Add External Secrets config
    if 'external_secrets' in enabled_addons:
        values += f"""
externalSecrets:
  enabled: true
  secretPath: {addon_config.get('secret_path', 'secret/data/myapp')}
  backend: vault
  vaultUrl: https://bao.k8s.ucar.edu
"""
    
    return values


def generate_base_deployment(app_config, enabled_addons, addon_config):
    """Generate deployment with conditional volume mounts"""
    
    # Build volume mounts
    volume_mounts = []
    volumes = []
    env_from = []
    
    if 'persistence' in enabled_addons:
        mount_path = addon_config.get('pv_mount_path', '/data')
        volume_mounts.append(f"""        - name: data
          mountPath: {mount_path}""")
        volumes.append("""      - name: data
        persistentVolumeClaim:
          claimName: {{ include "chart.fullname" . }}-pvc""")
    
    if 'nfs' in enabled_addons:
        mount_path = addon_config.get('nfs_mount_path', '/mnt/nfs')
        readonly = addon_config.get('nfs_readonly', False)
        readonly_str = '\n          readOnly: true' if readonly else ''
        volume_mounts.append(f"""        - name: nfs
          mountPath: {mount_path}{readonly_str}""")
        volumes.append("""      - name: nfs
        persistentVolumeClaim:
          claimName: {{ include "chart.fullname" . }}-nfs-pvc""")
    
    if 'external_secrets' in enabled_addons:
        env_from.append("""        - secretRef:
            name: {{ include "chart.fullname" . }}-external-secret""")
    
    # Build deployment template
    volume_mounts_str = '\n'.join(volume_mounts) if volume_mounts else ''
    volumes_str = '\n'.join(volumes) if volumes else ''
    env_from_str = '\n'.join(env_from) if env_from else ''
    
    deployment = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{{{ include "chart.fullname" . }}}}
  labels:
    {{{{- include "chart.labels" . | nindent 4 }}}}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
    spec:
      containers:
      - name: {{ .Values.webapp.name }}
        image: "{{ .Values.webapp.container.image }}"
        imagePullPolicy: IfNotPresent
        ports:
        - name: http
          containerPort: {{ .Values.webapp.container.port }}
          protocol: TCP"""
    
    if env_from_str:
        deployment += f"""
        envFrom:
{env_from_str}"""
    
    if volume_mounts_str:
        deployment += f"""
        volumeMounts:
{volume_mounts_str}"""
    
    deployment += """
        resources:
          limits:
            cpu: "{{ .Values.webapp.container.cpu }}"
            memory: {{ .Values.webapp.container.memory }}
          requests:
            cpu: 100m
            memory: 128Mi"""
    
    if volumes_str:
        deployment += f"""
      volumes:
{volumes_str}"""
    
    return deployment


def generate_service():
    """Generate service.yaml"""
    return """apiVersion: v1
kind: Service
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  type: ClusterIP
  ports:
  - port: {{ .Values.webapp.container.port }}
    targetPort: http
    protocol: TCP
    name: http
  selector:
    {{- include "chart.selectorLabels" . | nindent 4 }}
"""


def generate_ingress():
    """Generate ingress.yaml"""
    return """{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "chart.fullname" . }}
  labels:
    {{- include "chart.labels" . | nindent 4 }}
  annotations:
    cert-manager.io/cluster-issuer: "incommon"
spec:
  ingressClassName: nginx-{{ .Values.ingress.access }}
  tls:
  - hosts:
    - {{ .Values.webapp.tls.fqdn }}
    secretName: {{ .Values.webapp.tls.secretName }}
  rules:
  - host: {{ .Values.webapp.tls.fqdn }}
    http:
      paths:
      - path: {{ .Values.webapp.path }}
        pathType: Prefix
        backend:
          service:
            name: {{ include "chart.fullname" . }}
            port:
              number: {{ .Values.webapp.container.port }}
{{- end }}
"""


def generate_cnpg_cluster():
    """Generate CloudNativePG Cluster"""
    return """{{- if .Values.cnpg.enabled }}
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: {{ include "chart.fullname" . }}-cnpg
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  instances: {{ .Values.cnpg.instances }}
  
  postgresql:
    parameters:
      max_connections: "100"
      shared_buffers: "256MB"
  
  storage:
    size: {{ .Values.cnpg.storage.size }}
    storageClass: ceph-kubepv
  
  {{- if .Values.cnpg.superUser.enabled }}
  enableSuperuserAccess: true
  superuserSecret:
    name: {{ include "chart.fullname" . }}-superuser
  {{- end }}
  
  bootstrap:
    initdb:
      database: {{ .Values.cnpg.appUser.owner }}
      owner: {{ .Values.cnpg.appUser.owner }}
      secret:
        name: {{ include "chart.fullname" . }}-app-user
  
  {{- if .Values.cnpg.backup.enabled }}
  backup:
    retentionPolicy: {{ .Values.cnpg.backup.retentionPolicy }}
    barmanObjectStore:
      destinationPath: s3://cirrus-backups/{{ include "chart.fullname" . }}-cnpg
      s3Credentials:
        accessKeyId:
          name: backup-credentials
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: backup-credentials
          key: SECRET_ACCESS_KEY
  {{- end }}
{{- end }}
"""


def generate_cnpg_app_user_secret():
    """Generate CNPG App User ExternalSecret"""
    return """{{- if .Values.cnpg.enabled }}
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ include "chart.fullname" . }}-app-user-esos
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: user-ro
    kind: SecretStore
  target:
    name: {{ include "chart.fullname" . }}-app-user
    type: kubernetes.io/basic-auth
  data:
    - secretKey: username
      remoteRef:
        value: {{ .Values.cnpg.appUser.owner }}
    - secretKey: password
      remoteRef:
        key: {{ .Values.cnpg.appUser.secretPath }}
        property: {{ .Values.cnpg.appUser.passwordKey }}
{{- end }}
"""


def generate_cnpg_superuser_secret():
    """Generate CNPG Superuser ExternalSecret"""
    return """{{- if and .Values.cnpg.enabled .Values.cnpg.superUser.enabled }}
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: {{ include "chart.fullname" . }}-superuser-esos
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: user-ro
    kind: SecretStore
  target:
    name: {{ include "chart.fullname" . }}-superuser
    type: kubernetes.io/basic-auth
  data:
    - secretKey: username
      remoteRef:
        key: {{ .Values.cnpg.superUser.secretPath }}
        property: {{ .Values.cnpg.superUser.usernameKey }}
    - secretKey: password
      remoteRef:
        key: {{ .Values.cnpg.superUser.secretPath }}
        property: {{ .Values.cnpg.superUser.passwordKey }}
{{- end }}
"""


def generate_dask_scheduler():
    """Generate Dask scheduler deployment"""
    return """{{- if .Values.dask.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "chart.fullname" . }}-dask-scheduler
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: dask-scheduler
spec:
  replicas: 1
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: dask-scheduler
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: dask-scheduler
    spec:
      containers:
      - name: scheduler
        image: "{{ .Values.webapp.container.image }}"
        command:
        - dask-scheduler
        ports:
        - containerPort: {{ .Values.dask.scheduler.port }}
          name: scheduler
        - containerPort: {{ .Values.dask.scheduler.dashboardPort }}
          name: dashboard
{{- end }}
"""


def generate_dask_scheduler_service():
    """Generate Dask scheduler service"""
    return """{{- if .Values.dask.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "chart.fullname" . }}-dask-scheduler
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: dask-scheduler
spec:
  type: ClusterIP
  ports:
  - port: {{ .Values.dask.scheduler.port }}
    targetPort: scheduler
    name: scheduler
  - port: {{ .Values.dask.scheduler.dashboardPort }}
    targetPort: dashboard
    name: dashboard
  selector:
    {{- include "chart.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: dask-scheduler
{{- end }}
"""


def generate_dask_workers():
    """Generate Dask workers deployment"""
    return """{{- if .Values.dask.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "chart.fullname" . }}-dask-workers
  labels:
    {{- include "chart.labels" . | nindent 4 }}
    app.kubernetes.io/component: dask-worker
spec:
  replicas: {{ .Values.dask.worker.replicas }}
  selector:
    matchLabels:
      {{- include "chart.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: dask-worker
  template:
    metadata:
      labels:
        {{- include "chart.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: dask-worker
    spec:
      containers:
      - name: worker
        image: "{{ .Values.webapp.container.image }}"
        command:
        - dask-worker
        - {{ include "chart.fullname" . }}-dask-scheduler:{{ .Values.dask.scheduler.port }}
        - --nthreads
        - "{{ .Values.dask.worker.threads }}"
        - --memory-limit
        - "{{ .Values.dask.worker.memory }}"
        resources:
          limits:
            memory: {{ .Values.dask.worker.memory }}
          requests:
            memory: {{ .Values.dask.worker.memory }}
{{- end }}
"""


def generate_pvc():
    """Generate PVC for persistent storage"""
    return """{{- if .Values.persistence.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "chart.fullname" . }}-pvc
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  accessModes:
  - {{ .Values.persistence.accessMode }}
  resources:
    requests:
      storage: {{ .Values.persistence.size }}
  storageClassName: {{ .Values.persistence.storageClass }}
{{- end }}
"""


def generate_nfs_pv():
    """Generate NFS PersistentVolume"""
    return """{{- if .Values.nfs.enabled }}
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ include "chart.fullname" . }}-nfs-pv
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  capacity:
    storage: 100Gi
  accessModes:
  {{- if .Values.nfs.readOnly }}
  - ReadOnlyMany
  {{- else }}
  - ReadWriteMany
  {{- end }}
  nfs:
    server: {{ .Values.nfs.server }}
    path: {{ .Values.nfs.path }}
  mountOptions:
  - vers=4
  - minorversion=1
  {{- if .Values.nfs.readOnly }}
  - ro
  {{- end }}
{{- end }}
"""


def generate_nfs_pvc():
    """Generate NFS PersistentVolumeClaim"""
    return """{{- if .Values.nfs.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "chart.fullname" . }}-nfs-pvc
  labels:
    {{- include "chart.labels" . | nindent 4 }}
spec:
  accessModes:
  {{- if .Values.nfs.readOnly }}
  - ReadOnlyMany
  {{- else }}
  - ReadWriteMany
  {{- end }}
  resources:
    requests:
      storage: 100Gi
  volumeName: {{ include "chart.fullname" . }}-nfs-pv
{{- end }}
"""


def generate_external_secret():
    """Generate ExternalSecret"""
    return """{{- if .Values.externalSecrets.enabled }}
apiVersion: external-secrets.io/v1beta1
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
      key: {{ .Values.externalSecrets.secretPath }}
{{- end }}
"""


def generate_modular_readme(app_config, enabled_addons, addon_config):
    """Generate comprehensive README with enabled components"""
    from datetime import datetime
    
    app_name = app_config['app_name']
    image_parts = app_config['image'].rsplit(':', 1)
    image_repo = image_parts[0]
    image_tag = image_parts[1] if len(image_parts) > 1 else 'latest'
    replica_count = app_config['replicas']
    port = app_config['port']
    
    # Ingress info
    ingress_enabled = app_config['enable_ingress']
    if ingress_enabled:
        access_type = app_config.get('ingress_type', 'external')
        fqdn = app_config['domain']
        ingress_line = f"- **External Access**: https://{fqdn} ({access_type})"
    else:
        ingress_line = ""
        fqdn = f"{app_name}.k8s.ucar.edu"
    
    # Build components list
    components_list = []
    
    if 'cnpg' in enabled_addons:
        instances = addon_config.get('cnpg_instances', 3)
        components_list.append(f"- **CloudNativePG**: {instances}-instance PostgreSQL cluster")
    
    if 'dask' in enabled_addons:
        workers = addon_config.get('worker_replicas', 3)
        components_list.append(f"- **Dask**: Distributed computing cluster with {workers} workers")
    
    if 'persistence' in enabled_addons:
        size = addon_config.get('pv_storage_size', '10Gi')
        access_mode = addon_config.get('pv_access_mode', 'ReadWriteOnce')
        access_desc = "single-pod" if access_mode == "ReadWriteOnce" else "multi-pod"
        components_list.append(f"- **Persistent Volume**: {size} storage ({access_desc} access)")
    
    if 'nfs' in enabled_addons:
        server = addon_config.get('nfs_server', 'nfs.example.com')
        readonly = addon_config.get('nfs_readonly', False)
        access = "read-only" if readonly else "read-write"
        components_list.append(f"- **NFS**: Shared storage from {server} ({access})")
    
    if 'external_secrets' in enabled_addons:
        components_list.append(f"- **External Secrets**: Vault integration")
    
    components_text = "\n".join(components_list)
    
    readme = f"""# {app_name}

Helm chart for deploying to CIRRUS

## Quick Start

```bash
# Install
helm install {app_name} .

# Check status
kubectl get pods -l app.kubernetes.io/name={app_name}
```"""
    
    if ingress_enabled:
        readme += f"""

View at: **https://{fqdn}**
"""
    
    readme += f"""

## What's Deployed

- **Application**: {replica_count} replica(s) on port {port}
{ingress_line}
"""
    
    if components_text:
        readme += components_text + "\n"
    
    readme += f"""

## Configuration

Edit `values.yaml` to customize your deployment.

### Key Settings

```yaml
replicaCount: {replica_count}  # Recommended: 2+ for zero-downtime during maintenance

webapp:
  name: {app_name}
  tls:
    fqdn: {fqdn}
  container:
    image: {image_repo}:{image_tag}
    port: {port}
    memory: 1G
    cpu: 2
"""
    
    if ingress_enabled:
        readme += f"""
ingress:
  enabled: true
  access: {access_type}  # Switch between 'external' or 'internal'
"""
    
    readme += """```

### Switching Access Type

To change between external (public) and internal (UCAR-only) access, edit `values.yaml`:

```yaml
ingress:
  access: internal  # or 'external'
```

The ingress class is automatically set to `nginx-external` or `nginx-internal`.

"""
    
    # Add component-specific config if any major add-ons are enabled
    if 'cnpg' in enabled_addons:
        readme += """### Database Connection

CloudNativePG database credentials are automatically managed. Check the pod environment for connection details.

"""
    
    if 'nfs' in enabled_addons:
        readonly = addon_config.get('nfs_readonly', False)
        if readonly:
            readme += """### NFS Read-Only Access

NFS volume is mounted read-only. Write operations will fail. For write access, disable the read-only option or use a persistent volume.

"""
    
    readme += """## Common Tasks

### Update Application

```bash
# Edit values.yaml with new image tag
# Then upgrade:
helm upgrade {app_name} .
```

### Scale Replicas

```bash
# Edit values.yaml and change replicaCount
helm upgrade {app_name} .
```

### View Logs

```bash
kubectl logs -f -l app.kubernetes.io/name={app_name}
```

### Check Resource Usage

```bash
kubectl top pods -l app.kubernetes.io/name={app_name}
```

## Troubleshooting

### Pods Not Starting

```bash
kubectl describe pod -l app.kubernetes.io/name={app_name}
kubectl logs -l app.kubernetes.io/name={app_name}
```

Common causes:
- Image doesn't exist or isn't accessible
- Application crashes on startup (check logs)
- Resource limits too low

### Can't Access Application

- Wait 5-10 minutes for DNS propagation
- Verify ingress: `kubectl get ingress {app_name}`
- Check certificate: `kubectl get certificate`

## Support

- **CIRRUS Docs**: https://ncar-hpc-docs.readthedocs.io/en/latest/compute-systems/cirrus/
- **Support**: [Create Jira ticket](https://jira.ucar.edu/secure/CreateIssueDetails!init.jspa?pid=18470&issuetype=10903)

---

*Generated by CIRRUS Helm Chart Generator on {datetime.now().strftime('%Y-%m-%d')}*
"""
    
    return readme.format(app_name=app_name)
    """Generate comprehensive README with enabled components"""
    from datetime import datetime
    
    app_name = app_config['app_name']
    image_parts = app_config['image'].rsplit(':', 1)
    image_repo = image_parts[0]
    image_tag = image_parts[1] if len(image_parts) > 1 else 'latest'
    replica_count = app_config['replicas']
    port = app_config['port']
    
    # Ingress info
    ingress_enabled = app_config['enable_ingress']
    if ingress_enabled:
        access_type = app_config.get('ingress_type', 'external')
        fqdn = app_config['domain']
        ingress_info = f"- **Ingress**: External access at https://{fqdn} ({access_type} access)\n"
    else:
        ingress_info = ""
        access_type = "external"
        fqdn = f"{app_name}.k8s.ucar.edu"
    
    # Components info
    components_list = []
    components_config = ""
    
    if 'autoscaling' in enabled_addons:
        min_rep = addon_config.get('min_replicas', 2)
        max_rep = addon_config.get('max_replicas', 10)
        components_list.append(f"- **Autoscaling**: {min_rep}-{max_rep} replicas based on CPU")
        components_config += f"""
### Autoscaling
```yaml
autoscaling:
  enabled: true
  minReplicas: {min_rep}
  maxReplicas: {max_rep}
  targetCPUUtilizationPercentage: {addon_config.get('target_cpu', 80)}
```

"""
    
    if 'postgresql' in enabled_addons:
        db_name = addon_config.get('db_name', 'app_db')
        components_list.append(f"- **PostgreSQL**: Database '{db_name}' with persistent storage")
        components_config += f"""
### PostgreSQL Database
```yaml
postgresql:
  enabled: true
  auth:
    database: {db_name}
    username: {addon_config.get('db_user', 'app_user')}
    # Password auto-generated in secret
  persistence:
    size: {addon_config.get('postgres_storage_size', '10Gi')}
```

**Connection from app**: Environment variable `DATABASE_URL` is automatically injected.

"""
    
    if 'cnpg' in enabled_addons:
        instances = addon_config.get('cnpg_instances', 3)
        components_list.append(f"- **CloudNativePG**: {instances}-instance PostgreSQL cluster with HA")
        components_config += f"""
### CloudNativePG Cluster
```yaml
cnpg:
  enabled: true
  instances: {instances}
  storage:
    size: {addon_config.get('cnpg_storage_size', '20Gi')}
  backup:
    enabled: {addon_config.get('cnpg_backup_enabled', 'false')}
```

"""
    
    if 'dask' in enabled_addons:
        workers = addon_config.get('worker_replicas', 3)
        components_list.append(f"- **Dask Cluster**: 1 scheduler + {workers} workers")
        components_config += f"""
### Dask Cluster
```yaml
dask:
  enabled: true
  worker:
    replicas: {workers}
    threads: {addon_config.get('worker_threads', 4)}
    memory: {addon_config.get('worker_memory', '4Gi')}
```

**Connect to scheduler**: `{app_name}-dask-scheduler:8786`

"""
    
    if 'persistence' in enabled_addons:
        pv_size = addon_config.get('pv_storage_size', '10Gi')
        pv_mount = addon_config.get('pv_mount_path', '/data')
        components_list.append(f"- **Persistent Volume**: {pv_size} mounted at {pv_mount}")
        components_config += f"""
### Persistent Volume
```yaml
persistence:
  enabled: true
  size: {pv_size}
  mountPath: {pv_mount}
  storageClass: ceph-kubepv  # ReadWriteOnce
```

**Data persists** across pod restarts and redeployments.

"""
    
    if 'cephfs' in enabled_addons:
        ceph_size = addon_config.get('cephfs_storage_size', '10Gi')
        ceph_mount = addon_config.get('cephfs_mount_path', '/mnt/shared')
        components_list.append(f"- **CephFS**: {ceph_size} shared storage at {ceph_mount}")
        components_config += f"""
### CephFS Shared Storage
```yaml
cephfs:
  enabled: true
  size: {ceph_size}
  mountPath: {ceph_mount}
  storageClass: cephfs  # ReadWriteMany
```

**Shared across all pods** - multiple pods can read/write simultaneously.

"""
    
    if 'nfs' in enabled_addons:
        nfs_server = addon_config.get('nfs_server', 'nfs.example.com')
        nfs_path = addon_config.get('nfs_path', '/export/data')
        components_list.append(f"- **NFS**: External mount from {nfs_server}")
        components_config += f"""
### NFS Volume
```yaml
nfs:
  enabled: true
  server: {nfs_server}
  path: {nfs_path}
  mountPath: {addon_config.get('nfs_mount_path', '/mnt/nfs')}
```

"""
    
    if 'glade' in enabled_addons:
        glade_path = addon_config.get('glade_path', '/glade/work/username')
        components_list.append(f"- **Glade**: Read-only mount of {glade_path}")
        components_config += f"""
### Glade Mount
```yaml
glade:
  enabled: true
  path: {glade_path}
  mountPath: {addon_config.get('glade_mount_path', '/glade')}
  readOnly: true
```

**Read-only access** to NCAR Glade filesystem.

"""
    
    if 'external_secrets' in enabled_addons:
        secret_path = addon_config.get('secret_path', 'secret/data/myapp')
        components_list.append(f"- **External Secrets**: Vault secrets from {secret_path}")
        components_config += f"""
### External Secrets
```yaml
externalSecrets:
  enabled: true
  secretPath: {secret_path}
```

**Secrets injected** as environment variables from bao.k8s.ucar.edu.

"""
    
    components_info = "\n".join(components_list)
    if components_info:
        components_info = "\n" + components_info + "\n"
    
    # Generate README
    readme = f"""# {app_name} - CIRRUS Helm Chart

This Helm chart deploys your application to the CIRRUS Kubernetes platform.

## Quick Start

```bash
# Install your application
helm install {app_name} .

# Check deployment status
kubectl get pods -l app.kubernetes.io/name={app_name}
"""
    
    if ingress_enabled:
        readme += f"""
# View your application
# https://{fqdn}
"""
    
    readme += """```

## What's Included

This chart deploys:
- **Deployment**: """ + str(replica_count) + """ replica(s) of your application
- **Service**: Internal service on port """ + str(port) + """
"""
    
    if ingress_info:
        readme += ingress_info
    
    if components_info:
        readme += components_info
    
    readme += f"""
## Configuration

All configuration is in `values.yaml`. Key settings:

### Replica Count
```yaml
replicaCount: {replica_count}  # Number of pod replicas
```

**Why we recommend 2+ replicas:**
- **Zero-downtime deployments**: During CIRRUS server maintenance or updates, your application stays available if at least one pod runs on a different node
- **High availability**: If one pod crashes or the node fails, traffic automatically routes to healthy pods
- **Load distribution**: Requests are distributed across multiple pods for better performance

**When to use 1 replica:**
- Development/testing environments
- Applications that cannot run multiple instances (e.g., using local file storage)
- Very low-traffic applications where availability isn't critical

Note: If autoscaling is enabled, `replicaCount` sets the initial number of pods before autoscaling takes over.

### Application Settings
```yaml
webapp:
  name: {app_name}
  group: {app_name}
  path: /  # URL path - typically / unless your app uses a different base path
  tls:
    fqdn: {fqdn}
    secretName: incommon-cert-{app_name.replace('.k8s.ucar.edu', '') if '.k8s.ucar.edu' in app_name else app_name.split('.')[0]}
  container:
    image: {image_repo}:{image_tag}
    port: {port}
    memory: 1G  # Memory limit
    cpu: 2      # CPU limit (2 cores)
```

### Ingress (External Access)
"""
    
    if ingress_enabled:
        readme += f"""```yaml
ingress:
  enabled: true
  access: {access_type}  # Switch between 'external' or 'internal'
  
  # external: Public internet access (nginx-external)
  # internal: UCAR network/VPN only (nginx-internal)

webapp:
  tls:
    fqdn: {fqdn}
    secretName: incommon-cert-{fqdn.replace('.k8s.ucar.edu', '') if '.k8s.ucar.edu' in fqdn else fqdn.split('.')[0]}
```

To **switch between internal and external access**, simply change:
```yaml
ingress:
  access: internal  # Change to 'internal' or 'external'
```

The chart automatically uses `nginx-external` or `nginx-internal` based on this value.
"""
    else:
        readme += """```yaml
ingress:
  enabled: false  # Set to true to enable external access
  access: external  # or 'internal' for UCAR-only access

webapp:
  tls:
    fqdn: myapp.k8s.ucar.edu  # Your unique domain
    secretName: incommon-cert-myapp
```

To enable ingress, set `enabled: true` and configure your domain.
"""
    
    readme += """
### Resources
```yaml
webapp:
  container:
    memory: 1G  # Memory limit
    cpu: 2      # CPU limit (2 cores)
```

**Tuning Tips:**
- Start with defaults (1G memory, 2 CPU) and monitor using `kubectl top pods`
- Increase if pods are being OOMKilled (Out Of Memory) or CPU throttled
- Memory: Set based on your application's typical usage + buffer
- CPU: Set based on peak load requirements
- Rule of thumb: memory should be ~1.5x typical usage, CPU should handle peak + 30%

"""
    
    if components_config:
        readme += components_config
    
    readme += f"""
## Prerequisites

Before deploying, ensure:

1. **Container image is accessible**
   ```bash
   # Test image pull
   docker pull {image_repo}:{image_tag}
   ```

2. **Domain is unique** (if using ingress)
   - Must end in `.k8s.ucar.edu`
   - Check availability: `curl https://{fqdn}` (should 404 if available)

3. **You have CIRRUS access**
   - Kubernetes context configured
   - Namespace access granted

## Installation

### First Time Install
```bash
helm install {app_name} .
```

### Update Existing Deployment
```bash
# After editing values.yaml
helm upgrade {app_name} .

# Force pod restart
kubectl rollout restart deployment/{app_name}
```

### Uninstall
```bash
helm uninstall {app_name}
```

## Troubleshooting

### Pods Not Starting
```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name={app_name}

# View pod logs
kubectl logs -l app.kubernetes.io/name={app_name}

# Describe pod for events
kubectl describe pod -l app.kubernetes.io/name={app_name}
```

Common issues:
- **ImagePullBackOff**: Image not accessible or doesn't exist
- **CrashLoopBackOff**: Application is crashing, check logs
- **Pending**: Resource constraints, check `kubectl describe pod`

### Ingress Not Working
```bash
# Check ingress status
kubectl get ingress {app_name}

# Describe for events
kubectl describe ingress {app_name}
```

Common issues:
- DNS not resolving: Wait 5-10 minutes for DNS propagation
- Certificate pending: Check cert-manager logs
- Wrong access type: Verify `ingress.access` value matches your needs

## Monitoring

### View Logs
```bash
# Follow logs from all pods
kubectl logs -f -l app.kubernetes.io/name={app_name}
```

### Check Resource Usage
```bash
# CPU and memory usage
kubectl top pods -l app.kubernetes.io/name={app_name}
```

## Support

For issues or questions:
- Create a ticket in [CIRRUS Jira](https://jira.ucar.edu/secure/CreateIssueDetails!init.jspa?pid=18470&issuetype=10903)
- Email: cirrus-support@ucar.edu
- Documentation: https://ncar-hpc-docs.readthedocs.io/en/latest/compute-systems/cirrus/

## Chart Information

- **Chart Version**: 0.1.0
- **Generated**: {datetime.now().strftime('%Y-%m-%d')}
- **Generated By**: CIRRUS Modular Helm Chart Generator

---

*This chart was generated based on your selections. Edit `values.yaml` to enable/disable components or adjust configuration.*
"""
    
    return readme


def create_zip(files, app_name):
    """Create ZIP file"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filepath, content in files.items():
            zip_file.writestr(f"{app_name}/{filepath}", content)
    
    zip_buffer.seek(0)
    return zip_buffer


def create_github_pr(token, repo_url, base_branch, files, app_config, enabled_addons):
    """Create GitHub PR"""
    if not token or not repo_url:
        raise ValueError("GitHub token and repository URL are required")
    
    if repo_url.startswith('https://github.com/'):
        repo_path = repo_url.replace('https://github.com/', '').rstrip('.git')
    else:
        raise ValueError("Invalid GitHub repository URL")
    
    g = Github(token)
    repo = g.get_repo(repo_path)
    
    app_name = app_config['app_name']
    new_branch = f"add-helm-chart-{app_name}"
    
    base_ref = repo.get_git_ref(f"heads/{base_branch}")
    repo.create_git_ref(f"refs/heads/{new_branch}", base_ref.object.sha)
    
    for filepath, content in files.items():
        full_path = f"helm/{app_name}/{filepath}"
        try:
            existing_file = repo.get_contents(full_path, ref=new_branch)
            repo.update_file(
                full_path,
                f"Update {filepath}",
                content,
                existing_file.sha,
                branch=new_branch
            )
        except GithubException:
            repo.create_file(
                full_path,
                f"Add {filepath}",
                content,
                branch=new_branch
            )
    
    addons_str = ", ".join([AVAILABLE_ADDONS[a]['name'] for a in enabled_addons]) if enabled_addons else "None"
    
    pr = repo.create_pull(
        title=f"Add modular Helm chart for {app_name}",
        body=f"""Generated modular Helm chart for **{app_name}**

**Enabled add-ons:** {addons_str}

Generated using CIRRUS Modular Helm Chart Generator""",
        head=new_branch,
        base=base_branch
    )
    
    return pr.html_url