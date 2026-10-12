"""The marking page as a process of its own, so `judgekeeper` can open it and return: a coding
agent's shell would wait forever on a command that serves a page.

`start` runs `python -m judgekeeper.page` detached from the caller: a new session on POSIX;
DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP and CREATE_NO_WINDOW on Windows. The page's token
(made by the caller) and its settings go to it as one JSON line on its stdin, a pipe closed
right after: never in its arguments, its environment or a file. Its output is not the
caller's: errors go to .judgekeeper/page.log (never answer text or the token), the rest
nowhere. It returns the page's link once the page answers to that token (the port is in the
lock in .judgekeeper/), at most WAIT seconds; else None, and the process is ended.

`stop` closes the open page with a POST to /stop with the lock's stop secret, which works the
same on every system, and waits until it is gone: it no longer answers, and its lock is
released or its process has ended.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from judgekeeper.label import answers, ask, is_open, link, read_lock

WAIT = 10  # seconds
LOG = "page.log"
_started: list[subprocess.Popen] = []  # kept, so no page process is collected while it runs


def start(folder: Path, settings: dict, token: str, timeout: float = WAIT) -> str | None:
    """Start the page for the project whose .judgekeeper/ is `folder`, with `settings` (see
    page.main) and `token`; its link once it answers to the token, else None."""
    folder = Path(folder)
    flags = {"stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        flags["creationflags"] = (subprocess.DETACHED_PROCESS
                                  | subprocess.CREATE_NEW_PROCESS_GROUP
                                  | subprocess.CREATE_NO_WINDOW)
    else:
        flags["start_new_session"] = True
    try:
        with (folder / LOG).open("ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "judgekeeper.page"], stderr=log,
                                    **flags)
    except OSError:
        return None
    _started.append(proc)
    try:
        proc.stdin.write((json.dumps({**settings, "token": token}) + "\n").encode("utf-8"))
        proc.stdin.close()
    except OSError:
        proc.kill()
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lock = read_lock(folder)
        if lock is not None and answers(lock["port"], token):
            return link(lock["port"], token)
        if proc.poll() is not None:
            return None
        time.sleep(0.1)
    proc.kill()
    return None


def stop(folder: Path, timeout: float = WAIT) -> bool:
    """Close the page open for this project. False when none is open, or it did not close."""
    folder = Path(folder)
    lock = read_lock(folder)
    if lock is None or not is_open(folder):
        return False
    ask(lock["port"], "POST", "/stop", {"stop": lock["stop"]})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_open(folder) and (read_lock(folder) != lock or not _running(lock["pid"])):
            return True
        time.sleep(0.1)
    return False


def _running(pid: int) -> bool:
    """Whether the process `pid` is still running."""
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
    except OSError:
        return True
    return True
