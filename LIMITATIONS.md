# Limitations

Plain-language statement of what CityFragility **cannot** claim. These apply
to every page of the product, the static site, and all reports.

## 1. Model scope

- **Modelled network access only.** Results are shortest *drivable distance*
  changes on one extracted OSM graph. Not travel times: no congestion,
  signals, turn restrictions, road capacity, or time-of-day effects.
- **Hypothetical full-way closures.** A candidate = one complete OSM way
  removed (up to ~4 km). Real incidents close lanes/partial segments; these
  are upper-bound stress tests, not incident forecasts.
- **No event prediction.** Nothing here predicts floods, landslides,
  accidents or any real closure; scenarios are constructed what-ifs.
- **Bounded study area.** Core ~10 × 11 km, buffer ~15 × 17 km of central
  Karachi. **Not citywide coverage.** Conclusions do not transfer to other
  cities or to Karachi as a whole.

## 2. Sample limits

- **100 origins are a geographic grid sample** (5 × 5 cells × 4, seed
  20261010). They are **not population-representative**, not patient homes,
  not weighted by demand. “6/100 origins affected” is a statement about the
  sample only.
- **100 candidate ways are a biased subset** (1.18% of network length):
  path-frequency tiers favour central corridors; service roads excluded.
  **Rankings are not a citywide criticality assessment.**
- **Rankings are unstable.** East/west split: top-5 overlap **0/5** on both
  the composite and affected-count rankings (odd/even: 4/5 and 2/5). Rank
  order should be treated as exploratory.

## 3. Facility data (unverified)

- Facility points are **OpenStreetMap mapper tags** (`amenity=hospital`).
  No official health registry was consulted. **No 24/7 emergency, trauma or
  even hospital-operating status is confirmed for any point.**
- Duplicate mapping: 453 points → 419 unique snap nodes; 95 near-duplicate
  pairs ≤ 50 m; 8 duplicated-name clusters; 124 usable names are
  limited-scope (dental/diagnostic/clinic…).
- “Nearest facility” therefore means “nearest tagged, reachable node” —
  **not nearest verified emergency care.**

## 4. Explicit non-claims

This project does **not** claim or estimate:

- flood or disaster risk of any kind;
- ambulance travel times or emergency response times;
- casualties, injuries, lives saved, or health outcomes;
- traffic delay, emissions, or economic impact;
- operational status of any hospital;
- demographic or equity conclusions (no population data used).

## 5. Data-quality limits

- OSM completeness and mapper bias apply to this region (snapshot
  2026-10-09); missing roads or facilities change results.
- Boundary truncation: 9 sampled origins lie within 200 m of the core edge;
  routes near the buffer edge may be affected by the extract boundary.
- Snapping (≤ 300 m) and straight-line facility positions introduce small
  placement errors (median snap 27.1 m).

## 6. Process status

- **Not peer-reviewed.** Validation (Phase 3) is internal: reproducibility,
  an independent routing-engine cross-check, sensitivity analysis, and a
  data audit.
- Single-city, single-snapshot study; no uncertainty intervals beyond the
  published sensitivity partitions.
- A student project; results are offered for inspection and critique, not as
  an operational planning authority.

## 7. Where honest claims *do* hold

For the fixed artifacts in `reports/`, the following are measured, tested
and reproducible: per-origin before/after distances for 10,000 scenarios;
way-level rollups; 0/0/0 mismatches in reproducibility + independent
cross-check; sensitivity overlaps 4/5, 2/5, 0/5, 0/5; facility audit counts.
See `RESEARCH_PAPER.md` §8–§11 and `reports/phase3_findings.json`.
