"""Long, real text on the marking page, the result page and report.html: one screen to mark
on, the question and the answer by their length, fenced code kept as text, right-to-left text,
rows folded to 4 lines, reasons folded behind "Add a reason", rule parts by whole step and the
kept-aside count as a footnote."""

from __future__ import annotations

import re

from judgekeeper import mark_page, reasons, report_page, start_label
from tests.test_mark_page_script import _data, _run
from tests.test_product_pages import NOT_GATE_TNR, _mistakes, _result

# The marking page --------------------------------------------------------------------------


def _one(value, output: str = "A.") -> dict:
    data = _data(1)
    data["items"][0].update(input=value, output=output)
    return data


CLASSES = """
  console.log(JSON.stringify({q: ids["q-text"].className, a: ids["a-text"].className}));"""


def test_a_short_one_line_question_keeps_the_big_heading():
    got = _run(CLASSES, data=_one("Can I bring a 9 kg carry-on?"))
    assert got["q"].split() == ["question"]


def test_a_long_question_or_several_fields_read_at_normal_size():
    long = "You are the support assistant. " * 6  # over 140 characters
    assert "long" in _run(CLASSES, data=_one(long))["q"].split()
    assert "long" in _run(CLASSES, data=_one("Two lines\nof question"))["q"].split()
    fields = [["question", "Q?"], ["system", "Be kind."]]
    assert "long" in _run(CLASSES, data=_one(fields))["q"].split()


def test_the_answer_size_follows_its_length():
    def size(n: int) -> list[str]:
        return _run(CLASSES, data=_one("Q?", "x" * n))["a"].split()
    assert size(300) == ["answer"]
    assert size(301) == ["answer", "a-mid"] and size(1500) == ["answer", "a-mid"]
    assert size(1501) == ["answer", "a-long"]


def test_the_next_answer_gets_its_own_size_and_question_style():
    data = _data(2)
    data["items"][0].update(input="Q " * 100, output="x" * 2000)
    data["items"][1].update(input="Short?", output="Yes.")
    got = _run("""
      var before = [ids["q-text"].className, ids["a-text"].className];
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({before: before,
        after: [ids["q-text"].className, ids["a-text"].className]}));""", data=data)
    assert "long" in got["before"][0].split() and "a-long" in got["before"][1]
    assert got["after"] == ["question", "answer"]


def test_fenced_code_shows_in_a_box_as_text_and_the_rest_stays_text():
    answer = "Here:\n\n```python\n<script>alert(1)</script>\nx = 1\n```\n\nRun it."
    got = _run("""
      var a = ids["a-text"];
      console.log(JSON.stringify({parts: a.children.map(function (c) {
        return [c.tagName, c.className, c.textContent, c.getAttribute("dir")]; }),
        html: a.innerHTML}));""", data=_one("Q?", answer))
    assert got["parts"] == [["#TEXT", "", "Here:", None],
                            ["CODE", "block", "<script>alert(1)</script>\nx = 1", "ltr"],
                            ["#TEXT", "", "Run it.", None]]
    assert got["html"] == ""  # text only: nothing is parsed as HTML


def test_an_unclosed_fence_and_inline_backticks_stay_plain_text():
    for answer in ("Run `python fee.py` now.", "```\nnever closed"):
        got = _run("""
          console.log(JSON.stringify(ids["a-text"].children.map(function (c) {
            return c.tagName; })));""", data=_one("Q?", answer))
        assert got == ["#TEXT"]


def test_question_and_answer_read_in_their_own_direction():
    page = mark_page.label_page("bot", "judgekeeper mark")
    assert '<h1 class="question" id="q-text" dir="auto">' in page
    assert '<p class="answer" id="a-text" dir="auto">' in page
    got = _run("""
      console.log(JSON.stringify(ids["q-text"].children.map(function (c) {
        return c.getAttribute("dir"); })));""",
               data=_one([["question", "حقيبتي مفقودة"], ["context", "Policy"]]))
    assert got == ["auto", "auto", "auto", "auto"]


_AREA = """
  var area = new El("div"); area.appendChild(document.getElementById("a-text"));
  area.clientHeight = 400; area.scrollHeight = 3000;
"""


def test_space_page_down_and_the_arrows_scroll_the_answer_and_marks_still_work():
    got = _run("""
      var area = ids["a-text"].parentNode, at = [];
      [[" ", {}], [" ", {}], [" ", {shiftKey: true}], ["PageDown", {}], ["PageUp", {}],
       ["ArrowDown", {}], ["ArrowDown", {repeat: true}], ["ArrowUp", {}]].forEach(function (k) {
        var e = key(k[0], k[1]); at.push([area.scrollTop, e.defaultPrevented]); });
      key("ArrowRight"); await settle();
      console.log(JSON.stringify({at: at, sent: sent.length, top: area.scrollTop}));""",
               before=_AREA)
    tops = [t for t, _ in got["at"]]
    assert all(p for _, p in got["at"])
    assert tops[0] > 0 and tops[1] > tops[0] and tops[2] == tops[0]
    assert tops[3] > tops[2] and tops[4] == tops[2]
    assert tops[5] > tops[4] and tops[6] > tops[5] and tops[7] < tops[6]  # held: keeps going
    assert got["sent"] == 1 and got["top"] == 0  # marked; the next answer starts at the top


def test_scroll_keys_leave_a_focused_button_and_the_welcome_box_alone():
    got = _run("""
      var b = new El("button");
      var e = key(" ", {target: b});
      console.log(JSON.stringify({prevented: e.defaultPrevented,
        top: ids["a-text"].parentNode.scrollTop}));""", before=_AREA)
    assert got == {"prevented": False, "top": 0}


def test_the_page_is_one_screen_on_a_laptop():
    style = mark_page.STYLE
    laptop = style.split("@media (min-width: 761px) {", 1)[1].split("\n}\n", 1)[0]
    assert "html, body { height: 100%; overflow: hidden; }" in laptop
    assert ".row-a { flex: 1 1 auto; min-height: 0; overflow: auto;" in laptop
    assert "max-height: calc((100vh - 72px) * .4)" in laptop  # the question, shown all
    assert "max-height: calc((100vh - 72px) * .35)" in laptop  # the rule
    assert "@media (max-width: 760px) {" in style  # the phone's CSS, as it was


def test_show_all_on_a_long_question():
    page = mark_page.label_page("bot", "judgekeeper mark")
    assert ('<button type="button" class="quiet q-more" id="q-more" aria-expanded="false" '
            'aria-controls="q-text" hidden>Show all</button>') in page
    got = _run("""
      ids["q-text"].scrollHeight = 500; ids["q-text"].clientHeight = 100;
      ids["q-more"].fire("click");
      var open = [ids["q-text"].className, ids["q-more"].textContent,
                  ids["q-more"].getAttribute("aria-expanded")];
      ids["q-more"].fire("click");
      console.log(JSON.stringify({open: open, shut: [ids["q-text"].className,
        ids["q-more"].textContent]}));""", data=_one("Q " * 100))
    assert "open" in got["open"][0].split() and got["open"][1:] == ["Show less", "true"]
    assert "open" not in got["shut"][0].split() and got["shut"][1] == "Show all"


def test_the_question_like_field_comes_first():
    shown = start_label.question_view({"system": "Be kind. " * 40, "context": "Doc",
                                       "language": "en", "user_question": "Q?"})
    assert [k for k, _ in shown] == ["user_question", "language", "system", "context"]
    shown = start_label.question_view({"system_prompt": "S", "query": "Q?"})
    assert [k for k, _ in shown] == ["query", "system_prompt"]
    shown = start_label.question_view({"b": "x", "a": "y"})  # nothing to move: as written
    assert [k for k, _ in shown] == ["b", "a"]


# The result page and report.html -----------------------------------------------------------

def _html(mistakes: list[dict], live: bool = False, parts=None, own=None) -> str:
    fixing = {"mistakes": mistakes, "parts": parts or [], "own": own or []}
    r = _result(*NOT_GATE_TNR)
    if live:
        return report_page.page(r, back="/?token=t", fixing=fixing)
    return start_label.result_html(r, fixing=fixing)


def test_the_heading_counts_the_rows_and_a_footnote_counts_those_kept_aside():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    html = _html(_mistakes(c["easy"] - 4, c["strict"] - 1))
    assert (f'<h2 id="g-easy">You said Fail, your LLM-as-a-judge said Pass ({c["easy"] - 4})'
            "</h2>") in html
    assert "shown;" not in html
    assert '<p class="note kept">* 5 more are kept aside to test a new rule fairly.</p>' in html
    assert html.index('id="g-strict"') < html.index("* 5 more")  # under the lists
    one = _html(_mistakes(c["easy"] - 1, c["strict"]))
    assert "* 1 more is kept aside to test a new rule fairly." in one
    none = _html(_mistakes(c["easy"], c["strict"]))
    assert "note kept" not in none and "more are kept aside" not in none


def test_a_group_with_none_shown_is_left_out_but_still_counted():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    html = _html(_mistakes(c["easy"], 0))
    assert 'id="g-strict"' not in html and "said Fail (0" not in html
    assert f"* {c['strict']} more are kept aside to test a new rule fairly." in html


def test_rows_fold_to_four_lines_with_one_show_all_per_row():
    html = _html(_mistakes(2, 1))
    rows = re.findall(r'<td class="row-more"><button type="button" class="open-row" '
                      r'aria-expanded="false" hidden>Show all</button></td>', html)
    assert len(rows) == 3
    style = report_page.STYLE
    laptop = style.split("@media (min-width: 721px) {", 1)[1].split("\n}\n", 1)[0]
    assert "-webkit-line-clamp: 4;" in laptop and "line-height: 1.55;" in laptop
    assert "grid-template-columns: 28fr 44fr 28fr;" in laptop
    assert ".tbl tr[data-open] td[data-label] { display: block; }" in laptop
    assert "Show less" in report_page.SCRIPT and "open-row" in report_page.SCRIPT


def test_report_html_folds_rows_and_has_no_reason_buttons():
    html = _html(_mistakes(2, 1))
    assert 'class="open-row"' in html and "Add a reason" not in html
    assert 'class="why"' not in html


def _with_reason(why: dict) -> dict:
    return {**_mistakes(1, 0)[0], "id": "x1", "final": "fail", "why": why}


def test_live_rows_ask_for_a_reason_behind_a_small_button():
    html = _html([_with_reason({})], live=True, parts=["Be polite", "Never promise refunds"])
    line = re.search(r'<p class="why-line">.*?</p>', html)[0]
    assert ('<button type="button" class="add-reason" aria-expanded="false" '
            'aria-controls="wb-easy-0">Add a reason</button>') in line
    assert '<span class="said-now" hidden>' in line
    assert '<div class="why-body" id="wb-easy-0" hidden>' in html
    body = html.split('id="wb-easy-0" hidden>', 1)[1]
    assert "Why did you mark it Fail?" in body and 'data-part="1"' in body  # the panel, as was


def test_a_saved_reason_shows_in_one_line_with_change():
    why = {"reasons": ["wrong_fact"], "rule_parts": [2], "note": "Wrong year"}
    html = _html([_with_reason(why)], live=True, parts=["Be polite", "Never promise refunds"])
    line = re.search(r'<p class="why-line">.*?</p>', html)[0]
    text = re.sub(r"<[^>]+>", "", line)
    assert text == ("Your reason: it has a wrong fact; rule part 2 (“Never promise refunds”); "
                    "“Wrong year” · Change")
    assert "Change" in line and "Add a reason" not in line


def test_rule_part_buttons_show_90_characters_and_the_whole_part_on_hover():
    long = ("Determine whether the Actual Output sounds confident and does not refuse to help, "
            "and mark it Fail when it is rude")
    html = _html([_with_reason({})], live=True, parts=["Be polite", long])
    chip = re.search(r'<button[^>]*data-part="2"[^>]*>(.*?)</button>', html)
    assert chip[1] == "2. " + reasons.short(long) and chip[1].endswith("…")
    assert f'title="{long}"' in chip[0]
    first = re.search(r'<button[^>]*data-part="1"[^>]*>', html)[0]
    assert "title=" not in first  # whole already


def test_the_reasons_script_updates_the_line_after_a_save():
    s = report_page.REASONS_SCRIPT
    assert "Your reason: " in s and "Change" in s and "Add a reason" in s
    assert "data-said" in s
