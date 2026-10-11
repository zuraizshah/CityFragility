"""Phase 2.5 — frontend performance-repair tests.

Three layers (all cheap, no browser needed):
1. Headless logic tests of explorer-core.js run with macOS jsc against the
   REAL stored phase2_results.csv rows (ranking/filter/colour correctness,
   top-composite integrity).
2. Static wiring markers in explorer.js/index.html proving the performance
   fixes are present (debounce band, no un-throttled input->heavy path, no
   per-event full-sort, default slider values of 0, bounded table size).
3. API checks that Phase 1 and Phase 2 results are unchanged.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC = PROJECT_ROOT / "webapp" / "static"
JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")


@pytest.fixture(scope="session")
def client():
    sys.path.insert(0, str(PROJECT_ROOT / "webapp"))
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import server
    from fastapi.testclient import TestClient

    with TestClient(server.app) as c:
        yield c


def _explorer_js() -> str:
    return (STATIC / "explorer.js").read_text()


def _index_html() -> str:
    return (STATIC / "index.html").read_text()


# ------------------------------------------------- 1. headless JS logic
@pytest.mark.skipif(not JSC.exists(), reason="jsc (JavaScriptCore) not available")
def test_explorer_core_logic_with_real_rows(tmp_path):
    df = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    rows = json.loads(df.to_json(orient="records"))
    rows_js = tmp_path / "rows.js"
    rows_js.write_text("var TEST_ROWS = " + json.dumps(rows) + ";")
    proc = subprocess.run(
        [
            str(JSC),
            str(STATIC / "explorer-core.js"),
            str(rows_js),
            str(PROJECT_ROOT / "tests" / "explorer_core_test.js"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"jsc core tests failed:\n{out}"
    assert "CORE_TESTS_PASS" in out, out
    # scientific integrity: top composite way and score unchanged
    assert "top=26182600" in out, out
    assert "score=12.895" in out, out
    # benchmark line present (old vs new colour path)
    assert "bench_old=" in out and "bench_new=" in out, out


@pytest.mark.skipif(not JSC.exists(), reason="jsc (JavaScriptCore) not available")
def test_explorer_js_parses_without_syntax_errors():
    """Run explorer.js headless: a SyntaxError would fail the parse; the
    expected reference error is the missing DOM (document)."""
    proc = subprocess.run(
        [str(JSC), str(STATIC / "explorer.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = proc.stdout + proc.stderr
    assert "SyntaxError" not in out, out


# --------------------------------------- 2. static wiring markers (perf)
def test_debounce_is_in_required_band():
    src = _explorer_js()
    assert "const DEBOUNCE_MS = 180" in src, "slider debounce must be 150–250 ms"
    ms = int(src.split("const DEBOUNCE_MS = ")[1].split(";")[0].strip())
    assert 150 <= ms <= 250


def test_sliders_not_bound_directly_to_heavy_path_on_input():
    src = _explorer_js()
    # the old bug: addEventListener("input", applyFilters)
    assert 'addEventListener("input", applyFilters)' not in src
    assert "addEventListener('input', applyFilters)" not in src
    # heavy work must be reachable from 'change' (pointer release)
    assert src.count('addEventListener("change"') >= 3  # rank + 2 sliders


def test_no_per_event_full_sort_of_filtered_rows():
    """The old colorFor() re-sorted V.filtered once per road feature per
    event — that exact pattern must be gone."""
    src = _explorer_js()
    assert "V.filtered.map(metricValue).sort" not in src
    assert "function metricValue(row)" not in src  # moved to pure core


def test_colors_precomputed_once_and_styled_in_place():
    src = _explorer_js()
    assert "ExplorerCore.recomputeColors" in src  # once per ranking change
    assert "feat._styleKey" in src  # skip setStyle when style unchanged
    assert 'addEventListener("input"' in src  # live readout still updates


def test_sliders_default_to_zero():
    html = _index_html()
    assert 'id="vuln-min-aff" min="0" max="10" value="0"' in html
    assert 'id="vuln-min-det" min="0" max="900" step="25" value="0"' in html


def test_table_is_bounded_and_core_script_loaded_first():
    src = _explorer_js()
    assert "maxRowsShown: 60" in src, "only visible rows may be rendered"
    html = _index_html()
    assert html.index("/explorer-core.js") < html.index("/explorer.js")


def test_selected_road_highlight_is_distinct():
    src = _explorer_js()
    assert 'SELECTED_COLOR = "#f43f5e"' in src
    assert "isSel ? 8 : 4" in src  # selected way is twice the regular weight
    css = (STATIC / "style.css").read_text()
    assert "#f43f5e" in css  # table row accent matches map highlight


def test_map_layers_never_recreated_by_filters():
    src = _explorer_js()
    # drawRoads is the only layer creator; it must guard against re-entry
    assert "V.vulnLayer.getLayers().length" in src
    # applyFilters must not call drawRoads
    block = src.split("function applyFilters()")[1].split("function renderTable()")[0]
    assert "drawRoads" not in block


# ------------------------------------- 3. Phase 1/2 results unchanged
def test_api_still_serves_explorer_core(client):
    r = client.get("/explorer-core.js")
    assert r.status_code == 200
    assert "ExplorerCore" in r.text
    r2 = client.get("/explorer.js")
    assert r2.status_code == 200


def test_phase2_top_result_unchanged_in_api(client):
    j = client.get("/api/vuln/summary").json()
    top = j["summary"]["rankings"]["by_composite_score"][0]
    assert int(top) == 26182600
    row = next(r for r in j["rows"] if int(r["osmid"]) == 26182600)
    assert row["n_affected"] == 4
    assert abs(row["disruption_score"] - 12.895) < 1e-6
    assert abs(row["median_extra_m"] - 889.51) < 1e-6
    assert len(j["rows"]) == 100


def test_phase1_a_street_regression_still_exact(client):
    r = client.post("/api/simulate?osmid=22744767")
    assert r.status_code == 200
    dha = next(o for o in r.json()["per_origin"] if o["name"] == "DHA Phase 5, Karachi")
    assert dha["delta_m"] == pytest.approx(442.27, abs=0.05)
    client.get("/api/restore")


def test_filters_never_trigger_recompute_endpoints(client):
    """The explorer's filter path must stay client-side: the only vuln
    endpoints are the three stored-artifact readers (no run/simulate)."""
    import server

    routes = {getattr(r, "path", "") for r in server.app.routes}
    assert "/api/vuln/summary" in routes
    assert "/api/vuln/roads.geojson" in routes
    assert "/api/vuln/detail" in routes
    assert not any("run" in p or "simulate" in p for p in routes if p.startswith("/api/vuln"))
