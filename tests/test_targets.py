"""One set of label targets for every command (targets.py): a rough check needs 15 of each
kind of label, a reliable result 25 of each and both the TPR and the TNR range no wider than
0.30."""

from __future__ import annotations

import pytest

from judgekeeper import targets

NARROW, WIDE = [0.80, 0.98], [0.55, 0.96]  # 0.18 and 0.41 wide


def test_the_targets():
    assert (targets.ROUGH, targets.RELIABLE, targets.MAX_WIDTH) == (15, 25, 0.30)


@pytest.mark.parametrize("correct,wrong,check", [
    (0, 0, "too_few"), (14, 30, "too_few"), (30, 14, "too_few"), (15, 15, "rough"),
    (24, 40, "rough"), (40, 24, "rough"), (25, 25, "reliable"), (60, 31, "reliable"),
])
def test_the_check_follows_the_fewer_kind_of_label(correct, wrong, check):
    assert targets.check(correct, wrong, NARROW, NARROW)["check"] == check


def test_twenty_five_of_each_with_a_wide_range_is_not_reliable_yet():
    r = targets.check(25, 25, NARROW, WIDE)
    assert r["check"] == "rough"
    assert r["wide"] == {"tnr": pytest.approx(0.41)}
    r = targets.check(30, 30, WIDE, WIDE)
    assert set(r["wide"]) == {"tpr", "tnr"}
    r = targets.check(25, 25, NARROW, [None, None])  # a range that is unknown is not narrow
    assert r["check"] == "rough" and r["wide"] == {"tnr": None}


def test_a_range_of_exactly_the_width_is_narrow_enough():
    assert targets.check(25, 25, [0.5, 0.8], [0.6, 0.9])["check"] == "reliable"


def test_a_wide_range_below_the_targets_is_not_mentioned():
    assert targets.check(20, 20, WIDE, WIDE)["wide"] == {}


WRONG_WIDE = ("Not reliable yet: the range for answers you marked Wrong is still 0.41 wide. "
              "Label more answers to narrow it.")
CORRECT_WIDE = ("Not reliable yet: the range for answers you marked Correct is still 0.41 wide. "
                "Label more answers to narrow it.")
BOTH_WIDE = ("Not reliable yet: the ranges for answers you marked Correct and answers you "
             "marked Wrong are still 0.41 and 0.50 wide. Label more answers to narrow them.")
UNKNOWN = ("Not reliable yet: the range for answers you marked Wrong is not known yet. Label "
           "more answers.")


@pytest.mark.parametrize("correct,wrong,tpr,tnr,line", [
    (3, 9, NARROW, NARROW, "A rough check needs 15 of each."),
    (15, 20, NARROW, NARROW, "Rough check ready. A reliable result needs 25 of each."),
    (25, 25, NARROW, WIDE, WRONG_WIDE),
    (25, 25, WIDE, NARROW, CORRECT_WIDE),
    (25, 25, WIDE, [0.4, 0.9], BOTH_WIDE),
    (25, 25, NARROW, [None, None], UNKNOWN),
    (25, 25, NARROW, NARROW, "Reliable result ready."),
])
def test_the_line_says_how_far_along_and_what_to_do(correct, wrong, tpr, tnr, line):
    assert targets.line(targets.check(correct, wrong, tpr, tnr)) == line


def test_the_line_can_name_the_labels_another_way():
    r = targets.check(30, 26, NARROW, WIDE)
    assert targets.line(r, ("answers people passed", "answers people failed")) == (
        "Not reliable yet: the range for answers people failed is still 0.41 wide. Label more "
        "answers to narrow it.")


# The smallest drop a set of marks can see ---------------------------------------------------

@pytest.mark.parametrize("n,drop", [(15, 45), (16, 40), (25, 30), (50, 15), (100, 10)])
def test_the_smallest_drop_a_set_of_marks_can_see(n, drop):
    assert targets.smallest_drop(n, n) == drop


def test_the_smallest_drop_follows_the_fewer_kind_of_mark():
    assert targets.smallest_drop(100, 16) == targets.smallest_drop(16, 100) == 40
    assert targets.smallest_drop(25, 400) == 30


def test_no_smallest_drop_under_fifteen_of_each():
    assert targets.smallest_drop(14, 100) is None
    assert targets.drop_line(None) is None
    assert targets.drop_line(targets.smallest_drop(16, 16)) == (
        "This set can see a drop of 40 points or more. Smaller changes need more marks.")


def test_many_marks_see_a_drop_of_five_points_quickly():
    import time

    began = time.monotonic()
    assert targets.smallest_drop(2000, 2000) == 5
    assert time.monotonic() - began < 5
