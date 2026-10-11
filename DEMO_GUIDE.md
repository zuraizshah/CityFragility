# Demo Guide

How to run and present CityFragility locally. Two experiences exist — demo
them separately so the distinction is clear.

## 0. One-time setup

```bash
cd CityFragility
# Python 3.12 with: osmnx networkx geopandas pyproj scipy shapely pandas numpy fastapi uvicorn
env/conda/bin/python -m pytest tests/ -q     # expect 87+ passing, ~25 s
```

## A. Static public site (precomputed only)

```bash
cd public_site && python -m http.server 8090
# open http://127.0.0.1:8090
```

- Loads in well under a second; ~215 KB of JSON/GeoJSON + Leaflet CDN + OSM tiles.
- Shows: problem statement, study area map, 100 ranked roads with measured
  effects, validation highlights, methodology, limitations.
- **No live simulation** — say so explicitly when presenting.

## B. Full interactive application

```bash
# from the project root
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

Server starts in **research mode** (~0.6 s, ~100 MB). The routing graph
lazy-loads (~5–6 s, ~1.7 GB) on the **first Simulator action** only.

### Suggested 4-tab walkthrough (matches the 90-second script in PRESENTATION.md)

1. **Overview (default)** — problem, verified scale, CAN/CANNOT lists. Point
   at the “research mode” badge in the top bar.
2. **Explorer** — stored experiment: sliders + ranking selector; click the
   top road (rose + white casing); show per-origin evidence + before/after
   route geometry. Emphasise: *saved measurements, not live compute*.
3. **Simulator** — pick **A Street** → Simulate Closure → show +442.27 m for
   DHA Phase 5 (the regression everyone can re-run) → Restore Road.
   This is the only live-simulation part; first click includes the one-time
   graph load.
4. **Findings** — reproducibility 0 mismatches, independent cross-check,
   east/west **0/5** overlap box, facility audit; end on the disclaimer.

### Demo hygiene

- Keep the browser console closed unless asked; no fabricated numbers on screen.
- If asked about RAM: idle research mode ~100 MB; live graph ~1.7 GB
  (measured; see `reports/PHASE4_REPORT.md`).
- If something breaks mid-demo: restart the server; the app has no user state.

## C. What NOT to do in a demo

- Do not call any scenario a flood, accident or real closure.
- Do not say hospitals are verified emergency departments.
- Do not generalise the six simulator origins or 100 grid origins to “people”.
- Do not claim citywide coverage or ambulance-time savings.

## D. Troubleshooting

| Symptom | Fix |
|---|---|
| Port busy | `lsof -iTCP:8000` then kill that pid, or use `--port 8001` |
| Static site shows “HTTP 404” on data | you opened the file directly (`file://`); use `python -m http.server` |
| First simulate slow | expected one-time lazy graph load (~5–6 s) |
| Tests fail after editing JS | `jshell`-style parse check is part of the suite; run `pytest tests -q` |
| Missing `env/conda` | recreate the venv (see REPRODUCIBILITY.md §2) |
