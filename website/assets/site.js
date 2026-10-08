/*
  judgekeeper website behaviour. Plain JavaScript, no libraries, no network requests.

  Every page works without this file: all text is in the HTML. This file adds the theme
  switch and the phone menu, copy buttons, the install tabs, the home page's two-verdicts
  card, the Guide's rail and done ticks, the interactive numbers, the small toggles in
  "It keeps checking" and the bar widths in the real result. What it keeps (the theme and
  the ticked steps) stays in this browser, and every read or write is wrapped in try/catch.
*/
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function num(el) { return el ? parseFloat(el.textContent) : NaN; }
  function fmt(x) { return x === null ? "n/a" : x.toFixed(2); }

  // The theme switch: dark or light, kept in this browser (assets/theme.js reads it back).
  function setUpTheme() {
    var root = document.documentElement, button = $(".theme-btn");
    if (!button) return;
    function current() {
      if (root.dataset.theme) return root.dataset.theme;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    function label() {
      button.setAttribute("aria-label", current() === "dark" ? "Switch to the light theme" : "Switch to the dark theme");
    }
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { window.localStorage.setItem("jk-theme", next); } catch (e) { /* kept for this page only */ }
      label();
    });
    label();
  }

  // On a phone the navigation folds behind a Menu button.
  function setUpMenu() {
    var button = $(".menu-btn"), nav = $("#site-nav");
    if (!button || !nav) return;
    button.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      button.setAttribute("aria-expanded", String(open));
    });
  }

  // Copy buttons on every command block.
  function addCopyButtons() {
    $all(".code pre").forEach(function (block) {
      var holder = block.parentNode;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy";
      button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy this command");
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
      var windows = tabs.filter(function (t) {
        return t.getAttribute("aria-controls") === "panel-win";
      });
      var asked = tabs.filter(function (t) {
        return t.getAttribute("aria-controls") === linkedPanel();
      });
      select(asked.length ? asked[0] : onWindows() && windows.length ? windows[0] : tabs[0]);
    });
    if (linkedPanel() && $("#install")) $("#install").scrollIntoView();
  }

  // A link to #install-mac or #install-win opens the install steps on that tab.
  function linkedPanel() {
    return { "#install-mac": "panel-mac", "#install-win": "panel-win" }[location.hash] || null;
  }

  // The Windows tab comes first when the browser says it runs on Windows.
  function onWindows() {
    var data = navigator.userAgentData;
    var platform = (data && data.platform) || navigator.platform || navigator.userAgent || "";
    return /Win/.test(platform);
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

  // Home: the two-verdicts card. An illustration: it never runs judgekeeper. The examples
  // are the JSON in #verdict-examples; the first one is already in the HTML.
  function setUpVerdicts() {
    var card = $("#vcard"), next = $("#vnext");
    if (!card || !next) return;
    var examples = JSON.parse($("#verdict-examples").textContent), i = 0;
    var tick = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
    var cross = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>';
    function agrees(e) { return (e.j === "Pass") === (e.y === "Correct"); }
    function show() {
      var e = examples[i % examples.length], seen = (i % examples.length) + 1, agreed = 0;
      $("#vq").textContent = e.q; $("#va").textContent = e.a;
      $("#vj").textContent = e.j; $("#vy").textContent = e.y;
      $("#sj").className = "slip " + (e.j === "Pass" ? "pass" : "fail");
      $("#sy").className = "slip " + (e.y === "Correct" ? "pass" : "fail");
      var badge = $("#vb");
      badge.className = "badge " + (agrees(e) ? "agree" : "disagree");
      badge.innerHTML = agrees(e) ? tick + "They agree" : cross + "They disagree";
      for (var k = 0; k < seen; k++) if (agrees(examples[k])) agreed++;
      $("#vt b").textContent = agreed + " of " + seen;
      ["#sj", "#sy", "#vb"].forEach(function (id) {
        var el = $(id); el.classList.remove("in"); void el.offsetWidth; el.classList.add("in");
      });
    }
    next.addEventListener("click", function () { i++; show(); });
  }

  // The Guide: done ticks kept in this browser, and the rail marks the step in view.
  function loadDone() {
    try { return JSON.parse(window.localStorage.getItem("jk-done") || "{}") || {}; } catch (e) { return {}; }
  }
  function setUpGuide() {
    var rail = $(".rail");
    if (!rail) return;
    var links = $all(".rail ol > li > a"), done = loadDone();
    function paint() { links.forEach(function (a, n) { a.classList.toggle("done", !!done[n + 1]); }); }
    $all("input[data-step]").forEach(function (box) {
      box.checked = !!done[box.getAttribute("data-step")];
      box.addEventListener("change", function () {
        done[box.getAttribute("data-step")] = box.checked;
        try { window.localStorage.setItem("jk-done", JSON.stringify(done)); } catch (e) { /* this visit only */ }
        paint();
      });
    });
    paint();
    var stops = links.map(function (a) { return $(a.getAttribute("href")); });
    var ticking = false;
    function update() {
      ticking = false;
      var cur = 0;
      stops.forEach(function (el, n) { if (el && el.getBoundingClientRect().top < 220) cur = n; });
      links.forEach(function (a, n) {
        a.classList.toggle("on", n === cur);
        if (n === cur) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
      });
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  // A link to a part inside a closed fold-out opens the fold-out first.
  function openLinkedDetails() {
    if (!location.hash || location.hash.length < 2) return;
    var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!target) return;
    for (var el = target; el; el = el.parentElement) {
      if (el.tagName === "DETAILS") el.open = true;
    }
    target.scrollIntoView();
  }

  function start() {
    setUpTheme();
    setUpMenu();
    addCopyButtons();
    setUpMatrix();
    setUpPanels();
    setUpTabs();
    setUpBars();
    setUpVerdicts();
    setUpGuide();
    openLinkedDetails();
    window.addEventListener("hashchange", openLinkedDetails);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
