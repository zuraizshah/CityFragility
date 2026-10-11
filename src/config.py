"""Central configuration for CityFragility Phase 0 feasibility study.

All coordinates are WGS84 (EPSG:4326), ordered (minx, miny, maxx, maxy)
= (west, south, east, north).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from shapely.geometry import box

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SOURCE_DIR = DATA_DIR / "source"
REPORTS_DIR = PROJECT_ROOT / "reports"
TESTS_DIR = PROJECT_ROOT / "tests"

# ---------------------------------------------------------------------------
# Study area selection
#
# CORE   : analysis window for sampled origins (central Karachi:
#          Saddar / Lyari / Empress-Market corridor, Clifton and DHA north).
# BUFFER : CORE expanded by ~0.04 deg (~4.4 km) on every side.  The road
#          network and the hospital search are both performed over BUFFER so
#          that origins near the CORE boundary can still route around it and
#          destinations just outside CORE remain reachable.
# ---------------------------------------------------------------------------
CORE_BBOX = (66.995, 24.795, 67.095, 24.895)      # ~10.1 km E-W x 11.1 km N-S
BUFFER_BBOX = (66.970, 24.770, 67.120, 24.920)     # ~15.2 km E-W x 16.7 km N-S

CORE_POLYGON = box(*CORE_BBOX)
BUFFER_POLYGON = box(*BUFFER_BBOX)

# Karachi sits at ~67E -> WGS 84 / UTM zone 42N.  Projected CRS used for
# snapping distances (metres) and straight-line sanity checks.  Routing
# weights stay on OSMnx great-circle "length" attributes (metres).
ANALYSIS_CRS = "EPSG:32642"

# Primary Overpass endpoint (overpass-api.de returns HTTP 406 from this
# network); the Kumi Systems mirror answers correctly and is an official
# public mirror.  See FEASIBILITY_REPORT.md for the endpoint survey.
OVERPASS_URL = "https://overpass.kumi.systems/api"

# Landmarks used as origin seeds (resolved via Nominatim, see make_origins.py)
ORIGIN_LANDMARKS = [
    "Saddar Chowrangi, Karachi",
    "Empress Market, Karachi",
    "Mazar-e-Quaid, Karachi",
    "Do Talwar, Karachi",
    "DHA Phase 5, Karachi",
    "NIPA Chowrangi, Karachi",
]

NETWORK_PATH = DATA_DIR / "network_drive.graphml"
HOSPITALS_PATH = DATA_DIR / "hospitals.gpkg"
HOSPITALS_REPORT = REPORTS_DIR / "hospitals_report.json"
ORIGINS_REF_PATH = DATA_DIR / "origins_ref.csv"
ORIGINS_SNAPPED_PATH = DATA_DIR / "origins_snapped.csv"

# Hospital -> network snapping tolerance for a destination to count as
# "usable" for routing (larger campuses may sit further from a drivable way).
MAX_HOSPITAL_SNAP_M = 300.0
# Artifact flags for inspection
ORIGIN_SNAP_FLAG_M = 100.0
DETOUR_RATIO_FLAG = 4.0

DOWNLOAD_LOG_NETWORK = REPORTS_DIR / "download_log_network.json"
DOWNLOAD_LOG_HOSPITALS = REPORTS_DIR / "download_log_hospitals.json"
CLOSURE_RESULTS = REPORTS_DIR / "closure_results.json"
BASELINE_RESULTS = REPORTS_DIR / "baseline_results.csv"
ROUTE_INSPECTION = REPORTS_DIR / "route_inspection.csv"
BENCHMARK_RESULTS = REPORTS_DIR / "benchmark.json"

USER_AGENT = "CityFragility-Feasibility/0.0 (research prototype)"


def today() -> str:
    return time.strftime("%Y-%m-%d")


def configure_osmnx():
    """Configure OSMnx for cached, rate-limited downloads over the mirror."""
    import osmnx as ox

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    ox.settings.cache_folder = str(CACHE_DIR)
    ox.settings.use_cache = True
    ox.settings.overpass_url = OVERPASS_URL
    ox.settings.requests_timeout = 600          # also used as Overpass [timeout:]
    ox.settings.overpass_rate_limit = True      # status probe -> 60 s fallback pause
    ox.settings.log_console = False
    ox.settings.log_level = logging.INFO
    ox.settings.headers = {"User-Agent": USER_AGENT}
    return ox
