"""`judgekeeper steps [PATH]`: check an agent reviewer's "first wrong step" against people's.

Given agent runs (a JSONL file, one run per line: `id`, `steps`, each step `{"role" or "name",
"content"}`) it writes the Label Studio screen people label them on:
.judgekeeper/steps/label-these.json (one task per run) and label-config.xml. Given the Label
Studio export of that project it reads the people's first wrong steps (annotations with a
`number` region; 0 means all fine) and the reviewer's guesses (predictions, or a JSONL file
`{id, first_wrong_step, model}`), says how often the reviewer finds the same first wrong step
as the people, and saves .judgekeeper/steps/result.json. judgekeeper only reads and writes
files: it never calls Label Studio or an AI.

Run level: a run went wrong when its first wrong step is above 0. TPR, TNR and kappa against
the people, each with a range. Step level, on the runs both say went wrong: how often the
reviewer names the same step, and a step within one. Never raw agreement alone.

From the export only the annotator's numeric user id is kept (`who`): never an email, a name
or any other field of `completed_by`.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import __version__, metrics, project, targets, textio, weighted
from judgekeeper.fingerprint import JudgeFingerprint, unknown_fields, utc_now
from judgekeeper.redact import scrub_value
from judgekeeper.start import StartError, path_word
from judgekeeper.start_label import Workspace, make_folder
from judgekeeper.textio import plural, program, write_replacing

EXIT_OK, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 2, 3
FOLDER = "steps"
TASKS_FILE, CONFIG_FILE, RESULT_FILE = "label-these.json", "label-config.xml", "result.json"
RUNS_FILE = "runs.jsonl"
STEP_FIELD = "first_wrong_step"
DEFAULT_REVIEWER = "reviewer"
SHOWN = f".judgekeeper/{FOLDER}"

INSTRUCTIONS = ("First wrong step: the number of the first step that went wrong, counting "
                "from 1. 0 = all fine.")
CONFIG = f"""<View>
  <Header value="{INSTRUCTIONS}"/>
  <Paragraphs name="steps" value="$steps" layout="dialogue" nameKey="role" textKey="content"/>
  <Number name="{STEP_FIELD}" toName="steps" min="0"/>
</View>
"""

NEXT_LABEL = ("in Label Studio, make a project with the labelling setup in {config}, import "
              "{tasks}, give each run its first wrong step (0 if all fine), export the project "
              "as JSON and run `{export}`.")
NEXT_NO_LABELS = ("label the runs in Label Studio (the first wrong step, 0 if all fine), export "
                  "the project as JSON and run `{command}`.")
NEXT_MORE = "label more runs in Label Studio, export again and run `{command}`."
NEXT_GUESSES = ("give your reviewer's first wrong step for each run as a JSONL file (one line "
                "per run: {{\"id\": ..., \"first_wrong_step\": ..., \"model\": ...}}) and run "
                "`{command} --reviewer GUESSES.jsonl`.")
NEXT_AGAIN = ("change your reviewer, save its new guesses as a JSONL file and run "
              "`{command} --reviewer NEW-GUESSES.jsonl`.")

NOT_EXPORT = ("{name} is not a Label Studio export of the runs judgekeeper steps writes: give "
              "it your runs file (JSONL) or that project's export (JSON).")
FLAT_EXPORT = ("{name} looks like a Label Studio JSON_MIN (or CSV) export. judgekeeper steps "
               "reads the full JSON export: in Label Studio, export as JSON.")
NO_STEPS_IN_EXPORT = ("{name} is a Label Studio export, but its tasks hold no `steps` (they "
                      "hold: {keys}). This reads the export of the project made from "
                      f"{SHOWN}/{TASKS_FILE}.")


class StepsError(StartError):
    """`steps` cannot go on: a usage error (exit 2), said with the line's Next:."""


@dataclass
class Run:
    id: str
    steps: list[dict]
    task: str | None = None  # what the agent was asked to do, when the run says


@dataclass
class Task:
    id: str  # the run's id (data.run_id, else data.id), else Label Studio's own task id
    n_steps: int | None
    label: int | None = None  # the people's first wrong step, when they gave one
    state: str = "no_label"  # label | disagreed | unusable | no_label


@dataclass
class Export:
    name: str
    tasks: list[Task]
    who: dict[str, int]
    guesses: dict[str, dict[str, object]]  # reviewer -> run id -> number as given
    created: dict[str, str | None]  # reviewer -> newest created_at
    ids_only: bool = False
    stats: dict = field(default_factory=dict)


# The runs file -> the screen --------------------------------------------------------------

def _whole(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def _call_line(name, arguments) -> str:
    """"Tool call: search({"q": "x"})": arguments given as JSON text are shown as JSON."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return f"Tool call: {_text(name)}({arguments})"
    return f"Tool call: {_text(name)}({'' if arguments is None else _text(arguments)})"


def _block_lines(block) -> list[str]:
    """The readable lines of one content block (Anthropic style): text, a tool call, a tool
    result. Any other kind of block, and any other key, is left out."""
    if isinstance(block, str):
        return [block] if block else []
    if not isinstance(block, dict):
        return []
    kind = block.get("type")
    if kind == "text" and isinstance(block.get("text"), str):
        return [block["text"]] if block["text"] else []
    if kind == "tool_use":
        return [_call_line(block.get("name"), block.get("input"))]
    if kind == "tool_result":
        content = block.get("content")
        text = ("\n".join(x for b in content for x in _block_lines(b))
                if isinstance(content, list) else _text(content))
        return [f"Tool result: {text}"]
    return []


def step_text(step: dict) -> str:
    """A step as text a person can read: its content (text, or a list of blocks), then one
    line for each tool call (OpenAI `tool_calls` or Anthropic `tool_use` blocks). Nothing
    else in the step is written."""
    content = step.get("content")
    lines = ([x for b in content for x in _block_lines(b)] if isinstance(content, list)
             else [_text(content)] if _text(content) else [])
    for call in step.get("tool_calls") or []:
        if isinstance(call, dict):
            fn = call.get("function") if isinstance(call.get("function"), dict) else call
            lines.append(_call_line(fn.get("name"), fn.get("arguments")))
    return "\n".join(lines)


def read_runs(path: Path) -> list[Run]:
    """The runs in a JSONL file. A problem is said by line number, never by quoting the line."""
    runs: list[Run] = []
    seen: set[str] = set()
    text = textio.read_utf8(path, StepsError)
    for number, line in enumerate(textio.jsonl_lines(text), 1):
        if not line.strip():
            continue
        try:
            row = textio.loads(line)
        except ValueError:
            raise StepsError(f"Line {number} of {path.name} is not valid JSON.") from None
        if not isinstance(row, dict):
            raise StepsError(f"Line {number} of {path.name} is not a JSON object.")
        run_id = row.get("id")
        if not (isinstance(run_id, str) and run_id.strip()) and not (
                _whole(run_id) and not isinstance(run_id, float)):
            raise StepsError(f"Line {number} of {path.name} has no id.")
        run_id = str(run_id)
        if run_id in seen:
            raise StepsError(f"Line {number} of {path.name} has an id used twice.")
        seen.add(run_id)
        steps = row.get("steps")
        if not isinstance(steps, list) or not steps:
            raise StepsError(f"Line {number} of {path.name} has no steps (a list of "
                             "{\"role\": ..., \"content\": ...}).")
        out = []
        for k, step in enumerate(steps, 1):
            role = step.get("role") or step.get("name") if isinstance(step, dict) else None
            if not isinstance(role, str) or not role.strip():
                raise StepsError(f"Step {k} on line {number} of {path.name} has no role or "
                                 "name.")
            out.append({"role": f"{k}. {role}", "content": step_text(step)})
        asked = next((row[k] for k in ("task", "input") if row.get(k) not in (None, "")), None)
        runs.append(Run(run_id, out, None if asked is None else _text(asked)))
    if not runs:
        raise StepsError(f"{path.name} holds no runs.")
    return runs


def screen_files(runs: list[Run]) -> tuple[str, str]:
    """(label-these.json, label-config.xml) for `runs`."""
    with_task = any(r.task is not None for r in runs)
    tasks = [{"data": {"run_id": r.id, **({"task": r.task or ""} if with_task else {}),
                       "steps": r.steps}} for r in runs]
    config = CONFIG.replace("  <Paragraphs", '  <Text name="task" value="$task"/>\n  <Paragraphs'
                            ) if with_task else CONFIG
    return json.dumps(scrub_value(tasks), indent=2, ensure_ascii=False) + "\n", config


# The export -> labels and guesses ---------------------------------------------------------

def _number_of(result) -> tuple[str, object]:
    """How an annotation or a prediction answers the first wrong step: ("none", None) when no
    number region is there, else ("ok", the number as given). The region named
    first_wrong_step, or the only number region."""
    regions = [r for r in result if isinstance(r, dict) and r.get("type") == "number"
               and isinstance(r.get("value"), dict)] if isinstance(result, list) else []
    named = [r for r in regions if r.get("from_name") == STEP_FIELD]
    chosen = named[0] if named else regions[0] if len(regions) == 1 else None
    if chosen is None or "number" not in chosen["value"]:
        return "none", None
    return "ok", chosen["value"]["number"]


def usable(number, n_steps: int | None) -> int | None:
    """`number` as a first wrong step: a whole number from 0 to the last step (when known)."""
    if not _whole(number) or isinstance(number, float) and not math.isfinite(number):
        return None
    if number != int(number) or number < 0 or (n_steps is not None and number > n_steps):
        return None
    return int(number)


def _who(completed_by) -> int | None:
    """The annotator's user id, and nothing else of `completed_by`."""
    if isinstance(completed_by, dict):
        completed_by = completed_by.get("id")
    return completed_by if isinstance(completed_by, int) and not isinstance(
        completed_by, bool) else None


def _when(item: dict) -> str:
    stamp = item.get("updated_at") or item.get("created_at")
    return stamp if isinstance(stamp, str) else ""


def _people(annotations, n_steps: int | None, who_count: dict[str, int]) -> tuple[str, int | None]:
    """(state, label) of one run from its annotations: cancelled ones and ones with no number
    are no label; a person who labelled twice counts once, the newest; one label stands;
    several: the single ground_truth one, else the label they all gave, else disagreed."""
    given: dict[object, tuple[str, int, bool]] = {}
    unusable = 0
    for index, ann in enumerate(annotations if isinstance(annotations, list) else []):
        if not isinstance(ann, dict) or ann.get("was_cancelled"):
            continue
        status, number = _number_of(ann.get("result"))
        if status == "none":
            continue
        value = usable(number, n_steps)
        if value is None:
            unusable += 1
            continue
        who = _who(ann.get("completed_by"))
        key = who if who is not None else ("unnamed", index)
        newest = given.get(key)
        if newest is None or _when(ann) >= newest[0]:
            given[key] = (_when(ann), value, ann.get("ground_truth") is True, who)
    for _, _, _, who in given.values():
        if who is not None:
            who_count[str(who)] = who_count.get(str(who), 0) + 1
    if not given:
        return ("unusable" if unusable else "no_label"), None
    labels = {v[1] for v in given.values()}
    if len(given) == 1 or len(labels) == 1:
        return "label", next(iter(labels))
    truth = [v[1] for v in given.values() if v[2]]
    if len(truth) == 1:
        return "label", truth[0]
    return "disagreed", None


def read_export(path: Path, wanted_name: str | None = None) -> Export:
    """The tasks of a Label Studio export of a steps project."""
    try:
        data = textio.read_json(path, StepsError)
    except ValueError:
        raise StepsError(NOT_EXPORT.format(name=path.name)) from None
    tasks_in = data if isinstance(data, list) else None
    if tasks_in and all(isinstance(t, dict) and "data" not in t for t in tasks_in) and any(
            STEP_FIELD in t for t in tasks_in):
        raise StepsError(FLAT_EXPORT.format(name=path.name))  # JSON_MIN: one flat row each
    if not tasks_in or not all(isinstance(t, dict) and isinstance(t.get("data"), dict)
                               for t in tasks_in):
        raise StepsError(NOT_EXPORT.format(name=path.name))
    if not any(isinstance(t["data"].get("steps"), list) for t in tasks_in):
        keys = sorted({k for t in tasks_in for k in t["data"] if isinstance(k, str)})
        raise StepsError(NO_STEPS_IN_EXPORT.format(name=path.name,
                                                   keys=", ".join(keys[:10]) or "nothing"))
    export = Export(path.name, [], {}, {}, {})
    counts = dict.fromkeys(("labelled", "disagreed", "no_label", "unusable"), 0)
    for item in tasks_in:
        data = item["data"]
        n_steps = len(data["steps"]) if isinstance(data.get("steps"), list) else None
        raw_id = next((data[k] for k in ("run_id", "id") if isinstance(data.get(k), (str, int))
                       and not isinstance(data.get(k), bool) and str(data[k]).strip()),
                      item.get("id"))
        task = Task(str(raw_id), n_steps)
        task.state, task.label = _people(item.get("annotations"), n_steps, export.who)
        counts["labelled" if task.state == "label" else task.state] += 1
        export.tasks.append(task)
        for pred in item.get("predictions") or []:
            if not isinstance(pred, dict):
                export.ids_only = True
                continue
            status, number = _number_of(pred.get("result"))
            if status == "none":
                continue
            model = pred.get("model_version")
            name = model if isinstance(model, str) and model.strip() else DEFAULT_REVIEWER
            stamp = pred.get("created_at") if isinstance(pred.get("created_at"), str) else None
            export.guesses.setdefault(name, {})[task.id] = number
            if stamp and stamp > (export.created.get(name) or ""):
                export.created[name] = stamp
    export.stats = {"tasks": len(tasks_in), **counts}
    return export


def read_guesses(path: Path) -> tuple[dict, dict]:
    """(reviewer -> run id -> number, reviewer -> fingerprint fields given) from a JSONL file
    of {id, first_wrong_step, model}; a line may also say provider, snapshot, prompt_hash,
    rubric_version or temperature, and when it was judged (created_at or timestamp; the
    newest of a reviewer's lines is its fingerprint's created_at)."""
    guesses: dict[str, dict] = {}
    given: dict[str, dict] = {}
    text = textio.read_utf8(path, StepsError)
    for number, line in enumerate(textio.jsonl_lines(text), 1):
        if not line.strip():
            continue
        try:
            row = textio.loads(line)
        except ValueError:
            raise StepsError(f"Line {number} of {path.name} is not valid JSON.") from None
        if not isinstance(row, dict) or not isinstance(row.get("id"), (str, int)) or \
                isinstance(row.get("id"), bool):
            raise StepsError(f"Line {number} of {path.name} has no id.")
        if not _whole(row.get(STEP_FIELD)):
            raise StepsError(f"Line {number} of {path.name} has no number in "
                             f"{STEP_FIELD} (0 = all fine).")
        model = row.get("model")
        name = model if isinstance(model, str) and model.strip() else DEFAULT_REVIEWER
        guesses.setdefault(name, {})[str(row["id"])] = row[STEP_FIELD]
        keep = {k: row[k] for k in ("provider", "snapshot", "prompt_hash", "rubric_version",
                                    "temperature") if k in row}
        entry = given.setdefault(name, keep)
        stamp = next((row[k] for k in ("created_at", "timestamp")
                      if isinstance(row.get(k), str) and row[k].strip()), None)
        if stamp and stamp > (entry.get("created_at") or ""):
            entry["created_at"] = stamp  # the newest line's time is the fingerprint's
    return guesses, given


# The numbers ------------------------------------------------------------------------------

def kappa_range(tp: int, fn: int, fp: int, tn: int, kappa: float | None) -> list:
    """Kappa's range from Jeffreys draws of the four cells (the way weighted.py draws its
    ranges: the same level, number of draws and seed)."""
    if kappa is None:
        return [None, None]
    rng = random.Random(weighted.SEED)
    values = []
    for _ in range(weighted.DRAWS):
        cells = [rng.gammavariate(c + 0.5, 1.0) for c in (tp, fn, fp, tn)]
        value = weighted._table_kappa(*cells)
        if value is not None:
            values.append(value)
    return weighted.middle(sorted(values), weighted.LEVEL, kappa)


def compare(tasks: list[Task], guesses: dict) -> dict:
    """One reviewer's numbers against the people's labels."""
    people, found = [], []
    steps = []
    known = {task.id for task in tasks}
    left = {"no_guess": 0, "unusable": 0, "not_in_export": len(set(guesses) - known)}
    for task in tasks:
        if task.state != "label":
            continue
        if task.id not in guesses:
            left["no_guess"] += 1
            continue
        guess = usable(guesses[task.id], task.n_steps)
        if guess is None:
            left["unusable"] += 1
            continue
        people.append("wrong" if task.label else "fine")
        found.append("wrong" if guess else "fine")
        if task.label and guess:
            steps.append((task.label, guess))
    agree = metrics.agreement(people, found, "wrong", "fine")
    c = agree["confusion"]
    n_wrong, n_fine = c["tp"] + c["fn"], c["tn"] + c["fp"]
    rough = targets.ROUGH
    run_level = {"n": len(people), "n_wrong": n_wrong, "n_fine": n_fine,
                 "tpr": metrics.wilson(c["tp"], n_wrong) if n_wrong >= rough else None,
                 "tnr": metrics.wilson(c["tn"], n_fine) if n_fine >= rough else None,
                 "kappa": None, "kappa_interval": [None, None],
                 "needed_of_each_kind": rough}
    if n_wrong >= rough and n_fine >= rough:
        run_level["kappa"] = agree["kappa"]
        run_level["kappa_interval"] = kappa_range(c["tp"], c["fn"], c["fp"], c["tn"],
                                                  agree["kappa"])
    run_level["too_few"] = n_wrong < rough or n_fine < rough
    step_level = {"n": len(steps), "same": None, "within_one": None, "needed": rough,
                  "too_few": len(steps) < rough}
    if len(steps) >= rough:
        step_level["same"] = metrics.wilson(sum(a == b for a, b in steps), len(steps))
        step_level["within_one"] = metrics.wilson(sum(abs(a - b) <= 1 for a, b in steps),
                                                  len(steps))
    return {"runs_compared": len(people), "left_out": left, "run_level": run_level,
            "step_level": step_level}


def has_number(reviewer: dict) -> bool:
    run, step = reviewer["run_level"], reviewer["step_level"]
    return any(x is not None for x in (run["tpr"], run["tnr"], step["same"]))


# The command ------------------------------------------------------------------------------

def _say(text: str = "") -> None:
    from judgekeeper.cli import _say as say

    say(text)


def _pct(w: dict) -> str:
    """"80% (12 of 15; between 55% and 93%)"."""
    pct = textio.percent
    return f"{pct(w['p'])} ({w['k']} of {w['n']}; between {pct(w['lo'])} and {pct(w['hi'])})"


def _num(x: float) -> str:
    return f"{x:.2f}"


def _reviewer_lines(name: str, r: dict) -> list[str]:
    run, step = r["run_level"], r["step_level"]
    need = run["needed_of_each_kind"]
    compared = plural(r["runs_compared"], "run")
    lines = [f'Reviewer "{name}" against your people, on {compared} both labelled:']
    for what, key, n in (("went wrong", "tpr", run["n_wrong"]),
                         ("were fine", "tnr", run["n_fine"])):
        said = (f"your reviewer also says so for {_pct(run[key])}." if run[key]
                else f"too few ({n}) for a number; {need} are needed.")
        lines.append(f"  Runs your people say {what}: {said}")
    if run["kappa"] is not None:
        lo, hi = run["kappa_interval"]
        lines.append(f"  Kappa: {_num(run['kappa'])} (between {_num(lo)} and {_num(hi)}).")
    elif run["n_wrong"] >= need and run["n_fine"] >= need:
        lines.append("  Kappa: none (your people or your reviewer gave the same answer for "
                     "every run).")
    else:
        lines.append("  Kappa: too few runs of one kind for a number.")
    lines.append(f"How often your reviewer finds the same first wrong step as your people, on "
                 f"the {step['n']} runs both say went wrong:")
    if step["same"]:
        lines.append(f"  The same first wrong step: {_pct(step['same'])}.")
        lines.append(f"  Within one step: {_pct(step['within_one'])}.")
    else:
        lines.append(f"  Too few runs ({step['n']}) for a number; {step['needed']} are needed.")
    return lines


def _fingerprint(name: str, created: str | None, given: dict) -> JudgeFingerprint:
    return JudgeFingerprint(**{
        "model": None if name == DEFAULT_REVIEWER else name, "created_at": created,
        **{k: v for k, v in given.items() if k in JudgeFingerprint.__dataclass_fields__}})


def _command(path: str, reviewer: str | None) -> str:
    words = ["steps", path_word(path)]
    if reviewer is not None:
        words += ["--reviewer", path_word(reviewer)]
    return program(" ".join(words))


def _is_export(path: Path) -> bool:
    if path.suffix.lower() == ".json":
        return True
    head = textio.read_regular(path, 4096).decode("utf-8", "replace").lstrip("﻿ \t\r\n")
    return head.startswith("[")


def run(path: str | None = None, reviewer: str | None = None, model: str | None = None) -> int:
    from judgekeeper.check import no_such

    given = Path(path if path is not None else ".")
    if not given.exists():
        raise StepsError(no_such(str(given)))
    file = given
    if given.is_dir():
        file = given / RUNS_FILE
        if not file.is_file():
            raise StepsError(f"There is no {RUNS_FILE} in {given.name or 'this folder'}: give "
                             "judgekeeper steps your runs file (JSONL) or your Label Studio "
                             "export (JSON).")
    elif (bad := textio.not_a_file(file)) is not None:
        raise StepsError(textio.not_a_file_message(file, bad.kind))
    if file.suffix.lower() == ".csv":
        raise StepsError(FLAT_EXPORT.format(name=file.name))
    shown = str(given)
    _say(f"judgekeeper {__version__}")
    _say()
    if _is_export(file):
        return _numbers(file, shown, reviewer, model)
    if reviewer is not None or model is not None:
        raise StepsError("--reviewer and --model are for a Label Studio export; "
                         f"{file.name} is a runs file.")
    return _screen(file, given)


def _workspace(given: Path) -> Workspace:
    ws = Workspace(project.project_of(given))
    make_folder(ws)
    textio.make_private(ws.dir / FOLDER)
    return ws


def _screen(file: Path, given: Path) -> int:
    runs = read_runs(file)
    tasks, config = screen_files(runs)
    ws = _workspace(given)
    folder = ws.dir / FOLDER
    write_replacing(folder / TASKS_FILE, tasks)
    write_replacing(folder / CONFIG_FILE, config)
    _say(f"Wrote {plural(len(runs), 'run')} for Label Studio to {SHOWN}/{TASKS_FILE} and the "
         f"labelling setup to {SHOWN}/{CONFIG_FILE}.")
    _say()
    export = program("steps EXPORT.json")
    _say("Next: " + NEXT_LABEL.format(config=f"{SHOWN}/{CONFIG_FILE}",
                                       tasks=f"{SHOWN}/{TASKS_FILE}", export=export))
    return EXIT_OK


def _numbers(file: Path, shown: str, reviewer: str | None, model: str | None) -> int:
    export = read_export(file)
    guesses, given = export.guesses, {}
    if reviewer is not None:
        if textio.not_a_file(Path(reviewer)) is not None or not Path(reviewer).exists():
            raise StepsError(f"{Path(reviewer).name} is not a file judgekeeper can read.")
        guesses, given = read_guesses(Path(reviewer))
        export.created = {}
    if model is not None:
        if model not in guesses:
            names = ", ".join(sorted(guesses)) or "none"
            raise StepsError(f"No reviewer named {model!r} in the guesses (found: {names}).")
        guesses = {model: guesses[model]}
    command = _command(shown, reviewer)
    stats = export.stats
    people = {"tasks": stats["tasks"], "labelled": stats["labelled"],
              "disagreed": stats["disagreed"], "no_label": stats["no_label"],
              "unusable": stats["unusable"], "who": dict(sorted(export.who.items()))}
    reviewers = []
    for name, found in guesses.items():
        numbers = compare(export.tasks, found)
        fp = _fingerprint(name, export.created.get(name), given.get(name, {}))
        reviewers.append({"name": name, "model": fp.model, "fingerprint": fp.to_dict(),
                          "unknown_fields": unknown_fields(fp.to_dict()), **numbers})
    if stats["tasks"] == 1:
        labelled = "your people labelled it" if stats["labelled"] else "your people did not label it"
    else:
        labelled = f"your people labelled {stats['labelled']} of them"
    _say(f"Read {plural(stats['tasks'], 'run')} from {file.name}: {labelled}.")
    if stats["disagreed"]:
        _say(f"People disagreed on {plural(stats['disagreed'], 'run')}; they are left out of "
             "these numbers.")
    if stats["unusable"]:
        _say(f"{plural(stats['unusable'], 'run')} had a number that is not a step of the run "
             "(a whole number from 0 to the last step); they are left out.")
    _write_result(shown, people, reviewers, _given(file, reviewer))
    if not stats["labelled"]:
        _say()
        _say(f"No first wrong step is labelled in {file.name} yet.")
        _say()
        _say("Next: " + NEXT_NO_LABELS.format(command=command))
        return EXIT_NEEDS_YOU
    if not reviewers:
        _say()
        _say(f"{file.name} has no reviewer guesses"
             + (": Label Studio exports hold only the ids of predictions unless you ask for "
                "the full ones." if export.ids_only else "."))
        _say()
        _say("Next: " + NEXT_GUESSES.format(command=_command(shown, None)))
        return EXIT_NEEDS_YOU
    for entry in reviewers:
        _say()
        for line in _reviewer_lines(entry["name"], entry):
            _say(line)
        left = entry["left_out"]
        if left["no_guess"] or left["unusable"]:
            _say(f"  Left out: {left['no_guess']} with no guess from this reviewer, "
                 f"{left['unusable']} with a guess that is not a step of the run.")
        if left["not_in_export"]:
            n = left["not_in_export"]
            _say(f"  Left out: {n} guess is for a run that is not in {file.name}." if n == 1
                 else f"  Left out: {n} guesses are for runs that are not in {file.name}.")
    _say()
    _say(f"Saved in {SHOWN}/{RESULT_FILE}.")
    _say()
    if not any(has_number(r) for r in reviewers):
        _say("Next: " + NEXT_MORE.format(command=command))
        return EXIT_NEEDS_YOU
    if any(r["run_level"]["too_few"] or r["step_level"]["too_few"] for r in reviewers):
        _say("Next: " + NEXT_MORE.format(command=command))
    else:
        _say("Next: " + NEXT_AGAIN.format(command=_command(shown, None)))
    return EXIT_OK


def _given(file: Path, reviewer: str | None) -> dict:
    return {"export": file.name, "reviewer_file": Path(reviewer).name if reviewer else None}


def _write_result(shown: str, people: dict, reviewers: list, source: dict) -> None:
    ws = _workspace(Path(shown))
    data = {"kind": "agent-steps", "judgekeeper": __version__, "made_at": utc_now(),
            "source": source, "people": people, "reviewers": reviewers}
    write_replacing(ws.dir / FOLDER / RESULT_FILE,
                    json.dumps(scrub_value(data), indent=2, ensure_ascii=False) + "\n")
