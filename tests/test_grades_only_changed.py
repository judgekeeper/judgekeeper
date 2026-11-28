"""Without a judge_model column, judgekeeper can't tell two LLM-as-a-judge setups apart by
what the results say. An agent change changes answers: a question counts as fixed or broke
only when its answers changed. Grades that changed on the same answers are the
LLM-as-a-judge's doing (the same one may grade otherwise, or another one did): a plain run
starts again (ONLY_GRADES), --before does not compare them (exit 3), never "Your change made it
worse"."""

import csv
import json
import shutil

import pytest

from judgekeeper import before_after
from judgekeeper.start_label import StartSession, Workspace
from tests.test_compare_after_check import (
    WORSE,
    N,
    _checked,
    _flat,
    _lenient,
    _row,
    _run,
    _worse,
    _write,
)

COMPARED = "questions in both results:"


def _rows(path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _marked_project(here, monkeypatch, capsys, ids: bool):
    """results.csv (no judge_model), every answer marked as it truly is, a plain run read it."""
    monkeypatch.chdir(here)
    monkeypatch.delenv("CI", raising=False)
    rows = [{**_row(i), "verdict": _lenient(i), "id": f"q-{i:02}"} for i in range(N)]
    _write(here / "results.csv", rows, ids)
    _said(capsys)
    ws = Workspace(here)
    truth = {r["output"]: "pass" if r["right"] else "fail" for r in rows}
    pool = {json.loads(line)["id"]: json.loads(line)["output"]
            for line in ws.pool.read_text(encoding="utf-8").splitlines() if line.strip()}
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": truth[pool[item["id"]]], "seconds": 5})
    code, out = _said(capsys)
    assert code == 0 and "needs work" in out, out
    shutil.copy2(here / "results.csv", here / "results.orig.csv")
    return ws


def _stricter(path, ids: bool, k: int = 12) -> None:
    """The same answers graded again by a stricter LLM-as-a-judge: k passes become fails."""
    rows = _rows(path)
    flipped = [r for r in rows if r["verdict"] == "pass"][:k]
    assert len(flipped) == k
    for r in flipped:
        r["verdict"] = "fail"
    _write(path, rows, ids)


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_a_stricter_judge_on_the_same_answers_is_a_new_starting_point(tmp_path, monkeypatch,
                                                                       capsys, ids):
    """(A) No check. The same answers graded again, stricter: was "fixed 0, broke 12 ...
    Your change made it worse", exit 1."""
    _marked_project(tmp_path, monkeypatch, capsys, ids)
    _stricter(tmp_path / "results.csv", ids)
    code, out = _said(capsys)
    assert code == 0, out
    assert before_after.ONLY_GRADES in out and WORSE not in out and COMPARED not in out, out
    code, out = _said(capsys)  # the same results again: said once
    assert before_after.ONLY_GRADES not in out and COMPARED not in out, out
    monkeypatch.setenv("CI", "true")
    code, out = _said(capsys, "results.csv", "--before", "results.orig.csv")
    assert code == 3, out
    assert before_after.ONLY_GRADES_BEFORE in out and WORSE not in out, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_changed_answers_count_and_regraded_ones_do_not(tmp_path, monkeypatch, capsys, ids):
    """A mix: 10 answers changed (and fail now), 12 others only graded again. Only the 10
    count, on the 28 questions whose grades say something of the agent: broke 10, exit 1.
    A guard: an agent change still fails."""
    _marked_project(tmp_path, monkeypatch, capsys, ids)
    rows = _rows(tmp_path / "results.csv")
    passed = [r for r in rows if r["verdict"] == "pass"]
    for r in passed[:10]:
        r["output"] += " Or not."
        r["verdict"] = "fail"
    for r in passed[10:22]:
        r["verdict"] = "fail"
    _write(tmp_path / "results.csv", rows, ids)
    monkeypatch.setenv("CI", "true")
    code, out = _said(capsys, "results.csv", "--before", "results.orig.csv")
    assert code == 1 and "On the 28 questions in both results: fixed 0, broke 10," in out, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_after_a_take_on_reading_either_file_never_says_worse(tmp_path, monkeypatch, capsys,
                                                              ids):
    """(B) A check took on new-results.csv (the same answers, graded by another
    LLM-as-a-judge). Reading results.csv, then the plain run: was "helped, fixed ..." then
    "broke ...", exit 1."""
    _checked(tmp_path, monkeypatch, capsys, ids, named=True)
    monkeypatch.setenv("CI", "true")
    assert _said(capsys)[0] == 0  # the new starting point
    for argv in (["results.csv"], []):
        code, out = _said(capsys, *argv)
        assert code == 0, (argv, out)
        assert WORSE not in out and COMPARED not in out, (argv, out)


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_before_after_a_refused_check_does_not_compare(tmp_path, monkeypatch, capsys, ids):
    """(C) The check refused new-results.csv; --before results.csv: was "broke ...", exit 1."""
    _checked(tmp_path, monkeypatch, capsys, ids, named=True, grade=_worse)
    monkeypatch.setenv("CI", "true")
    code, out = _said(capsys, "new-results.csv", "--before", "results.csv")
    assert code == 3, out
    assert before_after.ONLY_GRADES_BEFORE in out and WORSE not in out, out


def test_a_file_from_before_answers_were_kept_is_still_read(tmp_path):
    """last-graded.json as judgekeeper wrote it before it kept the answers (1.4.0): read."""
    ws = Workspace(tmp_path)
    ws.dir.mkdir()
    side = {"questions": {"k1": ["pass"], "k2": ["fail"]}, "ids": False}
    before_after.write(ws, None, side, "setup")
    assert before_after.read(ws) == {"before": None, "now": side, "setup": "setup"}
