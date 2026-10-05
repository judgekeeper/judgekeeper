"""A branded labeling page, one answer at a time; unused for now, kept for real labeling."""

TRY_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>judgekeeper: try it</title>
<style>
:root { --navy: #1E293B; --green: #10B981; --bg: #FFFFFF; --bg-soft: #F8FAFC;
  --surface: #FFFFFF; --line: #E2E8F0; --text: #0F172A; --muted: #475569;
  --accent-text: #047857; --link: #1D4ED8; --pass: #047857; --fail: #B91C1C;
  --pass-bg: #D1FAE5; --fail-bg: #FEE2E2; --btn-bg: #1E293B; --btn-fg: #FFFFFF;
  color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0B1120; --bg-soft: #0F172A; --surface: #111827; --line: #1F2A3D;
    --text: #E2E8F0; --muted: #94A3B8; --accent-text: #34D399; --link: #93C5FD;
    --pass: #34D399; --fail: #FCA5A5; --pass-bg: #064E3B; --fail-bg: #5B1A1A;
    --btn-bg: #E2E8F0; --btn-fg: #0B1120; }
  .brand svg { background: #F8FAFC; border-radius: 8px; padding: 3px; } }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 17px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
:focus-visible { outline: 3px solid var(--link); outline-offset: 3px; border-radius: 6px; }
header { border-bottom: 1px solid var(--line); padding: 18px 16px 16px; text-align: center; }
.brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.15rem; letter-spacing: -0.01em; }
.brand svg { width: 28px; height: 32px; }
.intro { margin: 6px 0 0; color: var(--muted); font-size: 0.98rem; }
main { max-width: 36rem; margin: 0 auto; padding: 40px 16px 56px; text-align: center; }
.progress { display: flex; justify-content: center; gap: 6px; margin: 0 0 10px; }
.progress span { width: 34px; height: 6px; border-radius: 999px; background: var(--line); }
.progress span.done { background: var(--green); }
.progress span.now { background: var(--navy); }
@media (prefers-color-scheme: dark) { .progress span.now { background: #E2E8F0; } }
.count { margin: 0; color: var(--muted); font-size: 0.9rem; }
h1 { font-size: clamp(2.2rem, 8vw, 3.4rem); line-height: 1.15; letter-spacing: -0.02em;
  margin: 18px 0 26px; }
.said { margin: 0 0 6px; color: var(--muted); font-size: 0.95rem; }
.answer { display: inline-block; min-width: 4.5rem; margin: 0 0 34px; padding: 6px 26px;
  border: 2px dashed var(--line); border-radius: 14px; background: var(--bg-soft);
  font-size: clamp(2.4rem, 9vw, 3.4rem); font-weight: 700; line-height: 1.3;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.choice { font: inherit; font-size: 1.2rem; font-weight: 700; min-height: 68px;
  padding: 10px 14px; border-radius: 14px; border: 2px solid; background: var(--surface);
  cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px; }
.choice svg { width: 22px; height: 22px; flex: none; }
.choice kbd { font: 600 0.8rem/1 ui-monospace, Menlo, monospace; color: var(--muted);
  border: 1px solid var(--line); border-radius: 5px; padding: 3px 6px; }
#correct { color: var(--pass); border-color: var(--pass); }
#wrong { color: var(--fail); border-color: var(--fail); }
#correct:hover, #correct.chosen { background: var(--pass-bg); }
#wrong:hover, #wrong.chosen { background: var(--fail-bg); }
.choice:disabled { cursor: default; }
.keys { margin: 14px 0 0; color: var(--muted); font-size: 0.85rem; }
#status { min-height: 1.6em; margin: 12px 0 0; color: var(--fail); font-size: 0.95rem; }
#result { text-align: left; }
#result h1 { text-align: center; outline: none; margin: 4px 0 22px; }
.first { font-size: 1.35rem; font-weight: 700; line-height: 1.4; margin: 0 0 16px; }
.lines { list-style: none; margin: 0 0 22px; padding: 0; }
.lines li { border-left: 4px solid var(--green); background: var(--bg-soft);
  border-radius: 0 10px 10px 0; padding: 10px 14px; margin: 0 0 10px; }
.tiny { color: var(--muted); margin: 0 0 30px; }
h2 { font-size: 1.3rem; margin: 0 0 12px; padding-top: 24px; border-top: 1px solid var(--line); }
.btn { display: inline-block; padding: 12px 20px; border-radius: 10px; font-weight: 600;
  text-decoration: none; background: var(--btn-bg); color: var(--btn-fg); }
.more { margin: 14px 0 0; font-size: 0.95rem; }
.more a { color: var(--link); text-underline-offset: 2px; }
.closing { margin: 30px 0 0; color: var(--muted); font-size: 0.9rem; }
@media (max-width: 420px) {
  main { padding-top: 28px; }
  .choice { font-size: 1.05rem; min-height: 60px; }
  .choice kbd { display: none; } }
@media (prefers-reduced-motion: no-preference) {
  .choice { transition: background-color 0.12s ease; } }
</style>
</head>
<body>
<header>
  <div class="brand">
    <svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">
      <path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="#1E293B"/>
      <path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="#10B981"/>
      <path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    judgekeeper
  </div>
  <p class="intro" id="intro">Is this answer correct? Choose one. 5 questions.</p>
</header>
<main>
<section id="ask" aria-labelledby="question">
  <div class="progress" id="bar" aria-hidden="true"></div>
  <p class="count" id="count" aria-live="polite"></p>
  <h1 id="question"></h1>
  <p class="said">The answer</p>
  <div class="answer" id="answer"></div>
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
  <p class="keys">Or press 1 for Correct and 2 for Wrong.</p>
</section>
<section id="result" aria-labelledby="result-title" hidden>
  <h1 id="result-title">Your result</h1>
  <p class="first" id="first"></p>
  <ul class="lines" id="lines"></ul>
  <p class="tiny">This was a tiny example. With your own app you would label 30 to 100
    answers.</p>
  <h2>What next</h2>
  <p><a class="btn" href="https://www.judgekeeper.com/own-metric.html">Check your own
    LLM-as-a-judge</a></p>
  <p class="more">Or see <a href="https://www.judgekeeper.com/start.html">how to use it on
    your app</a>.</p>
  <p class="closing">The same result is in your terminal. You can close this tab.</p>
</section>
<p id="status" role="status"></p>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__";
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, labels = data.labels, pos = data.start, busy = false;
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }

  setText("intro", "Is this answer correct? Choose one. " + items.length + " questions.");

  function render() {
    var it = items[pos], bar = $("bar");
    while (bar.firstChild) { bar.removeChild(bar.firstChild); }
    items.forEach(function (other, n) {
      var seg = document.createElement("span");
      seg.className = n === pos ? "now" : (other.label || other.deferred ? "done" : "");
      bar.appendChild(seg);
    });
    setText("count", "Question " + (pos + 1) + " of " + items.length);
    setText("question", it.input);
    setText("answer", it.output);
    $("correct").className = "choice"; $("wrong").className = "choice";
    busy = false; $("correct").disabled = false; $("wrong").disabled = false;
  }

  function showResult(body) {
    var lines = body.lines || [];
    setText("first", lines[0]);
    var ul = $("lines");
    while (ul.firstChild) { ul.removeChild(ul.firstChild); }
    lines.slice(1).forEach(function (line) {
      var li = document.createElement("li"); li.textContent = line; ul.appendChild(li); });
    $("ask").hidden = true; $("result").hidden = false;
    setText("intro", "Done. Here is how the judge did against your answers.");
    $("result-title").setAttribute("tabindex", "-1");
    $("result-title").focus();
  }

  function fetchResult() {
    fetch(url("/result")).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { setText("status", "No result yet: " + res.body.error); return; }
      showResult(res.body);
    }).catch(function () {
      setText("status", "This page lost its link to judgekeeper. The result is in your " +
        "terminal.");
    });
  }

  function next() {
    for (var n = 1; n <= items.length; n++) {
      var i = (pos + n) % items.length;
      if (!items[i].label && !items[i].deferred) { pos = i; render(); return; }
    }
    fetchResult();
  }

  function answer(which) {
    if (busy || !$("result").hidden) { return; }
    busy = true; $("correct").disabled = true; $("wrong").disabled = true;
    $(which === 0 ? "correct" : "wrong").className = "choice chosen";
    var it = items[pos];
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: it.id, label: labels[which]})
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { setText("status", "Not saved: " + res.body.error); render(); return; }
      it.label = labels[which]; setText("status", "");
      next();
    }).catch(function () {
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal?");
      render();
    });
  }

  $("correct").addEventListener("click", function () { answer(0); });
  $("wrong").addEventListener("click", function () { answer(1); });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    if (e.key === "1") { answer(0); } else if (e.key === "2") { answer(1); } else { return; }
    e.preventDefault();
  });

  if (data.summary.done) { $("ask").hidden = true; fetchResult(); } else { render(); }
})();
</script>
</body>
</html>
"""
