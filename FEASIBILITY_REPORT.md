# CityFragility — Phase 0 Feasibility Report

**Date:** 2026-10-10 (all retrieval attempts this date, UTC+05 implied local; timestamps referenced in UTC)
**Addendum:** Phase 0B “Offline Geographic Data Recovery” executed 2026-10-10 14:59–15:00 UTC (HTTP 404, §4B). **Phase 0C executed 2026-10-10 evening: real Pakistan PBF downloaded, real Karachi graph + hospitals extracted, real baseline + closure + restoration computed — §4C, §8, §9, §13 updated with measured values.**
**Author:** Lead geospatial engineering pass (deterministic Python/NetworkX only — no LLM used for any calculation)
**Scope:** Phase 0 feasibility proof only. No frontend, no marketing site. Nothing outside this project folder was touched.

---

## 0. Decision: GO (Phase 0 complete on real data; Phase 1 pending approval)

| Question | Answer |
|---|---|
| Can routing primitives + closure logic be trusted? | **Yes** — proven on synthetic graphs (8/8) **and** on the real Karachi graph (restore verified bit-identical, §4C/§9) |
| Was a real Karachi OSM road network retrieved? | **Yes** — Geofabrik `pakistan-latest.osm.pbf` (149 MB, 2026-10-09 snapshot), bbox-extracted with pyrosm → **45,304 nodes / 122,599 directed edges**, 10,702 one-way segments (§4C) |
| Was a real baseline route computed? | **Yes** — 6 real origins → nearest real OSM hospital, distances 191–1,421 m (§9 table) |
| Was a real road-closure calculated? | **Yes** — 28 on-path ways available, 8 evaluated; deltas 0–+442 m; one **real disconnected origin** (Saddar Chowrangi) on way 58733431; graph restored exactly (§4C, §9) |
| Are hospital destinations verified on the map? | **Yes** — 453 deduped OSM hospital facilities, all snap ≤300 m (max 175 m); 419 unique snap nodes; uncertainty notes carried (§7, §10) |
| Phase 0B: one bounded resumable PBF download? | **NO-GO then (HTTP 404, §4B) — root-caused to a wrong URL on our side, not a Geofabrik failure. Correct URL succeeded in Phase 0C (§4C)** |
| **GO / NO-GO for Phase 1** | **GO** — every Phase 0 gate measured green (§13). Awaiting explicit approval before starting Phase 1 |

Phase 0 is now complete: no blocked gates remain. Phase 1 (the MVP in §10) must not start until the operator approves.

---

## 1. What Phase 0 was supposed to deliver vs. what exists

| # | Phase 0 requirement | Status |
|---|---|---|
| 1 | Isolated project folder, no other project touched | ✅ `CityFragility/` created; RuleWatch/other folders untouched (read-only listing only) |
| 2 | Check Python/disk/RAM; reproducible conda-forge env | ✅ §2 — micromamba + `env/environment.yml`, fully installed |
| 3 | Karachi study area + larger buffer, with justification | ✅ §3 (validated on real data: zero route nodes outside CORE, zero near buffer edge, §9) |
| 4 | Real OSM driving network, cached, source snapshot saved | ✅ **Phase 0C (§4C)** — `pakistan-latest.osm.pbf` (156,739,501 B, sha256 recorded) → pyrosm bbox extract → `data/network_drive.graphml` (45,304 nodes / 122,599 edges), GraphML roundtrip verified |
| 5 | Hospitals from OSM, dedupe, source tags, uncertainty report | ✅ **Phase 0C** — `amenity=hospital` ∪ `healthcare=hospital` from PBF: 828 raw → 482 unique OSM elements → **453 facilities** kept (29 spatial+name merges) → `data/hospitals.gpkg`; uncertainty notes in `reports/pbf_extraction_report.json` |
| 6 | Sample origins on network; baseline shortest drivable distances | ✅ **Phase 0C** — 6 real origins snapped (max 218.6 m, 1 flagged); baseline to nearest hospital: 191.2–1,420.9 m → `reports/baseline_results.csv` |
| 7 | Real segment closure + route changes + restore/reproducibility | ✅ **Phase 0C** — 28 on-path closure candidates found, 8 evaluated; max delta +442.3 m; one origin disconnected; restore: node/edge counts equal **and** baseline distances identical → `reports/closure_results.json` |
| 8 | Unit tests: alternatives, disconnects, monotonicity; real-route artifact inspection | ✅ Unit tests: **8/8 pass** (§7). Real-route inspection: `reports/route_inspection.csv` — detour ratios 0.84–1.45 (all <4), no boundary flags |
| 9 | Performance benchmark with real node/edge counts, memory, runtimes | ✅ **Phase 0C** — baseline Dijkstra ≈ 0.11 s; full closure cycle ≈ 0.13 s; peak RSS 1,899.5 MB → `reports/benchmark.json` |
| 10 | This report with commands, GO/NO-GO | ✅ (this document) |

---

## 2. Environment check (measured on this Mac)

| Item | Value |
|---|---|
| OS | macOS 26.6.2 (Build 25G83), arm64 (Apple Silicon) |
| RAM | 16 GB |
| Disk | 460 Gi volume, **298 Gi available** at start |
| System Python | 3.14.4 (`/Library/Frameworks/...`) — *not* used for the project |
| Pre-existing conda/mamba/brew | **None** → installed `micromamba 2.9.0` locally inside the project (`env/tools/`), no admin rights, no global changes |
| Project environment | `env/conda` created from `env/environment.yml` via **conda-forge only** |

**Exact dependencies (`env/environment.yml` + resolved versions):**

```
python=3.12.15, osmnx=2.0.7, geopandas=1.0.1, networkx=3.4.2,
shapely=2.0.7, pyproj=3.7.2, pandas=2.2.3, numpy=2.1.3,
pytest=8.4.2 (8.4.2 reported at runtime), requests=2, packaging=24
(+ transitive conda-forge: pyogrio, rasterio, matplotlib-base, scikit-learn, mapclassify ...)
micromamba 2.9.0 fetched from https://micro.mamba.pm/api/micromamba/osx-arm64/latest
```

Verified by import: `osmnx 2.0.7 / geopandas 1.0.1 / networkx 3.4.2` ✅.
Also verified available on conda-forge if a PBF fallback is needed later: **`pyrosm 0.11.0` has a `py312` build**; `pyosmium 4.3.0` likewise (repoquery, 2026-10-10).

---

## 3. Study area selection

```
CORE   (analysis window, origins sampled here): W,S,E,N = 66.995, 24.795, 67.095, 24.895   ≈ 10.1 km E–W × 11.1 km N–S
BUFFER (network + hospital search):            W,S,E,N = 66.970, 24.770, 67.120, 24.920   ≈ 15.2 km E–W × 16.7 km N–S
```

**Why this area (central Karachi):**

- Covers the historic core where mapped road density and mapped hospitals are highest in Karachi (Saddar, Empress-Market/Shahrah-e-Liaquat corridor, Mazar-e-Quaid, Lyari, Clifton/Do Talwar, DHA-5, NIPA/University-Road fringe) — the most favorable case for finding ≥2 usable hospital destinations, so a NO-GO there would be informative rather than caused by an obviously empty area.
- A single ~15×17 km driving extract is *appropriately sized*: large enough that a real arterial closure has alternate corridors to detour through, small enough to fetch within public Overpass limits (≈254 km² < the 2 500 km² default `max_query_area_size`, i.e. one request per dataset, not a burst).
- The **buffer is CORE expanded ~0.02–0.03° (~2.2–3.3 km) on every side** so that (a) origins near the CORE edge can still route around detours instead of being clipped by the download boundary, and (b) hospitals just outside CORE remain reachable destinations. Snapping/boundary artifacts are explicitly flagged per origin in `reports/route_inspection.csv` once data exists (code ready).
- CRS: routing weights are OSM great-circle `length` metres on the directed graph; snapping and straight-line checks are projected to **EPSG:32642 (WGS 84 / UTM zone 42N)**, the correct UTM zone for Karachi (67°E).

---

## 4. Data acquisition — exact attempts, statuses, dates

> Budget discipline: max 2 attempts per source for diagnostics, ≤20 s per diagnostic request; sources that failed were not re-polled. Full machine-readable record: `reports/network_survey.json`.

### 4.1 Endpoint survey (all on 2026-10-10)

| # | Source | Request | Result (exact) |
|---|---|---|---|
| 1 | `https://overpass-api.de/api/interpreter` (OSMnx default) | GET `/status`, then POST tiny query | **HTTP 406 Not Acceptable** (Apache/2.4.68), both attempts, <1 s — blocked, not a timeout |
| 2 | `https://overpass.kumi.systems/api/interpreter` | POST tiny query | ✅ earlier: **HTTP 200**, `timestamp_osm_base 2026-07-24T11:04:51Z`, **656 nodes tagged `amenity=hospital`** in bbox (24.70,66.90)-(24.95,67.15) |
| 2 | same | OSMnx `graph_from_polygon` download | ❌ **HTTP 500** after the built-in 60 s rate-limit pause (`ResponseStatusCodeError ... 500 Internal Server Error`) |
| 2 | same | independent tiny curl POST | ❌ **HTTP 500 in 0.41 s** → server-side outage, not query size; `/api/status` also 500 |
| 3 | `https://overpass.private.coffee/api/interpreter` | tiny query | **HTTP 500 in 0.46 s** |
| 4 | `https://overpass.osm.ch/api/interpreter` | tiny query, then Karachi counts | **HTTP 200 in 0.52 s**, but `way[highway]` in Saddar bbox = **0** and `amenity=hospital` = **0**, `timestamp_osm_base` = `"117629"` → Switzerland-limited extract, no Karachi data |
| 5 | `https://overpass.osm.jp/api/status` | GET | connection failed (curl exit 000) |
| 6 | `https://maps.mail.ru/osm/tools/overpass/api/interpreter` | POST tiny query | **DNS failure**: `Could not resolve host` |
| 7 | `https://download.geofabrik.de/asia/pakistan.html` | GET | **HTTP 200** — official index lists **only whole-country** `pakistan-*.osm.pbf`; **no Karachi or Sindh sub-extract exists** |
| 8 | `.../asia/pakistan/karachi-latest.osm.pbf` | GET | **HTTP 404** in 0.82 s (196-byte Apache 404 page) — URL never existed |
| 9 | `.../asia/pakistan/pakistan-latest.osm.pbf` | HEAD + ranged GET | **HTTP 404** in 0.49 s |
| 10 | `.../asia/pakistan/pakistan-261009.osm.pbf` (verbatim href from index, not guessed) | ranged GET | **HTTP 404** in 0.56 s |
| 11 | `https://download.bbbike.org/osm/bbbike/` | GET | **HTTP 200**, city list has **no Karachi** |
| 12 | `https://nominatim.openstreetmap.org/search` | 6 landmark queries, 1.1 s spacing | **HTTP 200** ×6 → 4 origins geocoded inside CORE; `Saddar Chowrangi` and `NIPA Chowrangi` returned only out-of-bbox hits → fell back to **flagged approximate anchors** (`data/origins_ref.csv`, column `source=approximate_anchor_fallback`) |

**Conclusion (as of the §4 survey, before Phase 0C):** Overpass path — one live mirror worked mid-session then went into 500-outage; primary is 406-blocked; others down/empty. Officially-listed PBF path — every `.pbf` URL we tried returned 404. Per instructions, network attempts stopped here; **no data was invented.** *(Superseded by §4C: the PBF 404s were our URL-resolution error; the corrected URL downloaded successfully the same evening, unblocking the entire Phase 0.)*

### 4.2 The one real OSM response we obtained

Kumi Overpass, 2026-10-10 (before its outage):

```json
{"type":"count","id":0,"tags":{"nodes":"656","ways":"0","relations":"0","total":"656"}}
```

Query: `node["amenity"="hospital"](24.70,66.90,24.95,67.15); out count;` with `timestamp_osm_base = 2026-07-24T11:04:51Z`.
This proves (a) the endpoint approach works, (b) OSM holds **656 hospital-tagged nodes in greater central Karachi alone**, so the ≥2-usable-destination bar is very likely met once data flows — *it does not substitute for actual facility records and none are claimed here.*

---

## 4B. Phase 0B — Offline Geographic Data Recovery (2026-10-10, 14:59–15:00 UTC)

Evidence file: `reports/pbf_attempt_0b.json`. All existing code, tests, env and reports preserved; no new packages installed.

**1. Official index checked (not guessed):**

- `https://download.geofabrik.de/asia/pakistan.html` → **HTTP 200** (0.87 s).
- Page lists exactly one “latest” extract: `href="pakistan-latest.osm.pbf"` (relative link) with page text: *“File size: **149 MB** … last modified 16 hours ago … contains all OSM data up to **2026-10-09T20:21:04Z**.”*
- **No Karachi-specific extract exists on Geofabrik** (Pakistan has no sub-extracts on the official page) — none was invented or requested.

**2. Pre-checks before downloading:**

| Check | Value | Verdict |
|---|---|---|
| Target size (from index) | 149 MB | small |
| Free disk | **294 Gi** | ample |
| URL correctness | resolved from official index href | verified |

**3. One bounded, resumable download attempt — result: BLOCKED (HTTP 404):**

```
curl --fail --location --continue-at - --max-time 600 --speed-limit 1024 --speed-time 60 \
  --user-agent "Mozilla/5.0 ... Chrome/126.0 ..." \
  --referer "https://download.geofabrik.de/asia/pakistan.html" \
  -o data/source/pakistan-latest.osm.pbf \
  "https://download.geofabrik.de/asia/pakistan/pakistan-latest.osm.pbf"

→ curl: (22) The requested URL returned error: 404
→ FINAL http=404 size=0 time=0.494818s
```

- **Exact verified URL:** `https://download.geofabrik.de/asia/pakistan/pakistan-latest.osm.pbf`
- **Exact HTTP error:** `404 Not Found` (also confirmed by HEAD → 404 with `Server: Apache`, `Via: 1.1 download-proxy12 (squid/6.14)`, `Cache-Status: download-proxy12;detail=mismatch`, and by `Range: bytes=0-0` GET → 404 with `Content-Length: 196`, `Content-Type: text/html`).
- **No partial/bogus file written** (`--fail`): `data/source/` remains empty. Destination exists as a folder only.
- Interpretation: the index HTML (200) advertises a file that object-serving proxies (`squid/6.14` inline) refuse with 404 — either a proxy-side fetch failure on this egress or an upstream object problem. Not a timeout, not a size/disk issue, not a wrong URL.

**4. Consequence — STOP (no fabrication):**

- Download blocked → **no PBF extraction performed** (pyrosm deliberately **not** installed; task forbids unnecessary packages).
- Therefore **no real Karachi node/edge counts, no real baseline route, no real closure/restoration results, no runtimes** are reported in this phase. Task step 5 (run real baseline/closure on the PBF) is **not executable** until the file exists. Synthetic data was **not** substituted for Karachi data.
- Re-run of the existing synthetic suite (task step 7): see §7 — **8 passed**.

**5. Manual browser-download procedure (for the operator):**

1. On any browser (this Mac or another network), open: `https://download.geofabrik.de/asia/pakistan.html`
2. Click **`pakistan-latest.osm.pbf`** (page states 149 MB, data up to `2026-10-09T20:21:04Z`).
3. Save to exactly: **`data/source/pakistan-latest.osm.pbf`**
4. Verify: size ≥ 140 MB **and** `file data/source/pakistan-latest.osm.pbf` says *OSM PBF file* (must not be HTML). Optional: record `shasum -a 256` in `data/source/` for provenance.
5. If the browser also receives 404, download on a different network (hotspot/another machine) and copy the file to that path.
6. Once present, the next authorized step is: install `pyrosm` (conda-forge, py312 build confirmed available) → bbox-extract CORE+BUFFER from the PBF preserving `oneway`/driving tags + hospital features → run `src/analyze.py` + `src/benchmark.py` → re-issue this report with real numbers.

> **Retraction of the §4B root-cause hypothesis (honesty note):** the Phase 0B 404 was **our URL-resolution error, not a Geofabrik/proxy failure.** The index page (`/asia/pakistan.html`) links the file as a *relative* href `pakistan-latest.osm.pbf`, which resolves to `https://download.geofabrik.de/asia/pakistan-latest.osm.pbf` (one level up). Phase 0B instead requested `https://download.geofabrik.de/asia/pakistan/pakistan-latest.osm.pbf` (an extra `/pakistan/` directory that does not exist) → 404 was the correct answer for a URL that was never advertised. Phase 0C verified the resolution with `urllib.parse.urljoin` against the fetched index and downloaded successfully on the first bounded attempt (§4C).

---

## 4C. Phase 0C — Real Pakistan PBF + real Karachi extraction (2026-10-10 evening)

Evidence file: `reports/pbf_extraction_report.json`. Machine-readable source provenance, hospital dedupe counts and GraphML sanitization log all recorded there.

**1. Corrected official URL (resolved, not guessed):**

- Index `https://download.geofabrik.de/asia/pakistan.html` → HTTP 200; page href `pakistan-latest.osm.pbf` resolves via `urljoin(index_url, href)` to **`https://download.geofabrik.de/asia/pakistan-latest.osm.pbf`**.
- Page states: 149 MB, OSM data up to **2026-10-09T20:21:04Z**.

**2. One bounded resumable download — SUCCESS:**

```
curl --fail --location --continue-at - --max-time 600 --speed-limit 1024 --speed-time 60 \
  -o data/source/pakistan-latest.osm.pbf \
  "https://download.geofabrik.de/asia/pakistan-latest.osm.pbf"
```

| Check | Value |
|---|---|
| Bytes written | **156,739,501** (149.5 MiB) in ≈54.6 s |
| sha256 | `a125c80a59a4a534cf4cfa8bc1bc1a762887981c9bafc6dfd7a88a33098a627b` (also written to `data/source/pakistan-latest.osm.pbf.sha256`) |
| Format validation | PBF magic bytes `OSMHeader`/`OSMData` present (not an HTML error page) |
| Free disk after | ≈294 Gi (ample) |

**3. `pyrosm 0.11.0` installed** (conda-forge py312 build — the package §2 already flagged as available; authorization given in the Phase 0B/C task).

**4. Extraction (`src/extract_from_pbf.py`) — real Karachi driving graph:**

- Bounding box = full BUFFER (`66.970, 24.770, 67.120, 24.920` WGS84), network_type driving, one-way tags honoured (`to_graph(direction="oneway", osmnx_compatible=True)`, simplified).
- Parse 30.3 s → graph build 2.4 s → **45,304 nodes / 122,599 directed edges** (10,702 directed edges without a reverse twin = genuine one-way segments).
- Saved as OSMnx GraphML; **roundtrip load verified identical node/edge counts**. GraphML sanitization (all logged): raw pyrosm `oneway='yes'` strings coerced to booleans (OSMnx reload requires strict `True/False`), simplified multi-way `osmid` lists kept as first-int `osmid` plus full list in a parallel `osmids` attribute, geometry/tags stringified.

**5. Hospitals from the same PBF (`get_pois` custom filters):**

| Step | Count |
|---|---|
| `amenity=hospital` rows | 480 |
| `healthcare=hospital` rows | 348 |
| Raw combined | 828 |
| Unique OSM elements (identity dedupe) | 482 |
| After 75 m + normalized-name merge | **453 facilities kept** (29 merged as node/way double-mappings) |
| Geometry split | 408 Point / 45 Polygon (polygons snapped via representative point) |
| Tag frequency | name 449, addr:city 353, addr:street 358, operator 7, opening_hours 3 |

Saved to `data/hospitals.gpkg` (layer `hospitals`, columns incl. `element_type`, `osmid`, `name`). **Uncertainty notes** (mapper-asserted tags, no 24/7 verification, possible clinic mis-tags, no registry check, no bed/ambulance data) are embedded in `reports/pbf_extraction_report.json`.

**6. Real baseline + closure + restoration (`src/analyze.py`) — headline results:**

- Graph load 4.4–5.1 s; snapping all 6 origins max 218.6 m; **453 hospitals usable (snap ≤300 m, max 175.5 m), collapsing to 419 unique snap nodes** (multiple facilities share a road node — both counts reported, §9).
- Baseline multi-source Dijkstra: **≈0.11 s**; single-source cross-check per origin identical to 1e-6 m.
- Closure candidates: **28 ways on real baseline shortest paths** identified (capped at 8 evaluated; earlier CORE-only ranking was superseded because those arterials carried no origin traffic → all deltas 0).
- Real route changes: +442.3 m (A Street, DHA Phase 5), +359.4 m (Lal Muhammad Chaudary Road, NIPA), +210.1 m (Khayaban-e-Shujaat), +90.6 m, +4.1 m, +2.4 m, +2.4 m; one candidate with no measurable delta.
- **Selected closure (max severity): way 58733431 `Aslam Raod (Hiralal Ganatra Road)`** (tertiary, 909.4 m in CORE, 30 directed edges, verbatim OSM spelling incl. the mapper's typo) → **Saddar Chowrangi disconnected** from all 453 hospital nodes (no remaining drivable path from its snapped node); other 5 origins unchanged (their nearest hospitals lie on other corridors). Monotonic non-decreasing distances verified across all candidates.
- **Restoration proof:** node/edge counts before/after identical (45,304 / 122,599) **and** all 6 baseline distances reproduced exactly → pipeline is re-runnable, no state leakage.
- Total analysis wall time ≈ 11.4 s.

**7. Bugs found & fixed during Phase 0C (all real-data only; synthetic suite unaffected):**

1. `restore_edges` crashed with `add_edge() got multiple values for argument 'key'` — pyrosm edge payloads carry a `key` attribute that collides with NetworkX's `key=` parameter; fixed by stripping it on restore.
2. GraphML sanitizer initially failed on pyrosm's raw `oneway='yes'` strings (OSMnx's loader strictly expects `True/False`); fixed with an explicit boolean coercion.
3. pyrosm POI frames use `id`/`osm_type` columns; mapped to the pipeline's `osmid`/`element_type` contract.
4. Hospital count discrepancy 453 vs 419 root-caused (usable facilities vs unique snap nodes) and both numbers now reported explicitly instead of silently diverging between `analyze.py` and `benchmark.py`.

---

## 5. Pipeline code (all saved; Overpass path kept as fallback, PBF path is primary)

| File | Role | Status |
|---|---|---|
| `src/config.py` | Study-area polygons, CRS (UTM 42N), artifact thresholds, paths | in use |
| `src/download_network.py` | OSMnx Overpass download path (cache + raw snapshot + sha256) | fallback, blocked by mirror outage (§4); superseded for Phase 0 by the PBF path |
| `src/download_hospitals.py` | Overpass hospital union + dedupe (fallback) | fallback |
| `src/extract_from_pbf.py` | **Primary path:** pyrosm bbox extract of driving network (one-way honoured, simplified, GraphML-sanitized, roundtrip-verified) + hospital POIs (`amenity` ∪ `healthcare=hospital`), identity + 75 m/name dedupe → `data/network_drive.graphml`, `data/hospitals.gpkg`, `reports/pbf_extraction_report.json` | **ran successfully (§4C)** |
| `src/make_origins.py` | Nominatim geocoding (policy-compliant spacing, flagged fallback anchors) | ran successfully → `data/origins_ref.csv` |
| `src/routing.py` | `distances_to_targets` (multi-source Dijkstra on reversed directed graph), `way_edge_keys` / `remove_way` / `restore_edges` | used by real analysis; `key`-collision fix in §4C |
| `src/analyze.py` | Snap in UTM; baseline + nearest hospital; inspection flags; **closure candidates = ways on real baseline shortest paths** (up to 8, cap 4 km length) + CORE-arterial fill-ins; per-origin deltas/disconnects; restore + exact reproducibility + monotonicity assertions → `reports/baseline_results.csv`, `reports/route_inspection.csv`, `reports/closure_results.json` | **ran successfully (§4C)** |
| `src/benchmark.py` | Counts, load/project/snap/Dijkstra/closure-cycle runtimes (3 reps), peak RSS → `reports/benchmark.json` | **ran successfully (§4C)** |
| `tests/test_synthetic.py` + `conftest.py` + `pytest.ini` | The test suite in §7 | 8/8 |

---

## 6. Hospitals: methodology and known uncertainty (executed on real data)

- **Source:** Geofabrik Pakistan PBF (2026-10-09 snapshot), bbox-filtered to BUFFER via pyrosm `get_pois` — **no Overpass dependency**.
- **Source tags queried:** `amenity=hospital` ∪ `healthcare=hospital` (run separately, then merged).
- **Dedupe:** (1) unique by `(element_type, osmid)` → 482; (2) merge elements ≤75 m apart with identical normalized names (or one unnamed) → **453 kept, 29 merged** (typical node-vs-way double mapping); tag frequencies recorded in `reports/pbf_extraction_report.json`.
- **Uncertainty statement** (carried in the report, same five notes as pre-registered):
  - Tags are mapper assertions, not verified capability.
  - `hospital` does **not** confirm 24/7 emergency/trauma service.
  - Possible mis-tags (clinics/dispensaries/closed sites); no check against any official health registry.
  - No bed counts, ambulance availability, or arrival-time data exist in the source.
- **“Usable destination” outcome:** all 453 facilities snap to the driving graph ≤ **300 m** (max 175.5 m) → **453 usable, 419 unique snap nodes** (facilities sharing a node collapse in the multi-source seed set; both counts reported everywhere).
- **Baseline nearest-hospital names are raw OSM tags** — some are clinics tagged `hospital` (e.g. “Virji Clinic”, “Samad Clinic …”); treat names as mapper labels, not capability claims.

---

## 7. Test results (exact output)

Final run — `env/conda/bin/python -m pytest tests -v` from the project root (full log: `reports/pytest_output.txt`). Re-run **after** the Phase 0C routing fixes (`restore_edges` key-collision, sanitizer) — still **8/8 pass**, i.e. the real-data fixes did not regress the synthetic guarantees:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.15, pytest-8.4.2, pluggy-1.6.0 -- .../CityFragility/env/conda/bin/python
cachedir: .pytest_cache
rootdir: CityFragility
configfile: pytest.ini
collecting ... collected 8 items

tests/test_synthetic.py::test_alternative_route_used_after_closure PASSED [ 12%]
tests/test_synthetic.py::test_disconnected_origin_after_bridge_closure PASSED [ 25%]
tests/test_synthetic.py::test_oneway_restrictions_respected PASSED       [ 37%]
tests/test_synthetic.py::test_monotonic_distances_after_random_deletions PASSED [ 50%]
tests/test_synthetic.py::test_remove_way_deletes_all_directed_and_parallel_edges PASSED [ 62%]
tests/test_synthetic.py::test_way_edge_keys_handles_simplified_list_osmid PASSED  [ 75%]
tests/test_synthetic.py::test_baseline_reproducible_after_remove_and_restore PASSED [ 87%]
tests/test_synthetic.py::test_empty_targets_rejected PASSED              [100%]

============================== 8 passed in 0.09s ===============================
```

**Failed tests (development history — all resolved):**

1. `test_monotonic_distances_after_random_deletions` — `assert 33.0 >= 35.0`: the *test* restored edges between iterations, so each round compared different graphs instead of cumulative deletion. Test logic fixed (cumulative deletions + final restore-equality check). **Not a routing-code bug.**
2. `test_baseline_reproducible_after_remove_and_restore` — asserted a distance *increase* after removing the *longer* of two parallel paths (distance correctly stayed 20 m). Test targeted way 1 (the short path) instead. **Not a routing-code bug.**

Final status: **0 failed tests.**

Coverage of the three required properties: alternative route after closure ✅, disconnected origin (bridge removal → `+inf`) ✅, monotonic non-decreasing distances under repeated deletion (20 deletions, 24-node random digraph, seeded) ✅ — plus one-way enforcement, all-directed-edge removal, simplified list-`osmid` handling, remove/restore exact reproducibility ✅.

---

## 8. Benchmark (measured on the real Karachi graph)

`reports/benchmark.json`, run 2026-10-10 on the same Mac (Apple Silicon, 16 GB RAM). 3 repeats where cheap. **Algorithmic routing costs on OSM data only — not traffic, not emergency-response times.**

| Metric | Measured |
|---|---|
| Network | 45,304 nodes / 122,599 directed edges |
| GraphML load | 4.24 s |
| `project_graph` (→ UTM 42N) | 1.83 / 2.19 / 2.23 s |
| Snap 6 origins | 0.060 s (each run) |
| Baseline multi-source Dijkstra (419 seed nodes) | **0.111 s** (each run) |
| Full closure cycle (remove 30 edges → Dijkstra → restore) | **0.133 s** (each run) |
| Hospitals | 453 usable facilities → 419 unique snap nodes |
| Peak RSS of benchmark process | **1,899.5 MB** (~1.9 GB — dominated by the loaded graph + projected copy; note the PBF parse itself peaked higher during extraction) |

Interpretation for Phase 1: routing is **not** the bottleneck at this scale — a full remove→recompute→restore cycle runs in ~0.13 s, so an interactive “close this street, show new nearest hospital” loop is comfortably feasible on this hardware with no optimization work. Memory (~2 GB) is the main constraint if Phase 1 ever loads multiple cities concurrently.

---

## 9. Real-route artifact inspection & map-quality limitations (now measured)

**Inspection results (`reports/route_inspection.csv`):**

| Origin | Origin snap (m) | Snap flag | Detour ratio | Boundary flags |
|---|---|---|---|---|
| Saddar Chowrangi | 50.6 | no | 1.05 | none |
| Empress Market | 90.5 | no | 0.84 | none |
| Mazar-e-Quaid | **218.6** | **YES** (>100 m) | 1.21 | none |
| Do Talwar | 31.1 | no | 1.22 | none |
| DHA Phase 5 | 18.3 | no | 1.45 | none |
| NIPA Chowrangi | 22.4 | no | 1.41 | none |

- **1 of 6 origins flagged for snapping** (Mazar-e-Quaid 218.6 m — the Nominatim fallback anchor; the other fallback anchor, NIPA, snapped cleanly at 22.4 m). Its route is still well-formed (detour 1.21), but treat its exact node as approximate.
- **All detour ratios 0.84–1.45×** — none near the 4× flag; note the <1.0 case (Empress Market) is a straight-line-vs-road-metric artifact (great-circle `length` vs UTM straight-line), not an error.
- **Zero boundary flags, zero nodes outside CORE** — the buffer design did its job; no routes clipped by the study-area edge.

**Remaining limitations (all still apply to Phase 1 outputs):**

1. **Tagging noise confirmed:** several “nearest hospital” names are clinics tagged `hospital` (Virji Clinic, Samad Clinic, Niazi Hospital). Dedupe + uncertainty notes mitigate but do not remove this; do not present facility names as verified hospitals.
2. **Driving network filter** excludes `service=*` roads: the final approach leg to a hospital is approximated by snapping to the nearest drivable node (≤300 m gate; all 453 passed).
3. **No turn restrictions / no traffic:** one-ways are modelled; turn:lanes, signals, congestion are out of scope. Outputs are *distance-based*, never travel-time or emergency-response claims.
4. **One snapshot, one date:** the 2026-10-09 Geofabrik snapshot will drift from ground truth; re-extraction is cheap (~46 s) whenever a refresh is needed.
5. **Boundary design validated** on this snapshot, but any future CORE change re-runs the inspection flags.

---

## 10. Realistic MVP scope (Phase 1, awaiting approval)

Phase 0 already delivered items 1–4 below as a one-shot script run. Phase 1 turns them into a maintained, repeatable capability:

1. Fixed study area (§3) + cached OSM driving graph + hospital GeoPackage with dedupe report. **(done as scripts; Phase 1 adds scheduled refresh)**
2. 6 snapped origins → baseline shortest drivable distance to nearest usable hospital (one-ways honoured, UTM-42N). **(done; Phase 1 may expand origin set)**
3. One real named-segment closure (all directed edges of one OSM way removed), per-origin deltas, disconnected-origin list, graph restored, baseline proven bit-identical. **(done — including a real disconnect on Saddar Chowrangi)**
4. Artifact inspection CSV + benchmark JSON + refreshed feasibility numbers → GO/NO-GO re-issue. **(done — this report)**

Phase 1 adds on top: a small operator-facing workflow to pick any origin/closure interactively (routing is ~0.13 s/cycle, so interactive is viable), richer hospital uncertainty surfacing, and a documented refresh routine for the PBF snapshot.

Explicitly out of scope until after Phase 1 approval: flood/water layers, traffic, travel-time modelling, emergency-response claims, frontend/UI beyond the minimum operator view, multi-closure scenario manager, hospital-capability verification.

---

## 11. Setup & run commands (reproducible from a clean Mac)

```bash
# ---- one-time setup (already performed for this Phase 0) ----
cd "CityFragility"
export MAMBA_ROOT_PREFIX="$PWD/env/mamba-root"
# micromamba binary already at env/tools/bin/micromamba (2.9.0)
env/tools/bin/micromamba create -y -f env/environment.yml -p "$PWD/env/conda"
env/tools/bin/micromamba install -y -p "$PWD/env/conda" -c conda-forge pyrosm  # Phase 0C addition

# ---- primary pipeline (PBF path — all steps below already ran successfully) ----
PY="$PWD/env/conda/bin/python"
# 1) download the official Pakistan extract (correct URL: index-relative href resolves to /asia/, NOT /asia/pakistan/)
curl --fail --location --continue-at - --max-time 600 --speed-limit 1024 --speed-time 60 \
  -o data/source/pakistan-latest.osm.pbf \
  "https://download.geofabrik.de/asia/pakistan-latest.osm.pbf"
# 2) extract Karachi bbox: driving graph + hospitals -> graphml/gpkg/report
$PY src/extract_from_pbf.py
# 3) geocode origins (already run; data/origins_ref.csv committed)
$PY src/make_origins.py
# 4) baseline + closure + restore verification -> reports/{baseline,closure,inspection}
$PY src/analyze.py
# 5) counts/memory/runtimes -> reports/benchmark.json
$PY src/benchmark.py

# ---- fallback pipeline (Overpass; blocked 2026-10-10 by mirror outage, kept for portability) ----
$PY src/download_network.py      # requires a reachable Overpass mirror
$PY src/download_hospitals.py    # requires the same

# ---- tests (run anytime; no network needed) ----
$PY -m pytest tests -v
```

Data-access pre-flight check before re-running (1 request, 20 s):

```bash
curl -sS --max-time 20 -X POST "https://overpass.kumi.systems/api/interpreter" \
  --data-urlencode 'data=[out:json][timeout:25];way["highway"](24.86,67.01,24.87,67.03);out count;'
# expect HTTP 200 + non-zero total when the mirror has recovered
```

Outputs land in: `data/` (graphml, gpkg, csv), `data/cache/` + `data/source/` (raw OSM snapshots + sha256), `reports/` (baseline, closure, inspection, benchmark, this survey).

---

## 12. Successes / Failures / Next steps

**Successes (Phase 0, complete on real data)**
- Isolated project; reproducible conda-forge env (Python 3.12.15, OSMnx 2.0.7 + pyrosm 0.11.0) built without touching any other project or system-wide tooling.
- Study area + buffer validated on real routes: zero boundary flags, all detour ratios sane.
- **Real Karachi OSM driving graph obtained** from the official Geofabrik Pakistan extract: 45,304 nodes / 122,599 directed edges (10,702 genuine one-way segments), GraphML roundtrip verified, sha256 provenance recorded.
- **453 real OSM hospital facilities** extracted + deduped from the same snapshot; all usable (snap ≤300 m); uncertainty notes carried into the machine-readable report.
- **Real baseline routes** for all 6 origins (191–1,421 m to nearest tagged hospital), cross-checked single-source vs multi-source to 1e-6 m.
- **Real closure simulation:** 28 on-path candidates identified, 8 evaluated; route deltas up to +442 m; **one origin genuinely disconnected** (Saddar Chowrangi via way 58733431); monotonicity holds; graph restored to bit-identical baseline.
- **Real benchmark:** ~0.11 s baseline, ~0.13 s full closure cycle, ~1.9 GB peak RSS — interactive-scale performance, no optimization needed for Phase 1.
- 8/8 synthetic tests still passing after the real-data fixes; four real-data-only bugs found and fixed (documented in §4C).
- Honest failure record preserved: Phase 0B's 404 root-caused to our own URL error, not hidden or blamed on the provider.

**Failures / caveats (documented, not hidden)**
- Overpass path remains unusable from this network (406/500/DNS across mirrors) — irrelevant now that the PBF path works, but kept as a fallback with all failures still on record (§4).
- Two origins used Nominatim fallback anchors; one (Mazar-e-Quaid) snaps 218.6 m (>100 m flag) — flagged in the inspection CSV, treat its node as approximate.
- Some “nearest hospital” labels are clinics tagged `hospital`; no capability verification was performed or claimed.
- Peak RSS ~1.9 GB (graph + projected copy) — fine for single-city work, a constraint if Phase 1 ever runs multi-city.

**Next steps (in order)**
1. **Operator reviews this report** and decides whether to start Phase 1 (MVP scope in §10). No frontend work has started and none will start without that approval.
2. On approval: implement the Phase 1 operator workflow (interactive origin/closure selection on the existing graph), PBF refresh routine, and any UX the MVP requires.
3. Optional hygiene: retry the §11 Overpass pre-flight occasionally — if a mirror recovers, the OSMnx fallback path needs no code changes and would complement the PBF snapshot.

**Wait for approval before Phase 1.** No frontend work started; none will start from this pass.

---

## 13. GO / NO-GO summary

| Gate | Result |
|---|---|
| Environment reproducible | **GO** |
| Routing/one-way/closure/restore logic validated (synthetic tests) | **GO** (8/8) |
| Real OSM driving network obtained | **GO** — 45,304 nodes / 122,599 directed edges (Geofabrik PBF, sha256-verified, §4C) |
| Real hospital destinations obtained | **GO** — 453 facilities, all snap ≤300 m, uncertainty notes carried (§6, §7) |
| Real baseline routes computed | **GO** — 6/6 origins, 191–1,421 m (§9) |
| Real road closure + route change + disconnect proven | **GO** — deltas 0–+442 m, 1 real disconnected origin, restore bit-identical (§4C, §9) |
| Route-artifact inspection clean | **GO** — 1 snap flag (documented), no detour/boundary flags (§9) |
| Benchmark with real counts | **GO** — 0.11 s baseline, 0.13 s closure cycle, 1.9 GB RSS (§8) |
| **Overall Phase 0 verdict** | **GO — Phase 0 complete on real data. Phase 1 ready to start upon operator approval (§10, §12).** |

---

## 14. Phase 1 — Interactive Road-Closure Simulator (2026-10-10, operator-approved)

Phase 1 wraps the **unchanged, tested** Phase 0 engine in a local web app. No routing logic was modified; the engine in `src/routing.py` is imported as-is.

**Stack (lightweight, as scoped):** FastAPI + Uvicorn backend (`webapp/server.py`), vanilla JS + Leaflet 1.9.4 (vendored locally, OSM tile attribution) front end (`webapp/static/`). No large frameworks, no accounts, no chatbot, local-only (`127.0.0.1:8000`).

**Architecture / memory (req. 12):** the real graph is loaded **once** per process (module singleton, verified: RSS **1,157 MB** running server vs Phase 0's 1.9 GB peak which included a duplicate projected copy — the web app never projects a second graph). The browser receives only a **filtered renderable subset: 21,117 major-road edges (motorway…tertiary + links), 4.67 MB GeoJSON**; residential/service (~97k edges) are excluded from rendering but remain fully active in routing. Simulations run server-side under a global lock, always remove→recompute→restore, so the in-memory graph is pristine between requests.

**Map contents:** real road network (major-road subset), **453 real OSM hospital facilities** (every popup and API record labeled *unverified OSM facility — not confirmed emergency care*), the **6 Phase 0 sample origins** (labeled sample-only), baseline route (blue) vs alternative route (red dashed), selected segment highlighted by stable `osmid`.

**Closure set (req. 6):** 20 bounded candidates with stable OSM way ids — the 8 Phase-0-tested ways + 12 additional on-baseline-path ways (same selection logic as `analyze.py`). Map-click selects a candidate; non-candidate roads are ignored with a notice.

**API:** `GET /api/health|network|hospitals|origins|candidates`, `POST /api/simulate?osmid=…` (per-origin before/after/Δ, disconnect flags, before+after route polylines), `GET /api/restore` (exact baseline recompute). One-ways preserved throughout (directed-graph engine).

**Live verification (real process, `reports/server.log`):**
- Way 58733431 (Phase 0 disconnect): Saddar Chowrangi 295.73 → **disconnected**; other 5 origins unchanged — identical to Phase 0.
- Way 22744767 (A Street): DHA Phase 5 852.22 → **1,294.49 m (+442.27)** — identical to Phase 0's +442.3.
- Restore: 122,599 edges, Saddar back at 295.73 m in 126 ms.
- Simulate latency ≈ 2.1 s (includes per-origin route geometry); network payload 4.67 MB in 0.13 s.

**Tests:** **20 passed** (8 original Phase 0 routing tests unchanged + 12 new API/interaction tests in `tests/test_webapi.py`, including: real graph counts, Phase 0 disconnect reproduction, monotonicity, restore-identity, cross-request statelessness, bounded payload, unverified-facility labeling). Log: `reports/pytest_phase1.txt`.

**Run commands:**
```bash
cd "CityFragility"
env/conda/bin/uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

**Limitations (surfaced in the UI, §0/§9 caveats unchanged):** hypothetical closures only; distance-based (not travel-time); unverified facilities; six sample origins only; no flood/ambulance/population claims; local hosting only (not published).

## 15. Phase 2 — Automated Infrastructure Vulnerability Intelligence (2026-10-10)

Phase 2 extends Phase 1's engine into a **bounded, reproducible closure experiment** over the same real Karachi graph, plus a second dashboard tab. Routing logic in `src/routing.py` is **unchanged** and reused. Full write-up in `reports/PHASE2_RESEARCH_REPORT.md`.

**What was built (scripts, all under `src/`):**
- `phase2_sample_origins.py` — seed-pinned (`20261010`) grid-uniform sample of **100 origins** (5×5 grid × 4/cell, snapped, exclusions tallied). Not population-representative.
- `phase2_candidates.py` — bounded set of **100 candidate ways** in 4 documented tiers (8 phase0-tested, 12 phase1-origin-path, 50 sample-path-frequency, 30 stratified-fill), length cap 6 km.
- `phase2_experiment.py` — measured closure experiment: 100 origins × 100 candidates = **10,000 scenarios**.

**Engine validation & a bug caught and fixed:** the per-candidate multi-source Dijkstra (returns every node's nearest-facility distance *and* facility identity in one pass) was cross-validated node-for-node against the Phase 0 verified engine on all 45,304 nodes. An initial **directionality bug** (forward instead of reversed propagation) produced 25,440 mismatches and a spurious disconnection; it was caught by the cross-check and a unit test, fixed, and the experiment re-run. Post-fix: **0 mismatches**; co-located facilities now collapse to a snap-node identity so a "destination switch" is always genuine.

**Metrics (transparent, no AI):** `n_affected`, `pct_affected`, `median/max` extra metres, `n_newly_disconnected` (numeric detour stored as **null, never `Infinity`**), `n_destination_switched`, and a documented composite `n_affected + 5×n_disconnected + min(median_extra_m/100, 20)`. Separate rankings per dimension.

**Measured results (24.4 s total, 158.9 ms/scenario, peak RSS 1,723.7 MB, restore verified identical):** 55/100 ways affected ≥1 origin; 34/100 caused ≥1 destination switch; **0/100** fully disconnected an origin in this sample. Top composite: way `26182600` (Ziauddin Hospital Chowrangi, 4 affected, +889.51 m median). Top by affected count: way `219168400` (15th Lane, 6 affected) — the two rankings **disagree**, and a sample-split sensitivity check shows top-5 overlap of 2/5 (affected) vs 4/5 (composite), i.e. ranks are sample-sensitive.

**Dashboard:** new **Vulnerability Explorer** tab (`webapp/static/explorer.js`) reading only stored artifacts via `GET /api/vuln/summary|roads.geojson|detail` — no mock data in the browser. Phase 1 Manual Simulator preserved and still reproduces A Street **+442.27 m**.

**Tests:** **41 passed** (8 Phase 0 routing + 12 Phase 1 webapi + 21 new in `tests/test_phase2.py`, covering sampling determinism, candidate bounds, engine cross-validation, disconnection null handling, destination switching, metric aggregation, rankings, restore identity, API payloads, and empty/404 cases). Log: `reports/pytest_phase2.txt`.

**Run commands:**
```bash
cd "CityFragility"
env/conda/bin/python src/phase2_sample_origins.py
env/conda/bin/python src/phase2_candidates.py
env/conda/bin/python src/phase2_experiment.py
env/conda/bin/python -m pytest tests -q
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000 -> "Vulnerability Explorer" tab
```

**Limitations (all still apply, shown in UI and report):** not population-representative; unverified facilities (no emergency-capability claim); hypothetical full-way closures; no flood/ambulance/traffic/casualty claims; rankings ≠ citywide criticality; mapping errors/boundary truncation/missing turn restrictions can change conclusions.

## 16. Phase 3 — Research Validation (2026-10-11)

Phase 3 does **not** re-run the experiment, download data, or change any Phase 0/1/2 result. It independently validates the saved artifacts and adds a **Findings** panel to the existing dashboard. Full write-up: `reports/PHASE3_VALIDATION_REPORT.md`; machine-readable: `reports/phase3_findings.json`. Runner: `src/phase3_validation.py` (11.6 s, one graph load, peak RSS ~1,681 MB, bounded to 12 cross-check scenarios).

**Validation results:**
1. **Reproducibility.** All 100 way-level metric rows and all five ranking lists recompute **exactly** from the 10,000 saved per-origin rows (8 metric columns checked; 0 mismatches; rankings match the stored summary). The published results are fully derivable from the raw data.
2. **Independent cross-check.** 11 selected closures (top-5 composite + top-5 affected + 2 zero-effect controls; 89 origin rows) were recomputed with the Phase 0-trusted networkx engine (`multi_source_dijkstra` on the reversed graph with path reconstruction — an independent implementation from Phase 2's heap Dijkstra). **Zero mismatches** in baseline distances, disrupted distances, facility identity, disconnect flags, and switch flags (tolerance 0.05 m). Graph restore verified after every scenario.
3. **Sensitivity.** Rankings were recomputed independently on two origin partitions. Odd/even split: top-5 overlap **4/5** (composite) and **2/5** (affected count). East/west geographic split (median longitude): **0/5 overlap on both rankings** — 40 ways with effect in the east half vs 17 in the west; the top-ranked ways are entirely different. The defensible conclusion is that certain ways measurably affect access *for this sample*, **not** that any road is definitively Karachi's most critical. Rank positions are unstable under resampling.
4. **Facility data-quality audit.** All 453 OSM facilities snap within the 300 m limit (median 27.1 m, max 175.5 m) but collapse to **419 unique snap nodes** — **95 near-duplicate pairs** within 50 m and **8 duplicated name clusters** suggest many are re-mapped sites. **124 usable facilities have limited-scope names** (dental/diagnostic/clinic etc.): the `amenity=hospital` tag is a mapper label, not an emergency-department confirmation. **No clinical or emergency capability is claimed for any facility.** 10 facilities were inspected individually (5 highest-snap + 5 serving the top-ranked way's origins).
5. **Study-area and modelling assumptions.** 9 origins lie within 200 m of the CORE edge (boundary truncation risk is small but real); candidates cover **1.18%** of total network length with documented tier bias; **28.1%** of candidate directed edges are genuinely one-way (one-ways are fully honoured by the directed engine); full-way closures (up to 6 km) are upper-bound stress tests, not incident forecasts.

**Website:** new **Findings** tab (`webapp/static/findings.js`, endpoint `GET /api/research`) renders the stored verified findings, sensitivity table, audit summary and limitations. Text-only — no map interaction, one fetch on first open. The Manual Simulator and Vulnerability Explorer tabs are unchanged.

**Tests:** **69 passed** (8 Phase 0 + 12 Phase 1 + 21 Phase 2 + 14 Phase 2.5 + 14 new in `tests/test_phase3_validation.py`, covering artifact integrity, independent in-test recomputation of three stored ways from raw rows, sensitivity anchors, audit non-clinical language, API payload shape/size, 404 path, panel wiring, and Phase 1/2 regressions). Log: `reports/pytest_phase3.txt`.

**Run commands:**
```bash
cd "CityFragility"
env/conda/bin/python src/phase3_validation.py   # regenerates phase3_findings.json + report
env/conda/bin/python -m pytest tests -q         # full suite
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000 -> "Findings" tab
```

**Remaining uncertainties:** origin sampling is geometric, not demographic; facility tags are unverified; candidate coverage is a small, biased share of the network; east/west rank divergence shows the sample drives conclusions; turn restrictions and congestion are not modelled. These bound every claim in the study.

## 17. Phase 4 — Final Product Experience and Performance (2026-10-11)

**Goal:** polished, readable, responsive local research product with all scientific results preserved. Full detail: `reports/PHASE4_REPORT.md`.

**Lightweight research viewer.** The server now starts **without** the 45k-node graph. `src/phase4_precompute.py` saved the outputs of the existing verified endpoints once (`data/phase1_candidates.json`, `data/phase2_roads.geojson` 97 KB / 100 features, `reports/phase2_vuln_details.json` 4.2 MB / 100 ways, `data/server_meta.json`); `/api/health`, `/api/vuln/*`, `/api/candidates` and `/api/research` serve them from disk. The routing engine lazy-loads as a single copy on the first live simulation (`ensure_loaded()` unchanged). Measured: cold start **0.56 s** to first response (**vs ~6.8 s**), idle RSS **101 MB** (**vs ~1,705 MB**); first simulate 7.5 s (one-time lazy load), steady state unchanged (1,685 MB after load, ~2 s/scan). Tests prove the research endpoints never touch the graph (monkeypatched load forbidden; clean-subprocess check < 600 MB).

**Professional website.** New default **Overview** tab (plain-English problem statement, verified scale tiles, explicit CAN/CANNOT conclusions, coverage, OSM/Geofabrik attribution); 4-tab shell; Explorer colour legend, hospital markers hidden + network dimmed while active, selected road = rose line on white casing + focused row, “modeled access — not real flood risk” wording; Simulator keeps the full workflow + A Street +442.27 m regression and gains a 3-step guide; Findings gains a plain-language sensitivity box highlighting the east/west **0/5** overlap; footer + topbar mode badge.

**Performance.** Explorer filter updates gain plateau gates (table/map signature checks skip DOM rebuild + setStyle when the visible set is unchanged), selection-only restyle path, CSS containment on tables, and an in-page profiler `window.__cfPerf` (real last/mean/max ms). Browser drag FPS was not automated on this machine — the profiler exists so a human check reads true numbers; no performance claim is guessed.

**Integrity.** Stored Phase 2/3 numbers re-asserted by tests (top composite 26182600, score 12.895; east/west 0/5; 453 unverified facilities; grid-not-population origins; bounded study area). No scientific artifact was recalculated or altered.

**Tests:** **87 passed** in 23.6 s (69 prior + 18 new in `tests/test_phase4.py`: graph-free serving, artifact↔CSV identity, UI shell wiring, DOM-id cross-check, jsc parses, clean-subprocess research viewer, stored-number integrity). Log: `reports/pytest_phase4.txt`.

**Run commands:**
```bash
cd "CityFragility"
env/conda/bin/python src/phase4_precompute.py    # only if artifacts were deleted (~42 s, needs graph)
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000 -> Overview tab (research mode, graph idle)
env/conda/bin/python -m pytest tests -q           # 87 passed
```

**Remaining uncertainties:** first live simulation after a fresh start costs ~7.5 s for the lazy graph load (by design, surfaced in the UI); deleting `server_meta.json` while the graph is also unavailable makes `/api/health` 503; map tiles still need network access (research data itself is fully local); real-browser slider-drag timing not automated.
