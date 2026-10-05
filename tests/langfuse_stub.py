"""A local HTTP server that answers like Langfuse's public API, from recorded responses.

Serves tests/fixtures/langfuse/: `GET /api/public/v3/scores` page by page (the first page
without a cursor, the next for each `meta.cursor`) and `GET /api/public/v2/evaluators`.
Every request is kept in `requests` as (path, query, headers). Behaviours a test can turn on:
`rate_limited` answers that many score requests with HTTP 429 first; `redirect_to` answers
every request with a 302 to that base URL; `status` answers every request with that code and a
body echoing the Authorization header, as a careless proxy might.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.conftest import FIXTURES

DIR = FIXTURES / "langfuse"


def load(name: str) -> dict:
    return json.loads((DIR / name).read_text())


def score_pages() -> list[dict]:
    return [load(f"scores-page-{n}.json") for n in (1, 2, 3)]


class LangfuseStub:
    def __init__(self, pages=None, evaluators=None, rate_limited=0, retry_after="7",
                 redirect_to=None, status=None):
        self.pages = score_pages() if pages is None else pages
        self.evaluators = load("evaluators.json") if evaluators is None else evaluators
        self.rate_limited = rate_limited
        self.retry_after = retry_after
        self.redirect_to = redirect_to
        self.status = status
        self.requests: list[tuple[str, dict, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                stub.requests.append((parts.path, query, dict(self.headers)))
                stub.handle(self, parts.path, query)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def score_requests(self):
        return [r for r in self.requests if r[0] == "/api/public/v3/scores"]

    def _send(self, h, code, body, headers=()):
        data = json.dumps(body).encode()
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)

    def handle(self, h, path, query):
        if self.redirect_to:
            return self._send(h, 302, {}, [("Location", self.redirect_to + h.path)])
        if self.status:
            return self._send(h, self.status, {"message": "denied",
                                               "echo": h.headers.get("Authorization")})
        if path == "/api/public/v3/scores":
            if self.rate_limited:
                self.rate_limited -= 1
                return self._send(h, 429, {"message": "rate limited"},
                                  [("Retry-After", self.retry_after)])
            cursors = [p["meta"].get("cursor") for p in self.pages]
            cursor = query.get("cursor")
            n = 0 if cursor is None else cursors.index(cursor) + 1
            return self._send(h, 200, self.pages[n])
        if path == "/api/public/v2/evaluators":
            return self._send(h, 200, self.evaluators)
        return self._send(h, 404, {"message": "not found"})
