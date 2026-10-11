"""Phase 1 web API + interaction tests.

These exercise the FastAPI app over the REAL Phase 0 Karachi graph
(graph loaded once per session via a session-scoped client fixture).
They do not modify the verified routing engine; the engine is reused as-is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "webapp"))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="session")
def candidates(client):
    r = client.get("/api/candidates")
    assert r.status_code == 200
    return r.json()["candidates"]


# ------------------------------------------------------------------ health
def test_health_reports_real_graph(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    # real Phase 0 counts (FEASIBILITY_REPORT.md §4C)
    assert j["nodes"] == 45304
    assert j["edges"] == 122599
    assert j["candidates"] >= 8


# -------------------------------------------------------------- static UI
def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"CityFragility" in r.content
    assert b"unverified" in r.content.lower() or b"Unverified" in r.content


def test_app_js_and_leaflet_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/vendor/leaflet.js").status_code == 200


# ------------------------------------------------------------------ data
def test_origins_are_the_six_phase0_seeds(client):
    r = client.get("/api/origins")
    assert r.status_code == 200
    fc = r.json()
    names = {f["properties"]["name"] for f in fc["features"]}
    assert names == {
        "Saddar Chowrangi, Karachi",
        "Empress Market, Karachi",
        "Mazar-e-Quaid, Karachi",
        "Do Talwar, Karachi",
        "DHA Phase 5, Karachi",
        "NIPA Chowrangi, Karachi",
    }
    assert "sample" in fc["note"].lower()


def test_hospitals_unverified_and_real(client):
    r = client.get("/api/hospitals")
    assert r.status_code == 200
    fc = r.json()
    assert len(fc["features"]) == 453
    assert "unverified" in fc["note"].lower()
    f0 = fc["features"][0]["properties"]
    assert f0["unverified"] is True
    assert "emergency" in f0["note"].lower()
    # every feature carries the disclaimer
    assert all(f["properties"]["unverified"] for f in fc["features"])


def test_network_payload_is_bounded(client):
    r = client.get("/api/network")
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    n = len(fc["features"])
    # renderable subset: far below the full 122k graph, but a real road set
    assert 1000 < n < 40000
    assert len(r.content) < 12_000_000  # keep the browser comfortable
    # every feature is a real way id + LineString
    for f in fc["features"][:200]:
        assert f["geometry"]["type"] == "LineString"
        assert f["properties"]["osmid"] is not None


def test_candidates_bounded_stable_ids(candidates):
    assert 8 <= len(candidates) <= 40
    tested = [c for c in candidates if c["tested_in_phase0"]]
    assert len(tested) >= 8  # Phase 0's evaluated set is exposed
    for c in candidates:
        assert isinstance(c["osmid"], int)
        assert c["length_m"] > 0
        assert c["edges"] >= 1


# -------------------------------------------------------------- simulate
def test_simulate_unknown_way_is_404(client):
    r = client.post("/api/simulate?osmid=999999999999")
    assert r.status_code == 404


def test_simulate_phase0_disconnect_way(client):
    """Way 58733431 disconnected Saddar Chowrangi in Phase 0 — must reproduce."""
    r = client.post("/api/simulate?osmid=58733431")
    assert r.status_code == 200
    j = r.json()
    assert j["edges_removed"] > 0
    assert j["restored_ok"] is True
    assert j["graph_nodes"] == 45304 and j["graph_edges"] == 122599
    by_name = {o["name"]: o for o in j["per_origin"]}
    saddar = by_name["Saddar Chowrangi, Karachi"]
    assert saddar["disconnected"] is True
    assert saddar["after_m"] is None
    assert saddar["after_route"] is None
    # monotonicity: no origin ever gets a *shorter* distance
    for o in j["per_origin"]:
        if o["delta_m"] is not None:
            assert o["delta_m"] >= -1e-6
    # geometry present for connected origins
    emp = by_name["Empress Market, Karachi"]
    assert emp["disconnected"] is False
    assert emp["after_route"]["geometry"]
    assert emp["after_route"]["length_m"] == pytest.approx(emp["after_m"], abs=0.5)


def test_graph_is_restored_after_every_simulation(client):
    """Endpoint returns the exact baseline: graph state never leaks."""
    r = client.get("/api/restore")
    assert r.status_code == 200
    j = r.json()
    assert j["nodes"] == 45304 and j["edges"] == 122599
    by_name = {o["name"]: o for o in j["per_origin"]}
    # Phase 0 baseline distances (reports/baseline_results.csv)
    assert by_name["Saddar Chowrangi, Karachi"]["distance_m"] == pytest.approx(295.73, abs=0.05)
    assert by_name["Empress Market, Karachi"]["distance_m"] == pytest.approx(191.16, abs=0.05)
    assert by_name["NIPA Chowrangi, Karachi"]["distance_m"] == pytest.approx(1420.87, abs=0.05)
    assert all(not o["disconnected"] for o in j["per_origin"])


def test_interaction_flow_select_simulate_restore(client, candidates):
    """Full UI flow: pick a tested detour way, simulate, then restore."""
    # pick a Phase 0 way with a known positive delta (A Street, +442 m)
    way = next(
        (c for c in candidates if c["osmid"] == 22744767),
        None,
    )
    if way is None:  # fallback: any tested way
        way = next(c for c in candidates if c["tested_in_phase0"])
    r = client.post(f"/api/simulate?osmid={way['osmid']}")
    assert r.status_code == 200
    sim = r.json()
    deltas = [o["delta_m"] for o in sim["per_origin"] if o["delta_m"] is not None]
    assert deltas, "expected measurable per-origin deltas"
    assert max(deltas) >= 0
    # every connected origin exposes a before+after route polyline pair
    for o in sim["per_origin"]:
        if not o["disconnected"]:
            assert o["before_route"]["geometry"]
            assert o["after_route"]["geometry"]
    # restore returns the pristine baseline again
    j = client.get("/api/restore").json()
    assert j["edges"] == 122599


def test_simulation_leaves_graph_pristine_for_next_request(client, candidates):
    """Two different simulations in sequence both start from the baseline."""
    way_a = next(c for c in candidates if c["osmid"] == 58733431)
    way_b = next(c for c in candidates if c["tested_in_phase0"] and c["osmid"] != 58733431)
    ra = client.post(f"/api/simulate?osmid={way_a['osmid']}").json()
    rb = client.post(f"/api/simulate?osmid={way_b['osmid']}").json()
    # Saddar's baseline before distance must be identical in both runs
    a0 = next(o for o in ra["per_origin"] if o["name"] == "Saddar Chowrangi, Karachi")
    b0 = next(o for o in rb["per_origin"] if o["name"] == "Saddar Chowrangi, Karachi")
    assert a0["before_m"] == b0["before_m"]
