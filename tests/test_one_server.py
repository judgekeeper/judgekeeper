"""One page server per project. Two `start` servers on one project each wrote labels.csv from
memory, so marks were lost while both pages said "saved": a second one is refused with the
first one's link, and each write reads the sheet again first."""

from __future__ import annotations

import json
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import start, start_label
from judgekeeper.cli import main
from judgekeeper.label import LabelError, make_server
from judgekeeper.start_label import StartSession
from tests.start_projects import split, table_project


def _quiet(line=""):
    pass


@pytest.fixture
def ws(tmp_path):
    table_project(tmp_path, split(16, 16))
    return start_label.prepare(start.find_judge(tmp_path), say=_quiet)


def _labels(ws) -> dict:
    return {i["id"]: i["label"] for i in StartSession(ws).items if i["label"]}


def test_two_sessions_keep_each_others_marks(ws):
    a, b = StartSession(ws), StartSession(ws)
    ids = [q["id"] for q in ws.data()["queue"]]
    for n in range(5):
        a.update({"id": ids[n], "label": "pass"})
        b.update({"id": ids[10 + n], "label": "fail"})
    assert len(_labels(ws)) == 10
    b.update({"id": ids[0], "label": None})  # a mark taken back on the other page
    a.update({"id": ids[1], "label": "fail"})
    marks = _labels(ws)
    assert ids[0] not in marks and marks[ids[1]] == "fail" and len(marks) == 9


def test_a_skip_on_the_other_page_is_kept(ws):
    a, b = StartSession(ws), StartSession(ws)
    ids = [q["id"] for q in ws.data()["queue"]]
    a.update({"id": ids[0], "deferred": True})
    b.update({"id": ids[1], "label": "pass"})
    item = StartSession(ws).by_id[ids[0]]
    assert item["deferred"] and item["label"] is None


def _serving(ws):
    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread


def test_a_second_server_on_the_project_is_refused_with_the_first_ones_link(ws):
    server, thread = _serving(ws)
    try:
        lock = json.loads((ws.dir / label_mod.LOCK).read_text(encoding="utf-8"))
        assert lock["port"] == server.port and lock["token"] == server.token
        with pytest.raises(LabelError) as e:
            make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
        assert str(e.value) == (f"judgekeeper is already open for this project: {server.url} "
                                "(or stop it with Ctrl-C in its terminal).")
        assert "--port" not in str(e.value)
    finally:
        server.stop()
        thread.join(timeout=5)
    assert not (ws.dir / label_mod.LOCK).exists()  # released on exit
    second = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    second.release()
    second.httpd.server_close()


def test_a_lock_nobody_answers_is_ignored(ws):
    (ws.dir / label_mod.LOCK).write_text(json.dumps({"pid": 1, "port": 9, "token": "x"}),
                                         encoding="utf-8")
    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    try:
        lock = json.loads((ws.dir / label_mod.LOCK).read_text(encoding="utf-8"))
        assert lock["token"] == server.token
    finally:
        server.release()
        server.httpd.server_close()


def test_a_second_start_says_where_the_page_is_and_stops(ws, tmp_path, capsys):
    server, thread = _serving(ws)
    try:
        code = main(["start", str(tmp_path), "--no-browser", "--yes", "--port", "8806"])
        out, err = capsys.readouterr()
    finally:
        server.stop()
        thread.join(timeout=5)
    assert code == 2
    assert f"judgekeeper is already open for this project: {server.url}" in out + err
