"""`judgekeeper fix <file>` and `judgekeeper check <file>` on a person's own table, graded again
by their own code: which marked answers the file holds, and what a file that holds too few of
them (missing, `error`, or a grade judgekeeper doesn't know) may and may not say.

The project: 60 answers, one in three BAD (the person fails those), the LLM-as-a-judge wrong on
every fifth. No test calls an API.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import random
import re

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.test_fix import closed

N = 60
COLUMNS = ("input", "output", "verdict", "reason", "model")


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "returns-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def _bad(i: int) -> bool:
    return i % 3 == 0


def _row(i: int) -> dict:
    """Answer i, graded by the LLM-as-a-judge: as the person sees it, but wrong on every fifth."""
    person = "fail" if _bad(i) else "pass"
    judge = person if i % 5 else {"pass": "fail", "fail": "pass"}[person]
    output = (f"Answer {i}: BAD made-up wrong answer." if _bad(i)
              else f"Answer {i}: 30 days with a receipt.")
    return {"input": f"Question {i}: what is the return policy?", "output": output,
            "verdict": judge, "reason": f"reason {i}", "model": "gpt-4.1-mini"}


def _write(path, rows, columns=COLUMNS) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def project(root, ids: bool = False) -> Workspace:
    """The 60 answers (with the table's own ids 1..60 when `ids`), every one marked, then
    `judgekeeper fix`: half of the marks are kept aside."""
    rows = [({"id": str(i + 1)} if ids else {}) | _row(i) for i in range(N)]
    _write(root / "results.csv", rows, (("id",) if ids else ()) + COLUMNS)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--no-browser"]) == 0
        ws = Workspace(root)
        closed(ws)
        session = StartSession(ws)
        pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
        for item in session.items:
            bad = "BAD" in pool[item["id"]]["output"]
            session.update({"id": item["id"], "label": "fail" if bad else "pass",
                            "seconds": 5})
        assert main(["fix"]) == 0
    return ws


def marked_answers(ws: Workspace) -> list[dict]:
    """fix/marked-answers.csv, as the person's code reads it."""
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def perfect(answer: str) -> str:
    return "fail" if "BAD" in answer else "pass"


def regraded(ws: Workspace, grade=perfect, ids: bool = False) -> list[dict]:
    """marked-answers.csv graded again by the person's own code, rows in the file's order,
    numbered 1.. when `ids` (a new numbering: the file has no ids)."""
    out = []
    for n, r in enumerate(marked_answers(ws), 1):
        row = {"input": r["question"], "output": r["answer"], "verdict": grade(r["answer"]),
               "reason": "new", "model": "gpt-4.1-mini"}
        out.append(({"id": str(n)} if ids else {}) | row)
    return out


def write(root, name: str, rows) -> str:
    columns = (("id",) if rows and "id" in rows[0] else ()) + COLUMNS
    _write(root / name, rows, columns)
    return name


def run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


# Answers are found by their text: a table's own ids are a new numbering ------------------------

def test_a_table_renumbered_in_another_order_is_matched_by_text(here, capsys):
    ws = project(here, ids=True)
    capsys.readouterr()
    code, out = run(capsys, "fix", write(here, "new.csv", regraded(ws, ids=True)))
    assert code == 0, out
    assert "Result: your new rule is better." in out
    assert "none from right to wrong" in out


def test_check_on_a_renumbered_table_finds_no_drop(here, capsys):
    project(here, ids=True)
    capsys.readouterr()
    rows = [{"id": str(i + 1)} | _row(i) | {"verdict": perfect(_row(i)["output"])}
            for i in range(N)]
    random.Random(1).shuffle(rows)
    for n, row in enumerate(rows, 1):
        row["id"] = str(n)
    code, out = run(capsys, "check", write(here, "new.csv", rows))
    assert code == 0, out
    assert "worse" not in out.lower()


def test_same_ids_with_other_answers_are_not_there(here, capsys):
    """A new app version: the same ids, every answer worded anew. None of the marked answers is
    in the file."""
    project(here, ids=True)
    capsys.readouterr()
    rows = [{"id": str(i + 1)} | _row(i) for i in range(N)]
    for row in rows:
        row["output"] = row["output"].replace("Answer", "Reply")
        row["verdict"] = "pass"
    code, out = run(capsys, "check", write(here, "new.csv", rows))
    assert code == 3, out
    assert "None of your" in out


# Answers kept aside with no grade: never "better" ------------------------------------------------

def _number(answer: str) -> int:
    return int(re.search(r"Answer (\d+):", answer)[1])


def broken_kept_aside(ws: Workspace) -> set[str]:
    """The answers kept aside that the old LLM-as-a-judge got right, every other one: the ones
    a new rule breaks."""
    split = json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))
    pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
    right = sorted((pool[i]["output"] for i in split["hidden"] if _number(pool[i]["output"]) % 5),
                   key=_number)
    return set(right[::2])


def breaking(ws: Workspace, how: str) -> list[dict]:
    """A new rule that fixes every mistake kept aside and breaks some answers it had right,
    whose grades are then `how`: "wrong", "error", "good" (a word judgekeeper doesn't know),
    or "dropped" from the file."""
    broken = broken_kept_aside(ws)
    rows = []
    for row in regraded(ws):
        if row["output"] in broken:
            if how == "dropped":
                continue
            row["verdict"] = {"wrong": {"pass": "fail", "fail": "pass"}[row["verdict"]],
                              "error": "error", "good": "good"}[how]
        rows.append(row)
    return rows


def test_the_new_rule_breaking_answers_is_seen(here, capsys):
    ws = project(here)
    capsys.readouterr()
    code, out = run(capsys, "fix", write(here, "new.csv", breaking(ws, "wrong")))
    assert code == 0, out
    assert "Result: your new rule is better" not in out and "Result: safe to try" not in out
    assert "Result: can't tell yet. That leans toward worse." in out


@pytest.mark.parametrize("how, why", [
    ("error", "have no decision from your LLM-as-a-judge (such as an error)"),
    ("dropped", "are not in the file")])
def test_answers_kept_aside_with_no_grade_never_read_better(here, capsys, how, why):
    ws = project(here)
    capsys.readouterr()
    k = len(broken_kept_aside(ws))
    code, out = run(capsys, "fix", write(here, "new.csv", breaking(ws, how)))
    assert code == 3, out
    assert (f"Result: can't tell. {k} of the 30 answers kept aside have no grade in your new "
            f"results: {k} {why}.") in out
    assert "Result: your new rule is better" not in out and "Result: safe to try" not in out
    assert "Next: grade every answer in .judgekeeper/fix/marked-answers.csv again" in out
    split = json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))
    assert split["tests"] == []  # no test used up


def test_one_error_kept_aside_is_not_safe_to_try(here, capsys):
    ws = project(here)
    capsys.readouterr()
    (one,) = sorted(broken_kept_aside(ws), key=_number)[:1]
    rows = [r | {"verdict": "error"} if r["output"] == one else r for r in regraded(ws)]
    code, out = run(capsys, "fix", write(here, "new.csv", rows))
    assert code == 3, out
    assert "1 of the 30 answers kept aside has no grade" in out
    assert "1 has no decision" in out


def test_a_grade_word_judgekeeper_does_not_know_is_refused(here, capsys):
    ws = project(here)
    capsys.readouterr()
    code, out = run(capsys, "fix", write(here, "new.csv", breaking(ws, "good")))
    assert code == 3, out
    assert ("judgekeeper can't tell which of the grades in new.csv mean Pass and which mean "
            "Fail: good. It never guesses.") in out
    assert "Next: grade each answer with the grade words your marked results use, then run " \
           "`judgekeeper fix new.csv` again." in out
    assert "Result" not in out


# check: "has not changed" only when the results hold the marked answers ------------------------

def _shapes(ws: Workspace) -> dict[str, list[dict]]:
    """New results that hold none of the marked answers with a grade."""
    same = [_row(i) for i in range(N)]
    return {
        "unrelated": [_row(i) | {"input": f"Question {i}: where is my parcel?",
                                 "output": f"Parcel {i} is on its way."} for i in range(N)],
        "other-question": [r | {"input": "A different question?"} for r in same],
        "zwsp": [r | {"output": r["output"].replace(" ", " \u200b", 1)} for r in same],
        "all-error": [r | {"verdict": "error"} for r in same],
    }


@pytest.mark.parametrize("shape", ["unrelated", "other-question", "zwsp", "all-error"])
def test_check_on_results_without_the_marked_answers_cant_tell(here, capsys, shape):
    ws = project(here)
    capsys.readouterr()
    code, out = run(capsys, "check", write(here, "new.csv", _shapes(ws)[shape]))
    assert code == 3, out
    assert "has not changed" not in out and "nothing to do" not in out
    if shape == "all-error":
        assert ("None of your 60 marked answers has a grade in your new results: 60 are there "
                "with no decision from your LLM-as-a-judge (such as an error).") in out
    else:
        assert "None of your 60 marked answers is in your new results." in out


def test_check_on_unknown_grade_words_refuses_them(here, capsys):
    project(here)
    capsys.readouterr()
    rows = [_row(i) | {"verdict": "good"} for i in range(N)]
    code, out = run(capsys, "check", write(here, "new.csv", rows))
    assert code == 3, out
    assert "mean Pass and which mean Fail: good. It never guesses." in out
    assert "has not changed" not in out


def test_check_on_a_few_marked_answers_cant_tell(here, capsys):
    project(here)
    capsys.readouterr()
    rows = [_row(i) for i in range(N)][:20] + [_row(i) | {"verdict": "error"}
                                               for i in range(20, N)]
    code, out = run(capsys, "check", write(here, "new.csv", rows))
    assert code == 3, out
    assert "40 of your 60 marked answers had no grade in your new results" in out
    assert "40 of them are there with no decision" in out
    assert "Result: can't tell yet." in out and "has not changed" not in out


def test_check_past_the_row_cap_cant_tell(here, capsys):
    """The marked answers after the first 100,000 rows read."""
    project(here)
    capsys.readouterr()
    rows = [_row(i) | {"input": f"Other question {i}?", "output": f"Other answer {i}."}
            for i in range(100_000)] + [_row(i) for i in range(N)]
    code, out = run(capsys, "check", write(here, "new.csv", rows))
    assert code == 3, out
    assert "None of your 60 marked answers is in your new results." in out


def test_plain_check_on_new_results_without_the_marked_answers_says_so_each_time(here,
                                                                                capsys):
    ws = project(here)
    capsys.readouterr()
    _write(here / "results.csv", _shapes(ws)["unrelated"])
    for _ in range(2):
        code, out = run(capsys, "check")
        assert code == 3, out
        assert "None of your 60 marked answers is in your new results." in out


# An eval tool version pinned in the project ------------------------------------------------------

def test_the_original_file_with_a_pinned_version_is_the_same_grades(here, capsys):
    """DeepEval pinned in pyproject.toml, results in a folder: the pin is the project's, read
    the same for the file given back as for the project."""
    from tests.start_projects import deepeval_project

    (here / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["deepeval==4.3.1"]\n',
        encoding="utf-8")
    verdicts = [True] * 25 + [False] * 25
    results = deepeval_project(here, verdicts,
                               name="deepeval-results/test_run_20261027_100000.json")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert main(["--no-browser"]) == 0
        ws = Workspace(here)
        closed(ws)
        session = StartSession(ws)
        for n, item in enumerate(session.items):
            label = session.groups[item["id"]]
            if n % 5 == 0:
                label = {"pass": "fail", "fail": "pass"}[label]
            session.update({"id": item["id"], "label": label, "seconds": 5})
        assert main(["fix"]) == 0
    capsys.readouterr()
    given = results.relative_to(here)
    code, out = run(capsys, "fix", given)
    assert code == 3, out
    assert "These are the same grades as when you marked" in out
    assert json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))["tests"] == []
    code, out = run(capsys, "check", given)
    assert code == 0, out
    assert "has not changed" in out and "version unknown" not in out


def test_a_new_rule_that_changes_no_grade_is_not_safe_to_try(here, capsys):
    ws = project(here)
    capsys.readouterr()
    old = {r["output"]: r["verdict"] for r in (_row(i) for i in range(N))}
    rows = regraded(ws, grade=lambda a: old[a])
    for r in rows:
        r["reason"] = "Another rule, the same grades."
    code, out = run(capsys, "fix", write(here, "new.csv", rows))
    assert code == 3, out
    assert "Result" not in out and "safe to try" not in out


# A PATH that is neither a results file nor the project folder --------------------------------

def _odd_path(root, kind: str) -> str:
    import os

    if kind == "missing":
        return "new.csv"
    if kind == "dangling link":
        os.symlink(root / "gone.csv", root / "new.csv")
        return "new.csv"
    if kind == "named pipe":
        os.mkfifo(root / "new.csv")
        return "new.csv"
    if kind == "device":
        return os.devnull
    (root / "new").mkdir()
    write(root / "new", "results.csv", [_row(i) for i in range(N)])
    return "new"


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="no named pipes")
@pytest.mark.parametrize("command", ["fix", "check"])
@pytest.mark.parametrize("kind, said", [
    ("missing", "There is no file or folder named new.csv here."),
    ("dangling link", "There is no file or folder named new.csv here."),
    ("named pipe", "new.csv isn't a regular file: it is a named pipe."),
    ("device", "null isn't a regular file: it is a special file."),
    ("folder", ("new is a folder inside your project, not a results file or your project "
                "folder."))])
def test_a_path_that_is_not_a_results_file_is_refused(here, capsys, command, kind, said):
    project(here)
    capsys.readouterr()
    code, out = run(capsys, command, _odd_path(here, kind))
    assert code == 2, out
    assert said in out
    assert "Where your LLM-as-a-judge goes wrong" not in out and "has not changed" not in out


def test_the_project_folder_by_its_path_still_works(here, capsys):
    project(here)
    capsys.readouterr()
    assert run(capsys, "fix", str(here))[0] == 0
    code, out = run(capsys, "check", str(here))
    assert code == 0 and "has not changed" in out, out


def test_check_on_logs_in_two_folders_says_to_choose_in_its_next_line(tmp_path, monkeypatch,
                                                                     capsys):
    """A regraded Inspect log written beside the project, not in logs/: check can't tell
    which logs to read, and its Next: line says what its text says."""
    from tests.start_projects import inspect_data, split

    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.json").write_text(json.dumps(inspect_data(split(20, 20))),
                                              encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["--no-browser"]) == 0
    ws = Workspace(tmp_path)
    closed(ws)
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": session.groups[item["id"]], "seconds": 5})
    (tmp_path / "new.json").write_text(json.dumps(inspect_data(split(20, 20))), encoding="utf-8")
    capsys.readouterr()
    code = main(["check"])
    out = " ".join(capsys.readouterr().out.split())
    assert code == 3 and "they need a choice first" in out, out
    assert out.endswith("Next: run `judgekeeper` to make that choice, then run `judgekeeper "
                        "check` again.")
