"""The file `fix` hands back has two columns: for a CSV, TSV or JSONL file of the person's own,
its question and answer columns as the file names them (input and output), so their grader runs
on it as it is; for every other tool, question and answer. A file named to `fix` or `check` with
a verdict column and no input or output column reads question as input and answer as output, so
the file goes back as it is, with a grade column added. A table judgekeeper can't read is told
its columns."""

from __future__ import annotations

import csv

import pytest

from judgekeeper.start_label import Workspace
from judgekeeper.table import as_marked
from tests.start_projects import answer, question
from tests.test_only_reads import closed, judge, main, mark_all, only_reads, person, project, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


@pytest.mark.parametrize("tool, header", [("jsonl", ["input", "output"]),
                                          ("promptfoo", ["question", "answer"])])
def test_marked_answers_take_the_results_file_s_columns_for_a_table(here, capsys, monkeypatch,
                                                                     tool, header):
    ws = project(tool, here, monkeypatch)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    assert _rows(ws.dir / "fix" / "marked-answers.csv")[0] == header


def test_marked_answers_use_the_column_names_as_the_file_writes_them(here, capsys, monkeypatch):
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Input", "Output", "Verdict"])
        for i in range(40):
            w.writerow([question(i), answer(i), "pass" if judge(i) else "fail"])
    with only_reads(monkeypatch):
        assert main(["--no-browser"]) == 0
    ws = Workspace(here)
    mark_all(ws)
    with only_reads(monkeypatch):
        closed(ws)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    rows = _rows(ws.dir / "fix" / "marked-answers.csv")
    assert rows[0] == ["Input", "Output"]
    assert "`Input`, `Output`, `Verdict`" in " ".join(out.split()), out
    index = {answer(i): i for i in range(40)}
    with (here / "results-v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([*rows[0], "Verdict"])
        for q, a in rows[1:]:
            w.writerow([q, a, "pass" if person(index[a]) else "fail"])
    for command in ("fix", "check"):
        code, out = run(capsys, command, "results-v2.csv")
        assert code == 0, out
        assert "can't read" not in " ".join(out.split()), out


def test_a_grader_reading_input_runs_on_the_file_and_fix_reads_its_grades(here, capsys,
                                                                          monkeypatch):
    """A grader written for the results file (it reads `input` and `output`) on
    marked-answers.csv as it is, saving its grade in a verdict column."""
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    index = {answer(i): i for i in range(40)}
    with (here / "results-v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["input", "output", "verdict"])
        w.writeheader()
        for row in rows:
            w.writerow({"input": row["input"], "output": row["output"],
                        "verdict": "pass" if person(index[row["output"]]) else "fail"})
    code, out = run(capsys, "fix", "results-v2.csv")
    said = " ".join(out.split())
    assert code == 0, said
    assert "New rule: When you say Pass: agrees on 9 of 9 When you say Fail: agrees on 11 of 11" \
        in said, said


def _graded_again(here, ws) -> str:
    """marked-answers.csv as it was handed out, with a verdict column: the person's own marks."""
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
