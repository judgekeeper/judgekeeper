"""--before between the file a check replaced (graded by the LLM-as-a-judge the marks were
made on) and the taken-on judge's file, where the agent re-worded the marked answers the two
judges grade otherwise (grades kept): no unchanged marked answer tells the judges apart, so
the bytes of the replaced file do. Two LLM-as-a-judges' grades are never compared as an agent
change."""
import csv
import shutil

from judgekeeper import before_after
from tests.test_compare_after_check import _checked, _flat, _run, _write


def _rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_two_judges_with_reworded_marked_answers(tmp_path, monkeypatch, capsys):
    _checked(tmp_path, monkeypatch, capsys, True, named=True)  # takes new-results.csv on
    shutil.copy2(tmp_path / "results.csv", tmp_path / "main-results.csv")  # judge marked with
    before = {r["output"]: r["verdict"] for r in _rows(tmp_path / "results.csv")}
    rows = _rows(tmp_path / "new-results.csv")  # the taken-on judge
    otherwise = [r for r in rows if before.get(r["output"]) not in (None, r["verdict"])]
    assert otherwise
    for r in otherwise:
        r["output"] += " Said another way."  # the agent re-worded them; the grade is kept
    _write(tmp_path / "cand.csv", rows, True)
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "cand.csv", "--before", "main-results.csv")
    flat = _flat(out)
    assert code == 3 and before_after.OTHER_SETUP in flat, out


def test_two_judges_with_every_answer_reworded(tmp_path, monkeypatch, capsys):
    _checked(tmp_path, monkeypatch, capsys, True, named=True)  # takes new-results.csv on
    shutil.copy2(tmp_path / "results.csv", tmp_path / "main-results.csv")  # judge marked with
    before = {r["output"]: r["verdict"] for r in _rows(tmp_path / "results.csv")}
    rows = _rows(tmp_path / "new-results.csv")  # the taken-on judge
    otherwise = [r for r in rows if before.get(r["output"]) not in (None, r["verdict"])]
    assert otherwise
    for r in rows:  # a new agent version: every answer re-worded
        r["output"] += " Said another way."  # the agent re-worded them; the grade is kept
    _write(tmp_path / "cand.csv", rows, True)
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "cand.csv", "--before", "main-results.csv")
    flat = _flat(out)
    assert code == 3 and before_after.OTHER_SETUP in flat, out
