"""Short wording on the result page, report.html and the marking page, and one look shared
with the website: counts, lists, the score, next steps and the marking page."""

from __future__ import annotations

import re

from judgekeeper import look, mark_page, report_page, start_label
from tests.start_projects import unwrapped
from tests.test_mark_page_script import _run
from tests.test_product_pages import (
    GATE,
    NOT_GATE_TNR,
    TOO_EARLY,
    TOO_FEW,
    _mistakes,
    _part,
    _result,
    _text,
)

KEPT = " kept aside on purpose, so a new rule can be tested on answers you haven't looked at again."
SHORT = " kept aside to test your fix."  # the result page's words


def _page(result=NOT_GATE_TNR, mistakes=(1, 0), live=False, **fixing) -> str:
    fixing = {"mistakes": _mistakes(*mistakes), **fixing}
    if live:
        return report_page.page(_result(*result), back="/?token=t", fixing=fixing)
    return start_label.result_html(_result(*result), fixing=fixing)


# The counts -----------------------------------------------------------------------------------

def test_the_counts_say_it_and_show_where_it_disagrees_in_amber():
    text = _text(_page())
    assert "You passed 24 answers. Of these, your LLM-as-a-judge passed 22 and failed 2." in text
    assert "You failed 56 answers. Of these, your LLM-as-a-judge passed 18 and failed 38." in text
    assert "Of those" not in text and "It passed" not in text
    counts = _part(_page(), '<div class="cnts">', "</div>")
    assert counts.count('class="mono off"') == 2
    assert 'failed <span class="mono off">2</span>' in counts
    assert 'passed <span class="mono off">18</span>' in counts
    assert ".off { color: var(--amber); }" in report_page.STYLE


def test_a_count_of_none_against_you_stays_plain():
    counts = _part(start_label.result_html(_result(100, 100, 40, 40, 40, 40)),
                   '<div class="cnts">', "</div>")
    assert "off" not in counts


def test_before_a_result_the_counts_are_your_own_with_no_amber():
    counts = _part(start_label.result_html(_result(*TOO_FEW)), '<div class="cnts">', "</div>")
    assert counts and "Of these" not in counts and "off" not in counts


# The lists ------------------------------------------------------------------------------------

def test_no_line_asks_for_reasons_above_the_lists():
    assert "fix` uses them" not in _page(live=True) and "uses them." not in _text(
        _page(live=True))


def test_group_headings_are_text_coloured_with_no_count():
    html = _page(mistakes=(3, 1))
    assert 'said <span class="w-pass">Pass</span></h2>' in html
    assert 'said <span class="w-fail">Fail</span></h2>' in html
    assert not re.search(r"said (Pass|Fail) \(\d+\)", html)
    rule = report_page.STYLE.split(".sh h2, .gh h2, .h-head h2 {", 1)[1].split("}", 1)[0]
    assert "amber" not in rule and "color: var(--text)" in rule


def test_the_kept_aside_count_is_under_its_own_group():
    # 18 you failed that it passed: 3 shown, 15 kept aside; 2 the other way: 1 shown, 1 kept
    html = _page(mistakes=(3, 1))
    easy, strict = _part(html, 'id="g-easy"'), _part(html, 'id="g-strict"')
    assert '<p class="kept">15 more are' + SHORT + "</p></div>" in easy
    assert '<p class="kept">1 more is' + SHORT + "</p></div>" in strict
    assert easy.index("kept aside") < easy.index("<table")
    assert "*" not in _text(html) and "a new rule fairly" not in html


def test_kept_aside_with_no_list_comes_after_the_lists():
    html = _page(mistakes=(2, 0))  # the 2 failed by it, passed by you: all kept aside
    assert 'id="g-strict"' not in html
    after = html.split('id="g-easy"', 1)[1].split("</section>", 1)[1]
    assert '<p class="sec slim">2 more disagreements are' + SHORT + "</p>" in after.split(
        'id="next-h"', 1)[0]
    assert KEPT not in html and html.count(SHORT) == 2


def test_show_more_is_a_row_under_the_table():
    html = _page(mistakes=(6, 0))
    group = _part(html, 'id="g-easy"')
    assert group.index("</table>") < group.index('class="more"')
    assert "Show 3 more</button>" in group
    assert ".more { display: block; width: 100%;" in report_page.STYLE


def test_the_third_column_is_its_reason_and_headers_use_the_small_label():
    html = _page(mistakes=(1, 1))
    assert html.count('<th scope="col">Its reason</th>') == 2
    assert "Why your LLM-as-a-judge" not in html
    th = report_page.STYLE.split(".tbl th {", 1)[1].split("}", 1)[0]
    for part in ("font-family: var(--sans)", "font-size: 12px", "font-weight: 600",
                 "letter-spacing: .1em", "color: var(--faint)"):
        assert part in th


PARTS = ["Read the input.", ("Assess the tone of the Actual Output: confirm it is polite and "
         "friendly, and that it does not contain rude, dismissive, or condescending language.")]


def _reasoned(live: bool) -> str:
    m = {**_mistakes(1, 0)[0], "id": "a1",
         "why": {"reasons": ["wrong_fact"], "rule_parts": [2], "note": "", "spans": []}}
    fixing = {"mistakes": [m], "parts": PARTS}
    if live:
        return report_page.page(_result(*NOT_GATE_TNR), back="/?token=t", fixing=fixing)
    return start_label.result_html(_result(*NOT_GATE_TNR), fixing=fixing)


def test_a_saved_reason_names_a_rule_part_by_its_number():
    for live in (True, False):
        html = _reasoned(live)
        assert "Your reason: <b" in html and "it has a wrong fact; rule part 2</b>" in html
        assert "rule part 2 (" not in _text(html)
        assert PARTS[1] in html  # the whole part in a title


def test_the_row_foot_has_its_button_first_and_show_all_last_with_no_dots():
    foot = _part(_reasoned(True), '<p class="why-line">', "</p>")
    assert foot.startswith('<button type="button" class="add-reason sbtn"')
    assert ">Change</button>" in foot
    assert foot.rstrip().endswith("Show more</button>") and "Show all" not in foot
    assert "·" not in _reasoned(True) and "·" not in _reasoned(False)
    assert ".sbtn { display: inline-flex; align-items: center; height: 32px;" in (
        report_page.STYLE)


def test_the_reason_box_asks_the_everyday_reasons_first_then_which_part():
    box = _part(_reasoned(True), '<div class="why-body"', '<div class="marked"')
    assert box.index("Why did you mark it Fail?") < box.index('class="saved"') < box.index(
        "data-reason=") < box.index("Which part of your rule?") < box.index("data-part=")
    assert "does this answer break" not in box and "get wrong?" not in box
    part = re.search(r'<button[^>]*data-part="2"[^>]*>.*?</button>', box)[0]
    assert 'class="part"' in part and '<span class="bx"' in part and '<span class="num">2</span>' in (
        part)
    assert ".chip { font-size: 14px; line-height: 1.35; padding: 7px 12px; border: 1px solid" in (
        report_page.STYLE)
    assert "border-radius: 4px" in report_page.STYLE.split(".chip {", 1)[1].split("}", 1)[0]


def test_opening_a_reason_box_opens_its_row():
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    import pytest

    from tests.test_long_text import _REASONS_DOM

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    scenario = """
      var row = new El("button"), clicks = 0, got = [];
      row.attrs["aria-expanded"] = "false";
      row.click = function () { clicks += 1; row.attrs["aria-expanded"] = "true"; };
      parts[".open-row"] = row;
      var add = parts[".add-reason"];
      add.fire("click"); got.push(clicks, cell.hidden === false);
      add.fire("click"); add.fire("click"); got.push(clicks);  // already open: not shut again
      row.attrs["aria-expanded"] = "false"; row.hidden = true;  // nothing cut: nothing to open
      add.fire("click"); add.fire("click"); got.push(clicks);
      console.log(JSON.stringify(got));"""
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "page.js"
        script.write_text(_REASONS_DOM + report_page.REASONS_SCRIPT + scenario, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [1, True, 1, 1]


# The score -----------------------------------------------------------------------------------

def test_the_score_heading_is_a_bar_with_no_line_under_it():
    html = _page()  # 80 of 200 marked
    assert "More details" not in html and "<details class=\"details" not in html
    assert ('<div class="sh"><h2 id="nums-h">How often your <span class="term">LLM-as-a-judge'
            '</span> agrees with you</h2></div>') in html
    assert "Estimated for all" not in html
    assert "Worked out for all" not in html and "(estimates)" not in html


def test_with_every_answer_marked_the_heading_stands_alone_too():
    html = start_label.result_html(_result(40, 40, 40, 38, 40, 22))
    head = _part(html, '<div class="sh">', "</div>")
    assert _text(f"<body>{head}") == "How often your LLM-as-a-judge agrees with you"


def test_too_early_shows_the_counts_and_the_numbers_but_no_what_next():
    html = start_label.result_html(_result(*TOO_EARLY))
    assert 'id="nums-h"' in html and 'class="cnts"' in html and 'id="next-h"' not in html


def test_good_enough_has_no_fix_command():
    html = start_label.result_html(_result(*GATE))
    assert 'class="cmd"' not in html and 'id="nums-h"' in html
    assert '<section class="sec next-box" aria-labelledby="next-h">' in html


# What next ------------------------------------------------------------------------------------

def test_what_next_has_the_websites_command_box():
    html = _page()
    fix = unwrapped(_part(html, '<section class="sec next-box"'))
    assert "<p>Next, in your project folder:</p>" in fix and "in your terminal" not in fix
    assert "marked-answers.csv" not in fix and "In your project folder" not in fix
    assert '<div class="cmd"><code>judgekeeper fix</code><button type="button" class="copy" ' \
           'data-copy aria-label="Copy command: judgekeeper fix">' in fix
    assert '<svg class="i-copy"' in fix and '<svg class="i-tick"' in fix
    assert '<span class="copied" aria-live="polite"></span>' in fix
    style = report_page.STYLE
    assert ".cmd code::before { content: \"$\"; margin-right: .6em; color: var(--green); }" in style
    assert ".cmd .copy.done { color: var(--green); }" in style
    assert "border-radius: 8px" in style.split("\n.cmd {", 1)[1].split("}", 1)[0]


def test_the_copy_script_is_the_websites_and_clears_its_selection():
    s = report_page.SCRIPT
    assert 'querySelectorAll("[data-copy]")' in s
    assert 'said.textContent = ok ? "Copied" : "Copy failed";' in s  # only when it worked
    assert 'document.execCommand("copy")' in s
    assert s.index('document.execCommand("copy")') < s.rindex("removeAllRanges()")
    assert "1500" in s
    for html, csp in ((_page(), report_page.CSP), (_page(live=True), report_page.LIVE_CSP)):
        assert f'content="{csp}"' in html
        for script in re.findall(r"<script>(.*?)</script>", html, re.DOTALL):
            assert look.script_hash(script) in csp


def test_report_html_keeps_one_closing_line():
    text = _text(_page(mistakes=(2, 0)))
    assert "To tell judgekeeper why you disagree on" in text
    assert "uses your reasons" not in text and "Optional: tell judgekeeper" not in text


def test_no_page_says_reasons_are_optional():
    """The live page's "Optional: tell judgekeeper why..." line is cut; the reason box's own
    question asks."""
    for mistakes in ((2, 1), (0, 0)):
        html = unwrapped(_page(mistakes=mistakes, live=True))
        assert "Optional: tell judgekeeper" not in html and 'class="add-why"' not in html


def test_the_term_stays_on_one_line_everywhere():
    assert ".term { white-space: nowrap; }" in report_page.STYLE
    html = _page()
    plain = re.sub(r'<span class="term">LLM-as-a-judge</span>', "", html.split("<body>")[1])
    plain = re.sub(r"<[^>]*>", "", re.sub(r"<script.*?</script>", "", plain, flags=re.DOTALL))
    assert "LLM-as-a-judge" not in plain.replace("LLM-AS-A-JUDGE", "")


def test_the_result_page_focus_ring_is_the_websites_in_the_text_colour():
    assert (":focus-visible { outline: 2px solid var(--text); outline-offset: 3px; "
            "border-radius: 4px; }") in report_page.STYLE


# The marking page -----------------------------------------------------------------------------

def test_no_not_marked_yet_and_no_legend():
    page = mark_page.label_page("support bot", "judgekeeper mark")
    assert "Not marked yet" not in page and 'class="legend"' not in page
    got = _run("""console.log(JSON.stringify(ids["ans-status"].textContent));""")
    assert got == ""


def test_the_footer_says_to_come_back():
    page = unwrapped(mark_page.label_page("support bot", "judgekeeper mark"))
    assert '<p class="foot">To come back: <code>judgekeeper mark</code>' in page
    assert "Come back any time" not in page


def test_skip_and_undo_are_centred_under_the_buttons():
    style = mark_page.STYLE
    assert ".sub { display: flex; align-items: center; justify-content: center; padding: 0 40px 6px; }" in style
    assert ("  .row, .actions, .status, .foot, .sub { padding-right: max(40px, "
            "calc(100cqw - 1160px)); }") in style


def test_only_the_three_standard_subdivision_flags_keep_their_tags():
    from judgekeeper import redact

    def flag(code: str) -> str:
        return "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in code) + "\U000E007F"

    for code in ("gbeng", "gbsct", "gbwls"):
        assert redact.visible(f"Go {flag(code)}!") == f"Go {flag(code)}!"
    for code in ("usca", "us06", "gbnir", "frbre", "abc"):
        assert redact.visible(f"Go {flag(code)}!") == "Go \U0001F3F4!"


# The website: its faint colour, its focus ring and its copy ------------------------------------

def _site(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "website" / "assets" / name).read_text(
        encoding="utf-8")


def test_the_website_shares_the_products_faint_colour_and_text_coloured_ring():
    css = _site("style.css")
    assert "--faint: #767c86;" in css and "#585e68" not in css
    assert (":focus-visible { outline: 2px solid var(--fg); outline-offset: 3px; "
            "border-radius: 4px; }") in css


def test_the_website_copy_clears_its_selection_after_the_fallback():
    js = _site("site.js")
    select = js.split("function select() {", 1)[1].split("\n      }", 1)[0]
    assert select.index('document.execCommand("copy")') < select.rindex("removeAllRanges()")


def test_the_what_next_copy_box_keeps_one_width_when_copied():
    # in What next the box fills its column (up to 640px), so "Copied" fits inside it
    style = report_page.STYLE
    assert ".nx-split .cmd { min-width: 0; width: 100%; max-width: 640px; }" in style
    assert ".nx-split .cmd code { font-size: 18px; padding: 18px 22px; }" in style
    assert ".nx-split .cmd .copy { padding: 0 22px; }" in style
    assert "min-width: min(380px, 100%)" in report_page.STYLE.split("\n.cmd {", 1)[1].split("}", 1)[0]


def test_every_website_page_loads_the_new_site_js_and_style_css():
    from pathlib import Path

    site = Path(__file__).resolve().parents[1] / "website"
    for page in [*site.glob("*.html"), site / "errors" / "404.html"]:
        refs = re.findall(r"assets/(?:style\.css|site\.js)\?v=(\d+)", page.read_text(encoding="utf-8"))
        assert refs and set(refs) == {"29"}, (page.name, refs)
    # the browser check's script has its own version number
    assert "assets/freecheck.js?v=19" in (site / "check.html").read_text(encoding="utf-8")


def test_a_reason_ending_in_inspects_grade_line_is_shown_without_it():
    """Inspect's model-graded scorers end the reason with "GRADE: C": the page keeps the
    LLM-as-a-judge's grade hidden, so the reason shown leaves that line out."""
    from tests.test_product_pages import MISTAKE

    mistakes = [{**MISTAKE, "question": "easy 0", "reason": "It answers the question.\n\nGRADE: C"},
                {**MISTAKE, "question": "easy 1", "reason": "GRADE: C"}]
    for live in (False, True):
        fixing = {"mistakes": mistakes}
        html = (report_page.page(_result(*NOT_GATE_TNR), back="/?token=t", fixing=fixing)
                if live else start_label.result_html(_result(*NOT_GATE_TNR), fixing=fixing))
        assert "GRADE: C" not in html
        assert "It answers the question.</td>" in html and "No reason given</td>" in html
