"""`--tool table` reads a file of answers with no grades (input and output columns) that sits
beside another eval tool's results, as it does when the file is alone."""

from __future__ import annotations

import csv
import json
import os
import re
import time

import pytest

from judgekeeper import project
from tests.start_projects import answer, promptfoo_project, question, split
from tests.test_folder_fuzz import _fresh
from tests.test_folder_matrix import _marked
from tests.test_front import flat, run

PAGE = ("--no-browser", "--port", "0")


def _answers(path, n: int = 12) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output"])
        for i in range(n):
            w.writerow([question(i, "a"), answer(i, "a")])


@pytest.mark.parametrize("marked_first", [False, True])
def test_tool_table_reads_the_answers_beside_promptfoo_results(tmp_path, capsys, monkeypatch,
                                                               marked_first):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    promptfoo_project(tmp_path / "evals", split(15, 15), name="out.json")
    _answers(tmp_path / "answers.csv")
    monkeypatch.chdir(tmp_path)
    if marked_first:  # the session's own file
        assert run(capsys, "answers.csv", *PAGE)[0] == 0
    code, out, err = run(capsys, "--tool", "table", *PAGE)
    said = flat(out + err)
    assert code == 0, said
    assert "No CSV, TSV or JSONL results file found" not in said, said
    assert "answers.csv has no LLM-as-a-judge grades" in said, said
    assert "evals/out.json has LLM-as-a-judge grades" not in said, said


def _jk_files(folder) -> dict:
    """Every file under folder/.judgekeeper, by place (a previous-<date>/ folder by its
    name without the date), with its bytes."""
    return {re.sub(r"previous-[^/]*", "previous-DATE", p.relative_to(folder).as_posix()):
            p.read_bytes() for p in sorted((folder / ".judgekeeper").rglob("*")) if p.is_file()}


def _after_a_run_beside_other_questions(tmp_path, capsys, monkeypatch, marks, where, argv):
    """promptfoo results (40 answers) with a session of `marks` marks, and a newer other.jsonl
    of other questions beside it or in more/; then judgekeeper `argv` there: its exit code and
    the files of .judgekeeper/ that changed."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    evals = tmp_path / "evals"
    promptfoo_project(evals, split(20, 20))
    monkeypatch.chdir(evals)
    project.forget()
    _fresh(monkeypatch)
    assert run(capsys, *PAGE)[0] == 0  # the session: a page to mark results.json on
    _marked(evals, marks)
    other = evals / where / "other.jsonl"
    other.parent.mkdir(exist_ok=True)
    other.write_text("".join(json.dumps({"input": f"Unrelated {i}?", "output": f"Other {i}."})
                             + "\n" for i in range(15)), encoding="utf-8")
    later = time.time() + 60
    os.utime(other, (later, later))
    before = _jk_files(evals)
    project.forget()
    _fresh(monkeypatch)
    code = run(capsys, *argv, *PAGE)[0]
    after = _jk_files(evals)
    return code, sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


@pytest.mark.parametrize("marks", [0, 4, 40])
@pytest.mark.parametrize("where", ["", "more"])
def test_tool_table_beside_a_session_does_what_naming_the_file_does(tmp_path, capsys,
                                                                    monkeypatch, marks, where):
    """A newer file of other questions beside a session on a tool's results: `--tool table`
    asks for that table as naming it does, so both give the same exit code and change the
    same files in .judgekeeper/ (with marks, both ask before starting over and change none)."""
    name = f"{where}/other.jsonl".lstrip("/")
    named = _after_a_run_beside_other_questions(tmp_path / "named", capsys, monkeypatch, marks,
                                                where, (name,))
    asked = _after_a_run_beside_other_questions(tmp_path / "table", capsys, monkeypatch, marks,
                                                where, ("--tool", "table"))
    assert asked == named
    code, changed = named
    assert (code, bool(changed)) == ((0, True) if marks == 0 else (3, False))
