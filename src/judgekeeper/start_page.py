"""The pages only `judgekeeper start` shows: the review page and the fix page (the marking
page is mark_page.py, the result page report_page.py).

Each is one self-contained page: no fonts, scripts or images from anywhere else. The heading
font (Bricolage Grotesque, under the SIL Open Font License) is embedded as base64 from this
package's `fonts/` folder. Text reaches the pages through textContent. The first step of
the review holds nothing the judge said; the fix page holds only the answers
judgekeeper used, never those set aside.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from importlib import resources

from judgekeeper import look, textio

FONT_FAMILY = "Bricolage Grotesque"
FONTS = (("bricolage-grotesque-latin-600-normal.woff2", 600),
         ("bricolage-grotesque-latin-800-normal.woff2", 800))
FONT_LICENCE = "OFL-BricolageGrotesque.txt"


@lru_cache(maxsize=1)
def font_faces() -> str:
    """The @font-face rules with the heading font embedded as base64, so the pages load
    nothing from outside."""
    folder = resources.files("judgekeeper") / "fonts"
    rules = []
    for name, weight in FONTS:
        data = base64.b64encode((folder / name).read_bytes()).decode("ascii")
        rules.append(f'@font-face {{ font-family: "{FONT_FAMILY}"; font-weight: {weight}; '
                     'font-style: normal; font-display: swap; '
                     f'src: url("data:font/woff2;base64,{data}") format("woff2"); }}')
    return "\n".join(rules)


LOGO = look.SHIELD  # the official two-colour shield, as on every page

CROSS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" '
         'stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>')
TICK = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" '
        'stroke="currentColor" stroke-width="2.3" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>')
QUESTION = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.2 9a3 3 0 015.6 1.2c0 2-2.8 '
            '2.4-2.8 4.3M12 18.2v.1" fill="none" stroke="currentColor" stroke-width="2.3" '
            'stroke-linecap="round"/></svg>')

# The look every page shares: the colours (navy only), the fonts, the thin top bar, buttons,
# cards and the small pieces. Only transform and opacity ever animate.
STYLE = """
:root { --bg: #0E1525; --panel: #141C2E; --card: #182235; --card-2: #1E2942; --raised: #22304A;
  --line: rgba(148,163,184,.13); --line-2: rgba(148,163,184,.22);
  --text: #E9EEF5; --text-2: #BCC7D6; --muted: #8693A8;
  --green: #10B981; --pass: #34D399; --pass-bg: rgba(52,211,153,.10);
  --pass-line: rgba(52,211,153,.42);
  --fail: #F59E8B; --fail-bg: rgba(245,158,139,.10); --fail-line: rgba(245,158,139,.42);
  --amber: #FBBF24; --amber-bg: rgba(251,191,36,.07); --amber-line: rgba(251,191,36,.28);
  --ease-out: cubic-bezier(.23,1,.32,1);
  --display: "Bricolage Grotesque", system-ui, sans-serif;
  --body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --hdr: 56px; color-scheme: dark; }
* { box-sizing: border-box; margin: 0; }
[hidden] { display: none !important; }
html, body { height: 100%; }
body { font: 400 15px/1.5 var(--body); color: var(--text); background: var(--bg);
  -webkit-font-smoothing: antialiased; }
h1, h2, h3 { font-family: var(--display); font-weight: 600; }
button { font: inherit; color: inherit; cursor: pointer; border: 0; background: none; }
button:disabled { cursor: default; }
code, kbd { font-family: var(--mono); }
code { font-size: 13px; background: var(--bg); border: 1px solid var(--line-2);
  border-radius: 7px; padding: 2px 7px; color: var(--text); }
kbd { font-size: 11px; font-weight: 600; color: var(--text-2); border: 1px solid var(--line-2);
  border-bottom-width: 2px; border-radius: 5px; padding: 0 5px; line-height: 17px;
  display: inline-block; min-width: 19px; text-align: center; }
:focus-visible { outline: 2px solid var(--pass); outline-offset: 2px; }
a { color: var(--text-2); }
.app { min-height: 100vh; display: flex; flex-direction: column; }
.hdr { height: var(--hdr); flex: none; display: grid; grid-template-columns: 1fr auto 1fr;
  align-items: center; padding: 0 24px; position: sticky; top: 0; z-index: 5;
  background: rgba(14,21,37,.75); -webkit-backdrop-filter: blur(20px) saturate(160%);
  backdrop-filter: blur(20px) saturate(160%); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 9px; font: 600 15px/1 var(--display);
  letter-spacing: -.01em; }
.brand .mark { width: 24px; height: 24px; border-radius: 7px; background: #E9EEF5;
  display: grid; place-items: center; }
.brand svg { width: 16px; height: 16px; }
.mid { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted);
  font-variant-numeric: tabular-nums; }
.mid b { color: var(--text); }
.bar { width: 160px; height: 4px; border-radius: 4px; background: var(--line-2);
  overflow: hidden; }
.bar i { display: block; height: 100%; width: 0; background: var(--green); }
.end { justify-self: end; display: flex; align-items: center; gap: 14px; font-size: 13px; }
.saved { color: var(--muted); display: flex; align-items: center; gap: 6px;
  transition: opacity 300ms ease; }
.saved::before { content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--pass); }
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  height: 36px; padding: 0 14px; border-radius: 9px; font: 600 14px/1 var(--body);
  color: var(--text); text-decoration: none; border: 1px solid var(--line-2);
  background: var(--card); transition: transform 140ms var(--ease-out), opacity 200ms ease; }
.btn:active { transform: scale(.97); }
.btn.primary { background: var(--green); color: #04241A; border-color: transparent; }
.btn.green { color: var(--pass); border-color: var(--pass-line); background: var(--pass-bg); }
.btn:disabled { opacity: .35; pointer-events: none; }
.link { color: var(--text-2); text-decoration: underline; text-decoration-color: var(--line-2);
  text-underline-offset: 3px; background: none; border: 0; padding: 0; font: inherit;
  cursor: pointer; }
.body { flex: 1; min-height: calc(100vh - var(--hdr)); display: grid; gap: 20px;
  padding: 20px 24px 40px; max-width: 1280px; width: 100%; margin: 0 auto;
  align-content: safe center; align-items: start; }
.split { grid-template-columns: minmax(0, 1fr) 400px; }
.col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px 18px; }
.card h3 { font-size: 16px; letter-spacing: -.01em; margin-bottom: 8px; }
.cap { font-size: 12px; color: var(--muted); letter-spacing: .01em; margin-bottom: 6px;
  display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.tag { font-size: 11.5px; color: var(--muted); border: 1px solid var(--line-2);
  border-radius: 999px; padding: 1px 8px; white-space: nowrap; }
.q { font: 600 19px/1.35 var(--display); letter-spacing: -.012em; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.a { font-size: 16.5px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.rule { font-size: 14px; color: var(--text-2); line-height: 1.6; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.rule.folded { max-height: 9.6em; overflow: hidden; }
.small { font-size: 13px; color: var(--muted); }
.h1 { font-size: 24px; letter-spacing: -.02em; line-height: 1.2; }
.h2 { font: 600 12px/1 var(--body); color: var(--muted); text-transform: uppercase;
  letter-spacing: .07em; margin-bottom: 10px; }
.field-name { font-size: 12px; font-weight: 600; color: var(--muted); }
.field + .field-name { margin-top: 8px; }
.status { color: var(--fail); font-size: 13px; min-height: 1.4em; margin: 8px 0 0;
  text-align: center; }
.row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.toast { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
  background: var(--raised); border: 1px solid var(--line-2); border-radius: 10px;
  padding: 8px 14px; font-size: 13px; color: var(--text-2); opacity: 0;
  transition: opacity 160ms ease; pointer-events: none; }
.toast.on { opacity: 1; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__FONTS__
__STYLE__</style>
</head>
<body>
"""

BRAND = f'<div class="brand"><span class="mark">{LOGO}</span>judgekeeper</div>'


def _head(title: str, style: str) -> str:
    return (HEAD.replace("__TITLE__", title).replace("__FONTS__", font_faces())
            .replace("__STYLE__", STYLE + style))


def _text(value: str) -> str:
    """Text from a results file for a page: escaped, and with no `_`, so it can never hold
    one of the names the server fills in (__DATA__, __TOKEN__, __NONCE__)."""
    return escape(value).replace("_", "&#95;")


def _tag(description: str | None) -> str:
    """The app's name as a small tag, when the results name one."""
    return f'<span class="tag" id="about">{_text(description)}</span>' if description else ""


BY_THIS_RULE = "Mark each answer by this rule."


def _rule_block(rule: str | None, line: str) -> str:
    """The judge's rule (its words only) with `line` under its title, folded with "Show all"
    when long; nothing when there is none."""
    if not rule:
        return ""
    return f"""<div class="cap">Your judge's rule</div>
      <p class="small by-rule">{line}</p>
      <p class="rule folded" id="rule">{_text(f'"{rule}"')}</p>
      <button class="link small" id="show-all" type="button" hidden>Show all</button>"""


def _rule_card(rule: str | None, line: str) -> str:
    block = _rule_block(rule, line)
    return f'<div class="card">{block}</div>' if block else ""


# The script every page with a rule shares: "Show all" appears only when the rule is cut.
RULE_FOLD = """
  var rule = $("rule");
  if (rule && rule.scrollHeight > rule.clientHeight + 2) { $("show-all").hidden = false; }
  if (rule) { $("show-all").addEventListener("click", function () {
    rule.classList.remove("folded"); $("show-all").hidden = true; }); }
"""


REVIEW_STYLE = """
.top { display: flex; justify-content: space-between; align-items: center; gap: 16px;
  flex-wrap: wrap; }
.steps { list-style: none; padding: 0; display: flex; gap: 16px; font-size: 13px;
  color: var(--muted); }
.steps li { display: flex; align-items: center; gap: 7px; }
.steps i { font-style: normal; width: 20px; height: 20px; border-radius: 50%; display: grid;
  place-items: center; border: 1px solid var(--line-2); font-size: 11px; }
.steps .now { color: var(--text); }
.steps .now i { background: var(--text); color: var(--bg); border-color: var(--text); }
.steps .done i { color: var(--pass); border-color: var(--pass-line); background: var(--pass-bg); }
.answer { max-height: calc(100vh - 330px); min-height: 160px; display: flex;
  flex-direction: column; background: var(--card-2); border-color: var(--line-2); }
.answer .a { flex: 1; overflow: auto; padding-right: 6px; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.lead { font-size: 17px; letter-spacing: -.01em; }
.sub { margin-top: 4px; }
.opts { display: grid; gap: 8px; }
.opts .big { height: 50px; }
.big.unsure { color: var(--text-2); border-color: var(--line-2); background: rgba(148,163,184,.06); }
.opt { display: flex; align-items: center; justify-content: space-between; width: 100%;
  height: 46px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--line-2);
  background: var(--card); font-weight: 600; font-size: 14.5px;
  transition: transform 120ms var(--ease-out); }
.opt:active { transform: scale(.98); }
.opt.sel { border-color: var(--pass); background: var(--pass-bg); color: var(--pass); }
.big.sel { box-shadow: 0 0 0 2px currentColor inset; }
.opt:disabled { opacity: .6; }
.vs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.vs > div { border: 1px solid var(--line); background: var(--card); border-radius: 10px;
  padding: 10px 12px; min-width: 0; }
.vs span { display: block; font-size: 12px; color: var(--muted); }
.vs b { font-size: 17px; }
.vs p { font-size: 13px; color: var(--muted); margin-top: 2px; }
.vs .pass, #judge.pass { color: var(--pass); } .vs .fail, #judge.fail { color: var(--fail); }
.reason { font-size: 14px; color: var(--text-2); border-left: 2px solid var(--line-2);
  padding-left: 12px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 30vh;
  overflow: auto; }
.why { display: flex; flex-direction: column; gap: 6px; }
.why label { font-size: 12px; color: var(--muted); }
.why .row { flex-wrap: nowrap; }
.why input { flex: 1; min-width: 0; height: 38px; border-radius: 9px;
  border: 1px solid var(--pass-line); background: var(--bg); color: var(--text);
  padding: 0 11px; font: 400 14px var(--body); }
.center { justify-content: center; font-size: 13px; }
"""

REVIEW_BODY = """<div class="app">
<header class="hdr">
  __BRAND__
  <div class="mid"><span><b id="at">1</b> of <span id="all">0</span></span>
    <span class="bar" aria-hidden="true"><i id="bar"></i></span></div>
  <div class="end"><a class="link see" href="#">Back to your result</a></div>
</header>
<main class="body split">
<div class="col">
  <div class="top"><h1 class="h1">See where you disagree</h1>
    <ol class="steps">
      <li id="step-a"><i>1</i>Look again</li>
      <li id="step-b"><i>2</i>See what your judge said</li>
    </ol></div>
  <div class="card"><div class="cap">The question</div><div class="q" id="question"></div></div>
  <div class="card answer"><div class="cap">Your app's answer __ABOUT__</div>
    <div class="a" id="answer"></div></div>
</div>
<div class="col">
  <section class="panel" id="ask" aria-labelledby="lead">
    <div><h3 class="lead" id="lead"></h3><p class="small sub" id="sub"></p></div>
    <div id="verdicts" hidden>
      <div class="vs"><div><p id="said"></p></div>
        <div><span>Your judge said</span><b id="judge"></b></div></div>
      <div id="reason-wrap"><div class="cap">Your judge's reason</div>
        <p class="reason" id="reason"></p></div>
    </div>
    <div class="opts" id="look">
      <button class="big fail" id="fail" type="button" data-value="fail">__CROSS__Fail <kbd>←</kbd></button>
      <button class="big unsure" id="unsure" type="button" data-value="unsure">__QUESTION__Not sure <kbd>N</kbd></button>
      <button class="big pass" id="pass" type="button" data-value="pass">__TICK__Pass <kbd>→</kbd></button>
    </div>
    <div class="opts" id="see" hidden>
      <button class="opt" type="button" data-value="judge_wrong">Your judge was wrong <kbd>1</kbd></button>
      <button class="opt" type="button" data-value="slipped">I was wrong <kbd>2</kbd></button>
      <button class="opt" type="button" data-value="rule_unclear">The rule is unclear <kbd>3</kbd></button>
    </div>
    <div class="why" id="whybox-wrap" hidden>
      <label for="whybox">Why? (optional, helps fix your judge)</label>
      <div class="row"><input id="whybox" type="text" maxlength="300" autocomplete="off">
        <button class="btn primary" id="whynext" type="button">Next <kbd>Enter</kbd></button></div>
    </div>
    <div class="row center"><button class="link" id="undo" type="button">Undo <kbd>U</kbd></button></div>
    <p class="small" id="why"></p>
    <p class="status" id="status" role="status"></p>
  </section>
  __RULE_CARD__
  <p class="small">Every click is saved. Your first marks stay as you gave them. Close the tab
    any time; run <code>__COMMAND__ --review</code> to continue.</p>
</div>
</main>
</div>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__";
  var TEXT = {
    a: {lead: "Look again",
        sub: "Mark it once more. Your judge's answer stays hidden for now.",
        why: "Some of these are answers you and your judge agreed on, so being shown one " +
             "does not mean you were wrong."},
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
  // After Enter in the why box, the next answer is on its way (moving): a key pressed then
  // waits (queued) and counts for that answer once it is on screen.
  var moving = false, queued = null;
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  var buttons = Array.prototype.slice.call(
    document.querySelectorAll(step === "a" ? "#look button" : "#see button"));

  if (step === "done") { window.location.href = url("/result"); return; }
  Array.prototype.forEach.call(document.querySelectorAll(".see"), function (a) {
    a.setAttribute("href", url("/result")); });
  setText("lead", TEXT[step].lead); setText("sub", TEXT[step].sub); setText("why", TEXT[step].why);
  $("look").hidden = step !== "a"; $("see").hidden = step !== "b";
  $("verdicts").hidden = step !== "b";
  $("step-a").className = step === "a" ? "now" : "done";
  $("step-b").className = step === "b" ? "now" : "";
__RULE_FOLD__
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
        node.className = part[0] === "Pass" ? "pass" : "fail";
      }
      p.appendChild(node);
    });
  }

  function answered() { return items.filter(function (it) { return it[FIELD]; }).length; }

  function render() {
    var it = items[pos], done = answered();
    setText("at", pos + 1); setText("all", items.length);
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
    $("answer").scrollTop = 0;
    showWhy(it);
    busy = false;
    buttons.forEach(function (b) {
      b.disabled = false;
      b.classList.toggle("sel", it[FIELD] === b.getAttribute("data-value"));  // the choice made
    });
  }

  // The why box: under the buttons once Your judge was wrong or The rule is unclear is picked.
  function showWhy(it) {
    var on = step === "b" && WHY.indexOf(it.choice) >= 0;
    $("whybox-wrap").hidden = !on;
    if (on) { $("whybox").value = it.why || ""; }
  }

  function next() {
    for (var n = 1; n <= items.length; n++) {
      var i = (pos + n) % items.length;
      if (!items[i][FIELD]) { pos = i; render(); arrived(); return; }
    }
    window.location.reload();
  }

  // The next answer is on screen: a key pressed on the way counts for it now.
  function arrived() {
    var k = queued;
    moving = false; queued = null;
    if (k !== null) { byKey(k); }
  }

  // A failed save stays on this answer: a key pressed on the way is dropped.
  function stay() { moving = false; queued = null; render(); }

  function post(change, then) {
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      referrerPolicy: "same-origin", body: JSON.stringify(change)
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { setText("status", "Not saved: " + res.body.error); stay(); return; }
      setText("status", "");
      lastSummary = res.body.summary;
      then(res.body.summary);
    }).catch(function () {
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier clicks are saved.");
      stay();
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

  function goOn() {
    if (moving) { return; }
    moving = true;
    saveWhy(function () { after(lastSummary); });
  }

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
  // Step A's keys: ← Fail, N Not sure, → Pass (1 Pass, 2 Fail and 3 Not sure still work);
  // step B's: 1, 2, 3 in the order shown.
  var KEYS_A = {arrowleft: "fail", n: "unsure", arrowright: "pass", "1": "pass", "2": "fail",
                "3": "unsure"};
  function isKey(k) {
    return step === "a" && !!KEYS_A[k] || step === "b" && (k === "1" || k === "2" || k === "3")
      || k === "u";
  }
  function byKey(k) {
    if (step === "a" && KEYS_A[k]) { choose(KEYS_A[k]); }
    else if (step === "b" && (k === "1" || k === "2" || k === "3")) {
      choose(buttons[+k - 1].getAttribute("data-value")); }
    else if (k === "u") { undo(); }
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    var k = e.key.toLowerCase();
    if (moving) {  // also from the why box, which keeps the focus until the answer changes
      if (isKey(k)) { queued = k; e.preventDefault(); }
      return;
    }
    if (e.target === $("whybox") || !isKey(k)) { return; }
    byKey(k);
    e.preventDefault();
  });

  render();
})();
</script>
</body>
</html>
"""


def review_page(description: str | None, rule: str | None,
                command: str | None = None) -> str:
    """The review page, both steps: the page data says which one to show. The server fills
    in __DATA__, __TOKEN__ and __NONCE__. `command` (start.Talk.command) is what the person
    runs to continue."""
    command = command or textio.program("start")
    body = (REVIEW_BODY.replace("__COMMAND__", _text(command))
            .replace("__BRAND__", BRAND).replace("__CROSS__", CROSS)
            .replace("__TICK__", TICK).replace("__QUESTION__", QUESTION)
            .replace("__RULE_CARD__", _rule_card(rule, BY_THIS_RULE))
            .replace("__RULE_FOLD__", RULE_FOLD)
            .replace("__ABOUT__", _tag(description)))
    return _head("judgekeeper: see where you disagree", LABEL_STYLE_SHARED + REVIEW_STYLE) + body


# What the review and fix pages borrow from the labeling page's look: the two big buttons.
LABEL_STYLE_SHARED = """
.big { height: 56px; border-radius: 13px; display: flex; align-items: center;
  justify-content: center; gap: 12px; font: 600 17px/1 var(--body); border: 1.5px solid;
  transition: transform 120ms var(--ease-out), background-color 120ms ease; }
.big:active { transform: scale(.97); }
.big svg { width: 20px; height: 20px; }
.big.fail { color: var(--fail); border-color: var(--fail-line); background: var(--fail-bg); }
.big.pass { color: var(--pass); border-color: var(--pass-line); background: var(--pass-bg); }
.big:disabled { opacity: .6; }
"""


FIX_STYLE = """
.body.fix { align-content: start; }
.stick { position: sticky; top: calc(var(--hdr) + 20px); max-height: calc(100vh - var(--hdr) - 40px);
  overflow: auto; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.panel h3 { font-size: 17px; letter-spacing: -.01em; margin: 0; }
.panel p { font-size: 14px; color: var(--text-2); }
.counts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.count { display: flex; align-items: baseline; gap: 12px; }
.count .n { font: 800 30px/1 var(--display); letter-spacing: -.02em; }
.count .n.fail { color: var(--fail); } .count .n.pass { color: var(--pass); }
.count .l { color: var(--text-2); font-size: 14px; }
.pat { display: grid; grid-template-columns: 12px 1fr; gap: 10px; font-size: 14px;
  color: var(--text-2); padding: 8px 0; border-top: 1px solid var(--line); }
.pat:first-child { border-top: 0; padding-top: 0; }
.pat::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--amber);
  margin-top: 7px; }
.list > summary { cursor: pointer; list-style: none; }
.list > summary::-webkit-details-marker { display: none; }
.list > summary .h2 { margin: 0; display: flex; justify-content: space-between; }
.list > summary .h2::after { content: "Show"; font-weight: 500; text-transform: none;
  letter-spacing: 0; }
.list[open] > summary .h2::after { content: "Hide"; }
.list > summary .h2 b { font-weight: 600; } .h2 .pass { color: var(--pass); } .h2 .fail { color: var(--fail); }
.mist { list-style: none; padding: 0; margin: 10px 0 0; font-size: 14px; }
.mist li { padding: 9px 0; border-top: 1px solid var(--line); color: var(--text-2); }
.mist li:first-child { border-top: 0; }
.mist summary { cursor: pointer; display: grid; grid-template-columns: 1fr auto; gap: 12px;
  list-style: none; }
.mist summary::-webkit-details-marker { display: none; }
.mist summary::after { content: "Open"; color: var(--text-2); text-decoration: underline;
  text-decoration-color: var(--line-2); text-underline-offset: 3px; align-self: start; }
.mist details[open] summary::after { content: "Close"; }
.mist summary b { color: var(--text); font-weight: 600; overflow-wrap: anywhere; }
.mist .why-t { font-size: 12.5px; color: var(--muted); display: block; margin-top: 2px; }
.mist .cap { margin: 10px 0 4px; }
.box { padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--bg); white-space: pre-wrap; overflow-wrap: anywhere; max-height: 40vh;
  overflow: auto; font-size: 14px; color: var(--text); }
.meta { color: var(--muted); font-size: 13px; }
.none { color: var(--muted); font-size: 14px; margin-top: 8px; }
.pm p { margin: 0 0 6px; font-size: 14px; color: var(--text-2); }
.pm .sentence { font-size: 16px; color: var(--text); }
.pm h3 { margin: 14px 0 6px; font-size: 15px; }
.pm h4 { margin: 14px 0 6px; font-size: 14px; font-family: var(--body); }
.pm ul { margin: 0; padding-left: 20px; font-size: 14px; color: var(--text-2); }
.pm details { font-size: 14px; color: var(--text-2); } .pm summary { cursor: pointer; }
.pm code { white-space: normal; }
.pm .btn { margin-top: 6px; }
.rc h4 { margin: 0 0 6px; font-size: 14px; font-family: var(--body); color: var(--text); }
.rc ul { margin: 0; padding-left: 20px; font-size: 14px; color: var(--text-2); }
.rc pre.box { font: 13px/1.5 var(--mono); }
textarea { width: 100%; min-height: 110px; border-radius: 9px; border: 1px solid var(--line-2);
  background: var(--bg); color: var(--text); padding: 10px 12px; font: 13px/1.5 var(--mono);
  resize: vertical; }
.checks p { margin: 8px 0 0; font-weight: 600; color: var(--amber); font-size: 14px; }
.checks p.block { color: var(--fail); }
.diff { white-space: pre-wrap; overflow-wrap: anywhere; }
.diff ins { color: var(--pass); background: var(--pass-bg); text-decoration: none; }
.diff del { color: var(--fail); background: var(--fail-bg); }
.err { color: var(--fail); min-height: 1.2em; font-size: 13px; }
#status { color: var(--fail); min-height: 1.2em; margin: 6px 0 0; font-size: 13px; }
.saved-note { margin-top: 6px; }
"""

FIX_BODY = """<div class="app">
<header class="hdr">
  __BRAND__
  <div class="mid"></div>
  <div class="end"><a class="link see" href="#">Back to your result</a></div>
</header>
<main class="body split fix">
<div class="col">
  <div><h1 class="h1">What your judge gets wrong</h1><p class="small" id="aside"></p></div>
  <div class="card"><div class="cap" id="sub"></div><div class="counts" id="counts"></div></div>
  <section class="card" id="patterns-card" aria-label="Patterns in your judge's mistakes" hidden>
    <div class="h2">What stands out</div><div id="patterns"></div></section>
  <div class="col" id="lists"></div>
  <details class="card list" id="unclear"><summary><div class="h2" id="unclear-title"></div></summary>
    <ol class="mist"></ol></details>
  <p class="small saved-note">Free: no AI call. Saved in <code>.judgekeeper/fix/</code>. Your own files are
  never changed. <a class="link see" id="see" href="#">See your result</a></p>
</div>
<div class="col stick">
  <section class="panel rc" id="rc" hidden aria-labelledby="rc-title">
    <h3 id="rc-title">Change the rule</h3>
    <p id="rc-text" hidden></p>
    <div class="col" id="rc-do" hidden>
      <p>Change your judge's rule with your coding agent, any AI assistant, or yourself.
        judgekeeper never edits your files: it says where the new rule goes.</p>
      <div class="row">
        <button class="btn primary" id="rc-loop" type="button">Let your coding agent do it</button>
        <button class="btn" id="rc-ask" type="button">Copy a prompt for your AI assistant</button>
        <button class="btn" id="rc-self" type="button">I'll write it myself</button>
      </div>
      <div id="rc-loop-box" hidden>
        <p class="small">Paste this into your coding agent (Claude Code, Cursor or Codex).</p>
        <pre class="box" id="rc-loop-text"></pre>
        <button class="btn" id="rc-loop-copy" type="button">Copy</button>
        <p class="small">It reads your mistakes from a file in .judgekeeper/, so your answers are
          not in this text. It asks you before anything that costs money.</p>
        <p class="small">When your agent has saved the new rule, reload this page to see it.</p>
      </div>
      <div id="rc-prompt" hidden>
        <p class="small">Paste this into any AI assistant. It holds only the answers judgekeeper
          used, never the ones kept aside.</p>
        <pre class="box" id="rc-prompt-text"></pre>
        <button class="btn" id="rc-copy" type="button">Copy</button>
      </div>
      <div id="rc-paste" hidden>
        <label class="cap" for="rc-new" id="rc-new-label">Paste the new rule here</label>
        <textarea id="rc-new" spellcheck="false"
          placeholder="Paste the whole reply. judgekeeper takes the rule from between NEW RULE START and NEW RULE END."></textarea>
        <button class="btn green" id="rc-save" type="button">Save the new rule</button>
      </div>
      <div class="checks" id="rc-checks" aria-live="polite"></div>
      <div id="rc-saved" hidden>
        <h4>Your new rule, against the old one</h4>
        <p class="small" id="rc-how" hidden>Your coding agent wrote this rule.</p>
        <p class="diff box" id="rc-diff"></p>
        <h4>Where it goes</h4>
        <ul id="rc-where"></ul>
        <h4>Or ask your coding agent</h4>
        <pre class="box" id="rc-agent"></pre>
        <button class="btn" id="rc-agent-copy" type="button">Copy</button>
        <p id="rc-last"></p>
      </div>
    </div>
    <p class="err" id="rc-status" role="status"></p>
  </section>
  <div class="card" id="rule-card" hidden><div class="cap">Your judge's rule today</div>
    <p class="rule" id="rule"></p></div>
  <section class="card pm" id="pm" hidden aria-labelledby="pm-title">
    <h3 id="pm-title">Move the pass mark</h3>
    <div id="pm-lines"></div>
    <button class="btn green" id="pm-test" type="button" hidden></button>
    <div id="pm-result" aria-live="polite"></div>
    <p id="status" role="status"></p>
  </section>
</div>
</main>
</div>
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
  // Each row: the question and the person's why; open, the full answer and the judge's reason.
  function items(list, ol) {
    list.forEach(function (it) {
      var li = el("li"), d = el("details"), s = el("summary"), head = el("span");
      head.appendChild(el("b", null, short(it.input)));
      if (it.why) { head.appendChild(el("span", "why-t", "Your why: " + it.why)); }
      s.appendChild(head); d.appendChild(s);
      d.appendChild(el("div", "cap", "The question")); d.appendChild(question(it.input));
      d.appendChild(el("div", "cap", "Your app's answer")); d.appendChild(el("div", "box", it.output));
      if (it.reason) {
        d.appendChild(el("div", "cap", "Your judge's reason"));
        d.appendChild(el("div", "box", it.reason));
      }
      li.appendChild(d); ol.appendChild(li);
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll(".see"), function (a) {
    a.setAttribute("href", url("/result")); });
  $("sub").textContent = "On the " + data.used + " answers judgekeeper used";
  $("aside").textContent = data.aside;
  if (data.rule) { $("rule-card").hidden = false; $("rule").textContent = data.rule; }
  $("patterns-card").hidden = !data.lines.length;
  data.lines.forEach(function (line) {
    var p = el("div", "pat"); p.appendChild(el("span", null, line)); $("patterns").appendChild(p); });
  data.lists.forEach(function (list, n) {
    // "Passed, but you said Fail (3)", the two decisions in their colours
    var words = (list.judge === "Pass" ? "Passed" : "Failed") + ", but you said " + list.you;
    var count = el("div", "count");
    count.appendChild(el("span", "n " + (n === 0 ? "fail" : "pass"), list.items.length));
    count.appendChild(el("span", "l", words));
    $("counts").appendChild(count);
    var d = el("details", "card list " + (n === 0 ? "pass-wrong" : "fail-wrong")), s = el("summary");
    var h = el("div", "h2"), t = el("span");
    t.appendChild(el("b", list.judge === "Pass" ? "pass" : "fail",
      list.judge === "Pass" ? "Passed" : "Failed"));
    t.appendChild(document.createTextNode(", but you said "));
    t.appendChild(el("b", list.you === "Pass" ? "pass" : "fail", list.you));
    t.appendChild(document.createTextNode(" (" + list.items.length + ")"));
    h.appendChild(t); s.appendChild(h); d.appendChild(s);
    if (list.items.length) { d.open = true; }
    var ol = el("ol", "mist"); items(list.items, ol); d.appendChild(ol);
    if (!list.items.length) { d.appendChild(el("p", "none", "None.")); }
    $("lists").appendChild(d);
  });
  var unclear = $("unclear");
  $("unclear-title").textContent = data.unclear.title;
  unclear.hidden = !data.unclear.items.length;
  items(data.unclear.items, unclear.querySelector("ol"));

  function renderTest(test) {
    var box = $("pm-result");
    box.textContent = "";
    if (!test) { return; }
    box.appendChild(el("p", "sentence", test.lines[0]));
    box.appendChild(el("p", null, test.lines[1]));
    var d = el("details"), ul = el("ul");
    d.appendChild(el("summary", null, "How often your judge agreed with you, before and after"));
    test.numbers.forEach(function (line) { ul.appendChild(el("li", null, line)); });
    d.appendChild(ul); box.appendChild(d);
    box.appendChild(el("h4", null, test.kind === "better" ? "Where to change it"
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
      referrerPolicy: "same-origin", body: JSON.stringify({mark: data.pass_mark.mark})
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

  function postJSON(path, body) {
    return fetch(url(path), {
      method: "POST", headers: {"Content-Type": "application/json"},
      referrerPolicy: "same-origin", body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (b) { return {ok: r.ok, body: b}; });
    });
  }
  var LOST = "this page lost its link to judgekeeper. Is it still running in your terminal?";

  function copy(text, button) {
    function done(ok) {
      button.textContent = ok ? "Copied" : "Select the text and copy it";
      setTimeout(function () { button.textContent = "Copy"; }, 2000);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); },
        function () { done(false); });
    } else { done(false); }
  }

  var how = "pasted", PASTE_LABEL = "Paste the new rule here";
  function renderRule() {
    var rc = data.rule_change;
    $("rc").hidden = !rc;
    if (!rc) { return; }
    $("rc-text").hidden = rc.kind === "ok";
    $("rc-do").hidden = rc.kind !== "ok";
    if (rc.kind !== "ok") { $("rc-text").textContent = rc.text; return; }
    var saved = rc.saved;
    $("rc-saved").hidden = !saved;
    if (!saved) { return; }
    $("rc-how").hidden = saved.how !== "agent";
    showChecks(saved.checks);
    var diff = $("rc-diff");
    diff.textContent = "";
    saved.diff.forEach(function (part) {
      var tag = part[0] === "add" ? "ins" : part[0] === "del" ? "del" : "span";
      diff.appendChild(el(tag, null, part[1]));
    });
    var where = $("rc-where");
    where.textContent = "";
    [saved.hand_over.where].concat(saved.hand_over.notes).forEach(function (line) {
      where.appendChild(el("li", null, line));
    });
    $("rc-agent").textContent = saved.hand_over.agent_prompt;
    $("rc-last").textContent = saved.hand_over.last;
  }

  function showChecks(checks) {
    var box = $("rc-checks");
    box.textContent = "";
    checks.forEach(function (c) { box.appendChild(el("p", c.blocking ? "block" : null, c.text)); });
  }

  $("rc-loop").addEventListener("click", function () {
    var button = $("rc-loop");
    button.disabled = true;
    postJSON("/fix/agent-prompt", {}).then(function (res) {
      button.disabled = false;
      if (!res.ok) { $("rc-status").textContent = res.body.error; return; }
      $("rc-status").textContent = "";
      $("rc-loop-text").textContent = res.body.prompt;
      $("rc-loop-box").hidden = false;
      $("rc-prompt").hidden = true;
      $("rc-paste").hidden = true;
    }).catch(function () { button.disabled = false; $("rc-status").textContent = LOST; });
  });
  $("rc-loop-copy").addEventListener("click", function () {
    copy($("rc-loop-text").textContent, $("rc-loop-copy"));
  });
  $("rc-ask").addEventListener("click", function () {
    var button = $("rc-ask");
    button.disabled = true;
    postJSON("/fix/prompt", {}).then(function (res) {
      button.disabled = false;
      if (!res.ok) { $("rc-status").textContent = res.body.error; return; }
      $("rc-status").textContent = "";
      $("rc-prompt-text").textContent = res.body.prompt;
      $("rc-loop-box").hidden = true;
      $("rc-prompt").hidden = false;
      how = "pasted";
      $("rc-paste").hidden = false;
      $("rc-new-label").textContent = PASTE_LABEL;
      $("rc-new").value = "";
      copy(res.body.prompt, $("rc-copy"));
    }).catch(function () { button.disabled = false; $("rc-status").textContent = LOST; });
  });
  $("rc-copy").addEventListener("click", function () {
    copy($("rc-prompt-text").textContent, $("rc-copy"));
  });
  $("rc-self").addEventListener("click", function () {
    how = "written";
    $("rc-loop-box").hidden = true;
    $("rc-prompt").hidden = true;
    $("rc-paste").hidden = false;
    $("rc-new-label").textContent = "Change the rule here, or paste a new one";
    $("rc-new").value = data.rule_change.rule;
    $("rc-new").focus();
  });
  $("rc-save").addEventListener("click", function () {
    var button = $("rc-save");
    if ($("rc-new").value.length > data.rule_change.max_paste) {
      $("rc-status").textContent = "Too long to save. Paste only the new rule.";
      return;
    }
    button.disabled = true;
    postJSON("/fix/rule", {text: $("rc-new").value, how: how}).then(function (res) {
      button.disabled = false;
      if (!res.ok) { $("rc-status").textContent = "Not saved: " + res.body.error; return; }
      $("rc-status").textContent = "";
      data.rule_change = res.body.rule_change;
      renderRule();
      showChecks(res.body.result.checks);
    }).catch(function () { button.disabled = false; $("rc-status").textContent = LOST; });
  });
  $("rc-agent-copy").addEventListener("click", function () {
    copy($("rc-agent").textContent, $("rc-agent-copy"));
  });

  renderPM();
  renderRule();
})();
</script>
</body>
</html>
"""


def fix_page(description: str | None) -> str:
    """The fix page ("What your judge gets wrong"). The server fills in __DATA__, __TOKEN__
    and __NONCE__; everything shown comes from the data, through textContent."""
    del description  # the page is about the judge, not the app: nothing from it is shown
    return _head("judgekeeper: fix your judge", FIX_STYLE) + FIX_BODY.replace("__BRAND__", BRAND)
