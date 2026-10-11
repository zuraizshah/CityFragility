"""Phase 5 — publication package tests.

Validates that the static public site's data files are EXACT copies of the
saved Phase 2/3 experiment outputs (no invented metrics, no fake geography),
that the public site never implies live simulation or a backend, that
attribution/limitation copy is present, that the git ignore rules exclude
large regenerable artifacts, and that presentation materials obey their own
constraints (e.g. Common App wording length).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC = PROJECT_ROOT / "public_site"
STATIC_LOCAL = PROJECT_ROOT / "webapp" / "static"
JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")


# ------------------------------------------------- data parity (no invention)
def test_results_rows_are_exact_phase2_rows():
    pub = json.loads((PUBLIC / "data" / "results.json").read_text())
    df = pd.read_csv(PROJECT_ROOT / "reports" / "phase2_results.csv")
    assert len(pub["rows"]) == len(df) == 100
    pub_by_id = {int(r["osmid"]): r for r in pub["rows"]}
    for _, row in df.iterrows():
        r = pub_by_id[int(row["osmid"])]
        assert abs(r["disruption_score"] - float(row["disruption_score"])) < 1e-9
        assert r["n_affected"] == int(row["n_affected"])
        assert abs((r["median_extra_m"] or 0) - (float(row["median_extra_m"]) or 0)) < 1e-6
        assert r["n_newly_disconnected"] == int(row["n_newly_disconnected"])


def test_results_summary_matches_stored_summary():
    pub = json.loads((PUBLIC / "data" / "results.json").read_text())["summary"]
    stored = json.loads((PROJECT_ROOT / "reports" / "phase2_summary.json").read_text())
    for key in ("n_origins", "n_candidates_completed", "seed",
                "restore_verified_identical", "peak_rss_mb", "composite_score_formula"):
        assert pub[key] == stored[key], key
    assert pub["runtime_s"]["total"] == stored["runtime_s"]["total"]


def test_findings_json_is_byte_identical_to_phase3_artifact():
    a = (PUBLIC / "data" / "findings.json").read_bytes()
    b = (PROJECT_ROOT / "reports" / "phase3_findings.json").read_bytes()
    assert a == b


def test_roads_geojson_is_copy_of_precomputed_layer():
    a = json.loads((PUBLIC / "data" / "roads.geojson").read_text())
    b = json.loads((PROJECT_ROOT / "data" / "phase2_roads.geojson").read_text())
    assert a == b
    assert len(a["features"]) == 100


def test_origins_match_sample_csv():
    pub = json.loads((PUBLIC / "data" / "origins.json").read_text())
    df = pd.read_csv(PROJECT_ROOT / "data" / "phase2_origins_sample.csv")
    assert len(pub) == len(df) == 100
    by_id = {o["id"]: o for o in pub}
    for _, row in df.sample(20, random_state=0).iterrows():
        o = by_id[row["sample_id"]]
        assert abs(o["lat"] - float(row["lat"])) < 1e-6
        assert abs(o["lon"] - float(row["lon"])) < 1e-6


def test_study_area_matches_server_meta_and_config():
    pub = json.loads((PUBLIC / "data" / "study_area.json").read_text())
    meta = json.loads((PROJECT_ROOT / "data" / "server_meta.json").read_text())
    assert pub["graph_nodes"] == meta["nodes"] == 45304
    assert pub["graph_edges"] == meta["edges"] == 122599
    assert pub["mapped_facilities"] == meta["hospitals_total"] == 453
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    import config

    assert pub["core_bbox_wgs84_wsen"] == list(config.CORE_BBOX)
    assert pub["buffer_bbox_wgs84_wsen"] == list(config.BUFFER_BBOX)


# --------------------------------------------- public site is truly static
def test_public_site_has_no_backend_or_live_simulation():
    html = (PUBLIC / "index.html").read_text()
    js = (PUBLIC / "assets" / "public.js").read_text()
    for text, name in ((html, "index.html"), (js, "public.js")):
        assert "/api/" not in text, f"{name} references a backend API"
        assert "networkx" not in text.lower()
        assert "graphml" not in text.lower()
    # uvicorn appears ONLY as local-app run instructions in the HTML
    assert "uvicorn" not in js.lower()
    assert "precomputed" in html.lower()
    assert "no live simulation" in html.lower()
    # it must still describe the local full app honestly
    assert "README.md" in html
    assert "127.0.0.1:8000" in html


def test_public_site_uses_only_relative_paths():
    html = (PUBLIC / "index.html").read_text()
    refs = re.findall(r'(?:href|src)="([^"]+)"', html)
    for r in refs:
        if r.startswith(("http://", "https://", "#")):
            continue
        assert not r.startswith("/"), f"absolute path breaks GitHub Pages: {r}"
        assert (PUBLIC / r).exists(), f"missing local asset: {r}"


def test_public_site_attribution_and_limitations_present():
    html = (PUBLIC / "index.html").read_text()
    assert "OpenStreetMap contributors" in html
    assert "ODbL" in html
    assert "not peer-reviewed" in html.lower() or "Not peer-reviewed" in html
    assert "flood" in html.lower()
    js = (PUBLIC / "assets" / "public.js").read_text()
    assert "Not population-weighted" in js or "not population" in js.lower()


def test_public_site_dom_ids_exist():
    html = (PUBLIC / "index.html").read_text()
    js = (PUBLIC / "assets" / "public.js").read_text()
    ids = set(re.findall(r'\$\("([^"]+)"\)', js))
    missing = {i for i in ids if f'id="{i}"' not in html}
    assert not missing, missing


@pytest.mark.skipif(not JSC.exists(), reason="jsc not available")
def test_public_js_parses():
    proc = subprocess.run(
        [str(JSC), str(PUBLIC / "assets" / "public.js")],
        capture_output=True, text=True, timeout=30,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "SyntaxError" not in out, out


def test_local_app_still_present_and_distinct():
    """Full simulator preserved as the separate local app."""
    assert (STATIC_LOCAL / "app.js").exists()
    assert (PROJECT_ROOT / "webapp" / "server.py").exists()
    local_html = (STATIC_LOCAL / "index.html").read_text()
    assert "/api/simulate" in local_html or "Simulate Closure" in local_html


# ------------------------------------------------------ git & documentation
def test_gitignore_excludes_large_regenerable_artifacts():
    checks = [
        "data/source/pakistan-latest.osm.pbf",
        "data/network_drive.graphml",
        "env/conda/bin/python",
        "reports/server.log",
        "reports/pytest_phase2.txt",
        ".DS_Store",
    ]
    for path in checks:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=str(PROJECT_ROOT), capture_output=True,
        )
        assert proc.returncode == 0, f"gitignore must exclude {path}"


def test_required_research_docs_exist_and_cover_topics():
    docs = ["README.md", "RESEARCH_PAPER.md", "METHODOLOGY.md", "LIMITATIONS.md",
            "REPRODUCIBILITY.md", "DATA_SOURCES.md", "DEMO_GUIDE.md",
            "CONTRIBUTIONS.md", "PRESENTATION.md"]
    for d in docs:
        p = PROJECT_ROOT / d
        assert p.exists() and p.stat().st_size > 400, d
    paper = (PROJECT_ROOT / "RESEARCH_PAPER.md").read_text().lower()
    for phrase in (
        "research question", "why healthcare accessibility", "study-area",
        "100 sampled origins", "candidate selection and bias", "10,000",
        "measured findings", "cross-check", "east/west", "unverified",
        "conclusions directly supported", "future research",
        "not peer-reviewed",
    ):
        assert phrase in paper, f"RESEARCH_PAPER.md missing topic: {phrase}"


def test_common_app_wording_under_150_chars():
    text = (PROJECT_ROOT / "PRESENTATION.md").read_text()
    m = re.search(r"^> (Built CityFragility:.+)$", text, re.M)
    assert m, "Common App wording not found"
    wording = m.group(1)
    assert len(wording) <= 150, f"too long: {len(wording)} chars"
    assert "lives" not in wording.lower() and "ambulance" not in wording.lower()


def test_no_forbidden_claims_in_public_site():
    html = (PUBLIC / "index.html").read_text().lower()
    js = (PUBLIC / "assets" / "public.js").read_text().lower()
    blob = html + js
    # positive-claim phrasings that would violate the non-claims policy
    # (legitimate *non-claim* sentences may contain words like "ambulance")
    for banned in ("lives saved", "saves lives", "we save",
                   "peer-reviewed study shows", "guaranteed",
                   "actually predicts floods", "confirmed emergency"):
        assert banned not in blob, banned
