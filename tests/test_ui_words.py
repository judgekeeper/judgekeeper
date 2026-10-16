"""The words a person reads on judgekeeper's pages: the keys on the marking page, and a scan
of every page's text for the words that must not be there: "Correct", "Wrong", "label"
and "verdict" (the person reads Pass, Fail, mark and decision; the saved files keep their
names)."""

from __future__ import annotations

import re
from html import unescape

import pytest

from judgekeeper import judge_check, start_label, start_page

BANNED = ("Correct", "Wrong")  # as words a person reads; "correct" in a rule is their text
BANNED_ANY_CASE = ("label", "verdict")


# The keys ---------------------------------------------------------------------------------

def test_the_labeling_page_keys_are_the_arrows_and_the_old_digits():
    page = start_page.label_page(None, None)
    assert '{arrowright: "pass", arrowleft: "fail", "1": "pass", "2": "fail"}' in page
    assert "Fail <kbd>←</kbd>" in page and "Pass <kbd>→</kbd>" in page
    assert "<kbd>1</kbd>" not in page and "<kbd>2</kbd>" not in page  # shown: the arrows only
    assert page.index('id="fail"') < page.index('id="pass"')  # Fail on the left


# No banned word on any page ---------------------------------------------------------------

def visible_text(html: str) -> str:
    """The page's text as a person reads it: no styles, scripts or tags; plus the titles
    and hints (title, aria-label, placeholder) that show on hover or to a screen reader."""
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL)
    hints = re.findall(r'(?:title|aria-label|placeholder)="([^"]*)"', html)
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(" ".join([text, *hints]))


def _scan(text: str, where: str) -> None:
    for word in BANNED:
        assert not re.search(rf"\b{word}\b", text), (where, word)
    for word in BANNED_ANY_CASE:
        assert word not in text.lower(), (where, word)


def _result(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, **extra):
    from judgekeeper import weighted

    r = start_label.describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    r.update(made_at="2026-10-05T12:00:00Z", **extra)
    return r


def test_the_templates_hold_no_banned_word():
    _scan(visible_text(start_page.label_page("support bot", "Be kind.")), "label")


@pytest.mark.parametrize("counts", [(100, 100, 20, 19, 20, 1), (100, 100, 20, 17, 20, 2),
                                    (100, 100, 25, 17, 25, 1), (100, 100, 10, 9, 10, 1),
                                    (900, 100, 25, 24, 25, 1)])
def test_the_result_page_holds_no_banned_word(counts):
    check = {"answers": 57, "error": 5, "unreadable": 2, "reason_says_opposite": 1,
             "tool": "promptfoo", "tool_counted_as": "fail"}
    r = _result(*counts, judge_check=check, left=7,
                judge={"tool": "promptfoo", "metric": "llm-rubric", "rule": "Be kind.",
                       "results_files": ["results.json"], "results_date": "2026-10-05 05:30"})
    for back in (None, "/?token=t"):
        _scan(visible_text(start_label.result_html(r, back)), f"result {counts} {back}")


def test_the_lines_the_server_sends_hold_no_banned_word():
    texts = [*start_label.VERDICTS.values(),
             start_label.status_line({"check": "rough", "wide": {"tpr": 0.4, "tnr": None}}),
             judge_check.LIST_LINE, start_label.ALL_LABELED,
             *judge_check.page_lines({"answers": 57, "error": 5, "unreadable": 2, "empty": 1,
                                      "nothing_checked": 4, "empty_answer_passed": 3,
                                      "reason_says_opposite": 2, "same_decision": "pass",
                                      "tool": "promptfoo", "tool_counted_as": "fail"})]
    _scan("\n".join(texts), "server lines")
