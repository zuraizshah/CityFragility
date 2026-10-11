"""Phase 2 Part B — bounded, documented closure-candidate selection.

Selection tiers (capped at MAX_TOTAL ways, deterministic with SEED):
1. phase0_tested       — the 8 ways evaluated in Phase 0 (closure_results.json)
2. phase1_origin_path  — ways on the original six origins' baseline paths
                         (same logic Phase 1 used; fills toward the Phase 1
                         20-way set, way length capped at 4 km)
3. sample_path_frequency — ways most frequently used by the 100 Phase 2
                         sample origins' baseline shortest paths (a
                         transparent "bottleneck-ish" proxy — NOT betweenness
                         centrality, NOT traffic volume)
4. stratified_fill     — seeded sample across highway classes x latitude
                         bands for geographic / road-type coverage

Documented biases (also written into the JSON report): OSM completeness;
driving-road filter (no service roads); full-way closure assumption;
grid-uniform origins (not population); tier-3 favors central corridors;
ways longer than MAX_WAY_M are excluded.

Outputs:
- data/phase2_candidates.csv
- reports/phase2_candidate_selection_report.json
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
from analyze import way_summary

SEED = 20261010
MAX_TOTAL = 100
MAX_WAY_M = 6000.0
TIER2_CAP = 12
TIER3_CAP = 50


def load_graph():
    import osmnx as ox

    return ox.load_graphml(config.NETWORK_PATH)


def baseline_nearest(G, hosp_nodes: set[int], origin_node: int):
    try:
        lengths, _ = nx.single_source_dijkstra(G, origin_node, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, None
    best, best_d = None, float("inf")
    for h in hosp_nodes:
        d = lengths.get(h)
        if d is not None and d < best_d:
            best, best_d = h, d
    return best, best_d


def path_way_ids(G, origin_node: int, target_node: int) -> list[int]:
    path = nx.dijkstra_path(G, origin_node, target_node, weight="length")
    ids = []
    for a, b in zip(path[:-1], path[1:]):
        edata = G.get_edge_data(a, b)
        best = min(edata.values(), key=lambda d: d["length"])
        v = best.get("osmid")
        if isinstance(v, str):
            parts = v.split()
            v = int(parts[0]) if parts else None
        if isinstance(v, (int, float)):
            ids.append(int(v))
    return ids


def way_midpoint(G, osmid: int):
    xs, ys = [], []
    for u, v, d in G.edges(data=True):
        if d.get("osmid") == osmid:
            xs += [G.nodes[u]["x"], G.nodes[v]["x"]]
            ys += [G.nodes[u]["y"], G.nodes[v]["y"]]
    if not xs:
        return None, None
    return round(sum(ys) / len(ys), 6), round(sum(xs) / len(xs), 6)


def usable_hospital_nodes(G) -> set[int]:
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


def main() -> int:
    t0 = time.time()
    G = load_graph()
    hosp = usable_hospital_nodes(G)
    selected: dict[int, dict] = {}

    def add(osmid: int, tier: str, extra: dict | None = None):
        if osmid in selected or len(selected) >= MAX_TOTAL:
            return False
        s = way_summary(G, osmid)
        if s["edges"] == 0 or s["length_m"] == 0 or s["length_m"] > MAX_WAY_M:
            return False
        mid_lat, mid_lon = way_midpoint(G, osmid)
        selected[osmid] = {
            **s,
            "mid_lat": mid_lat,
            "mid_lon": mid_lon,
            "selection_tier": tier,
            **(extra or {}),
        }
        return True

    # ---- tier 1: Phase 0 tested ---------------------------------------
    if config.CLOSURE_RESULTS.exists():
        payload = json.loads(config.CLOSURE_RESULTS.read_text())
        for c in payload.get("candidates_evaluated", []):
            add(int(c["osmid"]), "phase0_tested",
                {"phase0_total_delta_m": c.get("total_delta_m"),
                 "phase0_any_disconnected": c.get("any_disconnected_origin")})

    # ---- tier 2: six original origins' baseline paths ------------------
    origins6 = pd.read_csv(config.ORIGINS_SNAPPED_PATH)
    for _, o in origins6.iterrows():
        node = int(o["snapped_node"])
        h, _ = baseline_nearest(G, hosp, node)
        if h is None:
            continue
        for w in path_way_ids(G, node, h):
            if len([c for c in selected.values()
                    if c["selection_tier"] == "phase1_origin_path"]) >= TIER2_CAP:
                break
            add(w, "phase1_origin_path", {"origin6_path": o["name"]})

    # ---- tier 3: sample-origin path frequency --------------------------
    sample = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    freq: dict[int, int] = {}
    for _, o in sample.iterrows():
        node = int(o["node_id"])
        h, _ = baseline_nearest(G, hosp, node)
        if h is None:
            continue
        for w in set(path_way_ids(G, node, h)):
            freq[w] = freq.get(w, 0) + 1
    for w, count in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        if len([c for c in selected.values()
                if c["selection_tier"] == "sample_path_frequency"]) >= TIER3_CAP:
            break
        add(w, "sample_path_frequency", {"sample_path_origin_count": count})

    # ---- tier 4: stratified geographic / type fill ---------------------
    rng = random.Random(SEED)
    w, s, e, n = config.CORE_BBOX
    pool: dict[tuple[str, int], list[int]] = {}
    for u, v, d in G.edges(data=True):
        hw = d.get("highway")
        if isinstance(hw, (list, tuple)):
            hw = hw[0] if hw else None
        if hw not in {"motorway", "trunk", "primary", "secondary", "tertiary"}:
            continue
        osmid = d.get("osmid")
        if isinstance(osmid, (list, tuple, set)):
            osmid = next(iter(osmid))
        if osmid is None:
            continue
        mid_lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        if not (s <= mid_lat <= n):
            continue
        band = min(2, int((mid_lat - s) / (n - s) * 3))
        pool.setdefault((hw, band), set()).add(int(osmid))
    for key in sorted(pool.keys()):
        cands = sorted(pool[key])
        rng.shuffle(cands)
        for osmid in cands:
            if len(selected) >= MAX_TOTAL:
                break
            add(osmid, "stratified_fill")
        if len(selected) >= MAX_TOTAL:
            break

    df = pd.DataFrame(selected.values())
    out_csv = config.DATA_DIR / "phase2_candidates.csv"
    df.to_csv(out_csv, index=False)

    tier_counts = df["selection_tier"].value_counts().to_dict()
    report = {
        "retrieval_date": config.today(),
        "seed": SEED,
        "max_total": MAX_TOTAL,
        "max_way_length_m": MAX_WAY_M,
        "selected": len(df),
        "tier_counts": tier_counts,
        "method": (
            "Four deterministic tiers: (1) Phase 0 tested ways; (2) ways on "
            "the six original origins' baseline paths (<=4 km, capped "
            f"{TIER2_CAP}); (3) top-{TIER3_CAP} ways by how many of the 100 "
            "sample origins' baseline shortest paths traverse them; (4) "
            f"seeded stratified fill across highway class x latitude band "
            f"(seed {SEED}) up to {MAX_TOTAL} total."
        ),
        "biases": [
            "OSM completeness and mapper bias in central Karachi only.",
            "Driving-road filter: service roads excluded from candidates.",
            "A candidate is a full OSM way closure, not a single physical segment.",
            "Origins are grid-uniform geographic points, not population demand.",
            "Tier 3 favors ways on central corridors (path-frequency bias).",
            "Ways longer than the length cap are excluded.",
            "Rankings from these candidates are NOT a citywide criticality assessment.",
        ],
        "elapsed_s": round(time.time() - t0, 2),
        "output_csv": str(out_csv.relative_to(config.PROJECT_ROOT)),
    }
    rep_path = config.REPORTS_DIR / "phase2_candidate_selection_report.json"
    rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[candidates] {len(df)} ways -> {out_csv}")
    print(f"[candidates] tiers: {tier_counts}")
    print(f"[candidates] report -> {rep_path} ({report['elapsed_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
