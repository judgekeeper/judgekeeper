"""The marking page's one-time "Your result is ready." pop-up on answers with no grade: it
comes with the 10th mark, once, and never again for that folder (ready-seen.json), and its
link opens the result page made for answers with no grade."""
from __future__ import annotations

import threading

import pytest

from judgekeeper import page, start, start_label
from judgekeeper.report_page import RATE, own_line
from tests.test_answers_without_grades import JUDGE_WORDS, _seen, write_answers
from tests.test_label_server import Client


@pytest.fixture
def ws(tmp_path):
    write_answers(tmp_path, 14)
    ws = start_label.prepare(start.find_judge(tmp_path, answers=True), say=lambda line: None)
    assert ws.data()["graded"] is False
    return ws


def _serve(ws):
    server = page.page_server(ws, 0)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def served(ws):
    """Serve the marking page; `served.again()` stops it and serves a new one on the same
    folder, as `judgekeeper mark` would."""
    running = []

    class Served:
        def start(self):
            running.append(_serve(ws))
            return Client(running[-1][0])

        def again(self):
            server, thread = running.pop()
            server.stop()
            thread.join(timeout=5)
            return self.start()

    s = Served()
    s.client = s.start()
    yield s
    for server, thread in running:
        server.stop()
        thread.join(timeout=5)


def _ids(client) -> list[str]:
    return [i["id"] for i in client.state()["items"]]


def _mark(client, item: str, label: str | None) -> dict:
    status, body = client.label(id=item, label=label, seconds=3)
    assert status == 200, body
    return body["summary"]


def _marks(n: int) -> list[str]:
    return ["pass" if i % 3 else "fail" for i in range(n)]


def test_nine_marks_are_not_ready_and_bring_no_pop_up(ws, served):
    client = served.client
    for item, label in zip(_ids(client), _marks(9), strict=False):
        summary = _mark(client, item, label)
        assert not summary["status"]["ready"] and "popup" not in summary
    assert not ws.ready_seen.is_file()


def test_the_tenth_mark_brings_the_pop_up_once(ws, served):
    client = served.client
    said = [_mark(client, item, label)
            for item, label in zip(_ids(client), _marks(10), strict=False)]
    assert [s.get("popup", False) for s in said] == [False] * 9 + [True]
    assert said[-1]["status"]["ready"] and ws.ready_seen.is_file()


def test_no_pop_up_again_after_the_eleventh_mark_a_reload_or_a_new_page(ws, served):
    client = served.client
    ids = _ids(client)
    for item, label in zip(ids, _marks(10), strict=False):
        _mark(client, item, label)
    summary = _mark(client, ids[10], "pass")  # the 11th
    assert summary["status"]["ready"] and "popup" not in summary
    assert client.state()["status"]["ready"]  # a reload
    assert "popup" not in _mark(client, ids[11], "fail")
    client = served.again()  # a new page on the same folder
    assert client.state()["status"]["ready"]
    assert "popup" not in _mark(client, ids[12], "pass")


def test_marks_back_under_ten_and_up_again_bring_no_second_pop_up(ws, served):
    client = served.client
    ids = _ids(client)
    said = [_mark(client, item, label) for item, label in zip(ids, _marks(10), strict=False)]
    assert said[-1].get("popup") is True
    back = _mark(client, ids[9], None)  # a mark taken back: 9 marks
    assert not back["status"]["ready"] and "popup" not in back
    again = _mark(client, ids[9], "pass")  # 10 again
    assert again["status"]["ready"] and "popup" not in again
    for item in ids[8:10]:  # 8, then 10 again on a new page
        _mark(client, item, None)
    client = served.again()
    said = [_mark(client, item, "fail") for item in ids[8:10]]
    assert said[-1]["status"]["ready"] and not any("popup" in s for s in said)


def test_the_pop_up_links_to_the_result_page_for_answers_with_no_grade(ws, served):
    client = served.client
    resp, body = client.request("GET", "/")
    html = body.decode("utf-8")
    assert resp.status == 200
    assert 'id="ready-see"' in html and '$("ready-see").setAttribute("href", url("/result"))' in html
    for item, label in zip(_ids(client), _marks(10), strict=False):
        _mark(client, item, label)
    resp, body = client.request("GET", "/result")
    result = body.decode("utf-8")
    assert resp.status == 200
    assert own_line("passed", 6) in result and own_line("failed", 4) in result
    assert RATE in result
    shown = _seen(result)  # as a person reads it: the shared script names kappa
    assert [w for w in (*JUDGE_WORDS, "TPR", "TNR") if w in shown] == []
