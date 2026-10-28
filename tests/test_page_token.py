"""The page's token never passes through the coding agent's output. `judgekeeper` makes the
token, hands it to the page's own process on its stdin, and opens the page in the browser
itself: the token is not in the output, not in the page process's argv or environment. Under
.judgekeeper/ it is only in the page's lock (server.json and its copy), owner-only, and gone
once the page stops; a lock whose page is gone is not used and is removed. The lock's stop
secret can close the page and nothing else. Opening the open page again keeps its link: the
open tab keeps working, the marks stay; when the page must start again, it keeps the token.

Run for real (CI runs it on Linux, macOS and Windows): the page is its own process.
"""

from __future__ import annotations

import http.client
import json
import os
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

        try:
            os.kill(lock["pid"], signal.SIGTERM)
        except (PermissionError, ProcessLookupError):  # it was closing already (Windows)
            pass


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


def test_the_token_never_reaches_the_agents_output(here, capsys, no_browser, spawned):
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
    holding = {path.name for path in folder.rglob("*")
               if path.is_file() and token.encode() in path.read_bytes()}
    assert holding == {label.LOCK, label.LOCK_COPY}  # the page's lock only
    if os.name != "nt":  # owner-only, in an owner-only folder
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        for name in holding:
            assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600, name
    assert len(spawned) == 1
    assert all(token not in arg for arg in spawned[0]["args"])
    assert spawned[0]["env"] is None or token not in json.dumps(spawned[0]["env"])
    assert token not in json.dumps(dict(os.environ))
    lock = label.read_lock(folder)
    assert set(json.loads((folder / label.LOCK).read_text(encoding="utf-8"))) == \
        {"pid", "port", "stop", "token", "settings", "link"}
    assert lock["token"] == token
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
    for path in folder.rglob("*"):  # the token is gone with the page
        if path.is_file():
            assert token.encode() not in path.read_bytes(), path.name


def _mark(base: str, token: str, item: str) -> int:
    req = urllib.request.Request(f"{base}/label?token={token}",
                                 data=json.dumps({"id": item, "label": "pass"}).encode(),
                                 headers={"Content-Type": "application/json", "Origin": base})

    def send():
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status

    return retried(send)


def test_opening_the_open_page_again_keeps_its_link(here, capsys, no_browser):
    assert _run(capsys, "--port", "0")[0] == 0
    base, token = _split(no_browser[-1])
    ws = start_label.Workspace(here)
    assert _mark(base, token, start_label.StartSession(ws).items[0]["id"]) == 200
    old_pid = label.read_lock(ws.dir)["pid"]

    code, out, _ = _run(capsys, "mark", "--port", "0")
    assert code == 0, out
    assert "You marked 1 answer so far: 1 Pass, 0 Fail." in out  # the mark stays
    assert no_browser[-1] == f"{base}/?token={token}"  # the same link: the open tab works
    assert _status(base, f"/state?token={token}") == 200
    assert label.read_lock(ws.dir)["pid"] == old_pid  # the same page


@pytest.mark.parametrize("again", [("mark", "--port", "0"), ("--no-browser", "--port", "0"),
                                   ("mark", "--no-browser")])
def test_a_second_run_with_other_browser_flags_keeps_the_open_page(here, capsys, no_browser,
                                                                    monkeypatch, again):
    """Opening a browser or not, and the port asked for, change nothing the page shows: the
    open page is kept, and its link printed again."""
    from judgekeeper import page

    code, out, _ = _run(capsys, "--no-browser", "--port", "0")
    assert code == 0, out
    first = out.splitlines()[out.splitlines().index(page.LINK) + 1]
    ws = start_label.Workspace(here)
    old_pid = label.read_lock(ws.dir)["pid"]
    monkeypatch.setattr(page, "terminal", lambda: True)
    code, out, _ = _run(capsys, *again)
    assert code == 0, out
    assert first in [*out.splitlines(), *no_browser]  # printed again, or opened
    assert label.read_lock(ws.dir)["pid"] == old_pid  # the same page
    assert page.STARTS_AGAIN not in out


def test_a_page_started_again_keeps_the_token_and_the_printed_stamp(here, capsys, monkeypatch):
    """The page must start again (it would show another command), and says so: it keeps the
    token and the port, so the open tab still works. Its link was printed with no terminal
    before, so its marks are still stamped "printed"."""
    from judgekeeper import page

    code, out, _ = _run(capsys, "--no-browser", "--port", "0")  # no terminal: printed
    assert code == 0, out
    first = out.splitlines()[out.splitlines().index(page.LINK) + 1]
    base, token = _split(first)
    ws = start_label.Workspace(here)
    old_pid = label.read_lock(ws.dir)["pid"]

    monkeypatch.setattr(page, "terminal", lambda: True)  # now at a terminal: not stamped
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    code, out, _ = _run(capsys, "--tool", "promptfoo", "--port", "0")  # another command
    assert code == 0, out
    assert page.STARTS_AGAIN in out
    assert opened == [first]  # the same link
    assert label.read_lock(ws.dir)["pid"] != old_pid  # a new page
    assert _mark(base, token, start_label.StartSession(ws).items[0]["id"]) == 200
    last = json.loads(ws.marks.read_text(encoding="utf-8").splitlines()[-1])
    assert last["link"] == "printed"


def test_two_ports_asked_for_give_the_open_pages_link(here, capsys, no_browser):
    assert _run(capsys, "--port", "0")[0] == 0
    first = no_browser[-1]
    assert _run(capsys, "--port", "0")[0] == 0 and no_browser[-1] == first
    from judgekeeper import page

    assert _run(capsys, "--port", page.OTHER_PORTS[-1])[0] == 0
    assert no_browser[-1] == first  # the open page keeps its port


def test_a_lock_whose_page_is_gone_is_not_used_and_is_removed(here, capsys, no_browser):
    folder = here / ".judgekeeper"
    assert _run(capsys, "--port", "0")[0] == 0
    assert _run(capsys, "--stop")[0] == 0
    stale = json.dumps({"pid": 999999, "port": 9, "stop": "s" * 43, "token": "t" * 43,
                        "settings": None, "printed": False})
    for name in (label.LOCK, label.LOCK_COPY):
        (folder / name).write_text(stale, encoding="utf-8")
    assert label.live_lock(folder) is None
    assert not (folder / label.LOCK).exists() and not (folder / label.LOCK_COPY).exists()

    for name in (label.LOCK, label.LOCK_COPY):
        (folder / name).write_text(stale, encoding="utf-8")
    code, out, _ = _run(capsys, "--port", "0")
    assert code == 0, out
    base, token = _split(no_browser[-1])
    assert token != "t" * 43 and _status(base, f"/state?token={token}") == 200


def test_a_page_started_by_hand_gets_no_token_from_the_command_line(here):
    """The page's own process takes its token from stdin only: given none, it does not start."""
    p = subprocess.run([sys.executable, "-m", "judgekeeper.page"], cwd=here, input="",
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode != 0
    assert not label.is_open(here / ".judgekeeper")


class _Any(BaseHTTPRequestHandler):
    """Another program on this machine: 200 to every request, each one kept in `seen` (set by
    `listener`)."""
    seen: list

    def _yes(self):
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size).decode(errors="replace") if size else ""
        self.seen.append((self.command, self.path, body))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = _yes

    def log_message(self, *args):
        pass


@pytest.fixture
def listener():
    seen = []
    other = ThreadingHTTPServer(("127.0.0.1", 0), type("Kept", (_Any,), {"seen": seen}))
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    yield other.server_address[1], seen
    other.shutdown()
    other.server_close()


def _ended_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    return proc.pid


def test_a_lock_naming_another_programs_listener_gets_nothing(here, capsys, listener):
    """A server.json in the project names a port where another program answers 200: it gets
    no token and no /stop, and the page judgekeeper starts is the one linked."""
    from judgekeeper import page

    port, seen = listener
    folder = here / ".judgekeeper"
    folder.mkdir(exist_ok=True)
    (folder / label.LOCK).write_text(json.dumps({
        "pid": _ended_pid(), "port": port, "stop": "STOP-FROM-PROJECT",
        "token": "TOKEN-FROM-PROJECT-" + "x" * 32, "settings": {}, "link": None}),
        encoding="utf-8")
    code, out, err = _run(capsys, "--no-browser", "--port", "0")
    assert code == 0, out + err
    lines = out.splitlines()
    url = lines[lines.index(page.LINK) + 1]
    base, token = _split(url)
    lock = label.read_lock(folder)
    assert lock is not None and lock["port"] != port and lock["token"] == token
    assert base == f"http://127.0.0.1:{lock['port']}" and label.is_page(lock["port"])
    assert _status(base, f"/state?token={token}") == 200
    assert not [s for s in seen if token in s[1] + s[2]]
    assert not [s for s in seen if s[0] == "POST" or "STOP-FROM-PROJECT" in s[1]]
