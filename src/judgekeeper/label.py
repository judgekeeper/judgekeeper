"""The local labeling page that `judgekeeper start` serves: a session of items and labels, and
the server for it.

Standard library only. The server binds 127.0.0.1, serves one self-contained page (inline CSS
and JS, no external assets) and writes every change to the labels CSV at once (id, input,
output, human_label, notes).

Security: the page and every request need a random token from the URL; a request whose Host
header is not the bound address is refused (DNS rebinding); every displayed string goes
through textContent, and the data is embedded as JSON with <, > and & escaped. A connection
that stays silent for CONNECTION_TIMEOUT seconds is dropped. The server stops on Ctrl-C and
after IDLE_TIMEOUT seconds without a request.

The caller passes the page (start_page.py) and a `result` function: GET /result answers with
the result page, a static HTML page that runs no script. Once every
item is labeled or deferred, the server stops right after serving that page, or RESULT_WAIT
seconds after the last item if nobody fetches it. It may also pass `switches`: a GET of one of
their paths swaps the session, the page and the result function (from labeling to the review
of the disagreements) and sends the browser back to the page.
"""

from __future__ import annotations

import csv
import hmac
import io
import json
import os
import secrets
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from judgekeeper.anchors import LABELS
from judgekeeper.normalise import ERROR, Normaliser, UnmappedValue
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
from judgekeeper.textio import describe_os_error, unwritable_file

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
IDLE_TIMEOUT = 2 * 60 * 60  # seconds
# Seconds one connection may stay silent. The server handles one connection at a time, so
# without this a connection that sends nothing (a browser's spare one) would block the rest.
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
        """Apply one change: {"id", "label"?: label | None, "deferred"?: bool, "note"?: str}."""
        item = self.by_id[body["id"]]
        before = dict(item)
        try:
            self._apply(item, body)
            self.write()
        except BaseException:
            item.update(before)  # memory matches the file on disk
            raise

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
        """Write the whole sheet to a temporary file next to --out, then rename it over."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(self.columns)
        for i in self.items:
            w.writerow([guard_cell(i["id"]), *(guard_cell(i[c]) for c in self.columns[1:-2]),
                        i["label"] or "", guard_cell(i["note"])])
        self.out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.out.name}.", suffix=".tmp",
                                   dir=self.out.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(buf.getvalue())
            os.replace(tmp, self.out)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

def _json_for_html(data) -> str:
    """JSON that is safe inside a <script> element: no <, > or & characters at all."""
    return (json.dumps(data, ensure_ascii=False).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


class LabelServer:
    def __init__(self, session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                 page: str, switches: dict | None = None):
        self.session = session
        # (session, link back to the labeling page) -> the result page (HTML), for GET /result
        self.result = result
        self.template = page
        # path -> a function returning the (session, page, result) to switch to
        self.switches = switches or {}
        self.done_at: float | None = None
        self.token = secrets.token_urlsafe(32)
        self.httpd = HTTPServer((HOST, port), _handler(self))
        self.httpd.timeout = 0.2
        self.host = HOST
        self.port = self.httpd.server_address[1]
        self.url = f"http://{HOST}:{self.port}/?token={self.token}"
        self.last_request = time.monotonic()
        self._stopped = False

    def serve(self, idle_timeout: float | None = None) -> None:
        """Handle requests until stop(), Ctrl-C, or idle_timeout seconds without a request."""
        idle = IDLE_TIMEOUT if idle_timeout is None else idle_timeout
        try:
            while not self._stopped and time.monotonic() - self.last_request < idle:
                self.httpd.handle_request()
                if self.done_at is not None and time.monotonic() - self.done_at > RESULT_WAIT:
                    break
        finally:
            self.httpd.server_close()

    def stop(self) -> None:
        self._stopped = True

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
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _allowed(self, url) -> bool:
            server.last_request = time.monotonic()
            if self.headers.get("Host") != f"{HOST}:{server.port}":
                self._json(403, {"error": "wrong Host header"})
                return False
            token = parse_qs(url.query).get("token", [""])[0]
            if not hmac.compare_digest(token.encode(), server.token.encode()):
                self._json(403, {"error": "missing or wrong token"})
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            if url.path == "/":
                page, nonce = server.page()
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; "
                       "style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; "
                       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
            elif url.path == "/state":
                self._json(200, server.session.state())
            elif url.path in server.switches:
                server.session, server.template, server.result = server.switches[url.path]()
                server.done_at = None
                self._send(303, b"", "text/plain; charset=utf-8",
                           {"Location": f"/?token={server.token}"})
            elif url.path == "/result" and server.result is not None:
                page = server.result(server.session, f"/?token={server.token}")
                csp = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
                       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
                if server.session.summary()["done"]:
                    server.stop()  # nothing left to label: the page holds the result
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._allowed(url):
                return
            if url.path != "/label":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    raise ValueError("expected a JSON body")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or not isinstance(body.get("id"), str):
                    raise TypeError("expected a JSON object with an id")
            except (ValueError, TypeError, UnicodeDecodeError) as e:
                self._json(400, {"error": str(e)})
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
            if server.result is not None and summary["done"] and server.done_at is None:
                server.done_at = time.monotonic()

    return Handler


def make_server(session: LabelSession, port: int = DEFAULT_PORT, result=None, *,
                page: str, switches: dict | None = None) -> LabelServer:
    """A server for `session`, or a LabelError that says why there cannot be one."""
    # Labels are written on the first click: say now if they cannot be, not in the page.
    unwritable = unwritable_file(session.out)
    if unwritable:
        raise LabelError(unwritable)
    try:
        return LabelServer(session, port, result=result, page=page, switches=switches)
    except OSError as e:
        raise LabelError(f"cannot listen on {HOST}:{port} ({e.strerror}); try --port") from None
