"""`judgekeeper mark` starts the page as its own process and returns, so a coding agent's shell
does not wait on it. Run for real here (CI runs it on Linux, macOS and Windows): the command
returns, the page answers with its token, a mark posted lands in marks.jsonl (stamped: the
link was printed with no terminal), a second `mark` replaces the page, and `mark --stop`
closes it with no process left behind."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from judgekeeper import background, label
from tests.page_http import retried
from tests.start_projects import promptfoo_project, split

LINK = re.compile(r"^Marking page: (http://127\.0\.0\.1:(\d+)/\?token=([\w-]+))$", re.MULTILINE)


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)  # SYNCHRONIZE, query
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: running
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")  # Linux: a zombie is not left running
    try:
        return stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def jk(project: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "judgekeeper", *args], cwd=project,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout, env=env, check=False)


def call(base: str, token: str, path: str, body=None):
    req = urllib.request.Request(f"{base}{path}?token={token}",
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Origin": base})  # as the page sends it

    def send():
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())

    return retried(send)


@pytest.fixture
def project(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    yield tmp_path
    folder = tmp_path / ".judgekeeper"
    try:
        pid = json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"]
    except (OSError, ValueError, KeyError):
        pid = None
    background.stop(folder)
    if pid and alive(pid):  # never leave a page running after a failed test
        os.kill(pid, signal.SIGTERM)


def page_log(project: Path) -> str:
    """What the page's own process wrote: shown when a step fails."""
    try:
        return (project / ".judgekeeper" / background.LOG).read_text(encoding="utf-8",
                                                                     errors="replace")
    except OSError as e:
        return f"(no page.log: {type(e).__name__})"


def test_mark_runs_the_page_in_the_background(project):
    began = time.monotonic()
    first = jk(project, "mark", "--port", "0", "--no-browser")
    took = time.monotonic() - began
    assert first.returncode == 0, first.stdout + first.stderr + page_log(project)
    assert took < 20, took  # the page answered within its 10 seconds
    m = LINK.search(first.stdout)
    assert m, first.stdout
    url, port, token = m[1], m[2], m[3]
    base = f"http://127.0.0.1:{port}"
    folder = project / ".judgekeeper"
    pid = json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"]
    assert alive(pid) and pid != os.getpid()

    status, state = call(base, token, "/state")
    assert status == 200 and state["items"]
    item = state["items"][0]["id"]
    status, _ = call(base, token, "/label", {"id": item, "label": "pass", "seconds": 3})
    assert status == 200
    lines = (folder / "marks.jsonl").read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert (last["id"], last["mark"], last["by"], last["seconds"]) == (item, "pass", "page", 3)
    assert last["link"] == "printed"  # the link was printed where an agent reads it

    second = jk(project, "mark", "--port", "0", "--no-browser")
    assert second.returncode == 0, second.stdout + second.stderr + page_log(project)
    assert LINK.search(second.stdout)[1] != url  # the open page was replaced
    assert "Marked so far: 1 (1 Pass, 0 Fail)." in second.stdout
    new_pid = json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"]
    assert new_pid != pid
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)
    pid = new_pid

    stopped = jk(project, "mark", "--stop")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr + page_log(project)
    assert "Closed the marking page." in stopped.stdout
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)
    assert not label.is_open(folder)
    assert not (folder / label.LOCK).exists()


def test_mark_stop_closes_a_page_whose_server_json_is_gone(project):
    first = jk(project, "mark", "--port", "0", "--no-browser")
    assert first.returncode == 0, first.stdout + first.stderr + page_log(project)
    folder = project / ".judgekeeper"
    pid = json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"]
    (folder / label.LOCK).unlink()

    stopped = jk(project, "mark", "--stop")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr + page_log(project)
    assert "Closed the marking page." in stopped.stdout
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)
