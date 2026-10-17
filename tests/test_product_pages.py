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

GATE = (100, 100, 20, 19, 20, 1)
CHECK = (100, 100, 15, 12, 15, 3)          # both ranges reach below 80%, and are wide
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
            "report.html": start_label.result_html(_result(*CHECK)),
            "old link": mark_page.old_link_page()}


_new = _served


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


# Light, dark, contrast ---------------------------------------------------------------------

def _tokens(theme: str) -> dict[str, str]:
    start = look.TOKENS.index(':root[data-theme="light"]' if theme == "light" else ":root {")
    block = look.TOKENS[start:look.TOKENS.index("}", start)]
    return dict(re.findall(r"--([\w-]+): (#[0-9A-Fa-f]{6})", block))


def test_dark_first_and_light_by_the_switch():
    for name, page in _new().items():
        assert "<html lang=\"en\">" in page, name  # no theme set: dark
        assert "prefers-color-scheme" not in page and "invert(" not in page, name
        assert look.THEME_FIRST in page and look.SWITCH in page, name
        assert page.index(look.THEME_FIRST) < page.index("<style>"), name  # before drawing
    assert look.THEME_FIRST.startswith("try {")  # a blocked storage: dark
    assert '"jk-theme") === "light"' in look.THEME_FIRST  # only a saved "light" turns it light
    assert 'aria-label="Dark mode" aria-pressed="true"' in look.SWITCH
    assert ":root { color-scheme: dark;" in look.TOKENS


def test_the_colours_are_the_locked_looks():
    dark, light = _tokens("dark"), _tokens("light")
    assert (dark["bg"], dark["text"], dark["muted"], dark["faint"], dark["line"]) == (
        "#0b0c0e", "#e6e8eb", "#8b919a", "#585e68", "#262a30")
    assert (dark["hover"], dark["current"]) == ("#121418", "#17191e")
    assert (light["bg"], light["text"], light["muted"], light["faint"], light["line"]) == (
        "#ffffff", "#111317", "#5f6672", "#9aa0aa", "#d9dde3")
    assert (light["hover"], light["current"]) == ("#f6f7f9", "#eef0f3")
    # Green and red: Pass and Fail (their fill, hover and dots) and the "See your result" link
    assert (dark["green-fill"], dark["green"], dark["red-fill"], dark["red"]) == (
        "#0d9668", "#10B981", "#c73b40", "#e5484d")
    assert (light["green-fill"], light["green"], light["red-fill"], light["red"]) == (
        "#059669", "#059669", "#dc2626", "#dc2626")
    assert (dark["amber"], light["amber"]) == ("#e0a43a", "#b7791f")
    for theme in (dark, light):
        coloured = {k for k, v in theme.items() if v.lower() not in {
            theme["bg"], theme["text"], theme["muted"], theme["faint"], theme["line"],
            theme["hover"], theme["current"]}}
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


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_text_contrast_in_both_themes(theme):
    colours = {**_tokens("dark"), **_tokens(theme)}  # light overrides the dark defaults
    for text, ground, least in PAIRS:
        assert _contrast(colours[text], colours[ground]) >= least, (theme, text, ground)
    for fill in ("green-fill", "red-fill"):  # white bold text on Fail and Pass: the locked
        assert _contrast("#FFFFFF", colours[fill]) >= 3, (theme, fill)  # green is 3.8:1


def test_focus_rings_are_inset_in_the_text_colour_and_nothing_is_focused_on_load():
    for name, page in _new().items():
        style = page.split("<style>")[1].split("</style>")[0]
        assert re.findall(r"outline-offset: ([^;]+);", style) == ["-2px"], name
        assert ":focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }" in style
        assert "autofocus" not in page, name
    for name, page in (("marking", _marking()), ("old link", mark_page.old_link_page())):
        style = page.split("<style>")[1].split("</style>")[0]  # hairlines only: no shadows,
        assert "box-shadow" not in style and "drop-shadow" not in style, name  # no panels
        radii = set(re.findall(r"border-radius: ([^;]+);", style))
        assert radii <= {"4px", "2px"}, (name, radii)  # the buttons, the welcome box


def test_the_top_bar_is_the_same_on_every_page():
    for name, page in (("marking", _marking()),
                       ("result", start_label.result_html(_result(*CHECK), back="/?token=t"))):
        bar = page.split('<header class="top">')[1].split("</header>")[0]
        assert bar.startswith('<div class="meta"><span class="k">Judge:</span>'
                              '<span class="v" title="openai:gpt-4.1-mini">openai:gpt-4.1-mini'
                              '</span>'
                              '<span class="k">Eval tool:</span><span class="v">promptfoo</span>'
                              "</div>") or name == "result", name
        assert look.BRAND in bar and look.SWITCH in bar, name
        style = page.split("<style>")[1].split("</style>")[0]
        assert ".top { height: 72px;" in style and "border-bottom: 1px solid var(--line)" in style
        assert ".brand {" in style and "font-size: 24px; font-weight: 800;" in style
        assert ".logo-mark svg { width: 34px; height: 38px; }" in style
        assert ".theme { width: 34px; height: 34px; border: 1px solid var(--line);" in style
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
    for line in ("Judge: openai:gpt-4.1-mini", "Eval tool: promptfoo", "0 marked",
                 "See your result", "Pass Fail Not marked", "Question", "Answer",
                 "Not marked yet", "Fail ←", "Pass →", "Skip this one S", "Undo Z",
                 "Come back any time: judgekeeper mark", mark_page.TITLE, "Start marking"):
        assert line in text, line
    assert "support bot" not in text  # one source, the same on every answer: no tag
    for gone in ("Judge's grade hidden", "Toward your first result", "Shortcuts",
                 "Saved locally", "Judge's rule", "Answers", "To come back later",
                 "Mark a few more answers", "The question", "customer", "of 40", "..."):
        assert gone not in text, gone
    page = _marking()
    assert ('<div class="row row-q"><div><div class="label">Question</div>'
            '<h1 class="question" id="q-text"></h1></div>'
            '<div class="state" id="ans-status" aria-live="polite">Not marked yet</div></div>'
            ) in page  # the state: one quiet line at the top right of the question row
    assert '<div class="row row-a"><div class="label">Answer</div><p class="answer" id="a-text">' \
        in page
    assert "avatar" not in page and "ans-pos" not in page  # no icons, no "Answer 4" heading
    assert ('<div class="sub"><button type="button" class="quiet" id="skip" aria-keyshortcuts="S">'
            '<span>Skip this one</span><kbd>S</kbd></button><button type="button" class="quiet" '
            'id="undo" aria-keyshortcuts="Z"><span>Undo</span><kbd>Z</kbd></button></div>') in page
    assert '<p class="foot">Come back any time: <code>judgekeeper mark</code></p>' in page


def test_the_marking_page_layout_is_a_list_column_and_a_card_that_fills_the_window():
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
    assert ".item { width: 100%; display: grid; grid-template-columns: 36px 1fr 16px;" in style
    assert "padding: 15px 22px 15px 20px; border-bottom: 1px solid var(--line);" in style
    assert ".item .q { white-space: normal;" in style  # the question wraps, no "..."
    assert ".item[aria-current] { background: var(--current); color: var(--text); " \
        "border-left-color: var(--text); }" in style
    assert ".item:hover { background: var(--hover);" in style
    assert ".legend { display: flex; gap: 18px; padding: 16px 22px; border-top: 1px solid " \
        "var(--line); font-size: 13px; color: var(--muted); }" in style
    assert ".actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; " \
        "padding: 20px 40px 16px; border-top: 1px solid var(--line); }" in style
    assert ".foot { margin: 0; padding: 12px 40px; border-top: 1px solid var(--line); " \
        "font-size: 13px; color: var(--muted); text-align: center; }" in style
    assert ".foot code { font-family: var(--mono); font-size: 12.5px; color: var(--text); }" in style
    assert "ellipsis" not in style  # the question in the list wraps instead


def test_the_bar_is_segments_and_a_count_with_no_status_sentence():
    page = _marking()
    right = page.split('<div class="right">')[1].split("</header>")[0]
    assert right.startswith('<div class="status-1"><div class="seg" id="progress" '
                            'role="progressbar" aria-label="Answers looked at" '
                            'aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">')
    assert right.count("<i></i>") == mark_page.SEGMENTS == 16
    assert '<span class="count" id="count">0 marked</span>' in right
    assert '<a class="see" id="see" href="#" hidden>See your result</a>' in right
    assert right.index('id="count"') < right.index('id="see"') < right.index('id="theme"')
    style = mark_page.STYLE
    assert ".seg { display: flex; gap: 3px; }" in style
    assert ".seg i { display: block; width: 6px; height: 10px; background: var(--line); }" in style
    assert ".seg i.on { background: var(--text); }" in style
    assert ".count { font-family: var(--mono); font-size: 13px; }" in style
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
        "judgekeeper", "Mark", "each", "answer", "Pass", "or", "Fail.", "Start", "marking"]


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
        in style  # white on the Pass green in both themes
    assert "animation: none !important" in look.BASE  # no fade under reduced motion
    page = _marking()
    assert '$("app").setAttribute("inert", "")' in page  # the page behind the box is inert
    assert '$("app").removeAttribute("inert")' in page


def test_the_end_card_is_one_centred_card_in_the_answers_place():
    page = _marking()
    assert ('<section class="card end" id="end" hidden aria-live="polite"><h2 id="end-title"></h2>'
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


def test_the_marking_page_has_one_h1_a_progressbar_and_hidden_words_for_each_row():
    page = _marking()
    assert page.count("<h1") == 1 and '<h1 class="question" id="q-text">' in page
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
    bar = look.BASE.split("@media (max-width: 760px) {")[1].split("\n}\n")[0]
    assert ".meta { grid-row: 1;" in bar and ".brand { grid-row: 2;" in bar  # lines, logo,
    assert ".top .right { grid-row: 3;" in bar                                # then progress
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
    assert page.count("__NONCE__") == 2  # the two scripts' own


# The result page ---------------------------------------------------------------------------

def test_the_rows_say_what_the_percentages_are():
    r = _result(*CHECK)
    text = _text(start_label.result_html(r))
    (plo, phi), (flo, fhi) = r["tpr_interval"], r["tnr_interval"]
    for line in ((f"You passed 15: your judge also passed about {r['tpr']:.0%} (could be "
                  f"{plo:.0%} to {phi:.0%})."),
                 (f"You failed 15: your judge also failed about {r['tnr']:.0%} (could be "
                  f"{flo:.0%} to {fhi:.0%})."),
                 "too strict on 3", "too easy on 3",
                 report_page.ESTIMATES.format(n=30), "30 marks · made on 5 Oct",
                 "Your marks: 15 Pass · 15 Fail", r["verdict"]):
        assert line in text, line


def test_a_side_too_early_to_tell_has_no_number_or_bar():
    r = _result(100, 100, 30, 29, 15, 1)
    html = start_label.result_html(r)
    if start_label.too_early(r["tnr"], r["tnr_interval"]):
        row = html.split('You failed 15')[1].split('<div class="est')[0]
        assert "too early to tell" in row and 'class="fill"' not in row


def test_too_few_marks_show_no_numbers():
    r = _result(100, 100, 2, 1, 1, 0)
    body = _text(start_label.result_html(r))
    assert "%" not in body and "0.00" not in body and "about" not in body
    assert "Mark a few more answers to see your result. So far: 1 Pass, 2 Fail." in body


@pytest.mark.parametrize("counts", [GATE, CHECK, NOT_GATE_TNR, NOT_GATE_TPR, TOO_FEW])
def test_the_headline_is_the_verdict_and_weak_rows_are_amber(counts):
    from judgekeeper import targets

    r = _result(*counts)
    html = start_label.result_html(r)
    assert f'<h1 id="result-h">{escape(r["verdict"])}</h1>' in html and html.count("<h1") == 1
    if r["check"] != "too_few":
        rows = re.findall(r'<div class="est( weak)?">', html)
        assert [bool(w) for w in rows] == [targets.side(r[f"{k}_interval"]) != "yes"
                                           for k in ("tpr", "tnr")]


def test_details_define_tpr_and_tnr_and_show_the_raw_counts_beside_the_estimates():
    r = _result(*CHECK)
    text = _text(start_label.result_html(r))
    assert (f"TPR (true positive rate): about {r['tpr']:.0%} (12 of 15 of your marks, adjusted "
            "for how the answers were picked)") in text
    assert "Of the answers you passed, how many your judge also passed." in text
    assert (f"TNR (true negative rate): about {r['tnr']:.0%} (12 of 15 of your marks, adjusted "
            "for how the answers were picked)") in text
    assert "Of the answers you failed, how many your judge also failed." in text
    lo, hi = r["kappa_interval"]
    assert (f"Agreement beyond coincidence (kappa): {r['kappa']:.2f} (could be {lo:.2f} to "
            f"{hi:.2f}). 0 means no better than coincidence, 1 means it always agrees.") in text
    assert "Your judge passes" in text and "judgekeeper showed you half" in text


def test_the_page_runs_only_its_own_script():
    html = start_label.result_html(_result(*CHECK))
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert scripts == [look.THEME_FIRST, report_page.SCRIPT]
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)[1]
    assert meta == report_page.CSP
    assert all(look.script_hash(s) in meta for s in scripts)
    assert "'unsafe-inline'" not in meta.split("script-src")[1].split(";")[0]
    assert "default-src 'none'" in meta and "connect-src" not in meta  # it sends nothing


def test_report_html_has_commands_and_the_served_page_a_way_back():
    saved = start_label.result_html(_result(*CHECK))
    assert "<a " not in saved.split("<body>")[1]
    served = start_label.result_html(_result(*CHECK), back="/?token=t")
    assert '<a class="btn" href="/?token=t">Mark more answers</a>' in served
    assert '<a href="/?token=t">back to the marking page</a>' in served
    assert ("This page is saved as <code>.judgekeeper/report.html</code>. Your marks and "
            "answers stay on this computer.") in saved


# The next step: from the result --------------------------------------------------------------

MISTAKE = {"judge": "pass", "final": "fail", "question": "q", "answer": "a", "reason": "r"}


def test_the_next_step_follows_the_result():
    step = report_page.next_step
    assert step(_result(*TOO_FEW), None)["kind"] == "mark"
    assert step(_result(*TOO_FEW, left=0), None)["kind"] == "eval"
    assert step(_result(*CHECK), None) == {"kind": "mark", "title": "Mark more answers",
                                           "text": "More marks make your numbers more precise.",
                                           "command": program("mark")}
    assert step(_result(*CHECK, left=0), None)["kind"] == "eval"
    assert step(_result(*GATE), None) == {
        "kind": "done", "title": "Nothing to do", "command": program("check"),
        "text": "When you change your judge or update your eval tool, check it again:"}
    fixing = {"mistakes": [MISTAKE] * 3}
    assert step(_result(*NOT_GATE_TNR), fixing)["kind"] == "fix"
    assert step(_result(*NOT_GATE_TNR), {"mistakes": [MISTAKE] * 2})["kind"] == "done"
    tested = {**fixing, "tested": {"rule": "Be fair.", "verdict": "better",
                                   "where": ["promptfooconfig.yaml", 14]}}
    assert step(_result(*NOT_GATE_TNR), tested)["kind"] == "use"
    assert step(_result(*TOO_FEW), tested)["kind"] == "mark"  # no result: mark first


def test_use_your_tested_rule_shows_the_rule_with_its_own_copy():
    r = _result(*NOT_GATE_TNR, judge={"tool": "promptfoo", "results_files": ["results.json"]})
    fixing = {"mistakes": [], "tested": {"rule": "Be <fair>.", "verdict": "safe",
                                         "where": ["promptfooconfig.yaml", 14]}}
    html = start_label.result_html(r, fixing=fixing)
    text = _text(html)
    assert "Use your tested rule" in text
    assert "Put it in promptfooconfig.yaml, line 14: Be <fair>. Copy" in text
    assert "Run your eval: promptfoo eval -o results.json" in text
    assert f"Check again: {program('check')} Copy" in text
    assert '<pre class="rulebox" id="rule-text">Be &lt;fair&gt;.</pre>' in html
    assert 'data-copy="rule-text"' in html and 'data-copy="next-cmd"' in html


# Where it goes wrong -------------------------------------------------------------------------

def _mistakes(n_easy: int, n_strict: int) -> list[dict]:
    return ([{**MISTAKE, "question": f"easy {i}"} for i in range(n_easy)]
            + [{**MISTAKE, "judge": "fail", "final": "pass", "question": f"strict {i}"}
               for i in range(n_strict)])


def test_where_it_goes_wrong_is_a_table_with_the_first_rows_shown():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    shown = c["easy"] + c["strict"] - 4
    fixing = {"patterns": ["7 of its 10 mistakes are answers it passed but you failed.",
                           "Its rule may be too easy.", "Words found in many: refund (4)."],
              "mistakes": _mistakes(shown - 1, 1)}
    html = start_label.result_html(r, fixing=fixing)
    part = html.split('<section class="card wrong"')[1].split("</section>")[0]
    assert '<table class="mistakes" id="mistakes">' in part
    assert part.count('scope="col"') == 3 and part.count('scope="rowgroup"') == 2
    assert 'data-label="Question"' in part and 'data-label="Judge\'s reason"' in part
    rows = re.findall(r'<tr class="(easy|strict)-row( extra)?"', part)
    assert len(rows) == shown and [bool(x) for _, x in rows][:4] == [False] * 3 + [True]
    text = _text(part)
    assert f"On the {shown} answers you can see:" in text
    assert "<strong>7 of its 10 mistakes" in part and "Its rule may be too easy." in text
    assert f"It passed, you failed ({shown - 1})" in text and "It failed, you passed (1)" in text
    assert f"Show all {shown} disagreements" in text
    assert "4 more are among your hidden marks, kept aside to test a new rule fairly." in text


def test_before_any_marks_are_hidden_all_mistakes_show_and_no_hidden_line():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    fixing = {"patterns": [], "mistakes": _mistakes(c["easy"], c["strict"])}
    text = _text(start_label.result_html(r, fixing=fixing))
    assert "hidden marks" not in text and "you can see" not in text


def test_the_counts_on_the_page_add_up(tmp_path, monkeypatch):
    """Top rows (every mark) = the mistakes you can see + those among the hidden marks."""
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
    text = _text(ws.report_html.read_text(encoding="utf-8"))
    assert f"On the {seen} answers you can see:" in text
    assert f"{hidden} more are among your hidden marks" in text
    assert f"too strict on {c['strict']}" in text and f"too easy on {c['easy']}" in text


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
