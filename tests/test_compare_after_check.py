"""After `check` takes on a new LLM-as-a-judge's grades, the next run reading them is a new
starting point: its grades changed because the LLM-as-a-judge did, not the agent or chatbot, so
they are not compared with the grades from before (before_after.RESTARTED). A later change of
the answers compares as usual; a check that keeps the old LLM-as-a-judge leaves it alone."""

from __future__ import annotations

import csv
import json
import os
import shutil
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


def _worse(output: str) -> str:  # passes every answer
    return "pass"


def _baseline(here) -> str:
    return (here / ".judgekeeper" / before_after.FILE).read_text(encoding="utf-8")


def test_a_run_on_the_judge_a_check_found_worse_compares_nothing(tmp_path, monkeypatch, capsys):
    """A check that finds the new grades worse keeps the old LLM-as-a-judge: a run on the
    refused one's grades is about the old one's numbers, so it compares nothing and keeps
    the last grades read (a table: no model named)."""
    _, _, out = _checked(tmp_path, monkeypatch, capsys, False, grade=_worse)
    assert "Worse" in out, out
    kept = _baseline(tmp_path)
    _, out = _run(capsys, "new-results.csv", "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert before_after.RESTARTED not in _flat(out), out
    assert "questions in both results:" not in _flat(out) and WORSE not in _flat(out), out
    assert _baseline(tmp_path) == kept


def test_after_a_worse_check_a_change_of_the_answers_by_the_old_judge_still_compares(
        tmp_path, monkeypatch, capsys):
    """Named models: the run on the refused judge-c's file says the numbers still use the
    old grades, then nothing starts again (it said the setup changed and kept judge-c's
    grades, so the next runs, back on judge-a, said it again and compared nothing)."""
    _, _, out = _checked(tmp_path, monkeypatch, capsys, True, grade=_worse,
                         models=("judge-a", "judge-c"))
    assert "Worse" in out, out
    kept = _baseline(tmp_path)
    for argv in ([], ["results.csv"]):  # the newest file, then the one the marks test
        code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
        _run(capsys, "--stop")
        assert before_after.RESTARTED not in _flat(out), out
        assert "questions in both results:" not in _flat(out), out
    assert _baseline(tmp_path) == kept
    with (tmp_path / "results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    passed = [r for r in rows if r["verdict"] == "pass"][:8]
    for r in passed:  # the agent now gets 8 answers wrong, graded so by judge-a
        r["verdict"] = "fail"
    _write(tmp_path / "results.csv", rows, True, "judge-a")
    code, out = _run(capsys, "results.csv", "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    assert code == 1, out
    assert "questions in both results: fixed 0, broke 8" in _flat(out), out
    assert WORSE in _flat(out) and before_after.RESTARTED not in _flat(out), out


def test_a_pipeline_right_after_the_check_does_not_fail_on_the_judge_change(
        tmp_path, monkeypatch, capsys):
    _checked(tmp_path, monkeypatch, capsys, False)
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "new-results.csv")
    assert code == 0, out
    assert before_after.RESTARTED in _flat(out) and WORSE not in _flat(out), out


@pytest.mark.parametrize("ci", [False, True], ids=["run", "pipeline"])
def test_before_right_after_a_check_compares_two_files_of_one_judge(
        tmp_path, monkeypatch, capsys, ci):
    """--before names the two results compared: both graded by judge-v1, they are compared
    at once, whatever the check took on (it said the setup changed and exited 0)."""
    _checked(tmp_path, monkeypatch, capsys, True, models=("judge-v1", "judge-v2"))
    with (tmp_path / "results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    _write(tmp_path / "main-results.csv", rows, True, "judge-v1")
    passed = [r for r in rows if r["verdict"] == "pass"][:12]
    for r in passed:
        r["verdict"] = "fail"
    _write(tmp_path / "results.csv", rows, True, "judge-v1")
    if ci:
        monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "results.csv", "--before", "main-results.csv")
    assert code == 1, out
    assert "questions in both results: fixed 0, broke 12" in _flat(out), out
    assert before_after.RESTARTED not in _flat(out), out


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


def test_after_a_worse_check_new_results_of_the_old_judge_are_compared_in_a_plain_run(
        tmp_path, monkeypatch, capsys):
    """After the Worse check, a plain run (on the refused judge-c's file), then results-a2.csv:
    the agent changed, graded by judge-a, the judge the marks test. Compared with the grades
    judge-a gave before: worse, exit 1 (it said the setup changed and exited 0)."""
    _, _, out = _checked(tmp_path, monkeypatch, capsys, True, grade=_worse,
                         models=("judge-a", "judge-c"))
    assert "Worse" in out, out
    kept = _baseline(tmp_path)
    code, out = _plain(capsys)
    assert before_after.RESTARTED not in out and "questions in both results:" not in out, out
    assert _baseline(tmp_path) == kept
    with (tmp_path / "results.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    passed = [r for r in rows if r["verdict"] == "pass"]
    assert len(passed) >= 18, rows
    for r in passed[:18]:
        r["verdict"] = "fail"
    _write(tmp_path / "results-a2.csv", rows, True, "judge-a")
    code, out = _plain(capsys)
    assert code == 1, out
    assert "questions in both results: fixed 0, broke 18" in out, out
    assert before_after.RESTARTED not in out, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
@pytest.mark.parametrize("other", ["copy.csv", "results.csv"])
def test_a_before_run_after_the_check_leaves_the_new_starting_point(
        tmp_path, monkeypatch, capsys, ids, other):
    """Right after a check took on judge-b, a --before run (a copy of the new results, or
    the old judge-a file) says what it says, and the next plain run is still the new
    starting point: the --before run had kept judge-a's grades as the ones before, so the
    plain run compared judge-a with judge-b ("broke 18 ... made it worse", exit 1). A later
    change graded by judge-b is compared."""
    _checked(tmp_path, monkeypatch, capsys, ids, models=("judge-a", "judge-b"))
    shutil.copy2(tmp_path / "new-results.csv", tmp_path / "copy.csv")
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "new-results.csv", "--before", other)
    assert code == (0 if other == "copy.csv" else 3), out
    code, out = _run(capsys)
    flat = _flat(out)
    assert code == 0, out
    assert before_after.RESTARTED in flat and WORSE not in flat, out
    assert "questions in both results:" not in flat, out
    path = tmp_path / "new-results.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    passed = [r for r in rows if r["verdict"] == "pass"][:8]
    for r in passed:  # the agent now gets 8 answers wrong, graded so by judge-b
        r["verdict"] = "fail"
    _write(path, rows, ids, "judge-b")
    code, out = _run(capsys, "new-results.csv")
    assert code == 1, out
    assert "questions in both results: fixed 0, broke 8" in _flat(out), out


def test_a_before_run_on_another_judge_leaves_the_last_grades_alone(tmp_path, monkeypatch,
                                                                     capsys):
    """The last grades read are judge-b's. A --before run on two files graded by judge-c
    compares them and leaves judge-b's grades as the last ones read: the next plain run on
    judge-c's file compares nothing across the two (the --before run had kept judge-b's
    grades as the ones before judge-c's)."""
    _checked(tmp_path, monkeypatch, capsys, True, models=("judge-a", "judge-b"))
    _plain(capsys)  # the new starting point: judge-b's grades are the last read
    kept = _baseline(tmp_path)
    with (tmp_path / "new-results.csv").open(encoding="utf-8", newline="") as f:
        rows = [{**r, "verdict": "pass"} for r in csv.DictReader(f)]  # judge-c passes all
    _write(tmp_path / "other.csv", rows, True, "judge-c")
    shutil.copy2(tmp_path / "other.csv", tmp_path / "other-copy.csv")
    monkeypatch.setenv("CI", "true")
    code, out = _run(capsys, "other.csv", "--before", "other-copy.csv")
    assert code == 0 and "questions in both results: fixed 0, broke 0" in _flat(out), out
    assert _baseline(tmp_path) == kept
    code, out = _run(capsys, "other.csv")
    assert code == 0, out
    assert "questions in both results:" not in _flat(out) and WORSE not in _flat(out), out
