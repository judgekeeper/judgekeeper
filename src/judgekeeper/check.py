"""`judgekeeper check`: when the judge changed, re-test it on the person's marks.

Marks are tests for the judge. The judge is its whole setup (judge_setup.py), read from the
newest results, never from the eval config; `.judgekeeper/judge.json` keeps the setup last
checked. The person runs it by hand, after they change their judge or update their eval tool.

`results-seen.json` (local, never committed) remembers the setup of the newest results by what
the files it came from hold (the results, the lockfiles, judgekeeper.toml), so a check with
nothing new reads nothing again.

For a changed setup:
1. free first: marked answers whose exact text is in the newest results already have the new
   judge's verdict;
2. the rest only after the person's yes: `check` says how many answers and calls it would
   ask about and asks `Go ahead? [y/N]` at a terminal (Enter is no); without a terminal only
   `--yes` says yes, else it stops (exit 3) before anything is asked or saved. The person's
   own judge is then asked once about each, through `again/` (no menu);
3. per group (the answers the person passed, and failed), every mark with an old and a new
   verdict: how many turned wrong and turned right, and a range on the paired change
   (targets.paired_verdict): "Worse", "No drop bigger than 20 points" or "Not sure", always
   with the worst drop the marks could hide. The old verdicts are the last check's for the
   previous setup (`verdicts/<hash>.jsonl`), else the results the marks were made on. The
   screen shows counts; the rates the report and history.jsonl keep are re-weighted by the
   groups the marks were picked from, so the old one is the report's;
4. the lines below, a `history.jsonl` line (no answer text), the new verdicts in
   `verdicts/<hash>.jsonl` (ids and verdicts only, under a header with the setup and the
   judge's fingerprint), and judge.json moves to the new setup. When no answer could be
   tested, nothing is saved: the check stays pending.

Exit 0 (no drop bigger than 20 points, not sure with a smaller drop, or nothing changed), 1
(worse, or not sure with a drop bigger than 20 points, in either group), 3 (the person is
needed: not enough marks, nothing could be tested, or the question needs an answer).
report.html shows one History row per check (report_rows).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import __version__, find, judge_setup, marks, start, targets, weighted
from judgekeeper.fingerprint import utc_now
from judgekeeper.records import RecordsError
from judgekeeper.redact import one_line, scrub, scrub_value
from judgekeeper.start_label import Workspace
from judgekeeper.textio import plural, program, quote_arg, wrap, write_replacing

EXIT_OK, EXIT_WORSE, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 1, 2, 3
VERDICTS = "verdicts"
SEEN = "results-seen.json"
LOCKFILES = ("package-lock.json", "uv.lock", "poetry.lock", "judgekeeper.toml")
WHOLE = 4_000_000  # bytes: a results file up to this size is hashed whole
ENDS = 64 * 1024  # bytes read from each end of a bigger one
MAX_ENTRIES = 20_000  # files in a results folder (an MLflow store) looked at, at most
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
GROUPS = (("passed", "pass", "Answers you passed"), ("failed", "fail", "Answers you failed"))
SAID = {"passed": "You passed", "failed": "You failed"}
NEXT_NOT_SURE = ("Next: mark more answers with `{mark}`, then run `{command}` again.")
VERDICT_WORDS = {"worse": "Worse", "not_sure": "Not sure",
                 "no_drop": f"No drop bigger than {round(targets.NO_DROP_MARGIN * 100)} points"}

CONFIG_NEWER = ("Your judge's settings changed after your last eval run, so the grades "
                "judgekeeper has are out of date.")
SAME = "Same model, same rule, same eval tool."
NOT_SET_UP = "You have not marked enough answers yet for a re-check."
ASK_FIRST = ("To re-check, judgekeeper asks your new judge about {which}{n}. That is {calls}, "
             "paid with your own key.")
GO_AHEAD = "Go ahead? [y/N] "
CAN_WRITE = "Your judge is an agent that can change files when it runs."
NOT_ASKED = "Your judge was not asked."
NEXT_YES = "Next: run `{command}` in your terminal to answer, or `{command} --yes` to go ahead."
NEXT_LATER = "Next: run `{command}` again when you are ready to re-check your judge."
NEXT_NOT_MARKED = ("Next: run your eval on the questions you marked, then run `{command}` "
                   "again; or start over on your new answers with `{new}`.")
NEXT_SAME = "Next: nothing to do. Run `{command}` again after you change your judge."
NEXT_EVAL = "Next: run your eval again, then run `{command}`."
NEXT_RUN_EVAL = "Next: run your eval once, then run `{command}` again."
NEXT_WORSE = "Next: go back to {back}, or change your judge and run `{command}` again."
SWITCHED = ("Your results now come from {new}, not {old}.",
            "judgekeeper can't compare judges across two eval tools.")
NEXT_FRESH = "Next: run `{command}` to start fresh with {new}."
STEP = "Step 5 of 5: Re-check"
DOWNLOAD = ("Asking your judge would mean downloading promptfoo {version}; judgekeeper "
            "doesn't download anything by itself.")
NO_KEY = "The key your judge needs isn't set where judgekeeper runs, so your judge wasn't asked."
CLOSE = "This was a close copy of your judge, not an exact one: {why}."
TRACE_WHY = "your judge reads traces, which may have changed since your eval ran"


_n = plural  # textio.plural


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.0%}"


def _day(stamp: str | None) -> str | None:
    """"12 Oct" for a UTC stamp, in local time."""
    try:
        made = datetime.strptime(stamp or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    local = made.astimezone()
    return f"{local.day} {MONTHS[local.month - 1]}"


# What is there ----------------------------------------------------------------------------------

@dataclass
class State:
    ws: Workspace
    path: str
    data: dict  # start.json
    marks: dict[str, str]  # answer id -> "pass" or "fail"
    saved: dict  # judge.json (judge_setup.read)
    lines: list[str] = field(default_factory=list)  # what is said, in order

    @property
    def enough(self) -> bool:
        values = list(self.marks.values())
        n_pass, n_fail = values.count("pass"), values.count("fail")
        return min(n_pass, n_fail) >= targets.ROUGH


def _state(path: str) -> State | None:
    """What .judgekeeper/ holds, or None when marking never started there."""
    from judgekeeper.start_again import _project

    given = Path(path)
    if not given.exists():
        return None
    ws = Workspace(_project(given))
    if not ws.start.is_file():
        return None
    try:
        data = ws.data()
        saved = judge_setup.read(ws)
    except (OSError, ValueError):
        return None
    if saved is None or not isinstance(data, dict):
        return None
    return State(ws=ws, path=path, data=data, marks=marks.read(ws.marks).counted(), saved=saved)


def _newest(state: State):
    """The judge of the marks in the newest results (start.find_judge, with nothing asked),
    or the reason it can't be read, in one line."""
    data = state.data
    root = state.ws.root
    pm = data.get("pass_mark") or {}
    fp = data.get("fingerprint") or {}
    options = {"metric": data.get("metric"), "label_map": data.get("label_map"),
               "pass_if": pm.get("rule") if pm.get("source") == "pass_if" else None,
               "store": data.get("mlflow_store")}
    try:
        if start._saved(root) is None:
            options["tool"] = data.get("tool")
        given = fp.get("model") if fp.get("model_source") == start.GIVEN_BY_YOU else None
        try:
            return start.find_judge(root, judge_model=given, **options), None
        except start.StartError:
            if given is None:
                raise
            return start.find_judge(root, **options), None  # the results name it now
    except (start.StartError, start.Stop, RecordsError, OSError, ValueError) as e:
        tool = data.get("tool")
        if tool in find.TOOLS and not find.search(root).readable(tool):
            return None, (f"judgekeeper finds no {find.NAMES.get(tool, tool)} results in this "
                          f"folder ({Path(root).name})")
        why = (scrub(str(e)) if str(e) and not isinstance(e, start.Stop)
               else "they need a choice first, such as which results to read: run "
                    f"`{program()}` to make it")
        return None, (f"judgekeeper can't read your judge {data.get('metric')} in your newest "
                      f"results: {why}")


def _configs(found) -> list[Path]:
    """The files the judge comes from: promptfoo's config, Inspect's task file."""
    root = Path(found.root)
    if found.tool == "promptfoo":
        return [root / n for n in find.PROMPTFOO_CONFIGS]
    if found.tool == "inspect" and found.task_file:
        return [root / found.task_file]
    return []


def _newer(configs: list[Path], newest: Path) -> Path | None:
    """The first of `configs` that is newer than the results file `newest`."""
    try:
        results = newest.stat().st_mtime
    except OSError:
        return None
    for f in configs:
        try:
            if f.is_file() and f.stat().st_mtime > results:
                return f
        except OSError:
            continue
    return None


def _lock_newer(state: State, old: dict, new: dict, newest: Path | None) -> bool:
    """Whether the eval tool's version changed only in a lockfile written after the newest
    results: they were made by the old version, so they can't re-check the new one."""
    if old.get("tool_version") == new.get("tool_version") or new.get("version_from") != \
            "lockfile" or newest is None:
        return False
    root = Path(state.ws.root)
    locks = [root / n for n in LOCKFILES if n != "judgekeeper.toml"]
    locks += list(root.glob("requirements*.txt"))
    try:
        results = newest.stat().st_mtime
    except OSError:
        return False
    return any(f.is_file() and f.stat().st_mtime > results for f in locks)


def _config_newer(found) -> Path | None:
    """The file the judge comes from, when it is newer than the newest results."""
    return _newer(_configs(found), found.results[0].path)


# The setup of the newest results, remembered -----------------------------------------------------

def _file_part(h, path: Path, st: os.stat_result) -> None:
    h.update(f"{st.st_size}\0".encode())
    try:
        with open(path, "rb") as f:
            if st.st_size <= WHOLE:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
                return
            h.update(f"{st.st_mtime_ns}\0".encode())
            h.update(f.read(ENDS))
            f.seek(-ENDS, os.SEEK_END)
            h.update(f.read(ENDS))
    except OSError:
        h.update(b"unreadable\0")


def files_signature(paths) -> str | None:
    """A hash of what `paths` hold now: a file up to WHOLE bytes by its content, a bigger one
    by its size, modified time and both ends; a folder (an MLflow store) by the name, size and
    modified time of everything in it. None when a folder holds more than MAX_ENTRIES."""
    h = hashlib.sha256()
    entries = 0
    for path in sorted({Path(p) for p in paths}, key=str):
        h.update(str(path).encode("utf-8", "surrogatepass") + b"\0")
        try:
            st = path.stat()
        except OSError:
            h.update(b"none\0")
            continue
        if not stat.S_ISDIR(st.st_mode):
            _file_part(h, path, st)
            continue
        for folder, dirs, files in os.walk(path):  # never follows a link
            dirs.sort()
            for name in sorted(dirs + files):
                entries += 1
                if entries > MAX_ENTRIES:
                    return None
                try:
                    st = os.lstat(os.path.join(folder, name))
                except OSError:
                    continue
                rel = os.path.relpath(os.path.join(folder, name), path)
                h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\0".encode("utf-8",
                                                                         "surrogatepass"))
    return h.hexdigest()


def _key(state: State, read: list[str]) -> str | None:
    """What the setup of the newest results depends on, as one hash: the results judgekeeper
    finds and the ones it read last time, the lockfiles and judgekeeper.toml, how start.json
    says to read them, and judgekeeper's own version. None when it can't be told cheaply."""
    root = state.ws.root
    found = find.search(root)
    if found.stopped:
        return None
    paths = {str(r.path) for rs in found.results.values() for r in rs} | set(read)
    paths |= {str(root / n) for n in LOCKFILES} | {str(p) for p in root.glob("requirements*.txt")}
    paths |= {p + "-wal" for p in list(paths)}  # an SQLite store writes here first
    signature = files_signature(paths)
    if signature is None:
        return None
    data = state.data
    how = {k: data.get(k) for k in ("tool", "metric", "label_map", "pass_mark", "mlflow_store")}
    fp = data.get("fingerprint") or {}
    how["given"] = fp.get("model") if fp.get("model_source") == start.GIVEN_BY_YOU else None
    how["env"] = {v: os.environ.get(v) for v in (*find.RESULTS_VARS.values(),
                                                 "MLFLOW_TRACKING_URI")}
    text = json.dumps([__version__, how, signature], sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seen(ws: Workspace) -> dict:
    try:
        data = json.loads((ws.dir / SEEN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ok = (isinstance(data, dict) and data.get("judgekeeper_version") == __version__
          and isinstance(data.get("setup"), dict) and isinstance(data.get("read"), list))
    return data if ok else {}


def _remember(state: State, found, setup: dict) -> None:
    """results-seen.json: the setup of the results just read, and what it depends on."""
    root = state.ws.root
    read = [str(r.path) for r in found.results]
    try:
        key = _key(state, read)
        if key is None:
            return
        path = state.ws.dir / SEEN
        marks._refuse_links(path)
        write_replacing(path, json.dumps({
            "judgekeeper_version": __version__, "key": key, "setup": setup,
            "setup_hash": judge_setup.hash_of(setup), "read": read,
            "newest": str(found.results[0].path), "configs": [str(p) for p in _configs(found)],
            "root": str(root)}, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, marks.MarksError):
        pass  # the next check reads the results again


@dataclass
class Now:
    """The judge in the newest results: its setup, its config when that is newer than the
    results, and the results themselves when they were read (None: remembered)."""
    setup: dict
    config: Path | None
    found: object | None = None
    newest: Path | None = None  # the newest results file (or store)


def _now(state: State) -> tuple[Now | None, str | None]:
    """(the judge in the newest results, None), from results-seen.json when nothing it
    depends on changed; else read, and remembered. (None, why) when it can't be read."""
    seen = _seen(state.ws)
    if seen and seen.get("root") == str(state.ws.root):
        try:
            same = _key(state, [str(p) for p in seen["read"]]) == seen.get("key")
        except (OSError, ValueError):
            same = False
        if same:
            configs = [Path(p) for p in seen.get("configs") or []]
            newest = Path(seen.get("newest") or "")
            return Now(seen["setup"], _newer(configs, newest), newest=newest), None
    found, problem = _newest(state)
    if found is None:
        return None, problem
    setup = judge_setup.of(found)
    _remember(state, found, setup)
    return Now(setup, _config_newer(found), found, found.results[0].path), None


def _change_line(old: dict, new: dict, changed: list[str], full: bool) -> str:
    if judge_setup.tool_only(old, new):
        line = f"Your eval tool changed: {judge_setup.tool_words(old, new)}."
        if full:
            line += " Your judge's rule and model are the same."
        return line
    return f"Your judge changed: {', '.join(changed)}."


def _command(state_or_path) -> str:
    path = state_or_path.path if isinstance(state_or_path, State) else state_or_path
    return " ".join((program("check"), *([] if str(path) == "." else [quote_arg(path)])))


# Asking the judge -------------------------------------------------------------------------------

class _Quiet:
    """The talk a tool's run gets: nothing is printed."""

    quiet = True
    yes = False

    def say(self, text: str = "") -> None:
        pass


@dataclass
class Asked:
    verdicts: dict[str, str] = field(default_factory=dict)
    calls: int = 0
    reasons: list[str] = field(default_factory=list)
    close: str | None = None  # why it was a close copy
    not_marked: bool = False  # the newest results hold none of the marked answers


def _can_write(setup: dict) -> bool:
    agent = setup.get("agent") or {}
    return setup.get("kind") == judge_setup.AGENT and agent.get("can_write") is not False


def _wrap(said, text: str) -> None:
    for line in wrap(text):
        said.say(line)


def _go_ahead(yes: bool) -> bool | None:
    """The person's answer to GO_AHEAD: --yes, else asked at a terminal (Enter is no); None
    without a terminal."""
    if yes:
        return True
    if not start._interactive():
        return None
    while True:
        try:
            answer = input(GO_AHEAD).strip().lower()
        except EOFError:
            return False
        if answer in ("", "n", "no"):
            return False
        if answer in ("y", "yes"):
            return True


def ask(state: State, found, setup: dict, ids: list[str], said, yes: bool,
        rest: bool = False) -> Asked | None:
    """Ask the judge in the newest results about the marked answers `ids` (`rest`: the ones
    not found free), once the person said yes to the calls it makes. None without a terminal
    and without --yes: the question is said, nothing is asked."""
    from judgekeeper import again, new_judge
    from judgekeeper.again.fresh import NOT_COUNTED, AgainError, write_files

    out = Asked()
    ws = state.ws
    view = new_judge.View(ws, found)
    plan = again.make_plan(ws, again.AgainOptions(times=1), dry=True, new=view, only=set(ids))
    if plan.status == again.CANT:
        out.reasons.append(plan.plain or f"Your judge can't be asked again: {plan.why}.")
        out.not_marked = plan.why == again.NOT_MARKED
        return out
    if not plan.key_ok:
        out.reasons.append(NO_KEY)
        return out
    if plan.download:
        out.reasons.append(DOWNLOAD.format(version=plan.tool_version))
        return out
    said.say()
    _wrap(said, ASK_FIRST.format(which="the other " if rest else "your ",
                                 n=_n(len(ids), "marked answer"), calls=_n(plan.calls, "AI call")))
    if _can_write(setup):
        said.say(CAN_WRITE)
    answer = _go_ahead(yes)
    if answer is None:
        return None
    if not answer:
        out.reasons.append(NOT_ASKED)
        return out
    plan.folder = ws.dir / "checks" / utc_now().replace(":", "-")
    try:
        fresh = again.run_tool(view, plan, _Quiet())
    except AgainError as e:
        out.reasons.append(f"Asking your judge again did not finish: {scrub(str(e))}")
        out.calls = plan.calls
        return out
    write_files(ws, plan, fresh, prefix="check", metric=found.metric)
    out.verdicts = {i: v[0] for i, v in fresh.verdicts.items()}
    out.calls = plan.calls
    left: dict[str, int] = {}
    for why in fresh.not_counted.values():
        left[why] = left.get(why, 0) + 1
    for why, k in left.items():
        one, many = NOT_COUNTED.get(why, (why, why))
        out.reasons.append(f"1 answer was not counted: {one}." if k == 1 else
                           f"{k} answers were not counted: {many}.")
    whys = [plan.why] if plan.status == again.CLOSE else []
    if setup.get("kind") == judge_setup.AGENT and (setup.get("agent") or {}).get(
            "looks_at") == "trace":
        whys.append(TRACE_WHY)
    out.close = "; ".join(whys) or None
    return out


# The paired test --------------------------------------------------------------------------------

def _old_verdicts(state: State) -> dict[str, str]:
    """The old judge's verdicts on the marked answers: the last check's (or the baseline's)
    for the setup judge.json keeps, else the results the marks were made on."""
    pool = {q["id"]: q["group"] for q in state.data.get("queue") or []}
    return {**pool, **_read_verdicts(state.ws, state.saved["setup_hash"])}


def _picks(state: State) -> tuple[dict[str, str], dict[str, int]]:
    """(the group each mark was picked from, that pool's sizes): start.json's queue, or the
    groups a re-check kept (start_label.picked_numbers)."""
    data = state.data
    queue = {q["id"]: q["group"] for q in data.get("queue") or []}
    picked = data.get("picked") or {}
    pool = picked.get("pool") or data.get("pool") or {}
    return {**queue, **(picked.get("groups") or {})}, {g: int(pool.get(g) or 0)
                                                       for g in ("pass", "fail")}


def _rates(marked: dict[str, str], verdicts: dict[str, str], picked: dict[str, str],
           pool: dict[str, int]) -> dict:
    """TPR and TNR of `verdicts` on the marks, re-weighted by the groups they were picked
    from (weighted.general): the numbers the report shows."""
    items = [(picked.get(i, v), marked[i], v) for i, v in verdicts.items() if i in marked]
    if not items or not pool.get("pass", 0) + pool.get("fail", 0):
        return {"tpr": None, "tnr": None}
    out = weighted.general(items, pool["pass"], pool["fail"], draws=200)
    return {"tpr": out["tpr"], "tnr": out["tnr"]}


def groups(marked: dict[str, str], old: dict[str, str], new: dict[str, str],
           picked: dict[str, str] | None = None, pool: dict[str, int] | None = None) -> dict:
    """Per group of marks (passed, failed): of the marks with an old and a new verdict, how
    many each judge got right, how many turned wrong and right, the range on the paired change
    and its verdict (targets.paired_verdict); and each judge's re-weighted rate (`old_rate`,
    `new_rate`) when the pick groups and pool sizes are given."""
    both = [i for i in new if i in old and i in marked]
    rates = None
    if picked is not None and pool is not None:
        rates = (_rates(marked, {i: old[i] for i in both}, picked, pool),
                 _rates(marked, {i: new[i] for i in both}, picked, pool))
    out = {}
    for key, mark, _ in GROUPS:
        ids = [i for i in both if marked[i] == mark]
        n = len(ids)
        wrong = sum(old[i] == mark and new[i] != mark for i in ids)
        right = sum(old[i] != mark and new[i] == mark for i in ids)
        g = {"n": n, "old_right": sum(old[i] == mark for i in ids),
             "new_right": sum(new[i] == mark for i in ids),
             "old": sum(old[i] == mark for i in ids) / n if n else None,
             "new": sum(new[i] == mark for i in ids) / n if n else None,
             "now_wrong": wrong, "now_right": right, "verdict": "not tested"}
        if n:
            paired = targets.paired_verdict(right, wrong, n)
            g.update(verdict=paired["verdict"], change=paired["change"], low=paired["low"],
                     high=paired["high"], exit_worse=paired["exit_worse"])
        if rates is not None:
            rate = "tpr" if mark == "pass" else "tnr"
            g.update(old_rate=rates[0][rate], new_rate=rates[1][rate])
        out[key] = g
    return out


def _points(x: float) -> int:
    return round(abs(x) * 100)


def _count(k: int) -> str:
    return str(k) if k else "none"


def paired_lines(g: dict) -> list[str]:
    """The verdict on one group, in counts only (never which answers changed)."""
    wrong, right = g["now_wrong"], g["now_right"]
    if g["verdict"] == "worse":
        return [f"Worse: {_count(wrong)} turned wrong and {_count(right)} turned right.",
                (f"That is down {_points(g['change'])} points, and it could be as much as "
                f"{_points(g['low'])}.")]
    if g["verdict"] == "not_sure":
        return [(f"Not sure: {_count(wrong)} turned wrong and {_count(right)} turned right. It "
                f"could be up to {_points(g['low'])} points worse.")]
    first = f"{VERDICT_WORDS['no_drop']}: {_count(wrong)} turned wrong, {_count(right)} turned right."
    if g["low"] >= 0:
        return [first, "None of its range is a drop."]
    return [first, f"These marks can't rule out a drop of up to {_points(g['low'])} points."]


def _group_lines(key: str, g: dict) -> list[str]:
    head = f"  {SAID[key]}:  "
    if not g["n"]:
        return [head + "none could be re-checked."]
    return [(f"{head}old judge right on {g['old_right']} of {g['n']}, new judge on "
            f"{g['new_right']} of {g['n']}"), *(f"    {line}" for line in paired_lines(g))]


# Saving -----------------------------------------------------------------------------------------

def _verdicts_path(ws: Workspace, setup_hash: str) -> Path:
    return ws.dir / VERDICTS / f"{setup_hash.removeprefix('sha256:')}.jsonl"


def _read_verdicts(ws: Workspace, setup_hash: str) -> dict[str, str]:
    try:
        text = _verdicts_path(ws, setup_hash).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for raw in text.splitlines()[1:]:
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("verdict") in ("pass", "fail"):
            out[str(line.get("id"))] = line["verdict"]
    return out


def _save_verdicts(ws: Workspace, setup: dict, found, verdicts: dict[str, str]) -> None:
    """verdicts/<hash>.jsonl: a header with the setup and the judge's fingerprint, then one
    {id, verdict} line per answer; no text."""
    setup_hash = judge_setup.hash_of(setup)
    merged = {**_read_verdicts(ws, setup_hash), **verdicts}
    path = _verdicts_path(ws, setup_hash)
    marks._refuse_links(path)
    path.parent.mkdir(exist_ok=True)
    head = scrub_value({"setup": setup, "setup_hash": setup_hash,
                        "fingerprint": dict(found.fingerprint or {}, created_at=utc_now()),
                        "judgekeeper_version": __version__})
    lines = [head] + [{"id": i, "verdict": v} for i, v in merged.items()]
    write_replacing(path, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))


# check ------------------------------------------------------------------------------------------

@dataclass
class Said:
    """What check says, line by line: a Next: line, or any line over 80 columns, wrapped
    (textio.wrap) under its own indent."""
    lines: list[str] = field(default_factory=list)

    def say(self, text: str = "") -> None:
        text = one_line(text)
        if not text.startswith("Next:") and len(text) <= 80:
            self.lines.append(text)
            return
        indent = text[:len(text) - len(text.lstrip())]
        for line in wrap(text.strip(), indent=indent):
            self._say(line)

    def _say(self, line: str) -> None:
        self.lines.append(line)


def _not_set_up(path: str, state: State | None, said) -> int:
    """No marks to check with: where it looked, and where the marks are when a folder above
    holds them (check run from a folder inside the project, or in .judgekeeper/)."""
    from judgekeeper.start_again import _project

    given = Path(path)
    if not given.exists():
        said.say(f"There is no file or folder named {given.name or path} here.")
        said.say()
        said.say(f"Next: run `{program('check')}` in your project folder.")
        return EXIT_USAGE
    if state is not None:
        said.say(NOT_SET_UP)
        said.say()
        said.say(f"Next: run `{program('mark')}` to mark more answers.")
        return EXIT_NEEDS_YOU
    folder = _project(given)
    above = next((p for p in folder.parents if Workspace(p).start.is_file()), None)
    if above is None:
        said.say(f"No marks in this folder ({folder.name}).")
        said.say()
        said.say(f"Next: run `{program()}` to find your eval results and mark answers.")
        return EXIT_NEEDS_YOU
    where = os.path.relpath(above, given if given.is_dir() else given.parent)
    which = "the folder" if above == folder.parent else "a folder"
    said.say(f"No marks in this folder ({folder.name}). Your marks are in {which} above it "
             f"({above.name}).")
    said.say()
    said.say(f"Next: run `{program('check')} {quote_arg(where)}`.")
    return EXIT_NEEDS_YOU


def _tested_rule(state: State, found) -> str | None:
    """When the new judge's rule is one `judgekeeper fix` tested: the line that says so, with
    the day and the result of that test."""
    from judgekeeper.fix import VERDICT_NAMES
    from judgekeeper.start_fix_rule import rule_text

    if not found.rule:
        return None
    now = " ".join(rule_text(found.rule, found.tool).split())
    folder = state.ws.dir / "rules"
    hashes = []
    for path in sorted(folder.glob("*.txt")) if folder.is_dir() else []:
        try:
            if " ".join(path.read_text(encoding="utf-8").split()) == now:
                hashes.append("sha256:" + path.stem)
        except OSError:
            continue
    tests = [x for x in _history_all(state.ws)
             if x.get("kind") == "fix" and x.get("rule_hash") in hashes]
    if not tests:
        return None
    day = _day(tests[-1].get("time"))
    result = VERDICT_NAMES.get(tests[-1].get("verdict"), "").lower()
    return (f"This is the rule you tested with `{program('fix')}`"
            f"{f' on {day}' if day else ''}{f' ({result})' if result else ''}.")


def _history_all(ws: Workspace) -> list[dict]:
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


def _switched(state: State) -> str | None:
    """The eval tool whose results are here now, when the marks' tool has none: judges of two
    eval tools can't be compared."""
    search = find.search(state.ws.root)
    tools = [t for t in find.TOOLS if search.readable(t)]
    old = state.data.get("tool")
    return tools[0] if tools and old not in tools else None


def _no_change(state: State) -> str:
    """Since when the judge is the same: the last check, or the marks when none ran."""
    checks = _history(state.ws)
    day = _day(checks[-1].get("time")) if checks else None
    if not checks:
        return "Your judge has not changed since you marked your answers."
    return f"Your judge has not changed since your last check{f' ({day})' if day else ''}."


# How many changes the marks have helped pick -------------------------------------------------
# A pick: a `fix` test on these marks, or a check of a rule or pass-mark change (a change made
# by looking at the marks). A model change or a tool update is not one. After PICKS_ASK picks,
# until PICK_MARKS marks are made after the last one, the marks may flatter the judge.

PICKS_ASK = 3
PICK_MARKS = 10
NEXT_NEW_MARKS = ("Next: run `{mark}` to mark {n} new answers, then run `{command}` again.")


def is_pick(line: dict) -> bool:
    """Whether a history.jsonl line is a pick (above)."""
    if line.get("kind") == "fix":
        return True
    changed = line.get("changed") or []
    return line.get("kind") == "check" and any(
        c == "rule changed" or str(c).startswith("pass mark") for c in changed)


def rule_changed(changed: list[str]) -> bool:
    return is_pick({"kind": "check", "changed": changed})


def picks(ws: Workspace, now: bool = False) -> dict:
    """{"n": picks, "new_marks": marks made after the last, "ask": whether to ask for
    PICK_MARKS new marks}: counted from these marks on (marks.jsonl's start, or `fix --new`).
    `now`: this run is a pick too."""
    from judgekeeper import fix

    read = marks.read(ws.marks)
    split = fix.read_split(ws)
    since = max(str((read.header or {}).get("created_at") or ""),
                str(split.reset_at if split else ""))
    times = [str(x.get("time") or "") for x in _history_all(ws) if is_pick(x)]
    times = [t for t in times if t >= since] + ([utc_now()] if now else [])
    last = max(times) if times else None
    made = sum(str(x.get("at") or "") > last for i, x in read.last.items()
               if i in read.counted()) if last else 0
    return {"n": len(times), "new_marks": made,
            "ask": len(times) >= PICKS_ASK and made < PICK_MARKS}


def picks_lines(p: dict) -> list[str]:
    if not p["n"]:
        return []
    out = [f"These marks have helped pick {plural(p['n'], 'change')}."]
    if p["ask"]:
        out.append(f"Your marks have been used to pick {plural(p['n'], 'change')}, so they may "
                   f"now flatter your judge. Mark {PICK_MARKS} new answers to keep the check "
                   "honest.")
    return out


def _history(ws: Workspace) -> list[dict]:
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "check":
            out.append(line)
    return out


def _free(found, marked: dict[str, str]) -> dict[str, str]:
    """The new judge's verdicts on marked answers found word for word in the newest results
    (for a judge whose results are many files, in every file of the newest judge)."""
    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    return {a.id: a.verdict for a in found.pool.answers
            if a.id in marked and a.source in newest}


def full(path: str, said: Said, yes: bool = False) -> int:
    state = _state(path)
    if state is None or not state.enough:
        return _not_set_up(path, state, said)
    old = state.saved["setup"]
    now, problem = _now(state)
    found, new = (now.found, now.setup) if now is not None else (None, None)
    if now is not None and found is None and judge_setup.changes(old, new):
        found, problem = _newest(state)  # remembered, but a re-check needs the answers
        new = judge_setup.of(found) if found is not None else new
    switched = _switched(state) if problem else None
    if switched:
        names = find.NAMES
        old_tool = state.data.get("tool")
        for line in SWITCHED:
            said.say(line.format(new=names.get(switched, switched),
                                 old=names.get(old_tool, old_tool)))
        said.say()
        said.say(NEXT_FRESH.format(command=program(), new=names.get(switched, switched)))
        return EXIT_NEEDS_YOU
    if problem:
        said.say(problem + ".")
        said.say()
        said.say(NEXT_RUN_EVAL.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    changed = judge_setup.changes(old, new)
    if not changed:
        if now.config is not None:  # one line per case, never "no change" with it
            said.say(CONFIG_NEWER)
            said.say()
            said.say(NEXT_EVAL.format(command=_command(state)))
        else:
            said.say(_no_change(state))
            said.say(SAME)
            said.say()
            said.say(NEXT_SAME.format(command=_command(state)))
        return EXIT_OK

    change = _change_line(old, new, changed, full=True)
    said.say(change)
    tested = _tested_rule(state, found) if found is not None and old.get("rule_hash") != \
        new.get("rule_hash") else None
    if tested:
        said.say(tested)
    if _lock_newer(state, old, new, found.results[0].path if found else now.newest):
        said.say(CONFIG_NEWER)  # the results were made before the update: out of date
        said.say()
        said.say(NEXT_EVAL.format(command=_command(state)))
        return EXIT_OK
    free = _free(found, state.marks)
    # what the last check of this same new judge already asked (after a "Worse", say)
    cached = {i: v for i, v in _read_verdicts(state.ws, judge_setup.hash_of(new)).items()
              if i in state.marks and i not in free}
    rest = [i for i in state.marks if i not in free and i not in cached]
    asked = (ask(state, found, new, rest, said, yes, rest=bool(free)) if rest
             else Asked())
    if asked is None:
        said.say()
        said.say(NEXT_YES.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    tested = {**free, **cached, **asked.verdicts}
    if not tested:
        for line in asked.reasons:
            said.say(line)
        said.say()
        later = NEXT_NOT_MARKED if asked.not_marked else NEXT_LATER
        said.say(later.format(command=_command(state), new=program("--new")))
        return EXIT_NEEDS_YOU

    n, total = len(tested), len(state.marks)
    if free and not asked.verdicts and not cached:
        said.say("Re-checked for free from your new results.")
    for line in asked.reasons:
        said.say(line)
    said.say()
    on = f"all {total} of your marks" if n == total else f"{n} of your {_n(total, 'mark')}"
    said.say(f"Re-checked on {on}:")
    said.say()
    old_verdicts = _old_verdicts(state)
    picked, pool = _picks(state)
    g = groups(state.marks, old_verdicts, tested, picked, pool)
    for key, _, _title in GROUPS:
        for line in _group_lines(key, g[key]):
            said.say(line)
        said.say()
    if asked.close:
        said.say(CLOSE.format(why=asked.close))
        said.say()
    drop = targets.smallest_drop(g["passed"]["n"], g["failed"]["n"], g["passed"]["old"],
                                 g["failed"]["old"])
    worse = [k for k in ("failed", "passed") if g[k]["verdict"] == "worse"]
    unsure = [k for k in ("failed", "passed") if g[k]["verdict"] == "not_sure"]
    picked = picks(state.ws, now=rule_changed(changed))
    for line in picks_lines(picked):
        said.say(line)
    if picks_lines(picked):
        said.say()
    if worse:
        tool = find.NAMES.get(new.get("tool"), new.get("tool"))
        back = (f"the old version of {tool} ({old.get('tool_version')})"
                if judge_setup.tool_only(old, new) else "the old judge")
        said.say(NEXT_WORSE.format(back=back, command=_command(state)))
    elif picked["ask"]:
        said.say(NEXT_NEW_MARKS.format(mark=program("mark"), n=PICK_MARKS - picked["new_marks"],
                                       command=_command(state)))
    elif unsure:
        said.say(NEXT_NOT_SURE.format(mark=program("mark"), command=_command(state)))
    else:
        said.say(NEXT_SAME.format(command=_command(state)))
    exit_worse = any(g[k].get("exit_worse") for k in g)

    flipped = [i for i in tested if i in old_verdicts and old_verdicts[i] != tested[i]]
    line = scrub_value({
        "time": utc_now(), "kind": "check", "trigger": "by hand", "before": old, "after": new,
        "changed": changed, "marks": total, "free": len(free), "asked": len(asked.verdicts),
        "calls": asked.calls, "exact": "close" if asked.close else "exact", "groups": g,
        "smallest_drop": drop, "flipped": flipped})
    if not _same_as_last(state, line):
        marks.append(state.ws.history_jsonl, line)
    _save_verdicts(state.ws, new, found, tested)
    if not worse:  # after "Worse" the old judge stays the reference until it comes back
        judge_setup.save(state.ws, new, found.metric)
    _report(state.ws)
    return EXIT_WORSE if exit_worse else EXIT_OK


def _same_as_last(state: State, line: dict) -> bool:
    """Whether the last check in history.jsonl is this one again (the same judges, the same
    result): a "Worse" that is still open is not a new check."""
    checks = _history(state.ws)
    if not checks:
        return False
    last = checks[-1]
    same = (judge_setup.hash_of(last.get("before") or {}) == judge_setup.hash_of(line["before"])
            and judge_setup.hash_of(last.get("after") or {}) == judge_setup.hash_of(line["after"]))
    return same and last.get("groups") == line["groups"]


def _report(ws: Workspace) -> None:
    """report.html again, with this check in its History (when there is a result)."""
    from judgekeeper.start_label import write_report

    try:
        write_report(ws)
    except OSError:
        pass  # the check is saved; the report catches up with the next result


# The command ------------------------------------------------------------------------------------

def _print(text: str = "") -> None:
    print(one_line(scrub(text)))
    sys.stdout.flush()


class _Printed(Said):
    """Said as it goes, so the question is asked in its place among the lines."""

    def say(self, text: str = "") -> None:
        if not text.startswith("Next:") and len(one_line(text)) <= 80:
            _print(text)
        else:
            super().say(text)

    def _say(self, line: str) -> None:
        _print(line)


def run(path: str = ".", yes: bool = False) -> int:
    """`judgekeeper check`. Returns the exit code."""
    _print(f"judgekeeper {__version__}")
    _print()
    _print(STEP)
    _print()
    return full(path, _Printed(), yes=yes)


# The report's History ------------------------------------------------------------------------

def _rate(x) -> str:
    return "?" if x is None else f"{x:.0%}"


def _row_verdict(said: list) -> str:
    """The History row's verdict: the worst of the groups'. A check from before the ranges
    (a sign test) that saw no drop is "Not sure": it could not tell a small one."""
    if "worse" in said:
        return VERDICT_WORDS["worse"]
    if "not_sure" in said or "no drop seen" in said:
        return VERDICT_WORDS["not_sure"]
    return VERDICT_WORDS["no_drop"] if "no_drop" in said else "Not tested"


def history_rows(lines: list[dict]) -> list[dict]:
    """One row per check in history.jsonl lines (in their order): date, what changed, marks
    tested, old against new per group, the verdict, exact or close."""
    rows = []
    for line in lines:
        if isinstance(line, dict) and line.get("kind") == "fix":  # a rule tested by fix
            from judgekeeper.fix import VERDICT_NAMES

            n = int(line.get("hidden") or 0)
            rows.append({"date": _day(line.get("time")) or "",
                         "changed": f"New rule tested on {plural(n, 'hidden mark')}",
                         "tested": plural(n, "hidden mark"),
                         "groups": [f"Fixed {line.get('fixed')}, broke {line.get('broke')}"],
                         "verdict": VERDICT_NAMES.get(line.get("verdict"), ""), "exact": ""})
            continue
        if not isinstance(line, dict) or line.get("kind") != "check" or \
                line.get("trigger") == "baseline":  # asked by automatic checks (1.0 betas)
            continue
        free, asked = int(line.get("free") or 0), int(line.get("asked") or 0)
        parts = ([f"{free} free"] if free else []) + ([f"{asked} asked again"] if asked else [])
        groups_ = line.get("groups") or {}
        shown = []
        for key, _, title in GROUPS:
            g = groups_.get(key) or {}
            old, new = (g.get("old_rate"), g.get("new_rate")) if "old_rate" in g else (
                g.get("old"), g.get("new"))  # the re-weighted rates, as the report shows
            shown.append(f"{title}: {_rate(old)} → {_rate(new)}"
                         if g.get("n") else f"{title}: not tested")
        said = [(groups_.get(k) or {}).get("verdict") for k in groups_]
        rows.append({"date": _day(line.get("time")) or "",
                     "tested": (f"{plural(free + asked, 'mark')} ({', '.join(parts)})" if parts
                                else "0 marks"),
                     "exact": "close copy" if line.get("exact") == "close" else "exact",
                     "changed": ", ".join(line.get("changed") or []), "groups": shown,
                     "verdict": _row_verdict(said)})
    return rows


def report_rows(ws: Workspace) -> list[dict]:
    """The History rows for report.html: newest first."""
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = []
    for raw in text.splitlines():
        try:
            lines.append(json.loads(raw))
        except ValueError:
            continue
    return list(reversed(history_rows(lines)))


__all__ = ["full", "groups", "history_rows", "report_rows", "run"]
