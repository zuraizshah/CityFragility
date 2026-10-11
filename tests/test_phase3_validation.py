"""Phase 3 — research-validation tests.

Validates the stored Phase 3 findings artifact, re-derives reproducibility
in-test from the saved per-origin CSV (pandas only, no graph load), and
checks the Research Findings API/panel wiring. Existing Phase 0/1/2/2.5
tests are unchanged and run in the same suite.
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


@pytest.fixture(scope="session")
def findings():
    path = PROJECT_ROOT / "reports" / "phase3_findings.json"
    if not path.exists():
        pytest.skip("phase3_findings.json not present — run src/phase3_validation.py")
    return json.loads(path.read_text())


# ------------------------------------------------- stored artifact integrity
def test_reproducibility_recorded_as_exact(findings):
    r = findings["reproducibility"]
    assert r["ways_recomputed"] == 100
    assert r["per_origin_rows"] == 10_000
    assert r["metric_mismatches"] == []
    assert r["all_rankings_match"] is True
    assert all(r["rankings_match_stored_summary"].values())


def test_cross_check_recorded_as_clean(findings):
    c = findings["cross_check"]
    assert c["ways_count"] >= 10
    assert c["origin_rows_checked"] >= 50
    for key in ("baseline_distance_mismatches", "disrupted_distance_mismatches",
                "facility_identity_mismatches", "disconnect_flag_mismatches",
                "switch_flag_mismatches"):
        assert c[key] == 0, key
    assert c["restore_verified"] is True
    assert "networkx" in c["engine"]


def test_sensitivity_records_instability(findings):
    s = findings["sensitivity"]
    # documented anchors from the validated run
    assert s["odd_even"]["by_composite_score"]["overlap"]["overlap"] == 4
    assert s["odd_even"]["by_affected_count"]["overlap"]["overlap"] == 2
    assert s["east_west"]["by_composite_score"]["overlap"]["overlap"] == 0
    assert s["east_west"]["by_affected_count"]["overlap"]["overlap"] == 0
    # each half actually contains ways with effect (not an empty-partition artifact)
    ew = s["east_west"]["by_affected_count"]
    assert ew["ways_with_effect_a"] > 0 and ew["ways_with_effect_b"] > 0


def test_facility_audit_is_bounded_and_non_clinical(findings):
    a = findings["facility_audit"]
    assert a["total_facilities"] == 453
    assert a["usable"] == 453          # all within the 300 m snap limit
    assert a["usable_snap_nodes"] == 419  # after snap-node dedupe
    assert 8 <= len(a["inspected"]) <= 10
    assert "emergency" in a["disclaimer"].lower()
    assert "verified" in a["disclaimer"].lower() or "No clinical" in a["disclaimer"]
    # no facility may be described as confirmed emergency care
    for f_ in a["inspected"]:
        assert "emergency care confirmed" not in (f_["name"] or "").lower()


def test_limitations_and_disclaimer_present(findings):
    assert len(findings["limitations"]) >= 5
    assert "flooding" in findings["disclaimer"].lower()
    assert len(findings["verified_findings"]) >= 5


# ------------------------------------- independent in-test reproducibility
@pytest.mark.parametrize("osmid", [26182600, 219168400, 221699173])
def test_results_row_recomputes_from_per_origin(osmid):
    """Three stored ways re-derive exactly from the 10,000 saved rows —
    no graph, no experiment, pure pandas + the documented metric formula."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from phase2_experiment import compute_metrics

    po = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_per_origin.csv")
    res = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    grp = po[po["candidate_osmid"] == osmid]
    assert len(grp) == 100
    rows = [{
        "detour_m": None if pd.isna(r.detour_m) else float(r.detour_m),
        "newly_disconnected": bool(r.newly_disconnected),
        "destination_switched": bool(r.destination_switched),
    } for r in grp.itertuples()]
    m = compute_metrics(rows)
    s = res[res["osmid"] == osmid].iloc[0]
    assert m["n_affected"] == s["n_affected"]
    assert abs(m["median_extra_m"] - s["median_extra_m"]) < 1e-6
    assert abs(m["max_extra_m"] - s["max_extra_m"]) < 1e-6
    assert abs(m["disruption_score"] - s["disruption_score"]) < 1e-6
    assert m["n_destination_switched"] == s["n_destination_switched"]


def test_composite_formula_documented_in_report():
    md = (PROJECT_ROOT / "reports" / "PHASE3_VALIDATION_REPORT.md").read_text()
    assert "n_affected + 5*n_disconnected" in md
    assert "not an AI score" in md
    assert "Research question" in md
    assert "Future research" in md


# ------------------------------------------------------------- API + panel
def test_research_api_serves_verified_payload(client, findings):
    r = client.get("/api/research")
    assert r.status_code == 200
    j = r.json()
    assert j["tag"] == "cityfragility-phase3"
    assert len(j["verified_findings"]) == len(findings["verified_findings"])
    assert any("26182600" in f for f in j["verified_findings"])
    vs = j["validation_summary"]
    assert vs["reproducibility"]["metric_mismatches"] == 0
    assert vs["cross_check"]["origin_rows_checked"] == findings["cross_check"]["origin_rows_checked"]
    assert j["sensitivity_summary"]["east_west"]["composite_overlap"]["overlap"] == 0
    assert j["facility_audit_summary"]["near_duplicate_pairs"] == len(
        findings["facility_audit"]["near_duplicate_pairs_50m"])
    assert "flooding" in j["disclaimer"].lower()
    # panel payload must stay small (no 95-pair dump, no per-way details)
    assert len(json.dumps(j)) < 20_000


def test_research_missing_file_404(client, monkeypatch):
    """Handler resolves the artifact path at call time — patching
    config.REPORTS_DIR makes the stored file unreachable (404 path)."""
    import config

    monkeypatch.setattr(config, "REPORTS_DIR", Path("/nonexistent-reports-dir"))
    r = client.get("/api/research")
    assert r.status_code == 404
    assert "phase3_findings" in r.json()["detail"]


def test_panel_wiring_present(client):
    html = client.get("/").text
    assert 'id="tab-findings"' in html
    assert 'id="view-findings"' in html
    assert "/findings.js" in html
    js = (STATIC / "findings.js").read_text()
    assert "/api/research" in js
    explorer = (STATIC / "explorer.js").read_text()
    assert 'tab-findings' in explorer  # tab managed by shared initTabs


@pytest.mark.skipif(not JSC.exists(), reason="jsc not available")
def test_findings_js_parses():
    proc = subprocess.run([str(JSC), str(STATIC / "findings.js")],
                          capture_output=True, text=True, timeout=30)
    out = proc.stdout + proc.stderr
    assert "SyntaxError" not in out


# ---------------------------------------------------- regressions preserved
def test_phase1_and_phase2_still_intact(client):
    r = client.post("/api/simulate?osmid=22744767")
    dha = next(o for o in r.json()["per_origin"] if o["name"] == "DHA Phase 5, Karachi")
    assert dha["delta_m"] == pytest.approx(442.27, abs=0.05)
    client.get("/api/restore")
    j = client.get("/api/vuln/summary").json()
    assert len(j["rows"]) == 100
    assert j["summary"]["rankings"]["by_composite_score"][0] == 26182600
