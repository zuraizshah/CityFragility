"""Download the real OSM driving network for the Karachi buffer area.

Uses OSMnx over the configured Overpass mirror with local response caching.
Saves the GraphML network plus a snapshot (copy + sha256) of every raw
cached Overpass response under data/source/.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def osm_timestamp_from_cache(path: Path) -> str | None:
    """Overpass JSON starts with its osm3s metadata block; read just that."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        m = re.search(r'"timestamp_osm_base"\s*:\s*"([^"]+)"', head)
        return m.group(1) if m else None
    except OSError:
        return None


def snapshot_cache(tag: str) -> list[dict]:
    """Copy raw Overpass cache responses into data/source/ for provenance."""
    config.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for src in sorted(config.CACHE_DIR.glob("*")):
        if not src.is_file():
            continue
        dst = config.SOURCE_DIR / f"{tag}_{src.name}"
        if not dst.exists():
            shutil.copy2(src, dst)
        manifest.append(
            {
                "original": str(src),
                "snapshot": str(dst),
                "bytes": dst.stat().st_size,
                "sha256": sha256_of(dst),
                "osm_timestamp_osm_base": osm_timestamp_from_cache(dst),
            }
        )
    return manifest


def main() -> int:
    ox = config.configure_osmnx()
    t0 = time.time()
    print(f"[network] Overpass endpoint : {config.OVERPASS_URL}")
    print(f"[network] buffer bbox (W,S,E,N): {config.BUFFER_BBOX}")
    try:
        G = ox.graph_from_polygon(
            config.BUFFER_POLYGON, network_type="drive", simplify=True
        )
    except Exception as exc:  # noqa: BLE001 - report any download failure verbatim
        print(f"[network] FAILED after {time.time() - t0:.1f}s: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - t0

    ox.save_graphml(G, config.NETWORK_PATH)
    manifest = snapshot_cache("network")
    n_nodes, n_edges = G.number_of_nodes(), G.number_of_edges()
    print(
        f"[network] OK in {elapsed:.1f}s: {n_nodes} nodes, {n_edges} directed edges "
        f"-> {config.NETWORK_PATH}"
    )

    log = {
        "retrieval_date": config.today(),
        "overpass_endpoint": config.OVERPASS_URL,
        "osmnx_version": ox.__version__,
        "network_type": "drive",
        "simplify": True,
        "polygon_wgs84_wsen": list(config.BUFFER_BBOX),
        "elapsed_seconds": round(elapsed, 2),
        "nodes": n_nodes,
        "directed_edges": n_edges,
        "saved_graphml": str(config.NETWORK_PATH),
        "raw_response_snapshots": manifest,
        "geofabrik_status": {
            "karachi-latest.osm.pbf": "HTTP 404 (no such extract)",
            "pakistan-latest.osm.pbf": "HTTP 404 (server returns 404 for PBF from this network)",
        },
    }
    config.DOWNLOAD_LOG_NETWORK.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[network] log -> {config.DOWNLOAD_LOG_NETWORK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
