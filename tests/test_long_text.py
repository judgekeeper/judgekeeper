"""Long, real text on the marking page, the result page and report.html: one screen to mark
on, the question and the answer by their length, fenced code kept as text, right-to-left text,
rows folded to 4 lines, reasons folded behind "Add a reason", rule parts by whole step and the
kept-aside count as a footnote."""

from __future__ import annotations

import re

import pytest

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
                            ["SPAN", "code-wrap", "<script>alert(1)</script>\nx = 1", None],
                            ["#TEXT", "", "Run it.", None]]
    assert got["html"] == ""  # text only: nothing is parsed as HTML
    inner = _run("""
      var w = ids["a-text"].children[1], c = w.children[0];
      console.log(JSON.stringify([c.tagName, c.className, c.getAttribute("dir"), c.innerHTML]));""",
                 data=_one("Q?", answer))
    assert inner == ["CODE", "block", "ltr", ""]


def test_fenced_code_has_a_thin_scrollbar_always_shown_and_a_fade_to_the_right():
    style = mark_page.STYLE
    assert ".answer code.block::-webkit-scrollbar { height: 8px; }" in style
    assert "@supports not selector(::-webkit-scrollbar)" in style
    assert "scrollbar-width: thin;" in style
    assert ".code-wrap.more-right::after" in style
    got = _run("""
      var w = ids["a-text"].children[0], c = w.children[0];
      c.scrollWidth = 900; c.clientWidth = 400; c.scrollLeft = 0; c.fire("scroll");
      var more = w.className;
      c.scrollLeft = 500; c.fire("scroll");
      console.log(JSON.stringify([more, w.className]));""",
               data=_one("Q?", "```\nx = 1\n```"))
    assert "more-right" in got[0].split() and "more-right" not in got[1].split()


def test_an_unclosed_fence_and_inline_backticks_stay_plain_text():
    for answer in ("Run `python fee.py` now.", "```\nnever closed"):
        got = _run("""
          console.log(JSON.stringify(ids["a-text"].children.map(function (c) {
            return c.tagName; })));""", data=_one("Q?", answer))
        assert got == ["#TEXT"]


PARTS = """
  console.log(JSON.stringify(ids["a-text"].children.map(function (c) {
    return [c.tagName, c.textContent]; })));"""


@pytest.mark.parametrize("answer, parts", [
    # not a language: the rest of the line is the box's first line; ``` inside a line is text
    ("```<img src=x onerror=alert(1)>\ncode ``` inside\n```\nAfter.\n```",
     [["SPAN", "<img src=x onerror=alert(1)>\ncode ``` inside"], ["#TEXT", "After.\n```"]]),
    ("```c++\nint x;\n```", [["SPAN", "int x;"]]),  # one word: its language, not shown
    ("``` python \nx = 1\n   ```  \nDone.", [["SPAN", "x = 1"], ["#TEXT", "Done."]]),
    ("```js two words\nx\n```", [["SPAN", "js two words\nx"]]),
    ("A ```x``` b\n```\nnever closed", [["#TEXT", "A ```x``` b\n```\nnever closed"]]),
    ("Text ```\ncode\n```", [["#TEXT", "Text ```\ncode\n```"]]),  # opens only at a line's start
    ("```\na\n```\nMid\n```\nb\n```",
     [["SPAN", "a"], ["#TEXT", "Mid"], ["SPAN", "b"]]),
    ("```\r\na\r\n```\r\nEnd", [["SPAN", "a\r"], ["#TEXT", "End"]]),
])
def test_a_fence_opens_at_a_line_start_and_closes_on_a_line_of_its_own(answer, parts):
    assert _run(PARTS, data=_one("Q?", answer)) == parts


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


_BOXES = _AREA + """
  var qBox = document.getElementById("q-text"), ruleBox = document.getElementById("rule");
  ruleBox.hidden = true;
  qBox.clientHeight = 100; qBox.scrollHeight = 900;
  ruleBox.clientHeight = 100; ruleBox.scrollHeight = 700;
"""


def test_an_open_question_or_rule_takes_focus_and_its_own_scroll_keys():
    got = _run("""
      var q = ids["q-text"], rule = ids["rule"], area = ids["a-text"].parentNode;
      var shut = [q.getAttribute("tabindex"), rule.getAttribute("tabindex")];
      ids["q-more"].fire("click");  // the question, open
      var open = q.getAttribute("tabindex");
      q.focus();
      var keys = ["PageDown", " ", "ArrowDown", "End"].map(function (k) {
        var e = key(k); return [q.scrollTop, e.defaultPrevented]; });
      key("Home"); var home = q.scrollTop;
      key(" ", {shiftKey: true}); var upAtTop = q.scrollTop;
      ids["rule-btn"].fire("click");  // the rule, open: the question shuts
      var qShut = [q.getAttribute("tabindex"), document.activeElement === q];
      rule.focus(); key("PageDown"); key("ArrowDown"); var ruleTop = rule.scrollTop;
      key("End"); var ruleEnd = rule.scrollTop;
      var answerTop = area.scrollTop;
      key("ArrowRight"); await settle();  // the mark keys still work
      console.log(JSON.stringify({shut: shut, open: open, keys: keys, home: home, upAtTop: upAtTop,
        qShut: qShut, ruleTab: rule.getAttribute("tabindex"), ruleTop: ruleTop, ruleEnd: ruleEnd,
        answerTop: answerTop, sent: sent.length}));""", data=_one("Q " * 100), before=_BOXES)
    assert got["shut"] == [None, None] and got["open"] == "0"
    tops = [t for t, _ in got["keys"]]
    assert all(p for _, p in got["keys"])
    assert 0 < tops[0] < tops[1] < tops[2] < tops[3] == 800  # End: the bottom of the question
    assert got["home"] == 0 and got["upAtTop"] == 0
    assert got["qShut"] == [None, False]  # shut: no tab stop, and focus back on the answer
    assert got["ruleTab"] == "0" and 0 < got["ruleTop"] < got["ruleEnd"] == 600
    assert got["answerTop"] == 0  # the answer did not move
    assert got["sent"] == 1
    # its focus ring: thin, outside the text, with no fade over it
    assert (".question.long.open:focus-visible, .rule:focus-visible { -webkit-mask-image: none;\n"
            "    mask-image: none; outline: 1px solid var(--muted); outline-offset: 4px; }"
            in _laptop())


def test_home_and_end_move_the_answer_by_default():
    got = _run("""
      var area = ids["a-text"].parentNode;
      key("End"); var end = area.scrollTop; key("Home");
      console.log(JSON.stringify([end, area.scrollTop]));""", before=_AREA)
    assert got == [2600, 0]


def _laptop() -> str:
    return mark_page.STYLE.split("@media (min-width: 761px) {", 1)[1].split("\n}\n", 1)[0]


def test_the_page_is_one_screen_on_a_laptop_and_the_answer_always_has_room():
    laptop = _laptop()
    assert "html, body { height: 100%; overflow: hidden; }" in laptop
    cap = "max-height: min(calc((100vh - 72px) * .3), 28vh)"
    assert laptop.count(cap) == 2  # the question shown all, and the rule
    # the answer keeps 35% of the main area, the question and the rule give way
    assert ".a-scroll { flex: 1 1 0; min-height: calc((100vh - 72px) * .35 - 30px);" in laptop
    assert ".row-q { flex: 0 1 auto; min-height: 0;" in laptop
    assert "@media (max-width: 760px) {" in mark_page.STYLE  # the phone's CSS, as it was
    short = mark_page.STYLE.split("@media (min-width: 761px) and (max-height: 800px) {", 1)[1]
    assert ".actions { padding-top: 12px; padding-bottom: 8px; }" in short and ".btn { height: 44px; }" in short
    page = mark_page.label_page("bot", "judgekeeper mark")
    assert ('<div class="label">Answer</div><div class="a-scroll" id="a-scroll">'
            '<p class="answer" id="a-text" dir="auto"></p></div>') in page


def test_a_short_heading_has_room_for_one_line():
    assert ".question:not(.long) { max-width: 75ch; }" in _laptop()


def test_the_rule_and_the_whole_question_are_never_open_together():
    got = _run("""
      ids["q-text"].scrollHeight = 500; ids["q-text"].clientHeight = 100;
      ids["q-more"].fire("click");
      var before = ids["q-text"].className;
      ids["rule-btn"].fire("click");
      var rule = [ids["q-text"].className, ids["rule"].hidden, ids["q-more"].textContent];
      ids["q-more"].fire("click");
      console.log(JSON.stringify({before: before, rule: rule,
        again: [ids["q-text"].className, ids["rule"].hidden,
                ids["rule-btn"].textContent]}));""",
               data=_one("Q " * 100), before='document.getElementById("rule").hidden = true;')
    assert "open" in got["before"].split()
    assert "open" not in got["rule"][0].split() and got["rule"][1:] == [False, "Show all"]
    assert "open" in got["again"][0].split() and got["again"][1:] == [True, "Show the rule"]


def test_the_opened_question_fades_while_there_is_more_below():
    assert ".question.long.open.more-below," in _laptop()
    got = _run("""
      var q = ids["q-text"]; q.scrollHeight = 500; q.clientHeight = 100;
      ids["q-more"].fire("click");
      var more = q.className;
      q.scrollTop = 400; q.fire("scroll");
      console.log(JSON.stringify([more, q.className]));""", data=_one("Q " * 100))
    assert "more-below" in got[0].split() and "more-below" not in got[1].split()


CONTEXT = ("Context:\n" + "Pets in the cabin cost $125 each way. " * 30
           + "\n\nA missing bag must be reported within 24 hours.\n\n"
           + "Question: How long do I have to report a missing bag?")
HEAD_TAIL = """
  function parts(e) { return e.children.map(function (c) { return [c.className, c.textContent]; }); }
  var side = ids["queue"].children[0].children[0].children.filter(function (c) {
    return c.className === "q"; })[0];
  var folded = parts(ids["q-text"]);
  ids["q-more"].fire("click");
  console.log(JSON.stringify({folded: folded, more: ids["q-more"].hidden,
    open: ids["q-text"].textContent, openParts: parts(ids["q-text"]), side: side.textContent}));"""


def test_a_question_at_the_end_of_a_long_field_shows_its_start_and_its_end():
    got = _run(HEAD_TAIL, data=_one(CONTEXT))
    head, gap, tail = got["folded"]
    assert head[0] == "q-head" and head[1].startswith("Context:\nPets in the cabin")
    assert gap == ["q-gap", "…"]
    assert tail == ["q-tail", "Question: How long do I have to report a missing bag?"]
    # in order, nothing moved, nothing lost; folded, a blank line is not one of the 2 lines
    assert head[1] + "\n\n" + tail[1] == CONTEXT.replace("\n\nA missing", "\nA missing")
    assert got["more"] is False
    # Show all: everything, in order; the question at its end stays in view until reached
    assert got["open"] == CONTEXT
    start, end = CONTEXT.rsplit("\n\n", 1)
    assert got["openParts"] == [["q-start", start + "\n\n"], ["q-end", end]]
    assert ".question.open .q-end { position: sticky; bottom: 0;" in _laptop()
    # the list's title is the question itself, without its label
    assert got["side"] == "How long do I have to report a missing bag?"


def test_a_long_field_that_does_not_end_with_a_question_folds_as_before():
    got = _run(HEAD_TAIL, data=_one("Policy:\n" + "Bags are free. " * 40))
    assert got["folded"] == []  # plain text, 4 lines, then Show all
    assert got["side"] == "Bags are free. " * 40


def test_field_names_are_small_labels_like_the_others():
    style = mark_page.STYLE
    assert (".question .field-name { display: block; font-size: 11px; font-weight: 600; "
            "letter-spacing: .1em;\n  text-transform: uppercase; color: var(--faint);") in style
    assert (".label { font-size: 11px; font-weight: 600; letter-spacing: .1em; "
            "text-transform: uppercase; color: var(--faint);") in style
    assert ".field-name { font-family" not in style  # one font, one tracking


def test_text_is_never_split_into_fields_by_its_name_lines():
    chat = ("system: Be kind.\nnote: refunds take 7 days\nuser: Hi\nassistant: Hello\n"
            "user: Where is my refund?")
    for text in (chat, "question: If my bag is late?\nsystem: You are kind.",
                 "Context:\nfoo\n\nQuestion: bar?"):
        assert start_label.question_view(text) == text
        assert start_label.question_view({"question": text}) == text
    # named fields come from the reader as data: a value is never split again
    shown = start_label.question_view({"question": chat, "language": "en"})
    assert shown == [["question", chat], ["language", "en"]]


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


def test_a_split_that_cant_be_used_shows_no_footnote_but_one_plain_line():
    r = _result(*NOT_GATE_TNR)
    for live in (False, True):
        html = (report_page.page(r, back="/?token=t" if live else None,
                                 fixing={"mistakes": [], "split_unknown": True}))
        assert "kept aside to test" not in html and 'class="group' not in html
        assert ('<p class="add-why">judgekeeper can\'t tell which answers are kept aside: run '
                '<code>judgekeeper fix</code> to see why.</p>') in html.replace("&#x27;", "'")
    plain = report_page.page(r, fixing={"mistakes": []})  # a split that was read: none kept
    assert "can't tell which" not in plain.replace("&#x27;", "'")


def test_a_group_with_none_shown_is_left_out_but_still_counted():
    r = _result(*NOT_GATE_TNR)
    c = report_page.counts(r)
    html = _html(_mistakes(c["easy"], 0))
    assert 'id="g-strict"' not in html and "said Fail (0" not in html
    assert f"* {c['strict']} more are kept aside to test a new rule fairly." in html


OPEN_ROW = ('<button type="button" class="open-row" aria-expanded="false" hidden>Show all'
            '</button>')


def test_rows_fold_to_four_lines_with_one_show_all_per_row():
    html = _html(_mistakes(2, 1))
    assert html.count(f'<td colspan="3" class="why-cell"><p class="row-foot">{OPEN_ROW}</p>'
                      "</td></tr>") == 3
    style = report_page.STYLE
    laptop = style.split("@media (min-width: 721px) {", 1)[1].split("\n}\n", 1)[0]
    assert "max-height: calc(4 * 1.55em);" in laptop and "line-height: 1.55;" in laptop
    assert "line-clamp" not in style  # a fade, never "…" after a full stop
    assert "grid-template-columns: 28fr 44fr 28fr;" in laptop
    assert ".tbl tr[data-open] td[data-label] { max-height: none; overflow: visible; }" in laptop
    assert "Show less" in report_page.SCRIPT and "open-row" in report_page.SCRIPT
    assert ".open-row[hidden] + .dot { display: none; }" in style


def test_a_question_at_the_end_of_a_long_field_folds_to_its_start_and_its_end_in_rows():
    m = {**_mistakes(1, 0)[0], "question": CONTEXT}
    html = _html([m])
    cell = re.search(r'<td data-label="Question" class="ht">(.*?)</td>', html, re.DOTALL)[1]
    start, end = CONTEXT.rsplit("\n\n", 1)
    peek = "Context:\n" + ("Pets in the cabin cost $125 each way. " * 30)[:300]
    assert cell == (f'<span class="q-peek" aria-hidden="true">{peek}</span>'
                    '<span class="q-gap" aria-hidden="true">…</span>'
                    f'<span class="q-full">{start}\n\n</span><span class="q-end">{end}</span>')
    laptop = report_page.STYLE.split("@media (min-width: 721px) {", 1)[1].split("\n}\n", 1)[0]
    assert ".tbl td.ht { max-height: calc(5 * 1.55em); }" in laptop
    assert 'td.classList.contains("ht")' in report_page.SCRIPT  # always "Show all"
    plain = _html([{**_mistakes(1, 0)[0], "question": "Policy:\n" + "Bags are free. " * 40}])
    assert 'class="ht"' not in plain  # no question at the end: 4 lines, as before


def test_the_foot_line_sits_12px_under_the_text_on_both_pages():
    style = report_page.STYLE
    assert ".row-foot, .why-line { margin: 12px 0 0; }" in style
    assert "td.why-cell { padding-top: 8px; }" not in style  # no second margin
    assert ".row-foot > .open-row" not in style and ".why-line > .open-row" not in style


def test_a_rule_part_in_the_reason_line_is_cut_at_60_characters():
    long = ("Determine whether the Actual Output sounds confident and does not refuse to help, "
            "and mark it Fail when it is rude")
    why = {"reasons": [], "rule_parts": [2], "note": ""}
    html = _html([_with_reason(why)], live=True, parts=["Be polite", long])
    cut = reasons.short(long, reasons.SAID_CHARS)
    assert reasons.SAID_CHARS == 60 and len(cut) <= 60 and cut.endswith("…")
    line = re.search(r'<p class="why-line">.*?</p>', html)[0]
    assert (f'<span class="said-text" title="Your reason: rule part 2 (\u201c{long}\u201d)">'
            f"Your reason: rule part 2 (\u201c{cut}\u201d)</span>") in line
    chip = re.search(r'<button[^>]*data-part="2"[^>]*>', html)[0]
    assert f'data-said="rule part 2 (\u201c{cut}\u201d)"' in chip
    assert f'data-whole="rule part 2 (\u201c{long}\u201d)"' in chip
    assert "data-whole" in report_page.REASONS_SCRIPT and "said.title" in report_page.REASONS_SCRIPT
    report = _html([_with_reason(why)], parts=["Be polite", long])
    assert (f'<span class="said" title="Your reason: rule part 2 (\u201c{long}\u201d)">'
            f"Your reason: rule part 2 (\u201c{cut}\u201d)</span>") in report


def test_the_group_link_says_how_many_it_shows():
    html = _html(_mistakes(7, 1))
    assert 'data-n="4" aria-controls="t-easy">Show 4 more</button>' in html
    assert '"Show " + b.getAttribute("data-n") + " more"' in report_page.SCRIPT


def test_the_verdict_heading_wraps_evenly():
    assert "text-wrap: balance;" in report_page.STYLE.split(".verdict h1 {", 1)[1].split("}")[0]
    html = _html([])
    assert ('<h1 id="verdict-h" class="needs">Your <span class="term">LLM-as-a-judge</span> '
            "needs work.</h1>") in html  # a line never breaks inside the term
    assert ".verdict h1 .term { white-space: nowrap; }" in report_page.STYLE


def test_a_many_field_question_shows_its_field_names_as_labels():
    m = {**_mistakes(1, 0)[0], "fields": [["question", "Is it late?"], ["system", "Be kind."]],
         "question": "question: Is it late?\nsystem: Be kind."}
    html = _html([m])
    assert ('<td data-label="Question"><span class="fname">question</span>Is it late?\n'
            '<span class="fname">system</span>Be kind.</td>') in html


def test_one_disagreement_reads_in_the_singular():
    assert (start_label.say_why_run(1, "judgekeeper mark") ==
            "Tell judgekeeper why you disagree on this one: run `judgekeeper mark`.")
    assert (start_label.say_why_run(3, "judgekeeper mark") ==
            "Tell judgekeeper why you disagree on these 3: run `judgekeeper mark`.")
    assert reasons.parts_left_out_line(1) == "“Other…” covers the other part of your rule."
    assert reasons.parts_left_out_line(2) == "“Other…” covers the 2 other parts of your rule."


def test_report_html_folds_rows_and_has_no_reason_buttons():
    html = _html(_mistakes(2, 1))
    assert 'class="open-row"' in html and "Add a reason" not in html
    assert 'class="why"' not in html


def _with_reason(why: dict) -> dict:
    return {**_mistakes(1, 0)[0], "id": "x1", "final": "fail", "why": why}


def test_live_rows_ask_for_a_reason_behind_a_small_button():
    html = _html([_with_reason({})], live=True, parts=["Be polite", "Never promise refunds"])
    line = re.search(r'<p class="why-line">.*?</p>', html)[0]
    assert line.startswith(f'<p class="why-line">{OPEN_ROW}<span class="dot" aria-hidden="true">')
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
    assert text == ("Show all · Your reason: it has a wrong fact; rule part 2 (“Never promise "
                    "refunds”); “Wrong year” · Change")
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


_REASONS_DOM = r"""
var NOW = 0, timers = [], sent = [];
Date.now = function () { return NOW; };
function setTimeout(f, ms) { timers.push({f: f, at: NOW + ms, live: true}); return timers.length; }
function clearTimeout(n) { if (n && timers[n - 1]) { timers[n - 1].live = false; } }
function wait(ms) {  // time passes: the timers due run
  NOW += ms;
  timers.forEach(function (t) { if (t.live && t.at <= NOW) { t.live = false; t.f(); } });
}
function El(tag) { this.tagName = tag; this.attrs = {}; this.listeners = {}; this.hidden = false;
  this.textContent = ""; this.value = ""; this.firstChild = null; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (t, f) { this.listeners[t] = f; };
El.prototype.fire = function (t, extra) {
  var e = Object.assign({key: "", preventDefault: function () { this.prevented = true; }},
                        extra || {});
  if (this.listeners[t]) { this.listeners[t](e); } return e; };
El.prototype.focus = function () {};
El.prototype.appendChild = function () {};
var parts = {".saved": new El("p"), "input": new El("input"), ".other": new El("button"),
  ".mark-part": new El("button"), ".clear-part": new El("button"),
  ".add-reason": new El("button"), ".said-now": new El("span"), ".said-text": new El("span")};
var box = new El("div"), cell = new El("td");
box.attrs = {"data-answer": "a-0", "data-id": "x1", "data-len": "10", "data-spans": "[]"};
box.querySelector = function (s) { return parts[s]; };
box.querySelectorAll = function () { return []; };
var document = {getElementById: function () { return cell; },
  querySelectorAll: function () { return [box]; }, addEventListener: function () {},
  createRange: function () {}};
var location = {search: "?token=t"};
var window = {getSelection: function () { return {rangeCount: 0}; },
  fetch: function (url, o) { sent.push(JSON.parse(o.body).note);
    return {then: function () {}}; }};
var input = parts["input"];
function type(text) { input.value = text; input.fire("input"); }
"""


def test_the_other_box_saves_when_typing_pauses_on_enter_and_on_leaving():
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node to run the page's script")
    scenario = """
      var steps = [];
      type("G"); wait(400); type("Gi"); wait(1000); type("Giv"); wait(1400);
      steps.push(sent.slice());  // still typing: nothing saved
      wait(100); steps.push(sent.slice());  // 1.5 s after the last letter
      type("Gives a"); input.fire("keydown", {key: "Enter"}); steps.push(sent.slice());
      wait(2000); steps.push(sent.length);  // Enter saved it: no second save
      type("Gives a price"); input.fire("blur"); steps.push(sent.slice());
      input.fire("blur"); steps.push(sent.length);  // nothing new: no save
      console.log(JSON.stringify(steps));"""
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "page.js"
        script.write_text(_REASONS_DOM + report_page.REASONS_SCRIPT + scenario, encoding="utf-8")
        out = subprocess.run([node, str(script)], check=True, capture_output=True, text=True,
                             encoding="utf-8", timeout=60)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == [[], ["Giv"], ["Giv", "Gives a"], 2, ["Giv", "Gives a", "Gives a price"], 3]


def test_the_group_link_says_show_less():
    assert '"Show less" : "Show " + b.getAttribute("data-n") + " more"' in report_page.SCRIPT
    assert "Show fewer" not in report_page.SCRIPT


def test_an_emoji_keeps_its_variation_selector_and_other_hidden_marks_still_go():
    from judgekeeper import redact

    for text in ("Fly \u2708\ufe0f today", "\u2764\ufe0e", "Press 1\ufe0f\u20e3", "\u2708\ufe0f\u200d"):
        assert redact.visible(text) == text
    assert redact.visible("\u2708\ufe0f\ufe0f") == "\u2708\ufe0f"  # one only
    for hidden in ("\u200b", "\u202e", "\u2066", "\u200e", "\ufeff", "\U000e0041"):
        assert redact.visible(f"\u2708\ufe0f{hidden}x") == "\u2708\ufe0fx"
        assert redact.visible(f"\u2708{hidden}\ufe0fx") == "\u2708x"  # its own mark only
    # not after a letter or a sign: a name can't hide one
    assert redact.visible("openai:\ufe0fgpt\ufe0e") == "openai:gpt"
    assert redact.printable("Fly \u2708\ufe0f \u200d") == "Fly \u2708 "  # the terminal: as now
    page = start_label.result_html(_result(*NOT_GATE_TNR), fixing={"mistakes": [
        {"id": "a", "judge": "pass", "final": "fail", "question": "\u2708\ufe0f?",
         "answer": "Yes \u2708\ufe0f\u202e", "reason": "ok", "why": None}]})
    assert "Yes \u2708\ufe0f<" in page and "\u202e" not in page


# More details -------------------------------------------------------------------------------

def test_weighted_estimates_say_why_they_differ_from_the_counts():
    caption = "<caption>How often your LLM-as-a-judge agrees with you (estimates)"
    html = start_label.result_html(_result(*NOT_GATE_TNR))  # 80 of 200 marked
    assert (caption + '<span class="weighted">Worked out for all 200 answers, not only the 80 '
            "you marked, so they can differ from the counts above.</span></caption>") in html
    every = start_label.result_html(_result(40, 40, 40, 22, 40, 2))  # every answer marked
    assert caption + "</caption>" in every and 'class="weighted"' not in every
    assert ".panel caption .weighted { display: block;" in report_page.STYLE
