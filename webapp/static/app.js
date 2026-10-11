/* CityFragility — front end (Phase 1 simulator + shared shell).
   Talks to the FastAPI backend in ../server.py. Vanilla JS + Leaflet.

   Phase 4 loading model:
   - At startup only the LIGHT endpoints are used (/api/health answers from
     saved metadata; the NetworkX graph is never loaded for research tabs).
   - The map is created immediately (basemap only — cheap, no graph data).
   - The heavy Phase 1 layers (network / hospitals / origins / candidates)
     and the routing engine are lazy-loaded on the FIRST Simulator visit.
   - The Vulnerability Explorer reads precomputed artifacts and never needs
     the graph. */
"use strict";

const COLORS = {
  network: "#334155",
  candidate: "#facc15",
  baseline: "#38bdf8",
  alternative: "#fb7185",
  hospital: "#fb923c",
  origin: "#6366f1",
};

const state = {
  map: null,
  roadLayer: null,
  roadsByOsmid: new Map(), // osmid -> [Leaflet layers]
  hospitalLayer: null,
  originLayer: null,
  highlightLayer: null,
  routeLayer: null,
  candidates: [],
  candByOsmid: new Map(),
  lastSim: null,
  busy: false,
  mapReady: false,
  simulatorReady: false,
  simulatorLoading: false,
  health: null,
};

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function banner(msg, kind = "info", ms = 4000) {
  const el = $("map-banner");
  if (!el) return;
  el.textContent = msg;
  el.className = `map-banner ${kind}`;
  clearTimeout(banner._t);
  if (ms > 0) banner._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function setStatus(msg, kind = "") {
  const el = $("sim-status");
  if (!el) return;
  el.textContent = msg;
  el.className = `status ${kind}`;
}

/* ------------------------------------------------------------------ map */
function ensureMap() {
  if (state.map) return state.map;
  const map = L.map("map", { preferCanvas: true }).setView([24.845, 67.045], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  state.map = map;
  state.highlightLayer = L.layerGroup().addTo(map);
  state.routeLayer = L.layerGroup().addTo(map);
  state.mapReady = true;
  return map;
}

/* ------------------------------------------------------------- layers */
async function loadNetwork() {
  const fc = await (await fetch("/api/network")).json();
  const roadStyle = { color: COLORS.network, weight: 1.6, opacity: 0.65 };
  state.roadLayer = L.geoJSON(fc, {
    style: () => roadStyle,
    renderer: L.canvas({ padding: 0.4 }),
    onEachFeature: (feat, layer) => {
      const oid = feat.properties.osmid;
      if (oid != null) {
        if (!state.roadsByOsmid.has(oid)) state.roadsByOsmid.set(oid, []);
        state.roadsByOsmid.get(oid).push(layer);
        layer.on("click", () => onRoadClick(oid, feat.properties));
      }
    },
  }).addTo(state.map);
  $("stat-network-note")?.remove();
}

async function loadHospitals() {
  const fc = await (await fetch("/api/hospitals")).json();
  state.hospitalLayer = L.geoJSON(fc, {
    pointToLayer: (feat, latlng) =>
      L.circleMarker(latlng, {
        radius: 3.5,
        color: "#fff",
        weight: 0.8,
        fillColor: COLORS.hospital,
        fillOpacity: 0.9,
      }).bindPopup(() => {
        const p = feat.properties;
        const d = document.createElement("div");
        d.innerHTML =
          `<div class="popup-title">${esc(p.name || "Unnamed facility")}</div>` +
          `<div class="popup-warn">Unverified OSM facility — not confirmed emergency care</div>` +
          `<div class="popup-muted">OSM ${esc(p.element_type)}/${esc(p.osmid)} · ` +
          `snap ${esc(p.snap_dist_m)} m${p.usable ? "" : " (unusable)"}</div>`;
        return d;
      }),
  }).addTo(state.map);
}

async function loadOrigins() {
  const fc = await (await fetch("/api/origins")).json();
  state.originLayer = L.geoJSON(fc, {
    pointToLayer: (feat, latlng) => {
      const p = feat.properties;
      const m = L.circleMarker(latlng, {
        radius: 6,
        color: "#fff",
        weight: 1.2,
        fillColor: COLORS.origin,
        fillOpacity: 1,
      }).bindPopup(
        `<div class="popup-title">${esc(p.name)}</div>` +
          `<div class="popup-muted">sample origin · snap ${esc(p.snap_dist_m)} m` +
          `${p.snap_flag ? " (flagged)" : ""}</div>` +
          `<div class="popup-muted">Results apply to this sample only.</div>`
      );
      m.bindTooltip(p.name, { direction: "top", offset: [0, -6], opacity: 0.9 });
      return m;
    },
  }).addTo(state.map);
}

/* ---------------------------------------------------------- candidates */
async function loadCandidates() {
  const data = await (await fetch("/api/candidates")).json();
  state.candidates = data.candidates;
  state.candByOsmid = new Map(data.candidates.map((c) => [c.osmid, c]));

  const sel = $("candidate-select");
  const gTested = document.createElement("optgroup");
  gTested.label = "Tested in Phase 0 (verified)";
  const gExtra = document.createElement("optgroup");
  gExtra.label = "Testable (on a baseline route)";
  for (const c of data.candidates) {
    const o = document.createElement("option");
    o.value = String(c.osmid);
    const nm = c.name || `Unnamed way`;
    const flag = c.tested_in_phase0 ? " · tested" : "";
    o.textContent = `${nm} — osm/${c.osmid} (${Math.round(c.length_m)} m${flag})`;
    (c.tested_in_phase0 ? gTested : gExtra).appendChild(o);
  }
  sel.append(gTested, gExtra);
  $("stat-candidates").textContent = String(data.candidates.length);
  sel.addEventListener("change", () => onCandidateChange());
}

function onRoadClick(osmid, props) {
  if (state.candByOsmid.has(osmid)) {
    $("candidate-select").value = String(osmid);
    onCandidateChange();
  } else {
    banner(
      "That segment is not in the bounded candidate set. Choose one from the sidebar dropdown.",
      "warn"
    );
  }
}

function onCandidateChange() {
  const v = $("candidate-select").value;
  state.selectedOsmid = v ? Number(v) : null;
  $("btn-simulate").disabled = !state.selectedOsmid || state.busy;
  clearSimulationUI();
  updateCandidateHighlight();
  updateRoadDetails();
}

function updateCandidateHighlight() {
  if (!state.highlightLayer || !state.roadLayer) return;
  state.highlightLayer.clearLayers();
  const oid = state.selectedOsmid;
  if (oid == null) return;
  const layers = state.roadsByOsmid.get(oid) || [];
  for (const layer of layers) {
    layer.setStyle({ color: COLORS.candidate, weight: 5, opacity: 0.95 });
    layer.bringToFront();
  }
  // restore default style when selection changes
  state.roadLayer.eachLayer((l) => {
    if (!layers.includes(l)) l.setStyle({ color: COLORS.network, weight: 1.6, opacity: 0.65 });
  });
  if (layers.length === 0) {
    banner(
      "This segment is a minor road not shown in the rendered subset — simulation is still valid.",
      "info",
      6000
    );
  }
}

function updateRoadDetails() {
  const el = $("road-details");
  const c = state.candByOsmid.get(state.selectedOsmid);
  if (!c) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  const chip = c.tested_in_phase0
    ? '<span class="chip chip-tested">tested in Phase 0</span>'
    : '<span class="chip chip-testable">testable</span>';
  const phase0 = c.tested_in_phase0
    ? `<div class="rd-meta">Phase 0 result: total Δ ${esc(c.phase0_total_delta_m)} m · ` +
      `disconnected: ${c.phase0_any_disconnected ? "<b>yes</b>" : "no"}</div>`
    : "";
  const onPath =
    c.on_baseline_path_of && c.on_baseline_path_of.length
      ? `<div class="rd-meta">On baseline route of: ${esc(c.on_baseline_path_of.join(", "))}</div>`
      : "";
  el.innerHTML =
    `<div class="rd-name">${esc(c.name || "Unnamed way")} ${chip}</div>` +
    `<div class="rd-meta">OSM way <b>${esc(c.osmid)}</b> · class ${esc((c.highways || []).join(", ") || "?")}</div>` +
    `<div class="rd-meta">${esc(c.length_m)} m in study area · ${esc(c.edges)} directed edges</div>` +
    onPath +
    phase0;
  el.classList.remove("hidden");
}

/* --------------------------------------------------------- simulation */
function clearSimulationUI() {
  state.lastSim = null;
  if (state.routeLayer) state.routeLayer.clearLayers();
  state.focusLayer = null;
  const tb = $("results-table").querySelector("tbody");
  tb.innerHTML =
    '<tr class="empty"><td colspan="5">No simulation yet — pick a segment and press Simulate Closure.</td></tr>';
  const fs = $("focus-select");
  fs.innerHTML = '<option value="">— run a simulation —</option>';
  fs.disabled = true;
  $("btn-restore").disabled = true;
}

async function simulate() {
  const oid = state.selectedOsmid;
  if (oid == null || state.busy) return;
  state.busy = true;
  $("btn-simulate").disabled = true;
  setStatus("Simulating closure on the real graph…", "busy");
  banner("Removing every directed edge of this OSM way, recomputing, restoring…", "info", 0);
  try {
    const res = await fetch(`/api/simulate?osmid=${oid}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const sim = await res.json();
    state.lastSim = sim;
    renderResults(sim);
    populateFocus(sim);
    const focus =
      sim.per_origin.find((r) => r.disconnected) ||
      sim.per_origin.reduce(
        (a, b) => ((b.delta_m ?? -1) > (a.delta_m ?? -1) ? b : a),
        sim.per_origin[0]
      );
    $("focus-select").value = focus.name;
    drawRoutes(focus.name);
    setStatus(
      `Done in ${sim.compute_ms} ms · ${sim.edges_removed} directed edges removed · ` +
        `graph restored exactly (${sim.graph_nodes} nodes / ${sim.graph_edges} edges).`,
      "ok"
    );
    $("btn-restore").disabled = false;
    banner(null, "", 0);
    $("map-banner").classList.add("hidden");
  } catch (e) {
    setStatus(`Simulation failed: ${e.message}`, "err");
    banner(`Simulation failed: ${e.message}`, "warn", 6000);
  } finally {
    state.busy = false;
    $("btn-simulate").disabled = !state.selectedOsmid;
  }
}

function fmt(v) {
  return v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function renderResults(sim) {
  const tb = $("results-table").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of sim.per_origin) {
    const tr = document.createElement("tr");
    tr.dataset.focus = r.name;
    let tag;
    if (r.disconnected) tag = '<span class="tag tag-disc">disconnected</span>';
    else if (r.delta_m > 0) tag = '<span class="tag tag-delta">+detour</span>';
    else tag = '<span class="tag tag-unchanged">unchanged</span>';
    tr.innerHTML =
      `<td>${esc(r.name)}${r.snap_flag ? ' <span class="tag tag-unchanged">snap flag</span>' : ""}</td>` +
      `<td>${fmt(r.before_m)}</td>` +
      `<td class="${r.disconnected ? "na" : r.delta_m > 0 ? "delta-pos" : ""}">${fmt(r.after_m)}</td>` +
      `<td class="${r.delta_m > 0 ? "delta-pos" : "na"}">${fmt(r.delta_m)}</td>` +
      `<td>${tag}</td>`;
    tr.addEventListener("click", () => {
      $("focus-select").value = r.name;
      drawRoutes(r.name);
    });
    tb.appendChild(tr);
  }
  highlightFocusRow();
}

function populateFocus(sim) {
  const fs = $("focus-select");
  fs.innerHTML = "";
  for (const r of sim.per_origin) {
    const o = document.createElement("option");
    o.value = r.name;
    o.textContent = r.name;
    fs.appendChild(o);
  }
  fs.disabled = false;
  fs.onchange = () => drawRoutes(fs.value);
}

function highlightFocusRow() {
  const name = $("focus-select").value;
  document.querySelectorAll("#results-table tbody tr").forEach((tr) => {
    tr.classList.toggle("focused", tr.dataset.focus === name);
  });
}

function drawRoutes(originName) {
  if (!state.routeLayer) return;
  state.routeLayer.clearLayers();
  highlightFocusRow();
  const sim = state.lastSim;
  if (!sim) return;
  const row = sim.per_origin.find((r) => r.name === originName);
  if (!row) return;
  const origin = state.originLayer
    ? state.originLayer
        .getLayers()
        .find((l) => l.feature && l.feature.properties.name === originName)
    : null;
  const originLatLng = origin ? origin.getLatLng() : null;

  if (row.disconnected) {
    if (originLatLng) {
      L.circleMarker(originLatLng, {
        radius: 12,
        color: COLORS.alternative,
        weight: 2,
        fill: false,
      })
        .bindTooltip("No drivable path remains to any mapped facility", {
          direction: "top",
        })
        .addTo(state.routeLayer);
    }
    banner(
      `${originName}: MAPPED DISCONNECTION — no drivable path remains to any mapped facility after this hypothetical closure.`,
      "warn",
      0
    );
    return;
  }

  const bounds = [];
  if (row.before_route && row.before_route.geometry) {
    const latlngs = row.before_route.geometry.map(([la, lo]) => [la, lo]);
    L.polyline(latlngs, {
      color: COLORS.baseline,
      weight: 5,
      opacity: 0.9,
    })
      .bindTooltip(
        `Original route → ${row.before_route.hospital} (${fmt(row.before_route.length_m)} m)`,
        { sticky: true }
      )
      .addTo(state.routeLayer);
    bounds.push(...latlngs);
  }
  if (row.after_route && row.after_route.geometry) {
    const latlngs = row.after_route.geometry.map(([la, lo]) => [la, lo]);
    L.polyline(latlngs, {
      color: COLORS.alternative,
      weight: 5,
      opacity: 0.9,
      dashArray: "10 6",
    })
      .bindTooltip(
        `Alternative route → ${row.after_route.hospital} (${fmt(row.after_route.length_m)} m)`,
        { sticky: true }
      )
      .addTo(state.routeLayer);
    bounds.push(...latlngs);
  }
  if (bounds.length) {
    state.map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 15 });
  }
  if (row.delta_m > 0) {
    banner(
      `${originName}: +${fmt(row.delta_m)} m added (before ${fmt(row.before_m)} m → after ${fmt(row.after_m)} m).`,
      "info",
      5000
    );
  } else {
    banner(`${originName}: route unchanged by this closure.`, "info", 4000);
  }
}

async function restore() {
  if (state.busy) return;
  state.busy = true;
  setStatus("Restoring road and recomputing baseline…", "busy");
  try {
    const res = await fetch("/api/restore");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.routeLayer.clearLayers();
    state.lastSim = null;
    const tb = $("results-table").querySelector("tbody");
    tb.innerHTML = "";
    for (const r of data.per_origin) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${esc(r.name)}</td><td>${fmt(r.distance_m)}</td>` +
        `<td class="na">${fmt(r.distance_m)}</td><td class="na">0</td>` +
        `<td><span class="tag tag-unchanged">baseline</span></td>`;
      tb.appendChild(tr);
    }
    $("focus-select").innerHTML = '<option value="">— run a simulation —</option>';
    $("focus-select").disabled = true;
    $("btn-restore").disabled = true;
    setStatus(
      `Road restored. Baseline recomputed on the pristine graph: ` +
        `${data.nodes} nodes / ${data.edges} edges — identical to Phase 0.`,
      "ok"
    );
    banner("Road restored — baseline distances returned.", "info", 3500);
  } catch (e) {
    setStatus(`Restore failed: ${e.message}`, "err");
  } finally {
    state.busy = false;
  }
}

/* ------------------------------------------------- lazy simulator init */
async function initSimulator() {
  if (state.simulatorReady || state.simulatorLoading) return;
  state.simulatorLoading = true;
  ensureMap();
  setStatus("Loading real Karachi graph from the backend (first visit only)…", "busy");
  try {
    const health =
      state.health || (state.health = await (await fetch("/api/health")).json());
    $("stat-nodes").textContent = health.nodes.toLocaleString();
    $("stat-edges").textContent = health.edges.toLocaleString();
    await Promise.all([loadNetwork(), loadHospitals(), loadOrigins(), loadCandidates()]);
    const h2 = await (await fetch("/api/health")).json();
    if (h2.hospitals_total != null) {
      $("stat-hospitals").textContent = h2.hospitals_total;
    } else {
      $("stat-hospitals").textContent = state.hospitalLayer
        ? String(state.hospitalLayer.getLayers().length)
        : "–";
    }
    const badge = $("mode-badge");
    if (badge) {
      badge.textContent = `live routing loaded · ${h2.startup_s}s graph load`;
      badge.classList.add("badge-live");
    }
    setStatus(
      `Ready — ${health.nodes.toLocaleString()} nodes / ${health.edges.toLocaleString()} directed edges loaded once on the server.`,
      "ok"
    );
    $("btn-simulate").addEventListener("click", simulate);
    $("btn-restore").addEventListener("click", restore);
    state.simulatorReady = true;
  } catch (e) {
    setStatus(`Failed to load: ${e.message}`, "err");
    banner("Backend unavailable — start it with the launch command in the README.", "warn", 0);
  } finally {
    state.simulatorLoading = false;
  }
}

/* ------------------------------------------------------------- startup */
async function main() {
  ensureMap(); // basemap only — no graph, no heavy API calls
  try {
    const health = (state.health = await (await fetch("/api/health")).json());
    $("stat-nodes").textContent = health.nodes.toLocaleString();
    $("stat-edges").textContent = health.edges.toLocaleString();
    $("stat-candidates").textContent = String(health.candidates ?? "–");
    $("stat-hospitals").textContent =
      health.hospitals_total != null ? String(health.hospitals_total) : "–";
    const badge = $("mode-badge");
    if (badge && !health.graph_loaded) {
      badge.textContent = "research mode — live routing idle";
    }
    const scale = $("overview-scale");
    if (scale) {
      scale.innerHTML =
        `<div class="vs-item"><b>${health.nodes.toLocaleString()}</b><span>road-network nodes</span></div>` +
        `<div class="vs-item"><b>${health.edges.toLocaleString()}</b><span>directed edges</span></div>` +
        `<div class="vs-item"><b>${health.hospitals_total ?? "–"}</b><span>mapped facilities</span></div>` +
        `<div class="vs-item"><b>100</b><span>sample origins (grid)</span></div>` +
        `<div class="vs-item"><b>100</b><span>ways tested in experiment</span></div>` +
        `<div class="vs-item"><b>10,000</b><span>closure scenarios measured</span></div>`;
    }
  } catch (e) {
    const scale = $("overview-scale");
    if (scale) {
      scale.innerHTML = `<div class="status err">Backend unavailable: ${esc(e.message)}</div>`;
    }
  }
}

main();

/* Shared handle for explorer.js / findings.js.
   Exported BEFORE async work finishes so tab handlers can call
   ensureMap() / initSimulator() the moment they exist. */
window.__cf = { state, COLORS, ensureMap, initSimulator };
