# Contributions

Honest accounting of what this project contains and how the work is
organised. CityFragility was built as an individual student project
(author: repository owner). No third-party code beyond the open-source
libraries listed in `DATA_SOURCES.md` §5.

## 1. Component ownership (what was built here)

| Component | Files | Notes |
|---|---|---|
| Feasibility & extraction | `src/extract_from_pbf.py`, `src/download_*.py`, `src/config.py`, Phase 0 sections of `FEASIBILITY_REPORT.md` | PBF provenance, graph build, bbox policy |
| Routing engine | `src/routing.py` + `tests/test_synthetic.py` | shortest drivable distance, multi-target, removal/restore; synthetic correctness tests; frozen after validation |
| Phase 1 simulator | `src/analyze.py`, `webapp/server.py` (live endpoints), `webapp/static/app.js` | interactive closure/restore, route comparison |
| Phase 2 experiment | `src/phase2_sample_origins.py`, `phase2_candidates.py`, `phase2_experiment.py` | 100×100 design, composite score, stored outputs |
| Phase 2.5 performance | `webapp/static/explorer-core.js`, `explorer.js`, `tests/test_phase25_frontend.py` | debounced filters, precomputed colours, pure logic tested headlessly |
| Phase 3 validation | `src/phase3_validation.py`, `reports/PHASE3_VALIDATION_REPORT.md` | reproducibility, independent cross-check, sensitivity, facility audit |
| Phase 4 product | `src/phase4_precompute.py`, server lazy-loading, UI shell | research mode, Overview tab, measured perf |
| Phase 5 publication | `src/phase5_build_public_site.py`, `public_site/`, this documentation set | static site, GitHub prep, presentation materials |
| Test suite | `tests/` (87+ tests) | regression values, API contracts, artifact parity, headless JS |

## 2. Data & third parties

- All geographic data © **OpenStreetMap contributors** (ODbL), via Geofabrik
  — not authored here.
- Libraries: NetworkX, OSMnx, pyrosm, GeoPandas, SciPy, pandas, NumPy,
  FastAPI, Uvicorn, Leaflet (BSD/MIT-family licences).
- Tile display: tile.openstreetmap.org under OSMF tile policy.

## 3. External review status

- **No peer review.** Phase 3 validation is internal (self-review plus an
  independent *implementation* cross-check inside the codebase).
- No institutional affiliation, grant, or official data partner is claimed.

## 4. How to credit / reuse

If you quote results: cite the snapshot (2026-10-09), the bounded study
area, and the disclaimer; keep “© OpenStreetMap contributors” attribution
(ODbL). Do not present the rankings as citywide or clinically meaningful.
Suggested citation text is in `PRESENTATION.md` §6.

## 5. Adding a LICENSE file

Before public release, choose a code licence (MIT/Apache-2.0 are typical for
student portfolios). OSM-derived **data** remains ODbL regardless of the code
licence — keep them separate in your release notes.
