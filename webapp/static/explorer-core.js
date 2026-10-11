/* CityFragility Phase 2.5 — pure Explorer logic (no DOM, no Leaflet, no fetch).

   Kept side-effect free so it can be unit-tested headlessly (jsc).
   explorer.js owns all DOM/map/wiring and calls into this module. */
"use strict";

(function (g) {
  var SCALE = ["#38bdf8", "#34d399", "#fbbf24", "#fb923c", "#ef4444"];
  var NO_EFFECT = "#64748b"; // slate: way measured with zero effect

  function metricValue(row, rank) {
    switch (rank) {
      case "n_affected": return row.n_affected || 0;
      case "median_extra_m": return row.median_extra_m || 0;
      case "max_extra_m": return row.max_extra_m || 0;
      case "n_newly_disconnected": return row.n_newly_disconnected || 0;
      case "n_destination_switched": return row.n_destination_switched || 0;
      default: return row.disruption_score || 0;
    }
  }

  /* Precompute a quantile colour for every row once per ranking change.
     Equal values share a bucket; zero-effect ways are slate. O(N log N)
     total instead of re-sorting the whole array per road per event. */
  function recomputeColors(rows, rank) {
    var withVal = rows.map(function (r) {
      return [metricValue(r, rank), String(r.osmid)];
    });
    withVal.sort(function (a, b) { return a[0] - b[0]; });
    var map = new Map();
    var n = withVal.length;
    var i = 0;
    while (i < n) {
      var j = i;
      while (j + 1 < n && withVal[j + 1][0] === withVal[i][0]) j++;
      var q = n >= 5 ? i / (n - 1) : 0.5;
      var idx = Math.min(SCALE.length - 1, Math.floor(q * SCALE.length));
      var color = withVal[i][0] <= 0 ? NO_EFFECT : SCALE[idx];
      for (var k = i; k <= j; k++) map.set(withVal[k][1], color);
      i = j + 1;
    }
    return map;
  }

  /* In-memory filter over the already-loaded rows (never touches network). */
  function filterRows(rows, f) {
    return rows.filter(function (r) {
      return (r.n_affected || 0) >= f.minAff &&
        (r.median_extra_m || 0) >= f.minDet &&
        (!f.discOnly || (r.n_newly_disconnected || 0) > 0);
    });
  }

  /* Descending by the chosen rank column; ties broken by osmid (stable). */
  function rankRows(rows, rank) {
    return rows.slice().sort(function (a, b) {
      var d = (metricValue(b, rank) || 0) - (metricValue(a, rank) || 0);
      return d !== 0 ? d : a.osmid - b.osmid;
    });
  }

  function filterSignature(f) {
    return f.minAff + "|" + f.minDet + "|" + (f.discOnly ? 1 : 0) + "|" + f.rank;
  }

  g.ExplorerCore = {
    SCALE: SCALE,
    NO_EFFECT: NO_EFFECT,
    metricValue: metricValue,
    recomputeColors: recomputeColors,
    filterRows: filterRows,
    rankRows: rankRows,
    filterSignature: filterSignature,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
