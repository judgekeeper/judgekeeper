"""The local labeling page that `judgekeeper start` serves: a session of items and labels, and
the server for it.

Standard library only. The server binds 127.0.0.1, serves one self-contained page (inline CSS
and JS, no external assets) and writes every change to the labels CSV at once (id, input,
output, human_label, notes).

Security: the page and every request need a random token from the URL; a request whose Host
header is not the bound address is refused (DNS rebinding); every displayed string goes
through textContent, and the data is embedded as JSON with <, > and & escaped. Each
connection is read in a thread of its own, so a slow or silent one never holds up the rest;
it is dropped after CONNECTION_TIMEOUT seconds. Requests are then handled one at a time
(LabelServer.busy). A POST's body is read before any answer: a connection closed with unread
data is reset on Windows, and the answer is lost. Any other method (OPTIONS, HEAD...) gets the
same Host and token checks, then 405; no answer names the Python version. The server stops on Ctrl-C, on a
POST to /stop (it works the same on every system), and after IDLE_TIMEOUT seconds without a
request. The project's lock (server.json) holds a separate stop secret, never the token: with
it a request can only ask whether the page is open (GET /alive) or close it (POST /stop). A
copy of the lock (page.json) lets --stop find the page when server.json is gone.
POST /printed (with the token) says the link was printed where a coding agent could read it:
every later mark is stamped so. Every POST also needs the page's own Origin
(http://127.0.0.1:<port>, or localhost) and, when the browser sends it, `Sec-Fetch-Site:
same-origin`: only the page's own script marks, never another site or a program that has the
link (judgekeeper's own requests, `ask`, send the Origin).

The caller passes the page (start_page.py) and a `result` function: GET /result answers with
the result page, a static HTML page that runs no script. Once every item is labeled, none
deferred (finished), the server stops right after serving that page, or RESULT_WAIT seconds
after the last item if nobody fetches it; not after a click the session's `asks_why` says
leaves the page on its Why? box, which can take longer. While an item is deferred, the page
offers to look at it again, so the server keeps serving (until Ctrl-C or IDLE_TIMEOUT), also
after the result page; the page asking again (GET /, /state) or a label taken back (undo)
stops the RESULT_WAIT count. A server that `stays` (the page `judgekeeper mark` serves) never
stops by itself after the result: the person may mark more. It may also pass `switches`: a GET of one of their paths swaps
the session, the page and the result function (from labeling to the review of the
disagreements) and sends the browser back to the page; a switch that returns None leaves them
as they are. A session may answer POSTs to paths of its own (`posts`: path -> a function from
the JSON body to the JSON answer), under the same token and Host rules, and say what a body
too big to read means on one (`too_long`: path -> the error).
"""

from __future__ import annotations

import csv
import hmac
import http.client
import io
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from judgekeeper.anchors import LABELS
from judgekeeper.marks import PRINTED
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
from judgekeeper.textio import describe_os_error, unwritable_file, write_replacing

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
IDLE_TIMEOUT = 30 * 60  # seconds
# Seconds one connection may stay silent (a browser's spare one) before it is dropped.
CONNECTION_TIMEOUT = 5
MAX_BODY = 1_000_000
# Seconds a page may take to fetch its result after the last item before the server stops.
RESULT_WAIT = 60


class LabelError(Exception):
    """The items or the output file cannot be used: a usage error."""


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
        self.out.parent.mkdir(parents=True, exist_ok=True)
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
ALREADY_OPEN = ("A judgekeeper page is already open for this project. Close it with Ctrl-C in "
                "its terminal, or run `{program} --stop`.")
PROBE_TIMEOUT = 2  # seconds to wait for the page named in the lock to answer
RELEASE_TRIES = 40  # times to try removing the lock, RELEASE_PAUSE seconds apart
RELEASE_PAUSE = 0.05


def read_lock(folder: Path) -> dict | None:
    """{"pid", "port", "stop"} of the page named in the project's lock, or None. When
    server.json can't be read, its copy (page.json) is."""
    for name in (LOCK, LOCK_COPY):
        try:
            lock = json.loads((Path(folder) / name).read_text(encoding="utf-8"))
            return {"pid": int(lock["pid"]), "port": int(lock["port"]),
                    "stop": str(lock["stop"])}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def _answer(port: int, method: str, path: str, query: dict,
            body: dict | None = None) -> tuple[int, bytes] | None:
    """The status and body the page on `port` answers with, or None when nothing answers.
    Never through a proxy."""
    conn = http.client.HTTPConnection(HOST, port, timeout=PROBE_TIMEOUT)
    try:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if method == "POST":  # as the page's own script sends it
            headers["Origin"] = f"http://{HOST}:{port}"
        conn.request(method, f"{path}?{urlencode(query)}", body=data, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def ask(port: int, method: str, path: str, query: dict, body: dict | None = None) -> int | None:
    """The status the page on `port` answers with, or None when nothing answers."""
    answer = _answer(port, method, path, query, body)
    return None if answer is None else answer[0]


def is_page(port: int) -> bool:
    """Whether a judgekeeper page listens on `port`: it refuses a request without its token in
    its own words."""
    answer = _answer(port, "GET", "/alive", {})
    try:
        return answer is not None and answer[0] == 403 and \
            json.loads(answer[1]) == {"error": "missing or wrong token"}
    except ValueError:
        return False


def is_open(folder: Path) -> bool:
    """Whether the page named in the project's lock (in `folder`) answers to its stop secret;
    a lock nobody answers is stale. Asking the page, not the process, works the same
    everywhere: on Windows a process can't be looked at without the standard library's
    os.kill, which ends it."""
    lock = read_lock(folder)
    return lock is not None and ask(lock["port"], "GET", "/alive", {"stop": lock["stop"]}) == 200


def answers(port: int, token: str) -> bool:
    """Whether a page on `port` answers to `token`."""
    return ask(port, "GET", "/state", {"token": token}) == 200


def link(port: int, token: str) -> str:
    return f"http://{HOST}:{port}/?token={token}"


class _HTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without the host-name lookup it makes when it binds (socket.getfqdn
    of 127.0.0.1), which can hang for many seconds on some machines. The page needs no name.
    Closing it waits for no connection: the one being handled holds LabelServer.busy."""

    block_on_close = False

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name, self.server_port = HOST, self.server_address[1]


class LabelServer:
    def __init__(self, session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                 page: str, switches: dict | None = None, stays: bool = False,
                 token: str | None = None):
        self.session = session
        self.stays = stays  # never stops by itself after the result
        # (session, link back to the labeling page) -> the result page (HTML), for GET /result
        self.result = result
        self.template = page
        # path -> a function returning the (session, page, result) to switch to, or None
        self.switches = switches or {}
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

    def hold(self, folder: Path) -> None:
        """Write the project's lock and its copy: this process, port and stop secret (never
        the token: any program that can read .judgekeeper/ can read the lock)."""
        self.lock = Path(folder) / LOCK
        text = json.dumps({"pid": os.getpid(), "port": self.port, "stop": self.stop_secret})
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

        def __getattr__(self, name: str):
            if name.startswith("do_"):  # a method with no do_ of its own
                return self._other
            raise AttributeError(name)

        def _send(self, status: int, body: bytes, content_type: str, extra=None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, shown(data).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self, url) -> bool:
            """The token, or the stop secret on the two paths it opens (/alive, /stop)."""
            server.last_request = time.monotonic()
            if self.headers.get("Host") != f"{HOST}:{server.port}":
                self._json(403, {"error": "wrong Host header"})
                return False
            query = parse_qs(url.query)
            token = query.get("token", [""])[0]
            if hmac.compare_digest(token.encode(), server.token.encode()):
                return True
            stop = query.get("stop", [""])[0]
            if url.path in ("/alive", "/stop") and hmac.compare_digest(
                    stop.encode(), server.stop_secret.encode()):
                return True
            self._json(403, {"error": "missing or wrong token"})
            return False

        def _same_origin(self) -> bool:
            """Whether a POST comes from the page's own script (see the module's docstring)."""
            origins = (f"http://{HOST}:{server.port}", f"http://localhost:{server.port}")
            site = self.headers.get("Sec-Fetch-Site")
            if self.headers.get("Origin") in origins and site in (None, "same-origin"):
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
            return self.rfile.read(length) if 0 < length <= MAX_BODY else None

        def do_GET(self):
            with server.busy:
                self._get()

        def do_POST(self):
            body = self._body()
            with server.busy:
                self._post(body)

        def _other(self):
            self._body()
            with server.busy:
                if self._allowed(urlsplit(self.path)):
                    self._send(405, b'{"error": "method not allowed"}',
                               "application/json; charset=utf-8", {"Allow": "GET, POST"})

        def _get(self):
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            if url.path in ("/", "/state"):
                server.done_at = None  # the page is open and asking: keep serving it
            if url.path == "/alive":
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
            elif url.path in server.switches:
                swapped = server.switches[url.path]()
                if swapped is not None:
                    server.session, server.template, server.result = swapped
                    server.done_at = None
                self._send(303, b"", "text/plain; charset=utf-8",
                           {"Location": f"/?token={server.token}"})
            elif url.path == "/result" and server.result is not None:
                try:
                    page = server.result(server.session, f"/?token={server.token}")
                except OSError as e:  # .judgekeeper/ can't be written: say it, as /label does
                    self._send(500, (f"Not saved: {describe_os_error(e) or e}. Your marks are "
                                     "saved; try again once the folder can be written."
                                     ).encode(), "text/plain; charset=utf-8")
                    return
                csp = ("default-src 'none'; style-src 'unsafe-inline'; font-src data:; "
                       "img-src 'none'; base-uri 'none'; form-action 'none'; "
                       "frame-ancestors 'none'")
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
                if server.finished() and not server.stays:
                    server.stop()  # nothing left to label: the page holds the result
            else:
                self._json(404, {"error": "not found"})

        def _post(self, raw: bytes | None):
            url = urlsplit(self.path)
            if not self._allowed(url) or not self._same_origin():
                return
            if url.path == "/stop":
                self._json(200, {"stopped": True})
                server.stop()
                return
            if url.path == "/printed" and hasattr(server.session, "link"):
                server.session.link = PRINTED
                self._json(200, {"printed": True})
                return
            posts = getattr(server.session, "posts", {})
            if url.path != "/label" and url.path not in posts:
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                too_long = getattr(server.session, "too_long", {})
                if length > MAX_BODY and url.path in too_long:
                    raise ValueError(too_long[url.path])
                if raw is None:
                    raise ValueError("expected a JSON body")
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise TypeError("expected a JSON object")
                if url.path == "/label" and not isinstance(body.get("id"), str):
                    raise TypeError("expected a JSON object with an id")
            except (ValueError, TypeError, UnicodeDecodeError) as e:
                self._json(400, {"error": str(e)})
                return
            if url.path in posts:
                try:
                    self._json(200, posts[url.path](body))
                except (ValueError, TypeError) as e:
                    self._json(400, {"error": str(e)})
                except OSError as e:
                    self._json(500, {"error": describe_os_error(e) or str(e)})
                return
            if body["id"] not in server.session.by_id:
                self._json(404, {"error": "no item with that id"})
                return
            try:
                server.session.update(body)
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            except OSError as e:
                self._json(500, {"error": describe_os_error(e)
                                 or f"could not write {server.session.out}: {e}"})
                return
            summary = server.session.summary()
            self._json(200, {"summary": summary})
            if server.stays:
                return
            if server.result is not None and server.finished():
                if getattr(server.session, "asks_why", lambda body: False)(body):
                    server.done_at = None  # the page waits for a why; its GET /result stops
                elif server.done_at is None:
                    server.done_at = time.monotonic()
            else:  # a skip, or a label taken back: the page goes on
                server.done_at = None

    return Handler


def make_server(session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                page: str, switches: dict | None = None,
                lock: Path | None = None, stays: bool = False,
                token: str | None = None) -> LabelServer:
    """A server for `session`, or a LabelError that says why there cannot be one. With `lock`
    (the project's .judgekeeper/), one server per project: when its page is already open,
    that is the error; else this server holds the lock until it stops. Two pages on one
    project would each write their marks over the other's. `token`: the one its caller made
    (default: a new one)."""
    if lock is not None and is_open(lock):
        from judgekeeper.textio import program

        raise LabelError(ALREADY_OPEN.format(program=program()))
    # Labels are written on the first click: say now if they cannot be, not in the page.
    unwritable = unwritable_file(session.out)
    if unwritable:
        raise LabelError(unwritable)
    try:
        server = LabelServer(session, port, result=result, page=page, switches=switches,
                             stays=stays, token=token)
    except OSError as e:
        raise LabelError(f"cannot listen on {HOST}:{port} ({e.strerror}); try --port") from None
    if lock is not None:
        try:
            server.hold(lock)
        except OSError:
            pass  # no lock: the labels' own write still says when it can't save
    return server
