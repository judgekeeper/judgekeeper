""""Finding 15 answers you mark Fail can take many marks" is said only while enough answers are
left to mark to reach 15 Fail marks; with fewer left, the line says so and to run the eval on
more questions."""

from __future__ import annotations

import pytest

from judgekeeper import front, targets
from tests.start_projects import answer, table_project
from tests.test_labels_import import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _labels(here, n: int) -> None:
    lines = ["answer,label", *(f"{answer(i)},Pass" for i in range(n))]
    (here / "labels.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_with_one_answer_left_it_says_fail_marks_cant_be_reached(here, capsys):
    """520 answers, 500 passed and 20 failed; 519 brought as Pass marks: 1 answer is left, so
    15 Fail marks can't be had."""
    table_project(here, [True] * 500 + [False] * 20)
    _labels(here, 519)
    code, out = run(capsys, "--labels", "labels.csv")
    assert code == 0, out
    text = flat(out)
    assert "can take many marks" not in text, out
    assert (f"Only 1 answer is left to mark, not enough to reach {targets.ROUGH} Fail marks, "
            "so run your eval on more questions.") in text, out


def test_with_enough_answers_left_it_still_says_it_can_take_many_marks(here, capsys):
    table_project(here, [True] * 500 + [False] * 20)
    _labels(here, 100)
    code, out = run(capsys, "--labels", "labels.csv")
    assert code == 0, out
    assert front.FINDING.format(n=targets.ROUGH)[1:] in flat(out), out  # "Finding" or "finding"
    assert "not enough to reach" not in out


def test_the_line_counts_the_fail_marks_still_needed():
    needs = front.needs_each_kind
    assert "can take many marks" in needs(20, 520, left=14, fail_marks=1)  # 14 more: 14 left
    assert "Only 13 answers are left" in needs(20, 520, left=13, fail_marks=1)
    assert "can take many marks" in needs(20, 520)  # marking starts: every answer left
