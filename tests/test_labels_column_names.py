"""A labels file's answer column may have any name the results reader takes (`response`,
`completion`, ...), its question column `input`, `question` or `query`; a file without them is
told which columns it needs. A question that finds no answer falls back to the answer text."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper.start_label import Workspace
from tests.start_projects import answer, question, table_project
from tests.test_labels_import import _nothing_written, flat, imported, run, write_labels

NEEDS = ("needs an answer column (output or answer) and a label column (label or "
         "human_label).")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("asked, said", [("query", "response"), ("input", "completion"),
                                         ("Question", "Reply")])
def test_the_results_readers_names_are_read(here, capsys, asked, said):
    table_project(here, [True] * 20 + [False] * 20)
    write_labels(here / "mine.csv", [{asked: question(i), said: answer(i), "label": "fail"}
                                     for i in range(3)])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 3 marks from mine.csv (0 Pass, 3 Fail)." in flat(out), out
    ws = Workspace(here)
    rows = {json.loads(x)["id"]: json.loads(x)
            for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    assert sorted(rows[i]["input"] for i in imported(ws)) == [question(i) for i in range(3)]


def test_a_file_without_them_is_told_the_columns_it_needs(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    write_labels(here / "mine.csv", [{"Ticket": question(0), "Bot reply": answer(0),
                                      "Reviewer verdict": "pass", "Reviewer notes": "ok"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    assert f"mine.csv {NEEDS}" in flat(out) and "It has" not in out, out
    _nothing_written(Workspace(here))


def test_a_jsonl_file_without_them_is_told_the_columns_it_needs(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    (here / "mine.jsonl").write_text(json.dumps({"q": "x", "gold": "pass"}) + "\n",
                                     encoding="utf-8")
    code, out = run(capsys, "--labels", "mine.jsonl")
    assert code == 3 and f"mine.jsonl {NEEDS}" in flat(out) and "It has" not in out, out


def _same_text_twice(root) -> None:
    """40 graded answers where answers 0 and 1 have the same text."""
    with (root / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        for i in range(40):
            w.writerow([question(i), answer(0) if i == 1 else answer(i),
                        "pass" if i < 20 else "fail"])


def test_a_prompt_column_is_not_the_question(here, capsys):
    """A `prompt` column holding a whole template is no question: the label finds its answer
    by the answer text, as in 1.0.2."""
    table_project(here, [True] * 20 + [False] * 20)
    write_labels(here / "mine.csv", [{"output": answer(i), "label": "fail",
                                      "prompt": f"You are a support bot. Answer: {question(i)}"}
                                     for i in range(3)])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 3 marks from mine.csv (0 Pass, 3 Fail)." in flat(out), out
    assert "Skipped" not in out, out


def test_a_wrong_question_falls_back_to_the_answer(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    write_labels(here / "mine.csv", [{"output": answer(4), "label": "fail",
                                      "question": "Not this question?"}])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 1 mark from mine.csv (0 Pass, 1 Fail)." in flat(out), out


def test_a_wrong_question_with_an_answer_text_twice_is_more_than_one(here, capsys):
    _same_text_twice(here)
    write_labels(here / "mine.csv", [
        {"output": answer(0), "label": "fail", "question": "Not this question?"},
        {"output": answer(5), "label": "fail", "question": question(5)}])
    _, out = run(capsys, "--labels", "mine.csv")
    text = flat(out)
    assert "Added 1 mark from mine.csv (0 Pass, 1 Fail)." in text, out
    assert ("Skipped 1 label: 1 matches more than one answer (add a question column to tell "
            "them apart)") in text, out


def test_the_right_question_still_tells_answers_with_the_same_text_apart(here, capsys):
    _same_text_twice(here)
    write_labels(here / "mine.csv", [{"output": answer(0), "label": "fail",
                                      "question": question(1)}])
    _, out = run(capsys, "--labels", "mine.csv")
    assert "Added 1 mark from mine.csv (0 Pass, 1 Fail)." in flat(out), out
    ws = Workspace(here)
    rows = {json.loads(x)["id"]: json.loads(x)
            for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    assert [rows[i]["input"] for i in imported(ws)] == [question(1)]
