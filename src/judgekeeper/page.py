"""The marking page: the page `judgekeeper` and `judgekeeper mark` open to mark answers on,
served by a process of its own (background.py) or, with --wait, by the command itself.

The page's link holds its token. The command makes the token, hands it to the page's process
on its stdin (`main`) and opens the link in the browser itself (`show`), so the output prints
no link unless no browser opens (or with --no-browser). Marks made through a link printed for
another program are stamped "link": "printed", and with BROWSER set "link": "browser-env".
A link printed at the person's own terminal is not stamped.

The token is kept in server.json (owner-only, removed when the page stops), so a second run
prints the same link and the open tab keeps working: a page already showing the same thing
(`page_key`) is kept on its own port; else it is stopped and started again with the same token.
While one run opens a project's page, .judgekeeper/opening is there and a second run waits for
it (`_opening`).
"""

from __future__ import annotations

import faulthandler
import hashlib
import json
import os
import re
import secrets
import sys
import time
import webbrowser
from contextlib import contextmanager
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
    link,
    live_lock,
    make_server,
)
from judgekeeper.start_label import StartSession, Workspace

LINK = "Open this link in your browser to mark answers:"
RESULT_LINK = "Open this link in your browser to see your result:"
DONE = "When you're done, run {program} in your terminal."
BROWSER, TERMINAL, PRINTED = "browser", "terminal", marks.PRINTED  # how the page was shown
OTHER_PORTS = range(8766, 8786)  # tried when the default port is taken
PICKS = 10  # ports tried when one judgekeeper picked is taken before the page binds it
SLOW_BROWSER = 10  # seconds: a browser that took longer to open may not have shown the page
_clock = time.monotonic
ANOTHER_PROJECT = "A marking page for another project is open; close it there with `{command}`."
OPENING = "opening"  # in .judgekeeper/ while a run prepares the pool or opens the page
OPENING_NOW = "judgekeeper is already opening the marking page for this folder."
_PORT_FLAG = re.compile(r" --port \d+")


def port_free(port: int) -> bool:
    """Whether nothing listens on `port`. As the page binds it (http.server reuses an address
    a closed page left in TIME_WAIT, on macOS and Linux)."""
    import socket

    with socket.socket() as s:
        try:
            if os.name != "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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


def marking_status(session: StartSession, run: str | None = None) -> dict:
    """The line under the meters (start_label.start_status; `run`: the command that opened
    the page); once a result is ready it adds how to get it."""
    status = start_label.start_status(session, run)
    if status["ready"]:
        from judgekeeper.textio import program

        status = {**status, "text": f"{status['text']} {DONE.format(program=program())}"}
    return status


def marking_session(ws: Workspace, run: str | None = None) -> StartSession:
    return StartSession(ws, status=lambda session: marking_status(session, run))


def page_key(ws: Workspace, command: str, start_command: str) -> dict:
    """What a page shows besides the marks: the two commands (but the port they ask for: the
    open page keeps its own), and the check it is for."""
    try:
        about = hashlib.sha256(ws.start.read_bytes()).hexdigest()
    except OSError:
        about = None
    return {"command": _PORT_FLAG.sub("", command),
            "start_command": _PORT_FLAG.sub("", start_command), "start": about}


def page_server(ws: Workspace, port: int, command: str,
                start_command: str | None = None, token: str | None = None,
                stamp: str | None = None):
    """The marking page: marking, and the result. Every click is a stamped
    line in marks.jsonl. It holds the project's lock and stays open after the result, until
    /stop, Ctrl-C or 30 minutes idle. `command` is how to come back to it; the result keeps
    `start_command`. `token`: the one the command made (default: a new one). `stamp`: how the
    page with the same token was stamped before (marks.LINKS), so its marks are stamped so."""
    start_command = start_command or textio.program()
    session = marking_session(ws, start_command)
    if stamp in marks.LINKS:
        session.link = stamp

    def result(session: StartSession, back: str) -> str:
        return start_label.live_result(ws, session, start_command, back)

    return make_server(session, port, result=result,
                       page=start_label.page_template(ws.data(), command), lock=ws.dir,
                       stays=True, token=token,
                       settings=page_key(ws, command, start_command))


def server_for(ws: Workspace, settings: dict, token: str):
    """The marking page `settings` ask for."""
    return page_server(ws, int(settings["port"]), str(settings["command"]),
                       str(settings["start_command"]), token=token,
                       stamp=settings.get("link"))


@dataclass
class Page:
    url: str
    port: int
    token: str
    server: LabelServer | None = None  # served by this process (--wait)
    kept: bool = False  # the page that was open already: this run did not start it

    @property
    def result_url(self) -> str:
        """The same page, opened at its result page (/result), with its token."""
        return self.url.replace("/?token=", "/result?token=", 1)


def open_new(ws: Workspace, port: int, command: str, start_command: str,
             here: bool = False, say=lambda line: None) -> Page | None:
    """The page for this project, with the token of the one open (a new token when none is):
    the open page itself, on its port, when it shows the same (page_key); else it is
    closed and a page started (on its port when free, else on a free port when the default
    is taken, choose_port; `say` says why): in the background, or served by this process
    (`here`, for --wait). When a port judgekeeper picked is taken before the page binds it
    (another run), the next free one, up to PICKS tries. None when it could not start."""
    with one_at_a_time(ws.dir, say):
        old = live_lock(ws.dir)
        token = old["token"] if old else secrets.token_urlsafe(32)
        if (old is not None and not here
                and old["settings"] == page_key(ws, command, start_command)):
            return Page(link(old["port"], token), old["port"], token, kept=True)
        if is_open(ws.dir):
            background.stop(ws.dir)
        stamp = old["link"] if old is not None else None
        picked = port == DEFAULT_PORT  # judgekeeper's choice, not the person's
        if old is not None and port in (0, DEFAULT_PORT) and port_free(old["port"]):
            port = old["port"]  # the open tab's link still works
        else:
            port = choose_port(port, say)
        for _ in range(PICKS):
            try:
                if here:
                    server = page_server(ws, port, command, start_command, token=token,
                                         stamp=stamp)
                    return Page(server.url, server.port, server.token, server)
                settings = {"root": str(ws.root.resolve()), "port": port, "command": command,
                            "start_command": start_command, "link": stamp}
                url = background.start(ws.dir, settings, token)
            except LabelError:
                url = None
                if not picked or port_free(port):
                    raise
            if url is not None or not picked or port_free(port):
                break
            port = next((p for p in (DEFAULT_PORT, *OTHER_PORTS) if port_free(p)), 0)
    if url is None:
        return None
    from urllib.parse import urlsplit

    return Page(url, urlsplit(url).port, token)


@contextmanager
def one_at_a_time(folder: Path, say):
    """While this run prepares the project's pool or opens its page: .judgekeeper/opening.
    Another run that is doing so is said and waited for (an older mark, left by a run that
    stopped, is not). Two runs at once never write the pool twice, and neither reads a file
    the other is replacing (Windows refuses that)."""
    path = Path(folder) / OPENING
    wait = 2 * background.WAIT
    said, made = False, False
    while not made:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                old = time.time() - path.stat().st_mtime > wait
            except OSError:
                old = False  # gone meanwhile: try again
            if old:
                _remove(path)
            elif not said:
                say(OPENING_NOW)
                said = True
            time.sleep(0.1)
            continue
        except OSError:
            break  # no mark can be made here: open it all the same
        os.close(fd)
        made = True
    try:
        yield
    finally:
        if made:
            _remove(path)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _stamp(page: Page, how: str = PRINTED) -> bool:
    """Every later mark on `page` is stamped "link": `how` (marks.LINKS)."""
    if page.server is not None:
        page.server.session.link = how
        return True
    return ask(page.port, "POST", "/printed", {"token": page.token}, body={"link": how}) == 200


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


def show(say, page: Page, no_browser: bool, wait: bool, result: bool = False) -> str | None:
    """Open the page in the person's browser (BROWSER: nothing is said, the caller says it).
    When the BROWSER variable names the program that opens it, stamp the page's marks first.
    At a terminal, print the link when no browser opened (or it took more than SLOW_BROWSER
    seconds), with --no-browser or with --wait (TERMINAL). Without one, stamp the page's marks first, then print the link (PRINTED).
    None when the marks could not be stamped: then the page is not opened, or the link not
    printed. `result`: the page is opened at its result page (every answer is marked: the
    reason boxes are what is left)."""
    at_terminal = terminal()
    url = page.result_url if result else page.url
    if not no_browser and os.environ.get("BROWSER") and not _stamp(page, marks.BROWSER_ENV):
        return None
    began = _clock()
    in_browser = not no_browser and webbrowser.open(url)
    if in_browser and _clock() - began > SLOW_BROWSER:  # it hung: the link is printed too
        in_browser = False
    if in_browser and not (at_terminal and wait):
        return BROWSER
    if not at_terminal and not _stamp(page):
        return None
    say(RESULT_LINK if result else LINK)
    print(url)  # the link whole: printed by hand, never by say
    textio.flush_stdout()
    return TERMINAL if at_terminal else PRINTED


def serve(server: LabelServer) -> None:
    """Serve the page until it closes. Ctrl-C closes it and goes on up: with --wait the
    command says "Stopped." and exits 130."""
    faulthandler.cancel_dump_traceback_later()  # the page started
    server.serve()


def close(ws: Workspace, opened: Page | None) -> None:
    """Close the page this run started (Ctrl-C before its link was printed): in the
    background, or served by this process. A page that was open already stays."""
    if opened is not None and opened.kept:
        return
    if opened is not None and opened.server is not None:
        opened.server.stop()
        opened.server.serve()  # stopped: it only closes its socket and releases the lock
    else:
        background.stop(ws.dir)


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
                    "start_command": str(given["start_command"]),
                    "link": given.get("link")}
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
    try:
        serve(server)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
