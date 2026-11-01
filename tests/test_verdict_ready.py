"""The coloured verdict and "ready" (good enough / needs work), when the person can look after
every mark.

- The verdict uses wider ranges (the middle 99% of the same draws) than the ones on screen
  (96%), so a lucky streak seen on one look among many can't decide it.
- No rule shows or hides a range by its width: every number has its range from the first
  result, and the disagreements are listed whenever there is a result.
- "Ready" means a coloured verdict: the marking page's pop-up, its line under the bar, its
  link and the status line all follow it.
No test calls an AI API.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import report_page, start_label, targets, weighted

FIRST_NUMBERS = "Your first numbers are in. Too early to tell: keep marking."


# The verdict uses the 99% ends ---------------------------------------------------------------

def test_the_verdict_uses_the_wider_ends():
    """A 96% low end of 0.81 with a 99% low end of 0.78: can't tell yet, not good enough."""
    r = {"check": "result", "tpr_interval": [0.81, 0.95], "tnr_interval": [0.85, 0.97],
         "tpr_verdict_interval": [0.78, 0.96], "tnr_verdict_interval": [0.83, 0.98]}
    assert start_label._level(r) == "check"
    r["tpr_verdict_interval"] = [0.80, 0.96]
    assert start_label._level(r) == "gate"


def test_the_99_ranges_hold_the_96_ones():
    out = weighted.corrected(8000, 2000, 30, 26, 30, 9)
    for key in ("tpr", "tnr"):
        lo96, hi96 = out[f"{key}_interval"]
        lo99, hi99 = out[f"{key}_verdict_interval"]
        assert lo99 < lo96 and hi99 >= hi96, key
    assert weighted.VERDICT_LEVEL == 0.99


def test_after_check_the_verdict_has_wider_ends_too():
    items = [("pass", "pass", "pass")] * 25 + [("pass", "fail", "pass")] * 3 + \
        [("fail", "fail", "fail")] * 24 + [("fail", "pass", "fail")] * 6
    out = weighted.general_strata(items, {"pass": 800, "fail": 200})
    for key in ("tpr", "tnr"):
        assert out[f"{key}_verdict_interval"][0] < out[f"{key}_interval"][0], key


# No width rule -------------------------------------------------------------------------------

def test_a_wide_range_is_no_longer_too_early():
    """A 45-point range still gets a verdict from where it lies: can't tell yet, or needs
    work when it is all below the bar."""
    assert targets.level([0.50, 0.95], [0.85, 0.95]) == "check"
    assert targets.level([0.30, 0.75], [0.85, 0.95]) == "not_gate"
    assert targets.level([None, None], [0.85, 0.95]) == "too_early"


@pytest.mark.parametrize("interval", [[0.4, 0.85], [0.6, 0.9], [0.7, 0.75]])
def test_only_exact_is_a_width_word(interval):
    assert targets.width_word(interval) is None
    assert targets.width_word([0.8, 0.8]) == "exact"


def test_a_wide_range_is_said_with_its_range():
    said = start_label.side_sentence("tnr", 0.61, [0.38, 0.83])
    assert said == "You failed: your LLM-as-a-judge also failed about 61% (between 38% and 83%)."
    assert start_label.side_sentence("tnr", None, [None, None]) == \
        "You failed: too early to tell."


def test_the_disagreements_show_whenever_there_is_a_result():
    r = {"check": "result", "verdict_level": "check"}
    assert report_page.shows_disagreements(r)
    assert not report_page.shows_disagreements({"check": "too_few", "verdict_level": None})


# Ready means a coloured verdict --------------------------------------------------------------

def _strata(n_pass, c_p, n_fail, c_f, pool=(8000, 2000)):
    return [(1, "pass", pool[0], n_pass, c_p), (1, "fail", pool[1], n_fail, c_f)]


def test_first_numbers_without_a_verdict_are_not_ready():
    """Enough marks, too early to tell: the first numbers are in, nothing pops up."""
    status = start_label.strata_status(_strata(20, 17, 20, 3, pool=(500, 500)))
    assert status["first"] and not status["ready"]
    assert status["text"] == FIRST_NUMBERS
    assert status["headline"] is None


def test_a_coloured_verdict_is_ready():
    status = start_label.strata_status(_strata(40, 20, 40, 25))  # TNR far under 80%
    assert status["first"] and status["ready"]
    assert status["text"] == "Your result is ready."
    assert status["headline"] == "Your LLM-as-a-judge needs work."


def test_too_few_marks_say_what_they_said():
    status = start_label.strata_status(_strata(10, 8, 10, 2))
    assert not status["first"] and not status["ready"]
    assert status["text"] == "Mark a few more answers to see your result."


def test_the_status_line_follows_the_verdict():
    assert start_label.status_line({"check": "result", "verdict_level": "gate"}) == \
        "Your result is ready."
    assert start_label.status_line({"check": "result", "verdict_level": "not_gate"}) == \
        "Your result is ready."
    for level in ("check", "too_early"):
        assert start_label.status_line({"check": "result", "verdict_level": level}) == \
            FIRST_NUMBERS


# Looking after every mark --------------------------------------------------------------------

def test_looking_after_every_mark_rarely_says_good_enough_for_a_judge_under_the_bar():
    """A person who stops at the first coloured verdict, looking after every 5 marks up to 200:
    the LLM-as-a-judge passes 80% of the answers, TPR 95%, TNR 79% (just under the bar).
    Marks come as the page offers them (15 + 15 first, then the pool's mix)."""
    rng = random.Random(20261031)
    pi, tpr, tnr = 0.8, 0.95, 0.79
    # the share Correct among the judge's passes (a) and fails (b) that give these rates
    p = (tnr - 1 + pi) / (tpr + tnr - 1)  # the real pass rate
    a, b = p * tpr / pi, p * (1 - tpr) / (1 - pi)
    runs, wrong = 200, 0
    for _ in range(runs):
        n_p = n_f = c_p = c_f = 0
        for m in range(1, 201):
            if m <= 30:
                in_pass = m <= 15
            else:
                in_pass = rng.random() < pi
            if in_pass:
                n_p += 1
                c_p += rng.random() < a
            else:
                n_f += 1
                c_f += rng.random() < b
            if m < 30 or m % 5:
                continue
            correct = c_p + c_f
            if min(correct, n_p + n_f - correct) < targets.ROUGH:
                continue
            out = weighted.corrected(8000, 2000, n_p, c_p, n_f, c_f, draws=1000)
            level = targets.level(out["tpr_verdict_interval"], out["tnr_verdict_interval"])
            if level in ("gate", "not_gate"):
                wrong += level == "gate"
                break
    assert wrong / runs < 0.04, wrong


def test_no_first_numbers_under_20_marks_in_a_group():
    """15 marked Pass and 15 Fail, but 19 marks among the answers the LLM-as-a-judge failed."""
    status = start_label.strata_status(_strata(30, 14, 19, 1))
    assert not status["first"] and status["text"] == "Mark a few more answers to see your result."
    assert start_label.strata_status(_strata(30, 14, 20, 1))["first"]
