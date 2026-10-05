/*
  judgekeeper website behaviour. Plain JavaScript, no libraries, no network requests.

  Every page works without this file: all text is in the HTML. This file adds copy
  buttons, the interactive numbers, the small toggles in "It keeps checking", the
  install tabs and the bar widths in the real result.
*/
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function num(el) { return el ? parseFloat(el.textContent) : NaN; }
  function fmt(x) { return x === null ? "n/a" : x.toFixed(2); }

  // Copy buttons on every command block.
  function addCopyButtons() {
    $all(".code pre, .install").forEach(function (block) {
      var holder = block.classList.contains("install") ? block : block.parentNode;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy";
      button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy this command");
      if (holder.classList.contains("install")) button.style.position = "static";
      button.addEventListener("click", function () {
        var text = $("code", block).textContent;
        var done = function () {
          button.textContent = "Copied";
          setTimeout(function () { button.textContent = "Copy"; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, function () { button.textContent = "Select and copy"; });
        } else {
          button.textContent = "Select and copy";
        }
      });
      holder.appendChild(button);
    });
  }

  // What the numbers mean: the interactive confusion matrix.
  function setUpMatrix() {
    var root = $("#matrix");
    if (!root || !window.JKMetrics) return;
    var pos = $("#m-pos"), neg = $("#m-neg"), tpIn = $("#m-tp"), tnIn = $("#m-tn");
    // The verdict thresholds are read from the page, where a test checks them against
    // judgekeeper's code (judgekeeper.report: RATE_GATE, RATE_CARE, KAPPA_GATE).
    var rateGate = num($("#th-rate-gate")), rateCare = num($("#th-rate-care")), kappaGate = num($("#th-kappa-gate"));

    function set(id, text) { $(id).firstChild.nodeValue = text; }

    function update() {
      var p = +pos.value, n = +neg.value;
      tpIn.max = p; tnIn.max = n;
      var tp = Math.min(+tpIn.value, p), tn = Math.min(+tnIn.value, n);
      tpIn.value = tp; tnIn.value = tn;
      var fn = p - tp, fp = n - tn;
      $("#m-pos-out").textContent = p; $("#m-neg-out").textContent = n;
      $("#m-tp-out").textContent = tp; $("#m-tn-out").textContent = tn;
      set("#cm-tp", String(tp)); set("#cm-fn", String(fn)); set("#cm-fp", String(fp)); set("#cm-tn", String(tn));

      var a = window.JKMetrics.agreement(tp, fn, fp, tn);
      $("#s-tpr").textContent = fmt(a.tpr);
      $("#s-tnr").textContent = fmt(a.tnr);
      $("#s-kappa").textContent = fmt(a.kappa);
      $("#s-acc").textContent = a.accuracy === null ? "n/a" : Math.round(a.accuracy * 100) + "%";
      $("#s-tpr-why").textContent = p ? "Of the answers people passed, the judge passed " + tp + " of " + p + "." : "No answers were passed by people, so TPR cannot be measured.";
      $("#s-tnr-why").textContent = n ? "Of the answers people failed, the judge failed " + tn + " of " + n + "." : "No answers were failed by people, so TNR cannot be measured.";
      $("#s-kappa-why").textContent = a.kappa === null
        ? "Kappa cannot be computed: luck alone would give perfect agreement here."
        : "Agreement after taking away what lucky guessing would give. 0 is no better than chance, 1 is perfect.";

      var line = $("#s-verdict"), level, text;
      var low = a.tpr === null || a.tnr === null ? null : Math.min(a.tpr, a.tnr);
      if (a.kappa === null || a.kappa < kappaGate || low === null || low < rateGate) {
        level = "bad"; text = "Not trustworthy as a gate.";
        if (a.tnr !== null && a.tnr < rateGate) text += " The judge lets too many bad answers through.";
        else if (a.tpr !== null && a.tpr < rateGate) text += " The judge fails too many good answers.";
        if (a.accuracy !== null && a.accuracy >= 0.85) text += " Raw agreement still looks high: that is why judgekeeper never reports it alone.";
      } else if (low < rateCare) {
        level = "care"; text = "Usable with care: TPR or TNR is between " + fmt(rateGate) + " and " + fmt(rateCare) + ".";
      } else {
        level = "good"; text = "Usable as a gate.";
      }
      line.className = "verdict-line " + level;
      line.textContent = text;

      var ci = function (c) { return c.lo === null ? "n/a" : fmt(c.lo) + " to " + fmt(c.hi); };
      $("#s-ci").textContent = "Likely ranges with this few answers (95 percent Wilson intervals): TPR " + ci(a.tprCi) + ", TNR " + ci(a.tnrCi) + ". More labels make them narrower.";
    }

    [pos, neg, tpIn, tnIn].forEach(function (input) {
      input.addEventListener("input", function () {
        $all("[data-preset]", root).forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
        update();
      });
    });
    $all("[data-preset]", root).forEach(function (button) {
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", function () {
        var v = button.getAttribute("data-preset").split(",").map(Number);
        pos.value = v[0]; neg.value = v[1];
        tpIn.max = v[0]; tnIn.max = v[1];
        tpIn.value = v[2]; tnIn.value = v[3];
        $all("[data-preset]", root).forEach(function (b) { b.setAttribute("aria-pressed", String(b === button)); });
        update();
      });
    });
    update();
  }

  // A row of toggle buttons that each show a message.
  function toggles(attr, render) {
    var buttons = $all("[" + attr + "]");
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b === button)); });
        render(button.getAttribute(attr));
      });
    });
  }

  function setUpPanels() {
    var gateText = {
      PASS: "The judge clears every check. The build continues.",
      FAIL: "The judge fell below a threshold. The build stops.",
      FLAKY: "The judge flips too often to tell. The build stops unless you choose --flaky-as pass."
    };
    toggles("data-gate", function (status) {
      var code = $('[data-exit="gate:' + status + '"]').textContent;
      $("#ci-dot").className = "ci-dot " + (code === "0" ? "ok" : "no");
      $("#ci-text").textContent = "judge gate: " + status + " (exit " + code + "). " + gateText[status];
    });

    var migrateText = {
      BETTER: "the new judge agrees with people more, by more than the noise. Switch, and expect scores to move because the judge improved.",
      WORSE: "the new judge agrees with people less, by more than the noise. Do not switch yet.",
      EQUIVALENT: "both judges agree with people about equally, and almost no answers changed. Scores stay comparable across the switch.",
      DIFFERENT: "about as good overall, but on different answers. Old and new scores are not comparable answer by answer."
    };
    toggles("data-migrate", function (status) {
      var p = $("#migrate-text");
      p.innerHTML = "";
      var strong = document.createElement("strong");
      strong.textContent = status + ":";
      p.appendChild(strong);
      p.appendChild(document.createTextNode(" " + migrateText[status]));
    });

    var attrText = {
      SYSTEM_CHANGE: ["no", "The judge still grades the frozen examples the same way, so the drop comes from your app."],
      JUDGE_DRIFT: ["mid", "The judge's verdicts on the frozen examples moved, so the judge changed. Your app may be fine."]
    };
    toggles("data-attr", function (status) {
      var p = $("#attr-text");
      p.innerHTML = "";
      var tag = document.createElement("span");
      tag.className = "status " + attrText[status][0];
      tag.textContent = status;
      p.appendChild(tag);
      p.appendChild(document.createTextNode(" " + attrText[status][1]));
    });
  }

  // Get started: accessible tabs. Without this script every panel is shown.
  function setUpTabs() {
    $all(".tabs").forEach(function (box) {
      var tabs = $all('[role="tab"]', box);
      function select(tab, focus) {
        tabs.forEach(function (t) {
          var on = t === tab;
          t.setAttribute("aria-selected", String(on));
          t.tabIndex = on ? 0 : -1;
          $("#" + t.getAttribute("aria-controls")).hidden = !on;
        });
        if (focus) tab.focus();
      }
      tabs.forEach(function (tab, i) {
        tab.addEventListener("click", function () { select(tab); });
        tab.addEventListener("keydown", function (e) {
          var next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
          if (next === undefined) return;
          e.preventDefault();
          select(tabs[(next + tabs.length) % tabs.length], true);
        });
      });
      select(tabs[0]);
    });
  }

  // The real result: each bar's width is the number printed next to it.
  function setUpBars() {
    $all(".bar-row").forEach(function (row) {
      var value = num($(".num", row));
      var fill = $(".bar-fill", row);
      if (isNaN(value)) return;
      void fill.offsetWidth; // lay out the empty bar first, so the width change animates
      fill.style.width = (value * 100) + "%";
    });
  }

  function start() {
    addCopyButtons();
    setUpMatrix();
    setUpPanels();
    setUpTabs();
    setUpBars();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
