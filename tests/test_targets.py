"""One set of label targets for every command (targets.py): a first result needs 15 of each
kind of label. No rule follows a range's width (the verdict follows where the ranges lie)."""

from __future__ import annotations

import pytest

from judgekeeper import targets


def test_the_targets():
    assert targets.ROUGH == 15
    for gone in ("RELIABLE", "MAX_WIDTH", "TOO_WIDE", "ROUGH_WIDTH", "SHARP_WIDTH"):
        assert not hasattr(targets, gone), gone


@pytest.mark.parametrize("correct,wrong,check", [
    (0, 0, "too_few"), (14, 30, "too_few"), (30, 14, "too_few"), (15, 15, "result"),
    (24, 40, "result"), (40, 24, "result"), (25, 25, "result"), (60, 31, "result"),
])
def test_the_first_result_follows_the_fewer_kind_of_label(correct, wrong, check):
    assert targets.check(correct, wrong) == {"check": check}


# The smallest drop a set of marks can see ---------------------------------------------------

@pytest.mark.parametrize("n,drop", [(15, 30), (16, 30), (25, 20), (50, 10), (100, 10)])
def test_the_smallest_drop_a_set_of_marks_can_see(n, drop):
    assert targets.smallest_drop(n, n) == drop


def test_the_smallest_drop_follows_the_fewer_kind_of_mark():
    assert targets.smallest_drop(100, 16) == targets.smallest_drop(16, 100) == 30
    assert targets.smallest_drop(25, 400) == 20


def test_no_smallest_drop_under_fifteen_of_each():
    assert targets.smallest_drop(14, 100) is None
    assert targets.smallest_drop(16, 16) == 30


def test_many_marks_see_a_drop_of_five_points_quickly():
    import time

    began = time.monotonic()
    assert targets.smallest_drop(2000, 2000) == 5
    assert time.monotonic() - began < 5
