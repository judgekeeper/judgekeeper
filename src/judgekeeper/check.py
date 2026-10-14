"""`judgekeeper check`: when the judge changed, re-test it on the person's marks.

Marks are tests for the judge. The judge is its whole setup (judge_setup.py), read from the
newest results, never from the eval config; `.judgekeeper/judge.json` keeps the setup last
checked. Nothing here ever asks a question.

`check --fast` (git pre-commit, hooks): no AI call, no network.

| What is there                                    | What it says                       | Exit |
|--------------------------------------------------|------------------------------------|------|
| no marks, or under 15 Pass + 15 Fail             | nothing                            | 0    |
| the same setup                                   | nothing (one line at a terminal)   | 0    |
| the setup changed                                | what changed; Next: check          | 3    |
| the judge's config is newer than the results     | it is re-checked after the next    | 0    |
|                                                  | eval run                           |      |

`--fast` and `--hook` read the results (and with them inspect_ai or mlflow) only when they
changed: `results-seen.json` (local, never committed) remembers the setup of the newest results
by what the files it came from hold (the results, the lockfiles, judgekeeper.toml).

`check`: the same, then for a changed setup:
1. free first: marked answers whose exact text is in the newest results already have the new
   judge's verdict;
2. the rest only after the person's yes: `check` says how many answers and calls it would
   ask about and asks `Go ahead? [y/N]` at a terminal (Enter is no); without a terminal only
   `--yes` says yes, else it stops (exit 3) before anything is asked or saved. The person's
   own judge is then asked once about each, through `again/` (no menu);
3. a one-sided paired test per group (the answers the person passed, and failed): the old
   verdicts (the last check's for the previous setup, `verdicts/<hash>.jsonl`; else the
   results the marks were made on) against the new;
4. the lines below, a `history.jsonl` line (no answer text), the new verdicts in
   `verdicts/<hash>.jsonl` (ids and verdicts only, under a header with the setup and the
   judge's fingerprint), and judge.json moves to the new setup. When no answer could be
   tested, nothing is saved: the check stays pending.

Exit 0 (no drop seen, or nothing changed), 1 (worse in either group), 3 (the person is
needed: not enough marks, or nothing could be tested). `--hook` (Claude Code and Cursor
hooks) reads the hook's JSON on stdin and answers in hook JSON: the lines for the agent
(`additionalContext`) and one short line for the person (`systemMessage`), only when
something changed; it always exits 0 (the JSON is read only then, and 2 would block).

`--on` opens the "Turn on" page (keep.py), where only the person's click turns automatic
checks on; it needs 25 Pass and 25 Fail marks. `--off` takes out exactly what turning on
added; anyone may run it. Both keep the marks, history and verdicts.

`--ci` (hidden; judgekeeper's GitHub Action, `mode: full`) is `check` in GitHub Actions: the
team committed the marks, and their workflow, with the key as a secret, is the permission to
ask the judge (never one that can change files); checks.json, the person's, is not read.
`--fast` also works in a checkout holding only judge.json and history.jsonl.

`--baseline` (hidden; the page runs it after "Turn on") asks the current judge once about
every marked answer: its verdicts become the old ones the next check compares with, and how
often they differ from the original eval run is the judge's measured steadiness, which the
smallest-drop line uses from then on.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import __version__, find, judge_setup, marks, start, targets
from judgekeeper.fingerprint import utc_now
from judgekeeper.records import RecordsError
from judgekeeper.redact import one_line, scrub, scrub_value
from judgekeeper.start_label import Workspace
from judgekeeper.textio import describe_os_error, plural, program, quote_arg, write_replacing

EXIT_OK, EXIT_WORSE, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 1, 2, 3
CHECKS = "checks.json"  # written only by the "Turn on" page
VERDICTS = "verdicts"
SEEN = "results-seen.json"
LOCKFILES = ("package-lock.json", "uv.lock", "poetry.lock", "judgekeeper.toml")
WHOLE = 4_000_000  # bytes: a results file up to this size is hashed whole
ENDS = 64 * 1024  # bytes read from each end of a bigger one
MAX_ENTRIES = 20_000  # files in a results folder (an MLflow store) looked at, at most
WIDTH = 64  # the question's lines
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
GROUPS = (("passed", "pass", "Answers you passed"), ("failed", "fail", "Answers you failed"))

MATCHES = "judgekeeper: your judge matches your marks."
CONFIG_NEWER = ("Your judge's config changed after your last eval run; judgekeeper re-checks it "
                "after the next one.")
NOT_SET_UP = ("Your marks can't check your judge yet: that needs {n} you mark Pass and {n} you "
              "mark Fail.")
ASK_FIRST = ("To re-check, judgekeeper asks your new judge about {which}{n}. That is {calls}, "
             "paid with your own key.")
GO_AHEAD = "Go ahead? [y/N] "
CAN_WRITE = "Your judge is an agent that can change files when it runs."
NOT_ASKED = "Your judge was not asked."
NEXT_YES = "Next: run `{command}` in your terminal to answer, or `{command} --yes` to go ahead."
NEXT_LATER = "Next: run `{command}` again when you are ready to re-check your judge."
DOWNLOAD = ("Asking your judge would mean downloading promptfoo {version}; judgekeeper "
            "doesn't download anything by itself.")
NO_KEY = "The key your judge needs isn't set where judgekeeper runs, so your judge wasn't asked."
CLOSE = "This was a close copy of your judge, not an exact one: {why}."
TRACE_WHY = "your judge reads traces, which may have changed since your eval ran"
OFF = "Automatic checks are off, so judgekeeper doesn't ask your judge."
NOT_COMMITTED = ("Your marks are not in this checkout: `mode: full` needs .judgekeeper/start.json, "
                 "marks.jsonl and pool.jsonl committed.")
CI_ONLY = ("`--ci` is for judgekeeper's GitHub Action (action.yml), where your workflow allows "
           "asking your judge. On your computer, run `judgekeeper check`.")


def _terminal() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


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
    counts: tuple[int, int] | None = None  # (Pass, Fail) marks, when only history.jsonl says
    ci: bool = False  # in judgekeeper's GitHub Action: the workflow allows asking the judge

    @property
    def enough(self) -> bool:
        values = list(self.marks.values())
        n_pass, n_fail = self.counts or (values.count("pass"), values.count("fail"))
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


def _committed(path: str) -> State | None:
    """What a checkout holds when only what judgekeeper commits is there (judge.json and
    history.jsonl, as in CI): the judge last checked, its name, and how many marks the newest
    result had. None when marking never started there or there is no result."""
    from judgekeeper.start_again import _project

    given = Path(path)
    if not given.exists():
        return None
    ws = Workspace(_project(given))
    saved = judge_setup._saved(ws)
    if saved is None or ws.start.exists():
        return None
    counts = None
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "result":
            n_pass, n_fail = line.get("pass"), line.get("fail")
            if isinstance(n_pass, int) and isinstance(n_fail, int):
                counts = (n_pass, n_fail)
    if counts is None:
        return None
    data = {"tool": saved["setup"].get("tool"), "metric": saved.get("metric")}
    return State(ws=ws, path=path, data=data, marks={}, saved=saved, counts=counts)


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
        why = (scrub(str(e)) if str(e) and not isinstance(e, start.Stop)
               else "it would have to ask which results to read")
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
            return Now(seen["setup"], _newer(configs, Path(seen.get("newest") or ""))), None
    found, problem = _newest(state)
    if found is None:
        return None, problem
    setup = judge_setup.of(found)
    _remember(state, found, setup)
    return Now(setup, _config_newer(found), found), None


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


# --fast -----------------------------------------------------------------------------------------

def fast(path: str, say) -> int:
    state = _state(path) or _committed(path)
    if state is None or not state.enough:
        return EXIT_OK
    now, problem = _now(state)
    if now is None:
        say(problem + ".")
        return EXIT_OK
    old, new = state.saved["setup"], now.setup
    changed = judge_setup.changes(old, new)
    if changed:
        say(_change_line(old, new, changed, full=False))
        say(f"Next: run `{_command(state)}`.")
        return EXIT_NEEDS_YOU
    if now.config is not None:
        say(CONFIG_NEWER)
    elif _terminal():
        say(MATCHES)
    return EXIT_OK


# Asking the judge -------------------------------------------------------------------------------

class _Quiet:
    """The talk a tool's run gets: nothing is printed (the hook's output is JSON only)."""

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


def _can_write(setup: dict) -> bool:
    agent = setup.get("agent") or {}
    return setup.get("kind") == judge_setup.AGENT and agent.get("can_write") is not False


def _wrap(said, text: str) -> None:
    for line in textwrap.wrap(text, WIDTH):
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


def groups(marked: dict[str, str], old: dict[str, str], new: dict[str, str]) -> dict:
    """Per group of marks (passed, failed): how often the old and the new judge agree with
    the person, how many answers turned wrong and right, and the one-sided sign test."""
    out = {}
    for key, mark, _ in GROUPS:
        ids = [i for i in new if marked.get(i) == mark and i in old]
        n = len(ids)
        wrong = sum(old[i] == mark and new[i] != mark for i in ids)
        right = sum(old[i] != mark and new[i] == mark for i in ids)
        out[key] = {"n": n,
                    "old": sum(old[i] == mark for i in ids) / n if n else None,
                    "new": sum(new[i] == mark for i in ids) / n if n else None,
                    "now_wrong": wrong, "now_right": right,
                    "verdict": ("not tested" if not n else
                                "worse" if targets.got_worse(wrong, right) else "no drop seen")}
    return out


def _group_line(key: str, title: str, g: dict) -> str:
    if not g["n"]:
        return f"  {title}:  none could be re-checked."
    if g["verdict"] == "worse":
        did = "fails" if key == "passed" else "passes"
        said = "passed" if key == "passed" else "failed"
        end = f"Worse: it now {did} {_n(g['now_wrong'], 'answer')} you {said}."
    else:
        end = "No drop seen."
    return f"  {title}:  old judge {_pct(g['old'])}, new judge {_pct(g['new'])}.  {end}"


def _steadiness(ws: Workspace) -> tuple[float | None, float | None]:
    """(flip rate, rate of being right) from the newest baseline in history.jsonl."""
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return None, None
    for raw in reversed(text.splitlines()):
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "check" \
                and line.get("trigger") == "baseline" and line.get("asked"):
            return len(line.get("flipped") or []) / line["asked"], line.get("right")
    return None, None


def _drop_line(drop: int | None, measured: bool) -> str | None:
    if drop is None:
        return None
    how = " (from your judge's measured steadiness)" if measured else ""
    return f"This check can see a drop of {drop} points or more{how}."


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
    lines: list[str] = field(default_factory=list)
    person: str | None = None  # one short line for the person (the hook's systemMessage)

    def say(self, text: str = "") -> None:
        self.lines.append(one_line(text))


def _no_change(state: State) -> str:
    when = state.saved.get("first_seen")
    for line in _history(state.ws):
        when = line.get("time") or when
    day = _day(when)
    return f"No change in your judge since the last check{f' ({day})' if day else ''}."


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


def full(path: str, said: Said, trigger: str, edited: str | None = None,
         yes: bool = False) -> int:
    hook = trigger == "hook"
    state = _state(path)
    if state is not None:
        state.ci = trigger == "ci"
    if state is None or not state.enough:
        if hook:
            return EXIT_OK
        if state is None and trigger == "ci" and _committed(path) is not None:
            said.say(NOT_COMMITTED)
            return EXIT_NEEDS_YOU
        said.say(NOT_SET_UP.format(n=targets.ROUGH))
        said.say(f"Next: run `{program()}` to mark answers.")
        return EXIT_NEEDS_YOU
    old = state.saved["setup"]
    now, problem = _now(state)
    found, new = (now.found, now.setup) if now is not None else (None, None)
    if now is not None and found is None and judge_setup.changes(old, new):
        found, problem = _newest(state)  # remembered, but a re-check needs the answers
        new = judge_setup.of(found) if found is not None else new
    if problem:
        if hook:
            return EXIT_OK
        said.say(problem + ".")
        said.say("Next: ask the person to run their eval once, then run "
                 f"`{_command(state)}` again.")
        return EXIT_NEEDS_YOU
    changed = judge_setup.changes(old, new)
    if not changed:
        config = now.config
        if hook:
            if config is not None and edited and Path(edited).resolve() == config.resolve():
                said.say(CONFIG_NEWER)
            return EXIT_OK
        said.say(_no_change(state))
        if config is not None:
            said.say(CONFIG_NEWER)
        said.say()
        said.say("Next: nothing. Tell the person their judge has not changed since the last "
                 "check.")
        return EXIT_OK

    change = _change_line(old, new, changed, full=True)
    said.say(change)
    free = _free(found, state.marks)
    rest = [i for i in state.marks if i not in free]
    asked = (ask(state, found, new, rest, said, yes or state.ci, rest=bool(free)) if rest
             else Asked())
    if asked is None:
        said.say()
        said.say(NEXT_YES.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    tested = {**free, **asked.verdicts}
    short = ", ".join(changed)
    if not tested:
        for line in asked.reasons:
            said.say(line)
        said.say()
        said.say(NEXT_LATER.format(command=_command(state)))
        said.person = (f"judgekeeper: your judge changed ({short}); it could not be re-checked "
                       "yet.")
        return EXIT_NEEDS_YOU

    n, total = len(tested), len(state.marks)
    parts = [f"{len(free)} free from your new results"] if free else []
    parts += [f"{len(asked.verdicts)} asked again"] if asked.verdicts else []
    on = f"your {_n(total, 'mark')}" if n == total else f"{n} of your {_n(total, 'mark')}"
    said.say(f"Re-checked on {on} ({', '.join(parts)}).")
    for line in asked.reasons:
        said.say(line)
    said.say()
    old_verdicts = _old_verdicts(state)
    g = groups(state.marks, old_verdicts, tested)
    for key, _, title in GROUPS:
        said.say(_group_line(key, title, g[key]))
    said.say()
    if asked.close:
        said.say(CLOSE.format(why=asked.close))
    flip, right = _steadiness(state.ws)
    drop = targets.smallest_drop(g["passed"]["n"], g["failed"]["n"], flip, right)
    line = _drop_line(drop, flip is not None)
    if line:
        said.say(line)
    worse = [k for k in ("failed", "passed") if g[k]["verdict"] == "worse"]
    if worse:
        def what(who: str) -> str:
            return " and ".join(f"{'passes' if k == 'failed' else 'fails'} "
                                f"{_n(g[k]['now_wrong'], 'answer')} {who} {k}" for k in worse)

        tool = find.NAMES.get(new.get("tool"), new.get("tool"))
        back = (f"the old version of {tool} ({old.get('tool_version')})"
                if judge_setup.tool_only(old, new) else "the old judge")
        said.say(f"Next: tell the person the new judge {what('they')}. Ask whether to go back "
                 f"to {back}.")
        said.person = f"judgekeeper: your judge changed ({short}); it now {what('you')}."
    else:
        said.say(f"Next: nothing. Tell the person their judge changed ({short}) and the "
                 "re-check on their marks found no drop.")
        said.person = (f"judgekeeper: your judge changed ({short}); re-checked on your marks, "
                       "no drop seen.")

    flipped = [i for i in tested if i in old_verdicts and old_verdicts[i] != tested[i]]
    marks.append(state.ws.history_jsonl, scrub_value({
        "time": utc_now(), "kind": "check", "trigger": trigger, "before": old, "after": new,
        "changed": changed, "marks": total, "free": len(free), "asked": len(asked.verdicts),
        "calls": asked.calls, "exact": "close" if asked.close else "exact", "groups": g,
        "smallest_drop": drop, "flipped": flipped}))
    _save_verdicts(state.ws, new, found, tested)
    judge_setup.save(state.ws, new, found.metric)
    _report(state.ws)
    return EXIT_WORSE if worse else EXIT_OK


def baseline(path: str, said: Said) -> int:
    """Ask the current judge once about every marked answer: the old verdicts of the next
    check, and the judge's measured steadiness."""
    from judgekeeper import keep

    state = _state(path)
    if state is None or not state.enough:
        said.say(NOT_SET_UP.format(n=targets.ROUGH))
        return EXIT_NEEDS_YOU
    if not keep.is_on(state.ws):
        said.say(OFF)
        return EXIT_NEEDS_YOU
    found, problem = _newest(state)
    if found is None:
        said.say(problem + ".")
        return EXIT_NEEDS_YOU
    old, new = state.saved["setup"], judge_setup.of(found)
    if judge_setup.changes(old, new):
        said.say(f"Your judge changed since your marks; run `{_command(state)}` first.")
        return EXIT_NEEDS_YOU
    asked = ask(state, found, new, list(state.marks), Said(), yes=True)  # the click said yes
    for line in asked.reasons:
        said.say(line)
    if not asked.verdicts:
        return EXIT_NEEDS_YOU
    pool = {q["id"]: q["group"] for q in state.data.get("queue") or []}
    flipped = [i for i, v in asked.verdicts.items() if pool.get(i) not in (None, v)]
    n = len(asked.verdicts)
    right = sum(state.marks[i] == v for i, v in asked.verdicts.items()) / n
    said.say(f"Asked your judge again about {_n(n, 'marked answer')}: it changed its mind on "
             f"{len(flipped)} of your {n} marked answers.")
    values = [state.marks[i] for i in asked.verdicts]
    drop = targets.smallest_drop(values.count("pass"), values.count("fail"),
                                 len(flipped) / n, right)
    line = _drop_line(drop, True)
    if line:
        said.say(line)
    marks.append(state.ws.history_jsonl, scrub_value({
        "time": utc_now(), "kind": "check", "trigger": "baseline", "before": new,
        "after": new, "changed": [], "marks": len(state.marks), "free": 0, "asked": n,
        "calls": asked.calls, "exact": "close" if asked.close else "exact", "groups": None,
        "smallest_drop": drop, "flipped": flipped, "right": right}))
    _save_verdicts(state.ws, new, found, asked.verdicts)
    _report(state.ws)
    return EXIT_OK


def _report(ws: Workspace) -> None:
    """report.html again, with this check in its History (when there is a result)."""
    from judgekeeper.start_label import write_report

    try:
        write_report(ws)
    except OSError:
        pass  # the check is saved; the report catches up with the next result


# On and off -------------------------------------------------------------------------------------

def turn_on_page(path: str, said: Said, port: int | None = None) -> int:
    """`check --on`: the "Turn on" page, opened in the person's browser."""
    from judgekeeper import front, keep, page
    from judgekeeper.label import DEFAULT_PORT

    state = _state(path)
    least = min(list(state.marks.values()).count(k) for k in ("pass", "fail")) if state else 0
    if state is None or least < targets.RELIABLE:
        said.say(keep.MARK_MORE)
        said.say()
        said.say(f"Next: run `{program('mark')}` and ask the person to mark answers until they "
                 f"have {targets.RELIABLE} Pass and {targets.RELIABLE} Fail.")
        return EXIT_NEEDS_YOU
    if keep.is_on(state.ws):
        said.say("Automatic checks are already on.")
        said.say()
        said.say(f"Next: nothing. Tell the person automatic checks are on; `{program()}` says "
                 "what they do.")
        return EXIT_OK
    shown = front.open_keep(said.say, state.ws, port or DEFAULT_PORT, no_browser=False)
    said.say()
    if shown is None or shown == page.NOT_SHOWN:
        said.say("Next: " + front.NEXT_TERMINAL.format(command=f"{_command(state)} --on"))
        return EXIT_NEEDS_YOU
    again = " ".join((program(), *([] if str(path) == "." else [quote_arg(path)])))
    said.say("Next: " + (front.NEXT_KEEP if shown == "browser" else front.NEXT_KEEP_LINK)
             .format(command=again))
    return EXIT_OK


def turn_off(path: str, said: Said) -> int:
    """`check --off`: take out what turning on added; marks, history and verdicts stay."""
    from judgekeeper import keep

    state = _state(path)
    done = keep.turn_off(state.ws) if state is not None else None
    if done is None:
        said.say("Automatic checks are already off.")
        said.say()
        said.say("Next: nothing. Tell the person automatic checks are off.")
        return EXIT_OK
    removed, left = done
    said.say("Automatic checks: OFF.")
    if removed:
        said.say(f"Removed: {', '.join(removed)}.")
    for file, why in left:
        if why == keep.NOT_OURS:
            said.say(f"Left alone: {file} (checks.json lists it, but judgekeeper did not "
                     "add it there).")
        else:
            said.say(f"Left as it is: {file} (changed since judgekeeper added to it; remove "
                     "the judgekeeper lines yourself).")
    said.say(keep.KEPT)
    said.say(f"To turn them on again, run `{_command(state)} --on`.")
    said.say()
    said.say("Next: nothing. Tell the person automatic checks are off.")
    return EXIT_OK


# The command ------------------------------------------------------------------------------------

def _print(text: str = "") -> None:
    print(one_line(scrub(text)))
    sys.stdout.flush()


class _Printed(Said):
    """Said as it goes: a printed link (page.show) stays in its place among the lines."""

    def say(self, text: str = "") -> None:
        _print(text)


def _hook_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hook(path: str) -> int:
    """`--hook`: always exit 0 (Claude Code reads hook JSON only then, and 2 would block the
    agent); what went wrong, if anything, goes to the agent in the JSON."""
    said = Said()
    given: dict = {}
    try:
        given = _hook_input()
        edited = (given.get("tool_input") or {}).get("file_path") if isinstance(
            given.get("tool_input"), dict) else None
        full(path, said, "hook", edited if isinstance(edited, str) else None)
    except Exception as e:  # noqa: BLE001 - nothing may stop the agent's work
        why = describe_os_error(e) if isinstance(e, OSError) else None
        why = why or str(e) or type(e).__name__
        said.lines = []
        said.say(f"judgekeeper could not check your judge: {why}.")  # on one line
        said.person = None
    if said.lines:
        out = {"hookSpecificOutput": {
            "hookEventName": str(given.get("hook_event_name") or "PostToolUse"),
            "additionalContext": scrub("\n".join(said.lines).strip())}}
        if said.person:
            out["systemMessage"] = scrub(one_line(said.person))
        print(json.dumps(out, ensure_ascii=False))
    return EXIT_OK


def run(path: str = ".", fast_only: bool = False, hook: bool = False,
        baseline_only: bool = False, on: bool = False, off: bool = False,
        port: int | None = None, ci: bool = False, yes: bool = False) -> int:
    """`judgekeeper check`. Returns the exit code."""
    if fast_only:
        return fast(path, _print)
    if ci and os.environ.get("GITHUB_ACTIONS") != "true":
        _print(CI_ONLY)
        return EXIT_USAGE
    if hook:
        return _hook(path)
    _print(f"judgekeeper {__version__}")
    _print()
    if on:
        return turn_on_page(path, _Printed(), port)
    if off:
        return turn_off(path, _Printed())
    if baseline_only:
        said = Said()
        code = baseline(path, said)
        for line in said.lines:
            _print(line)
        return code
    return full(path, _Printed(), "ci" if ci else "by hand", yes=yes)


__all__ = ["baseline", "fast", "full", "groups", "run"]
