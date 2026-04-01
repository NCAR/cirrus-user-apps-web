import os
import json
import requests

MIMIR_URL = os.getenv(
    "MIMIR_URL",
    "https://mimir.k8s.ucar.edu/prometheus/api/v1/query"
)


def get_cpu_hours():
    """
    Fetch CPU hours per cluster (GitHub runners only)
    """

    query = """
    sum by (cluster) (
      increase(container_cpu_usage_seconds_total{
        namespace=~"(arc-runners|arc-systems)",
        container=~"(runner|buildkitd|job)"
      }[30d])
    ) / 3600
    """

    try:
        response = requests.get(
            MIMIR_URL,
            params={"query": query},
            auth=(os.getenv("MIMIR_USER"), os.getenv("MIMIR_PASS")),
            headers={"X-Scope-OrgID": "1"},
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

        results = {}
        total = 0

        for item in data.get("data", {}).get("result", []):
            cluster = item["metric"].get("cluster", "unknown")
            value = float(item["value"][1])
            results[cluster] = round(value, 2)
            total += value

        return {
            "total_hours": round(total, 2),
            "by_cluster": results
        }

    except Exception as e:
        print(f"Error querying Mimir: {e}")
        return {}


def main():
    cpu_data = get_cpu_hours()

    metrics = {
        "cpu_hours": cpu_data
    }

    print("Metrics:", metrics)

    with open("cirrus-apps/app/static/runner_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()