"""The marking page and its welcome box.

One self-contained page (look.py: nothing loaded from anywhere else). It shows one answer at a
time with the person's own marks and never anything the LLM-as-a-judge decided: no grade, no
reason, no agreement (an answer it graded more than once with different grades says only which
run it is: "Run 2 of 3: graded differently"). What it grades is shown: the metric's name above the answer, and its
rule behind a "Show the rule" button when the results hold one. Text reaches it through
textContent. The server fills in __DATA__ (start_label.StartSession.state), __TOKEN__ and
__NONCE__.

So that each mark comes from a real look at the answer: Fail and Pass look the same but for
their colour; a mark or skip within FRESH_MS (250 ms) of an answer showing does nothing, an
undo waits LOCK_MS (400 ms) after the one before, and the page ignores a held key and any key
with Cmd, Ctrl or Alt. A Pass, Fail or Skip, by click or key, made while a mark saves is held
for the answer on screen when it was made: it counts only if that answer is still showing when
the save ends, else the page says it was not marked. Focus goes to the answer, never to a
button. The progress bar follows how close the result is (Pass and Fail marks, each counted up
to ROUGH; a skipped answer counts for nothing), never full before the first numbers
(status.first), and no number on the page is a target. When the result becomes ready while
the page is open, a box says so, once. In an answer or a question only `**bold**` and "- "
lines are formatted, built with createElement and createTextNode. Skipped answers come back at
the end. On a phone (760px and narrower) the card comes first, then the list.
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
/* marks that wait: a row of its own under the top bar, so a long note never covers the list */
.wait-note { flex: none; margin: 0; padding: 10px 28px; border-bottom: 1px solid var(--line);
  font-size: 13px; line-height: 1.45; color: var(--muted); overflow-wrap: anywhere; }
.wait-note code { color: var(--text); }
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
.run, .again-note { margin: -4px 0 12px; font-size: 13px; color: var(--muted); }
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
.btn.saving { cursor: default; }
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
.end.only { justify-content: center; }
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
.intro .quiet { padding: 10px 20px; }
/* The result-ready box: the last part of the answer list's column, which gets shorter while
   it shows, so it covers no answer and no Pass or Fail */
.ready { flex: none; border-top: 1px solid var(--line); }
.ready .intro { max-width: none; border: 0; padding: 28px 24px; gap: 18px; }
.ready .intro h2 { font-size: 24px; }
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
  .row-a > .graded, .row-a > .label, .row-a > .run, .row-a > .again-note { flex: none; }
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
  .wait-note { padding: 10px 16px; }
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
<p class="wait-note" id="waiting" hidden></p>
<div class="wrap">
<nav class="side" aria-label="Answers">
  <ol class="list" id="queue"></ol>
<div class="ready" id="ready" hidden>
  <div class="intro" id="ready-box" role="region" aria-labelledby="ready-title">
    __BRAND__
    <h2 id="ready-title">Your result is ready.</h2>
    <a class="go" id="ready-see" href="#">See your result</a>
    <button type="button" class="quiet" id="ready-keep">Keep marking</button>
  </div>
</div>
</nav>
<main class="main">
  <section class="card" id="answer-card" tabindex="-1" aria-label="The answer to mark">
    <div class="row row-q"><div id="q-row"><div class="label" id="q-label">Question</div><h1 class="question" id="q-text" dir="auto"></h1><button type="button" class="quiet q-more" id="q-more" aria-expanded="false" aria-controls="q-text" hidden>Show all</button></div><div class="state" id="ans-status" aria-live="polite"></div></div>
    <div class="row row-a">__GRADED__<div class="label">Answer</div><p class="again-note" id="a-again" hidden>__AGAIN__</p><p class="run" id="a-run" hidden></p><div class="a-scroll" id="a-scroll"><p class="answer" id="a-text" dir="auto"></p></div></div>
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
    <button type="button" class="go" id="again" hidden>Go back to them</button></section>
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
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", FIRST = __FIRST__, ROUGH = __ROUGH__, SEGMENTS = __SEGMENTS__, LOCK_MS = 400, SAVE_MS = 10000;
  var WORDS = __WORDS__;  // the link and the line under the bar (_words)
  var OUTPUT_WORDS = __OUTPUT_WORDS__;  // the words of a part named as an answer
  // A question up to SHORT_Q characters on one line is a heading; an answer is read at its
  // size by length (up to SHORT_A, up to LONG_A, longer).
  var SHORT_Q = __SHORT_Q__, SHORT_A = __SHORT_A__, LONG_A = __LONG_A__;
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var total = data.total || items.length;  // the page holds the next answers, not all of them
  // marks.jsonl's version as this page last saw it: another writer (an import, another
  // page) changes it, and the page takes its list again before the next answer
  var version = data.version;
  var shownAt = Date.now();  // when the answer on screen was shown: each mark sends its seconds
  var status = data.status;  // whether a result is ready, from the server
  var ended = false;         // nothing left to mark: the page says what comes next
  var walkingSkipped = false;  // "Mark them" or "Go back to them": going through the skipped ones
  var lockUntil = 0;         // an undo click is ignored until then, after the one before
  // A mark or skip within FRESH_MS of the next answer showing does nothing (`freshUntil`):
  // nobody reads an answer that fast, so it was a second press meant for the one before.
  var FRESH_MS = 250, freshUntil = 0;
  // Pressed while a mark is saved, held in order until it ends: an undo ({run}) acts then; a
  // Pass, Fail or Skip ({run, id}) acts only on the answer that was on screen when it was
  // pressed (`id`), else the page says it was not marked.
  var queued = [];
  // The result-ready box waits until no mark came for READY_WAIT_MS (`readyDue`: the server
  // said to show it), so it does not come mid-marking; it covers nothing. It opens only
  // while the result is still ready (an undo meanwhile can take it back); until it opens it
  // is owed (`readyOwed`), and opens once a later mark makes the result ready again.
  var READY_WAIT_MS = 1200, readyDue = false, readyTimer = null, readyOwed = false;
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

  // A question is text, or [[name, value], ...]. A part named as an answer (mapper's
  // OUTPUT_WORDS) that is the answer itself is left out (it shows below); any other part is
  // kept, also one whose value happens to be the answer's text. One part left shows as plain
  // text, two or more under "Input", each name a small label above its value.
  function answerPart(name) {
    return String(name).replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase()
      .split(/[^a-z0-9]+/).some(function (w) { return OUTPUT_WORDS.indexOf(w) > -1; });
  }
  function question(it) {
    var value = it.input;
    if (!Array.isArray(value)) { return value == null ? "" : String(value); }
    var answer = String(it.output == null ? "" : it.output).trim();
    value = value.filter(function (pair) {
      return !(answerPart(pair[0]) && String(pair[1]).trim() === answer);
    });
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
    fitAnswer(); fade(); fitQuestion(); fitRule(); edges(); fitEnd(); });
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
  // Drawn in place: each row's link is kept and only its text, icon and state change, rows
  // added or taken away only as the list grows or shrinks, so a click pressed on a row while
  // a mark is saved still lands on it when it is let go.
  var DOT = {none: '__DOT_NONE__', pass: '__DOT_PASS__', fail: '__DOT_FAIL__'};
  var SAID = {pass: "marked Pass", fail: "marked Fail"};
  function newRow() {
    var li = el("li"), a = el("a", "item"), title = el("span", "q"), dot = el("span", "dot-wrap");
    a.href = "#";
    title.setAttribute("dir", "auto");
    dot.setAttribute("aria-hidden", "true");
    a.appendChild(el("span", "num")); a.appendChild(title); a.appendChild(dot);
    a.appendChild(el("span", "sr"));
    li.appendChild(a);
    return li;
  }
  function setRow(a, it, k, shown) {
    var parts = a.children, dot = it.label || "none";
    a.setAttribute("data-k", String(k));
    if (k === pos && !ended) { a.setAttribute("aria-current", "true"); }
    else { a.removeAttribute("aria-current"); }
    parts[0].textContent = shown < 100 ? ("0" + shown).slice(-2) : String(shown);
    parts[1].textContent = firstLine(it);
    if (parts[2].getAttribute("data-dot") !== dot) {  // the icon only when it changes
      parts[2].setAttribute("data-dot", dot);
      parts[2].innerHTML = DOT[dot];  // fixed icon markup only, no data
    }
    parts[3].textContent = ", " + (SAID[it.label] || (it.skipped ? "skipped" : "not marked"));
  }
  function renderQueue() {
    var list = $("queue"), shown = 0;
    items.forEach(function (it, k) {
      if (it.again != null) { return; }
      if (!list.children[shown]) { list.appendChild(newRow()); }
      setRow(list.children[shown].children[0], it, k, shown + 1);
      shown += 1;
    });
    while (list.children.length > shown) {
      list.removeChild(list.children[list.children.length - 1]); }
    showCurrent();
  }
  // The answer being marked stays in view in the list (also when the list gets shorter).
  function showCurrent() {
    var list = $("queue"), now = list.querySelector("[aria-current]");
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
    var toward = counts.toward || counts;  // a mark that waits counts for nothing
    var share = status.first ? 1 : Math.min((Math.min(toward.correct, ROUGH) +
      Math.min(toward.wrong, ROUGH)) / (2 * ROUGH), 0.9);
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
    // the answers, without the cards shown again (each adds one to `total`, never a mark)
    var answers = total - items.filter(function (it) { return it.again != null; }).length;
    var few = status.few;  // fewer answers than a first result needs: said at once
    keep.hidden = status.ready || status.only_wait || (!status.first && looked < FIRST && !few);
    // only skipped answers left (nothing else to mark): what the card in the middle says
    var skippedLeft = counts.skipped || 0, onlySkipped = skippedLeft > 0 && looked >= answers;
    keep.textContent = onlySkipped ? (skippedLeft === 1 ? WORDS.skippedOne : WORDS.skippedMany
      ).replace("{n}", String(skippedLeft)) : status.first ? WORDS.first
      : few ? WORDS.few : status.group || WORDS.wait;
    $("waiting").hidden = !status.waiting;  // marks the LLM-as-a-judge never graded: once, here
    if (status.waiting) { setLine("waiting", status.waiting); }
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
    $("a-again").hidden = it.again == null;  // a marked answer back to check the marks: said
    showQuestion(it);
    showAnswer(it.output);
    $("fail").setAttribute("aria-pressed", String(it.label === "fail"));
    $("pass").setAttribute("aria-pressed", String(it.label === "pass"));
    renderQueue(); renderProgress();
    busy = false; saving(false);
    shownAt = Date.now();
  }

  // A new answer opens with no word from the one before ("Marked Fail." was about that one)
  function open(index) { ended = false; pos = index; clearTimeout(hearing); setText("done", ""); render(); }

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
    if (i !== null) { open(i); freshUntil = Date.now() + FRESH_MS; return; }
    if (total > items.length) { window.location.reload(); return; }
    finish(changing);
  }

  // Nothing left to mark: the end card in the answer card's place. Every answer marked: the
  // result opens, or, when there is none yet (status.done), the end card says what comes
  // next. Some skipped: one button to look at them again (the bar keeps the link to the
  // result, to leave them out). `stay`: every answer was marked already (the page opened so,
  // or a mark was changed): the card says how to change a mark, and Z undoes as usual.
  var changing = false;
  function finish(stay) {
    ended = true; busy = false;
    $("answer-card").hidden = true; $("end").hidden = false; $("end").classList.remove("only");
    fitEnd();
    renderQueue(); renderProgress();
    var skipped = items.filter(function (it) { return it.skipped && it.again == null; }).length;
    if (!skipped) {
      setText("end-title", "You marked every answer.");
      $("again").hidden = true; $("end-note").hidden = false;
      setText("end-note", "Opening your result\u2026");
      if (status.done) {
        setText("end-title", status.done[0]); setLine("end-note", status.done[1]);
        focusCard(); return;
      }
      if (stay) {  // a mark can still be changed; the bar links to the result
        changing = true;
        var n = counts.correct + counts.wrong;
        setText("end-title", n === 1 ? "You have marked the one answer."
                                     : "You have marked all " + n + " answers.");
        setText("end-note", WORDS.change);
        focusCard(); return;
      }
      window.location.href = url("/result");
      return;
    }
    $("end-note").hidden = true;
    // no coloured result yet: a mark more, or more answers, can bring it; with one, the
    // skipped answers can be left out
    setText("end-title", status && status.ready
      ? (skipped === 1 ? "You skipped one answer. Go back to it, or leave it out."
                       : "You skipped " + skipped +
                         " answers. Go back to them, or leave them out.")
      : (skipped === 1 ? WORDS.skippedOne : WORDS.skippedMany).replace("{n}", String(skipped)));
    var ready = !!(status && status.ready);  // else only the skipped answers are left: centred
    setText("again", ready ? (skipped === 1 ? "Go back to it" : "Go back to them")
      : (skipped === 1 ? "Mark it" : "Mark them"));
    $("end").classList.toggle("only", !ready);
    fitEnd();
    $("again").hidden = false;
    focusCard();  // the end card, not its button: no ring on open; Enter looks again
  }
  // On a phone the list follows the card: the card alone fills the rest of the screen, so
  // its words sit in the middle as they do beside the list
  function fitEnd() {
    var e = $("end");
    e.style.minHeight = "";
    if (e.hidden || !e.classList.contains("only") || !media("(max-width: 760px)")) { return; }
    var top = e.getBoundingClientRect().top + (window.scrollY || 0);
    e.style.minHeight = Math.max(0, window.innerHeight - top) + "px";
  }
  function lookAgain() { walkingSkipped = true; open(nextIndex(0)); focusCard(); }
  $("again").addEventListener("click", lookAgain);
  $("end").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target === $("end") && !$("again").hidden) {
      e.preventDefault(); lookAgain(); }
  });

  // An answer the server asks to show again, next; its card says it was seen before
  // (AGAIN). Its mark is sent with its slot and never counts as a mark.
  function showAgain(again) {
    if (!again) { return; }
    var it = {id: again.id, input: again.input, output: again.output, label: null,
              skipped: false, again: again.slot};
    if (again.run) { it.run = again.run; }
    items.splice(pos + 1, 0, it); total += 1;
  }

  // A card shown again whose answer's first mark was just changed: the server took it back
  // (`dropped`, its slot). The places after it move up one, also in the undo list.
  function dropAgain(slot) {
    if (slot == null) { return; }
    for (var k = items.length - 1; k >= 0; k--) {
      if (items[k].again !== slot) { continue; }
      items.splice(k, 1); total -= 1;
      if (k < pos) { pos -= 1; }
      history = history.filter(function (h) { return h.pos !== k; })
        .map(function (h) { return h.pos > k ? {pos: h.pos - 1, was: h.was} : h; });
    }
  }

  // The list and counts again (/state), as a reload gives them, when someone else wrote marks
  // since this page last looked: the next answer is then one still to mark.
  function refresh(heard, popup) {
    fetch(url("/state"), {referrerPolicy: "same-origin"}).then(function (r) {
      return r.json();
    }).then(function (s) {
      items = s.items; total = s.total || items.length; counts = s.counts; status = s.status;
      version = s.version; history = []; walkingSkipped = false;
      if (nextIndex(0) !== null) { open(s.start); focusCard(); } else { finish(); }
      var lost = queued.some(function (q) { return q.id !== undefined; });
      queued = [];
      if (lost) { notMarked(heard); } else { hear(heard); }
      if (popup) { readyLater(); }
    }).catch(function () { window.location.reload(); });
  }

  function send(change, then, heard) {
    if (busy) { return false; }
    busy = true; saving(true);
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
      var stale = res.body.summary.before != null && res.body.summary.before !== version;
      if (res.body.summary.version != null) { version = res.body.summary.version; }
      if (stale) { refresh(heard, res.body.summary.popup); return; }
      dropAgain(res.body.summary.dropped);
      showAgain(res.body.summary.again);
      then();
      if (res.body.summary.popup || readyOwed && !readyDue && status && status.ready) {
        readyLater(); }
      drain(heard);
    }).catch(function () {
      clearTimeout(waited); queued = [];
      render();
      say(WORDS.noAnswer);
    });
    return true;
  }

  // An undo click waits LOCK_MS after the one before: a double click undoes one mark. A mark
  // or skip, by click or key, does nothing within FRESH_MS of its answer showing (fresh), so a
  // double click never marks an answer not yet read; any later click marks the answer on
  // screen. A Pass, Fail or Skip, by click or key, made while a mark is saved waits for it
  // (press), for the answer on screen when it was made; an undo key waits for it too (act); a
  // key held down does nothing.
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

  function act(f) { if (busy) { queued.push({run: f}); } else { f(); } }

  function fresh() { return Date.now() < freshUntil; }

  // The buttons stay clickable while a mark saves (a click on a disabled one is lost without a
  // word); the cursor alone shows it.
  function saving(on) {
    $("pass").classList.toggle("saving", on); $("fail").classList.toggle("saving", on);
  }

  // The start of the question on screen, as the line below names the answer to mark.
  function shownQuestion() {
    var v = items[pos] ? question(items[pos]) : "";
    if (Array.isArray(v)) { v = v.map(function (pair) { return pair[1]; }).join(" "); }
    v = String(v).replace(/[ \\t\\r\\n]+/g, " ").trim();
    if (!v) { return "the next answer"; }
    return '"' + (v.length > 40 ? v.slice(0, 40).trim() + "..." : v) + '"';
  }

  // A held click or key that is not used: said on screen and aloud, never dropped in silence.
  function notMarked(heard) {
    var line = WORDS.notMarked.replace("{shown}", function () { return shownQuestion(); });
    say(line);
    hear((heard ? heard + " " : "") + line);
  }

  // After a save: what was held acts, in order, if its answer is the one on screen; else the
  // page says so once.
  function drain(heard) {
    var lost = false;
    while (queued.length && !busy) {
      var held = queued.shift();
      if (held.id === undefined || (!ended && items[pos] && items[pos].id === held.id)) {
        held.run();
      } else { lost = true; }
    }
    if (lost) { notMarked(heard); }
  }

  // A Pass, Fail or Skip: nothing within FRESH_MS of an answer showing (a double click, on
  // purpose without a word); while a mark saves it is held for the answer on screen now.
  function press(run) {
    if (ended || fresh()) { return; }
    if (busy) { queued.push({run: run, id: items[pos].id}); } else { run(); }
  }

  function mark(value) { press(function () { markNow(value); }); }

  function markNow(value) {
    closeReady();  // marking goes on: the box goes
    if (readyDue) { readyLater(); }  // still marking: the box waits
    var it = items[pos];
    var heard = value === "pass" ? "Marked Pass." : "Marked Fail.";
    var was = it.label;  // a mark changed: Z puts it back, and the result doesn't open
    if (was) { changing = true; }
    send({label: value}, function () {
      it.label = value; it.skipped = false; history.push({pos: pos, was: was});
      next(); hear(heard); focusCard(); }, heard);
  }

  function skip() { press(skipNow); }

  function skipNow() {
    closeReady();
    if (readyDue) { readyLater(); }
    var it = items[pos], was = it.label;
    send({deferred: true}, function () {
      it.label = null; it.skipped = true; history.push({pos: pos, was: was});
      next(); hear("Skipped."); focusCard(); }, "Skipped.");
  }

  // Z: a first mark (or skip) is taken back; a changed mark goes back to the mark it had (an
  // ordinary mark line in marks.jsonl, so every step stays there).
  function undo(key) {
    if (!history.length) { say("Nothing to undo.", true); return; }
    if (locked(key)) { return; }
    closeReady();  // an undo can take the result back below ready
    var back = history.pop();
    walkingSkipped = false; open(back.pos);
    var it = items[pos];
    send({label: back.was, deferred: false}, function () {
      it.label = back.was; it.skipped = false; hear("Undone."); render(); focusCard(); },
      "Undone.");
  }

  // Mouse presses never leave focus on a button; focus stays on the answer. A press counts on
  // mouseup, after a mousedown on the same button: a tool that sends no click count (Chrome's
  // DevTools Protocol) gives those two and no click event. The click event that follows a
  // press is not counted again (`pressed`); a click with no mouse events before it (a button
  // reached from the keyboard) counts.
  var DO = {fail: function () { mark("fail"); }, pass: function () { mark("pass"); },
            skip: function () { skip(); }, undo: function () { undo(); }};
  var down = null, pressed = false;
  Object.keys(DO).forEach(function (id) {
    var button = $(id);
    button.addEventListener("mousedown", function (e) {
      e.preventDefault(); if (!e.button) { down = id; } });
    button.addEventListener("mouseup", function (e) {
      var from = down; down = null;
      if (e.button || from !== id) { return; }
      pressed = true; setTimeout(function () { pressed = false; }, 0);
      DO[id]();
    });
    button.addEventListener("click", function () { if (!pressed) { DO[id](); } });
  });

  // The keys: → Pass and ← Fail (shown), 1 Pass and 2 Fail (an old habit, still working),
  // S skip, Z undo (U too). A held key or any key with Cmd, Ctrl or Alt does nothing.
  var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden) { return; }
    if (e.key === "Escape" && !$("ready").hidden) { e.preventDefault(); keepMarking(); return; }
    var tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") { return; }
    var k = (e.key || "").toLowerCase();
    if (!ended && tag !== "BUTTON" && tag !== "A" && scrollAnswer(e, k)) {
      e.preventDefault(); return; }
    if (e.repeat) { return; }
    if (KEYS[k]) { mark(KEYS[k]); }
    else if (k === "s") { skip(); }
    else if (k === "z" || k === "u") { act(function () { undo(true); }); }
    else { return; }
    e.preventDefault();
  });

  // The welcome box: while the project has no marks yet (the server says so with `intro`),
  // on any port and in any browser. The page behind it is inert. Enter or Esc starts; focus
  // stays in the box; the button is not focused, so no ring shows.
  var box = $("intro-box");
  function startMarking() {
    $("intro").hidden = true; $("app").removeAttribute("inert");
    shownAt = Date.now();  // the answer is on screen from now
    freshUntil = shownAt + FRESH_MS;  // and a key within FRESH_MS of it is not meant for it
    focusCard();
  }
  $("intro-ok").addEventListener("click", startMarking);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); startMarking(); }
    else if (e.key === "Tab") { e.preventDefault(); $("intro-ok").focus(); }
  });

  // The result-ready box: once, when the result first turns ready (the server says so with
  // `popup`; not when the page opens already ready, nor after a reload or on another page),
  // after READY_WAIT_MS with no mark (readyLater). It is not modal: focus stays on the card,
  // whose buttons and keys keep working; a mark, skip or undo closes it, and so does Esc or
  // "Keep marking".
  var readyShown = false;
  $("ready-see").setAttribute("href", url("/result"));
  function readyLater() {
    readyDue = true; readyOwed = true; clearTimeout(readyTimer);
    readyTimer = setTimeout(function () {
      readyDue = false;
      if (readyShown || ended) { return; }
      if (busy) { readyLater(); }
      else if (status && status.ready) { showReady(); }
    }, READY_WAIT_MS);
  }
  function showReady() {
    readyShown = true; readyOwed = false;
    $("ready").hidden = false;
    showCurrent();  // the list is shorter now
    hear($("ready-title").textContent);  // the status line says it: focus stays on the card
  }
  function closeReady() { $("ready").hidden = true; }
  function keepMarking() { closeReady(); focusCard(); }
  $("ready-keep").addEventListener("click", keepMarking);

  var left = items.some(function (it) { return !it.label && !it.skipped; });
  if (left) { open(pos); } else { finish(true); }
  if (left && data.intro === true) {  // nothing left to mark: no box over "You have marked all"
    $("intro").hidden = false; $("app").setAttribute("inert", "");
    box.focus();
  } else if (left) { focusCard(); }
})();
</script>
</body>
</html>
"""


KEEP_GOING = "Keep going: your result appears once there are enough Pass and Fail marks."
FEW_ANSWERS = "A first result needs at least {n} answers. Your marks are kept for when more answers come."
SEE_FIRST = "See the numbers so far"  # from the first numbers until a coloured verdict
SEE_READY = "See your result"
# On the card of a marked answer shown again to check the marks (start_label's repeats)
AGAIN = "You saw this answer before. Mark it as you see it now."


def _progress() -> str:
    """The top bar's right: the segments by how close the result is, the count of marks, and
    the link to the numbers (hidden until the first numbers, status.first); under them,
    hidden until it is wanted, the line that says to keep going."""
    return ('<div class="progress-box" id="progress-box"><div class="status-1"><div class="seg" id="progress" '
            'role="progressbar" aria-label="How close your first numbers are" aria-valuemin="0" '
            'aria-valuemax="100" '
            f'aria-valuenow="0">{"<i></i>" * SEGMENTS}</div>'
            '<span class="count" id="count">0 marked</span>'
            f'<a class="see" id="see" href="#" hidden>{escape(SEE_READY)}</a></div>'
            f'<p class="keep" id="keep" hidden>{escape(KEEP_GOING)}</p></div>')


# Gone, or no answer: the footer names the command, as typed where it ran (and NAME's lines)
NO_ANSWER = ("Not saved: judgekeeper's marking page isn't answering. To open it again, run "
             "the command at the bottom of this page. Your marks are kept.")
# A click or key made while a mark was saving, for an answer no longer on screen: the page
# puts in the answer now showing ({shown}: the start of its question)
NOT_MARKED = ("Not marked: your last click or key came while a mark was saving. Showing now: "
              "{shown}. Mark it again.")


def _words() -> str:
    """The link's and the line's words, as the page's script reads them: before the first
    numbers, from them until a coloured verdict, and with one; and the line said when a mark
    can't be saved."""
    from judgekeeper.front import CHANGE_MARK
    from judgekeeper.start import MIN_POOL
    from judgekeeper.start_label import FIRST_NUMBERS, ONLY_SKIPPED_CARD, only_skipped

    words = {"wait": KEEP_GOING, "first": FIRST_NUMBERS, "seeFirst": SEE_FIRST,
             "seeReady": SEE_READY, "noAnswer": NO_ANSWER, "notMarked": NOT_MARKED,
             "change": CHANGE_MARK,
             # the end card with only skipped answers left; the page puts in their number
             "skippedOne": only_skipped(1, ONLY_SKIPPED_CARD),
             "skippedMany": only_skipped(2, ONLY_SKIPPED_CARD).replace("2", "{n}"),
             # fewer answers than a first result needs (start.MIN_POOL): as `mark` says it
             "few": FEW_ANSWERS.format(n=MIN_POOL)}
    # no `_` either: a command can never hold a name the server fills in (_text)
    return json.dumps(words).replace("<", "\\u003c").replace("_", "\\u005f")


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
    from judgekeeper.mapper import OUTPUT_WORDS
    from judgekeeper.textio import PLACEHOLDER, program

    command = command or program("mark")
    left = look.meta(_text(visible(model)) if model else None,
                     _text(visible(tool)) if tool else None)
    body = (BODY.replace("__TOP__", look.top(left, _progress()))
            .replace("__GRADED__", _graded(metric, rule))
            .replace("__COMMAND__", look.command(_shown(command)))
            .replace("__HELD__", "".join(f"<br><code>{_shown(f'{PLACEHOLDER}: {v}')}</code>"
                                         for v in held or ()))
            .replace("__TITLE__", _text(TITLE))
            .replace("__AGAIN__", _text(AGAIN))
            .replace("__FIRST__", str(FIRST)).replace("__ROUGH__", str(ROUGH))
            .replace("__SEGMENTS__", str(SEGMENTS)).replace("__WORDS__", _words())
            .replace("__OUTPUT_WORDS__", json.dumps(OUTPUT_WORDS))
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


WRONG_HOST = ("Open the link as judgekeeper printed it. It starts with "
              "http://127.0.0.1:{port}/.")


def wrong_host_page(port: int) -> str:
    """What a browser gets for the page under another host name (`localhost`): how to open
    it. Nothing else: the Host check guards the marks against DNS rebinding."""
    return (look.head("judgekeeper: open the printed link", OLD_LINK_STYLE)
            + look.top("", "")
            + '<main class="old"><div class="box"><h1>Open the printed link.</h1>'
            + f"<p>{escape(WRONG_HOST.format(port=int(port)))}</p>"
            + "</div></main>\n</body>\n</html>\n")


def old_link_page() -> str:
    """What a browser gets for a link with a missing or old token: the logo only, and how to
    open the page again."""
    from judgekeeper.textio import program

    return (look.head("judgekeeper: this link no longer works", OLD_LINK_STYLE)
            + look.top("", "")
            + '<main class="old"><div class="box"><h1>This link no longer works.</h1>'
            + f"<p>{escape(OLD_LINK)}</p>"
            + f"<p>To open the page again, run <code>{look.command(escape(program('mark')))}"
            "</code>.</p>"
            + "</div></main>\n</body>\n</html>\n")
