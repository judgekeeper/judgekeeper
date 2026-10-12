"""The marking page as a process of its own, so `judgekeeper mark` can print the link and
return: a coding agent's shell would wait forever on a command that serves a page.

`start` runs `python -m judgekeeper mark --wait ...` detached from the caller: a new session on
POSIX; DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP and CREATE_NO_WINDOW on Windows. Its input
and output are not the caller's: errors go to .judgekeeper/page.log (never answer text), the
rest nowhere. It returns the page's link once the page answers (the lock in .judgekeeper/ and
label.open_page), at most WAIT seconds; else None, and the process is ended.

`stop` closes the open page with a POST to /stop with its token, which works the same on every
system, and waits until it is gone: it no longer answers, and its lock is released or its
process has ended.
"""

from __future__ import annotations

import http.client
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from judgekeeper.label import HOST, PROBE_TIMEOUT, open_page, read_lock

WAIT = 10  # seconds
LOG = "page.log"
_started: list[subprocess.Popen] = []  # kept, so no page process is collected while it runs


def start(folder: Path, args: list[str], timeout: float = WAIT) -> str | None:
    """Start the page for the project whose .judgekeeper/ is `folder`, with `mark`'s `args`;
    its link once it answers, else None."""
    folder = Path(folder)
    flags = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        flags["creationflags"] = (subprocess.DETACHED_PROCESS
                                  | subprocess.CREATE_NEW_PROCESS_GROUP
                                  | subprocess.CREATE_NO_WINDOW)
    else:
        flags["start_new_session"] = True
    try:
        with (folder / LOG).open("ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", "judgekeeper", "mark", "--wait",
                                     *args], stderr=log, **flags)
    except OSError:
        return None
    _started.append(proc)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        url = open_page(folder)
        if url:
            return url
        if proc.poll() is not None:
            return None
        time.sleep(0.1)
    proc.kill()
    return None


def stop(folder: Path, timeout: float = WAIT) -> bool:
    """Close the page open for this project. False when none is open, or it did not close."""
    folder = Path(folder)
    lock = read_lock(folder)
    if lock is None or open_page(folder) is None:
        return False
    conn = http.client.HTTPConnection(HOST, lock["port"], timeout=PROBE_TIMEOUT)
    try:
        conn.request("POST", f"/stop?{urlencode({'token': lock['token']})}")
        conn.getresponse().read()
    except (OSError, http.client.HTTPException):
        pass
    finally:
        conn.close()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if open_page(folder) is None and (read_lock(folder) != lock
                                          or not _running(lock["pid"])):
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
