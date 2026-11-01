"""What the marking page and the result page are made from: the rule and the description
kept for the pages, how a question is shown, the status line the server sends, and a few
lines of the result. The pages themselves are tested in test_product_pages.py.
"""

from __future__ import annotations

import re

import pytest

from judgekeeper import start, start_label, weighted
from tests.start_projects import RUBRIC, promptfoo_project, split


def _ws(root, n_pass=20, n_fail=12, **kwargs):
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    return start_label.prepare(start.find_judge(root), say=lambda line: None)


def _flat(html: str) -> str:
    return " ".join(html.split())


# What `start` keeps for the pages --------------------------------------------------------

def test_the_full_rule_and_the_description_are_kept(tmp_path):
    promptfoo_project(tmp_path, split(20, 12))
    found = start.find_judge(tmp_path)
    assert found.rule == RUBRIC
    assert found.description == "support bot"
    data = start_label.prepare(found, say=lambda line: None).data()
    assert data["rule"] == RUBRIC and data["description"] == "support bot"


def test_without_a_description_there_is_none(tmp_path):
    promptfoo_project(tmp_path, split(20, 12), description=None)
    assert start.find_judge(tmp_path).description is None


def test_the_rule_is_the_whole_text_and_the_rubric_line_its_first_line():
    assert start.rule_text("Criteria: Be kind.\nAnd brief.") == "Be kind.\nAnd brief."
    assert start.rule_text("  ") is None and start.rule_text(None) is None
    assert start.rubric_line("Criteria: Be kind.\nAnd brief.") == "Be kind."
    long = "x" * 100
    assert start.rule_text(long) == long
    assert start.rubric_line(long).endswith("…")


# The labeling page -----------------------------------------------------------------------


def test_the_rule_card_holds_no_reason_from_the_judge(tmp_path):
    page = start_label.page_template(_ws(tmp_path).data())
    assert not re.search(r"reason \d", page)


# How the question is shown ---------------------------------------------------------------

def test_a_plain_question_is_shown_as_written():
    assert start_label.question_view("How do I sleep?\nThanks.") == "How do I sleep?\nThanks."
    assert start_label.question_view(None) == ""


def test_one_named_value_shows_only_the_value():
    assert start_label.question_view({"question": "How do I sleep?"}) == "How do I sleep?"
    assert start_label.question_view({"n": 3}) == "3"


def test_several_named_values_show_each_name_and_value():
    assert start_label.question_view({"question": "Hi?", "user": "Sam", "n": [1, 2]}) == [
        ["question", "Hi?"], ["user", "Sam"], ["n", "[1, 2]"]]


def test_a_script_in_the_question_stays_text(tmp_path):
    shown = start_label.question_view({"q": "<script>alert(1)</script>"})
    assert shown == "<script>alert(1)</script>"  # data: the page sets it with textContent
    assert "textContent" in start_label.page_template({})


def test_the_page_shows_the_question_without_its_name(tmp_path):
    ws = _ws(tmp_path)
    items = start_label.StartSession(ws).state()["items"]
    assert all(re.fullmatch(r"Question \d+\?", it["input"]) for it in items)


# The status line -------------------------------------------------------------------------

# (pool passes, pool fails, marked in the pass group, of them Pass, in the fail group, of
# them Pass). No target and no number is ever on the page: only what to do.
FEW = "Mark a few more answers to see your result."
FIRST = "Your first numbers are in. Too early to tell: keep marking."


@pytest.mark.parametrize("counts, text, first, ready", [
    ((100, 100, 0, 0, 0, 0), FEW, False, False),
    ((100, 100, 22, 14, 22, 0), FEW, False, False),  # 14 marked Pass
    ((100, 100, 15, 12, 15, 3), FEW, False, False),  # 15 of each kind, 15 marks per group
    ((100, 100, 20, 16, 20, 4), FIRST, True, False),  # too early to tell
    ((100, 100, 20, 19, 20, 1), FIRST, True, False),  # the 99% ends still reach under 80%
    ((100, 100, 50, 48, 50, 2), "Your result is ready.", True, True),  # good enough
])
def test_the_status_line(counts, text, first, ready):
    status = start_label.progress_status(*counts)
    assert (status["text"], status["first"], status["ready"]) == (text, first, ready)


def test_the_page_shows_the_status_the_server_sends():
    page = start_label.page_template({})
    assert "STATUS" not in page and "least < ROUGH" not in page  # no statistics in the page
    assert "summary.status" in page and "data.status" in page


# The result page -------------------------------------------------------------------------

def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


CHECK = (100, 100, 15, 12, 15, 3)          # both ranges reach below 80%, and are wide


# Marking more ----------------------------------------------------------------------------

def test_with_answers_left_it_still_offers_to_mark_more():
    html = _flat(start_label.result_html(_result(*CHECK, left=7), back="/?token=t"))
    assert '<a href="/?token=t">Mark more answers to get a result.</a>' in html
