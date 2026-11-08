"""The file `fix` hands back keeps its two columns, question and answer, for every tool. A file
named to `fix` or `check` with a verdict column and no input or output column reads question as
input and answer as output, so the file goes back as it is, with a grade column added. A table
judgekeeper can't read is told its columns."""

from __future__ import annotations

import csv

import pytest

from judgekeeper.table import as_marked
from tests.test_only_reads import person, project, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


@pytest.mark.parametrize("tool", ["jsonl", "promptfoo"])
def test_marked_answers_keep_question_and_answer(here, capsys, monkeypatch, tool):
    ws = project(tool, here, monkeypatch)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    assert _rows(ws.dir / "fix" / "marked-answers.csv")[0] == ["question", "answer"]


def _graded_again(here, ws) -> str:
    """marked-answers.csv as it was handed out, with a verdict column: the person's own marks."""
    from tests.start_projects import answer

    rows = _rows(ws.dir / "fix" / "marked-answers.csv")
    index = {answer(i): i for i in range(40)}
    with (here / "results-v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([*rows[0], "verdict"])
        for q, a in rows[1:]:
            w.writerow([q, a, "pass" if person(index[a]) else "fail"])
    return "results-v2.csv"


@pytest.mark.parametrize("step", ["fix", "check"])
def test_marked_answers_with_a_verdict_go_back_as_they_are(here, capsys, monkeypatch, step):
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    code, out = run(capsys, step, _graded_again(here, ws))
    said = " ".join(out.split())
    assert code != 2, said
    assert "not a results file" not in said and "looks like another eval" not in said, said


def test_question_and_answer_are_read_only_beside_a_grade_and_never_over_input_or_output():
    assert as_marked(["question", "answer", "verdict"]) == ["input", "output", "verdict"]
    assert as_marked(["Input", "question", "output", "answer", "verdict"]) == [
        "input", "question", "output", "answer", "verdict"]
    assert as_marked(["question", "output_a", "output_b", "answer", "verdict"]) == [
        "input", "output_a", "output_b", "answer", "verdict"]
    assert as_marked(["question", "answer", "score"]) == ["question", "answer", "score"]


def test_a_table_judgekeeper_cannot_read_is_told_its_columns(here, capsys, monkeypatch):
    project("jsonl", here, monkeypatch)
    capsys.readouterr()
    (here / "results-v2.csv").write_text("prompt,reply,verdict\nq,a,pass\n", encoding="utf-8")
    code, out = run(capsys, "fix", "results-v2.csv")
    assert code == 2, out
    said = " ".join(out.split())
    assert "results-v2.csv is not a results file judgekeeper can read" in said, said
    assert "Its columns are prompt, reply and verdict, so judgekeeper can't read it." in said, said
