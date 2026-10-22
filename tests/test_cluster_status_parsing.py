"""
Parsing-layer tests for /api/cluster-status.

The correctness trap this guards: a cluster with no GPUs has no
DCGM_FI_DEV_GPU_UTIL series at all, and a cluster with no PVCs computes 0/0.
Both must produce an *omitted* key, never 0 — reporting 0 reads as "GPUs
present and idle", which is a different and wrong statement.
"""


def _element(panel, value):
    return {"metric": {"panel": panel}, "value": [1756402307.123, value]}


def _response(pairs):
    return {
        "status": "success",
        "data": {"resultType": "vector", "result": [_element(p, v) for p, v in pairs]},
    }


# Captured shape of a real Mimir response for nwc1 (GPUs + PVCs present).
NWC1 = _response([
    ("cpu_used", "3.8696357512953365"),
    ("mem_used", "46.71926763151204"),
    ("pod_slots", "26.953125"),
    ("cpu_requested", "25.257936507936508"),
    ("mem_requested", "93.68347168911425"),
    ("pvc_used", "28.639176315892946"),
    ("gpu_allocated", "113.46153846153847"),
    ("gpu_util", "14.135416666666666"),
    ("gpu_total", "52"),
    ("gpu_physical", "7"),
    ("nodes_ready", "14"),
    ("nodes_total", "14"),
    ("pods_running", "415"),
    ("pods_pending", "29"),
    ("namespaces", "43"),
    ("cpu_cores_used", "47.318"),
    ("cpu_cores_total", "640"),
    ("mem_bytes_used", "1979120929996.8"),
    ("mem_bytes_total", "4508876898304"),
])

# mlc3 has no GPUs (series absent) and no PVCs (0/0 -> NaN).
MLC3 = _response([
    ("cpu_used", "8.11"),
    ("mem_used", "57.06"),
    ("pod_slots", "24.83"),
    ("cpu_requested", "40.2"),
    ("mem_requested", "61.4"),
    ("pvc_used", "NaN"),
    ("nodes_ready", "3"),
    ("nodes_total", "3"),
    ("pods_running", "82"),
    ("pods_pending", "0"),
    ("namespaces", "21"),
])


def test_a_fully_populated_cluster_parses_every_panel(mimir_cluster):
    metrics = mimir_cluster.parse_cluster_metrics(NWC1)
    assert set(metrics) == set(mimir_cluster.PANEL_QUERIES)


def test_percentages_stay_floats_and_counts_become_ints(mimir_cluster):
    metrics = mimir_cluster.parse_cluster_metrics(NWC1)
    assert metrics["cpu_used"] == 3.87
    assert metrics["mem_used"] == 46.72
    # "415" must render as 415, not 415.0.
    assert metrics["pods_running"] == 415
    assert isinstance(metrics["pods_running"], int)
    assert isinstance(metrics["gpu_total"], int)


def test_gpu_overcommit_is_not_clamped(mimir_cluster):
    # GPU requests legitimately exceed allocatable; >100% is the signal.
    assert mimir_cluster.parse_cluster_metrics(NWC1)["gpu_allocated"] == 113.46


def test_absent_gpu_series_are_omitted_not_zeroed(mimir_cluster):
    metrics = mimir_cluster.parse_cluster_metrics(MLC3)
    for panel in ("gpu_util", "gpu_total", "gpu_allocated"):
        assert panel not in metrics


def test_nan_pvc_used_is_omitted_not_zeroed(mimir_cluster):
    metrics = mimir_cluster.parse_cluster_metrics(MLC3)
    assert "pvc_used" not in metrics
    # ...and the rest of the cluster still parses.
    assert metrics["pods_running"] == 82


def test_real_zero_is_kept(mimir_cluster):
    # GPUs reserved but idle (measured on mlc1) and zero pending pods are both
    # real readings, distinct from absent.
    metrics = mimir_cluster.parse_cluster_metrics(
        _response([("gpu_util", "0"), ("gpu_allocated", "28.0"), ("pods_pending", "0")])
    )
    assert metrics["gpu_util"] == 0.0
    assert metrics["pods_pending"] == 0


def test_infinite_values_are_omitted(mimir_cluster):
    metrics = mimir_cluster.parse_cluster_metrics(
        _response([("mem_requested", "+Inf"), ("cpu_used", "1.0")])
    )
    assert "mem_requested" not in metrics
    assert metrics["cpu_used"] == 1.0


def test_empty_and_malformed_responses_yield_no_metrics(mimir_cluster):
    assert mimir_cluster.parse_cluster_metrics(_response([])) == {}
    assert mimir_cluster.parse_cluster_metrics({"status": "error"}) == {}
    assert mimir_cluster.parse_cluster_metrics({"data": {"result": None}}) == {}
    assert mimir_cluster.parse_cluster_metrics(None) == {}
    # Unknown panel labels are ignored rather than passed through.
    assert mimir_cluster.parse_cluster_metrics(_response([("bogus", "1")])) == {}


def test_query_builder_substitutes_cluster_without_format_errors(mimir_cluster):
    query = mimir_cluster.build_union_query("nwc1")
    assert "__CLUSTER__" not in query
    assert query.count('label_replace(') == len(mimir_cluster.PANEL_QUERIES)
    assert 'cluster="nwc1"' in query
    assert '"panel", "cpu_used"' in query


def test_mimir_base_url_trims_the_query_path(mimir_cluster, monkeypatch):
    monkeypatch.delenv("MIMIR_BASE_URL", raising=False)
    monkeypatch.setattr(
        mimir_cluster, "MIMIR_URL",
        "https://mimir.k8s.ucar.edu/prometheus/api/v1/query",
    )
    assert mimir_cluster.mimir_base_url() == "https://mimir.k8s.ucar.edu/prometheus"


def test_display_clusters_defaults_to_the_two_user_facing_clusters(cluster_status_pkg, monkeypatch):
    monkeypatch.delenv("CLUSTER_STATUS_DISPLAY_CLUSTERS", raising=False)
    assert cluster_status_pkg.display_clusters() == ["nwc1", "mlc1"]


def test_display_clusters_honours_the_env_override(cluster_status_pkg, monkeypatch):
    monkeypatch.setenv("CLUSTER_STATUS_DISPLAY_CLUSTERS", " nwc1 , mlc1 ,mgmt, ")
    assert cluster_status_pkg.display_clusters() == ["nwc1", "mlc1", "mgmt"]


def test_slot_count_and_physical_count_are_separate_metrics(mimir_cluster):
    # nwc1 advertises 52 schedulable slots across 7 physical cards because the
    # low-powered GPUs are time-sliced. Both numbers must survive intact — the
    # slot count is what the scheduler uses, the card count is what exists.
    metrics = mimir_cluster.parse_cluster_metrics(NWC1)
    assert metrics["gpu_total"] == 52
    assert metrics["gpu_physical"] == 7
    assert isinstance(metrics["gpu_physical"], int)


def test_physical_gpu_count_is_omitted_on_gpuless_clusters(mimir_cluster):
    assert "gpu_physical" not in mimir_cluster.parse_cluster_metrics(MLC3)



def test_absolute_capacity_figures_back_the_percentages(mimir_cluster):
    payload = _response([
        ("cpu_cores_used", "47.318"), ("cpu_cores_total", "640"),
        ("mem_bytes_used", "1979120929996.8"), ("mem_bytes_total", "4508876898304"),
    ])
    metrics = mimir_cluster.parse_cluster_metrics(payload)
    # Cores in use keeps its fraction; counts and byte totals round to int.
    assert metrics["cpu_cores_used"] == 47.32
    assert metrics["cpu_cores_total"] == 640
    assert isinstance(metrics["mem_bytes_total"], int)
    assert metrics["mem_bytes_total"] == 4508876898304


def test_capacity_queries_are_self_consistent(mimir_cluster):
    # used and total both come from node_cpu_seconds_total, so the ratio can't
    # drift the way mixing node metrics with kube allocatable would.
    assert "node_cpu_seconds_total" in mimir_cluster.PANEL_QUERIES["cpu_cores_used"]
    assert "node_cpu_seconds_total" in mimir_cluster.PANEL_QUERIES["cpu_cores_total"]
    assert "node_memory_MemTotal_bytes" in mimir_cluster.PANEL_QUERIES["mem_bytes_total"]


def test_no_namespace_filtering_remains(mimir_cluster):
    # Platform pods count: they run the plumbing user workloads depend on.
    assert "namespace!~" not in mimir_cluster.build_union_query("nwc1")
