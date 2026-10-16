"""The marking page: the page `judgekeeper` and `judgekeeper mark` open to mark answers on,
served by a process of its own (background.py) or, with --wait, by the command itself.

The page's link holds its token. The command makes the token, hands it to the page's process
on its stdin (`main`), and opens the link in the person's browser itself (`show`): the output
says the page is open, with no link. Only when no browser opens (or with --no-browser, on a
remote machine) is the link printed. Without a terminal (another program reads the output)
every mark made on that page is stamped "link": "printed", so the result can count them. At a
terminal (the person's own) a printed link is not stamped.

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

from judgekeeper import background, marks, start_label, textio
from judgekeeper.label import (
    DEFAULT_PORT,
    HOST,
    LabelError,
    LabelServer,
    ask,
    is_open,
    is_page,
    make_server,
)
from judgekeeper.start_label import StartSession, Workspace

LINK = "Open this link in your browser to mark answers:"
DONE = "When you're done, run {program} in your terminal."
BROWSER, TERMINAL, PRINTED = "browser", "terminal", marks.PRINTED  # how the page was shown
OTHER_PORTS = range(8766, 8786)  # tried when the default port is taken
ANOTHER_PROJECT = "A marking page for another project is open; close it there with `{command}`."


def port_free(port: int) -> bool:
    """Whether nothing listens on `port`."""
    import socket

    with socket.socket() as s:
        try:
            s.bind((HOST, port))
        except OSError:
            return False
    return True


def choose_port(port: int, say) -> int:
    """`port`, unless it is the default and taken: then the first free one of OTHER_PORTS,
    else `port` (starting the page then says it is taken). When a judgekeeper page holds the
    default (another project's: this project's is closed first), that is said."""
    if port != DEFAULT_PORT or port_free(port):
        return port
    if is_page(port):
        say(ANOTHER_PROJECT.format(command=textio.program("--stop")))
    return next((other for other in OTHER_PORTS if port_free(other)), port)


def marking_status(session: StartSession) -> dict:
    """The line under the meters (start_label.start_status); once a result is ready it adds
    how to get it."""
    status = start_label.start_status(session)
    if status["ready"]:
        from judgekeeper.textio import program

        status = {**status, "text": f"{status['text']} {DONE.format(program=program())}"}
    return status


def marking_session(ws: Workspace) -> StartSession:
    return StartSession(ws, status=marking_status)


def page_server(ws: Workspace, port: int, command: str,
                start_command: str | None = None, token: str | None = None):
    """The marking page: marking, and the result. Every click is a stamped
    line in marks.jsonl. It holds the project's lock and stays open after the result, until
    /stop, Ctrl-C or 30 minutes idle. `command` is how to come back to it; the result keeps
    `start_command`. `token`: the one the command made (default: a new one)."""
    start_command = start_command or textio.program()
    session = marking_session(ws)

    def result(session: StartSession, back: str) -> str:
        from judgekeeper import check

        r = start_label.store_result(ws, session, start_command)
        return start_label.result_html(start_label._scrubbed(r), back, marking=command,
                                       history=start_label._scrubbed(check.report_rows(ws)),
                                       fixing=start_label._fixing(ws))

    return make_server(session, port, result=result,
                       page=start_label.page_template(ws.data(), command), lock=ws.dir,
                       stays=True, token=token)


def server_for(ws: Workspace, settings: dict, token: str):
    """The marking page `settings` ask for."""
    return page_server(ws, int(settings["port"]), str(settings["command"]),
                       str(settings["start_command"]), token=token)


@dataclass
class Page:
    url: str
    port: int
    token: str
    server: LabelServer | None = None  # served by this process (--wait)


def open_new(ws: Workspace, port: int, command: str, start_command: str,
             here: bool = False, say=lambda line: None) -> Page | None:
    """Close the page open for this project, then start a new one (on a free port when the
    default is taken, choose_port; `say` says why): in the background, or served by this
    process (`here`, for --wait). None when it could not start."""
    if is_open(ws.dir):
        background.stop(ws.dir)
    port = choose_port(port, say)
    if here:
        server = page_server(ws, port, command, start_command)
        return Page(server.url, server.port, server.token, server)
    token = secrets.token_urlsafe(32)
    settings = {"root": str(ws.root.resolve()), "port": port, "command": command,
                "start_command": start_command}
    url = background.start(ws.dir, settings, token)
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
    """Open the page in the person's browser (BROWSER: nothing is said, the caller says it).
    At a terminal, print the link when no browser opened, with --no-browser or with --wait
    (TERMINAL). Without one, stamp the page's marks first, then print the link (PRINTED).
    None when the marks could not be stamped: then the link is not printed."""
    at_terminal = terminal()
    in_browser = not no_browser and webbrowser.open(page.url)
    if in_browser and not (at_terminal and wait):
        return BROWSER
    if not at_terminal and not _stamp_printed(page):
        return None
    say(LINK)
    print(page.url)  # the link whole: printed by hand, never by say
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
    the token, the project's root, the port and the two commands the page shows. Errors go to
    stderr (page.log), never the token."""
    _watch()
    try:
        given = json.loads(sys.stdin.readline())
        token, root = str(given["token"]), Path(given["root"])
        settings = {"port": int(given["port"]), "command": str(given["command"]),
                    "start_command": str(given["start_command"])}
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
        server = server_for(Workspace(root), settings, token)
    except (LabelError, OSError) as e:
        faulthandler.cancel_dump_traceback_later()
        print(f"judgekeeper: {e}", file=sys.stderr)
        return 2
    serve(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
