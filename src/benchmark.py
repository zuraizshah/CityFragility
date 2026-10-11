"""Modest performance benchmark for the Phase 0 pipeline.

Reports actual node/edge counts, runtimes (3 repeats where cheap) and peak
resident memory of the benchmark process.  These are NOT traffic or
emergency-response times - only algorithmic routing costs on OSM data.
"""
from __future__ import annotations

import json
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


def timed(fn, repeats=1):
    times, out = [], None
    for _ in range(repeats):
        t0 = time.time()
        out = fn()
        times.append(time.time() - t0)
    return out, times


def main() -> int:
    import osmnx as ox

    config.configure_osmnx()
    results: dict = {"retrieval_date": config.today()}

    if not config.NETWORK_PATH.exists():
        print("[benchmark] network missing - run download_network.py first")
        return 1

    # 1) load
    G, load_times = timed(lambda: ox.load_graphml(config.NETWORK_PATH), repeats=1)
    n_nodes, n_edges = G.number_of_nodes(), G.number_of_edges()
    results["network"] = {
        "nodes": n_nodes,
        "directed_edges": n_edges,
        "load_seconds": [round(t, 3) for t in load_times],
    }

    # 2) projection
    G_proj, proj_times = timed(
        lambda: ox.projection.project_graph(G, to_crs=config.ANALYSIS_CRS), repeats=3
    )
    results["project_graph_seconds"] = [round(t, 3) for t in proj_times]

    # 3) snapping origins
    if config.ORIGINS_REF_PATH.exists():
        import pandas as pd
        import osmnx.distance as oxd
        from pyproj import Transformer

        origins = pd.read_csv(config.ORIGINS_REF_PATH)
        tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)

        def do_snap():
            xs, ys = [], []
            for _, r in origins.iterrows():
                x, y = tr.transform(r["ref_lon"], r["ref_lat"])
                xs.append(x)
                ys.append(y)
            return oxd.nearest_nodes(G_proj, X=xs, Y=ys, return_dist=True)

        _, snap_times = timed(do_snap, repeats=3)
        results["snap_origins_seconds"] = [round(t, 4) for t in snap_times]

    # 4) baseline multi-source Dijkstra
    if config.HOSPITALS_PATH.exists():
        import geopandas as gpd
        import osmnx.distance as oxd
        from pyproj import Transformer
        from routing import distances_to_targets

        hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
        tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
        xs, ys = [], []
        for _, r in hospitals.iterrows():
            pt = r.geometry.representative_point()
            x, y = tr.transform(pt.x, pt.y)
            xs.append(x)
            ys.append(y)
        h_nodes, h_dists = oxd.nearest_nodes(G_proj, X=xs, Y=ys, return_dist=True)
        pairs = [
            (int(n), float(d))
            for n, d in zip(h_nodes, h_dists)
            if float(d) <= config.MAX_HOSPITAL_SNAP_M
        ]
        usable = {n for n, _ in pairs}
        results["hospitals"] = {
            "mapped": len(hospitals),
            "usable_for_routing": len(pairs),
            "unique_snap_nodes": len(usable),
            "note": (
                "usable_for_routing counts hospital facilities within the snap "
                "threshold; unique_snap_nodes is the smaller number of distinct "
                "graph nodes they map to (facilities can share a node), which is "
                "what multi-source Dijkstra actually seeds."
            ),
        }
        _, base_times = timed(lambda: distances_to_targets(G, usable), repeats=3)
        results["baseline_dijkstra_seconds"] = [round(t, 4) for t in base_times]

        # 5) closure remove + dijkstra + restore
        closure_path = config.CLOSURE_RESULTS
        if closure_path.exists():
            payload = json.loads(closure_path.read_text())
            osmid = payload["selected_closure"]["osm_way_id"]
            from routing import remove_way, restore_edges

            def closure_cycle():
                removed = remove_way(G, osmid)
                distances_to_targets(G, usable)
                restore_edges(G, removed)

            _, closure_times = timed(closure_cycle, repeats=3)
            results["closure_cycle_seconds"] = [round(t, 4) for t in closure_times]
            results["closure_way_id"] = osmid

    # 6) memory
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        rss_mb = rss / (1024 * 1024)  # bytes on macOS
    else:
        rss_mb = rss / 1024           # KiB on Linux
    results["peak_rss_mb"] = round(rss_mb, 1)
    results["note"] = (
        "Algorithmic routing timings on OSM data only. Not traffic, not "
        "emergency-response times."
    )

    config.BENCHMARK_RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"[benchmark] -> {config.BENCHMARK_RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
