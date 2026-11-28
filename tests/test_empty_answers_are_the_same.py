"""An answer that was empty and is still empty is the same answer: a grade that changed on it
is the LLM-as-a-judge's doing, as on any unchanged answer. Only an answer the results don't
hold at all (no answer field) can't be told. 6 empty answers graded again from fail to pass
read as "fixed 6 ... Your change helped"."""

import csv

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _flat, _run

N = 40


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _table(path, ids: bool, empty_pass: bool) -> None:
    """Answers 0 to 5 are empty: failed, or passed when `empty_pass`."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow((["id"] if ids else []) + ["input", "output", "verdict"])
        for i in range(N):
            empty = i < 6
            verdict = ("pass" if empty_pass else "fail") if empty else (
                "pass" if i % 2 else "fail")
            w.writerow(([f"q-{i:02}"] if ids else []) + [
                f"Question {i}?", "" if empty else f"Answer {i}.", verdict])


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_empty_answers_graded_again_are_only_grades(tmp_path, monkeypatch, capsys, ids):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "results.csv", ids, False)
    _table(tmp_path / "before.csv", ids, False)
    _said(capsys)
    _table(tmp_path / "results.csv", ids, True)
    code, out = _said(capsys)
    assert code == 0 and "fixed 6" not in out and before_after.ONLY_GRADES in out, out
    code, out = _said(capsys, "results.csv", "--before", "before.csv")
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in out, out
