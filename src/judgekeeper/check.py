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

`check`: the same, then for a changed setup:
1. free first: marked answers whose exact text is in the newest results already have the new
   judge's verdict;
2. the rest only when automatic checks are on (`checks.json`, written by the "Turn on" page):
   the person's own judge is asked once about each, through `again/` (no menu, no cost line),
   never a judge that can change files unless the person allowed it, at most PER_DAY checks
   with calls a day, and at most TIMES_LIMIT times the calls one re-check of every mark needs
   for one judge setup (a runaway retry stops there). `check-calls.json` counts them;
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

`--baseline` (hidden; the page runs it after "Turn on") asks the current judge once about
every marked answer: its verdicts become the old ones the next check compares with, and how
often they differ from the original eval run is the judge's measured steadiness, which the
smallest-drop line uses from then on.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from judgekeeper import __version__, find, judge_setup, marks, start, targets
from judgekeeper.fingerprint import utc_now
from judgekeeper.records import RecordsError
from judgekeeper.redact import printable, scrub, scrub_value
from judgekeeper.start_label import Workspace
from judgekeeper.textio import program, quote_arg, write_replacing

EXIT_OK, EXIT_WORSE, EXIT_NEEDS_YOU = 0, 1, 3
CHECKS = "checks.json"  # written only by the "Turn on" page
COUNTS = "check-calls.json"
VERDICTS = "verdicts"
PER_DAY = 10
TIMES_LIMIT = 2
KEEP_DAYS = 7
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
GROUPS = (("passed", "pass", "Answers you passed"), ("failed", "fail", "Answers you failed"))

MATCHES = "judgekeeper: your judge matches your marks."
CONFIG_NEWER = ("Your judge's config changed after your last eval run; judgekeeper re-checks it "
                "after the next one.")
NOT_SET_UP = ("Your marks can't check your judge yet: that needs {n} you mark Pass and {n} you "
              "mark Fail.")
TURN_ON = ("Turning on automatic checks lets judgekeeper ask your judge about {which}{n} "
           "marked answer{s}.")
AGENT = "judgekeeper doesn't run a judge that can change files by itself."
DAILY = ("judgekeeper already ran {n} checks that ask your judge today; it asks again "
         "tomorrow.")
LIMIT = "judgekeeper reached its call limit for this judge, so it didn't ask it again."
DOWNLOAD = ("Asking your judge would mean downloading promptfoo {version}; judgekeeper "
            "doesn't download anything by itself.")
NO_KEY = "The key your judge needs isn't set where judgekeeper runs, so your judge wasn't asked."
CLOSE = "This was a close copy of your judge, not an exact one: {why}."
TRACE_WHY = "your judge reads traces, which may have changed since your eval ran"
OFF = "Automatic checks are off, so judgekeeper doesn't ask your judge."


def _terminal() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


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
        return min(values.count("pass"), values.count("fail")) >= targets.ROUGH


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
        why = (scrub(str(e)) if str(e) and not isinstance(e, start.Stop)
               else "it would have to ask which results to read")
        return None, (f"judgekeeper can't read your judge {data.get('metric')} in your newest "
                      f"results: {why}")


def _config_newer(found) -> Path | None:
    """The file the judge comes from (promptfoo's config, Inspect's task file), when it is
    newer than the newest results."""
    root = Path(found.root)
    files = []
    if found.tool == "promptfoo":
        files = [root / n for n in find.PROMPTFOO_CONFIGS]
    elif found.tool == "inspect" and found.task_file:
        files = [root / found.task_file]
    try:
        results = found.results[0].path.stat().st_mtime
    except OSError:
        return None
    for f in files:
        try:
            if f.is_file() and f.stat().st_mtime > results:
                return f
        except OSError:
            continue
    return None


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
    state = _state(path)
    if state is None or not state.enough:
        return EXIT_OK
    found, problem = _newest(state)
    if found is None:
        say(problem + ".")
        return EXIT_OK
    old, new = state.saved["setup"], judge_setup.of(found)
    changed = judge_setup.changes(old, new)
    if changed:
        say(_change_line(old, new, changed, full=False))
        say(f"Next: run `{_command(state)}`.")
        return EXIT_NEEDS_YOU
    if _config_newer(found) is not None:
        say(CONFIG_NEWER)
    elif _terminal():
        say(MATCHES)
    return EXIT_OK


# Asking the judge -------------------------------------------------------------------------------

def _checks(ws: Workspace) -> dict:
    try:
        data = json.loads((ws.dir / CHECKS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _counts(ws: Workspace) -> dict:
    try:
        data = json.loads((ws.dir / COUNTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    days = data.get("days") if isinstance(data.get("days"), dict) else {}
    calls = data.get("calls") if isinstance(data.get("calls"), dict) else {}
    return {"days": days, "calls": calls}


def _count(ws: Workspace, counts: dict, setup_hash: str, calls: int) -> None:
    """One more check with calls today, and its calls for this setup; days older than a week
    are dropped. Written before the judge is asked, so a check that dies still counts."""
    today = _today()
    oldest = (datetime.now().astimezone() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    days = {d: n for d, n in counts["days"].items() if d >= oldest}
    days[today] = int(days.get(today, 0)) + 1
    calls_by = dict(counts["calls"])
    calls_by[setup_hash] = int(calls_by.get(setup_hash, 0)) + calls
    write_replacing(ws.dir / COUNTS, json.dumps({"days": days, "calls": calls_by}, indent=2)
                    + "\n")


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


def ask(state: State, found, setup: dict, ids: list[str], rest: bool = False) -> Asked:
    """Ask the judge in the newest results about the marked answers `ids` (`rest`: the ones
    not found free), when automatic checks are on and every limit allows it."""
    from judgekeeper import again, new_judge
    from judgekeeper.again.fresh import NOT_COUNTED, AgainError, write_files

    out = Asked()
    ws = state.ws
    checks = _checks(ws)
    if not checks.get("on"):
        out.reasons.append(TURN_ON.format(which="the other " if rest else "your ", n=len(ids),
                                          s="" if len(ids) == 1 else "s"))
        return out
    agent = setup.get("agent") or {}
    if setup.get("kind") == judge_setup.AGENT and agent.get("can_write") is not False \
            and checks.get("allow_agent_judge") is not True:
        out.reasons.append(AGENT)
        return out
    counts = _counts(ws)
    if int(counts["days"].get(_today(), 0)) >= PER_DAY:
        out.reasons.append(DAILY.format(n=PER_DAY))
        return out
    view = new_judge.View(ws, found)
    opts = again.AgainOptions(times=1)
    plan = again.make_plan(ws, opts, dry=False, new=view, only=set(ids))
    if plan.status != again.CANT:
        setup_hash = judge_setup.hash_of(setup)
        needs = math.ceil(plan.calls / max(plan.answers, 1) * len(state.marks))
        if int(counts["calls"].get(setup_hash, 0)) + plan.calls > TIMES_LIMIT * needs:
            out.reasons.append(LIMIT)
            return out
        plan = again.make_plan(ws, opts, dry=True, new=view, only=set(ids))
    if plan.status == again.CANT:
        out.reasons.append(plan.plain or f"Your judge can't be asked again: {plan.why}.")
        return out
    if not plan.key_ok:
        out.reasons.append(NO_KEY)
        return out
    if plan.download:
        out.reasons.append(DOWNLOAD.format(version=plan.tool_version))
        return out
    _count(ws, counts, judge_setup.hash_of(setup), plan.calls)
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
        self.lines.append(text)


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


def full(path: str, said: Said, trigger: str, edited: str | None = None) -> int:
    hook = trigger == "hook"
    state = _state(path)
    if state is None or not state.enough:
        if hook:
            return EXIT_OK
        said.say(NOT_SET_UP.format(n=targets.ROUGH))
        said.say(f"Next: run `{program()}` to mark answers.")
        return EXIT_NEEDS_YOU
    found, problem = _newest(state)
    if found is None:
        if hook:
            return EXIT_OK
        said.say(problem + ".")
        said.say("Next: ask the person to run their eval once, then run "
                 f"`{_command(state)}` again.")
        return EXIT_NEEDS_YOU
    old, new = state.saved["setup"], judge_setup.of(found)
    changed = judge_setup.changes(old, new)
    if not changed:
        config = _config_newer(found)
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
    asked = ask(state, found, new, rest, rest=bool(free)) if rest else Asked()
    tested = {**free, **asked.verdicts}
    short = ", ".join(changed)
    if not tested:
        for line in asked.reasons:
            said.say(line)
        said.say()
        said.say(f"Next: tell the person their judge changed ({short}) and none of their "
                 "marked answers could be re-checked yet.")
        said.person = (f"judgekeeper: your judge changed ({short}); it could not be re-checked "
                       "yet.")
        return EXIT_NEEDS_YOU

    n, total = len(tested), len(state.marks)
    parts = [f"{len(free)} free from your new results"] if free else []
    parts += [f"{len(asked.verdicts)} asked again"] if asked.verdicts else []
    on = f"your {total} marks" if n == total else f"{n} of your {total} marks"
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
    judge_setup.save(state.ws, new)
    return EXIT_WORSE if worse else EXIT_OK


def baseline(path: str, said: Said) -> int:
    """Ask the current judge once about every marked answer: the old verdicts of the next
    check, and the judge's measured steadiness."""
    state = _state(path)
    if state is None or not state.enough:
        said.say(NOT_SET_UP.format(n=targets.ROUGH))
        return EXIT_NEEDS_YOU
    if not _checks(state.ws).get("on"):
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
    asked = ask(state, found, new, list(state.marks))
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
    return EXIT_OK


# The command ------------------------------------------------------------------------------------

def _print(text: str = "") -> None:
    print(printable(scrub(text)))
    sys.stdout.flush()


def _hook_input() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run(path: str = ".", fast_only: bool = False, hook: bool = False,
        baseline_only: bool = False) -> int:
    """`judgekeeper check`. Returns the exit code."""
    if fast_only:
        return fast(path, _print)
    said = Said()
    if hook:
        given = _hook_input()
        edited = (given.get("tool_input") or {}).get("file_path") if isinstance(
            given.get("tool_input"), dict) else None
        full(path, said, "hook", edited if isinstance(edited, str) else None)
        if said.lines:
            out = {"hookSpecificOutput": {
                "hookEventName": str(given.get("hook_event_name") or "PostToolUse"),
                "additionalContext": scrub("\n".join(said.lines).strip())}}
            if said.person:
                out["systemMessage"] = scrub(said.person)
            print(json.dumps(out, ensure_ascii=False))
        return EXIT_OK
    code = baseline(path, said) if baseline_only else full(path, said, "by hand")
    _print(f"judgekeeper {__version__}")
    _print()
    for line in said.lines:
        _print(line)
    return code


__all__ = ["COUNTS", "PER_DAY", "baseline", "fast", "full", "groups", "run"]
