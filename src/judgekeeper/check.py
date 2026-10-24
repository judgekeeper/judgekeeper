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
   own judge is then asked once about each, through `again/` (no menu). When the model
   judgekeeper would hand the eval tool is not the new judge's, nothing is asked; when the
   tool says a call was answered by another model (wrong_model), nothing is saved (exit 2);
3. per group (the answers the person passed, and failed), every mark with an old and a new
   verdict: how many went from right to wrong and from wrong to right, and a range on the
   paired change (targets.paired_verdict): "Worse", "No drop bigger than 20 points" or
   "Not sure", always with the worst drop the marks could hide. The old verdicts are the
   last check's for the previous setup (`verdicts/<hash>.jsonl`), else the results the
   marks were made on. The screen shows counts; the rates the report and history.jsonl keep
   are re-weighted by the groups the marks were picked from, so the old one is the report's;
4. the lines below, a `history.jsonl` line (no answer text), the new verdicts in
   `verdicts/<hash>.jsonl` (ids and verdicts only, under a header with the setup and the
   judge's fingerprint), and judge.json moves to the new setup. Unless it is "Worse" or "Not
   sure" with a drop bigger than 20 points (exit 1), the marks then test the new judge:
   start.json and pool-judge.jsonl take its grades (_adopt), so the result and `fix` are about
   it. Such a check stays open: the next check of the same judge says it again, until the
   judge changes or more marks are re-checked. When no answer could be tested, nothing is saved: the check stays pending.

A setup counts as changed too when its judge's results hold no rule (a table) and its grades
on marked answers differ in the newest results (grades_changed), and the last check's change
is checked again when marks were made after it (_added_since_check).

Exit 0 (no drop bigger than 20 points, not sure with a smaller drop, or nothing changed), 1
(worse, or not sure with a drop bigger than 20 points, in either group), 2 (a call asked
another model than the new judge), 3 (the person is needed: not enough marks, nothing could be
tested, or the question needs an answer).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import (
    __version__,
    again,
    batches,
    find,
    judge_setup,
    marks,
    start,
    targets,
    weighted,
)
from judgekeeper.fingerprint import utc_now
from judgekeeper.records import RecordsError
from judgekeeper.redact import one_line, scrub, scrub_fingerprint, scrub_value
from judgekeeper.start_label import Workspace, every_marked, next_marks
from judgekeeper.textio import (
    make_private,
    old_hook,
    plural,
    program,
    quote_arg,
    wrap,
    write_replacing,
)

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
NEXT_NOT_SURE = "mark more answers with `{mark}`, then run `{command}` again."
NEXT_ALL_QUESTIONS = "run your eval on all your questions, then run `{command}`."
VERDICT_WORDS = {"worse": "Worse", "not_sure": "Not sure",
                 "no_drop": f"No drop bigger than {round(targets.NO_DROP_MARGIN * 100)} points"}

CONFIG_NEWER = ("Your LLM-as-a-judge's settings changed after your last eval run, so the grades "
                "judgekeeper has are out of date.")
SAME = "Same model, same rule, same eval tool."
NOT_SET_UP = "You have not marked enough answers yet for a re-check."
ASK_FIRST = ("To re-check, judgekeeper asks your new LLM-as-a-judge about {which}{n}, twice each. "
             "That is {calls}, paid with your own key.{download} Asking twice shows how much the "
             "LLM-as-a-judge varies by itself.")
DOWNLOADS = " It also downloads promptfoo {version} with npx."  # in the same question
ASK_TIMES = 2  # a paid re-check asks each answer twice: its own wobble is seen
WOBBLE = ("Asked twice, your new LLM-as-a-judge changed its own grade on {k} of your {n}. "
          "Differences that small can come from that alone.")
STEADY = "Asked twice, your new LLM-as-a-judge kept its own grade on all {n}."
GO_AHEAD = "Go ahead? [y/N] "
CAN_WRITE = "Your LLM-as-a-judge is an agent that can change files when it runs."
NOT_ASKED = "Your LLM-as-a-judge was not asked."
NEXT_YES = "Next: run `{command}` in your terminal to answer, or `{command} --yes` to go ahead."
NEXT_LATER = "Next: run `{command}` again when you are ready to re-check your LLM-as-a-judge."
NEXT_NOT_MARKED = ("Next: run your eval on the questions you marked, then run `{command}` "
                   "again; or start over on your new answers with `{new}`.")
NEXT_SAME = "Next: nothing to do. Run `{command}` again after you change your LLM-as-a-judge."
NEXT_REST = ("Next: {marks} {were} not re-checked. Run `{command}` again to ask your "
             "LLM-as-a-judge about them.")
NEXT_EVAL = "Next: run your eval again, then run `{command}`."
NEXT_RUN_EVAL = "Next: run your eval once, then run `{command}` again."
NEXT_WORSE = "go back to {back}, or change your LLM-as-a-judge and run `{command}` again."
# A judge whose results hold no rule (a table): it changes only where the eval keeps it
NEXT_WORSE_TABLE = ("go back to your old LLM-as-a-judge, or change its rule; then run your eval "
                    "and `{command}`.")
SWITCHED = ("Your results now come from {new}, not {old}.",
            "judgekeeper can't compare LLM-as-a-judge results across two eval tools.")
NEXT_FRESH = "Next: run `{command}` to start fresh with {new}."
STEP = "Step 5 of 5: Re-check"
NEXT_INSTALL = "Next: run `{install}` in your project, then run `{command}` again."
NEXT_KEY = "{step}, then run `{command}` again."  # the key the judge needs is not set
CLOSE = "This was a close copy of your LLM-as-a-judge, not an exact one: {why}."
WRONG_MODEL = "judgekeeper asked the wrong model ({used}, not {new}), so this check is not saved."
NEXT_WRONG_MODEL = ("Next: check which model your eval's config names for your LLM-as-a-judge, run "
                    "your eval, then run `{command}` again.")
TRACE_WHY = "your LLM-as-a-judge reads traces, which may have changed since your eval ran"


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
    counted = batches.counted_labels(data, marks.read(ws.marks).counted())  # not a new batch's
    return State(ws=ws, path=path, data=data, marks=counted, saved=saved)


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
        where = root
        if start._saved(root) is None:
            options["tool"] = data.get("tool")
            where = start.results_path(root, data)  # a file given by path: read there
        given = fp.get("model") if fp.get("model_source") == start.GIVEN_BY_YOU else None
        try:
            found = start.find_judge(where, judge_model=given, **options)
        except start.StartError:
            if given is None:
                raise
            found = start.find_judge(where, **options)  # the results name it now
        return (start.rebased(found, root) if where != root else found), None
    except (start.StartError, start.Stop, RecordsError, OSError, ValueError) as e:
        tool = data.get("tool")
        if tool in find.TOOLS and not find.search(root).readable(tool):
            name = "" if tool == "table" else f"{find.NAMES.get(tool, tool)} "
            return None, f"judgekeeper finds no {name}results in this folder ({Path(root).name})"
        why = (scrub(str(e)) if str(e) and not isinstance(e, start.Stop)
               else "they need a choice first, such as which results to read: run "
                    f"`{program()}` to make it")
        return None, (f"judgekeeper can't read your LLM-as-a-judge {data.get('metric')} in your "
                      f"newest results: {why}")


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
            line += " Your LLM-as-a-judge's rule and model are the same."
        return line
    return f"Your LLM-as-a-judge changed: {', '.join(changed)}."


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
    install: str | None = None  # the command that installs the judge's tool (Plan.install)
    wobble: tuple[int, int] | None = None  # asked twice: (answers whose grades differ, of)
    wrong_model: tuple[str, str] | None = None  # (a model a call used, the new judge's)
    key_step: str | None = None  # the key the judge needs is not set: where to set it
    unchecked: int = 0  # marked answers asked about that did not come back counted


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


class View:
    """A workspace seen through the newest results: the new judge's tool, files, name and
    fingerprint; everything else (the marked answers, the pool's groups) is the saved check's.
    `data()["saved"]` is the saved check's own start.json."""

    def __init__(self, ws: Workspace, found):
        self.ws, self.found = ws, found
        self.root, self.dir, self.start = ws.root, ws.dir, ws.start

    def data(self) -> dict:
        saved = self.ws.data()
        f = self.found
        return {**saved, "tool": f.tool, "results_files": list(f.used), "metric": f.metric,
                "judge": f.judge, "fingerprint": f.fingerprint, "saved": saved}


def ask(state: State, found, setup: dict, ids: list[str], said, yes: bool,
        rest: bool = False) -> Asked | None:
    """Ask the judge in the newest results about the marked answers `ids` (`rest`: the ones
    not found free), once the person said yes to the calls it makes. None without a terminal
    and without --yes: the question is said, nothing is asked."""
    from judgekeeper.again.fresh import NOT_COUNTED, AgainError, write_files

    out = Asked()
    ws = state.ws
    view = View(ws, found)
    plan = again.make_plan(ws, again.AgainOptions(times=ASK_TIMES), dry=True, new=view,
                           only=set(ids))
    if plan.status == again.CANT:
        out.reasons.append(plan.plain or f"Your LLM-as-a-judge can't be asked again: {plan.why}.")
        out.not_marked = plan.why == again.NOT_MARKED
        out.install = plan.install
        return out
    if not plan.key_ok:  # which key, and where to set it: never its value
        out.reasons += [*plan.key_lines, NOT_ASKED]
        out.key_step = plan.key_step or "set the key your LLM-as-a-judge needs"
        return out
    wrong = wrong_model(_handed(plan), found)
    if wrong:  # (a): what judgekeeper would hand the eval tool is not the new judge
        out.wrong_model = wrong
        return out
    said.say()
    _wrap(said, ASK_FIRST.format(which="the other " if rest else "your ",
                                 n=_n(len(ids), "marked answer"), calls=_n(plan.calls, "AI call"),
                                 download=downloads(plan)))
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
        out.reasons.append(f"Asking your LLM-as-a-judge again did not finish: {scrub(str(e))}")
        out.calls, out.unchecked = plan.calls, len(ids)
        return out
    wrong = wrong_model(fresh.models_used(), found)
    if wrong:  # (b): the calls say another model answered: nothing is kept
        shutil.rmtree(plan.folder, ignore_errors=True)
        out.wrong_model, out.calls = wrong, plan.calls
        return out
    write_files(ws, plan, fresh, prefix="check", metric=found.metric)
    out.verdicts = {i: v[0] for i, v in fresh.verdicts.items()}  # the first, like one run
    out.wobble = (sum(len(set(v)) > 1 for v in fresh.verdicts.values()), len(fresh.verdicts))
    out.calls, out.unchecked = plan.calls, len(fresh.not_counted)
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


def downloads(plan) -> str:
    """The sentence the question about the calls adds when running the judge downloads its
    tool first (npx), else ""."""
    return DOWNLOADS.format(version=plan.tool_version) if plan.download else ""


def _handed(plan) -> set[str]:
    """The models judgekeeper hands the eval tool for a re-ask: promptfoo's grader on each
    test, else the plan's model."""
    from judgekeeper.again.promptfoo import graders_handed

    if plan.tool == "promptfoo":
        return graders_handed(plan)
    return {plan.model} if isinstance(plan.model, str) and plan.model else set()


# Provider and API words a tool writes before a model's own name ("openai:chat:", "openai:/",
# "anthropic/", "anthropic:messages:")
_PREFIX = re.compile(r"^(?:openai|anthropic|azure|azureopenai|google|vertex|gemini|bedrock|"
                     r"ollama|mistral|groq|deepseek|xai|openrouter|together|litellm|"
                     r"huggingface|hf)(?::/|:|/)")
_API = re.compile(r"^(?:chat|messages|completion|responses):")


def _model_name(model: str) -> str:
    """A model's name without the provider and API words before it: "openai:chat:gpt-4.1",
    "openai/gpt-4.1" and "gpt-4.1" are one; the rest of the name is kept whole."""
    return _API.sub("", _PREFIX.sub("", model.strip().lower(), count=1), count=1)


def wrong_model(used: set[str], found) -> tuple[str, str] | None:
    """(a model the calls used, the new judge's model) when a call used another model than
    the one judgekeeper names as the new judge (found.models), else None."""
    named = [m for m in (found.models or [found.fingerprint.get("model")])
             if isinstance(m, str) and m]
    names = {_model_name(m) for m in named}
    other = sorted(m for m in used if _model_name(m) not in names)
    return (other[0], named[0]) if named and other else None


# The paired test --------------------------------------------------------------------------------

def _old_verdicts(state: State, old: dict) -> dict[str, str]:
    """The old judge's (`old`, a setup) verdicts on the marked answers: the last check's for
    that setup, else start.json's: the grades of the judge judge.json keeps (_adopt), or for
    an earlier judge the grades the marks were made on (`picked`)."""
    data = state.data
    pool = {q["id"]: q["group"] for q in data.get("queue") or []}
    setup_hash = judge_setup.hash_of(old)
    if setup_hash != state.saved["setup_hash"]:
        pool.update((data.get("picked") or {}).get("groups") or {})
    return {**pool, **_read_verdicts(state.ws, setup_hash)}


def _picks(state: State) -> tuple[dict[str, tuple[int, str]], dict[tuple[int, str], int]]:
    """(the stratum each mark was picked from, the strata's sizes) (batches.strata): its batch
    and start.json's queue group, or the group a re-check kept (start_label.picked_numbers)."""
    return batches.strata(state.data)


def _rates(marked: dict[str, str], verdicts: dict[str, str], picked: dict,
           pool: dict) -> dict:
    """TPR and TNR of `verdicts` on the marks, re-weighted by the strata (or groups) they were
    picked from (weighted.general_strata): the numbers the report shows."""
    items = [(picked.get(i, v), marked[i], v) for i, v in verdicts.items() if i in marked]
    if not items or not sum(pool.values()):
        return {"tpr": None, "tnr": None}
    out = weighted.general_strata(items, pool, draws=200)
    return {"tpr": out["tpr"], "tnr": out["tnr"]}


def groups(marked: dict[str, str], old: dict[str, str], new: dict[str, str],
           picked: dict[str, str] | None = None, pool: dict[str, int] | None = None) -> dict:
    """Per group of marks (passed, failed): of the marks with an old and a new verdict, how
    many each judge got right, how many went from right to wrong and from wrong to right,
    the range on the paired change and its verdict (targets.paired_verdict); and each
    judge's re-weighted rate (`old_rate`, `new_rate`) when the pick groups and pool sizes are
    given."""
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


# After a rule change: marks made after it (they were not looked at to write it) ---------------

WRITTEN_FROM = ("This includes marks you looked at to write this rule, so it may read a few "
                "points high.")
AFTER_NONE = "On marks made after this change: {said}."
AFTER_MORE = " Mark more answers to see it on answers it was not written for."
AFTER_NUMBERS = 10  # of each kind: their numbers are shown
AFTER_HEADLINE = 15  # of each kind: they decide the verdict


def _checked_before(state: State, old: dict, new: dict) -> list[str]:
    """The times this same change was checked before (history.jsonl)."""
    pair = (judge_setup.hash_of(old), judge_setup.hash_of(new))
    return [str(x.get("time") or "") for x in _history(state.ws)
            if (judge_setup.hash_of(x.get("before") or {}),
                judge_setup.hash_of(x.get("after") or {})) == pair]


def _first_seen(state: State, old: dict, new: dict) -> str:
    """When this change was first checked, else now."""
    return min(_checked_before(state, old, new), default=utc_now())


def _made_after(state: State, since: str, tested: dict[str, str]) -> dict[str, str]:
    """The marks made after `since` that the new judge was tested on: {id: mark}."""
    last = marks.read(state.ws.marks).last
    return {i: m for i, m in state.marks.items()
            if i in tested and str((last.get(i) or {}).get("at") or "") > since}


def _after_lines(fresh: dict[str, str], tested: dict[str, str], picked: dict[str, str],
                 pool: dict[str, int], wobble: float | None = None,
                 every: bool = False) -> list[str]:
    """The new judge on the marks made after the change: none yet, how many so far, or (with
    AFTER_NUMBERS of each) its numbers with their ranges, widened for its `wobble` (the share
    of answers it graded differently when asked twice). `every`: every answer is marked, so
    none is left to mark."""
    from judgekeeper.start_label import side_sentence

    kinds = list(fresh.values())
    n_pass, n_fail = kinds.count("pass"), kinds.count("fail")
    if min(n_pass, n_fail) < AFTER_NUMBERS:
        said = f"{len(fresh)} so far" if fresh else "none" if every else "none yet"
        return [AFTER_NONE.format(said=said) + ("" if every else AFTER_MORE)]
    items = [(picked.get(i, tested[i]), fresh[i], tested[i]) for i in fresh]
    out = weighted.general_strata(items, pool, wobble=wobble)
    return [f"On marks made after this change ({n_pass} Pass, {n_fail} Fail):",
            *(f"  {side_sentence(k, out[k], out[f'{k}_interval'])}" for k in ("tpr", "tnr"))]


def _say_groups(said: Said, g: dict) -> None:
    for key, _, _title in GROUPS:
        for line in _group_lines(key, g[key]):
            said.say(line)
        said.say()


def _points(x: float) -> int:
    return round(abs(x) * 100)


def _count(k: int) -> str:
    return str(k) if k else "none"


def paired_lines(g: dict) -> list[str]:
    """The verdict on one group, in counts only (never which answers changed): how many went
    from right to wrong, and from wrong to right."""
    wrong, right = g["now_wrong"], g["now_right"]
    if g["verdict"] == "worse":
        went = f"{wrong} {'answer' if wrong == 1 else 'answers'} went"
        return [f"Worse: {went} from right to wrong, and {_count(right)} from wrong to right.",
                (f"That is about {_points(g['change'])} points lower (between "
                 f"{_points(g['high'])} and {_points(g['low'])}).")]
    if g["verdict"] == "not_sure":
        return [(f"Not sure: {_count(wrong)} went from right to wrong, and {_count(right)} from "
                 f"wrong to right. It could be up to {_points(g['low'])} points worse.")]
    first = (f"{VERDICT_WORDS['no_drop']}: {_count(wrong)} went from right to wrong, "
             f"{_count(right)} from wrong to right.")
    if g["low"] >= 0:
        return [first, "None of its range is a drop."]
    return [first, f"These marks can't rule out a drop of up to {_points(g['low'])} points."]


def _group_lines(key: str, g: dict) -> list[str]:
    """One group: how often the old and the new judge agreed with the person's marks, then
    the verdict on the change."""
    if not g["n"]:
        return [f"  {SAID[key]}:  none could be re-checked."]
    said = SAID[key].split()[1]  # "passed" or "failed"
    return [(f"  You {said} {g['n']} {'answer' if g['n'] == 1 else 'answers'}. Your old "
             f"LLM-as-a-judge agreed with you on {g['old_right']}, your new LLM-as-a-judge on "
             f"{g['new_right']}."),
            *(f"    {line}" for line in paired_lines(g))]


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
    make_private(path.parent)
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
        said.say("Next: " + next_marks(state.ws, f"run `{program('mark')}` to mark more answers."))
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
        return "Your LLM-as-a-judge has not changed since you marked your answers."
    return f"Your LLM-as-a-judge has not changed since your last check{f' ({day})' if day else ''}."


# How many changes the marks have helped pick -------------------------------------------------
# A pick: a `fix` test on these marks, or a check of a rule or pass-mark change `fix` tested
# (a change made by looking at the marks). A model change, a tool update, or a rule or pass mark
# changed without `fix` is not one. After PICKS_ASK picks, until PICK_MARKS marks are made after
# the last one, the marks may flatter the judge.

PICKS_ASK = 3
PICK_MARKS = 10
NEXT_NEW_MARKS = "run `{mark}` to mark {n} new answers, then run `{command}` again."


def is_pick(line: dict) -> bool:
    """Whether a history.jsonl line is a pick (above). A check line from before `from_fix` was
    kept counts its rule or pass-mark change."""
    if line.get("kind") == "fix":
        return True
    changed = line.get("changed") or []
    return line.get("kind") == "check" and line.get("from_fix", True) is not False and any(
        c == "rule changed" or str(c).startswith("pass mark") for c in changed)


def rule_changed(changed: list[str]) -> bool:
    return is_pick({"kind": "check", "changed": changed})


def from_fix(ws: Workspace, old: dict, new: dict) -> bool:
    """Whether the change from `old` to `new` brings in a rule or a pass mark `fix` tested on
    these marks: one written by looking at them."""
    from judgekeeper import fix

    rule = new.get("rule_hash")
    if rule != old.get("rule_hash") and rule in {
            x.get("rule_hash") for x in _history_all(ws) if x.get("kind") == "fix"}:
        return True
    split = fix.read_split(ws)
    mark = (new.get("pass_mark") or {}).get("mark")
    return (mark != (old.get("pass_mark") or {}).get("mark") and split is not None
            and any(t.get("kind") == "pass mark" and t.get("new") == mark
                    for t in split.tests))


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


def picks_lines(p: dict, every: bool = False) -> list[str]:
    """How many changes the marks helped pick, said once; with PICKS_ASK picks, that they may
    flatter the judge, and (unless `every` answer is marked: none is left) to mark new ones."""
    if not p["n"]:
        return []
    picked = f"These marks have helped pick {plural(p['n'], 'change')}"
    if not p["ask"]:
        return [picked + "."]
    return [f"{picked}, so they may now flatter your LLM-as-a-judge."
            + ("" if every else f" Mark {PICK_MARKS} new answers for a fair check.")]


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


GRADES = "Your LLM-as-a-judge's grades changed on {k} of your marked answers."
BACK = ("Your LLM-as-a-judge is back to the one you marked with ({model}). Your marks' result "
        "still holds.")
HOLD = "Your newest results hold {k} of your {n}."  # some marked answers, not all
ADDED = "You added {n} since your last check."


def grades_changed(ws: Workspace, found) -> int:
    """For a judge whose results hold no rule (a table, say): on how many marked answers its
    grades in the newest results differ from the ones judge.json's judge gave. A rule changed
    in code shows only there; the new grades are in the file, so no AI call re-checks them."""
    saved = judge_setup.read(ws)
    if saved is None or saved["setup"].get("rule_hash") is not None or found.rule is not None:
        return 0
    try:
        data = ws.data()
    except (OSError, ValueError):
        return 0
    marked = marks.read(ws.marks).counted()
    old = {**{q["id"]: q["group"] for q in data.get("queue") or []},
           **_read_verdicts(ws, saved["setup_hash"])}
    return sum(1 for i, v in _free(found, marked).items() if i in old and old[i] != v)


def _added_since_check(state: State, new: dict | None) -> tuple[dict | None, list[str]]:
    """(the judge before the last check, the marks it did not re-check) when that check moved
    judge.json to `new`: marks made after it, or that its results did not hold."""
    if new is None or judge_setup.hash_of(new) != state.saved["setup_hash"]:
        return None, []
    last = next((x for x in reversed(_history(state.ws))
                 if judge_setup.hash_of(x.get("after") or {}) == state.saved["setup_hash"]),
                None)
    if last is None or not isinstance(last.get("before"), dict):
        return None, []
    before = last["before"]
    if not judge_setup.changes(before, new):
        return None, []
    tested = _read_verdicts(state.ws, state.saved["setup_hash"])
    return before, [i for i in state.marks if i not in tested]


def _made_since_last_check(state: State, ids: list[str]) -> int:
    """How many of the marks `ids` (not re-checked yet) were added since the last check: the
    marks there are now, less the ones it counted."""
    checks = _history(state.ws)
    if not ids or not checks:
        return 0
    before = checks[-1].get("marks")
    return min(len(ids), max(0, len(state.marks) - before)) if isinstance(before, int) else 0


def _adopt(ws: Workspace, found, tested: dict[str, str]) -> None:
    """After a check that is not "Worse", the marks test the new judge: start.json takes its
    grades (on the marks re-checked and the answers in the newest results), its rule, model
    and fingerprint, and pool-judge.jsonl its grades and reasons, so the result and `fix` are
    about the judge in the newest results. The groups the marks were picked from, and those
    groups' sizes, stay in `picked` (start_label.picked_numbers)."""
    from judgekeeper.fingerprint import JudgeFingerprint
    from judgekeeper.judgments import judgment_to_record, read_run, write_run
    from judgekeeper.runners.base import Judgment
    from judgekeeper.start_label import _write_json

    data = ws.data()
    queue = data.get("queue") or []
    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    answers = {a.id: a for a in found.pool.answers if a.source in newest}
    now = {**{i: a.verdict for i, a in answers.items()}, **tested}
    picked = data.get("picked") or {"pool": data.get("pool"),
                                    "groups": {q["id"]: q["group"] for q in queue}}
    for q in queue:  # a batch added since the last check: picked by the grades it has now
        picked["groups"].setdefault(q["id"], q["group"])
    queue = [{**q, "group": now.get(q["id"], q["group"])} for q in queue]
    kinds = [q["group"] for q in queue]
    data.update(picked=picked, queue=queue, rule=found.rule, one_rule=found.one_rule,
                judge=found.judge, fingerprint=scrub_fingerprint(found.fingerprint),
                pass_mark=found.pass_mark, results_files=list(found.used),
                pool={**(data.get("pool") or {}), "pass": kinds.count("pass"),
                      "fail": kinds.count("fail")},
                checked_at=utc_now())
    try:
        head, records = read_run(ws.pool_judge)
    except (OSError, ValueError):
        head, records = None, {}
    if head is not None:
        given = found.fingerprint.get("model_source") is not None
        fp = JudgeFingerprint.from_dict(found.fingerprint)
        lines = []
        for i, rec in records.items():
            a = answers.get(i)
            if a is not None and i in now:
                rec = judgment_to_record(i, Judgment(verdict=a.verdict, raw_score=a.score,
                                                     rationale=a.reason),
                                         a.fingerprint.with_(model=found.fingerprint["model"])
                                         if given else a.fingerprint)
            elif i in now and now[i] != rec.get("verdict"):  # asked again: no reason kept
                rec = judgment_to_record(i, Judgment(verdict=now[i], raw_score=None,
                                                     rationale=""), fp)
            lines.append(rec)
        write_run(ws.pool_judge, head.get("run", 1), head.get("anchors_sha256", ""), fp,
                  lines, source=head.get("source"), normaliser=head.get("normaliser"))
    _write_json(ws.start, data)


def full(path: str, said: Said, yes: bool = False) -> int:
    state = _state(path)
    if state is None or not state.enough:
        return _not_set_up(path, state, said)
    old = state.saved["setup"]
    now, problem = _now(state)
    found, new = (now.found, now.setup) if now is not None else (None, None)
    before, added = _added_since_check(state, new) if now is not None else (None, [])
    no_rule = new is not None and new.get("rule_hash") is None  # its grades tell a change
    checks = _history(state.ws)
    moved = bool(checks) and new is not None and judge_setup.hash_of(
        checks[-1].get("after") or {}) != judge_setup.hash_of(new)  # back from the last check
    if now is not None and found is None and (judge_setup.changes(old, new) or added or
                                               no_rule or moved):
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
        said.say(problem if problem.endswith(".") else problem + ".")  # one stop
        said.say()
        said.say(NEXT_RUN_EVAL.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    back = back_to_marked(state.ws, found) if found is not None else None
    if back:
        said.say(back)
        marks.append(state.ws.history_jsonl, scrub_value({
            "time": utc_now(), "kind": "check", "trigger": "back", "before": old, "after": new,
            "changed": ["back to the LLM-as-a-judge the marks were made on"],
            "marks": len(state.marks),
            "free": 0, "asked": 0, "calls": 0, "groups": {}}))
        _report(state.ws)  # no "Worse" from the other judge on it
        said.say()
        said.say(NEXT_SAME.format(command=_command(state)))
        return EXIT_OK
    changed = judge_setup.changes(old, new)
    if not changed and added:  # marks made since the last check: that change again
        old, changed = before, judge_setup.changes(before, new)
    grades = 0 if changed or found is None else grades_changed(state.ws, found)
    if not changed and not grades:
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

    said.say(_change_line(old, new, changed, full=True) if changed
             else GRADES.format(k=grades))
    new_marks = _made_since_last_check(state, added)
    if new_marks:  # only marks really made since; the others the last check could not test
        said.say(ADDED.format(n=_n(new_marks, "mark")))
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
    if asked.wrong_model:
        said.say()
        said.say(WRONG_MODEL.format(used=asked.wrong_model[0], new=asked.wrong_model[1]))
        said.say()
        said.say(NEXT_WRONG_MODEL.format(command=_command(state)))
        return EXIT_USAGE
    tested = {**free, **cached, **asked.verdicts}
    if not tested:
        for line in asked.reasons:
            said.say(line)
        said.say()
        later = (NEXT_INSTALL if asked.install else NEXT_NOT_MARKED if asked.not_marked
                 else NEXT_LATER)
        if asked.key_step:
            later = "Next: " + NEXT_KEY
        said.say(later.format(command=_command(state), new=program("--new"),
                              install=asked.install, step=asked.key_step))
        return EXIT_NEEDS_YOU

    n, total = len(tested), len(state.marks)
    if free and not asked.verdicts and not cached:
        said.say("Re-checked with no AI call, from your new results.")
    for line in asked.reasons:
        if free and asked.not_marked and line == again.NOT_MARKED_PLAIN:
            line = HOLD.format(k=len(free), n=_n(total, "marked answer"))
        said.say(line)
    said.say()
    on = f"all {total} of your marks" if n == total else f"{n} of your {_n(total, 'mark')}"
    old_verdicts = _old_verdicts(state, old)
    picked, pool = _picks(state)
    g = groups(state.marks, old_verdicts, tested, picked, pool)
    pick = rule_changed(changed) and from_fix(state.ws, old, new)
    fresh = _made_after(state, _first_seen(state, old, new), tested) if pick else None
    kinds = list(fresh.values()) if fresh is not None else []
    if min(kinds.count("pass"), kinds.count("fail")) >= AFTER_HEADLINE:
        g = groups(fresh, old_verdicts, tested, picked, pool)  # the headline now
        said.say(f"Re-checked on the {len(fresh)} marks you made after this change:")
        said.say()
        _say_groups(said, g)
        said.say(f"On {on}:")
        said.say()
        _say_groups(said, groups(state.marks, old_verdicts, tested, picked, pool))
        said.say(WRITTEN_FROM)
        said.say()
    else:
        said.say(f"Re-checked on {on}:")
        said.say()
        _say_groups(said, g)
        if fresh is not None:
            said.say(WRITTEN_FROM)
            wobble = asked.wobble[0] / asked.wobble[1] if asked.wobble and asked.wobble[1] \
                else None
            for line in _after_lines(fresh, tested, picked, pool, wobble,
                                     every=every_marked(state.ws)):
                said.say(line)
            said.say()
    if asked.close:
        said.say(CLOSE.format(why=asked.close))
        said.say()
    if asked.wobble and asked.wobble[1]:
        k, of = asked.wobble
        said.say(WOBBLE.format(k=k, n=_n(of, "answer")) if k
                 else STEADY.format(n=_n(of, "answer")))
        said.say()
    drop = targets.smallest_drop(g["passed"]["n"], g["failed"]["n"], g["passed"]["old"],
                                 g["failed"]["old"])
    worse = [k for k in ("failed", "passed") if g[k]["verdict"] == "worse"]
    unsure = [k for k in ("failed", "passed") if g[k]["verdict"] == "not_sure"]
    picked = picks(state.ws, now=pick  # a pick, unless checked before
                   and not _checked_before(state, old, new))
    every = every_marked(state.ws)
    for line in picks_lines(picked, every):
        said.say(line)
    if picks_lines(picked):
        said.say()
    if worse:
        said.say("Next: " + worse_step(old, new, _command(state)))
    elif asked.key_step:  # the rest can be re-checked once the key is set
        said.say("Next: " + NEXT_KEY.format(step=asked.key_step, command=_command(state)))
    elif (picked["ask"] or unsure) and n < total and every:  # marks the results did not hold:
        # more marks can't be made, and new answers would not help
        said.say("Next: " + NEXT_ALL_QUESTIONS.format(command=_command(state)))
    elif picked["ask"]:
        said.say("Next: " + next_marks(state.ws, NEXT_NEW_MARKS.format(
            mark=program("mark"), n=PICK_MARKS - picked["new_marks"], command=_command(state))))
    elif unsure:
        said.say("Next: " + next_marks(state.ws, NEXT_NOT_SURE.format(
            mark=program("mark"), command=_command(state))))
    elif asked.unchecked:  # asking again asks about them
        said.say(NEXT_REST.format(marks=_n(asked.unchecked, "mark"),
                                  were="was" if asked.unchecked == 1 else "were",
                                  command=_command(state)))
    else:
        said.say(NEXT_SAME.format(command=_command(state)))
    exit_worse = any(g[k].get("exit_worse") for k in g)
    new_rates = _new_rates(state.marks, tested, *_picks(state), asked.wobble) if worse else None

    flipped = [i for i in tested if i in old_verdicts and old_verdicts[i] != tested[i]]
    line = scrub_value({
        "time": utc_now(), "kind": "check", "trigger": "by hand", "before": old, "after": new,
        "changed": changed or [f"grades changed on {_n(grades, 'marked answer')}"],
        "marks": total, "free": len(free), "asked": len(asked.verdicts),
        "calls": asked.calls, "exact": "close" if asked.close else "exact", "groups": g,
        "smallest_drop": drop, "flipped": flipped, "from_fix": pick,
        "made_after_change": None if fresh is None else len(fresh),
        **({"new_rates": new_rates} if new_rates else {})})
    if not _same_as_last(state, line):
        marks.append(state.ws.history_jsonl, line)
    held = exit_worse  # "Worse", or "Not sure" with a big drop: the next check says it again
    if not held or judge_setup.hash_of(old) != judge_setup.hash_of(new):
        _save_verdicts(state.ws, new, found, tested)  # a "Worse" of the same setup (a table's
        # new grades) keeps the old grades: the next check says worse again
    if not held:  # after "Worse" the old judge stays the reference until it comes back
        judge_setup.save(state.ws, new, found.metric)
        _adopt(state.ws, found, tested)
        _refresh_mistakes(state.ws)
    _report(state.ws, adopted=not held,
            worse=worse_step(old, new, _command(state)) if worse else None)
    return EXIT_WORSE if exit_worse else EXIT_OK


def _new_rates(marked: dict[str, str], tested: dict[str, str], picked: dict[str, str],
               pool: dict[str, int], wobble) -> dict:
    """The new judge's TPR and TNR on the marks it was tested on, each with its range, as the
    result's are worked out (weighted.general_strata): for report.html's Last check block."""
    items = [(picked[i], marked[i], v) for i, v in tested.items() if i in marked and i in picked]
    share = wobble[0] / wobble[1] if wobble and wobble[1] else None
    out = weighted.general_strata(items, pool, wobble=share)
    return {k: out[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval")}


def worse_step(old: dict, new: dict, command: str) -> str:
    """The next step after "Worse" (without "Next: "), the same in `check`, `judgekeeper` and
    report.html: go back to the old judge (or tool version), or change the judge."""
    if judge_setup.tool_only(old, new):
        tool = find.NAMES.get(new.get("tool"), new.get("tool"))
        return NEXT_WORSE.format(back=f"the old version of {tool} ({old.get('tool_version')})",
                                 command=command)
    if new.get("rule_hash") is None:
        return NEXT_WORSE_TABLE.format(command=command)
    return NEXT_WORSE.format(back="the old LLM-as-a-judge", command=command)


def last_check(ws: Workspace) -> dict | None:
    """The last check when it found the new judge worse, as report.html says it at the top:
    the new judge's name and the lines the terminal gave for each group. None otherwise."""
    checks = _history(ws)
    last = checks[-1] if checks else {}
    g = last.get("groups") if isinstance(last.get("groups"), dict) else {}
    if not any(isinstance(x, dict) and x.get("verdict") == "worse" for x in g.values()):
        return None
    after = last.get("after") if isinstance(last.get("after"), dict) else {}
    names = [str(m) for m in after.get("models") or []]
    lines = []
    for key, _, _title in GROUPS:
        if isinstance(g.get(key), dict) and "n" in g[key]:
            try:
                lines.append(" ".join(x.strip() for x in _group_lines(key, g[key])))
            except (KeyError, TypeError):
                continue
    rates = last.get("new_rates") if isinstance(last.get("new_rates"), dict) else {}
    if rates:
        from judgekeeper.front import estimate_lines

        lines += [x.strip() for x in estimate_lines(rates)[1:]]
    return {"judge": ", ".join(names) or None, "lines": lines}


def open_worse(ws: Workspace, found) -> dict | None:
    """The last check, when it found the judge in the newest results (`found`) worse than the
    one the marks test, and no mark was made since: checking again says the same, so the next
    step is worse_step. For a judge whose results hold no rule (a table), only while its grades
    are the ones that check saw. None otherwise."""
    saved = judge_setup.read(ws)
    checks = _history(ws)
    if saved is None or not checks:
        return None
    last, now = checks[-1], judge_setup.of(found)
    if (judge_setup.hash_of(last.get("before") or {}) != saved["setup_hash"]
            or judge_setup.hash_of(last.get("after") or {}) != judge_setup.hash_of(now)):
        return None
    if not any(isinstance(g, dict) and g.get("verdict") == "worse"
               for g in (last.get("groups") or {}).values()):
        return None
    read = marks.read(ws.marks)
    data = ws.data()
    counted = batches.counted_labels(data, read.counted())  # as check: not a waiting batch's
    time = str(last.get("time") or "")
    if any(str((read.last.get(i) or {}).get("at") or "") > time for i in counted):
        return None
    if now.get("rule_hash") is None:  # a table: the same grades as that check saw
        old = {**{q["id"]: q["group"] for q in data.get("queue") or []},
               **_read_verdicts(ws, saved["setup_hash"])}
        flips = sorted(i for i, v in _free(found, counted).items() if i in old and old[i] != v)
        if flips != sorted(last.get("flipped") or []):
            return None
    return {"before": last["before"], "after": now}


def _marked_setup(ws: Workspace) -> dict | None:
    """The judge the marks were made on: the one the first check since they began started
    from. None before any check."""
    since = str((marks.read(ws.marks).header or {}).get("created_at") or "")
    return next((x["before"] for x in _history(ws)
                 if str(x.get("time") or "") >= since and isinstance(x.get("before"), dict)),
                None)


def back_to_marked(ws: Workspace, found) -> str | None:
    """The judge in the newest results (`found`) is the one the marks were made on, and the
    last check was of another judge: the line that says so, else None. When that check moved
    the marks to the other judge, they test the judge they were made on again, with the grades
    they were made on (no AI call, _restore); after a "Worse", nothing was moved, and that
    "Worse" no longer applies (open_worse)."""
    marked, saved, checks = _marked_setup(ws), judge_setup.read(ws), _history(ws)
    if marked is None or saved is None or not checks:
        return None
    now = judge_setup.of(found)
    if (judge_setup.hash_of(now) != judge_setup.hash_of(marked)
            or judge_setup.hash_of(checks[-1].get("after") or {}) == judge_setup.hash_of(now)):
        return None
    if saved["setup_hash"] != judge_setup.hash_of(now):
        _restore(ws, found, now)
    names = [re.split(r"[:/]", str(m))[-1] for m in now.get("models") or []]
    return BACK.format(model=", ".join(names) or "model not named")


def _restore(ws: Workspace, found, setup: dict) -> None:
    """The marks test the judge they were made on again (`found`, its `setup`): start.json
    takes back the grades the marks were picked by, judge.json that judge, and the result is
    made again from them."""
    from judgekeeper.start_label import _write_json

    data = ws.data()
    picked = data.get("picked") or {}
    groups = picked.get("groups") or {q["id"]: q["group"] for q in data.get("queue") or []}
    _adopt(ws, found, {i: groups[i] for i in marks.read(ws.marks).counted() if i in groups})
    data = ws.data()
    data["queue"] = [{**q, "group": groups.get(q["id"], q["group"])} for q in data["queue"]]
    data["pool"] = picked.get("pool") or data.get("pool")
    for key in ("picked", "checked_at"):
        data.pop(key, None)
    _write_json(ws.start, data)
    judge_setup.save(ws, setup, found.metric)
    _report(ws, adopted=True)


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


def _refresh_mistakes(ws: Workspace) -> None:
    """fix/mistakes.md describes the judge the marks test now (fix.refresh_mistakes)."""
    from judgekeeper import fix

    try:
        fix.refresh_mistakes(ws)
    except (OSError, ValueError, KeyError):
        pass  # the next `fix` writes it


def _report(ws: Workspace, adopted: bool = False, worse: str | None = None) -> None:
    """report.html again (when there is a result). `adopted`: the marks test the new judge
    now, so the result is made again from its grades (start_label.store_result): the report's
    counts, lists and kept-aside count all describe that one judge. `worse`: the next step
    after a "Worse" (worse_step)."""
    from judgekeeper.start_label import StartSession, store_result, write_report

    try:
        saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    try:
        if adopted and isinstance(saved, dict):
            store_result(ws, StartSession(ws), saved.get("command"), redraw=True)
        else:
            write_report(ws, worse=worse)
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
    hook = old_hook(path)
    if hook:
        for line in wrap(hook):
            _print(line)
        _print()
    _print(STEP)
    _print()
    return full(path, _Printed(), yes=yes)


__all__ = ["full", "groups", "run"]
