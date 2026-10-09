"""The pages `judgekeeper start` shows: the labeling page, the review page, the fix page and
the result page.

Both are one self-contained page: no fonts, scripts or images from anywhere else. On a laptop
they have two columns (the task, and a side panel); at 760px or less, one. Light and dark
follow the computer's setting.

The labeling page shows one answer at a time, its question and answer as written, and never
anything the judge said: the page data is only ids, text and the person's own labels, set
through textContent. The side panel shows the person's progress, the judge's rule (its words
only, never a verdict) and the keys: 1 Correct, 2 Wrong, S Skip, U Undo.

The review page has the labeling page's look. Step A ("Look again") shows answers one at a
time with Correct, Wrong and Not sure, and nothing the judge said and no first label; step B
("See what your judge said") shows each disagreement with both labels and the judge's verdict
and reason, with The judge was wrong, I was wrong and The rule is unclear; after the first or
the last, an optional one-line box asks why. Text goes through textContent.

The fix page ("What your judge gets wrong") shows the judge's rule, its two kinds of mistakes
as lists that fold open, the patterns in them, the answers whose rule is unclear and, for a
judge that gives a score, the pass mark that fits best with a button that tests it. Its data
holds only the answers judgekeeper used, never those set aside; text goes through textContent.

The result page is static HTML that runs no script and loads nothing, so the copy saved as
`.judgekeeper/result.html` opens with no server. Every string in it is escaped.
"""

from __future__ import annotations

from html import escape

from judgekeeper import targets
from judgekeeper.judge_check import TITLE as JUDGE_CHECK_TITLE

LOGO = """<svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">
      <path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="#1E293B"/>
      <path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="#10B981"/>
      <path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>"""

ICONS = {  # the verdict's icon, by name: the words carry the meaning too
    "tick": ('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" '
             'stroke-width="2.5"/><path d="M7.5 12.5l3 3 6-6.5" fill="none" '
             'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
             'stroke-linejoin="round"/>'),
    "warn": ('<path d="M12 3l9.5 17h-19z" fill="none" stroke="currentColor" stroke-width="2.3" '
             'stroke-linejoin="round"/><path d="M12 10v4.5M12 17.5v.1" stroke="currentColor" '
             'stroke-width="2.5" stroke-linecap="round"/>'),
    "cross": ('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" '
              'stroke-width="2.5"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7" '
              'stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>'),
}

STYLE = """
:root { --navy: #1E293B; --green: #10B981; --bg: #FFFFFF; --bg-soft: #F8FAFC;
  --surface: #FFFFFF; --line: #E2E8F0; --text: #0F172A; --muted: #475569;
  --link: #1D4ED8; --pass: #047857; --fail: #B91C1C; --care: #B45309;
  --pass-bg: #D1FAE5; --fail-bg: #FEE2E2; --care-bg: #FEF3C7; --edge: #1E293B;
  --btn-bg: #1E293B; --btn-text: #FFFFFF; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0B1120; --bg-soft: #0F172A; --surface: #111827; --line: #1F2A3D;
    --text: #E2E8F0; --muted: #94A3B8; --link: #93C5FD; --pass: #34D399; --fail: #FCA5A5;
    --care: #FBBF24; --pass-bg: #064E3B; --fail-bg: #5B1A1A; --care-bg: #4A3510;
    --edge: #475569; --btn-bg: #E2E8F0; --btn-text: #0B1120; }
  .brand svg { background: #F8FAFC; border-radius: 7px; padding: 2px; } }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  overflow-x: hidden; }
:focus-visible { outline: 3px solid var(--link); outline-offset: 3px; border-radius: 6px; }
header { height: 56px; border-bottom: 1px solid var(--line); padding: 0 20px; display: flex;
  align-items: center; justify-content: space-between; gap: 12px; }
.brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.1rem; letter-spacing: -0.01em; }
.brand svg { width: 26px; height: 30px; }
.hdr-note { color: var(--muted); font-size: 0.9rem; }
main { max-width: 1180px; margin: 0 auto; padding: 28px 24px 32px; }
.card { border: 1px solid var(--line); border-radius: 14px; padding: 16px;
  background: var(--surface); }
.card h2 { margin: 0 0 12px; font-size: 0.78rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
kbd { font: 600 0.78rem/1 ui-monospace, Menlo, monospace; color: var(--muted);
  border: 1px solid var(--line); border-radius: 5px; padding: 3px 6px; background: var(--bg); }
code { font: 600 0.85rem ui-monospace, Menlo, monospace; background: var(--bg-soft);
  border: 1px solid var(--line); border-radius: 6px; padding: 2px 6px; white-space: nowrap; }
.saved { margin: 10px 0 0; font-size: 0.85rem; color: var(--muted); }
.btn { display: inline-block; margin-top: 8px; padding: 9px 14px; border-radius: 10px;
  border: 0; font: inherit; font-weight: 600; background: var(--btn-bg); color: var(--btn-text);
  cursor: pointer; text-decoration: none; }
"""

LABEL_STYLE = """
.label-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 28px;
  align-items: start; }
.task, .side { height: calc(100vh - 116px); min-height: 480px; }
.task, #ask { display: flex; flex-direction: column; min-width: 0; }
#ask { flex: 1 1 auto; min-height: 0; }
.where { margin: 0 0 14px; color: var(--muted); font-size: 0.92rem; display: flex;
  justify-content: space-between; gap: 16px; }
.where #about { text-align: right; }
.cap { margin: 0 0 6px; font-size: 0.75rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
.box { margin: 0 0 18px; padding: 14px 16px; border: 1px solid var(--line);
  border-radius: 12px; background: var(--bg-soft); font-size: 17px; line-height: 1.6;
  white-space: pre-wrap; overflow-wrap: anywhere; overflow: auto; }
#question { flex: 0 1 auto; max-height: 28%; }
#answer { flex: 0 1 auto; min-height: 120px; font-size: 18px;
  border-left: 4px solid var(--edge); }
.field-name { font-size: 0.75rem; font-weight: 700; color: var(--muted); }
.field + .field-name { margin-top: 10px; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.choice { font: inherit; font-size: 1.15rem; font-weight: 700; min-height: 64px;
  padding: 10px 14px; border-radius: 14px; border: 2px solid; background: var(--surface);
  cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px; }
.choice svg { width: 22px; height: 22px; flex: none; }
#correct { color: var(--pass); border-color: var(--pass); }
#wrong { color: var(--fail); border-color: var(--fail); }
#correct:hover { background: var(--pass-bg); } #wrong:hover { background: var(--fail-bg); }
.choice:disabled { cursor: default; opacity: 0.6; }
.small { display: flex; justify-content: center; gap: 24px; margin: 14px 0 0; }
.text-btn { font: inherit; font-size: 0.95rem; background: none; border: none; padding: 4px;
  color: var(--link); cursor: pointer; text-decoration: underline;
  text-underline-offset: 3px; }
#status { min-height: 1.5em; margin: 6px 0 0; color: var(--fail); font-size: 0.92rem;
  text-align: center; }
#done { margin: 32px 0; text-align: center; font-size: 1.2rem; font-weight: 650; }
.side { position: sticky; top: 16px; display: flex; flex-direction: column; gap: 14px; }
.meter { margin: 0 0 12px; }
.meter-top { display: flex; justify-content: space-between; font-weight: 700;
  margin-bottom: 5px; }
.meter-top .n { font-variant-numeric: tabular-nums; }
.meter.c .meter-top { color: var(--pass); } .meter.w .meter-top { color: var(--fail); }
.track { position: relative; height: 8px; border-radius: 999px; background: var(--line); }
.track span { position: absolute; inset: 0 auto 0 0; border-radius: 999px; }
.meter.c .track span { background: var(--pass); } .meter.w .track span { background: var(--fail); }
.track i { position: absolute; top: -3px; width: 2px; height: 14px; background: var(--muted); }
.track i.reliable { left: calc(100% - 2px); }
.marks { position: relative; height: 16px; font-size: 0.72rem; color: var(--muted);
  margin-top: 3px; }
.marks em { position: absolute; font-style: normal; white-space: nowrap; }
.marks em.rough { transform: translateX(-50%); } .marks em.reliable { right: 0; }
.ready { margin: 6px 0 10px; padding: 8px 10px; border-radius: 8px; background: var(--pass-bg);
  color: var(--pass); font-weight: 600; font-size: 0.92rem; }
.ready.not { background: var(--bg-soft); color: var(--muted); font-weight: 500; }
.seelink { font-weight: 600; color: var(--link); text-decoration: none; }
.seelink:hover { text-decoration: underline; }
.unsure { margin: 6px 0 0; color: var(--muted); font-size: 0.85rem; }
details summary { cursor: pointer; font-weight: 600; }
details p { margin: 8px 0 0; font-size: 0.95rem; white-space: pre-wrap;
  overflow-wrap: anywhere; max-height: 40vh; overflow: auto; }
details small { display: block; margin-top: 6px; color: var(--muted); }
.keys { list-style: none; margin: 0; padding: 0; font-size: 0.92rem; color: var(--muted); }
.keys li { display: flex; justify-content: space-between; padding: 3px 0; }
.tally-mini { display: none; }
@media (max-width: 760px) {
  header { padding: 0 16px; } .hdr-note { display: none; }
  main { padding: 16px 16px 24px; }
  .label-grid { grid-template-columns: 1fr; gap: 18px; }
  .task, .side { height: auto; min-height: 0; }
  .task, #ask { display: block; }
  .side { position: static; }
  .side .progress, .side .keys-card { display: none; }
  .tally-mini { display: flex; justify-content: space-between; align-items: center; gap: 8px;
    margin: 0 0 12px; font-size: 0.92rem; font-weight: 700; }
  .tally-mini .c { color: var(--pass); } .tally-mini .w { color: var(--fail); }
  #question, #answer { max-height: none; overflow: visible; }
  .choices { position: sticky; bottom: 0; margin: 0 -16px; padding: 12px 16px 14px;
    background: var(--bg); border-top: 1px solid var(--line); z-index: 2; }
  .choice { font-size: 1.05rem; min-height: 56px; }
  .choice kbd { display: none; } }
"""

RESULT_STYLE = """
.result-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 32px;
  align-items: start; }
.panel { display: flex; flex-direction: column; gap: 14px; }
h1 { font-size: 2.1rem; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.02em; }
.kind { margin: 0 0 20px; color: var(--muted); }
.sentence { font-size: 1.2rem; font-weight: 650; line-height: 1.45; margin: 0 0 10px; }
.verdict { margin: 18px 0 22px; padding: 14px 16px; border-radius: 12px;
  border-left: 6px solid; font-size: 1.05rem; display: flex; gap: 12px;
  align-items: flex-start; }
.verdict svg { width: 22px; height: 22px; flex: none; margin-top: 2px; }
.verdict strong { display: block; font-weight: 600; }
.verdict span { display: block; color: var(--text); font-size: 0.95rem; margin-top: 2px; }
.verdict.green { background: var(--pass-bg); border-color: var(--pass); color: var(--pass); }
.verdict.amber { background: var(--care-bg); border-color: var(--care); color: var(--care); }
.verdict.red { background: var(--fail-bg); border-color: var(--fail); color: var(--fail); }
.verdict.grey { background: var(--bg-soft); border-color: var(--muted); color: var(--text); }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 0 0 18px; }
.tile { border: 1px solid var(--line); border-radius: 12px; padding: 14px;
  background: var(--surface); }
.tile .lbl { font-size: 0.95rem; font-weight: 650; margin: 0 0 6px; display: flex;
  justify-content: space-between; align-items: flex-start; gap: 8px; }
.tile .abbr { flex: none; font-size: 0.72rem; font-weight: 700; letter-spacing: .04em;
  color: var(--muted); border: 1px solid var(--line); border-radius: 5px; padding: 1px 5px;
  margin-top: 1px; }
.tile .val { font-size: 1.9rem; font-weight: 750; line-height: 1.1; }
.tile .rng { font-size: 0.85rem; color: var(--muted); margin-top: 4px; }
.rangebar { position: relative; height: 6px; background: var(--line); border-radius: 999px;
  margin: 8px 0 2px; }
.rangebar span { position: absolute; top: 0; bottom: 0; border-radius: 999px;
  background: var(--muted); opacity: .55; }
.rangebar i { position: absolute; top: -4px; width: 3px; height: 14px; margin-left: -1.5px;
  border-radius: 2px; background: var(--text); }
.facts { margin: 0; padding: 14px 16px; border-radius: 12px; background: var(--bg-soft);
  border: 1px solid var(--line); }
.facts p { margin: 0 0 6px; }
.facts p:last-child { margin: 0; color: var(--muted); font-size: 0.9rem; }
.judge { margin: 0; overflow-wrap: anywhere; }
.rule { margin: 6px 0 10px; padding: 10px 12px; border-left: 3px solid var(--green);
  background: var(--bg-soft); border-radius: 0 8px 8px 0; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.meta { color: var(--muted); font-size: 0.9rem; margin: 0; overflow-wrap: anywhere; }
.next-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;
  gap: 10px; }
.next-list li { border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
.next-list b { display: block; margin-bottom: 4px; }
.review { margin: 18px 0 0; padding: 14px 16px; border-radius: 12px;
  border: 1px solid var(--line); border-left: 4px solid var(--edge); }
.review h2 { margin: 0 0 8px; font-size: 0.78rem; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
.review p { margin: 0 0 6px; }
.review .meta { margin-top: 10px; }
.files { margin: 4px 0 0; padding-left: 20px; }
.quiet { margin: 10px 0 0; color: var(--muted); font-size: 0.9rem; }
.quiet summary { cursor: pointer; }
.quiet p { margin: 6px 0 0; }
@media (max-width: 760px) {
  header { padding: 0 16px; } .hdr-note { display: none; }
  main { padding: 16px 16px 32px; }
  .result-grid { grid-template-columns: 1fr; gap: 18px; }
  .tiles { grid-template-columns: 1fr; }
  h1 { font-size: 1.7rem; }
  .sentence { font-size: 1.08rem; } }
"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__STYLE__</style>
</head>
<body>
<header>
  <div class="brand">
    __LOGO__
    judgekeeper
  </div>
  <div class="hdr-note">__NOTE__</div>
</header>
"""


def _head(title: str, style: str, note: str) -> str:
    return (HEAD.replace("__TITLE__", title).replace("__STYLE__", STYLE + style)
            .replace("__LOGO__", LOGO).replace("__NOTE__", note))


LABEL_BODY = """<main>
<div class="label-grid">
<div class="task">
  <div class="tally-mini"><span aria-live="polite" aria-atomic="true"><span class="c">Correct
    <span class="nc">0</span></span> &middot; <span class="w">Wrong
    <span class="nw">0</span></span></span>
    <a class="seelink see" href="#" hidden>See result →</a></div>
  <section id="ask" aria-labelledby="where">
    <p class="where"><span id="where"></span><span id="about">__ABOUT__</span></p>
    <div class="cap">The question</div>
    <div class="box" id="question" tabindex="0"></div>
    <div class="cap">The answer</div>
    <div class="box" id="answer" tabindex="0"></div>
    <div class="choices">
      <button class="choice" id="correct" type="button">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none"
          stroke="currentColor" stroke-width="3" stroke-linecap="round"
          stroke-linejoin="round"/></svg>
        Correct <kbd>1</kbd></button>
      <button class="choice" id="wrong" type="button">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"
          fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
        Wrong <kbd>2</kbd></button>
    </div>
    <div class="small">
      <button class="text-btn" id="skip" type="button"
        title="For an answer that cannot be judged from the text">Skip <kbd>S</kbd></button>
      <button class="text-btn" id="undo" type="button">Undo <kbd>U</kbd></button>
    </div>
    <p id="status" role="status"></p>
  </section>
  <section id="done" hidden>
    <p>Every answer is labeled.</p>
  </section>
</div>
<aside class="side" aria-label="Your progress, your judge's rule and the keys">
  <div class="card progress">
    <h2>Your progress</h2>
    __METERS__
    <p class="ready not" id="ready" aria-live="polite"></p>
    <a class="seelink see" href="#" hidden>See my result →</a>
  </div>
  __RULE_CARD__
  <div class="card keys-card">
    <h2>Keys</h2>
    <ul class="keys"><li><span>Correct</span><kbd>1</kbd></li><li><span>Wrong</span><kbd>2</kbd></li>
      <li><span>Skip</span><kbd>S</kbd></li><li><span>Undo</span><kbd>U</kbd></li></ul>
    <p class="saved">Every click is saved. Close the tab any time; run
      <code>judgekeeper start</code> to continue.</p>
  </div>
</aside>
</div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", RELIABLE = __RELIABLE__;
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var status = data.status;  // the line under the meters, from the server
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function each(selector, fn) {
    Array.prototype.forEach.call(document.querySelectorAll(selector), fn); }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }

  each(".see", function (a) { a.setAttribute("href", url("/result")); });

  function renderCounts() {
    each(".nc", function (e) { e.textContent = counts.correct; });
    each(".nw", function (e) { e.textContent = counts.wrong; });
    $("bc").style.width = Math.min(counts.correct, RELIABLE) / RELIABLE * 100 + "%";
    $("bw").style.width = Math.min(counts.wrong, RELIABLE) / RELIABLE * 100 + "%";
    setText("ready", status.text);
    $("ready").className = status.ready ? "ready" : "ready not";
    each(".see", function (a) { a.hidden = !status.ready; });
  }

  // A question is text, or [[name, value], ...]: each name a small label above its value.
  function showQuestion(value) {
    var box = $("question");
    box.textContent = "";
    if (!Array.isArray(value)) { box.textContent = value == null ? "" : String(value); return; }
    value.forEach(function (pair) {
      var name = document.createElement("div"), text = document.createElement("div");
      name.className = "field-name"; name.textContent = pair[0];
      text.className = "field"; text.textContent = pair[1];
      box.appendChild(name); box.appendChild(text);
    });
  }

  function render() {
    renderCounts();
    var it = items[pos];
    setText("where", "Answer " + (pos + 1) + " of " + items.length);
    showQuestion(it.input);
    setText("answer", it.output);
    $("question").scrollTop = 0; $("answer").scrollTop = 0;
    busy = false; $("correct").disabled = false; $("wrong").disabled = false;
  }

  function open(index) { pos = index; $("ask").hidden = false; $("done").hidden = true; render(); }

  function next() {
    for (var n = 1; n <= items.length; n++) {
      var i = (pos + n) % items.length;
      if (!items[i].label && !items[i].skipped) { open(i); return; }
    }
    renderCounts();
    $("ask").hidden = true; $("done").hidden = false;
    window.location.href = url("/result");
  }

  function send(change, then) {
    if (busy) { return; }
    busy = true; $("correct").disabled = true; $("wrong").disabled = true;
    change.id = items[pos].id;
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(change)
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { setText("status", "Not saved: " + res.body.error); render(); return; }
      counts = res.body.summary.counts; status = res.body.summary.status;
      setText("status", "");
      then();
    }).catch(function () {
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier labels are saved.");
      render();
    });
  }

  function label(value) {
    var it = items[pos];
    send({label: value}, function () {
      it.label = value; it.skipped = false; history.push(pos); next(); });
  }

  function skip() {
    var it = items[pos];
    send({deferred: true}, function () {
      it.label = null; it.skipped = true; history.push(pos); next(); });
  }

  function undo() {
    if (!history.length) { setText("status", "Nothing to undo."); return; }
    var back = history.pop();
    open(back);
    var it = items[pos];
    send({label: null, deferred: false}, function () {
      it.label = null; it.skipped = false; render(); });
  }

  $("correct").addEventListener("click", function () { label("pass"); });
  $("wrong").addEventListener("click", function () { label("fail"); });
  $("skip").addEventListener("click", skip);
  $("undo").addEventListener("click", undo);
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || $("ask").hidden) { return; }
    var k = e.key.toLowerCase();
    if (k === "1") { label("pass"); } else if (k === "2") { label("fail"); }
    else if (k === "s") { skip(); } else if (k === "u") { undo(); }
    else { return; }
    e.preventDefault();
  });

  var left = items.some(function (it) { return !it.label && !it.skipped; });
  if (left) { open(pos); } else { renderCounts(); $("ask").hidden = true; $("done").hidden = false; }
})();
</script>
</body>
</html>
"""

METER = """<div class="meter __KEY__"><div class="meter-top" aria-live="polite" aria-atomic="true">
      <span>__NAME__</span><span class="n n__KEY__">0</span></div>
      <div class="track" aria-hidden="true"><span id="b__KEY__"></span><i style="left: __AT__%"></i>
        <i class="reliable"></i></div>
      <div class="marks" aria-hidden="true"><em class="rough" style="left: __AT__%">__ROUGH__
        __FIRST_MARK__</em><em class="reliable">__RELIABLE__ __SECOND_MARK__</em></div></div>"""


def _text(value: str) -> str:
    """Text from a results file for the labeling page: escaped, and with no `_`, so it can
    never hold one of the names the server fills in (__DATA__, __TOKEN__, __NONCE__)."""
    return escape(value).replace("_", "&#95;")


def label_page(description: str | None, rule: str | None,
               marks: tuple[tuple[int, str], tuple[int, str]] = (
                   (targets.ROUGH, "rough"), (targets.RELIABLE, "reliable"))) -> str:
    """The labeling page. `marks` are the two marks on the meters, (count, name): by default
    the rough check and the reliable result. The line under the meters is the session's
    `status`, which the server sends with the data and after every label: the page works out
    nothing itself. The server fills in __DATA__, __TOKEN__ and __NONCE__."""
    (rough, first), (reliable, second) = marks
    meters = "\n    ".join(
        METER.replace("__KEY__", key).replace("__NAME__", name)
        for key, name in (("c", "Correct"), ("w", "Wrong")))
    meters = (meters.replace("__AT__", f"{rough / reliable * 100:g}")
              .replace("__ROUGH__", str(rough)).replace("__RELIABLE__", str(reliable))
              .replace("__FIRST_MARK__", first).replace("__SECOND_MARK__", second))
    card = _rule_card(rule, """Mark each answer by what you think is right. The judge's verdict stays
        hidden.""")
    body = (LABEL_BODY.replace("__METERS__", meters)
            .replace("__RELIABLE__", str(reliable))
            .replace("__RULE_CARD__", card)
            .replace("__ABOUT__", _text(description or "")))
    return (_head("judgekeeper: label answers", LABEL_STYLE,
                  "Is this answer correct? Your judge's verdict is hidden.") + body)


def _pct(x: float) -> str:
    return f"{min(max(x, 0.0), 1.0) * 100:.1f}%"


def _tile(t: dict) -> str:
    bar = ""
    if t["mark"] is not None:
        span = ("" if t["interval"] is None else
                f'<span style="left: {_pct(t["interval"][0])}; '
                f'right: {_pct(1 - t["interval"][1])}"></span>')
        bar = (f'<div class="rangebar" aria-hidden="true">{span}'
               f'<i style="left: {_pct(t["mark"])}"></i></div>')
    return (f'<div class="tile"><div class="lbl">{escape(t["plain"])} '
            f'<span class="abbr">{escape(t["name"])}</span></div>'
            f'<div class="val">{escape(t["value"])}</div>{bar}'
            f'<div class="rng">{escape(t["line"])}</div></div>')


def _verdict(v: dict) -> str:
    icon = ("" if not v["icon"] else
            f'<svg class="vicon {v["icon"]}" viewBox="0 0 24 24" aria-hidden="true" '
            f'focusable="false">{ICONS[v["icon"]]}</svg>')
    detail = f'<span>{escape(v["detail"])}</span>' if v["detail"] else ""
    return (f'<div class="verdict {v["colour"]}">{icon}'
            f'<div><strong>{escape(v["text"])}</strong>{detail}</div></div>')


def _step(s: dict, back: str | None) -> str:
    """One "What next" step: a button while the server runs, else the command."""
    if back and s["link"]:
        href = f'{s["link"]}?{back.partition("?")[2]}'
        do = f'<br><a class="btn" href="{escape(href)}">{escape(s["button"])}</a>'
    else:
        do = f' <code>{escape(s["command"])}</code>'
    return f'<li><b>{escape(s["title"])}</b>{escape(s["text"])}{do}</li>'


def _review(review: dict | None) -> str:
    """A card of lines and saved files: the review, or asking the judge again."""
    if not review:
        return ""
    files = "".join(f"<li><code>{escape(f)}</code></li>" for f in review["files"])
    return (f'<div class="review"><h2>{escape(review["title"])}</h2>'
            f'{"".join(f"<p>{escape(line)}</p>" for line in review["lines"])}'
            + (f'<p class="meta">Saved:</p><ul class="files">{files}</ul>' if files else "")
            + "</div>")


def _quiet(line: str | None) -> str:
    """Nothing found by the judge check: one quiet line, folded."""
    if not line:
        return ""
    return (f'<details class="quiet"><summary>{escape(JUDGE_CHECK_TITLE)}</summary>'
            f'<p>{escape(line)}</p></details>')


def result_page(content: dict, back: str | None = None) -> str:
    """The result as a page. `content` holds the text (see start_label.page_content); `back`
    is the link to the labeling page while the server runs, None for the saved copy, where
    each button is the command that does the same."""
    steps = "".join(_step(s, back) for s in content["next"])
    judge = content["judge"]
    quoted = f'"{judge["rule"]}"' if judge["rule"] else ""
    rule = f'<div class="rule">{escape(quoted)}</div>' if quoted else ""
    source = f'<p class="meta">{escape(judge["source"])}</p>' if judge["source"] else ""
    name = f'<b>{escape(judge["name"])}</b> · ' if judge["name"] else ""
    rate = ("" if content["pass_rate"] is None else "<p>" + "".join(
        f"<b>{escape(text)}</b>" if bold else escape(text)
        for text, bold in content["pass_rate"]) + "</p>")
    corrected = f'<p>{escape(content["corrected"])}</p>' if content["corrected"] else ""
    facts = f'<div class="facts">{rate}{corrected}</div>' if rate or corrected else ""
    return _head("judgekeeper: your result", RESULT_STYLE,
                 "How often your judge agrees with you") + f"""<main>
<div class="result-grid">
<div>
<h1>Your result</h1>
<p class="kind">{escape(content["kind"])}</p>
{"".join(f'<p class="sentence">{escape(s)}</p>' for s in content["sentences"])}
{_verdict(content["verdict"])}
<div class="tiles">{"".join(_tile(t) for t in content["tiles"])}</div>
{facts}
{_review(content.get("judge_check"))}
{_review(content.get("review"))}
{_review(content.get("again"))}
{_review(content.get("new_judge"))}
</div>
<aside class="panel">
  <div class="card">
    <h2>Your judge</h2>
    <p class="judge">{name}{escape(judge["model"])}</p>
    {rule}
    {source}
    {_quiet(content.get("judge_check_quiet"))}
  </div>
  <div class="card">
    <h2>What next</h2>
    <ul class="next-list">{steps}</ul>
    <p class="saved">Saved in <code>{escape(content["folder"])}</code> in your project. This
      page is <code>result.html</code> there.</p>
  </div>
</aside>
</div>
</main>
</body>
</html>
"""


REVIEW_STYLE = """
.task { height: auto; min-height: calc(100vh - 116px); }
#question, #reason-wrap, .said { flex-shrink: 0; }
.lead { margin: 0 0 4px; font-size: 1.25rem; font-weight: 700; letter-spacing: -.01em; }
.sub { margin: 0 0 14px; color: var(--muted); font-size: 0.95rem; }
.choices.three { grid-template-columns: repeat(3, 1fr); }
#unsure, .pick { color: var(--text); border-color: var(--edge); }
#unsure:hover, .pick:hover { background: var(--bg-soft); }
.said { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 14px; }
.said p { margin: 0; padding: 10px 14px; border: 1px solid var(--line); border-radius: 12px;
  background: var(--surface); }
.said b.pass { color: var(--pass); } .said b.fail { color: var(--fail); }
#reason { flex: 0 1 auto; max-height: 22%; font-size: 15px; }
.steps { list-style: none; margin: 0 0 12px; padding: 0; display: flex; flex-direction: column;
  gap: 6px; font-size: 0.95rem; color: var(--muted); }
.steps li { display: flex; gap: 10px; align-items: center; }
.steps span { width: 24px; height: 24px; border-radius: 999px; border: 2px solid var(--line);
  display: inline-flex; align-items: center; justify-content: center; font-weight: 700;
  font-size: 0.8rem; flex: none; }
.steps li.now { color: var(--text); font-weight: 650; }
.steps li.now span { border-color: var(--green); background: var(--green); color: #FFFFFF; }
.steps li.done span { border-color: var(--green); color: var(--green); }
.count { font-size: 1.6rem; font-weight: 750; margin: 4px 0 6px;
  font-variant-numeric: tabular-nums; }
.track.one span { background: var(--green); }
#whybox-wrap { display: flex; gap: 12px; align-items: center; margin-top: 12px; }
#whybox { flex: 1 1 auto; min-width: 0; font: inherit; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 10px; background: var(--surface);
  color: var(--text); }
@media (max-width: 760px) {
  .choices.three { grid-template-columns: 1fr; gap: 8px; }
  .choices.three .choice { min-height: 48px; }
  .said { grid-template-columns: 1fr; }
  #reason { max-height: none; overflow: visible; } }
"""

REVIEW_BODY = """<main>
<div class="label-grid">
<div class="task">
  <section id="ask" aria-labelledby="lead">
    <p class="lead" id="lead"></p>
    <p class="sub" id="sub"></p>
    <p class="where"><span id="where"></span><span id="about">__ABOUT__</span></p>
    <div class="cap">The question</div>
    <div class="box" id="question" tabindex="0"></div>
    <div class="cap">The answer</div>
    <div class="box" id="answer" tabindex="0"></div>
    <div id="verdicts" hidden>
      <div class="said"><p id="said"></p><p>Your judge said: <b id="judge"></b></p></div>
      <div id="reason-wrap"><div class="cap">Your judge's reason</div>
        <div class="box" id="reason" tabindex="0"></div></div>
    </div>
    <div class="choices three" id="look">
      <button class="choice" id="correct" type="button" data-value="pass">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none"
          stroke="currentColor" stroke-width="3" stroke-linecap="round"
          stroke-linejoin="round"/></svg>
        Correct <kbd>1</kbd></button>
      <button class="choice" id="wrong" type="button" data-value="fail">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"
          fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
        Wrong <kbd>2</kbd></button>
      <button class="choice" id="unsure" type="button" data-value="unsure">
        Not sure <kbd>3</kbd></button>
    </div>
    <div class="choices three" id="see" hidden>
      <button class="choice pick" type="button" data-value="judge_wrong">
        The judge was wrong <kbd>1</kbd></button>
      <button class="choice pick" type="button" data-value="slipped">
        I was wrong <kbd>2</kbd></button>
      <button class="choice pick" type="button" data-value="rule_unclear">
        The rule is unclear <kbd>3</kbd></button>
    </div>
    <div id="whybox-wrap" hidden>
      <input id="whybox" type="text" maxlength="300" autocomplete="off"
        placeholder="Why? (optional, helps fix your judge)"
        aria-label="Why? (optional, helps fix your judge)">
      <button class="text-btn" id="whynext" type="button">Next <kbd>Enter</kbd></button>
    </div>
    <div class="small">
      <button class="text-btn" id="undo" type="button">Undo <kbd>U</kbd></button>
    </div>
    <p id="status" role="status"></p>
  </section>
</div>
<aside class="side" aria-label="Your review, your judge's rule and the keys">
  <div class="card progress">
    <h2>Your review</h2>
    <ol class="steps">
      <li id="step-a"><span>1</span>Look again</li>
      <li id="step-b"><span>2</span>See what your judge said</li>
    </ol>
    <div class="count" id="count" aria-live="polite"></div>
    <div class="track one" aria-hidden="true"><span id="bar"></span></div>
    <p class="unsure" id="why"></p>
  </div>
  __RULE_CARD__
  <div class="card keys-card">
    <h2>Keys</h2>
    <ul class="keys" id="keys-a"><li><span>Correct</span><kbd>1</kbd></li>
      <li><span>Wrong</span><kbd>2</kbd></li><li><span>Not sure</span><kbd>3</kbd></li>
      <li><span>Undo</span><kbd>U</kbd></li></ul>
    <ul class="keys" id="keys-b" hidden><li><span>The judge was wrong</span><kbd>1</kbd></li>
      <li><span>I was wrong</span><kbd>2</kbd></li><li><span>The rule is unclear</span><kbd>3</kbd></li>
      <li><span>Undo</span><kbd>U</kbd></li></ul>
    <p class="saved">Every click is saved. Your labels stay as you gave them. Close the tab any
      time; run <code>judgekeeper start --review</code> to continue.</p>
  </div>
</aside>
</div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__";
  var TEXT = {
    a: {lead: "Look again at a few answers. Your judge's verdict is still hidden.",
        sub: "Some are answers you and your judge agreed on, so being shown one does not " +
             "mean you were wrong.",
        why: "Mark each answer by what you think is right, as if for the first time."},
    b: {lead: "See what your judge said",
        sub: "Only the answers where you and your judge disagree. What you choose here " +
             "changes no number.",
        why: "Your choices go to judge-mistakes.csv and rule-unclear.csv, to improve your " +
             "judge's rule with."}
  };
  var data = JSON.parse(document.getElementById("data").textContent);
  var step = data.step, items = data.items, pos = data.start, busy = false, history = [];
  var FIELD = step === "a" ? "second" : "choice";
  var WHY = ["judge_wrong", "rule_unclear"], lastSummary = null;  // the choices that ask why
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  var buttons = Array.prototype.slice.call(
    document.querySelectorAll(step === "a" ? "#look .choice" : "#see .choice"));

  if (step === "done") { window.location.href = url("/result"); return; }
  setText("lead", TEXT[step].lead); setText("sub", TEXT[step].sub); setText("why", TEXT[step].why);
  $("look").hidden = step !== "a"; $("see").hidden = step !== "b";
  $("keys-a").hidden = step !== "a"; $("keys-b").hidden = step !== "b";
  $("verdicts").hidden = step !== "b";
  $("step-a").className = step === "a" ? "now" : "done";
  $("step-b").className = step === "b" ? "now" : "";

  function showQuestion(value) {
    var box = $("question");
    box.textContent = "";
    if (!Array.isArray(value)) { box.textContent = value == null ? "" : String(value); return; }
    value.forEach(function (pair) {
      var name = document.createElement("div"), text = document.createElement("div");
      name.className = "field-name"; name.textContent = pair[0];
      text.className = "field"; text.textContent = pair[1];
      box.appendChild(name); box.appendChild(text);
    });
  }

  function showSaid(parts) {
    var p = $("said");
    p.textContent = "";
    parts.forEach(function (part) {
      var node = part[1] ? document.createElement("b") : document.createTextNode(part[0]);
      if (part[1]) {
        node.textContent = part[0];
        node.className = part[0] === "Correct" ? "pass" : "fail";
      }
      p.appendChild(node);
    });
  }

  function answered() { return items.filter(function (it) { return it[FIELD]; }).length; }

  function render() {
    var it = items[pos], done = answered();
    setText("where", "Answer " + (pos + 1) + " of " + items.length);
    setText("count", (done === items.length ? done : done + 1) + " of " + items.length);
    $("bar").style.width = done / items.length * 100 + "%";
    showQuestion(it.input);
    setText("answer", it.output);
    if (step === "b") {
      showSaid(it.said);
      setText("judge", it.judge);
      $("judge").className = it.judge === "Pass" ? "pass" : "fail";
      setText("reason", it.reason);
      $("reason-wrap").hidden = !it.reason;
    }
    $("question").scrollTop = 0; $("answer").scrollTop = 0;
    showWhy(it);
    busy = false;
    buttons.forEach(function (b) { b.disabled = false; });
  }

  // The why box: under the buttons once The judge was wrong or The rule is unclear is picked.
  function showWhy(it) {
    var on = step === "b" && WHY.indexOf(it.choice) >= 0;
    $("whybox-wrap").hidden = !on;
    if (on) { $("whybox").value = it.why || ""; }
  }

  function next() {
    for (var n = 1; n <= items.length; n++) {
      var i = (pos + n) % items.length;
      if (!items[i][FIELD]) { pos = i; render(); return; }
    }
    window.location.reload();
  }

  function post(change, then) {
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(change)
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { setText("status", "Not saved: " + res.body.error); render(); return; }
      setText("status", "");
      lastSummary = res.body.summary;
      then(res.body.summary);
    }).catch(function () {
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier clicks are saved.");
      render();
    });
  }

  function send(value, then) {
    if (busy) { return; }
    busy = true;
    buttons.forEach(function (b) { b.disabled = true; });
    var change = {id: items[pos].id};
    change[FIELD] = value;
    post(change, then);
  }

  // Where to go once a click is saved: the result, the other step, or the next answer.
  function after(summary) {
    if (summary.step === "done") { window.location.href = url("/result"); return; }
    if (summary.step !== step) { window.location.reload(); return; }
    next();
  }

  function choose(value) {
    var it = items[pos];
    send(value, function (summary) {
      it[FIELD] = value; history.push(pos);
      if (step === "b" && WHY.indexOf(value) >= 0) { render(); $("whybox").focus(); }
      else { after(summary); }
    });
  }

  // Save the why when it changed, then `then`.
  function saveWhy(then) {
    var it = items[pos], text = $("whybox").value.trim();
    if ($("whybox-wrap").hidden || (it.why || "") === text) { then(); return; }
    post({id: it.id, why: text || null}, function () { it.why = text || null; then(); });
  }

  function goOn() { saveWhy(function () { after(lastSummary); }); }

  function undo() {
    if (!history.length) { setText("status", "Nothing to undo."); return; }
    pos = history.pop();
    var it = items[pos];
    render();
    send(null, function () { it[FIELD] = null; it.why = null; render(); });
  }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () { choose(b.getAttribute("data-value")); });
  });
  $("undo").addEventListener("click", undo);
  $("whynext").addEventListener("click", goOn);
  $("whybox").addEventListener("blur", function () { saveWhy(function () {}); });
  $("whybox").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); goOn(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target === $("whybox")) { return; }
    var k = e.key.toLowerCase();
    if (k === "1" || k === "2" || k === "3") { choose(buttons[+k - 1].getAttribute("data-value")); }
    else if (k === "u") { undo(); }
    else { return; }
    e.preventDefault();
  });

  render();
})();
</script>
</body>
</html>
"""


def _rule_card(rule: str | None, line: str) -> str:
    return "" if not rule else f"""<div class="card">
    <h2>What are you checking?</h2>
    <details open><summary>Your judge's rule</summary>
      <p>{_text(f'"{rule}"')}</p>
      <small>{line}</small></details>
  </div>"""


def review_page(description: str | None, rule: str | None) -> str:
    """The review page, both steps: the page data says which one to show. The server fills
    in __DATA__, __TOKEN__ and __NONCE__."""
    body = (REVIEW_BODY.replace("__RULE_CARD__", _rule_card(
                rule, "Mark each answer by what you think is right."))
            .replace("__ABOUT__", _text(description or "")))
    return (_head("judgekeeper: review the disagreements", LABEL_STYLE + REVIEW_STYLE,
                  "Review the answers where you and your judge disagree") + body)


FIX_STYLE = """
main.fix { max-width: 880px; }
h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 6px; letter-spacing: -.02em; }
.kind { margin: 0 0 18px; color: var(--muted); }
.fix > .card, .fix > section { margin: 0 0 16px; }
.rule { margin: 6px 0 0; padding: 10px 12px; border-left: 3px solid var(--green);
  background: var(--bg-soft); border-radius: 0 8px 8px 0; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.patterns p { margin: 0 0 8px; font-size: 1.08rem; font-weight: 600; }
.lists { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0 0 8px; }
.list { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  background: var(--surface); }
.list > summary { font-weight: 700; }
.list { border-left: 4px solid var(--edge); }
#unclear { margin: 0 0 16px; }
.list ol { margin: 10px 0 0; padding-left: 22px; }
.list li { margin: 0 0 8px; }
.list li summary { font-weight: 500; overflow-wrap: anywhere; }
.cap { margin: 10px 0 4px; font-size: 0.75rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
.box { padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--bg-soft); white-space: pre-wrap; overflow-wrap: anywhere;
  max-height: 40vh; overflow: auto; }
.field-name { font-size: 0.75rem; font-weight: 700; color: var(--muted); }
b.pass { color: var(--pass); } b.fail { color: var(--fail); }
.meta { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
.pm p { margin: 0 0 6px; }
.pm .sentence { font-size: 1.1rem; font-weight: 650; }
.pm h3 { margin: 14px 0 6px; font-size: 1rem; }
.pm ul { margin: 0; padding-left: 20px; }
.pm code { white-space: normal; }
.btn:disabled { opacity: 0.6; cursor: default; }
#status { color: var(--fail); min-height: 1.2em; margin: 6px 0 0; }
.saved a { color: var(--link); font-weight: 600; }
@media (max-width: 760px) {
  header { padding: 0 16px; } .hdr-note { display: none; }
  main { padding: 16px 16px 32px; }
  h1 { font-size: 1.6rem; }
  .lists { grid-template-columns: 1fr; } }
"""

FIX_BODY = """<main class="fix">
<h1>What your judge gets wrong</h1>
<p class="kind" id="sub"></p>
<div class="card" id="rule-card" hidden>
  <details open><summary>Your judge's rule</summary><p class="rule" id="rule"></p></details>
</div>
<section class="patterns" id="patterns" aria-label="Patterns in your judge's mistakes"></section>
<div class="lists" id="lists"></div>
<p class="meta" id="aside"></p>
<details class="list" id="unclear"><summary></summary><ol></ol></details>
<section class="card pm" id="pm" hidden aria-labelledby="pm-title">
  <h2 id="pm-title">Move the pass mark</h2>
  <div id="pm-lines"></div>
  <button class="btn" id="pm-test" type="button" hidden></button>
  <div id="pm-result" aria-live="polite"></div>
  <p id="status" role="status"></p>
</section>
<p class="saved">Free: no AI call. Saved in <code>.judgekeeper/fix/</code>. Your own files are
  never changed. <a class="seelink" id="see" href="#">See your result</a></p>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__";
  var data = JSON.parse(document.getElementById("data").textContent);
  var $ = function (id) { return document.getElementById(id); };
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text != null) { e.textContent = String(text); }
    return e;
  }
  function question(value) {
    var box = el("div", "box");
    if (!Array.isArray(value)) { box.textContent = value == null ? "" : String(value); return box; }
    value.forEach(function (pair) {
      box.appendChild(el("div", "field-name", pair[0]));
      box.appendChild(el("div", "field", pair[1]));
    });
    return box;
  }
  function short(value) {
    var text = Array.isArray(value) ? value.map(function (p) { return p[1]; }).join(" · ")
      : String(value == null ? "" : value);
    text = text.replace(/\\s+/g, " ").trim();
    return text.length > 110 ? text.slice(0, 109) + "…" : text || "(no question)";
  }
  function items(list, ol) {
    list.forEach(function (it) {
      var li = el("li"), d = el("details"), s = el("summary", null, short(it.input));
      d.appendChild(s);
      d.appendChild(el("div", "cap", "The question")); d.appendChild(question(it.input));
      d.appendChild(el("div", "cap", "The answer")); d.appendChild(el("div", "box", it.output));
      if (it.reason) {
        d.appendChild(el("div", "cap", "Your judge's reason"));
        d.appendChild(el("div", "box", it.reason));
      }
      if (it.why) {
        d.appendChild(el("div", "cap", "Why, in your words"));
        d.appendChild(el("div", "box", it.why));
      }
      li.appendChild(d); ol.appendChild(li);
    });
  }

  $("see").setAttribute("href", url("/result"));
  $("sub").textContent = "From the " + data.used + " answers judgekeeper used. Free: no AI call.";
  if (data.rule) { $("rule-card").hidden = false; $("rule").textContent = data.rule; }
  data.lines.forEach(function (line) { $("patterns").appendChild(el("p", null, line)); });
  data.lists.forEach(function (list, n) {
    // "Passed, but you said Fail (3)", the two verdicts in their colours
    var d = el("details", "list " + (n === 0 ? "pass-wrong" : "fail-wrong")), s = el("summary");
    s.appendChild(el("b", list.judge === "Pass" ? "pass" : "fail", list.judge === "Pass" ?
      "Passed" : "Failed"));
    s.appendChild(document.createTextNode(", but you said "));
    s.appendChild(el("b", list.you === "Pass" ? "pass" : "fail", list.you));
    s.appendChild(document.createTextNode(" (" + list.items.length + ")"));
    d.appendChild(s);
    var ol = el("ol"); items(list.items, ol); d.appendChild(ol);
    if (!list.items.length) { d.appendChild(el("p", "meta", "None.")); }
    $("lists").appendChild(d);
  });
  $("aside").textContent = data.aside;
  var unclear = $("unclear");
  unclear.querySelector("summary").textContent = data.unclear.title;
  unclear.hidden = !data.unclear.items.length;
  items(data.unclear.items, unclear.querySelector("ol"));

  function renderTest(test) {
    var box = $("pm-result");
    box.textContent = "";
    if (!test) { return; }
    box.appendChild(el("p", "sentence", test.lines[0]));
    box.appendChild(el("p", null, test.lines[1]));
    test.numbers.forEach(function (line) { box.appendChild(el("p", null, line)); });
    var d = el("details"), ul = el("ul");
    d.appendChild(el("summary", null, "How sure: the ranges"));
    test.ranges.forEach(function (line) { ul.appendChild(el("li", null, line)); });
    d.appendChild(ul); box.appendChild(d);
    box.appendChild(el("h3", null, test.kind === "better" ? "Where to change it"
      : "If you still want to use it"));
    var hand = el("ul");
    test.hand_over.forEach(function (line) { hand.appendChild(el("li", null, line)); });
    box.appendChild(hand);
  }

  function renderPM() {
    var pm = data.pass_mark;
    $("pm").hidden = !pm;
    if (!pm) { return; }
    var lines = $("pm-lines");
    lines.textContent = "";
    (pm.kind === "no_follow" ? [pm.text] : pm.lines).forEach(function (line) {
      lines.appendChild(el("p", null, line));
    });
    if (pm.refusal) { lines.appendChild(el("p", "meta", pm.refusal)); }
    $("pm-test").hidden = !pm.button;
    $("pm-test").textContent = pm.button || "";
    renderTest(pm.test);
  }

  $("pm-test").addEventListener("click", function () {
    var button = $("pm-test");
    button.disabled = true;
    fetch(url("/fix/pass-mark"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mark: data.pass_mark.mark})
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      button.disabled = false;
      if (!res.ok) { $("status").textContent = "Not tested: " + res.body.error; return; }
      $("status").textContent = "";
      data.pass_mark = res.body.pass_mark;
      renderPM();
    }).catch(function () {
      button.disabled = false;
      $("status").textContent = "Not tested: this page lost its link to judgekeeper. Is it " +
        "still running in your terminal?";
    });
  });

  renderPM();
})();
</script>
</body>
</html>
"""


def fix_page(description: str | None) -> str:
    """The fix page ("What your judge gets wrong"). The server fills in __DATA__, __TOKEN__
    and __NONCE__; everything shown comes from the data, through textContent."""
    note = _text(description) if description else "What your judge gets wrong"
    return _head("judgekeeper: fix your judge", FIX_STYLE, note) + FIX_BODY
