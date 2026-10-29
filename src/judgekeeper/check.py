"""`judgekeeper check [PATH]`: when the LLM-as-a-judge changed, re-test it on the person's marks.

Marks are tests for the LLM-as-a-judge. It is its whole setup (judge_setup.py), read from the
newest results (or the results file given as PATH), never from the eval config;
`.judgekeeper/judge.json` keeps the setup last checked, and `results-seen.json` lets a check
with nothing new read nothing again.

The new grades are the ones in the results: a marked answer is found by its exact text and
question (_free). judgekeeper never asks the LLM-as-a-judge itself; a marked answer the results
don't hold is counted, said once and left out. Per group (answers the person passed, and failed),
the paired change gives "Worse", "No drop bigger than 20 points" or "Not sure", always with
the worst drop the marks could hide (targets.paired_verdict). Unless the check ends worse, the
marks then test the new LLM-as-a-judge (_adopt); a worse check stays open until it changes.

Exit 0 no drop over 20 points, 1 a drop over 20 points, 2 results it can't compare, 3 needs
the person.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import (
    __version__,
    batches,
    find,
    judge_setup,
    marks,
    page,
    start,
    targets,
    weighted,
)
from judgekeeper.fingerprint import utc_now
from judgekeeper.records import RecordsError
from judgekeeper.redact import one_line, scrub, scrub_fingerprint, scrub_value
from judgekeeper.start_label import Workspace, every_marked, next_marks
from judgekeeper.textio import (
    flush_stdout,
    held_lines,
    loads,
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
NO_DROP = round(targets.NO_DROP_MARGIN * 100)
VERDICT_WORDS = {"worse": "Worse", "not_sure": "Not sure",
                 "no_drop": f"No drop bigger than {NO_DROP} points"}
# The screen: the result first, then the table's outcome word per group
RESULT = {"worse": "Result: worse. Your new LLM-as-a-judge agrees with you less.",
          "not_sure": ("Result: not sure. These marks can't tell whether your new LLM-as-a-judge "
                       "agrees with you less."),
          "no_drop": (f"Result: no drop bigger than {NO_DROP} in every 100 answers for your new "
                      "LLM-as-a-judge.")}
TABLE_WORDS = {"worse": "Worse", "not_sure": "Not sure", "no_drop": "No big drop"}
TABLE_HEAD = ("Agreed with you:", "Old LLM-as-a-judge", "New LLM-as-a-judge")
COLUMNS = (24, 21, 21)  # the table's columns line up for 1- to 3-digit counts, within 80
SIDES = (("passed", "Pass", "pass"), ("failed", "Fail", "fail"))  # group, what you said

CONFIG_NEWER = ("Your LLM-as-a-judge's settings changed after your last eval run, so the grades "
                "judgekeeper has are out of date.")
LOCK_NEWER = ("Your eval tool was updated after your last eval run, so your newest results come "
              "from the old version. judgekeeper compared no grades.")
SAME = "Same model, same rule, same eval tool."
SAME_GRADES = "Same model, same grades on your marked answers, same eval tool."  # no rule
NEXT_NEW_ANSWERS = ("Next: run `{program}` to mark the new answers in your results: they join "
                    "your marks as a new batch. Then run `{command}` again.")
NOT_SET_UP = "You have not marked enough answers yet for a re-check."
PICKS_WARNING = ("You've used these marks to choose {n}, so they may now make your "
                 "LLM-as-a-judge look better than it is.")
ONE_RUN = "One run, so a small change may be chance."
NONE_IN = ("None of your {n} is in your new results. judgekeeper finds a marked answer by its "
           "exact text and question.")
NEXT_GIVEN = ("Next: give `{command}` {results} for the LLM-as-a-judge your marks test, or run "
              "it in your project folder to read the newest results.")
OWN_RESULTS = "your own results file"  # marks on a plain table, or a file read with a map
NEXT_STORE = "Next: run `{command} {store}`: it reads the newest run."
NONE_GRADED = ("None of your {n} has a grade in your new results: {e} {are} there with no "
               "decision from your LLM-as-a-judge (such as an error).")
NO_DECISION = ("{e} of them {are} there with no decision from your LLM-as-a-judge (such as an "
               "error).")
NOT_IN = ("{k} of your {n} had no grade in your new results, so judgekeeper left {them} out. "
          "It finds a marked answer by its exact text and question.")
NEWER = ("Newer {tool} results are in {file}, outside your saved choice. To check them: "
         "`{command} {file}`.")
CHANGED = ("Your new results ask {c} of those questions again with a different answer: your "
           "eval wrote new answers, and judgekeeper compares only the answers you marked.")
EARLIER = ("{k} of your marked answers {have} no grade from your old LLM-as-a-judge, so "
           "judgekeeper left {them} out of the table.")
TOO_FEW = ("Result: can't tell yet. Your new results hold {p} of the answers you marked Pass and "
           "{f} you marked Fail; a re-check needs {need} of each.")
# Running the eval again makes new answers, which can't be compared: grade the marked ones
NEXT_NOT_MARKED = "Next: {regrade}; or start over on your new answers with `{new}`."
NEXT_SAME = "Next: nothing to do. Run `{command}` again after you change your LLM-as-a-judge."
NEXT_EVAL = "Next: run your eval again, then run `{command}`."
NEXT_RUN_EVAL = "Next: run your eval once, then run `{command}` again."
CHOOSE = f"they need a choice first, such as which results to read: run `{program()}` to make it"
NEXT_CHOOSE = f"Next: run `{program()}` to make that choice, then run `{{command}}` again."
NEXT_WORSE = "go back to {back}, or try another change and run `{command}` again."
# A judge whose results hold no rule (a table): it changes only where the eval keeps it
NEXT_WORSE_TABLE = "go back to your old LLM-as-a-judge or change its rule, {regrade}"
SWITCHED = ("Your results now come from {new}, not {old}.",
            "judgekeeper can't compare LLM-as-a-judge results across two eval tools.")
NEXT_FRESH = "Next: run `{command}` to start fresh with {new}."
STEP = "Step 5 of 5: Re-check"


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
    from judgekeeper.project import project_of as _project

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
               "store": data.get("mlflow_store"), "experiment": data.get("experiment")}
    try:
        where = root
        if start._saved(root) is None:
            options["tool"] = data.get("tool")
            where = start.results_path(root, data)  # a file given by path: read there
        given = start.given_model(fp, root)
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
        why = scrub(str(e)) if str(e) and not isinstance(e, start.Stop) else CHOOSE
        return None, (f"judgekeeper can't read your LLM-as-a-judge {data.get('metric')} in your "
                      f"newest results: {why}")


class OtherName(str):
    """read_given's why when the results name their LLM-as-a-judge otherwise: Fix's Next line
    then says the name to grade under."""


def read_given(state: State, path: Path):
    """The judge of the marks in the results file `path`, read as step 1 reads results (the
    same eval tool, the same LLM-as-a-judge): (found, None), or (None, why in one line) when
    it is another tool's, holds no such judge, or can't be read."""
    data = state.data
    pm = data.get("pass_mark") or {}
    fp = data.get("fingerprint") or {}
    tool, metric = data.get("tool"), data.get("metric")
    options = {"metric": metric, "label_map": data.get("label_map"),
               "pass_if": pm.get("rule") if pm.get("source") == "pass_if" else None,
               "judge_model": start.given_model(fp, state.ws.root),
               "experiment": data.get("experiment")}
    name = _results(tool)
    shown = Path(path).name
    try:
        kind = find.classify_file(Path(path))
    except (OSError, ValueError):
        kind = None
    if kind is not None and kind != tool and tool != "mapped":
        return None, _other_tool(shown, kind, tool)
    saved = start._saved(state.ws.root) if tool == "mapped" else None
    if saved is not None:  # read with the map judgekeeper.toml keeps, the file given
        from dataclasses import replace

        try:
            rel = Path(path).resolve().relative_to(Path(state.ws.root).resolve()).as_posix()
        except ValueError:
            return None, (f"{shown} is outside your project; judgekeeper reads results only "
                          "inside it.")
        options["saved"] = replace(saved, file=rel)
    try:
        found = start.find_judge(state.ws.root if saved is not None else path, **options)
    except start.StartError as e:
        why = f"judgekeeper can't read {shown} as {name}: {scrub(str(e))}"
        return None, OtherName(why) if e.drop == "--metric" else why
    except (start.Stop, RecordsError, OSError, ValueError):
        return None, (f"judgekeeper can't read {shown} as {name} with your "
                      f"LLM-as-a-judge {metric}.")
    if saved is None:  # the project is where .judgekeeper/ is, not the file's folder
        found = start.rebased(found, state.ws.root)
    if found.tool != tool:
        return None, _other_tool(shown, found.tool, tool)
    if scrub(found.metric) != scrub(metric):  # start.json keeps it with keys hidden
        return None, OtherName(f"{shown} has no LLM-as-a-judge named {metric}, the one your "
                               "marks test.")
    return found, None


def _results(tool: str | None) -> str:
    """A tool's results as words: "promptfoo results", "a plain table of results"."""
    return "a plain table of results" if tool == "table" else \
        f"{find.NAMES.get(tool or '', tool)} results"


def _new_results(tool: str | None) -> str:
    """What NEXT_GIVEN asks for: "your new promptfoo results", "your new results file"."""
    if tool in ("table", "mapped"):
        return "your new results file"
    return f"your new {find.NAMES[tool]} results" if tool in find.NAMES else "your new results"


def _other_tool(shown: str, kind: str, tool: str | None) -> str:
    """`shown` holds `kind` results, while the marks are on `tool`'s."""
    held = f"is {_results(kind)}" if kind == "table" else f"holds {_results(kind)}"
    ours = OWN_RESULTS if tool in ("table", "mapped") else _results(tool)
    return (f"{shown} {held}, but your marks are on {ours}. judgekeeper compares an "
            "LLM-as-a-judge only within one eval tool.")


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
    return any((st := judge_setup.lock_stat(f)) is not None and st.st_mtime > results
               for f in locks)


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
    how["given"] = start.given_model(fp, state.ws.root)
    how["env"] = {v: os.environ.get(v) for v in (*find.RESULTS_VARS.values(),
                                                 "MLFLOW_TRACKING_URI")}
    text = json.dumps([__version__, how, signature], sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seen(ws: Workspace) -> dict:
    try:
        data = loads((ws.dir / SEEN).read_text(encoding="utf-8"))
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
            "root": str(root), "covered": False}, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, marks.MarksError):
        pass  # the next check reads the results again


def _covered(ws: Workspace) -> None:
    """results-seen.json's results hold enough of the marked answers: the next check may
    trust it without reading them (until then it reads them, to say why not)."""
    seen = _seen(ws)
    if seen and not seen.get("covered"):
        try:
            path = ws.dir / SEEN
            marks._refuse_links(path)
            write_replacing(path, json.dumps({**seen, "covered": True}, indent=2,
                                             ensure_ascii=False) + "\n")
        except (OSError, ValueError, marks.MarksError):
            pass


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
    if seen and seen.get("root") == str(state.ws.root) and seen.get("covered"):
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


def _change_lines(old: dict, new: dict, changed: list[str], full: bool) -> list[str]:
    """What changed, first on the screen: a model change on its own line under its heading,
    so the two names can be read; any other change in one line."""
    if judge_setup.tool_only(old, new):
        line = f"Your eval tool changed: {judge_setup.tool_words(old, new)}."
        if full:
            line += " Your LLM-as-a-judge's rule and model are the same."
        return [line]
    if len(changed) == 1 and changed[0].startswith("model "):
        return ["Your LLM-as-a-judge's model changed:", f"  {changed[0][len('model '):]}"]
    return [f"Your LLM-as-a-judge changed: {', '.join(changed)}."]


def _command(state_or_path) -> str:
    path = state_or_path.path if isinstance(state_or_path, State) else state_or_path
    return " ".join((program("check"), *([] if str(path) == "." else [quote_arg(path)])))


# The paired test --------------------------------------------------------------------------------

def _old_verdicts(state: State, old: dict) -> dict[str, str]:
    """The old judge's (`old`, a setup) verdicts on the marked answers: the last check's for
    that setup, else start.json's: the grades of the judge judge.json keeps (_adopt), or for
    the judge the marks were made on the grades they were made on (`picked`). Never another
    judge's grade as this one's: a mark it never graded is left out."""
    data = state.data
    pool = {q["id"]: q["group"] for q in data.get("queue") or []}
    setup_hash = judge_setup.hash_of(old)
    if setup_hash != state.saved["setup_hash"]:
        marked = _marked_setup(state.ws)
        if marked is None or judge_setup.hash_of(marked) == setup_hash:
            picked = (data.get("picked") or {}).get("groups") or {}
            late = _batches_after_check(state.ws, data)  # graded by a judge taken on since
            batch = batches.of(data)
            pool.update(picked)
            pool = {i: g for i, g in pool.items() if batch.get(i, 1) not in late}
        else:  # a judge taken on after the marks began: only the grades it gave
            pool = {}
    else:  # never an earlier judge's grade as this one's
        for i in data.get("earlier_grades") or []:
            pool.pop(i, None)
    return {**pool, **_read_verdicts(state.ws, setup_hash)}


def _batches_after_check(ws: Workspace, data: dict) -> set[int]:
    """The batches of answers added after the first check since the marks began: the judge
    the marks were made on never graded them."""
    since = str((marks.read(ws.marks).header or {}).get("created_at") or "")
    first = next((str(x.get("time") or "") for x in _history(ws)
                  if str(x.get("time") or "") >= since), None)
    if first is None:
        return set()
    return {b["batch"] for b in data.get("batches") or []
            if isinstance(b, dict) and isinstance(b.get("batch"), int)
            and str(b.get("added_at") or "") > first}


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
                 pool: dict[str, int], every: bool = False) -> list[str]:
    """The new judge on the marks made after the change: none yet, how many so far, or (with
    AFTER_NUMBERS of each) its numbers with their ranges. `every`: every answer is marked, so
    none is left to mark."""
    from judgekeeper.start_label import side_sentence

    kinds = list(fresh.values())
    n_pass, n_fail = kinds.count("pass"), kinds.count("fail")
    if min(n_pass, n_fail) < AFTER_NUMBERS:
        said = f"{len(fresh)} so far" if fresh else "none" if every else "none yet"
        return [AFTER_NONE.format(said=said) + ("" if every else AFTER_MORE)]
    items = [(picked.get(i, tested[i]), fresh[i], tested[i]) for i in fresh]
    out = weighted.general_strata(items, pool)
    return [f"On marks made after this change ({n_pass} Pass, {n_fail} Fail):",
            *(f"  {side_sentence(k, out[k], out[f'{k}_interval'])}" for k in ("tpr", "tnr"))]


def outcome(g: dict) -> str | None:
    """The check's one result from the groups' verdicts: worse if either group is, else not
    sure if either is, else no drop bigger than NO_DROP; None when no group could be tested."""
    kinds = [g[key]["verdict"] for key, _, _ in SIDES]
    if "worse" in kinds:
        return "worse"
    if "not_sure" in kinds:
        return "not_sure"
    return "no_drop" if "no_drop" in kinds else None


def table_lines(g: dict) -> list[str]:
    """The small table: per group, how many of the person's marks the old and the new judge
    agreed with, and the group's outcome word; a group with no mark re-checked says so."""
    head, old, new = TABLE_HEAD
    lines = [f"{head:<{COLUMNS[0]}}{old:<{COLUMNS[1]}}{new}"]
    for key, said, _ in SIDES:
        x = g[key]
        lead = f"  When you said {said}"
        if not x["n"]:
            lines.append(f"{lead:<{COLUMNS[0]}}none could be re-checked")
            continue
        was, now = f"{x['old_right']} of {x['n']}", f"{x['new_right']} of {x['n']}"
        lines.append(f"{lead:<{COLUMNS[0]}}{was:<{COLUMNS[1]}}{now:<{COLUMNS[2]}}"
                     f"{TABLE_WORDS[x['verdict']]}")
    return lines


def expect_lines(g: dict) -> list[str]:
    """What to expect, one line per group whose outcome says something: for Worse, by about
    how much agreement drops in every 100 answers and the range; for no big drop, the most
    it could drop, or "no drop" when it didn't drop. A Not sure group gets no line: its word
    says it. A clear rise in both groups is said last."""
    out = []
    for key, _, said in SIDES:
        x = g[key]
        if not x["n"] or x["verdict"] == "not_sure":
            continue
        lead = f"On answers you {said},"
        if x["verdict"] == "worse":
            out.append(f"{lead} agreement drops by about {_points(x['change'])} in every 100 "
                       f"(somewhere between {_points(x['high'])} and {_points(x['low'])}).")
        elif x["low"] >= 0:
            out.append(f"{lead} none of the range is a drop.")
        elif x["change"] >= 0:  # no drop seen; the range can't rule one out
            out.append(f"{lead} no drop, though these marks can't rule out one of up to "
                       f"{_points(x['low'])} in every 100.")
        else:
            out.append(f"{lead} agreement drops by no more than {_points(x['low'])} in "
                       "every 100.")
    if all(g[key]["n"] and g[key].get("low", 0) > 0 for key, _, _ in SIDES):
        out.append("Agreement rose in both groups.")
    dropped = [said for key, _, said in SIDES if g[key]["n"] and g[key]["verdict"] == "worse"]
    rose = [said for key, _, said in SIDES if g[key]["n"] and g[key]["verdict"] != "worse"
            and g[key]["new_right"] > g[key]["old_right"]]
    if dropped and rose:  # "worse" next to a group that improved: say what decides
        out.append(f"Agreement rose on answers you {rose[0]} but dropped on answers you "
                   f"{dropped[0]}, and one big drop in either group makes the result worse.")
    return out


def _say_result(said: Said, g: dict) -> None:
    kind = outcome(g)
    if kind:
        said.say(RESULT[kind])
        said.say()


def _say_table(said: Said, g: dict) -> None:
    for line in table_lines(g):
        said.say(line)
    said.say()
    lines = expect_lines(g)
    for line in lines:
        said.say(line)
    if lines:
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
            line = loads(raw)
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
        else:
            indent = text[:len(text) - len(text.lstrip())]
            for line in wrap(text.strip(), indent=indent):
                self._say(line)
        for line in held_lines(text):  # a name left out of the command above, as data
            self._say(one_line(line))

    def _say(self, line: str) -> None:
        self.lines.append(line)


def given_results(path: str) -> bool:
    """Whether the PATH given to `check` or `fix` holds the new results: a results file, or
    an MLflow folder store (`mlruns/`), read like a file (its newest run)."""
    return Path(path).is_file() or find.is_mlflow_folder(Path(path))


def path_problem(path: str) -> str | None:
    """Why the PATH given to `check` or `fix` is neither a results file nor a project folder,
    in one line: nothing there (or a link to nothing), a named pipe or a device, or a folder
    inside a project. None for "." and for anything it can read."""
    from judgekeeper.project import project_of as _project
    from judgekeeper.textio import file_kind

    if path == "." or find.is_mlflow_folder(Path(path)):
        return None
    given = Path(path)
    name = given.name or path
    if not given.exists():
        return f"There is no file or folder named {name} here."
    try:
        kind = file_kind(given.stat().st_mode)
    except OSError:
        return f"There is no file or folder named {name} here."
    if kind == "folder" and _project(given) != given.resolve():
        return (f"{name} is a folder inside your project, not a results file or your project "
                "folder.")
    if kind not in (None, "folder"):
        return f"{name} isn't a regular file: it is a {kind}."
    return None


def _not_set_up(path: str, state: State | None, said) -> int:
    """No marks to check with: where it looked, and where the marks are when a folder above
    holds them (check run from a folder inside the project, or in .judgekeeper/)."""
    from judgekeeper.project import project_of as _project

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
    from judgekeeper import front

    sessions = front.sessions_here(given)
    if sessions:
        where, step = front.go_to_words(sessions, program("check"))
        said.say(where)
        said.say()
        said.say(f"Next: {step}")
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
    from judgekeeper.fix import RESULT_WORDS
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
    result = RESULT_WORDS.get(tests[-1].get("verdict"), "")
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
            line = loads(raw)
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
    split = fix.shown_split(ws)[1]
    mark = (new.get("pass_mark") or {}).get("mark")
    return (mark != (old.get("pass_mark") or {}).get("mark") and split is not None
            and any(t.get("kind") == "pass mark" and t.get("new") == mark
                    for t in split.tests))


def picks(ws: Workspace, now: bool = False) -> dict:
    """{"n": picks, "new_marks": marks made after the last, "ask": whether to ask for
    PICK_MARKS new marks}: counted from these marks on (marks.jsonl's start). `now`: this run
    is a pick too."""
    read = marks.read(ws.marks)
    since = str((read.header or {}).get("created_at") or "")
    times = [str(x.get("time") or "") for x in _history_all(ws) if is_pick(x)]
    times = [t for t in times if t >= since] + ([utc_now()] if now else [])
    last = max(times) if times else None
    made = sum(str(x.get("at") or "") > last for i, x in read.last.items()
               if i in read.counted()) if last else 0
    return {"n": len(times), "new_marks": made,
            "ask": len(times) >= PICKS_ASK and made < PICK_MARKS}


def picks_lines(p: dict, every: bool = False) -> list[str]:
    """With PICKS_ASK picks, the warning: the marks may now flatter the judge, and (unless
    `every` answer is marked: none is left) to mark new ones. Nothing before that: how many
    changes the marks picked is history.jsonl's to keep."""
    if not p["n"] or not p["ask"]:
        return []
    return [PICKS_WARNING.format(n=plural(p["n"], "change"))
            + ("" if every else " Mark some new answers.")]


def _history(ws: Workspace) -> list[dict]:
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            line = loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("kind") == "check":
            out.append(line)
    return out


def _text(value) -> str:
    """An answer's or a question's text as matched: scrubbed as pool.jsonl keeps it, with a
    spreadsheet's guard quote (table.guard_cell) and the line endings and the space at both
    ends left out."""
    from judgekeeper.start_label import display
    from judgekeeper.table import unguard_cell

    text = scrub(display(value)).replace("\r\n", "\n").strip()
    return unguard_cell(text).strip()


def _questions(value) -> set[str]:
    """The texts a results row asks its question by: the whole, and each named value of a set
    of them (promptfoo's vars), since grading marked-answers.csv again puts the marked
    question in one of them (`question`)."""
    texts = {_text(value)}
    if isinstance(value, dict):
        texts |= {_text(v) for v in value.values()}
    return texts - {""}


def _marked_question(value, output=None) -> tuple[str, ...]:
    """A marked answer's question as it is matched: its whole input, and as marked-answers.csv
    holds it (fix.question_text, of the answer `output`), which a regrade of that file asks.
    Never one value of a set of them: a persona, a document or an expected answer many
    questions share is no question."""
    from judgekeeper.fix import question_text

    return tuple(sorted({_text(value), _text(question_text(value, output))} - {""}))


def _rows(ws: Workspace) -> dict:
    """{id: row} of pool.jsonl: the marked answers' text."""
    from judgekeeper.fix import _pool_rows
    from judgekeeper.textio import read_cached

    try:
        return read_cached(ws.pool, _pool_rows)
    except (OSError, ValueError, KeyError):
        return {}


def _same_answer(a, row: dict) -> bool:
    """Whether the answer (or record) `a` is the marked answer pool.jsonl keeps as `row`: the
    same answer text, and the row's whole question asked (_marked_question). An answer with no
    question is only a marked answer with none: another question's answer may read the same.
    An empty answer is found by its question alone; with none, any empty answer reads the same."""
    text = _text(row.get("output"))
    asked, marked = _questions(a.input), set(_marked_question(row.get("input"), row.get("output")))
    return bool(text or marked) and _text(a.output) == text and (
        bool(asked & marked) if marked else not asked)


def _index(answers) -> dict[tuple[str, str | None], list]:
    """The answers by (answer text, each question text they ask), or (answer text, None) when
    they ask none: a marked answer is then found in a few lookups, never by a scan."""
    out: dict[tuple[str, str | None], list] = {}
    for a in answers:
        text = _text(a.output)
        for q in _questions(a.input) or {None}:
            out.setdefault((text, q), []).append(a)
    return out


def _candidates(index: dict, row: dict) -> list:
    """The answers in `index` (_index) that are the marked answer `row` (_same_answer), each
    once, in the results' order. An empty answer only with its question (_same_answer)."""
    text = _text(row.get("output"))
    questions = _marked_question(row.get("input"), row.get("output"))
    if not text and not questions:
        return []
    found = {}
    for q in questions or (None,):
        for a in index.get((text, q), []):
            found.setdefault(id(a), a)
    return list(found.values())


def lookup(found, marked, ws: Workspace) -> tuple[dict, set[str]]:
    """({id: the new judge's answer} for the marked answers `marked` found in the results, the
    ids found there with different grades). For a judge whose results are many files, in
    every file of the newest judge. Found by the exact answer text, with the same question
    when the results hold one: by id only where that row holds them too (a table's own ids
    are often a new numbering). An answer found with different grades counts against the
    judge: the grade that disagrees with the mark (`marked` a dict of marks; a list of ids
    leaves such an answer out)."""
    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    answers = [a for a in found.pool.answers if a.source in newest]
    repeat_of = {f"{key}#{k}": key for key, (n, _, _) in found.pool.split.items()
                 for k in range(2, n + 1)}  # build_pool's ids for the other grades
    by_id: dict[str, list] = {}
    for a in answers:
        by_id.setdefault(repeat_of.get(a.id, a.id), []).append(a)
    rows = _rows(ws)
    out, mixed = {}, set()

    def take(i, same):
        if len({a.verdict for a in same}) == 1:
            out[i] = same[0]
            return
        mark = marked.get(i) if isinstance(marked, dict) else None
        if mark is not None:
            out[i] = next(a for a in same if a.verdict != mark)
            mixed.add(i)

    for i in marked:
        same = [a for a in by_id.get(i, []) if _same_answer(a, rows.get(i) or {})]
        if same:
            take(i, same)
    left = [i for i in marked if i not in out and i not in mixed]
    if not left:
        return out, mixed
    index = _index(answers)
    for i in left:
        same = _candidates(index, rows.get(i) or {})
        if same:
            take(i, same)
    return out, mixed


def no_decision(found, ids, ws: Workspace) -> list[str]:
    """Which of the marked answers `ids` are in the results with no decision from the judge
    (an error, an empty grade), found as lookup finds an answer by its text."""
    index = _index(r for _, r in found.pool.left.values())
    rows = _rows(ws)
    return [i for i in ids if _candidates(index, rows.get(i) or {})]


UNKNOWN = ("judgekeeper can't tell which of the grades in {file} mean Pass and which mean "
           "Fail: {words}. It never guesses.")
NEXT_UNKNOWN = ("grade each answer with the grade words your marked results use, then run "
                "`{command}` again.")


def unknown_grades(found, path: Path) -> str | None:
    """The line refusing results whose grades hold words judgekeeper can't read as Pass or
    Fail (as step 1 refuses them): never a guess, never left out without a word."""
    values = list(dict.fromkeys(found.pool.unmapped))
    if not values:
        return None
    words = sorted(scrub(start.shown_value(v)) for v in values if start.verdict_like(v))
    longer = len(values) - len(words)
    shown = ", ".join(words[:10])
    more = len(words[10:]) + longer
    if more:
        shown += f" and {more} more" if words else _n(more, "longer value")
    return UNKNOWN.format(file=Path(path).name, words=shown)


def _matched(found, marked, ws: Workspace) -> dict:
    """{id: the new judge's answer} for the marked answers found in the results (lookup)."""
    return lookup(found, marked, ws)[0]


def _free(found, marked, ws: Workspace) -> dict[str, str]:
    """The new judge's verdicts on the marked answers `marked` found in the results
    (lookup)."""
    return {i: a.verdict for i, a in _matched(found, marked, ws).items()}


MIXED = ("{k} {answers} got different grades in your new results; counted against your "
         "LLM-as-a-judge.")
REPEATS = "{k} repeated results in your new results were counted once."


def mixed_line(k: int) -> str:
    return MIXED.format(k=k, answers="answer" if k == 1 else "answers")


def repeats_line(found) -> str | None:
    """How many repeats of an answer with the same grade the results held (counted once)."""
    k = found.pool.n_repeats if found is not None else 0
    return REPEATS.format(k=k) if k else None


GRADES = "Your LLM-as-a-judge's grades changed on {k} of your marked answers."
BACK = ("Your LLM-as-a-judge is back to the one you marked with ({model}). Your marks' result "
        "still holds.")
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
    return sum(1 for i, v in _free(found, marked, ws).items() if i in old and old[i] != v)


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
    groups' sizes, stay in `picked` (start_label.picked_numbers). The answers it has no grade
    on keep an earlier judge's: `earlier_grades` names them, and no comparison uses those."""
    from judgekeeper.fingerprint import JudgeFingerprint
    from judgekeeper.judgments import judgment_to_record, read_run, write_run
    from judgekeeper.runners.base import Judgment
    from judgekeeper.start_label import _write_json

    data = ws.data()
    queue = data.get("queue") or []
    newest = set(found.used) if found.tool in ("records", "mapped") else {found.used[0]}
    answers = {**{a.id: a for a in found.pool.answers if a.source in newest},
               **_matched(found, [q["id"] for q in queue], ws)}
    now = {**{i: a.verdict for i, a in answers.items()}, **tested}
    picked = data.get("picked") or {"pool": data.get("pool"),
                                    "groups": {q["id"]: q["group"] for q in queue}}
    for q in queue:  # a batch added since the last check: picked by the grades it has now
        picked["groups"].setdefault(q["id"], q["group"])
    earlier = sorted(q["id"] for q in queue if q["id"] not in now)
    queue = [{**q, "group": now.get(q["id"], q["group"])} for q in queue]
    kinds = [q["group"] for q in queue]
    data.pop("earlier_grades", None)
    if earlier:
        data["earlier_grades"] = earlier
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
            elif i in now and now[i] != rec.get("verdict"):  # found by its text: no reason kept
                rec = judgment_to_record(i, Judgment(verdict=now[i], raw_score=None,
                                                     rationale=""), fp)
            lines.append(rec)
        write_run(ws.pool_judge, head.get("run", 1), head.get("anchors_sha256", ""), fp,
                  lines, source=head.get("source"), normaliser=head.get("normaliser"))
    _write_json(ws.start, data)


def full(path: str, said: Said) -> int:
    """`judgekeeper check [PATH]`: PATH a results file holds the new results; a folder (or
    none) is the project, read at its newest results."""
    problem = path_problem(path)
    if problem:
        said.say(problem)
        said.say()
        said.say(f"Next: give `{program('check')}` your new results file, or run it in your "
                 "project folder.")
        return EXIT_USAGE
    state = _state(path)
    if state is None or not state.enough:
        return _not_set_up(path, state, said)
    old = state.saved["setup"]
    if given_results(path):
        found, problem = read_given(state, Path(path))
        if found is None:
            said.say(problem)
            said.say()
            from judgekeeper.fix import mlflow_store

            store = mlflow_store(state.ws)
            said.say(NEXT_STORE.format(command=program("check"), store=store) if store else
                     NEXT_GIVEN.format(results=_new_results(state.data.get("tool")),
                                       command=program("check")))
            return EXIT_USAGE
        now = Now(judge_setup.of(found), None, found, found.results[0].path)
    else:
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
        then = NEXT_CHOOSE if problem.endswith(CHOOSE) else NEXT_RUN_EVAL  # as the line says
        said.say(then.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    read = _read_line(state, path, now)
    if read:
        said.say(read)
        said.say()
    newer = None if given_results(path) or now is None else _newer_elsewhere(state, now.newest)
    if newer is not None:  # a note: the check reads what judgekeeper.toml says, as always
        tool = state.data.get("tool")
        said.say(NEWER.format(tool=find.NAMES.get(tool, tool), file=quote_arg(newer),
                              command=program("check")))
        said.say()
    unknown = unknown_grades(found, found.results[0].path) if found is not None else None
    if unknown:
        said.say(unknown)
        said.say()
        said.say("Next: " + NEXT_UNKNOWN.format(command=_command(state)))
        return EXIT_NEEDS_YOU
    back = (back_to_marked(state.ws, found, said.say, again=len(state.marks))
            if found is not None else None)
    if back:
        said.say(back)
        if not (checks and checks[-1].get("trigger") == "back" and judge_setup.hash_of(
                checks[-1].get("after") or {}) == judge_setup.hash_of(new)):  # once in history
            marks.append(state.ws.history_jsonl, _history_line({
                "time": utc_now(), "kind": "check", "trigger": "back", "before": old,
                "after": new, "changed": ["back to the LLM-as-a-judge the marks were made on"],
                "marks": len(state.marks),
                "free": 0, "groups": {}}))
        _report(state.ws)  # no "Worse" from the other judge on it
        said.say()
        said.say(NEXT_SAME.format(command=_command(state)))
        return EXIT_OK
    changed = judge_setup.changes(old, new)
    if not changed and added:  # marks made since the last check: that change again
        old, changed = before, judge_setup.changes(before, new)
    grades = 0 if changed or found is None else grades_changed(state.ws, found)
    if not changed and not grades:
        if found is not None and _too_few(said, state, found):  # "no change" only on what
            return EXIT_NEEDS_YOU  # the results hold
        held = len(lookup(found, state.marks, state.ws)[0]) if found is not None else None
        if held == len(state.marks) and not given_results(path):
            _covered(state.ws)
        if now.config is not None:  # one line per case, never "no change" with it
            said.say(CONFIG_NEWER)
            said.say()
            said.say(NEXT_EVAL.format(command=_command(state)))
        else:
            said.say(_no_change(state))
            said.say(SAME if new.get("rule_hash") else SAME_GRADES)
            if held is not None and held < len(state.marks):  # most were run again: new text
                k = len(state.marks) - held
                said.say(NOT_IN.format(k=k, n=_n(len(state.marks), "marked answer"),
                                       them="it" if k == 1 else "them"))
                said.say()
                said.say(NEXT_NEW_ANSWERS.format(program=program(), command=_command(state)))
                return EXIT_OK
            said.say()
            said.say(NEXT_SAME.format(command=_command(state)))
        return EXIT_OK

    for line in _change_lines(old, new, changed, full=True) if changed else [
            GRADES.format(k=grades)]:
        said.say(line)
    new_marks = _made_since_last_check(state, added)
    if new_marks:  # only marks really made since; the others the last check could not test
        said.say(ADDED.format(n=_n(new_marks, "mark")))
    tested = _tested_rule(state, found) if found is not None and old.get("rule_hash") != \
        new.get("rule_hash") else None
    if tested:
        said.say(tested)
    if _lock_newer(state, old, new, found.results[0].path if found else now.newest):
        said.say(LOCK_NEWER)  # the results were made before the update: nothing compared
        said.say()
        said.say(NEXT_EVAL.format(command=_command(state)))
        return EXIT_NEEDS_YOU  # never a pass for a CI gate: nothing was compared
    matched, mixed = lookup(found, state.marks, state.ws)
    tested = {i: a.verdict for i, a in matched.items()}
    n, total = len(tested), len(state.marks)
    if _too_few(said, state, found, (matched, mixed)):  # never exit 1 on few
        return EXIT_NEEDS_YOU
    on = f"all {total} of your marks" if n == total else f"{n} of your {_n(total, 'mark')}"
    old_verdicts = _old_verdicts(state, old)
    picked, pool = _picks(state)
    g = groups(state.marks, old_verdicts, tested, picked, pool)
    pick = rule_changed(changed) and from_fix(state.ws, old, new)
    fresh = _made_after(state, _first_seen(state, old, new), tested) if pick else None
    kinds = list(fresh.values()) if fresh is not None else []
    if min(kinds.count("pass"), kinds.count("fail")) >= AFTER_HEADLINE:
        g = groups(fresh, old_verdicts, tested, picked, pool)  # the headline now
        _say_result(said, g)
        said.say(f"Re-checked on the {len(fresh)} marks you made after this change:")
        said.say()
        _say_table(said, g)
        said.say(f"On {on}:")
        said.say()
        _say_table(said, groups(state.marks, old_verdicts, tested, picked, pool))
        said.say(WRITTEN_FROM)
        said.say()
    else:
        _say_result(said, g)
        if n < total:  # on every mark goes without saying
            said.say(f"Re-checked on {on}:")
            said.say()
        _say_table(said, g)
        if fresh is not None:
            said.say(WRITTEN_FROM)
            for line in _after_lines(fresh, tested, picked, pool,
                                     every=every_marked(state.ws)):
                said.say(line)
            said.say()
    left = sum(i in state.marks and i not in old_verdicts for i in tested)
    if left:  # graded before the last check took on the old judge (_adopt)
        said.say(EARLIER.format(k=left, have="has" if left == 1 else "have",
                                them="it" if left == 1 else "them"))
        said.say()
    said.say(ONE_RUN)
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
        said.say("Next: " + worse_step(old, new, _command(state), state.ws))
    elif (picked["ask"] or unsure) and n < total and every:  # marks the results did not hold:
        # more marks can't be made, and new answers would not help
        said.say("Next: " + regrade_marked(state, every=True))
    elif picked["ask"]:
        need = PICK_MARKS - picked["new_marks"]
        said.say("Next: " + next_marks(state.ws, NEXT_NEW_MARKS.format(
            mark=program("mark"), n=need, command=_command(state)), need=need))
    elif unsure:
        said.say("Next: " + next_marks(state.ws, NEXT_NOT_SURE.format(
            mark=program("mark"), command=_command(state))))
    else:
        said.say(NEXT_SAME.format(command=_command(state)))
    held = any(g[k].get("exit_worse") for k in g)  # "Worse", or "Not sure" with a big drop
    big = any(g[k]["n"] and round(-g[k]["change"], 9) > targets.NO_DROP_MARGIN for k in g)
    new_rates = _new_rates(state.marks, tested, *_picks(state)) if worse else None

    flipped = [i for i in tested if i in old_verdicts and old_verdicts[i] != tested[i]]
    line = _history_line({
        "time": utc_now(), "kind": "check", "trigger": "by hand", "before": old, "after": new,
        "changed": changed or [f"grades changed on {_n(grades, 'marked answer')}"],
        "marks": total, "free": n, "groups": g,
        "smallest_drop": drop, "flipped": flipped, "from_fix": pick,
        "made_after_change": None if fresh is None else len(fresh),
        **({"new_rates": new_rates} if new_rates else {})})
    if not _same_as_last(state, line):
        marks.append(state.ws.history_jsonl, line)
    if not held or judge_setup.hash_of(old) != judge_setup.hash_of(new):
        _save_verdicts(state.ws, new, found, tested)  # a "Worse" of the same setup (a table's
        # new grades) keeps the old grades: the next check says worse again
    if not held:  # after "Worse" the old judge stays the reference until it comes back
        judge_setup.save(state.ws, new, found.metric)
        with page.one_at_a_time(state.ws.dir, said.say):  # two runs at once: one writes
            _adopt(state.ws, found, tested)
        _refresh_mistakes(state.ws)
    _report(state.ws, adopted=not held,
            worse=worse_step(old, new, _command(state), state.ws) if worse else None)
    if not given_results(path):
        _covered(state.ws)
    return EXIT_WORSE if big else EXIT_OK  # exit 1 only on a drop over NO_DROP points


def _read_line(state: State, path: str, now: Now | None) -> str | None:
    """The line that names the results the check reads: the file given, else the newest
    file read (for MLflow, the newest run in its store)."""
    if given_results(path):
        return f"New results: {Path(path).as_posix()}"
    if now is None or now.newest is None:
        return None
    if state.data.get("tool") == "mlflow":
        from judgekeeper.fix import mlflow_store

        store = mlflow_store(state.ws)
        return f"New results: the newest run in {store}" if store else None
    root = Path(state.ws.root).resolve()
    newest = Path(now.newest).resolve()
    shown = newest.relative_to(root).as_posix() if newest.is_relative_to(root) else str(newest)
    return f"New results: {shown}"


def _newer_elsewhere(state: State, newest: Path | None) -> str | None:
    """With a saved choice (judgekeeper.toml), newer results of the same eval that it leaves
    out: the newest one's path from the project folder, else None. Newer by the date the
    reader goes by (find.Result.date); the same eval: the same eval tool, for Inspect AI the
    same task, for DeepEval a run that holds the same metric. Unknown is never the same."""
    tool = state.data.get("tool")
    if newest is None or tool not in ("promptfoo", "deepeval", "inspect"):
        return None
    root = Path(state.ws.root).resolve()
    try:
        if start._saved(root) is None:
            return None
        read = find.Result(tool, Path(newest).resolve(), "")
        after, task = read.date(), _task(read.path) if tool == "inspect" else None
        if tool == "inspect" and task is None:
            return None
        newer = [r for r in find.search(root).readable(tool)
                 if r.path.resolve() != read.path and r.date() > after
                 and _same_eval(tool, r.path, task, state.data.get("metric"))]
    except (start.StartError, OSError, ValueError):
        return None
    return max(newer, key=lambda r: r.date()).rel if newer else None


def _task(path: Path) -> str | None:
    """The task an Inspect AI log ran, or None."""
    from judgekeeper.readers.inspect_logs import eval_header

    try:
        task = eval_header(path).get("task")
    except (OSError, ValueError, KeyError, AttributeError):
        return None
    return task.strip() if isinstance(task, str) and task.strip() else None


def _same_eval(tool: str, path: Path, task: str | None, metric) -> bool:
    """Whether the results at `path` are of the same eval: for Inspect AI the task `task`, for
    DeepEval a run with the metric `metric`; promptfoo results are one eval."""
    if tool == "inspect":
        return _task(path) == task
    if tool == "deepeval":
        from judgekeeper.readers.deepeval import _load

        try:
            cases = _load(path).get("testCases") or []
            return any(isinstance(md, dict) and md.get("name") == metric
                       for case in cases if isinstance(case, dict)
                       for md in case.get("metricsData") or [])
        except (RecordsError, OSError, ValueError, AttributeError, TypeError):
            return False
    return True


def _too_few(said: Said, state: State, found, looked=None) -> bool:
    """Whether the results hold too few of the marked answers with a grade for a re-check
    (fewer than targets.ROUGH of each mark), said with why: not there, or there with no
    decision. Else the lines on the ones left out, before the result."""
    matched, mixed = looked or lookup(found, state.marks, state.ws)
    n, total = len(matched), len(state.marks)
    gone = [i for i in state.marks if i not in matched]
    e = len(no_decision(found, gone, state.ws)) if gone else 0
    kinds = [state.marks[i] for i in matched]
    few = min(kinds.count("pass"), kinds.count("fail")) < targets.ROUGH
    if not matched:
        said.say(NONE_GRADED.format(n=_n(total, "marked answer"), e=e, are=_are(e)) if e
                 else NONE_IN.format(n=_n(total, "marked answer")))
        said.say()
        from judgekeeper import fix

        answers = f"{fix.shown_folder(state.ws)}/{fix.FOLDER}/{fix.ANSWERS}"
        regrade = _regrade_answers(state.ws, answers, "your LLM-as-a-judge").rstrip(".")
        said.say(NEXT_NOT_MARKED.format(regrade=regrade, new=program("--new")))
        return True
    if not few and looked is None:
        return False  # the check goes on, and says them there
    if n < total:
        k = total - n
        said.say(NOT_IN.format(k=k, n=_n(total, "marked answer"), them="it" if k == 1
                               else "them"))
        if e:
            said.say(NO_DECISION.format(e=e, are=_are(e)))
    c = _asked_again(found, gone, state.ws) if gone else 0
    if c:
        said.say(CHANGED.format(c=c))
    if mixed:
        said.say(mixed_line(len(mixed)))
    if repeats_line(found):
        said.say(repeats_line(found))
    said.say()
    if few:
        said.say(TOO_FEW.format(p=kinds.count("pass"), f=kinds.count("fail"),
                                need=targets.ROUGH))
        said.say()
        said.say("Next: " + regrade_marked(state, every=True))  # new answers can't be compared
    return few


def _asked_again(found, ids, ws: Workspace) -> int:
    """How many of the marked answers `ids` the results ask again with another answer: the
    marked question asked (_marked_question), a different answer text."""
    answers: dict[str, set[str]] = {}
    for a in found.pool.answers:
        for q in _questions(a.input):
            answers.setdefault(q, set()).add(_text(a.output))
    rows = _rows(ws)
    return sum(1 for i in ids if (row := rows.get(i)) and any(
        answers.get(q, set()) - {_text(row.get("output"))}
        for q in _marked_question(row.get("input"), row.get("output"))))


def regrade_marked(state: State, every: bool = False) -> str:
    """The way to new grades on the answers marked (without "Next: "): grade them again as
    the eval tool does, then `check` the new results. Running the eval again would make new
    answers, which can't be compared. `every`: the new results left some out, so it says to
    grade every one."""
    from judgekeeper import fix

    ws, tool = state.ws, state.data.get("tool")
    check = program("check")
    store = fix.mlflow_store(ws) if tool == "mlflow" else None
    if store:
        return (f"evaluate {'all ' if every else ''}the same traces again with your "
                f"LLM-as-a-judge as it is now "
                f"(`mlflow.genai.evaluate()`), then run `{check} {store}`: it reads the newest "
                f"run.")
    if tool == "inspect":
        log = quote_arg(fix.new_log(ws))
        return (f"score your {'whole ' if every else ''}marked log again with your "
                f"LLM-as-a-judge as it is now: run "
                f"`{fix.INSPECT_SCORE}` with `--output-file {log}`, then run `{check} {log}`.")
    return _regrade_answers(ws, fix._file(ws, fix.ANSWERS), "your LLM-as-a-judge as it is now",
                            every)


def _regrade_answers(ws: Workspace, answers: str, judge: str, every: bool = False) -> str:
    """Grade marked-answers.csv (shown as `answers`) again with `judge`, then `check` the new
    results; `fix` writes the file first when there is none. `every`: each answer in it."""
    from judgekeeper import fix

    check = f"`{program('check')} {fix.NEW_RESULTS}`"
    if (fix._folder(ws) / fix.ANSWERS).is_file():
        return (f"grade {'every answer' if every else 'the answers'} in {answers} again with "
                f"{judge}, then run {check}.")
    return (f"run `{program('fix')}` to write the answers you marked to {answers}, grade "
            f"{'every one' if every else 'them'} again with {judge}, then run {check}.")


def _are(k: int) -> str:
    return "is" if k == 1 else "are"


def _new_rates(marked: dict[str, str], tested: dict[str, str], picked: dict[str, str],
               pool: dict[str, int]) -> dict:
    """The new judge's TPR and TNR on the marks it was tested on, each with its range, as the
    result's are worked out (weighted.general_strata): for report.html's Last check block."""
    items = [(picked[i], marked[i], v) for i, v in tested.items() if i in marked and i in picked]
    out = weighted.general_strata(items, pool)
    return {k: out[k] for k in ("tpr", "tpr_interval", "tnr", "tnr_interval")}


def worse_step(old: dict, new: dict, command: str, ws: Workspace) -> str:
    """The next step after "Worse" (without "Next: "), the same in `check`, `judgekeeper` and
    report.html: go back to the old judge (or tool version), or change the judge. A judge
    whose results hold no rule then grades the same marked answers again: running the eval
    again would make new answers, which can't be compared."""
    if judge_setup.tool_only(old, new):
        tool = find.NAMES.get(new.get("tool"), new.get("tool"))
        return NEXT_WORSE.format(back=f"the old version of {tool} ({old.get('tool_version')})",
                                 command=command)
    if new.get("rule_hash") is None:
        from judgekeeper import fix

        answers = f"{fix.shown_folder(ws)}/{fix.FOLDER}/{fix.ANSWERS}"  # plain: report.html too
        return NEXT_WORSE_TABLE.format(regrade=_regrade_answers(ws, answers, "it"))
    return NEXT_WORSE.format(back="your old LLM-as-a-judge", command=command)


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
        flips = sorted(i for i, v in _free(found, counted, ws).items()
                       if i in old and old[i] != v)
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


def back_to_marked(ws: Workspace, found, say, again: int | None = None) -> str | None:
    """The judge in the newest results (`found`) is the one the marks were made on, and the
    last check was of another judge: the line that says so, else None. When that check moved
    the marks to the other judge, they test the judge they were made on again, with the grades
    they were made on (no AI call, _restore); after a "Worse", nothing was moved, and that
    "Worse" no longer applies (open_worse). Only for a judge whose results hold its rule, and
    that gives the marked answers the grades they were made on: a table's model name alone
    is not that judge. With `again` (how many marks count now), the line also when the last
    check was that "back", with as many marks: the same results get the same answer."""
    marked, saved, checks = _marked_setup(ws), judge_setup.read(ws), _history(ws)
    if marked is None or saved is None or not checks:
        return None
    now = judge_setup.of(found)
    last = checks[-1]
    to_now = judge_setup.hash_of(last.get("after") or {}) == judge_setup.hash_of(now)
    if (not now.get("rule_hash") or judge_setup.hash_of(now) != judge_setup.hash_of(marked)
            or to_now and not (again is not None and last.get("trigger") == "back"
                               and last.get("marks") == again)):
        return None
    data = ws.data()
    made_on = (data.get("picked") or {}).get("groups") or {
        q["id"]: q["group"] for q in data.get("queue") or []}
    graded = lookup(found, list(marks.read(ws.marks).counted()), ws)[0]
    if any(a.verdict != made_on.get(i) for i, a in graded.items()):
        return None
    with page.one_at_a_time(ws.dir, say):  # two runs at once: one writes
        if saved["setup_hash"] != judge_setup.hash_of(now):
            _restore(ws, found, now)
        # the marks' grades from this judge: the next change is compared with them
        _save_verdicts(ws, now, found, {i: a.verdict for i, a in graded.items()})
    names = [re.split(r"[:/]", str(m))[-1] for m in now.get("models") or []]
    return BACK.format(model=", ".join(names) or "model not named")


def take_grades(ws: Workspace, grades: dict[str, str]) -> None:
    """The judge the marks test now graded answers that had only an earlier judge's grade
    (`earlier_grades`): start.json keeps its `grades` on them from now on."""
    from judgekeeper.start_label import _write_json

    data = ws.data()
    data["queue"] = [{**q, "group": grades.get(q["id"], q["group"])}
                     for q in data.get("queue") or []]
    kinds = [q["group"] for q in data["queue"]]
    data["pool"] = {**(data.get("pool") or {}), "pass": kinds.count("pass"),
                    "fail": kinds.count("fail")}
    left = [i for i in data.get("earlier_grades") or [] if i not in grades]
    data.pop("earlier_grades", None)
    if left:
        data["earlier_grades"] = left
    _write_json(ws.start, data)


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
    for key in ("picked", "checked_at", "earlier_grades"):  # every grade is that judge's again
        data.pop(key, None)
    _write_json(ws.start, data)
    judge_setup.save(ws, setup, found.metric)
    _report(ws, adopted=True)


def _history_line(line: dict) -> dict:
    """`line` scrubbed for history.jsonl, its setups as judge.json keeps them
    (judge_setup.keys_hidden): they are compared with the setups read later."""
    out = scrub_value(line)
    out["before"], out["after"] = (judge_setup.keys_hidden(line[k]) for k in ("before", "after"))
    return out


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
        saved = loads(ws.result_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    try:
        if adopted and isinstance(saved, dict):
            store_result(ws, StartSession(ws), saved.get("flags"), redraw=True)
        else:
            write_report(ws, worse=worse)
    except OSError:
        pass  # the check is saved; the report catches up with the next result


# The command ------------------------------------------------------------------------------------

def _print(text: str = "") -> None:
    print(one_line(scrub(text)))
    flush_stdout()


class _Printed(Said):
    """Said as it goes, so the question is asked in its place among the lines."""

    def say(self, text: str = "") -> None:
        if not text.startswith("Next:") and len(one_line(text)) <= 80:
            _print(text)
            for line in held_lines(text):  # a name left out of the command above, as data
                _print(line)
        else:
            super().say(text)

    def _say(self, line: str) -> None:
        _print(line)


def run(path: str = ".") -> int:
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
    return full(path, _Printed())


__all__ = ["full", "groups", "run"]
