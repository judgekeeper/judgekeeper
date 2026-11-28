"""A --before run that compares nothing (only the grades changed, two setups, no question in
both) leaves .judgekeeper/last-graded.json as it was: the next plain run still compares with
the results read last here, not with the file it refused. It wrote the refused file's grades,
so a plain run after it said "broke 10 ... made it worse" on answers that kept their grades."""

import csv

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import WORSE, N, _checked, _flat, _run, _worse, _write
from tests.test_grades_only_changed import _marked_project, _stricter

SAME = f"On the {N} questions in both results: fixed 0, broke 0, same {N}."


def _rows(path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ten_answers_reworded(path, ids: bool) -> None:
    """10 answers of the same LLM-as-a-judge get new text and keep their grades."""
    rows = _rows(path)
    for r in rows[:10]:
        r["output"] += " Said another way."
    _write(path, rows, ids)


def _then_same(tmp_path, capsys, ids: bool, last: bytes) -> None:
    assert (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes() == last
    _ten_answers_reworded(tmp_path / "results.csv", ids)
    code, out = _run(capsys)
    out = _flat(out)
    assert code == 0 and WORSE not in out, out
    assert SAME in out, out


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_a_refused_before_after_a_rejected_check_keeps_the_last_grades(tmp_path, monkeypatch,
                                                                      capsys, ids):
    """A check found the new LLM-as-a-judge worse and kept the old one; `new-results.csv
    --before results.csv` refuses (only the grades changed); then 10 answers of results.csv
    are reworded by the old one, grades kept."""
    _checked(tmp_path, monkeypatch, capsys, ids, grade=_worse)
    monkeypatch.setenv("CI", "true")
    last = (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes()
    code, out = _run(capsys, "new-results.csv", "--before", "results.csv")
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in _flat(out), out
    _then_same(tmp_path, capsys, ids, last)


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_a_refused_before_with_no_check_keeps_the_last_grades(tmp_path, monkeypatch, capsys,
                                                             ids):
    """strict.csv: the same answers graded again, stricter; `strict.csv --before results.csv`
    refuses."""
    _marked_project(tmp_path, monkeypatch, capsys, ids)
    monkeypatch.setenv("CI", "true")
    _write(tmp_path / "strict.csv", _rows(tmp_path / "results.csv"), ids)
    _stricter(tmp_path / "strict.csv", ids)
    last = (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes()
    code, out = _run(capsys, "strict.csv", "--before", "results.csv")
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in _flat(out), out
    _then_same(tmp_path, capsys, ids, last)


def test_a_before_of_another_setup_or_with_no_match_keeps_the_last_grades(tmp_path,
                                                                         monkeypatch, capsys):
    """The other ways a --before compares nothing: another model named, no question in both
    (other.csv, the same answers under other ids, read with --before results.csv)."""
    _marked_project(tmp_path, monkeypatch, capsys, True)
    monkeypatch.setenv("CI", "true")
    rows = _rows(tmp_path / "results.csv")
    _write(tmp_path / "judge-b.csv", rows, True, "judge-b")
    _write(tmp_path / "results.csv", rows, True, "judge-a")
    _run(capsys)  # judge-a's results read last
    last = (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes()
    code, out = _run(capsys, "results.csv", "--before", "judge-b.csv")
    assert code == 3 and before_after.OTHER_SETUP in _flat(out), out
    assert (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes() == last
    _write(tmp_path / "other.csv", [{**r, "id": f"x-{r['id']}"} for r in rows], True, "judge-a")
    code, out = _run(capsys, "other.csv", "--before", "results.csv")
    assert code == 3 and "questions in both results:" not in _flat(out), out
    assert (tmp_path / ".judgekeeper" / "last-graded.json").read_bytes() == last
    _write(tmp_path / "results.csv", rows, True, "judge-a")  # read again: compared as before
    code, out = _run(capsys, "results.csv")
    assert code == 0 and "No question is in both results" not in _flat(out), out
