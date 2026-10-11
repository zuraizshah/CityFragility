/* CityFragility Phase 2 — Vulnerability Explorer.
   Reads ONLY stored experiment artifacts via /api/vuln/* (no mock data).

   Phase 2.5 performance notes (see reports/PHASE2_PERF_REPAIR.md):
   - Filter sliders only re-filter the already-loaded 100 rows in memory.
     No network requests, no backend recomputation, no layer recreation.
   - Heavy work (table rebuild + map restyle) runs on a trailing debounce
     (~DEBOUNCE_MS) and on the slider 'change' event, not on every 'input'.
   - The quantile colour scale is precomputed ONCE per ranking change over
     all rows (stable colours, O(1) lookup) instead of re-sorting inside
     a per-feature loop on every event.
   - Map layers are created once; restyling updates styles in place and
     skips layers whose style has not changed. */
"use strict";

(() => {
  const DEBOUNCE_MS = 180; // within the required 150–250 ms band
  const V = {
    rows: [],
    summary: null,
    sampling: null,
    candsMethod: null,
    filtered: [],
    rank: "disruption_score",
    selectedOsmid: null,
    vulnLayer: null,
    detailLayer: null,
    casingLayer: null,
    refOrigins: null,
    roadGeo: null,
    maxRowsShown: 60, // only visible rows are rendered; full CSV stays on disk
    colorByOsmid: new Map(), // precomputed colours for current ranking
    lastFilterSig: null,
    lastTableSig: null,
    lastMapSig: null,
    filterTimer: null,
    wired: false,
    loaded: false,
  };

  /* Tiny in-page profiler (Phase 4): real measured timings of the filter
     hot path, exposed for inspection — no guessing, no UI overhead. */
  const PERF = { last: 0, mean: 0, max: 0, n: 0, table: 0, map: 0 };
  window.__cfPerf = PERF;
  function timed(fn) {
    const t0 = performance.now();
    const out = fn();
    const dt = performance.now() - t0;
    PERF.last = dt;
    PERF.mean = PERF.n ? (PERF.mean * PERF.n + dt) / (PERF.n + 1) : dt;
    PERF.n += 1;
    if (dt > PERF.max) PERF.max = dt;
    return out;
  }

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 1) =>
    v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  const SCALE = ["#38bdf8", "#34d399", "#fbbf24", "#fb923c", "#ef4444"];
  const SELECTED_COLOR = "#f43f5e"; // distinct from every scale colour

  /* Colours are precomputed ONCE per ranking change by the pure core
     (explorer-core.js); this is just an O(1) lookup per road. */
  function recomputeColors() {
    V.colorByOsmid = ExplorerCore.recomputeColors(V.rows, V.rank);
  }

  function colorFor(osmid) {
    return V.colorByOsmid.get(String(osmid)) || SCALE[0];
  }

  /* ------------------------------------------------------------ data */
  async function load() {
    const res = await fetch("/api/vuln/summary");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    V.summary = data.summary;
    V.rows = data.rows;
    V.sampling = data.sampling;
    V.candsMethod = data.candidates_method;
    V.roadGeo = await (await fetch("/api/vuln/roads.geojson")).json();
    recomputeColors();
    renderStats();
    renderMethodology();
    applyFilters(); // builds filtered list + renders the table (map optional)
    drawRoads();    // no-op until the map exists (Explorer tab first visit)
    wire();
    V.loaded = true;
  }

  function renderStats() {
    const s = V.summary;
    $("vuln-n-origins").textContent = s.n_origins;
    $("vuln-n-cands").textContent = s.n_candidates_completed;
    let aff = 0;
    let disc = 0;
    for (const r of V.rows) {
      if ((r.n_affected ?? 0) > 0) aff++;
      if ((r.n_newly_disconnected ?? 0) > 0) disc++;
    }
    $("vuln-stats").innerHTML =
      `<div class="vs-item"><b>${s.n_origins}</b><span>sample origins</span></div>` +
      `<div class="vs-item"><b>${s.n_candidates_completed}</b><span>ways tested</span></div>` +
      `<div class="vs-item"><b>${aff}</b><span>affected ≥1 origin</span></div>` +
      `<div class="vs-item"><b>${disc}</b><span>caused disconnection</span></div>` +
      `<div class="vs-item"><b>${fmt(s.runtime_s?.total, 1)}s</b><span>experiment runtime</span></div>` +
      `<div class="vs-item"><b>${s.restore_verified_identical ? "verified" : "FAILED"}</b><span>graph restore</span></div>`;
  }

  function renderMethodology() {
    const s = V.summary;
    const samp = V.sampling || {};
    const cm = V.candsMethod || {};
    const sens = s.sensitivity || {};
    const bias = (cm.biases || []).map((b) => `<li>${esc(b)}</li>`).join("");
    $("vuln-methodology").innerHTML =
      `<ul>` +
      `<li><b>Origins:</b> ${esc(samp.method || "?")} Seed ${esc(samp.seed)}; ` +
      `${esc(samp.sample_size)} points. Geographic grid sample — <b>not</b> population-weighted, ` +
      `not patient locations.</li>` +
      `<li><b>Roads:</b> ${esc(cm.method || "?")}</li>` +
      `<li><b>Composite score:</b> <code>${esc(s.composite_score_formula)}</code> — transparent, not an AI score. ` +
      `Separate rankings are also provided.</li>` +
      `<li><b>Sensitivity:</b> ${esc(sens.method || "n/a")} — top-5 overlap on affected-count ranking: ` +
      `${esc(JSON.stringify(sens.by_affected_count || {}))}.</li>` +
      `<li><b>Runtime / memory:</b> ${fmt(s.runtime_s?.total, 1)} s total, ` +
      `${fmt(s.runtime_s?.mean_scenario_ms, 0)} ms per closure, peak RSS ${fmt(s.peak_rss_mb, 0)} MB. ` +
      `Graph restore verified identical: ${s.restore_verified_identical ? "yes" : "NO"}.</li>` +
      `<li><b>Biases:</b><ul>${bias}</ul></li>` +
      `<li><b>Limitations:</b> road-network accessibility model for bounded central Karachi only. ` +
      `Facilities are unverified OSM tags (no emergency-capability claim). Full-way closures are hypothetical. ` +
      `No flood, ambulance, traffic-delay or casualty estimates. Rankings are not a citywide criticality ` +
      `assessment. Mapping errors, boundary truncation and missing turn restrictions can change conclusions.</li>` +
      `<li><b>Provenance:</b> OpenStreetMap via Geofabrik Pakistan PBF (2026-10-09 snapshot, ODbL).</li>` +
      `</ul>`;
  }

  /* ---------------------------------------------------------- filters */
  function currentFilter() {
    return {
      minAff: Number($("vuln-min-aff").value),
      minDet: Number($("vuln-min-det").value),
      discOnly: $("vuln-disc-only").checked,
      rank: V.rank,
    };
  }

  function filterSignature(f) {
    return ExplorerCore.filterSignature(f);
  }

  function updateReadouts(f) {
    $("vuln-min-aff-val").textContent = f.minAff;
    $("vuln-min-det-val").textContent = f.minDet;
  }

  /* Heavy path: re-filter the in-memory rows, re-rank, and update the
     table + map styles only when something they depend on actually changed.
     Never touches the network, the backend, or recreates map layers.
     Phase 4: separate table/map signatures — dragging within a filter
     plateau where the visible sets are identical skips DOM + setStyle work
     entirely (this was the remaining Mac lag during slider drags). */
  function applyFilters() {
    const f = currentFilter();
    updateReadouts(f);
    const sig = filterSignature(f);
    if (sig === V.lastFilterSig) return; // nothing changed → no DOM/map work
    V.lastFilterSig = sig;

    timed(() => {
      V.filtered = ExplorerCore.rankRows(
        ExplorerCore.filterRows(V.rows, f),
        V.rank
      );
      $("vuln-filter-count").textContent =
        `${V.filtered.length} of ${V.rows.length} tested ways match ` +
        `(showing top ${Math.min(V.maxRowsShown, V.filtered.length)}; full list in reports/phase2_results.csv)`;
      const shown = V.filtered.slice(0, V.maxRowsShown);
      const tableSig = `${V.filtered.length}|${V.selectedOsmid}|` +
        shown.map((r) => r.osmid).join(",");
      if (tableSig !== V.lastTableSig) {
        const t0 = performance.now();
        renderTable();
        PERF.table = performance.now() - t0;
        V.lastTableSig = tableSig;
      }
      const mapSig = `${V.filtered.length}|${V.selectedOsmid}|` +
        V.filtered.slice(0, 200).map((r) => r.osmid).join(",");
      if (mapSig !== V.lastMapSig || V._restyleForce) {
        const t0 = performance.now();
        restyleRoads();
        PERF.map = performance.now() - t0;
        V.lastMapSig = mapSig;
        V._restyleForce = false;
      }
    });
  }

  function renderTable() {
    const tb = $("vuln-table").querySelector("tbody");
    const shown = V.filtered.slice(0, V.maxRowsShown);
    if (!shown.length) {
      tb.innerHTML = '<tr class="empty"><td colspan="7">No ways match the current filters.</td></tr>';
      return;
    }
    // one innerHTML write instead of 60× createElement/appendChild
    const sel = String(V.selectedOsmid);
    let html = "";
    for (let i = 0; i < shown.length; i++) {
      const r = shown[i];
      const focused = String(r.osmid) === sel ? ' class="focused"' : "";
      html +=
        `<tr data-osmid="${esc(r.osmid)}"${focused}>` +
        `<td>${i + 1}</td>` +
        `<td>${esc(r.name || "(unnamed way)")}<div class="muted tiny">osm/${esc(r.osmid)} · ${esc(r.selection_tier)}</div></td>` +
        `<td>${fmt(r.n_affected, 0)} <span class="muted tiny">${fmt(r.pct_affected, 1)}%</span></td>` +
        `<td>${fmt(r.median_extra_m, 0)}</td>` +
        `<td>${fmt(r.max_extra_m, 0)}</td>` +
        `<td>${(r.n_newly_disconnected ?? 0) > 0 ? `<span class="tag tag-disc">${fmt(r.n_newly_disconnected, 0)}</span>` : "0"}</td>` +
        `<td><b>${fmt(r.disruption_score, 2)}</b></td>` +
        `</tr>`;
    }
    tb.innerHTML = html; // click handling via delegation (one listener)
  }

  /* ------------------------------------------------------------- map */
  function ensureLayers() {
    const cf = window.__cf;
    if (!cf) return null;
    if (cf.ensureMap) cf.ensureMap();
    const map = cf.state.map;
    if (!map) return null;
    if (!V.vulnLayer) V.vulnLayer = L.layerGroup();
    if (!V.detailLayer) V.detailLayer = L.layerGroup();
    if (!V.casingLayer) V.casingLayer = L.layerGroup();
    return map;
  }

  /* Create stable road layers ONCE (canvas renderer). Each feature keeps a
     reference so later restyles only call setStyle on existing layers. */
  function drawRoads() {
    const map = ensureLayers();
    if (!map || !V.roadGeo || V.vulnLayer.getLayers().length) return;
    for (const feat of V.roadGeo.features) {
      const props = feat.properties;
      const layer = L.geoJSON(feat, {
        style: () => ({
          color: colorFor(props.osmid),
          weight: 4,
          opacity: 0.9,
        }),
        renderer: L.canvas({ padding: 0.4 }),
      });
      layer.on("click", () => selectDetail(props.osmid));
      V.vulnLayer.addLayer(layer);
      feat._layer = layer;
      feat._styleKey = "";
    }
  }

  /* White "casing" polyline under the selected road so the click target is
     unmistakable even against the colour scale. One extra layer group. */
  function drawCasing() {
    if (!V.casingLayer) return;
    V.casingLayer.clearLayers();
    V._casingOsmid = V.selectedOsmid;
    if (V.selectedOsmid == null || !V.roadGeo) return;
    const feat = V.roadGeo.features.find(
      (f) => String(f.properties.osmid) === String(V.selectedOsmid)
    );
    if (!feat || !feat.geometry) return;
    const lines =
      feat.geometry.type === "MultiLineString"
        ? feat.geometry.coordinates
        : [feat.geometry.coordinates];
    for (const line of lines) {
      L.polyline(line.map(([lo, la]) => [la, lo]), {
        color: "#ffffff",
        weight: 12,
        opacity: 0.85,
        interactive: false,
      }).addTo(V.casingLayer);
    }
  }

  /* Update styles in place. Skips setStyle when the computed style is
     identical to the layer's current style (common during drags where most
     roads stay in/out of the filter). Selected way gets a distinct thick
     rose highlight on a white casing. */
  function restyleRoads() {
    if (!V.roadGeo) return;
    if (V.selectedOsmid !== V._casingOsmid) drawCasing();
    const sel = V.selectedOsmid == null ? null : String(V.selectedOsmid);
    const visible = new Set(V.filtered.slice(0, 200).map((r) => String(r.osmid)));
    for (const feat of V.roadGeo.features) {
      const layer = feat._layer;
      if (!layer) continue;
      const oid = String(feat.properties.osmid);
      const isSel = oid === sel;
      const inFilter = visible.has(oid);
      const color = isSel ? SELECTED_COLOR : colorFor(oid);
      const weight = isSel ? 8 : 4;
      const opacity = isSel ? 1 : inFilter ? 0.9 : 0.1;
      const key = `${color}|${weight}|${opacity}`;
      if (feat._styleKey === key) continue; // unchanged → skip the setStyle call
      feat._styleKey = key;
      layer.setStyle({ color, weight, opacity });
      if (isSel) layer.bringToFront();
    }
  }

  /* ----------------------------------------------------------- detail */
  async function selectDetail(osmid) {
    V.selectedOsmid = osmid;
    $("vuln-detail-panel").hidden = false;
    $("vuln-detail-title").textContent = `osm/${osmid}`;
    $("vuln-detail").innerHTML = "Loading stored evidence…";
    markSelectedRow();        // light DOM class toggle only
    V._restyleForce = true;   // selection colour/casing must refresh
    restyleRoads();           // direct call — selection is not a filter change
    try {
      const d = await (await fetch(`/api/vuln/detail?osmid=${osmid}`)).json();
      renderDetail(d);
      drawExample(d.worst_origin_example);
    } catch (e) {
      $("vuln-detail").innerHTML = `<div class="status err">Failed to load detail: ${esc(e.message)}</div>`;
    }
  }

  function markSelectedRow() {
    const tb = $("vuln-table").querySelector("tbody");
    const sel = String(V.selectedOsmid);
    tb.querySelectorAll("tr[data-osmid]").forEach((tr) => {
      tr.classList.toggle("focused", tr.dataset.osmid === sel);
    });
  }

  function renderDetail(d) {
    const m = d.meta;
    const worst = d.worst_origin_example;
    const po = (d.per_origin || [])
      .slice()
      .sort((a, b) => (b.detour_m ?? -1) - (a.detour_m ?? -1))
      .slice(0, 12);
    const poRows = po
      .map(
        (r) =>
          `<tr><td>${esc(r.origin_sample_id)}</td><td>${fmt(r.baseline_m)}</td>` +
          `<td>${fmt(r.disrupted_m)}</td><td class="${r.detour_m > 0 ? "delta-pos" : "na"}">${fmt(r.detour_m)}</td>` +
          `<td>${r.newly_disconnected ? '<span class="tag tag-disc">disc</span>' : r.destination_switched ? '<span class="tag tag-delta">switch</span>' : '<span class="tag tag-unchanged">same</span>'}</td></tr>`
      )
      .join("");
    let worstHtml = "<p class='hint'>No worst-origin example.</p>";
    if (worst) {
      worstHtml =
        `<div class="worst-box">` +
        `<div class="popup-title">${esc(worst.origin_sample_id)} (node ${esc(worst.origin_node)})</div>` +
        `<div>Baseline <b>${fmt(worst.baseline_m)} m</b> → ` +
        (worst.newly_disconnected
          ? `<span class="tag tag-disc">DISCONNECTED</span>`
          : `<b>${fmt(worst.disrupted_m)} m</b> (${worst.detour_m > 0 ? "+" : ""}${fmt(worst.detour_m)} m)`) +
        `</div>` +
        `<div class="muted tiny">Facility: ${esc(worst.baseline_facility || "?")}` +
        (worst.destination_switched ? ` → ${esc(worst.disrupted_facility || "?")} (switched)` : " (same)") +
        ` · shown on map (blue = original, red = after closure)</div>` +
        `</div>`;
    }
    $("vuln-detail").innerHTML =
      `<div class="detail-grid">` +
      `<div><b>${esc(m.name || "(unnamed way)")}</b><div class="muted tiny">OSM way ${esc(m.osmid)} · ${esc(m.selection_tier)} · ${fmt(m.length_m, 0)} m · ${fmt(m.edges, 0)} edges</div></div>` +
      `<div class="detail-metrics">` +
      `<span><b>${fmt(m.n_affected, 0)}</b> affected (${fmt(m.pct_affected, 1)}%)</span>` +
      `<span><b>${fmt(m.median_extra_m)}</b> m median +</span>` +
      `<span><b>${fmt(m.max_extra_m)}</b> m max +</span>` +
      `<span><b>${fmt(m.n_newly_disconnected, 0)}</b> disconnected</span>` +
      `<span><b>${fmt(m.n_destination_switched, 0)}</b> switched facility</span>` +
      `<span>score <b>${fmt(m.disruption_score, 2)}</b></span>` +
      `</div></div>` +
      worstHtml +
      `<div class="table-wrap"><table><thead><tr><th>Origin</th><th>Base m</th><th>After m</th><th>+m</th><th>Status</th></tr></thead>` +
      `<tbody>${poRows || '<tr class="empty"><td colspan="5">no rows</td></tr>'}</tbody></table></div>` +
      `<p class="hint">Showing 12 of ${d.per_origin.length} stored per-origin rows (sorted by detour). Full evidence: <code>reports/phase2_per_origin.csv</code>.</p>`;
  }

  function drawExample(worst) {
    const map = ensureLayers();
    if (!map) return;
    V.detailLayer.clearLayers();
    if (!worst) return;
    if (worst.before_geometry) {
      L.polyline(worst.before_geometry.map(([la, lo]) => [la, lo]), {
        color: "#38bdf8", weight: 6, opacity: 0.95,
      }).bindTooltip(`Original → ${worst.baseline_facility} (${fmt(worst.baseline_m)} m)`, { sticky: true })
        .addTo(V.detailLayer);
    }
    if (worst.after_geometry) {
      L.polyline(worst.after_geometry.map(([la, lo]) => [la, lo]), {
        color: "#fb7185", weight: 6, opacity: 0.95, dashArray: "10 6",
      }).bindTooltip(`After closure → ${worst.disrupted_facility} (${fmt(worst.disrupted_m)} m)`, { sticky: true })
        .addTo(V.detailLayer);
    }
    L.circleMarker([worst.origin_lat, worst.origin_lon], {
      radius: 7, color: "#fff", weight: 1.2, fillColor: "#6366f1", fillOpacity: 1,
    }).bindTooltip(worst.origin_sample_id).addTo(V.detailLayer);
    const coords = [...(worst.before_geometry || []), ...(worst.after_geometry || [])];
    if (coords.length) {
      map.fitBounds(L.latLngBounds(coords.map(([la, lo]) => [la, lo])), {
        padding: [40, 40], maxZoom: 15,
      });
    }
  }

  /* ------------------------------------------------------------ wire */
  function wire() {
    $("vuln-rank").addEventListener("change", (e) => {
      V.rank = e.target.value;
      recomputeColors(); // O(N log N) once per ranking change
      applyFilters();
    });

    const schedule = () => {
      clearTimeout(V.filterTimer);
      V.filterTimer = setTimeout(applyFilters, DEBOUNCE_MS);
    };

    // 'input': live readout only (a few textContent writes — cheap).
    // Heavy work is debounced; 'change' (pointer release) applies immediately.
    $("vuln-min-aff").addEventListener("input", () => {
      $("vuln-min-aff-val").textContent = $("vuln-min-aff").value;
      schedule();
    });
    $("vuln-min-det").addEventListener("input", () => {
      $("vuln-min-det-val").textContent = $("vuln-min-det").value;
      schedule();
    });
    $("vuln-min-aff").addEventListener("change", () => {
      clearTimeout(V.filterTimer);
      applyFilters();
    });
    $("vuln-min-det").addEventListener("change", () => {
      clearTimeout(V.filterTimer);
      applyFilters();
    });
    $("vuln-disc-only").addEventListener("change", applyFilters);

    // one delegated listener for the ranked table (instead of per-row)
    $("vuln-table").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-osmid]");
      if (tr) selectDetail(tr.dataset.osmid);
    });
  }

  /* ------------------------------------------------------------ tabs */
  /* Null-safe: works whether or not the Phase 1 simulator layers exist
     (they are lazy-loaded on the Simulator tab's first visit). Explorer
     never triggers the heavy graph load. */
  function activate(on) {
    const cf = window.__cf;
    if (!cf) return;
    if (on) {
      cf.ensureMap();
      const map = cf.state.map;
      if (!map) return;
      drawRoads(); // no-op if already built
      V.vulnLayer.addTo(map);
      V.detailLayer.addTo(map);
      V.casingLayer.addTo(map);
      restyleRoads();
      // Phase 1 layers: dim / hide so the measured candidate roads read clearly
      if (cf.state.roadLayer) cf.state.roadLayer.setStyle({ opacity: 0.12, weight: 1 });
      if (cf.state.hospitalLayer && map.hasLayer(cf.state.hospitalLayer)) {
        map.removeLayer(cf.state.hospitalLayer);
        V._hospitalsHidden = true;
      }
      if (cf.state.highlightLayer) map.removeLayer(cf.state.highlightLayer);
      if (cf.state.routeLayer) map.removeLayer(cf.state.routeLayer);
      if (cf.state.originLayer && map.hasLayer(cf.state.originLayer)) {
        map.removeLayer(cf.state.originLayer);
        // small reference dots (created once from the loaded origins)
        if (!V.refOrigins) {
          V.refOrigins = L.layerGroup();
          cf.state.originLayer.eachLayer((l) => {
            if (l.getLatLng) {
              L.circleMarker(l.getLatLng(), {
                radius: 4, color: "#fff", weight: 0.8, fillColor: "#6366f1", fillOpacity: 0.9,
              }).bindTooltip(l.getTooltip()?.getContent() || "origin").addTo(V.refOrigins);
            }
          });
        }
        V.refOrigins.addTo(map);
      }
    } else {
      const map = cf.state.map;
      if (map) {
        if (V.vulnLayer) map.removeLayer(V.vulnLayer);
        if (V.detailLayer) map.removeLayer(V.detailLayer);
        if (V.casingLayer) map.removeLayer(V.casingLayer);
        if (V.refOrigins) map.removeLayer(V.refOrigins);
      }
      if (cf.state.roadLayer) cf.state.roadLayer.setStyle({ opacity: 0.65, weight: 1.6 });
      if (map && V._hospitalsHidden && cf.state.hospitalLayer) {
        cf.state.hospitalLayer.addTo(map);
        V._hospitalsHidden = false;
      }
      if (cf.state.highlightLayer) cf.state.highlightLayer.addTo(map);
      if (cf.state.routeLayer) cf.state.routeLayer.addTo(map);
      if (cf.state.originLayer) cf.state.originLayer.addTo(map);
    }
  }

  function initTabs() {
    // Four tabs. Overview + Findings are text-only. Explorer reads saved
    // artifacts (graph-free) and owns the map while active. Simulator
    // lazy-loads the routing engine on its FIRST visit only.
    const tabs = [
      { btn: $("tab-overview"), view: $("view-overview") },
      {
        btn: $("tab-sim"), view: $("view-sim"),
        onActivate: () => window.__cf?.initSimulator?.(),
      },
      {
        btn: $("tab-vuln"), view: $("view-vuln"),
        onActivate: () => activate(true), onDeactivate: () => activate(false),
      },
      { btn: $("tab-findings"), view: $("view-findings") },
    ];
    for (const t of tabs) {
      t.btn.addEventListener("click", () => {
        for (const o of tabs) {
          const active = o === t;
          o.btn.classList.toggle("active", active);
          o.btn.setAttribute("aria-selected", active ? "true" : "false");
          o.view.hidden = !active;
          if (!active && o.onDeactivate) o.onDeactivate();
        }
        if (t.onActivate) t.onActivate();
      });
    }
  }

  initTabs();
  // Data load is graph-free (summary/rows/geojson from saved artifacts) and
  // starts immediately; map layers are drawn on first Explorer activation.
  load().catch((e) => {
    $("vuln-stats").innerHTML = `<div class="status err">${esc(e.message)}</div>`;
  });
})();
