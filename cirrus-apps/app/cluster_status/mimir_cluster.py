"""
Per-cluster Kubernetes health from Mimir.

Reuses the same Mimir access pattern as ``app.metrics.github_metrics``: HTTP
basic auth from MIMIR_USER / MIMIR_PASS and the ``X-Scope-OrgID: 1`` header.
Queries are sent as a single POST per cluster because the unioned PromQL is
too long for a URL.
"""

import math
import os
from datetime import datetime, timezone

import requests

# Same default as github_metrics.MIMIR_URL — the full instant-query path.
MIMIR_URL = os.getenv(
    "MIMIR_URL",
    "https://mimir.k8s.ucar.edu/prometheus/api/v1/query"
)

QUERY_PATH_SUFFIX = "/api/v1/query"

# Clusters that answer the label query but carry no kube_* metrics at all
# (Postgres scrape targets sharing the `cluster` label namespace).
CLUSTER_DISCOVERY_METRIC = "kube_node_status_condition"

HTTP_TIMEOUT = 15

# GPU resources, matching the Grafana `cirrus-cluster-detail` dashboard.
_GPU = 'resource=~"nvidia_com_gpu|amd_com_gpu"'

# Namespaces that hold platform components rather than user workloads. Used
# only to annotate the pod/namespace counts — capacity metrics stay whole-cluster,
# because system pods consume real capacity and hiding them would overstate
# headroom. A PromQL (RE2) regex, fully anchored by Prometheus.
#
# Anything not listed here counts as a user namespace, so an incomplete list
# over-reports user activity rather than hiding it. Get the real list with
#   count by (namespace) (kube_pod_info{cluster="nwc1"})
# and override with CLUSTER_STATUS_PLATFORM_NAMESPACES.
DEFAULT_PLATFORM_NAMESPACES = "|".join([
    # --- confirmed present on nwc1 / mlc1 (namespace census, 2026-08-28) ---
    "kube-.*",                                 # reserved by Kubernetes itself
    "harbor", "openbao", "ingress-nginx", "traefik",
    "prometheus", "promtail", "kyverno", "velero", "opencost",
    "npd",                                     # node problem detector
    "nvidia-device-plugin",                    # advertises the time-sliced GPU slots
    "ondemand",                                # the OOD portal; ood-<user> are user sessions
    "mpi-operator", "s3gateway",               # operators / shared gateways, not workloads
    # --- expected but not seen in the census (it was alphabetically truncated) ---
    "default", "argocd", "grafana", "monitoring", "observability",
    "fission", "fission-function", "fission-builder",
    "nginx-ingress", "cert-manager", "external-secrets", "metallb-system",
    "gpu-operator", "nvidia-gpu-operator",
    "calico-system", "tigera-operator", "cilium",
    "local-path-storage", "longhorn-system", "rook-ceph", "keda",
])
# Judgement calls, flip them in CLUSTER_STATUS_PLATFORM_NAMESPACES if you disagree:
# jupyterhub counts as USER (its pods are user notebook servers), as do ood-<user>,
# sam-queries and pg-testing. ondemand, mpi-operator and s3gateway count as platform.
#
# arc-runners and arc-systems are deliberately absent: GitHub Actions runners are
# user work, and /metrics already bills their CPU hours as such. arc-systems also
# holds the ARC controller and listeners, which are platform — but ARC puts
# listeners in the controller namespace and scale sets are often installed there
# too, so it can hold real runners. Counting the handful of controller pods as
# user is a far smaller error than hiding a namespace full of runners. Confirm
# with:
#   count by (namespace, container) (
#     container_cpu_usage_seconds_total{cluster="nwc1", namespace=~"arc-runners|arc-systems"})
# and add arc-systems back to the override if it only ever runs manager/listener.


def platform_namespaces_re():
    raw = os.getenv("CLUSTER_STATUS_PLATFORM_NAMESPACES", DEFAULT_PLATFORM_NAMESPACES)
    # The regex is interpolated into a double-quoted PromQL string literal.
    return raw.replace('"', "").replace("\\", "")


_NOT_PLATFORM = f'namespace!~"{platform_namespaces_re()}"'

# Sentinel rather than str.format() — `{cluster="x"}` is not a format string.
_C = '__CLUSTER__'

# Panel name -> PromQL. Order here is the order sent in the union.
PANEL_QUERIES = {
    "cpu_used":
        f'100 * (1 - avg(rate(node_cpu_seconds_total{{mode="idle", cluster="{_C}"}}[5m])))',
    "mem_used":
        f'100 * (1 - sum(node_memory_MemAvailable_bytes{{cluster="{_C}"}})'
        f' / sum(node_memory_MemTotal_bytes{{cluster="{_C}"}}))',
    "pod_slots":
        f'100 * sum(kube_pod_status_phase{{phase="Running", cluster="{_C}"}})'
        f' / sum(kube_node_status_allocatable{{resource="pods", cluster="{_C}"}})',
    "cpu_requested":
        f'100 * sum(kube_pod_container_resource_requests{{resource="cpu", cluster="{_C}"}})'
        f' / sum(kube_node_status_allocatable{{resource="cpu", cluster="{_C}"}})',
    "mem_requested":
        f'100 * sum(kube_pod_container_resource_requests{{resource="memory", cluster="{_C}"}})'
        f' / sum(kube_node_status_allocatable{{resource="memory", cluster="{_C}"}})',
    "pvc_used":
        f'100 * sum(kubelet_volume_stats_used_bytes{{cluster="{_C}"}})'
        f' / sum(kubelet_volume_stats_capacity_bytes{{cluster="{_C}"}})',
    "gpu_allocated":
        f'100 * sum(kube_pod_container_resource_requests{{{_GPU}, cluster="{_C}"}})'
        f' / sum(kube_node_status_allocatable{{{_GPU}, cluster="{_C}"}})',
    "gpu_util":
        f'avg(DCGM_FI_DEV_GPU_UTIL{{cluster="{_C}"}})'
        f' or avg(gpu_gfx_activity{{cluster="{_C}"}})'
        f' or avg(amd_gpu_use_percent{{cluster="{_C}"}})',
    # NOTE: this is the *schedulable* count the device plugin advertises, which
    # is physical GPUs x time-slicing replicas — not the number of cards. The
    # key name is fixed by the published API contract, so it stays; the /status
    # page labels it "schedulable slots". Pair it with gpu_physical below.
    "gpu_total":
        f'sum(kube_node_status_allocatable{{{_GPU}, cluster="{_C}"}})',
    # Physical devices. Exporters emit one series per real GPU, so counting
    # series counts cards regardless of how many slots each is sliced into.
    "gpu_physical":
        f'count(DCGM_FI_DEV_GPU_UTIL{{cluster="{_C}"}})'
        f' or count(gpu_gfx_activity{{cluster="{_C}"}})'
        f' or count(amd_gpu_use_percent{{cluster="{_C}"}})',
    "nodes_ready":
        f'sum(kube_node_status_condition{{condition="Ready", status="true", cluster="{_C}"}})',
    "nodes_total":
        f'count(count by (node) (kube_node_status_allocatable{{cluster="{_C}"}}))',
    "pods_running":
        f'sum(kube_pod_status_phase{{phase="Running", cluster="{_C}"}})',
    "pods_pending":
        f'sum(kube_pod_status_phase{{phase="Pending", cluster="{_C}"}})',
    "namespaces":
        f'count(count by (namespace) (kube_pod_info{{cluster="{_C}"}}))',
    # Same three counts again, minus the platform namespaces. Absent when every
    # pod on the cluster is a platform pod — the caller can tell that apart from
    # "no data" because the unfiltered count above is present.
    "pods_running_user":
        f'sum(kube_pod_status_phase{{phase="Running", cluster="{_C}", {_NOT_PLATFORM}}})',
    "pods_pending_user":
        f'sum(kube_pod_status_phase{{phase="Pending", cluster="{_C}", {_NOT_PLATFORM}}})',
    "namespaces_user":
        f'count(count by (namespace) (kube_pod_info{{cluster="{_C}", {_NOT_PLATFORM}}}))',
}

# Panels that are counts of things; everything else is a percentage.
INTEGER_PANELS = frozenset({
    "gpu_total", "gpu_physical", "nodes_ready", "nodes_total",
    "pods_running", "pods_pending", "namespaces",
    "pods_running_user", "pods_pending_user", "namespaces_user",
})


def mimir_base_url():
    """Base Mimir API URL (no ``/api/v1/query``), for the label endpoint."""
    base = os.getenv("MIMIR_BASE_URL")
    if base:
        return base.rstrip("/")
    url = MIMIR_URL.rstrip("/")
    if url.endswith(QUERY_PATH_SUFFIX):
        url = url[: -len(QUERY_PATH_SUFFIX)]
    return url


def _auth():
    return (os.getenv("MIMIR_USER"), os.getenv("MIMIR_PASS"))


def _headers():
    return {"X-Scope-OrgID": "1"}


def build_union_query(cluster):
    """All 14 panel expressions as one instant query, tagged with `panel`."""
    parts = [
        f'label_replace({expr.replace(_C, cluster)}, "panel", "{panel}", "", "")'
        for panel, expr in PANEL_QUERIES.items()
    ]
    return " or ".join(parts)


def parse_cluster_metrics(payload):
    """
    Turn a Mimir instant-query response for the unioned query into a flat
    ``{panel: number}`` dict.

    Metrics with no series are simply absent from the response and so are
    omitted here — never substituted with 0. NaN / +-Inf values (e.g. `0/0`
    on a cluster with no PVCs) are dropped for the same reason.
    """
    metrics = {}
    if not isinstance(payload, dict):
        return metrics
    if payload.get("status") not in (None, "success"):
        return metrics

    for item in payload.get("data", {}).get("result", []) or []:
        panel = (item.get("metric") or {}).get("panel")
        if not panel or panel not in PANEL_QUERIES:
            continue
        value = item.get("value")
        if not value or len(value) < 2:
            continue
        try:
            number = float(value[1])
        except (TypeError, ValueError):
            continue
        if math.isnan(number) or math.isinf(number):
            continue
        # Prometheus returns everything as a string: "415" -> 415, not 415.0.
        metrics[panel] = int(round(number)) if panel in INTEGER_PANELS else round(number, 2)

    return metrics


def discover_clusters():
    """
    Cluster names, scoped to a kube_* metric so non-Kubernetes scrape targets
    (pgdb01, pgdb02) are excluded. Mirrors the Grafana dashboard variable
    `label_values(kube_node_status_condition, cluster)`.
    """
    override = os.getenv("CLUSTER_STATUS_CLUSTERS")
    if override:
        return [c.strip() for c in override.split(",") if c.strip()]

    response = requests.get(
        f"{mimir_base_url()}/api/v1/label/cluster/values",
        params={"match[]": CLUSTER_DISCOVERY_METRIC},
        auth=_auth(),
        headers=_headers(),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return sorted(response.json().get("data") or [])


def query_cluster(cluster):
    """One POST per cluster; returns the parsed ``{panel: number}`` dict."""
    response = requests.post(
        MIMIR_URL,
        data={"query": build_union_query(cluster)},
        auth=_auth(),
        headers={**_headers(), "Content-Type": "application/x-www-form-urlencoded"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return parse_cluster_metrics(response.json())


def get_cluster_status():
    """
    Build the full payload. Raises if cluster discovery fails outright so the
    caller can fall back to the last good cache.
    """
    clusters = []
    for name in discover_clusters():
        try:
            metrics = query_cluster(name)
        except Exception as e:  # one bad cluster shouldn't sink the rest
            print(f"Error querying Mimir for cluster {name}: {e}")
            continue
        # Belt and braces: skip clusters that return nothing at all.
        if not metrics:
            continue
        clusters.append({"name": name, "metrics": metrics})

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale": False,
        "clusters": clusters,
    }
