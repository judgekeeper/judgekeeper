"""The pages judgekeeper shows: the labeling page and the result page.

Each is one self-contained page: no fonts, scripts or images from anywhere else. The heading
font (Bricolage Grotesque, under the SIL Open Font License) is embedded as base64 from this
package's `fonts/` folder. Text reaches the pages through textContent. The labeling page holds
nothing the judge said.

The result page runs no script and loads nothing, so the copy saved as
`.judgekeeper/report.html` opens with no server. Every string in it is escaped.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from importlib import resources

from judgekeeper import textio
from judgekeeper.judge_check import TITLE as JUDGE_CHECK_TITLE

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


LOGO = """<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 2.5l7.5 3v6c0 4.6-3.2 8.4-7.5 10-4.3-1.6-7.5-5.4-7.5-10v-6z" fill="#0E1525"/>
      <path d="M12 2.5l7.5 3v6c0 4.6-3.2 8.4-7.5 10z" fill="#10B981"/>
      <path d="M8.3 12.2l2.5 2.5 4.9-5" stroke="#fff" stroke-width="2" stroke-linecap="round"
        stroke-linejoin="round" fill="none"/>
    </svg>"""

CROSS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" '
         'stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>')
TICK = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" '
        'stroke="currentColor" stroke-width="2.3" stroke-linecap="round" '
        'stroke-linejoin="round"/></svg>')

ICONS = {  # the coloured line's icon, by name: the words carry the meaning too
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


# The script every page with a rule shares: "Show all" appears only when the rule is cut.
RULE_FOLD = """
  var rule = $("rule");
  if (rule && rule.scrollHeight > rule.clientHeight + 2) { $("show-all").hidden = false; }
  if (rule) { $("show-all").addEventListener("click", function () {
    rule.classList.remove("folded"); $("show-all").hidden = true; }); }
"""


LABEL_STYLE = """
.app { height: 100vh; }
.dots { display: flex; gap: 4px; justify-content: center; align-items: center;
  padding: 14px 24px 0; flex-wrap: wrap; max-width: 760px; margin: 0 auto; min-height: 23px; }
.dots button { width: 9px; height: 9px; padding: 0; border-radius: 50%; background: var(--line-2);
  transition: transform 120ms var(--ease-out); }
.dots button:hover { transform: scale(1.5); }
.dots .p { background: var(--pass); } .dots .f { background: var(--fail); }
.dots .s { background: transparent; box-shadow: inset 0 0 0 1.5px var(--line-2); }
.dots .now { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--text-2); }
.dots .more { font-size: 12px; color: var(--muted); margin: 0 6px; }
.stage { flex: 1; min-height: 0; display: grid; justify-content: center; gap: 28px;
  grid-template-columns: minmax(200px, 300px) minmax(0, 720px) minmax(200px, 300px);
  padding: 22px 28px 26px; align-items: start; overflow: auto; }
/* No rule to show (a table, say): no empty column, the answer gets the room */
.stage.no-rule { grid-template-columns: minmax(0, 760px) minmax(200px, 300px); }
.stage.no-rule > .side.rule { display: none; }
@media (max-width: 1200px) {
  .stage { gap: 20px; padding: 18px 20px 22px;
    grid-template-columns: minmax(160px, 220px) minmax(0, 1fr) minmax(160px, 220px); }
  .stage.no-rule { grid-template-columns: minmax(0, 1fr) minmax(160px, 220px); }
}
.side .by-rule { margin: -2px 0 8px; }
.how { margin-top: 22px; display: grid; gap: 9px; font-size: 13px; color: var(--muted); }
.how div { display: flex; align-items: center; gap: 8px; }
.side .ready { margin-top: 22px; color: var(--text-2); }
.side .ready:empty { display: none; }
.side .note { margin-top: 10px; }
.stack { position: relative; height: clamp(320px, 100vh - 300px, 440px); }
.swipe { position: absolute; inset: 0; background: var(--card); border: 1px solid var(--line-2);
  border-radius: 18px; padding: 22px 24px 20px; display: flex; flex-direction: column;
  box-shadow: 0 30px 60px -36px rgba(0,0,0,.85); touch-action: pan-y; user-select: none;
  -webkit-user-select: none; cursor: grab; transform-origin: 50% 120%; will-change: transform; }
.swipe.dragging { cursor: grabbing; }
.swipe.behind { transform: translateY(12px) scale(.965); opacity: .55; pointer-events: none;
  box-shadow: none; }
.swipe.plain { cursor: default; justify-content: center; align-items: center;
  text-align: center; gap: 16px; user-select: text; -webkit-user-select: text; }
.swipe.plain h2 { font-size: 22px; letter-spacing: -.015em; }
.scrollbox { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column;
  justify-content: safe center; gap: 14px; padding-right: 4px; }
.chat { display: flex; } .chat.reply { justify-content: flex-end; }
.chat > div { max-width: 86%; min-width: 0; }
.who { font-size: 12px; color: var(--muted); margin-bottom: 5px; display: flex;
  align-items: center; gap: 6px; }
.reply .who { justify-content: flex-end; }
.bubble { padding: 12px 15px; border-radius: 16px; line-height: 1.6; white-space: pre-wrap;
  overflow-wrap: anywhere; }
.ask .bubble { background: var(--card-2); border-bottom-left-radius: 5px;
  font: 600 17px/1.45 var(--display); letter-spacing: -.01em; }
.ask .bubble .field-name { font-family: var(--body); }
.reply .bubble { background: #223152; border: 1px solid rgba(147,197,253,.10);
  border-bottom-right-radius: 5px; font-size: 16px; }
.stamp { position: absolute; top: 22px; padding: 6px 14px; border-radius: 10px;
  border: 2px solid; font: 800 22px/1 var(--display); letter-spacing: .02em; opacity: 0;
  pointer-events: none; transition: opacity 120ms ease; }
.stamp.fail { left: 22px; color: var(--fail); border-color: var(--fail); transform: rotate(-10deg); }
.stamp.pass { right: 22px; color: var(--pass); border-color: var(--pass); transform: rotate(10deg); }
.decide { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; align-items: center;
  margin-top: 16px; }
.big { height: 56px; border-radius: 13px; display: flex; align-items: center;
  justify-content: center; gap: 12px; font: 600 17px/1 var(--body); border: 1.5px solid;
  transition: transform 120ms var(--ease-out), background-color 120ms ease; }
.big:active, .big.hit { transform: scale(.97); }
.big svg { width: 20px; height: 20px; }
.big.fail { color: var(--fail); border-color: var(--fail-line); background: var(--fail-bg); }
.big.pass { color: var(--pass); border-color: var(--pass-line); background: var(--pass-bg); }
.big.fail.hit { background: rgba(245,158,139,.22); } .big.pass.hit { background: rgba(52,211,153,.22); }
.big:disabled { opacity: .6; }
.mini { display: flex; gap: 14px; font-size: 13px; white-space: nowrap; }
.scrim { position: fixed; inset: 0; background: rgba(6,10,20,.6); display: grid;
  place-items: center; -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
  z-index: 20; }
.intro { width: 430px; background: var(--raised); border: 1px solid var(--line-2);
  border-radius: 16px; padding: 26px 26px 22px; text-align: center;
  box-shadow: 0 30px 80px -30px rgba(0,0,0,.85); }
.intro h2 { font-size: 20px; line-height: 1.3; letter-spacing: -.015em; margin: 14px 0 8px; }
.intro p { color: var(--text-2); font-size: 14.5px; }
.intro p + p { margin-top: 10px; }
.intro .tip { margin-top: 12px; font-size: 13px; color: var(--muted); }
.intro .btn { margin-top: 18px; min-width: 120px; }
.logo-tile { width: 48px; height: 48px; border-radius: 12px; background: #E9EEF5; display: grid;
  place-items: center; margin: 0 auto; }
.logo-tile svg { width: 28px; height: 28px; }
"""

LABEL_BODY = """<div class="app">
<header class="hdr">
  __BRAND__
  <div class="mid"><span><b id="at">1</b> of <span id="all">0</span></span>
    <span class="bar" aria-hidden="true"><i id="bar"></i></span></div>
  <div class="end"><span class="saved" id="saved">Saved</span>
    <a class="btn green see" href="#" hidden>See your result</a></div>
</header>
<div class="dots" id="dots" title="Click a dot to go back to that answer"></div>
<main class="stage__STAGE_CLASS__">
<aside class="side rule">
  __RULE_BLOCK__
</aside>
<section class="task" aria-label="The answer to mark">
  <div class="stack" id="stack"></div>
  <div class="decide">
    <button class="big fail" id="fail" type="button">__CROSS__Fail <kbd>←</kbd></button>
    <div class="mini">
      <button class="link" id="skip" type="button"
        title="Can't tell from the text? Skip it. You can come back to it.">Skip <kbd>S</kbd></button>
      <button class="link" id="undo" type="button">Undo <kbd>U</kbd></button>
    </div>
    <button class="big pass" id="pass" type="button">__TICK__Pass <kbd>→</kbd></button>
  </div>
  <p class="status" id="status" role="status"></p>
  <span id="about" hidden>__ABOUT__</span>
</section>
<aside class="side" aria-label="The keys">
  <p class="small">Mark each answer Pass or Fail. What your judge decided stays hidden.</p>
  <div class="how">
    <div><kbd>←</kbd> or drag left: Fail</div>
    <div><kbd>→</kbd> or drag right: Pass</div>
    <div><kbd>S</kbd> Skip &nbsp; <kbd>U</kbd> Undo</div>
    <div>Click a dot at the top to go back to any answer, skipped ones too.</div>
  </div>
  <p class="small ready" id="ready" aria-live="polite"></p>
  <p class="small note">Every click is saved. Close the tab any time; run
    <code>__COMMAND__</code> to continue.</p>
</aside>
</main>
</div>
<div class="scrim" id="intro" hidden>
  <div class="intro" role="dialog" aria-labelledby="intro-title">
    <div class="logo-tile">__LOGO__</div>
    <h2 id="intro-title">Mark each answer Pass or Fail, using your judge's rule.</h2>
    <p>You won't see what your judge decided. That way your marks are your own, and the check
      is fair.</p>
    <p>Your judge is the AI that grades your app's answers in your evals. judgekeeper then
      shows how often it agrees with you.</p>
    <p class="tip">Use <kbd>←</kbd> <kbd>→</kbd>, the buttons, or drag the card.</p>
    <button class="btn primary" id="intro-ok" type="button">OK</button>
  </div>
</div>
<div class="toast" id="toast" aria-live="polite"></div>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", MAX_DOTS = 60;
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, counts = data.counts, pos = data.start, busy = false, history = [];
  var total = data.total || items.length;  // the page holds the next answers, not all of them
  var shownAt = Date.now();  // when the answer on screen was shown: each mark sends its seconds
  var status = data.status;  // the line in the right column, from the server
  var ended = false;         // nothing left to mark: the page shows what comes next
  var walkingSkipped = false;  // "Look at them": going through the skipped answers
  var ABOUT = document.getElementById("about").textContent;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }
  function each(selector, fn) {
    Array.prototype.forEach.call(document.querySelectorAll(selector), fn); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text != null) { e.textContent = String(text); }
    return e;
  }
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }

  each(".see", function (a) { a.setAttribute("href", url("/result")); });

  // pure: start
  // The rules a dragged card follows. Nothing here touches the page; tests run it in node.
  var COMMIT_SHARE = 0.28, FLICK = 0.55, START_AT = 8, TILT_MAX = 12, TILT_PER_WIDTH = 18;
  var SPRING_K = 520;
  function tilt(x, width) {  // degrees: offset / width x 18, at most 12 either way
    return Math.max(-TILT_MAX, Math.min(TILT_MAX, x / width * TILT_PER_WIDTH)); }
  function stampOpacity(x, width) {  // fully visible at 28% of the width
    return Math.min(1, Math.abs(x) / (width * COMMIT_SHARE)); }
  function dragStarts(mx, my) { return Math.abs(mx) >= START_AT || Math.abs(my) >= START_AT; }
  function isVertical(mx, my) { return Math.abs(my) > Math.abs(mx); }
  // "pass", "fail" or null: past 28% of the width, or a flick over 0.55 px/ms the same way.
  function commit(dx, velocity, width) {
    var far = Math.abs(dx) > width * COMMIT_SHARE;
    var flick = Math.abs(velocity) > FLICK && Math.sign(velocity) === Math.sign(dx);
    if (!far && !flick) { return null; }
    return dx > 0 ? "pass" : "fail";
  }
  function releaseVelocity(hist) {  // px per ms over the last few moves
    var a = hist[0], b = hist[hist.length - 1];
    return (b.x - a.x) / Math.max(1, b.t - a.t);
  }
  function flyDuration(x, endX, velocity) {  // 140 to 260 ms, at the hand's speed
    var speed = Math.max(Math.abs(velocity), 1.4);
    return Math.min(260, Math.max(140, Math.abs(endX - x) / speed));
  }
  // One step of a critically damped spring back to 0: [position, velocity].
  function springStep(position, velocity, dt) {
    var c = 2 * Math.sqrt(SPRING_K), acc = -SPRING_K * position - c * velocity;
    velocity += acc * dt;
    return [position + velocity * dt, velocity];
  }
  function springDone(position, velocity) {
    return Math.abs(position) < 0.3 && Math.abs(velocity) < 5; }
  // pure: end

  // A question is text, or [[name, value], ...]: each name a small label above its value.
  function showQuestion(value, into) {
    if (!Array.isArray(value)) { into.textContent = value == null ? "" : String(value); return; }
    value.forEach(function (pair) {
      into.appendChild(el("div", "field-name", pair[0]));
      into.appendChild(el("div", "field", pair[1]));
    });
  }

  function card(it) {  // the chat: the question on the left, your app's answer on the right
    var c = el("div", "swipe"), box = el("div", "scrollbox");
    c.appendChild(el("div", "stamp fail", "FAIL")); c.appendChild(el("div", "stamp pass", "PASS"));
    var ask = el("div", "chat ask"), askWrap = el("div"), q = el("div", "bubble");
    askWrap.appendChild(el("div", "who", "The question"));
    showQuestion(it.input, q); askWrap.appendChild(q); ask.appendChild(askWrap);
    var reply = el("div", "chat reply"), replyWrap = el("div");
    var who = el("div", "who", "Your app's answer");
    if (ABOUT) { who.appendChild(el("span", "tag", ABOUT)); }
    replyWrap.appendChild(who); replyWrap.appendChild(el("div", "bubble", it.output));
    reply.appendChild(replyWrap);
    box.appendChild(ask); box.appendChild(reply); c.appendChild(box);
    return c;
  }

  function renderHeader() {
    setText("at", Math.min(pos + 1, total)); setText("all", total);
    var done = counts.correct + counts.wrong;
    $("bar").style.width = (total ? done / total * 100 : 0) + "%";
    setText("ready", status.text);
    each(".see", function (a) { a.hidden = !status.ready; });
    renderDots();
  }

  // One dot per answer, in the person's own colours; over MAX_DOTS, a window around the
  // current one with "+N" for the rest.
  function renderDots() {
    var dots = $("dots"), n = items.length;
    dots.textContent = "";
    var from = Math.max(0, n - MAX_DOTS);
    if (pos < from) { from = Math.max(0, Math.min(pos, n - MAX_DOTS)); }
    var to = Math.min(n, from + MAX_DOTS);
    if (from > 0) { dots.appendChild(el("span", "more", "+" + from)); }
    for (var k = from; k < to; k++) {
      var it = items[k], b = el("button", it.label === "pass" ? "p" : it.label === "fail" ? "f"
        : it.skipped ? "s" : "");
      if (k === pos && !ended) { b.className += " now"; }
      b.type = "button"; b.setAttribute("data-k", String(k));
      b.setAttribute("aria-label", "Answer " + (k + 1));
      dots.appendChild(b);
    }
    if (to < total) { dots.appendChild(el("span", "more", "+" + (total - to))); }
  }
  $("dots").addEventListener("click", function (e) {
    var k = e.target.getAttribute && e.target.getAttribute("data-k");
    if (k == null || flying) { return; }
    walkingSkipped = false; open(+k);
  });

  function render() {
    var stack = $("stack");
    stack.textContent = "";
    if (nextIndex(pos + 1) !== null) { stack.appendChild(el("div", "swipe behind")); }
    var c = card(items[pos]);
    stack.appendChild(c); bindDrag(c);
    renderHeader();
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

  // Nothing left to mark: the result, or first the skipped answers.
  function finish() {
    ended = true; busy = false;
    $("pass").disabled = true; $("fail").disabled = true;
    renderHeader();
    var stack = $("stack"), c = el("div", "swipe plain");
    stack.textContent = ""; stack.appendChild(c);
    var skipped = items.filter(function (it) { return it.skipped; }).length;
    if (!skipped) {
      c.appendChild(el("h2", null, "You marked every answer."));
      window.location.href = url("/result");
      return;
    }
    var them = skipped === 1 ? "it" : "them";
    c.appendChild(el("h2", null, "You skipped " + skipped + (skipped === 1 ? " answer" : " answers")
      + ". Look at " + them + " again?"));
    var row = el("div", "row"), again = el("button", "btn primary", "Look at " + them);
    var see = el("a", "btn", "See your result");
    again.type = "button"; see.href = url("/result");
    again.addEventListener("click", function () { walkingSkipped = true; open(nextIndex(0)); });
    row.appendChild(again); row.appendChild(see); c.appendChild(row);
  }

  function flashSaved() {
    var s = $("saved");
    s.style.opacity = "0.4";
    window.requestAnimationFrame(function () { s.style.opacity = "1"; });
  }
  var toastTimer;
  function toast(text) {
    var t = $("toast");
    t.textContent = text; t.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("on"); }, 900);
  }

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
      if (!res.ok) { setText("status", "Not saved: " + res.body.error); render(); return; }
      counts = res.body.summary.counts; status = res.body.summary.status;
      setText("status", "");
      flashSaved();
      then();
    }).catch(function () {
      setText("status", "Not saved: this page lost its link to judgekeeper. Is it still " +
        "running in your terminal? Your earlier marks are saved.");
      render();
    });
    return true;
  }

  // Pass or Fail: saved at once, with no card animation (people do this dozens of times).
  // `after` runs once the mark is saved and the next answer is on screen.
  function mark(value, after) {
    if (ended) { return false; }
    var it = items[pos];
    return send({label: value}, function () {
      it.label = value; it.skipped = false; history.push(pos); next();
      if (after) { after(); }
    });
  }

  // A card flying off after a drag is still its answer's mark: until it is saved, a key
  // waits (queued) and then counts for the next answer, and a click does nothing, so one
  // gesture marks one answer.
  var flying = false, queued = null;

  function skip() {
    if (ended) { return; }
    var it = items[pos];
    send({deferred: true}, function () {
      it.label = null; it.skipped = true; history.push(pos); next(); });
  }

  function undo() {
    if (!history.length) { setText("status", "Nothing to undo."); return; }
    var back = history.pop();
    walkingSkipped = false; open(back);
    var it = items[pos];
    send({label: null, deferred: false}, function () {
      it.label = null; it.skipped = false; render(); toast("Undone"); });
  }

  function hit(value) {  // the pressed button flashes for 120 ms
    var b = $(value);
    b.classList.add("hit");
    setTimeout(function () { b.classList.remove("hit"); }, 120);
  }

  // Drag: the card follows the pointer 1:1 and tilts; past 28% of its width or on a flick it
  // flies off and the mark is saved; released early, it springs back.
  function bindDrag(c) {
    var x0 = 0, y0 = 0, dx = 0, active = false, decided = false, hist = [];
    var stampFail = c.querySelector(".stamp.fail"), stampPass = c.querySelector(".stamp.pass");
    function width() { return c.offsetWidth || 1; }
    function set(x) {
      c.style.transform = "translateX(" + x + "px) rotate(" + tilt(x, width()) + "deg)";
      var t = stampOpacity(x, width());
      stampFail.style.opacity = x < 0 ? t : 0; stampPass.style.opacity = x > 0 ? t : 0;
    }
    c.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || ended || busy) { return; }
      active = true; decided = false; x0 = e.clientX; y0 = e.clientY; dx = 0;
      hist = [{x: 0, t: e.timeStamp}];
      if (c._spring) { c._spring.cancel(); c._spring = null; }
    });
    c.addEventListener("pointermove", function (e) {
      if (!active) { return; }
      var mx = e.clientX - x0, my = e.clientY - y0;
      if (!decided) {
        if (!dragStarts(mx, my)) { return; }
        if (isVertical(mx, my)) { active = false; return; }  // vertical: the answer scrolls
        decided = true; c.setPointerCapture(e.pointerId); c.classList.add("dragging");
        var sel = window.getSelection(); if (sel) { sel.removeAllRanges(); }
      }
      dx = mx; set(dx);
      hist.push({x: dx, t: e.timeStamp}); if (hist.length > 6) { hist.shift(); }
    });
    function end() {
      if (!active) { return; }
      active = false; c.classList.remove("dragging");
      if (!decided) { return; }
      var v = releaseVelocity(hist), value = commit(dx, v, width());
      if (value) { flyOut(c, dx, v, value); } else { springBack(c, dx, v, set); }
    }
    c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
  }
  function flyOut(c, x, v, value) {
    hit(value);
    if (reduce || !c.animate) { if (!mark(value)) { render(); } return; }
    var dir = x > 0 ? 1 : -1, endX = dir * (window.innerWidth * 0.75);
    c.style.pointerEvents = "none";
    flying = true;
    c.animate([{transform: "translateX(" + x + "px) rotate(" + tilt(x, c.offsetWidth || 1) +
                           "deg)", opacity: 1},
               {transform: "translateX(" + endX + "px) rotate(" + (dir * 18) + "deg)", opacity: 0}],
              {duration: flyDuration(x, endX, v), easing: "cubic-bezier(.2,.7,.4,1)",
               fill: "forwards"}).finished.then(function () {
                 function landed() {
                   flying = false;
                   var k = queued;
                   queued = null;
                   if (k) { byKey(k); }
                 }
                 if (!mark(value, landed)) { render(); landed(); }
               });
  }
  // The spring's path is worked out up front (60 steps a second, at most 2 seconds) and
  // played as one animation, so it runs the same whatever the screen is doing.
  function springPath(x, v, width) {
    var p = x, vel = v * 1000, frames = [], dt = 1 / 60;
    while (!springDone(p, vel) && frames.length < 120) {
      frames.push("translateX(" + p + "px) rotate(" + tilt(p, width) + "deg)");
      var s = springStep(p, vel, dt); p = s[0]; vel = s[1];
    }
    frames.push("translateX(0px) rotate(0deg)");
    return frames;
  }
  function springBack(c, x, v, set) {
    if (reduce) { set(0); c.style.transform = ""; return; }
    var frames = springPath(x, v, c.offsetWidth || 1);
    c.querySelector(".stamp.fail").style.opacity = 0; c.querySelector(".stamp.pass").style.opacity = 0;
    if (!c.animate) { set(0); c.style.transform = ""; return; }
    c.style.transform = "";
    c._spring = c.animate(frames.map(function (t) { return {transform: t}; }),
                          {duration: frames.length * 1000 / 60, easing: "linear"});
    c._spring.finished.then(function () { set(0); c.style.transform = ""; }, function () {});
  }

  // Keys and buttons mark at once: only the pressed button flashes.
  $("pass").addEventListener("click", function () {
    if (!flying) { hit("pass"); mark("pass"); } });
  $("fail").addEventListener("click", function () {
    if (!flying) { hit("fail"); mark("fail"); } });
  $("skip").addEventListener("click", function () { if (!flying) { skip(); } });
  $("undo").addEventListener("click", function () { if (!flying) { undo(); } });
  // The keys: → Pass and ← Fail (shown), 1 Pass and 2 Fail (an old habit, still working).
  var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};
  function byKey(k) {
    if (KEYS[k]) { hit(KEYS[k]); mark(KEYS[k]); }
    else if (k === "s") { skip(); } else if (k === "u") { undo(); }
  }
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden) { return; }
    var k = e.key.toLowerCase();
    if (!KEYS[k] && k !== "s" && k !== "u") { return; }
    if (flying) { queued = k; } else { byKey(k); }
    e.preventDefault();
  });

  // The first-time card: once per browser (the browser's storage, when it allows it).
  var INTRO_KEY = "judgekeeper-intro-seen";
  function seenIntro() {
    try { return window.localStorage.getItem(INTRO_KEY) === "1"; } catch (e) { return false; }
  }
  $("intro-ok").addEventListener("click", function () {
    $("intro").hidden = true;
    try { window.localStorage.setItem(INTRO_KEY, "1"); } catch (e) { /* shown again next time */ }
  });
  if (!seenIntro()) { $("intro").hidden = false; $("intro-ok").focus(); }
__RULE_FOLD__
  var left = items.some(function (it) { return !it.label && !it.skipped; });
  if (left) { open(pos); } else { finish(); }
})();
</script>
</body>
</html>
"""


def label_page(description: str | None, rule: str | None,
               command: str | None = None) -> str:
    """The labeling page. The line in the right column is the session's `status`, which the
    server sends with the data and after every mark: the page works out nothing itself. The
    server fills in __DATA__, __TOKEN__ and __NONCE__. `command` (start.Talk.command) is what
    the person runs to continue."""
    command = command or textio.program()
    block = _rule_block(rule, BY_THIS_RULE)
    body = (LABEL_BODY.replace("__COMMAND__", _text(command))
            .replace("__STAGE_CLASS__", "" if block.strip() else " no-rule")
            .replace("__BRAND__", BRAND).replace("__LOGO__", LOGO)
            .replace("__CROSS__", CROSS).replace("__TICK__", TICK)
            .replace("__RULE_BLOCK__", block)
            .replace("__RULE_FOLD__", RULE_FOLD)
            .replace("__ABOUT__", _text(description or "")))
    return _head("judgekeeper: mark answers", LABEL_STYLE) + body


RESULT_STYLE = """
.lead { gap: 18px; padding-top: 4px; }
.kind { margin-top: 4px; }
.stmt { display: grid; grid-template-columns: 44px 1fr; gap: 16px; align-items: start; }
.stmt + .stmt { margin-top: 18px; }
.stmt h2 { font-size: 27px; line-height: 1.18; letter-spacing: -.022em; }
.stmt .dot { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center;
  border: 1.5px solid var(--line-2); color: var(--muted); }
.stmt .dot svg { width: 18px; height: 18px; }
.stmt .dot.pass { color: var(--pass); border-color: var(--pass-line); background: var(--pass-bg); }
.stmt .dot.fail { color: var(--fail); border-color: var(--fail-line); background: var(--fail-bg); }
.sentence { font: 600 20px/1.35 var(--display); letter-spacing: -.015em; }
.ring { width: 44px; height: 44px; }
.ring circle { fill: none; stroke-width: 4; }
.ring .bg { stroke: var(--line-2); }
.ring .fg { stroke-linecap: round; transform: rotate(-90deg); transform-origin: 50% 50%;
  stroke-dasharray: 119.38; stroke-dashoffset: 119.38;
  animation: ring 900ms var(--ease-out) 200ms forwards; }
.ring .fg.pass { stroke: var(--pass); } .ring .fg.fail { stroke: var(--fail); }
@keyframes ring { to { stroke-dashoffset: var(--off); } }
@property --n { syntax: "<integer>"; inherits: false; initial-value: 0; }
.pct { font-style: normal; font-variant-numeric: tabular-nums; display: inline-block;
  min-width: 2.3ch; text-align: right; --n: 0; counter-reset: pct var(--n);
  animation: count 900ms var(--ease-out) 200ms forwards; }
.pct > span[aria-hidden]::before { content: counter(pct) "%"; }
@keyframes count { to { --n: var(--to); } }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; }
.verdict { display: flex; align-items: flex-start; gap: 10px; padding: 11px 14px;
  border-radius: 10px; font-weight: 600; font-size: 15px; border: 1px solid; }
.verdict svg { width: 20px; height: 20px; flex: none; margin-top: 1px; }
.verdict strong { font-weight: 600; }
.verdict span { display: block; font-weight: 400; color: var(--text-2); font-size: 14px;
  margin-top: 2px; }
.verdict.green { color: var(--pass); background: var(--pass-bg); border-color: var(--pass-line); }
.verdict.amber { color: var(--amber); background: var(--amber-bg); border-color: var(--amber-line); }
.verdict.red { color: var(--fail); background: var(--fail-bg); border-color: var(--fail-line); }
.verdict.grey { color: var(--text-2); background: var(--card); border-color: var(--line-2); }
.next-list { list-style: none; padding: 0; }
.next-list li { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px;
  padding: 10px 0; border-top: 1px solid var(--line); font-size: 14px; color: var(--text-2); }
.next-list li:first-child { border-top: 0; padding-top: 0; }
.next-list b { flex-basis: 100%; color: var(--text); font-weight: 600; }
.next-list .btn, .next-list code { margin-left: auto; }
.card.warn { border-color: var(--amber-line);
  background: linear-gradient(180deg, rgba(251,191,36,.05), rgba(251,191,36,.015)); }
.lines p { font-size: 14px; color: var(--text-2); margin: 0 0 7px; }
.bang { list-style: none; padding: 0; display: grid; gap: 7px; font-size: 14px;
  color: var(--text-2); }
.bang li { display: grid; grid-template-columns: 14px 1fr; gap: 6px; }
.bang li::before { content: "!"; font-weight: 800; color: var(--amber); }
.tile { font-size: 13.5px; color: var(--text-2); }
.tile + .tile { margin-top: 14px; }
.tile .lbl { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.tile .abbr { font-size: 11px; font-weight: 600; letter-spacing: .04em; color: var(--muted);
  border: 1px solid var(--line-2); border-radius: 5px; padding: 0 5px; }
.tile .val { margin-left: auto; color: var(--text); font-variant-numeric: tabular-nums;
  font-size: 15px; }
.rangebar { position: relative; height: 6px; border-radius: 6px; background: var(--line);
  margin: 0 0 6px; }
.rangebar span { position: absolute; top: 0; bottom: 0; border-radius: 6px;
  background: rgba(52,211,153,.33); transform-origin: left; transform: scaleX(0);
  animation: grow 700ms var(--ease-out) 500ms forwards; }
.rangebar i { position: absolute; top: -4px; width: 2px; height: 14px; margin-left: -1px;
  background: var(--pass); border-radius: 2px; opacity: 0;
  animation: show 200ms ease 1000ms forwards; }
@keyframes grow { to { transform: scaleX(1); } }
@keyframes show { to { opacity: 1; } }
.tile .rng { font-size: 12.5px; color: var(--muted); }
.facts { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); font-size: 13px;
  color: var(--muted); }
.facts p + p { margin-top: 6px; }
.facts b { color: var(--text-2); }
.judge { font-size: 14px; color: var(--text-2); overflow-wrap: anywhere; }
.judge b { color: var(--text); }
.card .rule { margin-top: 8px; padding: 10px 12px; border-left: 2px solid var(--green);
  background: var(--bg); border-radius: 0 8px 8px 0; }
.meta { color: var(--muted); font-size: 13px; margin-top: 8px; overflow-wrap: anywhere; }
.files { margin: 4px 0 0; padding-left: 18px; font-size: 13px; color: var(--muted); }
.quiet { margin-top: 10px; color: var(--muted); font-size: 13px; }
.quiet summary { cursor: pointer; }
.quiet p { margin: 6px 0 0; }
.hist { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--text-2); }
.hist th { text-align: left; font-weight: 600; color: var(--muted); padding: 0 8px 6px 0; }
.hist td { border-top: 1px solid var(--line); padding: 8px 8px 8px 0; vertical-align: top;
  overflow-wrap: anywhere; }
.hist td span { display: block; }
.fade { opacity: 0; transform: translateY(6px); animation: in 420ms var(--ease-out) forwards; }
@keyframes in { to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .fade, .ring .fg, .rangebar span, .rangebar i, .pct { animation: none !important; }
  .fade { opacity: 1; transform: none; }
  .ring .fg { stroke-dashoffset: var(--off); }
  .rangebar span { transform: none; } .rangebar i { opacity: 1; }
  .pct { --n: var(--to); } }
"""

RING_C = 119.38  # the ring's length: 2 x pi x 19


def _pct(x: float) -> str:
    return f"{min(max(x, 0.0), 1.0) * 100:.1f}%"


def _statement(s: dict) -> str:
    """One of the result's sentences: with its ring and counted-up number when the rate is
    known, else with an empty dot (or, before a result, as one plain line)."""
    text, rate, side = s["text"], s["rate"], s["side"]
    if side is None:
        return f'<p class="sentence">{escape(text)}</p>'
    icon = TICK if side == "pass" else CROSS
    if rate is None:
        return f'<div class="stmt"><span class="dot {side}">{icon}</span><h2>{escape(text)}</h2></div>'
    before, pct, after = text.partition(s["pct"])
    off = f"{RING_C * (1 - min(max(rate, 0.0), 1.0)):.2f}"
    ring = (f'<svg class="ring" viewBox="0 0 44 44" aria-hidden="true">'
            f'<circle class="bg" cx="22" cy="22" r="19"/>'
            f'<circle class="fg {side}" cx="22" cy="22" r="19" style="--off: {off}"/></svg>')
    number = (f'<em class="pct" style="--to: {int(pct.rstrip("%"))}"><span aria-hidden="true">'
              f'</span><span class="sr">{escape(pct)}</span></em>')
    return f'<div class="stmt">{ring}<h2>{escape(before)}{number}{escape(after)}</h2></div>'


def _tile(t: dict) -> str:
    bar = ""
    if t["mark"] is not None:
        span = ("" if t["interval"] is None else
                f'<span style="left: {_pct(t["interval"][0])}; '
                f'right: {_pct(1 - t["interval"][1])}"></span>')
        bar = (f'<div class="rangebar" aria-hidden="true">{span}'
               f'<i style="left: {_pct(t["mark"])}"></i></div>')
    return (f'<div class="tile"><div class="lbl">{escape(t["plain"])} '
            f'<span class="abbr">{escape(t["name"])}</span>'
            f'<b class="val">{escape(t["value"])}</b></div>{bar}'
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
        do = f'<a class="btn" href="{escape(href)}">{escape(s["button"])}</a>'
    else:
        do = f' <code>{escape(s["command"])}</code>'
    return f'<li><b>{escape(s["title"])}</b>{escape(s["text"])}{do}</li>'


def _card(block: dict | None) -> str:
    """A card of lines and saved files: the judge check, with its amber edge."""
    if not block:
        return ""
    warn = block["title"] == JUDGE_CHECK_TITLE
    files = "".join(f"<li><code>{escape(f)}</code></li>" for f in block["files"])
    if warn:
        lines = ('<ul class="bang">' + "".join(f"<li>{escape(x)}</li>" for x in block["lines"])
                 + "</ul>")
    else:
        lines = '<div class="lines">' + "".join(f"<p>{escape(x)}</p>" for x in block["lines"]) + "</div>"
    return (f'<div class="card{" warn" if warn else ""}"><h3>{escape(block["title"])}</h3>{lines}'
            + (f'<p class="meta">Saved:</p><ul class="files">{files}</ul>' if files else "")
            + "</div>")


def _quiet(line: str | None) -> str:
    """Nothing found by the judge check: one quiet line, folded."""
    if not line:
        return ""
    return (f'<details class="quiet"><summary>{escape(JUDGE_CHECK_TITLE)}</summary>'
            f'<p>{escape(line)}</p></details>')


def _fades(blocks: list[str], start: int = 0) -> str:
    """The blocks, each fading up 45 ms after the one before (once, on load)."""
    return "".join(f'<div class="fade" style="animation-delay: {(start + k) * 45}ms">{b}</div>'
                   for k, b in enumerate(x for x in blocks if x))


def _history(rows: list[dict]) -> str:
    """The checks of the judge on the marks, newest first: a static table."""
    if not rows:
        return ""
    body = "".join(
        f'<tr><td>{escape(r["date"])}</td><td>{escape(r["changed"])}</td>'
        f'<td>{escape(r["tested"])}</td><td>'
        + "".join(f"<span>{escape(g)}</span>" for g in r["groups"])
        + f'</td><td>{escape(r["verdict"])}</td><td>{escape(r["exact"])}</td></tr>'
        for r in rows)
    return ('<div class="card"><h3>History</h3><table class="hist"><thead><tr><th>Date</th>'
            '<th>What changed</th><th>Marks tested</th><th>Old → new judge</th>'
            f'<th>Result</th><th>Copy</th></tr></thead><tbody>{body}</tbody></table></div>')


def _fixing(section: dict | None) -> str:
    """The Fix card: where the judge goes wrong and its mistakes on the marks the person can
    see, with its own reason, and every rule tested on the hidden marks."""
    if not section:
        return ""
    parts = ['<div class="card"><h3>Fix</h3>']
    if section.get("patterns"):
        parts.append("<p><b>Where your judge goes wrong</b></p><ul>"
                     + "".join(f"<li>{escape(x)}</li>" for x in section["patterns"]) + "</ul>")
    if section.get("mistakes"):
        parts.append("<p><b>Its mistakes on the marks you can see</b></p>")
        for n, m in enumerate(section["mistakes"], 1):
            parts.append(
                f'<details><summary>[{n}] {escape(m["said"])}</summary>'
                f'<p class="small">Question: {escape(m["question"])}</p>'
                f'<p class="small">Answer: {escape(m["answer"])}</p>'
                + (f'<p class="small">Your judge\'s reason: {escape(m["reason"])}</p>'
                   if m.get("reason") else "") + "</details>")
    if section.get("rules"):
        body = "".join(
            f'<tr><td>{escape(r["date"])}</td><td><code>{escape(r["rule"])}</code></td>'
            f'<td>{escape(str(r["n"]))}</td><td>{escape(str(r["fixed"]))}</td>'
            f'<td>{escape(str(r["broke"]))}</td><td>{escape(r["result"])}</td></tr>'
            for r in section["rules"])
        parts.append('<p><b>Rules tested</b></p><table class="hist"><thead><tr><th>Date</th>'
                     '<th>Rule</th><th>Hidden marks</th><th>Fixed</th><th>Broke</th>'
                     f'<th>Result</th></tr></thead><tbody>{body}</tbody></table>')
    return "".join(parts) + "</div>"


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
    model = content.get("drop_model")
    model = f"<p>{escape(model)}</p>" if model else ""
    model += "".join(f"<p>{escape(x)}</p>" for x in content.get("picks") or [])
    facts = (f'<div class="facts">{rate}{corrected}{model}</div>' if rate or corrected or model
             else "")
    made = "".join(f'<p class="small">{escape(x)}</p>'
                   for x in [*content.get("made", []), content.get("drop")] if x)
    statements = content.get("statements") or [
        {"text": s, "rate": None, "side": None, "pct": None} for s in content["sentences"]]
    left = [
        f'<h1 class="h1">Your result</h1><p class="small kind">{escape(content["kind"])}</p>',
        "".join(_statement(s) for s in statements),
        _verdict(content["verdict"]),
        made,
        f'<div class="h2">What next</div><ul class="next-list">{steps}</ul>',
        (f'<p class="small">Saved in <code>{escape(content["folder"])}</code> in your project. '
         'This page is <code>report.html</code> there.</p>'),
        _history(content.get("history") or []),
    ]
    right = [
        _card(content.get("judge_check")),
        _fixing(content.get("fixing")),
        (f'<div class="card"><h3>Details</h3>{"".join(_tile(t) for t in content["tiles"])}'
         f'{facts}</div>'),
        (f'<div class="card"><h3>Your judge</h3><p class="judge">{name}{escape(judge["model"])}'
         f'</p>{rule}{source}{_quiet(content.get("judge_check_quiet"))}</div>'),
    ]
    return _head("judgekeeper: your result", RESULT_STYLE) + f"""<div class="app">
<header class="hdr">
  {BRAND}
  <div class="mid">How often your judge agrees with you</div>
  <div class="end"></div>
</header>
<main class="body split">
<div class="col lead">
{_fades(left)}
</div>
<div class="col">
{_fades(right, start=len([b for b in left if b]))}
</div>
</main>
</div>
</body>
</html>
"""


