"""`--tool table` reads a file of answers with no grades (input and output columns) that sits
beside another eval tool's results, as it does when the file is alone."""

from __future__ import annotations

import csv

import pytest

from tests.start_projects import answer, promptfoo_project, question, split
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
