"""A result made before a mark was taken back is made again from the marks that stand: the
page's Undo right after the last mark never leaves result.json and report.html on a mark
that is gone, so the files, the result page and the terminal say the same."""
from __future__ import annotations

import json

from judgekeeper import start, start_label
from tests.start_projects import split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_label_server import Client
from tests.test_no_grade_popup import _ids, _mark, _serve


def _saved(ws) -> dict:
    return json.loads(ws.result_json.read_text(encoding="utf-8"))


def _round(ws, marks: list[str]):
    """Serve the page, mark the answers with `marks`, open the result (it is saved), then
    take the last mark back as the page's Z does, and open nothing more. (The result saved
    before, the one saved after, report.html after.)"""
    server, thread = _serve(ws)
    try:
        client = Client(server)
        ids = _ids(client)
        for item, label in zip(ids, marks, strict=False):
            _mark(client, item, label)
        resp, _ = client.request("GET", "/result")
        assert resp.status == 200
        before = _saved(ws)
        _mark(client, ids[len(marks) - 1], None)  # Z: the last mark taken back
        return before, _saved(ws), ws.report_html.read_text(encoding="utf-8")
    finally:
        server.stop()
        thread.join(timeout=5)


def test_an_undo_after_a_result_on_answers_with_no_grade_makes_it_again(tmp_path):
    write_answers(tmp_path, 10)
    ws = start_label.prepare(start.find_judge(tmp_path, answers=True), say=lambda line: None)
    before, after, report = _round(ws, ["pass"] * 10)
    assert len(before["marked"]) == 10 and before["check"] == "result"
    assert len(after["marked"]) == 9 and after["check"] != "result"
    assert "You passed 10 of 10" not in report


def test_an_undo_after_a_result_with_an_llm_as_a_judge_makes_it_again(tmp_path):
    table_project(tmp_path, split(20, 20), tag="g")
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    before, after, _ = _round(ws, ["pass" if i % 2 else "fail" for i in range(40)])
    assert before["made"]["marks"] == 40
    assert after["made"]["marks"] == 39
