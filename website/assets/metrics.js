/*
  The numbers in judgekeeper's report, for the interactive example on the home page.

  This is a small copy of src/judgekeeper/metrics.py for two labels, pass and fail.
  tests/test_website.py runs it with Node and checks it gives the same numbers as the
  Python code on fixed cases.

  The four counts compare the judge with a human on each answer:
    tp  the human passed it and the judge passed it   (true positive)
    fn  the human passed it but the judge failed it   (false negative)
    fp  the human failed it but the judge passed it   (false positive)
    tn  the human failed it and the judge failed it   (true negative)
*/
(function (root) {
  "use strict";

  var Z95 = 1.96; // 95% confidence

  // Wilson score interval: a range that likely holds the true rate, given k out of n.
  // Same formula as wilson_interval() in metrics.py. null when there is nothing to measure.
  function wilson(k, n) {
    if (n <= 0) return { k: k, n: n, p: null, lo: null, hi: null };
    var z = Z95;
    var p = k / n;
    var denom = 1 + z * z / n;
    var centre = (p + z * z / (2 * n)) / denom;
    var half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom;
    return { k: k, n: n, p: p, lo: Math.max(0, centre - half), hi: Math.min(1, centre + half) };
  }

  // Cohen's kappa: agreement with the human, minus the agreement you would get by luck.
  // 1 is perfect, 0 is no better than chance. null when it cannot be computed (when luck
  // alone would give perfect agreement, for example when everyone said "pass").
  function kappa(tp, fn, fp, tn) {
    var n = tp + fn + fp + tn;
    if (n === 0) return null;
    var observed = (tp + tn) / n;
    var humanPass = tp + fn, humanFail = fp + tn;
    var judgePass = tp + fp, judgeFail = fn + tn;
    var chance = (humanPass * judgePass + humanFail * judgeFail) / (n * n);
    if (chance === 1) return null;
    return (observed - chance) / (1 - chance);
  }

  // Everything the report's headline shows, from the four counts.
  function agreement(tp, fn, fp, tn) {
    var n = tp + fn + fp + tn;
    var humanPass = tp + fn, humanFail = fp + tn;
    return {
      n: n,
      kappa: kappa(tp, fn, fp, tn),
      // TPR: of the answers the human passed, the share the judge passed too.
      tpr: humanPass ? tp / humanPass : null,
      // TNR: of the answers the human failed, the share the judge failed too.
      tnr: humanFail ? tn / humanFail : null,
      // Raw agreement. Shown only next to the others: on its own it hides a judge
      // that passes everything when most answers are good.
      accuracy: n ? (tp + tn) / n : null,
      tprCi: wilson(tp, humanPass),
      tnrCi: wilson(tn, humanFail)
    };
  }

  var api = { wilson: wilson, kappa: kappa, agreement: agreement };
  if (typeof module === "object" && module.exports) module.exports = api; // Node, for the test
  else root.JKMetrics = api; // the browser
})(this);
