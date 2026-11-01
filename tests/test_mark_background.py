"""`judgekeeper mark` starts the page as its own process and returns, so the shell
does not wait on it. Run for real here (CI runs it on Linux, macOS and Windows): the command
returns, the page answers with its token, a mark posted lands in marks.jsonl (stamped: the
link was printed with no terminal), a second `mark` prints the same link (two at once too),
and `mark --stop` closes it with no process left behind."""

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
from tests.test_command_safety import _from

LINK = re.compile(r"^Open this link in your browser to mark answers:\n"
                  r"(http://127\.0\.0\.1:(\d+)/\?token=([\w-]+))$", re.MULTILINE)


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


def stop_page(project: Path) -> None:
    """Close the marking page `project` started as its own process, if any: never leave a
    page running, after a failed test too."""
    folder = project / ".judgekeeper"
    try:
        pid = json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"]
    except (OSError, ValueError, KeyError):
        pid = None
    background.stop(folder)
    if pid and alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # it was on its way out (Windows denies ending a process that is exiting)


@pytest.fixture
def project(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    yield tmp_path
    stop_page(tmp_path)


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
    assert last["link"] == "printed"  # the link was printed with no terminal

    second = jk(project, "mark", "--port", "0", "--no-browser")
    assert second.returncode == 0, second.stdout + second.stderr + page_log(project)
    assert LINK.search(second.stdout)[1] == url  # the same page: the open tab keeps working
    assert "You marked 1 answer so far: 1 Pass, 0 Fail." in second.stdout
    assert json.loads((folder / label.LOCK).read_text(encoding="utf-8"))["pid"] == pid
    assert call(base, token, "/state")[0] == 200

    stopped = jk(project, "mark", "--stop")
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr + page_log(project)
    assert "Closed the marking page." in stopped.stdout
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not alive(pid)
    assert not label.is_open(folder)
    assert not (folder / label.LOCK).exists()


# A project module named like one the page imports: it leaves a file named after itself, then
# puts the real module in its place, so the page keeps working and only the file tells.
SHADOW = """import importlib, os, sys
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "ran-" + __name__), "w").close()
kept = sys.path[:]
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
del sys.modules[__name__]
sys.modules[__name__] = importlib.import_module(__name__)
sys.path[:] = kept
"""


def test_the_page_never_imports_the_projects_modules(project):
    for name in ("json", "secrets"):
        (project / f"{name}.py").write_text(SHADOW, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # -I: judgekeeper itself as its console script starts it, without the project on its path
    run = subprocess.run([sys.executable, "-I", "-m", "judgekeeper", "--no-browser"],
                         cwd=project, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         encoding="utf-8", timeout=60, env=env, check=False)
    assert run.returncode == 0, run.stdout + run.stderr + page_log(project)
    m = LINK.search(run.stdout)
    assert m, run.stdout
    assert call(f"http://127.0.0.1:{m[2]}", m[3], "/state")[0] == 200
    assert sorted(p.name for p in project.glob("ran-*")) == []


@pytest.mark.real_page
def test_the_page_keeps_the_user_site(tmp_path, monkeypatch):
    """A user install (pip's "Defaulting to user installation") puts judgekeeper in the user
    site: the page's Python keeps it, and still leaves out the current folder and PYTHON*."""
    started = []

    def popen(argv, **kwargs):
        started.append(argv)
        raise OSError

    with monkeypatch.context() as m:
        m.setattr(background.subprocess, "Popen", popen)
        assert background.start(tmp_path, {}, "t" * 43) is None
    flags = [a for a in started[0][1:] if a.startswith("-") and a != "-m"]
    code = "import sys; f = sys.flags; print(f.no_user_site, f.ignore_environment, f.safe_path)"
    seen = subprocess.run([sys.executable, *flags, "-c", code], capture_output=True, text=True,
                          check=True).stdout.split()
    assert seen == ["0", "1", "True"], started[0]


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


def test_two_runs_at_once_print_the_same_working_link(project):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    runs = [subprocess.Popen([sys.executable, "-m", "judgekeeper", "mark", "--port", "0",
                              "--no-browser"], cwd=project, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", env=env) for _ in range(2)]
    outs = [r.communicate(timeout=60) for r in runs]
    assert [r.returncode for r in runs] == [0, 0], outs
    links = [LINK.search(out) for out, _ in outs]
    assert all(links), outs
    assert links[0][1] == links[1][1]
    status, state = call(f"http://127.0.0.1:{links[0][2]}", links[0][3], "/state")
    assert status == 200 and state["items"]


@pytest.mark.real_page
def test_ctrl_c_while_the_page_starts_ends_its_process(project, monkeypatch):
    """Ctrl-C while the command waits for the page to answer: the page's process ends too,
    and no lock is left that names a running page."""
    first = jk(project, "mark", "--port", "0", "--no-browser")  # the project's .judgekeeper/
    assert first.returncode == 0, first.stdout + first.stderr + page_log(project)
    assert jk(project, "mark", "--stop").returncode == 0

    def interrupted(port, token):
        time.sleep(1)  # the page has started meanwhile
        raise KeyboardInterrupt

    monkeypatch.setattr(background, "answers", interrupted)
    folder = project / ".judgekeeper"
    settings = {"root": str(project), "port": 0, "flags": {}}
    with pytest.raises(KeyboardInterrupt):
        background.start(folder, settings, "t" * 43)
    proc = background._started[-1]
    proc.wait(timeout=15)
    assert not alive(proc.pid)
    assert not label.is_open(folder)


def test_the_page_says_python_m_when_started_that_way(project):
    """Started as `python -P -m judgekeeper` with no `judgekeeper` command on the PATH, the
    page's own process says to come back the same way."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PATH": ""}

    def py_m(*args):
        return subprocess.run([sys.executable, "-P", "-m", "judgekeeper", *args], cwd=project,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", timeout=60, env=env, check=False)

    first = py_m("mark", "--port", "0", "--no-browser")
    assert first.returncode == 0, first.stdout + first.stderr + page_log(project)
    python = _from(project, sys.executable)  # no python3 on that PATH
    command = f"{python} -P -m judgekeeper mark"
    m = LINK.search(first.stdout)
    base = f"http://127.0.0.1:{m[2]}"

    def send():
        with urllib.request.urlopen(f"{base}/?token={m[3]}", timeout=10) as r:
            return r.read().decode("utf-8")

    assert command in retried(send)
    assert py_m("mark", "--stop").returncode == 0
