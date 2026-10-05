"""The branded one-question-at-a-time labeling page (try_page.py) and the label server's
/result endpoint that goes with it. No command serves this page yet."""

from __future__ import annotations

import json
import re
import threading

from judgekeeper import label as label_mod
from tests.test_label_server import Client

OWN = "https://www.judgekeeper.com/own-metric.html"
START = "https://www.judgekeeper.com/start.html"


def _items(tmp_path, n: int = 5):
    items = tmp_path / "items.jsonl"
    items.write_text("".join(json.dumps({"id": f"x{k}", "input": "q", "output": "o"}) + "\n"
                             for k in range(n)))
    return items


def test_the_try_page_is_branded_simple_and_hides_the_judge(tmp_path):
    session = label_mod.LabelSession(_items(tmp_path), tmp_path / "l.csv")
    server = label_mod.LabelServer(session, port=0, result=lambda s: {"lines": []})
    try:
        page = " ".join(server.page()[0].split())
    finally:
        server.httpd.server_close()
    assert "#1E293B" in page and "#10B981" in page  # the logo's two halves
    for needed in ("Correct <kbd>1</kbd>", "Wrong <kbd>2</kbd>", "Your result", "What next",
                   OWN, START, "prefers-color-scheme: dark"):
        assert needed in page, needed
    for absent in ("Defer", "Undo", "Show judge", "Summary", "<textarea", "PASS.", "FAIL."):
        assert absent not in page, absent
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", page))
    assert urls <= {OWN, START, "http://www.w3.org/2000/svg"}, urls
    assert " src=" not in page  # nothing loaded from anywhere


def test_plain_label_keeps_its_own_page(tmp_path):
    session = label_mod.LabelSession(_items(tmp_path, 1), tmp_path / "l.csv")
    server = label_mod.LabelServer(session, port=0)
    try:
        page = server.page()[0]
    finally:
        server.httpd.server_close()
    assert "Defer" in page and "Show judge" in page and "Your result" not in page


def test_the_result_needs_the_token_and_every_answer(tmp_path):
    session = label_mod.LabelSession(_items(tmp_path, 2), tmp_path / "l.csv")
    server = label_mod.LabelServer(session, port=0, result=lambda s: {"lines": ["done"]})
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    client = Client(server)
    assert client.request("GET", "/result", token=False)[0].status == 403
    assert client.request("GET", "/result")[0].status == 409
    client.label(id="x0", label="pass")
    client.label(id="x1", label="fail")
    resp, payload = client.request("GET", "/result")
    assert resp.status == 200 and json.loads(payload) == {"lines": ["done"]}
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_plain_label_has_no_result(tmp_path):
    session = label_mod.LabelSession(_items(tmp_path, 1), tmp_path / "l.csv")
    server = label_mod.LabelServer(session, port=0)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    client = Client(server)
    client.label(id="x0", label="pass")
    assert client.request("GET", "/result")[0].status == 404
    assert thread.is_alive()
    server.stop()
    thread.join(timeout=5)
