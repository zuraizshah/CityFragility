# CityFragility

**Measuring how hypothetical road closures reshape shortest drivable access to
mapped healthcare — a bounded study of central Karachi on real OpenStreetMap
data.**

CityFragility is a student software + research project. It closes 100 real road
segments one at a time on a real 45,304-node driving graph and recomputes
shortest *drivable* distances from 100 sampled locations to the nearest mapped
healthcare facility — 10,000 before/after comparisons — then validates,
documents and publishes the saved measurements.

> **Not a prediction tool.** No flood, ambulance, traffic, casualty or
> emergency-capability claims. Facilities are unverified OSM tags. The 100
> origins are a geographic grid sample, not population-representative.
> The study area is bounded — not citywide. See [LIMITATIONS.md](LIMITATIONS.md).

## What's here

| Path | What it is |
|---|---|
| `public_site/` | **Static public research site** — precomputed results only, no server, GitHub-Pages ready |
| `webapp/` | Full local application (FastAPI + Leaflet): Overview, Explorer, live Simulator, Findings |
| `src/` | Extraction, routing engine, experiments, validation, precompute scripts |
| `tests/` | 87+ automated tests (routing, API, experiment integrity, frontend logic, static-site parity) |
| `reports/` | Measured results, validation findings, phase reports |
| `data/` | Study artifacts (small CSVs/JSON/GeoJSON); large OSM downloads are excluded — see [DATA_SOURCES.md](DATA_SOURCES.md) |
| [RESEARCH_PAPER.md](RESEARCH_PAPER.md) | The research report (problem, method, measured findings, conclusions) |
| [METHODOLOGY.md](METHODOLOGY.md) · [LIMITATIONS.md](LIMITATIONS.md) · [REPRODUCIBILITY.md](REPRODUCIBILITY.md) · [DATA_SOURCES.md](DATA_SOURCES.md) | Supporting research documentation |
| [DEMO_GUIDE.md](DEMO_GUIDE.md) · [PRESENTATION.md](PRESENTATION.md) · [CONTRIBUTIONS.md](CONTRIBUTIONS.md) | Demo script, presentation materials, contribution notes |
| `FEASIBILITY_REPORT.md` | Full engineering log (Phases 0–4) |

## Quick start — full interactive application (local)

```bash
cd CityFragility
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

Requires Python 3.12 with `osmnx networkx geopandas fastapi uvicorn pandas scipy`
(see [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for environment setup), plus the
small artifacts in `data/` and `reports/`. The server starts in **research
mode** (≈0.6 s, ~100 MB — the heavy routing graph lazy-loads on the first live
simulation only).

## Quick start — static public site (no Python server needed for hosting)

```bash
# preview locally:
cd CityFragility/public_site
python -m http.server 8090
# open http://127.0.0.1:8090
```

For GitHub Pages: publish the `public_site/` folder as-is (any static host
works — no build step, no backend, relative paths only). **Nothing is deployed
automatically; publishing requires explicit approval.**

Rebuild the static data from saved results (only if Phase 2/3 artifacts change):

```bash
env/conda/bin/python src/phase5_build_public_site.py
```

## Run the tests

```bash
env/conda/bin/python -m pytest tests/ -q
```

## Attribution & licence

Original source code and documentation: [MIT](LICENSE) © 2026 Zuraiz Shah.

Road network and facility data © OpenStreetMap contributors, via Geofabrik
([ODbL](https://opendatacommons.org/licenses/odbl/)). Map tiles © OpenStreetMap
contributors. Source snapshot: `pakistan-latest.osm.pbf` (2026-10-09),
sha256 `a125c80a…a627b`. OSM-derived files (`data/hospitals.gpkg`,
`public_site/data/*`, any regenerated graph) remain ODbL-licensed regardless
of the code licence. See [DATA_SOURCES.md](DATA_SOURCES.md).

## Status

Completed research phases 0–5 (feasibility → simulator → vulnerability
experiment → validation → product → publication package). Not peer-reviewed.
