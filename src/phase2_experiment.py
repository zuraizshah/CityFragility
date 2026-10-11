"""Phase 2 Parts C+D — automated closure experiment + scientific metrics.

One cached graph, one cached baseline (distance + nearest-facility source per
node, computed with a single multi-source Dijkstra that tracks the winning
facility). For each candidate way: remove every directed edge, recompute,
compare per origin, restore exactly. Never uses infinity as a numeric detour
(disconnections are recorded as flags + null detours).

Disconnection classification:
- newly_disconnected: baseline reachable, no path to any facility after closure
  - origin_isolated_stub: origin node has out-degree 0 after the closure
  - cut_from_facility_network: origin still has outgoing edges but none lead
    to any facility (genuine network cut relative to the facility set)
  (sampling/boundary causes are ruled out upstream: origins were pre-filtered
  for baseline reachability and snap inside CORE)

CLI (bounded, resumable):
  python src/phase2_experiment.py [--origins 100] [--candidates 100]
      [--max-seconds 1500] [--checkpoint-every 10] [--tag full]

Outputs (tag-dependent suffix for smoke runs):
  reports/phase2_per_origin{tag}.csv
  reports/phase2_results{tag}.csv
  reports/phase2_summary{tag}.json
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import networkx as nx
import pandas as pd
import routing
from routing import remove_way, restore_edges

SEED = 20261010

DISCLAIMER = (
    "Road-network accessibility model for the bounded central Karachi study "
    "area. Not population-representative; not emergency-capability verified; "
    "no ambulance/flood/casualty claims."
)


def log(msg: str) -> None:
    print(f"[phase2] {msg}", flush=True)


def load_graph():
    import osmnx as ox

    return ox.load_graphml(config.NETWORK_PATH)


def facility_map(G) -> dict[int, str]:
    """snap_node -> nearest facility name (same snapping as Phase 0/1).

    Co-located facilities collapse to a single snap_node entry (last name
    wins), so a "destination switch" always means the nearest facility
    NODE actually changed.
    """
    import geopandas as gpd
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
    tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
    node_ids = list(G.nodes())
    coords = [tr.transform(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids]
    tree = cKDTree(coords)
    out: dict[int, int] = {}
    names: dict[int, str] = {}
    for i, (_, r) in enumerate(hospitals.iterrows()):
        pt = r.geometry.representative_point()
        hx, hy = tr.transform(pt.x, pt.y)
        dist, idx = tree.query([hx, hy])
        if float(dist) > config.MAX_HOSPITAL_SNAP_M:
            continue
        node = int(node_ids[idx])
        out[node] = node
        nm = r["name"] if isinstance(r.get("name"), str) else f"Unnamed OSM {int(r['osmid'])}"
        names[node] = nm
    return out, names


def multi_source_with_source(G, targets: dict[int, int]):
    """Dijkstra from many sources, remembering which source won each node.

    Runs on the REVERSED graph (same direction convention as
    routing.distances_to_targets): dist[x] = shortest forward drivable
    distance from x to the nearest target facility. Returns (dist, src).
    """
    INF = float("inf")
    rev = G.reverse(copy=False)
    dist: dict[int, float] = {}
    src: dict[int, int] = {}
    pq: list[tuple[float, int, int]] = []
    for t, lab in targets.items():
        dist[t] = 0.0
        src[t] = lab
        heapq.heappush(pq, (0.0, t, lab))
    while pq:
        d, u, lab = heapq.heappop(pq)
        if d > dist.get(u, INF):
            continue
        for v, edata in rev[u].items():
            w = min(dd.get("length", 1.0) for dd in edata.values())
            nd = d + w
            if nd < dist.get(v, INF):
                dist[v] = nd
                src[v] = lab
                heapq.heappush(pq, (nd, v, lab))
    return dist, src


def compute_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    affected = [r for r in rows if (r["detour_m"] or 0) > 1e-6]
    disconnected = [r for r in rows if r["newly_disconnected"]]
    switched = [r for r in rows if r["destination_switched"]]
    extras = sorted(r["detour_m"] for r in affected)
    median_extra = extras[len(extras) // 2] if extras else 0.0
    max_extra = extras[-1] if extras else 0.0
    # Transparent composite: 1 point per affected origin, 5 points per newly
    # disconnected origin, plus min(median extra/100 m, 20). Documented, not AI.
    score = len(affected) + 5 * len(disconnected) + min(median_extra / 100.0, 20.0)
    return {
        "n_origins": n,
        "n_affected": len(affected),
        "pct_affected": round(100.0 * len(affected) / n, 2) if n else 0.0,
        "median_extra_m": round(median_extra, 2),
        "max_extra_m": round(max_extra, 2),
        "n_newly_disconnected": len(disconnected),
        "n_destination_switched": len(switched),
        "disruption_score": round(score, 3),
    }


def rank_lists(results: list[dict]) -> dict:
    by_affected = [r["osmid"] for r in sorted(
        results, key=lambda r: (-r["n_affected"], -r["n_newly_disconnected"], r["osmid"]))]
    by_detour = [r["osmid"] for r in sorted(
        results, key=lambda r: (-r["median_extra_m"], -r["max_extra_m"], r["osmid"])
        ) if r["n_affected"] > 0]
    by_disconnect = [r["osmid"] for r in sorted(
        results, key=lambda r: (-r["n_newly_disconnected"], -r["n_affected"], r["osmid"]))
        if r["n_newly_disconnected"] > 0]
    by_score = [r["osmid"] for r in sorted(
        results, key=lambda r: (-r["disruption_score"], r["osmid"]))]
    return {
        "by_affected_count": by_affected,
        "by_median_detour": by_detour,
        "by_max_detour": [r["osmid"] for r in sorted(
            results, key=lambda r: (-r["max_extra_m"], r["osmid"])) if r["n_affected"] > 0],
        "by_disconnections": by_disconnect,
        "by_composite_score": by_score,
    }


def top_overlap(rank_a: list, rank_b: list, k=5) -> dict:
    a, b = set(rank_a[:k]), set(rank_b[:k])
    return {"top_k": k, "overlap": len(a & b), "union": len(a | b) or 1}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origins", type=int, default=100)
    ap.add_argument("--candidates", type=int, default=100)
    ap.add_argument("--max-seconds", type=float, default=1500.0)
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    tag = f"_{args.tag}" if args.tag else ""
    t_start = time.time()

    ckpt_dir = config.REPORTS_DIR / f"phase2_checkpoint{tag}"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    state_path = ckpt_dir / "state.json"
    partial_path = ckpt_dir / "partial_per_origin.csv"

    log("loading graph (single copy, reused for every scenario)...")
    G = load_graph()
    nodes0, edges0 = G.number_of_nodes(), G.number_of_edges()
    fac, fac_names = facility_map(G)
    log(f"graph {nodes0}/{edges0}; {len(fac)} facility snap nodes")

    origins = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv").head(args.origins)
    cands = pd.read_csv(config.DATA_DIR / "phase2_candidates.csv").head(args.candidates)
    origin_nodes = [int(x) for x in origins["node_id"]]

    log(f"baseline pass ({len(origin_nodes)} origins, {len(cands)} candidates)...")
    dist_base, src_base = multi_source_with_source(G, fac)
    for o in origin_nodes:
        assert o in dist_base, f"sample origin {o} unreachable at baseline"
    baseline_s = time.time() - t_start
    log(f"baseline done in {baseline_s:.1f}s")

    # ---- resume state --------------------------------------------------
    done: set[int] = set()
    all_rows: list[dict] = []
    state: dict = {}
    if state_path.exists() and partial_path.exists():
        state = json.loads(state_path.read_text())
        done = set(state.get("completed_osmids", []))
        all_rows = pd.read_csv(partial_path).to_dict("records")
        log(f"resuming: {len(done)} candidates already completed")

    completed_meta: list[dict] = list(state.get("completed_meta", []))

    for i, (_, cand) in enumerate(cands.iterrows()):
        osmid = int(cand["osmid"])
        if osmid in done:
            continue
        if time.time() - t_start > args.max_seconds:
            log(f"STOP: wall-clock bound {args.max_seconds}s reached after "
                f"{len(done)} candidates — writing partial results")
            break
        t0 = time.time()
        removed = remove_way(G, osmid)
        if not removed:
            log(f"  way {osmid}: no edges in graph — skipped")
            done.add(osmid)
            continue
        try:
            dist_clos, src_clos = multi_source_with_source(G, fac)
            rows = []
            for o, oname in zip(origin_nodes, origins["sample_id"]):
                b = dist_base.get(o)
                a = dist_clos.get(o)
                newly_disc = a is None
                detour = None if newly_disc else round(a - b, 2)
                switched = (not newly_disc) and src_clos.get(o) != src_base.get(o)
                rows.append({
                    "candidate_osmid": osmid,
                    "origin_node": o,
                    "origin_sample_id": oname,
                    "baseline_m": round(b, 2),
                    "disrupted_m": None if newly_disc else round(a, 2),
                    "detour_m": detour,
                    "detour_pct": None if newly_disc else round(100.0 * (a - b) / b, 3) if b else None,
                    "newly_disconnected": newly_disc,
                    "origin_isolated_stub": newly_disc and G.out_degree(o) == 0,
                    "cut_from_facility_network": newly_disc and G.out_degree(o) > 0,
                    "destination_switched": switched,
                    "baseline_facility": fac_names.get(src_base.get(o), "?"),
                    "disrupted_facility": None if newly_disc else fac_names.get(src_clos.get(o), "?"),
                })
            all_rows.extend(rows)
            metrics = compute_metrics(rows)
            meta = {**{k: cand[k] for k in cand.index}, **metrics,
                    "edges_removed": len(removed),
                    "scenario_ms": round((time.time() - t0) * 1000, 1)}
            completed_meta.append(meta)
            done.add(osmid)
            log(f"  [{len(done)}/{len(cands)}] way {osmid} "
                f"'{cand.get('name')}' affected={metrics['n_affected']} "
                f"disc={metrics['n_newly_disconnected']} "
                f"switched={metrics['n_destination_switched']} "
                f"median+{metrics['median_extra_m']}m "
                f"({meta['scenario_ms']} ms)")
        finally:
            restore_edges(G, removed)
            assert G.number_of_nodes() == nodes0 and G.number_of_edges() == edges0, \
                "graph counts changed after restore"

        if len(done) % args.checkpoint_every == 0:
            pd.DataFrame(all_rows).to_csv(partial_path, index=False)
            state_path.write_text(json.dumps({
                "completed_osmids": sorted(done),
                "completed_meta": completed_meta,
            }), encoding="utf-8")
            log(f"  checkpoint: {len(done)} done, "
                f"{time.time()-t_start:.0f}s elapsed")

    # ---- restore-identity verification ---------------------------------
    dist_after, _ = multi_source_with_source(G, fac)
    identical = all(
        abs(dist_after[o] - dist_base[o]) < 1e-6 for o in origin_nodes
    )
    assert identical, "baseline distances changed after experiment!"
    assert (G.number_of_nodes(), G.number_of_edges()) == (nodes0, edges0)

    # ---- outputs --------------------------------------------------------
    per_origin_df = pd.DataFrame(all_rows)
    results_df = pd.DataFrame(completed_meta)
    rankings = rank_lists(completed_meta) if completed_meta else {}

    # sensitivity: odd/even origin halves
    sensitivity = {}
    if per_origin_df.shape[0] > 0:
        half_a = per_origin_df[per_origin_df["origin_node"].isin(origin_nodes[::2])]
        half_b = per_origin_df[per_origin_df["origin_node"].isin(origin_nodes[1::2])]
        ra = rank_lists([{"osmid": k, **compute_metrics(g.to_dict("records"))}
                         for k, g in half_a.groupby("candidate_osmid")]) \
            if half_a.shape[0] else {}
        rb = rank_lists([{"osmid": k, **compute_metrics(g.to_dict("records"))}
                         for k, g in half_b.groupby("candidate_osmid")]) \
            if half_b.shape[0] else {}
        sensitivity = {
            "method": "metrics recomputed on odd vs even sample origins; top-5 overlap per ranking",
            "by_affected_count": top_overlap(ra.get("by_affected_count", []),
                                             rb.get("by_affected_count", [])),
            "by_composite_score": top_overlap(ra.get("by_composite_score", []),
                                              rb.get("by_composite_score", [])),
        }

    per_origin_df.to_csv(config.REPORTS_DIR / f"phase2_per_origin{tag}.csv", index=False)
    results_df.to_csv(config.REPORTS_DIR / f"phase2_results{tag}.csv", index=False)

    total_s = time.time() - t_start
    summary = {
        "tag": args.tag or "full",
        "retrieval_date": config.today(),
        "seed": SEED,
        "n_origins": len(origin_nodes),
        "n_candidates_requested": len(cands),
        "n_candidates_completed": len(done),
        "partial": len(done) < len(cands),
        "graph_nodes": nodes0,
        "graph_edges": edges0,
        "facility_nodes": len(fac),
        "runtime_s": {
            "baseline_pass": round(baseline_s, 1),
            "total": round(total_s, 1),
            "mean_scenario_ms": round(
                results_df["scenario_ms"].mean(), 1) if len(results_df) else None,
        },
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
        if sys.platform == "darwin" else
        round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "restore_verified_identical": identical,
        "composite_score_formula": (
            "n_affected + 5*n_newly_disconnected + min(median_extra_m/100, 20)"
        ),
        "rankings": rankings,
        "sensitivity": sensitivity,
        "disclaimer": DISCLAIMER,
        "outputs": {
            "per_origin_csv": f"reports/phase2_per_origin{tag}.csv",
            "results_csv": f"reports/phase2_results{tag}.csv",
        },
    }
    if len(results_df):
        top = results_df.sort_values("disruption_score", ascending=False).head(5)
        summary["top5_by_composite"] = top[[
            "osmid", "name", "selection_tier", "n_affected", "n_newly_disconnected",
            "median_extra_m", "max_extra_m", "disruption_score",
        ]].to_dict("records")

    (config.REPORTS_DIR / f"phase2_summary{tag}.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log(f"wrote results ({len(results_df)} candidates, {len(per_origin_df)} rows)")
    log(f"total {total_s:.1f}s, peak RSS {summary['peak_rss_mb']} MB, "
        f"restore verified: {identical}")
    if summary["top5_by_composite"]:
        log("top-5 by composite score:")
        for r in summary["top5_by_composite"]:
            log(f"  way {r['osmid']} '{r['name']}': affected={r['n_affected']} "
                f"disc={r['n_newly_disconnected']} median+{r['median_extra_m']}m "
                f"score={r['disruption_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
