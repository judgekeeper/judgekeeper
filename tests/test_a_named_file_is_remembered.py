"""A results file named on the command line is the one later plain runs read, also once the
marking started on another (the reference: "Later runs remember a file you name"). After a
take-on, `judgekeeper results.csv` goes back to the LLM-as-a-judge the marks were made on;
the next plain run read the newest file, new-results.csv, again: it said "Only the grades
changed" a second time, and asked to check the LLM-as-a-judge already checked."""

import csv
import json
import os
import time

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _checked, _flat, _run


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _dated(here) -> None:
    """Both files written before the runs that follow, new-results.csv the newest."""
    for name, ago in (("results.csv", 120), ("new-results.csv", 60)):
        then = time.time() - ago
        os.utime(here / name, (then, then))


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_the_file_named_after_a_take_on_is_read_by_later_runs(tmp_path, monkeypatch, capsys,
                                                               ids):
    _checked(tmp_path, monkeypatch, capsys, ids)  # check took on new-results.csv
    _dated(tmp_path)
    monkeypatch.setenv("CI", "true")
    assert _said(capsys)[0] == 0
    code, out = _said(capsys, "results.csv")
    assert code == 0, out
    code, out = _said(capsys)
    assert code == 0, out
    assert before_after.ONLY_GRADES not in out and "got a different grade" not in out, out
    assert "Next: run `judgekeeper check`" not in out, out
    assert "new-results.csv" not in out, out


def test_results_written_after_going_back_are_read_again(tmp_path, monkeypatch, capsys):
    """The file named to go back to the marked LLM-as-a-judge is read until results are
    written after that run: those are the newest, as on any plain run."""
    _checked(tmp_path, monkeypatch, capsys, True)
    _dated(tmp_path)
    monkeypatch.setenv("CI", "true")
    assert _said(capsys, "results.csv")[0] == 0
    later = time.time() + 60
    os.utime(tmp_path / "new-results.csv", (later, later))  # graded again after that run
    _, out = _said(capsys)
    assert "new-results.csv" in out, out


def _eval(path, prefix: str, flip: int = 0) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "verdict"])
        for i in range(40):
            w.writerow([f"{prefix}-{i:02}", f"{prefix} question {i}?",
                        f"Answer {i}." + (" Now wrong." if i < flip else ""),
                        "fail" if i % 4 == 0 or i < flip else "pass"])


def test_an_older_file_looked_at_does_not_stick(tmp_path, monkeypatch, capsys):
    """Naming an older file once compares it, and plain runs read the file they read before:
    looking back never changes which results they read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _eval(tmp_path / "results.csv", "q")
    _eval(tmp_path / "other-eval.csv", "z")
    _eval(tmp_path / "results-old.csv", "q", flip=9)
    for name in ("results-old.csv", "other-eval.csv"):
        then = time.time() - 3600
        os.utime(tmp_path / name, (then, then))
    assert _said(capsys, "results.csv")[0] == 0
    assert _said(capsys, "other-eval.csv")[0] == 3
    assert _said(capsys)[0] == 0
    code, out = _said(capsys, "results-old.csv")
    assert code == 1 and "broke 6," in out, out
    _, out = _said(capsys)
    assert "results-old.csv" not in out, out
    data = json.loads((tmp_path / ".judgekeeper" / "start.json").read_text(encoding="utf-8"))
    assert data.get("given") == "results.csv"
