"""The live result page (/result) before there is a result: shown, with nothing written."""

from __future__ import annotations

import pytest

from judgekeeper import start, start_label
from judgekeeper.start_label import StartSession
from tests.start_projects import split, table_project


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    table_project(tmp_path, split(20, 16))
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


def _mark(ws, n: int) -> StartSession:
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:n]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 4})
    return session


def _written(ws) -> list[str]:
    return [p.name for p in (ws.history_jsonl, ws.result_json, ws.report_html) if p.is_file()]


@pytest.mark.parametrize("n", [0, 1, 12])
def test_the_result_page_before_a_result_writes_nothing(ws, n):
    session = _mark(ws, n)
    html = start_label.live_result(ws, session)
    assert html.startswith("<!doctype html>")
    assert _written(ws) == []
    start_label.live_result(ws, session)  # again: still nothing
    assert _written(ws) == []


def test_the_result_page_with_a_result_saves_it(ws):
    session = _mark(ws, 36)
    start_label.live_result(ws, session)
    assert set(_written(ws)) == {ws.history_jsonl.name, ws.result_json.name,
                                 ws.report_html.name}


def test_what_next_asks_for_more_marks_until_fix_can_run(tmp_path, monkeypatch):
    """A judge that passes every answer, 11 Pass and 1 Fail: a result, but `fix` needs more
    marks first; the result page and report.html say so, as the terminal does."""
    import html as html_mod
    import re

    from judgekeeper import fix

    monkeypatch.chdir(tmp_path)
    table_project(tmp_path, [True] * 120)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    session = StartSession(ws)
    for n, item in enumerate(session.items[:12]):
        session.update({"id": item["id"], "label": "fail" if n == 0 else "pass", "seconds": 4})
    assert not fix.can_run(ws)
    page = start_label.live_result(ws, session)
    assert ws.report_html.is_file()
    for text in (page, ws.report_html.read_text(encoding="utf-8")):
        words = " ".join(html_mod.unescape(re.sub(r"<[^>]+>", " ", text)).split())
        nxt = words[words.rindex("What next"):words.rindex("(function")]
        assert fix.NOT_ENOUGH in nxt, nxt
        assert "judgekeeper fix" not in nxt, nxt
        assert "judgekeeper mark" in nxt, nxt
