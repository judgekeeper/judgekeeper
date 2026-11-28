"""After `check` takes on a new LLM-as-a-judge's grades, the next run reading them is a new
starting point: its grades changed because the LLM-as-a-judge did, not the agent or chatbot, so
they are not compared with the grades from before (before_after.RESTARTED). A later change of
the answers compares as usual; a check that keeps the old LLM-as-a-judge leaves it alone."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper import before_after
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.test_front import before_comparison, next_lines

N = 40
WORSE = "Your change made it worse."


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


def _write(path, rows: list[dict], ids: bool) -> None:
    columns = ["input", "output", "verdict"] + (["id"] if ids else [])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _run(capsys, *argv) -> tuple[int, str]:
    capsys.readouterr()
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def _flat(text: str) -> str:
    return " ".join(text.split())


def _checked(here, monkeypatch, capsys, ids: bool, grade=None):
    """The tester's lenient/ flow up to `check NEW`: every answer marked as it truly is, a
    plain run (the old LLM-as-a-judge's result), fix, marked-answers.csv graded again by
    `grade` (the right grade by default) into new-results.csv, `fix` and `check` on it."""
    monkeypatch.chdir(here)
    monkeypatch.delenv("CI", raising=False)
    rows = [{**_row(i), "verdict": _lenient(i), "id": f"q-{i:02}"} for i in range(N)]
    _write(here / "results.csv", rows, ids)
    _run(capsys, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    ws = Workspace(here)
    truth = {r["output"]: "pass" if r["right"] else "fail" for r in rows}
    pool = {json.loads(line)["id"]: json.loads(line)["output"]
            for line in ws.pool.read_text(encoding="utf-8").splitlines() if line.strip()}
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": truth[pool[item["id"]]], "seconds": 5})
    code, out = _run(capsys, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert code == 0 and "needs work" in out, out
    assert _run(capsys, "fix")[0] == 0
    grade = grade or (lambda output: truth[output])
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        marked = list(csv.DictReader(f))
    assert ("id" in marked[0]) == ids
    _write(here / "new-results.csv", [{**m, "verdict": grade(m["output"])} for m in marked], ids)
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
    for row in rows[:4]:  # the agent got 4 answers wrong that it had right: graded so
        if row["verdict"] == "pass":
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
