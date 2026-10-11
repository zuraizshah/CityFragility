/* CityFragility Phase 3 — Research Findings panel.
   Fetches the stored validation artifact /api/research ONCE on first tab
   activation. Text only — no map interaction, no polling, no redraws. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let loaded = false;

  function overlapHtml(o) {
    if (!o) return "—";
    return `${o.overlap}/${o.top_k}`;
  }

  function render(d) {
    const v = d.validation_summary || {};
    const rep = v.reproducibility || {};
    const cross = v.cross_check || {};
    const sens = d.sensitivity_summary || {};
    const audit = d.facility_audit_summary || {};
    const snap = audit.snap_dist_m || {};
    const findings = (d.verified_findings || [])
      .map((f) => `<li>${esc(f)}</li>`)
      .join("");

    const oe = sens.odd_even || {};
    const ew = sens.east_west || {};
    const plain =
      `<div class="plain-box">` +
      `<b>In plain language — how much should you trust the “top 5 roads” list?</b>` +
      `<p>The exact ranking is <b>sensitive to which sample locations were chosen</b>. ` +
      `Using the odd-numbered half of the origins instead of the even half kept ` +
      `${overlapHtml(oe.composite_overlap)} of the top-5 composite-score roads and ` +
      `${overlapHtml(oe.affected_overlap)} of the top-5 affected-count roads — similar, ` +
      `but not identical. Splitting the origins <b>east vs west</b> kept ` +
      `${overlapHtml(ew.composite_overlap)} and ${overlapHtml(ew.affected_overlap)} — ` +
      `the two halves of the study area disagree about which roads matter most. ` +
      `So treat the lists as “roads worth a closer look in this sample”, ` +
      `not as a stable citywide priority order.</p></div>`;

    $("findings-body").innerHTML =
      plain +
      `<ul>` + findings + `</ul>` +
      `<div class="detail-metrics" style="margin-top:0.5rem">` +
      `<span>reproducibility: <b>${rep.metric_mismatches ?? "?"}</b> mismatches / ` +
      `${rep.ways_recomputed ?? "?"} ways</span>` +
      `<span>cross-check: <b>${cross.origin_rows_checked ?? "?"}</b> rows, ` +
      `${(cross.baseline_distance_mismatches ?? 0) + (cross.disrupted_distance_mismatches ?? 0) + (cross.facility_identity_mismatches ?? 0) + (cross.disconnect_flag_mismatches ?? 0) + (cross.switch_flag_mismatches ?? 0)} mismatches</span>` +
      `<span>odd/even top-5: composite ${overlapHtml(sens.odd_even?.composite_overlap)}, ` +
      `affected ${overlapHtml(sens.odd_even?.affected_overlap)}</span>` +
      `<span>east/west top-5: composite ${overlapHtml(sens.east_west?.composite_overlap)}, ` +
      `affected ${overlapHtml(sens.east_west?.affected_overlap)}</span>` +
      `<span>facilities: <b>${audit.total_facilities ?? "?"}</b> mapped, ` +
      `${audit.near_duplicate_pairs ?? "?"} near-dup pairs ≤50 m, ` +
      `${audit.limited_scope_name_usable ?? "?"} limited-scope names</span>` +
      `<span>snap m: median ${snap.median ?? "?"}, max ${snap.max ?? "?"}</span>` +
      `</div>` +
      `<p class="hint">Full report: <code>reports/PHASE3_VALIDATION_REPORT.md</code> · ` +
      `machine-readable: <code>reports/phase3_findings.json</code> · ` +
      `runtime ${d.runtime?.total_s ?? "?"} s, peak RSS ${d.runtime?.peak_rss_mb ?? "?"} MB · ` +
      `validated ${esc(d.date)}</p>`;

    const lims = (d.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
    $("findings-limits").innerHTML =
      `<ul>${lims}</ul>` +
      `<p class="hint"><b>Disclaimer:</b> ${esc(d.disclaimer)} ` +
      `${esc(audit.disclaimer || "")}</p>`;
  }

  async function load() {
    const res = await fetch("/api/research");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    render(await res.json());
    loaded = true;
  }

  $("tab-findings").addEventListener("click", () => {
    if (loaded) return;
    $("findings-body").textContent = "Loading stored findings…";
    load().catch((e) => {
      $("findings-body").innerHTML =
        `<div class="status err">${esc(e.message)}</div>`;
    });
  });
})();
