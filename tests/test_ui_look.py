"""The look of `judgekeeper start`'s pages: navy only, the heading font embedded, nothing
loaded from outside; the labeling page's card (one fixed height, drag rules, dots, the skipped
prompt, the first-time card); the result's reveal in CSS alone.

The drag rules are pure functions in the page's script, between `// pure: start` and
`// pure: end`; the tests run them in node when it is installed (CI's runners have it).
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from judgekeeper import start_label, start_page, weighted

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FONTS = ROOT / "src" / "judgekeeper" / "fonts"
SITE_FONTS = ROOT / "website" / "assets" / "fonts"


def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


CHECK = (100, 100, 20, 17, 20, 2)


def _pages() -> dict[str, str]:
    return {"label": start_page.label_page("support bot", "Be kind.\n" * 30),
            "review": start_page.review_page("support bot", "Be kind."),
            "fix": start_page.fix_page("support bot"),
            "result": start_label.result_html(_result(*CHECK), back="/?token=t"),
            "saved result": start_label.result_html(_result(*CHECK))}


# Fonts and loads ---------------------------------------------------------------------------

def test_the_heading_font_is_embedded_in_every_page_from_the_package_files():
    for name, page in _pages().items():
        for file, weight in start_page.FONTS:
            data = base64.b64encode((PACKAGE_FONTS / file).read_bytes()).decode()
            rule = (f'@font-face {{ font-family: "Bricolage Grotesque"; font-weight: {weight}; '
                    f'font-style: normal; font-display: swap; '
                    f'src: url("data:font/woff2;base64,{data}") format("woff2"); }}')
            assert rule in page, (name, weight)
        assert page.count("@font-face") == 2, name
        assert '--display: "Bricolage Grotesque", system-ui, sans-serif;' in page
        assert '--body: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;' in page
        assert 'ui-monospace, "SF Mono", Menlo, Consolas, monospace' in page


def test_the_package_fonts_are_the_sites_fonts_with_their_licence():
    for file, _ in start_page.FONTS:
        assert (PACKAGE_FONTS / file).read_bytes() == (SITE_FONTS / file).read_bytes()
    licence = (PACKAGE_FONTS / start_page.FONT_LICENCE).read_text(encoding="utf-8")
    assert licence == (SITE_FONTS / start_page.FONT_LICENCE).read_text(encoding="utf-8")
    assert "SIL Open Font License" in licence and "Bricolage" in licence
    assert sorted(p.name for p in PACKAGE_FONTS.iterdir() if p.is_file()) == sorted(
        [start_page.FONT_LICENCE, *(f for f, _ in start_page.FONTS)])


def test_no_page_loads_anything_from_outside():
    for name, page in _pages().items():
        assert "<link" not in page and "@import" not in page, name
        assert not re.search(r"https?://", page), name
        style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)[1]
        for match in re.finditer(r"url\(([^)]*)\)", style):
            assert match[1].startswith('"data:font/woff2;base64,'), (name, match[1][:40])
        assert ' src="' not in page.replace('src: url("data:', ""), name


def test_the_pages_are_navy_only_and_animate_transform_and_opacity_alone():
    for name, page in _pages().items():
        style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)[1]
        assert "--bg: #0E1525" in style and "--green: #10B981" in style, name
        assert "prefers-color-scheme" not in style, name
        assert "transition: all" not in style, name
        for transition in re.findall(r"transition: ([^;]*);", style):
            for part in transition.split(","):
                assert part.split()[0] in ("transform", "opacity", "background-color",
                                           "none"), (name, part)
        assert "cubic-bezier(.23,1,.32,1)" in style and ":focus-visible" in style, name
        assert "@media (prefers-reduced-motion: reduce)" in style, name
        assert "backdrop-filter: blur(20px)" in style, name
        assert "max-width: 1280px" in style, name


def test_pass_and_fail_look_equally_strong():
    page = start_page.label_page(None, None)
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)[1]
    fail = re.search(r"\.big\.fail \{([^}]*)\}", style)[1]
    good = re.search(r"\.big\.pass \{([^}]*)\}", style)[1]
    assert fail.replace("fail", "x") == good.replace("pass", "x")  # the same rule, own colour
    assert ".big { height: 56px;" in style  # one size for both
    assert 'class="big fail" id="fail"' in page and 'class="big pass" id="pass"' in page
    assert page.index('id="fail"') < page.index('id="pass"')


# The labeling page -------------------------------------------------------------------------

def _script(page: str) -> str:
    return re.search(r'<script nonce="__NONCE__">(.*?)</script>', page, re.DOTALL)[1]


def _pure(page: str) -> str:
    return _script(page).split("// pure: start")[1].split("// pure: end")[0]


def _node(code: str) -> dict:
    """Run `code` (which prints one JSON line) in node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's drag rules")
    out = subprocess.run([node, "-e", code], check=True, capture_output=True, text=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_drag_rules_are_pure_functions():
    pure = _pure(start_page.label_page(None, None))
    assert "document" not in pure and "window" not in pure and "$(" not in pure
    for name in ("tilt", "stampOpacity", "dragStarts", "isVertical", "commit",
                 "releaseVelocity", "flyDuration", "springStep", "springDone"):
        assert f"function {name}(" in pure, name


def test_a_drag_commits_past_a_quarter_of_the_width_or_on_a_flick():
    pure = _pure(start_page.label_page(None, None))
    got = _node(pure + """
    var W = 600;
    console.log(JSON.stringify({
      far_right: commit(0.29 * W, 0, W), far_left: commit(-0.29 * W, 0, W),
      short: commit(0.27 * W, 0, W), short_left: commit(-0.1 * W, 0, W),
      flick_right: commit(0.1 * W, 0.56, W), flick_left: commit(-0.1 * W, -0.56, W),
      flick_back: commit(0.1 * W, -0.9, W), slow: commit(0.1 * W, 0.5, W),
      nothing: commit(0, 0, W)}));""")
    assert got == {"far_right": "pass", "far_left": "fail", "short": None, "short_left": None,
                   "flick_right": "pass", "flick_left": "fail", "flick_back": None,
                   "slow": None, "nothing": None}


def test_the_card_tilts_with_the_offset_up_to_twelve_degrees():
    pure = _pure(start_page.label_page(None, None))
    got = _node(pure + """
    var W = 600;
    console.log(JSON.stringify({half: tilt(W / 2, W), full: tilt(W, W), back: tilt(-W, W),
      third: tilt(W / 3, W), stamp_full: stampOpacity(0.28 * W, W),
      stamp_half: stampOpacity(0.14 * W, W), stamp_over: stampOpacity(W, W)}));""")
    assert got["half"] == 9 and got["full"] == 12 and got["back"] == -12
    assert got["third"] == pytest.approx(6)
    assert got["stamp_full"] == 1 and got["stamp_half"] == pytest.approx(0.5)
    assert got["stamp_over"] == 1


def test_a_drag_starts_after_eight_pixels_and_a_vertical_move_scrolls_instead():
    pure = _pure(start_page.label_page(None, None))
    got = _node(pure + """
    console.log(JSON.stringify({still: dragStarts(7, 7), moved: dragStarts(8, 0),
      down: dragStarts(0, -8), vertical: isVertical(3, 9), sideways: isVertical(9, 3)}));""")
    assert got == {"still": False, "moved": True, "down": True, "vertical": True,
                   "sideways": False}


def test_the_card_flies_off_at_the_hands_speed_within_140_to_260_ms():
    pure = _pure(start_page.label_page(None, None))
    got = _node(pure + """
    console.log(JSON.stringify({fast: flyDuration(100, 1000, 10), slow: flyDuration(100, 1000, 0.1),
      mid: flyDuration(0, 900, 4.5), velocity: releaseVelocity([{x: 0, t: 0}, {x: 50, t: 100}]),
      one: releaseVelocity([{x: 0, t: 5}])}));""")
    assert got["fast"] == 140 and got["slow"] == 260 and got["mid"] == 200
    assert got["velocity"] == 0.5 and got["one"] == 0


def test_a_released_card_springs_back_without_overshooting():
    pure = _pure(start_page.label_page(None, None))
    got = _node(pure + """
    var pos = 120, vel = 800, steps = 0, lowest = pos, s;  // let go 120px out, still moving out
    while (!springDone(pos, vel) && steps < 600) {
      s = springStep(pos, vel, 1 / 60); pos = s[0]; vel = s[1]; steps++;
      lowest = Math.min(lowest, pos);
    }
    console.log(JSON.stringify({steps: steps, pos: pos, lowest: lowest}));""")
    assert got["steps"] < 60  # back within a second
    assert abs(got["pos"]) < 0.3 and got["lowest"] > -1  # critically damped: no swing past 0


def test_keys_and_buttons_mark_at_once_and_only_a_drag_animates():
    script = _script(start_page.label_page(None, None))
    keys = script[script.index('document.addEventListener("keydown"'):]
    keys = keys[:keys.index("});") + 3]
    assert "mark(KEYS[k])" in keys and "hit(KEYS[k])" in keys
    assert "animate" not in keys and "flyOut" not in keys
    assert 'var KEYS = {arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"};' in script
    assert '$("pass").addEventListener("click", function () { hit("pass"); mark("pass"); });' in script
    # The card's own animation runs only when a drag commits.
    assert script.count("flyOut(") == 2  # defined, and called once: from the drag's end
    assert "if (value) { flyOut(c, dx, v, value); } else { springBack(c, dx, v, set); }" in script
    assert "if (reduce || !c.animate) { if (!mark(value)) { render(); } return; }" in script
    assert "if (reduce) { set(0); c.style.transform = \"\"; return; }" in script
    assert "c._spring = c.animate(frames.map(" in script  # the spring back: one animation too


def test_clicking_a_dot_opens_that_answer():
    script = _script(start_page.label_page(None, None))
    assert 'b.setAttribute("data-k", String(k));' in script
    assert ('$("dots").addEventListener("click", function (e) {\n'
            '    var k = e.target.getAttribute && e.target.getAttribute("data-k");\n'
            '    if (k == null) { return; }\n'
            '    walkingSkipped = false; open(+k);') in script
    assert "function open(index) { ended = false; pos = index; render(); }" in script
    # Over 60 answers, a window of dots with "+N" for the rest.
    assert "MAX_DOTS = 60" in script and '"+" + from' in script and '"+" + (n - to)' in script
    page = start_page.label_page(None, None)
    assert "Click a dot at the top to go back to any answer, skipped ones too." in page


def test_the_skipped_prompt_comes_only_when_skipped_answers_are_left():
    script = _script(start_page.label_page(None, None))
    finish = script[script.index("function finish()"):script.index("function flashSaved()")]
    assert 'var skipped = items.filter(function (it) { return it.skipped; }).length;' in finish
    assert finish.index("if (!skipped) {") < finish.index('window.location.href = url("/result")')
    assert finish.index('url("/result")') < finish.index('"You skipped "')
    assert '". Look at " + them + " again?"' in finish
    assert '"Look at " + them' in finish and '"See your result"' in finish
    assert 'walkingSkipped = true; open(nextIndex(0));' in finish
    # Walking the skipped ones: nextIndex looks for skipped answers, and a mark clears the skip.
    assert "walkingSkipped ? it.skipped : (!it.label && !it.skipped)" in script
    assert "it.label = value; it.skipped = false; history.push(pos); next();" in script


def test_the_first_time_card_is_shown_once_per_browser_and_its_storage_is_guarded():
    page = start_page.label_page(None, None)
    for line in ("Mark each answer Pass or Fail, using your judge's rule.",
                 ("You won't see what your judge decided. That way your marks are your own, "
                  "and the check is fair."),
                 ("Your judge is the AI that grades your app's answers in your evals. "
                  "judgekeeper then shows how often it agrees with you."),
                 "Use <kbd>←</kbd> <kbd>→</kbd>, the buttons, or drag the card.",
                 'id="intro-ok" type="button">OK</button>'):
        assert line in " ".join(page.split()), line
    assert '<div class="scrim" id="intro" hidden>' in page  # shown by the script, not by default
    script = _script(page)
    for match in re.finditer(r"localStorage", script):
        line = script[script.rfind("\n", 0, match.start()):match.start()]
        assert "try {" in line, line
    assert 'if (!seenIntro()) { $("intro").hidden = false; $("intro-ok").focus(); }' in script
    assert '!$("intro").hidden) { return; }' in script  # keys wait until the card is closed


def test_the_card_is_a_chat_with_the_question_left_and_the_answer_right():
    script = _script(start_page.label_page("support bot", None))
    assert 'el("div", "who", "The question")' in script
    assert 'el("div", "who", "Your app\'s answer")' in script
    assert 'if (ABOUT) { who.appendChild(el("span", "tag", ABOUT)); }' in script
    assert "innerHTML" not in script
    page = start_page.label_page(None, None)
    assert ".chat.reply { justify-content: flex-end; }" in page
    assert ".swipe.behind {" in page  # a faint second card behind the first
    assert "user-select: none" in page and "touch-action: pan-y" in page
    assert "transform-origin: 50% 120%" in page  # the card pivots below itself


# The result page ---------------------------------------------------------------------------

def test_the_result_reveal_is_css_alone_and_plays_once():
    r = _result(*CHECK)
    html = start_label.result_html(r)
    assert "<script" not in html
    for key, side in (("tpr", "pass"), ("tnr", "fail")):
        off = f"{start_page.RING_C * (1 - r[key]):.2f}"
        assert f'<circle class="fg {side}" cx="22" cy="22" r="19" style="--off: {off}"/>' in html
        pct = f"{r[key]:.0%}"
        assert (f'<em class="pct" style="--to: {pct[:-1]}"><span aria-hidden="true"></span>'
                f'<span class="sr">{pct}</span></em>') in html
    assert "animation: ring 900ms var(--ease-out) 200ms forwards" in html
    assert "animation: count 900ms var(--ease-out) 200ms forwards" in html
    assert '@property --n { syntax: "<integer>"; inherits: false; initial-value: 0; }' in html
    assert "animation: grow 700ms var(--ease-out) 500ms forwards" in html
    assert "animation: in 420ms var(--ease-out) forwards" in html
    delays = [int(d) for d in re.findall(r'class="fade" style="animation-delay: (\d+)ms"', html)]
    assert delays == [45 * k for k in range(len(delays))] and len(delays) >= 6
    reduced = html[html.index("@media (prefers-reduced-motion: reduce) {\n  .fade"):]
    assert ".fade, .ring .fg, .rangebar span, .rangebar i, .pct { animation: none !important; }" in reduced
    assert ".pct { --n: var(--to); }" in reduced and ".ring .fg { stroke-dashoffset: var(--off); }" in reduced


def test_the_result_has_two_columns_with_the_sentences_left_and_the_details_right():
    html = start_label.result_html(_result(*CHECK), back="/?token=t")
    left, right = html.split('<div class="col lead">')[1].split('<div class="col">')
    for needed in ("Your result", "When you said Pass, your judge also said Pass",
                   "When you said Fail, your judge also said Fail", 'class="verdict amber"',
                   "What next", '<a class="btn" href="/?token=t">Mark more answers</a>',
                   "Check again after your next eval run", "<code>judgekeeper start</code>"):
        assert needed in left, needed
    for needed in ("<h3>Details</h3>", "When you said Pass", "TPR", "TNR",
                   "How much you agree beyond luck", "<h3>Your judge</h3>"):
        assert needed in right, needed
    assert "<h3>Details</h3>" not in left and "What next" not in right
    assert ".split { grid-template-columns: minmax(0, 1fr) 400px; }" in html


def test_a_result_with_every_card_puts_the_judge_check_first_on_the_right():
    check = {"answers": 57, "error": 5, "unreadable": 2, "tool": "promptfoo",
             "tool_counted_as": "fail"}
    fix = {"counts": {"passed_but_fail": 6, "failed_but_pass": 2, "unclear": 0}, "used": 35,
           "aside": 15, "tests": []}
    r = _result(*CHECK, judge_check=check, fix=fix)
    html = start_label.result_html(r)
    right = html.split('<div class="col">')[1]
    assert right.index('<div class="card warn"><h3>Did your judge actually judge?</h3>') < \
        right.index("<h3>Fix your judge</h3>") < right.index("<h3>Details</h3>") < \
        right.index("<h3>Your judge</h3>")
    assert '<ul class="bang"><li>' in right


# The review and fix pages ------------------------------------------------------------------

def test_the_review_page_has_the_task_left_and_the_panel_right():
    page = start_page.review_page("support bot", "Be kind.")
    left, right = page.split('<main class="body split">')[1].split('<div class="col">\n  <section')
    assert '<h1 class="h1">See where you disagree</h1>' in left
    assert '<li id="step-a"><i>1</i>Look again</li>' in left
    assert '<div class="q" id="question"></div>' in left and '<div class="a" id="answer"></div>' in left
    assert '<span class="tag" id="about">support bot</span>' in left
    for needed in ('class="panel" id="ask"', 'id="look"', 'id="see" hidden', 'id="said"',
                   'id="judge"', 'id="reason"', 'Your judge\'s rule', "Show all",
                   'id="whybox"', "Why? (optional, helps fix your judge)"):
        assert needed in right, needed
    assert "Back to your result" in page and ".vs { display: grid; grid-template-columns: 1fr 1fr;" in page


def test_the_fix_page_has_the_lists_left_and_a_panel_that_stays_in_view_right():
    page = start_page.fix_page("support bot")
    left, right = page.split('<main class="body split fix">')[1].split('<div class="col stick">')
    for needed in ("What your judge gets wrong", 'id="aside"', 'id="counts"', "What stands out",
                   'id="lists"', 'id="unclear"', "Your own files are\n  never changed."):
        assert needed in left, needed
    for needed in ("Change the rule", "Your judge's rule today", "Move the pass mark"):
        assert needed in right, needed
    assert ".stick { position: sticky; top: calc(var(--hdr) + 20px);" in page
    assert "support bot" not in page  # the fix page is about the judge, not the app
