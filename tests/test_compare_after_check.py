"""After `check` takes on a new LLM-as-a-judge's grades, the next run reading them is a new
starting point: its grades changed because the LLM-as-a-judge did, not the agent or chatbot, so
they are not compared with the grades from before (before_after.RESTARTED). A later change of
the answers compares as usual; a check that keeps the old LLM-as-a-judge leaves it alone."""

from __future__ import annotations

import csv
import json
import os
import time

import pytest

from judgekeeper import before_after
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.test_front import before_comparison, next_lines

N = 40
WORSE = "Your change made it worse."
READS_NEW = "Measure new-results.csv has LLM-as-a-judge grades"


def _row(i: int) -> dict:
    """Question i: the even ones answered right, the odd ones wrong."""
    a, b = 10 + i, 50 + 2 * i
    right = i % 2 == 0
    return {"input": f"What is {a} plus {b}?",
            "output": f"The total of {a} and {b} is {a + b if right else a + b + 1}.",
            "right": right}


def _lenient(i: int) -> str:
    """The old LLM-as-a-judge passes every right answer and 8 of the 20 wrong ones."""
    r = _row(i)
    return "pass" if r["right"] or i < 16 else "fail"


def _write(path, rows: list[dict], ids: bool, model: str | None = None) -> None:
    """`model`: a judge_model column, as an eval tool writes the LLM-as-a-judge's name."""
    columns = ["input", "output", "verdict"] + (["id"] if ids else []) + (
        ["judge_model"] if model else [])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({**row, **({"judge_model": model} if model else {})})
    _newer(path)


def _newer(path) -> None:
    """Each file written is newer than the last, as when an eval runs again."""
    _newer.at = max(getattr(_newer, "at", 0), time.time()) + 10
    os.utime(path, (_newer.at, _newer.at))


def _run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def _flat(text: str) -> str:
    return " ".join(text.split())


def _checked(here, monkeypatch, capsys, ids: bool, grade=None, named: bool = False,
             models: tuple[str, str] | None = None):
    """The tester's lenient/ flow up to `check NEW`: every answer marked as it truly is, a
    plain run (the old LLM-as-a-judge's result), fix, marked-answers.csv graded again by
    `grade` (the right grade by default) into new-results.csv, `fix` and `check` on it.
    `named`: the first runs name results.csv (`judgekeeper results.csv`). `models`: each
    file's judge_model, the old LLM-as-a-judge's and the new one's."""
    monkeypatch.chdir(here)
    monkeypatch.delenv("CI", raising=False)
    old, new = models or (None, None)
    rows = [{**_row(i), "verdict": _lenient(i), "id": f"q-{i:02}"} for i in range(N)]
    _write(here / "results.csv", rows, ids, old)
    given = ["results.csv"] if named else []
    _run(capsys, *given, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    ws = Workspace(here)
    truth = {r["output"]: "pass" if r["right"] else "fail" for r in rows}
    pool = {json.loads(line)["id"]: json.loads(line)["output"]
            for line in ws.pool.read_text(encoding="utf-8").splitlines() if line.strip()}
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": truth[pool[item["id"]]], "seconds": 5})
    code, out = _run(capsys, *given, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert code == 0 and "needs work" in out, out
    assert _run(capsys, "fix")[0] == 0
    grade = grade or (lambda output: truth[output])
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        marked = list(csv.DictReader(f))
    assert ("id" in marked[0]) == ids
    _write(here / "new-results.csv", [{**m, "verdict": grade(m["output"])} for m in marked], ids,
           new)
    _run(capsys, "fix", "new-results.csv")
    code, out = _run(capsys, "check", "new-results.csv")
    return ws, code, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_the_run_after_a_check_takes_on_a_new_judge_is_a_new_starting_point(
        tmp_path, monkeypatch, capsys, ids):
    _, code, out = _checked(tmp_path, monkeypatch, capsys, ids)
    assert code == 0 and "Better" in out, out
    code, out = _run(capsys, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert code == 0, out  # its own result, never "made it worse"
    flat = _flat(out)
    assert before_after.RESTARTED in flat, out
    assert "On the" not in flat.replace("On the page", "") and WORSE not in flat, out
    assert "leans toward" not in flat, out
    assert len(next_lines(before_comparison(out))) == 1, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_a_later_change_of_the_answers_compares_as_usual(tmp_path, monkeypatch, capsys, ids):
    _checked(tmp_path, monkeypatch, capsys, ids)
    _run(capsys, "--no-browser", "--port", "0")  # the new starting point
    _run(capsys, "--stop")
    _, out = _run(capsys, "--no-browser", "--port", "0")  # the same results again
    _run(capsys, "--stop")
    assert "On the" not in _flat(out).replace("On the page", ""), out  # nothing new to compare
    assert before_after.RESTARTED not in _flat(out), out
    with (tmp_path / "new-results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    passed = [row for row in rows if row["verdict"] == "pass"][:4]  # rows come in any order
    assert len(passed) == 4, rows
    for row in passed:  # the agent got 4 answers wrong that it had right: graded so
        row["verdict"] = "fail"
    _write(tmp_path / "new-results.csv", rows, ids)
    _, out = _run(capsys, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert "questions in both results: fixed 0, broke" in _flat(out), out
    assert before_after.RESTARTED not in _flat(out), out


def test_a_check_that_keeps_the_old_judge_leaves_the_comparison_alone(
        tmp_path, monkeypatch, capsys):
    """A check that finds the new grades worse keeps the old LLM-as-a-judge: no new
    starting point, the run after compares as before."""
    def worse(output: str) -> str:  # passes every answer
        return "pass"

    _, _, out = _checked(tmp_path, monkeypatch, capsys, False, grade=worse)
    assert "Worse" in out, out
    _, out = _run(capsys, "new-results.csv", "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert before_after.RESTARTED not in _flat(out), out
    assert "questions in both results:" in _flat(out), out


def test_a_pipeline_right_after_the_check_does_not_fail_on_the_judge_change(
        tmp_path, monkeypatch, capsys):
    _checked(tmp_path, monkeypatch, capsys, False)
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "new-results.csv")
    assert code == 0, out
    assert before_after.RESTARTED in _flat(out) and WORSE not in _flat(out), out


def test_before_with_the_grades_the_check_replaced_is_a_new_starting_point(
        tmp_path, monkeypatch, capsys):
    """--before results.csv, the old LLM-as-a-judge's grades the check replaced: comparing
    them would be about the LLM-as-a-judge, not the answers."""
    _checked(tmp_path, monkeypatch, capsys, False)
    code, out = _run(capsys, "new-results.csv", "--before", "results.csv")
    assert code == 0, out
    assert before_after.RESTARTED in _flat(out) and WORSE not in _flat(out), out


def _plain(capsys) -> tuple[int, str]:
    code, out = _run(capsys, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_after_a_check_plain_runs_read_the_file_it_took_on_when_one_was_named(
        tmp_path, monkeypatch, capsys, ids):
    """The first runs named results.csv, so plain runs read it. After `check new-results.csv`
    took on its LLM-as-a-judge, they read new-results.csv: the run after starts again once,
    and each later change to it is compared (they kept reading results.csv, never compared,
    and said the setup changed each time the other file was read)."""
    _checked(tmp_path, monkeypatch, capsys, ids, named=True,
             models=("judge-mini-1", "judge-mini-2"))
    code, out = _plain(capsys)
    assert code == 0 and before_after.RESTARTED in out, out
    assert READS_NEW in out, out  # the first lines name the file read
    path = tmp_path / "new-results.csv"
    for edit in (1, 2):
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        failed = [r for r in rows if r["verdict"] == "fail"][:edit]
        for r in failed:  # the agent's answer now right, graded so
            r["verdict"], r["output"] = "pass", r["output"] + f" (run {edit})"
        _write(path, rows, ids, "judge-mini-2")
        code, out = _plain(capsys)
        assert code == 0, out
        assert before_after.RESTARTED not in out, out
        assert f"questions in both results: fixed {edit}, broke 0" in out, out
    _write(tmp_path / "results.csv", rows, ids, "judge-mini-2")  # newer, and not the one named
    code, out = _plain(capsys)
    assert code == 0 and READS_NEW in out, out  # said, so the file not read is no surprise


def test_a_named_file_the_check_did_not_take_on_is_still_read(tmp_path, monkeypatch, capsys):
    """A check found worse keeps the old LLM-as-a-judge, and with it the file named."""
    _, _, out = _checked(tmp_path, monkeypatch, capsys, False, grade=lambda output: "pass",
                         named=True, models=("judge-mini-1", "judge-mini-2"))
    assert "Worse" in out, out
    assert json.loads((tmp_path / ".judgekeeper" / "start.json").read_text(
        encoding="utf-8"))["given"] == "results.csv"
