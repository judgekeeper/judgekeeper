"""The marking page (page.page_server): marking and the result only, every click a stamped
line in marks.jsonl, and it stays open until `/stop` (with the token or the stop secret) or 2
hours idle."""

from __future__ import annotations

import json
import threading
import time

import pytest

from judgekeeper import label as label_mod
from judgekeeper import marks, page, start, start_label
from tests.start_projects import promptfoo_project, split
from tests.test_label_server import Client


@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(16, 16))
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


@pytest.fixture
def served(ws):
    server = page.page_server(ws, 0, "judgekeeper")
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    yield server, thread, Client(server)
    server.stop()
    thread.join(timeout=5)


def _clicks(ws):
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()][1:]


def test_a_click_with_seconds_lands_as_a_stamped_line(ws, served):
    _, _, client = served
    item = client.state()["items"][0]["id"]
    status, _ = client.label(id=item, label="fail", seconds=6.2)
    assert status == 200
    [line] = _clicks(ws)
    assert line["id"] == item and line["mark"] == "fail" and line["seconds"] == 6.2
    assert line["by"] == "page" and line["at"].endswith("Z") and line["sitting"]
    assert line["group"] == {q["id"]: q["group"] for q in ws.data()["queue"]}[item]


@pytest.mark.parametrize("given,kept", [(-1, 0), (86400, 3600)])
def test_seconds_out_of_range_are_kept_within_0_and_3600(ws, served, given, kept):
    _, _, client = served
    client.label(id=client.state()["items"][0]["id"], label="pass", seconds=given)
    assert _clicks(ws)[0]["seconds"] == kept


def test_seconds_that_are_not_a_number_are_refused(ws, served):
    _, _, client = served
    status, body = client.label(id=client.state()["items"][0]["id"], label="pass",
                                seconds="soon")
    assert status == 400 and "seconds" in body["error"]
    assert _clicks(ws) == []


def test_the_page_sends_the_seconds_on_each_answer(served):
    server, _, _ = served
    script = server.page()[0]
    assert "seconds" in script and "shownAt" in script


def test_stop_needs_the_token(ws, served):
    _, thread, client = served
    resp, _ = client.request("POST", "/stop", token=False)
    assert resp.status == 403
    assert client.state()  # still serving
    resp, body = client.request("POST", "/stop")
    assert resp.status == 200 and json.loads(body) == {"stopped": True}
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not (ws.dir / label_mod.LOCK).exists()


def test_the_page_is_marking_and_result_only(served):
    server, _, client = served
    for path in ("/review", "/fix"):
        resp, _ = client.request("GET", path)
        assert resp.status == 404
    assert "/review" not in server.page()[0] and "/fix" not in server.page()[0]


def test_it_stays_open_after_the_result(ws, served, monkeypatch):
    monkeypatch.setattr(label_mod, "RESULT_WAIT", 0)
    _, thread, client = served
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in client.state()["items"]:
        client.label(id=item["id"], label=groups[item["id"]], seconds=5)
    resp, body = client.request("GET", "/result")
    text = body.decode("utf-8")
    assert resp.status == 200
    assert "/review" not in text and "/fix" not in text
    assert 'id="verdict-h"' in text and 'class="counts"' in text
    time.sleep(0.5)
    assert thread.is_alive() and client.state()
    assert (ws.dir / "report.html").is_file() and not (ws.dir / "result.html").exists()
    assert marks.read(ws.marks).header is not None


def test_the_stop_secret_closes_the_page_and_does_nothing_else(ws, served):
    server, thread, client = served
    secret = label_mod.read_lock(ws.dir)["stop"]
    assert secret != server.token
    item = client.state()["items"][0]["id"]
    for path, method in (("/state", "GET"), ("/", "GET"), ("/result", "GET"),
                         ("/label", "POST"), ("/printed", "POST")):
        resp, _ = client.request(method, f"{path}?stop={secret}", token=False,
                                 body={"id": item, "label": "pass"})
        assert resp.status == 403, path
    assert _clicks(ws) == []
    resp, _ = client.request("GET", f"/alive?stop={secret}", token=False)
    assert resp.status == 200
    resp, _ = client.request("POST", f"/stop?stop={secret}", token=False)
    assert resp.status == 200
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_printed_stamps_every_later_mark(ws, served):
    _, _, client = served
    items = [x["id"] for x in client.state()["items"]]
    client.label(id=items[0], label="pass", seconds=2)
    resp, _ = client.request("POST", "/printed", body={})
    assert resp.status == 200
    client.label(id=items[1], label="fail", seconds=2)
    first, second = _clicks(ws)
    assert "link" not in first and second["link"] == "printed"
