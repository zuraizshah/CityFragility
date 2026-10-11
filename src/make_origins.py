"""Resolve sample origin landmarks to real coordinates (Nominatim/OSM).

Network budget: one request per landmark, 20 s timeout, at most 1 retry for
the whole source.  If Nominatim is unreachable, falls back to approximate
landmark anchor coordinates (documented, clearly flagged); the *final*
origin is always the snapped real OSM network node recorded later by
analyze.py, never an invented point.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Approximate anchors used ONLY if Nominatim fails; snapped node is authoritative.
FALLBACK_ANCHORS = {
    "Saddar Chowrangi, Karachi": (24.8634, 67.0126),
    "Empress Market, Karachi": (24.8587, 67.0115),
    "Mazar-e-Quaid, Karachi": (24.8769, 67.0206),
    "Do Talwar, Karachi": (24.8043, 67.0446),
    "DHA Phase 5, Karachi": (24.8085, 67.0625),
    "NIPA Chowrangi, Karachi": (24.8640, 67.0700),
}


def in_core(lon: float, lat: float) -> bool:
    w, s, e, n = config.CORE_BBOX
    return w <= lon <= e and s <= lat <= n


def geocode(query: str, timeout: float = 20.0):
    params = urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 5}
    )
    url = f"{NOMINATIM}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return url, payload


def main() -> int:
    rows = []
    nominatim_ok = True
    failures = []
    for i, landmark in enumerate(config.ORIGIN_LANDMARKS):
        result = None
        url = ""
        if nominatim_ok:
            try:
                if i:
                    time.sleep(1.1)  # Nominatim usage policy: max ~1 req/s
                url, payload = geocode(landmark)
                for item in payload:
                    lon, lat = float(item["lon"]), float(item["lat"])
                    if in_core(lon, lat):
                        result = {
                            "ref_lat": lat,
                            "ref_lon": lon,
                            "source": f"nominatim:{url}",
                            "osm_type": item.get("osm_type", ""),
                            "osm_id": item.get("osm_id", ""),
                            "display_name": item.get("display_name", ""),
                        }
                        break
            except Exception as exc:  # noqa: BLE001
                nominatim_ok = False
                failures.append(f"{landmark}: {type(exc).__name__}: {exc}")
                print(f"[origins] Nominatim failure, switching to fallback: {exc}")

        if result is None:
            lat, lon = FALLBACK_ANCHORS[landmark]
            if not in_core(lon, lat):
                print(f"[origins] SKIP {landmark}: anchor outside CORE")
                continue
            result = {
                "ref_lat": lat,
                "ref_lon": lon,
                "source": "approximate_anchor_fallback",
                "osm_type": "",
                "osm_id": "",
                "display_name": "",
            }
        rows.append({"name": landmark, **result})

    if len(rows) < 2:
        print(f"[origins] FAILED: only {len(rows)} origins resolved")
        return 1

    config.ORIGINS_REF_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.ORIGINS_REF_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name", "ref_lat", "ref_lon", "source",
                "osm_type", "osm_id", "display_name",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    n_nomi = sum(1 for r in rows if r["source"].startswith("nominatim"))
    print(f"[origins] wrote {len(rows)} origins ({n_nomi} via Nominatim, "
          f"{len(rows) - n_nomi} fallback) -> {config.ORIGINS_REF_PATH}")
    if failures:
        print(f"[origins] nominatim_failures: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
