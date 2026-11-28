"""Spaces around an answer or a question, and Windows line ends, don't make it another answer:
before an answer is hashed, CRLF is LF and the spaces at its two ends go. Inside it, every
space counts: a doubled space or a new line break is a changed answer. A trailing space on
every answer, graded again stricter, read as "broke 14 ... made it worse"."""

import csv

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _flat, _run

N = 40
STRICTER = 14


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _table(path, ids: bool, edit=lambda text: text, stricter: int = 0) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow((["id"] if ids else []) + ["input", "output", "verdict"])
        for i in range(N):
            verdict = "fail" if i % 2 or i < 2 * stricter else "pass"
            w.writerow(([f"q-{i:02}"] if ids else []) + [
                f"Question {i}?", edit(f"Answer {i}.\nIn two lines."), verdict])


EDITS = {"trailing space": lambda t: t + " ", "CRLF": lambda t: t.replace("\n", "\r\n"),
         "spaces around": lambda t: f"  {t}\n"}


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
@pytest.mark.parametrize("edit", EDITS)
def test_spaces_at_the_ends_and_line_ends_are_the_same_answer(tmp_path, monkeypatch, capsys,
                                                              ids, edit):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "results.csv", ids)
    _table(tmp_path / "before.csv", ids)
    _said(capsys)
    _table(tmp_path / "results.csv", ids, EDITS[edit], stricter=STRICTER // 2)
    code, out = _said(capsys)
    assert code == 0 and "made it worse" not in out, out
    assert before_after.ONLY_GRADES in out, out
    code, out = _said(capsys, "results.csv", "--before", "before.csv")
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in out, out


def test_a_doubled_space_inside_is_a_changed_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "before.csv", True)
    _table(tmp_path / "results.csv", True, lambda t: t.replace(" ", "  ", 1),
           stricter=STRICTER // 2)
    _, out = _said(capsys, "results.csv", "--before", "before.csv")
    assert before_after.ONLY_GRADES_BEFORE not in out, out
    assert "fixed 0, broke 7," in out, out
