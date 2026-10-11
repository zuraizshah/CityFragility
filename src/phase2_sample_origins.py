"""Phase 2 Part A — reproducible grid-stratified origin sampling.

Method (documented, deterministic):
- Study area = existing CORE bbox (config.CORE_BBOX), divided into a
  GRID_ROWS x GRID_COLS spatial grid.
- Candidate pool per cell: graph nodes whose midpoint lies in the cell,
  with degree >= 1 (drivable junction/segment endpoint).
- Reachability filter: nodes with no path to any usable mapped facility at
  baseline are excluded ("unreachable_facility") and counted as exclusions.
- Selection: seeded RNG (SEED) shuffles each cell's candidate list; take up
  to PER_CELL nodes per cell (fill order is row-major, cell candidates
  sorted by node id before shuffling so the shuffle is reproducible).
- The original six Phase 0/1 origins are NOT part of this sample; they stay
  as regression examples (data/origins_snapped.csv untouched).

Outputs:
- data/phase2_origins_sample.csv  (node_id, lat, lon, grid_row, grid_col, ...)
- reports/phase2_origin_sampling_report.json (method, seed, counts,
  exclusions, coverage diagnostics)
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import networkx as nx
import pandas as pd
from routing import distances_to_targets

SEED = 20261010
GRID_ROWS = 5
GRID_COLS = 5
PER_CELL = 4  # 5 x 5 x 4 = 100 target sample size


def load_graph():
    import osmnx as ox

    if not config.NETWORK_PATH.exists():
        raise FileNotFoundError(f"network missing: {config.NETWORK_PATH}")
    return ox.load_graphml(config.NETWORK_PATH)


def usable_hospital_nodes(G) -> set[int]:
    """Same snapping contract as Phase 0/1 (UTM KDTree, <= 300 m)."""
    import geopandas as gpd
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
    tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
    node_ids = list(G.nodes())
    coords = [tr.transform(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids]
    tree = cKDTree(coords)
    nodes: set[int] = set()
    for _, r in hospitals.iterrows():
        pt = r.geometry.representative_point()
        hx, hy = tr.transform(pt.x, pt.y)
        dist, idx = tree.query([hx, hy])
        if float(dist) <= config.MAX_HOSPITAL_SNAP_M:
            nodes.add(int(node_ids[idx]))
    return nodes


def cell_of(lon: float, lat: float, w, s, e, n, rows, cols):
    col = min(cols - 1, max(0, int((lon - w) / (e - w) * cols)))
    row = min(rows - 1, max(0, int((lat - s) / (n - s) * rows)))
    return row, col


def main() -> int:
    t0 = time.time()
    G = load_graph()
    w, s, e, n = config.CORE_BBOX

    hosp_nodes = usable_hospital_nodes(G)
    print(f"[sample] graph {G.number_of_nodes()} nodes; "
          f"{len(hosp_nodes)} usable facility snap nodes")
    dist_base = distances_to_targets(G, hosp_nodes)
    print(f"[sample] baseline reachability computed in {time.time()-t0:.1f}s")

    # ---- build per-cell candidate pools ------------------------------
    pools: dict[tuple[int, int], list[int]] = {}
    excl = {"outside_core": 0, "degree_zero": 0, "unreachable_facility": 0}
    for node in G.nodes():
        lon, lat = G.nodes[node]["x"], G.nodes[node]["y"]
        if not (w <= lon <= e and s <= lat <= n):
            excl["outside_core"] += 1
            continue
        if G.degree(node) == 0:
            excl["degree_zero"] += 1
            continue
        if node not in dist_base:
            excl["unreachable_facility"] += 1
            continue
        row, col = cell_of(lon, lat, w, s, e, n, GRID_ROWS, GRID_COLS)
        pools.setdefault((row, col), []).append(int(node))

    # ---- seeded selection --------------------------------------------
    rng = random.Random(SEED)
    sample: list[dict] = []
    per_cell_counts: dict[str, int] = {}
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cands = sorted(pools.get((row, col), []))
            per_cell_counts[f"r{row}c{col}"] = len(cands)
            rng.shuffle(cands)
            for k, node in enumerate(cands[:PER_CELL]):
                lon, lat = G.nodes[node]["x"], G.nodes[node]["y"]
                sample.append(
                    {
                        "sample_id": f"grid-r{row}c{col}-{k}",
                        "node_id": node,
                        "lat": round(float(lat), 7),
                        "lon": round(float(lon), 7),
                        "grid_row": row,
                        "grid_col": col,
                        "cell_index": row * GRID_COLS + col,
                        "baseline_dist_m": round(float(dist_base[node]), 2),
                    }
                )

    df = pd.DataFrame(sample)
    out_csv = config.DATA_DIR / "phase2_origins_sample.csv"
    df.to_csv(out_csv, index=False)

    lats, lons = df["lat"], df["lon"]
    report = {
        "retrieval_date": config.today(),
        "method": (
            "Grid-stratified sampling: CORE bbox divided into "
            f"{GRID_ROWS}x{GRID_COLS} cells; per cell, drivable degree>=1 "
            f"graph nodes with a baseline path to a mapped facility are "
            f"shuffled with seed {SEED} and the first {PER_CELL} are kept."
        ),
        "seed": SEED,
        "grid_rows": GRID_ROWS,
        "grid_cols": GRID_COLS,
        "per_cell_target": PER_CELL,
        "sample_size": len(df),
        "core_bbox_wgs84_wsen": list(config.CORE_BBOX),
        "exclusions": excl,
        "per_cell_candidate_counts": per_cell_counts,
        "cells_with_sample": int((df.groupby(["grid_row", "grid_col"]).size() > 0).sum()),
        "coverage_diagnostics": {
            "lat_min": round(float(lats.min()), 6),
            "lat_max": round(float(lats.max()), 6),
            "lon_min": round(float(lons.min()), 6),
            "lon_max": round(float(lons.max()), 6),
            "baseline_dist_min_m": round(float(df["baseline_dist_m"].min()), 1),
            "baseline_dist_median_m": round(float(df["baseline_dist_m"].median()), 1),
            "baseline_dist_max_m": round(float(df["baseline_dist_m"].max()), 1),
        },
        "regression_note": (
            "The original six Phase 0/1 origins (data/origins_snapped.csv) are "
            "preserved separately and are NOT part of this sample."
        ),
        "interpretation_note": (
            "These are geographic sampling points on the road network, NOT "
            "population-weighted demand points and NOT actual patient locations."
        ),
        "elapsed_s": round(time.time() - t0, 2),
        "output_csv": str(out_csv.relative_to(config.PROJECT_ROOT)),
    }
    rep_path = config.REPORTS_DIR / "phase2_origin_sampling_report.json"
    rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[sample] {len(df)} origins -> {out_csv}")
    print(f"[sample] exclusions: {excl}")
    print(f"[sample] report -> {rep_path} ({report['elapsed_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
