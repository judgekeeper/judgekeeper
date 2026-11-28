"""Results that don't say who graded them, no check: a new results.csv with 9 answers that
changed and 5 unchanged marked answers graded otherwise. Grades that changed on the same
answers don't show that the LLM-as-a-judge changed (the same one may grade otherwise), and
marks don't depend on it: the 9 new answers are added for marking. They waited "until your
changed LLM-as-a-judge is checked", and mark said every answer was marked."""

import csv

import pytest

from tests.test_compare_after_check import _flat, _run, _write
from tests.test_grades_only_changed import _marked_project

ADDED_9 = "Your newest results have 9 answers you haven't seen. They're added for marking."
WAITS = "so they wait until"


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _mixed(path, ids: bool) -> None:
    """9 answers get new text (graded as before); 5 right answers keep theirs and now fail
    (the LLM-as-a-judge does worse on them)."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows[:9]:
        r["output"] += " Said another way."
    for r in rows[20:30:2]:  # right answers, passed
        assert r["verdict"] == "pass"
        r["verdict"] = "fail"
    _write(path, rows, ids)


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_new_answers_are_added_when_a_few_marked_ones_got_other_grades(tmp_path, monkeypatch,
                                                                       capsys, ids):
    _marked_project(tmp_path, monkeypatch, capsys, ids)
    _mixed(tmp_path / "results.csv", ids)
    _, out = _said(capsys)
    assert ADDED_9 in out and WAITS not in out, out
    _, out = _said(capsys, "mark")
    assert "You have marks on all" not in out, out


def test_after_a_check_of_them_new_answers_still_do_not_wait(tmp_path, monkeypatch, capsys):
    _marked_project(tmp_path, monkeypatch, capsys, True)
    _mixed(tmp_path / "results.csv", True)
    code, out = _run(capsys, "check", "results.csv")
    assert code == 1, out  # worse on the marks: kept the grades from before
    _, out = _said(capsys)
    assert WAITS not in out, out
    # no model named: the grades may have changed with the same LLM-as-a-judge
    assert "Next: change your LLM-as-a-judge's rule, or" in out, out
    assert "go back to your old LLM-as-a-judge" not in out, out
    assert "You have marks on all" not in _said(capsys, "mark")[1]
    _run(capsys, "fix")
    _, out = _said(capsys)
    assert ("Next: change your LLM-as-a-judge's rule, or grade "
            ".judgekeeper/fix/marked-answers.csv again with the LLM-as-a-judge you marked "
            "with, then run `judgekeeper check <new results file>`.") in out, out
