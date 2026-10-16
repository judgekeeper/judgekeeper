"""One page server per project. Two `start` servers on one project each wrote labels.csv from
memory, so marks were lost while both pages said "saved": a second one is refused, and each
write reads the sheet again first. The lock holds the page's port and stop secret, never its
token."""

from __future__ import annotations

import json
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import start, start_label
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


def test_a_second_server_on_the_project_is_refused(ws):
    server, thread = _serving(ws)
    try:
        lock = json.loads((ws.dir / label_mod.LOCK).read_text(encoding="utf-8"))
        assert lock == {"pid": lock["pid"], "port": server.port, "stop": server.stop_secret}
        assert server.token not in json.dumps(lock)
        with pytest.raises(LabelError) as e:
            make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
        assert str(e.value) == ("A judgekeeper page is already open for this project. Close "
                                "it with Ctrl-C in its terminal, or run `judgekeeper --stop`.")
        assert "--port" not in str(e.value) and server.token not in str(e.value)
    finally:
        server.stop()
        thread.join(timeout=5)
    assert not (ws.dir / label_mod.LOCK).exists()  # released on exit
    second = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    second.release()
    second.httpd.server_close()


def test_a_lock_nobody_answers_is_ignored(ws):
    (ws.dir / label_mod.LOCK).write_text(json.dumps({"pid": 1, "port": 9, "stop": "x"}),
                                         encoding="utf-8")
    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    try:
        lock = json.loads((ws.dir / label_mod.LOCK).read_text(encoding="utf-8"))
        assert lock["stop"] == server.stop_secret
    finally:
        server.release()
        server.httpd.server_close()


def test_the_lock_is_removed_while_another_reader_has_it_open(ws):
    """On Windows a file someone has open can't be deleted, and `mark --stop` reads the lock
    while the page closes: the page still removes its lock."""
    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    lock = ws.dir / label_mod.LOCK
    reader = lock.open(encoding="utf-8")
    threading.Timer(0.5, reader.close).start()
    server.httpd.server_close()
    server.release()
    reader.close()
    assert not lock.exists()


def test_the_page_binds_without_looking_up_a_host_name(ws, monkeypatch):
    """http.server looks up the host name of 127.0.0.1 when it binds, which can hang for
    many seconds on some machines (a CI Mac): the page needs no name."""
    import socket

    def no_lookup(*args):
        raise AssertionError("looked up a host name")

    monkeypatch.setattr(socket, "getfqdn", no_lookup)
    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    assert server.port > 0
    server.release()
    server.httpd.server_close()


def test_a_lock_that_cant_be_removed_yet_is_tried_again(ws, monkeypatch):
    """Windows refuses to delete a file another process has open for a moment."""
    from pathlib import Path

    server = make_server(StartSession(ws), 0, page="<p>page</p>", lock=ws.dir)
    real, refused = Path.unlink, []

    def busy(self, *args, **kwargs):
        if self.name == label_mod.LOCK and len(refused) < 3:
            refused.append(self)
            raise PermissionError(32, "being used by another process")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", busy)
    server.httpd.server_close()
    server.release()
    assert len(refused) == 3 and not (ws.dir / label_mod.LOCK).exists()


def test_a_page_that_stopped_counts_as_closed_though_its_lock_stays(ws, monkeypatch):
    """`mark --stop`: a page that no longer answers, whose process has ended, is closed."""
    from judgekeeper import background

    _, thread = _serving(ws)
    monkeypatch.setattr(label_mod.LabelServer, "release", lambda self: None)  # lock stays
    monkeypatch.setattr(background, "_running", lambda pid: False)
    assert background.stop(ws.dir, timeout=5)
    thread.join(timeout=5)
    assert (ws.dir / label_mod.LOCK).exists()
