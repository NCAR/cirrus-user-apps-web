import json
import os
import threading
from datetime import datetime, timedelta
from flask import jsonify
from app import app
from .github_metrics import get_cpu_hours

METRICS_FILE = "static/runner_metrics.json"
METRICS_MAX_AGE_HOURS = 1

_metrics_generating = False
_metrics_lock = threading.Lock()


def metrics_are_stale():
    if not os.path.exists(METRICS_FILE):
        return True
    file_age = datetime.utcnow() - datetime.utcfromtimestamp(os.path.getmtime(METRICS_FILE))
    return file_age > timedelta(hours=METRICS_MAX_AGE_HOURS)


    
def regenerate_metrics():
    cpu_data = get_cpu_hours()
    metrics = {
        "cpu_hours": cpu_data
    }
    os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)
    with open(METRICS_FILE, "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def regenerate_metrics_background():
    global _metrics_generating
    with _metrics_lock:
        if _metrics_generating:
            return
        _metrics_generating = True
    try:
        regenerate_metrics()
    finally:
        _metrics_generating = False


@app.route("/metrics")
def metrics():
    global _metrics_generating

    if metrics_are_stale():
        thread = threading.Thread(target=regenerate_metrics_background, daemon=True)
        thread.start()

        # Stale file exists — return it with a flag so the UI can show a warning and re-poll
        if os.path.exists(METRICS_FILE):
            with open(METRICS_FILE, "r") as f:
                data = json.load(f)
            data["stale"] = True
            return jsonify(data)

        # No file at all — return 202 so the UI knows to keep polling
        return jsonify({"generating": True}), 202

    with open(METRICS_FILE, "r") as f:
        return jsonify(json.load(f))