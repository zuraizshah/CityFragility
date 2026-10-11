# Presentation Materials

Everything here is **scripted material for you to review and record
yourself** — no fabricated recordings, no invented metrics.

---

## 1. 90-second video demonstration SCRIPT

*(Screen-record yourself performing these steps against the running app.
Total ≈ 90 s. Speak plainly; every number below is stored and test-verified.)*

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:08 | Browser on `http://127.0.0.1:8000` — Overview tab | “This is CityFragility — a research tool that measures how closing a road changes shortest drivable access to mapped healthcare in central Karachi, using real OpenStreetMap data.” |
| 0:08–0:18 | Point at the scale tiles + CAN/CANNOT lists | “The study is bounded: about ten by eleven kilometres of central Karachi. 45,304 road-network nodes, 453 mapped facilities — unverified OSM tags, not confirmed emergency departments.” |
| 0:18–0:35 | Open **Explorer**; table of 100 roads; click top road (rose line + white casing) | “This is the stored experiment: 100 sampled locations × 100 real road ways — ten thousand before-and-after comparisons, measured once and saved. Clicking a road shows its measured effect on each sampled location, with the original and disrupted routes drawn on the map.” |
| 0:35–0:45 | Hover the “+m median” and “aff.” columns | “Affected means a sampled location's nearest-facility route got longer. These are modelled access changes for a sample — not flood risk, not ambulance times.” |
| 0:45–1:05 | Open **Simulator**; select A Street; Simulate Closure; show +442.27 m for DHA Phase 5; Restore | “This is the live part: it loads the real graph once, removes every directed edge of one way, recomputes, and restores exactly. A Street adds 442.27 metres for this origin — a fixed regression test in the suite re-checks that number automatically.” |
| 1:05–1:20 | Open **Findings**; point at 0 mismatch tiles and the east/west 0-of-5 box | “Validation: re-running the metrics gives zero mismatches; an independent routing implementation agrees on every checked row. But rankings are sensitive — the east and west halves of the study agree on zero of the top five roads, so we present them as exploratory, not authoritative.” |
| 1:20–1:28 | Static site briefly, or back to Overview + footer attribution | “A static version of the findings runs without any server. Data © OpenStreetMap contributors, ODbL. Not peer-reviewed; not a citywide model.” |

**Recording tips:** 1280×720 or better, no personal tabs visible, no console
errors, speak the disclaimer lines verbatim.

---

## 2. One-page nontechnical explanation

**CityFragility — what it is (one page).**

Cities run on roads. When a road is blocked, the fastest way to the nearest
hospital can get longer — or, on a network of one-way streets, stop existing.
CityFragility is a small, transparent research instrument that measures this
for one city slice: **central Karachi**, using free **OpenStreetMap** data
from **October 2026**.

Researchers picked **100 sample spots** across a 10×11 km window and **100
real road segments**. Each road was “closed” in a computer model of the
driving network, and the tool recalculated, for every sample spot, how far
the nearest tagged hospital became by road. That's **10,000 measurements**.
Most tested roads (55) made at least one sample route longer; a third (34)
changed which hospital was closest. The single most disruptive road by a
transparent score was **“Ziauddin Hospital Chowrangi”** (+889 m median extra
driving distance for the four sample spots affected).

Then the work was checked two ways: re-running the calculations reproduced
every number exactly (zero mismatches), and a second, independently written
routing engine agreed on every tested row. A third check asked: *if we split
the sample in half geographically, do the “top 5” lists stay the same?* They
don't — the east and west halves agree on **none** of the top five. That
honesty is part of the result: the lists flag roads worth a closer look, not
a citywide priority ranking.

What this is **not**: not a flood simulator, not an ambulance-time
calculator, not a claim about any hospital's emergency capabilities (the
facility points are crowd-sourced tags), and not representative of Karachi's
population — the sample spots are geographic, not demographic.

What it **is**: a reproducible, fully documented student project — code,
data provenance, tests, limitations — that shows how to measure network
fragility carefully and publish the uncertainty along with the numbers.

---

## 3. Technical architecture (short)

```
[Geofabrik Pakistan PBF, 2026-10-09, sha256-pinned]
        │  pyrosm bbox extract (buffer window)
        ▼
[Directed driving graph  45,304 nodes / 122,599 edges]  ← NetworkX, length-weighted
        │
        ├── facilities.gpkg (453 OSM hospital tags → 419 snap nodes)
        ├── origins: 6 landmark (Phase 1) + 100 grid (Phase 2, seed 20261010)
        ▼
[routing.py — frozen, regression-tested engine]
        │
        ├─ Phase 1: live single-closure API (remove → route → restore, locked)
        ├─ Phase 2: batch 100×100 experiment → CSV/JSON artifacts
        ├─ Phase 3: validation → phase3_findings.json
        ▼
[Saved artifacts] ──► FastAPI server (lazy graph, research mode)
                └──► static_site build (JSON only, no server)
                          ▼
              Leaflet front ends (vanilla JS, canvas renderer)
```

- **One graph copy** in memory; mutations reversible and verified.
- **Research tabs are file-backed** (~100 MB idle); the 1.7 GB graph loads
  only for live simulation.
- **Pure filter/ranking logic** extracted to `explorer-core.js` and tested
  headlessly; DOM/map code is thin.
- **Tests (87+)** encode the scientific contract: fixed regression values,
  monotonicity, restore identity, artifact parity, sensitivity anchors.

---

## 4. Demonstrates vs does not demonstrate

| The system demonstrates | The system does NOT demonstrate |
|---|---|
| End-to-end reproducible network experiment on real OSM data | Peer-reviewed science |
| Exact, test-pinned measured effects of 100 full-way closures on 100 sample points | Real flood/accident/incident effects |
| Transparent scoring + multiple rankings | A definitive “most critical road” |
| Independent-engine cross-checking and restore verification | Correctness under unmodelled conditions (congestion, signals) |
| Honest sensitivity analysis (0/5 east-west overlap) | Citywide or demographic representativeness |
| Professional engineering: lazy loading, measured performance, 87+ tests | Operational emergency planning capability |
| ODbL-compliant attribution and data provenance | Verified hospital/emergency-department data |

---

## 5. Suggested Common App activity wording (< 150 characters)

> Built CityFragility: an OSM-based research tool measuring how road closures
> change hospital access in Karachi; 10,000 modelled scenarios, 87+ tests.

(148 characters. Pair with “Research Project” or “Computer Science” category;
keep the static site + repo private until you approve publication.)

---

## 6. What YOU must review, validate and understand before presenting

Do not present this work until you can personally do all of the following:

1. **Run everything yourself:** tests (`pytest tests -q`), local app, static
   site preview — using only the commands in README/DEMO_GUIDE.
2. **Re-derive the headline numbers from the CSVs** (top composite way
   26182600 = 12.895; 55/100 affected; 0 disconnections; east/west 0/5) —
   e.g. sort `reports/phase2_results.csv` yourself.
3. **Explain the composite formula** in words and why disconnections are
   weighted ×5.
4. **Explain the sampling design** (5×5 grid × 4, seed) and why it is *not*
   population-representative.
5. **Explain the candidate bias** (path-frequency tier favours central
   corridors; 1.18% of network length).
6. **State the facility disclaimer from memory:** OSM tags, no registry, no
   emergency-capability claim; 453→419 nodes, 95 near-duplicate pairs.
7. **State the ranking-instability result** (odd/even 4/5 & 2/5; east/west
   0/5 & 0/5) and what it means for interpretation.
8. **Know the non-claims:** no flood, ambulance, casualty, citywide or
   lives-saved statements — ever.
9. **Review every page of `public_site/` and the local app** for wording you
   would not defend in an interview; edit before release.
10. **Decide licensing** (add `LICENSE` for code; data stays ODbL) and
    **approve (or decline) public hosting** — nothing was pushed or deployed.
11. **Read `LIMITATIONS.md` aloud once** — if any sentence feels
    uncomfortable to say, fix the project, not the sentence.
12. **Prepare for hard questions:** “Why only 100 roads?”, “Why full-way
    closures?”, “What would make rankings stable?”, “How do you know the
    graph is right?” — answers live in METHODOLOGY.md and RESEARCH_PAPER.md.

---

## 7. Honest citation block (for submissions)

> CityFragility: student research project (2026). Road network and facility
> data © OpenStreetMap contributors, via Geofabrik (ODbL), 2026-10-09
> snapshot. Bounded central-Karachi study; 100 grid-sampled origins × 100
> OSM ways. Not peer-reviewed. Not a citywide, flood, ambulance or
> emergency-care model. Limitations: LIMITATIONS.md.
