"""One set of label targets for every command (targets.py): a first result needs 15 of each
kind of label; it is ready when both the TPR and the TNR range are no wider than 0.30, whatever
the counts."""

from __future__ import annotations

import pytest

from judgekeeper import targets

NARROW, WIDE = [0.80, 0.98], [0.55, 0.96]  # 0.18 and 0.41 wide


def test_the_targets():
    assert (targets.ROUGH, targets.MAX_WIDTH) == (15, 0.30)
    assert (targets.TOO_WIDE, targets.ROUGH_WIDTH, targets.SHARP_WIDTH) == (0.40, 0.30, 0.20)
    assert not hasattr(targets, "RELIABLE")


@pytest.mark.parametrize("correct,wrong,check", [
    (0, 0, "too_few"), (14, 30, "too_few"), (30, 14, "too_few"), (15, 15, "reliable"),
    (24, 40, "reliable"), (40, 24, "reliable"), (25, 25, "reliable"), (60, 31, "reliable"),
])
def test_the_first_result_follows_the_fewer_kind_of_label(correct, wrong, check):
    assert targets.check(correct, wrong, NARROW, NARROW)["check"] == check


def test_a_wide_range_keeps_a_result_from_being_ready():
    r = targets.check(25, 25, NARROW, WIDE)
    assert r["check"] == "rough"
    assert r["wide"] == {"tnr": pytest.approx(0.41)}
    r = targets.check(15, 15, WIDE, WIDE)
    assert set(r["wide"]) == {"tpr", "tnr"}
    r = targets.check(25, 25, NARROW, [None, None])  # a range that is unknown is not narrow
    assert r["check"] == "rough" and r["wide"] == {"tnr": None}


def test_a_range_of_exactly_the_width_is_narrow_enough():
    assert targets.check(25, 25, [0.5, 0.8], [0.6, 0.9])["check"] == "reliable"


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
