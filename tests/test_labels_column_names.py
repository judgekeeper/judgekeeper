"""A labels file's answer and question columns may have the names the results reader takes
(`response`, `query`, ...)."""

from __future__ import annotations

import json

import pytest

from judgekeeper.start_label import Workspace
from tests.start_projects import answer, question, table_project
from tests.test_labels_import import flat, imported, run, write_labels


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
