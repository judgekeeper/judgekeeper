"""Marking with `judgekeeper`: the queue, the `.judgekeeper/` folder, the session the marking
page writes to, and the result.

The queue: a seeded shuffle of the LLM-as-a-judge's passes and fails, in blocks of 10 with 5
from each, so both kinds are seen early; the seed is saved, so it can be rebuilt.
`.judgekeeper/` holds start.json, pool.jsonl and pool-judge.jsonl (written when marking
starts or a batch joins), marks.jsonl (written by the page), the anchors, judge-check files,
result.json, report.html and history.jsonl, and fix/. Its .gitignore keeps the answers off Git.

report.html is written first, then the history line, then result.json, each renamed into
place, so a run stopped half way is repaired by the next. A cloned project controls
`.judgekeeper/`: a link in it stops judgekeeper (`refuse_links`), and every file is written as
a new file renamed over the old one, which replaces a link instead of following it. Every
string from a results file is scrubbed of credentials before it is written.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
import re
import secrets
from pathlib import Path

from judgekeeper import __version__, batches, judge_check, marks, reasons, targets, weighted
from judgekeeper.anchors import canonical_hash
from judgekeeper.fingerprint import JudgeFingerprint, rule_hash, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.label import LabelSession
from judgekeeper.records import AGENT_FIELDS
from judgekeeper.redact import scrub, scrub_fingerprint, scrub_value, visible
from judgekeeper.runners.base import Judgment
from judgekeeper.table import guard_cell, write_anchor_file
from judgekeeper.textio import (
    file_stamp,
    jsonl_lines,
    link_in,
    make_private,
    plural,
    program,
    read_cached,
    write_replacing,
)

FOLDER = ".judgekeeper"
BLOCK = 10
ROUGH = targets.ROUGH
GITIGNORE = ("# judgekeeper's files hold your answers. Commit them only if your data "
             "may live here.\n*\n!.gitignore\n!judge.json\n!history.jsonl\n")
# The exact text 0.2 wrote, by its SHA-256 (its first line has older words)
OLD_GITIGNORE_SHA256 = "fbefa615c803cdd5410b6da92a3d848d329dcb64930a47830f9e834fa4d44663"
LINK = ("{path} is a link to another {kind}. judgekeeper does not write through links. "
        "Remove it, then run {program} again.")
SAVED_NOTE = ("Saved in {folder}/. It holds your answers' text: commit it only if your data "
              "may live in your repo.")


def shown_folder(ws: Workspace) -> str:
    """The workspace folder as the person finds it from where they ran start: .judgekeeper
    here, else its path (next to a results file given from elsewhere, or a link's target)."""
    import os

    here = Path.cwd().resolve() / FOLDER
    folder = ws.dir.resolve()
    if folder == here:
        return FOLDER
    try:
        rel = Path(os.path.relpath(folder, Path.cwd().resolve()))
    except ValueError:  # another drive on Windows
        return folder.as_posix()
    # a folder nearby as ../elsewhere/.judgekeeper; one far away as its whole path
    return rel.as_posix() if rel.parts.count("..") <= 2 else folder.as_posix()


# The three headlines, the same in the terminal and on the result page (report_page.STATES)
GOOD = "Your LLM-as-a-judge is good enough to use."
NEEDS = "Your LLM-as-a-judge needs work."
EARLY = "Too early to tell."
MARK_MORE = "Mark more answers to get a result."
VERDICTS = {  # the result line (targets.level decides)
    "gate": GOOD,
    "check": f"{EARLY} {MARK_MORE}",
    "not_gate": NEEDS,
    "too_early": f"{EARLY} {MARK_MORE}",
    None: "Mark a few more answers to see your result.",
}
ALL_LABELED = "Every saved answer is marked. Run your eval again for more answers, then:"
# Every answer marked, and a result still needs more: the same words in the terminal, `mark`,
# the Measure screen, the marking page's end card and the result page
ALL_MARKED = "You've marked every answer: {marks}."
NEEDS_EACH = " A result needs at least {n} of each."
TOO_FEW_TO_TELL = " That's still too few to tell."  # enough of each, the ranges still too wide
EVERY_MARKED = "You marked every answer."  # the page's line once a result is ready
# Under the disagreements ({n}: how many), the terminal and report.html say these two lines
SAY_WHY_RUN = "Tell judgekeeper why you disagree on these {n}: run `{command}`."
SAY_WHY_FIX = "`{fix}` uses your reasons to find where your LLM-as-a-judge goes wrong."
NEXT_ALL_MARKED = ("run your eval on more questions, then run `{command}`: the new answers join "
                   "the ones you marked.")
SAID = {"tpr": "Pass", "tnr": "Fail"}  # what the person said, per rate
DID = {"tpr": "passed", "tnr": "failed"}
TOO_EARLY = "too early to tell"
# How the numbers are worked out: one more whenever the Measure maths changes. A result saved
# with another (or none: 1.0.0b1) is worked out again from the marks before it is shown.
NUMBERS_VERSION = 2
WORKED_OUT_AGAIN = "Your numbers were worked out again with this version of judgekeeper."


class Workspace:
    """The `.judgekeeper/` folder of one project, or (`folder`) another folder holding a
    check of its own, such as a new judge's confirmation check."""

    def __init__(self, root: str | Path, folder: str | Path | None = None):
        self.root = Path(root)
        self.dir = Path(folder) if folder is not None else self.root / FOLDER
        self.start = self.dir / "start.json"
        self.pool = self.dir / "pool.jsonl"
        self.pool_judge = self.dir / "pool-judge.jsonl"
        self.marks = self.dir / marks.FILE
        self.labels = self.dir / "labels.csv"  # judgekeeper 0.2's marks: never read
        self.anchors = self.dir / "anchors.jsonl"
        self.result_json = self.dir / "result.json"
        self.report_html = self.dir / "report.html"
        self.result_html = self.dir / "result.html"  # the result page's name before 1.0
        self.history = self.dir / "history"
        self.history_jsonl = self.dir / "history.jsonl"
        self.judge_check_json = self.dir / judge_check.JSON_FILE
        self.judge_check_csv = self.dir / judge_check.CSV_FILE

    def data(self) -> dict:
        return json.loads(self.start.read_text(encoding="utf-8"))

    def cached_data(self) -> dict:
        """start.json, parsed again only when it changed: for reading only (it is shared)."""
        return read_cached(self.start, _load_start)

    def cached_strata(self) -> tuple:
        """batches.strata of start.json, worked out again only when it changed: read only."""
        return read_cached(self.start, _start_strata)


def _load_start(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _start_strata(path: Path) -> tuple:
    return batches.strata(read_cached(path, _load_start))


def refuse_links(ws: Workspace) -> None:
    """Stop (StartError) when `ws.dir`, or anything in it, is a link."""
    from judgekeeper.start import StartError

    link = link_in(ws.dir)
    if link is not None:
        try:
            shown = link.relative_to(ws.root).as_posix()
        except ValueError:
            shown = str(link)
        raise StartError(LINK.format(path=shown, kind="folder" if link.is_dir() else "file",
                                     program=program()))


def check_writable(ws: Workspace) -> None:
    """StartError when judgekeeper can't write in `ws.dir` (a read-only .judgekeeper/): the
    same words wherever the first write would have failed."""
    from judgekeeper.start import StartError
    from judgekeeper.textio import WORKSPACE_DENIED, WORKSPACE_DENIED_NEXT

    try:
        if ws.dir.is_dir() and not ws.dir.is_symlink() and not os.access(ws.dir, os.W_OK):
            raise StartError(WORKSPACE_DENIED, WORKSPACE_DENIED_NEXT)
    except OSError:
        return


def make_folder(ws: Workspace) -> None:
    """Make `ws.dir` (after `refuse_links`), with its .gitignore when a first check starts in
    the project's own folder and it has none. One holding exactly the text 0.2 wrote is
    replaced; any other is left alone."""
    refuse_links(ws)
    make_private(ws.dir)
    gitignore = ws.dir / ".gitignore"
    if ws.dir != ws.root / FOLDER:
        return
    if not ws.start.is_file() and not os.path.lexists(gitignore):
        write_replacing(gitignore, GITIGNORE)
    elif gitignore.is_file() and not gitignore.is_symlink():
        try:  # 0.2 wrote it with the system's line endings
            text = gitignore.read_text(encoding="utf-8")
            old = hashlib.sha256(text.encode("utf-8")).hexdigest() == OLD_GITIGNORE_SHA256
        except (OSError, ValueError):
            old = False
        if old:
            write_replacing(gitignore, GITIGNORE)


def _scrubbed(value):
    """`value` with every string in it scrubbed of credentials."""
    return scrub_value(value)


def _write_json(path: Path, data) -> None:
    write_replacing(path, json.dumps(_scrubbed(data), indent=2, ensure_ascii=False) + "\n")


# The queue -------------------------------------------------------------------------------

AHEAD = 100  # answers past the furthest one marked that the page gets at once

def build_queue(answers, seed: int) -> list[dict]:
    """[{"id", "group"}] for every answer in the pool, in the order the page shows them."""
    rng = random.Random(seed)
    left = {g: sorted(a.id for a in answers if a.verdict == g) for g in ("pass", "fail")}
    for ids in left.values():
        rng.shuffle(ids)
    half = BLOCK // 2
    queue = []
    while left["pass"] or left["fail"]:
        take = {g: min(half, len(ids)) for g, ids in left.items()}
        short = BLOCK - sum(take.values())
        for g, other in (("pass", "fail"), ("fail", "pass")):
            if take[g] < half:  # this group ran out: the other fills the block
                take[other] = min(take[other] + short, len(left[other]))
        block = [{"id": i, "group": g} for g in ("pass", "fail") for i in left[g][:take[g]]]
        for g, ids in left.items():
            del ids[:take[g]]
        rng.shuffle(block)
        queue += block
    return queue


# Starting to label -----------------------------------------------------------------------

def save_judge_check(ws: Workspace, found) -> None:
    """judge-check.json (the counts and each answer found) and judge-check.csv (the same
    answers with their text) for `found.check`, scrubbed; CSV cells guarded as labels.csv's."""
    check = found.check
    if check is None:
        return
    if not judge_check.has_rows(check.block()):  # nothing to list: no file, no stale list
        for stale in (ws.judge_check_json, ws.judge_check_csv):
            if stale.is_file() and not stale.is_symlink():
                stale.unlink()
        return
    make_folder(ws)
    _write_json(ws.judge_check_json, check.to_json())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(judge_check.CSV_COLUMNS)
    for x in check.findings:
        w.writerow([guard_cell(scrub(v) or "") for v in (
            x.id, x.problem, x.tool_counted_as or "", x.judge_decision, x.judge_reason,
            display(x.input), display(x.output))])
    write_replacing(ws.judge_check_csv, buf.getvalue(), newline="")


def prepare(found, say, ws: Workspace | None = None) -> Workspace:
    """Write start.json, pool.jsonl and pool-judge.jsonl for `found` (a start.Found), in `ws`
    (default: the project's `.judgekeeper/`).

    When start.json already holds the same pool (the same answers with the same verdicts),
    its seed and queue are kept, so labeling again carries on where it stopped.
    """
    from judgekeeper.start import StartError

    ws = ws or Workspace(found.root)
    refuse_links(ws)
    answers = {a.id: a for a in found.pool.answers}
    old = ws.data() if ws.start.is_file() else None
    groups = {a.id: a.verdict for a in found.pool.answers}
    same = old is not None and {q["id"]: q["group"] for q in old["queue"]} == groups
    if same:
        seed, queue, started = old["seed"], old["queue"], old.get("started_at")
    else:
        if ws.marks.is_file() and marks.read(ws.marks).counted():
            raise StartError(f"{FOLDER}/{marks.FILE} holds marks for other results. Move "
                             f"{FOLDER}/ somewhere else to start fresh; nothing was changed.")
        seed = secrets.randbelow(2**31)
        queue, started = build_queue(found.pool.answers, seed), None
    first = old is None
    make_folder(ws)

    pool, records = [], []
    for q in queue:
        a = answers[q["id"]]
        pool.append({"id": a.id, "input": a.input, "output": a.output, **a.agent})
        records.append(judge_record(a, found))
    pool = _scrubbed(pool)
    write_replacing(ws.pool, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pool))
    pool_sha = canonical_hash(pool)
    source = {"kind": found.tool, "file": ", ".join(found.used), "metric": found.metric}
    write_run(ws.pool_judge, 1, pool_sha, JudgeFingerprint.from_dict(found.fingerprint),
              records, source=source)
    save_judge_check(ws, found)

    newest = found.results[0]
    p = found.pool
    _write_json(ws.start, {
        "judgekeeper_version": __version__,
        "tool": found.tool,
        "results_files": found.used,
        "results_date": f"{newest.date():%Y-%m-%d %H:%M}",
        "metric": found.metric,
        "judge": found.judge,
        "rule": found.rule,
        "description": found.description,
        "app_version": found.app_version,
        **({"mlflow_store": found.store} if found.store else {}),
        **({"given": found.given} if getattr(found, "given", None) else {}),
        "fingerprint": scrub_fingerprint(found.fingerprint),
        "pass_mark": found.pass_mark,
        "one_rule": found.one_rule,
        **({"task_file": found.task_file} if found.task_file else {}),
        **({"rule_field": found.rule_field} if found.rule_field else {}),
        # --label-map as given: later runs without it read the results the same way
        **({"label_map": found.label_map} if getattr(found, "label_map", None) else {}),
        "pool": {"answers": len(p.answers), "pass": p.n_pass, "fail": p.n_fail},
        "pool_sha256": pool_sha,
        "left_out": {"no_clear_verdict": p.n_unclear, "unmapped_values": p.unmapped,
                     "repeats_merged": p.n_merged, "human_labels_not_used": p.n_human},
        **({"judge_check": found.check.block()} if found.check is not None else {}),
        "seed": seed,
        "queue": queue,
        "started_at": started or utc_now(),
        "updated_at": utc_now(),
    })
    if not same or not ws.marks.is_file():
        begin_marks(ws)
    if first:
        say(SAVED_NOTE.format(folder=shown_folder(ws)))
    return ws


def judge_record(a, found) -> dict:
    """pool-judge.jsonl's line for the answer `a` (a start.Answer) of `found`: its verdict,
    score and reason, with its fingerprint (the model given by the person, when given)."""
    given = found.fingerprint.get("model_source") is not None
    fp = a.fingerprint.with_(model=found.fingerprint["model"]) if given else a.fingerprint
    return judgment_to_record(a.id, Judgment(verdict=a.verdict, raw_score=a.score,
                                             rationale=a.reason), fp)


def judge_of(data: dict) -> dict:
    """The judge as start.json keeps it, as marks.jsonl's header and history.jsonl say it."""
    fp = data.get("fingerprint") or {}
    return {"tool": data.get("tool"), "model": fp.get("model"),
            "rule_hash": rule_hash(data.get("rule")), "pass_mark": data.get("pass_mark"),
            "fingerprint": fp}


def begin_marks(ws: Workspace) -> None:
    """A new marks.jsonl, its header from start.json: marking starts."""
    data = ws.data()
    marks.begin(ws.marks, _scrubbed(marks.header(judge=judge_of(data), pool=data["pool"],
                                                 results=data.get("results_files") or [])))


# The session the page writes to ----------------------------------------------------------

def display(value) -> str:
    """An input or output as text for the page: a string as written; a dict of fields (such
    as promptfoo's vars) as one `name: value` line each."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"
                         for k, v in value.items())
    return json.dumps(value, ensure_ascii=False, indent=2)


def question_view(value):
    """A question as the page shows it: text as written; of a set of named values (such as
    promptfoo's vars), one value alone, or several as [[name, value as text], ...]."""
    if isinstance(value, dict) and len(value) > 1:
        return [[str(k), v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)]
                for k, v in value.items()]
    if isinstance(value, dict) and value:
        value = next(iter(value.values()))
    return display(value)


def _all_exact(r: dict) -> bool:
    """Whether both ranges have no width: more marks can't change them."""
    ends = [r.get(f"{k}_interval") or [None, None] for k in ("tpr", "tnr")]
    return all(lo is not None and hi is not None and hi - lo <= 1e-12 for lo, hi in ends)


def status_line(r: dict) -> str:
    """How far along a check is, in the words the person reads (no targets, no numbers): the
    line under the meters on the labeling page, and on the result when a range is still
    wide. The counts behind it are targets.check's."""
    if r["check"] == "too_few":
        return VERDICTS[None]
    if r["check"] == "reliable":
        return "Your result is ready."
    wide = r.get("wide") or {}
    if not wide and _all_exact(r):  # a judge that passes (or fails) every answer
        return "You can see your result now."
    if not wide:
        return "You can see your result now. Marking more answers narrows its ranges."
    sides = " and ".join(SAID[key] for key in ("tpr", "tnr") if key in wide)
    return f"Marking more answers narrows the range for the answers you marked {sides}."


def progress_status(n_pool_pass: int, n_pool_fail: int, n_p: int, c_p: int, n_f: int,
                    c_f: int) -> dict:
    """The line under the meters on the labeling page (status_line), and whether a result is
    ready: from the marks in each group, as the result counts them (one batch)."""
    return strata_status([(1, "pass", n_pool_pass, n_p, c_p), (1, "fail", n_pool_fail, n_f, c_f)])


def strata_status(strata: list[tuple[int, str, int, int, int]]) -> dict:
    """progress_status from the marks in each stratum, as the result counts them
    (batches.counted_strata). Under ROUGH marks of each kind there is no result yet, a count
    rule (targets.check): no range is drawn."""
    correct = sum(s[4] for s in strata)
    if min(correct, sum(s[3] for s in strata) - correct) < ROUGH:
        return {"text": VERDICTS[None], "ready": False}
    r = describe(weighted.stratified(strata))
    return {"text": status_line(r), "ready": r["check"] != "too_few"}


def start_status(session: StartSession, run: str | None = None) -> dict:
    """The line under the meters for `start`'s labeling: from the session's labels. With
    every answer marked and no result yet, `done` holds what the end card says
    (all_marked_lines, with mark_command of `run`, the command that opened the page)."""
    ws = session.workspace
    status = strata_status(batches.counted_strata(ws.cached_data(), session.marked(),
                                                  ws.cached_strata()))
    every = bool(session.items) and all(i["label"] for i in session.items)
    if not status["ready"] and every:
        counts = session.counts()  # nothing left to mark: the end card says what comes next
        done = all_marked_lines({"correct": counts["correct"], "wrong": counts["wrong"]},
                                mark_command(run))
        status.update(text=done[0], done=done)
    elif every:  # never "marking more answers narrows...": there is none left to mark
        status.update(text=EVERY_MARKED)
    return status


class StartSession(LabelSession):
    """The pool in queue order and the person's marks. Skip is the label session's defer. Each
    change is one stamped line in marks.jsonl (marks.py), with this session's `sitting` and
    the `seconds` the page sends; a session made again reads the marks back. The page gets
    ids, text, the person's labels and the line under the meters (`status`, by default
    start_status) only."""

    def __init__(self, ws: Workspace, status=None):
        self.workspace = ws
        data = ws.data()
        self.groups = {q["id"]: q["group"] for q in data.get("queue", [])}
        self.pool = data.get("pool", {})
        self.status = status or start_status
        self.sitting = marks.new_sitting()
        self.link: str | None = None  # marks.PRINTED once the page's link was printed for an agent
        self.not_counted = 0  # lines of marks.jsonl not made on the page
        self.changes = 0  # counts every change to the marks in memory
        self._marks_seen: tuple | None = None  # marks.jsonl as last read or written
        self._status: tuple | None = None  # (changes, start.json's stamp, the status)
        super().__init__(ws.pool, ws.marks)
        raw = [json.loads(line) for line in jsonl_lines(ws.pool.read_text(encoding="utf-8"))
               if line.strip()]
        self.raw = {r["id"]: r for r in raw}

    def _resume(self) -> None:
        """The marks on disk: the last stamped line of each answer."""
        seen = file_stamp(self.out)
        m = marks.read(self.out)
        self._marks_seen, self.changes = seen, self.changes + 1
        self.not_counted = m.not_counted
        for item in self.items:
            line = m.last.get(item["id"]) or {}
            mark = line.get("mark")
            item["label"] = mark if mark in ("pass", "fail") else None
            item["deferred"] = mark == "skip"
            item["note"] = line.get("note") or ""

    def _reread(self) -> None:
        """The marks on disk, when marks.jsonl changed since this session last read or wrote
        it (another page or run wrote a line)."""
        if self.out.is_file() and file_stamp(self.out) != self._marks_seen:
            try:
                self._resume()
            except OSError:
                pass

    def current_status(self) -> dict:
        """The line under the meters (`status`), worked out again only after a change to the
        marks or to start.json: it draws the ranges."""
        key = (self.changes, file_stamp(self.workspace.start))
        if self._status is None or self._status[0] != key:
            self._status = (key, self.status(self))
        return self._status[1]

    def update(self, body: dict) -> None:
        """Apply one change ({"id", "label"?, "deferred"?, "note"?, "seconds"?}) and add its
        stamped line. The marks on disk are read again first, so marks another page wrote are
        kept. A change with reasons and no mark (the result page) is a reason line
        (add_reasons). A mark changed after the judge's grades were shown is stamped so."""
        self._reread()
        item = self.by_id[body["id"]]
        if any(k in body for k in ("reasons", "note", "rule_parts", "spans")):
            if "label" in body or "deferred" in body:
                raise ValueError("a reason is given on your result page, not with a mark")
            self.add_reasons(item, body)
            return
        before = dict(item)
        try:
            self._apply(item, body)
            mark = item["label"] or ("skip" if item["deferred"] else None)
            changed = before["label"] in ("pass", "fail") and mark != before["label"]
            line = marks.stamp(item["id"], mark, self.groups.get(item["id"]),
                               body.get("seconds"), self.sitting, note=body.get("note"),
                               link=self.link,
                               after_result=changed and reasons.grades_shown(self.workspace))
            if not self.out.is_file():
                begin_marks(self.workspace)
            seen = file_stamp(self.out)
            marks.append(self.out, line)
            if seen == self._marks_seen:  # nobody else wrote in between: memory is the file
                self._marks_seen = file_stamp(self.out)
            self.changes += 1
        except BaseException:
            item.update(before)  # memory matches the file on disk
            raise

    def add_reasons(self, item: dict, body: dict) -> None:
        """Why the person disagrees with the judge on `item` (reasons.check), as a line with
        the same mark; the person's own button follows the "Other…" box, and report.html is
        drawn again with the reasons."""
        why = reasons.check(self.workspace, item["id"], item["label"],
                            self.groups.get(item["id"]), body,
                            marks.read(self.out).last.get(item["id"]))
        if "note" in body:  # the button first: the page says "Saved" only once both are
            m = marks.read(self.out)
            tapped = {k for i, x in m.last.items() if i != item["id"]
                      for k in x.get("reasons") or []}
            reasons.sync_own(self.workspace, item["id"], why.get("note", ""), tapped)
        marks.append(self.out, marks.stamp(item["id"], item["label"],
                                           self.groups.get(item["id"]), None, self.sitting,
                                           link=self.link, why=why))
        try:
            write_report(self.workspace)
        except OSError:
            pass  # the reasons are saved; report.html catches up with the next result

    def write(self) -> None:
        raise NotImplementedError("marks.jsonl gets one line per change: use update()")

    def counts(self) -> dict:
        labels = [i["label"] for i in self.items]
        return {"correct": labels.count("pass"), "wrong": labels.count("fail"),
                "skipped": sum(i["deferred"] for i in self.items)}

    def marked(self) -> dict[str, str]:
        """{id: "pass" or "fail"}: the answers marked."""
        return {i["id"]: i["label"] for i in self.items if i["label"]}

    def summary(self) -> dict:
        counts = self.counts()
        return {"n_items": len(self.items), "n_labeled": counts["correct"] + counts["wrong"],
                "counts": counts, "done": all(i["label"] or i["deferred"] for i in self.items),
                "status": self.current_status()}

    def state(self) -> dict:
        """What the page needs: the answers up to the furthest one marked or skipped and the
        next AHEAD after it (never the whole pool: it can hold 100,000 answers), and `total`.
        Past them the page asks again."""
        touched = max((n for n, i in enumerate(self.items) if i["label"] or i["deferred"]),
                      default=-1)
        shown = self.items[:touched + 1 + AHEAD]
        start = next((n for n, i in enumerate(shown)
                      if not i["label"] and not i["deferred"]), 0)
        items = [{"id": i["id"], "input": question_view(self.raw[i["id"]].get("input")),
                  "output": display(self.raw[i["id"]].get("output")), "label": i["label"],
                  "skipped": i["deferred"]} for i in shown]
        return {"items": items, "total": len(self.items), "start": start,
                "counts": self.counts(), "status": self.current_status()}


# The result ------------------------------------------------------------------------------

def plain(x: float | None) -> float | None:
    """`x` rounded to 9 decimals, for comparing with a cut-off: 9/10 worked out in floating
    point is 0.8999999999999999, which is 0.90."""
    return None if x is None else round(x, 9)


def _level(r: dict) -> str | None:
    """The verdict from the ranges (targets.level); None before a first result."""
    if r["check"] == "too_few":
        return None
    return targets.level(r["tpr_interval"], r["tnr_interval"])


def _verdict(r: dict) -> str:
    """The verdict's words."""
    return VERDICTS[r["verdict_level"]]


def describe(corrected: dict) -> dict:
    """The corrected numbers plus the mark counts (`labels`: correct is marked Pass, wrong is
    marked Fail), how far along they are, and the one coloured line (`verdict`: from the two
    ranges, never a number alone, with wording that only says how often it agrees)."""
    g = corrected["groups"]
    correct = g["pass"]["correct"] + g["fail"]["correct"]
    wrong = g["pass"]["labeled"] + g["fail"]["labeled"] - correct
    r = dict(corrected)
    r["labels"] = {"correct": correct, "wrong": wrong}
    r.update(targets.check(correct, wrong, r["tpr_interval"], r["tnr_interval"]))
    r["verdict_level"] = _level(r)
    r["verdict"] = _verdict(r)
    return r


def _pct(x: float) -> str:
    return f"{x:.0%}"


def marks_words(labels: dict) -> str:
    """"12 Pass, 9 Fail"."""
    return f"{labels['correct']} Pass, {labels['wrong']} Fail"


def short_words(labels: dict) -> str:
    """The kinds still under ROUGH marks: "3 Fail", or "9 Pass and 3 Fail"."""
    said = [f"{labels[k]} {word}" for k, word in (("correct", "Pass"), ("wrong", "Fail"))
            if labels[k] < ROUGH]
    return " and ".join(said)


def sentences(r: dict) -> list[str]:
    """The two sentences of the result; before a result, the one line that says to mark more,
    or, when every answer is marked and still a kind is short, why there is no result (the one
    place a count is said: it explains a stop, it is not a target)."""
    if r["check"] == "too_few":
        if all_labeled(r):
            from judgekeeper.start import command_from

            return all_marked_lines(r["labels"],
                                    mark_command(command_from(r.get("flags"), kept=True)))
        return [f"{VERDICTS[None]} So far: {marks_words(r['labels'])}."]
    return [side_sentence(key, r[key], r[f"{key}_interval"]) for key in SAID]


def too_early(value, interval) -> bool:
    """Whether a number can't be given yet: unknown, or its range wider than
    targets.TOO_WIDE."""
    known = value is not None and bool(interval) and interval[0] is not None
    return not known or targets.width_word(interval) == "too_wide"


def side_sentence(key: str, value, interval) -> str:
    """One side of the result, as the terminal says it: "You passed: your judge also passed
    about 61% (between 42% and 78%)."; too early to tell while its range is too wide."""
    did = DID[key]
    if too_early(value, interval):
        return f"You {did}: {TOO_EARLY}."
    if targets.width_word(interval) == "exact":
        return f"You {did}: your LLM-as-a-judge also {did} {_pct(value)} (exactly)."
    return (f"You {did}: your LLM-as-a-judge also {did} about {_pct(value)} (between "
            f"{_pct(interval[0])} and {_pct(interval[1])}).")


def all_labeled(r: dict) -> bool:
    return r.get("left") == 0


# The page's own flags: how it opens, never how the results are read
_PAGE_FLAGS = re.compile(r" --(?:port \d+|no-browser|wait|yes)(?= |$)")


def mark_command(run: str | None = None) -> str:
    """`judgekeeper mark` for the run that made the marks (`run`, start.Talk.command): its
    path and the flags that change how the results are read (start.REPEATED), never the
    page's own (--port, --no-browser, --wait, --yes). The same in the terminal, on the
    marking page's end card, the result page and report.html."""
    run = _PAGE_FLAGS.sub("", run or program())
    flags = run[len(program()):].strip() if run.startswith(program()) else ""
    if flags == "start" or flags.startswith("start "):  # a result made before 1.0
        flags = flags[len("start"):].strip()
    return " ".join(x for x in (program("mark"), flags) if x)


def all_marked_lines(labels: dict, command: str | None = None) -> list[str]:
    """Every answer is marked, so there is none left to mark: the line that says so (what a
    result needs while a kind is under ROUGH, else that it is still too early to tell), and the
    Next: line. New answers join the marks as a batch (batches.py): `command` (mark_command)
    adds them once the eval ran on more questions."""
    command = command or mark_command()
    short = min(labels["correct"], labels["wrong"]) < ROUGH
    first = ALL_MARKED.format(marks=marks_words(labels)) + (NEEDS_EACH.format(n=ROUGH)
                                                             if short else TOO_FEW_TO_TELL)
    return [first, "Next: " + NEXT_ALL_MARKED.format(command=command)]


def every_marked(ws: Workspace) -> bool:
    """Whether every answer in the pool has a Pass or Fail mark: none is left to mark."""
    try:
        queue = ws.data().get("queue") or []
        counted = marks.read(ws.marks).counted()
    except (OSError, ValueError, AttributeError):
        return False
    return bool(queue) and all(q["id"] in counted for q in queue)


def next_marks(ws: Workspace, step: str) -> str:
    """The next step after Measure, Fix or Check that asks for more marks (`step`, without
    "Next: "), unless every answer in the pool is marked: then all_marked_lines' next step, as
    there is nothing left to mark until the eval runs on more questions. The one place this is
    decided. Its command is made again from the flags result.json keeps, never its text."""
    from judgekeeper.start import command_from

    if not every_marked(ws):
        return step
    try:
        flags = json.loads(ws.result_json.read_text(encoding="utf-8")).get("flags")
    except (OSError, ValueError, AttributeError):
        flags = None
    return NEXT_ALL_MARKED.format(command=mark_command(command_from(flags)))


_plural = plural  # textio.plural


def made_lines(made: dict | None) -> list[str]:
    """How the marks were made (marks.made), and a note when more than a quarter took under a
    second each (more than half: it looks like a program), when lines of marks.jsonl are not
    counted, or when marks came through a page another program could have used (link_lines)."""
    if not made or not made["marks"]:
        return []
    n, quick = made["marks"], made["under_second"]
    line = (f"Your marks: {n} ({made['pass']} Pass, {made['fail']} Fail), made on the page in "
            f"{_plural(made['sittings'], 'sitting', 'sittings')}")
    seconds = made.get("seconds")
    if seconds is not None:
        line += (", under a second each" if seconds == 0
                 else f", about {_plural(seconds, 'second', 'seconds')} each")
    out = [line + "."]
    if quick and quick * 4 > n:
        out.append(f"{quick} of your marks took under a second each. A result is only as good "
                   "as the marks." + (" This looks like a program, not a person."
                                      if quick * 2 > n else ""))
    not_counted = marks.not_counted_line(made.get("not_counted") or 0)
    return out + ([not_counted] if not_counted else []) + link_lines(made) + second_thoughts(made)


def second_thoughts(made: dict | None) -> list[str]:
    """How many marks the person wasn't sure about, and how many they changed after seeing the
    judge's grades (marks.made): the same in the terminal, on the result page and report.html."""
    made = made or {}
    out = []
    if made.get("unsure"):
        out.append(f"You weren't sure about {made['unsure']} of your marks.")
    if made.get("after_result"):
        out.append(f"You changed {_plural(made['after_result'], 'mark', 'marks')} after seeing "
                   "your LLM-as-a-judge's grades.")
    return out


PRINTED_NOTE = ("a link printed in a terminal, so another program on this computer could "
                "have made {them}")
BROWSER_ENV_NOTE = ("a page opened by the program named in BROWSER, so a program could have "
                    "made {them}")
LINK_NOTES = (("printed", PRINTED_NOTE), ("browser_env", BROWSER_ENV_NOTE))  # marks.made's key


def link_lines(made: dict | None) -> list[str]:
    """A note for the marks that came through a link printed where another program could read
    it (no terminal), and one for those made on a page the program named in BROWSER opened:
    what each means. In the terminal and on the result page, once each."""
    out = []
    for key, how in LINK_NOTES:
        n = (made or {}).get(key) or 0
        if n:
            them = "it" if n == 1 else "them"
            out.append(f"{n} of your marks came through {how.format(them=them)}. If you marked "
                       f"{them} yourself, nothing to do.")
    return out


def result_html(r: dict, back: str | None = None, fixing: dict | None = None,
                worse: str | None = None, last: dict | None = None) -> str:
    """The result page; `back`: the link to the marking page while it runs (the page then asks
    why on each disagreement); `fixing`: the mistakes the person can see
    (fix.report_section); `worse`: the next step after a check found the new judge worse
    (check.worse_step), and `last` that check (check.last_check). No value on it holds a
    hidden character (redact.visible)."""
    from judgekeeper.report_page import page

    return visible(page(r, back, fixing, worse, last))


def _fixing(ws: Workspace) -> dict | None:
    """The disagreements, after the hidden marks are set aside (fix.prepare_split): no mistake
    is shown from a mark that a later test hides. Once they are shown, a mark changed later is
    stamped (reasons.saw_grades). The answers' ids stay as they are: the page posts them."""
    from judgekeeper import fix

    fix.prepare_split(ws)
    section = fix.report_section(ws)
    if not section:
        return None
    reasons.saw_grades(ws)
    ids = [m["id"] for m in section["mistakes"]]
    section = _scrubbed(section)
    for m, i in zip(section["mistakes"], ids, strict=True):
        m["id"] = i
    return section


def why_count(ws: Workspace, r: dict) -> int:
    """How many disagreements the result page lists with a reason box, for the result
    `r`: none while it is too early to tell (the page lists none), else the mistakes on
    the marks the person can see (fix.report_section), the hidden marks set aside first."""
    from judgekeeper import fix
    from judgekeeper.report_page import shows_disagreements

    if not shows_disagreements(r):
        return 0
    fix.prepare_split(ws)
    section = fix.report_section(ws)
    return len(section["mistakes"]) if section else 0


def _now(ws: Workspace, r: dict) -> dict:
    """`r` with how the marks were made counted again: reasons added after the result change
    what the pages say, not the result."""
    try:
        ids = {q["id"] for q in ws.data().get("queue") or []}
        return {**r, "made": marks.made(marks.read(ws.marks), ids=ids)}
    except (OSError, ValueError, KeyError, TypeError):
        return r


def _last_check(ws: Workspace, worse: str | None) -> dict | None:
    """The check that found the new judge worse, for the top of report.html (only with its
    next step, `worse`)."""
    from judgekeeper import check

    return _scrubbed(check.last_check(ws)) if worse else None


def write_report(ws: Workspace, worse: str | None = None) -> None:
    """report.html again from the saved result (made again first when it was worked out
    another way: recompute_old); nothing when there is no result yet."""
    if recompute_old(ws, worse=worse):
        return
    try:
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(r, dict):
        write_replacing(ws.report_html, result_html(_scrubbed(_now(ws, r)), fixing=_fixing(ws),
                                                    worse=worse, last=_last_check(ws, worse)))


def live_result(ws: Workspace, session: StartSession, flags: dict | None = None,
                back: str = "/") -> str:
    """The result page the marking page serves at /result: the result from the marks so far,
    with the reason boxes. `flags`: start.run_flags of the run that opened the page."""
    r = store_result(ws, session, flags)
    return result_html(_scrubbed(_now(ws, r)), back, fixing=_fixing(ws))


def page_template(about: dict | None = None, command: str | None = None,
                  held: list[str] | None = None) -> str:
    """The marking page for a check whose start.json is `about`: its judge's model and tool
    are shown in the top bar, its metric above the answer and its rule behind a button (only
    when every answer was graded by the same rule); never a grade. `command`: what the
    person runs to continue; `held`: the values it shows as NAME (start.held_values)."""
    from judgekeeper.front import tool_name
    from judgekeeper.mark_page import label_page

    command = command or program("mark")
    about = about or {}
    rule = about.get("rule") if about.get("one_rule", True) else None
    return label_page(about.get("description") or about.get("app_version"), command,
                      model=(about.get("fingerprint") or {}).get("model"),
                      tool=tool_name(about.get("tool"), about.get("results_files")),
                      held=held, metric=about.get("metric"),
                      rule=rule if isinstance(rule, str) else None)


def picked_numbers(picked: dict, labels: dict, verdicts: dict, pool: dict,
                   batch: dict | None = None, **draws) -> dict:
    """The numbers of marks made before the judge's verdicts changed (a re-check): weighted
    by the strata they were picked from (`picked`: {"pool", "groups"}; `batch`: {id: batch},
    batch 1 when not given) and those strata's sizes, against the new verdicts `verdicts` (of
    every answer in the pool) (weighted.general_strata). The real pass rate comes from the
    marks and their strata; the judge's own pass share from the new pool (`pool`). A mark made
    after the re-check counts in the group of its verdict now. `labels`: the marks of the
    batches that count; with one batch the sizes are `picked`'s pool."""
    from collections import Counter

    batch = batch or {}
    groups = picked.get("groups") or {}
    by = {i: (batch.get(i, 1), groups.get(i, verdicts[i])) for i in labels}
    if set(batch.values()) <= {1}:
        sizes = {(1, g): picked["pool"][g] for g in ("pass", "fail")}
    else:
        n = Counter((batch.get(i, 1), groups.get(i, v)) for i, v in verdicts.items())
        keep = {b for b, _ in by.values()} | {min(batch.values())}
        sizes = {(b, g): n[(b, g)] for b in sorted(keep) for g in ("pass", "fail")}
    rows = [(b, g, size, sum(by[i] == (b, g) for i in labels),
             sum(by[i] == (b, g) and labels[i] == "pass" for i in labels))
            for (b, g), size in sizes.items()]
    out = weighted.stratified(rows, **draws)
    new = weighted.general_strata([(by[i], labels[i], verdicts[i]) for i in labels], sizes,
                                  **draws)
    out.update({k: new[k] for k in ("tpr", "tnr", "kappa", "tpr_interval", "tnr_interval",
                                    "kappa_interval")})
    total = pool["pass"] + pool["fail"]
    out["judge_pass_rate"] = pool["pass"] / total if total else None
    return out


def compute(ws: Workspace, session: StartSession) -> dict:
    """The result from the marks of the batches that count (batches.counting)."""
    data = ws.data()
    groups = {q["id"]: q["group"] for q in data["queue"]}
    labels = batches.counted_labels(data, session.marked())
    disagreements = sum(m != groups[i] for i, m in labels.items())
    if data.get("picked"):  # a re-check: the marks keep the groups they were picked by
        r = describe(picked_numbers(data["picked"], labels, groups, data["pool"],
                                     batches.of(data)))
        r["groups"] = {g: {"pool": data["pool"][g],  # the counts: by the judge's grades now
                           "labeled": sum(groups[i] == g for i in labels),
                           "correct": sum(groups[i] == g and m == "pass"
                                          for i, m in labels.items())}
                       for g in ("pass", "fail")}
    else:
        r = describe(weighted.stratified(batches.counted_strata(data, labels)))
    about = batches.about(data, session.marked())
    if about is not None:
        r["batches"] = about
    r.update(skipped=session.counts()["skipped"], disagreements=disagreements,
             left=sum(1 for item in session.items if not item["label"]),
             made_at=utc_now(), numbers_version=NUMBERS_VERSION,
             judgekeeper_version=__version__, fingerprint=data["fingerprint"],
             judge={"name": data["judge"], "tool": data["tool"], "metric": data["metric"],
                    "rule": data.get("rule"), "one_rule": data.get("one_rule", True),
                    "description": data.get("description"),
                    "results_files": data["results_files"],
                    "results_date": data.get("results_date")})
    if data.get("judge_check"):
        r["judge_check"] = data["judge_check"]
    r["made"] = marks.made(marks.read(ws.marks), ids=set(session.by_id))
    r["smallest_drop"] = targets.smallest_drop(r["labels"]["correct"], r["labels"]["wrong"],
                                               r["tpr"], r["tnr"])
    from judgekeeper import check

    r["picks"] = check.picks_lines(check.picks(ws), r["left"] == 0)  # changes the marks picked
    return r


def marks_digest(ws: Workspace, session: StartSession) -> str:
    """What a result is made from: the marks (answer and label, never a skip) and the judge's
    verdicts."""
    import hashlib

    marks = sorted([i["id"], i["label"]] for i in session.items if i["label"])
    verdicts = ws.pool_judge.read_bytes() if ws.pool_judge.is_file() else b""
    return hashlib.sha256(json.dumps(marks).encode("utf-8") + b"\0" + verdicts).hexdigest()


def _same_result(ws: Workspace, digest: str) -> dict | None:
    """The saved result, when it was made from these same marks, with these numbers."""
    try:
        saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and saved.get("marks_sha256") == digest and \
        saved.get("numbers_version") == NUMBERS_VERSION else None


def recompute_old(ws: Workspace, worse: str | None = None) -> bool:
    """When result.json was worked out another way (NUMBERS_VERSION): the result made again
    from start.json and the marks, with no AI call, the old one copied to history/. Whether it
    was. A result that can't be made again is left as it was saved."""
    try:
        saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(saved, dict) or "labels" not in saved or \
            saved.get("numbers_version") == NUMBERS_VERSION:
        return False
    try:
        store_result(ws, StartSession(ws), saved.get("flags"), worse=worse)
    except (OSError, ValueError, KeyError, TypeError, marks.MarksError):
        return False
    return True


def history_line(ws: Workspace, r: dict) -> dict:
    """The line history.jsonl gets for a new result: the judge as marks.jsonl's header keeps
    it, the counts and the numbers. No answer text, no ids."""
    head = marks.read(ws.marks).header or {}

    def rate(key):
        lo, hi = r.get(f"{key}_interval") or (None, None)
        return {"value": r[key], "low": lo, "high": hi}

    labels = r["labels"]
    line = {"time": r["made_at"], "kind": "result", "judge": head.get("judge"),
            "marks": labels["correct"] + labels["wrong"], "pass": labels["correct"],
            "fail": labels["wrong"], "marks_hash": r["marks_sha256"], "tpr": rate("tpr"),
            "tnr": rate("tnr"), "kappa": r["kappa"], "smallest_drop": r.get("smallest_drop")}
    if r.get("batches"):  # which batches the result is on (batches.about)
        line["batches"] = r["batches"]
    return line


def store_result(ws: Workspace, session: StartSession,
                 flags: dict | None = None, worse: str | None = None,
                 redraw: bool = False) -> dict:
    """Make a result from the marks so far: anchors, result.json and report.html (the last
    result moves to history/; a result.html from before goes), and a line in history.jsonl.
    `flags` (start.run_flags) are kept in it, and the command they make (start.command_from):
    every next command it shows is made again from them.
    With no new marks since the saved result, that result stays as it is, and history.jsonl
    gets no line; `redraw` draws its report.html again. `worse`: the next step after a check
    found the new judge worse (check.worse_step), on report.html."""
    from judgekeeper.start import command_from, saved_flags

    flags = saved_flags(flags)
    digest = marks_digest(ws, session)
    same = _same_result(ws, digest)
    if same is not None:
        if redraw:
            write_report(ws, worse=worse)
        return same
    r = compute(ws, session)
    r["command"] = command_from(flags, kept=True)
    r["flags"] = flags
    r["marks_sha256"] = digest
    anchors = [{"id": i["id"], "input": session.raw[i["id"]].get("input", ""),
                "output": session.raw[i["id"]].get("output", ""), "human_label": i["label"],
                **{k: session.raw[i["id"]][k] for k in AGENT_FIELDS if k in session.raw[i["id"]]}}
               for i in session.items if i["label"]]
    if anchors:
        write_anchor_file(ws.anchors, _scrubbed(anchors))
    # report.html, the history line, then result.json: stopped half way (Ctrl-C), the saved
    # result is the old one, which the next run sees as not made from these marks (repair)
    write_replacing(ws.report_html, result_html(_scrubbed(r), fixing=_fixing(ws), worse=worse,
                                                last=_last_check(ws, worse)))
    if ws.result_html.is_file() and not ws.result_html.is_symlink():
        ws.result_html.unlink()
    _add_history_line(ws, r)
    if ws.result_json.is_file():
        make_private(ws.history)
        try:
            text = ws.result_json.read_text(encoding="utf-8")
            made = json.loads(text).get("made_at")
        except (ValueError, AttributeError, RecursionError):
            made = None
        stamp = re.sub(r"[^0-9A-Za-z-]", "", str(made or "").replace(":", "-"))[:32] \
            or utc_now().replace(":", "-")  # from the file: never a path, never too long
        target = ws.history / f"result-{stamp}.json"
        n = 2
        while target.exists():
            target = ws.history / f"result-{stamp}-{n}.json"
            n += 1
        if os.path.dirname(os.path.abspath(target)) != os.path.abspath(ws.history):
            raise ValueError(f"{target.name} is not a file name in history/")
        write_replacing(target, text)  # a copy: result.json is replaced below in one rename
    _write_json(ws.result_json, r)
    _same_time(ws.report_html, ws.result_json)
    return r


def _same_time(path: Path, as_file: Path) -> None:
    """`path` gets `as_file`'s modified time: a report written with its result is not older."""
    try:
        st = as_file.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        pass


def _has_line(ws: Workspace, digest: str | None) -> bool:
    """Whether history.jsonl holds the line of the result made from marks `digest`."""
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in jsonl_lines(text):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "result" and \
                line.get("marks_hash") == digest:
            return True
    return False


def _add_history_line(ws: Workspace, r: dict) -> None:
    """The result's line in history.jsonl, once: the whole file written again and renamed over
    it, so it is never half written."""
    if _has_line(ws, r.get("marks_sha256")):
        return
    marks._refuse_links(ws.history_jsonl)
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text and not text.endswith("\n"):
        text += "\n"
    write_replacing(ws.history_jsonl, text + marks._line(_scrubbed(history_line(ws, r))),
                    newline="")


def repair(ws: Workspace) -> None:
    """After a run stopped half way through saving a result (judgekeeper before 1.0 wrote
    result.json first): when result.json is newer than report.html, report.html is drawn again,
    and when history.jsonl has no line for it, the line is added."""
    try:
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(r, dict) or "labels" not in r:
        return
    try:
        stale = (not ws.report_html.is_file()
                 or ws.result_json.stat().st_mtime_ns > ws.report_html.stat().st_mtime_ns)
        if stale:
            write_report(ws)
            _same_time(ws.report_html, ws.result_json)
        if r.get("marks_sha256") and ws.marks.is_file():
            _add_history_line(ws, r)
    except (OSError, marks.MarksError):
        pass  # the next result writes them


