# Phase 2 — Automated Infrastructure Vulnerability Intelligence
## Research Report (Karachi road-network closure experiment)

**Tag:** `cityfragility-phase2`
**Retrieval date:** 2026-10-10
**Random seed:** `20261010`
**Study area:** bounded central Karachi, `CORE_BBOX=(66.995,24.795,67.095,24.895)`, analysis CRS `EPSG:32642`.
**Local dashboard:** `http://127.0.0.1:8000` (tab **Vulnerability Explorer**), launch command in §7.

---

### 1. What this experiment is (and is not)

This is a **road-network accessibility experiment**. For each candidate road closure we
recompute, for a fixed sample of origins, the shortest **drivable** distance to the
**nearest snap node of an OSM-listed hospital** in the study area, and compare it to the
baseline (no closure). We measure how many origins are affected, how much extra distance
they incur, whether an origin becomes unable to reach any facility, and whether the
*nearest facility identity* changes.

**Explicit non-claims** (also shown in the dashboard and `summary.disclaimer`):

- **Not population-representative.** Origins are a grid-uniform sample, not weighted by
  where people live, work, or travel.
- **Facilities are unverified OSM points.** A snapped "hospital" node carries no verified
  emergency capability, bed count, or operating status.
- **Hypothetical full-way closures.** Each scenario removes an entire OSM way. Real
  incidents are partial, temporary, and directional.
- **No ambulance, traffic, flood, or casualty modeling.** Distances are free-flow shortest
  paths on the street graph; no signal timing, congestion, or response-time claims.
- **Rankings are not citywide criticality.** A low-ranked way in this sample is not proven
  unimportant city-wide; it simply did not change the *measured* origin→facility metric
  under *this* sampling.
- **Mapping uncertainty.** Missing turn restrictions, one-way errors, truncated boundaries,
  and OSM temporal drift can change conclusions. Any of these could flip a ranking.

---

### 2. Reproducible sample (Part A)

- **Seed:** `20261010`.
- **Method:** 5×5 grid over `CORE_BBOX`; 4 candidate nodes per cell; deterministic seeded
  shuffle; snapped to the road graph; **excludes** nodes outside the core, degree-0 nodes,
  and nodes with no reachable facility.
- **Result:** `data/phase2_origins_sample.csv` — **100 origins, all 25 cells covered.**
  Exclusion tallies: outside_core 19,989; degree_zero 0; unreachable_facility 0.
- **Interpretation note (in report):** grid-uniform sampling is used for geometric balance,
  **not** demographic or epidemiological representativeness.
- **Regression set preserved:** the 6 Phase 0/1 snap-verified origins in
  `data/origins_snapped.csv` are untouched and still pass their exact-distance assertions.
- Machine-readable: `reports/phase2_origin_sampling_report.json`.

### 3. Bounded candidate set (Part B)

- **Cap:** 100 candidate ways total; way length capped at 6,000 m.
- **Tiers** (with documented selection bias per tier):

  | tier | count | selection bias |
  |---|---|---|
  | `phase0_tested` | 8 | previously exercised by routing tests |
  | `phase1_origin_path` | 12 | lies on a Phase 1 sample origin path |
  | `sample_path_frequency` | 50 | high baseline path frequency from this origin sample |
  | `stratified_fill` | 30 | stratified fill to reach the cap |

- **Result:** `data/phase2_candidates.csv` — 100 unique ways, all present in the graph.
- Machine-readable: `reports/phase2_candidate_selection_report.json` (bias list included;
  the dashboard surfaces these biases verbatim).

---

### 4. Measurement engine (Parts C+D)

- **Graph:** real Geofabrik Pakistan extract, drive network, `45,304 nodes / 122,599
  directed edges` (sha256-pinned; snapshot 2026-10-09).
- **Facilities:** 453 deduplicated OSM hospitals → **419 unique usable snap nodes**
  (snap cap 300 m). Co-located facilities collapse to one snap node, so a "destination
  switch" always means the nearest facility *node* genuinely changed.
- **Shortest path:** a labeled multi-source Dijkstra on the **reversed** graph returns, in
  one pass, every node's shortest forward drivable distance to the nearest facility *and*
  that facility's identity. This is validated node-for-node against the Phase 0 verified
  routing engine (`routing.distances_to_targets`) on all 45,304 nodes (**0 mismatches**).
- **Disconnection handling:** an origin that reaches a facility at baseline but not after
  the closure is flagged `newly_disconnected`. The numeric detour is stored as **null
  (never `Infinity`)** and classified as either `origin_isolated_stub` (out-degree 0 after
  closure) or `cut_from_facility_network` (out-edges exist but none lead to a facility).
- **Graph restoration:** after every scenario the way is re-inserted and the run asserts
  the edge/node counts return to baseline. **Restore verified identical: true.**

**Metrics (transparent, no AI/black box).** Per candidate way:

- `n_affected` — origins whose shortest path lengthened.
- `pct_affected` — `n_affected / n_origins`.
- `median_extra_m`, `max_extra_m` — median/max added meters among affected origins.
- `n_newly_disconnected` — origins that lost all facility access.
- `n_destination_switched` — origins whose nearest facility identity changed.
- **Composite score** (single documented scalar):
  `n_affected + 5 * n_newly_disconnected + min(median_extra_m / 100, 20)`

Separate rankings are kept for affected count, median detour, max detour, disconnections,
and composite score — **a single score is never presented as the only truth.**

---

### 5. Key findings (stored artifacts only — no numbers here are hand-entered)

Run: **100 origins × 100 candidates = 10,000 scenarios**, total **24.4 s**,
**158.9 ms/scenario** mean, **peak RSS 1,723.7 MB**, restore verified.

- **55 / 100** candidate ways affected at least one origin.
- **34 / 100** ways caused ≥1 destination switch (**52** per-origin switch events).
- **0 / 100** ways fully disconnected an origin in this sample (see sensitivity note below).

**Top 5 by composite score:**

| osmid | name | affected | median extra (m) | score |
|---|---|---|---|---|
| 26182600 | Ziauddin Hospital Chowrangi | 4 | +889.51 | 12.895 |
| 182385941 | (unnamed) | 2 | +1,046.54 | 12.465 |
| 39998276 | 10th Street | 3 | +942.71 | 12.427 |
| 485726463 | (unnamed) | 3 | +835.21 | 11.352 |
| 40119137 | ایونیو 3 | 2 | +825.45 | 10.255 |

**Top 5 by affected count:**

| osmid | name | affected | median extra (m) | max extra (m) |
|---|---|---|---|---|
| 219168400 | 15th Lane | 6 | +206.28 | +501.75 |
| 479722526 | 15th Lane | 5 | +204.94 | +301.15 |
| 1475627437 | (unnamed) | 5 | +204.94 | +500.41 |
| 26182600 | Ziauddin Hospital Chowrangi | 4 | +889.51 | +1,261.02 |
| 26800453 | Brunton Road | 4 | +465.45 | +465.45 |

Note that the rankings **disagree**: `219168400` (15th Lane) hits the most origins but is
not top by composite, because composite also weights disconnection and median detour
magnitude — `26182600` moves fewer origins but with a far larger median detour.

**Sensitivity (sample split).** Recomputing metrics on odd vs even origin halves:
top-5 overlap — affected count **2/5**, composite **4/5**. The composite ranking is more
stable than raw affected count, but **both are sample-sensitive**; treat ranks near the
cut as indistinguishable.

**On disconnections.** With the corrected engine and this grid-uniform sample, no full
origin→facility severing occurred. Earlier development runs that appeared to show a
disconnection were an artifact of a directionality bug in the labeled Dijkstra (forward
instead of reversed), which was caught by cross-validation against the verified engine and
by a unit test, then fixed. The disconnection code path is still exercised and unit-tested
on synthetic cases; the **0** above is the true measured value for this sample.

---

### 6. Dashboard (Vulnerability Explorer)

Added as a tab alongside the preserved Phase 1 Manual Simulator. It reads **only** the
stored artifacts via `/api/vuln/*` — the browser never invents a number.

- `GET /api/vuln/summary` — rows, summary, rankings, sampling method, candidate biases.
- `GET /api/vuln/roads.geojson` — candidate way geometries merged with stored metrics.
- `GET /api/vuln/detail?osmid=…` — per-origin breakdown + worst-origin example.
- The simulator tab and its verified A Street result (`+442.27 m`) are unchanged.
- Server runs as a **single cached graph copy** with a lock around mutations; RSS stays
  ~1.1 GB idle and ~1.7 GB at experiment peak.

### 7. Reproduce

```bash
# from the project root
env/conda/bin/python src/phase2_sample_origins.py      # Part A  -> data/phase2_origins_sample.csv
env/conda/bin/python src/phase2_candidates.py          # Part B  -> data/phase2_candidates.csv
env/conda/bin/python src/phase2_experiment.py          # Parts C+D -> reports/phase2_*.csv/json
env/conda/bin/python -m pytest tests -q                # 41 tests (Phase 0/1/2)
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000  -> "Vulnerability Explorer" tab
```

**Machine-readable outputs:** `reports/phase2_origin_sampling_report.json`,
`reports/phase2_candidate_selection_report.json`, `reports/phase2_per_origin.csv`,
`reports/phase2_results.csv`, `reports/phase2_summary.json`.

---

### 8. Summary

Phase 2 delivers a **bounded, reproducible, seed-pinned** vulnerability experiment over the
real Karachi road graph with a **validated** shortest-path engine, **transparent**
documented metrics (disconnections never become `Infinity`), **exact** graph restoration,
a **live dashboard** reading only stored results, and an honest set of scientific
limitations. 55 of 100 sampled ways measurably affect origin→hospital access; the
affected-count and composite rankings disagree and are sample-sensitive, which is itself
the correct scientific result to report rather than a single "most dangerous road."
