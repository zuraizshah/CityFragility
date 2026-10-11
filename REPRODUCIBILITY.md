# Reproducibility

Everything in this project is regenerable from open data + recorded seeds.
No paid APIs; no hidden state; random seeds fixed.

## 1. Fixed seeds & parameters

| Parameter | Value | Where |
|---|---|---|
| Origin sampling seed | `20261010` | `src/phase2_sample_origins.py` |
| Candidate selection seed | `20261010` | `src/phase2_candidates.py` |
| Core / buffer bbox | see `src/config.py` | WGS84, ordered W,S,E,N |
| Facility snap threshold | 300 m | `config.MAX_HOSPITAL_SNAP_M` |
| Analysis CRS | EPSG:32642 | `config.ANALYSIS_CRS` |
| Candidate length cap | 4,000 m | `src/phase2_candidates.py` |
| Composite formula | `n_affected + 5*n_newly_disconnected + min(median_extra_m/100, 20)` | stored in `phase2_summary.json` |

## 2. Environment

```bash
# Python 3.12, packages:
osmnx networkx geopandas pyproj scipy shapely pyrosm pandas numpy fastapi uvicorn
# project venv used here: env/  (excluded from git — recreate with pip)
```

## 3. Full rebuild order (only if starting from nothing)

```bash
# 1. source OSM data (149 MB download; excluded from git) — see DATA_SOURCES.md
# 2. extract graph + facilities + Phase 0/1 baselines
env/conda/bin/python src/extract_from_pbf.py
env/conda/bin/python src/analyze.py            # baselines, Phase 0 closures
# 3. Phase 2: sample origins -> candidates -> experiment (~30 s)
env/conda/bin/python src/phase2_sample_origins.py
env/conda/bin/python src/phase2_candidates.py
env/conda/bin/python src/phase2_experiment.py
# 4. Phase 3: validation (~12 s)
env/conda/bin/python src/phase3_validation.py
# 5. Phase 4: server precompute (~42 s)
env/conda/bin/python src/phase4_precompute.py
# 6. Phase 5: static site data
env/conda/bin/python src/phase5_build_public_site.py
```

Note: **small derived artifacts (CSV/JSON/GeoJSON) are committed**, so steps
1–6 are unnecessary to *run* the app or site — only to rebuild from raw OSM.

## 4. Tests (the reproducibility contract)

```bash
env/conda/bin/python -m pytest tests/ -q        # 87+ tests, ~25 s
```

Coverage includes:

- routing correctness + disconnection semantics (Phase 0/1 suites);
- **fixed-value regressions**: A Street → DHA Phase 5 origin = **+442.27 m**
  (±0.05); Saddar Chowrangi disconnect way reproduces;
- Phase 2 integrity: 10,000 rows, monotonicity, restore-verified, top
  composite way/score (26182600 / 12.895), stored-number parity;
- Phase 3 anchors: sensitivity overlaps (4/5, 2/5, 0/5, 0/5), audit counts,
  cross-check zeros;
- Phase 4: graph-free research serving, artifact↔CSV identity;
- frontend logic tests (jsc) and static-site parity tests (Phase 5).

## 5. Key artifacts and what they prove

| Artifact | Proves |
|---|---|
| `reports/phase2_per_origin.csv` | raw 10,000 measurements (source of truth) |
| `reports/phase2_results.csv` / `phase2_summary.json` | way-level rollups + rankings |
| `reports/phase3_findings.json` | validation: reproducibility, cross-check, sensitivity, audit |
| `reports/PHASE*_REPORT.md` | phase narratives with measured numbers |
| `data/server_meta.json` + `phase*_*.json/geojson` | served research payloads (parity-tested) |
| `public_site/data/*` | exact copies for the static site (parity-tested) |
| `tests/pytest_phase*.txt` | dated test logs |

## 6. Determinism notes

- The experiment is deterministic given the same graph + seeds (heap Dijkstra
  ties broken by node id order; scenario merge order fixed).
- OSM snapshots change over time: **exact node ids/ways depend on the
  2026-10-09 snapshot** (sha256 recorded). A later extract will produce a
  different (but same-methodology) study.
- Static site rebuild (`phase5_build_public_site.py`) byte-copies saved
  outputs — it never recomputes scientific values.

## 7. Independence of checks

Validation deliberately uses **two different routing implementations**
(Phase 2 heap Dijkstra vs Phase 0 networkx engine) and a raw-row recomputation
path — so agreement is evidence, not circularity.
