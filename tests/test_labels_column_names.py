"""A labels file's answer and question columns may have the names the results reader takes
(`response`, `query`, ...); a file without them is told which columns it has."""

from __future__ import annotations

import json

import pytest

from judgekeeper.start_label import Workspace
from tests.start_projects import answer, question, table_project
from tests.test_labels_import import _nothing_written, flat, imported, run, write_labels

NEEDS = ("needs an answer column (output, outputs, answer, answers, response, responses, "
         "completion, reply or generation) and a label column (label or human_label).")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("asked, said", [("query", "response"), ("prompt", "completion"),
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


def test_a_file_without_them_is_told_its_columns(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    write_labels(here / "mine.csv", [{"Ticket": question(0), "Bot reply": answer(0),
                                      "Reviewer verdict": "pass", "Reviewer notes": "ok"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3
    assert (f"mine.csv {NEEDS} It has: Ticket, Bot reply, Reviewer verdict, Reviewer notes."
            in flat(out)), out
    _nothing_written(Workspace(here))


def test_a_jsonl_file_without_them_is_told_its_columns(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    (here / "mine.jsonl").write_text(json.dumps({"q": "x", "gold": "pass"}) + "\n",
                                     encoding="utf-8")
    code, out = run(capsys, "--labels", "mine.jsonl")
    assert code == 3 and f"mine.jsonl {NEEDS} It has: q, gold." in flat(out), out
