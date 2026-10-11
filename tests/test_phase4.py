"""Phase 4 — lightweight research viewer + product shell tests.

Proves the server serves the Vulnerability Explorer + Findings + health
WITHOUT loading the 45k-node NetworkX graph (lazy routing engine), that the
precomputed artifacts match the stored experiment, and that the professional
UI shell (4 tabs, Overview default, deferred simulator init, footer) is wired.
No browser required; the one subprocess test is the independent
research-viewer check.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = PROJECT_ROOT / "webapp" / "static"
JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")

KNOWN_NODES, KNOWN_EDGES = 45304, 122599


@pytest.fixture()
def client():
    sys.path.insert(0, str(PROJECT_ROOT / "webapp"))
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import server
    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def graph_free(client):
    """Patch the module so any graph load raises, and hide any cached graph.

    Research endpoints must keep working; the live simulate endpoint must
    fail — proving it still needs the routing engine.
    """
    import server

    def _raise(*a, **k):
        raise RuntimeError("GRAPH LOAD FORBIDDEN in research mode")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server, "ensure_loaded", _raise)
        mp.setattr(server, "_G", None)
        yield client


# ------------------------------------------------------- graph-free serving
def test_research_endpoints_never_touch_graph(graph_free):
    c = graph_free
    for url in (
        "/api/health",
        "/api/candidates",
        "/api/vuln/summary",
        "/api/vuln/roads.geojson",
        "/api/vuln/detail?osmid=26182600",
        "/api/research",
    ):
        r = c.get(url)
        assert r.status_code == 200, f"{url} -> {r.status_code}"


def test_health_research_mode_is_from_saved_metadata(graph_free):
    j = graph_free.get("/api/health").json()
    assert j["status"] == "ok"
    assert j["nodes"] == KNOWN_NODES and j["edges"] == KNOWN_EDGES
    assert j["graph_loaded"] is False
    assert j["mode"] == "research"
    assert j["hospitals_total"] == 453
    assert j["hospitals_usable_nodes"] == 419
    assert j["candidates"] >= 8


def test_live_simulate_still_requires_the_graph(graph_free):
    """The lazy engine is intact: simulate fails loudly without the graph."""
    r = graph_free.post("/api/simulate?osmid=26182600")
    assert r.status_code == 500
    assert "GRAPH LOAD FORBIDDEN" in r.json()["detail"]


# ------------------------------------------------------ artifact integrity
def test_precomputed_roads_match_experiment():
    import pandas as pd

    roads = json.loads((PROJECT_ROOT / "data" / "phase2_roads.geojson").read_text())
    assert roads["type"] == "FeatureCollection"
    assert len(roads["features"]) == 100
    props = {f["properties"]["osmid"] for f in roads["features"]}
    df = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    assert props == set(int(x) for x in df["osmid"])


def test_precomputed_details_cover_all_100_ways_and_top_payload():
    det = json.loads(
        (PROJECT_ROOT / "reports" / "phase2_vuln_details.json").read_text()
    )
    import pandas as pd

    df = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    assert set(det.keys()) == {str(int(x)) for x in df["osmid"]}
    top = det["26182600"]
    assert top["meta"]["n_affected"] == 4
    assert abs(top["meta"]["disruption_score"] - 12.895) < 1e-9
    assert len(top["per_origin"]) == 100
    assert top["worst_origin_example"] is not None
    assert top["worst_origin_example"]["before_geometry"]


def test_detail_endpoint_returns_stored_payload_identically(client):
    r = client.get("/api/vuln/detail?osmid=26182600")
    assert r.status_code == 200
    j = r.json()
    assert j["meta"]["n_affected"] == 4
    assert abs(j["meta"]["disruption_score"] - 12.895) < 1e-9
    assert len(j["per_origin"]) == 100
    assert j["worst_origin_example"]["baseline_m"] is not None


def test_server_meta_matches_real_graph_counts():
    meta = json.loads((PROJECT_ROOT / "data" / "server_meta.json").read_text())
    assert meta["nodes"] == KNOWN_NODES
    assert meta["edges"] == KNOWN_EDGES
    assert meta["hospitals_total"] == 453


# ------------------------------------------------------------- UI shell
def _html() -> str:
    return (STATIC / "index.html").read_text()


def test_index_four_tabs_overview_default_and_footer():
    h = _html()
    for tab in ("tab-overview", "tab-vuln", "tab-sim", "tab-findings"):
        assert f'id="{tab}"' in h
    assert 'id="tab-overview" class="tab active"' in h
    for view in ("view-overview", "view-vuln", "view-sim", "view-findings"):
        assert f'id="{view}"' in h
    assert "site-footer" in h and "OpenStreetMap" in h
    assert "mode-badge" in h
    assert "research mode" in h
    # product copy present
    assert "What this model CANNOT say" in h
    assert "How to use — 3 steps" in h
    assert "not real flood" in h.lower() or "Not real flood" in h


def test_app_js_defers_heavy_simulator_init():
    src = (STATIC / "app.js").read_text()
    # public lazy-init API exported for tab handlers
    assert "function ensureMap()" in src
    assert "function initSimulator()" in src
    assert "window.__cf = { state, COLORS, ensureMap, initSimulator }" in src
    # main() must not load the heavy layers
    main = src.split("async function main()")[1].split("main();")[0]
    assert "loadNetwork" not in main
    assert "loadHospitals" not in main
    assert "loadCandidates" not in main
    assert "/api/health" in main


def test_explorer_activation_is_null_safe_and_graph_free():
    src = (STATIC / "explorer.js").read_text()
    assert "cf.ensureMap()" in src
    assert "initSimulator" in src  # sim tab hook
    assert "cf.state.roadLayer" in src and "if (cf.state.roadLayer)" in src
    assert "casingLayer" in src
    assert "__cfPerf" in src  # measured hot-path profiler


def test_dom_ids_used_by_js_exist_in_html():
    h = _html()
    ids: set[str] = set()
    for f in ("app.js", "explorer.js", "findings.js"):
        src = (STATIC / f).read_text()
        ids.update(re.findall(r'\$\("([^"]+)"\)', src))
        ids.update(re.findall(r'getElementById\("([^"]+)"\)', src))
    # stat-network-note is an optional legacy element removed if present
    ids.discard("stat-network-note")
    missing = {i for i in ids if f'id="{i}"' not in h}
    assert not missing, f"HTML missing element ids used by JS: {sorted(missing)}"


@pytest.mark.skipif(not JSC.exists(), reason="jsc (JavaScriptCore) not available")
@pytest.mark.parametrize("fname", ["app.js", "explorer.js", "explorer-core.js", "findings.js"])
def test_jsc_parses_all_scripts(fname):
    """Syntax-clean: jsc fails only on missing DOM globals, never on SyntaxError."""
    proc = subprocess.run(
        [str(JSC), str(STATIC / fname)],
        capture_output=True, text=True, timeout=30,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "SyntaxError" not in out, f"{fname} has a syntax error:\n{out}"
    assert "document" in out or "window" in out or "L is not defined" in out or proc.returncode == 0


# ---------------------------------------- independent research-viewer check
def test_research_viewer_works_in_clean_subprocess():
    """Fresh process: research endpoints + health without any graph load."""
    code = r"""
import json, resource, sys
sys.path.insert(0, r"PROJECT/webapp")
sys.path.insert(0, r"PROJECT/src")
import server

def _raise(*a, **k):
    raise RuntimeError("GRAPH LOAD FORBIDDEN")
server.ensure_loaded = _raise

from fastapi.testclient import TestClient
with TestClient(server.create_app()) as c:
    assert c.get("/api/health").json()["graph_loaded"] is False
    assert c.get("/api/vuln/summary").status_code == 200
    assert len(c.get("/api/vuln/roads.geojson").json()["features"]) == 100
    d = c.get("/api/vuln/detail?osmid=26182600").json()
    assert d["meta"]["n_affected"] == 4
    assert c.get("/api/research").status_code == 200
    assert server._G is None
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    print(f"OK RSS={rss_mb:.0f}MB")
"""
    code = code.replace("PROJECT", str(PROJECT_ROOT))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"research-viewer subprocess failed:\n{out}"
    assert "OK RSS=" in out
    rss = float(out.split("OK RSS=")[1].split("MB")[0])
    assert rss < 600, f"research viewer used {rss} MB (expected < 600 MB)"


# ------------------------------------------------- scientific integrity
def test_explorer_copy_distinguishes_modeled_access():
    h = _html()
    assert "modeled access" in h
    assert "not real flood risk" in h.lower() or "not real flood" in h.lower()
    assert "not population" in h.lower() or "not representative" in h.lower()
    assert "Geofabrik" in h


def test_saved_scientific_results_untouched():
    """Key stored numbers from Phases 2–3 still match the verified record."""
    import pandas as pd

    df = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    assert len(df) == 100
    top = df.sort_values("disruption_score", ascending=False).iloc[0]
    assert int(top["osmid"]) == 26182600
    assert abs(float(top["disruption_score"]) - 12.895) < 1e-9
    f3 = json.loads((PROJECT_ROOT / "reports" / "phase3_findings.json").read_text())
    ew = f3["sensitivity"]["east_west"]
    assert ew["by_composite_score"]["overlap"]["overlap"] == 0
    assert ew["by_affected_count"]["overlap"]["overlap"] == 0
