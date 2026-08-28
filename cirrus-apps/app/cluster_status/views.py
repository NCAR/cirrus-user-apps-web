import json
import os
import threading
from datetime import datetime, timedelta

from flask import jsonify

from app import app
from .mimir_cluster import get_cluster_status

# Per-pod cache (replicaCount is 2, so this is not shared — that's fine).
CLUSTER_STATUS_FILE = os.getenv("CLUSTER_STATUS_FILE", "static/cluster_status.json")
# 60s, not the 1 hour /metrics uses: these queries are fast (~1.8s for all
# clusters) and this sits inside the Grafana dashboard's own 1m refresh.
CLUSTER_STATUS_MAX_AGE_SECONDS = int(os.getenv("CLUSTER_STATUS_MAX_AGE_SECONDS", "60"))

_cluster_status_generating = False
_cluster_status_lock = threading.Lock()


def cluster_status_is_stale():
    if not os.path.exists(CLUSTER_STATUS_FILE):
        return True
    file_age = datetime.utcnow() - datetime.utcfromtimestamp(
        os.path.getmtime(CLUSTER_STATUS_FILE)
    )
    return file_age > timedelta(seconds=CLUSTER_STATUS_MAX_AGE_SECONDS)


def regenerate_cluster_status():
    payload = get_cluster_status()

    # Don't overwrite a good cache with an empty result — a Mimir blip should
    # leave the last good payload in place to be served as stale.
    if not payload.get("clusters"):
        raise RuntimeError("Mimir returned no cluster data")

    os.makedirs(os.path.dirname(CLUSTER_STATUS_FILE) or ".", exist_ok=True)
    tmp_path = f"{CLUSTER_STATUS_FILE}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, CLUSTER_STATUS_FILE)  # atomic, so readers never see a partial file
    return payload


def regenerate_cluster_status_background():
    global _cluster_status_generating
    with _cluster_status_lock:
        if _cluster_status_generating:
            return
        _cluster_status_generating = True
    try:
        regenerate_cluster_status()
    except Exception as e:
        print(f"Error refreshing cluster status: {e}")
    finally:
        _cluster_status_generating = False


@app.route("/api/cluster-status")
def cluster_status():
    if cluster_status_is_stale():
        thread = threading.Thread(target=regenerate_cluster_status_background, daemon=True)
        thread.start()

        # Stale (or last-good-after-failure) file exists — serve it flagged.
        if os.path.exists(CLUSTER_STATUS_FILE):
            try:
                with open(CLUSTER_STATUS_FILE, "r") as f:
                    data = json.load(f)
                data["stale"] = True
                return jsonify(data)
            except (OSError, ValueError) as e:
                print(f"Error reading cluster status cache: {e}")
                return jsonify({"generating": True}), 202

        # No file at all — tell the consumer to keep polling.
        return jsonify({"generating": True}), 202

    with open(CLUSTER_STATUS_FILE, "r") as f:
        return jsonify(json.load(f))
