"""The result page: what the marking page shows at /result, and `.judgekeeper/report.html`.

One self-contained page (look.py: nothing loaded from anywhere else); every string in it is
escaped. Its one script ("Show all", kappa's ⓘ and Copy) is fixed text: the page's Content-Security-Policy
lets exactly that run (by its hash) and nothing else, both when served and in the saved copy.

Served by the marking page (`back` given), each disagreement also asks why the person marked it
so (reasons.py), and a second fixed script (REASONS_SCRIPT) saves each change with POST /label;
only that page may connect back (LIVE_CSP). report.html shows the reasons read-only.

The marks kept aside are counted, never shown: fix.py keeps them to test a new rule fairly.
Which parts show depends on the result's level (targets.level): Fix it only when the
LLM-as-a-judge needs work, and only the counts before there is a result (too_early).
"""

from __future__ import annotations

import json
import re
from html import escape

from judgekeeper import batches, look, reasons, targets
from judgekeeper.start_label import EARLY, FOLDER, GOOD, MARK_MORE, NEEDS, VERDICTS

ROWS_SHOWN = 3  # disagreements shown in a group before "Show all"
KAPPA_MEANS = ("Kappa is agreement beyond coincidence. 0 means no better than coincidence, 1 "
               "means perfect agreement.")
STATES = {"gate": ("good", GOOD), "not_gate": ("needs", NEEDS), "check": ("plain", EARLY),
          "too_early": ("plain", EARLY), None: ("plain", EARLY)}
TICK = ('<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
        '<path d="M3 8.5l3.2 3.2L13 5"/></svg>')

# The page's script: fixed text, so its hash can be in the Content-Security-Policy.
SCRIPT = """
  (function () {
    function each(list, f) { Array.prototype.forEach.call(list, f); }
    // A row's "Show all": only when one of its cells is longer than its 4 lines; a cut cell
    // fades out at the bottom.
    function fit() {
      each(document.querySelectorAll(".open-row"), function (b) {
        var row = b.closest("tr"), open = row.hasAttribute("data-open"), cut = false;
        each(row.querySelectorAll("td[data-label]"), function (td) {
          var ht = td.classList.contains("ht");
          var more = !open && (ht || td.scrollHeight > td.clientHeight + 1);
          td.classList.toggle("cut", more && !ht);
          cut = cut || more;
        });
        b.hidden = !open && !cut;
      });
    }
    each(document.querySelectorAll(".open-row"), function (b) {
      b.addEventListener("click", function () {
        var row = b.closest("tr"), open = !row.hasAttribute("data-open");
        if (open) { row.setAttribute("data-open", ""); } else { row.removeAttribute("data-open"); }
        b.setAttribute("aria-expanded", String(open));
        b.textContent = open ? "Show less" : "Show all";
        fit();
      });
    });
    fit();
    window.addEventListener("resize", fit);
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(fit); }
    each(document.querySelectorAll(".more"), function (b) {
      b.addEventListener("click", function () {
        var open = b.getAttribute("aria-expanded") !== "true";
        b.setAttribute("aria-expanded", String(open));
        var table = document.getElementById(b.getAttribute("aria-controls"));
        each(table.querySelectorAll("tr.extra"), function (row) { row.hidden = !open; });
        b.textContent = open ? "Show fewer" : "Show all " + b.getAttribute("data-n");
        fit();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".kappa .i"), function (b) {
      function show(open) { b.setAttribute("aria-expanded", String(open)); }
      b.addEventListener("click", function () {
        b.removeAttribute("data-shut"); show(b.getAttribute("aria-expanded") !== "true"); });
      b.addEventListener("blur", function () { b.removeAttribute("data-shut"); });
      document.addEventListener("click", function (e) {
        if (!b.parentNode.contains(e.target)) { show(false); } });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { show(false); b.setAttribute("data-shut", ""); } });
    });
    var copy = document.getElementById("copy"), timer;
    if (!copy) { return; }
    copy.addEventListener("click", function () {
      var text = document.getElementById(copy.getAttribute("data-copy")).textContent;
      function done(ok) {
        if (ok) { copy.innerHTML = '__TICK__Copied'; } else { copy.textContent = "Copy failed"; }
        copy.classList.toggle("done", ok);
        clearTimeout(timer);
        timer = setTimeout(function () {
          copy.textContent = "Copy"; copy.classList.toggle("done", false); }, 1500);
      }
      try { navigator.clipboard.writeText(text).then(function () { done(true); },
                                                     function () { done(false); }); }
      catch (e) { done(false); }
    });
  })();
""".replace("__TICK__", TICK)
# The live page's second script: the reason boxes. Each change is saved at once (the "Other…"
# box when it is left, and at most once a second while typing); the token is the page's own.
REASONS_SCRIPT = """
  (function () {
    var token = new URLSearchParams(location.search).get("token") || "", MAX = __MAX__;
    function count(text) { return Array.from(text).length; }
    function each(list, f) { Array.prototype.forEach.call(list, f); }
    function on(b) { return b.getAttribute("aria-pressed") === "true"; }
    each(document.querySelectorAll(".why"), function (box) {
      var saved = box.querySelector(".saved"), input = box.querySelector("input"),
          other = box.querySelector(".other"), mark = box.querySelector(".mark-part"),
          clear = box.querySelector(".clear-part"),
          cell = document.getElementById(box.getAttribute("data-answer")),
          add = box.querySelector(".add-reason"), now = box.querySelector(".said-now"),
          said = box.querySelector(".said-text"),
          text = cell.textContent, shown = parseInt(box.getAttribute("data-len"), 10),
          spans = JSON.parse(box.getAttribute("data-spans") || "[]"),
          sent = input.value, last = 0, timer = null, pick = null;
      function body() {
        var taps = Array.prototype.filter.call(box.querySelectorAll(".chip[aria-pressed]"), on);
        return {id: box.getAttribute("data-id"),
                reasons: taps.filter(function (b) { return b.hasAttribute("data-reason"); })
                  .map(function (b) { return b.getAttribute("data-reason"); }),
                rule_parts: taps.filter(function (b) { return b.hasAttribute("data-part"); })
                  .map(function (b) { return Number(b.getAttribute("data-part")); }),
                spans: spans, note: input.value};
      }
      // "Your reason: ... · Change" from what is saved, or "Add a reason".
      function line() {
        var taps = Array.prototype.filter.call(box.querySelectorAll(".chip[aria-pressed]"), on);
        var words = taps.filter(function (b) { return b.hasAttribute("data-reason"); })
          .concat(taps.filter(function (b) { return b.hasAttribute("data-part"); }))
          .map(function (b) { return b.getAttribute("data-said"); });
        var whole = taps.filter(function (b) { return b.hasAttribute("data-reason"); })
          .concat(taps.filter(function (b) { return b.hasAttribute("data-part"); }))
          .map(function (b) { return b.getAttribute("data-whole") || b.getAttribute("data-said"); });
        if (input.value.trim()) {
          words.push("\u201c" + input.value.trim() + "\u201d");
          whole.push("\u201c" + input.value.trim() + "\u201d");
        }
        said.textContent = "Your reason: " + words.join("; ");
        // the whole rule parts on hover, when one is cut
        if (whole.join() !== words.join()) { said.title = "Your reason: " + whole.join("; "); }
        else { said.removeAttribute("title"); }
        now.hidden = !words.length;
        add.textContent = words.length ? "Change" : "Add a reason";
      }
      add.addEventListener("click", function () {
        var open = add.getAttribute("aria-expanded") !== "true";
        add.setAttribute("aria-expanded", String(open));
        document.getElementById(add.getAttribute("aria-controls")).hidden = !open;
      });
      function send() {
        clearTimeout(timer); last = Date.now(); sent = input.value; saved.textContent = "";
        window.fetch("/label?token=" + encodeURIComponent(token), {method: "POST",
          headers: {"Content-Type": "application/json"}, body: JSON.stringify(body())})
          .then(function (r) {
            if (r.ok) { saved.textContent = "Saved"; line(); return; }
            return r.json().then(function (e) {
              saved.textContent = "Not saved: " + (e.error || r.status); });
          }, function () { saved.textContent = "Not saved: judgekeeper is not running."; });
      }
      function draw() {
        var chars = Array.from(text), at = 0;
        while (cell.firstChild) { cell.removeChild(cell.firstChild); }
        spans.slice().sort(function (a, b) { return a[0] - b[0]; }).forEach(function (s) {
          var from = Math.max(s[0], at), to = Math.min(s[1], shown);
          if (to <= from) { return; }
          cell.appendChild(document.createTextNode(chars.slice(at, from).join("")));
          var b = document.createElement("b");
          b.className = "hl"; b.textContent = chars.slice(from, to).join("");
          cell.appendChild(b); at = to;
        });
        cell.appendChild(document.createTextNode(chars.slice(at).join("")));
        clear.hidden = !spans.length;
      }
      each(box.querySelectorAll(".chip[aria-pressed]"), function (b) {
        b.addEventListener("click", function () {
          b.setAttribute("aria-pressed", String(!on(b))); send(); });
      });
      other.addEventListener("click", function () {
        var open = other.getAttribute("aria-expanded") !== "true";
        other.setAttribute("aria-expanded", String(open));
        document.getElementById(other.getAttribute("aria-controls")).hidden = !open;
        if (open) { input.focus(); }
      });
      input.addEventListener("input", function () {
        var wait = 1000 - (Date.now() - last);
        clearTimeout(timer);
        if (wait <= 0) { send(); } else { timer = setTimeout(send, wait); }
      });
      input.addEventListener("blur", function () { if (input.value !== sent) { send(); } });
      document.addEventListener("selectionchange", function () {
        var sel = window.getSelection();
        if (!sel.rangeCount || sel.isCollapsed) { return; }  // a tap on the button may clear it
        var r = sel.getRangeAt(0), before = document.createRange();
        pick = null;
        if (cell.contains(r.startContainer) && cell.contains(r.endContainer)) {
          before.setStart(cell, 0); before.setEnd(r.startContainer, r.startOffset);
          var s = count(before.toString()), e = Math.min(s + count(r.toString()), shown);
          if (e > s) { pick = [s, e]; }
        }
        mark.hidden = !pick || spans.length >= MAX;
      });
      mark.addEventListener("mousedown", function (e) { e.preventDefault(); });
      mark.addEventListener("click", function () {
        if (!pick || spans.length >= MAX) { return; }
        spans.push(pick); pick = null; mark.hidden = true;
        window.getSelection().removeAllRanges(); draw(); send(); clear.focus();
      });
      clear.addEventListener("click", function () {
        spans = []; draw(); send(); other.focus(); });
    });
  })();
""".replace("__MAX__", str(reasons.MAX_SPANS))
CSP = ("default-src 'none'; script-src " + look.script_hash(SCRIPT) + "; style-src "
       "'unsafe-inline'; font-src data:; img-src 'none'; base-uri 'none'; form-action 'none'")
LIVE_CSP = ("default-src 'none'; script-src " + look.script_hash(SCRIPT) + " "
            + look.script_hash(REASONS_SCRIPT) + "; style-src 'unsafe-inline'; font-src data:; "
            "connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'")


def script_csp(live: bool = False) -> str:
    """The page's Content-Security-Policy: the live page may also save reasons."""
    return LIVE_CSP if live else CSP

STYLE = """
:root { --gutter: 32px; }
table { border-collapse: collapse; width: 100%; }
.mono { font-family: var(--mono); font-weight: 500; white-space: nowrap; }
.band { padding-left: var(--gutter); padding-right: var(--gutter); }
.verdict { padding-top: 88px; padding-bottom: 72px; text-align: center; }
.verdict h1 { margin: 0 auto; font-size: clamp(34px, 4vw, 56px); line-height: 1.1;
  letter-spacing: -.02em; font-weight: 800; max-width: 20ch; text-wrap: balance; }
.verdict h1 .term { white-space: nowrap; }
.verdict h1.needs { color: var(--amber); }
.verdict h1.good { color: var(--green); }
.verdict h1.plain { color: var(--text); }
.lead { margin: 20px auto 0; font-size: 20px; line-height: 1.4; color: var(--muted); }
.lead b { font-family: var(--mono); font-weight: 500; font-size: 18px; color: var(--text); }
.lead a { color: var(--text); text-decoration: underline; text-underline-offset: 3px; }
.lead code { font-size: 18px; color: var(--text); }
.counts { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); display: grid; grid-template-columns: 1fr 1fr; }
.counts p { margin: 0; padding: 32px var(--gutter); font-size: 19px; line-height: 1.4; font-weight: 500; }
.counts p + p { border-left: 1px solid var(--line); }
.left-out { margin: 16px 0 0; font-size: 15px; color: var(--muted); }
.group { padding-top: 64px; }
.gh { display: flex; align-items: baseline; justify-content: space-between; gap: 24px; }
.gh h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; color: var(--amber); }
.more { font-size: 14px; color: var(--text); text-decoration: underline;
  text-underline-offset: 3px; white-space: nowrap; }
.tbl { margin-top: 32px; table-layout: fixed; }
.tbl col.c1 { width: 28%; } .tbl col.c2 { width: 44%; } .tbl col.c3 { width: 28%; }
.tbl th, .panel th { font-family: var(--mono); font-weight: 400; font-size: 12px;
  letter-spacing: .06em; text-transform: uppercase; color: var(--muted); text-align: left;
  border-bottom: 1px solid var(--line); }
.tbl th { padding: 0 32px 14px 0; }
.tbl td { font-size: 17px; line-height: 1.55; padding: 24px 32px 24px 0; vertical-align: top;
  border-bottom: 1px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
.tbl th:last-child, .tbl td:last-child { padding-right: 0; }
.tbl td:last-child { color: var(--muted); }
.note { margin: 16px 0 0; font-size: 13px; color: var(--muted); text-align: left; }
.open-row, .add-reason { font-size: 14px; color: var(--text); text-decoration: underline;
  text-underline-offset: 3px; white-space: nowrap; }
.open-row { margin-top: 10px; color: var(--muted); }
.open-row:hover { color: var(--text); }
.why-line { margin: 0; display: flex; align-items: baseline; gap: 0; min-width: 0;
  font-size: 15px; color: var(--muted); }
.said-now { display: inline-flex; min-width: 0; white-space: pre; }
.said-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.why-body { margin-top: 16px; }
.add-why { margin: 24px 0 0; font-size: 15px; color: var(--muted); }
.add-why code { font-size: 14px; color: var(--text); }
.tbl td[data-label] { border-bottom: 0; padding-bottom: 10px; }
.tbl td.why-cell { white-space: normal; padding-top: 0; color: var(--text); }
.row-foot { margin: 0; font-size: 15px; line-height: 1.5; color: var(--muted); }
.row-foot > .open-row, .row-foot > .said { display: inline-block; margin-top: 10px; }
.why-line > .open-row { margin-top: 0; }
.open-row[hidden] + .dot { display: none; }
.dot { white-space: pre; }
.said { color: var(--muted); }
.q-peek, .q-gap { display: none; }
.q-full, .q-end { display: block; }
.fname { display: block; font-family: var(--mono); font-size: 11px; font-weight: 400;
  letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-bottom: 2px; }
b.hl { font-weight: 800; color: var(--text); text-decoration: underline;
  text-decoration-color: var(--amber); text-decoration-thickness: 2px;
  text-underline-offset: 3px; }
.why .q { margin: 0 0 10px; font-size: 15px; font-weight: 700; }
.why .sub { margin: 0 0 8px; font-size: 13px; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chips + .sub, .chips + .chips { margin-top: 14px; }
.chip { font-size: 14px; line-height: 1.35; padding: 8px 12px; border: 1px solid var(--line);
  color: var(--muted); text-align: left; max-width: 100%; overflow-wrap: anywhere; }
.chip:hover { color: var(--text); background: var(--hover); }
.chip[aria-pressed="true"] { color: var(--bg); background: var(--text);
  border-color: var(--text); }
.chip[aria-pressed="true"]:focus-visible { outline-color: var(--bg); }
.other[aria-expanded="true"] { color: var(--text); border-color: var(--text); }
.other-box { margin-top: 12px; display: grid; gap: 6px; max-width: 640px; }
.other-box label { font-size: 13px; color: var(--muted); }
.other-box input { font: inherit; font-size: 15px; color: var(--text); background: var(--bg);
  border: 1px solid var(--line); padding: 10px 12px; width: 100%; }
.marked { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center;
  gap: 8px 16px; min-height: 24px; }
.mark-part, .clear-part { font-size: 14px; text-decoration: underline;
  text-underline-offset: 3px; }
.saved { font-size: 13px; color: var(--muted); }
.details { padding-top: 64px; }
.details h2, .fix h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; }
.panel { margin-top: 32px; table-layout: fixed; }
.panel caption { text-align: left; font-size: 13px; color: var(--muted); padding: 0 0 12px; }
.panel caption .weighted { display: block; margin-top: 4px; }
.panel col.d1 { width: 48%; } .panel col.d2 { width: 26%; } .panel col.d3 { width: 26%; }
.panel th { padding: 0 24px 10px 0; }
.panel thead td { border-bottom: 1px solid var(--line); }
.panel td { font-size: 17px; padding: 20px 32px 20px 0; border-bottom: 1px solid var(--line);
  vertical-align: top; }
.panel tbody th { font-family: var(--sans); font-size: 17px; font-weight: 400; letter-spacing: 0;
  text-transform: none; color: var(--text); padding: 20px 32px 20px 0; vertical-align: top; }
.panel tbody td { font-family: var(--mono); font-size: 15px; white-space: nowrap; }
.kappa { position: relative; display: inline-block; }
.kappa .i { font-size: 15px; color: var(--muted); margin-left: 6px; line-height: 1; }
.kappa .tip { position: absolute; left: 0; bottom: calc(100% + 8px); width: min(320px, 80vw);
  background: var(--bg); border: 1px solid var(--line); padding: 10px 12px; font-size: 13px;
  line-height: 1.45; color: var(--text); white-space: normal; display: none; z-index: 2; }
.kappa .i[aria-expanded="true"] + .tip, .kappa .i:focus-visible:not([data-shut]) + .tip {
  display: block; }
@media (hover: hover) { .kappa:hover .tip { display: block; } }
.fix { margin-top: 64px; border-top: 1px solid var(--line); padding-top: 48px; padding-bottom: 72px; }
.fix-in { display: grid; grid-template-columns: 1fr auto; gap: 24px 48px; align-items: center; }
.fix-in h2, .fix-in p { grid-column: 1; }
.fix-in .cmd { grid-column: 2; grid-row: 1 / span 2; }
.fix p { margin: 0; font-size: 17px; line-height: 1.6; color: var(--muted); max-width: 64ch; }
.fix p code { font-size: 15px; color: var(--text); }
.cmd { display: inline-grid; grid-template-columns: auto auto; border: 1px solid var(--line);
  min-width: 0; }
.cmd code { font-size: 17px; padding: 16px 24px; align-self: center; }
.cmd button { font-size: 13px; padding: 0 18px; border-left: 1px solid var(--line); color: var(--muted); min-width: 92px; }
.cmd button:hover, .cmd button.done { color: var(--text); }
.cmd button.done svg { width: 14px; height: 14px; vertical-align: -2px; margin-right: 6px;
  fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round;
  stroke-linejoin: round; }
@media (min-width: 721px) {
  .tbl, .tbl thead, .tbl tbody { display: block; }
  .tbl colgroup { display: none; }
  .tbl tr { display: grid; grid-template-columns: 28fr 44fr 28fr; column-gap: 32px;
    border-bottom: 1px solid var(--line); }
  .tbl th, .tbl td { display: block; padding: 0; border-bottom: 0; }
  .tbl thead th { padding-bottom: 14px; }
  .tbl tbody tr { padding: 22px 0; }
  .tbl td[data-label] { font-size: 16px; line-height: 1.55; max-height: calc(4 * 1.55em);
    overflow: hidden; }
  .tbl td[data-label].cut { -webkit-mask-image: linear-gradient(#000 60%, transparent);
    mask-image: linear-gradient(#000 60%, transparent); }
  .tbl tr[data-open] td[data-label] { max-height: 60vh; overflow: auto; }
  .tbl tr[data-open] td.why-cell { padding-top: 8px; }
  .tbl td.ht { max-height: calc(5 * 1.55em); }
  .tbl tr:not([data-open]) td.ht .q-peek, .tbl tr:not([data-open]) td.ht .q-end {
    display: block; max-height: calc(2 * 1.55em); overflow: hidden; }
  .tbl tr:not([data-open]) td.ht .q-gap { display: block; color: var(--faint); }
  .tbl tr:not([data-open]) td.ht .q-full { display: none; }
  .tbl tr:not([data-open]) td.ht .q-end { display: flex; flex-direction: column;
    justify-content: flex-end; }
  .tbl td.why-cell { grid-column: 1 / -1; }
  .tbl td[data-label], .tbl td.why-cell { padding-bottom: 0; border-bottom: 0; }
}
@media (max-width: 720px) {
  :root { --gutter: 16px; }
  .verdict { padding-top: 72px; padding-bottom: 64px; }
  .lead { font-size: 17px; }
  .counts { grid-template-columns: 1fr; }
  .counts p { font-size: 18px; padding: 24px var(--gutter); }
  .counts p + p { border-left: 0; border-top: 1px solid var(--line); }
  .gh { flex-direction: column; gap: 10px; }
  .gh h2 { font-size: 20px; }
  .tbl thead, .panel thead { display: none; }
  .tbl, .tbl tbody, .tbl tr, .tbl td { display: block; }
  .tbl tr { padding: 18px 0; border-bottom: 1px solid var(--line); }
  .tbl td { border: 0; padding: 0; font-size: 16px; }
  .tbl td + td { margin-top: 10px; }
  .tbl td::before { content: attr(data-label); display: block; font-family: var(--mono);
    font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted);
    margin-bottom: 3px; }
  .tbl td[data-label], .tbl td.why-cell { padding-bottom: 0; border-bottom: 0; }
  .tbl td.why-cell::before { content: none; }
  .panel, .panel tbody, .panel tr, .panel th, .panel td, .panel caption { display: block; }
  .panel tr { padding: 12px 0; border-bottom: 1px solid var(--line); }
  .panel th, .panel td { border: 0; padding: 0; }
  .panel tbody td { margin-top: 4px; }
  .panel td[data-label]::before { content: attr(data-label) " "; font-family: var(--sans);
    color: var(--muted); font-size: 13px; }
  .fix { margin-top: 48px; padding-top: 40px; padding-bottom: 56px; }
  .fix-in { grid-template-columns: 1fr; }
  .fix-in .cmd { grid-column: 1; grid-row: auto; }
  .cmd { display: grid; grid-template-columns: 1fr auto; width: 100%; }
  .cmd code { padding: 16px; }
  .cmd button { font-size: 15px; }
  .tbl td::before { font-size: 13px; }
  .panel td[data-label]::before, .panel caption, .note { font-size: 14px; }
  .kappa .tip { font-size: 15px; }
}
@media (max-width: 720px), (pointer: coarse) {
  .more { font-size: 16px; padding: 12px 0; margin: -12px 0; }
  .kappa .i { font-size: 18px; padding: 13px 14px; margin: -13px -14px -13px -8px; }
}
@media (max-width: 300px) {
  .cmd { grid-template-columns: 1fr; }
  .cmd button { border-left: 0; border-top: 1px solid var(--line); min-height: 48px; }
}
"""


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _two(x: float) -> str:
    """Two decimals with a real minus sign, never "−0.00"."""
    text = f"{x:.2f}"
    return "0.00" if text == "-0.00" else text.replace("-", "−")


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def counts(r: dict) -> dict:
    """From every mark: how many you passed and failed, and how many of each the judge got
    the other way ("strict": you passed, it failed; "easy": you failed, it passed)."""
    g = r.get("groups") or {}
    gp, gf = g.get("pass") or {}, g.get("fail") or {}
    return {"passed": r["labels"]["correct"], "failed": r["labels"]["wrong"],
            "strict": int(gf.get("correct") or 0),
            "easy": int(gp.get("labeled") or 0) - int(gp.get("correct") or 0)}


def commands(r: dict) -> dict[str, str]:
    """The commands the page names, made again from the flags of the run that made the result
    (r["flags"], start.run_flags; never the text of r["command"]), as the terminal prints
    them: `mark` keeps every flag, `check` and `fix` the path only, `more`
    (start_label.mark_command) the flags that read results. On Windows a value no quotes keep
    as text shows as NAME (said by held_note)."""
    from judgekeeper.start import command_from, saved_flags
    from judgekeeper.start_label import mark_command

    flags = r.get("flags")
    path = {"path": saved_flags(flags).get("path", ".")}
    run = command_from(flags, kept=True)
    return {"run": run, "mark": command_from(flags, "mark", kept=True),
            "check": command_from(path, "check", kept=True),
            "fix": command_from(path, "fix", kept=True), "more": mark_command(run)}


def held_note(r: dict, shown: str) -> str:
    """When a command in `shown` (the page's parts) shows NAME, on Windows: each value the
    commands show as NAME, as data."""
    from judgekeeper.start import held_values
    from judgekeeper.textio import PLACEHOLDER

    if not re.search(rf"\b{PLACEHOLDER}\b", shown):
        return ""
    lines = "".join(f'<p class="note"><code>{_e(f"{PLACEHOLDER}: {v}")}</code></p>'
                    for v in held_values(r.get("flags")))
    return f'<div class="band">{lines}</div>' if lines else ""


def next_step(r: dict) -> str | None:
    """What comes after this result, the same in the terminal and on this page: "fix" when
    the judge needs work, None when it is good enough, else "mark" (too early to tell)."""
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    return "fix" if level == "not_gate" else None if level == "gate" else "mark"


def shows_disagreements(r: dict) -> bool:
    """Whether the page lists the disagreements (and the estimates): real numbers, not too
    early to tell."""
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    return level not in ("too_early", None)


def _all_marked(r: dict) -> str:
    """start_label.all_marked_lines as one paragraph, its command as code."""
    from judgekeeper.start_label import all_marked_lines

    first, then = all_marked_lines(r["labels"], commands(r)["more"])
    return f"{_e(first)} {_code_line(then.removeprefix('Next: '))}"


def _code_line(text: str) -> str:
    """A next step as a sentence: its first letter in capitals, each `command` as code."""
    parts = text.split("`")
    out = "".join(f"<code>{_e(x)}</code>" if i % 2 else _e(x) for i, x in enumerate(parts))
    return out[:1].upper() + out[1:]


def disagreed(c: dict) -> str:
    """How many answers the person and the judge disagreed on, as the terminal says it
    (front.agreement_lines), the numbers in bold."""
    d, n = c["strict"] + c["easy"], c["passed"] + c["failed"]
    if not d:
        return (f"You and your LLM-as-a-judge agreed on all <b>{n}</b> "
                f"{'answer' if n == 1 else 'answers'}.")
    return f"You and your LLM-as-a-judge disagreed on <b>{d}</b> of <b>{n}</b> answers."


def _verdict(r: dict, c: dict, back: str | None, worse: str | None = None,
             above: bool = False) -> str:
    """The headline, and under it the disagreements, for every result, as in the terminal;
    then, too early to tell, how to mark more: a link to the marking page while it runs, the
    command in the saved copy; with every answer marked, what comes next
    (start_label.all_marked_lines). After a check found the new judge worse, the next step
    that check gave (`worse`), unless the Last check block `above` gives it."""
    from judgekeeper.start_label import all_labeled

    level = r.get("verdict_level") if r["check"] != "too_few" else None
    cls, headline = STATES.get(level, STATES[None])
    if level is None and not all_labeled(r):  # before a result: what the terminal says
        headline = VERDICTS[None]
    if worse:
        then = "" if above else _code_line(worse)
    elif cls != "plain":
        then = ""
    elif all_labeled(r):
        then = _all_marked(r)
    elif back:
        then = f'<a href="{_e(back)}">{_e(MARK_MORE)}</a>'
    else:
        then = f"Run <code>{_e(commands(r)['mark'])}</code> to mark more answers."
    lead = " ".join(x for x in (disagreed(c) if level is not None else "", then) if x)
    return (f'<section class="verdict band" aria-labelledby="verdict-h"><h1 id="verdict-h" '
            f'class="{cls}">{_term(headline)}</h1><p class="lead">{lead}</p></section>')


def _term(text: str) -> str:
    """`text` escaped, "LLM-as-a-judge" kept on one line (the heading wraps evenly)."""
    return _e(text).replace("LLM-as-a-judge", '<span class="term">LLM-as-a-judge</span>')


def count_line(did: str, n: int, judge_passed: int, judge_failed: int) -> str:
    """"You passed 15 answers. Of those, your judge passed 7 and failed 8.", numbers in mono."""
    def mono(x: int) -> str:
        return f'<span class="mono">{x}</span>'
    return (f"You {did} {mono(n)} {'answer' if n == 1 else 'answers'}. Of those, your "
            f"LLM-as-a-judge passed {mono(judge_passed)} and failed {mono(judge_failed)}.")


def own_line(did: str, n: int) -> str:
    """"You passed 15 answers.", the number in mono: before a result, the person's own count
    only, so marking an answer and taking it back never shows the judge's grade on it."""
    return f'You {did} <span class="mono">{n}</span> {"answer" if n == 1 else "answers"}.'


def _counts(r: dict, c: dict) -> str:
    """The two counts (before a result, the person's own only), and the answers the judge gave
    no Pass or Fail on (left out), if any."""
    from judgekeeper.judge_check import NO_DECISION

    if r["check"] == "too_few":
        lines = [own_line("passed", c["passed"]), own_line("failed", c["failed"])]
    else:
        lines = [count_line("passed", c["passed"], c["passed"] - c["strict"], c["strict"]),
                 count_line("failed", c["failed"], c["easy"], c["failed"] - c["easy"])]
    row = '<div class="counts">' + "".join(f"<p>{x}</p>" for x in lines) + "</div>"
    left = batches.line(r.get("batches"))
    if left:
        row += f'<p class="left-out band">{_e(left)}</p>'
    block = r.get("judge_check") or {}
    none = sum(int(block.get(k) or 0) for k in NO_DECISION)
    if none:
        row += ('<p class="left-out band">Your LLM-as-a-judge gave no Pass or Fail on '
                f'{_plural(none, "answer", "answers")}. {"It is" if none == 1 else "They are"} '
                'left out.</p>')
    from judgekeeper.start_label import second_thoughts

    for line in second_thoughts(r.get("made")):
        row += f'<p class="left-out band">{_e(line)}</p>'
    return row


OPEN_ROW = ('<button type="button" class="open-row" aria-expanded="false" hidden>Show all'
            '</button>')
DOT = '<span class="dot" aria-hidden="true"> · </span>'


PEEK_CHARS = 300  # of each of the first 2 lines a folded question shows before its "…"


def head_tail(text: str) -> tuple[str, str, str] | None:
    """A long text whose last paragraph (or line) is a question, as the marking page folds it:
    (its start, the line break, that question); None for any other text."""
    at, gap = text.rfind("\n\n"), 2
    if at < 0:
        at, gap = text.rfind("\n"), 1
    if at < 0:
        return None
    head, tail = text[:at], text[at + gap:]
    if not tail.strip() or not tail.rstrip().endswith("?") or (
            len(head) <= 200 and head.count("\n") < 3):
        return None
    return head, text[at:at + gap], tail


def _question(m: dict) -> tuple[str, str]:
    """A row's question cell (its class, its HTML): each field under its name when it has
    several (fix.py's "fields"); a long text ending in a question folded to its first 2 lines,
    "…" and that question, the whole text in order when the row is open (SCRIPT, STYLE)."""
    fields = m.get("fields")
    if fields:
        return "", "\n".join(f'<span class="fname">{_e(k)}</span>{_e(v)}' for k, v in fields)
    parts = head_tail(m["question"])
    if not parts:
        return "", _e(m["question"])
    head, gap, tail = parts
    peek = "\n".join([line[:PEEK_CHARS] for line in head.split("\n") if line.strip()][:2])
    return " ht", (f'<span class="q-peek" aria-hidden="true">{_e(peek)}</span>'
                   '<span class="q-gap" aria-hidden="true">…</span>'
                   f'<span class="q-full">{_e(head + gap)}</span>'
                   f'<span class="q-end">{_e(tail)}</span>')


def _answer(text: str, spans) -> str:
    """An answer, the words the person marked in bold."""
    out, at = [], 0
    for s, e in reasons.merged(spans, len(text)):
        out += [_e(text[at:s]), f'<b class="hl">{_e(text[s:e])}</b>']
        at = e
    return "".join(out) + _e(text[at:])


def _part_said(n: int, part: str, whole: bool = False) -> str:
    """A rule part in "Your reason: ...", cut at reasons.SAID_CHARS unless `whole`."""
    shown = part if whole else reasons.short(part, reasons.SAID_CHARS)
    return f"rule part {n} (\u201c{shown}\u201d)"


def _reason_said(k: str, own: dict[str, str]) -> str:
    return (reasons.lower(reasons.REASONS[k][0]) if k in reasons.REASONS
            else f"\u201c{own[k]}\u201d")


def _said_words(m: dict, parts: list[str], own: dict[str, str],
                whole: bool = False) -> list[str]:
    """The person's reasons on one answer, each as it reads in "Your reason: ...": the reasons
    tapped, the rule parts (each cut, or `whole` for the line's title), the note."""
    why = m.get("why") or {}
    said = [_reason_said(k, own) for k in why.get("reasons") or []
            if k in reasons.REASONS or k in own]
    said += [_part_said(n, parts[n - 1], whole) for n in why.get("rule_parts") or []
             if 1 <= n <= len(parts)]
    if why.get("note"):
        said.append(f"\u201c{why['note']}\u201d")
    return said


def _whole_title(m: dict, parts: list[str], own: dict[str, str]) -> str:
    """A title with the whole "Your reason: ..." when a rule part in it is cut."""
    said, whole = _said_words(m, parts, own), _said_words(m, parts, own, whole=True)
    return f' title="{_e("Your reason: " + "; ".join(whole))}"' if whole != said else ""


def _said(m: dict, parts: list[str], own: dict[str, str]) -> str:
    """"Your reason: ..." for report.html, or nothing when the person gave none."""
    said = _said_words(m, parts, own)
    return (f'{DOT}<span class="said"{_whole_title(m, parts, own)}>Your reason: '
            f'{_e("; ".join(said))}</span>' if said else "")


def _chip(text: str, pressed: bool, attr: str, said: str = "", whole: str = "") -> str:
    whole = f' data-whole="{_e(whole)}"' if whole and whole != said else ""
    return (f'<button type="button" class="chip" aria-pressed="{str(pressed).lower()}" '
            f'{attr} data-said="{_e(said)}"{whole}>{_e(text)}</button>')


def _box(m: dict, n: str, parts: list[str], own: list[dict], left_out: int = 0) -> str:
    """The reason box of one disagreement on the live page (`left_out`: the rule's parts with
    no button)."""
    why = m.get("why") or {}
    taps, chosen = set(why.get("reasons") or []), set(why.get("rule_parts") or [])
    mark = "Fail" if m["final"] == "fail" else "Pass"
    words = {c["id"]: c["text"] for c in own}
    said = _said_words(m, parts, words)
    out = [(f'<div class="why" data-id="{_e(m["id"])}" data-answer="a-{n}" '
            f'data-len="{len(m["answer"])}" '
            f'data-spans="{_e(json.dumps(why.get("spans") or []))}" role="group" '
            f'aria-labelledby="q-{n}">'),
           (f'<p class="why-line">{OPEN_ROW}{DOT}<span class="said-now"'
            f'{"" if said else " hidden"}>'
            f'<span class="said-text"{_whole_title(m, parts, words)}>Your reason: '
            f'{_e("; ".join(said))}</span>'
            '<span aria-hidden="true"> · </span></span><button type="button" '
            f'class="add-reason" aria-expanded="false" aria-controls="wb-{n}">'
            f'{"Change" if said else "Add a reason"}</button></p>'),
           f'<div class="why-body" id="wb-{n}" hidden>',
           f'<p class="q" id="q-{n}">{_e(reasons.QUESTION.format(mark=mark))}</p>']
    if parts:
        out.append(f'<p class="sub" id="p-{n}">{_e(reasons.PART_QUESTION[m["judge"]])}</p>'
                   f'<div class="chips" role="group" aria-labelledby="p-{n}">'
                   + "".join(_chip(f"{k}. {reasons.short(text)}", k in chosen,
                                   f'data-part="{k}"' + (f' title="{_e(text)}"'
                                                        if reasons.short(text) != text else ""),
                                   _part_said(k, text), _part_said(k, text, whole=True))
                             for k, text in enumerate(parts, 1)) + "</div>")
        if left_out:
            out.append(f'<p class="sub">{_e(reasons.parts_left_out_line(left_out))}</p>')
    chips = [_chip(reasons.REASONS[k][0], k in taps, f'data-reason="{k}"', _reason_said(k, words))
             for k in reasons.offered(m["judge"])]
    chips += [_chip(c["text"], c["id"] in taps, f'data-reason="{_e(c["id"])}"',
                    _reason_said(c["id"], words))
              for c in own if c.get("from") != m["id"]]
    note, opened = why.get("note") or "", bool(why.get("note"))
    chips.append(f'<button type="button" class="chip other" aria-expanded="'
                 f'{str(opened).lower()}" aria-controls="o-{n}">{_e(reasons.OTHER)}</button>')
    out.append(f'<div class="chips" role="group" aria-labelledby="q-{n}">{"".join(chips)}'
               "</div>")
    out.append(f'<div class="other-box" id="o-{n}"{"" if opened else " hidden"}>'
               f'<label for="n-{n}">Your reason, in your words</label>'
               f'<input type="text" id="n-{n}" maxlength="{reasons.MAX_NOTE}" '
               f'autocomplete="off" value="{_e(note)}"></div>')
    out.append('<div class="marked"><button type="button" class="mark-part" hidden>Mark this '
               'part</button><button type="button" class="clear-part"'
               f'{"" if why.get("spans") else " hidden"}>Clear marked words</button>'
               '<span class="saved" aria-live="polite"></span></div>')
    return "".join(out) + "</div></div>"


def _made(r: dict) -> str:
    """The notes on marks another program could have made (start_label.link_lines), as in the
    terminal."""
    from judgekeeper.start_label import link_lines

    said = link_lines(r.get("made"))
    return ('<div class="band">' + "".join(f'<p class="note">{_e(x)}</p>' for x in said)
            + "</div>") if said else ""


def _group(key: str, said: str, judge: str, rows: list[dict], live: bool = False,
           parts: list[str] | None = None, own: list[dict] | None = None,
           left_out: int = 0) -> str:
    """One group of disagreements: its title with how many it shows, "Show all" past
    ROWS_SHOWN rows, the table. Each row's cells show 4 lines, then the row's own "Show all"
    (SCRIPT) in the row's foot, with its reason box behind "Add a reason" on the live page
    (`live`), or the person's reasons, read-only, in report.html."""
    why = f"Why your LLM-as-a-judge {judge} it"
    parts, own = parts or [], own or []
    words = {c["id"]: c["text"] for c in own}
    body = []
    for k, m in enumerate(rows):
        n = f"{key}-{k}"
        box = live and m.get("id") is not None
        foot = (_box(m, n, parts, own, left_out) if box
                else f'<p class="row-foot">{OPEN_ROW}{_said(m, parts, words)}</p>')
        extra = ' class="extra" hidden' if k >= ROWS_SHOWN else ""
        ht, question = _question(m)
        ht = f' class="{ht.strip()}"' if ht else ""
        body.append(f'<tr{extra}>'
                    f'<td data-label="Question"{ht}>{question}</td>'
                    f'<td data-label="Answer" id="a-{n}">'
                    f'{_answer(m["answer"], (m.get("why") or {}).get("spans"))}</td>'
                    f'<td data-label="{why}">{_e(m.get("reason") or "No reason given")}</td>'
                    f'<td colspan="3" class="why-cell">{foot}</td></tr>')
    more = (f'<button type="button" class="more" aria-expanded="false" data-n="{len(rows)}" '
            f'aria-controls="t-{key}">Show all {len(rows)}</button>'
            if len(rows) > ROWS_SHOWN else "")
    return (f'<section class="group band" aria-labelledby="g-{key}"><div class="gh">'
            f'<h2 id="g-{key}">{said} ({len(rows)})</h2>{more}</div>'
            f'<table class="tbl" id="t-{key}"><colgroup><col class="c1"><col class="c2">'
            '<col class="c3"></colgroup><thead><tr><th scope="col">Question</th>'
            f'<th scope="col">Answer</th><th scope="col">{why}</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></section>')


# In place of the lists when split.json can't be used, around the fix command
SPLIT_UNKNOWN = ("judgekeeper can't tell which answers are kept aside: run ", " to see why.")


def _groups(c: dict, fixing: dict | None, live: bool = False,
            mark: str | None = None, fix: str | None = None,
            fix_command: str | None = None) -> str:
    """The disagreements on the marks the person can see, in two groups (a group with none
    to show is left out), then a footnote: how many more are among the marks kept aside. On
    the live page, a line first: add a reason. In report.html, which can't save one, two lines last: to say why, run `mark`, and
    `fix` uses the reasons (`mark`, `fix`: the commands)."""
    from judgekeeper.start_label import SAY_WHY_FIX, say_why_run

    mistakes = (fixing or {}).get("mistakes") or []
    parts, own = (fixing or {}).get("parts") or [], (fixing or {}).get("own") or []
    out = []
    if (fixing or {}).get("split_unknown"):  # no list and no count: it can't say which
        return (f'<div class="band"><p class="add-why">{_e(SPLIT_UNKNOWN[0])}<code>'
                f'{_e(fix_command or "judgekeeper fix")}</code>{_e(SPLIT_UNKNOWN[1])}</p></div>')
    if live and mistakes:
        out.append(f'<div class="band"><p class="add-why">{_code_line(reasons.ADD)}</p></div>')
    kept = 0
    for key, said, judge in (("easy", "You said Fail, your LLM-as-a-judge said Pass", "pass"),
                             ("strict", "You said Pass, your LLM-as-a-judge said Fail", "fail")):
        rows = [m for m in mistakes if m.get("judge") == judge]
        kept += max(0, c[key] - len(rows))
        if rows:
            out.append(_group(key, said, "passed" if judge == "pass" else "failed", rows,
                              live, parts, own, (fixing or {}).get("left_out", 0)))
    if kept:
        out.append(f'<div class="band"><p class="note kept">* {kept} more '
                   f'{"is" if kept == 1 else "are"} kept aside to test a new rule fairly.</p></div>')
    if mistakes and not live and mark:
        tell = say_why_run(c["strict"] + c["easy"], mark)
        uses = f'<p class="add-why">{_code_line(SAY_WHY_FIX.format(fix=fix))}</p>' if fix else ""
        out.append(f'<div class="band"><p class="add-why">{_code_line(tell)}</p>{uses}</div>')
    return "".join(out)


def estimate(value, interval) -> tuple[str, str]:
    """An estimate and its range for More details: "about 57%", "37% and 74%", also while the
    range is too wide for a result (the headline says it is too early to tell). Too early to
    tell when there is no number yet. A range of no width (a judge that passes or fails every
    answer) is exact, with no "about". Ends that round to the same percent are shown with one
    decimal, never as one point."""
    if value is None or not interval or interval[0] is None or interval[1] is None:
        return "too early to tell", "–"
    lo, hi = interval
    if targets.width_word(interval) == "exact":
        return _pct(value), f"{_pct(lo)} and {_pct(hi)}"
    if _pct(lo) == _pct(hi):
        return f"about {_pct(value)}", f"{lo:.1%} and {hi:.1%}"
    return f"about {_pct(value)}", f"{_pct(lo)} and {_pct(hi)}"


def _weighted(r: dict) -> str:
    """Under the caption, when some answers are not marked: the estimates are worked out for
    them all (each mark weighed by its grade's share), so they can differ from the counts."""
    g = r.get("groups") or {}
    every = sum((g.get(k) or {}).get("pool") or 0 for k in ("pass", "fail"))
    marked = sum((g.get(k) or {}).get("labeled") or 0 for k in ("pass", "fail"))
    if not marked or marked >= every:
        return ""
    return (f'<span class="weighted">Worked out for all {every} answers, not only the {marked} '
            "you marked, so they can differ from the counts above.</span>")


def _details(r: dict) -> str:
    """More details: how often the judge agrees with the person, estimated (weighted, with
    their ranges), and kappa."""
    rows = []
    for said, key in (("Pass", "tpr"), ("Fail", "tnr")):
        est, between = estimate(r.get(key), r.get(f"{key}_interval"))
        rows.append((f"When you say {said}, your LLM-as-a-judge also says {said}", est, between))
    kappa, (lo, hi) = r.get("kappa"), (r.get("kappa_interval") or (None, None))
    tip = ('<span class="kappa">Kappa<button type="button" class="i" aria-describedby='
           '"kappa-tip" aria-expanded="false" aria-controls="kappa-tip" '
           'aria-label="What kappa means">ⓘ</button><span class="tip" '
           f'role="tooltip" id="kappa-tip">{_e(KAPPA_MEANS)}</span></span>')
    body = "".join(f'<tr><th scope="row">{_e(name)}</th><td data-label="Estimate">{_e(est)}</td>'
                   f'<td data-label="Between">{_e(between)}</td></tr>'
                   for name, est, between in rows)
    body += (f'<tr><th scope="row">{tip}</th><td data-label="Estimate">'
             f'{_two(kappa) if kappa is not None else "–"}</td><td data-label="Between">'
             f'{f"{_two(lo)} and {_two(hi)}" if lo is not None else "–"}</td></tr>')
    return ('<section class="details band" aria-labelledby="details-h">'
            '<h2 id="details-h">More details</h2><table class="panel">'
            "<caption>How often your LLM-as-a-judge agrees with you (estimates)"
            f"{_weighted(r)}</caption>"
            '<colgroup><col class="d1"><col class="d2"><col class="d3"></colgroup>'
            '<thead><tr><td></td><th scope="col">Estimate</th><th scope="col">Between</th>'
            f"</tr></thead><tbody>{body}</tbody></table></section>")


def _fix(r: dict) -> str:
    """Fix it: the command that saves the clues and the marked answers to grade again with a
    new rule, with Copy; the same steps as `judgekeeper fix`."""
    from judgekeeper.fix import ANSWERS, NEW_RESULTS

    fix = _e(commands(r)["fix"])
    saved = f"{FOLDER}/fix/"
    then = (f"It lists the answers your LLM-as-a-judge got wrong and saves them in {saved}, with "
            f"{ANSWERS}. Change your rule in your eval tool, grade those answers again, then run "
            f"<code>{fix} {_e(NEW_RESULTS)}</code> to test it on the marks kept aside.")
    return ('<section class="fix band" aria-labelledby="fix-h"><div class="fix-in">'
            '<h2 id="fix-h">Fix it</h2>'
            f"<p>In your project folder, run <code>{fix}</code>. {then}</p>"
            f'<div class="cmd"><code id="fix-cmd">{fix}</code><button type="button" '
            'class="copy" id="copy" data-copy="fix-cmd">Copy</button></div></div></section>')


def _last_check(last: dict | None, worse: str) -> str:
    """After a check found the new judge worse: that judge, "Worse", the counts and ranges the
    terminal gave, and the way back. The rest of the page stays the old judge's result."""
    if not last:
        return ""
    judge = "Your new LLM-as-a-judge" + (f" ({_e(last['judge'])})" if last.get("judge") else "")
    said = "".join(f"<p>{_e(x)}</p>" for x in last.get("lines") or [])
    return (f'<section class="band last-check" aria-labelledby="last-h"><h2 id="last-h">'
            f"Last check</h2><p>{judge}: <b>Worse</b>. The result below is still your old "
            f"LLM-as-a-judge's.</p>{said}<p>{_code_line(worse)}</p></section>")


def page(r: dict, back: str | None = None, fixing: dict | None = None,
         worse: str | None = None, last: dict | None = None) -> str:
    """The result page. `r`: the result; `back`: the link to the marking page while it runs
    (None in report.html); `fixing`: fix.report_section (the mistakes the person can see);
    `worse`: the next step after a check found the new judge worse, in place of the lead's
    and of Fix it; `last`: that check (check.last_check), said at the top. The page carries its Content-Security-Policy in a meta tag, so the saved
    copy keeps it too."""
    from judgekeeper.front import tool_name

    c = counts(r)
    judge = r.get("judge") or {}
    tool = tool_name(judge.get("tool"), judge.get("results_files"))
    model = (r.get("fingerprint") or {}).get("model")
    left = look.meta(_e(model) if model else None, _e(tool) if tool else None)
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    top = _last_check(last, worse) if worse else ""
    parts = [top, _verdict(r, c, back, worse, above=bool(top)), _counts(r, c), _made(r)]
    live = back is not None
    if shows_disagreements(r):  # real numbers: the disagreements and the estimates
        mark = None if live or worse else commands(r)["mark"]  # after Worse: one way out
        fix = None if next_step(r) == "mark" else commands(r)["fix"]  # never while too early
        parts += [_groups(c, fixing, live, mark, fix, commands(r)["fix"]), _details(r)]
    elif level is not None:  # too early to tell: the estimates and their ranges all the same
        parts.append(_details(r))
    if level == "not_gate" and not worse:
        parts.append(_fix(r))
    parts.append(held_note(r, "".join(parts)))
    meta = f'<meta http-equiv="Content-Security-Policy" content="{script_csp(live)}">\n'
    scripts = f"<script>{SCRIPT}</script>\n"
    if live and 'class="why"' in "".join(parts):
        scripts += f"<script>{REASONS_SCRIPT}</script>\n"
    return (look.head("judgekeeper: your result", STYLE, meta)
            + look.top(left, "") + '<main class="result">' + "".join(parts)
            + f"</main>\n{scripts}</body>\n</html>\n")
