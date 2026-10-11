# CityFragility — Phase 4: Final Product Experience and Performance

Date: 2026-10-11 · Status: **complete — 87/87 tests passing** (69 prior + 18 new)

## 1. What Phase 4 changed

Phase 4 turned the working research system into a polished, readable, responsive
local product **without touching any scientific result**. All Phase 0–3 artifacts
(`phase2_results.csv`, `phase2_per_origin.csv`, `phase3_findings.json`, routing
engine, verified rankings) are byte-for-byte unchanged; tests assert this.

| Area | Change |
|---|---|
| Lightweight research viewer | Server starts **without** the 45k-node graph; Explorer + Findings + health are served from precomputed artifacts. The routing engine lazy-loads on the first live simulation only. |
| Professional website | New **Overview** tab (problem in plain English, verified scale, can/cannot conclusions, attribution), 4-tab shell, color legend, 3-step simulator guide, footer, mode badge, clearer scientific wording. |
| Performance | Idle server 1,685 MB → **101 MB**; cold start ~6.8 s → **0.56 s** to first response; explorer filter plateau gates + selection-only restyle + in-page profiler; explorer hides 453 hospital markers and dims the network while active. |
| Scientific integrity | “Modeled access, not flood risk” wording on every relevant panel; sample-not-population language; facility-unverified warnings preserved; OSM/Geofabrik attribution in topbar area, footer, and both provenance panels. |

## 2. Lightweight research viewer (PRIORITY 1)

### Design
One graph copy, ever. `src/phase4_precompute.py` ran the **existing verified
server functions once** and saved their outputs; the server now serves them
from disk until a live simulation is requested:

| Saved artifact | Built from | Size |
|---|---|---|
| `data/phase1_candidates.json` | `build_candidates()` | 20 candidates |
| `data/phase2_roads.geojson` | `vuln_roads_geojson()` | 97 KB, 100 features |
| `reports/phase2_vuln_details.json` | `vuln_detail(osmid)` × 100 | 4,168 KB, 100 ways |
| `data/server_meta.json` | graph/facility counts | ~0.4 KB |

`webapp/server.py` changes:
- `lifespan` no longer loads the graph (lazy `ensure_loaded()` on first
  simulate / network / hospitals / origins request — single singleton, no
  duplicate copies).
- `/api/health` answers from `server_meta.json` when the graph is idle
  (`"mode": "research"`, `"graph_loaded": false`); live values when loaded.
- `/api/vuln/roads.geojson`, `/api/vuln/detail`, `/api/candidates` read the
  precomputed artifacts first (payloads identical to the live endpoints —
  they *are* the live endpoints' outputs).
- Live-simulation fallbacks preserved: if artifacts are missing and the graph
  is loaded, endpoints recompute exactly as before.

Frontend: `app.js` creates the basemap immediately but defers
`loadNetwork/loadHospitals/loadOrigins/loadCandidates` (≈5 MB network payload)
to the **first Simulator tab visit** (`initSimulator()`). Explorer and
Findings never trigger the graph.

### Measured performance (this machine, real measurements only)

| Metric | Phase 3 (eager) | Phase 4 (lazy) |
|---|---|---|
| Time to first API response | ~6.8 s (import + graph load) | **0.56 s** |
| Server RSS before any simulation | ~1,705 MB | **101 MB** (running process), 116 MB at cold start |
| First simulate after idle start | ~0.2 s | **7.5 s** (one-time lazy graph load + first-route warm-up) |
| Second simulate | ~0.2 s | **2.0 s** (same steady state as before) |
| RSS after live graph in memory | 1,685 MB | 1,685 MB (unchanged — one copy) |
| `/api/vuln/detail` (stored way) | live recompute ~0.2–0.4 s | **0.04 s** (file) |
| `/api/research` payload | 3.9 KB | 3.9 KB (unchanged) |

Graph-free serving is proven by tests that monkeypatch `ensure_loaded` to
raise: health/summary/roads/detail/research/candidates all still return 200,
while `POST /api/simulate` correctly fails with “GRAPH LOAD FORBIDDEN”.
A clean-subprocess test serves every research endpoint with the graph
load forbidden and peaks at **< 600 MB** RSS (actual ~150–190 MB including
Python + pandas imports).

## 3. Professional website (PRIORITY 2)

- **Overview (default tab):** name + tagline; the real problem in plain
  English; verified scale tiles (45,304 nodes / 122,599 edges / 453 mapped
  facilities / 100 origins / 100 ways / 10,000 scenarios); study-area
  coverage (~10×11 km CORE, ~15×17 km BUFFER — explicitly not whole-city);
  “CAN say” / “CANNOT say” lists; three-way guide; OSM/Geofabrik attribution.
- **Vulnerability Explorer:** defaults (thresholds 0, sort = composite) show
  the full ranked list immediately; color legend; non-matching roads dimmed to
  0.10 opacity and hidden hospital markers while active; selected road =
  rose (weight 8) on a **white casing** (weight 12) + focused table row;
  column meanings explained in plain language; “modeled access changes for
  sampled origins — not real flood risk” stated on the panel.
- **Manual Simulator:** fully preserved workflow + A Street +442.27 m
  regression still covered by the existing test suite; new 3-step guide;
  blue solid vs dashed pink routes unchanged; first-visit graph-load hint.
- **Findings:** new plain-language sensitivity box explaining odd/even
  (4/5, 2/5) and **east/west 0/5, 0/5** top-five overlap — “treat the lists
  as roads worth a closer look in this sample, not a stable citywide
  priority order” — with numbers injected from the stored artifact only.
- Footer with attribution + “modeled access only” disclaimer; topbar mode
  badge (“research mode — live routing idle” → “live routing loaded · Xs”).

## 4. Remaining performance work (PRIORITY 3)

Browser-side, structurally (no guessing about *causes*, measured where possible):

- **Plateau gates:** filter updates now compute separate table/map
  signatures (visible-set identity). Dragging a slider inside a plateau where
  the visible ways don't change skips the 60-row DOM rebuild and all
  `setStyle` calls entirely.
- **Selection path:** clicking a road restyles only via the existing
  in-place style-key skip + draws one casing group; table row focus is a
  class toggle.
- **Less to draw in Explorer:** hospital layer (453 markers) hidden while
  the Explorer is active and restored on return; Phase 1 network dimmed to
  0.12 opacity; CSS `contain: content` on the scrolling tables.
- **Payloads:** Explorer needs only `/api/vuln/summary` (~50 KB) +
  `phase2_roads.geojson` (97 KB); Findings only 3.9 KB; the 4.67 MB network
  payload loads only on first Simulator visit.
- **In-page profiler:** `window.__cfPerf` records real
  `last/mean/max` applyFilters milliseconds plus the table/map split —
  inspectable in any browser console.

**Honest limitation:** automated browser slider-drag FPS could not be
measured on this machine (no browser automation installed). The profiler
above exists so a human check can read real numbers; no performance claim in
this report is based on a guess.

## 5. Scientific integrity (PRIORITY 4)

Preserved verbatim and re-asserted by tests: top composite way `26182600`
(score 12.895, 4 affected), east/west overlap 0/5 and 0/5, 453 unverified
facilities, 100 grid origins, bounded study area. Copy across Overview /
Explorer / Findings distinguishes modeled access from verified emergency
care, states the origins are a geographic grid sample (not
population-representative), disclaims flood/ambulance/casualty/citywide
claims, and shows OSM/Geofabrik attribution in topbar, footer, simulator
provenance, explorer methodology, and the findings panel.

## 6. Test and verify (PRIORITY 5)

```
env/conda/bin/python -m pytest tests/ -q     # 87 passed in 23.6 s
```

New `tests/test_phase4.py` (18 tests): graph-free endpoint battery with the
graph load forbidden; health research-mode metadata; simulate still requires
the engine; precomputed roads/details match the stored CSVs (100 ways,
top payload 26182600 = 4 affected, score 12.895); server_meta matches real
graph counts; 4-tab shell + Overview default + footer; deferred simulator
init markers; null-safe explorer activation; every DOM id used by JS exists
in the HTML; jsc parses all four scripts; independent clean-subprocess
research-viewer check (< 600 MB, graph never loaded); integrity of stored
Phase 2/3 numbers.

Live server verified end-to-end after restart (pid reported by `ps`): all
static assets and APIs 200; first lazy simulate 7.5 s with exact restore;
second simulate 2.0 s; server log clean.

### Exact launch command

```bash
cd "CityFragility"
env/conda/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

If the precomputed artifacts are ever deleted, rebuild them once (needs the
graph, ~42 s):

```bash
env/conda/bin/python src/phase4_precompute.py
```

## 7. Tested feature list

1. Overview tab: verified scale tiles, can/cannot lists, attribution (health metadata source).
2. Vulnerability Explorer: full stored rankings with default filters, 6 sort metrics, 3 filters, color legend, map dimming, hospital hiding, road click → rose + white casing + focused row, per-origin detail from stored payloads, worst-origin route example, methodology panel.
3. Manual Simulator: lazy graph load on first visit, 20-candidate dropdown, simulate/restore, 6-origin results table, focus-origin route comparison, Phase 0 regression tests still green.
4. Findings: lazy stored findings, plain-language sensitivity box (odd/even + east/west), reproducibility/cross-check/audit metrics, limitations + disclaimer.
5. Health: research mode (metadata) ↔ live mode (after graph load) with identical counts.
6. All 69 pre-existing tests plus 18 new ones pass.

## 8. Unresolved issues

- Real-browser slider-drag frame timing not automated on this machine
  (profiler hook provided instead).
- First live simulation after a fresh server start costs ~7.5 s (lazy graph
  load) — by design, surfaced in the UI hint; steady state unchanged.
- Deleting `data/server_meta.json` while the graph is also unavailable makes
  `/api/health` return 503 (research tabs still work; only the topbar counts
  are affected).
- Map tiles still come from tile.openstreetmap.org (needs network); the
  research data itself is fully local.
