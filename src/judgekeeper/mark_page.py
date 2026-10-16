"""The marking page and its welcome box.

One self-contained page (look.py: nothing loaded from anywhere else). It shows one answer at a
time with the person's own marks and never anything the judge decided: no grade, no reason,
no agreement. Text reaches it through textContent. The server fills in __DATA__ (the answers
and the person's marks, start_label.StartSession.state), __TOKEN__ and __NONCE__.

How it keeps marks honest: Fail and Pass look the same but for their colour; after each mark
the page ignores input for about 400 ms, and it ignores a held key and any key with
Cmd, Ctrl or Alt, so a double click or a held key never marks an answer not yet seen. Focus
goes to the answer, never to a button. The bar follows the answers looked at, never the Pass
and Fail balance, and no number on the page is a target. Skipped answers come back at the
end.
"""

from __future__ import annotations

from html import escape

from judgekeeper import look, targets

# Answers looked at that fill the bar: about what a first result takes (enough of each kind)
FIRST = 2 * targets.ROUGH

HOW = ("Mark each answer the way you want your judge to decide. Its current rule is shown "
       "here, for reference.")
TITLE = "Mark each answer the way you want your judge to decide."
WELCOME = [("You'll see one answer at a time. Your judge's grade stays hidden, so your marks "
            "are your own."),
           "Mark honestly, even if most answers look alike. That is a finding too."]
# Shown in the welcome box only when the rule card is out of view when it opens
RULE_HINT = "Your judge's rule is {where} of the page: read it first."
SHORT_SIDE = ("Your result needs some answers you pass and some you fail. Keep marking "
              "honestly; if most look alike, that is a finding too.")

CROSS = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 6l12 12M18 '
         '6 6 18"/></svg>')
TICK = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m5 12.5 4.5 '
        '4.5L19 7"/></svg>')


def _text(value: str) -> str:
    """Text for the page: escaped, and with no `_`, so it can never hold one of the names the
    server fills in (__DATA__, __TOKEN__, __NONCE__)."""
    return escape(value).replace("_", "&#95;")


STYLE = """
#app { min-height: 100vh; display: flex; flex-direction: column; }
.progress { display: flex; flex-direction: column; gap: 5px; min-width: 220px; max-width: 100%; }
.progress .row { display: flex; justify-content: space-between; gap: 12px; white-space: nowrap;
  font-size: 12px; font-weight: 600; color: var(--ink-3); }
.progress .row a { font-weight: 700; text-decoration: none; }
.track { height: 6px; border-radius: 999px; background: var(--track); overflow: hidden; }
.track span { display: block; height: 100%; width: 0; border-radius: 999px;
  background: var(--accent); transition: width .2s; }
main.mark { flex: 1 1 auto; width: 100%; max-width: 1280px; margin: 0 auto; padding: 24px;
  display: flex; flex-wrap: wrap; gap: 20px; align-items: stretch; }
.answers { flex: 1 1 220px; max-width: 250px; display: flex; flex-direction: column;
  overflow: hidden; max-height: calc(100vh - 110px); }
.queue { list-style: none; margin: 0; padding: 8px; display: flex; flex-direction: column;
  gap: 2px; font-size: 14.5px; overflow: auto; min-height: 0; flex: 1 1 auto; }
.queue a { display: flex; align-items: center; gap: 10px; padding: 10px 10px 10px 12px;
  border-radius: 9px; color: var(--ink-2); text-decoration: none; font-weight: 600; }
.queue a.open { color: var(--ink-3); }
.queue a:hover { background: var(--tint); }
.queue a[aria-current] { background: var(--accent-bg); box-shadow: inset 3px 0 0 var(--mark-line);
  color: var(--ink); font-weight: 700; }
.queue .n { flex: none; min-width: 20px; font-family: var(--mono); font-size: 11px;
  color: var(--ink-3); }
.queue .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.dot { flex: none; width: 22px; height: 22px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; }
.dot svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 3;
  stroke-linecap: round; stroke-linejoin: round; }
.dot.pass { background: var(--pass-dot); color: var(--pass); }
.dot.fail { background: var(--fail-dot); color: var(--fail); }
.dot.now { border: 2px solid var(--accent); }
.dot.now::after { content: ""; width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent); }
.dot.open { border: 1.5px dashed var(--dash); }
.legend { margin-top: auto; padding: 12px 16px 14px; border-top: 1px solid var(--rule-2);
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px; font-size: 14.5px;
  font-weight: 600; color: var(--ink-3); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend .dot { width: 14px; height: 14px; }
.legend .dot svg { width: 9px; height: 9px; stroke-width: 3.5; }
.work { flex: 999 1 500px; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.answer { overflow: clip; flex: 1 1 auto; display: flex; flex-direction: column; }
.strip { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 20px;
  background: var(--tint); border-bottom: 1px solid var(--rule); }
#ans-pos { font-size: 14px; font-weight: 800; color: var(--accent); text-transform: uppercase;
  letter-spacing: .8px; }
.strip .sep { width: 4px; height: 4px; border-radius: 50%; background: var(--dash); }
#ans-status { font-size: 14px; font-weight: 600; color: var(--ink-3); }
.hidden-grade { margin-left: auto; display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px; border: 1px solid var(--rule); background: var(--sheet);
  font-size: 12px; font-weight: 700; color: var(--ink-3); }
.hidden-grade svg, .avatar svg, .saved svg { fill: none; stroke: currentColor;
  stroke-linecap: round; stroke-linejoin: round; }
.hidden-grade svg { width: 12px; height: 12px; stroke-width: 2.4; }
.qa { padding: 24px 24px 22px; display: flex; gap: 16px; align-items: flex-start; }
.qa.reply { border-top: 1px solid var(--rule); background: var(--tint-2); padding: 22px 24px 26px;
  flex: 1 1 auto; }
.qa > div { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.avatar { flex: none; width: 40px; height: 40px; border-radius: 50%; background: var(--chip);
  color: var(--ink-2); display: inline-flex; align-items: center; justify-content: center; }
.avatar svg { width: 20px; height: 20px; stroke-width: 2; }
.reply .avatar { background: var(--accent-bg); color: var(--accent); }
.lbl { font-size: 12px; font-weight: 700; color: var(--ink-3); text-transform: uppercase;
  letter-spacing: .6px; }
#q-text { margin: 0; font-size: 20px; line-height: 1.35; font-weight: 700; letter-spacing: -.2px;
  white-space: pre-wrap; overflow-wrap: anywhere; }
#q-text .field-name { display: block; font-size: 12px; font-weight: 700; color: var(--ink-3);
  letter-spacing: 0; }
#q-text .field { display: block; }
#q-text .field + .field-name { margin-top: 10px; }
#a-text { margin: 0; font-size: 19px; line-height: 1.65; font-weight: 500; max-width: 70ch;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.decide { position: sticky; bottom: 0; z-index: 5; background: var(--sheet);
  box-shadow: 0 -10px 18px -14px rgba(22,33,28,.35); border-top: 1px solid var(--rule);
  padding: 18px 28px 22px; display: flex; flex-direction: column; gap: 12px; }
.pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.dec { height: 58px; border-radius: 10px; border: 1.5px solid; font-size: 18px; font-weight: 800;
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  transition: transform .08s, background-color .12s, border-color .12s; }
.dec:active, .dec.hit { transform: scale(.98); }
.dec svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2.5;
  stroke-linecap: round; stroke-linejoin: round; }
.dec kbd { font-family: inherit; font-size: 11px; font-weight: 700; padding: 2px 6px;
  border-radius: 5px; border: 1px solid; }
.dec.fail { background: var(--fail-bg); border-color: var(--fail-line); color: var(--fail); }
.dec.pass { background: var(--pass-bg); border-color: var(--pass-line); color: var(--pass); }
.dec.fail kbd { background: var(--fail-kbd); border-color: var(--fail-kbd-line); color: var(--fail); }
.dec.pass kbd { background: var(--pass-kbd); border-color: var(--pass-kbd-line); color: var(--pass); }
.dec.fail:hover { border-color: var(--fail); }
.dec.pass:hover { border-color: var(--pass); }
.dec.fail[aria-pressed="true"] { background: var(--fail-on); border-color: var(--fail-on); color: #FFFFFF; }
.dec.pass[aria-pressed="true"] { background: var(--pass-on); border-color: var(--pass-on); color: #FFFFFF; }
.dec[aria-pressed="true"] kbd { background: transparent; border-color: #FFFFFF; color: #FFFFFF; }
.dec:disabled { cursor: default; }
.skiprow { display: flex; justify-content: center; }
.skip { height: 36px; padding: 0 14px; border-radius: 8px; border: 0; background: transparent;
  color: var(--ink-3); font-size: 14px; font-weight: 700; display: inline-flex;
  align-items: center; gap: 8px; }
.skip:hover { background: var(--paper); }
.skip:active, .skip.hit { transform: scale(.98); }
.skip kbd { font-family: inherit; font-size: 11px; font-weight: 700; padding: 2px 6px;
  border-radius: 5px; border: 1px solid var(--rule); background: var(--sheet); color: var(--ink-3); }
.status { margin: 0; min-height: 1.4em; text-align: center; font-size: 13px; font-weight: 600;
  color: var(--fail); }
.status:empty { display: none; }
.end { padding: 40px 28px; display: flex; flex-direction: column; align-items: center;
  gap: 16px; text-align: center; }
.end h2 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -.3px; }
.go { height: 48px; padding: 0 22px; border: 0; border-radius: 10px; background: var(--btn);
  color: var(--on-btn); font-size: 16px; font-weight: 600; text-decoration: none;
  display: inline-flex; align-items: center; justify-content: center; }
.go:hover { background: var(--btn-hover); color: var(--on-btn); }
.go:active { background: var(--btn-active); }
.rail { flex: 1 1 250px; max-width: 290px; display: flex; flex-direction: column; gap: 16px; }
.rail .body { padding: 14px 16px 16px; }
.rail .how { margin: 0 0 10px; font-size: 14.5px; color: var(--ink-2); }
.fold { border: 0; background: none; padding: 0; color: var(--accent); font-size: 14.5px;
  font-weight: 700; }
#rule { margin: 0; padding: 2px 0 2px 14px; border-left: 3px solid var(--mark-line);
  font-size: 15.5px; line-height: 1.6; color: var(--ink); white-space: pre-wrap;
  overflow-wrap: anywhere; }
#rule.folded { max-height: 12.8em; overflow: hidden; }
.keys { padding: 12px 16px 14px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px; }
.keys div { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px;
  background: var(--tint); font-size: 14.5px; font-weight: 600; color: var(--ink-2); }
.keys kbd { font-family: inherit; min-width: 24px; height: 24px; padding: 0 6px;
  border-radius: 6px; border: 1px solid var(--rule-3); border-bottom-width: 2px;
  background: var(--sheet); font-size: 12.5px; font-weight: 800; color: var(--ink);
  display: inline-flex; align-items: center; justify-content: center; }
.saved { padding: 10px 16px 12px; border-top: 1px solid var(--rule-2); display: flex;
  align-items: center; gap: 10px; }
.saved > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.saved b { font-size: 14.5px; font-weight: 700; }
.saved span { font-size: 14.5px; color: var(--ink-3); }
.saved code { font-size: 12.5px; }
.note { margin: 0; padding: 12px 16px; font-size: 14.5px; color: var(--ink-2); }
.note:empty { display: none; }
.scrim { position: fixed; inset: 0; z-index: 50; background: var(--scrim); display: flex;
  align-items: center; justify-content: center; padding: 16px; }
.intro { width: 440px; max-width: calc(100vw - 32px); max-height: calc(100vh - 32px);
  overflow: auto; background: var(--sheet); border: 1px solid var(--rule); border-radius: 16px;
  padding: 28px 40px 32px; box-shadow: var(--shadow-lg); display: flex; flex-direction: column;
  align-items: center; gap: 14px; text-align: center; }
.intro .brand { margin-bottom: 8px; font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
.intro h2 { margin: 0; max-width: 32ch; font-size: 24px; line-height: 1.3; font-weight: 700;
  letter-spacing: -.015em; text-wrap: balance; }
.intro p { margin: 0; max-width: 34ch; font-size: 15px; line-height: 1.55; font-weight: 500;
  color: var(--ink-3); text-wrap: balance; }
#intro-text { display: flex; flex-direction: column; align-items: center; gap: 10px; }
.intro .go { margin-top: 10px; width: 100%; }
#answer-card:focus-visible, .intro:focus-visible { outline: none; }
@media (max-height: 760px) { #app { min-height: auto; } }
@media (max-width: 600px) {
  main.mark { flex-direction: column; flex-wrap: nowrap; padding: 16px; }
  .answers, .rail { max-width: none; flex: none; }
  .answers { order: 3; max-height: 60vh; }
  .work { flex: none; }
  .rail { order: 2; }
  .answer .rail { order: 0; padding: 0 16px 16px; gap: 12px; }
  .decide { padding: 14px 16px 16px; }
  .qa { padding: 18px 16px; }
  .intro { padding: 24px 20px; }
}
"""

BODY = """<div id="app">
__TOP__
<main class="mark">
<nav class="card answers" aria-labelledby="answers-h">
  <div class="head"><span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg></span>
    <h2 id="answers-h">Answers</h2></div>
  <ol class="queue" id="queue"></ol>
  <div class="legend" aria-hidden="true"><span><span class="dot pass">__TICK__</span>Pass</span>
    <span><span class="dot fail">__CROSS__</span>Fail</span>
    <span><span class="dot open"></span>Not marked</span></div>
</nav>
<section class="work" aria-label="The answer to mark">
  <div class="card answer" id="answer-card" tabindex="-1" aria-label="The answer to mark">
    <div class="strip"><span id="ans-pos">Answer</span><span class="sep" aria-hidden="true"></span>
      <span id="ans-status" aria-live="polite">Not marked yet</span>
      <span class="hidden-grade"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>Judge's grade hidden</span></div>
    <div class="qa ask"><span class="avatar" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg></span>
      <div><span class="lbl">The question</span><h1 id="q-text"></h1></div></div>
    <div class="qa reply"><span class="avatar" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4M9 14h.01M15 14h.01"/></svg></span>
      <div><span class="lbl">The answer</span><p id="a-text"></p></div></div>
    <div class="decide" id="decide">
      <div class="pair">
        <button type="button" class="dec fail" id="fail" aria-pressed="false" aria-keyshortcuts="ArrowLeft">__CROSS__<span>Fail</span><kbd>←</kbd></button>
        <button type="button" class="dec pass" id="pass" aria-pressed="false" aria-keyshortcuts="ArrowRight">__TICK__<span>Pass</span><kbd>→</kbd></button>
      </div>
      <div class="skiprow"><button type="button" class="skip" id="skip" aria-keyshortcuts="S"><span>Skip this one</span><kbd>S</kbd></button></div>
      <p class="status" id="status" role="status"></p>
    </div>
  </div>
  <div class="card end" id="end" hidden aria-live="polite"><h2 id="end-title"></h2>
    <button type="button" class="go" id="again" hidden>Look at them</button></div>
</section>
<aside class="rail" id="rail">
  __RULE_CARD__
  <div class="card">
    <div class="head"><span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8"/></svg></span>
      <h2>Shortcuts</h2></div>
    <div class="keys"><div><kbd>←</kbd>Fail</div><div><kbd>→</kbd>Pass</div>
      <div><kbd>S</kbd>Skip</div><div><kbd>Z</kbd>Undo</div></div>
    <div class="saved"><span class="ic" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg></span>
      <div><b>Saved locally as you go</b><span>To come back later, run <code>__COMMAND__</code>.</span></div></div>
  </div>
  <div class="card"><p class="note" id="ready" aria-live="polite"></p></div>
</aside>
</main>
</div>
<div class="scrim" id="intro" hidden>
  <div class="intro" id="intro-box" role="dialog" aria-modal="true" aria-labelledby="intro-title" aria-describedby="intro-text" tabindex="-1">
    __BRAND__
    <h2 id="intro-title">__TITLE__</h2>
    <div id="intro-text">__WELCOME__<p id="rule-hint" hidden></p></div>
    <button type="button" class="go" id="intro-ok">Start marking</button>
  </div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
__THEME_SWITCH__
(function () {
  var TOKEN = "__TOKEN__", FIRST = __FIRST__, LOCK_MS = 400;
  var SHORT_SIDE = "__SHORT_SIDE__", RULE_HINT = "__RULE_HINT__";
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var total = data.total || items.length;  // the page holds the next answers, not all of them
  var shownAt = Date.now();  // when the answer on screen was shown: each mark sends its seconds
  var status = data.status;  // whether a result is ready, and its line, from the server
  var ended = false;         // nothing left to mark: the page says what comes next
  var walkingSkipped = false;  // "Look at them": going through the skipped answers
  var lockUntil = 0;         // input is ignored until then, after each mark
  var $ = function (id) { return document.getElementById(id); };
  var card = $("answer-card");
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text != null) { e.textContent = String(text); }
    return e;
  }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  function focusCard() { card.focus({preventScroll: true}); }
  $("see").setAttribute("href", url("/result"));

  // A question is text, or [[name, value], ...]: each name a small label above its value.
  function showQuestion(value, into) {
    into.textContent = "";
    if (!Array.isArray(value)) { into.textContent = value == null ? "" : String(value); return; }
    value.forEach(function (pair) {
      into.appendChild(el("span", "field-name", pair[0]));
      into.appendChild(el("span", "field", pair[1]));
    });
  }
  function firstLine(value) {
    var text = Array.isArray(value) ? (value[0] ? value[0][1] : "") : (value || "");
    return String(text).split("\\n")[0];
  }

  // The answers list: the person's own marks only.
  var ICON = {pass: '__TICK__', fail: '__CROSS__'};
  var SAID = {pass: "marked Pass", fail: "marked Fail"};
  function renderQueue() {
    var list = $("queue");
    list.textContent = "";
    items.forEach(function (it, k) {
      var li = el("li"), a = el("a", it.label ? "" : "open");
      a.href = "#"; a.setAttribute("data-k", String(k));
      if (k === pos && !ended) { a.setAttribute("aria-current", "true"); }
      a.appendChild(el("span", "n", k < 99 ? ("0" + (k + 1)).slice(-2) : String(k + 1)));
      a.appendChild(el("span", "t", firstLine(it.input)));
      var dot = el("span", "dot " + (it.label || (k === pos && !ended ? "now" : "open")));
      dot.setAttribute("aria-hidden", "true");
      if (it.label) { dot.innerHTML = ICON[it.label]; }  // fixed icon markup only, no data
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

  // The bar: answers looked at (marked or skipped), never the Pass and Fail balance.
  function renderProgress() {
    var looked = counts.correct + counts.wrong + (counts.skipped || 0);
    var share = status.ready ? 1 : Math.min(looked / FIRST, 0.95);
    $("bar").style.width = (share * 100) + "%";
    var bar = $("progress");
    bar.setAttribute("aria-valuenow", String(Math.round(share * 100)));
    bar.setAttribute("aria-valuetext", looked === 1 ? "1 answer looked at" :
      looked + " answers looked at");
    setText("progress-label", status.ready ? "Ready for your first result" :
      "Toward your first result");
    $("see").hidden = !status.ready;
    setText("ready", !status.ready && looked >= FIRST ? SHORT_SIDE : status.text);
  }

  function render() {
    var it = items[pos];
    $("answer-card").hidden = false; $("end").hidden = true;
    setText("ans-pos", "Answer " + (pos + 1));
    setText("ans-status", it.label ? "Your mark: " + (it.label === "pass" ? "Pass" : "Fail") +
      ". Press the other button to change it." : it.skipped ? "Skipped for now" :
      "Not marked yet");
    showQuestion(it.input, $("q-text"));
    setText("a-text", it.output);
    $("fail").setAttribute("aria-pressed", String(it.label === "fail"));
    $("pass").setAttribute("aria-pressed", String(it.label === "pass"));
    renderQueue(); renderProgress();
    busy = false; $("pass").disabled = false; $("fail").disabled = false;
    shownAt = Date.now();
  }

  function open(index) { ended = false; pos = index; render(); }

  // The next answer still to mark (or, walking the skipped ones, still skipped), from `from`.
  function nextIndex(from) {
    for (var n = 0; n < items.length; n++) {
      var i = (from + n) % items.length, it = items[i];
      if (walkingSkipped ? it.skipped : (!it.label && !it.skipped)) { return i; }
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

  // Nothing left to mark: the result, or first the skipped answers. One action, no buttons
  // to mark with.
  function finish() {
    ended = true; busy = false;
    $("answer-card").hidden = true; $("end").hidden = false;
    renderQueue(); renderProgress();
    var skipped = items.filter(function (it) { return it.skipped; }).length;
    if (!skipped) {
      setText("end-title", "You marked every answer.");
      $("again").hidden = true;
      window.location.href = url("/result");
      return;
    }
    setText("end-title", (skipped === 1 ? "1 skipped answer" : skipped + " skipped answers") +
      ". Look again, or leave " + (skipped === 1 ? "it" : "them") + " out.");
    setText("again", skipped === 1 ? "Look at it" : "Look at them");
    $("again").hidden = false; $("again").focus();
  }
  $("again").addEventListener("click", function () {
    walkingSkipped = true; open(nextIndex(0)); focusCard(); });

  function send(change, then) {
    if (busy) { return false; }
    busy = true; $("pass").disabled = true; $("fail").disabled = true;
    change.id = items[pos].id;
    change.seconds = Math.max(0, (Date.now() - shownAt) / 1000);
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      referrerPolicy: "same-origin", body: JSON.stringify(change)
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { render(); setText("status", "Not saved: " + res.body.error); return; }
      counts = res.body.summary.counts; status = res.body.summary.status;
      setText("status", "");
      then();
    }).catch(function () {
      render();
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier marks are saved.");
    });
    return true;
  }

  // Each action waits LOCK_MS after the one before: a double click or a key held down never
  // marks an answer not yet on screen.
  function locked() {
    var t = Date.now();
    if (t < lockUntil) { return true; }
    lockUntil = t + LOCK_MS;
    return false;
  }

  function hit(id) {
    var b = $(id);
    b.classList.add("hit");
    setTimeout(function () { b.classList.remove("hit"); }, 140);
  }

  function mark(value) {
    if (ended || locked()) { return; }
    hit(value);
    var it = items[pos];
    send({label: value}, function () {
      it.label = value; it.skipped = false; history.push(pos); next(); focusCard(); });
  }

  function skip() {
    if (ended || locked()) { return; }
    hit("skip");
    var it = items[pos];
    send({deferred: true}, function () {
      it.label = null; it.skipped = true; history.push(pos); next(); focusCard(); });
  }

  function undo() {
    if (!history.length) { setText("status", "Nothing to undo."); return; }
    if (locked()) { return; }
    var back = history.pop();
    walkingSkipped = false; open(back);
    var it = items[pos];
    send({label: null, deferred: false}, function () {
      it.label = null; it.skipped = false; render(); focusCard(); });
  }

  // Mouse presses never leave focus on a button; focus stays on the answer.
  ["fail", "pass", "skip"].forEach(function (id) {
    $(id).addEventListener("mousedown", function (e) { e.preventDefault(); });
  });
  $("fail").addEventListener("click", function () { mark("fail"); });
  $("pass").addEventListener("click", function () { mark("pass"); });
  $("skip").addEventListener("click", function () { skip(); });

  // The keys: → Pass and ← Fail (shown), 1 Pass and 2 Fail (an old habit, still working),
  // S skip, Z undo (U too). A held key or any key with Cmd, Ctrl or Alt does nothing.
  var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};
  document.addEventListener("keydown", function (e) {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden) { return; }
    var tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") { return; }
    var k = (e.key || "").toLowerCase();
    if (KEYS[k]) { mark(KEYS[k]); }
    else if (k === "s") { skip(); }
    else if (k === "z" || k === "u") { undo(); }
    else { return; }
    e.preventDefault();
  });

  // The rule: folded when long, opened in its place, closed again with Esc.
  var rule = $("rule"), fold = $("fold");
  function setFold(open) {
    rule.classList.toggle("folded", !open);
    fold.setAttribute("aria-expanded", String(open));
    fold.textContent = open ? "Show less" : "Full rule";
  }
  if (rule) {
    if (rule.scrollHeight > rule.clientHeight + 2) { fold.hidden = false; }
    else { rule.classList.remove("folded"); }
    fold.addEventListener("click", function () { setFold(rule.classList.contains("folded")); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !rule.classList.contains("folded") && !fold.hidden &&
          $("intro").hidden) { setFold(false); }
    });
  }

  // On a narrow window the rule sits between the answer and the buttons, the list last.
  var narrow = window.matchMedia("(max-width: 600px)"), rail = $("rail");
  function place() {
    if (narrow.matches) { card.insertBefore(rail, $("decide")); }
    else if (rail.parentNode === card) { card.parentNode.parentNode.appendChild(rail); }
  }
  if (narrow.addEventListener) { narrow.addEventListener("change", place); }
  place();

  // The welcome box: once per browser (the browser's storage, when it allows it). Enter or
  // Esc starts; focus stays in the box; the button is not focused, so no ring shows.
  var INTRO_KEY = "judgekeeper-intro-seen", box = $("intro-box");
  function seenIntro() {
    try { return window.localStorage.getItem(INTRO_KEY) === "1"; } catch (e) { return false; }
  }
  function startMarking() {
    $("intro").hidden = true;
    try { window.localStorage.setItem(INTRO_KEY, "1"); } catch (e) { /* shown again next time */ }
    focusCard();
  }
  $("intro-ok").addEventListener("click", startMarking);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); startMarking(); }
    else if (e.key === "Tab") { e.preventDefault(); $("intro-ok").focus(); }
  });

  var left = items.some(function (it) { return !it.label && !it.skipped; });
  if (left) { open(pos); } else { finish(); }
  if (!seenIntro()) {
    $("intro").hidden = false;
    if (rule) {
      var r = rule.getBoundingClientRect(), c = card.getBoundingClientRect();
      if (r.top < 0 || r.bottom > window.innerHeight || r.right > window.innerWidth) {
        setText("rule-hint", RULE_HINT.replace("{where}", r.left >= c.right ? "on the right" :
          "further down"));
        $("rule-hint").hidden = false;
      }
    }
    box.focus();
  } else if (left) { focusCard(); }
})();
</script>
</body>
</html>
"""


def _rule_card(rule: str | None) -> str:
    """The judge's rule (its words only), folded when long; nothing when there is none."""
    if not rule:
        return ""
    return (
        '<div class="card"><div class="head"><span class="ic green" aria-hidden="true">'
        '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h7"/></svg></span>'
        "<h2>Judge's rule</h2>"
        '<button type="button" class="fold" id="fold" aria-controls="rule" '
        'aria-expanded="false" hidden>Full rule</button></div>'
        f'<div class="body"><p class="how">{_text(HOW)}</p>'
        f'<blockquote class="folded" id="rule">{_text(rule)}</blockquote></div></div>')


def _progress() -> str:
    return ('<div class="progress"><div class="row"><span id="progress-label">Toward your first '
            'result</span><a id="see" href="#" hidden>See your result</a></div>'
            '<div class="track" id="progress" role="progressbar" aria-label="Toward your first '
            'result" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span id="bar">'
            "</span></div></div>")


def label_page(description: str | None, rule: str | None, command: str | None = None,
               model: str | None = None, tool: str | None = None) -> str:
    """The marking page. `command` is what the person runs to come back; `model` and `tool`
    name the judge in the top bar. `description` (the app the answers came from, as the
    results name it) is not shown: the results name one source, the same on every answer.
    The server fills in __DATA__, __TOKEN__ and __NONCE__."""
    from judgekeeper.textio import program

    command = command or program("mark")
    left = look.chips(_text(model) if model else None, _text(tool) if tool else None)
    welcome = "".join(f"<p>{_text(line)}</p>" for line in WELCOME)
    body = (BODY.replace("__TOP__", look.top(left, _progress()))
            .replace("__RULE_CARD__", _rule_card(rule))
            .replace("__COMMAND__", _text(command))
            .replace("__TITLE__", _text(TITLE)).replace("__WELCOME__", welcome)
            .replace("__THEME_SWITCH__", look.THEME_SWITCH)
            .replace("__FIRST__", str(FIRST))
            .replace("__SHORT_SIDE__", SHORT_SIDE).replace("__RULE_HINT__", RULE_HINT)
            .replace("__BRAND__", look.BRAND)
            .replace("__CROSS__", CROSS).replace("__TICK__", TICK))
    return look.head("judgekeeper: mark answers", STYLE, '<script nonce="__NONCE__">') + body


OLD_LINK_STYLE = """
main.old { max-width: 560px; margin: 0 auto; padding: 64px 24px; }
main.old .card { padding: 28px 32px; display: flex; flex-direction: column; gap: 12px; }
main.old h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.3px; }
main.old p { margin: 0; font-size: 15px; color: var(--ink-2); }
"""
OLD_LINK = ("Each time judgekeeper opens its page, it makes a new private link, and older links "
            "stop working. Your marks are saved.")
OLD_LINK_SCRIPT = look.THEME_SWITCH
OLD_LINK_CSP = (f"default-src 'none'; script-src {look.script_hash(look.THEME_FIRST)} "
                f"{look.script_hash(OLD_LINK_SCRIPT)}; style-src 'unsafe-inline'; font-src data:; "
                "img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def old_link_page() -> str:
    """What a browser gets for a link with a missing or old token: the logo only, and how to
    open the page again."""
    from judgekeeper.textio import program

    return (look.head("judgekeeper: this link no longer works", OLD_LINK_STYLE, "<script>")
            + look.top("", "")
            + '<main class="old"><div class="card"><h1>This link no longer works.</h1>'
            + f"<p>{escape(OLD_LINK)}</p>"
            + f"<p>To open the page again, run <code>{escape(program('mark'))}</code>.</p>"
            + f"</div></main>\n<script>{OLD_LINK_SCRIPT}</script>\n</body>\n</html>\n")
