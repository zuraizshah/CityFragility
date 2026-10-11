"""Phase 4 — one-time precompute for the lightweight research viewer.

Builds compact, saved artifacts from the REAL graph + stored experiment
outputs so the server can serve the Vulnerability Explorer and Findings
tabs WITHOUT loading the 1.7 GB NetworkX graph. Live simulation (Phase 1)
still lazy-loads the graph on first use — nothing is recomputed or altered.

Outputs (all derived from existing verified functions in webapp/server.py,
so payloads are identical to what the live endpoints returned):
  data/phase1_candidates.json      <- build_candidates()
  data/phase2_roads.geojson        <- vuln_roads_geojson()
  reports/phase2_vuln_details.json <- {osmid: vuln_detail(osmid)} x100
  data/server_meta.json            <- graph counts + facility counts for
                                      /api/health before the graph loads

CLI: python src/phase4_precompute.py
Runtime: ~6 s graph load + ~25 s for 100 worst-origin examples.
"""
from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

import config
import server


def log(msg: str) -> None:
    print(f"[phase4] {msg}", flush=True)


def main() -> int:
    t0 = time.time()
    log("loading graph (single copy, reused for all precomputes)...")
    G = server.ensure_loaded()
    log(f"graph ready: {G.number_of_nodes()} nodes / {G.number_of_edges()} edges")

    # 1) Phase 1 candidates (simulator dropdown) ----------------------------
    cands = server.build_candidates()
    cand_path = config.DATA_DIR / "phase1_candidates.json"
    cand_path.write_text(json.dumps(cands, indent=1, default=str), encoding="utf-8")
    log(f"wrote {cand_path} ({len(cands)} candidates)")

    # 2) Candidate road geometries + metrics (Explorer map layer) -----------
    roads = server.vuln_roads_geojson()
    roads_path = config.DATA_DIR / "phase2_roads.geojson"
    roads_path.write_text(json.dumps(roads), encoding="utf-8")
    log(f"wrote {roads_path} ({len(roads['features'])} features, "
        f"{roads_path.stat().st_size // 1024} KB)")

    # 3) Per-way detail payloads incl. worst-origin example geometry --------
    details: dict[str, dict] = {}
    for r in server.vuln_rows():
        oid = int(r["osmid"])
        details[str(oid)] = server.vuln_detail(oid)
        if len(details) % 20 == 0:
            log(f"  details {len(details)}/100 "
                f"({time.time()-t0:.0f}s elapsed)")
    det_path = config.REPORTS_DIR / "phase2_vuln_details.json"
    det_path.write_text(json.dumps(details, default=str), encoding="utf-8")
    log(f"wrote {det_path} ({len(details)} ways, "
        f"{det_path.stat().st_size // 1024} KB)")

    # 4) Server metadata for graph-free /api/health -------------------------
    meta = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "candidates": len(cands),
        "hospitals_usable_nodes": len(server._HOSPITALS["nodes"]),
        "hospitals_total": len(server._HOSPITALS["records"]),
        "graph_load_s_reference": round(server._STARTUP_S, 2),
        "precomputed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": {
            "candidates": cand_path.name,
            "roads": roads_path.name,
            "details": det_path.name,
        },
        "note": (
            "Static counts for /api/health before the graph is lazy-loaded. "
            "Matches the real graph; refreshed by src/phase4_precompute.py."
        ),
    }
    meta_path = config.DATA_DIR / "server_meta.json"
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"wrote {meta_path}")

    # verify detail file round-trips through the endpoint's own loader
    reloaded = json.loads(det_path.read_text())
    assert set(reloaded) == set(details)
    log(f"done in {time.time()-t0:.1f}s, peak RSS "
        f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024):.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
