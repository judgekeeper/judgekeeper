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
