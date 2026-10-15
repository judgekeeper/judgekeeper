"""The smallest drop a set of marks can see, from how often this judge is right."""

from __future__ import annotations

from judgekeeper import targets


def test_the_smallest_drop_keeps_a_fixed_model_when_the_rates_are_not_known():
    assert targets.smallest_drop(25, 25) == targets.smallest_drop(25, 25, targets.RIGHT_NOW,
                                                                  targets.RIGHT_NOW)


def test_more_marks_see_a_smaller_drop():
    drops = [targets.smallest_drop(n, n, 0.9, 0.9) for n in (15, 25, 50, 100)]
    assert all(d is not None for d in drops)
    assert drops == sorted(drops, reverse=True) and drops[0] > drops[-1]


def test_the_weaker_kind_of_mark_sets_the_drop():
    both = targets.smallest_drop(25, 100, 0.9, 0.9)
    assert both == targets.smallest_drop(25, 25, 0.9, 0.9)


def test_none_under_fifteen_of_each():
    assert targets.smallest_drop(14, 30, 0.9, 0.9) is None
