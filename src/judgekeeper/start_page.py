"""The pages `judgekeeper start` shows: the labeling page and the result page.

The labeling page shows one answer at a time, its question and answer as written, and never
anything the judge said: the page data is only ids, text and the person's own labels. Every
string is shown through textContent. Keys: 1 Correct, 2 Wrong, S Skip, U Undo.

The result page is static HTML that runs no script and loads nothing, so the copy saved as
`.judgekeeper/result.html` opens with no server. Every string in it is escaped.
"""

from __future__ import annotations

from html import escape

LOGO = """<svg viewBox="0 0 64 72" aria-hidden="true" focusable="false">
      <path d="M32 3 L5 12 V34 C5 51 17 63 32 69 Z" fill="#1E293B"/>
      <path d="M32 3 L59 12 V34 C59 51 47 63 32 69 Z" fill="#10B981"/>
      <path d="M18 36 L28 46 L47 25" fill="none" stroke="#FFFFFF" stroke-width="6"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>"""

STYLE = """
:root { --navy: #1E293B; --green: #10B981; --bg: #FFFFFF; --bg-soft: #F8FAFC;
  --surface: #FFFFFF; --line: #E2E8F0; --text: #0F172A; --muted: #475569;
  --link: #1D4ED8; --pass: #047857; --fail: #B91C1C;
  --pass-bg: #D1FAE5; --fail-bg: #FEE2E2; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0B1120; --bg-soft: #0F172A; --surface: #111827; --line: #1F2A3D;
    --text: #E2E8F0; --muted: #94A3B8; --link: #93C5FD;
    --pass: #34D399; --fail: #FCA5A5; --pass-bg: #064E3B; --fail-bg: #5B1A1A; }
  .brand svg { background: #F8FAFC; border-radius: 8px; padding: 3px; } }
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 17px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  overflow-x: hidden; }
:focus-visible { outline: 3px solid var(--link); outline-offset: 3px; border-radius: 6px; }
header { border-bottom: 1px solid var(--line); padding: 14px 16px; text-align: center; }
.brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700;
  font-size: 1.15rem; letter-spacing: -0.01em; }
.brand svg { width: 28px; height: 32px; }
main { max-width: 44rem; margin: 0 auto; padding: 20px 16px 48px; }
.counts { display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: baseline;
  justify-content: space-between; }
.tally { font-weight: 700; font-size: 1.05rem; }
.tally .c { color: var(--pass); } .tally .w { color: var(--fail); }
.bars { display: grid; gap: 6px; margin: 8px 0 4px; }
.bar { position: relative; height: 6px; border-radius: 999px; background: var(--line); }
.bar span { display: block; height: 100%; border-radius: 999px; }
.bar.c span { background: var(--pass); } .bar.w span { background: var(--fail); }
.bar i { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--muted); }
.bar i.rough { left: 60%; } .bar i.reliable { left: calc(100% - 2px); }
.need { margin: 0; color: var(--muted); font-size: 0.95rem; }
.result-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
  margin: 10px 0 0; }
.unsure { margin: 0; color: var(--muted); font-size: 0.9rem; }
.where { margin: 22px 0 6px; color: var(--muted); font-size: 0.9rem; }
.box-label { margin: 14px 0 4px; font-size: 0.8rem; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase; color: var(--muted); }
.box { margin: 0; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px;
  background: var(--bg-soft); font: 17px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
  white-space: pre-wrap; overflow-wrap: anywhere; max-height: 38vh; overflow-y: auto; }
.choices { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 22px 0 0; }
.choice { font: inherit; font-size: 1.2rem; font-weight: 700; min-height: 64px;
  padding: 10px 14px; border-radius: 14px; border: 2px solid; background: var(--surface);
  cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px; }
.choice svg { width: 22px; height: 22px; flex: none; }
kbd { font: 600 0.8rem/1 ui-monospace, Menlo, monospace; color: var(--muted);
  border: 1px solid var(--line); border-radius: 5px; padding: 3px 6px; }
#correct { color: var(--pass); border-color: var(--pass); }
#wrong { color: var(--fail); border-color: var(--fail); }
#correct:hover { background: var(--pass-bg); } #wrong:hover { background: var(--fail-bg); }
.choice:disabled { cursor: default; opacity: 0.6; }
.small { display: flex; justify-content: center; gap: 18px; margin: 12px 0 0; }
.text-btn { font: inherit; font-size: 0.95rem; background: none; border: none; padding: 4px;
  color: var(--link); cursor: pointer; text-decoration: underline;
  text-underline-offset: 2px; }
.btn { display: inline-block; font: inherit; font-weight: 600; font-size: 0.95rem;
  padding: 8px 16px; border-radius: 10px; border: 0; background: var(--navy); color: #FFF;
  cursor: pointer; text-decoration: none; }
@media (prefers-color-scheme: dark) { .btn { background: #E2E8F0; color: #0B1120; } }
#status { min-height: 1.6em; margin: 12px 0 0; color: var(--fail); font-size: 0.95rem; }
#done { text-align: center; margin: 32px 0; }
h1 { font-size: clamp(1.8rem, 6vw, 2.4rem); line-height: 1.2; margin: 4px 0 18px; }
.first { font-size: 1.25rem; font-weight: 700; line-height: 1.45; margin: 0 0 10px; }
.verdict { font-size: 1.15rem; margin: 6px 0 22px; padding: 10px 14px;
  border-left: 4px solid var(--green); background: var(--bg-soft);
  border-radius: 0 10px 10px 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
  gap: 12px; margin: 0 0 18px; }
.tile { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.tile .name { font-size: 0.85rem; color: var(--muted); font-weight: 700; }
.tile .value { font-size: 1.8rem; font-weight: 700; line-height: 1.2; }
.tile .sub { font-size: 0.85rem; color: var(--muted); }
.note { color: var(--muted); font-size: 0.95rem; margin: 0 0 6px; }
h2 { font-size: 1.15rem; margin: 26px 0 10px; padding-top: 18px;
  border-top: 1px solid var(--line); }
.plain { list-style: none; padding: 0; margin: 0; }
.plain li { margin: 0 0 6px; overflow-wrap: anywhere; }
code { font: 0.95rem ui-monospace, Menlo, monospace; background: var(--bg-soft);
  border: 1px solid var(--line); border-radius: 6px; padding: 1px 6px; }
@media (max-width: 420px) {
  .choice { font-size: 1.05rem; min-height: 56px; }
  .choice kbd { display: none; } }
"""

START_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>judgekeeper: label answers</title>
<style>__STYLE__</style>
</head>
<body>
<header>
  <div class="brand">
    __LOGO__
    judgekeeper
  </div>
</header>
<main>
<section aria-label="Your labels">
  <div class="counts">
    <div class="tally" aria-live="polite"><span class="c">Correct <b id="nc">0</b></span>
      &middot; <span class="w">Wrong <b id="nw">0</b></span></div>
  </div>
  <div class="bars" aria-hidden="true">
    <div class="bar c"><span id="bc"></span><i class="rough"></i><i class="reliable"></i></div>
    <div class="bar w"><span id="bw"></span><i class="rough"></i><i class="reliable"></i></div>
  </div>
  <p class="need" id="need">A rough check needs 15 of each.</p>
  <div class="result-row">
    <a class="btn" id="see" href="#">See my result</a>
    <p class="unsure" id="unsure">With so few labels the result will be very unsure.</p>
  </div>
</section>
<section id="ask" aria-labelledby="where">
  <p class="where" id="where"></p>
  <div class="box-label">The question</div>
  <div class="box" id="question" tabindex="0"></div>
  <div class="box-label">The answer</div>
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
</section>
<section id="done" hidden>
  <p class="first">Every answer is labeled.</p>
</section>
<p id="status" role="status"></p>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", ROUGH = 15, RELIABLE = 25;
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }

  $("see").setAttribute("href", url("/result"));

  function renderCounts() {
    setText("nc", counts.correct); setText("nw", counts.wrong);
    $("bc").style.width = Math.min(counts.correct, RELIABLE) / RELIABLE * 100 + "%";
    $("bw").style.width = Math.min(counts.wrong, RELIABLE) / RELIABLE * 100 + "%";
    var least = Math.min(counts.correct, counts.wrong);
    setText("need", least < ROUGH ? "A rough check needs 15 of each." :
      least < RELIABLE ? "Rough check ready. A reliable result needs 25 of each." :
      "Reliable result ready.");
    $("unsure").hidden = least >= ROUGH;
  }

  function render() {
    renderCounts();
    var it = items[pos];
    setText("where", "Answer " + (pos + 1) + " of " + items.length);
    setText("question", it.input);
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
      counts = res.body.summary.counts; setText("status", "");
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
""".replace("__STYLE__", STYLE).replace("__LOGO__", LOGO)


def _list(lines) -> str:
    return "".join(f"<li>{escape(line)}</li>" for line in lines)


def result_page(content: dict, back: str | None = None) -> str:
    """The result as a page. `content` holds the text (see start_label.page_content); `back`
    is the link to the labeling page while the server runs, None for the saved copy."""
    tiles = "".join(
        f'<div class="tile"><div class="name">{escape(t["name"])}</div>'
        f'<div class="value">{escape(t["value"])}</div>'
        f'<div class="sub">{escape(t["interval"])}</div>'
        f'<div class="sub">{escape(t["count"])}</div></div>' for t in content["tiles"])
    keep = (f'<p><a class="btn" href="{escape(back)}">Keep labeling</a></p>'
            if back else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>judgekeeper: your result</title>
<style>{STYLE}</style>
</head>
<body>
<header>
  <div class="brand">
    {LOGO}
    judgekeeper
  </div>
</header>
<main>
<h1>{escape(content["title"])}</h1>
{"".join(f'<p class="first">{escape(s)}</p>' for s in content["sentences"])}
<p class="verdict">{escape(content["verdict"])}</p>
<div class="tiles">{tiles}</div>
{"".join(f'<p class="note">{escape(s)}</p>' for s in content["notes"])}
{keep}
<h2>Your judge</h2>
<ul class="plain">{_list(content["judge"])}</ul>
<h2>What next</h2>
<ul class="plain">{"".join(f"<li>{escape(text)} <code>{escape(cmd)}</code></li>"
                           for text, cmd in content["next"])}</ul>
<p class="note">{escape(content["saved"])}</p>
</main>
</body>
</html>
"""
