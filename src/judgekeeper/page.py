"""The marking page: the page `judgekeeper` and `judgekeeper mark` open to mark answers on,
served by a process of its own (background.py) or, with --wait, by the command itself.

The page's link holds its token, and the token never passes through a coding agent. The
command makes the token, hands it to the page's process on its stdin (`main`), and opens the
link in the person's browser itself (`show`): the output says the page is open, with no link.
Only when no browser opens is the link printed. Without a terminal (an agent or a script
reads the output) that is said, and every mark made on that page is stamped "link":
"printed", so the result can count them. At a terminal (the person's own) a printed link is
not stamped.

An open page can't be shown again without its token, so opening a page closes the open one
first (with the stop secret in server.json) and starts a new one, with a new token. The marks
are on disk: nothing is lost.
"""

from __future__ import annotations

import faulthandler
import json
import secrets
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import background, marks, start_label
from judgekeeper.label import LabelError, LabelServer, ask, is_open, make_server
from judgekeeper.start_label import StartSession, Workspace

OPEN = "The marking page is open in your browser."
NO_BROWSER = ("judgekeeper could not open a browser, so the link is printed here, where your "
              "coding agent can read it.")
DONE = "When you're done, tell your coding agent, or run judgekeeper in your terminal."
BROWSER, TERMINAL, PRINTED = "browser", "terminal", marks.PRINTED  # how the page was shown


def marking_status(session: StartSession) -> dict:
    """The line under the meters (start_label.start_status); once a result is ready it adds
    how to get it."""
    status = start_label.start_status(session)
    if status["ready"]:
        status = {**status, "text": f"{status['text']} {DONE}"}
    return status


def marking_session(ws: Workspace) -> StartSession:
    return StartSession(ws, status=marking_status)


def page_server(ws: Workspace, port: int, command: str,
                start_command: str = "judgekeeper start", token: str | None = None):
    """The marking page: marking, and the result (no review or fix). Every click is a stamped
    line in marks.jsonl. It holds the project's lock and stays open after the result, until
    /stop, Ctrl-C or 2 hours idle. `command` is how to come back to it; the result keeps
    `start_command`. `token`: the one the command made (default: a new one)."""
    session = marking_session(ws)

    def result(session: StartSession, back: str) -> str:
        r = start_label.store_result(ws, session, start_command)
        return start_label.result_html(start_label._scrubbed(r), back, marking=command)

    return make_server(session, port, result=result,
                       page=start_label.page_template(ws.data(), command), lock=ws.dir,
                       stays=True, token=token)


@dataclass
class Page:
    url: str
    port: int
    token: str
    server: LabelServer | None = None  # served by this process (--wait)


def open_new(ws: Workspace, port: int, command: str, start_command: str,
             here: bool = False) -> Page | None:
    """Close the page open for this project, then start a new one: in the background, or
    served by this process (`here`, for --wait). None when it could not start."""
    if is_open(ws.dir):
        background.stop(ws.dir)
    if here:
        server = page_server(ws, port, command, start_command)
        return Page(server.url, server.port, server.token, server)
    token = secrets.token_urlsafe(32)
    url = background.start(ws.dir, {"root": str(ws.root.resolve()), "port": port,
                                    "command": command, "start_command": start_command},
                           token)
    if url is None:
        return None
    from urllib.parse import urlsplit

    return Page(url, urlsplit(url).port, token)


def _stamp_printed(page: Page) -> bool:
    """Every later mark on `page` is stamped "link": "printed"."""
    if page.server is not None:
        page.server.session.link = PRINTED
        return True
    return ask(page.port, "POST", "/printed", {"token": page.token}, body={}) == 200


def terminal() -> bool:
    """Whether a person reads this output at a terminal: input and output are both one. On
    Windows the NUL device says it is a terminal, so input alone is not enough; and what
    matters for the link is who reads the output."""
    from judgekeeper.start import _interactive

    try:
        output = sys.stdout.isatty()
    except (AttributeError, ValueError):
        output = False
    return output and _interactive()


def show(say, page: Page, no_browser: bool, wait: bool) -> str | None:
    """Open the page in the person's browser and say so (BROWSER). At a terminal, print the
    link when no browser opened or with --wait (TERMINAL). Without one, when no browser
    opened: say so, stamp the page's marks, then print the link (PRINTED). None when the
    marks could not be stamped: then the link is not printed."""
    at_terminal = terminal()
    opened = not no_browser and webbrowser.open(page.url)
    if opened and not (at_terminal and wait):
        say(OPEN)
        return BROWSER
    if not at_terminal:
        say(NO_BROWSER)
        if not _stamp_printed(page):
            return None
    print(f"Marking page: {page.url}")  # the link whole: printed by hand, never by say
    sys.stdout.flush()
    return TERMINAL if at_terminal else PRINTED


def serve(server: LabelServer) -> None:
    faulthandler.cancel_dump_traceback_later()  # the page started
    try:
        server.serve()
    except KeyboardInterrupt:
        pass


# The page's own process ------------------------------------------------------------------

def _watch() -> None:
    """When the page has not started a little before the command stops waiting for it, write
    where it is stuck to stderr (page.log)."""
    try:
        faulthandler.dump_traceback_later(background.WAIT - 2, exit=False, file=sys.stderr)
    except (AttributeError, OSError, ValueError):
        pass


def main() -> int:
    """`python -m judgekeeper.page`, as background.start runs it: one JSON line on stdin holds
    the token, the project's root, the port and the two commands the page shows. Errors go
    to stderr (page.log), never the token."""
    _watch()
    try:
        given = json.loads(sys.stdin.readline())
        token, root = str(given["token"]), Path(given["root"])
        port, command = int(given["port"]), str(given["command"])
        start_command = str(given["start_command"])
    except (ValueError, KeyError, TypeError):
        faulthandler.cancel_dump_traceback_later()
        print("judgekeeper: the page got no token on its input, so it did not start.",
              file=sys.stderr)
        return 2
    if len(token) < 32:
        faulthandler.cancel_dump_traceback_later()
        print("judgekeeper: the page's token is too short, so it did not start.",
              file=sys.stderr)
        return 2
    try:
        server = page_server(Workspace(root), port, command, start_command, token=token)
    except (LabelError, OSError) as e:
        faulthandler.cancel_dump_traceback_later()
        print(f"judgekeeper: {e}", file=sys.stderr)
        return 2
    serve(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
