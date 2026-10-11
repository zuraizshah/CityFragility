# Methodology

Pipeline: **Phase 0** feasibility & extraction → **Phase 1** interactive
simulator → **Phase 2** vulnerability experiment → **Phase 3** validation →
**Phase 4** product/performance → **Phase 5** publication. Every step is
scripted under `src/` and re-runnable; this file summarises the *how*.

## 1. Network extraction

1. Download the official Geofabrik Pakistan extract
   (`https://download.geofabrik.de/asia/pakistan-latest.osm.pbf`,
   2026-10-09 snapshot, sha256 recorded).
2. Bbox-extract the buffer window (66.970, 24.770, 67.120, 24.920) with
   pyrosm, keeping drivable highways only.
3. Build a directed graph (OSMnx-compatible GraphML): **45,304 nodes /
   122,599 directed edges**; 10,702 genuine one-way segments preserved as
   directed edges. GraphML roundtrip verified.
4. Routing engine: NetworkX Dijkstra variants on edge attribute `length`
   (metres). Engine code (`src/routing.py`) is regression-tested and never
   modified after validation.

## 2. Facility snapping

- 453 OSM points tagged `amenity=hospital` / `healthcare=hospital` within the
  buffer, from the same PBF.
- Projected to EPSG:32642; each point snapped to the nearest graph node via
  KDTree with a **300 m threshold** (all 453 pass: median 27.1 m, max
  175.5 m). Co-located points collapse to **419 unique destination nodes**.
- Destination = nearest *reachable* facility node (forward reachability from
  the origin on the directed graph); ties broken by distance.

## 3. Origin sampling (100 points)

Grid-stratified (`src/phase2_sample_origins.py`):

- Core window → 5 × 5 cells; 4 random points per cell that contains drivable
  network; seed **20261010** (Python `random`, deterministic).
- Exclusions and per-cell diagnostics saved to
  `reports/phase2_origin_sampling_report.json`.
- Each point snapped to a graph node (UTM KDTree, 300 m max, flagged when far).

## 4. Candidate selection (100 ways)

Four deterministic tiers (`src/phase2_candidates.py`), in order:

1. **8** Phase 0 tested ways (already regression-covered).
2. **12** ways on the six original Phase 1 origins' baseline routes (≤ 4 km).
3. **50** ways ranked by how often they appear on the 100 sampled origins'
   baseline shortest paths (path-frequency).
4. **30** stratified fill from remaining eligible ways.

Eligibility: drivable classes (service roads excluded), length cap 4 km,
unique OSM ids. Biases are stored verbatim in
`phase2_candidate_selection_report.json` and surfaced in both UIs.

## 5. Scenario measurement (Phase 2)

For each way, for each origin (`src/phase2_experiment.py`):

```
baseline:  d0 = shortest drivable distance(origin → nearest reachable facility)
scenario:  remove every directed edge of the way (remove_way)
           d1 = recompute same quantity on the mutated graph
           restore edges exactly (restore_edges), verify graph identity
record:    detour = d1 - d0 | facility switch? | disconnected? (d1 missing)
```

- Graph mutations run under a global lock; baseline and scenario use the same
  destination set and tie-breaking, so comparisons are like-for-like.
- **Monotonicity invariant:** d1 ≥ d0 always (checked in tests).
- Disconnects are stored as null, never ±Infinity.
- Parallelism: scenario-level processes over read-only graph copies where the
  platform allows; results merged in deterministic order.
- Outputs: `phase2_per_origin.csv` (10,000 rows), `phase2_results.csv`
  (100 rows), `phase2_summary.json`.
- Runtime: 24.4 s total, 158.9 ms/scenario, peak RSS 1,724 MB;
  restore verified identical after every scenario.

## 6. Composite score & rankings

```
disruption_score = n_affected + 5 × n_newly_disconnected + min(median_extra_m / 100, 20)
```

Transparent integer/float arithmetic — **not an AI model**. Weights chosen
a priori to make a disconnection dominate a long detour. Five per-dimension
rankings (affected count, median detour, max detour, disconnections,
destination switches) are published alongside the composite ranking.

## 7. Validation (Phase 3, `src/phase3_validation.py`)

1. **Reproducibility:** recompute all way-level metrics and all five ranking
   lists from the raw 10,000 rows; compare to stored summary (8 metric
   columns; mismatch tolerance 0 on exact fields, 1e-9 on floats).
2. **Independent cross-check:** 11 ways / 89 origin rows recomputed with the
   Phase-0-trusted networkx engine (independent implementation); compare
   distances (0.05 m tol), facility identity, disconnect and switch flags.
3. **Sensitivity:** odd/even and east/west origin partitions; top-5 overlap
   recomputed independently for composite and affected-count rankings.
4. **Facility audit:** snap distances, near-duplicates ≤ 50 m, duplicate
   name clusters, limited-scope name flags, individual inspection records.
5. **Assumption effects:** boundary-proximity origins, coverage share,
   one-way share of candidate edges.

Output: `reports/phase3_findings.json` + `reports/PHASE3_VALIDATION_REPORT.md`
(runtime ~12 s, peak RSS ~1.68 GB).

## 8. Serving & static publication

- **Local app** (`webapp/server.py`): FastAPI; the graph is a process-wide
  singleton, lazy-loaded on the first live simulation. Research tabs read
  saved artifacts (Phase 4: `src/phase4_precompute.py`).
- **Static site** (`public_site/`): built by `src/phase5_build_public_site.py`
  from the *same* server readers — pure JSON copy, no backend, no graph.
- **Frontend:** vanilla JS + Leaflet; filter logic in `explorer-core.js` is
  pure and tested headlessly (jsc).

## 9. Statistical framing

- No hypothesis tests or p-values are claimed: this is a deterministic
  network experiment with resampling *sensitivity* analysis, not an
  inferential study.
- Sample size: 100 origins / 100 ways / 10,000 comparisons; scenario effects
  are exact for those points, not estimates of a population quantity.
