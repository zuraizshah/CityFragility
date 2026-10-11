"""Extract the bounded Karachi road network + hospital features from the
official Geofabrik Pakistan PBF (offline path, Phase 0 recovery).

Inputs:
  data/source/pakistan-latest.osm.pbf   (sha256 in reports/pbf_extraction_report.json)

Outputs (same paths the existing pipeline expects):
  data/network_drive.graphml            drivable directed graph, one-ways honoured
  data/hospitals.gpkg (layer hospitals)  deduped OSM-tagged hospitals w/ source tags
  reports/pbf_extraction_report.json     counts, timings, provenance
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

PBF_PATH = config.DATA_DIR / "source" / "pakistan-latest.osm.pbf"

UNCERTAINTY_NOTES = [
    "OSM tags record what the mapper asserted, not verified service capability.",
    "amenity/healthcare=hospital does not confirm 24/7 emergency or trauma capability.",
    "Some entries may be clinics, dispensaries or closed facilities mis-tagged as hospitals.",
    "No verification against any official health-facility registry was performed.",
    "Bed counts, ambulance availability and arrival times are not present in the data.",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def sanitize_graph_for_graphml(G) -> list[str]:
    """Coerce node/edge/graph attrs to GraphML-safe scalars OSMnx can reload.

    Handles the two known pyrosm->OSMnx mismatches:
      - edge 'oneway'/'reversed': pyrosm keeps raw tag values ('yes'), OSMnx
        reload converts them strictly to bool/'True'/'False'
      - edge 'osmid': must reload as int (multi-way simplifications keep the
        full id list in a parallel 'osmids' string attribute)
    """
    changed: list[str] = []

    def as_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, (list, tuple, set)):
            return any(as_bool(x) for x in v)
        return str(v) in {"True", "yes", "true", "1", "-1", "reverse"}

    def clean_edge(d: dict) -> None:
        for k in ("oneway", "reversed"):
            if k in d and not isinstance(d[k], bool):
                d[k] = as_bool(d[k])
                changed.append(f"edge.{k}->{d[k]}")
        if "osmid" in d:
            v = d["osmid"]
            if isinstance(v, (list, tuple, set)):
                ivals = [int(x) for x in v]
                d["osmids"] = " ".join(str(x) for x in ivals)
                d["osmid"] = ivals[0]
                changed.append(f"edge.osmid:list({len(ivals)})->first int + osmids")
            elif isinstance(v, str):
                d["osmid"] = int(v)
                changed.append("edge.osmid:str->int")
            elif isinstance(v, float):
                d["osmid"] = int(v)

    def clean(d: dict, edge: bool = False) -> None:
        if edge:
            clean_edge(d)
        for k, v in list(d.items()):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                del d[k]
                changed.append(f"removed-none:{k}")
            elif isinstance(v, bool) or isinstance(v, (int, float, str)):
                pass
            elif isinstance(v, (list, tuple, set)):
                d[k] = " ".join(str(x) for x in v)  # OSMnx-style list encoding
                changed.append(f"list->str:{k}")
            else:
                d[k] = str(v)
                changed.append(f"{type(v).__name__}->str:{k}")

    for _, d in G.nodes(data=True):
        clean(d)
    for _, _, d in G.edges(data=True):
        clean(d, edge=True)
    clean(G.graph)
    return sorted(set(changed))


def dedupe_hospitals(gdf):
    import geopandas as gpd
    import pandas as pd

    gdf = gdf.copy()
    if "element_type" not in gdf.columns:
        gdf["element_type"] = [
            "node" if geom.geom_type == "Point" else "way"
            for geom in gdf.geometry
        ]
    gdf["element_type"] = gdf["element_type"].astype(str)
    gdf["osmid"] = gdf["osmid"].astype("int64")
    raw = len(gdf)
    gdf = gdf.drop_duplicates(subset=["element_type", "osmid"])
    after_id = len(gdf)

    gdf["norm_name"] = gdf["name"].map(normalize_name) if "name" in gdf.columns else ""
    proj = gdf.geometry.representative_point().to_crs(config.ANALYSIS_CRS)
    x, y = proj.x.to_numpy(), proj.y.to_numpy()
    names = gdf["norm_name"].tolist()
    n = len(gdf)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    R = 75.0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = x[i] - x[j], y[i] - y[j]
            if dx * dx + dy * dy > R * R:
                continue
            if names[i] and names[j]:
                if names[i] == names[j]:
                    union(i, j)
            else:
                union(i, j)
    gdf["dup_group"] = [find(i) for i in range(n)]
    gdf["_completeness"] = gdf.notna().sum(axis=1)
    gdf["_is_poly"] = ~gdf.geometry.geom_type.eq("Point")
    gdf = gdf.sort_values(
        ["dup_group", "_completeness", "_is_poly", "osmid"],
        ascending=[True, False, False, True],
    )
    gdf["is_primary"] = ~gdf.duplicated(subset=["dup_group"], keep="first")
    kept = gdf[gdf["is_primary"]].copy()
    return raw, after_id, len(kept), kept


def main() -> int:
    from pyrosm import OSM
    import osmnx as ox

    config.configure_osmnx()
    if not PBF_PATH.exists():
        print(f"[pbf] missing {PBF_PATH}")
        return 1

    report: dict = {"retrieval_date": config.today()}
    report["pbf"] = {
        "path": str(PBF_PATH.relative_to(config.PROJECT_ROOT)),
        "bytes": PBF_PATH.stat().st_size,
        "sha256": sha256_of(PBF_PATH),
        "source_url": "https://download.geofabrik.de/asia/pakistan-latest.osm.pbf",
        "source_index": "https://download.geofabrik.de/asia/pakistan.html",
        "index_states": "149 MB, OSM data up to 2026-10-09T20:21:04Z (fetched 2026-10-10)",
    }
    bbox = list(config.BUFFER_BBOX)  # [minx, miny, maxx, maxy] = lon/lat
    report["bounding_box_wgs84_wsen"] = bbox

    # ---------------- roads ----------------
    t0 = time.time()
    osm = OSM(str(PBF_PATH), bounding_box=bbox)
    nodes, edges = osm.get_network(network_type="driving", nodes=True)
    t_parse = time.time() - t0
    print(f"[pbf] parsed driving network in {t_parse:.1f}s: "
          f"{len(nodes)} nodes / {len(edges)} way-segments (pre-graph)")

    t1 = time.time()
    G = osm.to_graph(
        nodes,
        edges,
        graph_type="networkx",
        direction="oneway",
        network_type="driving",
        osmnx_compatible=True,
        retain_all=False,
        simplify=True,
    )
    t_graph = time.time() - t1
    print(f"[pbf] graph built in {t_graph:.1f}s: "
          f"{G.number_of_nodes()} nodes / {G.number_of_edges()} directed edges")

    # one-way stats: directed edges whose reverse pair is absent
    one_way_edges = sum(
        1
        for u, v in G.edges()
        if not G.has_edge(v, u)
    )
    report["network"] = {
        "parse_seconds": round(t_parse, 2),
        "graph_build_seconds": round(t_graph, 2),
        "nodes": G.number_of_nodes(),
        "directed_edges": G.number_of_edges(),
        "directed_edges_without_reverse (one-way segments)": one_way_edges,
        "network_type": "driving",
        "direction_policy": "pyrosm to_graph(direction='oneway', network_type='driving'): "
                            "OSM oneway tag honoured; default OSM two-way otherwise",
        "simplified": True,
    }

    # required attrs
    missing = []
    sample_n = next(iter(G.nodes))
    if "x" not in G.nodes[sample_n] or "y" not in G.nodes[sample_n]:
        missing.append("node x/y")
    sample_e = next(iter(G.edges(keys=True)))
    if "length" not in G.edges[sample_e]:
        missing.append("edge length")
    report["network"]["missing_required_attrs"] = missing
    if missing:
        print(f"[pbf] MISSING ATTRS: {missing}")
        return 1

    changes = sanitize_graph_for_graphml(G)
    report["network"]["graphml_attr_coercions"] = changes[:40]

    ox.save_graphml(G, config.NETWORK_PATH)
    # roundtrip verification
    G2 = ox.load_graphml(config.NETWORK_PATH)
    rt_ok = (G2.number_of_nodes() == G.number_of_nodes()
             and G2.number_of_edges() == G.number_of_edges())
    report["network"]["graphml_roundtrip_ok"] = rt_ok
    print(f"[pbf] graphml saved+reloaded roundtrip ok: {rt_ok} "
          f"({G2.number_of_nodes()} nodes / {G2.number_of_edges()} edges) "
          f"-> {config.NETWORK_PATH}")
    if not rt_ok:
        return 1

    # ---------------- hospitals ----------------
    t2 = time.time()
    import pandas as pd

    frames = []
    for tag_key in ("amenity", "healthcare"):
        try:
            part = osm.get_pois(custom_filter={tag_key: ["hospital"]})
            print(f"[pbf] get_pois {{{tag_key}: hospital}} -> {len(part)} rows, "
                  f"cols={list(part.columns)[:12]}")
            if len(part):
                part["_matched_tag"] = tag_key
                frames.append(part)
        except Exception as exc:  # noqa: BLE001
            print(f"[pbf] get_pois failed for {tag_key}: {type(exc).__name__}: {exc}")
    t_pois = time.time() - t2
    if not frames:
        print("[pbf] no hospital POIs extracted")
        return 1

    import geopandas as gpd

    cols = sorted({c for f in frames for c in f.columns})
    pois = gpd.GeoDataFrame(
        pd.concat([f.reindex(columns=cols) for f in frames], ignore_index=True),
        geometry="geometry",
        crs=frames[0].crs,
    )
    # pyrosm POI frames use 'id'/'osm_type'; pipeline expects 'osmid'/'element_type'
    if "osmid" not in pois.columns and "id" in pois.columns:
        pois = pois.rename(columns={"id": "osmid"})
    if "osm_type" in pois.columns:
        pois["element_type"] = pois["osm_type"].astype(str).str.lower()
    if "osmid" not in pois.columns:
        print(f"[pbf] no osmid column; columns={list(pois.columns)}")
        return 1
    if "name" not in pois.columns:
        pois["name"] = None

    raw_rows, unique_rows, kept_rows, kept = dedupe_hospitals(pois)

    # keep source tags
    keep_cols = ["element_type", "osmid", "name"]
    for c in ("amenity", "healthcare", "emergency", "operator", "operator:type",
              "addr:city", "addr:street", "opening_hours", "beds", "wheelchair",
              "_matched_tag"):
        if c in kept.columns and c not in keep_cols:
            keep_cols.append(c)
    out = kept[keep_cols + ["geometry"]].copy()
    config.HOSPITALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if config.HOSPITALS_PATH.exists():
        config.HOSPITALS_PATH.unlink()
    out.to_file(config.HOSPITALS_PATH, layer="hospitals", driver="GPKG")

    tag_freq = {c: int(out[c].notna().sum()) for c in keep_cols if c not in
                {"element_type", "osmid", "geometry"}}
    report["hospitals"] = {
        "extract_seconds": round(t_pois, 2),
        "raw_rows_both_tag_queries": raw_rows,
        "unique_osm_elements": unique_rows,
        "duplicate_elements_removed_75m_name": unique_rows - kept_rows,
        "facilities_kept": kept_rows,
        "tag_frequency": tag_freq,
        "geometry_types": {str(k): int(v) for k, v in out.geometry.geom_type.value_counts().items()},
        "saved_gpkg": str(config.HOSPITALS_PATH.relative_to(config.PROJECT_ROOT)),
        "uncertainty_notes": UNCERTAINTY_NOTES,
    }
    print(f"[pbf] hospitals: raw={raw_rows} unique={unique_rows} kept={kept_rows} "
          f"-> {config.HOSPITALS_PATH}")

    report["total_seconds"] = round(time.time() - t0, 2)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.REPORTS_DIR / "pbf_extraction_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[pbf] report -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
