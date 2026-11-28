"""A last-graded.json written by judgekeeper 1.4.0 holds no answer hashes, so it can't tell
an agent change from grades changed on the same answers. A plain run compares nothing, says
so once and starts again from these results (exit 0); the next run compares as usual. It
compared the grades alone: "broke 14 ... made it worse", exit 1."""

import csv

import pytest

from judgekeeper import before_after
from judgekeeper.start_label import Workspace
from tests.test_compare_after_check import _flat, _run

N = 40
OLDER = ("Your last results were saved by an older judgekeeper, so there is nothing to compare "
         "yet. This run is the new starting point.")


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _table(path, ids: bool, stricter: int = 0, changed: int = 0) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow((["id"] if ids else []) + ["input", "output", "verdict"])
        for i in range(N):
            verdict = "fail" if i % 2 or i < 2 * stricter else "pass"
            text = f"Answer {i}." + (" Or not." if i < 2 * changed else "")
            w.writerow(([f"q-{i:02}"] if ids else []) + [f"Question {i}?", text, verdict])


def _as_older(ws) -> None:
    """last-graded.json as 1.4.0 writes it: no answer hashes."""
    saved = before_after.read(ws)
    sides = [None if s is None else {k: v for k, v in s.items() if k != "answers"}
             for s in (saved["before"], saved["now"])]
    before_after.write(ws, *sides, saved["setup"])


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_last_grades_saved_by_an_older_version_start_again_once(tmp_path, monkeypatch, capsys,
                                                                ids):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "results.csv", ids)
    _said(capsys)
    _as_older(Workspace(tmp_path))
    _table(tmp_path / "results.csv", ids, stricter=7)  # the same answers, graded stricter
    code, out = _said(capsys)
    assert code == 0 and OLDER in out and "made it worse" not in out, out
    assert "questions in both results:" not in out, out
    assert "answers" in before_after.read(Workspace(tmp_path))["now"]  # saved anew
    code, out = _said(capsys)
    assert code == 0 and OLDER not in out, out
    _table(tmp_path / "results.csv", ids, stricter=7, changed=8)  # then 8 answers changed
    code, out = _said(capsys)
    assert code == 0 and OLDER not in out, out
    assert f"On the {N} questions in both results: fixed 0, broke 0, same {N}." in out, out
