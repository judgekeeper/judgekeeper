"""The pages `judgekeeper start` shows: the labeling page, the review page, the fix page and
the result page.

Each is one self-contained page: no fonts, scripts or images from anywhere else. The heading
font (Bricolage Grotesque, under the SIL Open Font License) is embedded as base64 from this
package's `fonts/` folder. Text reaches the pages through textContent. The labeling page and
the first step of the review hold nothing the judge said; the fix page holds only the answers
judgekeeper used, never those set aside.

The result page runs no script and loads nothing, so the copy saved as
`.judgekeeper/result.html` opens with no server. Every string in it is escaped.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from importlib import resources

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
QUESTION = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.2 9a3 3 0 015.6 1.2c0 2-2.8 '
            '2.4-2.8 4.3M12 18.2v.1" fill="none" stroke="currentColor" stroke-width="2.3" '
            'stroke-linecap="round"/></svg>')

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
.mini { display: flex; gap: 14px; font-size: 13px; }
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
<main class="stage">
<aside class="side">
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
    <code>judgekeeper start</code> to continue.</p>
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
    setText("at", Math.min(pos + 1, items.length)); setText("all", items.length);
    var done = counts.correct + counts.wrong;
    $("bar").style.width = (items.length ? done / items.length * 100 : 0) + "%";
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
    if (to < n) { dots.appendChild(el("span", "more", "+" + (n - to))); }
  }
  $("dots").addEventListener("click", function (e) {
    var k = e.target.getAttribute && e.target.getAttribute("data-k");
    if (k == null) { return; }
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
    var i = nextIndex(pos + 1);
    if (i === null && walkingSkipped) { walkingSkipped = false; i = nextIndex(pos + 1); }
    if (i !== null) { open(i); return; }
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
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(change)
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
  function mark(value) {
    if (ended) { return false; }
    var it = items[pos];
    return send({label: value}, function () {
      it.label = value; it.skipped = false; history.push(pos); next(); });
  }

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
    c.animate([{transform: "translateX(" + x + "px) rotate(" + tilt(x, c.offsetWidth || 1) +
                           "deg)", opacity: 1},
               {transform: "translateX(" + endX + "px) rotate(" + (dir * 18) + "deg)", opacity: 0}],
              {duration: flyDuration(x, endX, v), easing: "cubic-bezier(.2,.7,.4,1)",
               fill: "forwards"}).finished.then(function () { if (!mark(value)) { render(); } });
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
  $("pass").addEventListener("click", function () { hit("pass"); mark("pass"); });
  $("fail").addEventListener("click", function () { hit("fail"); mark("fail"); });
  $("skip").addEventListener("click", skip);
  $("undo").addEventListener("click", undo);
  // The keys: → Pass and ← Fail (shown), 1 Pass and 2 Fail (an old habit, still working).
  var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden) { return; }
    var k = e.key.toLowerCase();
    if (KEYS[k]) { hit(KEYS[k]); mark(KEYS[k]); }
    else if (k === "s") { skip(); } else if (k === "u") { undo(); }
    else { return; }
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


def label_page(description: str | None, rule: str | None) -> str:
    """The labeling page. The line in the right column is the session's `status`, which the
    server sends with the data and after every mark: the page works out nothing itself. The
    server fills in __DATA__, __TOKEN__ and __NONCE__."""
    body = (LABEL_BODY.replace("__BRAND__", BRAND).replace("__LOGO__", LOGO)
            .replace("__CROSS__", CROSS).replace("__TICK__", TICK)
            .replace("__RULE_BLOCK__", _rule_block(rule, BY_THIS_RULE))
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
        cls = "btn primary" if s["link"] in ("/review", "/fix") else "btn"
        do = f'<a class="{cls}" href="{escape(href)}">{escape(s["button"])}</a>'
    else:
        do = f' <code>{escape(s["command"])}</code>'
    return f'<li><b>{escape(s["title"])}</b>{escape(s["text"])}{do}</li>'


def _card(block: dict | None) -> str:
    """A card of lines and saved files: the judge check (with its amber edge), the review,
    the fix, or asking the judge again."""
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
    statements = content.get("statements") or [
        {"text": s, "rate": None, "side": None, "pct": None} for s in content["sentences"]]
    left = [
        f'<h1 class="h1">Your result</h1><p class="small kind">{escape(content["kind"])}</p>',
        "".join(_statement(s) for s in statements),
        _verdict(content["verdict"]),
        f'<div class="h2">What next</div><ul class="next-list">{steps}</ul>',
        (f'<p class="small">Saved in <code>{escape(content["folder"])}</code> in your project. '
         'This page is <code>result.html</code> there.</p>'),
    ]
    right = [
        _card(content.get("judge_check")),
        _card(content.get("fix")),
        _card(content.get("review")),
        _card(content.get("again")),
        _card(content.get("new_judge")),
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
{_fades(right, start=len(left))}
</div>
</main>
</div>
</body>
</html>
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
    any time; run <code>judgekeeper start --review</code> to continue.</p>
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
  // Step A's keys: ← Fail, N Not sure, → Pass (1 Pass, 2 Fail and 3 Not sure still work);
  // step B's: 1, 2, 3 in the order shown.
  var KEYS_A = {arrowleft: "fail", n: "unsure", arrowright: "pass", "1": "pass", "2": "fail",
                "3": "unsure"};
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target === $("whybox")) { return; }
    var k = e.key.toLowerCase();
    if (step === "a" && KEYS_A[k]) { choose(KEYS_A[k]); }
    else if (step === "b" && (k === "1" || k === "2" || k === "3")) {
      choose(buttons[+k - 1].getAttribute("data-value")); }
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


def review_page(description: str | None, rule: str | None) -> str:
    """The review page, both steps: the page data says which one to show. The server fills
    in __DATA__, __TOKEN__ and __NONCE__."""
    body = (REVIEW_BODY.replace("__BRAND__", BRAND).replace("__CROSS__", CROSS)
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
      <p>Change your judge's rule with any AI assistant, or yourself. judgekeeper never edits
        your files: it says where the new rule goes.</p>
      <div class="row">
        <button class="btn primary" id="rc-ask" type="button">Copy a prompt for your AI assistant</button>
        <button class="btn" id="rc-self" type="button">I'll write it myself</button>
      </div>
      <div id="rc-prompt" hidden>
        <p class="small">Paste this into any AI assistant. It holds only the answers judgekeeper
          used, never the ones kept aside.</p>
        <pre class="box" id="rc-prompt-text"></pre>
        <button class="btn" id="rc-copy" type="button">Copy</button>
      </div>
      <div id="rc-paste" hidden>
        <label class="cap" for="rc-new">Paste the new rule here</label>
        <textarea id="rc-new" spellcheck="false"
          placeholder="Paste the whole reply. judgekeeper takes the rule from between NEW RULE START and NEW RULE END."></textarea>
        <button class="btn green" id="rc-save" type="button">Save the new rule</button>
      </div>
      <div class="checks" id="rc-checks" aria-live="polite"></div>
      <div id="rc-saved" hidden>
        <h4>Your new rule, against the old one</h4>
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

  function postJSON(path, body) {
    return fetch(url(path), {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
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

  var how = "pasted";
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

  $("rc-ask").addEventListener("click", function () {
    var button = $("rc-ask");
    button.disabled = true;
    postJSON("/fix/prompt", {}).then(function (res) {
      button.disabled = false;
      if (!res.ok) { $("rc-status").textContent = res.body.error; return; }
      $("rc-status").textContent = "";
      $("rc-prompt-text").textContent = res.body.prompt;
      $("rc-prompt").hidden = false;
      how = "pasted";
      $("rc-paste").hidden = false;
      $("rc-new").value = "";
      copy(res.body.prompt, $("rc-copy"));
    }).catch(function () { button.disabled = false; $("rc-status").textContent = LOST; });
  });
  $("rc-copy").addEventListener("click", function () {
    copy($("rc-prompt-text").textContent, $("rc-copy"));
  });
  $("rc-self").addEventListener("click", function () {
    how = "written";
    $("rc-prompt").hidden = true;
    $("rc-paste").hidden = false;
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
