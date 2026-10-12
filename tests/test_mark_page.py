"""The page `judgekeeper mark` serves (mark.page_server): marking and the result only, every
click a stamped line in marks.jsonl, and it stays open until `/stop` (with the token) or 2
hours idle."""

from __future__ import annotations

import json
import threading
import time

import pytest

from judgekeeper import label as label_mod
from judgekeeper import mark, marks, start, start_label
from tests.start_projects import promptfoo_project, split
from tests.test_label_server import Client


@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(16, 16))
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


@pytest.fixture
def page(ws):
    server = mark.page_server(ws, 0, "judgekeeper mark")
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    yield server, thread, Client(server)
    server.stop()
    thread.join(timeout=5)


def _clicks(ws):
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()][1:]


def test_a_click_with_seconds_lands_as_a_stamped_line(ws, page):
    _, _, client = page
    item = client.state()["items"][0]["id"]
    status, _ = client.label(id=item, label="fail", seconds=6.2)
    assert status == 200
    [line] = _clicks(ws)
    assert line["id"] == item and line["mark"] == "fail" and line["seconds"] == 6.2
    assert line["by"] == "page" and line["at"].endswith("Z") and line["sitting"]
    assert line["group"] == {q["id"]: q["group"] for q in ws.data()["queue"]}[item]


@pytest.mark.parametrize("given,kept", [(-1, 0), (86400, 3600)])
def test_seconds_out_of_range_are_kept_within_0_and_3600(ws, page, given, kept):
    _, _, client = page
    client.label(id=client.state()["items"][0]["id"], label="pass", seconds=given)
    assert _clicks(ws)[0]["seconds"] == kept


def test_seconds_that_are_not_a_number_are_refused(ws, page):
    _, _, client = page
    status, body = client.label(id=client.state()["items"][0]["id"], label="pass",
                                seconds="soon")
    assert status == 400 and "seconds" in body["error"]
    assert _clicks(ws) == []


def test_the_page_sends_the_seconds_on_each_answer(page):
    server, _, _ = page
    script = server.page()[0]
    assert "seconds" in script and "shownAt" in script


def test_stop_needs_the_token(ws, page):
    _, thread, client = page
    resp, _ = client.request("POST", "/stop", token=False)
    assert resp.status == 403
    assert client.state()  # still serving
    resp, body = client.request("POST", "/stop")
    assert resp.status == 200 and json.loads(body) == {"stopped": True}
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not (ws.dir / label_mod.LOCK).exists()


def test_the_page_is_marking_and_result_only(page):
    server, _, client = page
    for path in ("/review", "/fix"):
        resp, _ = client.request("GET", path)
        assert resp.status == 404
    assert "/review" not in server.page()[0] and "/fix" not in server.page()[0]


def test_it_stays_open_after_the_result(ws, page, monkeypatch):
    monkeypatch.setattr(label_mod, "RESULT_WAIT", 0)
    _, thread, client = page
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in client.state()["items"]:
        client.label(id=item["id"], label=groups[item["id"]], seconds=5)
    resp, body = client.request("GET", "/result")
    text = body.decode("utf-8")
    assert resp.status == 200
    assert "/review" not in text and "/fix" not in text
    assert "Mark more answers" in text
    assert "This set can see a drop of" in text
    assert "made on the page in 1 sitting, about 5 seconds each" in text
    time.sleep(0.5)
    assert thread.is_alive() and client.state()
    assert (ws.dir / "report.html").is_file() and not (ws.dir / "result.html").exists()
    assert marks.read(ws.marks).header is not None
