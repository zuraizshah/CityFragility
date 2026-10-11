/* Phase 2.5 headless test for explorer-core.js (run with macOS jsc).
   Loads the real stored experiment rows (injected as TEST_ROWS by the
   Python test runner) and asserts filtering, ranking, colour logic and
   that the Phase 2 scientific top result is unchanged.

   Usage: jsc tests/explorer_core_test.js   (expects explorer-core-core.js
   path baked in via CORE_PATH below) */
"use strict";

var failures = [];
function check(cond, msg) {
  if (!cond) failures.push(msg);
}
function near(a, b, tol, msg) {
  check(Math.abs(a - b) <= tol, msg + " (got " + a + ", want " + b + ")");
}

if (typeof ExplorerCore === "undefined") {
  print("FAIL: ExplorerCore not loaded");
  quit(1);
}
if (typeof TEST_ROWS === "undefined" || !TEST_ROWS.length) {
  print("FAIL: TEST_ROWS not loaded");
  quit(1);
}
var C = ExplorerCore;
var rows = TEST_ROWS;
check(rows.length === 100, "expected 100 stored rows, got " + rows.length);

/* ---- filter correctness at zero and nonzero thresholds ---- */
var all = C.filterRows(rows, { minAff: 0, minDet: 0, discOnly: false });
check(all.length === 100, "zero thresholds must return every row, got " + all.length);

var aff5 = C.filterRows(rows, { minAff: 5, minDet: 0, discOnly: false });
check(aff5.length > 0, "minAff=5 should keep at least one row");
for (var i = 0; i < aff5.length; i++)
  check((aff5[i].n_affected || 0) >= 5, "filter leak: n_affected=" + aff5[i].n_affected);

var det200 = C.filterRows(rows, { minAff: 0, minDet: 200, discOnly: false });
check(det200.length > 0, "minDet=200 should keep at least one row");
for (i = 0; i < det200.length; i++)
  check((det200[i].median_extra_m || 0) >= 200, "filter leak: median=" + det200[i].median_extra_m);

var discOnly = C.filterRows(rows, { minAff: 0, minDet: 0, discOnly: true });
for (i = 0; i < discOnly.length; i++)
  check((discOnly[i].n_newly_disconnected || 0) > 0, "discOnly leak");
// zero disconnections exist in this sample → empty is the correct result
check(discOnly.length === 0, "sample has 0 disconnections, discOnly must be empty");

var combo = C.filterRows(rows, { minAff: 4, minDet: 400, discOnly: false });
for (i = 0; i < combo.length; i++) {
  check((combo[i].n_affected || 0) >= 4, "combo leak affected");
  check((combo[i].median_extra_m || 0) >= 400, "combo leak detour");
}

/* ---- ranking: top composite way must remain OSM 26182600 with exact values ---- */
var byScore = C.rankRows(rows, "disruption_score");
check(String(byScore[0].osmid) === "26182600",
  "top composite must be osm/26182600, got " + byScore[0].osmid);
near(byScore[0].disruption_score, 12.895, 0.001, "top composite score drifted");
check(byScore[0].n_affected === 4, "top composite n_affected drifted");
near(byScore[0].median_extra_m, 889.51, 0.01, "top composite median drifted");

// descending order + osmid tie-break
for (i = 1; i < byScore.length; i++) {
  var prev = byScore[i - 1].disruption_score || 0;
  var cur = byScore[i].disruption_score || 0;
  check(prev > cur || (prev === cur && byScore[i - 1].osmid <= byScore[i].osmid),
    "rank order broken at index " + i);
}

var byAff = C.rankRows(rows, "n_affected");
check(String(byAff[0].osmid) === "219168400",
  "top affected-count must be osm/219168400, got " + byAff[0].osmid);
check(byAff[0].n_affected === 6, "top affected n_affected drifted");

var byMed = C.rankRows(rows, "median_extra_m");
check((byMed[0].median_extra_m || 0) >= (byMed[1].median_extra_m || 0),
  "median ranking not descending");

/* ---- filter + rank combined (what the slider path executes) ---- */
var f5 = C.rankRows(C.filterRows(rows, { minAff: 4, minDet: 0, discOnly: false }), "disruption_score");
check(f5.length >= 3, "combined filter should keep the affected ways");
check((f5[0].n_affected || 0) >= 4, "combined filter leaked low-affected rows");

/* ---- colours: one Map built once, stable + O(1) lookup ---- */
var cmap = C.recomputeColors(rows, "disruption_score");
check(cmap instanceof Map, "recomputeColors must return a Map");
check(cmap.size === 100, "colour map must cover all rows, got " + cmap.size);
check(cmap.has("26182600"), "colour map missing top way");
check(cmap.get("26182600") !== C.NO_EFFECT, "top way must not be slate");
var zeroWays = rows.filter(function (r) { return (r.n_affected || 0) === 0; });
check(zeroWays.length > 0, "sample should contain zero-effect ways");
for (i = 0; i < zeroWays.length; i++)
  check(cmap.get(String(zeroWays[i].osmid)) === C.NO_EFFECT,
    "zero-effect way " + zeroWays[i].osmid + " must be slate");
// colours must only come from the documented scale (or slate)
for (i = 0; i < rows.length; i++) {
  var col = cmap.get(String(rows[i].osmid));
  check(col === C.NO_EFFECT || C.SCALE.indexOf(col) !== -1,
    "unknown colour " + col + " for " + rows[i].osmid);
}

/* ---- filter signature: drives the "skip redundant work" gate ---- */
check(C.filterSignature({ minAff: 0, minDet: 0, discOnly: false, rank: "disruption_score" })
  !== C.filterSignature({ minAff: 1, minDet: 0, discOnly: false, rank: "disruption_score" }),
  "signature must change when a threshold changes");
check(C.filterSignature({ minAff: 3, minDet: 100, discOnly: false, rank: "n_affected" })
  === C.filterSignature({ minAff: 3, minDet: 100, discOnly: false, rank: "n_affected" }),
  "signature must be stable for identical filters");

/* ---- micro-benchmark: old per-event colour recompute vs new precomputed ---- */
function oldColorPass(rowsIn, filteredIn) {
  // mirrors the Phase 2 code: one full sort per road feature per event
  var calls = 0;
  for (var fIdx = 0; fIdx < rowsIn.length; fIdx++) {
    var vals = filteredIn.map(function (r) { return C.metricValue(r, "disruption_score"); })
      .sort(function (a, b) { return a - b; });
    var v = C.metricValue(rowsIn[fIdx], "disruption_score");
    var pos = vals.findIndex(function (x) { return x >= v; });
    calls += pos >= 0 ? pos : 0;
  }
  return calls;
}
function newColorPass(rowsIn) {
  var cm = C.recomputeColors(rowsIn, "disruption_score"); // once per rank change
  var sum = 0;
  for (var fIdx = 0; fIdx < rowsIn.length; fIdx++)
    sum += cm.get(String(rowsIn[fIdx].osmid)) ? 1 : 0;
  return sum;
}
var filtered = rows;
var t0 = Date.now();
for (var ev = 0; ev < 60; ev++) oldColorPass(rows, filtered); // 60 events ≈ 1s of drag
var oldMs = Date.now() - t0;
t0 = Date.now();
for (ev = 0; ev < 60; ev++) newColorPass(rows); // colours rebuilt once per rank, not per event
var newMs = Date.now() - t0;
print("BENCH old-per-event=" + oldMs + "ms new-precomputed=" + newMs + "ms over 60 simulated slider events");

if (failures.length) {
  for (var i2 = 0; i2 < failures.length; i2++) print("FAIL: " + failures[i2]);
  print("CORE_TESTS_FAILED " + failures.length);
  quit(1);
}
print("CORE_TESTS_PASS " + rows.length + " rows, top=" + byScore[0].osmid +
  " score=" + byScore[0].disruption_score + " bench_old=" + oldMs + "ms bench_new=" + newMs + "ms");
quit(0);
