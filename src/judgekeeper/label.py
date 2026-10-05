"""`judgekeeper label`: label items in a local page instead of a spreadsheet.

Standard library only. The server binds 127.0.0.1, serves one self-contained page (inline CSS
and JS, no external assets) and writes every change to the output CSV at once, in the shape
`judgekeeper template` produces, so `import-labels` and `check --labels` read it unchanged.

Security: the page and every request need a random token from the URL; a request whose Host
header is not the bound address is refused (DNS rebinding); every displayed string goes
through textContent, and the data is embedded as JSON with <, > and & escaped. A connection
that stays silent for CONNECTION_TIMEOUT seconds is dropped. The server stops on Ctrl-C and
after IDLE_TIMEOUT seconds without a request.

With a `result` function the server serves a simpler page (try_page.py) and a
/result endpoint, which answers once every item is labeled or deferred. It stops right after
serving that result, or RESULT_WAIT seconds after the last item if nobody fetches it. The page
holds the result once fetched, so it keeps showing it with the server gone.
"""

from __future__ import annotations

import csv
import hmac
import io
import json
import os
import secrets
import sys
import tempfile
import time
import webbrowser
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
from judgekeeper.textio import describe_os_error, quote_arg, unwritable_file

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
IDLE_TIMEOUT = 2 * 60 * 60  # seconds
# Seconds one connection may stay silent. The server handles one connection at a time, so
# without this a connection that sends nothing (a browser's spare one) would block the rest.
CONNECTION_TIMEOUT = 5
MAX_BODY = 1_000_000
# Seconds a try page may take to fetch its result after the last item before the server stops.
RESULT_WAIT = 60
JUDGE_COLUMNS = ("judge_verdict", "verdict", "judge")
REASON_COLUMNS = ("judge_reason", "reason", "rationale")


class LabelError(Exception):
    """The items or the output file cannot be used: a usage error."""


def _text(value) -> str:
    return "" if _blank(value) else _plain(value)


class LabelSession:
    """Items, their labels and notes, and the CSV they are written to."""

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
            item["judge"] = self._judge(row)
            item.update(label=self._label(row.get("human_label"), item_id), deferred=False,
                        note=_text(row.get("notes")))
            self.items.append(item)
        self.by_id = {i["id"]: i for i in self.items}
        if self.out.is_file() and self.out.resolve() != self.items_path.resolve():
            self._resume()

    def _judge(self, row: dict) -> dict | None:
        col = next((c for c in JUDGE_COLUMNS if c in row and not _blank(row[c])), None)
        if col is None:
            return None
        reason = next((_text(row[c]) for c in REASON_COLUMNS if not _blank(row.get(c))), "")
        return {"verdict": _text(row[col]), "reason": reason}

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

    def summary(self) -> dict:
        from judgekeeper.report import label_quality

        labeled = [i["label"] for i in self.items if i["label"]]
        n_deferred = sum(1 for i in self.items if i["deferred"])
        dist = {lab: labeled.count(lab) for lab in sorted(set(labeled))}
        quality = label_quality({"label_distribution": dist})
        return {
            "n_items": len(self.items),
            "n_labeled": len(labeled),
            "n_deferred": n_deferred,
            "progress": f"{len(labeled)} of {len(self.items)} labeled, {n_deferred} deferred",
            "done": all(i["label"] or i["deferred"] for i in self.items),
            "distribution": dist,
            "warnings": [f["message"] for f in quality["flags"]] if labeled else [],
            "next_command": f"judgekeeper import-labels {quote_arg(self.out)} -o anchors.jsonl",
        }

    def state(self) -> dict:
        start = next((n for n, i in enumerate(self.items) if not i["label"]
                      and not i["deferred"]), 0)
        return {"kind": self.kind, "labels": list(self.labels), "out": str(self.out),
                "items": self.items, "start": start, "summary": self.summary()}


def _json_for_html(data) -> str:
    """JSON that is safe inside a <script> element: no <, > or & characters at all."""
    return (json.dumps(data, ensure_ascii=False).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


class LabelServer:
    def __init__(self, session: LabelSession, port: int = DEFAULT_PORT, result=None):
        self.session = session
        self.result = result  # session -> JSON-able dict; selects try_page.py
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
        if self.result is None:
            template = PAGE
        else:
            from judgekeeper.try_page import TRY_PAGE as template
        return (template.replace("__NONCE__", nonce)
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
            elif url.path == "/result" and server.result is not None:
                if not server.session.summary()["done"]:
                    self._json(409, {"error": "not every item is answered yet"})
                    return
                self._json(200, server.result(server.session))
                server.stop()  # the page holds the result now
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


def run(items: str | Path, out: str | Path, port: int = DEFAULT_PORT,
        open_browser: bool = True, print_fn=print, intro: str | None = None,
        result=None) -> LabelSession:
    """Serve the labeling page until Ctrl-C, idle, or (with `result`) the result is served.

    With `intro`, that line is printed before the link instead of the usual start-up and
    closing lines: the caller says what happens next.
    """
    session = LabelSession(items, out)
    # Labels are written on the first click: say now if they cannot be, not in the page.
    unwritable = unwritable_file(session.out)
    if unwritable:
        raise LabelError(unwritable)
    try:
        server = LabelServer(session, port, result=result)
    except OSError as e:
        raise LabelError(f"cannot listen on {HOST}:{port} ({e.strerror}); try --port") from None

    def say(line: str) -> None:
        # Flushed line by line: started in the background or piped to a log, stdout is not a
        # terminal, and the link (it carries the token) must not wait in a buffer until exit.
        print_fn(line)
        sys.stdout.flush()

    if intro is None:
        noun = "item" if len(session.items) == 1 else "items"
        say(f"labeling {len(session.items)} {session.kind} {noun} into {session.out} "
            f"({session.summary()['progress']})")
    else:
        say(intro)
    say(f"open {server.url}")
    if intro is None:
        say("every label is saved at once; Ctrl-C to stop (it also stops after 2 hours idle)")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    if intro is not None:
        return session
    summary = session.summary()
    if not summary["n_labeled"] and not session.out.is_file():
        say("stopped: nothing was labeled, so no file was written")
        return session
    say(f"stopped: {summary['progress']}; labels in {session.out}")
    if summary["n_labeled"]:
        say(f"next: {summary['next_command']}")
    return session


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>judgekeeper label</title>
<style>
:root { --bg: #fff; --fg: #1a1a1a; --muted: #666; --line: #ddd; --card: #f6f6f4;
  --pass: #1f7a3a; --fail: #b3261e; --accent: #2457c5; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161616; --fg: #ececec; --muted: #9a9a9a; --line: #333; --card: #202020;
    --pass: #5cc27a; --fail: #f2766d; --accent: #7aa2ff; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 16px; }
header { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline;
  justify-content: space-between; border-bottom: 1px solid var(--line); padding-bottom: 8px; }
h1 { font-size: 18px; margin: 0; }
#progress { color: var(--muted); }
.label { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted);
  margin: 16px 0 4px; }
pre { white-space: pre-wrap; word-wrap: break-word; margin: 0; padding: 12px;
  background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; max-height: 45vh;
  overflow: auto; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 700px) { .pair { grid-template-columns: 1fr; } }
.bar { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
button { font: inherit; padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--card); color: var(--fg); cursor: pointer; }
button:hover { border-color: var(--accent); }
button.on { outline: 2px solid var(--accent); }
#bpos { color: var(--pass); } #bneg { color: var(--fail); }
kbd { font: 12px ui-monospace, monospace; color: var(--muted); }
textarea { width: 100%; min-height: 3em; font: inherit; color: var(--fg); background: var(--bg);
  border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
#status { color: var(--muted); min-height: 1.5em; }
#status.err { color: var(--fail); }
#current { font-weight: 600; }
#done ul { padding-left: 20px; }
code { font: 14px ui-monospace, monospace; background: var(--card); padding: 2px 4px;
  border-radius: 4px; word-break: break-all; }
</style>
</head>
<body>
<main>
<header>
  <h1>judgekeeper label <span id="where"></span></h1>
  <div id="progress"></div>
</header>
<section id="item">
  <div class="label">Input</div>
  <pre id="input"></pre>
  <div id="single">
    <div class="label">Output</div>
    <pre id="output"></pre>
  </div>
  <div id="pairwise" class="pair" hidden>
    <div><div class="label">A</div><pre id="output_a"></pre></div>
    <div><div class="label">B</div><pre id="output_b"></pre></div>
  </div>
  <div class="bar">
    <button id="bpos" type="button"></button>
    <button id="bneg" type="button"></button>
    <button id="bdefer" type="button">Defer <kbd>d</kbd></button>
    <button id="bundo" type="button">Undo <kbd>u</kbd></button>
    <button id="bprev" type="button">&larr; Previous</button>
    <button id="bnext" type="button">Next &rarr;</button>
    <button id="bjudge" type="button">Show judge</button>
    <button id="bsummary" type="button">Summary</button>
  </div>
  <div>Current: <span id="current"></span></div>
  <div id="judge" hidden>
    <div class="label">Judge verdict</div>
    <pre id="judge_text"></pre>
  </div>
  <div class="label">Note <kbd>n</kbd></div>
  <textarea id="note" placeholder="Why? (optional)"></textarea>
  <div id="status"></div>
</section>
<section id="done" hidden>
  <h2>Summary</h2>
  <p id="done_counts"></p>
  <p id="done_split"></p>
  <ul id="done_warnings"></ul>
  <div id="done_more">
    <p>Next, freeze the labels as an anchor set:</p>
    <p><code id="done_next"></code></p>
    <button id="bback" type="button">Back to labeling</button>
  </div>
</section>
</main>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__";
  var data = JSON.parse(document.getElementById("data").textContent);
  var items = data.items, labels = data.labels, pairwise = data.kind === "pairwise";
  var pos = data.start, summary = data.summary, history = [];
  var $ = function (id) { return document.getElementById(id); };
  function setText(id, text) { $(id).textContent = text == null ? "" : String(text); }

  setText("bpos", pairwise ? "A is better (1 / a)" : "Pass (1)");
  setText("bneg", pairwise ? "B is better (2 / b)" : "Fail (2)");
  $("pairwise").hidden = !pairwise;
  $("single").hidden = pairwise;

  function status(text, err) { setText("status", text); $("status").className = err ? "err" : ""; }

  function render() {
    var it = items[pos];
    setText("where", "(" + (pos + 1) + " / " + items.length + ": " + it.id + ")");
    setText("progress", summary.progress);
    setText("input", it.input);
    if (pairwise) { setText("output_a", it.output_a); setText("output_b", it.output_b); }
    else { setText("output", it.output); }
    setText("current", it.label ? it.label : (it.deferred ? "deferred" : "unlabeled"));
    $("bpos").className = it.label === labels[0] ? "on" : "";
    $("bneg").className = it.label === labels[1] ? "on" : "";
    $("bdefer").className = it.deferred ? "on" : "";
    setText("judge_text", it.judge ? it.judge.verdict + (it.judge.reason ? "\\n\\n" +
      it.judge.reason : "") : "No judge verdict for this item.");
    if (document.activeElement !== $("note")) { $("note").value = it.note || ""; }
  }

  function renderDone() {
    var s = summary;
    setText("done_counts", s.progress + " (of " + s.n_items + " items).");
    var parts = [];
    for (var k in s.distribution) { parts.push(k + ": " + s.distribution[k]); }
    setText("done_split", parts.length ? "Split: " + parts.join(", ") : "No labels yet.");
    var ul = $("done_warnings");
    while (ul.firstChild) { ul.removeChild(ul.firstChild); }
    s.warnings.forEach(function (w) {
      var li = document.createElement("li"); li.textContent = w; ul.appendChild(li); });
    setText("done_next", s.next_command);
  }

  function show(done) {
    $("item").hidden = done; $("done").hidden = !done;
    if (done) { setText("where", ""); setText("progress", summary.progress); renderDone(); }
    else { render(); }
  }

  function send(change, after) {
    change.id = items[pos].id;
    fetch("/label?token=" + encodeURIComponent(TOKEN), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(change)
    }).then(function (r) {
      return r.json().then(function (body) { return {ok: r.ok, body: body}; });
    }).then(function (res) {
      if (!res.ok) { status("Not saved: " + res.body.error, true); return; }
      summary = res.body.summary; status("Saved.");
      if (after) { after(); } else { render(); }
    }).catch(function (e) { status("Not saved: " + e, true); });
  }

  function snapshot() {
    var it = items[pos];
    history.push({pos: pos, label: it.label, deferred: it.deferred});
  }

  function advance() {
    for (var n = 1; n <= items.length; n++) {
      var i = (pos + n) % items.length;
      if (!items[i].label && !items[i].deferred) { pos = i; render(); return; }
    }
    show(true);
  }

  function setLabel(lab) {
    snapshot();
    var it = items[pos]; it.label = lab; it.deferred = false;
    send({label: lab, note: $("note").value}, advance);
    it.note = $("note").value;
  }

  function defer() {
    snapshot();
    var it = items[pos]; it.label = null; it.deferred = true;
    send({deferred: true, note: $("note").value}, advance);
    it.note = $("note").value;
  }

  function undo() {
    var h = history.pop();
    if (!h) { status("Nothing to undo."); return; }
    pos = h.pos; show(false);
    var it = items[pos]; it.label = h.label; it.deferred = h.deferred;
    send(h.deferred ? {deferred: true} : {label: h.label, deferred: false});
  }

  function move(step) {
    pos = (pos + step + items.length) % items.length; show(false);
  }

  function toggleJudge() {
    $("judge").hidden = !$("judge").hidden;
    setText("bjudge", $("judge").hidden ? "Show judge" : "Hide judge");
  }

  $("bpos").addEventListener("click", function () { setLabel(labels[0]); });
  $("bneg").addEventListener("click", function () { setLabel(labels[1]); });
  $("bdefer").addEventListener("click", defer);
  $("bundo").addEventListener("click", undo);
  $("bprev").addEventListener("click", function () { move(-1); });
  $("bnext").addEventListener("click", function () { move(1); });
  $("bjudge").addEventListener("click", toggleJudge);
  $("bsummary").addEventListener("click", function () { show(true); });
  $("bback").addEventListener("click", function () { show(false); });
  $("note").addEventListener("change", function () {
    items[pos].note = $("note").value; send({note: $("note").value});
  });

  document.addEventListener("keydown", function (e) {
    if (e.target === $("note")) {
      if (e.key === "Escape") { $("note").blur(); }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    var k = e.key.toLowerCase();
    if (!$("done").hidden) { if (k === "escape") { show(false); } return; }
    if (k === "1" || (pairwise && k === "a")) { setLabel(labels[0]); }
    else if (k === "2" || (pairwise && k === "b")) { setLabel(labels[1]); }
    else if (k === "d") { defer(); }
    else if (k === "u") { undo(); }
    else if (k === "n") { $("note").focus(); }
    else if (k === "arrowright" || k === "arrowdown") { move(1); }
    else if (k === "arrowleft" || k === "arrowup") { move(-1); }
    else { return; }
    e.preventDefault();
  });

  show(summary.done && summary.n_labeled > 0);
})();
</script>
</body>
</html>
"""
