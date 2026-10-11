"""CityFragility Phase 1 — interactive road-closure simulator backend.

Loads the REAL Phase 0 graph once (module-level singleton, never duplicated)
and exposes it over a small FastAPI app for a Leaflet front end.

Design rules:
- Reuse the verified routing engine in ``src/routing.py`` unchanged.
- Mutations (remove_way / restore_edges) happen under a global lock and are
  always reversed before the response returns; the in-memory graph stays at
  the baseline state between requests.
- Never send the full graph to the browser: only a filtered renderable
  subset, hospital points, origin points, and computed route polylines.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from pathlib import Path

# src/ sits next to webapp/ under the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config
import networkx as nx
import pandas as pd
from routing import (
    dist_of,
    distances_to_targets,
    is_disconnected,
    remove_way,
    restore_edges,
)

# ---------------------------------------------------------------------------
# Module-level singletons (graph cached for the process lifetime)
# ---------------------------------------------------------------------------
_G: nx.MultiDiGraph | None = None
_ORIGINS: pd.DataFrame | None = None
_HOSPITALS: dict | None = None  # {"nodes": set[int], "records": list[dict]}
_CANDIDATES: list[dict] | None = None
_NETWORK_GEOJSON: dict | None = None
_LOCK = threading.Lock()  # serialises graph mutation + recompute
_STARTUP_S = 0.0

# Hospital facilities are OSM-tagged, not clinically verified. Wording carried
# over from the Phase 0 uncertainty notes.
UNVERIFIED_FACILITY_NOTE = (
    "Unverified OSM facility. Tagged amenity/healthcare=hospital by mappers; "
    "this does not confirm 24/7 emergency or trauma capability, and no official "
    "health registry was checked."
)

# Renderable road classes only. Measured on the real graph: residential +
# service alone are ~97k edges (too heavy for a browser). Major roads
# (motorway..tertiary + links) across the full BUFFER = 21,117 edges (~5 MB),
# which keeps the arterial structure and every candidate closure segment
# visible without overloading the client.
RENDER_HIGHWAY_FILTER = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link",
}


def _log(msg: str) -> None:
    print(f"[webapp] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Loading (once per process)
# ---------------------------------------------------------------------------
def load_graph() -> nx.MultiDiGraph:
    global _G, _STARTUP_S
    if _G is not None:
        return _G
    t0 = time.time()
    import osmnx as ox

    if not config.NETWORK_PATH.exists():
        raise FileNotFoundError(
            f"network not found at {config.NETWORK_PATH}; run Phase 0 extraction"
        )
    _G = ox.load_graphml(config.NETWORK_PATH)
    _STARTUP_S = time.time() - t0
    _log(f"graph loaded once in {_STARTUP_S:.2f}s: "
         f"{_G.number_of_nodes()} nodes / {_G.number_of_edges()} edges")
    return _G


def load_origins() -> pd.DataFrame:
    global _ORIGINS
    if _ORIGINS is not None:
        return _ORIGINS
    _ORIGINS = pd.read_csv(config.ORIGINS_SNAPPED_PATH)
    _log(f"origins loaded: {len(_ORIGINS)}")
    return _ORIGINS


def load_hospitals(G: nx.MultiDiGraph) -> dict:
    """Snap real mapped hospital facilities to the graph via a UTM KDTree.

    Uses a coordinate-only index (no second graph copy), matching the Phase 0
    snapping approach (EPSG:32642 + 300 m threshold). osmnx's nearest_nodes
    uses the same KDTree method on projected coordinates, so results match.
    """
    global _HOSPITALS
    if _HOSPITALS is not None:
        return _HOSPITALS

    import geopandas as gpd
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
    tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)

    node_ids = list(G.nodes())
    coords_utm = [tr.transform(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids]
    tree = cKDTree(coords_utm)

    records = []
    hosp_nodes: set[int] = set()
    for _, r in hospitals.iterrows():
        pt = r.geometry.representative_point()
        hx, hy = tr.transform(pt.x, pt.y)
        dist, idx = tree.query([hx, hy])
        node = int(node_ids[idx])
        snap_ok = float(dist) <= config.MAX_HOSPITAL_SNAP_M
        if snap_ok:
            hosp_nodes.add(node)
        records.append(
            {
                "osmid": int(r["osmid"]),
                "element_type": str(r["element_type"]),
                "name": r["name"] if isinstance(r.get("name"), str) else None,
                "lat": float(pt.y),
                "lon": float(pt.x),
                "snap_node": node,
                "snap_dist_m": round(float(dist), 2),
                "usable": bool(snap_ok),
                "unverified": True,
                "note": UNVERIFIED_FACILITY_NOTE,
            }
        )
    _HOSPITALS = {"nodes": hosp_nodes, "records": records}
    _log(f"hospitals: {len(records)} mapped, {len(hosp_nodes)} unique usable snap nodes")
    return _HOSPITALS


# ---------------------------------------------------------------------------
# Phase 4: saved metadata + precomputed artifacts (graph-free serving)
# ---------------------------------------------------------------------------
_META_CACHE: dict | None = None
_VULN_DETAILS: dict | None = None


def server_meta() -> dict:
    """Graph counts + facility counts saved by src/phase4_precompute.py.

    Lets /api/health answer without loading the NetworkX graph.
    """
    global _META_CACHE
    if _META_CACHE is None:
        path = config.DATA_DIR / "server_meta.json"
        _META_CACHE = _load_json(path) if path.exists() else {}
    return _META_CACHE


def _vuln_details_file() -> dict:
    """Per-way detail payloads precomputed once by src/phase4_precompute.py."""
    global _VULN_DETAILS
    if _VULN_DETAILS is None:
        path = config.REPORTS_DIR / "phase2_vuln_details.json"
        _VULN_DETAILS = _load_json(path) if path.exists() else {}
    return _VULN_DETAILS


def ensure_loaded() -> nx.MultiDiGraph:
    G = load_graph()
    load_origins()
    load_hospitals(G)
    return G


# ---------------------------------------------------------------------------
# Routing helpers (metres, one-ways preserved — engine untouched)
# ---------------------------------------------------------------------------
def baseline_distances() -> dict[int, float]:
    G = ensure_loaded()
    if not _HOSPITALS["nodes"]:
        raise RuntimeError("no usable hospital destinations")
    return distances_to_targets(G, _HOSPITALS["nodes"])


def nearest_hospital_forward(G, origin_node):
    """Nearest usable hospital reachable from origin + forward path geometry.

    Runs a forward single-source Dijkstra on the directed graph (origin ->
    every reachable node), then picks the closest hospital node. One-ways are
    preserved because the search never leaves the directed graph.
    Returns (hospital_name, length_m, [[lat, lon], ...]) or (None, None, None).
    """
    try:
        lengths, paths = nx.single_source_dijkstra(G, origin_node, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, None, None
    best_node, best_len, best_path = None, math.inf, None
    for n in _HOSPITALS["nodes"]:
        d = lengths.get(n)
        if d is not None and d < best_len:
            best_node, best_len, best_path = n, d, paths[n]
    if best_node is None:
        return None, None, None
    name = None
    for rec in _HOSPITALS["records"]:
        if rec["snap_node"] == best_node and rec["usable"]:
            name = rec["name"] or f"Unnamed facility (OSM {rec['osmid']})"
            break
    geometry = [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in best_path]
    return name or f"Hospital node {best_node}", float(best_len), geometry


# ---------------------------------------------------------------------------
# Renderable network GeoJSON (built once, cached)
# ---------------------------------------------------------------------------
def network_geojson() -> dict:
    global _NETWORK_GEOJSON
    if _NETWORK_GEOJSON is not None:
        return _NETWORK_GEOJSON
    G = ensure_loaded()
    t0 = time.time()
    features = []
    for u, v, k, d in G.edges(keys=True, data=True):
        hw = d.get("highway")
        if isinstance(hw, (list, tuple)):
            hw = hw[0] if hw else None
        if hw not in RENDER_HIGHWAY_FILTER:
            continue
        osmid = d.get("osmid")
        if isinstance(osmid, (list, tuple, set)):
            osmid = next(iter(osmid))
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [round(float(G.nodes[u]["x"]), 6), round(float(G.nodes[u]["y"]), 6)],
                        [round(float(G.nodes[v]["x"]), 6), round(float(G.nodes[v]["y"]), 6)],
                    ],
                },
                "properties": {
                    "osmid": int(osmid) if osmid is not None else None,
                    "highway": hw,
                    "name": d.get("name") if isinstance(d.get("name"), str) else None,
                    "oneway": bool(d.get("oneway", False)),
                    "length_m": round(float(d.get("length", 0.0)), 1),
                },
            }
        )
    _NETWORK_GEOJSON = {
        "type": "FeatureCollection",
        "generator": "CityFragility Phase 1 — renderable subset of the Phase 0 graph",
        "highway_filter": sorted(RENDER_HIGHWAY_FILTER),
        "features": features,
    }
    _log(f"network geojson: {len(features)} renderable edges in {time.time()-t0:.2f}s")
    return _NETWORK_GEOJSON


def hospitals_geojson() -> dict:
    ensure_loaded()
    return {
        "type": "FeatureCollection",
        "note": UNVERIFIED_FACILITY_NOTE,
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [r["lon"], r["lat"]],
                },
                "properties": {k: v for k, v in r.items() if k not in ("lat", "lon")},
            }
            for r in _HOSPITALS["records"]
        ],
    }


def origins_geojson() -> dict:
    ensure_loaded()
    return {
        "type": "FeatureCollection",
        "note": (
            "Sample origin seeds only — results apply to these six locations, "
            "not to the whole city."
        ),
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(r["snapped_lon"]), float(r["snapped_lat"])],
                },
                "properties": {
                    "name": r["name"],
                    "snap_dist_m": float(r["snap_dist_m"]),
                    "snap_flag": bool(r["snap_flag"]),
                    "source": r["origin_source"],
                    "snapped_node": int(r["snapped_node"]),
                },
            }
            for _, r in load_origins().iterrows()
        ],
    }


# ---------------------------------------------------------------------------
# Closure candidates: Phase 0 tested set + additional on-path testable ways
# ---------------------------------------------------------------------------
def build_candidates() -> list[dict]:
    global _CANDIDATES
    if _CANDIDATES is not None:
        return _CANDIDATES
    saved = config.DATA_DIR / "phase1_candidates.json"
    if _G is None and saved.exists():
        _CANDIDATES = json.loads(saved.read_text(encoding="utf-8"))
        _log(f"candidates loaded from saved artifact ({len(_CANDIDATES)})")
        return _CANDIDATES
    G = ensure_loaded()
    cands: list[dict] = []
    seen: set[int] = set()

    # 1) Phase 0 tested closures (monotonicity + restore already verified)
    if config.CLOSURE_RESULTS.exists():
        payload = json.loads(config.CLOSURE_RESULTS.read_text())
        for c in payload.get("candidates_evaluated", []):
            oid = int(c["osmid"])
            seen.add(oid)
            cands.append(
                {
                    "osmid": oid,
                    "name": c.get("name"),
                    "highways": c.get("highways", []),
                    "length_m": c.get("length_m"),
                    "edges": c.get("edges"),
                    "on_baseline_path_of": c.get("on_baseline_path_of", []),
                    "tested_in_phase0": True,
                    "phase0_total_delta_m": c.get("total_delta_m"),
                    "phase0_any_disconnected": c.get("any_disconnected_origin"),
                }
            )

    # 2) Additional testable ways: ways actually used by Phase 0 baseline
    #    shortest paths (same selection logic as src/analyze.py, capped)
    from analyze import way_summary

    path_meta: dict[int, list[str]] = {}
    origins = load_origins()
    for _, o in origins.iterrows():
        node = int(o["snapped_node"])
        h_node, _h_len = _baseline_nearest_for(G, node)
        if h_node is None:
            continue
        try:
            path = nx.dijkstra_path(G, node, h_node, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        for a, b in zip(path[:-1], path[1:]):
            edata = G.get_edge_data(a, b)
            best = min(edata.values(), key=lambda dd: dd["length"])
            v = best.get("osmid")
            if isinstance(v, str):
                parts = v.split()
                v = int(parts[0]) if parts else None
            if isinstance(v, (int, float)):
                path_meta.setdefault(int(v), []).append(o["name"])

    extras = []
    for w, served in path_meta.items():
        if w in seen:
            continue
        s = way_summary(G, w)
        if s["edges"] == 0 or s["length_m"] > 4000:
            continue
        extras.append(
            {
                "osmid": w,
                "name": s["name"],
                "highways": s["highways"],
                "length_m": s["length_m"],
                "edges": s["edges"],
                "on_baseline_path_of": list(dict.fromkeys(served)),
                "tested_in_phase0": False,
            }
        )
    extras.sort(key=lambda c: (-len(c["on_baseline_path_of"]), -c["length_m"]))
    for e in extras[:12]:
        seen.add(e["osmid"])
        cands.append(e)

    _CANDIDATES = cands
    _log(f"closure candidates: {len(cands)} "
         f"({sum(1 for c in cands if c['tested_in_phase0'])} Phase-0-tested)")
    return cands


_BASELINE_NEAREST: dict[int, tuple] | None = None


def _baseline_nearest_for(G, origin_node):
    """(hospital_node, length) on the baseline graph, memoised per origin."""
    global _BASELINE_NEAREST
    if _BASELINE_NEAREST is None:
        _BASELINE_NEAREST = {}
    if origin_node in _BASELINE_NEAREST:
        return _BASELINE_NEAREST[origin_node]
    try:
        lengths, _ = nx.single_source_dijkstra(G, origin_node, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        _BASELINE_NEAREST[origin_node] = (None, None)
        return None, None
    best_node, best_len = None, math.inf
    for n in _HOSPITALS["nodes"]:
        d = lengths.get(n)
        if d is not None and d < best_len:
            best_node, best_len = n, d
    _BASELINE_NEAREST[origin_node] = (best_node, best_len)
    return best_node, best_len


# ---------------------------------------------------------------------------
# Simulation (atomic: remove -> recompute -> restore, under a global lock)
# ---------------------------------------------------------------------------
def simulate_closure(osmid: int) -> dict:
    G = ensure_loaded()
    osmid = int(osmid)
    with _LOCK:
        t0 = time.time()
        base = baseline_distances()

        removed = remove_way(G, osmid)
        if not removed:
            raise ValueError(f"no edges found for osmid {osmid}")
        try:
            closed = distances_to_targets(G, _HOSPITALS["nodes"])
            per_origin = []
            for _, o in load_origins().iterrows():
                node = int(o["snapped_node"])
                d0 = dist_of(base, node)
                d1 = dist_of(closed, node)
                disc0, disc1 = is_disconnected(d0), is_disconnected(d1)
                # after-route computed while the closure is still applied
                h_a, l_a, geo_a = (None, None, None) if disc1 else nearest_hospital_forward(G, node)
                per_origin.append(
                    {
                        "name": o["name"],
                        "snap_flag": bool(o["snap_flag"]),
                        "snap_dist_m": float(o["snap_dist_m"]),
                        "before_m": None if disc0 else round(float(d0), 2),
                        "after_m": None if disc1 else round(float(d1), 2),
                        "delta_m": None if (disc0 or disc1) else round(float(d1) - float(d0), 2),
                        "disconnected": bool(disc1),
                        "was_disconnected": bool(disc0),
                        "after_route": None if disc1 else {
                            "hospital": h_a,
                            "length_m": None if l_a is None else round(l_a, 2),
                            "geometry": geo_a,
                        },
                    }
                )
        finally:
            restore_edges(G, removed)

        # before-routes computed on the restored (pristine) baseline graph
        base2 = baseline_distances()
        assert all(
            (is_disconnected(dist_of(base2, int(o["snapped_node"])))
             == r["was_disconnected"])
            for _, o in load_origins().iterrows()
            for r in per_origin if r["name"] == o["name"]
        ), "graph not identical after restore (disconnectivity changed)"
        for r in per_origin:
            node = int(
                load_origins().loc[load_origins()["name"] == r["name"], "snapped_node"].iloc[0]
            )
            d0 = dist_of(base2, node)
            h_b, l_b, geo_b = (None, None, None) if is_disconnected(d0) else nearest_hospital_forward(G, node)
            r["before_route"] = None if is_disconnected(d0) else {
                "hospital": h_b,
                "length_m": None if l_b is None else round(l_b, 2),
                "geometry": geo_b,
            }

        return {
            "osmid": osmid,
            "edges_removed": len(removed),
            "per_origin": per_origin,
            "any_disconnected": any(r["disconnected"] for r in per_origin),
            "max_delta_m": max(
                (r["delta_m"] for r in per_origin if r["delta_m"] is not None),
                default=0.0,
            ),
            "compute_ms": round((time.time() - t0) * 1000, 1),
            "restored_ok": True,
            "graph_nodes": G.number_of_nodes(),
            "graph_edges": G.number_of_edges(),
            "note": (
                "Hypothetical closure. Distances are shortest DRIVABLE metres "
                "on the OSM graph with one-ways preserved. Not travel-time, "
                "not ambulance response, not a real closure."
            ),
        }


def restore_baseline() -> dict:
    """Return the exact baseline calculation (graph is already pristine)."""
    G = ensure_loaded()
    with _LOCK:
        t0 = time.time()
        base = baseline_distances()
        rows = []
        for _, o in load_origins().iterrows():
            node = int(o["snapped_node"])
            d = dist_of(base, node)
            rows.append(
                {
                    "name": o["name"],
                    "distance_m": None if is_disconnected(d) else round(float(d), 2),
                    "disconnected": is_disconnected(d),
                }
            )
        return {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "per_origin": rows,
            "compute_ms": round((time.time() - t0) * 1000, 1),
            "note": "Baseline recomputed on the restored graph (closure undone).",
        }


# ---------------------------------------------------------------------------
# Phase 2 — Vulnerability Explorer (reads stored experiment artifacts only)
# ---------------------------------------------------------------------------
_VULN_ROWS: list[dict] | None = None
_VULN_SUMMARY: dict | None = None
_VULN_GEO: dict | None = None
_VULN_DETAIL_CACHE: dict[int, dict] = {}
_VULN_FAC_NODES: dict[int, str] | None = None


def _jsonable_df(df) -> list[dict]:
    return json.loads(df.to_json(orient="records"))


def _scrub_nan(obj):
    """Recursively replace NaN/Inf (non-JSON-compliant) with None."""
    if isinstance(obj, dict):
        return {k: _scrub_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_nan(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _load_json(path):
    import pandas as pd

    return _scrub_nan(json.loads(path.read_text(), parse_constant=lambda c: float("nan")))


def vuln_rows() -> list[dict]:
    global _VULN_ROWS
    if _VULN_ROWS is None:
        path = config.REPORTS_DIR / "phase2_results.csv"
        if not path.exists():
            raise FileNotFoundError(
                "phase2_results.csv missing — run src/phase2_experiment.py first"
            )
        import pandas as pd

        _VULN_ROWS = _jsonable_df(pd.read_csv(path))
    return _VULN_ROWS


def vuln_summary() -> dict:
    global _VULN_SUMMARY
    if _VULN_SUMMARY is None:
        path = config.REPORTS_DIR / "phase2_summary.json"
        if not path.exists():
            raise FileNotFoundError("phase2_summary.json missing — run the experiment")
        _VULN_SUMMARY = _load_json(path)
    return _VULN_SUMMARY


def vuln_roads_geojson() -> dict:
    """Candidate way geometries merged with stored metrics (one pass over G)."""
    global _VULN_GEO
    if _VULN_GEO is not None:
        return _VULN_GEO
    saved = config.DATA_DIR / "phase2_roads.geojson"
    if saved.exists():
        _VULN_GEO = _load_json(saved)
        _log(f"vuln geojson loaded from saved artifact "
             f"({len(_VULN_GEO.get('features', []))} ways)")
        return _VULN_GEO
    G = ensure_loaded()
    rows = {int(r["osmid"]): r for r in vuln_rows()}
    segs: dict[int, list[list[list[float]]]] = {oid: [] for oid in rows}
    for u, v, d in G.edges(data=True):
        osmid = d.get("osmid")
        if isinstance(osmid, (list, tuple, set)):
            osmid = next(iter(osmid))
        if osmid is None or int(osmid) not in segs:
            continue
        segs[int(osmid)].append([
            [round(float(G.nodes[u]["x"]), 6), round(float(G.nodes[u]["y"]), 6)],
            [round(float(G.nodes[v]["x"]), 6), round(float(G.nodes[v]["y"]), 6)],
        ])
    features = []
    for oid, lines in segs.items():
        if not lines:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": lines},
            "properties": {
                "osmid": oid,
                "name": rows[oid].get("name"),
                "n_affected": rows[oid].get("n_affected"),
                "pct_affected": rows[oid].get("pct_affected"),
                "median_extra_m": rows[oid].get("median_extra_m"),
                "max_extra_m": rows[oid].get("max_extra_m"),
                "n_newly_disconnected": rows[oid].get("n_newly_disconnected"),
                "n_destination_switched": rows[oid].get("n_destination_switched"),
                "disruption_score": rows[oid].get("disruption_score"),
                "selection_tier": rows[oid].get("selection_tier"),
            },
        })
    _VULN_GEO = {
        "type": "FeatureCollection",
        "generator": "CityFragility Phase 2 experiment (stored results)",
        "features": features,
    }
    _log(f"vuln geojson: {len(features)} candidate ways")
    return _VULN_GEO


def _vuln_facility_nodes() -> dict[int, str]:
    global _VULN_FAC_NODES
    if _VULN_FAC_NODES is None:
        G = ensure_loaded()
        import geopandas as gpd
        from pyproj import Transformer
        from scipy.spatial import cKDTree

        hospitals = gpd.read_file(config.HOSPITALS_PATH, layer="hospitals")
        tr = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True)
        node_ids = list(G.nodes())
        coords = [tr.transform(G.nodes[n]["x"], G.nodes[n]["y"]) for n in node_ids]
        tree = cKDTree(coords)
        out: dict[int, str] = {}
        for _, r in hospitals.iterrows():
            pt = r.geometry.representative_point()
            hx, hy = tr.transform(pt.x, pt.y)
            dist, idx = tree.query([hx, hy])
            if float(dist) <= config.MAX_HOSPITAL_SNAP_M:
                nm = r["name"] if isinstance(r.get("name"), str) else f"Unnamed OSM {int(r['osmid'])}"
                out[int(node_ids[idx])] = nm
        _VULN_FAC_NODES = out
    return _VULN_FAC_NODES


def vuln_detail(osmid: int) -> dict:
    """Stored per-origin evidence for one way + a live worst-origin example."""
    import pandas as pd

    rows = vuln_rows()
    if int(osmid) not in {int(r["osmid"]) for r in rows}:
        raise ValueError(f"osmid {osmid} not in the Phase 2 experiment set")
    if osmid in _VULN_DETAIL_CACHE:
        return _VULN_DETAIL_CACHE[osmid]

    per_origin = pd.read_csv(config.REPORTS_DIR / "phase2_per_origin.csv")
    po = _jsonable_df(per_origin[per_origin["candidate_osmid"] == int(osmid)])
    meta = next(r for r in rows if int(r["osmid"]) == int(osmid))

    # Phase 4: precomputed payload (same shape, same stored rows + example
    # geometry) — served without touching the graph.
    saved = _vuln_details_file().get(str(int(osmid)))
    if saved is not None:
        _VULN_DETAIL_CACHE[osmid] = saved
        return saved

    # live worst-origin example (one remove->route->restore cycle, ~0.2 s)
    G = ensure_loaded()
    example = None
    worst = None
    for r in po:
        if r["newly_disconnected"]:
            worst = r
            break
        if worst is None or (r["detour_m"] or 0) > (worst["detour_m"] or 0):
            worst = r
    if worst is not None:
        fac = _vuln_facility_nodes()
        with _LOCK:
            origin = int(worst["origin_node"])
            before_path = None
            h_before = None
            try:
                lengths, paths = nx.single_source_dijkstra(G, origin, weight="length")
                best = min(
                    ((h, lengths[h]) for h in fac if h in lengths),
                    key=lambda t: t[1], default=None,
                )
                if best:
                    h_before = fac[best[0]]
                    before_path = [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in paths[best[0]]]
            except Exception:
                pass
            removed = remove_way(G, int(osmid))
            after_path, h_after, disconnected = None, None, False
            try:
                lengths, paths = nx.single_source_dijkstra(G, origin, weight="length")
                best = min(
                    ((h, lengths[h]) for h in fac if h in lengths),
                    key=lambda t: t[1], default=None,
                )
                if best is None:
                    disconnected = True
                else:
                    h_after = fac[best[0]]
                    after_path = [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in paths[best[0]]]
            finally:
                restore_edges(G, removed)
            example = {
                "origin_sample_id": worst["origin_sample_id"],
                "origin_node": origin,
                "origin_lat": G.nodes[origin]["y"],
                "origin_lon": G.nodes[origin]["x"],
                "baseline_m": worst["baseline_m"],
                "disrupted_m": worst["disrupted_m"],
                "detour_m": worst["detour_m"],
                "newly_disconnected": worst["newly_disconnected"],
                "destination_switched": worst["destination_switched"],
                "baseline_facility": h_before,
                "disrupted_facility": h_after,
                "before_geometry": before_path,
                "after_geometry": after_path,
            }

    detail = {
        "meta": meta,
        "per_origin": po,
        "worst_origin_example": example,
        "note": (
            "Per-origin rows are stored experiment outputs. The worst-origin "
            "example geometry is recomputed live from the same verified engine."
        ),
    }
    _VULN_DETAIL_CACHE[osmid] = detail
    return detail


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
def create_app():
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles

    @asynccontextmanager
    async def lifespan(app):
        # Phase 4: the heavyweight graph is NOT loaded at startup. It is
        # lazy-loaded on the first live request (simulate/restore/network/
        # hospitals/origins) so the research tabs (Explorer, Findings) start
        # instantly from saved artifacts. Single copy, no duplication.
        yield

    app = FastAPI(
        title="CityFragility — Phase 1 Road-Closure Simulator",
        version="1.0.0",
        description=(
            "Interactive hypothetical road-closure simulator over a real OSM "
            "driving graph of central Karachi. Distances are shortest "
            "drivable metres with one-ways preserved. Not flood, ambulance, "
            "or population-impact prediction."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/health")
    def health():
        if _G is None:
            meta = server_meta()
            if not meta:
                raise HTTPException(503, "graph not loaded and no server_meta.json")
            return {
                "status": "ok",
                "nodes": meta["nodes"],
                "edges": meta["edges"],
                "startup_s": meta.get("graph_load_s_reference", 0.0),
                "candidates": meta["candidates"],
                "hospitals_total": meta.get("hospitals_total"),
                "hospitals_usable_nodes": meta["hospitals_usable_nodes"],
                "graph_loaded": False,
                "mode": "research",
            }
        G = _G
        return {
            "status": "ok",
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "startup_s": round(_STARTUP_S, 2),
            "candidates": len(build_candidates()),
            "hospitals_total": len(_HOSPITALS["records"]) if _HOSPITALS else None,
            "hospitals_usable_nodes": len(_HOSPITALS["nodes"]) if _HOSPITALS else None,
            "graph_loaded": True,
            "mode": "live",
        }

    @app.get("/api/network")
    def api_network():
        return JSONResponse(network_geojson())

    @app.get("/api/hospitals")
    def api_hospitals():
        return JSONResponse(hospitals_geojson())

    @app.get("/api/origins")
    def api_origins():
        return JSONResponse(origins_geojson())

    @app.get("/api/candidates")
    def api_candidates():
        return {"candidates": build_candidates()}

    @app.post("/api/simulate")
    def api_simulate(osmid: int):
        try:
            return simulate_closure(osmid)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=f"simulation failed: {e}")

    @app.get("/api/restore")
    def api_restore():
        return restore_baseline()

    # ---- Phase 2: Vulnerability Explorer (stored experiment artifacts) ----
    @app.get("/api/vuln/summary")
    def api_vuln_summary():
        try:
            rep_s = config.REPORTS_DIR / "phase2_origin_sampling_report.json"
            rep_c = config.REPORTS_DIR / "phase2_candidate_selection_report.json"
            return {
                "summary": vuln_summary(),
                "rows": vuln_rows(),
                "sampling": _load_json(rep_s) if rep_s.exists() else None,
                "candidates_method": _load_json(rep_c) if rep_c.exists() else None,
            }
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/vuln/roads.geojson")
    def api_vuln_roads():
        try:
            return JSONResponse(vuln_roads_geojson())
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/vuln/detail")
    def api_vuln_detail(osmid: int):
        try:
            return vuln_detail(osmid)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # ---- Phase 3: Research Findings (stored validation artifacts) ----
    @app.get("/api/research")
    def api_research():
        path = config.REPORTS_DIR / "phase3_findings.json"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="phase3_findings.json missing — run src/phase3_validation.py",
            )
        data = _load_json(path)
        audit = data.get("facility_audit") or {}
        dup = audit.get("near_duplicate_pairs_50m")
        repro = data.get("reproducibility") or {}
        cross = data.get("cross_check") or {}
        sens = data.get("sensitivity") or {}
        return {
            "tag": data.get("tag"),
            "date": data.get("date"),
            "runtime": data.get("runtime"),
            "verified_findings": data.get("verified_findings", []),
            "limitations": data.get("limitations", []),
            "disclaimer": data.get("disclaimer"),
            "validation_summary": {
                "reproducibility": {
                    "ways_recomputed": repro.get("ways_recomputed"),
                    "metric_mismatches": len(repro.get("metric_mismatches") or []),
                    "all_rankings_match": repro.get("all_rankings_match"),
                },
                "cross_check": {
                    "engine": cross.get("engine"),
                    "ways_count": cross.get("ways_count"),
                    "origin_rows_checked": cross.get("origin_rows_checked"),
                    "baseline_distance_mismatches": cross.get("baseline_distance_mismatches"),
                    "disrupted_distance_mismatches": cross.get("disrupted_distance_mismatches"),
                    "facility_identity_mismatches": cross.get("facility_identity_mismatches"),
                    "disconnect_flag_mismatches": cross.get("disconnect_flag_mismatches"),
                    "switch_flag_mismatches": cross.get("switch_flag_mismatches"),
                },
            },
            "sensitivity_summary": {
                "odd_even": {
                    "composite_overlap": (sens.get("odd_even") or {}).get("by_composite_score", {}).get("overlap"),
                    "affected_overlap": (sens.get("odd_even") or {}).get("by_affected_count", {}).get("overlap"),
                },
                "east_west": {
                    "composite_overlap": (sens.get("east_west") or {}).get("by_composite_score", {}).get("overlap"),
                    "affected_overlap": (sens.get("east_west") or {}).get("by_affected_count", {}).get("overlap"),
                },
                "note": sens.get("note"),
            },
            "facility_audit_summary": {
                "total_facilities": audit.get("total_facilities"),
                "usable": audit.get("usable"),
                "usable_snap_nodes": audit.get("usable_snap_nodes"),
                "snap_dist_m": audit.get("snap_dist_m"),
                "near_duplicate_pairs": len(dup) if isinstance(dup, list) else dup,
                "duplicate_name_clusters": len(audit.get("duplicate_name_clusters") or {}),
                "limited_scope_name_usable": audit.get("limited_scope_name_usable"),
                "disclaimer": audit.get("disclaimer"),
            },
        }

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
