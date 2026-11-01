"""The pages judgekeeper serves, as built: the marking page with its welcome box (mark_page.py),
the result page and report.html (report_page.py) and the page for an old link, on the shared
look (look.py): the logo, the fonts, dark colours, contrast, focus rings, equal Fail and Pass,
and the words.

The marking page's behaviour is in test_mark_page_script.py.
"""

from __future__ import annotations

import base64
import re
from html import escape, unescape
from pathlib import Path

import pytest

from judgekeeper import look, mark_page, report_page, start_label, weighted
from judgekeeper.textio import program

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_FONTS = ROOT / "src" / "judgekeeper" / "fonts"

GATE = (100, 100, 30, 29, 30, 1)           # both 99% ranges start at 80% or more
CHECK = (100, 100, 20, 16, 20, 4)          # both ranges reach below 80%, and are wide
NOT_GATE_TNR = (100, 100, 40, 22, 40, 2)   # the TNR range stays below 80%
NOT_GATE_TPR = (100, 100, 40, 38, 40, 18)  # the TPR range stays below 80%
TOO_FEW = (100, 100, 10, 9, 10, 1)


def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


def _marking() -> str:
    return mark_page.label_page("support bot", "judgekeeper mark",
                                model="openai:gpt-4.1-mini", tool="promptfoo")


def _served() -> dict[str, str]:
    """Every page judgekeeper serves."""
    return {"marking": _marking(),
            "result": start_label.result_html(_result(*CHECK), back="/?token=t"),
            "report.html": start_label.result_html(_result(*NOT_GATE_TNR)),
            "old link": mark_page.old_link_page()}


_new = _served
TERM = '<span class="term">LLM-as-a-judge</span>'


def _flat(html: str) -> str:
    return " ".join(unescape(html).split())


def _text(html: str) -> str:
    """What a reader sees: the body without its style and scripts, tags removed."""
    body = html.split("<body>", 1)[-1]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.DOTALL)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", body)).split())
    return re.sub(r" ([.,:;)])", r"\1", text)


# The logo ------------------------------------------------------------------------------------

def test_every_page_carries_the_two_colour_logo():
    for name, page in _served().items():
        assert 'fill="#1E293B"' in page and 'fill="#10B981"' in page, name
        assert "#1F6B4A\"/>" not in page, name  # never a one-colour shield
    for name, page in _new().items():
        assert page.count(look.SHIELD) == page.count('class="logo-mark"') >= 1, name
        assert "drop-shadow" not in page, name  # nothing added
        logo_css = re.findall(r"\.logo-mark[^{]*\{([^}]*)\}", page)
        assert logo_css, name
        assert not any("background" in r or "filter" in r for r in logo_css), name  # no tile
        assert "#64748B" not in page, name  # the official colours


def test_the_logo_is_the_websites():
    site = (ROOT / "website" / "assets" / "logo.svg").read_text(encoding="utf-8")
    assert re.findall(r' d="([^"]+)"', site) == re.findall(r' d="([^"]+)"', look.SHIELD)
    assert re.findall(r'fill="(#[0-9A-F]{6})"', site) == ["#1E293B", "#10B981"]
    assert re.findall(r'fill="(#[0-9A-F]{6})"', look.SHIELD) == ["#1E293B", "#10B981"]
    assert re.findall(r'stroke="([^"]+)"', look.SHIELD) == ["#FFFFFF"]  # the check, no edge


# Fonts and loads -----------------------------------------------------------------------------

def test_the_fonts_are_embedded_from_the_package_with_their_licences():
    for name, page in _new().items():
        for file, family, weight in look.FONTS:
            data = base64.b64encode((PACKAGE_FONTS / file).read_bytes()).decode()
            assert (f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
                    f'font-style: normal; font-display: swap; '
                    f'src: url("data:font/woff2;base64,{data}") format("woff2"); }}') in page, \
                (name, file)
    for licence, family in zip(look.FONT_LICENCES, ("Manrope", "JetBrains Mono"), strict=True):
        text = (PACKAGE_FONTS / licence).read_text(encoding="utf-8")
        assert "SIL Open Font License" in text and family in text
    for name, page in _new().items():  # and the pages use them
        assert '--sans: "Manrope", system-ui,' in page and "var(--sans)" in page, name
        assert '--mono: "JetBrains Mono", ui-monospace,' in page, name
    site = ROOT / "website" / "assets" / "fonts"
    assert (PACKAGE_FONTS / "jetbrains-mono-latin-400-normal.woff2").read_bytes() == \
        (site / "jetbrains-mono-latin-400-normal.woff2").read_bytes()


def test_no_page_loads_anything_from_outside():
    for name, page in _new().items():
        assert "<link" not in page and "@import" not in page, name
        assert not re.search(r"https?://", page), name
        assert not re.search(r"<(img|iframe|object|embed)\b", page), name
        style = page.split("<style>")[1].split("</style>")[0]
        for match in re.finditer(r"url\(([^)]*)\)", style):
            assert match[1].startswith('"data:font/woff2;base64,'), (name, match[1][:40])
        assert ' src="' not in page, name


# Dark only, contrast ------------------------------------------------------------------------

def _tokens() -> dict[str, str]:
    start = look.TOKENS.index(":root {")
    block = look.TOKENS[start:look.TOKENS.index("}", start)]
    return dict(re.findall(r"--([\w-]+): (#[0-9A-Fa-f]{6})", block))


def test_dark_only():
    for name, page in _new().items():
        assert "<html lang=\"en\">" in page, name
        assert "prefers-color-scheme" not in page and "invert(" not in page, name
        assert "data-theme" not in page and "jk-theme" not in page, name
    assert ":root { color-scheme: dark;" in look.TOKENS
    assert look.TOKENS.count(":root") == 1  # no second set of colours


def test_the_colours():
    dark = _tokens()
    assert (dark["bg"], dark["text"], dark["muted"], dark["faint"], dark["line"]) == (
        "#0b0c0e", "#e6e8eb", "#8b919a", "#767c86", "#262a30")
    assert (dark["hover"], dark["current"]) == ("#121418", "#17191e")
    # Green and red: Pass and Fail (their fill, hover and dots) and the "See your result" link
    assert (dark["green-fill"], dark["green"], dark["red-fill"], dark["red"]) == (
        "#047857", "#10B981", "#c73b40", "#e5484d")
    assert dark["amber"] == "#e0a43a"
    coloured = {k for k, v in dark.items() if v.lower() not in {
        dark["bg"], dark["text"], dark["muted"], dark["faint"], dark["line"],
        dark["hover"], dark["current"]}}
    assert coloured == {"green", "green-fill", "red", "red-fill", "amber"}, coloured


def _luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (text, background, at least): the text colours on the grounds they sit on; white on the
# Pass and Fail fills; the verdict colours and the focus ring at the 3:1 of large text and rings
PAIRS = [(text, ground, 4.5) for text in ("text", "muted") for ground in ("bg", "hover", "current")
         ] + [("amber", "bg", 3), ("green", "bg", 3), ("text", "bg", 3)]


def test_text_contrast():
    colours = _tokens()
    for text, ground, least in PAIRS:
        assert _contrast(colours[text], colours[ground]) >= least, (text, ground)
    for fill in ("green-fill", "red-fill"):  # white bold text on Fail and Pass
        assert _contrast("#FFFFFF", colours[fill]) >= 4.5, fill


def test_focus_rings_and_no_focus_on_load():
    for name, page in _new().items():
        style = page.split("<style>")[1].split("</style>")[0]
        # one ring everywhere; the open question and rule: a thin one, clear of their text;
        # the result page: the website's ring, in the text colour
        assert set(re.findall(r"outline-offset: ([^;]+);", style)) <= {"-2px", "3px", "4px"}, name
        assert re.findall(r"outline-offset: 4px", style) in ([], ["outline-offset: 4px"]), name
        assert ":focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }" in style
        assert (":focus-visible { outline: 2px solid var(--text); outline-offset: 3px; "
                "border-radius: 4px; }" in style) == (name in ("result", "report.html")), name
        assert "autofocus" not in page, name
    for name, page in (("marking", _marking()), ("old link", mark_page.old_link_page())):
        style = page.split("<style>")[1].split("</style>")[0]  # hairlines only: no shadows,
        assert "box-shadow" not in style and "drop-shadow" not in style, name  # no panels
        radii = set(re.findall(r"border-radius: ([^;]+);", style))
        assert radii <= {"4px", "2px"}, (name, radii)  # the buttons, the welcome box


# The ™ after the wordmark, the same on the website and the tool pages: 0.42em of the name, a
# 0.2em of the name as a gap before it (.476em of the ™), raised by its own size so its top lines
# up with the top of the letters.
TM_RULE = (".brand sup { font-size: .42em; line-height: 1; font-weight: 600; margin-left: .476em; "
           "position: relative; top: -1em; vertical-align: baseline; }")


def test_the_brand_has_one_tm_after_the_name_and_none_on_the_logo():
    """Logo next to the wordmark: ™ right after the name, styled as the website's .brand sup."""
    assert look.BRAND.endswith("<span>judgekeeper<sup>™</sup></span></span>")
    assert look.BRAND.count("™") == 1 and "™" not in look.LOGO
    for name, page in _served().items():
        if 'class="brand"' not in page:
            continue
        style = page.split("<style>")[1].split("</style>")[0]
        assert TM_RULE in " ".join(style.split()), name
        assert page.count("<sup>™</sup>") == page.count('class="brand"'), name  # one each
        assert "™" not in page.replace("<sup>™</sup>", ""), name  # never in text or code


def test_the_top_bar_is_the_same_on_every_page():
    for name, page in (("marking", _marking()),
                       ("result", start_label.result_html(_result(*CHECK), back="/?token=t"))):
        bar = page.split('<header class="top">')[1].split("</header>")[0]
        assert bar.startswith('<div class="meta"><span class="k">LLM-as-a-judge:</span>'
                              '<span class="v" title="openai:gpt-4.1-mini">openai:gpt-4.1-mini'
                              '</span>'
                              '<span class="k">Eval tool:</span><span class="v">promptfoo</span>'
                              "</div>") or name == "result", name
        assert look.BRAND in bar and "theme" not in bar, name
        style = page.split("<style>")[1].split("</style>")[0]
        assert ".top { height: 72px;" in style and "border-bottom: 1px solid var(--line)" in style
        assert ".brand {" in style and "font-size: 24px; font-weight: 800;" in style
        assert ".logo-mark svg { width: 34px; height: 38px; }" in style
        assert ".meta .k { font-size: 12px; font-weight: 600; letter-spacing: .04em;" in style
        assert ".meta .v { font-family: var(--mono); font-size: 12.5px;" in style


# The marking page --------------------------------------------------------------------------

def test_fail_and_pass_look_the_same_but_for_their_colour():
    style = mark_page.STYLE
    fails = re.findall(r"^(\.btn\.fail[^{]*)\{([^}]*)\}", style, re.MULTILINE)
    passes = re.findall(r"^(\.btn\.pass[^{]*)\{([^}]*)\}", style, re.MULTILINE)
    assert len(fails) == len(passes) >= 2  # the fill, and the hover
    for (fs, fb), (ps, pb) in zip(fails, passes, strict=True):
        assert fs.replace("fail", "x") == ps.replace("pass", "x")
        assert fb.replace("red", "x") == pb.replace("green", "x")
    page = _marking()
    assert 'class="btn fail" id="fail"' in page and 'class="btn pass" id="pass"' in page
    assert page.index('id="fail"') < page.index('id="pass"')
    assert (".btn { height: 50px; border-radius: 4px;" in style and "color: #fff;" in style
            and "font-size: 16px; font-weight: 700;" in style)
    assert ".btn:active { filter: brightness(.9); }" in style  # pressed: 10% darker, both
    assert ".btn.fail { background: var(--red-fill); }" in style
    assert ".btn.pass { background: var(--green-fill); }" in style


def test_the_marking_page_shows_nothing_the_judge_decided():
    text = _text(_marking()).lower()
    for word in ("agree", "kappa", "tpr", "tnr", "%", "reason", "correct", "rule", "grade"):
        assert word not in text, word


def test_the_marking_page_words():
    text = _text(_marking())
    for line in ("LLM-as-a-judge: openai:gpt-4.1-mini", "Eval tool: promptfoo", "0 marked",
                 "See your result", "Question", "Answer", "Fail ←", "Pass →",
                 "Skip this one S", "Undo Z", "To come back: judgekeeper mark", mark_page.TITLE,
                 "Start marking"):
        assert line in text, line
    assert "support bot" not in text  # one source, the same on every answer: no tag
    for gone in ("Judge's grade hidden", "Toward your first result", "Shortcuts",
                 "Saved locally", "Judge's rule", "Answers", "To come back later",
                 "Mark a few more answers", "The question", "customer", "of 40", "...",
                 "Not marked", "Come back any time"):
        assert gone not in text, gone
    page = _marking()
    assert ('<div class="row row-q"><div id="q-row"><div class="label" id="q-label">Question</div>'
            '<h1 class="question" id="q-text" dir="auto"></h1><button type="button" '
            'class="quiet q-more" id="q-more" aria-expanded="false" aria-controls="q-text" '
            'hidden>Show all</button></div>'
            '<div class="state" id="ans-status" aria-live="polite"></div></div>'
            ) in page  # the state: one quiet line at the top right of the question row
    assert ('<div class="row row-a"><div class="label">Answer</div><p class="run" id="a-run" '
            'hidden></p><div class="a-scroll" id="a-scroll"><p class="answer" id="a-text" '
            'dir="auto">') in page  # the run line: only for a repeat graded differently
    assert "avatar" not in page and "ans-pos" not in page  # no icons, no "Answer 4" heading
    assert ('<div class="sub"><button type="button" class="quiet" id="skip" aria-keyshortcuts="S">'
            '<span>Skip this one</span><kbd>S</kbd></button><button type="button" class="quiet" '
            'id="undo" aria-keyshortcuts="Z"><span>Undo</span><kbd>Z</kbd></button></div>') in page
    assert '<p class="foot">To come back: <code>judgekeeper mark</code></p>' in page
    # Skip and Undo side by side: each has its own padding, no gap between them
    assert (".sub { display: flex; align-items: center; justify-content: center; "
            "padding: 0 40px 6px; }") in mark_page.STYLE


def test_marking_page_layout():
    style = mark_page.STYLE
    assert ".wrap { flex: 1; display: grid; grid-template-columns: 400px 1fr;" in style
    assert "height: calc(100vh - 72px);" in style  # no page scroll on a laptop
    assert ".side { border-right: 1px solid var(--line);" in style
    assert ".list { list-style: none; margin: 0; padding: 0; flex: 1; overflow: auto;" in style
    assert ".card { flex: 1; display: flex; flex-direction: column; }" in style
    assert ".row { padding: 32px 40px; border-bottom: 1px solid var(--line); }" in style
    assert ".question { font-size: 26px; font-weight: 700;" in style and "max-width: 28ch;" in style
    assert ".answer { font-size: 20px; line-height: 1.6;" in style and "max-width: 60ch;" in style
    assert (".label { font-size: 11px; font-weight: 600; letter-spacing: .1em; "
            "text-transform: uppercase; color: var(--faint);") in style
    assert ".state { font-size: 13px; color: var(--muted);" in style
    assert ".state .said { font-weight: 600; }" in style  # the mark word: semibold, coloured
    assert ".state .said.pass { color: var(--green); }" in style
    assert ".state .said.fail { color: var(--red); }" in style
    assert ".item { width: 100%; display: grid; grid-template-columns: 36px minmax(0, 1fr) 16px;" \
        in style
    assert "padding: 15px 22px 15px 20px; border-bottom: 1px solid var(--line);" in style
    assert ".item .q { white-space: nowrap;" in style  # one line, cut with "…"
    assert ".item[aria-current] { background: var(--current); color: var(--text); " \
        "border-left-color: var(--text); }" in style
    assert ".item:hover { background: var(--hover);" in style
    assert ".legend" not in style  # the list's tick and cross are the buttons' own
    assert ".actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; " \
        "padding: 20px 40px 16px; border-top: 1px solid var(--line); }" in style
    assert ".foot { margin: 0; padding: 12px 40px; border-top: 1px solid var(--line); " \
        "font-size: 13px; color: var(--muted); text-align: center; }" in style
    assert ".foot code { font-family: var(--mono); font-size: 12.5px; color: var(--text); }" in style
    assert style.count("ellipsis") == 1  # only the question in the list is cut


def test_the_bar_is_segments_and_a_count_with_no_status_sentence():
    page = _marking()
    right = page.split('<div class="right">')[1].split("</header>")[0]
    assert right.startswith('<div class="progress-box" id="progress-box"><div class="status-1">'
                            '<div class="seg" '
                            'id="progress" '
                            'role="progressbar" aria-label="How close your first numbers are" '
                            'aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">')
    assert right.count("<i></i>") == mark_page.SEGMENTS == 16
    assert '<span class="count" id="count">0 marked</span>' in right
    assert '<a class="see" id="see" href="#" hidden>See your result</a>' in right
    assert right.index('id="count"') < right.index('id="see"')
    assert right.index('id="see"') < right.index('id="keep"')
    assert right.endswith('<p class="keep" id="keep" hidden>Keep going: your result appears once '
                          'there are enough Pass and Fail marks.</p></div></div>')
    style = mark_page.STYLE
    assert ".seg { display: flex; gap: 3px; }" in style
    assert ".seg i { display: block; width: 6px; height: 10px; background: var(--line); }" in style
    assert ".seg i.on { background: var(--text); }" in style
    assert ".count { font-family: var(--mono); font-size: 13px; white-space: nowrap; }" in style
    assert ".see { font-size: 13px; font-weight: 700; color: var(--green);" in style
    assert "progress-label" not in page and "SHORT_SIDE" not in page


def test_the_welcome_box_is_a_modal_over_the_whole_window():
    page = _marking()
    assert ('<div class="intro" id="intro-box" role="dialog" aria-modal="true" '
            'aria-labelledby="intro-title" tabindex="-1">') in page
    assert '<div class="scrim" id="intro" hidden>' in page  # opened by the script
    assert ".scrim { position: fixed; inset: 0;" in page
    assert '<button type="button" class="go" id="intro-ok">Start marking</button>' in page
    box = page.split('id="intro-box"')[1].split('tabindex="-1">', 1)[1].split("</div>\n</div>")[0]
    assert re.sub(r"<[^>]+>", " ", box).split() == [  # the logo, the headline, the button
        "judgekeeper", "™", "Mark", "each", "answer", "Pass", "or", "Fail.", "Start", "marking"]


def test_the_welcome_box_is_centred_green_and_plain():
    style = mark_page.STYLE
    assert (".intro { background: var(--bg); border: 1px solid var(--line); border-radius: 2px; "
            "width: 100%;\n  max-width: 520px; padding: 40px; display: flex; "
            "flex-direction: column; align-items: center;\n  gap: 24px; text-align: center; "
            "animation: appear 120ms ease-out; }") in style
    assert "@keyframes appear { from { opacity: 0; } to { opacity: 1; } }" in style
    assert ".intro .brand { font-size: 21px;" in style  # the box keeps the smaller logo and name
    assert ".intro .logo-mark svg { width: 30px; height: 33px; }" in style
    assert ".intro h2 { margin: 0; font-size: 28px; font-weight: 700;" in style
    assert ".intro .go { width: 100%; height: 56px; font-size: 17px; }" in style
    assert ".go { font-weight: 700; border-radius: 4px; color: #fff; background: var(--green-fill);" \
        in style  # white on the Pass green
    assert "animation: none !important" in look.BASE  # no fade under reduced motion
    page = _marking()
    assert '$("app").setAttribute("inert", "")' in page  # the page behind the box is inert
    assert '$("app").removeAttribute("inert")' in page


def test_the_end_card_is_one_centred_card_in_the_answers_place():
    page = _marking()
    assert ('<section class="card end" id="end" hidden aria-live="polite" tabindex="-1">'
            '<h2 id="end-title"></h2>'
            '\n    <p class="note" id="end-note" hidden>Opening your result…</p>'
            '\n    <button type="button" class="go" id="again" hidden>Look at them</button>'
            "</section>") in page
    style = mark_page.STYLE
    assert (".end { padding: 56px 28px; display: flex; flex-direction: column; "
            "align-items: center; gap: 24px;") in style
    assert ".end h2 { margin: 0; font-size: 26px; font-weight: 700;" in style
    assert "max-width: 32ch; }" in style
    assert ".end .note { margin: 0; color: var(--muted); font-size: 15px; }" in style
    assert "height: 50px; padding: 0 28px; font-size: 16px;" in style.split(".go {")[1]
    assert "You marked every answer." in page and "skipped answer" in page


def test_marking_page_heading_progressbar_and_row_words():
    page = _marking()
    assert page.count("<h1") == 1 and '<h1 class="question" id="q-text" dir="auto">' in page
    assert "<h2" not in page.split('id="end"')[0].split("</header>")[1]  # no list heading
    assert '"marked Pass"' in page and '"marked Fail"' in page and '"not marked"' in page
    assert '<nav class="side" aria-label="Answers">' in page


def test_a_narrow_window_stacks_the_bar_and_puts_the_card_before_the_list():
    style = mark_page.STYLE
    narrow = style.split("@media (max-width: 760px) {")[1].split("\n}\n")[0]
    assert ".wrap { grid-template-columns: 1fr; height: auto; }" in narrow
    assert ".side { border-right: 0; border-top: 1px solid var(--line); order: 2; }" in narrow
    assert ".main { order: 1; }" in narrow
    assert ".btn { height: 60px;" in narrow
    # the bar stacks up to 900px, so an iPad held upright shows the whole model name
    bar = look.BASE.split("@media (max-width: 900px) {")[1].split("\n}\n")[0]
    assert ".meta { grid-row: 1;" in bar and ".brand { grid-row: 2;" in bar  # lines, logo,
    assert ".top .right { grid-row: 3;" in bar                                # then progress
    phone = look.BASE.split("@media (max-width: 760px) {")[1].split("\n}\n")[0]
    assert ".meta .k { font-size: 13px; }" in phone and ".meta .v { font-size: 14px; }" in phone
    # a small phone puts each label above its value, so the model name is shown whole
    small = look.BASE.split("@media (max-width: 420px) {")[1].split("\n}\n")[0]
    assert ".meta { grid-template-columns: minmax(0, 1fr); gap: 0; }" in small
    assert ".meta .v { white-space: normal; overflow-wrap: anywhere; }" in small
    assert "insertBefore" not in mark_page.BODY and "rail" not in mark_page.BODY


def test_the_judges_rule_is_not_on_the_marking_page():
    about = {"rule": "THE RULE: be <kind> & fair", "fingerprint": {"model": "m"}, "tool": "promptfoo",
             "results_files": ["results.json"]}
    page = start_label.page_template(about)
    assert "be <kind>" not in page and "be &lt;kind&gt;" not in page and "THE RULE" not in page
    assert 'id="rule"' not in page and 'id="fold"' not in page


def test_text_from_results_can_never_hold_a_server_name():
    page = mark_page.label_page(None, "judgekeeper mark __NONCE__", model="__TOKEN__",
                                tool="__DATA__")
    assert page.count("__DATA__") == 1 and page.count("__TOKEN__") == 1
    assert page.count("__NONCE__") == 1  # the one script's own


# The result page ---------------------------------------------------------------------------

TOO_EARLY = (900, 100, 25, 24, 25, 1)  # one 99% range reaches far below 80%: too early
MISTAKE = {"judge": "pass", "final": "fail", "question": "q", "answer": "a", "reason": "r"}


def _mistakes(n_easy: int, n_strict: int) -> list[dict]:
    return ([{**MISTAKE, "question": f"easy {i}"} for i in range(n_easy)]
            + [{**MISTAKE, "judge": "fail", "final": "pass", "question": f"strict {i}",
                "reason": f"why strict {i}"} for i in range(n_strict)])


HIDDEN = "hidden on purpose, so a new rule can be tested on answers you haven't looked at again."


def _part(html: str, start: str, end: str = "</section>") -> str:
    return html.split(start, 1)[1].split(end, 1)[0] if start in html else ""


def test_the_result_top_bar_has_the_judge_and_the_logo_only():
    html = start_label.result_html(_result(*CHECK, judge={"tool": "promptfoo",
                                                          "results_files": ["r.json"]}))
    bar = html.split('<header class="top">')[1].split("</header>")[0]
    assert bar.endswith('<div class="right"></div>')
    assert "marked" not in bar and "See your result" not in bar and "progress" not in bar
    assert "Eval tool:" in bar


@pytest.mark.parametrize("counts, state, headline", [
    (GATE, "good", "Your LLM-as-a-judge is good enough to use."),
    (NOT_GATE_TNR, "needs", "Your LLM-as-a-judge needs work."),
    (NOT_GATE_TPR, "needs", "Your LLM-as-a-judge needs work."),
    (CHECK, "plain", "Too early to tell."),
    (TOO_EARLY, "plain", "Too early to tell."),
    (TOO_FEW, "plain", "Mark a few more answers to see your result.")])
def test_each_result_level_shows_its_state(counts, state, headline):
    html = start_label.result_html(_result(*counts))
    shown = headline.replace("LLM-as-a-judge", '<span class="term">LLM-as-a-judge</span>')
    assert f'<h1 id="verdict-h" class="{state}">{shown}</h1>' in html
    assert html.count("<h1") == 1


def test_good_and_needs_work_lead_with_the_disagreements():
    for counts, d, n in ((GATE, 2, 60), (NOT_GATE_TNR, 20, 80)):
        html = start_label.result_html(_result(*counts))
        assert (f'<p class="lead">You and your {TERM} disagreed on <b>{d}</b> of <b>{n}</b> '
                "answers.</p>") in html


@pytest.mark.parametrize("counts, said", [
    (CHECK, "You and your LLM-as-a-judge disagreed on <b>8</b> of <b>40</b> answers. "),
    (TOO_EARLY, "You and your LLM-as-a-judge disagreed on <b>2</b> of <b>50</b> answers. "),
    (TOO_FEW, "")])  # no result yet: no count
def test_too_early_leads_to_the_marking_page_or_says_the_command(counts, said):
    said = said.replace("LLM-as-a-judge", TERM)
    served = start_label.result_html(_result(*counts), back="/?token=t")
    assert (f'<p class="lead">{said}<a href="/?token=t">Mark more answers to get a result.</a>'
            "</p>") in served
    saved = start_label.result_html(_result(*counts))
    assert (f'<p class="lead">{said}Run <code>{program("mark")}</code> to mark more answers.</p>'
            in saved)
    assert "<a " not in saved.split("<body>")[1]  # the saved copy has no server to go back to


@pytest.mark.parametrize("counts, level", [(GATE, "gate"), (NOT_GATE_TNR, "not_gate"),
                                           (CHECK, "check"), (TOO_EARLY, "check")])
def test_every_result_level_says_how_many_answers_you_disagreed_on(counts, level):
    """The terminal's line ("You and your LLM-as-a-judge disagreed on 6 of 60 answers."), on the
    report for every level of result."""
    r = _result(*counts)
    assert r["verdict_level"] == level
    c = report_page.counts(r)
    html = start_label.result_html(r)
    assert (f"You and your {TERM} disagreed on <b>{c['strict'] + c['easy']}</b> of "
            f"<b>{c['passed'] + c['failed']}</b> answers.") in html


def test_the_numbers_in_the_counts_and_the_lead_are_mono_at_500():
    """JetBrains Mono at 500, so the numbers stand out from the 500
    Manrope around them; the 400 face alone reads as plain text."""
    assert ("jetbrains-mono-latin-500-normal.woff2", "JetBrains Mono", "500") in look.FONTS
    data = (PACKAGE_FONTS / "jetbrains-mono-latin-500-normal.woff2").read_bytes()
    assert data[:4] == b"wOF2"
    html = start_label.result_html(_result(*NOT_GATE_TNR))
    assert html.count('<span class="mono') == 6  # three numbers in each count sentence


def test_the_counts_row_in_every_state():
    for counts in (GATE, CHECK, NOT_GATE_TNR, TOO_EARLY):
        r = _result(*counts)
        c = report_page.counts(r)
        text = _text(start_label.result_html(r))
        assert (f"You passed {c['passed']} answers. It passed "
                f"{c['passed'] - c['strict']} and failed {c['strict']}.") in text, counts
        assert (f"You failed {c['failed']} answers. It passed {c['easy']} "
                f"and failed {c['failed'] - c['easy']}.") in text, counts
    r = _result(*TOO_FEW)  # before a result: the person's own counts only
    c = report_page.counts(r)
    text = _text(start_label.result_html(r))
    assert f"You passed {c['passed']} answers. You failed {c['failed']} answers." in text
    assert "It passed" not in text
    html = start_label.result_html(_result(*NOT_GATE_TNR))
    assert ('<div class="counts"><p>You passed <span class="mono">24</span> answers. It passed '
            '<span class="mono">22</span> and failed <span class="mono off">2'
            "</span>.</p><p>") in html


def test_one_answer_is_said_in_the_singular():
    assert report_page.count_line("passed", 1, 1, 0) == (
        'You passed <span class="mono">1</span> answer. It passed '
        '<span class="mono">1</span> and failed <span class="mono">0</span>.')


def test_ungraded_answers_are_said_under_the_counts():
    check = {"answers": 57, "error": 2, "unreadable": 1, "nothing_checked": 4,
             "tool": "promptfoo", "tool_counted_as": "fail"}
    html = start_label.result_html(_result(*CHECK, judge_check=check))
    assert (f'<p class="left-out band">Your {TERM} gave no Pass or Fail on 3 answers. They are '
            "left out.</p>") in html
    one = start_label.result_html(_result(*CHECK, judge_check={"answers": 9, "empty": 1}))
    assert "Your LLM-as-a-judge gave no Pass or Fail on 1 answer. It is left out." in _text(one)
    for clean in ({"answers": 57}, None):
        assert 'class="left-out' not in start_label.result_html(_result(*CHECK,
                                                                         judge_check=clean))


def test_the_disagreement_groups_show_three_rows_then_show_all():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    html = start_label.result_html(r, fixing={"mistakes": _mistakes(5, 2)})
    first = _part(html, '<section class="group band" aria-labelledby="g-easy">')
    assert f'<h2 id="g-easy">You said Fail, your {TERM} said Pass</h2>' in first
    assert f'{c["easy"] - 5} more are hidden on purpose' in first
    assert ('<button type="button" class="more" aria-expanded="false" data-n="2" '
            'aria-controls="t-easy">Show 2 more</button>') in first
    assert ('<thead><tr><th scope="col">Question</th><th scope="col">Answer</th>'
            '<th scope="col">Its reason</th></tr></thead>') in first
    rows = re.findall(r"<tr( class=\"extra\" hidden)?><td data-label", first)
    assert [bool(x) for x in rows] == [False] * 3 + [True] * 2
    assert ('<td data-label="Question">easy 0</td><td data-label="Answer" id="a-easy-0">a</td>'
            '<td data-label="Its reason">r</td>') in first
    second = _part(html, '<section class="group band" aria-labelledby="g-strict">')
    assert f'<h2 id="g-strict">You said Pass, your {TERM} said Fail</h2>' in second
    assert '<th scope="col">Its reason</th>' in second and "why strict 1" in second
    assert 'class="more"' not in second  # 3 rows or fewer: no link
    assert html.index('id="g-easy"') < html.index('id="g-strict"')
    only = start_label.result_html(r, fixing={"mistakes": _mistakes(0, c["strict"])})
    easy = _part(only, '<section class="group band" aria-labelledby="g-easy">')
    assert easy == "" and 'id="g-easy"' not in only  # none to show: the group is left out


def test_the_judges_text_in_the_tables_is_escaped():
    html = start_label.result_html(_result(*NOT_GATE_TNR), fixing={"mistakes": [
        {**MISTAKE, "question": "<b>q</b>", "answer": "a & b", "reason": None}]})
    assert "&lt;b&gt;q&lt;/b&gt;" in html and "a &amp; b" in html and "<b>q</b>" not in html
    assert '<td data-label="Its reason">No reason given</td>' in html


def test_each_group_says_under_its_heading_how_many_are_kept_aside():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    html = start_label.result_html(r, fixing={"mistakes": _mistakes(c["easy"] - 4,
                                                                    c["strict"] - 1)})
    easy = _part(html, '<section class="group band" aria-labelledby="g-easy">')
    assert (f'<h2 id="g-easy">You said Fail, your {TERM} said Pass</h2></div>'
            f'<p class="kept">4 more are {HIDDEN}</p>') in easy
    strict = _part(html, '<section class="group band" aria-labelledby="g-strict">')
    assert f'<p class="kept">1 more is {HIDDEN}</p>' in strict
    none = start_label.result_html(r, fixing={"mistakes": _mistakes(c["easy"], c["strict"])})
    assert "more are hidden" not in none and "more is hidden" not in none
    hidden_only = start_label.result_html(r, fixing={"mistakes": _mistakes(c["easy"], 0)})
    assert 'id="g-strict"' not in hidden_only
    assert (f'<div class="band kept-after"><p class="kept">{c["strict"]} more are {HIDDEN}</p>'
            '</div>') in hidden_only
    early = start_label.result_html(_result(*TOO_FEW), fixing={"mistakes": []})
    assert "hidden on purpose" not in early and 'class="group' not in early


@pytest.mark.parametrize("counts", [GATE, CHECK, NOT_GATE_TNR])
def test_more_details_is_folded_with_the_estimates_and_kappa(counts):
    r = _result(*counts)
    html = start_label.result_html(r)
    main = _part(html, '<section class="main-lines band"')
    part = _part(html, '<details class="details band">', "</details>")
    assert '<summary><h2 id="details-h">More details</h2></summary>' in part
    assert f"<caption>How often your {TERM} agrees with you" in main
    for table in (main, part):
        assert ('<thead><tr><td></td><th scope="col">Estimate</th><th scope="col">Between</th>'
                "</tr></thead>") in table
    (plo, phi), (flo, fhi), (klo, khi) = (r["tpr_interval"], r["tnr_interval"],
                                          r["kappa_interval"])
    text = _text(main)
    assert (f"When you say Pass, your LLM-as-a-judge also says Pass about {r['tpr']:.0%} {plo:.0%} and "
            f"{phi:.0%}") in text
    assert (f"When you say Fail, your LLM-as-a-judge also says Fail about {r['tnr']:.0%} {flo:.0%} and "
            f"{fhi:.0%}") in text
    assert "Kappa" not in text and "When you say" not in _text(part)
    text = _text(part)
    kappa = f"{r['kappa']:.2f} {klo:.2f} and {khi:.2f}".replace("-", "−")
    assert f"Kappa ⓘ {report_page.KAPPA_MEANS} {kappa}" in text
    assert ('<button type="button" class="i" aria-describedby="kappa-tip" '
            'aria-expanded="false" aria-controls="kappa-tip" '
            'aria-label="What kappa means">ⓘ</button>') in part
    assert "<details open" not in html and 'hidden' not in part  # folded, all there
    # the main lines are open, under the headline result and before the lists
    assert html.index('class="counts"') < html.index('class="main-lines')
    assert html.index('class="main-lines') < html.index('<details class="details band">')
    assert "<details" not in main


def test_a_judge_that_gave_every_answer_one_grade_shows_kappa_as_n_a():
    part = _part(start_label.result_html(_result(100, 0, 60, 20, 0, 0)),
                 '<details class="details band">', "</details>")
    assert f"Kappa ⓘ {report_page.KAPPA_MEANS} n/a –" in _text(part)


def test_a_side_still_too_early_shows_its_number_and_range_in_more_details():
    r = _result(100, 100, 40, 22, 40, 2)
    r["tnr_interval"] = [0.1, 0.9]  # wider than the result can use
    part = _part(start_label.result_html(r), '<section class="main-lines band"')
    assert (f"When you say Fail, your LLM-as-a-judge also says Fail about {r['tnr']:.0%} "
            "10% and 90%") in _text(part)


def test_too_early_to_tell_shows_the_counts_the_estimates_and_the_disagreements():
    """A result that can't tell yet: everything but what to do next, and the note that the
    result line uses wider ranges."""
    r = _result(*TOO_EARLY)
    html = start_label.result_html(r, fixing={"mistakes": _mistakes(3, 3)})
    assert 'class="counts"' in html
    part = _part(html, '<section class="main-lines band"')
    (plo, phi), (flo, fhi) = r["tpr_interval"], r["tnr_interval"]
    text = _text(part)
    assert (f"When you say Pass, your LLM-as-a-judge also says Pass about {r['tpr']:.0%} "
            f"{plo:.0%} and {phi:.0%}") in text
    assert (f"When you say Fail, your LLM-as-a-judge also says Fail about {r['tnr']:.0%} "
            f"{flo:.0%} and {fhi:.0%}") in text
    assert "too early to tell" not in text
    assert 'class="group' in html and 'class="next' not in html
    assert '<p class="note wider">' in html


def test_before_a_result_the_page_shows_the_counts_only():
    html = start_label.result_html(_result(*TOO_FEW), fixing={"mistakes": _mistakes(3, 3)})
    assert 'class="counts"' in html
    for gone in ('class="group', 'class="main-lines', 'id="details-h"', 'class="next',
                 'class="note"'):
        assert gone not in html, gone


def test_can_t_tell_yet_keeps_everything_but_what_next():
    r = _result(*CHECK)
    c = report_page.counts(r)
    html = start_label.result_html(r, fixing={"mistakes": _mistakes(c["easy"] - 1, c["strict"])})
    for needed in ('class="counts"', 'id="g-easy"', 'id="g-strict"', "1 more is hidden on purpose",
                   'id="details-h"'):
        assert needed in html, needed
    assert 'class="next' not in html and "Keep checking it" not in html


NEXT_OPEN = '<section class="next band" aria-labelledby="next-h">'
SAVED = ("<p>Your marks and reasons are saved in this project's <code>.judgekeeper</code> "
         "folder. You can close this page.</p>")
KEEP_MARKING = '<p>Want more certain numbers? <a href="/?token=t">Keep marking</a>.</p>'
CLOSED = ("<p>It closes by itself after 30 minutes without use. Closed? Run "
          "<code>{mark}</code> in your project folder: your marks are still there.</p>")
TO_MARK_MORE = ("<p>To mark more, run <code>{mark}</code> in your project folder: your marks "
                "are still there.</p>")


def test_what_next_has_the_fix_command_for_a_judge_that_needs_work():
    judge = {"tool": "promptfoo", "rule": "Is polite."}
    html = start_label.result_html(_result(*NOT_GATE_TNR, judge=judge))
    part = _part(html, NEXT_OPEN)
    fix = program("fix")
    assert '<h2 id="next-h">What next</h2>' in part and "Fix it" not in html
    assert SAVED in part
    assert "<p>Next, in your terminal, in your project folder:</p>" in part
    assert (f'<div class="cmd"><code>{fix}</code><button type="button" class="copy" data-copy '
            'aria-label="Copy the command">') in part
    assert "Nothing more to do" not in part
    assert part.index("saved in this project") < part.index("Next, in your terminal") \
        < part.index('class="cmd"')


def test_what_next_says_there_is_nothing_more_when_the_judge_is_good_enough():
    html = start_label.result_html(_result(*GATE))
    part = _part(html, NEXT_OPEN)
    assert SAVED in part
    assert (f"<p>Nothing more to do. Run <code>judgekeeper check</code> after you change your "
            f"{TERM}.</p>") in part
    assert 'class="cmd"' not in part and "Next, in your terminal" not in part


def test_what_next_links_back_to_the_marking_page_only_on_the_page_the_server_serves():
    mark = program("mark")
    for counts in (GATE, NOT_GATE_TNR):
        live = _part(start_label.result_html(_result(*counts), "/?token=t"), NEXT_OPEN)
        saved_html = start_label.result_html(_result(*counts))
        saved = _part(saved_html, NEXT_OPEN)
        assert KEEP_MARKING in live and CLOSED.format(mark=mark) in live, counts
        assert live.index(KEEP_MARKING) < live.index("Closed?")
        assert TO_MARK_MORE.format(mark=mark) not in live
        assert SAVED in live and SAVED in saved
        assert TO_MARK_MORE.format(mark=mark) in saved, counts
        assert "Keep marking" not in saved and "Closed?" not in saved
        assert "<a " not in saved and "token" not in saved_html



def test_what_next_never_sends_to_marking_when_every_answer_is_marked():
    mark = program("mark")
    for counts in (GATE, NOT_GATE_TNR):
        live = _part(start_label.result_html(_result(*counts, left=0), "/?token=t"), NEXT_OPEN)
        saved = _part(start_label.result_html(_result(*counts, left=0)), NEXT_OPEN)
        assert SAVED in live and SAVED in saved, counts
        assert "Keep marking" not in live and "Closed?" not in live, counts
        assert TO_MARK_MORE.format(mark=mark) not in saved, counts
        assert mark not in live and mark not in saved, counts
    left = _part(start_label.result_html(_result(*GATE, left=3)), NEXT_OPEN)
    assert TO_MARK_MORE.format(mark=mark) in left

def test_the_mark_line_comes_after_the_next_step():
    mark = program("mark")
    fix = _part(start_label.result_html(_result(*NOT_GATE_TNR)), NEXT_OPEN)
    assert fix.index('class="cmd"') < fix.index(TO_MARK_MORE.format(mark=mark))
    good = _part(start_label.result_html(_result(*GATE)), NEXT_OPEN)
    assert good.index("Nothing more to do") < good.index(TO_MARK_MORE.format(mark=mark))


def test_the_mark_command_keeps_the_flags_of_the_run():
    r = _result(*GATE, flags={"path": "evals/app", "port": 9000})
    mark = report_page.commands(r)["mark"]
    assert mark == f"{program('mark')} evals/app"
    assert TO_MARK_MORE.format(mark=mark) in start_label.result_html(r)
    assert CLOSED.format(mark=mark) in start_label.result_html(r, "/?token=t")


def test_what_next_is_the_same_one_command_for_a_table_of_grades():
    """A table of grades has no rule judgekeeper can read: the command is the same one, as for
    every eval tool (`fix` says what to do next)."""
    html = start_label.result_html(_result(*NOT_GATE_TNR, judge={"tool": "table", "rule": None}))
    part = _part(html, NEXT_OPEN)
    assert "<p>Next, in your terminal, in your project folder:</p>" in part
    assert "re-run" not in part
    for counts in (CHECK, TOO_EARLY, TOO_FEW):  # no result yet: no end panel
        assert 'class="next' not in start_label.result_html(_result(*counts)), counts


def test_what_next_keeps_the_path_the_result_was_made_for():
    html = start_label.result_html(_result(*NOT_GATE_TNR, flags={"path": "evals/app"}))
    assert f'<div class="cmd"><code>{program("fix")} evals/app</code>' in html


GONE = ("History", "Your marks:", "Where it goes wrong", "Its rule may be", "results.json",
        "made on", "This page is saved", "Changed your LLM-as-a-judge", "Fix it",
        "showed you half", "Your LLM-as-a-judge passes", "Next step", "Did your LLM-as-a-judge actually judge?",
        "Nothing to do", "Use your tested rule", "Keep checking it", "Details</h3>",
        "too strict on", "too easy on", "Your LLM-as-a-judge's rule")


@pytest.mark.parametrize("counts", [GATE, CHECK, NOT_GATE_TNR, TOO_EARLY, TOO_FEW])
def test_what_is_gone_from_the_result_page(counts):
    r = _result(*counts, left=7, judge={"tool": "promptfoo", "results_files": ["results.json"],
                                        "rule": "Be kind.", "results_date": "2026-10-05 05:30"},
                judge_check={"answers": 57, "reason_says_opposite": 1, "tool": "promptfoo"})
    fixing = {"patterns": ["7 of its 10 mistakes are answers it passed but you failed.",
                           "Its rule may be too easy."], "mistakes": _mistakes(2, 1),
              "tested": {"rule": "Be fair.", "verdict": "better", "where": None}}
    for back in (None, "/?token=t"):
        html = start_label.result_html(r, back, fixing=fixing)
        text = _text(html)
        for gone in GONE:
            assert gone not in text, (gone, back)
        above = _text(html.split('class="main-lines')[0])
        assert "%" not in above  # no percentage above the two main lines
        if r["verdict_level"] not in ("too_early", None, "check"):
            assert "Mark more answers" not in text


def test_the_result_page_style():
    style = report_page.STYLE
    for rule in ((".band { padding-left: max(var(--gutter), calc((100% - 1376px) / 2));\n"
                  "  padding-right: max(var(--gutter), calc((100% - 1376px) / 2)); }"),
                 ":root { --gutter: 32px; }",
                 ".verdict { padding-top: 88px; padding-bottom: 72px; text-align: center; }",
                 (".verdict h1 { margin: 0 auto; font-size: clamp(34px, 4vw, 56px); "
                  "line-height: 1.1;"),
                 ".verdict h1.needs { color: var(--amber); }",
                 ".verdict h1.good { color: var(--green); }",
                 ".verdict h1.plain { color: var(--text); }",
                 (".lead b { font-family: var(--mono); font-weight: 500; font-size: 18px; "
                  "color: var(--text); }"),
                 ".mono { font-family: var(--mono); font-weight: 500; white-space: nowrap; }",
                 (".counts { border-top: 1px solid var(--line); border-bottom: 1px solid "
                  "var(--line); display: grid; grid-template-columns: 1fr 1fr; }"),
                 (".counts p { margin: 0; padding: 32px var(--gutter); font-size: 19px; "
                  "line-height: 1.4; font-weight: 500; }"),
                 (".left-out { margin: 16px 0 0; font-size: 14px; color: var(--muted); "
                  "max-width: 80ch; }"),
                 ".group { padding-top: 64px; }",
                 (".gh h2 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -.01em; "
                  "}"),
                 (".open-row { font-size: 14px; color: var(--muted); text-decoration: "
                  "underline;\n  text-decoration-color: var(--faint); text-underline-offset: 3px;"),
                 (".tbl col.c1 { width: 28%; } .tbl col.c2 { width: 44%; } "
                  ".tbl col.c3 { width: 28%; }"),
                 ".tbl td { font-size: 17px; line-height: 1.55; padding: 24px 32px 24px 0;",
                 (".note { margin: 16px 0 0; font-size: 14px; color: var(--muted); "
                  "text-align: left;\n  max-width: 80ch; }"),
                 ".details { margin-top: 64px; border-top: 1px solid var(--line); }",
                 (".panel col.d1 { width: 48%; } .panel col.d2 { width: 26%; } "
                  ".panel col.d3 { width: 26%; }"),
                 ".panel td { font-size: 17px; padding: 20px 32px 20px 0;",
                 # a tap opens kappa's tip and a second tap closes it; hover only with a mouse
                 (".kappa .i[aria-expanded=\"true\"] + .tip, "
                  ".kappa .i:focus-visible:not([data-shut]) + .tip {\n  display: block; }"),
                 "@media (hover: hover) { .kappa:hover .tip { display: block; } }",
                 (".next { border-top: 1px solid var(--line); padding-top: 48px; "
                  "padding-bottom: 72px; }"),
                 (".next p { margin: 0; font-size: 17px; line-height: 1.6; color: var(--muted); "
                  "max-width: 64ch; }"),
                 # the website's command box: 8px corners, its own dark ground
                 ("  border: 1px solid var(--line); border-radius: 8px; overflow: hidden; "
                  "max-width: 100%;\n  min-width: min(380px, 100%); background: #07080a; }"),
                 "@media (max-width: 720px) {"):
        assert rule in style, rule
    assert "box-shadow" not in style.replace(".part[aria-pressed=\"true\"] .bx { background: "
                                             "var(--text); border-color: var(--text);\n  "
                                             "box-shadow: inset 0 0 0 2px var(--bg); }", "")
    assert set(re.findall(r"border-radius: ([^;]+);", style)) <= {"0", "3px", "4px", "8px"}
    narrow = style.split("@media (max-width: 720px) {")[1]
    assert ":root { --gutter: 16px; }" in narrow
    assert ".tbl, .tbl tbody, .tbl tr, .tbl td { display: block; }" in narrow
    assert ".tbl td::before { content: attr(data-label);" in narrow
    # on a phone: "judgekeeper fix" on one line, and no text under 13px
    for rule in (".cmd code { padding: 12px 14px; }", ".cmd { display: grid; width: 100%; min-width: 0; }",
                 ".tbl td::before { font-size: 13px; }",
                 ".panel td[data-label]::before, .panel caption, .note { font-size: 14px; }",
                 ".kappa .tip { font-size: 15px; }"):
        assert rule in narrow, rule
    # on a phone or a touch screen, "Show all" and kappa's ⓘ are big enough to tap (48 and
    # 44px), with the layout as it was
    touch = style.split("@media (max-width: 720px), (pointer: coarse) {")[1].split("\n}\n")[0]
    assert ".more { font-size: 16px; }" in touch
    assert (".kappa .i { font-size: 18px; padding: 13px 14px; margin: -13px -14px -13px -8px; }"
            in touch)
    # from 300px down (a phone with bigger text), Copy goes under the command
    tiny = style.split("@media (max-width: 300px) {")[1].split("\n}\n")[0]
    assert ".cmd { grid-template-columns: 1fr; }" in tiny
    # Safari sized the command box from its 380px floor and let it stick out: not on a phone
    assert "min-width: min(380px, 100%)" in style


def test_the_page_runs_only_its_own_script():
    html = start_label.result_html(_result(*NOT_GATE_TNR), fixing={"mistakes": _mistakes(5, 1)})
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert scripts == [report_page.SCRIPT]
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)[1]
    assert meta == report_page.CSP
    assert all(look.script_hash(s) in meta for s in scripts)
    assert "'unsafe-inline'" not in meta.split("script-src")[1].split(";")[0]
    assert "default-src 'none'" in meta and "connect-src" not in meta  # it sends nothing


def test_show_all_and_copy_work(tmp_path):
    """The page's script in node, against a small stand-in for the browser."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    stub = r"""
var timers = [], copied = [];
function El(id) { this.id = id; this.attrs = {}; this.hidden = false; this.listeners = {};
  this.textContent = ""; this.innerHTML = ""; this.className = ""; var self = this;
  this.classList = { toggle: function (c, on) { self.className = on ? c : ""; } }; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.addEventListener = function (t, f) { this.listeners[t] = f; };
El.prototype.querySelectorAll = function () { return this.rows; };
El.prototype.closest = function () { return null; };
El.prototype.getBoundingClientRect = function () { return {top: 0}; };
var copy = new El("copy"), code = new El("code"), said = new El("copied"), sel = [];
code.textContent = "judgekeeper fix";
copy.parentNode = {querySelector: function () { return code; }};
copy.querySelector = function () { return said; };
copy.classList = {add: function (c) { copy.className = c; },
  remove: function () { copy.className = ""; }};
var ids = {"t-easy": new El("t-easy")};
var more = new El("more"); more.attrs["aria-controls"] = "t-easy"; more.attrs["data-n"] = "2";
more.textContent = "Show 2 more";
ids["t-easy"].rows = [new El(), new El()]; ids["t-easy"].rows.forEach(function (r) { r.hidden = true; });
var document = {documentElement: new El("html"),
  getElementById: function (id) { return ids[id] || null; },
  querySelectorAll: function (s) { return s === ".more" ? [more] : s === "[data-copy]" ? [copy] : []; },
  createRange: function () { return {selectNodeContents: function () {}}; },
  execCommand: function (c) { sel.push("copy " + c);
    if (execThrows) { throw new Error("no"); } return execWorks; }};
var execWorks = true, execThrows = false;
var window = {localStorage: {getItem: function () { return null; }, setItem: function () {}},
  addEventListener: function () {},
  getSelection: function () { return {removeAllRanges: function () { sel.push("clear"); },
    addRange: function () { sel.push("select"); }}; }};
var works = true;
var navigator = {clipboard: {writeText: function (t) { copied.push(t);
  return works ? Promise.resolve() : Promise.reject(new Error("no")); }}};
function setTimeout(f, ms) { timers.push([f, ms]); return timers.length; }
function clearTimeout() {}
"""
    scenario = r"""
(async function () {
  more.listeners.click();
  var opened = [more.textContent, more.getAttribute("aria-expanded"),
                ids["t-easy"].rows.map(function (r) { return r.hidden; })];
  more.listeners.click();
  var closed = [more.textContent, ids["t-easy"].rows.map(function (r) { return r.hidden; })];
  copy.listeners.click(); await Promise.resolve(); await Promise.resolve();
  var done = [copied.slice(), said.textContent, copy.className, timers[0][1]];
  timers[0][0]();
  var back = [said.textContent, copy.className];
  works = false; copy.listeners.click();  // no clipboard: select, copy, then clear
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  var fallback = [sel.slice(), said.textContent];
  execWorks = false; sel.length = 0; copy.listeners.click();  // the copy itself failed
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  var failed = [sel.slice(), said.textContent, copy.className];
  timers[timers.length - 1][0]();
  var after = [said.textContent, copy.className];
  execThrows = true; copy.listeners.click();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  console.log(JSON.stringify({opened: opened, closed: closed, done: done, back: back,
    fallback: fallback, failed: failed, after: after,
    thrown: [said.textContent, copy.className]}));
})();
"""
    script = tmp_path / "page.js"
    script.write_text(stub + report_page.SCRIPT + scenario, encoding="utf-8")
    out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["opened"] == ["Show less", "true", [False, False]]
    assert got["closed"] == ["Show 2 more", [True, True]]
    assert got["done"] == [["judgekeeper fix"], "Copied", "done", 1500]
    assert got["back"] == ["", ""]
    assert got["fallback"] == [["clear", "select", "copy copy", "clear"], "Copied"]
    # "Copied" only when the copy worked: execCommand gave false, or threw
    assert got["failed"] == [["clear", "select", "copy copy", "clear"], "Copy failed", "failed"]
    assert got["after"] == ["", ""]
    assert got["thrown"] == ["Copy failed", "failed"]


def test_the_counts_on_the_page_add_up(tmp_path, monkeypatch):
    """The counts row (every mark) = the disagreements in the tables (the marks you can see)
    + those kept aside (the hidden marks)."""
    import json

    from judgekeeper import fix
    from judgekeeper.cli import main
    from tests.test_fix import project

    project_dir = tmp_path / "support-bot"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    ws = project(project_dir)
    assert main(["fix"]) == 0  # hides some marks
    assert main([]) == 0  # the result, with report.html
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    c = report_page.counts(r)
    split = json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))
    m = fix.Marks(ws)
    seen = sum(m.person[i] != m.judge[i] for i in split["visible"])
    hidden = sum(m.person[i] != m.judge[i] for i in split["hidden"])
    assert c["easy"] + c["strict"] == seen + hidden and hidden > 0
    html = ws.report_html.read_text(encoding="utf-8")
    assert html.count('<td data-label="Question">') == seen
    kept = re.findall(r"(\d+) more (?:is|are) hidden on purpose", _text(html))
    assert sum(map(int, kept)) == hidden

# The page for an old link ------------------------------------------------------------------

def test_the_old_link_page():
    page = mark_page.old_link_page()
    text = _text(page)
    assert "This link no longer works." in text and mark_page.OLD_LINK in text
    assert f"To open the page again, run {program('mark')}." in text
    assert "Judge:" not in text  # the logo only
    assert all(look.script_hash(s) in mark_page.OLD_LINK_CSP
               for s in re.findall(r"<script>(.*?)</script>", page, re.DOTALL))


def test_every_page_fits_a_phone_width_viewport():
    for name, page in _new().items():
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page, \
            name


@pytest.mark.parametrize("tool, files, name", [
    ("table", ["evals/results.csv"], "your own CSV file"),
    ("table", ["graded.jsonl"], "your own JSONL file"),
    ("records", None, "judgekeeper.record() in your code"),
    ("mapped", ["out.json"], "your own format"),
    ("promptfoo", ["results.json"], "promptfoo")])
def test_the_pages_name_the_eval_tool_as_the_terminal_does(tool, files, name):
    from judgekeeper.front import tool_name

    assert tool_name(tool, files) == name
    marking = start_label.page_template({"tool": tool, "results_files": files,
                                         "fingerprint": {"model": "m"}})
    result = start_label.result_html(_result(*CHECK, judge={"tool": tool,
                                                            "results_files": files}))
    for page in (marking, result):
        assert f'Eval tool:</span><span class="v">{escape(name)}</span>' in page


def test_the_top_bar_labels_and_the_details_table_are_readable_by_everyone():
    """The Judge and Eval tool labels at 4.5:1; every value in More details has a column and a
    row header, so a screen reader says what each number is."""
    colours = _tokens()
    label = re.search(r"\.meta \.k \{([^}]*)\}", look.BASE).group(1)
    colour = re.search(r"color: var\(--([a-z-]+)\)", label).group(1)
    assert _contrast(colours[colour], colours["bg"]) >= 4.5, colour
    html = _served()["report.html"]
    tables = re.findall(r'<table class="panel">.*?</table>', html, re.DOTALL)
    assert len(tables) == 2  # the two main lines, and kappa in More details
    rows = [row for table in tables for row in re.findall(r"<tr>(.*?)</tr>", table.split("<tbody>")[1])]
    assert len(rows) == 3
    for row in rows:
        assert row.startswith('<th scope="row">'), row
        assert row.count("<td") == 2
    for table in tables:
        assert '<th scope="col">Estimate</th><th scope="col">Between</th>' in table


# Bold and bullets in an answer or a question: only these two --------------------------------

PAYLOAD = ("**<img src=x onerror=alert(1)>** <script>alert(1)</script>\n- <b>x</b>\n"
           "- **two** items\n**unclosed and * a star\nlast")
PAYLOAD_HTML = ("<strong>&lt;img src=x onerror=alert(1)&gt;</strong> "
                "&lt;script&gt;alert(1)&lt;/script&gt;"
                "<ul><li>&lt;b&gt;x&lt;/b&gt;</li><li><strong>two</strong> items</li></ul>"
                "**unclosed and * a star\nlast")


def _cell(html: str, label: str) -> str:
    return html.split(f'<td data-label="{label}"', 1)[1].split(">", 1)[1].split("</td>", 1)[0]


def _page_with(row: dict, back: str | None = None) -> str:
    return start_label.result_html(_result(*NOT_GATE_TNR), back,
                                   fixing={"mistakes": [{**MISTAKE, **row}]})


@pytest.mark.parametrize("back", [None, "/?token=t"])
def test_an_answer_shows_bold_and_bullets_and_everything_else_as_text(back):
    cell = _cell(_page_with({"answer": PAYLOAD}, back), "Answer")
    assert cell == PAYLOAD_HTML
    assert set(re.findall(r"</?([a-z]+)", cell)) == {"strong", "ul", "li"}


@pytest.mark.parametrize("back", [None, "/?token=t"])
def test_a_question_shows_bold_and_bullets_and_everything_else_as_text(back):
    cell = _cell(_page_with({"question": PAYLOAD}, back), "Question")
    assert cell == PAYLOAD_HTML
    fields = _page_with({"fields": [["Topic", PAYLOAD], ["Other", "- **a**"]]}, back)
    cell = _cell(fields, "Question")
    assert (f'<span class="fname">Topic</span>{PAYLOAD_HTML}\n<span class="fname">Other</span>'
            "<ul><li><strong>a</strong></li></ul>") == cell


def test_a_long_question_ending_in_a_question_keeps_its_bold_in_every_part():
    text = "**Context** line one\n" + "More context here.\n" * 12 + "- a\n\n**Why** not?"
    cell = _cell(_page_with({"question": text}), "Question")
    assert cell.count("<strong>Context</strong>") == 2  # the folded start and the whole text
    assert cell.count("<strong>Why</strong>") == 1
    assert set(re.findall(r"</?([a-z]+)", cell)) <= {"span", "strong", "ul", "li"}


def test_the_words_the_person_marked_keep_their_highlight_inside_bold():
    why = {"spans": [[0, 5], [8, 12]]}
    cell = _cell(_page_with({"answer": "hello **bold** world", "why": why}), "Answer")
    assert cell == ('<b class="hl">hello</b> <strong><b class="hl">bold</b></strong> world')


def test_a_row_with_a_reason_box_keeps_its_answer_as_text_because_the_box_counts_it():
    row = {"id": "a1", "answer": "**x** and\n- y"}
    live = _page_with(row, "/?token=t")
    assert _cell(live, "Answer") == "**x** and\n- y" and 'data-len="13"' in live
    assert _cell(_page_with(row), "Answer") == "<strong>x</strong> and<ul><li>y</li></ul>"


def test_an_answer_with_no_marks_is_escaped_text_as_before():
    cell = _cell(_page_with({"answer": "a < b & c\n\nd -e **"}), "Answer")
    assert cell == "a &lt; b &amp; c\n\nd -e **"


def test_the_wider_ranges_note_shows_only_with_a_range_on_screen():
    """The note is about the ranges shown: with every answer marked there are none, so the
    result page and report.html leave it out; one range on screen keeps it."""
    every = _result(30, 30, 30, 27, 30, 3, left=0)  # no range on either line
    one = _result(30, 900, 30, 30, 25, 5, left=875)  # TNR exact, TPR with a range
    for back in ("/?token=t", None):  # the result page, report.html
        assert '<p class="note wider">' not in start_label.result_html(every, back=back)
        assert '<p class="note wider">' in start_label.result_html(one, back=back)
