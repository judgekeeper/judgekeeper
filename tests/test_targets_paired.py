"""The paired test a re-check uses, and the smallest drop from the judge's measured
steadiness."""

from __future__ import annotations

import pytest

from judgekeeper import targets


@pytest.mark.parametrize("now_wrong, now_right, worse", [
    (9, 0, True),  # 9 now wrong, none now right: worse
    (2, 1, False),
    (0, 0, False),
    (5, 0, True),  # 1/32 is under 5%
    (4, 0, False),  # 1/16 is not
    (8, 1, True),
    (6, 6, False),
    (0, 9, False),  # one-sided: only a drop counts
])
def test_the_one_sided_sign_test(now_wrong, now_right, worse):
    assert targets.got_worse(now_wrong, now_right) is worse


def test_the_smallest_drop_keeps_its_fixed_model_by_default():
    assert targets.smallest_drop(25, 25) == targets.smallest_drop(25, 25, flip=None, right=None)
    assert targets.smallest_drop(20, 20) == 35


def test_a_steadier_judge_lets_the_same_marks_see_a_smaller_drop():
    fixed = targets.smallest_drop(25, 25)
    steady = targets.smallest_drop(25, 25, flip=0.0, right=0.95)
    shaky = targets.smallest_drop(25, 25, flip=0.20, right=0.80)
    assert steady <= fixed
    assert shaky is None or shaky > fixed


def test_a_measured_flip_rate_counts_as_at_least_one_percent():
    assert targets.smallest_drop(25, 25, flip=0.0, right=0.9) == \
        targets.smallest_drop(25, 25, flip=0.01, right=0.9)


def test_none_under_fifteen_of_each_also_when_measured():
    assert targets.smallest_drop(14, 30, flip=0.01, right=0.9) is None
