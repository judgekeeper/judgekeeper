"""`judgekeeper start`: find the judge's saved results, make the pool of answers, say what was
found.

No AI call and no API key: everything comes from files the user's eval tool already saved
(see judgekeeper.find for where it looks). judgekeeper never runs the user's app, eval or
code; when there are too few answers it prints the command that makes more, and the user
runs it.

The pool is every answer with a clear pass or fail from the judge. An answer is its input
and output, plus the agent's steps when the results keep them (`derive_record_id`), so a
repeat of the same answer counts once: the newest
results file wins, and inside it the majority of its verdicts, a tie going to fail. Verdicts
that are errors or cannot be mapped are left out and counted.

Questions are asked only at a terminal (stdin). Without one, `start` prints the question as
the flag that answers it and exits 2; `--yes` takes the default answer of a yes/no question,
but never picks between tools or judges.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import find
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, _example, parse_label_map
from judgekeeper.readers import read_deepeval, read_inspect, read_mlflow, read_promptfoo
from judgekeeper.readers.inspect_logs import DEFAULT_PROMPT
from judgekeeper.readers.promptfoo import is_stripped_warning
from judgekeeper.records import (
    HUMAN,
    LLM,
    RecordList,
    RecordsError,
    ScoreRecord,
    _consensus,
    _verdict_value,
    derive_record_id,
    fingerprint_known,
)
from judgekeeper.redact import printable, scrub
from judgekeeper.table import _blank, make_fingerprint, read_table
from judgekeeper.textio import quote_arg, tick

EXIT_OK = 0
EXIT_USAGE = 2

MIN_POOL = 30  # a rough check needs ROUGH of each
MIN_GROUP = 5
ROUGH = 15
RELIABLE = 25
RUBRIC_WIDTH = 60
GIVEN_BY_YOU = "given by you"
POINT_ME = "Point me at the results: judgekeeper start path/to/results.json"
PAIRWISE = ("These are A/B comparisons. judgekeeper start handles pass/fail answers for now; "
            "see judgekeeper import.")
HUMAN_COLUMNS = ("human_label", "label")
FILE_READERS = {"promptfoo": read_promptfoo, "deepeval": read_deepeval, "inspect": read_inspect}
_TEST_FILE = re.compile(rb'"testFile"\s*:\s*"([^"\\]{1,200})"')
_TASK_FILE = re.compile(rb'"task_file"\s*:\s*"([^"\\]{1,200})"')
_DESCRIPTION = re.compile(r"^description:\s*(.*?)\s*$", re.MULTILINE)


class StartError(Exception):
    """`start` cannot go on: a usage error (exit 2)."""


class Stop(Exception):
    """`start` stops here, having said why."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _interactive() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


class Talk:
    """What `start` says, and the questions it asks when there is a person to answer."""

    def __init__(self, yes: bool = False, quiet: bool = False):
        self.yes = yes
        self.quiet = quiet
        self._blank = True  # the last line said was empty: never two in a row

    def say(self, text: str = "") -> None:
        if self.quiet or (not text and self._blank):
            return
        print(printable(scrub(text)))
        sys.stdout.flush()  # piped or in the background, lines must not wait in a buffer
        self._blank = not text

    def choose(self, title: str, options: list[str], flag_hint: str,
               ask: str = "Which one?") -> int:
        """The index of the option the person picks. Without a terminal: the hint, exit 2."""
        if not _interactive():
            for line in flag_hint.splitlines():
                self.say(line)
            raise Stop(EXIT_USAGE)
        self.say(title)
        for n, option in enumerate(options, 1):
            self.say(f"  {n}. {option}")
        while True:
            answer = self._input(f"{ask} [1-{len(options)}]: ")
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1

    def confirm(self, question: str, default: bool, hint: str, with_yes: bool) -> bool:
        """Yes or no. Without a terminal, `--yes` answers `with_yes`; else the hint, exit 2."""
        if not _interactive():
            if self.yes:
                return with_yes
            self.say(hint)
            raise Stop(EXIT_USAGE)
        while True:
            answer = self._input(f"{question} {'[Y/n]' if default else '[y/N]'} ").lower()
            if not answer:
                return default
            if answer in ("y", "yes", "n", "no"):
                return answer.startswith("y")

    def ask(self, question: str, default: str) -> str | None:
        """A short text answer at a terminal (Enter takes `default`); None without one."""
        if not _interactive():
            return None
        return self._input(f"{question} [{default}] ") or default

    def ask_yes(self, question: str) -> bool:
        """A yes/no confirmation at a terminal, default yes; False without one."""
        if not _interactive():
            return False
        return self.confirm(question, default=True, hint=question, with_yes=False)

    def _input(self, prompt: str) -> str:
        try:
            return input(printable(prompt)).strip()
        except EOFError:
            raise Stop(EXIT_USAGE) from None


# The pool --------------------------------------------------------------------------------

@dataclass
class Answer:
    id: str
    input: object
    output: object
    verdict: str  # pass or fail
    reason: str
    score: float | None
    fingerprint: JudgeFingerprint
    source: str
    agent: dict = field(default_factory=dict)  # trajectory, outcome, app_version: kept, not shown


@dataclass
class Pool:
    answers: list[Answer] = field(default_factory=list)
    n_unclear: int = 0
    unmapped: list = field(default_factory=list)
    n_merged: int = 0
    n_human: int = 0

    @property
    def n_pass(self) -> int:
        return sum(a.verdict == "pass" for a in self.answers)

    @property
    def n_fail(self) -> int:
        return sum(a.verdict == "fail" for a in self.answers)


def _known(evaluator: dict) -> dict:
    return fingerprint_known(evaluator)


def _identity(records: RecordList, metric: str) -> frozenset:
    return frozenset(make_fingerprint(_known(r.evaluator)).identity() for r in records
                     if r.annotator_kind == LLM and r.name == metric)


def build_pool(files: list[tuple[str, RecordList]], metric: str, norm: Normaliser) -> Pool:
    """The pool from the judge `metric`'s verdicts in `files`, newest file first."""
    pool = Pool()
    chosen: dict[str, Answer] = {}
    for source, records in files:
        groups: dict[str, list] = {}
        for r in records:
            if r.annotator_kind == HUMAN:
                pool.n_human += 1
                continue
            if r.annotator_kind != LLM or r.name != metric:
                continue
            try:
                v = norm(_verdict_value(r, norm.pass_if))
            except UnmappedValue as e:
                pool.n_unclear += 1
                if e.value not in pool.unmapped:
                    pool.unmapped.append(e.value)
                continue
            if v.verdict == ERROR:
                pool.n_unclear += 1
                continue
            groups.setdefault(derive_record_id(r.input, r.output, r.trajectory),
                              []).append((r, v))
        for key, judged in groups.items():
            if key in chosen:  # a newer file has this answer
                pool.n_merged += len(judged)
                continue
            pool.n_merged += len(judged) - 1
            passes = sum(v.verdict == "pass" for _, v in judged)
            verdict = "pass" if passes * 2 > len(judged) else "fail"
            r, v = next((r, v) for r, v in reversed(judged) if v.verdict == verdict)
            chosen[key] = Answer(
                id=key, input=r.input, output=r.output, verdict=verdict,
                reason=v.rationale or r.explanation or "", score=v.raw_score,
                fingerprint=make_fingerprint(_known(r.evaluator), r.created_at), source=source,
                agent=r.agent())
    pool.answers = list(chosen.values())
    return pool


# Reading ---------------------------------------------------------------------------------

def read_results_table(path: Path) -> RecordList:
    """A plain table (input, output and a verdict column) as judge records; a human label
    column, when there is one, as human records (counted, not used). A `model` (or
    `judge_model`) column names the judge's model, an `app_version` column the app's."""
    rows = read_table(path)
    columns = list(dict.fromkeys(k for row in rows for k in row))
    if "output_a" in columns and "output_b" in columns:
        raise StartError(PAIRWISE)
    verdict = next((c for c in find.VERDICT_COLUMNS if c in columns), None)
    if verdict is None or "input" not in columns or "output" not in columns:
        raise StartError(f"{path.name} needs input, output and verdict columns; columns are: "
                         f"{', '.join(columns)}")
    human = next((c for c in HUMAN_COLUMNS if c in columns), None)
    records = RecordList(ids_derived=True)
    for row in rows:
        content = {"target_id": derive_record_id(row.get("input"), row.get("output")),
                   "input": row.get("input"), "output": row.get("output")}
        model = row.get("model") if not _blank(row.get("model")) else row.get("judge_model")
        records.append(ScoreRecord(
            name=verdict, annotator_kind=LLM,
            label=None if _blank(row.get(verdict)) else row[verdict],
            explanation=None if _blank(row.get("reason")) else str(row["reason"]),
            evaluator={} if _blank(model) else {"model": str(model)},
            app_version=None if _blank(row.get("app_version")) else str(row["app_version"]),
            **content))
        if human and not _blank(row.get(human)):
            records.append(ScoreRecord(name=verdict, annotator_kind=HUMAN, label=row[human],
                                       **content))
    return records


@dataclass
class Loaded:
    """One results file (or one MLflow run), read."""

    label: str
    records: RecordList


def _read(result: find.Result) -> Loaded:
    if result.tool == "table":
        records = read_results_table(result.path)
    else:
        records = FILE_READERS[result.tool](result.path)
    stripped = [w for w in records.warnings if is_stripped_warning(w)]
    if stripped:
        raise StartError(stripped[0])
    return Loaded(result.rel, records)


def _where(result: find.Result) -> str:
    return f"{result.rel}, saved {result.date():%Y-%m-%d %H:%M}"


def _folder_of(result: find.Result) -> str:
    parent = Path(result.rel).parent.as_posix()
    return result.rel if parent == "." else f"{parent}/"


def _needs_extra(talk: Talk, tool: str, where: str) -> Stop:
    talk.say(f"{find.NAMES[tool]} found ({where}). To read it, add the extra in your "
             f"project's environment: pip install \"judgekeeper[{find.EXTRAS[tool]}]\", then "
             "run judgekeeper start again.")
    return Stop(EXIT_USAGE)


def _has(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _mlflow_runs(talk: Talk, store: find.Result, experiment: str | None,
                 metric: str | None = None) -> tuple[str, list[Loaded]]:
    """(experiment name, its runs newest first). The store is opened read-only. `metric`
    (--metric) may name a judge whose assessments are only on spans."""
    if not _has("mlflow"):
        raise _needs_extra(talk, "mlflow", f"{store.rel}/" if store.path.is_dir() else store.rel)
    if store.path.is_dir():
        uri = str(store.path)
    else:
        uri = f"sqlite:///file:{store.path.as_posix()}?mode=ro&uri=true"
    if experiment is not None:
        found = [(experiment, read_mlflow(experiment, tracking_uri=uri, metric=metric))]
    else:
        from mlflow import MlflowClient

        found = []
        for exp in MlflowClient(tracking_uri=uri).search_experiments():
            try:
                runs = read_mlflow(exp.name, tracking_uri=uri, metric=metric)
            except RecordsError:  # an experiment with no traces
                continue
            if any(r.annotator_kind == LLM for _, recs in runs for r in recs):
                found.append((exp.name, runs))
        if not found:
            raise StartError(f"no MLflow experiment in {store.rel} has judge assessments")
        if len(found) > 1:
            names = [name for name, _ in found]
            found = [found[talk.choose(
                "Several MLflow experiments have judge results:", names,
                f"Several MLflow experiments have judge results; choose one with "
                f"{_or([f'--experiment {quote_arg(n)}' for n in names])}")]]
    name, runs = found[0]
    judged = [Loaded(label, recs) for label, recs in runs if label != "human assessments"]
    humans = [r for label, recs in runs if label == "human assessments" for r in recs
              if r.annotator_kind == HUMAN]
    judged.reverse()  # newest run first
    if judged:
        judged[0].records.extend(humans)  # counted in the pool's note, never used
    return name, judged


# Finding ---------------------------------------------------------------------------------

@dataclass
class Found:
    root: Path
    tool: str
    results: list[find.Result]  # the readable results of the chosen tool, newest first
    used: list[str]  # labels of the files (or MLflow runs) in the pool, newest first
    metric: str
    pool: Pool
    fingerprint: dict
    judge: str  # the judge, as `Your judge:` names it
    signs: dict
    rule: str | None = None  # the judge's whole rule, as its results file holds it
    description: str | None = None  # promptfoo's `config.description` of the newest results
    metrics: list[str] = field(default_factory=list)  # every judge in the newest results
    app_version: str | None = None  # the app's version in the pool, when the results say it


def _or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


# Why a tool seen in the project has no results judgekeeper can read. "Run your eval" only
# where the tool's normal run writes the files judgekeeper reads.
NO_RESULTS = {
    "deepeval": ("but DeepEval saves results only when your tests run through deepeval test "
                 "run or evaluate(); calling a metric's measure() directly saves nothing."),
    "inspect": ("but it has no saved logs in this folder yet. Run your eval (inspect eval saves "
                "its logs in logs/), then run judgekeeper start again."),
    "mlflow": "but it has no saved judge assessments in this folder yet.",
}


def _nothing_found(talk: Talk, root: Path, signs: dict) -> None:
    from judgekeeper import own_format

    talk.say(f"No saved eval results found in {root}.")
    for tool, where in signs.items():
        talk.say(f"{find.NAMES[tool]} is used here ({where[0]}), "
                 + NO_RESULTS.get(tool, "but it has no saved results in this folder yet."))
    own = own_format.search(root)
    how = (f"turn it into a table with input, output and verdict columns (see "
           f"{own_format.OWN_FORMAT_URL}), or ask your coding agent with the prompt below.")
    if own is not None:
        talk.say(f"{own.rel} looks like saved judge results in your own format.")
        talk.say(f"To use it: {how}")
    elif "deepeval" in signs:
        talk.say("If your judge saves its results in a format of its own: "
                 + how.replace("turn it into", "turn them into"))
    if own is not None or "deepeval" in signs:
        talk.say()
        talk.say("Paste this into your coding agent (Claude Code, Cursor or Codex):")
        talk.say()
        for line in own_format.AGENT_PROMPT.splitlines():
            talk.say(line)
        talk.say()
    talk.say("judgekeeper start reads the results that promptfoo, DeepEval, Inspect AI and "
             "MLflow save, or a CSV or JSONL file with input, output and verdict columns.")
    talk.say(POINT_ME)


def _promptfoo_export(talk: Talk) -> None:
    """The commands that write promptfoo's last run to a file."""
    for line in (
        "  Write your last run to a file (this runs nothing and costs nothing):",
        "",
        "    promptfoo list evals -n 10",
        "    promptfoo export eval <eval id from that list> -o promptfoo-results.json",
        "",
        "  If your last promptfoo run was in this folder, this is the same:",
        "    promptfoo export eval latest -o promptfoo-results.json",
        "",
        "  Update promptfoo if this command is not found.",
        "  Then run judgekeeper start again.",
    ):
        talk.say(line)


def _export(talk: Talk, path: Path, tool: str | None, root: Path, config: str):
    """promptfoo results only in promptfoo's database: offer to export them (start_export),
    then carry on with the file; else print the export commands and stop."""
    from judgekeeper import start_export

    talk.say(f"{tick()} Your eval tool: promptfoo ({config})")
    talk.say("  No promptfoo results file in this folder. promptfoo keeps them in its own "
             "database.")
    outcome = start_export.offer(talk, root)
    if outcome == "done":
        return _locate(talk, path, tool)
    if outcome == "commands":
        _promptfoo_export(talk)
    raise Stop(EXIT_OK)


def _locate(talk: Talk, path: Path, tool: str | None) -> tuple[Path, str, list, dict]:
    """(project folder, tool, its readable results newest first, tool signs)."""
    if not path.exists():
        raise StartError(f"file or folder not found: {path}")
    if path.is_file():
        kind = tool or find.classify_file(path)
        if kind is None:
            raise StartError(f"{path.name} is not a results file judgekeeper start can read "
                             "(promptfoo, DeepEval, Inspect AI, an MLflow store, or a table "
                             "with input, output and verdict columns)")
        path = path.resolve()
        return path.parent, kind, [find.Result(kind, path, path.name, path.stat().st_size)], {}
    root = path.resolve()
    talk.say(f"Looking in {root} ...")
    talk.say()
    found = find.search(root)
    for note in found.notes:
        talk.say(note)
    if found.stopped:
        talk.say(f"{found.stopped} {POINT_ME}")
    for big in found.too_big():
        talk.say(big.too_big_message())
    available = [t for t in find.TOOLS if found.readable(t)]
    if tool is not None:
        if tool not in available:
            if any(r.tool == tool for r in found.too_big()):
                raise Stop(EXIT_USAGE)
            if tool == "promptfoo" and "promptfoo" in found.signs:
                return _export(talk, path, tool, root, found.signs["promptfoo"][0])
            raise StartError(f"No saved {find.NAMES[tool]} results found in {root}.")
        available = [tool]
    if not available:
        if found.too_big():  # said above, with how to read them anyway
            raise Stop(EXIT_USAGE)
        if "promptfoo" in found.signs:
            return _export(talk, path, tool, root, found.signs["promptfoo"][0])
        _nothing_found(talk, root, found.signs)
        raise Stop(EXIT_USAGE)
    by_date = {t: sorted(found.readable(t), key=lambda r: r.date(), reverse=True)
               for t in available}
    kind = available[0]
    if len(available) > 1:
        options = [f"{find.NAMES[t]} ({_where(by_date[t][0])})" for t in available]
        kind = available[talk.choose(
            "Saved results from more than one eval tool:", options,
            f"Several tools found; choose one with {_or([f'--tool {t}' for t in available])}")]
    return root, kind, by_date[kind], found.signs


def results_description(result: find.Result) -> str | None:
    """The `config.description` of a promptfoo results file, or None."""
    try:
        data = json.loads(result.path.read_text(encoding="utf-8", errors="replace"))
        theirs = (data.get("config") or {}).get("description")
    except (OSError, ValueError, AttributeError):
        return None
    return (theirs.strip() or None) if isinstance(theirs, str) else None


def _check_description(talk: Talk, root: Path, theirs: str | None,
                       result: find.Result) -> None:
    """Ask before using promptfoo results whose description is not this project's."""
    mine = _project_description(root)
    if theirs is None or mine is None or theirs == mine:
        return
    question = (f'{result.rel} looks like it is from another project (its description is '
                f'"{theirs}"). Continue?')
    if not talk.confirm(question, default=False, with_yes=False,
                        hint=f"{question} Run judgekeeper start in a terminal to answer, or "
                             "point me at the right results file."):
        raise Stop(EXIT_OK)


def _project_description(root: Path) -> str | None:
    """The top-level `description:` of the project's promptfoo config: a line scan, no YAML."""
    for name in find.PROMPTFOO_CONFIGS:
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if name.endswith(".json"):
            try:
                value = json.loads(text).get("description")
            except (ValueError, AttributeError):
                return None
            return value.strip() if isinstance(value, str) else None
        m = _DESCRIPTION.search(text)
        return m[1].strip().strip("'\"").strip() if m else None
    return None


def _choose_metric(talk: Talk, newest: Loaded, metric: str | None,
                   prefer: str | None = None) -> str:
    counts = Counter(r.name for r in newest.records if r.annotator_kind == LLM)
    names = sorted(counts)
    if not names:
        raise StartError(f"{newest.label} holds no verdicts from an LLM judge")
    if metric is None and prefer in counts:
        return prefer
    if metric is not None:
        if metric not in counts:
            raise StartError(f"no judge named {metric!r}; judges are: "
                             f"{', '.join(repr(n) for n in names)}")
        return metric
    if len(names) == 1:
        return names[0]
    options = [f"{n} ({counts[n]} answers)" for n in names]
    return names[talk.choose(
        "These results hold more than one judge:", options,
        f"Several judges found; choose one with {_or([f'--metric {quote_arg(n)}' for n in names])}")]


def rule_text(prompt) -> str | None:
    """The judge's whole rule as text, or None.

    The prompt is as the reader keeps it: a promptfoo assertion value, DeepEval's
    "Criteria:" part, or Inspect's scorer options as JSON (instructions, else template).
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    try:
        data = json.loads(prompt)
    except ValueError:
        data = None
    if isinstance(data, dict):
        texts = [data.get(k) for k in ("instructions", "template")]
        texts = [t for t in texts if isinstance(t, str)
                 and not t.startswith(DEFAULT_PROMPT.split("{")[0])]
        if not texts:
            return None
        prompt = texts[0]
    elif data is not None:
        return None
    text = prompt.strip()
    if text.startswith("Criteria:"):
        text = text[len("Criteria:"):].strip()
    return text or None


def rule_of(records) -> str | None:
    """The judge's whole rule: a record's `evaluator.rule` when it has one, else read from
    the first saved prompt (rule_text)."""
    for r in records:
        rule = r.evaluator.get("rule")
        if isinstance(rule, str) and rule.strip():
            return rule.strip()
    prompt = next((r.evaluator.get("prompt") for r in records if r.evaluator.get("prompt")),
                  None)
    return rule_text(prompt)


def rubric_line(prompt) -> str | None:
    """The first line of the judge's rule (or of the rule in `prompt`), cut to
    RUBRIC_WIDTH, or None."""
    text = rule_text(prompt)
    if text is None:
        return None
    line = next(line.strip() for line in text.splitlines() if line.strip())
    return line[:RUBRIC_WIDTH - 1] + "…" if len(line) > RUBRIC_WIDTH else line


def _judge_name(tool: str, metric: str, rubric: str | None, models: list[str],
                given: bool, file_name: str) -> str:
    model = ", ".join(models)
    if len(models) > 1:
        model = f"more than one model ({model})"
    with_model = f" with {model}{' (as you told me)' if given else ''}" if models else ""
    if tool == "table":
        return f"{metric} in {file_name}{with_model}" if models else f"not named in {file_name}"
    quoted = f' "{rubric}"' if rubric else ""
    if models:
        return f"{metric}{quoted}{with_model}"
    if tool == "promptfoo":
        return "promptfoo's default grader (the results file does not say which model)"
    return f"{metric}{quoted} (the results file does not say which model)"


def find_judge(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
               experiment: str | None = None, pass_if: str | None = None,
               label_map: str | dict | None = None, judge_model: str | None = None,
               talk: Talk | None = None, prefer: str | None = None) -> Found:
    """Find the results, choose what to use, make the pool and name the judge.

    `talk` says each step and asks the questions; the default says nothing and, with no one
    to ask, stops (Stop) where a question would be needed. `prefer` (the judge of the last
    check) is chosen without asking when the newest results hold it among several.
    """
    talk = talk or Talk(quiet=True)
    root, kind, results, signs = _locate(talk, Path(path), tool)
    newest = results[0]
    description = None
    if kind == "mlflow":
        name, runs = _mlflow_runs(talk, newest, experiment, metric)
        talk.say(f"{tick()} Your eval tool: MLflow ({newest.rel}, experiment {name})")
        read_older = iter(runs[1:])
        first = runs[0] if runs else None
        if first is None:
            raise StartError(f"MLflow experiment {name!r} has no judge assessments")
    else:
        if kind == "inspect" and not _has("inspect_ai"):
            json_logs = [r for r in results if r.path.suffix.lower() != ".eval"]
            if not json_logs:
                raise _needs_extra(talk, "inspect", _folder_of(newest))
            results, newest = json_logs, json_logs[0]
        if kind == "promptfoo":
            description = results_description(newest)
            _check_description(talk, root, description, newest)
        first = _read(newest)
        talk.say(f"{tick()} Your eval tool: {find.NAMES[kind]} ({_where(newest)})")
        read_older = (_read(r) for r in results[1:])
    metric = _choose_metric(talk, first, metric, prefer)
    metrics = sorted({r.name for r in first.records if r.annotator_kind == LLM})

    norm = Normaliser(pass_if=pass_if,
                      label_map={**first.records.label_map, **parse_label_map(label_map)})
    used = [first]
    pool = build_pool([(x.label, x.records) for x in used], metric, norm)
    identity = _identity(first.records, metric)
    for older in read_older:
        if len(pool.answers) >= MIN_POOL:
            break
        if _identity(older.records, metric) == identity:
            used.append(older)
            pool = build_pool([(x.label, x.records) for x in used], metric, norm)
    if len(used) > 1:
        talk.say(f"  Fewer than {MIN_POOL} answers in the newest results, so older results "
                 f"from the same judge were added: {', '.join(x.label for x in used[1:])}")

    records = [r for x in used for r in x.records
               if r.annotator_kind == LLM and r.name == metric]
    known, _ = _consensus([a.fingerprint for a in pool.answers]) if pool.answers else ({}, [])
    fingerprint = make_fingerprint(known).to_dict()
    models = sorted({str(r.evaluator["model"]) for r in records if r.evaluator.get("model")})
    if judge_model is not None:
        if models:
            raise StartError(f"{Path(first.label).name} already names the judge's model "
                             f"({', '.join(models)}): drop --judge-model")
        fingerprint.update(model=judge_model, model_source=GIVEN_BY_YOU)
        models = [judge_model]
    rule = rule_of(records)
    rubric = rubric_line(rule)
    judge = _judge_name(kind, metric, rubric, models, judge_model is not None,
                        Path(newest.rel).name)
    talk.say(f"{tick()} Your judge: {judge}")
    versions = sorted({a.agent["app_version"] for a in pool.answers if "app_version" in a.agent})
    return Found(root=root, tool=kind, results=results, used=[x.label for x in used],
                 metric=metric, pool=pool, fingerprint=fingerprint, judge=judge, signs=signs,
                 rule=rule, description=description, metrics=metrics,
                 app_version=", ".join(versions) or None)


# What `start` says after finding ---------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


ROW_CELL = 40  # characters of a cell shown in a table's first rows


def _cell(value) -> str:
    text = " ".join(str("" if value is None else value).split())
    return text[:ROW_CELL - 1] + "…" if len(text) > ROW_CELL else text


def _first_rows(talk: Talk, found: Found) -> None:
    """A plain table's first 3 rows as read, so a wrong conversion shows at once."""
    try:
        rows = read_table(found.results[0].path)[:3]
    except (OSError, ValueError, RecordsError):
        return
    verdict = next((c for c in find.VERDICT_COLUMNS if rows and c in rows[0]), None)
    if not rows or verdict is None:
        return
    talk.say(f"  The first {len(rows)} rows, as judgekeeper read them:")
    for row in rows:
        talk.say(f"    input: {_cell(row.get('input'))}   output: {_cell(row.get('output'))}   "
                 f"{verdict}: {_cell(row.get(verdict))}")


def _say_pool(talk: Talk, found: Found) -> None:
    pool = found.pool
    talk.say(f"{tick()} {_plural(len(pool.answers), 'answer', 'answers')} with a verdict: the "
             f"judge passed {pool.n_pass} and failed {pool.n_fail}")
    if found.tool == "table":
        _first_rows(talk, found)
    if pool.n_merged:
        talk.say("  " + (f"{pool.n_merged} repeats of the same answer were merged."
                         if pool.n_merged != 1 else
                         "1 repeat of the same answer was merged."))
    if pool.n_unclear:
        talk.say("  " + (f"{pool.n_unclear} answers had no clear verdict and were left out."
                         if pool.n_unclear != 1 else
                         "1 answer had no clear verdict and was left out."))
    if pool.unmapped:
        words = [str(v) for v in pool.unmapped]
        shown = ", ".join(repr(w) for w in words[:5])
        talk.say(f"  To count {shown}, map {'it' if len(words) == 1 else 'them'} with "
                 f'--label-map, e.g. --label-map "{_example(words)}"')
    if pool.n_human:
        where = (f"{Path(found.used[0]).name} also holds" if len(found.used) == 1
                 else "These results also hold")
        talk.say(f"  {where} {_plural(pool.n_human, 'human label', 'human labels')}. "
                 "judgekeeper start does not use them: you label the answers yourself.")


def _head_value(found: Found, pattern: re.Pattern, default: str) -> str:
    try:
        m = pattern.search(find._head(found.results[0].path))
    except OSError:
        m = None
    return quote_arg(m[1].decode("utf-8", errors="replace")) if m else default


def more_answers(found: Found) -> list[str]:
    """How to make more answers with the user's own tool. judgekeeper runs none of it."""
    newest = found.results[0]
    if found.tool == "promptfoo":
        configs = [s for s in found.signs.get("promptfoo", [])
                   if Path(s).name in find.PROMPTFOO_CONFIGS]
        config = configs[0] if configs else "promptfooconfig.yaml"
        run = f"promptfoo eval -o {quote_arg(newest.rel)}"
        return [f"  Add more tests to {config}, then run: {run}",
                "  This one runs your eval again: new answers need it."]
    if found.tool == "deepeval":
        test_file = _head_value(found, _TEST_FILE, "test_file.py")
        return [f"  Add more test cases, then run: deepeval test run {test_file}",
                ("  Tip: set DEEPEVAL_RESULTS_FOLDER so DeepEval keeps every run, not only "
                 "the latest.")]
    if found.tool == "inspect":
        return [f"  inspect eval {_head_value(found, _TASK_FILE, 'your_task.py')} --limit 100"]
    if found.tool == "mlflow":
        return ["  Run your MLflow evaluation again on more data."]
    return [f"  Add more rows to {newest.rel}."]


INTRO = (
    "You will label answers in your browser, one at a time: Correct or Wrong.",
    "You won't see what the judge said. judgekeeper picks half from the judge's",
    "passes and half from its fails, so you see enough of both.",
    "",
    f"  A rough check needs {ROUGH} Correct and {ROUGH} Wrong.",
    f"  A reliable result needs {RELIABLE} Correct and {RELIABLE} Wrong.",
    "  Most people need 10 to 20 minutes.",
)


def label_found(talk: Talk, found: Found, port: int, open_browser: bool) -> int:
    """Say the pool, check there are enough answers, then open the labeling page."""
    _say_pool(talk, found)
    pool = found.pool
    n = len(pool.answers)
    if not n:
        raise StartError("no answer has a clear pass or fail from the judge, so there is "
                         "nothing to label")
    if n < MIN_POOL or min(pool.n_pass, pool.n_fail) < MIN_GROUP:
        talk.say()
        talk.say(f"That is too few for a result: a rough check needs {ROUGH} Correct and "
                 f"{ROUGH} Wrong,")
        talk.say(f"so judgekeeper needs at least {MIN_POOL} answers, with some the judge "
                 "failed.")
        talk.say()
        talk.say("Make more answers with your own eval, then run judgekeeper start again:")
        for line in more_answers(found):
            talk.say(line)
        talk.say()
        question = f"Label the {n} you have anyway?"
        if not talk.confirm(f"{question} The result will say how unsure it is.",
                            default=False, with_yes=True,
                            hint=f"{question} Run judgekeeper start --yes to say yes."):
            return EXIT_OK
    else:
        for count, did, label in ((pool.n_pass, "passed", "Correct"),
                                  (pool.n_fail, "failed", "Wrong")):
            if count < ROUGH:
                talk.say(f"Your judge {did} only {count} answers, so you may not reach "
                         f"{ROUGH} {label}. The result will say how sure it is.")
    talk.say()
    for line in INTRO:
        talk.say(line)
    talk.say()
    if not talk.confirm("Open the labeling page now?", default=True, with_yes=True,
                        hint="Open the labeling page? Run judgekeeper start --yes to open it."):
        return EXIT_OK
    from judgekeeper import start_label

    return start_label.run_labeling(found, port=port, open_browser=open_browser, say=talk.say)


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, pass_if: str | None = None,
        label_map: str | None = None, judge_model: str | None = None,
        yes: bool = False, port: int = 8765, no_browser: bool = False,
        new: bool = False, review: bool = False, label_more: bool = False,
        ask_again: bool = False, try_new_judge: bool = False, times: int | None = None,
        python: str | None = None,
        fields: str | None = None, judge_command: str | None = None,
        allow_calls: int | None = None) -> int:
    """`judgekeeper start`: say what was found, then open the labeling page and make the
    result. What is already saved in `.judgekeeper/` decides where it starts (start_again).
    `review`, `ask_again`, `try_new_judge` and `label_more` answer the menu shown after a
    result; `times` (default 2, or 1 when trying a new judge),
    `python`, `fields`, `judge_command` and `allow_calls` shape asking the judge again.
    Returns the exit code."""
    from judgekeeper import start_again
    from judgekeeper.again import AgainOptions

    talk = Talk(yes=yes)
    again_options = AgainOptions(times=times, python=python, fields=fields,
                                 judge_command=judge_command, judge_model=judge_model,
                                 allow_calls=allow_calls)
    options = {"tool": tool, "metric": metric, "experiment": experiment, "pass_if": pass_if,
               "label_map": label_map, "judge_model": judge_model}
    try:
        then = ("review" if review else "ask" if ask_again else "try" if try_new_judge
                else "label" if label_more else None)
        return start_again.run(Path(path), talk, options, port=port,
                               open_browser=not no_browser, new=new, then=then,
                               again_options=again_options)
    except Stop as stop:
        return stop.code


__all__ = ["Answer", "Found", "Pool", "StartError", "build_pool", "find_judge",
           "label_found", "run"]
