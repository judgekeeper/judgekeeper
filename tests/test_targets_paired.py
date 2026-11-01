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


def test_the_drop_is_worked_out_as_before_on_a_grid():
    """Every (marks, rate) of the grid gives the drop that the full search gave."""
    import json
    from pathlib import Path

    grid = json.loads((Path(__file__).parent / "fixtures" / "smallest_drop_grid.json")
                      .read_text(encoding="utf-8"))
    for key, drop in grid.items():
        n, rate = key.split(",")
        assert targets._smallest(int(n), max(float(rate), 0.01)) == drop, key


def test_many_marks_need_few_steps(monkeypatch):
    """Thousands of imported marks: only the counts that can happen are worked out."""
    calls = []
    score = targets._score

    def counted(*args):
        calls.append(1)
        return score(*args)

    monkeypatch.setattr(targets, "_score", counted)
    assert targets.smallest_drop(3000, 3000, 0.85, 0.85) == 5
    assert len(calls) < 500_000
