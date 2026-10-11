# Phase 3 — Research Validation Report

Generated 2026-10-11 from saved Phase 0/1/2 artifacts (no experiment re-run, no downloads). Runtime 11.3 s, peak RSS 1779 MB.

## 1. Research question

Under a road-network accessibility model of bounded central Karachi, which tested road closures measurably degrade shortest drivable access from sampled origins to the nearest mapped healthcare facility — and how robust are those findings to sampling, data quality and modelling assumptions?

## 2. Dataset sources and provenance

- Road network: OpenStreetMap via Geofabrik `pakistan-latest.osm.pbf` (snapshot 2026-10-09, sha256-pinned, ODbL); drive graph 45,304 nodes / 122,599 directed edges (`data/network_drive.graphml`).
- Facilities: 453 OSM points tagged as healthcare facilities (`data/hospitals.gpkg`), unverified.
- Origins: 100 grid-sampled nodes (seed 20261010, `data/phase2_origins_sample.csv`).
- Candidates: 100 OSM ways in four documented tiers (`data/phase2_candidates.csv`).
- Experiment artifacts: `reports/phase2_per_origin.csv` (10,000 rows), `reports/phase2_results.csv`, `reports/phase2_summary.json`.

## 3. Methodology

Shortest drivable distances on the directed graph (one-ways honoured, edge length in metres). Each candidate way is fully removed, distances to the nearest facility snap node recomputed for all 100 origins, then the graph is restored exactly. Disconnections are recorded as flags with null detours (never infinity). Composite score: `n_affected + 5*n_disconnected + min(median_extra_m/100, 20)` — transparent, documented, not an AI score. Phase 3 validation recomputes everything from saved rows and re-checks selected scenarios with the independent Phase 0 networkx engine.

## 4. Measured results (unchanged from Phase 2)

- 55/100 tested ways affect ≥1 origin; 0/100 disconnect any origin; 34/100 change a nearest facility.

Top 5 by composite score:

| osmid | name | affected | median +m | score |
|---|---|---|---|---|
| 26182600 | Ziauddin Hospital Chowrangi | 4 | 889.51 | 12.895 |
| 182385941 | (unnamed) | 2 | 1046.54 | 12.465 |
| 39998276 | 10th Street | 3 | 942.71 | 12.427 |
| 485726463 | (unnamed) | 3 | 835.21 | 11.352 |
| 40119137 | ایونیو 3 | 2 | 825.45 | 10.255 |

Top 5 by affected count:

| osmid | name | affected | median +m | max +m |
|---|---|---|---|---|
| 219168400 | 15th Lane | 6 | 206.28 | 501.75 |
| 479722526 | 15th Lane | 5 | 204.94 | 301.15 |
| 1475627437 | (unnamed) | 5 | 204.94 | 500.41 |
| 26182600 | Ziauddin Hospital Chowrangi | 4 | 889.51 | 1261.02 |
| 26800453 | Brunton Road | 4 | 465.45 | 465.45 |

The two rankings disagree — a road can touch many origins with small detours or fewer origins with very large detours. Neither alone defines 'most critical'.

## 5. Validation tests

**Reproducibility (task 1).** All 100 way rows and all five ranking lists recompute exactly from the 10,000 saved per-origin rows (8 columns; 0 mismatches; rankings match: True).

**Independent cross-check (task 2).** 11 ways (26182600, 182385941, 39998276, 485726463, 40119137, 219168400, 479722526, 1475627437, 26800453, 221699173, 25976974) and 89 origin rows were recomputed with the Phase 0-trusted networkx engine (networkx.multi_source_dijkstra on the reversed graph with path reconstruction (Phase 0-verified routing family, independent implementation from the Phase 2 heap Dijkstra)). Mismatches: baseline distances 0, disrupted distances 0, facility identity 0, disconnect flags 0, switch flags 0 (tolerance 0.05 m). Graph restore verified after every scenario.

## 6. Sensitivity analysis

Origins were split two ways (odd/even by sampling order; east/west by median longitude 67.04581; 50 west / 50 east). Rankings were recomputed independently within each half:

| partition | ranking | top-5 overlap | ways with effect (A/B) |
|---|---|---|---|
| odd_even | by_composite_score | 4/5 | 47/50 |
| odd_even | by_affected_count | 2/5 | 47/50 |
| east_west | by_composite_score | 0/5 | 40/17 |
| east_west | by_affected_count | 0/5 | 40/17 |

Overlap is partial in every case: individual rank positions are unstable under resampling. The defensible conclusion is that certain ways measurably affect access *for this sample*, not that any road is definitively Karachi's most critical. Rankings are computed independently within each partition (half the origins each). Low overlap means ranks depend on which origins were sampled — not that any road is uniquely critical for Karachi.

## 7. Facility data-quality audit

- 453 mapped facilities; 453 usable within 300.0 m of the network (snap-node dedupe → 419 unique nodes).
- Snap distances: median 27.1 m, p95 73.6 m, max 175.5 m; 0 above 250 m.
- 95 near-duplicate pairs within 50 m (different OSM ids, possibly the same site); 8 duplicated name clusters.
- 124 usable facilities have names suggesting limited scope (dental/diagnostic/clinic etc.) — the OSM `amenity=hospital` tag is a mapper label, not an emergency-department confirmation.
- 149 usable facilities sit outside the CORE box (still reachable; boundary effects noted in §8).

9 inspected facilities (up to 5 highest snap distances + up to 5 serving the top-ranked way's affected origins):

| osmid | name | snap m | outside core | limited-scope name |
|---|---|---|---|---|
| 4785947196 | Clifton Hospital | 22.9 | no | no |
| 4786285990 | DHA Medical Centre | 23.5 | no | no |
| 5051184069 | Hassan Railway Hospital | 103.6 | no | no |
| 5306005133 | Sick Bay NORE-I | 11.3 | no | no |
| 7241491371 | Madina Homeo Pethic | 101.7 | no | yes |
| 12162751022 | Alkhidmat Virology & Genetic Lab | 95.8 | yes | no |
| 12213583964 | Dr Mehdi S. Chunara Clinic | 175.5 | yes | yes |
| 723897308 | 7th Day Adventist Hospital | 103.0 | no | no |
| 993569855 | ضیاء الدین ہسپتال | 35.9 | no | no |

Facilities are OpenStreetMap points carrying an amenity=hospital (or similar) mapper tag. This audit checks coordinates, duplication and naming scope ONLY. No clinical or emergency capability is verified or claimed for any facility.

Effect on findings: nearest-facility identities and switches inherit any mis-snapping or duplication error; detour *magnitudes* for a given origin are less sensitive (they depend on the road network, not on which duplicate won).

## 8. Study-area and modelling assumptions

- **Boundary:** 9 origins within 200 m of the CORE edge (min 3.7 m). Facilities are drawn from the full BUFFER area while origins are restricted to CORE; routes near the CORE edge may be truncated relative to a wider network.
- **Full-way closures:** candidate lengths 11.0–4702.0 m (median 585.0 m). Each scenario closes an ENTIRE OSM way (up to 6 km). Real incidents are usually partial and temporary; full-way closure is an upper-bound stress test.
- **One-ways:** 28.1% of candidate directed edges are genuinely one-way. Routing is fully directed (one-ways honoured). The share above counts candidate-way directed edges that have no opposite-direction twin, i.e. genuinely one-way segments.
- **Candidate bias:** candidates cover 1.18% of total network length; tiers {'sample_path_frequency': 50, 'stratified_fill': 30, 'phase1_origin_path': 12, 'phase0_tested': 8}. Candidates are NOT a random sample of the network: 30% come from high path-frequency tiers, which biases towards roads already used by this origin sample. Unlisted roads were not tested and may still matter.

## 9. Scientific limitations

- Origins are a grid-uniform sample — not population-weighted; results describe this sample only.
- Facilities are unverified OSM tags; no clinical or emergency capability is asserted for any facility.
- Closures are hypothetical and full-way; no flood, traffic, ambulance or casualty modelling is performed.
- Candidate roads are selected (not randomly sampled) and cover a small share of network length; untested roads may be more important.
- Rankings change materially across origin partitions; they are indicative of this sample, not a definitive citywide ranking.
- Graph geometry, one-ways and turn-restriction completeness reflect the 2026-10-09 OSM snapshot and can change conclusions when corrected.

## 10. Future research

- Population-weighted origins (census/building-footprint density) to move from geometric to demographic relevance.
- Verified facility registries (capability, hours) to replace mapper tags; sensitivity of switches to verified-only facility sets.
- Incident-shaped partial closures and time-of-day traffic for travel time instead of free-flow distance.
- Monte-Carlo origin resampling (many seeds) to attach confidence intervals to rankings.
- Extension to flood/heat exposure layers once credible open data is chosen — explicitly out of scope here.

## 11. Reproduce

```bash
env/conda/bin/python src/phase3_validation.py   # ~40 s, one graph load
env/conda/bin/python -m pytest tests -q         # full suite incl. Phase 3
```
