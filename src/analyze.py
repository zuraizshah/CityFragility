"""Baseline nearest-hospital routing + one real road-closure simulation.

Outputs:
  data/origins_snapped.csv     - origin seeds snapped to real OSM nodes
  reports/baseline_results.csv - baseline drivable distances
  reports/route_inspection.csv - snapping / boundary / detour artifact flags
  reports/closure_results.json - closure simulation + restore verification
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import routing
from routing import INF, dist_of, distances_to_targets, graph_counts, is_disconnected

ARTERIAL_HIGHWAYS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}


def utm_transformer():
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)


def node_lonlat(G, n):
    return G.nodes[n]["x"], G.nodes[n]["y"]


def load_all():
    import osmnx as ox
    import geopandas as gpd
    import pandas as pd

    config.configure_osmnx()
    t0 = time.time()
    G = ox.load_graphml(config.NETWORK_PATH)
    load_s = time.time() - t0
    hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
    origins = pd.read_csv(config.ORIGINS_REF_PATH)
    return G, hospitals, origins, load_s


def candidate_ways(G, limit=6):
    """Named arterial ways fully inside the CORE window, 300-3000 m long."""
    w, s, e, n = config.CORE_BBOX
    agg = {}
    for u, v, k, data in G.edges(keys=True, data=True):
        xu, yu = node_lonlat(G, u)
        xv, yv = node_lonlat(G, v)
        if not (w <= xu <= e and s <= yu <= n and w <= xv <= e and s <= yv <= n):
            continue
        name = data.get("name")
        hw = data.get("highway")
        if not isinstance(name, str) or not name:
            continue
        if isinstance(hw, (list, tuple)):
            hw = hw[0] if hw else None
        if hw not in ARTERIAL_HIGHWAYS:
            continue
        osmid = data.get("osmid")
        if isinstance(osmid, (list, tuple, set)):
            continue  # keep closure candidates to single-way segments
        entry = agg.setdefault(
            osmid, {"osmid": osmid, "name": name, "highways": set(),
                    "length_m": 0.0, "edges": 0}
        )
        entry["highways"].add(hw)
        entry["length_m"] += float(data.get("length", 0.0))
        entry["edges"] += 1
    cands = [c for c in agg.values() if 300.0 <= c["length_m"] <= 3000.0]
    cands.sort(key=lambda c: (-c["length_m"], c["osmid"]))
    for c in cands:
        c["highways"] = sorted(c["highways"])
    return cands[:limit]


def nearest_hospital(G, origin_node, hospital_nodes):
    """Single-source Dijkstra: nearest usable hospital for one origin."""
    dist_all = nx.single_source_dijkstra_path_length(G, origin_node, weight="length")
    best_h, best_d = None, INF
    for h in hospital_nodes:
        d = dist_all.get(h, INF)
        if d < best_d:
            best_h, best_d = h, d
    return best_h, best_d, dist_all


def path_stats(G, origin_node, hospital_node, hospital_xy_utm, transformer):
    """Route + snapping/boundary/detour inspection for one origin."""
    path = nx.dijkstra_path(G, origin_node, hospital_node, weight="length")
    length = 0.0
    way_ids: list[int] = []
    for a, b in zip(path[:-1], path[1:]):
        # MultiDiGraph: pick the shortest parallel edge between a and b
        edata = G.get_edge_data(a, b)
        best = min(edata.values(), key=lambda d: d["length"])
        length += float(best["length"])
        v = best.get("osmid")
        if isinstance(v, str):
            parts = v.split()
            v = int(parts[0]) if parts else None
        if isinstance(v, (int, float)):
            way_ids.append(int(v))
    w, s, e, n = config.CORE_BBOX
    bw, bs, be, bn = config.BUFFER_BBOX
    outside_core = 0
    near_buffer_edge = 0
    for node in path:
        x, y = node_lonlat(G, node)
        if not (w <= x <= e and s <= y <= n):
            outside_core += 1
        if (
            abs(x - bw) < 0.001 or abs(x - be) < 0.001
            or abs(y - bs) < 0.001 or abs(y - bn) < 0.001
        ):
            near_buffer_edge += 1
    ox_, oy_ = transformer.transform(*node_lonlat(G, origin_node))
    straight = math.hypot(ox_ - hospital_xy_utm[0], oy_ - hospital_xy_utm[1])
    detour = (length / straight) if straight > 0 else float("nan")
    return {
        "path_nodes": len(path),
        "path_length_m": round(length, 2),
        "nodes_outside_core": outside_core,
        "nodes_near_buffer_edge": near_buffer_edge,
        "straight_line_m": round(straight, 2),
        "detour_ratio": round(detour, 3),
        "way_ids": way_ids,
    }


def way_summary(G, osmid: int) -> dict:
    """Name/length/edge-count of one OSM way (all its directed edges)."""
    name = None
    highways: set[str] = set()
    length = 0.0
    edges = 0
    for _, _, _, d in G.edges(keys=True, data=True):
        if d.get("osmid") != osmid:
            continue
        edges += 1
        nm = d.get("name")
        if name is None and isinstance(nm, str):
            name = nm
        hw = d.get("highway")
        if isinstance(hw, (list, tuple)):
            hw = hw[0] if hw else None
        if isinstance(hw, str):
            highways.add(hw)
        length += float(d.get("length") or 0.0)
    return {
        "osmid": int(osmid),
        "name": name,
        "highways": sorted(highways),
        "length_m": round(length, 1),
        "edges": edges,
    }


def main() -> int:
    t_start = time.time()
    config.configure_osmnx()
    import osmnx as ox

    G, hospitals, origins_ref, load_s = load_all()
    counts_before = graph_counts(G)
    print(f"[analyze] loaded network in {load_s:.2f}s: "
          f"{counts_before[0]} nodes / {counts_before[1]} edges")

    G_proj = ox.projection.project_graph(G, to_crs=config.ANALYSIS_CRS)
    transformer = utm_transformer()

    # ---------------- origins: seed -> real network node ----------------
    import pandas as pd

    import osmnx.distance as oxd

    o_nodes, o_dists = oxd.nearest_nodes(
        G_proj, X=[transformer.transform(r["ref_lon"], r["ref_lat"])[0]
                   for _, r in origins_ref.iterrows()],
        Y=[transformer.transform(r["ref_lon"], r["ref_lat"])[1]
           for _, r in origins_ref.iterrows()],
        return_dist=True,
    )
    origin_rows = []
    for (_, r), node, dist in zip(origins_ref.iterrows(), o_nodes, o_dists):
        origin_rows.append(
            {
                "name": r["name"],
                "ref_lat": r["ref_lat"],
                "ref_lon": r["ref_lon"],
                "origin_source": r["source"],
                "snapped_node": int(node),
                "snapped_lat": G.nodes[node]["y"],
                "snapped_lon": G.nodes[node]["x"],
                "snap_dist_m": round(float(dist), 2),
                "snap_flag": bool(float(dist) > config.ORIGIN_SNAP_FLAG_M),
            }
        )
    origins = pd.DataFrame(origin_rows)
    origins.to_csv(config.ORIGINS_SNAPPED_PATH, index=False)
    print(f"[analyze] snapped {len(origins)} origins; "
          f"max snap dist {origins['snap_dist_m'].max():.1f} m")

    # ---------------- hospitals: usable destinations ----------------
    h_lons, h_lats = [], []
    for _, r in hospitals.iterrows():
        pt = r.geometry.representative_point()
        x, y = transformer.transform(pt.x, pt.y)
        h_lons.append(x)
        h_lats.append(y)
    h_nodes, h_dists = oxd.nearest_nodes(G_proj, X=h_lons, Y=h_lats, return_dist=True)

    hosp_rows = []
    for (_, r), node, dist in zip(hospitals.iterrows(), h_nodes, h_dists):
        usable = float(dist) <= config.MAX_HOSPITAL_SNAP_M
        hosp_rows.append(
            {
                "element_type": r["element_type"],
                "osmid": int(r["osmid"]),
                "name": r.get("name"),
                "snap_node": int(node),
                "snap_dist_m": round(float(dist), 2),
                "usable": bool(usable),
            }
        )
    hosp_df = pd.DataFrame(hosp_rows)
    usable_hosp = hosp_df[hosp_df["usable"]]
    n_usable = len(usable_hosp)
    n_unique_nodes = usable_hosp["snap_node"].nunique()
    print(f"[analyze] hospitals: {len(hosp_df)} mapped, {n_usable} usable "
          f"(snap <= {config.MAX_HOSPITAL_SNAP_M:.0f} m), "
          f"{n_unique_nodes} unique snap nodes")
    if n_usable < 2:
        print("[analyze] NO-GO: fewer than 2 usable destinations - "
              "recommend a different study area")
        return 2

    hospital_nodes = set(int(n) for n in usable_hosp["snap_node"])
    hosp_lookup = {
        int(r["snap_node"]): r for _, r in usable_hosp.iterrows()
    }

    # ---------------- baseline ----------------
    t0 = time.time()
    D_base = distances_to_targets(G, hospital_nodes)
    base_s = time.time() - t0
    print(f"[analyze] baseline multi-source Dijkstra: {base_s*1000:.0f} ms")

    baseline_rows = []
    inspection_rows = []
    path_ways: dict[str, list[int]] = {}  # origin name -> osmids on its path
    for _, o in origins.iterrows():
        node = int(o["snapped_node"])
        h_node, d, _ = nearest_hospital(G, node, hospital_nodes)
        assert h_node is not None and not is_disconnected(d), \
            f"origin {o['name']} has no reachable hospital"
        # consistency: single-source min == multi-source distance
        assert abs(d - dist_of(D_base, node)) < 1e-6, "single/multi-source mismatch"
        h_row = hosp_lookup[h_node]
        h_name = h_row["name"] if isinstance(h_row["name"], str) else "(unnamed)"
        hospital_geom = hospitals[
            (hospitals["element_type"] == h_row["element_type"])
            & (hospitals["osmid"] == h_row["osmid"])
        ].iloc[0]
        h_pt = hospital_geom.geometry.representative_point()
        h_xy = transformer.transform(h_pt.x, h_pt.y)

        stats = path_stats(G, node, h_node, h_xy, transformer)
        path_ways[o["name"]] = stats["way_ids"]
        baseline_rows.append(
            {
                "origin": o["name"],
                "origin_node": node,
                "nearest_hospital": h_name,
                "hospital_osmid": int(h_row["osmid"]),
                "distance_m": round(d, 2),
                "distance_km": round(d / 1000.0, 3),
            }
        )
        inspection_rows.append(
            {
                "origin": o["name"],
                "origin_snap_dist_m": o["snap_dist_m"],
                "origin_snap_flag": o["snap_flag"],
                "hospital_snap_dist_m": h_row["snap_dist_m"],
                "detour_ratio": stats["detour_ratio"],
                "detour_flag": stats["detour_ratio"] > config.DETOUR_RATIO_FLAG,
                "nodes_outside_core": stats["nodes_outside_core"],
                "nodes_near_buffer_edge": stats["nodes_near_buffer_edge"],
                "boundary_flag": stats["nodes_near_buffer_edge"] > 0,
                "path_nodes": stats["path_nodes"],
                "path_length_m": stats["path_length_m"],
            }
        )
    baseline_df = pd.DataFrame(baseline_rows)
    baseline_df.to_csv(config.BASELINE_RESULTS, index=False)
    pd.DataFrame(inspection_rows).to_csv(config.ROUTE_INSPECTION, index=False)
    print("[analyze] baseline distances (m):")
    for _, r in baseline_df.iterrows():
        print(f"  {r['origin']:28s} -> {r['nearest_hospital'][:40]:40s} "
              f"{r['distance_m']:9.1f} m")

    # ---------------- closure candidates ----------------
    # 1) ways actually used by baseline shortest paths (route-affecting)
    path_meta: dict[int, list[str]] = {}
    for origin_name, wids in path_ways.items():
        for w in dict.fromkeys(wids):
            path_meta.setdefault(w, []).append(origin_name)
    path_cands = []
    for w, served in path_meta.items():
        s = way_summary(G, w)
        if s["edges"] == 0 or s["length_m"] > 4000:
            continue
        s["on_baseline_path_of"] = served
        path_cands.append(s)
    path_cands.sort(key=lambda c: (-len(c["on_baseline_path_of"]), -c["length_m"]))
    # 2) CORE arterial fill-ins (may not sit on any baseline path)
    path_ids = {c["osmid"] for c in path_cands}
    core_cands = [
        {**c, "on_baseline_path_of": []}
        for c in candidate_ways(G, limit=6)
        if c["osmid"] not in path_ids
    ]
    cands = (path_cands + core_cands)[:8]
    n_path = min(len(path_cands), 8)
    n_core = len(cands) - n_path
    print(f"[analyze] {len(cands)} closure candidates evaluated "
          f"({n_path} on baseline paths [{len(path_cands)} available], "
          f"{n_core} core arterials)")
    evaluations = []
    selected = None
    for cand in cands:
        removed = routing.remove_way(G, cand["osmid"])
        if not removed:
            continue
        D_c = distances_to_targets(G, hospital_nodes)
        per_origin = []
        total_delta = 0.0
        any_disconnect = False
        for _, o in origins.iterrows():
            node = int(o["snapped_node"])
            d0 = dist_of(D_base, node)
            d1 = dist_of(D_c, node)
            disc = is_disconnected(d1)
            if disc:
                any_disconnect = True
                delta = None
            else:
                delta = d1 - d0
                total_delta += delta
            per_origin.append(
                {
                    "origin": o["name"],
                    "before_m": None if is_disconnected(d0) else round(d0, 2),
                    "after_m": None if disc else round(d1, 2),
                    "delta_m": None if delta is None else round(delta, 2),
                    "pct_change": None if (delta is None or d0 == 0)
                    else round(100.0 * delta / d0, 2),
                    "disconnected": disc,
                }
            )
        evaluations.append(
            {
                **cand,
                "edges_removed": len(removed),
                "total_delta_m": round(total_delta, 2),
                "any_disconnected_origin": any_disconnect,
                "per_origin": per_origin,
            }
        )
        on_path = cand.get("on_baseline_path_of") or []
        marker = f" [on baseline path of: {', '.join(on_path)}]" if on_path else ""
        print(f"  way {cand['osmid']} '{cand['name']}' "
              f"({cand['length_m']:.0f} m, {len(removed)} directed edges)"
              f"{marker}: total_delta={total_delta:.1f} m, disconnected={any_disconnect}")
        routing.restore_edges(G, removed)
        if any_disconnect or total_delta > 1e-6:
            if selected is None or (
                (evaluations[-1]["any_disconnected_origin"],
                 evaluations[-1]["total_delta_m"])
                > (selected["any_disconnected_origin"], selected["total_delta_m"])
            ):
                selected = evaluations[-1]

    if selected is None and evaluations:
        selected = max(evaluations, key=lambda c: c["total_delta_m"])
    if selected is None:
        print("[analyze] FAILED: no removable candidate way found")
        return 1

    # ---------------- deep dive on selected closure ----------------
    removed = routing.remove_way(G, selected["osmid"])
    removed_edges_detail = [
        {
            "u": u, "v": v, "key": k,
            "u_latlon": [G.nodes[u]["y"], G.nodes[u]["x"]],
            "v_latlon": [G.nodes[v]["y"], G.nodes[v]["x"]],
            "name": data.get("name"),
            "highway": data.get("highway"),
            "oneway": data.get("oneway"),
            "length_m": data.get("length"),
            "osmid": data.get("osmid"),
        }
        for (u, v, k, data) in removed
    ]
    D_sel = distances_to_targets(G, hospital_nodes)
    closure_per_origin = []
    disconnected_origins = []
    monotonic_ok = True
    for _, o in origins.iterrows():
        node = int(o["snapped_node"])
        d0 = dist_of(D_base, node)
        d1 = dist_of(D_sel, node)
        if is_disconnected(d1):
            disconnected_origins.append(o["name"])
            new_h, new_d, new_path_len = None, None, None
        else:
            if d1 < d0 - 1e-9:
                monotonic_ok = False
            new_h_node, new_d, _ = nearest_hospital(G, node, hospital_nodes)
            h_row = hosp_lookup[new_h_node]
            new_h = h_row["name"] if isinstance(h_row["name"], str) else "(unnamed)"
            new_path_len = round(new_d, 2)
        closure_per_origin.append(
            {
                "origin": o["name"],
                "before_m": round(d0, 2),
                "after_m": None if is_disconnected(d1) else round(d1, 2),
                "delta_m": None if is_disconnected(d1) else round(d1 - d0, 2),
                "pct_change": None if is_disconnected(d1) or d0 == 0
                else round(100.0 * (d1 - d0) / d0, 2),
                "disconnected": is_disconnected(d1),
                "nearest_hospital_after": new_h,
            }
        )
    routing.restore_edges(G, removed)

    # ---------------- restore & reproducibility verification ----------------
    counts_after = graph_counts(G)
    D_final = distances_to_targets(G, hospital_nodes)
    reproducible = (D_final == D_base) and (counts_after == counts_before)
    print(f"[analyze] restore check: counts {counts_after} == {counts_before}: "
          f"{counts_after == counts_before}; distances identical: {D_final == D_base}")
    assert reproducible, "baseline not reproducible after restore"
    assert monotonic_ok, "monotonicity violated after closure"

    closure_payload = {
        "retrieval_date": config.today(),
        "selected_closure": {
            "osm_way_id": selected["osmid"],
            "name": selected["name"],
            "highway": selected["highways"],
            "way_length_in_core_m": round(selected["length_m"], 1),
            "graph_edges_in_way": selected["edges"],
            "directed_edges_removed": len(removed_edges_detail),
            "removed_edges": removed_edges_detail,
        },
        "candidates_evaluated": evaluations,
        "per_origin": closure_per_origin,
        "disconnected_origins": disconnected_origins,
        "monotonic_non_decreasing_verified": monotonic_ok,
        "restore_verification": {
            "node_edge_counts_before": list(counts_before),
            "node_edge_counts_after": list(counts_after),
            "counts_equal": counts_after == counts_before,
            "baseline_distances_identical": D_final == D_base,
            "reproducible": reproducible,
        },
        "timing_seconds": {
            "graph_load": round(load_s, 3),
            "baseline_dijkstra": round(base_s, 4),
            "total_analysis": round(time.time() - t_start, 2),
        },
        "usable_destinations": n_usable,
        "unique_destination_nodes": int(n_unique_nodes),
        "study_area_recommendation": "usable" if n_usable >= 2 else "choose different area",
    }
    config.CLOSURE_RESULTS.write_text(json.dumps(closure_payload, indent=2), encoding="utf-8")
    print(f"[analyze] disconnected origins: {disconnected_origins or 'none'}")
    print(f"[analyze] closure -> {config.CLOSURE_RESULTS}")
    print(f"[analyze] total {time.time() - t_start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
