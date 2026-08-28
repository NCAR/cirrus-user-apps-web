"""Per-cluster Kubernetes status from Mimir."""

import os

# Which clusters the /status page shows, in order. The API itself stays
# policy-free and returns every cluster it discovers — this is presentation
# only, so a consumer that wants the full set still gets it.
DEFAULT_DISPLAY_CLUSTERS = "nwc1,mlc1"


def display_clusters():
    raw = os.getenv("CLUSTER_STATUS_DISPLAY_CLUSTERS", DEFAULT_DISPLAY_CLUSTERS)
    return [c.strip() for c in raw.split(",") if c.strip()]
