"""Requests to a page server from the tests. Windows can refuse, reset or abort a local
connection now and then (a server thread not listening yet, a busy loopback): such a request
is sent again for a few seconds instead of failing the test. Any answer, an error status
included, is returned at once."""

from __future__ import annotations

import time

RETRIED = (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)
WAIT = 5  # seconds


def retried(send, wait: float = WAIT):
    """send(), sent again while its connection is refused, reset or aborted."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return send()
        except OSError as e:
            reason = getattr(e, "reason", e)  # urllib wraps the error in a URLError
            if not isinstance(reason, RETRIED) or time.monotonic() > deadline:
                raise
            time.sleep(0.1)
