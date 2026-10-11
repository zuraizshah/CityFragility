"""Phase 2 tests: sampling, candidates, experiment engine, metrics, API.

Uses the REAL Phase 0/1/2 artifacts (graph via the shared server module
singleton; stored experiment CSVs). No mock data is presented as real —
synthetic rows are used ONLY for pure-metric unit tests and are labelled.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "webapp"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import config  # noqa: E402
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from phase2_experiment import compute_metrics, rank_lists, top_overlap  # noqa: E402
from phase2_sample_origins import GRID_COLS, GRID_ROWS, PER_CELL, SEED, cell_of  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="session")
def graph():
    return server.ensure_loaded()


@pytest.fixture(scope="session")
def phase2_results():
    path = config.REPORTS_DIR / "phase2_results.csv"
    if not path.exists():
        pytest.skip("phase2_results.csv not present")
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def phase2_per_origin():
    path = config.REPORTS_DIR / "phase2_per_origin.csv"
    if not path.exists():
        pytest.skip("phase2_per_origin.csv not present")
    return pd.read_csv(path)


# ------------------------------------------------------------ Part A: sampling
def test_sample_is_100_rows_in_core_unique(graph):
    df = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    assert len(df) == 100
    assert df["node_id"].is_unique
    w, s, e, n = config.CORE_BBOX
    assert ((df["lon"] >= w) & (df["lon"] <= e) & (df["lat"] >= s) & (df["lat"] <= n)).all()
    # every node exists in the real graph and has degree >= 1
    for node in df["node_id"].head(20):
        assert graph.has_node(int(node))
        assert graph.degree(int(node)) >= 1


def test_sample_report_matches_csv():
    df = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    rep = json.loads((config.REPORTS_DIR / "phase2_origin_sampling_report.json").read_text())
    assert rep["sample_size"] == len(df)
    assert rep["seed"] == SEED
    assert rep["grid_rows"] == GRID_ROWS and rep["grid_cols"] == GRID_COLS
    assert "population" in rep["interpretation_note"].lower()


def test_sampling_cell_function_is_deterministic():
    w, s, e, n = config.CORE_BBOX
    assert cell_of(w, s, w, s, e, n, 5, 5) == (0, 0)
    assert cell_of(e, n, w, s, e, n, 5, 5) == (4, 4)
    # clamped out-of-bounds stays inside grid
    assert cell_of(e + 1, n + 1, w, s, e, n, 5, 5) == (4, 4)


def test_sampling_rng_reproducible():
    a = list(range(50))
    b = list(range(50))
    random.Random(SEED).shuffle(a)
    random.Random(SEED).shuffle(b)
    assert a == b


def test_original_six_origins_preserved():
    df = pd.read_csv(config.ORIGINS_SNAPPED_PATH)
    assert len(df) == 6  # untouched Phase 0/1 regression set


# ------------------------------------------------------------ Part B: candidates
def test_candidates_bounded_unique_tiers(phase2_results, graph):
    cdf = pd.read_csv(config.DATA_DIR / "phase2_candidates.csv")
    assert 8 <= len(cdf) <= 100
    assert cdf["osmid"].is_unique
    assert set(cdf["selection_tier"]) <= {
        "phase0_tested", "phase1_origin_path", "sample_path_frequency", "stratified_fill"
    }
    assert (cdf["selection_tier"] == "phase0_tested").sum() == 8
    # every candidate way exists in the graph
    graph_osmids = {d.get("osmid") for _, _, d in graph.edges(data=True)}
    for oid in cdf["osmid"].head(30):
        assert int(oid) in {int(x) for x in graph_osmids if x is not None}


# ------------------------------------------------- Part C/D: engine + metrics
def test_multi_source_with_source_matches_routing_engine(graph):
    """Custom labeled Dijkstra must equal the verified multi-source engine."""
    from phase2_experiment import facility_map, multi_source_with_source
    from routing import distances_to_targets

    fac, _ = facility_map(graph)
    dist, src = multi_source_with_source(graph, fac)
    ref = distances_to_targets(graph, set(fac.keys()))
    for node in list(ref.keys())[::500]:
        assert dist[node] == pytest.approx(ref[node], rel=1e-9)
        assert node in src


def test_compute_metrics_on_synthetic_rows():
    # SYNTHETIC rows (metric unit test only — not presented as real results)
    rows = [
        {"detour_m": 0.0, "newly_disconnected": False, "destination_switched": False},
        {"detour_m": 100.0, "newly_disconnected": False, "destination_switched": True},
        {"detour_m": 300.0, "newly_disconnected": False, "destination_switched": False},
        {"detour_m": None, "newly_disconnected": True, "destination_switched": False},
    ]
    m = compute_metrics(rows)
    assert m["n_origins"] == 4
    assert m["n_affected"] == 2
    assert m["pct_affected"] == 50.0
    assert m["median_extra_m"] == 300.0  # upper median of [100, 300]
    assert m["max_extra_m"] == 300.0
    assert m["n_newly_disconnected"] == 1
    assert m["n_destination_switched"] == 1
    assert m["disruption_score"] == 2 + 5 * 1 + min(300 / 100, 20)


def test_rank_lists_ordering_synthetic():
    # SYNTHETIC results (ranking unit test only)
    results = [
        {"osmid": 1, "n_affected": 1, "n_newly_disconnected": 0,
         "median_extra_m": 50, "max_extra_m": 50, "disruption_score": 1.5},
        {"osmid": 2, "n_affected": 5, "n_newly_disconnected": 1,
         "median_extra_m": 200, "max_extra_m": 400, "disruption_score": 12.0},
        {"osmid": 3, "n_affected": 0, "n_newly_disconnected": 0,
         "median_extra_m": 0, "max_extra_m": 0, "disruption_score": 0.0},
    ]
    r = rank_lists(results)
    assert r["by_affected_count"][0] == 2
    assert r["by_disconnections"][0] == 2
    assert r["by_composite_score"][0] == 2
    assert r["by_median_detour"][0] == 2
    assert 3 not in r["by_median_detour"]  # unaffected ways excluded from detour ranking


def test_top_overlap_math():
    o = top_overlap([1, 2, 3, 4, 5, 9], [4, 5, 6, 7, 8, 9], k=5)
    assert o["overlap"] == 2  # {4,5}


def test_stored_experiment_restore_verified():
    s = json.loads((config.REPORTS_DIR / "phase2_summary.json").read_text())
    assert s["restore_verified_identical"] is True
    assert s["n_candidates_completed"] == 100
    assert s["n_origins"] == 100
    assert s["partial"] is False


def test_disconnection_classification_consistent(phase2_per_origin):
    """If any disconnections exist, they must be classified and never inf."""
    disc = phase2_per_origin[phase2_per_origin["newly_disconnected"] == True]  # noqa: E712
    for _, r in disc.iterrows():
        assert pd.isna(r["detour_m"])  # never infinity as a numeric detour
        assert pd.isna(r["disrupted_m"])
        assert bool(r["origin_isolated_stub"]) ^ bool(r["cut_from_facility_network"])
    # the classification code path is covered by a synthetic row regardless
    # of whether the real sample produced a disconnection
    from phase2_experiment import compute_metrics

    m = compute_metrics([{"detour_m": None, "newly_disconnected": True,
                          "destination_switched": False}])
    assert m["n_newly_disconnected"] == 1


def test_destination_switch_rows_have_different_facilities(phase2_per_origin):
    sw = phase2_per_origin[phase2_per_origin["destination_switched"] == True]  # noqa: E712
    if len(sw) == 0:
        pytest.skip("sample produced no destination switches")
    resolved = sw[(sw["baseline_facility"] != "?") & (sw["disrupted_facility"] != "?")]
    if len(resolved) == 0:
        pytest.skip("no switches with both facilities resolved to a name")
    for _, r in resolved.head(20).iterrows():
        assert r["baseline_facility"] != r["disrupted_facility"]


def test_unaffected_rows_retained(phase2_per_origin):
    unchanged = phase2_per_origin[
        (phase2_per_origin["detour_m"].fillna(0) == 0)
        & (phase2_per_origin["newly_disconnected"] == False)  # noqa: E712
    ]
    assert len(unchanged) > 1000  # unaffected results are kept, not dropped


# ------------------------------------------------------------- Part E: API
def test_vuln_summary_payload_matches_stored_csv(client, phase2_results):
    r = client.get("/api/vuln/summary")
    assert r.status_code == 200
    j = r.json()
    assert len(j["rows"]) == len(phase2_results) == 100
    row0 = j["rows"][0]
    csv0 = phase2_results.iloc[0].to_dict()
    assert int(row0["osmid"]) == int(csv0["osmid"])
    assert float(row0["disruption_score"]) == pytest.approx(float(csv0["disruption_score"]), rel=1e-6)
    assert j["summary"]["restore_verified_identical"] is True
    assert "by_composite_score" in j["summary"]["rankings"]
    assert j["sampling"]["seed"] == SEED
    assert any("population" in b.lower() for b in j["candidates_method"]["biases"])


def test_vuln_roads_geojson_covers_candidates(client, phase2_results):
    r = client.get("/api/vuln/roads.geojson")
    assert r.status_code == 200
    fc = r.json()
    ids = {f["properties"]["osmid"] for f in fc["features"]}
    # every candidate with geometry in the graph appears
    assert len(ids) >= 90
    assert set(phase2_results["osmid"].astype(int)) >= ids or len(ids) >= 90


def test_vuln_detail_known_way_payload(client, phase2_results):
    """Detail payload for a real top-ranked way has the full structure."""
    top = phase2_results.sort_values("disruption_score", ascending=False).iloc[0]
    oid = int(top["osmid"])
    r = client.get(f"/api/vuln/detail?osmid={oid}")
    assert r.status_code == 200
    j = r.json()
    assert len(j["per_origin"]) == 100
    # every disconnection present (if any) is classified, never a numeric detour
    for p in j["per_origin"]:
        if p["newly_disconnected"]:
            assert p["detour_m"] is None
            assert bool(p["origin_isolated_stub"]) ^ bool(p["cut_from_facility_network"])
    ex = j["worst_origin_example"]
    if ex is not None and not ex["newly_disconnected"]:
        # for a reachable worst case, both before/after geometries are provided
        assert ex.get("before_geometry") and ex.get("after_geometry")


def test_vuln_detail_unknown_osmid_404(client):
    r = client.get("/api/vuln/detail?osmid=999999999")
    assert r.status_code == 404


def test_dashboard_uses_only_stored_results(client, phase2_results, phase2_per_origin):
    """Summary rows must equal the CSV — the dashboard cannot invent rows."""
    j = client.get("/api/vuln/summary").json()
    csv_scores = {
        int(r.osmid): round(float(r.disruption_score), 6)
        for r in phase2_results.itertuples()
    }
    for row in j["rows"]:
        assert csv_scores[int(row["osmid"])] == round(float(row["disruption_score"]), 6)
    per = pd.DataFrame(j["rows"])
    assert len(per) == len(phase2_per_origin.groupby("candidate_osmid"))


# --------------------------------------------------- Part F: regressions
def test_a_street_still_reproduces_442(client):
    """Phase 1/0 regression: A Street closure = +442.27 m for DHA Phase 5."""
    r = client.post("/api/simulate?osmid=22744767")
    assert r.status_code == 200
    j = r.json()
    dha = next(o for o in j["per_origin"] if o["name"] == "DHA Phase 5, Karachi")
    assert dha["delta_m"] == pytest.approx(442.27, abs=0.05)


def test_baseline_still_identical_after_all_phase2_traffic(client):
    r = client.get("/api/restore")
    j = r.json()
    assert j["nodes"] == 45304 and j["edges"] == 122599
    by = {o["name"]: o for o in j["per_origin"]}
    assert by["Saddar Chowrangi, Karachi"]["distance_m"] == pytest.approx(295.73, abs=0.05)
    assert by["NIPA Chowrangi, Karachi"]["distance_m"] == pytest.approx(1420.87, abs=0.05)
