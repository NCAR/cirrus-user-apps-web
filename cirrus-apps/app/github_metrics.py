import os
import requests
from datetime import datetime, timedelta

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

OWNER = "NCAR"
REPO = "cirrus-user-apps-web"

def get_workflow_runs():

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    params = {
        "per_page": 100
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        return []

    return response.json()["workflow_runs"]


def last_30_days_runs(runs):

    cutoff = datetime.utcnow() - timedelta(days=30)

    filtered = []

    for run in runs:
        created = datetime.strptime(run["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        if created > cutoff:
            filtered.append(run)

    return filtered


def calculate_metrics(runs):

    workflow_count = len(runs)
    total_minutes = 0

    for run in runs:

        if run["run_started_at"] and run["updated_at"]:

            start = datetime.strptime(run["run_started_at"], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(run["updated_at"], "%Y-%m-%dT%H:%M:%SZ")

            minutes = (end - start).total_seconds() / 60
            total_minutes += minutes

    return {
        "workflow_count": workflow_count,
        "runner_minutes": round(total_minutes, 2)
    }

