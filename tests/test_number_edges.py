"""The numbers' edge cases: a rate of exactly 0.90 in floating point, a judge that passes (or
fails) every answer, a range narrower than one point, and a group of the judge with nothing
counted when it is asked again."""

from __future__ import annotations

from judgekeeper import report_page, start_label, targets


def test_a_range_ending_exactly_on_the_bar_reaches_it():
    low = 0.4 * 2  # 0.8, worked out as 0.8000000000000002 one way, 0.7999999999999999 another
    end = 0.7 + 0.1
    assert end < 0.8 and round(end, 9) == 0.8
    assert targets.side([end, 0.95]) == "yes"  # green, not amber
    assert targets.side([low, 0.95]) == "yes"
    assert targets.side([0.7999, 0.95]) == "cant_tell"


def test_a_judge_that_passes_every_answer_has_exact_numbers():
    assert report_page.estimate(1.0, [1.0, 1.0]) == ("100%", "100% and 100%")  # no "about"
    assert report_page.estimate(0.0, [0.0, 0.0]) == ("0%", "0% and 0%")
    check = targets.check(25, 25, [1.0, 1.0], [0.0, 0.0])
    assert check == {"check": "rough", "wide": {}}  # never "reliable" from no width at all
    r = {"check": "rough", "wide": {}, "tpr_interval": [1.0, 1.0], "tnr_interval": [0.0, 0.0]}
    assert start_label.status_line(r) == "You can see your result now."


def test_a_range_never_shows_as_one_point():
    assert report_page.estimate(0.999, [0.997, 1.0]) == ("about 100%", "99.7% and 100.0%")
    assert report_page.estimate(0.8, [0.66, 0.93]) == ("about 80%", "66% and 93%")
