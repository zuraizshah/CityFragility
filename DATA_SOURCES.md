# Data Sources

## 1. OpenStreetMap (primary source)

| Field | Value |
|---|---|
| Provider | OpenStreetMap contributors |
| Repository | https://www.openstreetmap.org |
| Licence | **ODbL** — https://opendatacommons.org/licenses/odbl/ |
| Attribution required | “© OpenStreetMap contributors” (shown in app, static site, reports) |

### Road network snapshot

| Field | Value |
|---|---|
| File | `pakistan-latest.osm.pbf` (Geofabrik South Asia mirror) |
| Download URL | https://download.geofabrik.de/asia/pakistan-latest.osm.pbf |
| Index page | https://download.geofabrik.de/asia/pakistan.html |
| Snapshot date | **2026-10-09** |
| Size | 156,739,501 bytes (~149 MB) |
| sha256 | `a125c80a59a4a534cf4cfa8bc1bc1a762887981c9bafc6dfd7a88a33098a627b` |
| Local path (excluded from git) | `data/source/pakistan-latest.osm.pbf` (+ `.sha256`) |

**Note:** Geofabrik updates continuously; `latest.osm.pbf` today will differ
from this snapshot. To reproduce this exact study, request/archive the
2026-10-09 file and verify the sha256 above. Methodology stays valid on any
snapshot; node ids and rankings may change.

### Derived OSM products (committed, small)

| File | Derived from | Used for |
|---|---|---|
| `data/network_drive.graphml` (96 MB, **excluded from git**) | PBF bbox extract (pyrosm), drivable classes | routing graph |
| `data/hospitals.gpkg` (192 KB) | PBF `amenity=hospital` / `healthcare=hospital` tags | facility destinations |
| `data/origins_ref.csv`, `origins_snapped.csv` | landmark snapping (Phase 0/1) | simulator origins |
| `data/phase2_origins_sample.csv` | grid sampling (seed 20261010) | experiment origins |
| `data/phase2_candidates.csv` | 4-tier selection | tested ways |

Rebuild: `env/conda/bin/python src/extract_from_pbf.py` (see
`REPRODUCIBILITY.md`).

## 2. Facility points (healthcare)

- Same OSM snapshot; tag filter `amenity=hospital` OR `healthcare=hospital`
  within the buffer bbox.
- 453 points → 419 unique snap nodes (duplicates documented in
  `reports/phase3_findings.json` → `facility_audit`).
- **Unverified**: no health registry, no emergency-capability data.
  ODbL obligations apply to redistribution of these points.

## 3. Map tiles (display only)

- Static basemap: `https://tile.openstreetmap.org/{z}/{x}/{y}.png`
  (usage policy: https://operations.osmfoundation.org/policies/tiles/).
- Attribution rendered in every map view (Leaflet `attribution` control +
  page footer).
- Tiles are *not* stored or redistributed in this repository.

## 4. Geographic reference systems

- Storage/display: WGS84 (EPSG:4326).
- Metre measurements/snapping: **EPSG:32642** (WGS 84 / UTM zone 42N).
- Routing weights: OSM `length` attribute (metres, great-circle projected).

## 5. Third-party software (not data)

NetworkX, OSMnx, pyrosm, GeoPandas, Shapely, pyproj, SciPy, FastAPI,
Uvicorn, pandas, NumPy, Leaflet (BSD-2-Clause), Inter/system fonts.
No paid services are used anywhere in this project.

## 6. What is deliberately NOT included

| Excluded | Why | How to get it |
|---|---|---|
| `data/source/*.osm.pbf` (149 MB) | large binary download | Geofabrik URL + sha256 above |
| `data/network_drive.graphml` (96 MB) | regenerable in ~1 min | `src/extract_from_pbf.py` |
| `reports/phase2_checkpoint*/` (1.3 MB) | resume state of a 24 s run | `src/phase2_experiment.py` |
| `env/`, `__pycache__/`, logs, `.pytest_cache` | environment/local state | recreate with pip / rerun |
| API keys / secrets | none exist — project uses no keys | — |

## 7. Licence summary for redistribution

- OSM-derived data in `data/` and `public_site/data/`: **ODbL 1.0** — keep
  attribution (“© OpenStreetMap contributors”), share-alike on derived
  databases, no warranty.
- Code in this repository: your chosen licence (add a `LICENSE` file before
  public release — see CONTRIBUTIONS.md).
- Generated measurements (CSV of distances/scores): facts, but keep the
  attribution and disclaimer context when quoting.
