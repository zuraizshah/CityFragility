# CityFragility — Research Report

**Status: completed student research project. Not peer-reviewed. Not a
validated citywide model.**

**Study area:** central Karachi, Pakistan · **Data:** OpenStreetMap via
Geofabrik (2026-10-09 snapshot) · **Experiments:** 100 origins × 100 road ways
= 10,000 measured before/after scenarios · **Validation:** Phase 3
(`reports/phase3_findings.json`, 2026-10-11)

---

## 1. Research problem and question

Urban roads are shared infrastructure: when a road segment is blocked, every
route that used it must be re-found, and in one-way networks some routes may
become impossible. CityFragility addresses a narrow, measurable version of
this problem. The research question is:

> **When a road in central Karachi is hypothetically closed in full, how do
> shortest *drivable* distances from sampled locations to the nearest mapped
> healthcare facility change — and how stable are the resulting road rankings
> under resampling?**

The project deliberately avoids unmeasurable questions (real flood risk,
ambulance times, casualties) and answers only what the road network data can
support: **modelled network access for a fixed sample of locations.**

## 2. Why healthcare accessibility matters

Access to care depends on the transport network: a facility that is close in
straight-line distance may be far by road if the direct route is one-way,
indirect, or blocked. Road closures (accidents, works, events, disasters)
temporarily reshape that network. Measuring *how much* the closest-facility
distance changes for specific closures gives planners and researchers a
transparent, reproducible stress test of network redundancy — a building block
for vulnerability analysis, without overclaiming what road data alone can
prove.

## 3. Data: source and date

| Item | Value |
|---|---|
| Road network & facility points | © OpenStreetMap contributors, via Geofabrik `pakistan-latest.osm.pbf` |
| Snapshot date | **2026-10-09** (sha256 `a125c80a59a4a534…3098a627b`) |
| Licence | ODbL (Open Database License) |
| Extracted driving graph | 45,304 nodes / 122,599 directed edges, 10,702 genuine one-way segments |
| Healthcare facilities | 453 points tagged `amenity=hospital` / `healthcare=hospital` |
| Analysis CRS | EPSG:32642 (UTM 42N) for metre distances |

## 4. Study-area boundaries

- **Core window (analysis):** W,S,E,N = 66.995, 24.795, 67.095, 24.895 —
  ~10.1 × 11.1 km (Saddar / Lyari / Empress Market corridor toward Clifton/DHA).
- **Buffer window (network + facility search):** 66.970, 24.770, 67.120,
  24.920 — ~15.2 × 16.7 km, so boundary origins can route around the edge and
  destinations just outside the core remain reachable.

All conclusions are bounded by these windows. **This is not whole-Karachi
coverage.**

## 5. The 100 sampled origins — selection method

Grid-stratified geographic sample (`src/phase2_sample_origins.py`):

1. The core window is divided into a **5 × 5 grid** (25 cells).
2. Per cell, **4** points are drawn from cells containing drivable network —
   25 × 4 = **100 origins** (seed `20261010`, fully deterministic).
3. Exclusions (e.g. non-drivable cells) and coverage diagnostics are recorded
   in `reports/phase2_origin_sampling_report.json`.

Each origin snaps to the nearest drivable node (UTM KDTree). The sample is
**geographic, not demographic**: it is explicitly *not* population-weighted,
*not* patient locations, and *not* representative of people.

## 6. The 100 tested roads — candidate selection and bias

Four deterministic tiers (`src/phase2_candidates.py`, 100 ways total):

| Tier | Count | Rule |
|---|---|---|
| Phase 0 tested | 8 | Already verified in the feasibility phase |
| Phase 1 origin paths | 12 | On the six original origins' baseline routes (≤ 4 km, capped) |
| Sample-path frequency | 50 | Ways most often on the 100 origins' baseline shortest paths |
| Stratified fill | 30 | Additional eligible ways for coverage |

**Documented selection biases** (verbatim in the data):
OSM completeness/mapper bias in central Karachi only; service roads excluded;
a candidate is a *full OSM way* closure, not one physical segment; origins are
grid-uniform, not demand; tier 3 favours central corridors (path-frequency
bias); over-length ways excluded; **rankings are NOT a citywide criticality
assessment.**

## 7. The experiment — 10,000 comparisons

For each of the 100 ways (`src/phase2_experiment.py`):

1. Remove **every directed edge** of that OSM way (one-ways preserved).
2. Recompute shortest drivable distance from each of the 100 origins to its
   nearest reachable mapped facility.
3. Record before/after distance, detour, destination switch, disconnect flag.
4. Restore the graph exactly; verify identity against the baseline
   (**verified after every scenario**).

Results: **100 × 100 = 10,000 rows** in `reports/phase2_per_origin.csv`;
way-level rollups in `reports/phase2_results.csv`. Runtime 24.4 s
(158.9 ms/scenario), peak RSS 1,724 MB.

Transparent composite score (arithmetic, not AI):
`n_affected + 5 × n_newly_disconnected + min(median_extra_m / 100, 20)`
— with separate per-dimension rankings published alongside.

## 8. Measured findings

- **55 of 100** tested ways changed at least one sampled origin's route.
- **34 of 100** switched an origin to a different facility (52 switch events).
- **0 newly disconnected origins** in this scenario set (every way tested
  left at least one path from every origin).
- Highest composite score: **OSM way 26182600 "Ziauddin Hospital Chowrangi"**
  — score **12.895**, 4/100 origins affected, median **+889.51 m**,
  max +1,261.02 m.
- Most origins affected: **OSM way 219168400 "15th Lane"** — **6/100**
  origins affected, median +206.28 m, max +501.75 m.
- The two rankings **disagree** — affected-count and composite rankings are
  reported separately; neither is presented as “the” answer.

Full tables: `public_site/data/results.json`,
`reports/phase2_results.csv` (this document's numbers are test-verified
against those files).

## 9. Cross-checking and regression tests

- **Reproducibility (Phase 3):** all 100 way-level rows and all five ranking
  lists recomputed from the 10,000 raw rows — **0 mismatches** across 8 metric
  columns; rankings identical to the stored summary.
- **Independent engine cross-check:** 11 selected ways (top-5 of both
  rankings + 2 zero-effect controls; **89 origin rows**) recomputed with the
  Phase-0-trusted networkx routing family (independent implementation from the
  Phase 2 heap Dijkstra): **0 mismatches** in baseline distances, disrupted
  distances, facility identity, disconnect and switch flags (tol 0.05 m).
- **Regression tests:** the full test suite (87+ tests) includes fixed-value
  regressions — e.g. the A Street closure must reproduce **+442.27 m** for the
  DHA Phase 5 origin (± 0.05 m) — plus monotonicity checks (no origin ever
  gets a *shorter* distance), exact graph-restore checks, and stored-number
  integrity tests for Phases 2–4.

## 10. Sensitivity: east/west instability

Rankings were recomputed on two origin partitions:

| Split | Composite top-5 overlap | Affected-count top-5 overlap |
|---|---|---|
| Odd vs even origins | **4/5** | **2/5** |
| East vs west half (median longitude) | **0/5** | **0/5** |

The east half had 40 ways with any effect; the west half 17. **The two halves
of the study area agree on none of the top-5 roads.** Rank positions are
unstable under resampling: defensible interpretation is “these ways measurably
affect access *for this sample*”, never “this is Karachi's most critical
road”.

## 11. Healthcare-facility limitations (unverified)

- All 453 facilities are **OpenStreetMap mapper tags** (`amenity=hospital`)
  — no official health registry was checked; **no 24/7 emergency or trauma
  capability is confirmed for any point.**
- Snap distances to the network: median 27.1 m, max 175.5 m; the 453 points
  collapse to **419 unique snap nodes**, with **95 near-duplicate pairs ≤ 50 m**
  and **8 duplicated-name clusters** — many are likely re-mapped sites.
- **124 usable facilities have limited-scope names** (dental/diagnostic/clinic
  etc.); 9 were inspected individually. “Hospital” here means a mapper label.

## 12. Conclusions directly supported by the data

1. Within this bounded sample, **most tested ways (55/100) measurably changed
   modelled access**, usually as extra drivable metres (median +20 to
   ~+900 m depending on way), and 34/100 changed which facility was closest.
2. **No tested way disconnected any sampled origin** — within this scenario
   set, redundancy existed for every sampled point.
3. **Rankings are sample-sensitive**: east/west top-5 agreement is 0/5 on
   both rankings; rankings are exploratory, not authoritative.
4. Facility data quality (duplicates, unverified scope) materially limits any
   care-capability reading of the results.

Nothing beyond these statements — no citywide, demographic, clinical,
flood, ambulance or casualty conclusions — is supported by the data.

## 13. Honest future research directions

- Population-weighted or origin-from-real-demand origins (e.g. anonymised
  mobility aggregates) to test whether rankings stabilise.
- Verified facility data (official registries, opening hours, emergency
  departments) and facility-capacity weighting.
- Edge-level (lane/segment) rather than full-way closures; time-of-day
  traffic data; turn restrictions via OSRM/Valhalla.
- Multiple city replication to test whether east/west-style instability is
  generic.
- Incident- or flood-*informed* closure scenarios (still not prediction)
  with published uncertainty bands.
- Formal peer review — **this project has not undergone peer review.**

## References

- OpenStreetMap contributors, Open Database License (ODbL) —
  https://www.openstreetmap.org/copyright
- Geofabrik South Asia extracts — https://download.geofabrik.de/asia/pakistan.html
- NetworkX, OSMnx, pyrosm, FastAPI, Leaflet (software used)
- Supporting documents: `METHODOLOGY.md`, `LIMITATIONS.md`,
  `REPRODUCIBILITY.md`, `DATA_SOURCES.md`, `reports/PHASE3_VALIDATION_REPORT.md`
