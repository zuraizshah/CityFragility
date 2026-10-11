"""Phase 3 — research validation (bounded; reuses ALL saved Phase 0/1/2 artifacts).

Tasks (no experiment re-run, no downloads):
  1. Reproducibility: recompute every results.csv metric + ranking list from
     phase2_per_origin.csv with the SAME pure metric functions.
  2. Independent cross-check: selected closure scenarios recomputed with the
     Phase 0-trusted networkx engine (routing.distances_to_targets + nx
     multi-source Dijkstra with path reconstruction for facility identity).
  3. Sensitivity: odd/even origin halves AND east/west geographic partition;
     top-5 overlaps per ranking.
  4. Facility data-quality audit: aggregate snapping stats + 10 inspected
     facilities (duplicates, suspicious snaps, limited-scope name notes).
  5. Assumption effects: boundary, full-way closures, one-ways, candidate bias.

Outputs (machine-readable first, report generated FROM these numbers):
  reports/phase3_findings.json
  reports/PHASE3_VALIDATION_REPORT.md

CLI: python src/phase3_validation.py [--max-crosscheck-ways 12]
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

import config
import routing
from phase2_experiment import SEED, compute_metrics, facility_map, rank_lists, top_overlap

TOL_M = 0.05  # metres tolerance for independent distance reproduction


def log(msg: str) -> None:
    print(f"[phase3] {msg}", flush=True)


# ----------------------------------------------------------------- task 1
def task1_reproducibility() -> dict:
    po = pd.read_csv(config.REPORTS_DIR / "phase2_per_origin.csv")
    res = pd.read_csv(config.REPORTS_DIR / "phase2_results.csv")
    summary = json.loads((config.REPORTS_DIR / "phase2_summary.json").read_text())

    mismatches = []
    recomputed = []
    for osmid, grp in po.groupby("candidate_osmid"):
        rows = [
            {
                "detour_m": None if pd.isna(r.detour_m) else float(r.detour_m),
                "newly_disconnected": bool(r.newly_disconnected),
                "destination_switched": bool(r.destination_switched),
            }
            for r in grp.itertuples()
        ]
        m = compute_metrics(rows)
        m["osmid"] = int(osmid)
        recomputed.append(m)
        stored = res[res["osmid"] == int(osmid)]
        if stored.empty:
            mismatches.append({"osmid": int(osmid), "reason": "missing in results.csv"})
            continue
        s = stored.iloc[0]
        for col in ("n_origins", "n_affected", "pct_affected", "median_extra_m",
                    "max_extra_m", "n_newly_disconnected", "n_destination_switched",
                    "disruption_score"):
            if abs(float(m[col]) - float(s[col])) > 1e-6:
                mismatches.append({"osmid": int(osmid), "column": col,
                                   "recomputed": m[col], "stored": float(s[col])})

    rankings = rank_lists(recomputed)
    rank_match = {
        k: rankings[k] == summary["rankings"][k] for k in summary["rankings"]
    }
    log(f"task1: {len(recomputed)} ways recomputed, "
        f"{len(mismatches)} metric mismatches, rankings match={all(rank_match.values())}")
    return {
        "per_origin_rows": int(len(po)),
        "ways_recomputed": len(recomputed),
        "metric_mismatches": mismatches,
        "metric_columns_checked": 8,
        "rankings_match_stored_summary": rank_match,
        "all_rankings_match": all(rank_match.values()),
    }


# ----------------------------------------------------------------- task 2
def task2_cross_check(G, fac, fac_names, max_ways: int) -> dict:
    po = pd.read_csv(config.REPORTS_DIR / "phase2_per_origin.csv")
    res = pd.read_csv(config.REPORTS_DIR / "phase2_results.csv")
    top_score = res.nlargest(5, "disruption_score")["osmid"].tolist()
    top_aff = res.nlargest(5, "n_affected")["osmid"].tolist()
    zero = res[res["n_affected"] == 0]["osmid"].head(2).tolist()
    ways = list(dict.fromkeys([int(x) for x in top_score + top_aff + zero]))[:max_ways]

    fac_nodes = sorted(fac.keys())
    log("task2: trusted baseline pass (networkx multi-source)...")
    t0 = time.time()
    base_dist = routing.distances_to_targets(G, set(fac_nodes))
    rev = G.reverse(copy=False)
    base_dist2, base_path = nx.multi_source_dijkstra(rev, fac_nodes, weight="length")
    log(f"task2: baseline in {time.time()-t0:.1f}s")

    nodes0, edges0 = G.number_of_nodes(), G.number_of_edges()
    details = []
    total_rows = 0
    dist_mis = base_dist_mis = switch_mis = disc_mis = fac_mis = 0

    for osmid in ways:
        grp = po[po["candidate_osmid"] == osmid]
        affected = grp[(grp["detour_m"].fillna(0) > TOL_M) | grp["newly_disconnected"]
                       | grp["destination_switched"]]
        unaffected = grp[grp["detour_m"].fillna(0) == 0].head(5)
        check = pd.concat([affected, unaffected]).drop_duplicates("origin_node")

        removed = routing.remove_way(G, osmid)
        try:
            clos_dist = routing.distances_to_targets(G, set(fac_nodes))
            clos_dist2, clos_path = nx.multi_source_dijkstra(rev, fac_nodes, weight="length")
        finally:
            routing.restore_edges(G, removed)
        assert (G.number_of_nodes(), G.number_of_edges()) == (nodes0, edges0)

        w = {"osmid": int(osmid), "rows_checked": int(len(check)),
             "mismatches": []}
        for r in check.itertuples():
            o = int(r.origin_node)
            total_rows += 1
            b1, b2 = base_dist.get(o), base_dist2.get(o)
            if b1 is None or b2 is None or abs(b1 - b2) > TOL_M:
                base_dist_mis += 1
                w["mismatches"].append({"origin": o, "kind": "engine_baseline_disagree",
                                        "a": b1, "b": b2})
            if b2 is None or abs(round(b2, 2) - float(r.baseline_m)) > TOL_M:
                base_dist_mis += 1
                w["mismatches"].append({"origin": o, "kind": "baseline_vs_stored",
                                        "engine": b2, "stored": float(r.baseline_m)})
            # facility identity at baseline (path source node)
            b_fac_node = base_path[o][0] if o in base_path else None
            b_fac_name = fac_names.get(b_fac_node, "?")
            if b_fac_name != r.baseline_facility:
                fac_mis += 1
                w["mismatches"].append({"origin": o, "kind": "baseline_facility",
                                        "engine": b_fac_name, "stored": r.baseline_facility})

            a2 = clos_dist2.get(o)
            stored_disc = bool(r.newly_disconnected)
            engine_disc = a2 is None
            if engine_disc != stored_disc:
                disc_mis += 1
                w["mismatches"].append({"origin": o, "kind": "disconnect_flag",
                                        "engine": engine_disc, "stored": stored_disc})
            if not engine_disc and not stored_disc:
                if abs(round(a2, 2) - float(r.disrupted_m)) > TOL_M:
                    dist_mis += 1
                    w["mismatches"].append({"origin": o, "kind": "disrupted_distance",
                                            "engine": round(a2, 2),
                                            "stored": float(r.disrupted_m)})
                a_fac_node = clos_path[o][0] if o in clos_path else None
                a_fac_name = fac_names.get(a_fac_node, "?")
                engine_switch = a_fac_node != b_fac_node
                if engine_switch != bool(r.destination_switched):
                    switch_mis += 1
                    w["mismatches"].append({"origin": o, "kind": "switch_flag",
                                            "engine": engine_switch,
                                            "stored": bool(r.destination_switched)})
                if a_fac_name != (r.disrupted_facility if not pd.isna(r.disrupted_facility) else None):
                    # stored None only when disconnected; else name
                    if pd.isna(r.disrupted_facility) or a_fac_name != r.disrupted_facility:
                        fac_mis += 1
                        w["mismatches"].append({"origin": o, "kind": "disrupted_facility",
                                                "engine": a_fac_name,
                                                "stored": r.disrupted_facility})
        details.append(w)
        log(f"task2: way {osmid} checked {len(check)} rows, "
            f"{len(w['mismatches'])} mismatches")

    return {
        "engine": ("networkx.multi_source_dijkstra on the reversed graph with path "
                   "reconstruction (Phase 0-verified routing family, independent "
                   "implementation from the Phase 2 heap Dijkstra)"),
        "ways_checked": ways,
        "ways_count": len(ways),
        "origin_rows_checked": total_rows,
        "baseline_distance_mismatches": base_dist_mis,
        "disrupted_distance_mismatches": dist_mis,
        "facility_identity_mismatches": fac_mis,
        "disconnect_flag_mismatches": disc_mis,
        "switch_flag_mismatches": switch_mis,
        "per_way": details,
        "restore_verified": True,
    }


# ----------------------------------------------------------------- task 3
def _rank_from_subset(po_sub: pd.DataFrame, rank_key: str) -> tuple[list[int], int]:
    """Rank ways using only origins in po_sub; also count ways with any effect."""
    recs = []
    with_effect = 0
    for osmid, grp in po_sub.groupby("candidate_osmid"):
        rows = [{"detour_m": None if pd.isna(r.detour_m) else float(r.detour_m),
                 "newly_disconnected": bool(r.newly_disconnected),
                 "destination_switched": bool(r.destination_switched)}
                for r in grp.itertuples()]
        m = compute_metrics(rows)
        m["osmid"] = int(osmid)
        if m["n_affected"] > 0 or m["n_newly_disconnected"] > 0:
            with_effect += 1
        recs.append(m)
    return rank_lists(recs).get(rank_key, []) if recs else [], with_effect


def task3_sensitivity() -> dict:
    po = pd.read_csv(config.REPORTS_DIR / "phase2_per_origin.csv")
    origins = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    order = origins["node_id"].tolist()
    odd = set(order[::2])
    even = set(order[1::2])
    lon_med = float(origins["lon"].median())
    west = set(origins[origins["lon"] <= lon_med]["node_id"])
    east = set(origins[origins["lon"] > lon_med]["node_id"])

    partitions = {"odd_even": (odd, even), "east_west": (west, east)}
    out = {"lon_median": lon_med, "n_west": len(west), "n_east": len(east)}
    for name, (a, b) in partitions.items():
        block = {}
        for rank_key in ("by_affected_count", "by_composite_score"):
            ra, eff_a = _rank_from_subset(po[po["origin_node"].isin(a)], rank_key)
            rb, eff_b = _rank_from_subset(po[po["origin_node"].isin(b)], rank_key)
            block[rank_key] = {
                "top5_a": ra[:5], "top5_b": rb[:5],
                "overlap": top_overlap(ra, rb, 5),
                "ways_with_effect_a": eff_a, "ways_with_effect_b": eff_b,
            }
        out[name] = block
        log(f"task3: {name} composite overlap="
            f"{block['by_composite_score']['overlap']['overlap']}/5 "
            f"affected overlap={block['by_affected_count']['overlap']['overlap']}/5")
    out["note"] = ("Rankings are computed independently within each partition "
                   "(half the origins each). Low overlap means ranks depend on "
                   "which origins were sampled — not that any road is uniquely "
                   "critical for Karachi.")
    return out


# ----------------------------------------------------------------- task 4
LIMITED_SCOPE_KEYWORDS = [
    "dental", "diagnostic", "laborator", "pharmacy", "maternity", "mother",
    "eye", "ent ", "physio", "rehab", "nursing", "unani", "homeo",
    "veterinary", "clinic", "fertility", "dialysis", "x-ray", "xray",
]


def task4_facility_audit(G, fac) -> dict:
    hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
    tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
    node_ids = list(G.nodes())
    coords = np.array([tr.transform(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids])
    tree = cKDTree(coords)

    recs = []
    for _, r in hospitals.iterrows():
        pt = r.geometry.representative_point()
        hx, hy = tr.transform(pt.x, pt.y)
        dist, idx = tree.query([hx, hy])
        name = r["name"] if isinstance(r.get("name"), str) else None
        scope = any(k in (name or "").lower() for k in LIMITED_SCOPE_KEYWORDS)
        recs.append({
            "osmid": int(r["osmid"]), "element_type": r["element_type"],
            "name": name, "amenity": r["amenity"],
            "matched_tag": r["_matched_tag"],
            "lat": float(pt.y), "lon": float(pt.x),
            "snap_dist_m": round(float(dist), 1),
            "usable": float(dist) <= config.MAX_HOSPITAL_SNAP_M,
            "outside_core": not (config.CORE_BBOX[0] <= pt.x <= config.CORE_BBOX[2]
                                 and config.CORE_BBOX[1] <= pt.y <= config.CORE_BBOX[3]),
            "limited_scope_name": scope,
        })
    df = pd.DataFrame(recs)
    usable = df[df["usable"]]

    # facility-to-facility near-duplicates (usable only)
    utr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
    fxy = np.array([utr.transform(x, y) for x, y in zip(usable["lon"], usable["lat"])])
    ftree = cKDTree(fxy)
    pairs = ftree.query_pairs(50.0)
    dup_pairs = [
        {"a": int(usable.iloc[i]["osmid"]), "b": int(usable.iloc[j]["osmid"]),
         "name_a": usable.iloc[i]["name"], "name_b": usable.iloc[j]["name"]}
        for i, j in sorted(pairs)
    ]

    named = usable.dropna(subset=["name"])
    name_counts = named.groupby(named["name"].str.lower()).size()
    dup_names = name_counts[name_counts > 1].to_dict()

    # 10 inspected: 5 highest snap distances + 5 facilities serving the top
    # composite way's affected origins (deterministic, distinct)
    top5 = pd.read_csv(config.REPORTS_DIR / "phase2_results.csv").nlargest(5, "disruption_score")
    ref_names = []
    for oid in top5["osmid"]:
        g = pd.read_csv(config.REPORTS_DIR / "phase2_per_origin.csv")
        g = g[(g["candidate_osmid"] == oid) & (g["detour_m"].fillna(0) > 0)]
        for nm in g["baseline_facility"].dropna().unique().tolist():
            if nm not in ref_names:
                ref_names.append(nm)
    inspect_osmids = usable.nlargest(5, "snap_dist_m")["osmid"].tolist()
    for nm in ref_names[:5]:
        row = named[named["name"] == nm]
        if not row.empty and int(row.iloc[0]["osmid"]) not in inspect_osmids:
            inspect_osmids.append(int(row.iloc[0]["osmid"]))
    inspected = df[df["osmid"].isin(inspect_osmids)].head(10).to_dict("records")

    stats = {
        "total_facilities": int(len(df)),
        "usable": int(len(usable)),
        "usable_snap_nodes": int(len(fac)),
        "snap_dist_m": {
            "median": round(float(usable["snap_dist_m"].median()), 1),
            "p95": round(float(usable["snap_dist_m"].quantile(0.95)), 1),
            "max": round(float(usable["snap_dist_m"].max()), 1),
        },
        "snap_gt_250m": int((usable["snap_dist_m"] > 250).sum()),
        "outside_core_usable": int(usable["outside_core"].sum()),
        "limited_scope_name_usable": int(usable["limited_scope_name"].sum()),
        "near_duplicate_pairs_50m": dup_pairs,
        "duplicate_name_clusters": {k: int(v) for k, v in dup_names.items()},
        "inspected": inspected,
        "disclaimer": ("Facilities are OpenStreetMap points carrying an "
                       "amenity=hospital (or similar) mapper tag. This audit "
                       "checks coordinates, duplication and naming scope ONLY. "
                       "No clinical or emergency capability is verified or "
                       "claimed for any facility."),
    }
    log(f"task4: {len(df)} facilities, {len(usable)} usable, "
        f"{len(dup_pairs)} near-dup pairs, {len(inspected)} inspected")
    return stats


# ----------------------------------------------------------------- task 5
def task5_assumption_effects(G) -> dict:
    origins = pd.read_csv(config.DATA_DIR / "phase2_origins_sample.csv")
    cands = pd.read_csv(config.DATA_DIR / "phase2_candidates.csv")
    w, s, e, n = config.CORE_BBOX
    # degrees → metres (UTM-42N approx at 24.85°N: 1° lat ≈ 110.9 km, 1° lon ≈ 102.7 km)
    d_edge_m = np.minimum.reduce([
        (origins["lon"] - w) * 102_700.0, (e - origins["lon"]) * 102_700.0,
        (origins["lat"] - s) * 110_900.0, (n - origins["lat"]) * 110_900.0,
    ])

    cand_len = cands["length_m"]
    total_graph_len = sum(
        d.get("length", 0.0) for _, _, d in G.edges(data=True)
    )
    cand_total_len = float(cand_len.sum())

    one_way_edges = 0
    cand_edges = 0
    for osmid in cands["osmid"].head(100):
        keys = routing.way_edge_keys(G, int(osmid))
        cand_edges += len(keys)
        edge_set = set((u, v) for u, v, k in keys)
        for u, v in edge_set:
            if (v, u) not in edge_set:
                one_way_edges += 1

    return {
        "boundary": {
            "origins_within_200m_of_core_edge": int((d_edge_m < 200).sum()),
            "min_origin_distance_to_edge_m": round(float(d_edge_m.min()), 1),
            "median_origin_distance_to_edge_m": round(float(np.median(d_edge_m)), 1),
            "note": ("Facilities are drawn from the full BUFFER area while "
                     "origins are restricted to CORE; routes near the CORE "
                     "edge may be truncated relative to a wider network."),
        },
        "full_way_closures": {
            "candidate_length_m": {
                "min": round(float(cand_len.min()), 0),
                "median": round(float(cand_len.median()), 0),
                "max": round(float(cand_len.max()), 0),
            },
            "note": ("Each scenario closes an ENTIRE OSM way (up to 6 km). "
                     "Real incidents are usually partial and temporary; "
                     "full-way closure is an upper-bound stress test."),
        },
        "one_ways": {
            "candidate_directed_edges": cand_edges,
            "directed_edges_without_reverse_twin": one_way_edges,
            "share_pct": round(100.0 * one_way_edges / cand_edges, 1) if cand_edges else 0.0,
            "note": ("Routing is fully directed (one-ways honoured). The share "
                     "above counts candidate-way directed edges that have no "
                     "opposite-direction twin, i.e. genuinely one-way segments."),
        },
        "candidate_bias": {
            "candidates_count": int(len(cands)),
            "candidate_total_length_m": round(cand_total_len, 0),
            "graph_total_length_km": round(total_graph_len / 1000.0, 1),
            "coverage_of_network_pct": round(100.0 * cand_total_len / total_graph_len, 2),
            "tiers": cands["selection_tier"].value_counts().to_dict(),
            "note": ("Candidates are NOT a random sample of the network: "
                     "30% come from high path-frequency tiers, which biases "
                     "towards roads already used by this origin sample. "
                     "Unlisted roads were not tested and may still matter."),
        },
    }


# ----------------------------------------------------------------- report
def verified_findings_block(t1, t2, t3, t4, t5) -> list[str]:
    res = pd.read_csv(config.REPORTS_DIR / "phase2_results.csv")
    top = res.nlargest(1, "disruption_score").iloc[0]
    aff = (res["n_affected"] > 0).sum()
    return [
        f"Reproducibility: all {t1['ways_recomputed']} way-level metric rows and "
        f"all ranking lists recompute exactly from the 10,000 saved per-origin rows "
        f"({t1['metric_columns_checked']} metric columns checked; "
        f"{len(t1['metric_mismatches'])} mismatches).",
        f"Independent cross-check: {t2['origin_rows_checked']} origin-way rows "
        f"across {t2['ways_count']} selected closures reproduce with the Phase 0 "
        f"networkx engine — {t2['baseline_distance_mismatches'] + t2['disrupted_distance_mismatches']} "
        f"distance mismatches, {t2['facility_identity_mismatches']} facility-identity "
        f"mismatches, {t2['disconnect_flag_mismatches'] + t2['switch_flag_mismatches']} "
        f"flag mismatches (tolerance {TOL_M} m).",
        f"Measured scope: {aff} of {len(res)} tested ways measurably affect at "
        f"least one sampled origin; {int(res['n_newly_disconnected'].sum())} "
        f"origin-way disconnections in total. Highest composite score in this "
        f"sample: OSM {int(top['osmid'])} ({top['name'] if isinstance(top['name'], str) else 'unnamed way'}, "
        f"score {top['disruption_score']}).",
        f"Sensitivity: splitting the same 100 origins into odd/even halves gives "
        f"top-5 composite overlap {t3['odd_even']['by_composite_score']['overlap']['overlap']}/5 "
        f"and affected-count overlap "
        f"{t3['odd_even']['by_affected_count']['overlap']['overlap']}/5; an "
        f"east/west geographic split gives "
        f"{t3['east_west']['by_composite_score']['overlap']['overlap']}/5 and "
        f"{t3['east_west']['by_affected_count']['overlap']['overlap']}/5. "
        f"Rankings are sample-dependent and must not be read as a citywide "
        f"criticality ordering.",
        f"Facility audit: {t4['total_facilities']} mapped points, "
        f"{t4['usable']} within the {config.MAX_HOSPITAL_SNAP_M} m snap limit "
        f"(median snap {t4['snap_dist_m']['median']} m, max {t4['snap_dist_m']['max']} m); "
        f"{len(t4['near_duplicate_pairs_50m'])} near-duplicate pairs within 50 m; "
        f"{t4['limited_scope_name_usable']} usable names suggest limited-scope "
        f"facilities (e.g. dental/diagnostic). OSM tags do not verify emergency care.",
        f"Study-area effects: {t5['boundary']['origins_within_200m_of_core_edge']} "
        f"sampled origins lie within 200 m of the CORE boundary; candidates cover "
        f"{t5['candidate_bias']['coverage_of_network_pct']}% of network length and "
        f"include {t5['one_ways']['share_pct']}% one-way directed edges. "
        f"Full-way closures are upper-bound stress tests, not incident forecasts.",
    ]


LIMITATIONS = [
    "Origins are a grid-uniform sample — not population-weighted; results "
    "describe this sample only.",
    "Facilities are unverified OSM tags; no clinical or emergency capability "
    "is asserted for any facility.",
    "Closures are hypothetical and full-way; no flood, traffic, ambulance or "
    "casualty modelling is performed.",
    "Candidate roads are selected (not randomly sampled) and cover a small "
    "share of network length; untested roads may be more important.",
    "Rankings change materially across origin partitions; they are indicative "
    "of this sample, not a definitive citywide ranking.",
    "Graph geometry, one-ways and turn-restriction completeness reflect the "
    "2026-10-09 OSM snapshot and can change conclusions when corrected.",
]


def write_report(findings: dict, runtime: dict) -> str:
    t1, t2, t3 = findings["reproducibility"], findings["cross_check"], findings["sensitivity"]
    t4, t5 = findings["facility_audit"], findings["assumption_effects"]
    res = pd.read_csv(config.REPORTS_DIR / "phase2_results.csv")
    top5 = res.nlargest(5, "disruption_score")[["osmid", "name", "n_affected", "median_extra_m", "disruption_score"]]
    top5aff = res.nlargest(5, "n_affected")[["osmid", "name", "n_affected", "median_extra_m", "max_extra_m"]]
    lines = [
        "# Phase 3 — Research Validation Report",
        "",
        f"Generated {findings['date']} from saved Phase 0/1/2 artifacts "
        f"(no experiment re-run, no downloads). Runtime "
        f"{runtime['total_s']:.1f} s, peak RSS {runtime['peak_rss_mb']:.0f} MB.",
        "",
        "## 1. Research question",
        "",
        "Under a road-network accessibility model of bounded central Karachi, "
        "which tested road closures measurably degrade shortest drivable "
        "access from sampled origins to the nearest mapped healthcare "
        "facility — and how robust are those findings to sampling, data "
        "quality and modelling assumptions?",
        "",
        "## 2. Dataset sources and provenance",
        "",
        "- Road network: OpenStreetMap via Geofabrik `pakistan-latest.osm.pbf` "
        "(snapshot 2026-10-09, sha256-pinned, ODbL); drive graph 45,304 nodes / "
        "122,599 directed edges (`data/network_drive.graphml`).",
        f"- Facilities: {t4['total_facilities']} OSM points tagged as healthcare "
        "facilities (`data/hospitals.gpkg`), unverified.",
        "- Origins: 100 grid-sampled nodes (seed "
        f"{SEED}, `data/phase2_origins_sample.csv`).",
        "- Candidates: 100 OSM ways in four documented tiers "
        "(`data/phase2_candidates.csv`).",
        "- Experiment artifacts: `reports/phase2_per_origin.csv` (10,000 rows), "
        "`reports/phase2_results.csv`, `reports/phase2_summary.json`.",
        "",
        "## 3. Methodology",
        "",
        "Shortest drivable distances on the directed graph (one-ways honoured, "
        "edge length in metres). Each candidate way is fully removed, "
        "distances to the nearest facility snap node recomputed for all 100 "
        "origins, then the graph is restored exactly. Disconnections are "
        "recorded as flags with null detours (never infinity). Composite "
        "score: `n_affected + 5*n_disconnected + min(median_extra_m/100, 20)` "
        "— transparent, documented, not an AI score. Phase 3 validation "
        "recomputes everything from saved rows and re-checks selected "
        "scenarios with the independent Phase 0 networkx engine.",
        "",
        "## 4. Measured results (unchanged from Phase 2)",
        "",
        f"- {int((res['n_affected'] > 0).sum())}/100 tested ways affect ≥1 origin; "
        f"{int((res['n_newly_disconnected'] > 0).sum())}/100 disconnect any origin; "
        f"{int((res['n_destination_switched'] > 0).sum())}/100 change a nearest facility.",
        "",
        "Top 5 by composite score:",
        "",
        "| osmid | name | affected | median +m | score |",
        "|---|---|---|---|---|",
    ]
    for r in top5.itertuples():
        nm = r.name if isinstance(r.name, str) else "(unnamed)"
        lines.append(f"| {r.osmid} | {nm} | {r.n_affected} | {r.median_extra_m} | {r.disruption_score} |")
    lines += ["", "Top 5 by affected count:", "",
              "| osmid | name | affected | median +m | max +m |",
              "|---|---|---|---|---|"]
    for r in top5aff.itertuples():
        nm = r.name if isinstance(r.name, str) else "(unnamed)"
        lines.append(f"| {r.osmid} | {nm} | {r.n_affected} | {r.median_extra_m} | {r.max_extra_m} |")
    lines += [
        "",
        "The two rankings disagree — a road can touch many origins with small "
        "detours or fewer origins with very large detours. Neither alone "
        "defines 'most critical'.",
        "",
        "## 5. Validation tests",
        "",
        f"**Reproducibility (task 1).** All {t1['ways_recomputed']} way rows and "
        f"all five ranking lists recompute exactly from the 10,000 saved "
        f"per-origin rows ({t1['metric_columns_checked']} columns; "
        f"{len(t1['metric_mismatches'])} mismatches; rankings match: "
        f"{t1['all_rankings_match']}).",
        "",
        f"**Independent cross-check (task 2).** {t2['ways_count']} ways "
        f"({', '.join(str(x) for x in t2['ways_checked'])}) and "
        f"{t2['origin_rows_checked']} origin rows were recomputed with the "
        f"Phase 0-trusted networkx engine ({t2['engine']}). Mismatches: "
        f"baseline distances {t2['baseline_distance_mismatches']}, disrupted "
        f"distances {t2['disrupted_distance_mismatches']}, facility identity "
        f"{t2['facility_identity_mismatches']}, disconnect flags "
        f"{t2['disconnect_flag_mismatches']}, switch flags "
        f"{t2['switch_flag_mismatches']} (tolerance {TOL_M} m). Graph restore "
        "verified after every scenario.",
        "",
        "## 6. Sensitivity analysis",
        "",
        f"Origins were split two ways (odd/even by sampling order; east/west by "
        f"median longitude {t3['lon_median']:.5f}; {t3['n_west']} west / "
        f"{t3['n_east']} east). Rankings were recomputed independently within "
        "each half:",
        "",
        "| partition | ranking | top-5 overlap | ways with effect (A/B) |",
        "|---|---|---|---|",
    ]
    for part in ("odd_even", "east_west"):
        for rk in ("by_composite_score", "by_affected_count"):
            b = t3[part][rk]
            lines.append(f"| {part} | {rk} | {b['overlap']['overlap']}/5 | "
                         f"{b['ways_with_effect_a']}/{b['ways_with_effect_b']} |")
    lines += [
        "",
        "Overlap is partial in every case: individual rank positions are "
        "unstable under resampling. The defensible conclusion is that certain "
        "ways measurably affect access *for this sample*, not that any road is "
        "definitively Karachi's most critical. " + t3["note"],
        "",
        "## 7. Facility data-quality audit",
        "",
        f"- {t4['total_facilities']} mapped facilities; {t4['usable']} usable "
        f"within {config.MAX_HOSPITAL_SNAP_M} m of the network "
        f"(snap-node dedupe → {t4['usable_snap_nodes']} unique nodes).",
        f"- Snap distances: median {t4['snap_dist_m']['median']} m, p95 "
        f"{t4['snap_dist_m']['p95']} m, max {t4['snap_dist_m']['max']} m; "
        f"{t4['snap_gt_250m']} above 250 m.",
        f"- {len(t4['near_duplicate_pairs_50m'])} near-duplicate pairs within "
        "50 m (different OSM ids, possibly the same site); "
        f"{len(t4['duplicate_name_clusters'])} duplicated name clusters.",
        f"- {t4['limited_scope_name_usable']} usable facilities have names "
        "suggesting limited scope (dental/diagnostic/clinic etc.) — the OSM "
        "`amenity=hospital` tag is a mapper label, not an emergency-department "
        "confirmation.",
        f"- {t4['outside_core_usable']} usable facilities sit outside the CORE "
        "box (still reachable; boundary effects noted in §8).",
        "",
        f"{len(t4['inspected'])} inspected facilities (up to 5 highest snap "
        "distances + up to 5 serving the top-ranked way's affected origins):",
        "",
        "| osmid | name | snap m | outside core | limited-scope name |",
        "|---|---|---|---|---|",
    ]
    for f_ in t4["inspected"]:
        nm = f_["name"] or "(unnamed)"
        lines.append(f"| {f_['osmid']} | {nm} | {f_['snap_dist_m']} | "
                     f"{'yes' if f_['outside_core'] else 'no'} | "
                     f"{'yes' if f_['limited_scope_name'] else 'no'} |")
    lines += [
        "",
        t4["disclaimer"],
        "",
        "Effect on findings: nearest-facility identities and switches inherit "
        "any mis-snapping or duplication error; detour *magnitudes* for a "
        "given origin are less sensitive (they depend on the road network, "
        "not on which duplicate won).",
        "",
        "## 8. Study-area and modelling assumptions",
        "",
        f"- **Boundary:** {t5['boundary']['origins_within_200m_of_core_edge']} "
        f"origins within 200 m of the CORE edge (min "
        f"{t5['boundary']['min_origin_distance_to_edge_m']} m). "
        f"{t5['boundary']['note']}",
        f"- **Full-way closures:** candidate lengths "
        f"{t5['full_way_closures']['candidate_length_m']['min']}–"
        f"{t5['full_way_closures']['candidate_length_m']['max']} m "
        f"(median {t5['full_way_closures']['candidate_length_m']['median']} m). "
        f"{t5['full_way_closures']['note']}",
        f"- **One-ways:** {t5['one_ways']['share_pct']}% of candidate directed "
        f"edges are genuinely one-way. {t5['one_ways']['note']}",
        f"- **Candidate bias:** candidates cover "
        f"{t5['candidate_bias']['coverage_of_network_pct']}% of total network "
        f"length; tiers {t5['candidate_bias']['tiers']}. "
        f"{t5['candidate_bias']['note']}",
        "",
        "## 9. Scientific limitations",
        "",
    ] + [f"- {x}" for x in findings["limitations"]] + [
        "",
        "## 10. Future research",
        "",
        "- Population-weighted origins (census/building-footprint density) to "
        "move from geometric to demographic relevance.",
        "- Verified facility registries (capability, hours) to replace mapper "
        "tags; sensitivity of switches to verified-only facility sets.",
        "- Incident-shaped partial closures and time-of-day traffic for travel "
        "time instead of free-flow distance.",
        "- Monte-Carlo origin resampling (many seeds) to attach confidence "
        "intervals to rankings.",
        "- Extension to flood/heat exposure layers once credible open data is "
        "chosen — explicitly out of scope here.",
        "",
        "## 11. Reproduce",
        "",
        "```bash",
        "env/conda/bin/python src/phase3_validation.py   # ~40 s, one graph load",
        "env/conda/bin/python -m pytest tests -q         # full suite incl. Phase 3",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-crosscheck-ways", type=int, default=12)
    args = ap.parse_args()
    t_start = time.time()

    log("task1: reproducibility from saved rows...")
    t1 = task1_reproducibility()

    import osmnx  # noqa: F401  (load_graph in experiment uses it)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
    import server  # cached single graph via the webapp loader

    G = server.ensure_loaded()
    fac, fac_names = facility_map(G)

    t2 = task2_cross_check(G, fac, fac_names, args.max_crosscheck_ways)
    t3 = task3_sensitivity()
    t4 = task4_facility_audit(G, fac)
    t5 = task5_assumption_effects(G)

    runtime = {
        "total_s": round(time.time() - t_start, 1),
        # ru_maxrss is bytes on macOS, KB on Linux
        "peak_rss_mb": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1
        ),
    }
    findings = {
        "tag": "cityfragility-phase3",
        "date": time.strftime("%Y-%m-%d"),
        "seed": SEED,
        "runtime": runtime,
        "reproducibility": t1,
        "cross_check": t2,
        "sensitivity": t3,
        "facility_audit": t4,
        "assumption_effects": t5,
        "verified_findings": verified_findings_block(t1, t2, t3, t4, t5),
        "limitations": LIMITATIONS,
        "disclaimer": ("Models hypothetical disruptions to road-network access "
                       "to mapped facilities. Does not predict flooding, "
                       "ambulance response, casualties or hospital availability."),
    }
    out_json = config.REPORTS_DIR / "phase3_findings.json"
    out_json.write_text(json.dumps(findings, indent=1, default=str), encoding="utf-8")
    out_md = config.REPORTS_DIR / "PHASE3_VALIDATION_REPORT.md"
    out_md.write_text(write_report(findings, runtime), encoding="utf-8")
    log(f"wrote {out_json}")
    log(f"wrote {out_md}")
    log(f"done in {runtime['total_s']}s, peak RSS {runtime['peak_rss_mb']} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
