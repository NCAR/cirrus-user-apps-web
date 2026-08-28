"""
Load app/cluster_status/mimir_cluster.py directly from its path.

Importing it as `app.cluster_status.mimir_cluster` would run app/__init__.py,
which builds the Flask app and needs the full runtime dependency set. The
parsing layer has no Flask dependency, so load it standalone.
"""

import importlib.util
import pathlib

import pytest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "cirrus-apps" / "app" / "cluster_status" / "mimir_cluster.py"
)


@pytest.fixture(scope="session")
def mimir_cluster():
    spec = importlib.util.spec_from_file_location("mimir_cluster", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
