"""The page's token never passes through the coding agent. `judgekeeper` makes the token,
hands it to the page's own process on its stdin, and opens the page in the browser itself: the
token is not in the output, not in any file under .judgekeeper/, not in the page process's
argv or environment. server.json keeps a stop secret, which can close the page and nothing
else. Opening an open page replaces it: the old token stops working, the marks stay.

Run for real (CI runs it on Linux, macOS and Windows): the page is its own process.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from judgekeeper import background, label, start_label
from judgekeeper.cli import main
from tests.page_http import retried
from tests.start_projects import promptfoo_project, split
from tests.test_mark_background import alive

pytestmark = pytest.mark.real_page


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    yield tmp_path
    folder = tmp_path / ".judgekeeper"
    lock = label.read_lock(folder)
    background.stop(folder)
    if lock and alive(lock["pid"]):  # never leave a page running after a failed test
        import signal

        os.kill(lock["pid"], signal.SIGTERM)


@pytest.fixture
def spawned(monkeypatch):
    """Every process judgekeeper starts: its arguments and the environment it is given."""
    calls = []
    real = subprocess.Popen

    def popen(args, *a, **k):
        calls.append({"args": [str(x) for x in args], "env": k.get("env")})
        return real(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def _split(url: str) -> tuple[str, str]:
    base, token = url.split("/?token=")
    return base, token


def _status(base: str, path: str, method="GET", body=None) -> int:
    host, port = base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        data = None if body is None else json.dumps(body).encode()
        conn.request(method, path, body=data,
                     headers={"Content-Type": "application/json", "Origin": base})
        return conn.getresponse().status
    except OSError:
        return 0  # nothing answers
    finally:
        conn.close()


def _process_text(pid: int) -> str:
    """What the system shows of a running process: its command line and environment."""
    if sys.platform.startswith("linux"):
        from pathlib import Path

        texts = []
        for name in ("cmdline", "environ"):
            try:
                texts.append(Path(f"/proc/{pid}/{name}").read_bytes().decode(errors="replace"))
            except OSError:
                pass
        return "\n".join(texts)
    if sys.platform == "darwin":
        return subprocess.run(["ps", "-ww", "-E", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True, check=False).stdout
    return ""


def test_the_token_never_reaches_the_agent(here, capsys, no_browser, spawned):
    code, out, err = _run(capsys, "--port", "0")
    assert code == 0, out + err
    assert "The marking page is open in your browser." in out
    assert len(no_browser) == 1
    url = no_browser[0]
    base, token = _split(url)
    assert len(token) >= 32

    assert token not in out + err
    assert "token=" not in out + err and "http://" not in out
    folder = here / ".judgekeeper"
    for path in folder.rglob("*"):
        if path.is_file():
            assert token.encode() not in path.read_bytes(), path.name
    assert len(spawned) == 1
    assert all(token not in arg for arg in spawned[0]["args"])
    assert spawned[0]["env"] is None or token not in json.dumps(spawned[0]["env"])
    assert token not in json.dumps(dict(os.environ))
    lock = label.read_lock(folder)
    assert set(json.loads((folder / label.LOCK).read_text(encoding="utf-8"))) == \
        {"pid", "port", "stop"}
    assert lock["pid"] != os.getpid() and alive(lock["pid"])
    assert token not in _process_text(lock["pid"])

    # The page answers only with its token.
    assert _status(base, f"/state?token={token}") == 200
    assert _status(base, "/state") == 403
    assert _status(base, "/state?token=wrong") == 403
    assert _status(base, f"/state?token={lock['stop']}") == 403
    assert _status(base, f"/?stop={lock['stop']}") == 403

    # The stop secret can't mark, and it closes the page.
    item = start_label.StartSession(start_label.Workspace(here)).items[0]["id"]
    for query in (f"token={lock['stop']}", f"stop={lock['stop']}"):
        assert _status(base, f"/label?{query}", "POST", {"id": item, "label": "pass"}) == 403
    assert start_label.StartSession(start_label.Workspace(here)).counts()["correct"] == 0
    code, out, _ = _run(capsys, "--stop")
    assert code == 0 and "Closed the marking page." in out
    assert not label.is_open(folder)
    assert _status(base, f"/state?token={token}") != 200


def test_opening_an_open_page_replaces_it(here, capsys, no_browser):
    assert _run(capsys, "--port", "0")[0] == 0
    first = no_browser[-1]
    base, token = _split(first)
    ws = start_label.Workspace(here)
    item = start_label.StartSession(ws).items[0]["id"]
    req = urllib.request.Request(f"{base}/label?token={token}",
                                 data=json.dumps({"id": item, "label": "pass"}).encode(),
                                 headers={"Content-Type": "application/json", "Origin": base})

    def send():
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status

    assert retried(send) == 200
    old_pid = label.read_lock(ws.dir)["pid"]

    code, out, _ = _run(capsys, "--port", "0")
    assert code == 0, out
    assert "Marked so far: 1 (1 Pass, 0 Fail)." in out  # the mark stays
    second = no_browser[-1]
    new_base, new_token = _split(second)
    assert new_token != token
    assert _status(new_base, f"/state?token={new_token}") == 200
    assert _status(base, f"/state?token={token}") != 200  # the old token stops working
    assert _status(new_base, f"/state?token={token}") == 403
    assert label.read_lock(ws.dir)["pid"] != old_pid


def test_a_page_started_by_hand_gets_no_token_from_the_command_line(here):
    """The page's own process takes its token from stdin only: given none, it does not start."""
    p = subprocess.run([sys.executable, "-m", "judgekeeper.page"], cwd=here, input="",
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode != 0
    assert not label.is_open(here / ".judgekeeper")
