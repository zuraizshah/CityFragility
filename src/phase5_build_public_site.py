"""Phase 5 — build the static public research site (public_site/).

Copies DERIVED, SAVED Phase 2/3 outputs into a folder that works on any
static host (GitHub Pages, python -m http.server). No NetworkX graph, no
Python server, no live simulation — the site reads JSON files only.

Everything is copied or derived from stored artifacts; nothing is
recomputed or invented. Re-run after Phase 2/3 artifacts change:

    env/conda/bin/python src/phase5_build_public_site.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webapp"))
sys.path.insert(0, str(ROOT / "src"))

import config
import server  # imported for the SAME verified readers the local app uses

OUT = ROOT / "public_site"
DATA_OUT = OUT / "data"


def log(msg: str) -> None:
    print(f"[phase5] {msg}", flush=True)


def main() -> int:
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    # 1) Vulnerability experiment: summary + 100 way rows + sampling +
    #    candidate-method provenance (identical payload to /api/vuln/summary,
    #    built by the same server functions — no graph needed).
    rep_s = config.REPORTS_DIR / "phase2_origin_sampling_report.json"
    rep_c = config.REPORTS_DIR / "phase2_candidate_selection_report.json"
    payload = {
        "summary": server.vuln_summary(),
        "rows": server.vuln_rows(),
        "sampling": json.loads(rep_s.read_text()),
        "candidates_method": json.loads(rep_c.read_text()),
    }
    p = DATA_OUT / "results.json"
    p.write_text(json.dumps(payload, default=str), encoding="utf-8")
    log(f"results.json {p.stat().st_size // 1024} KB ({len(payload['rows'])} ways)")

    # 2) Candidate road geometries (precomputed, 100 features)
    src = config.DATA_DIR / "phase2_roads.geojson"
    shutil.copyfile(src, DATA_OUT / "roads.geojson")
    log(f"roads.geojson {src.stat().st_size // 1024} KB")

    # 3) Phase 3 validation findings
    src = config.REPORTS_DIR / "phase3_findings.json"
    shutil.copyfile(src, DATA_OUT / "findings.json")
    log(f"findings.json {src.stat().st_size // 1024} KB")

    # 4) The 100 sampled origins (real grid sample, compact columns)
    import pandas as pd

    og = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    origins = [
        {
            "id": r["sample_id"],
            "lat": round(float(r["lat"]), 6),
            "lon": round(float(r["lon"]), 6),
            "baseline_m": float(r["baseline_dist_m"]),
        }
        for _, r in og.iterrows()
    ]
    p = DATA_OUT / "origins.json"
    p.write_text(json.dumps(origins), encoding="utf-8")
    log(f"origins.json {len(origins)} origins")

    # 5) Study-area + provenance card
    meta = json.loads((config.DATA_DIR / "server_meta.json").read_text())
    summary = server.vuln_summary()
    study = {
        "core_bbox_wgs84_wsen": list(config.CORE_BBOX),
        "buffer_bbox_wgs84_wsen": list(config.BUFFER_BBOX),
        "graph_nodes": meta["nodes"],
        "graph_edges": meta["edges"],
        "mapped_facilities": meta["hospitals_total"],
        "retrieval_date": summary.get("retrieval_date"),
        "snapshot": "Geofabrik pakistan-latest.osm.pbf (2026-10-09 snapshot)",
        "licence": (
            "Road network and facility data © OpenStreetMap contributors, "
            "available under the Open Database Licence (ODbL), via Geofabrik."
        ),
        "analysis_crs": config.ANALYSIS_CRS,
        "mode": "precomputed research scenarios — static site, no live simulation",
        "disclaimer": summary.get("disclaimer"),
    }
    p = DATA_OUT / "study_area.json"
    p.write_text(json.dumps(study, indent=1), encoding="utf-8")
    log(f"study_area.json")

    total = sum(f.stat().st_size for f in DATA_OUT.iterdir())
    log(f"total data payload: {total // 1024} KB — build complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
