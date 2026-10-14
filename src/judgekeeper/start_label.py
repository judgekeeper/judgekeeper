"""Labeling with `judgekeeper start`: the queue, the `.judgekeeper/` folder, the session the
labeling page writes to, and the result.

The queue: a seeded shuffle of each group (the judge's passes and its fails), then blocks of
10, 5 from each group, shuffled inside the block. When one group runs out the rest comes
from the other. The whole pool is queued. The seed is saved, so the queue can be rebuilt.

`.judgekeeper/` in the project holds:
- start.json: the tool, the results files used, the judge and its fingerprint, its pass mark
  (for a judge that gives a score), the pool counts, what was left out, the seed and the
  queue (ids and groups). Written when labeling starts.
- pool.jsonl (id, input, output, in queue order; plus trajectory, outcome and app_version
  when the results have them, never shown on a page) and pool-judge.jsonl (the judge's
  verdict on every pool answer, in the run-file format, each line with the full fingerprint).
  Written when labeling starts.
- marks.jsonl: the person's marks (marks.py), a header written when labeling starts, then
  one stamped line per click, written by the page. No answer text. File names and keys use
  "label", "pass" and "fail". A labels.csv (judgekeeper 0.2, no stamps) is never read.
- anchors.jsonl and its manifest: the labeled answers as a frozen anchor set (with the
  pool's trajectory, outcome and app_version, frozen too). Written with each result.
- judge-check.json and judge-check.csv: did the judge actually judge? (judge_check.py): the
  counts and each answer found, written when labeling starts (and when `start` names the
  CSV). A re-check copies the old ones to history/ with the other start files.
- result.json and report.html (the result page), with the earlier result moved to history/;
  and one line in history.jsonl for each result made from marks that changed: the judge, the
  counts and the numbers, no answer text and no ids.
- review.json, judge-mistakes.csv and rule-unclear.csv: the review of the disagreements
  (start_review.py).
- fix.json and fix/: fixing the judge after the review (start_fix.py).
- .gitignore: written when a first check starts in the folder, if there is none, so the
  answers stay off Git (all but judge.json and history.jsonl). Never overwritten, except the
  exact text judgekeeper 0.2 wrote, which is replaced.
Every string from a results file is scrubbed of credentials before it is written. Nothing is
written anywhere else, and the user's own .gitignore is never touched.

A cloned project controls `.judgekeeper/`. Before anything is written there, a link in it
(or the folder itself being one) stops `start` (`refuse_links`): writing through it would
change a file outside the project. Every file is written as a new file renamed over the old
one (`write_replacing`), which replaces a link instead of following it.
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import secrets
import sys
import webbrowser
from datetime import UTC, date, datetime
from pathlib import Path

from judgekeeper import __version__, find, judge_check, marks, targets, weighted
from judgekeeper.anchors import canonical_hash
from judgekeeper.fingerprint import JudgeFingerprint, rule_hash, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.label import LabelSession, make_server
from judgekeeper.records import AGENT_FIELDS
from judgekeeper.redact import scrub, scrub_fingerprint, scrub_value, visible
from judgekeeper.runners.base import Judgment
from judgekeeper.start_page import label_page, result_page
from judgekeeper.table import guard_cell, write_anchor_file
from judgekeeper.textio import jsonl_lines, link_in, plural, program, write_replacing

FOLDER = ".judgekeeper"
BLOCK = 10
ROUGH = targets.ROUGH
GITIGNORE = ("# judgekeeper's files hold your app's answers. Commit them only if your data "
             "may live here.\n*\n!.gitignore\n!judge.json\n!history.jsonl\n")
OLD_GITIGNORE = ("# judgekeeper's files hold your app's answers. Commit them only if your data "
                 "may live here.\n*\n!.gitignore\n!baseline.json\n!migrations/\n!migrations/*\n")
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
CORRECTED = "Corrected for picking half from the judge's passes and half from its fails."
LEVELS = {  # verdict level: (colour, icon, second line)
    "gate": ("green", "tick", "Keep checking it after changes to its model or rule."),
    "check": ("amber", "warn", None),
    "not_gate": ("red", "cross", None),
    "too_early": ("grey", None, None),
    None: ("grey", None, None),
}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
VERDICTS = {  # the one coloured line under the two sentences (targets.level decides)
    "gate": "Your judge agrees with you often enough to use.",
    "check": "Can't tell yet if your judge is good enough. Marking more answers will tell.",
    "not_gate": "Your judge disagrees with you too often.",
    "too_early": "Too early to tell: mark more answers.",
    None: "Mark a few more answers to see your result.",
}
# Red, by the side whose range stays below the bar
TOO_MANY = {"tnr": "Your judge passes too many answers you would fail.",
            "tpr": "Your judge fails too many answers you would pass."}
MORE = "Marking more answers narrows this."
ASKABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools whose judge can be run again
ALL_LABELED = "Every saved answer is marked. Run your eval again for more answers, then:"
SAID = {"tpr": "Pass", "tnr": "Fail"}  # what the person said, per rate
DID = {"tpr": "passed", "tnr": "failed"}
TOO_EARLY = "too early to tell"
WIDTH_WORDS = {"too_wide": "Not enough marks yet", "rough": "Rough", "sharp": "Sharp"}
# Under a range too wide to give a number, when few of the answers are of that kind
KAPPA_PLAIN = "Kappa on your real mix (agreement beyond coincidence)"
RANGE_MEANS = ("'Could be' means: in judgekeeper's tests, ranges made this way held the true "
               "number about 95 times in 100.")
RANGE_COVERS = ("Ranges cover the coincidence of which answers you marked. They don't cover "
                "your own slips or answers unlike these.")
FEW = ("Few of these answers should {kind}, so it takes more marks to measure how your judge "
       "handles the ones that do.")


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
        self.review = self.dir / "review.json"
        self.judge_mistakes = self.dir / "judge-mistakes.csv"
        self.rule_unclear = self.dir / "rule-unclear.csv"
        self.judge_check_json = self.dir / judge_check.JSON_FILE
        self.judge_check_csv = self.dir / judge_check.CSV_FILE

    def data(self) -> dict:
        return json.loads(self.start.read_text(encoding="utf-8"))


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


def make_folder(ws: Workspace) -> None:
    """Make `ws.dir` (after `refuse_links`), with its .gitignore when a first check starts in
    the project's own folder and it has none. One holding exactly the text 0.2 wrote is
    replaced; any other is left alone."""
    refuse_links(ws)
    ws.dir.mkdir(parents=True, exist_ok=True)
    gitignore = ws.dir / ".gitignore"
    if ws.dir != ws.root / FOLDER:
        return
    if not ws.start.is_file() and not os.path.lexists(gitignore):
        write_replacing(gitignore, GITIGNORE)
    elif gitignore.is_file() and not gitignore.is_symlink():
        try:  # 0.2 wrote it with the system's line endings
            old = gitignore.read_text(encoding="utf-8") == OLD_GITIGNORE
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

    given = found.fingerprint.get("model_source") is not None
    pool, records = [], []
    for q in queue:
        a = answers[q["id"]]
        pool.append({"id": a.id, "input": a.input, "output": a.output, **a.agent})
        fp = a.fingerprint.with_(model=found.fingerprint["model"]) if given else a.fingerprint
        records.append(judgment_to_record(a.id, Judgment(
            verdict=a.verdict, raw_score=a.score, rationale=a.reason), fp))
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
    ready: from the marks in each group, as the result counts them."""
    r = describe(weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f))
    return {"text": status_line(r), "ready": r["check"] != "too_few"}


def start_status(session: StartSession) -> dict:
    """The line under the meters for `start`'s labeling: from the session's labels."""
    counted = session.group_counts()
    return progress_status(session.pool["pass"], session.pool["fail"], *counted["pass"],
                           *counted["fail"])


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
        super().__init__(ws.pool, ws.marks)
        raw = [json.loads(line) for line in jsonl_lines(ws.pool.read_text(encoding="utf-8"))
               if line.strip()]
        self.raw = {r["id"]: r for r in raw}

    def _resume(self) -> None:
        """The marks on disk: the last stamped line of each answer."""
        m = marks.read(self.out)
        self.not_counted = m.not_counted
        for item in self.items:
            line = m.last.get(item["id"]) or {}
            mark = line.get("mark")
            item["label"] = mark if mark in ("pass", "fail") else None
            item["deferred"] = mark == "skip"
            item["note"] = line.get("note") or ""

    def _reread(self) -> None:
        if self.out.is_file():
            try:
                self._resume()
            except OSError:
                pass

    def update(self, body: dict) -> None:
        """Apply one change ({"id", "label"?, "deferred"?, "note"?, "seconds"?}) and add its
        stamped line. The marks on disk are read again first, so marks another page wrote are
        kept."""
        self._reread()
        item = self.by_id[body["id"]]
        before = dict(item)
        try:
            self._apply(item, body)
            mark = item["label"] or ("skip" if item["deferred"] else None)
            line = marks.stamp(item["id"], mark, self.groups.get(item["id"]),
                               body.get("seconds"), self.sitting, note=body.get("note"),
                               link=self.link)
            if not self.out.is_file():
                begin_marks(self.workspace)
            marks.append(self.out, line)
        except BaseException:
            item.update(before)  # memory matches the file on disk
            raise

    def write(self) -> None:
        raise NotImplementedError("marks.jsonl gets one line per change: use update()")

    def counts(self) -> dict:
        labels = [i["label"] for i in self.items]
        return {"correct": labels.count("pass"), "wrong": labels.count("fail"),
                "skipped": sum(i["deferred"] for i in self.items)}

    def group_counts(self) -> dict:
        """{"pass": [marked, marked Pass], "fail": [...]}: the marks in each of the judge's
        groups."""
        counted = {"pass": [0, 0], "fail": [0, 0]}
        for item in self.items:
            if item["label"]:
                g = counted[self.groups[item["id"]]]
                g[0] += 1
                g[1] += item["label"] == "pass"
        return counted

    def summary(self) -> dict:
        counts = self.counts()
        return {"n_items": len(self.items), "n_labeled": counts["correct"] + counts["wrong"],
                "counts": counts, "done": all(i["label"] or i["deferred"] for i in self.items),
                "status": self.status(self)}

    def state(self) -> dict:
        start = next((n for n, i in enumerate(self.items)
                      if not i["label"] and not i["deferred"]), 0)
        items = [{"id": i["id"], "input": question_view(self.raw[i["id"]].get("input")),
                  "output": display(self.raw[i["id"]].get("output")), "label": i["label"],
                  "skipped": i["deferred"]} for i in self.items]
        return {"items": items, "start": start, "counts": self.counts(),
                "status": self.status(self)}


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
    """The verdict's words; when red, the side whose range stays below the bar (of two, the
    one with the lower high end)."""
    if r["verdict_level"] != "not_gate":
        return VERDICTS[r["verdict_level"]]
    below = [k for k in ("tpr", "tnr") if targets.side(r[f"{k}_interval"]) == "no"]
    return TOO_MANY[min(below, key=lambda k: r[f"{k}_interval"][1])]


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
            return [(f"You've marked every answer. A result needs at least {ROUGH} you mark "
                     f"Pass and {ROUGH} you mark Fail; you have {short_words(r['labels'])}. Run "
                     f"your eval on more questions, then {command_of(r, '--label-more')}.")]
        return [f"{VERDICTS[None]} So far: {marks_words(r['labels'])}."]
    return [side_sentence(key, r[key], r[f"{key}_interval"]) for key in SAID]


def too_early(value, interval) -> bool:
    """Whether a number can't be given yet: unknown, or its range wider than
    targets.TOO_WIDE."""
    known = value is not None and bool(interval) and interval[0] is not None
    return not known or targets.width_word(interval) == "too_wide"


def side_sentence(key: str, value, interval) -> str:
    """One side of the result, as the terminal says it: "You passed: your judge also passed
    about 61% (could be 42% to 78%)."; too early to tell while its range is too wide."""
    did = DID[key]
    if too_early(value, interval):
        return f"You {did}: {TOO_EARLY}."
    if targets.width_word(interval) == "exact":
        return f"You {did}: your judge also {did} {_pct(value)} (exactly)."
    return (f"You {did}: your judge also {did} about {_pct(value)} (could be "
            f"{_pct(interval[0])} to {_pct(interval[1])}).")


def statements(r: dict) -> list[dict]:
    """The result's sentences for the page, each with the rate its ring draws to, the number
    the page counts up to and its side ("pass" or "fail"); before a result, the one line."""
    if r["check"] == "too_few":
        return [{"text": sentences(r)[0], "rate": None, "pct": None, "side": None}]
    out = []
    for text, (key, said) in zip(sentences(r), SAID.items(), strict=True):
        value = None if too_early(r[key], r[f"{key}_interval"]) else r[key]
        out.append({"text": text, "rate": value, "pct": None if value is None else _pct(value),
                    "side": said.lower()})
    return out


EXACT_RANGE = "exactly: marking more answers won't change it."


def range_words(interval) -> str | None:
    """"Rough: could be 64% to 97%. Marking more answers narrows this.", or None: the word for
    its width (targets.width_word: "Not enough marks yet", "Rough", none, "Sharp"), then the
    range. A range of no width is exact ("100%, exactly: ..."): a judge that passes (or
    fails) every answer. Ends that round to the same percent are shown with one decimal,
    never one point."""
    if interval is None or interval[0] is None:
        return None
    lo, hi = interval
    word = targets.width_word(interval)
    if word == "exact":
        return f"{_pct(lo)}, {EXACT_RANGE}"
    ends = (f"{lo:.1%} to {hi:.1%}" if _pct(lo) == _pct(hi) else f"{_pct(lo)} to {_pct(hi)}")
    if word in WIDTH_WORDS:
        return f"{WIDTH_WORDS[word]}: could be {ends}. {MORE}"
    return f"Could be {ends}. {MORE}"


def _number(name: str, value, interval) -> str:
    if value is None:
        return f"{name} unknown"
    if interval is None or interval[0] is None:
        return f"{name} {value:.2f}"
    return f"{name} {value:.2f} ({interval[0]:.2f}–{interval[1]:.2f})"


def pass_rate_line(r: dict) -> str:
    if r["judge_pass_rate"] is None:
        return ""
    line = f"Your judge passes {_pct(r['judge_pass_rate'])} of the answers in your results."
    if r["real_pass_rate"] is None:
        return f"{line} How many should pass is unknown yet."
    lo, hi = r["real_pass_rate_interval"]
    return (f"{line} From your marks, about {_pct(r['real_pass_rate'])} should pass "
            f"(could be {_pct(lo)} to {_pct(hi)}).")


def to_review(r: dict) -> int:
    """How many disagreements are left to review: none once the review is done."""
    return 0 if (r.get("review") or {}).get("done") else r.get("disagreements") or 0


def can_fix(r: dict) -> bool:
    """Whether the review is done and found something to fix the judge with."""
    review = r.get("review") or {}
    return bool(review.get("done") and review.get("to_fix"))


def can_ask_again(r: dict) -> bool:
    """Whether judgekeeper can run this judge again: not for verdicts saved by your own code
    or in a table. A result that does not name its tool is offered it."""
    tool = (r.get("judge") or {}).get("tool")
    return tool is None or tool in ASKABLE


def all_labeled(r: dict) -> bool:
    return r.get("left") == 0


def command_of(r: dict, *extra: str) -> str:
    """The command the person runs next: `judgekeeper start` with the path and flags of the
    run that made the result (start.Talk.command, kept in it), then `extra`."""
    return " ".join((r.get("command") or program("start"), *extra))


def _next(r: dict) -> list[tuple[str, str]]:
    steps = []
    if r["check"] != "reliable" and not all_labeled(r):
        steps.append(("Mark more answers:", command_of(r)))
    if to_review(r):
        steps.append((f"See where you disagree ({to_review(r)}):", command_of(r, "--review")))
    if can_fix(r):
        steps.append(("Fix your judge (free):", command_of(r, "--fix")))
    if can_ask_again(r):
        steps.append(("Ask your judge again:", command_of(r, "--ask-again")))
    if r.get("new_judge"):
        steps.append(("Check your new judge from now on:", command_of(r, "--new")))
    return steps + [("Check again after your next eval run:", command_of(r))]


def _again_lines(r: dict) -> list[str]:
    from judgekeeper.again.fresh import again_lines

    return again_lines(r["again"]) if r.get("again") else []


def _new_judge_lines(r: dict) -> list[str]:
    from judgekeeper.new_judge import lines

    return lines(r["new_judge"]) if r.get("new_judge") else []


def _review_lines(r: dict) -> list[str]:
    from judgekeeper.start_review import review_lines

    return review_lines(r["review"]) if r.get("review") else []


def _fix_lines(r: dict) -> list[str]:
    from judgekeeper.start_fix import result_lines as fix_lines

    return fix_lines(r["fix"]) if r.get("fix") else []


def result_lines(r: dict, saved: str = FOLDER) -> list[str]:
    """The result as the terminal shows it."""
    labels = r["labels"]
    n = labels["correct"] + labels["wrong"]
    title = (f"Your result, from the {_plural(n, 'answer', 'answers')} you marked "
             f"({marks_words(labels)}):")
    lines = [title, ""]
    lines += sentences(r)
    if r["check"] != "too_few":
        lines.append(r["verdict"])
    if r.get("wide"):
        lines.append(status_line(r))
    if r["check"] != "too_few":
        lines.append("")
        lines.append("  " + "   ".join([_number("TPR", r["tpr"], r["tpr_interval"]),
                                        _number("TNR", r["tnr"], r["tnr_interval"]),
                                        _number("kappa", r["kappa"],
                                                r.get("kappa_interval"))]))
        if pass_rate_line(r):
            lines.append(f"  {pass_rate_line(r)}")
        lines.append(f"  {CORRECTED}")
    if r.get("review"):
        lines += [""] + [f"  {line}" for line in _review_lines(r)]
    if r.get("fix"):
        lines += ["", "  Fix your judge:"] + [f"  {line}" for line in _fix_lines(r)]
    if r.get("again"):
        lines += ["", "  Your judge, asked again:"] + [f"  {line}" for line in _again_lines(r)]
    if r.get("new_judge"):
        lines += ["", "  Your new judge:"] + [f"  {line}" for line in _new_judge_lines(r)]
    lines += ["", "Next:"]
    lines += [f"  {text}  {command}" for text, command in _next(r)]
    lines += ["", f"Saved in {saved}/ (report.html is the page you just saw)."]
    return lines


_plural = plural  # textio.plural


def in_words(day: str) -> str:
    """"2026-10-05" as "5 October 2026"; anything else as it is."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _made_on(made_at: str | None) -> str | None:
    """The local date a result was made (`made_at` is UTC), in words."""
    try:
        made = datetime.strptime(made_at or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return in_words(f"{made.astimezone():%Y-%m-%d}")


def _detail(r: dict) -> str | None:
    """The coloured line's second line (a bad result names its weaker side in the first)."""
    return LEVELS[r["verdict_level"]][2]


def still_needed(r: dict) -> str | None:
    """Why marking more answers helps, while the result is not reliable: the range that is
    still wide (status_line), else that more marks narrow the ranges; None once reliable."""
    if r["check"] == "reliable" or not r.get("wide") and _all_exact(r):
        return None
    if r.get("wide"):
        return status_line(r)
    return "Marking more answers narrows the ranges."


def _pass_rate(r: dict) -> list[tuple[str, bool]] | None:
    """The pass-rate line as (text, bold) parts."""
    if r["judge_pass_rate"] is None:
        return None
    parts = [("Your judge passes ", False), (_pct(r["judge_pass_rate"]), True),
             (" of the answers in your results.", False)]
    if r["real_pass_rate"] is None:
        return parts + [(" How many should pass is unknown yet.", False)]
    lo, hi = r["real_pass_rate_interval"]
    return parts + [(" From your marks, about ", False), (_pct(r["real_pass_rate"]), True),
                    (f" should pass (could be {_pct(lo)} to {_pct(hi)}).", False)]


def made_lines(made: dict | None) -> list[str]:
    """How the marks were made (marks.made), and a note when more than a quarter took under a
    second each, when lines of marks.jsonl are not counted, or when marks were made through a
    link printed where another program could read it (no terminal)."""
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
                   "as the marks.")
    not_counted = marks.not_counted_line(made.get("not_counted") or 0)
    printed = made.get("printed") or 0
    return out + ([not_counted] if not_counted else []) + (
        [(f"{printed} of your marks were made through a link printed where another program "
          "could read it.")]
        if printed else [])


def page_content(r: dict, marking: str | None = None) -> dict:
    """The result page's text and numbers (start_page.result_page lays them out). `marking`:
    for the page `judgekeeper mark` serves, its command; the one next step is marking more."""
    labels = r["labels"]
    n = labels["correct"] + labels["wrong"]
    kind = [f"From the {_plural(n, 'answer', 'answers')} you marked: {marks_words(labels)}"
            + (f", {r['skipped']} skipped" if r.get("skipped") else "")]
    if _made_on(r.get("made_at")):
        kind.append(_made_on(r.get("made_at")))

    too_few = r["check"] == "too_few"

    def tile(name, plain, value, interval, count, as_pct=True):
        if too_few:
            return {"name": name, "plain": plain, "value": "–", "interval": None,
                    "mark": None, "line": count}
        known = value is not None
        span = known and interval is not None and interval[0] is not None
        shown = (_pct(value) if as_pct else f"{value:.2f}") if known else "unknown"
        return {"name": name, "plain": plain, "value": shown,
                "interval": (interval[0], interval[1]) if span else None,
                "mark": value if known else None,
                "line": range_words(interval) if span else count}

    def few(shown: dict, key: str) -> dict:
        """Under a range too wide to give a number: why, when few answers are of that kind
        (the wide side is Fail and most answers should pass, or the other way round)."""
        real = r.get("real_pass_rate")
        if too_few or real is None or targets.width_word(r[f"{key}_interval"]) != "too_wide":
            return shown
        if (key == "tnr" and real > 0.5) or (key == "tpr" and real < 0.5):
            kind = "fail" if key == "tnr" else "pass"
            shown["line"] = f"{shown['line']} {FEW.format(kind=kind)}"
        return shown

    def kappa_tile(shown: dict) -> dict:
        """Kappa's tile: its range in words (it has no bar: it moves with how many answers
        pass, so it is no target)."""
        lo, hi = r.get("kappa_interval") or (None, None)
        if not too_few and r["kappa"] is not None and lo is not None:
            shown["line"] = f"could be {lo:.2f} to {hi:.2f}, from {n} answers"
        return shown

    colour, icon, _ = LEVELS[r["verdict_level"]]
    judge = r.get("judge") or {}
    fingerprint = r.get("fingerprint") or {}
    model = fingerprint.get("model") or "model not named in the results"
    if fingerprint.get("model_source"):
        model += " (as you told me)"
    source = None
    if judge.get("results_files"):
        tool = find.NAMES.get(judge.get("tool"), judge.get("tool"))
        source = f"From {', '.join(judge['results_files'])}" + (f" ({tool})" if tool else "")
        saved = judge.get("results_date")  # "2026-10-05 05:30"
        if saved:
            source += f", saved {in_words(saved[:10])}{saved[10:].replace(' ', ', ', 1)}"
    steps = []
    needed = still_needed(r)
    if needed and all_labeled(r):
        steps.append({"title": "Mark more answers", "text": ALL_LABELED,
                      "command": command_of(r), "link": None, "button": None})
    elif needed:
        steps.append({"title": "Mark more answers", "text": needed,
                      "command": command_of(r), "link": "/", "button": "Mark more answers"})
    if to_review(r):
        steps.append({"title": f"See where you disagree ({to_review(r)})",
                      "text": ("Each answer where you and your judge disagree, with its "
                               "reason. Free."),
                      "command": command_of(r, "--review"), "link": "/review",
                      "button": "See where you disagree"})
    if can_fix(r):
        steps.append({"title": "Fix your judge",
                      "text": ("See what your judge gets wrong, and test a change on answers "
                               "kept aside. Free."),
                      "command": command_of(r, "--fix"), "link": "/fix",
                      "button": "Fix your judge"})
    if can_ask_again(r):
        steps.append({"title": "Ask your judge again",
                      "text": ("How often it changes its mind, and how well it agrees with "
                               "you today. It asks before any call:"),
                      "command": command_of(r, "--ask-again"), "link": None,
                      "button": None})
    if r.get("new_judge"):
        steps.append({"title": "Check your new judge from now on",
                      "text": ("Your last check moves to .judgekeeper/previous-<date>/; nothing "
                               "is deleted:"),
                      "command": command_of(r, "--new"), "link": None, "button": None})
    if not (needed and all_labeled(r)):  # else the first step already says it
        steps.append({"title": "Check again after your next eval run", "text": "",
                      "command": command_of(r), "link": None, "button": None})
    if marking:
        steps = [{"title": "Mark more answers", "text": ALL_LABELED, "command": marking,
                  "link": None, "button": None} if all_labeled(r) else
                 {"title": "Mark more answers", "text": needed or "Marking more answers "
                  "narrows the ranges.", "command": marking, "link": "/",
                  "button": "Mark more answers"}]
    review = None
    if r.get("review"):
        review = {"title": "Where you disagree", "lines": _review_lines(r),
                  "files": [f"{FOLDER}/{name}" for name in r["review"].get("files", [])]}
    fixed = None
    if r.get("fix"):
        fixed = {"title": "Fix your judge", "lines": _fix_lines(r), "files": [f"{FOLDER}/fix/"]}
    asked_again = None
    if r.get("again"):
        asked_again = {"title": "Your judge, asked again", "lines": _again_lines(r),
                       "files": [r["again"]["folder"] + "/"]}
    new_judge = None
    if r.get("new_judge"):
        files = [r["new_judge"]["folder"] + "/"]
        new_judge = {"title": "Your new judge", "lines": [x for x in _new_judge_lines(r) if x],
                     "files": files}
    checked = r.get("judge_check")
    judged = None
    if judge_check.lines(checked):
        judged = {"title": judge_check.TITLE, "lines": judge_check.page_lines(checked)
                  + ([judge_check.LIST_LINE] if judge_check.has_rows(checked) else []),
                  "files": []}
    return {
        "kind": " · ".join(kind),
        "sentences": sentences(r),
        "statements": statements(r),
        "verdict": {"colour": colour, "icon": icon, "text": r["verdict"], "detail": _detail(r)},
        "made": made_lines(r.get("made")),
        "drop": targets.drop_line(r.get("smallest_drop")),
        "drop_model": targets.DROP_MODEL if r.get("smallest_drop") is not None else None,
        "tiles": [few(tile("TPR", "When you said Pass", r["tpr"], r["tpr_interval"],
                           f"{labels['correct']} marked Pass so far"), "tpr"),
                  few(tile("TNR", "When you said Fail", r["tnr"], r["tnr_interval"],
                           f"{labels['wrong']} marked Fail so far"), "tnr"),
                  kappa_tile(tile("kappa", KAPPA_PLAIN, r["kappa"], None,
                                  f"from {n} answers", as_pct=False))],
        "pass_rate": None if too_few else _pass_rate(r),
        "corrected": None if too_few else (
            "judgekeeper showed you half of your judge's passes and half of its fails, and "
            "corrects the numbers for that. The bar under each number is the range it could "
            f"be in. {RANGE_MEANS} {RANGE_COVERS}"),
        "judge": {"name": judge.get("metric") or judge.get("name"), "model": model,
                  "rule": judge.get("rule"), "source": source},
        "review": review,
        "fix": fixed,
        "again": asked_again,
        "new_judge": new_judge,
        "judge_check": judged,
        "judge_check_quiet": judge_check.EVERY_ANSWER if checked and not judged else None,
        "next": steps,
        "folder": f"{FOLDER}/",
    }


def result_html(r: dict, back: str | None = None, marking: str | None = None,
                history: list[dict] | None = None, fixing: dict | None = None) -> str:
    """The result page; `history`: the History rows of report.html (check.report_rows);
    `fixing`: its Fix section (fix.report_section). No value on it holds a hidden character
    (redact.visible)."""
    return visible(result_page({**page_content(r, marking), "history": history or [],
                                "fixing": fixing}, back))


def _fixing(ws: Workspace) -> dict | None:
    """The Fix section, after the hidden marks are set aside (fix.prepare_split): no mistake
    is shown from a mark that a later test hides."""
    from judgekeeper import fix

    fix.prepare_split(ws)
    section = fix.report_section(ws)
    return _scrubbed(section) if section else None


def write_report(ws: Workspace) -> None:
    """report.html again from the saved result, with the checks so far in its History; nothing
    when there is no result yet."""
    from judgekeeper import check

    try:
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(r, dict):
        write_replacing(ws.report_html, result_html(_scrubbed(r),
                                                    history=_scrubbed(check.report_rows(ws)),
                                                    fixing=_fixing(ws)))


def page_template(about: dict | None = None, command: str | None = None) -> str:
    """The labeling page for a check whose start.json is `about`: its description and its
    judge's rule are shown; nothing else from it is. `command`: what the person runs to
    continue."""
    command = command or program("start")
    about = about or {}
    return label_page(about.get("description") or about.get("app_version"), about.get("rule"),
                      command)


def picked_numbers(picked: dict, labels: dict, verdicts: dict, pool: dict, **draws) -> dict:
    """The numbers of marks made before the judge's verdicts changed (a re-check): weighted
    by the groups they were picked from and that pool's sizes (`picked`: {"pool", "groups"}),
    against the new verdicts (weighted.general). The real pass rate comes from the marks and
    their pick groups; the judge's own pass share from the new pool (`pool`). A mark made
    after the re-check counts in the group of its verdict now."""
    by = {i: picked["groups"].get(i, verdicts[i]) for i in labels}
    counts = {g: [sum(by[i] == g for i in labels),
                  sum(by[i] == g and labels[i] == "pass" for i in labels)]
              for g in ("pass", "fail")}
    p = picked["pool"]
    out = weighted.corrected(p["pass"], p["fail"], *counts["pass"], *counts["fail"], **draws)
    new = weighted.general([(by[i], labels[i], verdicts[i]) for i in labels], p["pass"],
                           p["fail"], **draws)
    out.update({k: new[k] for k in ("tpr", "tnr", "kappa", "tpr_interval", "tnr_interval",
                                    "kappa_interval")})
    total = pool["pass"] + pool["fail"]
    out["judge_pass_rate"] = pool["pass"] / total if total else None
    return out


def compute(ws: Workspace, session: StartSession) -> dict:
    data = ws.data()
    groups = {q["id"]: q["group"] for q in data["queue"]}
    counted = session.group_counts()
    disagreements = sum(item["label"] != groups[item["id"]] for item in session.items
                        if item["label"])
    if data.get("picked"):  # a re-check: the marks keep the groups they were picked by
        labels = {i["id"]: i["label"] for i in session.items if i["label"]}
        r = describe(picked_numbers(data["picked"], labels, groups, data["pool"]))
    else:
        r = describe(weighted.corrected(data["pool"]["pass"], data["pool"]["fail"],
                                        *counted["pass"], *counted["fail"]))
    r.update(skipped=session.counts()["skipped"], disagreements=disagreements,
             left=sum(1 for item in session.items if not item["label"]),
             made_at=utc_now(),
             judgekeeper_version=__version__, fingerprint=data["fingerprint"],
             judge={"name": data["judge"], "tool": data["tool"], "metric": data["metric"],
                    "rule": data.get("rule"), "description": data.get("description"),
                    "results_files": data["results_files"],
                    "results_date": data.get("results_date")})
    if data.get("judge_check"):
        r["judge_check"] = data["judge_check"]
    r["made"] = marks.made(marks.read(ws.marks), ids=set(session.by_id))
    r["smallest_drop"] = targets.smallest_drop(r["labels"]["correct"], r["labels"]["wrong"],
                                               r["tpr"], r["tnr"])
    return r


def marks_digest(ws: Workspace, session: StartSession) -> str:
    """What a result is made from: the marks (answer and label, never a skip) and the judge's
    verdicts."""
    import hashlib

    marks = sorted([i["id"], i["label"]] for i in session.items if i["label"])
    verdicts = ws.pool_judge.read_bytes() if ws.pool_judge.is_file() else b""
    return hashlib.sha256(json.dumps(marks).encode("utf-8") + b"\0" + verdicts).hexdigest()


def _same_result(ws: Workspace, digest: str) -> dict | None:
    """The saved result, when it was made from these same marks."""
    try:
        saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) and saved.get("marks_sha256") == digest else None


def save_result(ws: Workspace, session: StartSession, say,
                command: str | None = None) -> dict:
    """store_result, then say the result in the terminal."""
    command = command or program("start")
    r = store_result(ws, session, command)
    say("")
    for line in result_lines(r, shown_folder(ws)):
        say(line)
    return r


def history_line(ws: Workspace, r: dict) -> dict:
    """The line history.jsonl gets for a new result: the judge as marks.jsonl's header keeps
    it, the counts and the numbers. No answer text, no ids."""
    head = marks.read(ws.marks).header or {}

    def rate(key):
        lo, hi = r.get(f"{key}_interval") or (None, None)
        return {"value": r[key], "low": lo, "high": hi}

    labels = r["labels"]
    return {"time": r["made_at"], "kind": "result", "judge": head.get("judge"),
            "marks": labels["correct"] + labels["wrong"], "pass": labels["correct"],
            "fail": labels["wrong"], "marks_hash": r["marks_sha256"], "tpr": rate("tpr"),
            "tnr": rate("tnr"), "kappa": r["kappa"], "smallest_drop": r.get("smallest_drop")}


def store_result(ws: Workspace, session: StartSession,
                 command: str | None = None) -> dict:
    """Make a result from the marks so far: anchors, result.json and report.html (the last
    result moves to history/; a result.html from before goes), and a line in history.jsonl.
    `command` (start.Talk.command) is kept in it: every next command it shows starts with it.
    With no new marks since the saved result, that result stays as it is (with its review,
    fix and asking again), and history.jsonl gets no line: a new one would move the finished
    review and fix to history/."""
    command = command or program("start")
    digest = marks_digest(ws, session)
    same = _same_result(ws, digest)
    if same is not None:
        return same
    r = compute(ws, session)
    r["command"] = command
    r["marks_sha256"] = digest
    anchors = [{"id": i["id"], "input": session.raw[i["id"]].get("input", ""),
                "output": session.raw[i["id"]].get("output", ""), "human_label": i["label"],
                **{k: session.raw[i["id"]][k] for k in AGENT_FIELDS if k in session.raw[i["id"]]}}
               for i in session.items if i["label"]]
    if anchors:
        write_anchor_file(ws.anchors, _scrubbed(anchors))
    if ws.result_json.is_file():
        ws.history.mkdir(exist_ok=True)
        try:
            made = json.loads(ws.result_json.read_text(encoding="utf-8")).get("made_at")
        except ValueError:
            made = None
        stamp = (made or utc_now()).replace(":", "-")
        target = ws.history / f"result-{stamp}.json"
        n = 2
        while target.exists():
            target = ws.history / f"result-{stamp}-{n}.json"
            n += 1
        ws.result_json.replace(target)
    _write_json(ws.result_json, r)
    from judgekeeper import check

    write_replacing(ws.report_html, result_html(_scrubbed(r),
                                                history=_scrubbed(check.report_rows(ws)),
                                                fixing=_fixing(ws)))
    if ws.result_html.is_file() and not ws.result_html.is_symlink():
        ws.result_html.unlink()
    marks.append(ws.history_jsonl, _scrubbed(history_line(ws, r)))
    return r


def result_maker(ws: Workspace, say, made: list | None = None,
                 command: str | None = None):
    """The server's result function: each call makes and saves a new result."""
    command = command or program("start")

    def make(session: StartSession, back: str) -> str:
        r = save_result(ws, session, say, command)
        done = session.summary()["done"]
        if made is not None:
            made.append(done)
        return result_html(_scrubbed(r), None if done else back)

    return make


def run_labeling(found, port: int, open_browser: bool, say,
                 command: str | None = None) -> int:
    """Save the pool of `found`, then serve the labeling page for it."""
    command = command or program("start")
    return serve_workspace(prepare(found, say), port, open_browser, say, command)


def say_opened(url: str, open_browser: bool, say, command: str | None = None,
               more: str = "", session=None) -> None:
    """What the terminal says once a page is served: that it opened (or its link), that every
    click is saved, and how to stop and come back. `more` is added to the come-back command
    (--review, say). The link holds the token, so it is printed whole, and only where a
    coding agent can't read it, or when no browser opened: without a terminal that is said,
    and the marks on `session` are stamped (page.py)."""
    command = command or program("start")
    from judgekeeper.page import NO_BROWSER
    from judgekeeper.page import terminal as at_terminal
    from judgekeeper.textio import tick

    terminal = at_terminal()
    if open_browser and webbrowser.open(url) is not False:
        say(f"{tick()} Opened in your browser. Every click is saved.")
        if terminal:
            print(f"  If it did not open, use this link: {url}")
    else:
        if not terminal:
            say(NO_BROWSER)
            if session is not None and hasattr(session, "link"):
                session.link = marks.PRINTED
        print(f"Open this link in your browser: {url}")
        say("Every click is saved.")
    say(f"  To stop: Ctrl-C. To carry on later: {command}{more}")
    sys.stdout.flush()


def serve_workspace(ws: Workspace, port: int, open_browser: bool, say,
                    command: str | None = None) -> int:
    """Serve the labeling page until the last answer, Ctrl-C or 30 minutes idle. `command`
    (start.Talk.command) is what the person runs to continue."""
    command = command or program("start")
    from judgekeeper import start_fix, start_review

    session = StartSession(ws)
    made: list[bool] = []
    reviewed: list[bool] = []
    server = make_server(session, port, result=result_maker(ws, say, made, command),
                         page=page_template(ws.data(), command),
                         switches={"/review": start_review.switch(ws, say, reviewed),
                                   "/fix": start_fix.switch(ws, say, command)}, lock=ws.dir)
    say_opened(server.url, open_browser, say, command, session=session)
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    summary = session.summary()
    if summary["done"] and not any(made):
        save_result(ws, session, say, command)  # nobody fetched the last result: make it
    elif not summary["done"]:
        say("")
        say(f"Stopped. You marked {_plural(summary['n_labeled'], 'answer', 'answers')}. To "
            f"carry on later: {command}")
    if reviewed:
        start_review.finish(ws, say, command)
    return 0
