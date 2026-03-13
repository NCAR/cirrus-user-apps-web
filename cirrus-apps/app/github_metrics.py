import os
import json
import requests
from datetime import datetime, timedelta

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable not set")

REPOS = [
    "CROCODILE-CESM/CrocoDash",
    "ESCOMP/CAM-SIMA",
    "ESCOMP/CTSM",
    "khrpcek-ucar/actions-test",
    "NCAR/CIRRUS-MILES-CREDIT",
    "NCAR/MILES-CREDIT",
    "NCAR/stormspeed",
    "TURBO-ESM/turbo-stack"
]


def get_workflow_runs(repo):

    url = f"https://api.github.com/repos/{repo}/actions/runs"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    params = {
        "per_page": 100
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        print(f"Failed to fetch runs for {repo}: {response.status_code}")
        return []

    return response.json().get("workflow_runs", [])


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


def main():

    all_runs = []

    for repo in REPOS:
        print(f"Fetching workflow runs for {repo}")
        runs = get_workflow_runs(repo)
        all_runs.extend(runs)

    runs_last_30 = last_30_days_runs(all_runs)

    metrics = calculate_metrics(runs_last_30)

    print("Metrics:", metrics)

    with open("static/runner_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()