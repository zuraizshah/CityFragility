"""Retrieve OSM-tagged hospitals in the buffer area, deduplicate, report tags.

Sources: Overpass (amenity=hospital OR healthcare=hospital) via OSMnx
features_from_polygon, with raw response caching.  No facility or
coordinate is invented: every row originates from an OSM element.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from download_network import snapshot_cache

UNCERTAINTY_NOTES = [
    "OSM tags record what the mapper asserted, not verified service capability.",
    "amenity/healthcare=hospital does not confirm 24/7 emergency or trauma capability.",
    "Some entries may be clinics, dispensaries or closed facilities mis-tagged as hospitals.",
    "No verification against any official health-facility registry was performed.",
    "Bed counts, ambulance availability and arrival times are not present in the data.",
]


def normalize_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def main() -> int:
    ox = config.configure_osmnx()
    t0 = time.time()
    tags = {"amenity": "hospital", "healthcare": "hospital"}
    print(f"[hospitals] endpoint: {config.OVERPASS_URL}")
    print(f"[hospitals] tags: {tags}")
    try:
        gdf = ox.features_from_polygon(config.BUFFER_POLYGON, tags=tags)
    except Exception as exc:  # noqa: BLE001
        print(f"[hospitals] FAILED after {time.time() - t0:.1f}s: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - t0

    raw_count = len(gdf)
    if isinstance(gdf.index, pd.RangeIndex) or "osmid" not in gdf.columns:
        print(f"[hospitals] unexpected frame: index={type(gdf.index).__name__} cols={list(gdf.columns)[:8]}")
        return 1

    # 1) intrinsic dedupe: unique OSM element identity
    gdf = gdf.copy()
    gdf["element_type"] = gdf["element_type"].astype(str)
    gdf["osmid"] = gdf["osmid"].astype("int64")
    before_id = len(gdf)
    gdf = gdf.drop_duplicates(subset=["element_type", "osmid"])
    after_id = len(gdf)

    # 2) spatial/name dedupe: same facility often mapped as node + way
    rep = gdf.geometry.representative_point()
    gdf["rep_lon"] = rep.x
    gdf["rep_lat"] = rep.y
    gdf["norm_name"] = gdf["name"].map(normalize_name) if "name" in gdf.columns else ""

    # project for metre distances (UTM 42N)
    rep_proj = (
        gpd_points(gdf)
        .to_crs(config.ANALYSIS_CRS)
    )
    x = rep_proj.x.to_numpy()
    y = rep_proj.y.to_numpy()

    parent = list(range(len(gdf)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    coords = list(zip(x, y))
    names = gdf["norm_name"].tolist()
    n = len(gdf)
    DUP_RADIUS_M = 75.0
    for i in range(n):
        for j in range(i + 1, n):
            dx = coords[i][0] - coords[j][0]
            dy = coords[i][1] - coords[j][1]
            if dx * dx + dy * dy > DUP_RADIUS_M * DUP_RADIUS_M:
                continue
            # merge when names match, or when one side has no name
            if names[i] and names[j]:
                if names[i] == names[j]:
                    union(i, j)
            else:
                union(i, j)

    gdf["dup_group"] = [find(i) for i in range(n)]

    # keep the most tag-complete element per group (more known columns, then polygon over node)
    col_counts = gdf.notna().sum(axis=1)
    gdf["_completeness"] = col_counts
    gdf["_is_poly"] = (gdf.geometry.type == "Polygon") | (gdf.geometry.type == "MultiPolygon")
    gdf = gdf.sort_values(
        ["dup_group", "_completeness", "_is_poly", "osmid"],
        ascending=[True, False, False, True],
    )
    gdf["is_primary"] = ~gdf.duplicated(subset=["dup_group"], keep="first")
    kept = gdf[gdf["is_primary"]].copy()
    n_dup_removed = after_id - len(kept)

    dup_detail = []
    kept_by_group = kept.set_index("dup_group")
    for group_id, sub in gdf[~gdf["is_primary"]].groupby("dup_group"):
        kept_row = kept_by_group.loc[group_id]
        dup_detail.append(
            {
                "kept_element": f"{kept_row['element_type']}_{int(kept_row['osmid'])}",
                "kept_name": kept_row.get("name"),
                "dropped_elements": [
                    f"{r['element_type']}_{int(r['osmid'])}" for _, r in sub.iterrows()
                ],
                "dropped_names": [v for v in sub.get("name", []) if isinstance(v, str)],
            }
        )

    # save GeoPackage with all original source columns + dedupe bookkeeping
    out = kept.drop(columns=["_completeness", "_is_poly"], errors="ignore")
    config.HOSPITALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if config.HOSPITALS_PATH.exists():
        config.HOSPITALS_PATH.unlink()
    out.to_file(config.HOSPITALS_PATH, layer="hospitals", driver="GPKG")

    # tag frequency table (source tags actually present)
    tag_cols = [
        c
        for c in out.columns
        if c not in {"geometry", "element_type", "osmid", "rep_lon", "rep_lat",
                     "norm_name", "dup_group", "is_primary"}
    ]
    tag_freq = {c: int(out[c].notna().sum()) for c in tag_cols}
    tag_freq = dict(sorted(tag_freq.items(), key=lambda kv: (-kv[1], kv[0])))

    snap = snapshot_cache("hospitals")

    osm_ts = next(
        (s["osm_timestamp_osm_base"] for s in snap if s["osm_timestamp_osm_base"]), None
    )

    report = {
        "retrieval_date": config.today(),
        "overpass_endpoint": config.OVERPASS_URL,
        "query_tags": tags,
        "polygon_wgs84_wsen": list(config.BUFFER_BBOX),
        "elapsed_seconds": round(elapsed, 2),
        "raw_elements_returned": int(raw_count),
        "unique_osm_elements": int(after_id),
        "duplicate_elements_removed_spatial_name_75m": int(n_dup_removed),
        "facilities_kept": int(len(kept)),
        "duplicate_groups_detail": dup_detail,
        "geometry_types": {str(k): int(v) for k, v in out.geometry.type.value_counts().items()},
        "tag_frequency": tag_freq,
        "osm_timestamp_osm_base": osm_ts,
        "raw_response_snapshots": snap,
        "uncertainty_notes": UNCERTAINTY_NOTES,
        "saved_gpkg": str(config.HOSPITALS_PATH),
    }
    config.HOSPITALS_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"[hospitals] OK in {elapsed:.1f}s: raw={raw_count} unique={after_id} "
        f"dup_removed={n_dup_removed} kept={len(kept)}"
    )
    print(f"[hospitals] saved -> {config.HOSPITALS_PATH}")
    print(f"[hospitals] report -> {config.HOSPITALS_REPORT}")
    return 0


def gpd_points(gdf):
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoSeries(
        [Point(xy) for xy in zip(gdf["rep_lon"], gdf["rep_lat"])],
        index=gdf.index,
        crs="EPSG:4326",
    )


if __name__ == "__main__":
    raise SystemExit(main())
