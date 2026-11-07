"""The terminal result says kappa, as the result page's More details does.

Kappa never decides the result, so it stands apart from the lines the result uses, and `check`,
which reuses those lines, stays as it is.
"""

from __future__ import annotations

from judgekeeper import front, report_page
from judgekeeper.textio import wrap

SAYS = "Kappa (agreement beyond coincidence): {}. It never decides the result."


def test_a_kappa_with_a_range_says_about_and_its_ends():
    r = {"kappa": 0.128, "kappa_interval": [-0.092, 0.334], "left": 3}
    assert front.kappa_line(r) == SAYS.format("about 0.13 (between -0.09 and 0.33)")


def test_a_negative_kappa_keeps_its_sign_on_any_terminal():
    """A legacy Windows code page has no real minus sign: it would print "?0.05"."""
    r = {"kappa": -0.051, "kappa_interval": [-0.2, 0.1], "left": 3}
    line = front.kappa_line(r)
    assert line == SAYS.format("about -0.05 (between -0.20 and 0.10)")
    assert line.isascii()


def test_wrapping_never_splits_a_number_from_its_sign():
    r = {"kappa": -0.051, "kappa_interval": [-0.2, -0.01], "left": 3}
    words = " ".join(wrap(front.kappa_line(r))).split()
    assert "-0.20" in words and "-0.01)." in words


def test_with_every_answer_marked_it_has_no_range_and_says_why():
    r = {"kappa": 0.62, "kappa_interval": [0.62, 0.62], "left": 0}
    assert front.kappa_line(r) == SAYS.format("0.62 (you marked every answer)")


def test_a_range_too_narrow_to_write_shows_the_number_alone():
    r = {"kappa": 0.6201, "kappa_interval": [0.6200, 0.6204], "left": 3}
    assert front.kappa_line(r) == SAYS.format("0.62")


def test_no_kappa_reads_as_on_the_result_page():
    r = {"kappa": None, "kappa_interval": None, "left": 3}
    assert front.kappa_line(r) == SAYS.format("n/a")
    assert ">n/a<" in report_page._details(r)


def test_the_page_and_the_terminal_show_the_same_numbers():
    r = {"kappa": 0.128, "kappa_interval": [-0.092, 0.334], "left": 3}
    page = report_page._details(r)
    assert ">0.13<" in page and "−0.09 and 0.33" in page


def test_the_lines_check_reuses_hold_no_kappa():
    r = {"tpr": 0.8, "tpr_interval": [0.7, 0.9], "tnr": 0.6, "tnr_interval": [0.5, 0.7],
         "kappa": 0.4, "kappa_interval": [0.2, 0.6], "left": 3}
    assert not [line for line in front.estimate_lines(r) if "Kappa" in line]
