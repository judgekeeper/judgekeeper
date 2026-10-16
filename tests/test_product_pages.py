"""The pages judgekeeper serves, as built: the marking page with its welcome box (mark_page.py),
the result page and report.html (report_page.py) and the page for an old link, on the shared
look (look.py): the logo, the fonts, light by default with a dark switch, contrast, focus
rings, equal Fail and Pass, and the words.

The marking page's behaviour is in test_mark_page_script.py.
"""

from __future__ import annotations

import base64
import re
from html import escape, unescape
from pathlib import Path

import pytest

from judgekeeper import look, mark_page, report_page, start_label, start_page, weighted
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
    return mark_page.label_page("support bot", "Be kind.\n" * 30, "judgekeeper mark",
                                model="openai:gpt-4.1-mini", tool="promptfoo")


def _served() -> dict[str, str]:
    """Every page judgekeeper serves, with the ones only `judgekeeper start` shows."""
    return {"marking": _marking(),
            "result": start_label.result_html(_result(*CHECK), back="/?token=t"),
            "report.html": start_label.result_html(_result(*CHECK)),
            "old link": mark_page.old_link_page(),
            "review": start_page.review_page("support bot", "Be kind."),
            "fix": start_page.fix_page("support bot")}


def _new() -> dict[str, str]:
    pages = _served()
    return {k: pages[k] for k in ("marking", "result", "report.html", "old link")}


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
        assert look.NAVY in page and look.GREEN in page, name
        assert "#1F6B4A\"/>" not in page, name  # never a one-colour shield
    for name, page in _new().items():
        assert page.count(look.SHIELD) == page.count('class="logo-tile"') >= 1, name
        assert look.SLATE in page, name  # the left half in dark


def test_the_logo_is_the_websites():
    site = (ROOT / "website" / "assets" / "logo.svg").read_text(encoding="utf-8")
    assert re.findall(r' d="([^"]+)"', site) == re.findall(r' d="([^"]+)"', look.SHIELD)
    assert re.findall(r'fill="(#[0-9A-F]{6})"', site) == re.findall(
        r'fill="(#[0-9A-F]{6})"', look.SHIELD)
    assert start_page.LOGO == look.SHIELD


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
    start = look.TOKENS.index(':root[data-theme="dark"]' if theme == "dark" else ":root {")
    block = look.TOKENS[start:look.TOKENS.index("}", start)]
    return dict(re.findall(r"--([\w-]+): (#[0-9A-Fa-f]{6})", block))


def test_light_by_default_and_dark_only_by_the_switch():
    for name, page in _new().items():
        assert "<html lang=\"en\">" in page, name  # no theme set: light
        assert "prefers-color-scheme" not in page and "invert(" not in page, name
        assert look.THEME_FIRST in page and look.SWITCH in page, name
        assert page.index(look.THEME_FIRST) < page.index("<style>"), name  # before drawing
    assert look.THEME_FIRST.startswith("try {") and '"jk-theme"' in look.THEME_FIRST
    assert 'aria-label="Dark mode" aria-pressed="false"' in look.SWITCH


def test_the_colours_are_the_websites():
    light, dark = _tokens("light"), _tokens("dark")
    assert (light["paper"], light["sheet"], light["ink"], light["ink-3"], light["rule"],
            light["btn"]) == ("#FFFFFF", "#F5F5F5", "#000000", "#4D4D4D", "#D9D9D9", "#000000")
    assert (dark["paper"], dark["sheet"], dark["ink"], dark["btn"]) == (
        "#000000", "#111111", "#FFFFFF", "#FFFFFF")
    for theme in (light, dark):  # green and red only on Pass and Fail, and the accent lines
        greens = {k for k, v in theme.items() if v in ("#1F6B4A", "#6FCF9B", "#10B981",
                                                       "#3D9A6A", "#1E7A4E")}
        assert greens <= {"pass", "pass-line", "pass-on", "pass-kbd-line", "mark-line"}, greens


def _luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (text, background, at least): every text colour on the backgrounds it sits on
PAIRS = [(text, ground, 4.5) for text in ("ink", "ink-2", "ink-3", "accent")
         for ground in ("paper", "sheet", "tint", "tint-2", "chip")] + [
    ("on-btn", "btn", 4.5), ("pass", "pass-bg", 4.5), ("fail", "fail-bg", 4.5),
    ("pass", "pass-dot", 4.5), ("fail", "fail-dot", 4.5), ("pass", "sheet", 4.5),
    ("fail", "sheet", 4.5), ("amber", "sheet", 4.5), ("amber", "amber-bg", 4.5),
    ("blue", "sheet", 4.5), ("blue", "blue-bg", 4.5), ("ink-3", "accent-bg", 4.5),
    ("focus", "paper", 3), ("focus", "sheet", 3)]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_in_both_themes(theme):
    colours = _tokens(theme)
    for text, ground, least in PAIRS:
        assert _contrast(colours[text], colours[ground]) >= least, (theme, text, ground)
    for pressed in ("pass-on", "fail-on"):  # white text on a pressed button
        assert _contrast("#FFFFFF", colours[pressed]) >= 4.5, (theme, pressed)


def test_focus_rings_sit_on_the_edge_and_nothing_is_focused_on_load():
    for name, page in _new().items():
        style = page.split("<style>")[1].split("</style>")[0]
        assert re.findall(r"outline-offset: ([^;]+);", style) == ["0"], name
        assert ":focus-visible { outline: 2px solid var(--focus); outline-offset: 0; }" in style
        assert "autofocus" not in page, name


# The marking page --------------------------------------------------------------------------

def test_fail_and_pass_look_the_same_but_for_their_colour():
    style = mark_page.STYLE
    fails = re.findall(r"^(\.dec\.fail[^{]*)\{([^}]*)\}", style, re.MULTILINE)
    passes = re.findall(r"^(\.dec\.pass[^{]*)\{([^}]*)\}", style, re.MULTILINE)
    assert len(fails) == len(passes) >= 4
    for (fs, fb), (ps, pb) in zip(fails, passes, strict=True):
        assert fs.replace("fail", "x") == ps.replace("pass", "x")
        assert fb.replace("fail", "x") == pb.replace("pass", "x")
    page = _marking()
    assert 'class="dec fail" id="fail"' in page and 'class="dec pass" id="pass"' in page
    assert page.index('id="fail"') < page.index('id="pass"')


def test_the_marking_page_shows_nothing_the_judge_decided():
    text = _text(_marking()).lower()
    for word in ("agree", "kappa", "tpr", "tnr", "%", "reason", "correct"):
        assert word not in text, word
    assert "judge's grade hidden" in text and "grade stays hidden" in text


def test_the_marking_page_words():
    text = _text(_marking())
    for line in ("Judge: openai:gpt-4.1-mini", "Eval tool: promptfoo", "Toward your first result",
                 "The question", "The answer", "Fail ←", "Pass →", "Skip this one S",
                 "Judge's rule", mark_page.HOW, "Shortcuts", "Saved locally as you go",
                 "To come back later, run judgekeeper mark.", mark_page.TITLE,
                 "You'll see one answer at a time.", "Start marking"):
        assert line in text, line
    assert "support bot" not in text  # one source, the same on every answer: no tag
    for gone in ("Your app's answer", "customer", "of 40", "Resume with", "drag"):
        assert gone not in text, gone


def test_the_welcome_box_is_a_modal_over_the_whole_window():
    page = _marking()
    assert ('<div class="intro" id="intro-box" role="dialog" aria-modal="true" '
            'aria-labelledby="intro-title" aria-describedby="intro-text" tabindex="-1">') in page
    assert '<div class="scrim" id="intro" hidden>' in page  # opened by the script
    assert ".scrim { position: fixed; inset: 0;" in page
    assert "max-width: calc(100vw - 32px)" in page
    assert '<button type="button" class="go" id="intro-ok">Start marking</button>' in page


def test_the_marking_page_has_one_h1_real_headings_and_a_progressbar():
    page = _marking()
    assert page.count("<h1") == 1 and '<h1 id="q-text">' in page
    for heading in ("Answers", "Judge's rule", "Shortcuts"):
        assert re.search(rf"<h2[^>]*>{re.escape(heading)}</h2>", page), heading
    assert ('role="progressbar" aria-label="Toward your first result" aria-valuemin="0" '
            'aria-valuemax="100"') in page
    assert '"marked Pass"' in page and '"marked Fail"' in page and '"not marked"' in page


def test_a_narrow_window_moves_the_rule_above_the_buttons_and_the_list_last():
    page = _marking()
    narrow = page.split("@media (max-width: 600px) {", 2)[2]
    assert ".answers { order: 3;" in narrow and ".rail { order: 2; }" in narrow
    assert ".answer .rail { order: 0;" in narrow  # inside the card: in its place, above the buttons
    assert 'card.insertBefore(rail, $("decide"))' in page
    assert ".top .left { grid-column: 1 / -1; grid-row: 2; }" in page  # chips under the logo


def test_the_rule_is_text_and_folds_when_long():
    page = mark_page.label_page(None, "<b>Be kind</b> & fair")
    assert "&lt;b&gt;Be kind&lt;/b&gt; &amp; fair" in page and "<b>Be kind</b>" not in page
    assert '<blockquote class="folded" id="rule">' in page
    assert 'id="fold" aria-controls="rule" aria-expanded="false" hidden>Full rule' in page
    assert 'id="rule"' not in mark_page.label_page(None, None)


def test_text_from_results_can_never_hold_a_server_name():
    page = mark_page.label_page(None, "__DATA__ __TOKEN__", "judgekeeper mark __NONCE__",
                                model="__TOKEN__", tool="__DATA__")
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
