"""Answers with no grade: a results file with a question and an answer column and no grade
column (find.is_answers_table). The person marks each answer Pass or Fail on the usual marking
page. From MIN_MARKS marks the result says how many they passed and the pass rate with its
plain Wilson range on the marked answers (metrics.wilson): the answers are a sample of what
people will ask, so there is a range even with every answer marked. On the answers they
failed they can give reasons (the buttons about the answer only, `offered`); the result counts
them. There is no LLM-as-a-judge, so no TPR, TNR or kappa, nothing kept aside, no `fix`.

The marks are the usual ones in .judgekeeper/ (start.json says "graded": false), so a grade
column added later is checked against them by the normal steps with no marking again
(to_graded)."""

from __future__ import annotations

import json
import os
import random
import re
import secrets
from pathlib import Path

from judgekeeper import __version__, marks, reasons
from judgekeeper.anchors import canonical_hash
from judgekeeper.fingerprint import utc_now
from judgekeeper.metrics import wilson
from judgekeeper.redact import scrub_fingerprint
from judgekeeper.textio import loads, make_private, plural, write_replacing

MIN_MARKS = 10  # marks for a first result
COUNTS = "You passed {k} of {n}."  # the headline, the pop-up and the terminal
REASONS_LINE = "Your reasons: {said}."
# every answer marked, fewer than MIN_MARKS: the terminal's and the end card's Next line
MORE_ANSWERS = "add more answers to {file} (at least {n} in all), then run `{command}` again."


NO_JUDGE = "Your answers have no grades, so there is no LLM-as-a-judge to {what}."
NO_JUDGE_NEXT = ("add your LLM-as-a-judge's grades to {file} as a verdict column (pass or fail), "
                 "then run `{command}`. Your marks are kept.")


def no_judge_stop(path, what: str) -> tuple[str, str] | None:
    """For `check` ("re-check") and `fix` ("fix") in a project whose marks are on answers with
    no grade: what they say, and the Next step. None anywhere else."""
    from judgekeeper.project import project_of
    from judgekeeper.start_label import Workspace
    from judgekeeper.textio import program

    given = Path(path)
    if not given.exists():
        return None
    ws = Workspace(project_of(given))
    if not here(ws):
        return None
    files = ws.cached_data().get("results_files") or []
    file = files[0] if files and isinstance(files[0], str) else "your results file"
    return NO_JUDGE.format(what=what), NO_JUDGE_NEXT.format(file=file, command=program())


def is_off(data: dict | None) -> bool:
    """Whether start.json `data` is for answers with no grade."""
    return isinstance(data, dict) and data.get("graded") is False


def here(ws) -> bool:
    """Whether the marks in `ws` are on answers with no grade."""
    try:
        return ws.start.is_file() and is_off(ws.cached_data())
    except (OSError, ValueError, AttributeError):
        return False


def offered() -> list[str]:
    """The reasons asked on an answer the person failed, with no LLM-as-a-judge: those about
    the answer and "not sure about my own mark", never one about an LLM-as-a-judge or its rule
    (reasons.REASONS, in order). The person's own buttons and "Other…" come after them."""
    return [k for k in reasons.offered("pass") if k != "rule_silent"]


# The numbers --------------------------------------------------------------------------------

def numbers(k: int, n: int) -> dict:
    """The pass rate of `k` Pass marks in `n`, with its 95% Wilson range; none under
    MIN_MARKS ("check": "too_few")."""
    if n < MIN_MARKS:
        return {"check": "too_few", "pass_rate": None, "pass_rate_interval": None}
    w = wilson(k, n)
    return {"check": "result", "pass_rate": w["p"], "pass_rate_interval": [w["lo"], w["hi"]]}


def counts_line(k: int, n: int) -> str:
    return COUNTS.format(k=k, n=plural(n, "answer"))


def rate_words(r: dict) -> str | None:
    """"about 60%, between 31% and 83%", as the result page's estimates are written
    (report_page.estimate); None before a result."""
    from judgekeeper.report_page import estimate

    if r.get("pass_rate") is None:
        return None
    shown, between = estimate(r["pass_rate"], r["pass_rate_interval"])
    return shown if between == "–" else f"{shown}, between {between}"


# Reasons ----------------------------------------------------------------------------------

def reason_rows(ws, session) -> list[dict]:
    """A row (reasons.tally's) per answer the person failed, in the page's order: "id",
    "reasons" (the buttons tapped, an own button too when its words are in the "Other…" box)
    and "words" (an own button's words)."""
    m = marks.read(ws.marks) if ws.marks.is_file() else None
    own = {c["id"]: c for c in reasons.own_chips(ws)}
    rows = []
    for item in session.items:
        if item["label"] != "fail":
            continue
        why = reasons.of_line(m.last.get(item["id"]) if m else None)
        taps = list(why["reasons"]) + [
            c["id"] for c in own.values() if why["note"] and c["id"] not in why["reasons"]
            and (c.get("from") == item["id"] or reasons.same_words(c["text"], why["note"]))]
        taps = [k for k in taps if k in reasons.REASONS or k in own]
        rows.append({"id": item["id"], "reasons": taps,
                     "words": {k: own[k]["text"] for k in taps if k in own}})
    return rows


def _said(row_words: dict, key: str) -> str:
    """A reason as the line says it: a button's words as they are on it; the person's own in
    quotes."""
    if key in reasons.REASONS:
        return reasons.REASONS[key][0]
    return f"“{row_words.get(key, key)}”"


def tally(rows: list[dict]) -> list[tuple[str, str, int]]:
    """(id, words, count) of each reason given (reasons.tally: "not sure" is not one), the
    most common first."""
    counts = reasons.tally(rows)
    words: dict[str, str] = {}
    for r in rows:
        for k in r.get("reasons") or []:
            words.setdefault(k, _said(r.get("words") or {}, k))
    return [(k, words[k], counts[k]) for k in reasons._order(counts)]


def reasons_line(rows: list[dict]) -> str | None:
    """"Your reasons: It has a wrong fact (3), It leaves out something important (2)."; None
    when no reason was given."""
    said = tally(rows)
    if not said:
        return None
    return REASONS_LINE.format(said=", ".join(f"{w} ({n})" for _, w, n in said))


def fail_order(rows: list[dict]) -> list[str]:
    """The ids of the answers the person failed, by reason: those whose most common reason is
    the most common one first, answers with no reason (or only "not sure") last; otherwise in
    the page's order."""
    counts = reasons.tally(rows)
    rank = {k: n for n, k in enumerate(reasons._order(counts))}

    def key(pair):
        n, row = pair
        mine = [k for k in row.get("reasons") or [] if k in rank]
        if not mine:
            return (1, 0, n)
        return (0, min(rank[k] for k in mine), n)

    return [row["id"] for _, row in sorted(enumerate(rows), key=key)]


def check_reason(ws, item_id: str, mark: str | None, body: dict, before: dict | None) -> dict:
    """reasons.check with no LLM-as-a-judge: only on an answer the person failed, once there
    is a result (MIN_MARKS marks), and only the reasons `offered` and the person's own."""
    if mark not in ("pass", "fail"):
        raise ValueError("mark this answer Pass or Fail first")
    if mark != "fail" or not _result_shown(ws):
        raise ValueError(reasons.NOT_LISTED)
    saved = reasons.of_line(before)
    body = {"reasons": saved["reasons"], "note": saved["note"], **body}
    if body.get("rule_parts") or body.get("spans"):
        raise ValueError("with no LLM-as-a-judge, a reason is a button or your own words")
    got = body.get("reasons", [])
    if not isinstance(got, list) or not all(isinstance(r, str) for r in got) or \
            len(set(got)) != len(got):
        raise ValueError("reasons must be a list of reason ids, each once")
    own = {c["id"] for c in reasons.own_chips(ws)}
    unknown = [r for r in got if r not in reasons.REASONS and r not in own]
    if unknown:
        raise ValueError(f"unknown reason: {unknown[0]}")
    other = [r for r in got if r in reasons.REASONS and r not in offered()]
    if other:
        raise ValueError(f"reason {other[0]} is not asked on this answer")
    out: dict = {"reasons": list(got)}
    note = body.get("note")
    if note is not None:
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        if len(note) > reasons.MAX_NOTE:
            raise ValueError(f"a reason can be at most {reasons.MAX_NOTE} characters")
        if note.strip():
            from judgekeeper.redact import scrub

            out["note"] = scrub(note.strip())
    return out


def _result_shown(ws) -> bool:
    try:
        r = loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(r, dict) and r.get("graded") is False and r.get("check") == "result"


# The result -------------------------------------------------------------------------------

NUMBERS_VERSION = 1


def compute(ws, session) -> dict:
    """The result from the marks: the counts, the pass rate with its range from MIN_MARKS
    marks, the answers failed (fail_order) and the reasons given (tally)."""
    from judgekeeper.start_label import NUMBERS_VERSION as SAME_VERSION

    data = ws.data()
    marked = session.marked()
    k = sum(m == "pass" for m in marked.values())
    n = len(marked)
    rows = reason_rows(ws, session)
    r = numbers(k, n)
    m = marks.read(ws.marks) if ws.marks.is_file() else None
    r.update(graded=False, labels={"correct": k, "wrong": n - k},
             fails=fail_order(rows), reasons=[[w, c] for _, w, c in tally(rows)],
             skipped=session.counts()["skipped"],
             left=sum(1 for item in session.items if not item["label"]),
             made_at=utc_now(), numbers_version=SAME_VERSION,
             judgekeeper_version=__version__, fingerprint=data.get("fingerprint"),
             judge={"name": None, "tool": data.get("tool"), "metric": None,
                    "results_files": data.get("results_files") or [],
                    "results_date": data.get("results_date")},
             made=marks.made(m, ids=set(session.by_id)) if m else None)
    return r


def digest(ws, session) -> str:
    """What a result is made from: the marks and the reasons on the answers failed."""
    import hashlib

    marked = sorted(session.marked().items())
    rows = [[r["id"], r["reasons"], sorted(r["words"].items())]
            for r in reason_rows(ws, session)]
    return hashlib.sha256(json.dumps([marked, rows]).encode("utf-8")).hexdigest()


def store(ws, session, flags: dict | None = None) -> dict:
    """The result from the marks so far, saved in result.json (the last one copied to
    history/); the same result when nothing changed since."""
    from judgekeeper.start import kept_command, saved_flags
    from judgekeeper.start_label import _scrubbed, _write_json

    d = digest(ws, session)
    try:
        saved = loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    if isinstance(saved, dict) and saved.get("marks_sha256") == d and saved.get("graded") is False:
        return saved
    r = compute(ws, session)
    flags = saved_flags(flags)
    r.update(command=kept_command(flags), flags=flags, marks_sha256=d)
    if isinstance(saved, dict):  # the last result: kept in history/
        make_private(ws.history)
        stamp = re.sub(r"[^0-9A-Za-z-]", "", str(saved.get("made_at") or "").replace(":", "-"))
        stamp = stamp[:32] or utc_now().replace(":", "-")
        target = ws.history / f"result-{stamp}.json"
        n = 2
        while target.exists():
            target = ws.history / f"result-{stamp}-{n}.json"
            n += 1
        if os.path.dirname(os.path.abspath(target)) == os.path.abspath(ws.history):
            write_replacing(target, ws.result_json.read_text(encoding="utf-8"))
    _write_json(ws.result_json, _scrubbed(r))
    return r


def status(session, run: str | None = None) -> dict:
    """The marking page's status (start_label.start_status): before MIN_MARKS marks the usual
    line; from them the result is ready, its headline the counts. With every answer marked and
    no result yet, what the end card says."""
    from judgekeeper.start_label import ALL_MARKED, EVERY_MARKED, READY, VERDICTS, marks_words

    marked = session.marked()
    n, k = len(marked), sum(m == "pass" for m in marked.values())
    every = bool(session.items) and all(i["label"] for i in session.items)
    if n < MIN_MARKS:
        out = {"text": VERDICTS[None], "first": False, "ready": False, "headline": None}
        if every:
            counts = session.counts()
            labels = {"correct": counts["correct"], "wrong": counts["wrong"]}
            done = [f"{ALL_MARKED.format(marks=marks_words(labels))} {VERDICTS[None]}",
                    "Next: " + more_answers(session.workspace, run)]
            out.update(text=done[0], done=done)
        return out
    return {"text": EVERY_MARKED if every else READY, "first": True, "ready": True,
            "headline": counts_line(k, n)}


def results_file(ws) -> str:
    """The results file the marks are on, named from here (textio.line_path)."""
    from judgekeeper.start import results_path
    from judgekeeper.textio import line_path

    data = ws.cached_data()
    path = results_path(ws.root, data)
    files = [f for f in data.get("results_files") or [] if isinstance(f, str)]
    if path.is_dir() and files:
        path = path / files[0]
    return line_path(path)


def more_answers(ws, run: str | None = None) -> str:
    """MORE_ANSWERS for the run that opened the page or made the marks (`run`), without the
    page's own flags (start_label.mark_command's)."""
    from judgekeeper.start_label import _PAGE_FLAGS
    from judgekeeper.textio import program

    command = _PAGE_FLAGS.sub("", run or program())
    return MORE_ANSWERS.format(file=results_file(ws), n=MIN_MARKS, command=command)


def toward(n: int) -> dict:
    """The marking page's bar (counts.toward) with no LLM-as-a-judge: full at MIN_MARKS marks
    of any kind (the bar counts up to targets.ROUGH Pass and ROUGH Fail marks)."""
    from judgekeeper.targets import ROUGH

    x = ROUGH * min(n, MIN_MARKS) / MIN_MARKS
    return {"correct": x, "wrong": x}


# Saving the answers -------------------------------------------------------------------------

def prepare(found, ws) -> None:
    """start.json and pool.jsonl for answers with no grade (`found`). Marking already started
    on them: the answers marked keep their place, new answers in the file come after them in
    a shuffled order, and the marks stay. The page's order is shuffled once."""
    from judgekeeper.start_label import _scrubbed, _write_json, begin_marks, make_folder

    old = ws.data() if ws.start.is_file() else None
    old = old if is_off(old) else None
    answers = {a.id: a for a in found.pool.answers}
    if old is not None:
        seed, started = old["seed"], old.get("started_at")
        kept = [q["id"] for q in old["queue"] if q["id"] in answers]
        new = [i for i in answers if i not in set(kept)]
        random.Random(f"{seed}:{len(kept)}").shuffle(new)
        order = kept + new
    else:
        seed, started = secrets.randbelow(2**31), None
        order = list(answers)
        random.Random(seed).shuffle(order)
    make_folder(ws)
    pool = _scrubbed([{"id": i, "input": answers[i].input, "output": answers[i].output,
                       **answers[i].agent} for i in order])
    write_replacing(ws.pool, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pool))
    newest = found.results[0]
    p = found.pool
    _write_json(ws.start, {
        "judgekeeper_version": __version__,
        "tool": found.tool,
        "results_files": found.used,
        "results_date": f"{newest.date():%Y-%m-%d %H:%M}",
        "metric": None,
        "judge": None,
        "rule": None,
        "description": None,
        "app_version": found.app_version,
        **({"given": found.given} if getattr(found, "given", None) else {}),
        "fingerprint": scrub_fingerprint(found.fingerprint),
        "pass_mark": None,
        "one_rule": True,
        "graded": False,
        "pool": {"answers": len(p.answers), "pass": 0, "fail": 0},
        "pool_sha256": canonical_hash(pool),
        "left": {"ids": [], "texts": []},
        "left_out": {"no_clear_verdict": 0, "unmapped_values": [],
                     "repeats_merged": p.n_merged, "human_labels_not_used": 0},
        "seed": seed,
        "queue": [{"id": i, "group": None} for i in order],
        "started_at": started or utc_now(),
        "updated_at": utc_now(),
    })
    if not ws.marks.is_file():
        begin_marks(ws)


def to_graded(ws, found) -> None:
    """A grade column was added to answers marked with none: the usual start.json and
    pool files for the LLM-as-a-judge (start_label.prepare), and the marks kept, their header
    naming it now. Marks on answers the file no longer holds are kept and not counted."""
    from judgekeeper.start_label import _scrubbed, judge_of, prepare

    for path in (ws.start, ws.result_json):  # made again from the marks by the usual steps
        if path.is_file() and not path.is_symlink():
            path.unlink()
    for path in (ws.ready_seen,):  # the usual result gets its own pop-up
        if path.is_file() and not path.is_symlink():
            path.unlink()
    prepare(found, say=lambda line: None, ws=ws, keep_marks=True)
    data = ws.data()
    _header(ws.marks, _scrubbed(marks.header(judge=judge_of(data), pool=data["pool"],
                                             results=data.get("results_files") or [])))


def _header(path: Path, head: dict) -> None:
    """marks.jsonl's first line (its header) as `head`; every mark after it as it is."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return
    if lines:
        try:
            first = loads(lines[0])
        except ValueError:
            first = None
        if isinstance(first, dict) and "marks" in first:
            lines = lines[1:]
    marks._refuse_links(path)
    write_replacing(path, marks._line(head) + "".join(lines))
