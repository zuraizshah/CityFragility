/* CityFragility — static public research site.
   Reads ONLY precomputed JSON in ../data (no backend, no graph, no live
   simulation). All values are stored Phase 2/3 measurements. */

/* Set this once the repository is public, e.g.
   "https://github.com/<user>/CityFragility" — until then the docs list
   shows a pending label instead of a broken link. */
const REPO_URL = "";
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 1) =>
    v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  const SCALE = ["#38bdf8", "#34d399", "#fbbf24", "#fb923c", "#ef4444"];
  const state = { results: null, rows: [], map: null, roadLayers: [], originLayer: null, selected: null };

  async function getJson(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  }

  /* ------------------------------------------------------------- scale */
  function renderScale(study, results) {
    const s = results.summary;
    $("scale-tiles").innerHTML =
      `<div class="tile"><b>${study.graph_nodes.toLocaleString()}</b><span>road-network nodes</span></div>` +
      `<div class="tile"><b>${study.graph_edges.toLocaleString()}</b><span>directed edges</span></div>` +
      `<div class="tile"><b>${study.mapped_facilities}</b><span>mapped facilities (unverified)</span></div>` +
      `<div class="tile"><b>${s.n_origins}</b><span>grid-sampled origins</span></div>` +
      `<div class="tile"><b>${s.n_candidates_completed}</b><span>road ways tested</span></div>` +
      `<div class="tile"><b>${(s.n_origins * s.n_candidates_completed).toLocaleString()}</b><span>before/after comparisons</span></div>`;
    const b = study.buffer_bbox_wgs84_wsen;
    $("area-note").innerHTML =
      `Core analysis window ~10 × 11 km, network buffer ~15 × 17 km, central Karachi ` +
      `(W,S,E,N = <code>${b.join(", ")}</code>). Data: ${esc(study.snapshot)}. ` +
      `<b>This is a bounded study area — not citywide coverage.</b>`;
  }

  /* --------------------------------------------------------------- map */
  function scoreColor(score, max) {
    const t = Math.max(0, Math.min(1, score / max));
    return SCALE[Math.min(SCALE.length - 1, Math.floor(t * SCALE.length))];
  }

  function initMap(study, results) {
    const s = results.summary;
    const maxScore = Math.max(...state.rows.map((r) => r.disruption_score || 0));
    const map = L.map("map", { scrollWheelZoom: false }).setView([24.845, 67.045], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    state.map = map;

    const rect = (bbox, color, dash, label) =>
      L.rectangle(
        [[bbox[1], bbox[0]], [bbox[3], bbox[2]]],
        { color, weight: 1.5, dashArray: dash, fill: false, interactive: false }
      ).bindTooltip(label, { sticky: true }).addTo(map);
    rect(study.buffer_bbox_wgs84_wsen, "#64748b", "6 6", "Network buffer (~15 × 17 km)");
    rect(study.core_bbox_wgs84_wsen, "#2dd4bf", null, "Core analysis window (~10 × 11 km)");

    const roads = L.geoJSON(
      { type: "FeatureCollection", features: state.roadGeo.features },
      {
        style: (f) => ({
          color: scoreColor(f.properties.disruption_score || 0, maxScore),
          weight: 4,
          opacity: 0.9,
        }),
        onEachFeature: (f, layer) => {
          const p = f.properties;
          layer.bindPopup(() =>
            `<div class="popup-title">${esc(p.name || "(unnamed way)")}</div>` +
            `<div class="popup-muted">osm/${esc(p.osmid)} · score ${fmt(p.disruption_score, 2)} · ` +
            `${fmt(p.n_affected, 0)}/${s.n_origins} origins affected · ` +
            `${p.n_newly_disconnected > 0 ? `<b>${fmt(p.n_newly_disconnected, 0)} disconnected</b>` : "0 disconnected"}</div>` +
            `<div class="popup-muted">median +${fmt(p.median_extra_m)} m · max +${fmt(p.max_extra_m)} m</div>` +
            `<div class="popup-muted">precomputed scenario — not a live simulation</div>`
          );
          layer.on("click", () => selectRoad(p.osmid, { pan: false }));
          state.roadLayers.push({ osmid: p.osmid, layer });
        },
      }
    ).addTo(map);

    getJson("data/origins.json").then((origins) => {
      L.geoJSON(
        {
          type: "FeatureCollection",
          features: origins.map((o) => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [o.lon, o.lat] },
            properties: { id: o.id, baseline_m: o.baseline_m },
          })),
        },
        {
          pointToLayer: (f, ll) =>
            L.circleMarker(ll, {
              radius: 3.5, color: "#fff", weight: 0.6,
              fillColor: "#818cf8", fillOpacity: 0.9,
            }).bindTooltip(`${f.properties.id} (baseline ${fmt(f.properties.baseline_m, 0)} m)`),
        }
      ).addTo(map);
    });

    map.fitBounds(L.latLngBounds([
      [study.buffer_bbox_wgs84_wsen[1], study.buffer_bbox_wgs84_wsen[0]],
      [study.buffer_bbox_wgs84_wsen[3], study.buffer_bbox_wgs84_wsen[2]],
    ]), { padding: [12, 12] });

    $("map-legend").innerHTML =
      `<div class="score-legend">` +
      `<span class="score-legend-label"><b>Measured composite disruption score</b> ` +
      `(transparent formula — see Methodology)</span>` +
      `<div class="score-gradient" role="img" aria-label="Colour scale from score 0 to ${fmt(maxScore, 2)}"></div>` +
      `<div class="score-ends">` +
      `<span><i class="dot" style="background:${SCALE[0]}"></i> 0 — no measured effect on sampled origins</span>` +
      `<span><i class="dot" style="background:${SCALE[SCALE.length - 1]}"></i> ` +
      `${fmt(maxScore, 2)} — highest measured score in this study</span>` +
      `</div>` +
      `</div>` +
      `<span><i class="swatch" style="background:#818cf8;border-radius:50%"></i>sampled origin (100)</span>` +
      `<span><i class="swatch" style="background:#2dd4bf"></i>core analysis window</span>`;
  }

  /* ------------------------------------------------------------- table */
  function renderTable() {
    const metric = $("metric-select").value;
    const rows = state.rows.slice().sort(
      (a, b) => (b[metric] ?? -Infinity) - (a[metric] ?? -Infinity)
    );
    const tb = $("roads-table").querySelector("tbody");
    const sel = String(state.selected);
    tb.innerHTML = rows.map((r, i) =>
      `<tr data-osmid="${esc(r.osmid)}" class="${String(r.osmid) === sel ? "focused" : ""}">` +
      `<td>${i + 1}</td>` +
      `<td>${esc(r.name || "(unnamed way)")}<div class="tiny">osm/${esc(r.osmid)} · ${esc(r.selection_tier)}</div></td>` +
      `<td>${fmt(r.n_affected, 0)} <span class="tiny">${fmt(r.pct_affected, 1)}%</span></td>` +
      `<td>${fmt(r.median_extra_m, 0)}</td>` +
      `<td>${fmt(r.max_extra_m, 0)}</td>` +
      `<td>${r.n_newly_disconnected > 0 ? `<span class="disc-tag">${fmt(r.n_newly_disconnected, 0)}</span>` : "0"}</td>` +
      `<td><b>${fmt(r.disruption_score, 2)}</b></td></tr>`
    ).join("");
  }

  function selectRoad(osmid, opts = {}) {
    state.selected = osmid;
    const row = state.rows.find((r) => String(r.osmid) === String(osmid));
    if (!row) return;
    renderTable();
    $("road-detail").classList.remove("hidden");
    $("road-detail").innerHTML =
      `<b>${esc(row.name || "(unnamed way)")}</b> — osm/${esc(row.osmid)} · ${esc(row.selection_tier)} · ` +
      `${fmt(row.length_m, 0)} m · ${fmt(row.edges, 0)} directed edges<br>` +
      `<b>${fmt(row.n_affected, 0)}</b> of 100 sampled origins affected (${fmt(row.pct_affected, 1)}%) · ` +
      `median <b>+${fmt(row.median_extra_m)} m</b>, max <b>+${fmt(row.max_extra_m)} m</b> · ` +
      `<b>${fmt(row.n_newly_disconnected, 0)}</b> newly disconnected · ` +
      `<b>${fmt(row.n_destination_switched, 0)}</b> destination switches · ` +
      `composite score <b>${fmt(row.disruption_score, 2)}</b><br>` +
      `<span class="tiny">Stored measurement from reports/phase2_results.csv (row per origin in phase2_per_origin.csv).</span>`;
    for (const { osmid: o, layer } of state.roadLayers) {
      layer.setStyle({
        weight: String(o) === String(osmid) ? 8 : 4,
        color: String(o) === String(osmid) ? "#f43f5e"
          : scoreColor(
              state.rows.find((r) => String(r.osmid) === String(o))?.disruption_score || 0,
              Math.max(...state.rows.map((r) => r.disruption_score || 0))
            ),
        opacity: String(o) === String(osmid) ? 1 : 0.75,
      });
      if (String(o) === String(osmid)) {
        layer.bringToFront();
        if (opts.pan !== false && state.map) {
          state.map.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: 15 });
        }
      }
    }
    document.querySelector(`tr[data-osmid="${CSS.escape(String(osmid))}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }

  /* ------------------------------------------------- sensitivity visual */
  function overlapDots(overlap, topK) {
    const filled = overlap || 0;
    const total = topK || 5;
    let html = "";
    for (let i = 0; i < total; i++) {
      html += `<span class="ov-dot${i < filled ? " ov-on" : ""}"></span>`;
    }
    return html;
  }

  function renderSensitivity(f) {
    const sens = f.sensitivity || {};
    const oe = sens.odd_even || {};
    const ew = sens.east_west || {};
    const row = (splitLabel, metricLabel, ov) => {
      const k = ov ? ov.overlap : 0;
      const topK = ov ? ov.top_k : 5;
      return (
        `<div class="ov-row">` +
        `<div class="ov-title"><b>${esc(splitLabel)}</b> · ${esc(metricLabel)}</div>` +
        `<div class="ov-dots">${overlapDots(k, topK)}</div>` +
        `<div class="ov-count">${k} / ${topK} shared</div>` +
        `</div>`
      );
    };
    $("sensitivity-vis").innerHTML =
      row("Odd vs even origins", "composite-score ranking", oe.by_composite_score?.overlap) +
      row("Odd vs even origins", "origins-affected ranking", oe.by_affected_count?.overlap) +
      row("East vs west half", "composite-score ranking", ew.by_composite_score?.overlap) +
      row("East vs west half", "origins-affected ranking", ew.by_affected_count?.overlap) +
      `<p class="hint">Filled dots = roads that appear in the top five of
        <em>both</em> halves of the split. The east and west halves share
        <b>none</b> of their top-five roads on either ranking — a strong, stored
        warning that rank order depends on which locations you sample.
        Counts only; no significance test is claimed.</p>`;
  }

  /* ------------------------------------------------------ repository link */
  function renderRepoLink() {
    const el = $("repo-link");
    if (!el) return;
    if (REPO_URL) {
      el.outerHTML =
        `<a href="${esc(REPO_URL)}" rel="noopener">${esc(REPO_URL)}</a>`;
    }
    /* empty REPO_URL: keep the pending label already in the HTML */
  }

  /* ---------------------------------------------------------- findings */
  function renderFindings(f, results) {
    const rep = f.reproducibility || {};
    const cc = f.cross_check || {};
    const sens = f.sensitivity || {};
    const audit = f.facility_audit || {};
    const oe = sens.odd_even || {};
    const ew = sens.east_west || {};
    const ovl = (o) => o ? `${o.overlap}/${o.top_k}` : "—";
    const mism = (cc.baseline_distance_mismatches || 0) + (cc.disrupted_distance_mismatches || 0) +
      (cc.facility_identity_mismatches || 0) + (cc.disconnect_flag_mismatches || 0) +
      (cc.switch_flag_mismatches || 0);

    $("findings").innerHTML =
      `<div class="metrics">` +
      `<span>re-run reproducibility: <b>${(rep.metric_mismatches || []).length} mismatches</b> over ${rep.ways_recomputed ?? "?"} ways</span>` +
      `<span>independent engine cross-check: <b>${mism} mismatches</b> over ${cc.origin_rows_checked ?? "?"} origin rows</span>` +
      `<span>odd/even top-5 overlap: <b>${ovl(oe.by_composite_score?.overlap)}</b> score, <b>${ovl(oe.by_affected_count?.overlap)}</b> affected</span>` +
      `<span>east/west top-5 overlap: <b>${ovl(ew.by_composite_score?.overlap)}</b> score, <b>${ovl(ew.by_affected_count?.overlap)}</b> affected</span>` +
      `<span>facilities: <b>${audit.total_facilities ?? "?"}</b> mapped → <b>${audit.usable_snap_nodes ?? "?"}</b> unique snap nodes</span>` +
      `</div>` +
      `<ul>${(f.verified_findings || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
      `<p class="hint">Validation runtime ${fmt(f.runtime?.total_s, 1)} s · validated ${esc(f.date)} · ` +
      `source: <code>reports/phase3_findings.json</code></p>` +
      `<p class="hint"><b>Ranking sensitivity in plain language:</b> the “top 5” lists change with how the ` +
      `sample locations were split. The east and west halves of the study area agree on ` +
      `<b>0 of 5</b> top roads. Treat rankings as “roads worth a closer look in this sample”, ` +
      `not a stable citywide priority order.</p>`;
  }

  function renderMethodology(results) {
    const s = results.summary;
    const samp = results.sampling || {};
    const cm = results.candidates_method || {};
    const biases = (cm.biases || []).map((b) => `<li>${esc(b)}</li>`).join("");
    $("methodology").innerHTML =
      `<ul>` +
      `<li><b>Road network:</b> driving graph from OpenStreetMap (Geofabrik Pakistan PBF, ` +
      `${esc(s.retrieval_date || "2026-10-09")} snapshot) over the buffer window: ` +
      `${s.graph_nodes?.toLocaleString() ?? "45,304"} nodes / ${s.graph_edges?.toLocaleString() ?? "122,599"} directed edges, one-ways preserved.</li>` +
      `<li><b>Origins:</b> ${esc(samp.method || "geographic grid sample")} — seed ${esc(samp.seed)}, ` +
      `${samp.sample_size} points. <b>Not population-weighted, not patient locations.</b></li>` +
      `<li><b>Tested roads:</b> ${esc(cm.method || "?")} — documented selection bias:</li>` +
      `<ul>${biases}</ul>` +
      `<li><b>Experiment:</b> each way removed entirely (all directed edges), shortest drivable distances ` +
      `recomputed for all origins to the nearest mapped facility, graph restored and verified — ` +
      `${(s.n_origins * s.n_candidates_completed).toLocaleString()} comparisons total, ` +
      `${fmt(s.runtime_s?.mean_scenario_ms, 0)} ms per scenario.</li>` +
      `<li><b>Composite score:</b> <code>${esc(s.composite_score_formula)}</code> — transparent arithmetic, ` +
      `not an AI score. Separate per-dimension rankings are also shown above.</li>` +
      `<li><b>Restore check:</b> graph identical after every scenario: ` +
      `<b>${s.restore_verified_identical ? "verified" : "FAILED"}</b>.</li>` +
      `</ul>`;
  }

  function renderLimits(f) {
    const audit = f.facility_audit || {};
    const lims = (f.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
    $("limits").innerHTML =
      `<ul>${lims}</ul>` +
      `<ul>` +
      `<li><b>This static page</b> shows precomputed scenarios only — it does not run live road closures ` +
      `and cannot predict floods, accidents, traffic, ambulance times or casualties.</li>` +
      `<li><b>Facilities are unverified OSM tags</b>${audit.disclaimer ? `: ${esc(audit.disclaimer)}` : "."}</li>` +
      `<li><b>100 origins are a geographic grid sample</b> — no population representativeness is claimed.</li>` +
      `</ul>` +
      `<p class="hint"><b>Disclaimer (as stored):</b> ${esc(f.disclaimer || "")}</p>`;
  }

  /* --------------------------------------------------------------- wire */
  function wire() {
    $("metric-select").addEventListener("change", () => {
      state.selected = state.selected; // keep selection, re-rank
      renderTable();
    });
    $("roads-table").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-osmid]");
      if (tr) selectRoad(tr.dataset.osmid);
    });
  }

  async function main() {
    const [study, results, findings, roadGeo] = await Promise.all([
      getJson("data/study_area.json"),
      getJson("data/results.json"),
      getJson("data/findings.json"),
      getJson("data/roads.geojson"),
    ]);
    state.results = results;
    state.rows = results.rows;
    state.roadGeo = roadGeo;
    renderScale(study, results);
    initMap(study, results);
    renderTable();
    renderFindings(findings, results);
    renderSensitivity(findings);
    renderMethodology(results);
    renderLimits(findings);
    renderRepoLink();
    wire();
    // default selection: the top composite way — meaningful results immediately
    const top = state.rows.slice()
      .sort((a, b) => (b.disruption_score || 0) - (a.disruption_score || 0))[0];
    if (top) selectRoad(top.osmid, { pan: false });
  }

  main().catch((e) => {
    const el = $("scale-tiles");
    if (el) el.innerHTML = `<div class="tile"><b>!</b><span>${esc(e.message)}</span></div>`;
    console.error(e);
  });
})();
