"""A shown number is never rounded to 100% or 0% unless it is exactly that, a range counts as
no range only when it has no width at all, and the bracket that says why there is no range is
true for the answers the result is on."""

import pytest

from judgekeeper import front, report_page, targets
from judgekeeper.start_label import side_sentence

# A large judge-pass group, all but one answer marked: 499 of 500 it passed, 2 of the 20 it
# failed are a Pass to the person. The TPR range is 0.002 points wide.
NEAR = {"tpr": 0.9960159362549801, "tpr_interval": [0.9959948949661799, 0.9960159362549801],
        "tnr": 1.0, "tnr_interval": [0.8722064504176722, 1.0],
        "kappa": 0.9453781512605044, "kappa_interval": [0.8812461963268031, 0.9453781512605044],
        "left": 1, "labels": {"correct": 501, "wrong": 18},
        "groups": {"pass": {"pool": 500, "labeled": 499, "correct": 499},
                   "fail": {"pool": 20, "labeled": 20, "correct": 2}}}

# The first batch fully marked, a newer batch of 50 answers not marked at all.
ONE_BATCH = {"tpr": 0.6933333333333334, "tpr_interval": [0.6933333333333334, 0.6933333333333334],
             "tnr": 0.7266666666666666, "tnr_interval": [0.7266666666666666, 0.7266666666666666],
             "kappa": 0.42, "kappa_interval": [0.42, 0.42], "left": 50,
             "batches": {"counted": [1], "of": 2, "answers": 300, "waiting": 50},
             "labels": {"correct": 150, "wrong": 150},
             "groups": {"pass": {"pool": 145, "labeled": 145, "correct": 104},
                        "fail": {"pool": 155, "labeled": 155, "correct": 46}}}


def test_only_a_range_of_no_width_is_exact():
    assert targets.width_word([0.5, 0.5]) == "exact"
    assert targets.width_word([0.1 + 0.2, 0.3]) == "exact"  # float noise is no width
    assert targets.width_word(NEAR["tpr_interval"]) is None
    assert targets.width_word([0.40, 0.40004]) is None


def test_a_very_narrow_range_is_almost_exact_not_every_answer():
    why = report_page.why_for(NEAR, "tpr")
    assert report_page.estimate(NEAR["tpr"], NEAR["tpr_interval"], why) == (
        "about 99.6% (almost exact)", "–")


def test_the_narrow_range_reads_the_same_on_the_terminal_and_the_page():
    lines = front.estimate_lines(NEAR)
    assert "  When you say Pass, it also says Pass: about 99.6% (almost exact)" in lines
    assert not any("100% (you marked" in line for line in lines)
    html = report_page._main_lines(NEAR)
    assert '<td data-label="Estimate">about 99.6% (almost exact)</td>' in html, html
    assert side_sentence("tpr", NEAR["tpr"], NEAR["tpr_interval"]) == (
        "You passed: your LLM-as-a-judge also passed about 99.6% (almost exact).")


@pytest.mark.parametrize(("value", "shown"), [
    (499 / 501, "99.6%"),
    (1.0, "100%"),
    (0.0, "0%"),
    (1 / 501, "0.2%"),
    (9995 / 10000, "99.95%"),
    (0.78, "78%"),
    (0.999996, "over 99.99%"),
    (0.000004, "under 0.01%"),
])
def test_an_exact_value_is_never_rounded_to_100_or_0(value, shown):
    why = report_page.EVERY_MARKED
    assert report_page.estimate(value, [value, value], why) == (f"{shown} ({why})", "–")
    assert side_sentence("tpr", value, [value, value], why) == (
        f"You passed: your LLM-as-a-judge also passed {shown} ({why}).")


@pytest.mark.parametrize(("value", "interval", "shown", "between"), [
    (0.996, [0.95, 1.0], "about 99.6%", "95% and 100%"),
    (0.004, [0.0, 0.05], "about 0.4%", "0% and 5%"),
    (1.0, [0.92, 1.0], "about 100%", "92% and 100%"),
    (0.8, [0.66, 0.93], "about 80%", "66% and 93%"),
])
def test_an_estimate_is_never_rounded_to_100_or_0(value, interval, shown, between):
    assert report_page.estimate(value, interval) == (shown, between)


def test_the_terminal_range_uses_the_same_decimals_as_the_page():
    """Never "about 99% (between 99% and 99%)" in the terminal."""
    assert side_sentence("tnr", 0.99251, [0.99122, 0.99292]) == (
        "You failed: your LLM-as-a-judge also failed about 99.3% (between 99.1% and 99.3%).")


def test_a_kappa_range_that_reads_the_same_is_almost_exact():
    r = {**NEAR, "kappa": 0.5, "kappa_interval": [0.4999, 0.5001]}
    assert '0.50 (almost exact)</td><td data-label="Between">–' in report_page._details(r)
    r = {**NEAR, "kappa": 0.5, "kappa_interval": [0.5, 0.5], "left": 0}
    assert "0.50 (you marked every answer)" in report_page._details(r)


def test_with_a_newer_batch_unmarked_the_bracket_names_the_answers_it_counts():
    why = {k: report_page.why_for(ONE_BATCH, k) for k in ("tpr", "tnr", "kappa")}
    assert why == {
        "tpr": "you marked every answer it failed in the 300 answers this result is on",
        "tnr": "you marked every answer it passed in the 300 answers this result is on",
        "kappa": "you marked every answer in the 300 answers this result is on"}
    lines = front.estimate_lines(ONE_BATCH)
    assert ("  When you say Pass, it also says Pass: 69% (you marked every answer it failed in "
            "the 300 answers this result is on)") in lines


def test_with_every_batch_counted_the_bracket_stays_short():
    r = {**ONE_BATCH, "batches": None}
    assert report_page.why_for(r, "tpr") == "you marked every answer it failed"
    r = {**ONE_BATCH, "batches": {"counted": [1, 2], "of": 2, "answers": 350, "waiting": 0}}
    assert report_page.why_for(r, "tpr") == "you marked every answer it failed"
