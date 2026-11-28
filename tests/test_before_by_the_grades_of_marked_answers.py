"""--before on results that don't say who graded them, while a check's take-on is in force:
each file is told by the grades of its marked answers whose text is unchanged, the grades the
marks were made on or the grades taken on. Two files of one LLM-as-a-judge compare, whichever
file's bytes a check replaced; files of the two are not compared (exit 3). When neither can be
told (no unchanged marked answer the two grade otherwise), they compare as usual. A --before
run never goes "back to the one you marked with" and never changes start.json."""

import csv
import shutil

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import BACK_TO, _checked, _flat, _run, _write


def _rows(path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _eight_wrong(path, ids: bool, keep=()) -> None:
    """8 answers that passed are now wrong: new text, graded fail."""
    rows = _rows(path)
    passed = [r for r in rows if r["verdict"] == "pass" and r["output"] not in keep][:8]
    assert len(passed) == 8
    for r in passed:
        r["output"] += " Or not."
        r["verdict"] = "fail"
    _write(path, rows, ids)


def _start(here) -> bytes:
    return (here / ".judgekeeper" / "start.json").read_bytes()


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_two_files_of_the_marked_judge_compare_after_a_take_on(tmp_path, monkeypatch, capsys,
                                                               ids):
    """main-results.csv is a byte copy of the results.csv the check replaced; both are graded
    by the LLM-as-a-judge the marks were made on. Then the taken-on judge's pair still
    compares too."""
    _checked(tmp_path, monkeypatch, capsys, ids, named=True)  # takes new-results.csv on
    shutil.copy2(tmp_path / "results.csv", tmp_path / "main-results.csv")
    shutil.copy2(tmp_path / "new-results.csv", tmp_path / "main-new.csv")
    _eight_wrong(tmp_path / "results.csv", ids)
    monkeypatch.setenv("CI", "true")
    start = _start(tmp_path)
    code, out = _run(capsys, "results.csv", "--before", "main-results.csv")
    flat = _flat(out)
    assert code == 1 and "questions in both results: fixed 0, broke 8," in flat, out
    assert BACK_TO not in flat and before_after.OTHER_SETUP not in flat, out
    assert _start(tmp_path) == start  # never back, never a change to start.json
    shutil.copy2(tmp_path / "main-new.csv", tmp_path / "cand-new.csv")
    _eight_wrong(tmp_path / "cand-new.csv", ids)
    code, out = _run(capsys, "cand-new.csv", "--before", "main-new.csv")
    assert code == 1 and "questions in both results: fixed 0, broke 8," in _flat(out), out


def test_files_the_grades_cannot_tell_apart_are_told_by_the_replaced_bytes(tmp_path,
                                                                             monkeypatch, capsys):
    """Every marked answer the two LLM-as-a-judges grade otherwise got new text in results.csv
    (with its grade kept): what is left grades the same under both, so the grades can't tell
    which judge graded it. main-results.csv holds the bytes of the file the check replaced,
    results.csv not: taken as two setups, not compared (as the taken-on judge's file would be,
    test_before_against_the_replaced_file)."""
    _checked(tmp_path, monkeypatch, capsys, True, named=True)
    shutil.copy2(tmp_path / "results.csv", tmp_path / "main-results.csv")
    taken = {r["output"]: r["verdict"] for r in _rows(tmp_path / "new-results.csv")}
    rows = _rows(tmp_path / "results.csv")
    otherwise = {r["output"] for r in rows if taken.get(r["output"]) not in (None, r["verdict"])}
    assert otherwise
    for r in rows:
        if r["output"] in otherwise:
            r["output"] += " Said another way."
    _write(tmp_path / "results.csv", rows, True)
    _eight_wrong(tmp_path / "results.csv", True,
                 keep={o + " Said another way." for o in otherwise})
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "results.csv", "--before", "main-results.csv")
    flat = _flat(out)
    assert code == 3 and before_after.OTHER_SETUP in flat, out
    assert "questions in both results:" not in flat, out
