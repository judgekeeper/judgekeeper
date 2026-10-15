"""Stopping judgekeeper stops the program it waits for. Agents, editors and CI stop a command
with SIGTERM; judgekeeper used to end at once while its asking-again worker went on making
judge calls (money). Now the worker and everything it started are stopped with it."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SLOW = r"""
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open("pids.txt", "w") as f:
    f.write(f"{os.getpid()} {child.pid}\n")
for n in range(600):  # one "judge call" every 50 ms, for 30 s
    with open("calls.txt", "a") as f:
        f.write(f"{n}\n")
    time.sleep(0.05)
"""

WRAPPER = r"""
import sys
from pathlib import Path
from judgekeeper import again
again.run_process([sys.executable, "slow.py"], cwd=Path("."))
"""


def _calls(folder: Path) -> int:
    path = folder / "calls.txt"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a finished child its parent has not collected yet is not running
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                             text=True, check=False).stdout.strip()
    except OSError:
        return True
    return bool(out) and not out.startswith("Z")


def _until(test, limit=30.0):
    """Whether `test()` comes true within `limit` seconds: a busy machine (two test suites
    at once) can take seconds to start or stop a process, so no fixed sleep is trusted."""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM from outside: POSIX")
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_stopping_judgekeeper_stops_the_worker_and_its_children(tmp_path, sig):
    (tmp_path / "slow.py").write_text(SLOW, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    wrapper = subprocess.Popen([sys.executable, "-c", WRAPPER], cwd=tmp_path, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert _until(lambda: _calls(tmp_path) >= 3), "the worker never started"
        worker, child = map(int, (tmp_path / "pids.txt").read_text(encoding="utf-8").split())
        wrapper.send_signal(sig)  # to judgekeeper only, as an agent or CI does
        wrapper.wait(timeout=60)
        assert _until(lambda: not _alive(worker) and not _alive(child)), "still running"
        made = _calls(tmp_path)  # both are gone: no call can be added after this
        assert not _until(lambda: _calls(tmp_path) != made, limit=0.5), \
            "the worker went on making calls"
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
