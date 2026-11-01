"""The marking page and its welcome box.

One self-contained page (look.py: nothing loaded from anywhere else). It shows one answer at a
time with the person's own marks and never anything the LLM-as-a-judge decided: no grade, no
reason, no agreement (an answer it graded more than once with different grades says only which
run it is: "Run 2 of 3: graded differently"). What it grades is shown: the metric's name above the answer, and its
rule behind a "Show the rule" button when the results hold one. Text reaches it through
textContent. The server fills in __DATA__ (start_label.StartSession.state), __TOKEN__ and
__NONCE__.

So that each mark comes from a real look at the answer: Fail and Pass look the same but for
their colour; after each mark the page ignores input for about 400 ms, and it ignores a held
key and any key with Cmd, Ctrl or Alt. Focus goes to the answer, never to a button. The
progress bar follows how close the result is (Pass and Fail marks, each counted up to ROUGH;
a skipped answer counts for nothing), never full before the result is ready, and no number on
the page is a target. When the result becomes ready while the page is open, a box says so,
once. In an answer or a question only `**bold**` and "- " lines are formatted, built with
createElement and createTextNode. Skipped answers come back at the end. On a phone (760px and
narrower) the card comes first, then the list.
"""

from __future__ import annotations

import json
from html import escape

from judgekeeper import look, targets
from judgekeeper.redact import scrub, visible

ROUGH = targets.ROUGH  # marks of each kind that fill the bar: a first result takes that many
# Answers looked at (marked or skipped) after which, with no result yet, the page says to
# keep going: about what a first result takes
FIRST = 2 * ROUGH
SEGMENTS = 16  # the bar's cells

TITLE = "Mark each answer Pass or Fail."  # the welcome box: its logo, this headline and one button
RULE_CHARS = 2000  # of the rule shown; a longer one is cut, with "…"
METRIC_CHARS = 200  # of the metric's name shown, the same way
SHORT_QUESTION = 140  # characters of a one-line question shown as the big heading
SHORT_ANSWER, LONG_ANSWER = 300, 1500  # an answer's size: 20 px up to 300, 18 up to 1500, 17

CROSS = ('<svg class="btn-ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
         '<path d="M4 4l8 8M12 4l-8 8"/></svg>')
TICK = ('<svg class="btn-ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
        '<path d="M3 8.5l3.2 3.2L13 5"/></svg>')
# The state dots in the list: a dashed ring (not marked), a green ring with a check (Pass), a
# red ring with a cross (Fail).
DOTS = {"none": ('<svg class="dot dot-none" viewBox="0 0 20 20" aria-hidden="true" '
                 'focusable="false"><circle cx="10" cy="10" r="9"/></svg>'),
        "pass": ('<svg class="dot dot-pass" viewBox="0 0 20 20" aria-hidden="true" '
                 'focusable="false"><circle cx="10" cy="10" r="9"/>'
                 '<path d="M6 10.5l2.6 2.6L14 7.5"/></svg>'),
        "fail": ('<svg class="dot dot-fail" viewBox="0 0 20 20" aria-hidden="true" '
                 'focusable="false"><circle cx="10" cy="10" r="9"/>'
                 '<path d="M7 7l6 6M13 7l-6 6"/></svg>')}


def _text(value: str) -> str:
    """Text for the page: escaped, and with no `_`, so it can never hold one of the names the
    server fills in (__DATA__, __TOKEN__, __NONCE__)."""
    return escape(value).replace("_", "&#95;")


STYLE = """
html, body { height: 100%; }
body { display: flex; flex-direction: column; min-height: 100vh; }
#app { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.status-1 { display: flex; align-items: center; gap: 12px; }
.seg { display: flex; gap: 3px; }
.seg i { display: block; width: 6px; height: 10px; background: var(--line); }
.seg i.on { background: var(--text); }
.count { font-family: var(--mono); font-size: 13px; white-space: nowrap; }
.progress-box { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.keep { margin: 0; max-width: 40ch; font-size: 12.5px; line-height: 1.35; color: var(--muted);
  white-space: normal; text-align: right; }
.see { font-size: 13px; font-weight: 700; color: var(--green); text-decoration: none;
  white-space: nowrap; }
.see:hover { text-decoration: underline; }
.wrap { flex: 1; display: grid; grid-template-columns: 400px 1fr; min-height: 0;
  height: calc(100vh - 72px); }
.side { border-right: 1px solid var(--line); display: flex; flex-direction: column;
  min-height: 0; }
.list { list-style: none; margin: 0; padding: 0; flex: 1; overflow: auto; min-height: 0; }
.item { width: 100%; display: grid; grid-template-columns: 36px minmax(0, 1fr) 16px;
  align-items: center; gap: 12px; padding: 15px 22px 15px 20px; border-bottom: 1px solid var(--line);
  border-left: 2px solid transparent; text-align: left; color: var(--muted); font-size: 15px;
  line-height: 1.4; text-decoration: none; }
.item .q { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item { position: relative; }  /* its screen-reader words stay inside the list */
.item:hover { background: var(--hover); color: var(--text); }
.item[aria-current] { background: var(--current); color: var(--text); border-left-color: var(--text); }
.item .num { font-family: var(--mono); font-size: 12px; color: var(--faint); }
.item[aria-current] .num { color: var(--text); }
.dot { width: 14px; height: 14px; }
.dot circle { fill: none; stroke: var(--faint); stroke-width: 1.8; stroke-dasharray: 2 2.2; }
.dot path { fill: none; stroke-width: 2.2; stroke-linecap: square; }
.dot-pass circle, .dot-fail circle { stroke-dasharray: none; }
.dot-pass circle, .dot-pass path { stroke: var(--green); }
.dot-fail circle, .dot-fail path { stroke: var(--red); }
.main { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: auto; }
.card { flex: 1; display: flex; flex-direction: column; }
.row { padding: 32px 40px; border-bottom: 1px solid var(--line); }
.row-q { display: grid; grid-template-columns: 1fr auto; gap: 16px; }
.row-a { flex: 1; }
.label { font-size: 11px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--faint); margin-bottom: 12px; }
.state { font-size: 13px; color: var(--muted); white-space: nowrap; }
.state .said { font-weight: 600; }
.state .said.pass { color: var(--green); }
.state .said.fail { color: var(--red); }
.run { margin: -4px 0 12px; font-size: 13px; color: var(--muted); }
.question { font-size: 26px; font-weight: 700; letter-spacing: -.01em; line-height: 1.25;
  margin: 0; max-width: 28ch; white-space: pre-wrap; overflow-wrap: anywhere; }
.question .field-name { display: block; font-size: 11px; font-weight: 600; letter-spacing: .1em;
  text-transform: uppercase; color: var(--faint); line-height: 1.5; }
.question .field { display: block; }
.question .field + .field-name { margin-top: 10px; }
.graded { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px;
  margin-bottom: 22px; }
.graded .label { margin: 0; }
.metric-name { font-family: var(--mono); font-size: 13px; color: var(--text);
  overflow-wrap: anywhere; min-width: 0; }
.rule-btn { margin-left: auto; }
.rule { margin: 0 0 18px; padding: 12px 16px; border-left: 2px solid var(--line);
  background: var(--hover); width: fit-content; max-width: 100%; }
.rule-text { margin: 0; font-size: 14px; line-height: 1.55; color: var(--muted); max-width: 70ch;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.answer { font-size: 20px; line-height: 1.6; margin: 0; max-width: 60ch; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.answer:dir(rtl), .question:dir(rtl) { margin-left: auto; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 20px 40px 16px; border-top: 1px solid var(--line); }
.btn { height: 50px; border-radius: 4px; display: flex; align-items: center; justify-content: center;
  gap: 10px; font-size: 16px; font-weight: 700; color: #fff; transition: filter 100ms ease; }
.btn:active { filter: brightness(.9); }
.btn:disabled { cursor: default; }
.btn-ico { width: 15px; height: 15px; }
.btn-ico path { fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: square; }
.btn kbd { font-family: var(--sans); font-size: 13px; font-weight: 400; margin-left: 8px; }
.btn.fail { background: var(--red-fill); }
.btn.pass { background: var(--green-fill); }
.btn.fail:hover { filter: brightness(1.08); }
.btn.pass:hover { filter: brightness(1.08); }
.sub { display: flex; align-items: center; justify-content: center; padding: 0 40px 6px; }
.quiet { padding: 8px 20px; font-size: 14px; color: var(--muted); }
.quiet:hover { color: var(--text); background: var(--hover); }
.quiet kbd { font-family: var(--mono); font-size: 12px; color: var(--text); margin-left: 8px; }
.status { margin: 0; padding: 0 40px 10px; text-align: center; font-size: 13px; font-weight: 600;
  color: var(--red); }
.status:empty { display: none; }
.status.calm { color: var(--muted); font-weight: 400; }
.end { padding: 56px 28px; display: flex; flex-direction: column; align-items: center; gap: 24px;
  text-align: center; }
.end h2 { margin: 0; font-size: 26px; font-weight: 700; letter-spacing: -.01em; line-height: 1.25;
  max-width: 32ch; }
.end .note { margin: 0; color: var(--muted); font-size: 15px; }
.go { font-weight: 700; border-radius: 4px; color: #fff; background: var(--green-fill);
  height: 50px; padding: 0 28px; font-size: 16px; text-decoration: none; display: inline-flex;
  align-items: center; justify-content: center; transition: filter 100ms ease; }
.go:hover, .go:active { filter: brightness(.92); }
.foot { margin: 0; padding: 12px 40px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); text-align: center; }
.foot code { font-family: var(--mono); font-size: 12.5px; color: var(--text); }
#end-note code { font-family: var(--mono); font-size: .9em; color: var(--text); }
.scrim { position: fixed; inset: 0; z-index: 10; background: var(--scrim); display: flex;
  align-items: center; justify-content: center; padding: 20px; }
.intro { background: var(--bg); border: 1px solid var(--line); border-radius: 2px; width: 100%;
  max-width: 520px; padding: 40px; display: flex; flex-direction: column; align-items: center;
  gap: 24px; text-align: center; animation: appear 120ms ease-out; }
@keyframes appear { from { opacity: 0; } to { opacity: 1; } }
.intro .brand { font-size: 21px; gap: 10px; }
.intro .logo-mark svg { width: 30px; height: 33px; }
.intro h2 { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -.01em; line-height: 1.25; }
.intro .go { width: 100%; height: 56px; font-size: 17px; }
.intro .note { margin: 0; color: var(--muted); font-size: 15px; }
.intro .quiet { padding: 10px 20px; }
.answer ul, .question ul { margin: .4em 0; padding-left: 1.4em; white-space: normal; }
.answer li, .question li { margin: .15em 0; }
#answer-card:focus-visible, #end:focus-visible, .intro:focus-visible { outline: none; }
/* the text as written: no font ligature turns -> into an arrow */
.question, .answer, .item .q, .rule { font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }
.answer .code-wrap { position: relative; display: block; margin: 12px 0; }
.answer code.block { display: block; margin: 0; padding: 14px 16px; font-family: var(--mono);
  font-size: 14px; line-height: 1.55; white-space: pre; overflow-x: auto; overflow-wrap: normal;
  border: 1px solid var(--line); background: var(--hover); text-align: left;
  font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }
.answer code.block::-webkit-scrollbar { height: 8px; }
.answer code.block::-webkit-scrollbar-track { background: transparent; }
.answer code.block::-webkit-scrollbar-thumb { background: var(--faint); border-radius: 4px; }
@supports not selector(::-webkit-scrollbar) {
  .answer code.block { scrollbar-width: thin; scrollbar-color: var(--faint) transparent; }
}
.code-wrap.more-right::after { content: ""; position: absolute; top: 1px; right: 1px;
  bottom: 9px; width: 1.5em; pointer-events: none;
  background: linear-gradient(to right, transparent, var(--hover)); }
.question .q-head, .question .q-gap, .question .q-tail, .question .q-start,
.question .q-end { display: block; }
.q-more { margin-top: 8px; }
/* One link style: "Show all" and "Show the rule" */
.quiet.q-more, .quiet.rule-btn { padding: 6px 0; font-size: 14px; color: var(--muted);
  text-decoration: underline; text-decoration-color: var(--faint); text-underline-offset: 3px; }
.quiet.q-more:hover, .quiet.rule-btn:hover, .quiet.q-more:focus-visible,
.quiet.rule-btn:focus-visible { color: var(--text); background: none; }
@media (min-width: 761px) {
  html, body { height: 100%; overflow: hidden; }
  body { min-height: 0; }
  .wrap { height: auto; grid-template-rows: minmax(0, 1fr); }
  .main { overflow: hidden; }
  .card { min-height: 0; }
  .row-q { flex: 0 1 auto; min-height: 0; overflow: hidden; grid-template-rows: minmax(0, 1fr);
    padding-top: 26px; padding-bottom: 22px; }
  #q-row { display: flex; flex-direction: column; min-height: 0; }
  #q-row > .label, .q-more { flex: none; align-self: flex-start; }
  #q-row > .question { flex: 0 1 auto; min-height: 0; }
  .row-a { flex: 1 1 0; min-height: calc((100vh - 72px) * .35 + 65px); display: flex;
    flex-direction: column; overflow: hidden; padding-top: 26px; padding-bottom: 0; }
  .card:has(.rule:not([hidden])) .row-q { flex-shrink: 0; }  /* the rule gives way, not the question */
  .row-a > .graded, .row-a > .label, .row-a > .run { flex: none; }
  .a-scroll { flex: 1 1 0; min-height: calc((100vh - 72px) * .35 - 30px); overflow: auto;
    overscroll-behavior: contain; margin: 0 -40px; padding: 0 40px 32px; }
  .a-scroll.fits { flex: 0 0 auto; min-height: 0; }
  .card:has(.rule:not([hidden])) .a-scroll:not(.fits) { min-height: calc((100vh - 72px) * .25 - 30px); }
  .row-a:has(> .a-scroll.fits) { min-height: 0; }
  .a-scroll.more-below, .question.long.cut:not(.open), .question.long.open.more-below,
  .rule.more-below { -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 1.5em), transparent); mask-image: linear-gradient(to bottom, #000 calc(100% - 1.5em), transparent); }
  .actions, .sub, .status, .foot { flex: none; }
  /* Wide: the text, the buttons and the foot line keep to 1120px; the hairlines run the
     full width */
  .main { container-type: inline-size; }
  .row, .actions, .status, .foot, .sub { padding-right: max(40px, calc(100cqw - 1160px)); }
  .a-scroll { margin-right: calc(-1 * max(40px, calc(100cqw - 1160px)));
    padding-right: max(40px, calc(100cqw - 1160px)); }
  .question:not(.long) { max-width: 75ch; }
  .question.long { font-size: 17px; font-weight: 400; line-height: 1.6; letter-spacing: 0;
    max-width: 75ch; max-height: calc(4 * 1.6em); overflow: hidden; }
  .question.long .field + .field-name { margin-top: 6px; }
  .question.long.ht:not(.open) { max-height: none; }
  .question .q-head, .question .q-tail { max-height: calc(2 * 1.6em); overflow: hidden; }
  .question .q-tail { display: flex; flex-direction: column; justify-content: flex-end; }
  .question .q-gap { font-size: 13px; letter-spacing: .3em; color: var(--muted); }
  .question.open .q-end { position: sticky; bottom: 0; background: var(--bg);
    border-top: 1px solid var(--line); padding-top: 4px; }
  .question.long.open { max-height: min(calc((100vh - 72px) * .3), 28vh); overflow: auto;
    overscroll-behavior: contain; }
  .question.long.open:focus-visible, .rule:focus-visible { -webkit-mask-image: none;
    mask-image: none; outline: 1px solid var(--muted); outline-offset: 4px; }
  .answer .empty { color: var(--muted); }
  .answer.a-mid { font-size: 18px; line-height: 1.6; max-width: 68ch; }
  .answer.a-long { font-size: 17px; line-height: 1.65; max-width: 75ch; }
  .rule { flex: 0 1 auto; min-height: 0; max-height: min(calc((100vh - 72px) * .3), 28vh); overflow: auto;
    overscroll-behavior: contain; }
}
@media (min-width: 761px) and (max-height: 800px) {
  .row-q { padding-top: 18px; padding-bottom: 14px; }
  .row-a { padding-top: 18px; }
  .label { margin-bottom: 8px; }
  .graded { margin-bottom: 10px; }
  .rule { margin-bottom: 12px; }
  .q-more { margin-top: 4px; }
  .actions { padding-top: 12px; padding-bottom: 8px; }
  .btn { height: 44px; }
  .sub { padding-bottom: 2px; }
  .sub .quiet { padding: 6px 16px; }
  .foot { padding-top: 8px; padding-bottom: 8px; }
}
@media (max-width: 760px) {
  html, body { height: auto; }
  #app, .wrap { flex: none; min-height: 0; }
  .wrap { grid-template-columns: 1fr; height: auto; }
  .main, .list { overflow: visible; }
  .side { border-right: 0; border-top: 1px solid var(--line); order: 2; }
  .main { order: 1; }
  .row { padding: 18px 16px; }
  .row-a { min-height: 120px; }
  .question { font-size: 22px; }
  .answer { font-size: 17px; }
  .actions { padding: 16px 16px 12px; }
  .btn { height: 60px; font-size: 16px; gap: 8px; }
  .sub { flex-wrap: wrap; padding: 8px 16px; gap: 4px 8px; }
  .quiet { padding: 10px 14px; }
  .foot { padding-left: 16px; padding-right: 16px; }
  .intro { padding: 32px 24px 28px; }
  .intro h2 { font-size: 24px; }
  .progress-box { width: 100%; align-items: flex-end; scroll-margin-top: 8px; }
  /* the link drops under the bar when the three don't fit on one line */
  .status-1 { flex-wrap: wrap; justify-content: flex-end; row-gap: 4px; }
}
"""

BODY = """<div id="app">
__TOP__
<div class="wrap">
<nav class="side" aria-label="Answers">
  <ol class="list" id="queue"></ol>
</nav>
<main class="main">
  <section class="card" id="answer-card" tabindex="-1" aria-label="The answer to mark">
    <div class="row row-q"><div id="q-row"><div class="label" id="q-label">Question</div><h1 class="question" id="q-text" dir="auto"></h1><button type="button" class="quiet q-more" id="q-more" aria-expanded="false" aria-controls="q-text" hidden>Show all</button></div><div class="state" id="ans-status" aria-live="polite"></div></div>
    <div class="row row-a">__GRADED__<div class="label">Answer</div><p class="run" id="a-run" hidden></p><div class="a-scroll" id="a-scroll"><p class="answer" id="a-text" dir="auto"></p></div></div>
    <div class="actions" id="decide">
      <button type="button" class="btn fail" id="fail" aria-pressed="false" aria-keyshortcuts="ArrowLeft">__CROSS__<span>Fail</span><kbd>←</kbd></button>
      <button type="button" class="btn pass" id="pass" aria-pressed="false" aria-keyshortcuts="ArrowRight">__TICK__<span>Pass</span><kbd>→</kbd></button>
    </div>
    <div class="sub"><button type="button" class="quiet" id="skip" aria-keyshortcuts="S"><span>Skip this one</span><kbd>S</kbd></button><button type="button" class="quiet" id="undo" aria-keyshortcuts="Z"><span>Undo</span><kbd>Z</kbd></button></div>
    <p class="status" id="status" role="status"></p>
    <p class="sr" id="done" role="status"></p>
  </section>
  <section class="card end" id="end" hidden aria-live="polite" tabindex="-1"><h2 id="end-title"></h2>
    <p class="note" id="end-note" hidden>Opening your result…</p>
    <button type="button" class="go" id="again" hidden>Look at them</button></section>
  <p class="foot">To come back: <code>__COMMAND__</code>__HELD__</p>
</main>
</div>
</div>
<div class="scrim" id="intro" hidden>
  <div class="intro" id="intro-box" role="dialog" aria-modal="true" aria-labelledby="intro-title" tabindex="-1">
    __BRAND__
    <h2 id="intro-title">__TITLE__</h2>
    <button type="button" class="go" id="intro-ok">Start marking</button>
  </div>
</div>
<div class="scrim" id="ready" hidden>
  <div class="intro" id="ready-box" role="dialog" aria-modal="true" aria-labelledby="ready-title" tabindex="-1">
    __BRAND__
    <h2 id="ready-title">Your result is ready.</h2>
    <p class="note" id="ready-note"></p>
    <a class="go" id="ready-see" href="#">See your result</a>
    <button type="button" class="quiet" id="ready-keep">Keep marking</button>
  </div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", FIRST = __FIRST__, ROUGH = __ROUGH__, SEGMENTS = __SEGMENTS__, LOCK_MS = 400, SAVE_MS = 10000;
  var WORDS = __WORDS__;  // the link and the line under the bar (_words)
  // A question up to SHORT_Q characters on one line is a heading; an answer is read at its
  // size by length (up to SHORT_A, up to LONG_A, longer).
  var SHORT_Q = __SHORT_Q__, SHORT_A = __SHORT_A__, LONG_A = __LONG_A__;
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var total = data.total || items.length;  // the page holds the next answers, not all of them
  var shownAt = Date.now();  // when the answer on screen was shown: each mark sends its seconds
  var status = data.status;  // whether a result is ready, from the server
  var ended = false;         // nothing left to mark: the page says what comes next
  var walkingSkipped = false;  // "Look at them": going through the skipped answers
  var lockUntil = 0;         // clicks are ignored until then, after each mark
  var queued = [];           // keys pressed while a mark is saved: they act, in order, after it
  var $ = function (id) { return document.getElementById(id); };
  var card = $("answer-card");
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  // A line from the terminal: each `command` in it shows as code, without its backticks.
  function setLine(id, text) {
    var into = $(id);
    into.textContent = "";
    String(text).split("`").forEach(function (part, k) {
      if (part) { into.appendChild(k % 2 ? el("code", null, part) : document.createTextNode(part)); }
    });
  }
  // The rule, behind its button: shown when asked for, the same for every answer. It and the
  // whole question are never open together, so the answer always keeps its room.
  function showRule(show, back) {
    if (!$("rule-btn") || !$("rule")) { return; }
    tabStop($("rule"), show, back);  // first: hidden, the box has already lost focus
    $("rule").hidden = !show;
    $("rule-btn").setAttribute("aria-expanded", String(show));
    setText("rule-btn", show ? "Hide the rule" : "Show the rule");
    $("rule").scrollTop = 0;
    fitRule();
  }
  // The open rule: a fade at its bottom while there is more below, as the answer has.
  function fitRule() {
    var box = $("rule");
    if (!box) { return; }
    box.classList.toggle("more-below",
      !box.hidden && box.scrollTop + box.clientHeight < box.scrollHeight - 2);
  }
  if ($("rule")) { $("rule").addEventListener("scroll", fitRule); }
  if ($("rule-btn")) {
    $("rule-btn").addEventListener("mousedown", function (e) { e.preventDefault(); });
    $("rule-btn").addEventListener("click", function () {
      var show = $("rule").hidden;
      if (show) { openQuestion(false, $("rule-btn")); }
      showRule(show, $("rule-btn"));
      fitQuestion();
    });
  }
  // An open question or rule is a tab stop of its own, so the keys can scroll it; shut, it is
  // not, and focus on it goes back to the answer.
  // Shut while it has focus, focus goes to `back` (the button that shut it), else the answer.
  function tabStop(box, on, back) {
    if (on) { box.setAttribute("tabindex", "0"); return; }
    var had = document.activeElement === box;
    box.removeAttribute("tabindex");
    if (had) { if (back) { back.focus(); } else { focusCard(); } }
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text != null) { e.textContent = String(text); }
    return e;
  }
  // `**bold**` as <strong> and lines that start with "- " as a list: built with createElement
  // and createTextNode, never innerHTML. Anything else stays text; a `**` never closed stays.
  var BOLD = /\\*\\*(.+?)\\*\\*/g;
  function inline(into, text) {
    var at = 0, m;
    BOLD.lastIndex = 0;
    while ((m = BOLD.exec(text))) {
      if (m.index > at) { into.appendChild(document.createTextNode(text.slice(at, m.index))); }
      into.appendChild(el("strong", null, m[1]));
      at = m.index + m[0].length;
    }
    if (at < text.length) { into.appendChild(document.createTextNode(text.slice(at))); }
  }
  function rich(into, text) {
    var plain = [], list = null;
    function flush() { if (plain.length) { inline(into, plain.join("\\n")); plain = []; } }
    String(text).split("\\n").forEach(function (line) {
      if (line.slice(0, 2) !== "- ") { list = null; plain.push(line); return; }
      flush();
      if (!list) { list = el("ul"); into.appendChild(list); }
      var item = el("li");
      inline(item, line.slice(2));
      list.appendChild(item);
    });
    flush();
  }
  function richEl(cls, text) { var e = el("span", cls); rich(e, text); return e; }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  // A line that a mark was not saved is brought into view, also on a phone.
  function say(text, calm) {
    setText("status", text);
    $("status").classList.toggle("calm", !!calm);
    if (text && $("status").scrollIntoView) { $("status").scrollIntoView({block: "nearest"}); }
  }
  // On a phone the card comes first, then the list: the bar, which sits before the card, is
  // scrolled to the top, so its link and line show with the card (at once under reduced
  // motion). Wider, the card is next to the list and stays where it is.
  function media(query) { return !!(window.matchMedia && window.matchMedia(query).matches); }
  function focusCard() {
    var to = ended ? $("end") : card;
    to.focus({preventScroll: true});
    var into = ended ? to : $("progress-box");
    if (media("(max-width: 760px)") && into.scrollIntoView) {
      into.scrollIntoView({behavior: media("(prefers-reduced-motion: reduce)") ? "auto" : "smooth",
                         block: "start"});
    }
  }
  $("see").setAttribute("href", url("/result"));

  // A question is text, or [[name, value], ...]. A part that is the answer itself is left
  // out (it shows below); one part left shows as plain text, two or more under "Input", each
  // name a small label above its value.
  function question(it) {
    var value = it.input;
    if (!Array.isArray(value)) { return value == null ? "" : String(value); }
    var answer = String(it.output == null ? "" : it.output).trim();
    value = value.filter(function (pair) { return String(pair[1]).trim() !== answer; });
    return value.length > 1 ? value : value.length ? String(value[0][1]) : "";
  }
  function chars(text) { return Array.from(String(text)).length; }
  // A long text whose last paragraph (or line) is a question: its start, then that question.
  // [start, end, the line break between] cut where they meet, or null.
  function headTail(text) {
    var at = text.lastIndexOf("\\n\\n"), gap = 2;
    if (at < 0) { at = text.lastIndexOf("\\n"); gap = 1; }
    if (at < 0) { return null; }
    var head = text.slice(0, at), tail = text.slice(at + gap);
    if (!/\\?\\s*$/.test(tail) || !tail.trim() ||
        (chars(head) <= 200 && head.split("\\n").length <= 3)) { return null; }
    return [head, tail, text.slice(at, at + gap)];
  }
  var whole = "";  // the question as text, when it folds to its start and its end
  // Folded: the first 2 lines (a blank line is not one of them), a "…" line, the last 2
  // lines, in their order. Shown all: the whole text in order, its question kept in view at
  // the bottom until the person scrolls to it.
  function drawQuestion(open) {
    var into = $("q-text"), parts = whole ? headTail(whole) : null;
    if (!parts) { return; }
    into.textContent = "";
    if (open) {
      into.appendChild(richEl("q-start", parts[0] + parts[2]));
      into.appendChild(richEl("q-end", parts[1]));
      return;
    }
    into.appendChild(richEl("q-head", parts[0].replace(/\\n\\s*\\n/g, "\\n")));
    var gap = el("span", "q-gap", "\u2026");
    gap.setAttribute("aria-hidden", "true");
    into.appendChild(gap);
    into.appendChild(richEl("q-tail", parts[1]));
  }
  // A short one-line question is the big heading; a longer one, or several named values, reads
  // at normal size, about 4 lines of it, then "Show all".
  function showQuestion(it) {
    var value = question(it), into = $("q-text");
    var long = Array.isArray(value) || chars(value) > SHORT_Q || value.indexOf("\\n") > -1;
    into.textContent = "";
    // not on a phone, which shows the whole text
    whole = !Array.isArray(value) && long && !media("(max-width: 760px)") && headTail(value) ?
      value : "";
    into.className = long ? "question long" + (whole ? " ht" : "") : "question";
    tabStop(into, false);  // shut again for the next answer: no tab stop of its own
    into.scrollTop = 0;
    setText("q-more", "Show all"); $("q-more").setAttribute("aria-expanded", "false");
    setText("q-label", "Question");
    $("q-label").hidden = Array.isArray(value);  // its fields are labelled
    $("q-row").hidden = Array.isArray(it.input) && value === "";
    if (whole) { drawQuestion(false); }
    else if (!Array.isArray(value)) { rich(into, value); }
    else {
      value.forEach(function (pair) {
        var name = el("span", "field-name", pair[0]), field = richEl("field", pair[1]);
        name.setAttribute("dir", "auto"); field.setAttribute("dir", "auto");
        into.appendChild(name); into.appendChild(field);
      });
    }
    fitQuestion();
  }
  // "Show all" only when the question is longer than its 4 lines (always for its start and
  // its end); shown all, a fade at its bottom while there is more below.
  function fitQuestion() {
    var into = $("q-text"), open = into.classList.contains("open");
    var cut = !whole && into.classList.contains("long") &&
              into.scrollHeight > into.clientHeight + 1;
    into.classList.toggle("cut", cut);
    into.classList.toggle("more-below",
      open && !whole && into.scrollTop + into.clientHeight < into.scrollHeight - 2);
    $("q-more").hidden = !(cut || open || whole);
  }
  function openQuestion(open, back) {
    var into = $("q-text");
    if (into.classList.contains("open") === open) { return; }
    into.classList.toggle("open", open);
    tabStop(into, open, back);
    into.scrollTop = 0;
    drawQuestion(open);
    $("q-more").setAttribute("aria-expanded", String(open));
    setText("q-more", open ? "Show less" : "Show all");
    fitQuestion();
  }
  $("q-text").addEventListener("scroll", fitQuestion);
  $("q-more").addEventListener("mousedown", function (e) { e.preventDefault(); });
  $("q-more").addEventListener("click", function () {
    var open = !$("q-text").classList.contains("open");
    if (open) { showRule(false, $("q-more")); }
    openQuestion(open, $("q-more"));
  });

  // The answer, never cut: its text as text, a ``` fenced block in a box of its own (still
  // text), in an area that scrolls by itself, a fade at its bottom while there is more.
  // A fence opens on a line that starts with ```: the rest of that line is its language when
  // it is one word (not shown), else the box's first line. It closes on a line that is just
  // ``` (spaces allowed). One never closed stays text. No other character is left out.
  var LANG = /^[A-Za-z0-9+#._-]+$/, CLOSE = /^\\s*```\\s*$/;
  function fences(text) {
    var lines = text.split("\\n"), parts = [], prose = [], i = 0;
    while (i < lines.length) {
      var line = lines[i], end = -1, j;
      if (line.slice(0, 3) === "```") {
        for (j = i + 1; j < lines.length; j++) { if (CLOSE.test(lines[j])) { end = j; break; } }
      }
      if (end < 0) { prose.push(line); i++; continue; }
      var rest = line.slice(3), body = lines.slice(i + 1, end);
      if (rest.trim() && !LANG.test(rest.trim())) { body.unshift(rest); }
      parts.push({text: prose.join("\\n")}, {code: body.join("\\n")});
      prose = [];
      i = end + 1;
    }
    parts.push({text: prose.join("\\n")});
    return parts;
  }
  function showAnswer(text) {
    var into = $("a-text");
    text = text == null ? "" : String(text);
    codes = [];
    into.textContent = "";
    into.className = "answer" + (chars(text) > LONG_A ? " a-long" :
                                 chars(text) > SHORT_A ? " a-mid" : "");
    if (!text.trim()) { into.appendChild(el("span", "empty", "(empty answer)")); text = ""; }
    var parts = fences(text);
    parts.forEach(function (part, k) {  // the line breaks next to a box are the box's edges
      if (part.code != null) { into.appendChild(codeBox(part.code)); return; }
      var t = part.text;
      if (k > 0) { t = t.replace(/^\\n+/, ""); }
      if (k < parts.length - 1) { t = t.replace(/\\n+$/, ""); }
      if (t) { rich(into, t); }
    });
    edges();
    var area = answerArea();
    if (area) { area.scrollTop = 0; fitAnswer(); fade(); }
  }
  // An answer shorter than the room kept for it takes only its own height, so the question
  // and the rule can use the rest.
  function fitAnswer() {
    var area = answerArea();
    if (!area || !window.getComputedStyle) { return; }
    area.classList.remove("fits");
    var style = getComputedStyle(area), room = parseFloat(style.minHeight) || 0;
    area.classList.toggle("fits", room > 0 &&
      $("a-text").offsetHeight + (parseFloat(style.paddingBottom) || 0) <= room);
  }
  // A code box, with a fade at its right edge while more of it is to the side.
  var codes = [];
  function codeBox(text) {
    var wrap = el("span", "code-wrap"), code = el("code", "block", text);
    code.setAttribute("dir", "ltr");
    code.addEventListener("scroll", function () { edge(code); });
    wrap.appendChild(code);
    codes.push(code);
    return wrap;
  }
  function edge(code) {
    code.parentNode.classList.toggle("more-right",
      code.scrollLeft + code.clientWidth < code.scrollWidth - 2);
  }
  function edges() { codes.forEach(edge); }
  function answerArea() { return $("a-text").parentNode; }
  function fade() {  // more text below, not only the area's bottom padding
    var area = answerArea();
    if (!area) { return; }
    var pad = window.getComputedStyle ? parseFloat(getComputedStyle(area).paddingBottom) || 0 : 0;
    area.classList.toggle("more-below",
      area.scrollTop + area.clientHeight < area.scrollHeight - pad - 2);
  }
  if (answerArea()) { answerArea().addEventListener("scroll", fade); }
  window.addEventListener && window.addEventListener("resize", function () {
    fitAnswer(); fade(); fitQuestion(); fitRule(); edges(); });
  // Space, Page Down and the arrows up and down scroll the answer (Shift+Space and Page Up
  // back), also held, Home and End to its top and bottom; the open question or rule instead
  // while it has focus. Not on a phone, where the page itself scrolls.
  function scrollAnswer(e, k) {
    var t = e.target, area = (t === $("q-text") || t === $("rule")) &&
      t.getAttribute("tabindex") === "0" ? t : answerArea();
    if (!area || media("(max-width: 760px)")) { return false; }
    var page = Math.max(area.clientHeight - 60, 40), most = area.scrollHeight - area.clientHeight;
    var by = {" ": e.shiftKey ? -page : page, pagedown: page, pageup: -page,
              arrowdown: 40, arrowup: -40, home: -Infinity, end: Infinity}[k];
    if (by === undefined) { return false; }
    area.scrollTop = Math.max(0, Math.min(area.scrollTop + by, most));
    if (area === answerArea()) { fade(); }
    return true;
  }
  // The list's title for an answer: the question at the end of a long text, without its
  // label ("Question: "); else the first line with real words ("Context:" alone is only a
  // label), of the question-like field when there are several. A label is 1 to 3 words: a
  // sentence with a colon in it ("Please reply ...: no words") keeps its start.
  var LABEL = /^[^\\s:]+(?: [^\\s:]+){0,2}:\\s+(?=\\S)/;
  function firstLine(it) {
    var value = question(it), lines, parts = Array.isArray(value) ? null : headTail(value);
    if (parts) {
      lines = parts[1].split("\\n").filter(function (line) { return line.trim(); });
      return lines[lines.length - 1].replace(LABEL, "");
    }
    lines = String(Array.isArray(value) ? value[0][1] : value).split("\\n");
    return (lines.filter(function (line) {
      return line.trim() && !/^[^:]{1,40}:$/.test(line.trim()); })[0] || lines[0])
      .replace(LABEL, "");
  }

  // The answers list: the person's own marks only, each answer once (never one shown again).
  var DOT = {none: '__DOT_NONE__', pass: '__DOT_PASS__', fail: '__DOT_FAIL__'};
  var SAID = {pass: "marked Pass", fail: "marked Fail"};
  function renderQueue() {
    var list = $("queue");
    list.textContent = "";
    var shown = 0;
    items.forEach(function (it, k) {
      if (it.again != null) { return; }
      var li = el("li"), a = el("a", "item");
      shown += 1;
      a.href = "#"; a.setAttribute("data-k", String(k));
      if (k === pos && !ended) { a.setAttribute("aria-current", "true"); }
      a.appendChild(el("span", "num", shown < 100 ? ("0" + shown).slice(-2) : String(shown)));
      var title = el("span", "q", firstLine(it));
      title.setAttribute("dir", "auto");
      a.appendChild(title);
      var dot = el("span", "dot-wrap");
      dot.setAttribute("aria-hidden", "true");
      dot.innerHTML = DOT[it.label || "none"];  // fixed icon markup only, no data
      a.appendChild(dot);
      a.appendChild(el("span", "sr", ", " + (SAID[it.label] || (it.skipped ? "skipped" :
        "not marked"))));
      li.appendChild(a); list.appendChild(li);
    });
    var now = list.querySelector("[aria-current]");
    if (now && (now.offsetTop < list.scrollTop ||
                now.offsetTop + now.offsetHeight > list.scrollTop + list.clientHeight)) {
      list.scrollTop = now.offsetTop - list.clientHeight / 2;
    }
  }
  $("queue").addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!a) { return; }
    e.preventDefault();
    walkingSkipped = false; open(+a.getAttribute("data-k")); focusCard();
  });

  // The bar: how close the first numbers are (Pass and Fail marks, each up to ROUGH; a skipped
  // answer counts for nothing); the count: the marks. The link from the first numbers on ("See
  // the numbers so far" until a coloured verdict, then "See your result"), and, from FIRST
  // answers looked at until a coloured verdict, one calm line under the bar.
  function renderProgress() {
    var marked = counts.correct + counts.wrong;
    var looked = marked + (counts.skipped || 0);
    // the bar follows how close the result is: Pass and Fail marks, each up to ROUGH
    var share = status.first ? 1 : Math.min((Math.min(counts.correct, ROUGH) +
      Math.min(counts.wrong, ROUGH)) / (2 * ROUGH), 0.9);
    var bar = $("progress"), on = Math.round(share * SEGMENTS);
    Array.prototype.forEach.call(bar.children, function (cell, i) {
      cell.classList.toggle("on", i < on); });
    bar.setAttribute("aria-valuenow", String(Math.round(share * 100)));
    bar.setAttribute("aria-valuetext", looked === 1 ? "1 answer looked at" :
      looked + " answers looked at");
    setText("count", marked + " marked");
    var see = $("see"), keep = $("keep");
    see.hidden = !status.first;
    see.textContent = status.ready ? WORDS.seeReady : WORDS.seeFirst;
    keep.hidden = status.ready || (!status.first && looked < FIRST);
    keep.textContent = status.first ? WORDS.first : WORDS.wait;
  }

  function render() {
    var it = items[pos];
    $("answer-card").hidden = false; $("end").hidden = true;
    // The state, muted; after a mark, the mark word in its colour: "Marked Pass".
    var state = $("ans-status");
    state.textContent = it.label ? "" : it.skipped ? "Skipped" : "";
    if (it.label) {
      state.appendChild(el("span", "", "Marked "));
      state.appendChild(el("span", "said " + it.label, it.label === "pass" ? "Pass" : "Fail"));
    }
    // An answer the LLM-as-a-judge graded more than once, with different grades: which run
    // this card is, never its grade.
    setText("a-run", it.run ? "Run " + it.run[0] + " of " + it.run[1] +
      ": graded differently" : "");
    $("a-run").hidden = !it.run;
    showQuestion(it);
    showAnswer(it.output);
    $("fail").setAttribute("aria-pressed", String(it.label === "fail"));
    $("pass").setAttribute("aria-pressed", String(it.label === "pass"));
    renderQueue(); renderProgress();
    busy = false; $("pass").disabled = false; $("fail").disabled = false;
    shownAt = Date.now();
  }

  function open(index) { ended = false; pos = index; render(); }

  // The next answer still to mark (or, walking the skipped ones, still skipped), from `from`.
  // An answer shown again and skipped is not shown a third time.
  function nextIndex(from) {
    for (var n = 0; n < items.length; n++) {
      var i = (from + n) % items.length, it = items[i];
      if (walkingSkipped ? it.skipped && it.again == null : (!it.label && !it.skipped)) {
        return i; }
    }
    return null;
  }

  function next() {
    // past the answers this page holds: ask for the next ones
    if (!walkingSkipped && total > items.length && pos + 1 >= items.length) {
      window.location.reload(); return; }
    var i = nextIndex(pos + 1);
    if (i === null && walkingSkipped) { walkingSkipped = false; i = nextIndex(pos + 1); }
    if (i !== null) { open(i); return; }
    if (total > items.length) { window.location.reload(); return; }
    finish();
  }

  // Nothing left to mark: the end card in the answer card's place. Every answer marked: the
  // result opens, or, when there is none yet (status.done), the end card says what comes
  // next. Some skipped: one button to look at them again (the bar keeps the link to the
  // result, to leave them out).
  function finish() {
    ended = true; busy = false;
    $("answer-card").hidden = true; $("end").hidden = false;
    renderQueue(); renderProgress();
    var skipped = items.filter(function (it) { return it.skipped && it.again == null; }).length;
    if (!skipped) {
      setText("end-title", "You marked every answer.");
      $("again").hidden = true; $("end-note").hidden = false;
      if (status.done) {
        setText("end-title", status.done[0]); setLine("end-note", status.done[1]);
        focusCard(); return;
      }
      window.location.href = url("/result");
      return;
    }
    $("end-note").hidden = true;
    setText("end-title", (skipped === 1 ? "1 skipped answer" : skipped + " skipped answers") +
      ". Look again, or leave " + (skipped === 1 ? "it" : "them") + " out.");
    setText("again", skipped === 1 ? "Look at it" : "Look at them");
    $("again").hidden = false;
    focusCard();  // the end card, not its button: no ring on open; Enter looks again
  }
  function lookAgain() { walkingSkipped = true; open(nextIndex(0)); focusCard(); }
  $("again").addEventListener("click", lookAgain);
  $("end").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target === $("end") && !$("again").hidden) {
      e.preventDefault(); lookAgain(); }
  });

  // An answer the server asks to show again, next, as any answer looks (never said); its
  // mark is sent with its slot and never counts as a mark.
  function showAgain(again) {
    if (!again) { return; }
    var it = {id: again.id, input: again.input, output: again.output, label: null,
              skipped: false, again: again.slot};
    if (again.run) { it.run = again.run; }
    items.splice(pos + 1, 0, it); total += 1;
  }

  function send(change, then) {
    if (busy) { return false; }
    busy = true; $("pass").disabled = true; $("fail").disabled = true;
    change.id = items[pos].id;
    if (items[pos].again != null) { change.again = items[pos].again; }  // shown again: its slot
    change.seconds = Math.max(0, (Date.now() - shownAt) / 1000);
    // No answer in SAVE_MS (judgekeeper stopped, or the computer slept): not saved, as below.
    var stop = new AbortController(), waited = setTimeout(function () { stop.abort(); }, SAVE_MS);
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      referrerPolicy: "same-origin", body: JSON.stringify(change), signal: stop.signal
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      clearTimeout(waited);
      if (!res.ok) { queued = []; render(); say("Not saved: " + res.body.error); return; }
      counts = res.body.summary.counts; status = res.body.summary.status;
      setText("status", "");
      showAgain(res.body.summary.again);
      then();
      if (res.body.summary.popup && !readyShown && !ended) { showReady(); }
      while (queued.length && !busy) { queued.shift()(); }
    }).catch(function () {
      clearTimeout(waited); queued = [];
      render();
      say("Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier marks are saved.");
    });
    return true;
  }

  // Each click waits LOCK_MS after the action before: a double click never marks an answer not
  // yet on screen. A key is never ignored (`key`): one pressed while a mark is saved waits for
  // it (act); a key held down does nothing.
  function locked(key) {
    var t = Date.now();
    if (t < lockUntil && !key) { return true; }
    lockUntil = t + LOCK_MS;
    return false;
  }

  // What a screen reader hears after a mark: the line is cleared, then said a moment later,
  // so the same words twice in a row are heard twice.
  var hearing;
  function hear(text) {
    setText("done", "");
    clearTimeout(hearing);
    hearing = setTimeout(function () { setText("done", text); }, 100);
  }

  function act(f) { if (busy) { queued.push(f); } else { f(); } }

  function mark(value, key) {
    if (ended || locked(key)) { return; }
    var it = items[pos];
    send({label: value}, function () {
      it.label = value; it.skipped = false; history.push(pos);
      hear(value === "pass" ? "Marked Pass." : "Marked Fail."); next(); focusCard(); });
  }

  function skip(key) {
    if (ended || locked(key)) { return; }
    var it = items[pos];
    send({deferred: true}, function () {
      it.label = null; it.skipped = true; history.push(pos);
      hear("Skipped."); next(); focusCard(); });
  }

  function undo(key) {
    if (!history.length) { say("Nothing to undo.", true); return; }
    if (locked(key)) { return; }
    var back = history.pop();
    walkingSkipped = false; open(back);
    var it = items[pos];
    send({label: null, deferred: false}, function () {
      it.label = null; it.skipped = false; hear("Undone."); render(); focusCard(); });
  }

  // Mouse presses never leave focus on a button; focus stays on the answer.
  ["fail", "pass", "skip", "undo"].forEach(function (id) {
    $(id).addEventListener("mousedown", function (e) { e.preventDefault(); });
  });
  $("fail").addEventListener("click", function () { mark("fail"); });
  $("pass").addEventListener("click", function () { mark("pass"); });
  $("skip").addEventListener("click", function () { skip(); });
  $("undo").addEventListener("click", function () { undo(); });

  // The keys: → Pass and ← Fail (shown), 1 Pass and 2 Fail (an old habit, still working),
  // S skip, Z undo (U too). A held key or any key with Cmd, Ctrl or Alt does nothing.
  var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden || !$("ready").hidden) {
      return; }
    var tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") { return; }
    var k = (e.key || "").toLowerCase();
    if (!ended && tag !== "BUTTON" && tag !== "A" && scrollAnswer(e, k)) {
      e.preventDefault(); return; }
    if (e.repeat) { return; }
    if (KEYS[k]) { act(function () { mark(KEYS[k], true); }); }
    else if (k === "s") { act(function () { skip(true); }); }
    else if (k === "z" || k === "u") { act(function () { undo(true); }); }
    else { return; }
    e.preventDefault();
  });

  // The welcome box: once per browser (the browser's storage, when it allows it). The page
  // behind it is inert. Enter or Esc starts; focus stays in the box; the button is not
  // focused, so no ring shows.
  var INTRO_KEY = "judgekeeper-intro-seen", box = $("intro-box");
  function seenIntro() {
    try { return window.localStorage.getItem(INTRO_KEY) === "1"; } catch (e) { return false; }
  }
  function startMarking() {
    $("intro").hidden = true; $("app").removeAttribute("inert");
    try { window.localStorage.setItem(INTRO_KEY, "1"); } catch (e) { /* shown again next time */ }
    focusCard();
  }
  $("intro-ok").addEventListener("click", startMarking);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); startMarking(); }
    else if (e.key === "Tab") { e.preventDefault(); $("intro-ok").focus(); }
  });

  // The result-ready box: once, when the result first turns ready (the server says so with
  // `popup`; not when the page opens already ready, nor after a reload or on another page). The page behind it is inert. Esc is "Keep marking"; Tab stays
  // between its two buttons.
  var readyShown = false, readyBox = $("ready-box");
  $("ready-see").setAttribute("href", url("/result"));
  function showReady() {
    readyShown = true; queued = [];  // keys pressed meanwhile do not mark behind the box
    setText("ready-note", status.headline || "");
    $("ready").hidden = false; $("app").setAttribute("inert", "");
    readyBox.focus();
  }
  function keepMarking() {
    $("ready").hidden = true; $("app").removeAttribute("inert");
    focusCard();
  }
  $("ready-keep").addEventListener("click", keepMarking);
  readyBox.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); keepMarking(); }
    else if (e.key === "Tab") {
      e.preventDefault();
      var order = [$("ready-see"), $("ready-keep")], at = order.indexOf(document.activeElement);
      order[at < 0 ? (e.shiftKey ? 1 : 0) : (at + 1) % 2].focus();
    }
  });

  var left = items.some(function (it) { return !it.label && !it.skipped; });
  if (left) { open(pos); } else { finish(); }
  if (!seenIntro()) {
    $("intro").hidden = false; $("app").setAttribute("inert", "");
    box.focus();
  } else if (left) { focusCard(); }
})();
</script>
</body>
</html>
"""


KEEP_GOING = "Keep going: your result appears once there are enough Pass and Fail marks."
SEE_FIRST = "See the numbers so far"  # from the first numbers until a coloured verdict
SEE_READY = "See your result"


def _progress() -> str:
    """The top bar's right: the segments by how close the result is, the count of marks, and
    the link to the result (hidden until one is ready); under them, hidden until it is
    wanted, the line that says to keep going."""
    return ('<div class="progress-box" id="progress-box"><div class="status-1"><div class="seg" id="progress" '
            'role="progressbar" aria-label="How close your result is" aria-valuemin="0" '
            'aria-valuemax="100" '
            f'aria-valuenow="0">{"<i></i>" * SEGMENTS}</div>'
            '<span class="count" id="count">0 marked</span>'
            f'<a class="see" id="see" href="#" hidden>{escape(SEE_READY)}</a></div>'
            f'<p class="keep" id="keep" hidden>{escape(KEEP_GOING)}</p></div>')


def _words() -> str:
    """The link's and the line's words, as the page's script reads them: before the first
    numbers, from them until a coloured verdict, and with one."""
    from judgekeeper.start_label import FIRST_NUMBERS

    words = {"wait": KEEP_GOING, "first": FIRST_NUMBERS, "seeFirst": SEE_FIRST,
             "seeReady": SEE_READY}
    return json.dumps(words).replace("<", "\\u003c")


def _shown(value: str) -> str:
    """A value for the page: scrubbed of credentials, without hidden characters, escaped."""
    return _text(visible(scrub(value) or ""))


def _graded(metric: str | None, rule: str | None) -> str:
    """Above the answer: the metric's name (cut at METRIC_CHARS), and the "Show the rule"
    button with the rule (cut at RULE_CHARS) when there is one. Nothing without a metric."""
    if not metric:
        return ""
    name = visible(scrub(metric) or "")
    if len(name) > METRIC_CHARS:
        name = name[:METRIC_CHARS].rstrip() + "…"
    button = box = ""
    rule = visible(scrub(rule) or "").strip() if rule else ""
    if rule:
        if len(rule) > RULE_CHARS:
            rule = rule[:RULE_CHARS].rstrip() + "…"
        button = ('<button type="button" class="quiet rule-btn" id="rule-btn" '
                  'aria-expanded="false" aria-controls="rule">Show the rule</button>')
        box = (f'<div class="rule" id="rule" hidden><p class="rule-text" id="rule-text">'
               f"{_text(rule)}</p></div>")
    return (f'<div class="graded"><span class="label">Metric</span><span class="metric-name" '
            f'id="metric-name">{_text(name)}</span>{button}</div>{box}')


def label_page(description: str | None, command: str | None = None,
               model: str | None = None, tool: str | None = None,
               held: list[str] | None = None, metric: str | None = None,
               rule: str | None = None) -> str:
    """The marking page. `command` is what the person runs to come back, with a line under
    it for each value it shows as NAME (`held`, on Windows), both scrubbed of credentials;
    `model` and `tool` name the judge in the top bar, without hidden characters
    (redact.visible). `metric` and `rule`: what the LLM-as-a-judge grades, shown above the
    answer (_graded). `description` (the app the answers came from, as the results name it)
    is not shown: the results name one source, the same on every answer.
    The server fills in __DATA__, __TOKEN__ and __NONCE__."""
    from judgekeeper.textio import PLACEHOLDER, program

    command = command or program("mark")
    left = look.meta(_text(visible(model)) if model else None,
                     _text(visible(tool)) if tool else None)
    body = (BODY.replace("__TOP__", look.top(left, _progress()))
            .replace("__GRADED__", _graded(metric, rule))
            .replace("__COMMAND__", _shown(command))
            .replace("__HELD__", "".join(f"<br><code>{_shown(f'{PLACEHOLDER}: {v}')}</code>"
                                         for v in held or ()))
            .replace("__TITLE__", _text(TITLE))
            .replace("__FIRST__", str(FIRST)).replace("__ROUGH__", str(ROUGH))
            .replace("__SEGMENTS__", str(SEGMENTS)).replace("__WORDS__", _words())
            .replace("__SHORT_Q__", str(SHORT_QUESTION))
            .replace("__SHORT_A__", str(SHORT_ANSWER)).replace("__LONG_A__", str(LONG_ANSWER))
            .replace("__BRAND__", look.BRAND)
            .replace("__CROSS__", CROSS).replace("__TICK__", TICK)
            .replace("__DOT_NONE__", DOTS["none"]).replace("__DOT_PASS__", DOTS["pass"])
            .replace("__DOT_FAIL__", DOTS["fail"]))
    return look.head("judgekeeper: mark answers", STYLE) + body


OLD_LINK_STYLE = """
main.old { max-width: 560px; margin: 0 auto; padding: 64px 24px; }
main.old .box { padding: 28px 32px; border: 1px solid var(--line); display: flex;
  flex-direction: column; gap: 12px; }
main.old h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; }
main.old p { margin: 0; font-size: 15px; color: var(--muted); }
main.old code { color: var(--text); font-size: 14px; }
"""
OLD_LINK = ("Each time judgekeeper opens its page, it makes a new private link, and older links "
            "stop working. Your marks are saved.")
OLD_LINK_CSP = ("default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src 'none'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def old_link_page() -> str:
    """What a browser gets for a link with a missing or old token: the logo only, and how to
    open the page again."""
    from judgekeeper.textio import program

    return (look.head("judgekeeper: this link no longer works", OLD_LINK_STYLE)
            + look.top("", "")
            + '<main class="old"><div class="box"><h1>This link no longer works.</h1>'
            + f"<p>{escape(OLD_LINK)}</p>"
            + f"<p>To open the page again, run <code>{escape(program('mark'))}</code>.</p>"
            + "</div></main>\n</body>\n</html>\n")
