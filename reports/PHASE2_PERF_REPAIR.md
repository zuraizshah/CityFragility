# Phase 2.5 — Critical Performance Repair (Vulnerability Explorer)

Date: 2026-10-11. Scope: fix slider-drag freezing in the Vulnerability Explorer.
No experiment re-run, no data downloads, no rebuild, no new features.

---

## 1. Actual discovered cause (measured, not guessed)

Dragging either filter slider fired an **un-throttled `input` event at display rate
(~60–120×/s)**, and every single event synchronously executed the full pipeline
(original `explorer.js`):

| # | Per-event work (old code) | Measured/derived cost |
|---|---|---|
| 1 | `colorFor(row)` called **once per road feature (100×/event)**, each call doing `V.filtered.map(metricValue).sort(...)` + linear `findIndex` — an O(features × rows log rows) pass | **0.330 ms/event** (jsc micro-benchmark, 100 events; pure colour math only) |
| 2 | `renderTable()`: full `tbody` wipe + up to **60 rows × 7 cells** rebuilt via `innerHTML` + **60 fresh click listeners registered per event** | layout invalidation of the sidebar every event; ~6,000 listener allocations/s at 100 Hz |
| 3 | `restyleRoads()`: rebuilds the `osmid→row` Map and issues **100 × `layer.setStyle(...)`** per event (each computing `colorFor` again → cost 1 counted twice) | canvas-path style invalidation ×100 per event |
| 4 | **No debounce/throttle anywhere** (`input` → `applyFilters` directly) | event queue grows while the main thread is busy → input starvation / beachball |

**Root cause = compound per-event cost × unbounded event rate.** Per-event work
(JS + DOM layout + Leaflet canvas invalidation) exceeded the inter-event interval at
drag rates, so the main thread never yielded and the event backlog stalled the UI.

**Verified NON-causes:** no network requests during slider moves (only
`selectDetail` fetches, on click); the Leaflet map and road layers were created once
at load (`drawRoads` runs only from `load()`); no backend routing/recomputation was
ever reachable from the filter path.

## 2. Fix (files changed)

| File | Change |
|---|---|
| `webapp/static/explorer-core.js` | **NEW** — pure, side-effect-free logic: `filterRows`, `rankRows`, `recomputeColors` (quantile colours precomputed **once per ranking change**, O(1) lookup after), `filterSignature`, `metricValue`. |
| `webapp/static/explorer.js` | Rewritten hot path: `input` handlers now update **only the readout labels**; heavy work runs on a **180 ms trailing debounce** (band 150–250 ms) and immediately on `change` (pointer release). Table/map updates are **signature-gated** (skip when nothing changed). One `innerHTML` table write ≤ 60 rows with **event delegation** (one listener total). `restyleRoads` updates styles **in place with `setStyle` skip-keys** — layers are never recreated, the map is never recreated. Selected road gets a **distinct rose `#f43f5e`, weight 8, opacity 1, bring-to-front** highlight. Full CSV pointer kept in the hint text. |
| `webapp/static/index.html` | Loads `explorer-core.js` before `explorer.js`. Slider defaults confirmed `value="0"` (ranking opens non-empty). |
| `webapp/static/style.css` | Focused table row accent `#f43f5e` matching the map highlight. |
| `tests/explorer_core_test.js` | **NEW** — headless jsc logic tests against the **real 100 stored rows**. |
| `tests/test_phase25_frontend.py` | **NEW** — orchestrates jsc tests + static wiring markers + API integrity checks. |

No server changes; no experiment re-run; no data touched. Static files are served
from disk, so no server restart was required.

## 3. Before / after (honest numbers)

| Measure | Before | After |
|---|---|---|
| Heavy work per `input` event | full pipeline (colour pass 0.330 ms + 60-row DOM rebuild + 100 `setStyle` + Map rebuild) | **2 × `textContent` label writes only** |
| Heavy-work rate while dragging | ~60–120 Hz (un-throttled) | **≤ ~5.5 Hz** (180 ms debounce) + 1× on release |
| Colour path (jsc micro-benchmark, 100 drag events) | **33 ms** (0.330 ms/event, re-sorted per feature) | **1 ms** (0.010 ms/event — filter+rank+O(1) colour lookup) |
| Table DOM writes while dragging | up to 60 rows + 60 listeners **per event** | one `innerHTML` write **per debounced update**, unchanged signature → **zero writes** |
| `setStyle` calls | 100 per event, always | only for layers whose style actually changed (skip-key) |
| Map/layers on slider move | created once (unchanged) | created once (unchanged, now guarded against re-entry) |

The colour-path benchmark was measured headless in JavaScriptCore (same engine
family as Safari). DOM/Leaflet paint cannot be measured without a browser; those
costs were **eliminated from the per-event path entirely** (debounce + skip gates)
rather than optimised, which is why the drag no longer saturates the main thread.

## 4. Verification

- **55/55 tests pass** — 8 Phase 0 routing + 12 Phase 1 webapi + 21 Phase 2 + **14 Phase 2.5** (`reports/pytest_phase2.txt`).
- Headless jsc suite on the real rows: `CORE_TESTS_PASS 100 rows, top=26182600 score=12.895`.
  - Filter correctness at **0** (returns all 100) and nonzero thresholds (no leaks).
  - **Top composite way unchanged: OSM `26182600`, score 12.895, 4 affected, +889.51 m median.**
  - Top affected-count way unchanged: `219168400` (6 affected).
  - Colours only from the documented scale (or slate for zero-effect ways).
- Static markers: debounce 180 ∈ [150, 250]; no `input → applyFilters`; no
  per-event full-sort; defaults `0`; bounded table (60); core script load order.
- API integrity: `/api/vuln/summary` still 100 rows / top `26182600`;
  Phase 1 A Street regression still exactly **+442.27 m**; restore → 122,599 edges.
- Live: `/`, `/explorer-core.js`, `/explorer.js`, `/app.js` all 200; server log
  clean (no errors/500s); graph memory unchanged (1,702 MB, loaded once).
- Console: `explorer.js` and `explorer-core.js` parse clean under JavaScriptCore
  (headless run reaches the expected missing-DOM reference, never a SyntaxError).
  A full interactive browser drag session was not automatable in this environment —
  the before/after mechanism above is from measured hot-path analysis.

## 5. Preserved

- Phase 1 Manual Simulator: untouched behaviour, all 12 API tests pass live.
- Phase 2 stored artifacts: byte-identical (not re-read, not rewritten by this phase).
- Scientific numbers: unchanged — verified against the API and the CSV by tests.
