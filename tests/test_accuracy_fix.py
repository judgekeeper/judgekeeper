"""The numbers around `judgekeeper fix` and `check`: hidden marks set aside at the first
result and kept out of sight while in use, every fix test counted, few mistakes said up front,
how many changes the marks have helped pick, the person's own slips, a range that stays honest
while the person is still marking, and paid re-checks that ask twice.

No test calls an API: the judge is the faked promptfoo of tests/test_fix.py.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import fix, targets
from tests import test_fix as base
from tests.test_fix import NEW_RULE, _split, _write_rule, project, run

here, judge = base.here, base.judge  # the fixtures: a project folder, and its faked judge


def _flat(text: str) -> str:
    return " ".join(text.split())


# Every fix test counts ------------------------------------------------------------------------

@pytest.mark.parametrize("k,safe,better", [(1, 3, 6), (2, 4, 7), (3, 5, 7), (4, 5, 8)])
def test_each_extra_test_on_the_same_hidden_marks_is_stricter(k, safe, better):
    """On 10 hidden marks, with nothing broken: the fewest fixed for "safe to try" and for
    "better" at the k-th test."""
    def fewest(kinds):
        return next(f for f in range(11) if targets.fix_verdict(f, 0, 10, test=k).kind in kinds)

    assert fewest(("safe", "better")) == safe
    assert fewest(("better",)) == better


def test_every_test_counts_whatever_the_last_verdict():
    split = fix.Split(seed=1, seen=[], hidden=[], tests=[
        {"kind": "rule", "verdict": "safe"}, {"kind": "rule", "verdict": "leans better"}])
    assert fix.next_test(split) == 3


def test_few_mistakes_hidden_are_said_before_the_question(here, capsys, judge, monkeypatch):
    monkeypatch.setattr(base, "WRONG_PASSES", 3)  # 3 + 1 mistakes: about 1 of them hidden
    monkeypatch.setattr(base, "WRONG_FAILS", 1)
    ws = project(here)
    run(capsys)
    split, marks = _split(ws), fix.Marks(ws)
    wrong = sum(marks.judge[i] != marks.person[i] for i in split["hidden"])
    assert wrong < 3
    _write_rule(ws)
    code, out = run(capsys)
    assert code == 3  # no terminal: the question stops it
    n = len(split["hidden"])
    safe = next(f for f in range(n + 1) if targets.fix_verdict(f, 0, n).kind in ("safe",
                                                                                  "better"))
    better = next(f for f in range(n + 1) if targets.fix_verdict(f, 0, n).kind == "better")
    said = (f"Your hidden marks hold only {wrong} {'answer' if wrong == 1 else 'answers'} "
            f"your judge got wrong. A new rule needs at least {safe} of those fixed to be "
            f"called safe to try, and about {better} to be called better, so this test can "
            "only catch a worse rule.")
    assert said in _flat(out)
    assert _flat(out).index(said) < _flat(out).index("To test it, judgekeeper asks")


def test_enough_mistakes_hidden_say_nothing_more(here, capsys, judge):
    ws = project(here)
    run(capsys)
    _write_rule(ws)
    _, out = run(capsys)
    assert "Your hidden marks hold only" not in out
    assert json.dumps(NEW_RULE) not in out


def test_the_guide_says_how_extra_tests_stay_fair():
    from pathlib import Path

    guide = (Path(__file__).parent.parent / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "under about 1 in 20" in guide
