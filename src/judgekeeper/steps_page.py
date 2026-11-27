"""The steps marking page: one agent run at a time, the person clicks the first wrong step
(or "All steps are fine"), and the result page shows how often the agent-as-a-judge picks the
same step.

It is served by the answers page's server (label.LabelServer: token, Host, Origin, MAX_BODY
and the 409 for a stale tab, unchanged) and opened by the same machinery (page.open_new,
page.show): one page per project at a time, its lock in .judgekeeper/server.json.

Marks go in .judgekeeper/steps/marks.jsonl, append only: a header line, then one line per
click, {"id", "first_wrong_step", "steps_hash", "at", "seconds", "by": "page"} and "link"
"printed" or "browser-env" when a program may have clicked: the page's link was printed with
no terminal, or the program in BROWSER opened it (as the answers page stamps its marks). 0 is all steps fine, null is taken back (Undo); the newest line for a run
wins. `steps_hash` is the run's (steps.Run.steps_hash, of its steps as the runs file holds them): a
run whose steps changed since loses its old click.

Blind: the agent-as-a-judge's picks never reach the marking page, only the result page. The runs
come in one shuffled order, seeded by the runs file's hash, never by the picks, so every
prefix is a fair sample. Step text is scrubbed (credentials, hidden characters) and reaches
the page as JSON, shown with textContent only.
"""

from __future__ import annotations

import hashlib
import json
import random
from html import escape
from pathlib import Path

from judgekeeper import __version__, look, marks, steps, textio
from judgekeeper.fingerprint import utc_now
from judgekeeper.label import StaleMark, make_server
from judgekeeper.mark_page import NO_ANSWER, SEE_FIRST, SEE_READY
from judgekeeper.mark_page import _text as _page_text
from judgekeeper.redact import scrub, visible
from judgekeeper.start_label import Workspace, make_folder

__all__ = ["StaleMark", "StepsSession", "page_template", "steps_server"]

MARKS_FILE = steps.MARKS_FILE
VERSION = 1  # the header's "step_marks"
CUT = 600  # characters of a step shown before "Show all"
# Characters of step text one page holds (at least one run): past them the page asks again
PAGE_TEXT = 4_000_000
FRESH_MS, LOCK_MS = 250, 400  # as the answers page

TITLE = "Click the first wrong step of each run."  # the welcome box
FINE = "All steps are fine"
OTHER_TAB = ("Not marked: this run was already marked in another tab. "
             "The list is up to date again.")
STALE = "this run was already marked in another tab"
NOTHING_TO_UNDO = "Nothing to undo."
EMPTY_STEP = "(empty step)"
# The result page
RESULT_TITLE = "Your result"
CHANGE = "Change a mark"
NO_PICKS = ("Add your agent-as-a-judge's picks to see how often it agrees with you: "
            "judgekeeper steps runs.jsonl --reviewer picks.jsonl")
JUDGE = "Agent-as-a-judge"
ALL_FINE = "All fine"
BOTH = "Both"


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def shuffled(ids: list[str], seed: str) -> list[str]:
    """`ids` in one order made from `seed` (the runs file's hash): the same file, the same
    order, on every machine (a str seed is hashed with SHA-512, not Python's hash)."""
    order = list(ids)
    random.Random(seed).shuffle(order)
    return order


def _same(a, b) -> bool:
    """Two marks are the same: None and None, or the same whole number (never 0 and False)."""
    if a is None or b is None:
        return a is None and b is None
    return type(a) is int and type(b) is int and a == b


class StepsSession:
    """The runs of one runs file and the person's step marks, for label.LabelServer: `by_id`,
    `update`, `state`, `summary`, and `out` (the marks file)."""

    def __init__(self, ws: Workspace, runs_path: str | Path, reviewer: str | Path | None = None,
                 model: str | None = None, shown: str | None = None):
        self.ws = ws
        self.runs_path = Path(runs_path)
        self.runs_hash = file_hash(self.runs_path)
        self.runs = steps.read_runs(self.runs_path)
        self.by_id = {r.id: r for r in self.runs}
        self.hashes = {r.id: r.steps_hash for r in self.runs}
        self.order = shuffled([r.id for r in self.runs], self.runs_hash)
        self.out = ws.dir / steps.FOLDER / MARKS_FILE
        self.reviewer = Path(reviewer) if reviewer else None
        self.model = model
        self.shown = shown  # the runs path as typed where the page was opened
        self.link: str | None = None  # marks.LINKS: how its link was shown (page.show)
        self._marks: dict[str, int] = {}
        self.changed = 0  # marks dropped because their run's steps changed
        self.made = False  # a mark line was ever written: no welcome box
        self._read()

    # The marks file ------------------------------------------------------------------

    def _read(self) -> None:
        """The marks that stand, by the rules of steps.read_marks (a line that is not a mark
        is skipped, the header first): the newest line of each run of these runs, unless it
        is null (taken back) or for steps that have changed since. The steps' hashes are
        made once, so a click never hashes every run again."""
        newest: dict[str, tuple[int | None, str]] = {}
        made, first = False, True
        try:
            text = self.out.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            text = ""
        except (OSError, UnicodeDecodeError):
            return  # memory stays as it is; the next write says what is wrong
        for line in textio.jsonl_lines(text):
            if not line.strip():
                continue
            try:
                row = textio.loads(line)
            except ValueError:
                row = None
            header, first = first and isinstance(row, dict) and "step_marks" in row, False
            mark = None if header else steps._mark_of(row)
            if mark is None:
                continue
            made = True
            if mark[0] in self.by_id:
                newest[mark[0]] = mark[1:]
        stand, changed = {}, 0
        for run_id, (step, kept) in newest.items():
            if step is None:
                continue
            if kept != self.hashes[run_id]:
                changed += 1
            elif step <= len(self.by_id[run_id].steps):
                stand[run_id] = step
        self._marks, self.changed, self.made = stand, changed, made

    def marked(self) -> dict[str, int]:
        """Run id -> the first wrong step the person gave (0: all fine)."""
        return dict(self._marks)

    def update(self, body: dict) -> None:
        """One click: {"id", "first_wrong_step": 0 to the run's step count, or null (Undo),
        "was": the mark the page saw, "seconds"}. Refused (ValueError, the server's 400) for
        a step that is not one of the run's; StaleMark (409) when the run has another mark
        now than the page saw."""
        self._read()
        run = self.by_id[body["id"]]
        if steps.STEP_FIELD not in body:
            raise ValueError("first_wrong_step is missing")
        value = body[steps.STEP_FIELD]
        if value is not None and not (type(value) is int and 0 <= value <= len(run.steps)):
            raise ValueError(f"first_wrong_step must be a whole number from 0 to "
                             f"{len(run.steps)}, or null")
        seconds = body.get("seconds")
        if not steps._seconds(seconds) or seconds < 0:  # as the marks reader takes it
            raise ValueError("seconds must be a number from 0")
        if "was" in body and not _same(body["was"], self._marks.get(run.id)):
            raise StaleMark(STALE)
        line = {"id": run.id, steps.STEP_FIELD: value, "steps_hash": self.hashes[run.id],
                "at": utc_now(), "seconds": round(float(seconds), 3), "by": "page"}
        if self.link in (marks.PRINTED, marks.BROWSER_ENV):  # a program may have clicked
            line[steps.LINK_FIELD] = self.link
        make_folder(self.ws)
        textio.make_private(self.out.parent)
        if not self.out.is_file() or self.out.stat().st_size == 0:
            marks.append(self.out, {"step_marks": VERSION, "created_at": utc_now(),
                                    "judgekeeper_version": __version__,
                                    "runs": self.runs_path.name, "runs_hash": self.runs_hash})
        marks.append(self.out, line)
        self.made = True
        if value is None:
            self._marks.pop(run.id, None)
        else:
            self._marks[run.id] = value

    # What the page gets ---------------------------------------------------------------

    def _shown_run(self, k: int, run_id: str, mark: int | None) -> dict:
        run = self.by_id[run_id]
        shown = []
        for step in run.steps:
            role = step["role"].split(". ", 1)[-1]
            shown.append({"role": visible(scrub(role) or ""),
                          "text": visible(scrub(step["content"]) or "")})
        task = visible(scrub(run.task) or "") if run.task else None
        return {"id": run_id, "n": k + 1, "task": task or None, "steps": shown, "mark": mark}

    def state(self) -> dict:
        """The runs from the first unmarked one in the order, as many as PAGE_TEXT allows
        (at least one); the page asks again past them. `intro`: no mark made yet."""
        stand = self._marks
        first = next((k for k, run_id in enumerate(self.order) if run_id not in stand), 0)
        runs, size = [], 0
        for k in range(first, len(self.order)):
            run_id = self.order[k]
            weight = sum(len(s["content"]) for s in self.by_id[run_id].steps)
            if runs and size + weight > PAGE_TEXT:
                break
            runs.append(self._shown_run(k, run_id, stand.get(run_id)))
            size += weight
        return {"runs": runs, "start": 0, "total": len(self.order), "marked": len(stand),
                "intro": not self.made}

    def summary(self) -> dict:
        return {"marked": len(self._marks), "total": len(self.order),
                "done": len(self._marks) == len(self.order)}


# The page -------------------------------------------------------------------------------

STYLE = """
html, body { height: 100%; overflow: hidden; }
body { display: flex; flex-direction: column; }
#app { flex: 1; display: flex; flex-direction: column; min-height: 0; }
.see { font-size: 13px; font-weight: 700; color: var(--green); text-decoration: none; }
.see:hover { text-decoration: underline; }
.main { flex: 1; overflow: auto; min-height: 0; overscroll-behavior: contain; }
.card { max-width: 980px; margin: 0 auto; padding: 0 40px; }
.card:focus-visible { outline: none; }
.row { padding: 26px 0; border-bottom: 1px solid var(--line); }
.row:last-child { border-bottom: 0; }
.label { font-size: 11px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase;
  color: var(--faint); margin-bottom: 12px; }
.task { font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }
.task { margin: 0; font-size: 22px; font-weight: 700; line-height: 1.35; letter-spacing: -.01em;
  white-space: pre-wrap; overflow-wrap: anywhere; max-width: 75ch; }
.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;
  gap: 6px; }
.steps li { display: flex; flex-direction: column; align-items: flex-start; }
.step { width: 100%; display: grid; grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: start; gap: 14px; text-align: left; padding: 10px 14px;
  border: 1px solid var(--line); border-radius: 6px; font-size: 15px; line-height: 1.5; }
.step:hover { border-color: var(--red); background: var(--hover); }
.step .n { width: 26px; height: 26px; border: 1px solid var(--line); border-radius: 50%;
  display: grid; place-items: center; font-family: var(--mono); font-size: 12px;
  color: var(--muted); font-variant-ligatures: none; }
.step:hover .n, .step.you .n { border-color: var(--red); color: var(--red); }
.step .body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.step .role { font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  color: var(--faint); }
.step .text { white-space: pre-wrap; overflow-wrap: anywhere;
  font-variant-ligatures: none; font-feature-settings: "calt" 0, "liga" 0; }
.step .text.empty { color: var(--muted); }
.step.you, .step.you:hover { border-color: var(--red); }
.tag:empty { display: none; }
.tag { border: 1px solid var(--red); border-radius: 999px; padding: 1px 8px; font-size: 12px;
  line-height: 1.4; color: var(--red); white-space: nowrap; }
.more { margin: 2px 0 2px 56px; padding: 4px 0; font-size: 14px; color: var(--muted);
  text-decoration: underline; text-decoration-color: var(--faint); text-underline-offset: 3px; }
.more:hover, .more:focus-visible { color: var(--text); }
.fine { margin-top: 14px; display: inline-flex; align-items: center; gap: 10px;
  padding: 10px 16px; border: 1px solid var(--line); border-radius: 6px; font-size: 15px;
  font-weight: 600; }
.fine:hover { border-color: var(--red); background: var(--hover); }
.fine.you, .fine.you:hover { border-color: var(--red); }
kbd { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.bar { flex: none; border-top: 1px solid var(--line); }
.bar-in { max-width: 980px; margin: 0 auto; padding: 14px 40px; display: grid;
  grid-template-columns: auto 1fr auto auto; align-items: center; gap: 16px; }
.where { font-family: var(--mono); font-size: 13px; color: var(--muted); white-space: nowrap; }
.status { margin: 0; font-size: 13px; font-weight: 600; color: var(--red); text-align: center; }
.status.calm { color: var(--muted); font-weight: 400; }
.quiet { padding: 10px 16px; font-size: 14px; color: var(--muted); }
.quiet:hover { color: var(--text); background: var(--hover); }
.go { font-weight: 700; border-radius: 4px; color: #fff; background: var(--green-fill);
  height: 46px; padding: 0 24px; font-size: 16px; display: inline-flex; align-items: center;
  gap: 10px; transition: filter 100ms ease; text-decoration: none; justify-content: center; }
.go kbd { color: #fff; opacity: .8; font-size: 13px; }
.go:hover { filter: brightness(1.08); }
.go:disabled { background: var(--line); color: var(--muted); cursor: default; filter: none; }
.go:disabled kbd { color: var(--muted); }
.foot { flex: none; margin: 0; padding: 10px 40px; border-top: 1px solid var(--line);
  font-size: 13px; color: var(--muted); text-align: center; }
.foot code { font-family: var(--mono); font-size: 12.5px; color: var(--text); }
.scrim { position: fixed; inset: 0; z-index: 10; background: var(--scrim); display: flex;
  align-items: center; justify-content: center; padding: 20px; }
.intro { background: var(--bg); border: 1px solid var(--line); border-radius: 2px; width: 100%;
  max-width: 520px; padding: 40px; display: flex; flex-direction: column; align-items: center;
  gap: 24px; text-align: center; }
.intro:focus-visible { outline: none; }
.intro .brand { font-size: 21px; gap: 10px; }
.intro .logo-mark svg { width: 30px; height: 33px; }
.intro h2 { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -.01em; line-height: 1.25; }
.intro .go { width: 100%; height: 56px; font-size: 17px; }
.step-list-label { margin-bottom: 14px; }
"""

BODY = """<div id="app">
__TOP__
<main class="main" id="main">
  <section class="card" id="card" tabindex="-1" aria-label="The run to mark">
    <div class="row" id="task-row"><div class="label">Agent run</div><h1 class="task" id="task" dir="auto"></h1></div>
    <div class="row"><div class="label step-list-label">Click the first wrong step</div>
      <ol class="steps" id="steps"></ol>
      <button type="button" class="fine" id="fine" aria-keyshortcuts="0"><span>__FINE__</span><span class="tag" id="fine-tag"></span><kbd>0</kbd></button>
    </div>
  </section>
</main>
<div class="bar"><div class="bar-in">
  <span class="where" id="where"></span>
  <p class="status" id="status" role="status"></p>
  <button type="button" class="quiet" id="undo" aria-keyshortcuts="Z">Undo <kbd>Z</kbd></button>
  <button type="button" class="go" id="next" aria-keyshortcuts="Enter ArrowRight" disabled><span id="next-text">Next</span><kbd>→</kbd></button>
</div></div>
<p class="foot">To come back: <code>__COMMAND__</code></p>
<p class="sr" id="done" role="status"></p>
</div>
<div class="scrim" id="intro" hidden>
  <div class="intro" id="intro-box" role="dialog" aria-modal="true" aria-labelledby="intro-title" tabindex="-1">
    __BRAND__
    <h2 id="intro-title">__TITLE__</h2>
    <button type="button" class="go" id="intro-ok">Start marking</button>
  </div>
</div>
<script type="application/json" id="data">__DATA__</script>
<script nonce="__NONCE__">
"use strict";
(function () {
  var TOKEN = "__TOKEN__", CUT = __CUT__, FRESH_MS = __FRESH_MS__, LOCK_MS = __LOCK_MS__;
  var SAVE_MS = 10000;
  var WORDS = __WORDS__;
  var data = JSON.parse(document.getElementById("data").textContent);
  var runs, total, marked, pos, pick, walk;
  var busy = false, history = [], shownAt = Date.now(), freshUntil = 0, lockUntil = 0;
  var opened = {};  // the steps shown whole ("Show all"), on the run on screen
  var $ = function (id) { return document.getElementById(id); };
  function url(path) { return path + "?token=" + encodeURIComponent(TOKEN); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text != null) { e.textContent = String(text); }
    return e;
  }
  function say(text, calm) {
    $("status").textContent = text || "";
    $("status").classList.toggle("calm", !!calm);
  }
  var hearing;
  function hear(text) {
    $("done").textContent = "";
    clearTimeout(hearing);
    hearing = setTimeout(function () { $("done").textContent = text; }, 100);
  }
  function focusCard() { $("card").focus({preventScroll: true}); }
  function fresh() { return Date.now() < freshUntil; }
  function unmarked(k) { return runs[k].mark == null; }

  function take(s) {
    runs = s.runs; total = s.total; marked = s.marked; pos = s.start || 0;
    walk = !runs.some(function (r) { return r.mark == null; });  // every run marked already
  }

  // Where Next goes from the run on screen once it is marked: the next unmarked run on this
  // page (after it, then before it), else "reload" when unmarked runs are past this page,
  // else the next run when every run was marked as the page opened, else "result".
  function following() {
    var k, n = runs.length;
    for (k = 1; k < n; k++) { if (unmarked((pos + k) % n)) { return (pos + k) % n; } }
    var here = runs.filter(function (r) { return r.mark == null; }).length;
    var left = total - marked - here;  // unmarked runs this page does not hold
    if (left > 0) { return "reload"; }
    if (walk && pos + 1 < n) { return pos + 1; }
    return "result";
  }
  function lastOne() {
    var n = runs.length, k;
    for (k = 1; k < n; k++) { if (unmarked((pos + k) % n)) { return false; } }
    var here = runs.filter(function (r) { return r.mark == null; }).length;
    return total - marked - here <= 0 && !(walk && pos + 1 < n);
  }

  function stepText(text, whole) {
    if (!text) { return {text: WORDS.empty, empty: true}; }
    if (whole || text.length <= CUT) { return {text: text, empty: false}; }
    return {text: text.slice(0, CUT) + "\\u2026", empty: false};
  }
  function drawText(span, text, whole) {
    var shown = stepText(text, whole);
    span.textContent = shown.text;
    span.className = "text" + (shown.empty ? " empty" : "");
  }

  function render() {
    var run = runs[pos], list = $("steps");
    $("task-row").hidden = run.task == null;
    $("task").textContent = run.task == null ? "" : run.task;
    list.textContent = "";
    run.steps.forEach(function (step, i) {
      var li = el("li"), b = el("button", "step"), n = i + 1, body = el("span", "body");
      b.type = "button";
      b.setAttribute("data-n", String(n));
      b.setAttribute("aria-pressed", String(pick === n));
      b.appendChild(el("span", "n", String(n)));
      body.appendChild(el("span", "role", step.role));
      var text = el("span", "text");
      drawText(text, step.text, !!opened[n]);
      body.appendChild(text);
      b.appendChild(body);
      b.appendChild(el("span", "tag", pick === n ? WORDS.you : ""));
      if (pick === n) { b.classList.add("you"); }
      li.appendChild(b);
      if (step.text && step.text.length > CUT) {
        var more = el("button", "more", opened[n] ? WORDS.less : WORDS.all);
        more.type = "button";
        more.setAttribute("data-n", String(n));
        more.setAttribute("aria-expanded", String(!!opened[n]));
        li.appendChild(more);
      }
      list.appendChild(li);
    });
    $("fine").classList.toggle("you", pick === 0);
    $("fine").setAttribute("aria-pressed", String(pick === 0));
    $("fine-tag").textContent = pick === 0 ? WORDS.you : "";
    $("where").textContent = "Run " + run.n + " of " + total;
    $("next").disabled = pick == null;
    $("next-text").textContent = lastOne() ? WORDS.result : WORDS.next;
    $("see").hidden = marked === 0;
  }

  function open(k) {
    pos = k; pick = runs[k].mark == null ? null : runs[k].mark; opened = {};
    say(""); render();
    shownAt = Date.now();
    $("main").scrollTop = 0;
  }

  function choose(n) {
    if (busy || fresh() || !$("intro").hidden) { return; }
    if (n > runs[pos].steps.length) { return; }
    pick = n; say(""); render();
  }

  function refresh(line) {
    fetch(url("/state"), {referrerPolicy: "same-origin"}).then(function (r) {
      return r.json();
    }).then(function (s) {
      take(s); history = []; busy = false; open(pos); say(line); hear(line); focusCard();
    }).catch(function () { window.location.reload(); });
  }

  function send(change, then) {
    busy = true;
    var run = runs[pos];
    var body = {id: run.id, first_wrong_step: change, was: run.mark == null ? null : run.mark,
                seconds: Math.max(0, (Date.now() - shownAt) / 1000)};
    var stop = typeof AbortController === "function" ? new AbortController() : null;
    var waited = setTimeout(function () { if (stop) { stop.abort(); } }, SAVE_MS);
    fetch(url("/label"), {
      method: "POST", headers: {"Content-Type": "application/json"},
      referrerPolicy: "same-origin", body: JSON.stringify(body),
      signal: stop ? stop.signal : undefined
    }).then(function (r) {
      return r.json().then(function (b) { return {ok: r.ok, status: r.status, body: b}; });
    }).then(function (res) {
      clearTimeout(waited);
      if (res.status === 409 && res.body.stale) { refresh(WORDS.otherTab); return; }
      busy = false;
      if (!res.ok) { say("Not saved: " + res.body.error); return; }
      marked = res.body.summary.marked;
      run.mark = change;
      then();
    }).catch(function () {
      clearTimeout(waited); busy = false; say(WORDS.noAnswer);
    });
  }

  function go(to) {
    if (to === "result") { window.location.href = url("/result"); return; }
    if (to === "reload") { window.location.reload(); return; }
    open(to); freshUntil = Date.now() + FRESH_MS; focusCard();
  }

  function next() {
    if (busy || fresh() || pick == null || !$("intro").hidden) { return; }
    var run = runs[pos], was = run.mark == null ? null : run.mark;
    if (was === pick) { go(following()); return; }  // unchanged: nothing to save
    var at = pos;
    send(pick, function () {
      history.push({pos: at, was: was});
      hear(pick === 0 ? WORDS.fine + "." : "Step " + pick + ".");
      go(following());
    });
  }

  function undo() {
    if (busy || !$("intro").hidden) { return; }
    if (!history.length) { say(WORDS.nothing, true); return; }
    var t = Date.now();
    if (t < lockUntil) { return; }
    lockUntil = t + LOCK_MS;
    var back = history.pop();
    open(back.pos);
    send(back.was, function () {
      pick = back.was; render(); hear("Undone."); focusCard();
    });
  }

  $("steps").addEventListener("mousedown", function (e) { e.preventDefault(); });
  $("steps").addEventListener("click", function (e) {
    var t = e.target, more = t.closest ? t.closest(".more") : null;
    if (more) {  // shows the whole step: never a mark
      var n = +more.getAttribute("data-n");
      opened[n] = !opened[n];
      render();
      return;
    }
    var b = t.closest ? t.closest(".step") : null;
    if (b) { choose(+b.getAttribute("data-n")); }
  });
  [["fine", function () { choose(0); }], ["next", next], ["undo", undo]].forEach(function (p) {
    $(p[0]).addEventListener("mousedown", function (e) { e.preventDefault(); });
    $(p[0]).addEventListener("click", p[1]);
  });
  $("see").setAttribute("href", url("/result"));
  $("see").textContent = WORDS.see;

  // The keys: 1 to 9 pick steps 1 to 9, 0 all steps fine, Enter or → Next, Z (or U) Undo. A
  // held key, or a key with Cmd, Ctrl or Alt, does nothing.
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || !$("intro").hidden) { return; }
    var tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") { return; }
    var k = (e.key || "").toLowerCase();
    if (k === "enter" && (tag === "BUTTON" || tag === "A")) { return; }  // the button's own
    if (e.repeat) { return; }
    if (k.length === 1 && k >= "1" && k <= "9") { choose(+k); }
    else if (k === "0") { choose(0); }
    else if (k === "enter" || k === "arrowright") { next(); }
    else if (k === "z" || k === "u") { undo(); }
    else { return; }
    e.preventDefault();
  });

  // The welcome box: until the first mark. The page behind it is inert.
  function startMarking() {
    $("intro").hidden = true; $("app").removeAttribute("inert");
    shownAt = Date.now(); freshUntil = shownAt + FRESH_MS;
    focusCard();
  }
  $("intro-ok").addEventListener("click", startMarking);
  $("intro-box").addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "Escape") { e.preventDefault(); startMarking(); }
    else if (e.key === "Tab") { e.preventDefault(); $("intro-ok").focus(); }
  });

  take(data);
  open(pos);
  if (data.intro === true) {
    $("intro").hidden = false; $("app").setAttribute("inert", "");
    $("intro-box").focus();
  } else { focusCard(); }
})();
</script>
</body>
</html>
"""


def _words() -> str:
    words = {"you": "You", "see": SEE_FIRST, "all": "Show all", "less": "Show less", "next": "Next",
             "result": SEE_READY, "fine": FINE, "empty": EMPTY_STEP, "otherTab": OTHER_TAB,
             "noAnswer": NO_ANSWER, "nothing": NOTHING_TO_UNDO}
    # no `<` and no `_`: the page can never hold a name the server fills in
    return json.dumps(words).replace("<", "\\u003c").replace("_", "\\u005f")


def _shown(value: str) -> str:
    """A value for the page's HTML: scrubbed of credentials, no hidden characters, escaped,
    and with no `_` (mark_page._text)."""
    return _page_text(visible(scrub(value) or ""))


def page_template(command: str) -> str:
    """The steps marking page; the server fills in __DATA__, __TOKEN__ and __NONCE__.
    `command`: how to come back to it, in the footer."""
    see = f'<a class="see" id="see" href="#" hidden>{escape(SEE_FIRST)}</a>'
    body = (BODY.replace("__TOP__", look.top("", see))
            .replace("__COMMAND__", look.command(_shown(command)))
            .replace("__TITLE__", _page_text(TITLE)).replace("__FINE__", _page_text(FINE))
            .replace("__BRAND__", look.BRAND).replace("__WORDS__", _words())
            .replace("__CUT__", str(CUT)).replace("__FRESH_MS__", str(FRESH_MS))
            .replace("__LOCK_MS__", str(LOCK_MS)))
    return look.head("judgekeeper: mark steps", STYLE) + body


# The result page --------------------------------------------------------------------------

RESULT_STYLE = """
main.result { max-width: 980px; margin: 0 auto; padding: 40px; }
main.result h1 { margin: 0 0 18px; font-size: 28px; font-weight: 800; letter-spacing: -.01em; }
.lines { margin: 0 0 28px; padding: 0; list-style: none; font-size: 15px; line-height: 1.6; }
.lines li { white-space: pre-wrap; overflow-wrap: anywhere; font-variant-ligatures: none;
  font-feature-settings: "calt" 0, "liga" 0; }  /* -- stays two hyphens */
.lines code { font-family: var(--mono); font-size: 13.5px; }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
th { text-align: left; font-size: 11px; font-weight: 600; letter-spacing: .1em;
  text-transform: uppercase; color: var(--faint); padding: 8px 12px;
  border-bottom: 1px solid var(--line); }
td { padding: 10px 12px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
td.g { font-family: var(--mono); font-size: 13.5px; white-space: nowrap; }
td.both { color: var(--green); }
.back { display: inline-block; margin: 0 0 24px; font-size: 14px; font-weight: 700;
  color: var(--green); text-decoration: none; }
.back:hover { text-decoration: underline; }
"""


def _pick_word(value) -> str:
    return ALL_FINE if value == 0 else f"Step {value}"


def _picks(session: StepsSession) -> tuple[str | None, dict] | None:
    """(the column's name, run id -> the agent-as-a-judge's pick) from the --reviewer file:
    the one --model names, else the first by name (named in the column when there are
    several); None without a file."""
    if session.reviewer is None:
        return None
    guesses, _ = steps._picks({}, str(session.reviewer), session.model)
    if not guesses:
        return JUDGE, {}
    name = min(guesses)
    column = JUDGE if len(guesses) == 1 else f'{JUDGE} "{name}"'
    return column, guesses[name]


def number_lines(session: StepsSession) -> list[str]:
    """The numbers' lines, as the terminal says them (steps.numbers_from_marks), without
    blank lines and its Next: line (the page's way on is "Change a mark"). None marked yet:
    none."""
    if not session.out.is_file():
        return []
    lines, _ = steps.numbers_from_marks(session.runs_path, session.out, session.reviewer,
                                        session.model, shown=session.shown)
    return [x for x in lines if x.strip() and not x.startswith("Next:")]


def _line_html(line: str) -> str:
    parts = _shown(line).split("`")
    return "".join(f"<code>{p}</code>" if k % 2 else p for k, p in enumerate(parts))


def result_page(session: StepsSession, back: str) -> str:
    """"Your result": the numbers' lines, then one row per marked run: the run, the person's
    pick and the agent-as-a-judge's ("Both" when they match)."""
    session._read()
    stand = session.marked()
    try:
        picks = _picks(session)
        lines = number_lines(session)
    except steps.StepsError as err:  # a file gone or broken since the page opened
        picks, lines = None, [str(err)]
    else:
        if picks is None:
            lines = [*lines, NO_PICKS]
    head = ["Run", "You"] + ([] if picks is None else [picks[0]])
    rows = []
    for run_id in session.order:
        if run_id not in stand:
            continue
        cells = [f"<td>{_shown(run_id)}</td>", f'<td class="g">{_pick_word(stand[run_id])}</td>']
        if picks is not None:
            theirs = steps.usable(picks[1].get(run_id), len(session.by_id[run_id].steps))
            if theirs is None:
                cells.append('<td class="g"></td>')
            elif theirs == stand[run_id]:
                cells.append(f'<td class="g both">{BOTH}</td>')
            else:
                cells.append(f'<td class="g">{_pick_word(theirs)}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    items = "".join(f"<li>{_line_html(x)}</li>" for x in lines)
    table = ("<table><thead><tr>" + "".join(f"<th>{_shown(h)}</th>" for h in head)
             + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    return (look.head("judgekeeper: your steps result", RESULT_STYLE) + look.top("", "")
            + f'<main class="result"><h1>{RESULT_TITLE}</h1>'
            + f'<a class="back" href="{escape(back)}">{CHANGE}</a>'
            + f'<ul class="lines">{items}</ul>{table}</main>\n</body>\n</html>\n')


# The server -------------------------------------------------------------------------------

def flags_for(path: str | Path, shown: str | None = None, reviewer: str | None = None,
              model: str | None = None, port: int = 0, no_browser: bool = False) -> dict:
    """What the page keeps of the run that opened it (page.open_new's `flags`): the runs file
    and the picks file, as typed (`path`, `reviewer`, for its come-back command) and whole
    (`steps`, `reviewer_file`: the page runs in another folder)."""
    return {"path": shown if shown is not None else str(path), "port": port,
            "no_browser": no_browser, "steps": str(Path(path).resolve()),
            "reviewer": reviewer,
            "reviewer_file": str(Path(reviewer).resolve()) if reviewer else None,
            "model": model}


def page_key(flags: dict) -> dict:
    """What the steps page shows (page.page_key): the runs file, the picks file and the
    runs file's hash. A page open with another key is started again."""
    kept = {k: flags.get(k) for k in ("path", "steps", "reviewer", "reviewer_file", "model")}
    try:
        about = file_hash(Path(flags["steps"]))
    except OSError:
        about = None
    return {"flags": kept, "start": about}


def come_back(flags: dict) -> str:
    """`judgekeeper steps RUNS [--reviewer FILE]`, as the footer says it."""
    return steps._command(str(flags.get("path") or "."), flags.get("reviewer"))


def steps_server(ws: Workspace, port: int, flags: dict, token: str | None = None,
                 stamp: str | None = None, code: str | None = None):
    """The steps marking page on `port`, holding the project's lock (one page at a time).
    `stamp`: how the page with the same token was stamped (marks.LINKS)."""
    session = StepsSession(ws, flags["steps"], reviewer=flags.get("reviewer_file"),
                           model=flags.get("model"), shown=flags.get("path"))
    if stamp in marks.LINKS:
        session.link = stamp
    port_asked = flags.get("port")
    return make_server(session, port, result=result_page, page=page_template(come_back(flags)),
                       lock=ws.dir, stays=True, token=token, settings=page_key(flags),
                       asked=port_asked if type(port_asked) is int else None,
                       no_browser=flags.get("no_browser") is True, code=code)


# The command: `judgekeeper steps runs.jsonl` opens the page ---------------------------------

OPEN = "The marking page is open in your browser. Click the first wrong step of each run."
CLICK = "Click the first wrong step of each run."
NEXT = 'Next: mark runs on the page, then click "See the numbers so far".'
LABEL_STUDIO = ("Label in Label Studio instead? Import .judgekeeper/steps/label-these.json with "
                "label-config.xml, then run judgekeeper steps on its export.")
NEW_ANSWERS_ONLY = "--new works for answers only. To take back a step mark, use Undo on the page."
NO_PAGE_ON_EXPORT = ("`{command}` opens no page, so it takes no --port or --no-browser.")
# As the answers page says them (front.py)
STAYS = "The page stays open while this runs. To stop it: Ctrl-C."
COULD_NOT_START = ("The marking page could not start in the background (what went wrong is in "
                   ".judgekeeper/page.log).")


def _say(text: str = "") -> None:
    steps._say(text)


def opened_with(flags) -> tuple[str, str | None] | None:
    """The runs path and the picks file as typed where the open page was started (its lock's
    flags), each one line of text; None when the lock holds no steps page."""
    if not isinstance(flags, dict) or not flags.get("steps"):
        return None
    path, reviewer = flags.get("path"), flags.get("reviewer")

    def ok(value) -> bool:
        return isinstance(value, str) and value.isprintable() and 0 < len(value) < 4096

    if not ok(path):
        return None
    return path, reviewer if ok(reviewer) else None


def stop(given: Path) -> int:
    """`judgekeeper steps --stop`: close the project's open page (one page at a time, so the
    answers page too), as `judgekeeper --stop` says it."""
    from judgekeeper import background
    from judgekeeper.front import NEXT_CONTINUE
    from judgekeeper.label import is_open, read_lock

    ws = Workspace(project_of(given))
    lock = read_lock(ws.dir) if is_open(ws.dir) else None
    typed = opened_with((lock.get("settings") or {}).get("flags")) if lock else None
    _say(f"judgekeeper {__version__}")
    _say()
    if lock is None:
        _say("No marking page is open.")
    elif not background.stop(ws.dir):
        _say("The marking page did not close.")
        _say()
        _say("Next: close it with Ctrl-C in the terminal it runs in; else it closes by itself "
             "after 30 minutes without use.")
        return steps.EXIT_NEEDS_YOU
    else:
        saved = " Your marks are saved." if (ws.dir / steps.FOLDER / MARKS_FILE).is_file() else ""
        _say(f"Closed the marking page.{saved}")
    _say()
    command = steps._command(*typed) if typed else steps._command(str(given), None)
    _say("Next: " + NEXT_CONTINUE.format(command=command))
    return steps.EXIT_OK


def project_of(given: Path) -> Path:
    from judgekeeper import project

    return project.project_of(given)


def open_runs(file: Path, given: Path, reviewer: str | None, model: str | None,
              options: dict) -> int:
    """After the Label Studio files are written: open the steps page for the runs in `file`
    (`given` as typed), with the page flags in `options` (port, no_browser, wait), and say
    how to go on. With --no-browser and marks already made, the numbers too; with --wait,
    the numbers once the page closes."""
    from judgekeeper import background
    from judgekeeper import page as pages
    from judgekeeper.front import (
        CLOSED_IT,
        COULD_NOT,
        IN_BROWSER,
        NEXT_ANY_PORT,
        PORT_TAKEN,
        RESULT_OPEN,
    )

    ws = Workspace(project_of(given))
    shown = str(given)
    no_browser, wait = bool(options.get("no_browser")), bool(options.get("wait"))
    flags = flags_for(file, shown=shown, reviewer=reviewer, model=model,
                      port=options.get("port", pages.DEFAULT_PORT), no_browser=no_browser)
    command = steps._command(shown, reviewer)
    done = StepsSession(ws, file).summary()["done"]  # every run marked: open at the result
    opened = None
    try:
        opened = pages.open_new(ws, flags["port"], flags, here=wait, say=_say)
        how = opened and pages.show(_say, opened, no_browser, wait, result=done,
                                    link_line=pages.STEPS_LINK)
    except KeyboardInterrupt:  # before its link was printed: no page is left running
        pages.close(ws, opened)
        raise
    if not how:
        if opened is not None and opened.server is None:
            background.stop(ws.dir)
        tried = pages.choose_port(flags["port"], lambda line: None)
        if opened is None and not pages.port_free(tried):
            _say(PORT_TAKEN.format(port=tried))
            _say()
            _say("Next: " + NEXT_ANY_PORT.format(command=f"{command} --port 0"))
        else:
            _say(COULD_NOT_START)
            _say()
            _say("Next: " + COULD_NOT.format(command=f"{command} --wait"))
        return steps.EXIT_NEEDS_YOU
    if opened.kept and not no_browser:  # no new tab for a page open already
        _say(IN_BROWSER if done else f"{IN_BROWSER} {CLICK}")
        if how == pages.KEPT:
            _say(CLOSED_IT.format(command=f"{command} --no-browser"))
    elif done:  # opened at the result: its link says so when printed
        if how == pages.BROWSER:
            _say(RESULT_OPEN)
    else:
        _say(OPEN if how == pages.BROWSER else CLICK)
    if opened.server is not None:
        _say(STAYS)
    marked = steps.marks_path(given).is_file()
    _say()
    if (no_browser or done) and marked:  # the numbers, also for a program with no page
        code = steps.say_numbers_from_marks(file, shown, reviewer, model)
    else:
        _say(NEXT)
        _say(LABEL_STUDIO)
        code = steps.EXIT_OK
    if opened.server is None:
        return steps.EXIT_OK if code is None else code
    stopped = False
    try:
        pages.serve(opened.server)
    except KeyboardInterrupt:
        stopped = True
    _say()
    said = steps.say_numbers_from_marks(file, shown, reviewer, model)
    if said is None:
        if stopped:
            raise KeyboardInterrupt
        return steps.EXIT_OK
    return said
