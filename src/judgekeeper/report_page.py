"""The result page: what the marking page shows at /result, and `.judgekeeper/report.html`.

One self-contained page (look.py: nothing loaded from anywhere else); every string in it is
escaped. Its one script ("Show more", kappa's ⓘ and Copy) is fixed text: the page's Content-Security-Policy
lets exactly that run (by its hash) and nothing else, both when served and in the saved copy.

Served by the marking page (`back` given), each disagreement also asks why the person marked it
so (reasons.py), and a second fixed script (REASONS_SCRIPT) saves each change with POST /label;
only that page may connect back (LIVE_CSP). report.html shows the reasons read-only.

The marks kept aside are counted, never shown: fix.py keeps them to test a new rule fairly.
Which parts show depends on the result's level (targets.level): What next once there is a
result (the fix command only when the LLM-as-a-judge needs work), and only the counts before
there is a result (too_few). In an answer or a question only `**bold**` and "- " lines are
formatted (_rich); a row with a reason box keeps its answer as plain text, because the box
counts characters of it.
"""

from __future__ import annotations

import json
import re
from html import escape

from judgekeeper import batches, look, reasons, targets
from judgekeeper.judge_check import shown_reason
from judgekeeper.start_label import (
    BEST_SO_FAR,
    EARLY,
    GOOD,
    NARROW,
    NEEDS,
    TO_A_RESULT,
    VERDICTS,
)

ROWS_SHOWN = 3  # disagreements shown in a group before "Show N more"
KAPPA_MEANS = ("Kappa is agreement beyond coincidence. 0 means no better than coincidence, 1 "
               "means perfect agreement.")
STATES = {"gate": ("good", GOOD), "not_gate": ("needs", NEEDS), "check": ("plain", EARLY),
          "too_early": ("plain", EARLY), None: ("plain", EARLY)}
# The website's Copy button: a copy icon; after a copy, a green tick and "Copied" for 1.5 s.
COPY_ICONS = ('<svg class="i-copy" viewBox="0 0 16 16" aria-hidden="true" focusable="false" '
              'fill="none" stroke="currentColor" stroke-width="1.5"><rect x="5.5" y="5.5" '
              'width="8" height="8"/><path d="M10.5 5.5v-3h-8v8h3"/></svg><svg class="i-tick" '
              'viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="none" '
              'stroke="currentColor" stroke-width="2" stroke-linecap="square"><path '
              'd="M3 8.5l3.2 3.2L13 5"/></svg><span class="copied" aria-live="polite"></span>')

# The page's script: fixed text, so its hash can be in the Content-Security-Policy.
SCRIPT = """
  (function () {
    function each(list, f) { Array.prototype.forEach.call(list, f); }
    // A row's "Show more": only when one of its cells is longer than its 4 lines; a cut cell
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
    // Shut, a row or group whose top is above the screen comes back into view: the reader is
    // not left far below it.
    function backInView(box) {
      if (box && box.getBoundingClientRect().top < 0) { box.scrollIntoView({block: "start"}); }
    }
    each(document.querySelectorAll(".open-row"), function (b) {
      b.addEventListener("click", function () {
        var row = b.closest("tr"), open = !row.hasAttribute("data-open");
        if (open) { row.setAttribute("data-open", ""); } else { row.removeAttribute("data-open"); }
        b.setAttribute("aria-expanded", String(open));
        b.textContent = open ? "Show less" : "Show more";
        fit();
        if (!open) { backInView(row); }
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
        b.textContent = open ? "Show less" : "Show " + b.getAttribute("data-n") + " more";
        fit();
        if (!open) { backInView(b.closest("section") || table); }
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
    // Copy, as on the website: the command (never its "$"), a green tick and "Copied" for
    // 1.5 s; where the clipboard can't be used, the command is selected and copied, then the
    // selection is cleared. A copy that did not work says "Copy failed" instead.
    each(document.querySelectorAll("[data-copy]"), function (button) {
      var code = button.parentNode.querySelector("code"), said = button.querySelector(".copied"),
          timer;
      function done(ok) {
        button.classList.remove(ok ? "failed" : "done");
        button.classList.add(ok ? "done" : "failed");
        said.textContent = ok ? "Copied" : "Copy failed";
        clearTimeout(timer);
        timer = setTimeout(function () {
          button.classList.remove("done");
          button.classList.remove("failed");
          said.textContent = "";
        }, 1500);
      }
      function select() {
        var range = document.createRange(), sel = window.getSelection(), ok = false;
        range.selectNodeContents(code);
        sel.removeAllRanges();
        sel.addRange(range);
        try { ok = document.execCommand("copy") === true; } catch (e) { /* nothing more to try */ }
        sel.removeAllRanges();
        done(ok);
      }
      button.addEventListener("click", function () {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code.textContent).then(function () { done(true); }, select);
        } else {
          select();
        }
      });
    });
  })();
"""
# The live page's second script: the reason boxes. Each change is saved at once (the "Other…"
# box when typing pauses, on Enter and when it is left); the token is the page's own.
REASONS_SCRIPT = """
  (function () {
    var token = new URLSearchParams(location.search).get("token") || "", MAX = __MAX__,
        PAUSE = 1500;
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
          sent = input.value, timer = null, pick = null;
      function body() {
        var taps = Array.prototype.filter.call(box.querySelectorAll("[aria-pressed]"), on);
        return {id: box.getAttribute("data-id"),
                reasons: taps.filter(function (b) { return b.hasAttribute("data-reason"); })
                  .map(function (b) { return b.getAttribute("data-reason"); }),
                rule_parts: taps.filter(function (b) { return b.hasAttribute("data-part"); })
                  .map(function (b) { return Number(b.getAttribute("data-part")); }),
                spans: spans, note: input.value};
      }
      // "Change" and "Your reason: ..." from what is saved, or "Add a reason".
      function line() {
        var taps = Array.prototype.filter.call(box.querySelectorAll("[aria-pressed]"), on);
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
        said.querySelector(".said-words").textContent = words.join("; ");
        // the whole rule parts on hover, when one is cut
        if (whole.join() !== words.join()) { said.title = "Your reason: " + whole.join("; "); }
        else { said.removeAttribute("title"); }
        now.hidden = !words.length;
        add.textContent = words.length ? "Change" : "Add a reason";
      }
      // Opening the reason box opens its row too: the whole answer shows while you pick.
      add.addEventListener("click", function () {
        var open = add.getAttribute("aria-expanded") !== "true", row = box.querySelector(".open-row");
        add.setAttribute("aria-expanded", String(open));
        document.getElementById(add.getAttribute("aria-controls")).hidden = !open;
        if (open && row && !row.hidden && row.getAttribute("aria-expanded") !== "true") {
          row.click(); }
      });
      // A reason picked, or typed and Enter pressed: the box closes, the line shows it.
      function shut() {
        add.setAttribute("aria-expanded", "false");
        document.getElementById(add.getAttribute("aria-controls")).hidden = true;
        add.focus();
      }
      function send(close) {
        clearTimeout(timer); sent = input.value; saved.textContent = "";
        window.fetch("/label?token=" + encodeURIComponent(token), {method: "POST",
          headers: {"Content-Type": "application/json"}, body: JSON.stringify(body())})
          .then(function (r) {
            if (r.ok) { saved.textContent = "Saved"; line(); if (close) { shut(); } return; }
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
      each(box.querySelectorAll("[aria-pressed]"), function (b) {
        b.addEventListener("click", function () {
          b.setAttribute("aria-pressed", String(!on(b))); send(true); });
      });
      other.addEventListener("click", function () {
        var open = other.getAttribute("aria-expanded") !== "true";
        other.setAttribute("aria-expanded", String(open));
        document.getElementById(other.getAttribute("aria-controls")).hidden = !open;
        if (open) { input.focus(); }
      });
      // Saved once typing pauses, on Enter and on leaving the box: never a half-typed word.
      input.addEventListener("input", function () {
        clearTimeout(timer); timer = setTimeout(send, PAUSE);
      });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          if (input.value !== sent) { send(true); } else { shut(); }
        }
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
:root { --pad: 56px; --bar: #14171c; }
/* the website's focus ring, in the text colour */
:focus-visible { outline: 2px solid var(--text); outline-offset: 3px; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; }
.mono { font-family: var(--mono); font-weight: 500; white-space: nowrap;
  font-variant-ligatures: none; }
.term { white-space: nowrap; }
.off { color: var(--amber); }
/* Pass and Fail, calmer than the marking page's buttons */
.w-pass { color: #5cc99b; }
.w-fail { color: #ef7a7e; }
/* a command in a sentence: the website's code chip */
main p code, .notes-list code { font-size: .9em; color: var(--text);
  background: rgba(255,255,255,.06); border-radius: 4px; padding: 2px 6px;
  -webkit-box-decoration-break: clone; box-decoration-break: clone; }
.verdict { padding: 60px 40px 52px; text-align: center; }
.verdict h1 { margin: 0 auto; font-size: clamp(34px, 3.2vw, 48px); line-height: 1.1;
  letter-spacing: -.02em; font-weight: 800; max-width: 24ch; text-wrap: balance; }
.verdict h1.needs { color: var(--amber); }
.verdict h1.good { color: var(--green); }
.verdict h1.plain { color: var(--text); }
.lead { margin: 20px auto 0; font-size: 20px; line-height: 1.4; color: var(--muted); }
.lead b { font-family: var(--mono); font-weight: 500; font-size: 18px; color: var(--text); }
.lead b.off { color: var(--amber); }
.lead a { color: var(--text); text-decoration: underline; text-decoration-color: var(--muted);
  text-underline-offset: 3px; }
.lead a:hover { text-decoration-color: var(--text); }
.file { overflow-wrap: anywhere; }  /* a file name with no break in it wraps, also on a phone */
/* every section: edge to edge, a lit heading bar, then its content */
.sec { border-top: 1px solid var(--line); }
.sh, .gh, .h-head { background: var(--bar); border-bottom: 1px solid var(--line);
  padding: 26px var(--pad) 24px; text-align: center; }
.sh h2, .gh h2, .h-head h2 { margin: 0; font-size: 26px; font-weight: 800;
  letter-spacing: -.015em; line-height: 1.25; color: var(--text); }
.kept { margin: 8px auto 0; font-size: 16px; color: var(--muted); max-width: 70ch;
  text-align: center; }
.sec.slim { margin: 0; padding: 22px var(--pad); text-align: center; font-size: 16px;
  color: var(--muted); }
/* the score: the three numbers side by side, big, then your two counts */
.nums { display: grid; grid-template-columns: 1fr 1fr 1fr; }
.cell { padding: 32px 32px 34px; text-align: center; display: flex; flex-direction: column;
  align-items: center; gap: 10px; }
.cell + .cell { border-left: 1px solid var(--line); }
.n-lab { font-size: 17px; line-height: 1.45; color: var(--muted); max-width: 30ch; }
.n-val { font-family: var(--sans); font-weight: 700; font-size: 58px;
  font-variant-numeric: tabular-nums; line-height: 1.05; color: var(--text);
  letter-spacing: -.02em; }
.n-val .about { font-size: 22px; font-weight: 600; color: var(--muted); margin-right: 4px;
  letter-spacing: 0; vertical-align: middle; }
.n-rng { font-size: 16px; color: var(--muted); }
.kappa { position: relative; display: inline-block; }
.kappa .i { font-size: 15px; color: var(--muted); margin-left: 6px; line-height: 1;
  min-width: 24px; min-height: 24px; }
.kappa .tip { position: absolute; left: 50%; transform: translateX(-50%);
  bottom: calc(100% + 8px); width: min(320px, 80vw); background: var(--bg);
  border: 1px solid var(--line); padding: 10px 12px; font-family: var(--sans); font-size: 13px;
  font-weight: 500; line-height: 1.45; letter-spacing: 0; text-transform: none;
  text-align: left; color: var(--text); white-space: normal; display: none; z-index: 2; }
.kappa .i[aria-expanded="true"] + .tip, .kappa .i:focus-visible:not([data-shut]) + .tip {
  display: block; }
@media (hover: hover) { .kappa:hover .tip { display: block; } }
.cnts { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--line); }
.cnts p { margin: 0; padding: 24px 32px; text-align: center; font-size: 19px; font-weight: 700;
  line-height: 1.4; }
.cnts p + p { border-left: 1px solid var(--line); }
.c-main, .c-sub { display: block; }
.c-sub { margin-top: 4px; font-size: 17px; font-weight: 500; color: var(--muted);
  line-height: 1.5; text-wrap: balance; }
.c-sub .mono { color: var(--text); }
.c-sub .mono.off { color: var(--amber); }
.foot { margin: 0; padding: 16px 32px; border-top: 1px solid var(--line); text-align: center;
  font-size: 16px; color: var(--muted); }
/* a row's "Show more": a quiet link */
.open-row { font-size: 14px; color: var(--muted); text-decoration: underline;
  text-decoration-color: var(--faint); text-underline-offset: 3px; white-space: nowrap; }
.open-row:hover, .open-row:focus-visible { color: var(--text); }
/* a group's "Show N more": a full-width row under its table */
.more { display: block; width: 100%; padding: 18px var(--pad);
  border-top: 1px solid var(--line); text-align: center; font-size: 16px; font-weight: 600;
  color: var(--muted); }
.more:hover { color: var(--text); background: var(--hover); }
.tbl { margin: 0; padding: 8px var(--pad) 0; table-layout: fixed; }
.tbl col.c1 { width: 28%; } .tbl col.c2 { width: 44%; } .tbl col.c3 { width: 28%; }
.tbl.no-reason col.c2 { width: 72%; }
/* the small labels: the marking page's .label */
.tbl th { font-family: var(--sans); font-size: 12px; font-weight: 600;
  letter-spacing: .1em; text-transform: uppercase; color: var(--faint); text-align: left;
  border-bottom: 1px solid var(--line); padding: 0 32px 14px 0; }
.tbl td { font-size: 17px; line-height: 1.55; padding: 24px 32px 24px 0; vertical-align: top;
  border-bottom: 1px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
.tbl th:last-child, .tbl td:last-child { padding-right: 0; }
/* the last row shown: "Show N more" or the next section draws the line under it */
.tbl tbody tr:last-child, .tbl tbody tr:has(+ tr[hidden]) { border-bottom: 0; }
.tbl td[data-label]:nth-child(3) { color: var(--muted); }
/* a row's foot: its button first (the website's small bordered button), the reason saved,
   "Show more" at the right */
.why-line, .row-foot { display: flex; align-items: center; gap: 14px; min-width: 0;
  min-height: 32px; font-size: 14px; color: var(--muted); }
.open-row { margin-left: auto; padding: 3px 0; flex: none; }
.sbtn { display: inline-flex; align-items: center; height: 32px; padding: 0 12px;
  border: 1px solid var(--line); border-radius: 4px; font-size: 14px; font-weight: 600;
  color: var(--text); white-space: nowrap; flex: none; }
.sbtn:hover { background: var(--hover); }
.sbtn[aria-expanded="true"] { border-color: var(--muted); }
.said-now { display: flex; min-width: 0; }
.said-text, .said { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.said-text b, .said b { color: var(--text); font-weight: 600; }
.why-body { margin-top: 16px; padding: 4px 0 6px 18px; border-left: 2px solid var(--line); }
.tbl td[data-label] { border-bottom: 0; padding-bottom: 10px; }
.tbl td.why-cell { white-space: normal; padding-top: 0; color: var(--text); }
/* a row foot with nothing in it takes no room */
.tbl td.why-cell:not(:has(button:not([hidden]), a, .why-body, .said, .why)) { display: none; }
.row-foot, .why-line { margin: 14px 0 0; }
/* the text as written: no font ligature turns -> into an arrow */
.tbl td[data-label], .said, .why { font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }
.q-peek, .q-gap { display: none; }
.q-full, .q-end { display: block; }
.fname { display: block; font-family: var(--mono); font-size: 11px; font-weight: 400;
  letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-bottom: 2px; }
b.hl { font-weight: 800; color: var(--text); text-decoration: underline;
  text-decoration-color: var(--amber); text-decoration-thickness: 2px;
  text-underline-offset: 3px; }
/* the reason box: its question with "Saved" beside it, the everyday reasons, then the
   rule's parts as light checkbox rows */
.box-h { display: flex; align-items: baseline; gap: 16px; margin: 0 0 12px; }
.why .q { margin: 0; font-size: 15px; font-weight: 700; }
.why .sub { margin: 18px 0 6px; font-size: 14px; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font-size: 14px; line-height: 1.35; padding: 7px 12px; border: 1px solid var(--line);
  border-radius: 4px; color: var(--muted); text-align: left; max-width: 100%;
  overflow-wrap: anywhere; }
.chip:hover { color: var(--text); background: var(--hover); }
.chip[aria-pressed="true"] { color: var(--bg); background: var(--text);
  border-color: var(--text); }
.parts { display: grid; max-width: 820px; }
.part { display: grid; grid-template-columns: 16px 18px minmax(0, 1fr); gap: 10px;
  align-items: center; padding: 6px 8px; margin-left: -8px; border-radius: 4px;
  font-size: 14px; color: var(--muted); text-align: left; }
.part:hover { background: var(--hover); color: var(--text); }
.part .bx { width: 14px; height: 14px; border: 1.5px solid var(--faint); border-radius: 3px; }
.part[aria-pressed="true"] { color: var(--text); }
.part[aria-pressed="true"] .bx { background: var(--text); border-color: var(--text);
  box-shadow: inset 0 0 0 2px var(--bg); }
.part .num { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.part .t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.other[aria-expanded="true"] { color: var(--text); border-color: var(--text); }
.other-box { margin-top: 12px; display: grid; gap: 6px; max-width: 640px; }
.other-box label { font-size: 13px; color: var(--muted); }
.other-box input { font: inherit; font-size: 15px; color: var(--text); background: var(--bg);
  border: 1px solid var(--faint); padding: 10px 12px; width: 100%; }
.marked { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center;
  gap: 8px 16px; min-height: 24px; }
.mark-part, .clear-part { font-size: 14px; text-decoration: underline;
  text-underline-offset: 3px; }
.saved { font-size: 13px; color: var(--muted); }
/* a field the same in every row (an agent's prompt), once above the lists, folded */
.same { margin: 0; }
.same summary { list-style: none; cursor: pointer; display: flex; align-items: baseline;
  gap: 14px; color: var(--muted); font-size: 15px; }
.same summary::-webkit-details-marker { display: none; }
.same summary::before { content: ""; width: 7px; height: 7px; flex: none;
  border-right: 1.5px solid var(--muted); border-bottom: 1.5px solid var(--muted);
  transform: rotate(-45deg) translateY(-2px); }
.same[open] summary::before { transform: rotate(45deg) translateY(-4px); }
.same summary .fname { margin: 0; }
.same p { margin: 14px 0 0; font-size: 17px; line-height: 1.55; white-space: pre-wrap;
  overflow-wrap: anywhere; }
/* bold and a list in an answer or a question: only these two */
.tbl td ul { margin: 6px 0; padding-left: 1.3em; white-space: normal; }
.tbl td li { margin: 2px 0; }
.tbl td strong { font-weight: 700; }
/* What next: where your marks are kept, the command beside it, the notes under both */
.nx-split { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: auto 1fr;
  grid-template-areas: "lead act" "more act"; }
.nx-split > div { padding: 32px var(--pad) 0; display: flex; flex-direction: column; gap: 16px;
  align-items: flex-start; min-width: 0; }
.a-lead { grid-area: lead; }
.a-more { grid-area: more; padding-top: 16px !important; }
.nx-split > div:last-child, .nx-split > .a-act { padding-bottom: 36px; }
.a-act { grid-area: act; border-left: 1px solid var(--line); }
.nx-split p { margin: 0; font-size: 17px; line-height: 1.6; color: var(--muted); }
.nx-split p, .notes-list li { text-align: justify; hyphens: auto; -webkit-hyphens: auto; }
.nx-split p.small { font-size: 16px; }
.nx-split a { color: var(--text); }
.nx-notes { padding: 24px var(--pad) 32px; border-top: 1px solid var(--line); }
.notes-list { margin: 0; padding: 0; list-style: none; display: block; columns: 2;
  column-gap: 72px; }
.notes-list li { position: relative; padding-left: 18px; margin-bottom: 12px;
  break-inside: avoid; font-size: 16px; line-height: 1.55; color: var(--muted); }
.notes-list li::before { content: ""; position: absolute; left: 2px; top: .7em; width: 6px;
  height: 6px; border-radius: 50%; background: var(--faint); }
/* after a check found the new LLM-as-a-judge worse: that check, above the verdict */
.last-check { padding: 28px var(--pad) 30px; text-align: center;
  border-bottom: 1px solid var(--line); }
.last-check h2 { margin: 0 0 6px; font-size: 24px; font-weight: 800; }
.last-check p { max-width: 90ch; margin: 10px auto 0; font-size: 16px; line-height: 1.6;
  color: var(--muted); }
.last-check .lc-top { color: var(--text); font-size: 17px; }
/* the command box with Copy: the same as the website's; the "$" is drawn, never copied */
.cmd { display: inline-grid; grid-template-columns: minmax(0, 1fr) auto;
  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; max-width: 100%;
  min-width: min(380px, 100%); background: #07080a; }
.nx-split .cmd { min-width: 0; width: 100%; max-width: 640px; }
.nx-split .cmd code { font-size: 18px; padding: 18px 22px; }
.nx-split .cmd .copy { padding: 0 22px; }
.cmd code { display: block; align-self: center; padding: 12px 18px; font-size: 15px;
  white-space: nowrap; overflow-x: auto; color: var(--text); font-variant-ligatures: none; }
.cmd code::before { content: "$"; margin-right: .6em; color: var(--green); }
.cmd .copy { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  min-width: 50px; padding: 0 16px; border-left: 1px solid var(--line); color: var(--muted); }
.cmd .copy:hover { color: var(--text); background: var(--hover); }
.cmd .copy:focus-visible { outline-offset: -2px; border-radius: 0; }
.cmd .copy.done { color: var(--green); }
.cmd .copy svg { width: 16px; height: 16px; flex: none; }
.cmd .i-tick, .cmd .copy.done .i-copy { display: none; }
.cmd .copy.done .i-tick { display: block; }
.cmd .copied { display: none; font-family: var(--mono); font-variant-ligatures: none;
  font-size: 12.5px; font-weight: 500; white-space: nowrap; }
.cmd .copy.done .copied { display: inline; }
.cmd .copy.failed .copied { display: inline; }
@media (min-width: 721px) {
  .tbl, .tbl thead, .tbl tbody { display: block; }
  .tbl colgroup { display: none; }
  .tbl tr { display: grid; grid-template-columns: 26fr 46fr 28fr; column-gap: 48px;
    border-bottom: 1px solid var(--line); }
  .tbl.no-reason tr { grid-template-columns: 1fr 1fr; column-gap: 56px; }
  .tbl th, .tbl td { display: block; padding: 0; border-bottom: 0; }
  .tbl thead th { padding: 18px 0 14px; }
  .tbl tbody tr { padding: 24px 0; }
  .tbl td[data-label] { font-size: 17px; line-height: 1.55; max-height: calc(4 * 1.55em);
    overflow: hidden; }
  .tbl td[data-label].cut { -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 1.5em), transparent); mask-image: linear-gradient(to bottom, #000 calc(100% - 1.5em), transparent); }
  .tbl tr[data-open] td[data-label] { max-height: none; overflow: visible; }
  .tbl td.ht { max-height: calc(5 * 1.55em); }
  .tbl tr:not([data-open]) td.ht .q-peek, .tbl tr:not([data-open]) td.ht .q-end {
    display: block; max-height: calc(2 * 1.55em); overflow: hidden; }
  .tbl tr:not([data-open]) td.ht .q-gap { display: block; font-size: 13px; letter-spacing: .3em;
    color: var(--muted); }
  .tbl tr:not([data-open]) td.ht .q-full { display: none; }
  .tbl tr:not([data-open]) td.ht .q-end { display: flex; flex-direction: column;
    justify-content: flex-end; }
  .tbl td.why-cell { grid-column: 1 / -1; }
  .tbl td[data-label], .tbl td.why-cell { padding-bottom: 0; border-bottom: 0; }
}
@media (max-width: 1100px) {
  :root { --pad: 36px; }
  .n-val { font-size: 46px; }
  .tbl tr { column-gap: 32px; }
}
@media (max-width: 860px) {
  .nums, .cnts { grid-template-columns: 1fr; }
  .cell + .cell, .cnts p + p { border-left: 0; border-top: 1px solid var(--line); }
  .nx-split { grid-template-columns: 1fr; grid-template-rows: auto;
    grid-template-areas: "lead" "act" "more"; }
  .a-act { border-left: 0; }
  .notes-list { columns: 1; }
}
@media (max-width: 720px) {
  :root { --pad: 16px; }
  .verdict { padding: 48px var(--pad) 40px; }
  .lead { font-size: 17px; }
  .sh h2, .gh h2, .h-head h2 { font-size: 22px; }
  .tbl thead { display: none; }
  .tbl, .tbl tbody, .tbl tr, .tbl td { display: block; }
  .tbl tr { padding: 18px 0; border-bottom: 1px solid var(--line); }
  .tbl td { border: 0; padding: 0; font-size: 16px; }
  .tbl td + td { margin-top: 10px; }
  .tbl td.why-cell { margin-top: 0; }
  .tbl td::before { content: attr(data-label); display: block; font-family: var(--mono);
    font-size: 13px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted);
    margin-bottom: 3px; }
  .tbl td[data-label], .tbl td.why-cell { padding-bottom: 0; border-bottom: 0; }
  .tbl td.why-cell::before { content: none; }
  .cmd { display: grid; width: 100%; min-width: 0; }
  .cmd code { padding: 12px 14px; }
  .kappa .tip { font-size: 15px; }
}
@media (max-width: 720px), (pointer: coarse) {
  .kappa .i { font-size: 18px; padding: 13px 14px; margin: -13px -14px -13px -8px; }
}
@media (max-width: 300px) {
  .cmd { grid-template-columns: 1fr; }
  .cmd .copy { border-left: 0; border-top: 1px solid var(--line); min-height: 48px; }
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
    them: `mark` keeps every flag, as the terminal's does, `run` every flag but --port,
    `check` and `fix` the path only, `more` (start_label.mark_command) the flags that read
    results. On Windows a value no quotes keep as text shows as NAME (said by held_note)."""
    from judgekeeper.start import command_from, saved_flags
    from judgekeeper.start_label import mark_command

    flags = saved_flags(r.get("flags"))
    mark = command_from(flags, "mark", kept=True)  # with the port the terminal names
    flags.pop("port", None)
    path = {"path": flags.get("path", ".")}
    run = command_from(flags, kept=True)
    return {"run": run, "mark": mark,
            "check": command_from(path, "check", kept=True),
            "fix": command_from(path, "fix", kept=True), "more": mark_command(run)}


def held_note(r: dict, shown: str) -> list[str]:
    """When a command in `shown` (the page's parts) shows NAME, on Windows: each value the
    commands show as NAME, as data, for the notes."""
    from judgekeeper.start import held_values
    from judgekeeper.textio import PLACEHOLDER

    if not re.search(rf"\b{PLACEHOLDER}\b", shown):
        return []
    return [f'<code>{_e(f"{PLACEHOLDER}: {v}")}</code>' for v in held_values(r.get("flags"))]


def next_step(r: dict) -> str | None:
    """What comes after this result, the same in the terminal and on this page: "fix" when
    the judge needs work, None when it is good enough, else "mark" (too early to tell)."""
    level = r.get("verdict_level") if r["check"] != "too_few" else None
    return "fix" if level == "not_gate" else None if level == "gate" else "mark"


def shows_disagreements(r: dict) -> bool:
    """Whether the page lists the disagreements (and the estimates): whenever there is a
    result, too early to tell too, from ROUGH marks of each kind (when the hidden marks are
    set aside, fix.prepare_split: a judge of one grade has a result before that)."""
    from judgekeeper.targets import ROUGH

    labels = r.get("labels") or {}
    return r["check"] != "too_few" and min(labels.get("correct", ROUGH),
                                           labels.get("wrong", ROUGH)) >= ROUGH


def _all_marked(r: dict) -> str:
    """start_label.all_marked_lines as one paragraph, its command as code."""
    from judgekeeper.start_label import all_marked_lines, graded

    first, then = all_marked_lines(r["labels"], commands(r)["more"], graded(r))
    return f"{_e(first)} {_code_line(then.removeprefix('Next: '))}"


def _code_line(text: str) -> str:
    """A next step as a sentence: its first letter in capitals, each `command` as code."""
    parts = text.split("`")
    out = "".join(f"<code>{look.command(_e(x))}</code>" if i % 2 else _term(x)
                  for i, x in enumerate(parts))
    return out[:1].upper() + out[1:]


def disagreed(c: dict) -> str:
    """How many answers the person and the judge disagreed on, as the terminal says it
    (front.agreement_lines), the numbers in bold, the disagreements in amber."""
    d, n = c["strict"] + c["easy"], c["passed"] + c["failed"]
    if not d:
        what = "the one answer" if n == 1 else f"all <b>{n}</b> answers"
        return f"You and your {TERM} agreed on {what}."
    return f'You and your {TERM} disagreed on <b class="off">{d}</b> of <b>{n}</b> answers.'


def _verdict(r: dict, c: dict, back: str | None, worse: str | None = None,
             above: bool = False) -> str:
    """The headline, and under it the disagreements, for every result, as in the terminal;
    then, too early to tell, how to mark more: a link to the marking page while it runs, the
    command in the saved copy; with every answer marked, what comes next
    (start_label.all_marked_lines). After a check found the new judge worse, the next step
    that check gave (`worse`), unless the Last check block `above` gives it."""
    from judgekeeper.start_label import all_labeled, next_only_skipped, only_skipped

    level = r.get("verdict_level") if r["check"] != "too_few" else None
    cls, headline = STATES.get(level, STATES[None])
    if level is None and not all_labeled(r):  # before a result: what the terminal says
        headline = VERDICTS[None]
    if worse:
        then = "" if above else _code_line(worse)
    elif cls != "plain" or r.get("only_wait"):  # no mark counts now: the wait line says it
        then = ""
    elif all_labeled(r):
        then = _all_marked(r)
    elif r.get("only_skipped"):  # the headline is too early to tell: the rest of the line
        n = r["only_skipped"]
        then = (f"{_e(only_skipped(n))} "
                f"{_code_line(next_only_skipped(n, commands(r)['more']))}")
    elif back:
        then = (f'<a href="{_e(back)}">{_e(TO_A_RESULT)}</a>' if level is None else
                f'{_e(BEST_SO_FAR)} <a href="{_e(back)}">'
                f'{_e(NARROW if shows_range(r) else TO_A_RESULT)}</a>')
    else:
        then = f"Run <code>{look.command(_e(commands(r)['mark']))}</code> to mark more answers."
    lead = " ".join(x for x in (disagreed(c) if level is not None else "", then) if x)
    from judgekeeper.labels import gate_line

    gate = gate_line(r.get("import_gate"), r.get("imported"))  # imported marks, unchecked
    gate = f'<p class="lead">{_files(_term(gate), r)}</p>' if gate else ""
    written = "".join(f'<p class="lead">{_term(x.strip())}</p>'  # as `check` said it
                      for x in r.get("written_from") or [])
    written += waiting_html(r)
    return (f'<section class="verdict" aria-labelledby="verdict-h"><h1 id="verdict-h" '
            f'class="{cls}">{_term(headline)}</h1>{written}{gate}<p class="lead">{lead}</p>'
            "</section>")


def waiting_html(r: dict) -> str:
    """The marks that wait (batches.graded) and how to count them, as Measure says it; with
    none waiting but no answer left that a mark counts on (only_wait), that, and how to mark
    more."""
    from judgekeeper.check import WAIT, WAIT_COUNT, WAIT_GROUP, WAIT_MORE, no_grade_left

    k = r.get("waiting")
    if not k and not r.get("only_wait"):
        return ""
    from judgekeeper import textio

    command = r.get("waiting_check") or "judgekeeper check"  # named plainly (result.json)
    typed = textio.program("check")  # report.html: plainly too; the live page: its own
    with textio.plainly():
        plain = textio.program("check")
    if typed != plain and command.startswith(f"{plain} "):
        command = typed + command[len(plain):]
    run = f"run <code>{look.command(_e(command))}</code>"
    first, then = ((WAIT.format(k=k), WAIT_COUNT) if k
                   else (no_grade_left(r), WAIT_GROUP if r.get("wait_group") else WAIT_MORE))
    if k and r.get("wait_group"):  # and the group no mark can move
        first = f"{first} {no_grade_left(r)}"
    count = _term(then.format(run="\0")).replace("\0", run)
    return f'<p class="lead">{_term(first)} {count}</p>'


TERM = '<span class="term">LLM-as-a-judge</span>'


def _term(text: str) -> str:
    """`text` escaped, "LLM-as-a-judge" kept on one line wherever it is."""
    return _e(text).replace("LLM-as-a-judge", TERM)


def _files(html: str, r: dict) -> str:
    """`html` with each file the marks were imported from in a span that may wrap anywhere,
    so a long name with no break in it stays on the page."""
    names = sorted({_e(x) for x in (r.get("imported") or {}).get("from") or []
                    if isinstance(x, str) and x}, key=len, reverse=True)
    if not names:
        return html
    return re.sub("|".join(map(re.escape, names)),
                  lambda m: f'<span class="file">{m.group(0)}</span>', html)


def count_line(did: str, n: int, judge_passed: int, judge_failed: int) -> str:
    """"You passed 15 answers." and, on its own line, "Of these, your LLM-as-a-judge passed 7
    and failed 8.", numbers in mono, "passed" and "failed" in Pass and Fail colours; where it
    went the other way from you (failed what you passed, passed what you failed), amber above
    0."""
    def mono(x: int, off: bool = False) -> str:
        return f'<span class="mono{" off" if off and x else ""}">{x}</span>'
    return (f'<span class="c-main">You {_verb(did)} {mono(n)} '
            f'{"answer" if n == 1 else "answers"}.</span> <span class="c-sub">Of these, your '
            f"{TERM} passed "
            f"{mono(judge_passed, did == 'failed')} and failed "
            f"{mono(judge_failed, did == 'passed')}.</span>")


def own_line(did: str, n: int) -> str:
    """"You passed 15 answers.", the number in mono: before a result, the person's own count
    only, so marking an answer and taking it back never shows the judge's grade on it."""
    return f'You {_verb(did)} <span class="mono">{n}</span> {"answer" if n == 1 else "answers"}.'


def _verb(did: str) -> str:
    """"passed" or "failed" in the colour of the marking page's Pass or Fail button."""
    return f'<span class="w-{did.removesuffix("ed")}">{did}</span>'


def no_grade_line(r: dict) -> str | None:
    """How many answers the judge gave no Pass or Fail on, left out; None when it graded
    every one. Under the counts here, and under the result line in the terminal."""
    from judgekeeper.judge_check import NO_DECISION

    block = r.get("judge_check") or {}
    none = sum(int(block.get(k) or 0) for k in NO_DECISION)
    if not none:
        return None
    return (f"Your LLM-as-a-judge gave no Pass or Fail on {_plural(none, 'answer', 'answers')}. "
            f"{'It is' if none == 1 else 'They are'} left out.")


def _counts(r: dict, c: dict) -> str:
    """The two counts side by side (before a result, the person's own only), under the
    numbers."""
    if r["check"] == "too_few":
        lines = [own_line("passed", c["passed"]), own_line("failed", c["failed"])]
    else:
        lines = [count_line("passed", c["passed"], c["passed"] - c["strict"], c["strict"]),
                 count_line("failed", c["failed"], c["easy"], c["failed"] - c["easy"])]
    return (f'<div class="cnts"><p class="c-pass">{lines[0]}</p>'
            f'<p class="c-fail">{lines[1]}</p></div>')


def _notes(r: dict) -> list[str]:
    """The small notes, said once at the end next to What next: the answers left out (a newer
    batch, no grade), imported marks, second thoughts, and marks made too fast
    (start_label.quick_lines) or through a printed link (start_label.link_lines), as in the
    terminal."""
    from judgekeeper.labels import assumes_line, looks_off_line
    from judgekeeper.start_label import link_lines, quick_lines, second_thoughts

    out = [_term(x) for x in (batches.line(r.get("batches")), no_grade_line(r)) if x]
    assumes = assumes_line(r.get("imported"))  # marks brought with --labels
    off = looks_off_line(r.get("imports_off"), r.get("imported"))  # unlike the page marks
    thoughts = second_thoughts(r.get("made"), r.get("real_pass_rate"),
                               (r.get("tpr"), r.get("tnr")))
    out += [_files(_term(x), r) for x in [x for x in (assumes, off) if x] + thoughts]
    return out + [_term(x) for x in quick_lines(r.get("made"), r.get("imported"))
                  + link_lines(r.get("made"))]


OPEN_ROW = ('<button type="button" class="open-row" aria-expanded="false" hidden>Show more'
            '</button>')


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


def _question(m: dict, same: tuple = ()) -> tuple[str, str]:
    """A row's question cell (its class, its HTML): each field under its name when it has
    several (fix.py's "fields"), but those in `same`, shown once above the lists; a long text
    ending in a question folded to its first 2 lines, "…" and that question, the whole text
    in order when the row is open (SCRIPT, STYLE)."""
    fields = m.get("fields")
    if fields:
        return "", "\n".join(f'<span class="fname">{_e(k)}</span>{_rich(v)}' for k, v in fields
                             if k not in same)
    parts = head_tail(m["question"])
    if not parts:
        return "", _rich(m["question"])
    head, gap, tail = parts
    peek = "\n".join([line[:PEEK_CHARS] for line in head.split("\n") if line.strip()][:2])
    return " ht", (f'<span class="q-peek" aria-hidden="true">{_rich(peek)}</span>'
                   '<span class="q-gap" aria-hidden="true">…</span>'
                   f'<span class="q-full">{_rich(head + gap)}</span>'
                   f'<span class="q-end">{_rich(tail)}</span>')


BOLD = re.compile(r"\*\*(.+?)\*\*")


def _rich(text: str, spans=()) -> str:
    """Text for a cell: escaped first, then only `**bold**` as <strong> and lines that start
    with "- " as <ul><li>. Anything else stays text; a `**` never closed stays as stars. The
    words the person marked (`spans`, offsets in `text`) keep their <b class="hl">."""
    marks = reasons.merged(spans, len(text))

    def piece(a: int, b: int, bold: bool) -> str:
        out, at = [], a
        for s, e in marks:
            s, e = max(s, a), min(e, b)
            if e > s:
                out += [_e(text[at:s]), f'<b class="hl">{_e(text[s:e])}</b>']
                at = e
        html = "".join(out) + _e(text[at:b])
        return f"<strong>{html}</strong>" if bold else html

    def line(a: int, b: int) -> str:
        out, at = [], a
        for m in BOLD.finditer(text, a, b):
            out += [piece(at, m.start(), False), piece(m.start(1), m.end(1), True)]
            at = m.end()
        return "".join(out) + piece(at, b, False)

    blocks: list[tuple[str, list[str]]] = []
    pos = 0
    for ln in text.split("\n"):
        a, b = pos, pos + len(ln)
        pos = b + 1
        kind, html = ("ul", line(a + 2, b)) if ln.startswith("- ") else ("p", line(a, b))
        if blocks and blocks[-1][0] == kind:
            blocks[-1][1].append(html)
        else:
            blocks.append((kind, [html]))
    return "".join("\n".join(v) if k == "p" else
                   "<ul>" + "".join(f"<li>{x}</li>" for x in v) + "</ul>" for k, v in blocks)


def _answer(text: str, spans) -> str:
    """An answer, the words the person marked in bold."""
    out, at = [], 0
    for s, e in reasons.merged(spans, len(text)):
        out += [_e(text[at:s]), f'<b class="hl">{_e(text[s:e])}</b>']
        at = e
    return "".join(out) + _e(text[at:])


def _part_said(n: int, part: str, whole: bool = False) -> str:
    """A rule part in "Your reason: ...": its number, or with its text when `whole` (the
    line's title)."""
    return f"rule part {n} (\u201c{part}\u201d)" if whole else f"rule part {n}"


def _reason_said(k: str, own: dict[str, str]) -> str:
    return (reasons.lower(reasons.REASONS[k][0]) if k in reasons.REASONS
            else f"\u201c{own[k]}\u201d")


def _said_words(m: dict, parts: list[str], own: dict[str, str],
                whole: bool = False) -> list[str]:
    """The person's reasons on one answer, each as it reads in "Your reason: ...": the reasons
    tapped, the rule parts (each by its number, or `whole` for the line's title), the note."""
    why = m.get("why") or {}
    said = [_reason_said(k, own) for k in why.get("reasons") or []
            if k in reasons.REASONS or k in own]
    said += [_part_said(n, parts[n - 1], whole) for n in why.get("rule_parts") or []
             if 1 <= n <= len(parts)]
    if why.get("note"):
        said.append(f"\u201c{why['note']}\u201d")
    return said


def _whole_title(m: dict, parts: list[str], own: dict[str, str]) -> str:
    """A title with the whole "Your reason: ..." when a rule part is in it."""
    said, whole = _said_words(m, parts, own), _said_words(m, parts, own, whole=True)
    return f' title="{_e("Your reason: " + "; ".join(whole))}"' if whole != said else ""


def _said(m: dict, parts: list[str], own: dict[str, str]) -> str:
    """"Your reason: ..." for report.html, or nothing when the person gave none."""
    said = _said_words(m, parts, own)
    return (f'<span class="said"{_whole_title(m, parts, own)}>Your reason: '
            f'<b>{_e("; ".join(said))}</b></span>' if said else "")


def _chip(text: str, pressed: bool, attr: str, said: str = "", whole: str = "") -> str:
    whole = f' data-whole="{_e(whole)}"' if whole and whole != said else ""
    return (f'<button type="button" class="chip" aria-pressed="{str(pressed).lower()}" '
            f'{attr} data-said="{_e(said)}"{whole}>{_e(text)}</button>')


def _part(k: int, text: str, pressed: bool) -> str:
    """A rule part as a light checkbox row: box, number, one line of its text (cut by the
    page), the whole text in its title."""
    return (f'<button type="button" class="part" aria-pressed="{str(pressed).lower()}" '
            f'data-part="{k}" data-said="{_e(_part_said(k, text))}" '
            f'data-whole="{_e(_part_said(k, text, whole=True))}" title="{_e(text)}">'
            f'<span class="bx" aria-hidden="true"></span><span class="num">{k}</span>'
            f'<span class="t">{_e(text)}</span></button>')


def _box(m: dict, n: str, parts: list[str], own: list[dict], left_out: int = 0,
         asked: list[str] | None = None) -> str:
    """The row foot and reason box of one disagreement on the live page (`left_out`: the
    rule's parts with no button): "Add a reason" (or "Change" and the reason saved), "Show
    all" at the right; in the box, the everyday reasons first (`asked`, when not those
    reasons.offered gives for the judge's grade), then the rule's parts."""
    why = m.get("why") or {}
    taps, chosen = set(why.get("reasons") or []), set(why.get("rule_parts") or [])
    mark = "Fail" if m["final"] == "fail" else "Pass"
    words = {c["id"]: c["text"] for c in own}
    said = _said_words(m, parts, words)
    out = [(f'<div class="why" data-id="{_e(m["id"])}" data-answer="a-{n}" '
            f'data-len="{len(m["answer"])}" '
            f'data-spans="{_e(json.dumps(why.get("spans") or []))}" role="group" '
            f'aria-labelledby="q-{n}">'),
           (f'<p class="why-line"><button type="button" class="add-reason sbtn" '
            f'aria-expanded="false" aria-controls="wb-{n}">'
            f'{"Change" if said else "Add a reason"}</button><span class="said-now"'
            f'{"" if said else " hidden"}><span class="said-text"'
            f'{_whole_title(m, parts, words)}>Your reason: <b class="said-words">'
            f'{_e("; ".join(said))}</b></span></span>{OPEN_ROW}</p>'),
           f'<div class="why-body" id="wb-{n}" hidden>',
           (f'<div class="box-h"><p class="q" id="q-{n}">{_e(reasons.QUESTION.format(mark=mark))}'
            '</p><span class="saved" aria-live="polite"></span></div>')]
    chips = [_chip(reasons.REASONS[k][0], k in taps, f'data-reason="{k}"', _reason_said(k, words))
             for k in (reasons.offered(m["judge"]) if asked is None else asked)]
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
    if parts:
        out.append(f'<p class="sub" id="p-{n}">{_e(reasons.PART_QUESTION)}</p>'
                   f'<div class="parts" role="group" aria-labelledby="p-{n}">'
                   + "".join(_part(k, text, k in chosen) for k, text in enumerate(parts, 1))
                   + "</div>")
        if left_out:
            out.append(f'<p class="sub">{_e(reasons.parts_left_out_line(left_out))}</p>')
    out.append('<div class="marked"><button type="button" class="mark-part" hidden>Mark this '
               'part</button><button type="button" class="clear-part"'
               f'{"" if why.get("spans") else " hidden"}>Clear marked words</button></div>')
    return "".join(out) + "</div></div>"


def _group(key: str, said: str, rows: list[dict], kept: int, live: bool = False,
           parts: list[str] | None = None, own: list[dict] | None = None,
           left_out: int = 0, same: tuple = (), reasons_given: bool = True,
           asked: list[str] | None = None) -> str:
    """One group of disagreements: its title, how many more are kept aside (`kept`), the
    table (its REASON column only when an answer marked has a reason: `reasons_given`), then
    "Show N more" under it past ROWS_SHOWN rows. Each row's cells show 4 lines,
    then the row's foot: on the live page (`live`) its reason button and box, the reason
    saved, and the row's own "Show more" (SCRIPT) at the right; in report.html the person's
    reasons, read-only. `asked`: the reason buttons, when not the judge's (_box)."""
    parts, own = parts or [], own or []
    words = {c["id"]: c["text"] for c in own}
    third = (('<col class="c3">', f'<th scope="col">{REASON}</th>') if reasons_given
             else ("", ""))  # the REASON column's col and heading
    body = []
    for k, m in enumerate(rows):
        n = f"{key}-{k}"
        box = live and m.get("id") is not None
        foot = (_box(m, n, parts, own, left_out, asked) if box
                else f'<p class="row-foot">{_said(m, parts, words)}{OPEN_ROW}</p>')
        extra = ' class="extra" hidden' if k >= ROWS_SHOWN else ""
        ht, question = _question(m, same)
        ht = f' class="{ht.strip()}"' if ht else ""
        body.append(f'<tr{extra}>'
                    f'<td data-label="Question"{ht}>{question}</td>'
                    f'<td data-label="Answer" id="a-{n}">'
                    f'{(_answer if box else _rich)(m["answer"], (m.get("why") or {}).get("spans"))}</td>'
                    + (f'<td data-label="{REASON}">'
                       f'{_e(shown_reason(m.get("reason") or "") or "No reason given")}</td>'
                       if reasons_given else "")
                    + f'<td colspan="{3 if reasons_given else 2}" class="why-cell">{foot}</td></tr>')
    more = (f'<button type="button" class="more" aria-expanded="false" data-n="{len(rows) - ROWS_SHOWN}" '
            f'aria-controls="t-{key}">Show {len(rows) - ROWS_SHOWN} more</button>'
            if len(rows) > ROWS_SHOWN else "")
    return (f'<section class="sec group" aria-labelledby="g-{key}"><div class="gh">'
            f'<h2 id="g-{key}">{_colour(_term(said))}</h2>{_kept(kept)}</div>'
            f'<table class="tbl{"" if reasons_given else " no-reason"}" id="t-{key}"><colgroup>'
            f'<col class="c1"><col class="c2">{third[0]}</colgroup><thead><tr>'
            f'<th scope="col">Question</th><th scope="col">Answer</th>{third[1]}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>{more}</section>')


REASON = "Its reason"  # the third column: the LLM-as-a-judge's reason


def kept_line(n: int, of_these: bool = False) -> str:
    """How many more disagreements are kept aside, in words (the terminal says them too);
    `of_these`: under one group's list, so the count is that group's."""
    what = "of these" if of_these else "disagreement" if n == 1 else "disagreements"
    return (f'{n} more {what} {"is" if n == 1 else "are"} kept aside on purpose, so a new rule '
            "can be tested on answers you haven't looked at again.")


def _kept(n: int) -> str:
    """Under a group's heading: how many more of it are kept aside, in fewer words than the
    terminal's kept_line, or nothing."""
    if not n:
        return ""
    return f'<p class="kept">{n} more {"is" if n == 1 else "are"} kept aside to test your fix.</p>'


def _kept_after(n: int) -> str:
    """After the lists, for the groups with none to show: how many disagreements are kept
    aside, in the page's words (the terminal keeps kept_line)."""
    what = "disagreement is" if n == 1 else "disagreements are"
    return f"{n} more {what} kept aside to test your fix."


def _colour(html: str) -> str:
    """Pass and Fail in a heading, each in its own colour."""
    return re.sub(r"\b(Pass|Fail)\b",
                  lambda m: f'<span class="w-{m[1].lower()}">{m[1]}</span>', html)


def kept_count(c: dict, mistakes: list[dict]) -> int:
    """How many disagreements are kept aside: of each group, those past the ones listed."""
    return sum(max(0, c[key] - sum(m.get("judge") == judge for m in mistakes))
               for key, judge in (("easy", "pass"), ("strict", "fail")))


# In place of the lists when split.json can't be used, around the fix command
SPLIT_UNKNOWN = ("judgekeeper can't use the file that says which answers are kept aside. Run ",
                 " to see why and what to do.")


def _same(rows: list[dict]) -> list[tuple[str, str]]:
    """The fields with the same text in every listed row, when there are 2 or more and each
    row keeps a field of its own: shown once, not in each row."""
    if len(rows) < 2 or not all(m.get("fields") for m in rows):
        return []
    same = [(k, v) for k, v in rows[0]["fields"]
            if all([k, v] in [list(f) for f in m["fields"]] for m in rows[1:])]
    names = {k for k, _ in same}
    if any(all(k in names for k, _ in m["fields"]) for m in rows):
        return []
    return same


SAME = "The same in every answer below"


def _groups(c: dict, fixing: dict | None, live: bool = False,
            fix_command: str | None = None) -> str:
    """The disagreements on the marks the person can see, in two groups (a group with none
    to show is left out), each with how many more of it are kept aside; those of a group with
    none to show after the lists."""
    mistakes = (fixing or {}).get("mistakes") or []
    parts, own = (fixing or {}).get("parts") or [], (fixing or {}).get("own") or []
    out = []
    if (fixing or {}).get("split_unknown"):  # no list and no count: it can't say which
        return (f'<section class="sec slim"><p>{_e(SPLIT_UNKNOWN[0])}<code>'
                f'{look.command(_e(fix_command or "judgekeeper fix"))}</code>'
                f'{_e(SPLIT_UNKNOWN[1])}</p></section>')
    same = _same(mistakes)
    if same:  # each field folded, in one box above the lists
        out.append('<div class="sec slim">' + "".join(
            f'<details class="same"><summary><span class="fname">{_e(k)}</span>{SAME}</summary>'
            f'<p>{_e(v)}</p></details>' for k, v in same) + "</div>")
    names = tuple(k for k, _ in same)
    left = 0  # kept aside of a group with none to show
    for key, said, judge in (("easy", "You said Fail, your LLM-as-a-judge said Pass", "pass"),
                             ("strict", "You said Pass, your LLM-as-a-judge said Fail", "fail")):
        rows = [m for m in mistakes if m.get("judge") == judge]
        kept = max(0, c[key] - len(rows))
        if rows:
            out.append(_group(key, said, rows, kept, live, parts, own,
                              (fixing or {}).get("left_out", 0), names,
                              (fixing or {}).get("reasons_given", True)))
        else:
            left += kept
    if left:
        out.append(f'<p class="sec slim">{_kept_after(left)}</p>')
    return "".join(out)


def say_why(fixing: dict | None, live: bool, mark: str | None) -> str:
    """report.html, which can't save a reason: how to say why (`mark`: the command), for What
    next; nothing on the live page."""
    from judgekeeper.fix import without_why
    from judgekeeper.start_label import say_why_run

    mistakes = (fixing or {}).get("mistakes") or []
    asked = len(without_why(mistakes))  # the ones listed with no reason yet: never kept aside
    if not asked or live or not mark or (fixing or {}).get("split_unknown"):
        return ""
    return _code_line(say_why_run(asked, mark, len(mistakes) - asked))


def estimate(value, interval, why: str | None = None) -> tuple[str, str]:
    """An estimate and its range for the numbers box: "about 57%", "37% and 74%", also while the
    range is too wide for a result (the headline says it is too early to tell). Too early to
    tell when there is no number yet. A range of no width is not shown: the number says why
    in brackets, `why` (why_no_range), as in "78% (you marked every answer)". Ends that round
    to the same percent are shown with one decimal, then two, and so is the value, so it
    always sits inside its range ("about 99.3% (between 99.1% and 99.3%)"); ends the same
    with two decimals too are no range to show: "about 99.3%", alone. Neither the
    value nor an end is shown as 100% or 0% unless it is exactly that (share): "99% and
    99.96%"; an end past two decimals reads "99.99%" or "0.01%", never "over" or "under"."""
    if value is None or not interval or interval[0] is None or interval[1] is None:
        return "too early to tell", "–"
    lo, hi = interval
    if targets.width_word(interval) == "exact":
        return f"{share(value)} ({why or EVERY_MARKED})", "–"
    for places in range(3):
        if f"{lo:.{places}%}" != f"{hi:.{places}%}":
            ends = _end(lo, places), _end(hi, places)
            if ends[0] != ends[1]:
                return _about(share(value, places)), " and ".join(ends)
            break
    return _about(share(value, 1)), "–"


def _end(x: float, places: int) -> str:
    return share(x, places).removeprefix("over ").removeprefix("under ")


def share(x: float, places: int = 0) -> str:
    """`x` as a percent with `places` decimals, or one or two more when fewer would read 100%
    or 0% though it is not exactly 1 or 0 ("99.6%", never "100%" for 499 of 501); past two
    decimals, "over 99.99%" or "under 0.01%"."""
    for n in range(places, 3):
        text = f"{x:.{n}%}"
        if x in (0, 1) or float(text[:-1]) not in (0, 100):
            return text
    return "over 99.99%" if x > 0.5 else "under 0.01%"


def _about(shown: str) -> str:
    return shown if shown.startswith(("over ", "under ")) else f"about {shown}"


# Why a number has no range, said in brackets after it: "78% (you marked every answer)"
EVERY_MARKED = "you marked every answer"
EXACT = "You marked every answer, so these numbers are exact."  # said once, under the numbers
NUM_HEAD = "How often your LLM-as-a-judge agrees with you"  # the numbers' heading
CHANGE_MARK = "Change a mark"  # the result page's link to marking, every answer marked
SAME_GRADE = "it gave every answer the same grade"
EVERY_OF = "you marked every answer it {did}"


def why_no_range(key: str, every: bool, pool: dict | None = None) -> str:
    """Why `key`'s range has no width. Every answer marked; or the judge gave every answer one
    grade (`pool`: how many it passed and failed); or, for TPR, every answer it failed is
    marked and none should pass (so it failed none that should), and for TNR the same with
    the answers it passed. Kappa has no range only with every answer marked."""
    if every:
        return EVERY_MARKED
    if pool and (not pool.get("pass") or not pool.get("fail")):
        return SAME_GRADE
    if key in ("tpr", "tnr"):
        return EVERY_OF.format(did="failed" if key == "tpr" else "passed")
    return EVERY_MARKED


ALL_ON = "you marked all {n} answers it is on"  # a newer batch is not counted yet
ON_ANSWERS = " in the {n} answers this result is on"


def why_for(r: dict, key: str) -> str:
    """why_no_range for a result: its count left to mark and its groups' sizes. When the
    result is on fewer batches than the results hold, the newer ones are not all marked: the
    bracket says every answer it is on is marked (ALL_ON, only when `counted_left` is 0), or,
    with some of those still left, names the answers it is on (ON_ANSWERS)."""
    g = r.get("groups") or {}
    pool = {k: (g.get(k) or {}).get("pool") for k in ("pass", "fail")} if g else None
    why = why_no_range(key, r.get("left") == 0 and not r.get("waiting"), pool)
    on = r.get("batches") or {}
    if why != SAME_GRADE and on.get("waiting") and len(on.get("counted") or []) < (on.get("of") or 0):
        if r.get("counted_left") == 0:  # no answer of the counted batches is unmarked
            return ALL_ON.format(n=on["answers"])
        why += ON_ANSWERS.format(n=on["answers"])
    return why


def shows_range(r: dict) -> bool:
    """Whether either main line shows a range: with none (every answer marked), the note
    that the result line uses wider ranges has nothing to compare with."""
    return any(estimate(r.get(k), r.get(f"{k}_interval"), why_for(r, k))[1] != "–"
               for k in ("tpr", "tnr"))


def _score(r: dict, c: dict) -> str:
    """Under the verdict: once there is a result, how often the judge agrees with the person
    when they say Pass and when they say Fail, and kappa, side by side, each with its range
    when it has one; under them the two counts. The heading has no line under it: "about"
    and the ranges say these are estimates. "(you marked every answer)" is said once at the
    foot (EXACT), not after each number. Before a result, the counts only."""
    if r["check"] == "too_few" or r.get("verdict_level") is None:
        return f'<section class="sec score" aria-label="Your marks">{_counts(r, c)}</section>'
    tail = f" ({EVERY_MARKED})"
    cells, exact = [], False
    for said, key in (("Pass", "tpr"), ("Fail", "tnr")):
        est, between = estimate(r.get(key), r.get(f"{key}_interval"), why_for(r, key))
        if est.endswith(tail):
            est, exact = est.removesuffix(tail), True
        cells.append((key, _term(f"When you say {said}, your LLM-as-a-judge also says {said}"),
                      est, None if between == "–" else _e(between)))
    shown, lo, hi = kappa_shown(r)
    if shown.endswith(tail):
        shown, exact = shown.removesuffix(tail), True
    tip = ('<span class="kappa">Kappa<button type="button" class="i" aria-describedby='
           '"kappa-tip" aria-expanded="false" aria-controls="kappa-tip" '
           'aria-label="What kappa means">ⓘ</button><span class="tip" '
           f'role="tooltip" id="kappa-tip">{_e(KAPPA_MEANS)}</span></span>')
    cells.append(("kappa", tip, shown, f"{lo} and {hi}" if lo is not None else None))
    body = "".join(f'<div class="cell c-{key}"><span class="n-lab">{name}</span>'
                   f'<span class="n-val">{_value(value)}</span>'
                   + (f'<span class="n-rng">between {rng}</span>' if rng else "") + "</div>"
                   for key, name, value, rng in cells)
    return ('<section class="sec score" aria-labelledby="nums-h"><div class="sh">'
            f'<h2 id="nums-h">{_term(NUM_HEAD)}</h2></div>'
            f'<div class="nums">{body}</div>{_counts(r, c)}'
            + (f'<p class="foot">{_e(EXACT)}</p>' if exact else "") + "</section>")


def _value(text: str) -> str:
    """A number as the score shows it: "about" smaller and muted, before the number."""
    if text.startswith("about "):
        return f'<span class="about">about </span>{_e(text[6:])}'
    return _e(text)


def kappa_shown(r: dict) -> tuple[str, str | None, str | None]:
    """Kappa as text and the ends of its range: none when it has no width (the text says why
    in brackets) or is too narrow to write (the number stands alone)."""
    kappa, (lo, hi) = r.get("kappa"), (r.get("kappa_interval") or (None, None))
    shown = _two(kappa) if kappa is not None else "n/a"
    if kappa is None or lo is None or hi is None:
        return shown, None, None
    if _two(lo) == _two(hi):
        if targets.width_word([lo, hi]) == "exact":
            shown = f"{shown} ({why_for(r, 'kappa')})"
        return shown, None, None
    return shown, _two(lo), _two(hi)


def _next(r: dict, back: str | None, extra: list[str]) -> str:
    """What next, once there is a result: where the marks are saved; when the judge needs work,
    the command (`judgekeeper fix` prints what to do next) in the website's command box with
    Copy; when it is good enough, that there is nothing more to do; then, unless every answer
    is marked, how to mark more: on the page the marking server serves, a link back to the
    marking page (`back`, with its token) and the command for once it has closed; in
    report.html the command only, so the token is never saved. `extra`: lines under the
    command (how to say why, STARTED_ELSE). NOTES marks where the notes go."""
    step = next_step(r)
    if step == "mark":
        return ""
    lead = ("<p>Your marks and reasons are saved in this project's <code>.judgekeeper</code> "
            "folder. You can close this page.</p>")
    act = []
    if step == "fix" and r.get("fix_ready") is False:  # `fix` would say this: mark more
        from judgekeeper.fix import NOT_ENOUGH

        act.append(f"<p>{_e(NOT_ENOUGH)}</p>")
    elif step == "fix":
        act.append("<p>Next, in your project folder:</p>"
                   f'<div class="cmd"><code>{look.command(_e(commands(r)["fix"]))}</code>'
                   '<button type="button" '
                   f'class="copy" data-copy aria-label="Copy command: {_e(commands(r)["fix"])}">'
                   f"{COPY_ICONS}</button>"
                   "</div>")
    else:
        act.append(f'<p>Nothing more to do. Run <code>{look.command(_e(commands(r)["check"]))}'
                   '</code> after '
                   f"you change your {TERM}.</p>")
    act += [f'<p class="small">{x}</p>' for x in extra]
    mark = f"<code>{look.command(_e(commands(r)['mark']))}</code>"
    # with every answer marked, or only answers a mark would wait on, nothing sends to marking
    more = r.get("left") != 0 and not r.get("only_wait")
    if more and back is not None and shows_range(r):  # no range: no more marks to ask for
        then = (f'<p>Want more certain numbers? <a href="{_e(back)}">Keep marking</a>. It '
                f"closes by itself after 30 minutes without use. Then run {mark} to open it "
                "again.</p>")
    elif more and step == "fix" and r.get("fix_ready") is False:  # NOT_ENOUGH: how to mark more
        then = f"<p>To mark more, run {mark} in your project folder.</p>"
    elif more:  # no link back to marking: report.html, or numbers that marks would not narrow
        then = ""
    elif back is not None:  # every answer marked: a mark can still be changed
        then = (f'<p><a href="{_e(back)}">{CHANGE_MARK}</a>: click it in the list and mark '
                "it again.</p>")
    else:
        then = f"<p>To change a mark, run {mark} in your project folder.</p>"
    return ('<section class="sec next-box" aria-labelledby="next-h"><div class="nx">'
            '<div class="h-head"><h2 id="next-h">What next</h2></div><div class="nx-split">'
            f'<div class="a-lead">{lead}</div><div class="a-act">{"".join(act)}</div>'
            + (f'<div class="a-more">{then}</div>' if then else "") + f"</div></div>{NOTES}"
            "</section>")


NOTES = "<!--notes-->"  # where the notes go in What next


def _notes_html(lines: list[str]) -> str:
    """The notes as a list, at the foot of What next (in two columns when it is wide)."""
    return ('<div class="nx-notes"><ul class="notes-list">'
            + "".join(f"<li>{x}</li>" for x in lines) + "</ul></div>") if lines else ""


def _last_check(last: dict | None, worse: str) -> str:
    """After a check found the new judge worse: that judge, "Worse", the counts and ranges the
    terminal gave, and the way back. The rest of the page stays the old judge's result."""
    if not last:
        return ""
    judge = f"Your new {TERM}" + (f" ({_e(last['judge'])})" if last.get("judge") else "")
    said = "".join(f"<p>{_term(x)}</p>" for x in last.get("lines") or [])
    return (f'<section class="last-check" aria-labelledby="last-h"><h2 id="last-h">'
            f'Last check</h2><p class="lc-top">{judge}: <b class="off">Worse</b>. The result '
            f'below is still about your old {TERM}.</p>{said}<p class="lc-next">'
            f"{_code_line(worse)}</p></section>")


STARTED_ELSE = ("These commands start with `judgekeeper`. If you start judgekeeper another way, "
                "start it that way.")


def page(r: dict, back: str | None = None, fixing: dict | None = None,
         worse: str | None = None, last: dict | None = None, started_else: bool = False) -> str:
    """The result page. `r`: the result; `back`: the link to the marking page while it runs
    (None in report.html); `fixing`: fix.report_section (the mistakes the person can see);
    `worse`: the next step after a check found the new judge worse, in place of the lead's
    and of What next; `last`: that check (check.last_check), said at the top;
    `started_else`: report.html of a run not started as its commands name the program
    (STARTED_ELSE under them). The page carries its Content-Security-Policy in a meta tag, so
    the saved copy keeps it too.

    One column, edge to edge: the verdict, the score (the numbers, then your counts), each
    list of disagreements, then What next with the notes. Each section starts with the same
    lit heading bar."""
    from judgekeeper.front import tool_name

    c = counts(r)
    judge = r.get("judge") or {}
    tool = tool_name(judge.get("tool"), judge.get("results_files"))
    model = (r.get("fingerprint") or {}).get("model")
    left = look.meta(_e(model) if model else None, _e(tool) if tool else None)
    live = back is not None
    top = _last_check(last, worse) if worse else ""
    lists, extra = "", []  # extra: lines under What next's command
    if shows_disagreements(r):  # real numbers: the disagreements
        mark = None if live or worse else commands(r)["mark"]  # after Worse: one way out
        lists = _groups(c, fixing, live, commands(r)["fix"])
        extra.append(say_why(fixing, live, mark))
    if started_else:
        extra.append(_e(STARTED_ELSE).replace("`judgekeeper`", "<code>judgekeeper</code>"))
    extra = [x for x in extra if x]
    nxt = "" if worse else _next(r, back, extra)
    head = top + _verdict(r, c, back, worse, above=bool(top))
    notes = _notes(r) + held_note(r, head + lists + nxt + "".join(extra))
    if nxt:
        nxt = nxt.replace(NOTES, _notes_html(notes))
    else:
        notes += extra  # no What next to put them under
        nxt = f'<section class="sec next-box">{_notes_html(notes)}</section>' if notes else ""
    body = head + _score(r, c) + lists + nxt
    meta = f'<meta http-equiv="Content-Security-Policy" content="{script_csp(live)}">\n'
    scripts = f"<script>{SCRIPT}</script>\n"
    if live and 'class="why"' in body:
        scripts += f"<script>{REASONS_SCRIPT}</script>\n"
    return (look.head("judgekeeper: your result", STYLE, meta)
            + look.top(left, "") + f'<main class="result">{body}'
            + f"</main>\n{scripts}</body>\n</html>\n")


# Answers with no grade (no_grades) ----------------------------------------------------------

FAILED = "Answers you failed"  # the one list, with no LLM-as-a-judge
RATE_HEAD = "Your pass rate"
RATE = "Of the answers you marked, you passed"
SURER_MARK = "Mark more answers for a surer number."
ONE_CELL = ".nums.one { grid-template-columns: 1fr; }\n"  # this page only: the others stay as they are


def no_grades_page(r: dict, back: str | None = None, fixing: dict | None = None,
                   worse: str | None = None, last: dict | None = None,
                   started_else: bool = False) -> str:
    """The result page for answers with no grade (no_grades), from page()'s parts, nothing
    about an LLM-as-a-judge: the counts as the headline, the pass rate with its Wilson range,
    the person's counts, the answers they failed in `fixing["mistakes"]`'s order (no_grades.
    section) with the reasons about the answer only (no_grades.offered), then What next.
    Before MIN_MARKS marks, the usual line and the counts only. `worse` and `last` are never
    given: there is no check."""
    from judgekeeper import no_grades
    from judgekeeper.start_label import _PAGE_FLAGS, ALL_MARKED, TO_A_RESULT, VERDICTS, marks_words

    fixing = fixing or {}
    labels = r["labels"]
    k, n = labels["correct"], labels["correct"] + labels["wrong"]
    live, left = back is not None, r.get("left")
    cmd = commands(r)
    mark = f"<code>{look.command(_e(cmd['mark']))}</code>"
    file = fixing.get("file") or "your results file"
    more = (no_grades.SURER if r["check"] == "result" else no_grades.MORE_ANSWERS).format(
        file=file, n=no_grades.MIN_MARKS, command=_PAGE_FLAGS.sub("", cmd["run"]))
    cnts = (f'<div class="cnts"><p class="c-pass">{own_line("passed", k)}</p>'
            f'<p class="c-fail">{own_line("failed", n - k)}</p></div>')
    if r["check"] != "result":  # too few marks: as before a graded result
        if left == 0:
            lead = f"{_e(ALL_MARKED.format(marks=marks_words(labels)))} {_code_line(more)}"
        elif live:
            lead = f'<a href="{_e(back)}">{_e(TO_A_RESULT)}</a>'
        else:
            lead = f"Run {mark} to mark more answers."
        body = (f'<section class="verdict" aria-labelledby="verdict-h"><h1 id="verdict-h" '
                f'class="plain">{_e(VERDICTS[None])}</h1><p class="lead">{lead}</p></section>'
                f'<section class="sec score" aria-label="Your marks">{cnts}</section>')
    else:
        head = _e(no_grades.COUNTS).format(k=f"<b>{k}</b>", n=f"<b>{n}</b> answer"
                                           + ("" if n == 1 else "s"))
        est, between = estimate(r["pass_rate"], r["pass_rate_interval"])
        rng = f'<span class="n-rng">between {_e(between)}</span>' if between != "–" else ""
        rows = fixing.get("mistakes") or []
        names = tuple(x for x, _ in _same(rows))
        lists = (_group("fail", FAILED, rows, 0, live, [], fixing.get("own") or [], 0, names,
                        reasons_given=False, asked=no_grades.offered()) if rows else "")
        if left:
            act = (f'<p><a href="{_e(back)}">{_e(SURER_MARK)}</a></p>' if live else
                   f"<p>{_e(SURER_MARK)} Run {mark} in your project folder.</p>")
            then = ""
        else:
            act = f"<p>{_code_line(more)}</p>"
            then = (f'<p><a href="{_e(back)}">{CHANGE_MARK}</a>: click it in the list and mark '
                    "it again.</p>" if live else
                    f"<p>To change a mark, run {mark} in your project folder.</p>")
        if started_else:
            act += ('<p class="small">' + _e(STARTED_ELSE).replace(
                "`judgekeeper`", "<code>judgekeeper</code>") + "</p>")
        from judgekeeper.start_label import link_lines, quick_lines

        notes = [_e(x) for x in quick_lines(r.get("made"), None) + link_lines(r.get("made"))]
        body = (f'<section class="verdict" aria-labelledby="verdict-h"><h1 id="verdict-h" '
                f'class="plain">{head}</h1></section>'
                '<section class="sec score" aria-labelledby="nums-h"><div class="sh">'
                f'<h2 id="nums-h">{_e(RATE_HEAD)}</h2></div><div class="nums one">'
                f'<div class="cell c-rate"><span class="n-lab">{_e(RATE)}</span>'
                f'<span class="n-val">{_value(est)}</span>{rng}</div></div>{cnts}</section>'
                + lists +
                '<section class="sec next-box" aria-labelledby="next-h"><div class="nx">'
                '<div class="h-head"><h2 id="next-h">What next</h2></div><div class="nx-split">'
                "<div class=\"a-lead\"><p>Your marks and reasons are saved in this project's "
                "<code>.judgekeeper</code> folder. You can close this page.</p></div>"
                f'<div class="a-act">{act}</div>'
                + (f'<div class="a-more">{then}</div>' if then else "")
                + f"</div></div>{_notes_html(notes)}</section>")
    meta = f'<meta http-equiv="Content-Security-Policy" content="{script_csp(live)}">\n'
    scripts = f"<script>{SCRIPT}</script>\n"
    if live and 'class="why"' in body:
        scripts += f"<script>{REASONS_SCRIPT}</script>\n"
    from judgekeeper.front import tool_name

    judge = r.get("judge") or {}
    tool = tool_name(judge.get("tool"), judge.get("results_files"))
    return (look.head("judgekeeper: your result", STYLE + ONE_CELL, meta)
            + look.top(look.meta(None, _e(tool) if tool else None), "")
            + f'<main class="result">{body}</main>\n{scripts}</body>\n</html>\n')
