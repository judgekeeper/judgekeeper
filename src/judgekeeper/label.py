"""The local marking page's server: a session of items and marks, served on 127.0.0.1.

Standard library only. One self-contained page (no external assets); every change is saved at
once. Every request needs the random token from the URL and the bound Host (no DNS
rebinding); every POST also needs the page's own Origin, so only the page's script marks. A
request no browser sends (two Host headers, a target that is not a path) gets 400.
Shown text goes through textContent, and the data is embedded as JSON with <, > and & escaped.

Each connection is read in its own thread with a deadline, at most MAX_CONNECTIONS at once,
and requests are handled one at a time (LabelServer.busy). Host and token are checked before a
body is read; a body over MAX_BODY gets 413. The lock (server.json, owner-only) holds the
token, so a second run prints the same link, and a separate stop secret that can only ask
GET /alive or POST /stop. GET /project (the project folder's name, for the lock check) takes
the token or its SHA-256 (`proof`): the check sends the proof, never the lock's token, before
it knows the page is this project's. The server stops on Ctrl-C, /stop, IDLE_TIMEOUT without a request,
or soon after the result page once every item is marked (unless it `stays`, as for `mark`).
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import http.client
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from judgekeeper.anchors import LABELS
from judgekeeper.marks import LINKS, PRINTED
from judgekeeper.normalise import ERROR, Normaliser, UnmappedValue
from judgekeeper.redact import visible_value
from judgekeeper.table import (
    TEMPLATE_COLUMNS,
    TableError,
    _blank,
    _plain,
    _with_ids,
    guard_cell,
    kind_of,
    read_table,
    sheet_id,
    unguard_cell,
)
from judgekeeper.textio import describe_os_error, make_private, unwritable_file, write_replacing

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
IDLE_TIMEOUT = 30 * 60  # seconds
# Seconds one connection may stay silent (a browser's spare one) before it is dropped.
CONNECTION_TIMEOUT = 5
MAX_BODY = 1_000_000
MAX_DRAIN = 64_000_000  # a body over MAX_BODY is read and dropped up to this, then 413
MAX_CONNECTIONS = 32
CLOSING = 4  # connections over MAX_CONNECTIONS while the ones closed for them end
READ_STEP = 0.25  # seconds of each read of a request line and headers
MAX_HEAD = 256 * 1024  # bytes read before the request line and headers are parsed
HEADER_DEADLINE = 5  # seconds a connection may take to send its request line and headers
REFUSED_READ = 65_536  # bytes of a refused request's body read and dropped before closing
TOO_LARGE = "too large: the page sends at most 1 MB"
# Seconds a page may take to fetch its result after the last item before the server stops.
RESULT_WAIT = 60


class LabelError(Exception):
    """The items or the output file cannot be used: a usage error."""


class PageBusy(LabelError):
    """The page named in the project's lock did not answer in time (BUSY)."""


def _text(value) -> str:
    return "" if _blank(value) else _plain(value)


class LabelSession:
    """Items, their labels and notes, and the CSV they are written to. A subclass gives the
    page its data (`state`) and the progress (`summary`)."""

    def __init__(self, items_path: str | Path, out_path: str | Path):
        self.items_path = Path(items_path)
        self.out = Path(out_path)
        try:
            rows = read_table(self.items_path)
            if not rows:
                raise LabelError(f"{self.items_path} has no rows")
            columns = set().union(*rows)
            self.kind = kind_of(columns)
            self.columns = TEMPLATE_COLUMNS[self.kind]
            needed = self.columns[1:-2]
            missing = [c for c in needed if c not in columns]
            if missing:
                raise LabelError(f"{self.items_path} has no {', '.join(missing)} column")
            keyed = _with_ids(rows)
        except TableError as e:
            raise LabelError(str(e)) from None
        self.labels = LABELS[self.kind]
        self._norm = Normaliser(self.kind)
        self.items: list[dict] = []
        for item_id, row in keyed:
            item = {"id": item_id, **{c: _text(row.get(c)) for c in needed}}
            item.update(label=self._label(row.get("human_label"), item_id), deferred=False,
                        note=_text(row.get("notes")))
            self.items.append(item)
        self.by_id = {i["id"]: i for i in self.items}
        if self.out.is_file() and self.out.resolve() != self.items_path.resolve():
            self._resume()

    def _label(self, value, item_id: str) -> str | None:
        try:
            verdict = self._norm(value).verdict
        except UnmappedValue:
            raise LabelError(f"{item_id}: human_label {value!r} is not one of "
                             f"{', '.join(self.labels)}") from None
        return None if verdict == ERROR else verdict

    def _resume(self) -> None:
        try:
            rows = read_table(self.out)
        except TableError as e:
            raise LabelError(str(e)) from None
        unknown = [str(r.get("id")) for r in rows if sheet_id(r.get("id", "")) not in
                   self.by_id]
        if unknown:
            raise LabelError(f"{self.out} has rows for ids that are not in {self.items_path}: "
                             f"{', '.join(unknown[:10])}; pick another --out")
        for row in rows:
            item = self.by_id[sheet_id(row["id"])]
            item["label"] = self._label(row.get("human_label"), item["id"])
            item["note"] = unguard_cell(_text(row.get("notes")))

    def update(self, body: dict) -> None:
        """Apply one change: {"id", "label"?: label | None, "deferred"?: bool, "note"?: str}.
        The sheet on disk is read again first, so marks another page wrote are kept, not
        written over from memory."""
        self._reread()
        item = self.by_id[body["id"]]
        before = dict(item)
        try:
            self._apply(item, body)
            self.write()
        except BaseException:
            item.update(before)  # memory matches the file on disk
            raise

    def _reread(self) -> None:
        """The labels and notes on disk, over the ones in memory (_resume); a sheet that can't
        be read now leaves memory as it is, and the write says what is wrong."""
        if self.out.is_file() and self.out.resolve() != self.items_path.resolve():
            try:
                self._resume()
            except (LabelError, OSError):
                pass

    def _apply(self, item: dict, body: dict) -> None:
        if "label" in body:
            value = body["label"]
            if value is not None and value not in self.labels:
                raise ValueError(f"label must be one of {', '.join(self.labels)} or null")
            item["label"] = value
            if value is not None:
                item["deferred"] = False
        if "deferred" in body:
            if not isinstance(body["deferred"], bool):
                raise ValueError("deferred must be true or false")
            item["deferred"] = body["deferred"]
            if body["deferred"]:
                item["label"] = None
        if "note" in body:
            if not isinstance(body["note"], str):
                raise ValueError("note must be a string")
            item["note"] = body["note"]

    def write(self) -> None:
        """Write the whole sheet to a temporary file next to the output, then rename it over."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(self.columns)
        for i in self.items:
            w.writerow([guard_cell(i["id"]), *(guard_cell(i[c]) for c in self.columns[1:-2]),
                        i["label"] or "", guard_cell(i["note"])])
        make_private(self.out.parent)
        write_replacing(self.out, buf.getvalue(), newline="")

def shown(data) -> str:
    """`data` as the JSON a page is sent: no value holds a hidden character (ESC, zero-width,
    bidirectional controls: redact.visible)."""
    return json.dumps(visible_value(data), ensure_ascii=False)


def _json_for_html(data) -> str:
    """JSON that is safe inside a <script> element: no <, > or & characters at all, and no
    hidden character (shown)."""
    return (shown(data).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


ONLY_PAGE = "only the marking page in your browser can send this"
LOCK = "server.json"  # in a project's .judgekeeper/: the page judgekeeper serves for it now
LOCK_COPY = "page.json"  # the same, read when server.json is gone
MAX_LOCK = 64 * 1024  # bytes of a lock read: a real one is a few hundred
ALREADY_OPEN = ("A judgekeeper page is already open for this project. Close it with Ctrl-C in "
                "its terminal, or run `{program} --stop`.")
PROBE_TIMEOUT = 2  # seconds to wait for the page named in the lock to answer
BUSY = ("A marking page for this folder is open but not answering. Try again in a moment. "
        f"If no judgekeeper page is open, delete .judgekeeper/{LOCK}.")
RELEASE_TRIES = 40  # times to try removing the lock, RELEASE_PAUSE seconds apart
RELEASE_PAUSE = 0.05


def read_lock(folder: Path) -> dict | None:
    """{"pid", "port", "stop", "token", "settings", "link"} of the page named in the
    project's lock, or None (a lock from before 1.0 has no token: None). `link`: how its marks
    are stamped (marks.LINKS), or None. When server.json can't be read, its copy (page.json)
    is. A lock that is a link, or over MAX_LOCK, is not read."""
    for name in (LOCK, LOCK_COPY):
        try:
            path = Path(folder) / name
            if path.is_symlink():
                continue
            with path.open("rb") as f:
                raw = f.read(MAX_LOCK + 1)
            if len(raw) > MAX_LOCK:
                continue
            lock = json.loads(raw.decode("utf-8"))
            token, settings, how = lock.get("token"), lock.get("settings"), lock.get("link")
            if how not in LINKS:
                how = PRINTED if lock.get("printed") is True else None  # a lock before the stamps
            return {"pid": int(lock["pid"]), "port": int(lock["port"]),
                    "stop": str(lock["stop"]), "token": token if isinstance(token, str) else None,
                    "settings": settings if isinstance(settings, dict) else None,
                    "link": how}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def proof(token: str) -> str:
    """What the lock check sends to /project in place of the token: its SHA-256, which tells
    nothing usable to a program that is not the page."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def own_lock(folder: Path) -> dict | None:
    """The project's lock when the port it names is judgekeeper's page for this project
    (`is_page`, and /project, asked with the token's proof, names the project's folder) and
    that page answers to its stop secret, else None. Nothing from the lock but the token's
    proof is sent before the first two checks; a lock with no token fails them. A lock that
    fails them is removed: its page is gone, or another program listens on its port (a lock
    shipped with the project, or a port taken over), which never gets a token or a /stop. A
    page that does not answer in time may be busy: its lock stays, and PageBusy is raised."""
    lock = read_lock(folder)
    if lock is None:
        return None
    project = Path(folder).absolute().parent.name
    port = lock["port"]
    if (lock["token"] and is_page(port, wait=True)
            and page_folder(port, lock["token"], wait=True) == project
            and ask(port, "GET", "/alive", {"stop": lock["stop"]}, wait=True) == 200):
        return lock
    for name in (LOCK, LOCK_COPY):
        try:
            (Path(folder) / name).unlink()
        except OSError:
            pass
    return None


def live_lock(folder: Path) -> dict | None:
    """The project's lock (`own_lock`) when its page answers to its token too, else None."""
    lock = own_lock(folder)
    return lock if lock and lock["token"] and answers(lock["port"], lock["token"]) else None


def _answer(port: int, method: str, path: str, query: dict, body: dict | None = None,
            wait: bool = False) -> tuple[int, bytes] | None:
    """The status and body the page on `port` answers with, or None when nothing answers.
    Never through a proxy. `wait`: an answer that does not come within PROBE_TIMEOUT once
    connected raises PageBusy. A connection that fails or times out is nobody there: a live
    page accepts at once, even when busy, and Windows tries a port nobody listens on again
    for about 2 seconds before it refuses."""
    conn = http.client.HTTPConnection(HOST, port, timeout=PROBE_TIMEOUT)
    try:
        conn.connect()
    except (OSError, ValueError):
        conn.close()
        return None
    try:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if method == "POST":  # as the page's own script sends it
            headers["Origin"] = f"http://{HOST}:{port}"
        conn.request(method, f"{path}?{urlencode(query)}", body=data, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    except TimeoutError:
        if wait:
            raise PageBusy(BUSY) from None
        return None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def ask(port: int, method: str, path: str, query: dict, body: dict | None = None,
        wait: bool = False) -> int | None:
    """The status the page on `port` answers with, or None when nothing answers (`wait`:
    _answer)."""
    answer = _answer(port, method, path, query, body, wait)
    return None if answer is None else answer[0]


def is_page(port: int, wait: bool = False) -> bool:
    """Whether a judgekeeper page listens on `port`: it refuses a request without its token in
    its own words (`wait`: _answer)."""
    answer = _answer(port, "GET", "/alive", {}, wait=wait)
    try:
        return answer is not None and answer[0] == 403 and \
            json.loads(answer[1]) == {"error": "missing or wrong token"}
    except ValueError:
        return False


def is_open(folder: Path) -> bool:
    """Whether the project's lock (in `folder`) names its open page (`own_lock`: PageBusy
    when it does not answer in time); any other lock is stale. Asking the page, not the process, works the same everywhere: on Windows a
    process can't be looked at without the standard library's os.kill, which ends it."""
    return own_lock(folder) is not None


def page_folder(port: int, token: str, wait: bool = False) -> str | None:
    """The name of the project folder whose judgekeeper page listens on `port`, asked with
    `token`'s proof, or None (`wait`: _answer)."""
    answer = _answer(port, "GET", "/project", {"proof": proof(token)}, wait=wait)
    try:
        folder = json.loads(answer[1]).get("folder") if answer and answer[0] == 200 else None
    except (ValueError, AttributeError):
        return None
    return folder if isinstance(folder, str) and folder else None


def answers(port: int, token: str) -> bool:
    """Whether a page on `port` answers to `token`."""
    return ask(port, "GET", "/state", {"token": token}) == 200


def link(port: int, token: str) -> str:
    return f"http://{HOST}:{port}/?token={token}"


class _Head(io.RawIOBase):
    """A connection's bytes: those already read (its request line and headers), then the
    socket's."""

    def __init__(self, head: bytes, sock):
        self.head, self.sock = head, sock

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self.head:
            n = min(len(b), len(self.head))
            b[:n], self.head = self.head[:n], self.head[n:]
            return n
        return self.sock.recv_into(b)


class _HTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the host-name lookup it makes when it binds (socket.getfqdn
    of 127.0.0.1), which can hang for many seconds on some machines. The page needs no name.
    Closing it waits for no connection: the one being handled holds LabelServer.busy. At most
    MAX_CONNECTIONS are open (CLOSING more while the ones dropped for them end): `waiting`
    holds each one still sending its request line and headers, with when it began, and one
    more drops the oldest of those (`dropped`), which its own thread sees within READ_STEP
    seconds. No thread touches another's socket: on Windows a shutdown doesn't wake a thread
    waiting to read, and a socket closed under one could be read again as the next one."""

    block_on_close = False

    def __init__(self, *args, **kwargs):
        self.open = 0
        self.waiting: dict = {}  # connection -> time.monotonic() when its request began
        self.dropped: set = set()
        self.count_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name, self.server_port = HOST, self.server_address[1]

    def process_request(self, request, client_address) -> None:
        with self.count_lock:
            if self.open >= MAX_CONNECTIONS:
                oldest = min(self.waiting, key=self.waiting.get, default=None)
                if oldest is None or self.open >= MAX_CONNECTIONS + CLOSING:
                    self.shutdown_request(request)
                    return
                self.waiting.pop(oldest)
                self.dropped.add(oldest)
            self.open += 1
            self.waiting[request] = time.monotonic()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._done(request)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._done(request)

    def _done(self, request) -> None:
        with self.count_lock:
            self.open -= 1
            self.waiting.pop(request, None)
            self.dropped.discard(request)

    def handle_error(self, request, client_address) -> None:
        if isinstance(sys.exc_info()[1], OSError):
            return  # a connection the other end closed, or one dropped here: no news
        super().handle_error(request, client_address)

    def read_head(self, request, timeout: float) -> bytes | None:
        """`request`'s request line and headers (and any bytes after them), read in steps of
        READ_STEP seconds; None when it was dropped, took over HEADER_DEADLINE seconds or
        closed first. The socket then waits `timeout` seconds again."""
        end = time.monotonic() + HEADER_DEADLINE
        head = b""
        try:
            request.settimeout(READ_STEP)
            while b"\r\n\r\n" not in head and len(head) <= MAX_HEAD:
                with self.count_lock:
                    if request in self.dropped:
                        return None
                if time.monotonic() > end:
                    return None
                try:
                    chunk = request.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    return head or None
                head += chunk
            request.settimeout(timeout)
        finally:
            with self.count_lock:
                self.waiting.pop(request, None)
        return head


class LabelServer:
    def __init__(self, session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                 page: str, stays: bool = False, token: str | None = None):
        self.session = session
        self.stays = stays  # never stops by itself after the result
        # (session, link back to the labeling page) -> the result page (HTML), for GET /result
        self.result = result
        self.template = page
        self.done_at: float | None = None
        self.token = token or secrets.token_urlsafe(32)
        self.stop_secret = secrets.token_urlsafe(32)  # closes the page; can't read or mark
        self.httpd = _HTTPServer((HOST, port), _handler(self))
        self.httpd.timeout = 0.2
        self.host = HOST
        self.port = self.httpd.server_address[1]
        self.url = link(self.port, self.token)
        self.last_request = time.monotonic()
        self.busy = threading.Lock()  # held while a request is handled: one at a time
        self._stopped = False
        self.lock: Path | None = None  # the lock file this server wrote (make_server)
        self.settings: dict | None = None  # what the page shows (page.page_key), in the lock

    def hold(self, folder: Path, settings: dict | None = None) -> None:
        """Write the project's lock and its copy (owner-only): this process, port, stop
        secret and token, how its marks are stamped (marks.LINKS), and `settings`."""
        self.lock = Path(folder).absolute() / LOCK  # /project names its folder
        self.settings = settings
        self.write_lock()

    def write_lock(self) -> None:
        if self.lock is None:
            return
        text = json.dumps({"pid": os.getpid(), "port": self.port, "stop": self.stop_secret,
                           "token": self.token, "settings": self.settings,
                           "link": getattr(self.session, "link", None)})
        write_replacing(self.lock, text)
        write_replacing(self.lock.with_name(LOCK_COPY), text)

    def release(self) -> None:
        """Remove the lock and its copy, each when it is still this server's."""
        if self.lock is None:
            return
        for path in (self.lock, self.lock.with_name(LOCK_COPY)):
            self._remove(path)
        self.lock = None

    def _remove(self, path: Path) -> None:
        """Remove `path` when it holds this server's stop secret. Windows refuses to delete a
        file that another process (`mark --stop`, asking whether the page is open) is
        reading, so a refusal is tried again for a moment."""
        for tries in range(RELEASE_TRIES, 0, -1):
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("stop") == \
                        self.stop_secret:
                    path.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError as e:
                if tries == 1:
                    print(f"judgekeeper: {path.name} was not removed ({e})", file=sys.stderr)
                time.sleep(RELEASE_PAUSE)
            except (OSError, ValueError, AttributeError) as e:
                print(f"judgekeeper: {path.name} was not removed ({type(e).__name__}: {e})",
                      file=sys.stderr)
                break

    def serve(self, idle_timeout: float | None = None) -> None:
        """Handle requests until stop(), Ctrl-C, or idle_timeout seconds without a request."""
        idle = IDLE_TIMEOUT if idle_timeout is None else idle_timeout
        try:
            while not self._stopped and time.monotonic() - self.last_request < idle:
                self.httpd.handle_request()
                if self.done_at is not None and time.monotonic() - self.done_at > RESULT_WAIT:
                    break
        finally:
            with self.busy:  # a request being handled finishes first
                self.httpd.server_close()
                self.release()

    def stop(self) -> None:
        self._stopped = True

    def finished(self) -> bool:
        """Every item labeled, none deferred: nothing is left for the page to offer."""
        items = getattr(self.session, "items", [])
        return self.session.summary()["done"] and not any(
            isinstance(i, dict) and i.get("deferred") for i in items)

    def page(self) -> tuple[str, str]:
        """The page and the nonce its script runs under."""
        nonce = secrets.token_urlsafe(16)
        return (self.template.replace("__NONCE__", nonce)
                .replace("__TOKEN__", self.token)
                .replace("__DATA__", _json_for_html(self.session.state()))), nonce


def _handler(server: LabelServer):
    class Handler(BaseHTTPRequestHandler):
        timeout = CONNECTION_TIMEOUT

        def log_message(self, format, *args):
            pass  # quiet: request lines carry the token

        def version_string(self) -> str:
            return "judgekeeper"  # the Server header: not the Python version

        def handle_one_request(self):
            head = server.httpd.read_head(self.connection, self.timeout)
            if head is None:
                self.close_connection = True
                return
            self.rfile.close()  # nothing read from it yet
            self.rfile = io.BufferedReader(_Head(head, self.connection))
            super().handle_one_request()

        def __getattr__(self, name: str):
            if name.startswith("do_"):  # a method with no do_ of its own
                return self._other
            raise AttributeError(name)

        def _send(self, status: int, body: bytes, content_type: str | None, extra=None) -> None:
            self.send_response(status)
            if status != 204:  # No Content: no type, no length
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if self.close_connection:
                self.send_header("Connection", "close")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, shown(data).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self, url) -> bool:
            """The token, or the stop secret on the two paths it opens (/alive, /stop). Only
            a request with one of them keeps the page open (IDLE_TIMEOUT)."""
            path = self.path
            if len(self.headers.get_all("Host") or ()) > 1 or not path.startswith("/") \
                    or path.startswith("//"):  # "//evil.com/state": a host, to urlsplit
                self._json(400, {"error": "not a request a browser sends"})
                return False
            if self.headers.get("Host") != f"{HOST}:{server.port}":
                self._json(403, {"error": "wrong Host header"})
                return False
            if url.path == "/favicon.ico" and self.command == "GET":
                return True  # a browser asks for the icon without the token
            query = parse_qs(url.query)
            if url.path == "/project" and self.command == "GET" and hmac.compare_digest(
                    query.get("proof", [""])[0].encode(), proof(server.token).encode()):
                return True  # the lock check (own_lock)
            token = query.get("token", [""])[0]
            if hmac.compare_digest(token.encode(), server.token.encode()):
                server.last_request = time.monotonic()
                return True
            stop = query.get("stop", [""])[0]
            if url.path in ("/alive", "/stop") and hmac.compare_digest(
                    stop.encode(), server.stop_secret.encode()):
                server.last_request = time.monotonic()
                return True
            if self.command in ("GET", "HEAD") and url.path == "/" and \
                    "text/html" in (self.headers.get("Accept") or ""):  # a browser: a page
                from judgekeeper.mark_page import OLD_LINK_CSP, old_link_page

                self._send(403, old_link_page().encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": OLD_LINK_CSP})
                return False
            self._json(403, {"error": "missing or wrong token"})
            return False

        def _same_origin(self) -> bool:
            """Whether a POST comes from the page's own script (see the module's docstring)."""
            site = self.headers.get("Sec-Fetch-Site")
            if self.headers.get("Origin") == f"http://{HOST}:{server.port}" and \
                    site in (None, "same-origin"):
                return True
            self._json(403, {"error": ONLY_PAGE})
            return False

        def _body(self) -> bytes | None:
            """The request's body, read before any answer (see the module's docstring); None
            when it has no length that can be read."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if length > MAX_BODY:  # read and dropped: unread data would reset the answer
                left = min(length, MAX_DRAIN)
                try:
                    while left > 0 and (chunk := self.rfile.read(min(left, 65536))):
                        left -= len(chunk)
                except OSError:
                    pass
                return None
            return self.rfile.read(length) if length > 0 else None

        def do_GET(self):
            with server.busy:
                self._get()

        def _refused(self) -> bool:
            """Whether a request with a body is refused (wrong Host, no token, or a POST from
            elsewhere), checked before its body is read; a refused one is answered and closed,
            with no more than REFUSED_READ bytes of its body read and dropped."""
            asked, self.close_connection = self.close_connection, True
            refused = not self._allowed(urlsplit(self.path)) or (
                self.command == "POST" and not self._same_origin())
            if not refused:
                self.close_connection = asked
                return False
            try:
                left = min(int(self.headers.get("Content-Length") or 0), REFUSED_READ)
                self.connection.settimeout(0.2)
                while left > 0 and (chunk := self.rfile.read1(min(left, 65536))):
                    left -= len(chunk)
            except (OSError, ValueError):
                pass
            return True

        def do_POST(self):
            if self._refused() or self._far_too_large():  # the token first
                return
            body = self._body()
            with server.busy:
                self._post(body)

        def _far_too_large(self) -> bool:
            """A body over MAX_DRAIN is answered 413 at once, before any of it is read, and
            the connection closed: the sending side first, then what is still on its way is
            read and dropped for a moment, so closing does not reset the answer away."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return False
            if length <= MAX_DRAIN:
                return False
            self.close_connection = True
            self._send(413, shown({"error": TOO_LARGE}).encode("utf-8"),
                       "application/json; charset=utf-8", {"Connection": "close"})
            try:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                left, until = MAX_DRAIN, time.monotonic() + CONNECTION_TIMEOUT
                while left > 0 and time.monotonic() < until and (
                        chunk := self.rfile.read1(65536)):
                    left -= len(chunk)
            except OSError:
                pass
            return True

        def _other(self):
            if self._refused():
                return
            self._body()
            with server.busy:
                self._send(405, b'{"error": "method not allowed"}',
                           "application/json; charset=utf-8", {"Allow": "GET, POST"})

        def _get(self):
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            if url.path in ("/", "/state"):
                server.done_at = None  # the page is open and asking: keep serving it
            if url.path == "/favicon.ico":
                self._send(204, b"", None)  # no icon
            elif url.path == "/project":
                folder = server.lock.parent.parent.name if server.lock is not None else None
                self._json(200, {"folder": folder})
            elif url.path == "/alive":
                self._json(200, {"open": True})
            elif url.path == "/":
                page, nonce = server.page()
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; "
                       "style-src 'unsafe-inline'; font-src data:; connect-src 'self'; "
                       "img-src 'none'; base-uri 'none'; form-action 'none'; "
                       "frame-ancestors 'none'")
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
            elif url.path == "/state":
                self._json(200, server.session.state())
            elif url.path == "/result" and server.result is not None:
                try:
                    page = server.result(server.session, f"/?token={server.token}")
                except OSError as e:  # .judgekeeper/ can't be written: say it, as /label does
                    said = str(describe_os_error(e) or e).rstrip(".")  # one full stop
                    self._send(500, (f"Not saved: {said}. Your marks are saved; try again once "
                                     "the folder can be written.").encode(),
                               "text/plain; charset=utf-8")
                    return
                from judgekeeper.report_page import LIVE_CSP

                csp = f"{LIVE_CSP}; frame-ancestors 'none'"  # it saves reasons
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
                if server.finished() and not server.stays:
                    server.stop()  # nothing left to label: the page holds the result
            else:
                self._json(404, {"error": "not found"})

        def _post(self, raw: bytes | None):
            url = urlsplit(self.path)  # Host, token and Origin are checked (_refused)
            if url.path == "/stop":
                self._json(200, {"stopped": True})
                server.stop()
                return
            if url.path == "/printed" and hasattr(server.session, "link"):
                try:
                    how = (json.loads(raw) if raw else {}).get("link", PRINTED)
                except (ValueError, AttributeError, RecursionError):
                    how = None
                if how not in LINKS:
                    self._json(400, {"error": "unknown link"})
                    return
                server.session.link = how
                try:
                    server.write_lock()  # a page started again with this token is stamped too
                except OSError:
                    pass
                self._json(200, {"link": how})
                return
            if url.path != "/label":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY:
                self._json(413, {"error": TOO_LARGE})
                return
            try:
                if raw is None:
                    raise ValueError("expected a JSON body")
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise TypeError("expected a JSON object")
                if not isinstance(body.get("id"), str):
                    raise TypeError("expected a JSON object with an id")
            except (ValueError, TypeError, UnicodeDecodeError) as e:
                self._json(400, {"error": str(e)})
                return
            except RecursionError:  # nested deeper than Python's JSON reader goes
                self._json(400, {"error": "expected a JSON object"})
                return
            if body["id"] not in server.session.by_id:
                self._json(404, {"error": "no item with that id"})
                return
            try:
                server.session.update(body)
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            except (TypeError, KeyError) as e:  # a damaged file in .judgekeeper/
                self._json(400, {"error": f"not saved: a file in .judgekeeper/ is damaged "
                                          f"({type(e).__name__})"})
                return
            except OSError as e:
                self._json(500, {"error": describe_os_error(e)
                                 or f"could not write {server.session.out}: {e}"})
                return
            summary = server.session.summary()
            pop_up = getattr(server.session, "pop_up", None)
            if pop_up is not None and pop_up(summary["status"]):
                summary["popup"] = True
            self._json(200, {"summary": summary})
            if server.stays:
                return
            if server.result is not None and server.finished():
                if server.done_at is None:
                    server.done_at = time.monotonic()
            else:  # a skip, or a label taken back: the page goes on
                server.done_at = None

    return Handler


def make_server(session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                page: str, lock: Path | None = None, stays: bool = False,
                token: str | None = None, settings: dict | None = None) -> LabelServer:
    """A server for `session`, or a LabelError that says why there cannot be one. With `lock`
    (the project's .judgekeeper/), one server per project: when its page is already open,
    that is the error; else this server holds the lock until it stops. Two pages on one
    project would each write their marks over the other's. `token`: the one its caller made
    (default: a new one); `settings`: kept in the lock."""
    if lock is not None and is_open(lock):
        from judgekeeper.textio import program

        raise LabelError(ALREADY_OPEN.format(program=program()))
    # Labels are written on the first click: say now if they cannot be, not in the page.
    unwritable = unwritable_file(session.out)
    if unwritable:
        raise LabelError(unwritable)
    try:
        server = LabelServer(session, port, result=result, page=page, stays=stays,
                             token=token)
    except OSError as e:
        raise LabelError(f"cannot listen on {HOST}:{port} ({e.strerror}); try --port") from None
    if lock is not None:
        try:
            server.hold(lock, settings)
        except OSError:
            pass  # no lock: the labels' own write still says when it can't save
    return server
