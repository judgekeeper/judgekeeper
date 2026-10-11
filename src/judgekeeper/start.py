"""`judgekeeper start`: find the judge's saved results, make the pool of answers and say what
was found.

No AI call and no API key: everything comes from files the user's eval tool already saved
(see judgekeeper.find for where it looks). judgekeeper never runs the user's app, eval or
code; when there are too few answers it prints the command that makes more, and the user
runs it.

The pool is every answer with a clear pass or fail from the judge. An answer is its input
and output, plus the agent's steps when the results keep them (`derive_record_id`), so a
repeat of the same answer counts once: the newest results file wins, and inside it the
majority of its verdicts, a tie going to fail. An answer with no real decision from the judge
(judge_check: an error, a reply it could not read, none at all, or a check of nothing) is
left out and counted, and said; a verdict that cannot be mapped stops `start`.

Questions are asked only at a terminal (stdin). Without one, `start` prints the question as
the flag that answers it and exits 8 (EXIT_QUESTION: nothing went wrong); `--yes` takes the
default answer of a yes/no question, but never picks between tools or judges. Every printed
"run this next" command comes from `Talk.command`, so it repeats the flags the person gave.
"""

from __future__ import annotations

import json
import math
import operator
import os
import re
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import find, judge_check, settings, targets
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, parse_label_map, unmapped_error
from judgekeeper.readers import read_deepeval, read_inspect, read_mlflow, read_promptfoo
from judgekeeper.readers.inspect_logs import DEFAULT_PROMPT
from judgekeeper.readers.promptfoo import is_stripped_warning
from judgekeeper.records import (
    CUT_END,
    HUMAN,
    LLM,
    NO_MARK,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    _consensus,
    _verdict_value,
    derive_record_id,
    fingerprint_known,
    read_records,
)
from judgekeeper.redact import printable, scrub
from judgekeeper.table import _blank, make_fingerprint, read_table
from judgekeeper.textio import quote_arg, tick

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_QUESTION = 8  # stopped at a question it cannot ask (no terminal); nothing went wrong

ROUGH = targets.ROUGH  # the label targets every command shares
RELIABLE = targets.RELIABLE
MIN_POOL = 2 * ROUGH  # a rough check needs ROUGH of each
RUBRIC_WIDTH = 70  # characters of the rule's first line shown in the first block
COLUMN = 16  # the first block's label column
MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                "Dec")
GIVEN_BY_YOU = "given by you"
POINT_ME = "Point me at the results: judgekeeper start path/to/results.json"
PAIRWISE = ("These are A/B comparisons. judgekeeper start handles pass/fail answers for now; "
            "see judgekeeper import.")
HUMAN_COLUMNS = ("human_label", "label")
FILE_READERS = {"promptfoo": read_promptfoo, "deepeval": read_deepeval, "inspect": read_inspect}
_TEST_FILE = re.compile(rb'"testFile"\s*:\s*"([^"\\]{1,200})"')
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


# The flags a printed "run this next" command repeats, in this order: (run's parameter,
# flag). --port and --no-browser follow them. Left out on purpose (NOT_REPEATED): the menu's
# answers, --yes and --allow-calls, which each hint adds when it needs them.
REPEATED = (("tool", "--tool"), ("metric", "--metric"), ("experiment", "--experiment"),
            ("tracking_uri", "--tracking-uri"), ("pass_if", "--pass-if"), ("label_map", "--label-map"),
            ("judge_model", "--judge-model"), ("times", "--times"), ("python", "--python"),
            ("fields", "--fields"), ("judge_command", "--judge-command"))
NOT_REPEATED = frozenset({"new", "review", "fix", "test_pass_mark", "ask_again",
                          "try_new_judge", "label_more", "yes", "allow_calls", "agent_prompt",
                          "rule_file"})
DEFAULT_PORT = 8765


def repeated_flags(path: str | Path = ".", port: int = DEFAULT_PORT, no_browser: bool = False,
                   **values) -> tuple[str, ...]:
    """The words a printed command repeats: the path (unless this folder), each REPEATED flag
    that was given, then --port (unless the default) and --no-browser."""
    words = [] if str(path) == "." else [quote_arg(path)]
    for name, flag in REPEATED:
        if values.get(name) is not None:
            words += [flag, quote_arg(str(values[name]))]
    if port != DEFAULT_PORT:
        words += ["--port", str(port)]
    if no_browser:
        words.append("--no-browser")
    return tuple(words)


class Talk:
    """What `start` says, and the questions it asks when there is a person to answer.
    `flags` (repeated_flags) are what every printed command repeats."""

    def __init__(self, yes: bool = False, quiet: bool = False, flags: tuple[str, ...] = (),
                 path: str | Path = "."):
        self.yes = yes
        self.quiet = quiet
        self.flags = flags
        self.path = str(path)  # the path the person gave; flags[0] when it is not "."
        self._blank = True  # the last line said was empty: never two in a row

    def command(self, *extra: str) -> str:
        """`judgekeeper start` with the person's flags, then `extra`: run as printed, it gets
        past the question it answers."""
        return " ".join(("judgekeeper start", *self.flags, *extra))

    def command_at(self, where: str | Path, *extra: str) -> str:
        """`command`, with `where` (a path inside the folder the person gave) as the path."""
        given = self.flags[:1] == (quote_arg(self.path),) and self.path != "."
        flags = self.flags[1:] if given else self.flags
        path = Path(where) if self.path == "." else Path(self.path) / where
        return " ".join(("judgekeeper start", quote_arg(path), *flags, *extra))

    def say(self, text: str = "") -> None:
        if self.quiet or (not text and self._blank):
            return
        print(printable(scrub(text)))
        sys.stdout.flush()  # piped or in the background, lines must not wait in a buffer
        self._blank = not text

    def choose(self, title: str, options: list[str], flag_hint: str,
               ask: str = "Which one?") -> int:
        """The index of the option the person picks. Without a terminal: the hint, exit 8."""
        if not _interactive():
            for line in flag_hint.splitlines():
                self.say(line)
            raise Stop(EXIT_QUESTION)
        self.say(title)
        for n, option in enumerate(options, 1):
            self.say(f"  {n}. {option}")
        while True:
            answer = self._input(f"{ask} [1-{len(options)}]: ")
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1

    def confirm(self, question: str, default: bool, hint: str, with_yes: bool) -> bool:
        """Yes or no. Without a terminal, `--yes` answers `with_yes`; else the hint, exit 8."""
        if not _interactive():
            if self.yes:
                return with_yes
            self.say(hint)
            raise Stop(EXIT_QUESTION)
        while True:
            prompt = f"{question} {'[Y/n]' if default else '[y/N]'} ".lstrip()
            answer = self._input(prompt).lower()
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
            raise Stop(EXIT_QUESTION) from None


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
    mark: Mark = NO_MARK  # what the reader learned about this verdict (records.Mark)
    pass_mark: float | None = None  # the pass mark `score` was held against, when known
    pass_op: str | None = None  # how: ">=", ">", "<=" or "<"; None when only the data can tell


@dataclass
class Pool:
    answers: list[Answer] = field(default_factory=list)
    unmapped: list = field(default_factory=list)
    n_merged: int = 0
    n_human: int = 0
    left: dict = field(default_factory=dict)  # answer id: (judge_check kind, its record)

    @property
    def n_unclear(self) -> int:
        """Answers left out: no real decision from the judge."""
        return len(self.left)

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


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or math.isnan(value):
        return None
    return float(value)


def _mark_of(r: ScoreRecord, v, norm: Normaliser, threshold) -> tuple[float | None, str | None]:
    """The pass mark a verdict was made with, and how a score is held against it: --pass-if's
    rule, the pass mark judgekeeper.record() or a mapped file keeps with each verdict, or
    DeepEval's threshold (its direction left to the data)."""
    if norm.pass_if is not None and v.raw_score is not None:
        return norm.pass_if.threshold, norm.pass_if.op
    mark = _number(r.metadata.get("pass_mark"))
    if mark is not None:
        return mark, ">="
    return _number(threshold), None


def build_pool(files: list[tuple[str, RecordList]], metric: str, norm: Normaliser) -> Pool:
    """The pool from the judge `metric`'s verdicts in `files`, newest file first. An answer
    whose verdicts are all no real decision (the reader's mark, or nothing the normaliser can
    read) goes to `left` with its kind instead."""
    pool = Pool()
    chosen: dict[str, Answer] = {}
    for source, records in files:
        extra = records.per_metric.get(metric, {})
        threshold = None if extra.get("strict_mode") else extra.get("threshold")
        groups: dict[str, list] = {}
        for r in records:
            if r.annotator_kind == HUMAN:
                pool.n_human += 1
                continue
            if r.annotator_kind != LLM or r.name != metric:
                continue
            v, kind = None, r.mark.problem
            if kind is None:
                try:
                    v = norm(_verdict_value(r, norm.pass_if))
                except UnmappedValue as e:
                    if e.value not in pool.unmapped:
                        pool.unmapped.append(e.value)
                    continue
                if v.verdict == ERROR:
                    kind = judge_check.EMPTY
            groups.setdefault(derive_record_id(r.input, r.output, r.trajectory),
                              []).append((r, v, kind))
        for key, seen in groups.items():
            judged = [(r, v) for r, v, kind in seen if kind is None]
            if key in chosen or key in pool.left:  # a newer file has this answer
                pool.n_merged += len(judged)
                continue
            if not judged:
                pool.left[key] = (seen[0][2], seen[0][0])
                continue
            pool.n_merged += len(judged) - 1
            passes = sum(v.verdict == "pass" for _, v in judged)
            verdict = "pass" if passes * 2 > len(judged) else "fail"
            r, v = next((r, v) for r, v in reversed(judged) if v.verdict == verdict)
            score = v.raw_score if v.raw_score is not None else _number(r.score)
            pass_mark, pass_op = _mark_of(r, v, norm, threshold)
            chosen[key] = Answer(
                id=key, input=r.input, output=r.output, verdict=verdict,
                reason=v.rationale or r.explanation or "", score=score,
                fingerprint=make_fingerprint(_known(r.evaluator), r.created_at), source=source,
                agent=r.agent(), mark=r.mark, pass_mark=pass_mark, pass_op=pass_op)
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
    elif result.tool == "inspect":  # a sample that errored before it was scored, too
        records = read_inspect(result.path, with_errors=True)
    else:
        records = FILE_READERS[result.tool](result.path)
    stripped = [w for w in records.warnings if is_stripped_warning(w)]
    if stripped:
        raise StartError(stripped[0])
    return Loaded(result.rel, records)


def _read_records(talk: Talk, results: list[find.Result]) -> list[Loaded]:
    """The records files judgekeeper.record() wrote, newest first. A file that cannot be
    read is left out, with how to see why; a last line cut short is left out too."""
    loaded = []
    for r in results:
        try:
            records = read_records(r.path, cut_end_ok=True)
        except RecordsError as e:
            text = str(e)
            text = text[text.find("line "):] if "line " in text else text
            talk.say(f"  {r.rel} could not be read ({text}), so it was left out. To see every "
                     f"problem: judgekeeper import records {quote_arg(r.rel)} --check")
            continue
        if CUT_END in records.notes:
            talk.say(f"  Note: the last line of {r.rel} was cut short (the program stopped while "
                     "writing it) and was left out.")
        for warning in records.warnings:
            talk.say(f"  {warning}")
        loaded.append(Loaded(r.rel, records))
    return loaded


def _saved(path: Path):
    """The [start] table of the project's judgekeeper.toml, when `path` is a folder."""
    if not path.is_dir():
        return None
    try:
        return settings.load(path.resolve())
    except settings.SettingsError as e:
        raise StartError(str(e)) from None


def _mapped_source(talk: Talk, root: Path, saved) -> tuple[Path, str, list, dict]:
    """The results file judgekeeper.toml maps: no search."""
    path = root / saved.file
    if not path.is_file():
        raise StartError(f"{settings.FILE} says your judge's results are in {saved.file}, "
                         "which is not there. Run judgekeeper setup again.")
    talk.say(f"Looking in {root} ...")
    talk.say()
    return root, "mapped", [find.Result("mapped", path, saved.file, path.stat().st_size)], {}


def _read_mapped(result: find.Result, saved) -> list[Loaded]:
    from judgekeeper.readers.mapped import read_mapped

    m = {**saved.map, "judge": saved.judge, "pass_mark": saved.pass_mark, "model": saved.model}
    return [Loaded(label, records) for label, records in read_mapped(result.path, m,
                                                                     label=result.rel)]


def _where(result: find.Result) -> str:
    return f"{result.rel}, saved {result.date():%Y-%m-%d %H:%M}"


def _folder_of(result: find.Result) -> str:
    parent = Path(result.rel).parent.as_posix()
    return result.rel if parent == "." else f"{parent}/"


def _needs_extra(talk: Talk, tool: str, where: str) -> Stop:
    talk.say(f"{find.NAMES[tool]} found ({where}). To read it, add the extra in your "
             f"project's environment: pip install \"judgekeeper[{find.EXTRAS[tool]}]\", then "
             f"run {talk.command()} again.")
    return Stop(EXIT_USAGE)


def _has(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _store_name(store: find.Result) -> str:
    return f"{store.rel}/" if store.path.is_dir() else store.rel


def _mlflow_runs(talk: Talk, store: find.Result, experiment: str | None,
                 metric: str | None = None) -> tuple[str, list[Loaded]]:
    """(experiment name, its runs newest first). An mlflow.db store is read through a
    temporary copy (mlflow_store.store_uri), never opened itself. `metric` (--metric) may name
    a judge whose assessments are only on spans. MLflow's own log lines are kept out."""
    from judgekeeper.readers.mlflow_store import folder_store_allowed, quiet, store_uri

    with quiet():
        if not _has("mlflow"):
            raise _needs_extra(talk, "mlflow", _store_name(store))
        uri = store_uri(store.path, say=talk.say)
        with folder_store_allowed(uri, say=talk.say):
            return _mlflow_experiment(talk, store, experiment, metric, uri)


def _no_experiment(experiment: str, stores: list[tuple[find.Result, list[str]]]) -> StartError:
    """--experiment names none of the experiments: say each store searched and its own."""
    where = [f"{_store_name(s)} (its experiments: {', '.join(names) or 'none'})"
             for s, names in stores]
    return StartError(f"no MLflow experiment named {experiment!r} in {_or(where)}")


def _mlflow_experiment(talk: Talk, store: find.Result, experiment: str | None,
                       metric: str | None, uri: str) -> tuple[str, list[Loaded]]:
    from judgekeeper.readers.mlflow_store import TracesMissing, experiments_with_traces

    if experiment is not None:
        try:
            found = [(experiment, read_mlflow(experiment, tracking_uri=uri, metric=metric))]
        except TracesMissing as e:
            raise StartError(str(e)) from None
        except RecordsError as e:
            if not str(e).startswith("no MLflow experiment named"):
                raise
            raise _no_experiment(experiment, [(store, experiments_with_traces(uri))]) from None
    else:
        from mlflow import MlflowClient

        found, missing = [], []
        for exp in MlflowClient(tracking_uri=uri).search_experiments():
            try:
                runs = read_mlflow(exp.name, tracking_uri=uri, metric=metric)
            except TracesMissing as e:
                missing.append(str(e))
                continue
            except RecordsError:  # an experiment with no traces
                continue
            if any(r.annotator_kind == LLM for _, recs in runs for r in recs):
                found.append((exp.name, runs))
        if not found and missing:
            raise StartError(missing[0])
        if not found:
            raise StartError(f"no MLflow experiment in {store.rel} has judge assessments")
        if len(found) > 1:
            names = [name for name, _ in found]
            found = [found[talk.choose(
                "Several MLflow experiments have judge results:", names,
                f"Several MLflow experiments have judge results; choose one with "
                f"{_or([f'--experiment {quote_arg(n)}' for n in names])}")]]
            _next_time(talk, "--experiment", found[0][0])
    name, runs = found[0]
    for label, recs in runs:
        for note in recs.notes if label == "human assessments" else ():
            if "trace files are missing" in note:
                talk.say(f"  {note}")
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
    store: str | None = None  # MLflow: the store read (mlflow.db, mlruns), inside `root`
    check: judge_check.Result | None = None  # did the judge actually judge?
    # The judge's pass mark, when every answer has a number score held against the same one
    # (pass_mark_of); None for a judge that gives no score or no pass mark
    pass_mark: dict | None = None
    # whether every verdict of the judge has the same rule (no rule per test)
    one_rule: bool = True
    task_file: str | None = None  # Inspect: the task file its newest log names
    rule_field: str | None = None  # Inspect: "instructions" or "template", the rule's field
    models: list[str] = field(default_factory=list)  # the judge's model(s), as the results say
    model_source: str | None = None  # None (the results), GIVEN_BY_YOU or judgekeeper.toml
    experiment: str | None = None  # MLflow: the experiment read


PASS_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


def passes(score: float, op: str, mark: float) -> str:
    """The verdict a score gets against a pass mark."""
    return "pass" if PASS_OPS[op](score, mark) else "fail"


def pass_mark_of(pool: Pool, tool: str, pass_if=None, key: str | None = None) -> dict | None:
    """{"mark", "op", "source", "follows"} when every answer has a number score and the same
    pass mark; `follows` says whether every verdict is the score held against it. The
    direction of a DeepEval threshold comes from the verdicts (some of its metrics pass a
    lower score); when they do not tell it, None. `source` is "pass_if" (with its "rule"),
    "deepeval", "records" or "mapped" (with the "key" a mapped file states it in)."""
    answers = pool.answers
    if not answers or any(a.score is None or a.pass_mark is None for a in answers):
        return None
    marks, ops = {a.pass_mark for a in answers}, {a.pass_op for a in answers}
    if len(marks) != 1 or len(ops) != 1:
        return None
    mark, op = marks.pop(), ops.pop()
    if op is None:
        fits = [o for o in (">=", "<=")
                if all(passes(a.score, o, mark) == a.verdict for a in answers)]
        if len(fits) > 1:
            return None
        op = fits[0] if fits else None
    elif op not in PASS_OPS:
        return None
    source = ("pass_if" if pass_if is not None else
              "deepeval" if tool == "deepeval" else tool)
    out = {"mark": mark, "op": op, "source": source,
           "follows": op is not None and all(passes(a.score, op, mark) == a.verdict
                                             for a in answers)}
    if pass_if is not None:
        out["rule"] = pass_if.text
    if key and source == "mapped":
        out["key"] = key
    return out


def _or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


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
        talk.say("Or save your judge's verdicts from now on with one judgekeeper.record() line "
                 f"where it runs: {own_format.RECORD_URL} has a prompt that asks your coding "
                 "agent to add it.")
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
    if find.is_mlflow_folder(path) and tool in (None, "mlflow"):  # a store, like a file
        path = path.resolve()
        return path.parent, "mlflow", [find.Result("mlflow", path, path.name)], {}
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
        _next_time(talk, "--tool", kind)
    return root, kind, by_date[kind], found.signs


def known_tool(path: str | Path, tool: str | None = None) -> str | None:
    """The tool `start` would read at `path` when that needs no question and no reading of
    results: --tool, judgekeeper.toml's [start] table, a results file's kind, or the one tool
    found. None when it cannot tell."""
    path = Path(path)
    if tool is not None:
        return tool
    if path.is_file():
        return find.classify_file(path)
    if find.is_mlflow_folder(path):
        return "mlflow"
    if not path.is_dir():
        return None
    saved = _saved(path)
    if saved is not None:
        return "mapped" if saved.source == "map" else saved.source
    found = find.search(path.resolve())
    tools = [t for t in find.TOOLS if found.readable(t)]
    return tools[0] if len(tools) == 1 else None


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
    name = names[talk.choose(
        "These results hold more than one judge:", options,
        f"Several judges found; choose one with {_or([f'--metric {quote_arg(n)}' for n in names])}")]
    _next_time(talk, "--metric", name)
    return name


def _next_time(talk: Talk, flag: str, chosen: str) -> None:
    """After the person picks at "Which one?": the flag that picks it without asking."""
    talk.say(f"(Next time: {flag} {quote_arg(chosen)})")


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
        return _geval_rule(text)
    return text or None


GEVAL_PARTS = " \n \n"  # how DeepEval joins the parts of a GEval prompt (readers/deepeval.py)


def _geval_rule(text: str) -> str | None:
    """A GEval rule: its criteria, or, for a GEval built with evaluation steps and no
    criteria (saved as "None"), the steps, one numbered line each. Never "None"."""
    parts = {}
    for part in text.split(GEVAL_PARTS):
        for name in ("Criteria:", "Evaluation Steps:", "Rubric:"):
            if part.startswith(name):
                parts[name] = part[len(name):].strip()
    criteria = parts.get("Criteria:")
    if criteria and criteria != "None":
        return text[len("Criteria:"):].strip()
    steps = parts.get("Evaluation Steps:")
    if not steps or steps == "None":
        return None
    try:
        listed = json.loads(steps)
    except ValueError:
        return steps
    if not isinstance(listed, list):
        return steps
    listed = [" ".join(str(s).split()) for s in listed if str(s).strip()]
    return "\n".join(f"{n}. {s}" for n, s in enumerate(listed, 1)) or None


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
    line = re.sub(r"^1\.\s+", "", line)  # the first of numbered steps
    if len(line) <= RUBRIC_WIDTH:
        return line
    cut = line[:RUBRIC_WIDTH - 1]
    if " " in cut[RUBRIC_WIDTH // 2:]:  # at a word, unless that leaves too little
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "…"


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
    if tool == "records":
        return f"{metric}{quoted} (your records do not say which model: pass judge= to record())"
    return f"{metric}{quoted} (the results file does not say which model)"


def find_judge(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
               experiment: str | None = None, pass_if: str | None = None,
               label_map: str | dict | None = None, judge_model: str | None = None,
               talk: Talk | None = None, prefer: str | None = None,
               tracking_uri: str | None = None, store: str | None = None) -> Found:
    """Find the results, choose what to use, make the pool and name the judge.

    `talk` says each step and asks the questions; the default says nothing and, with no one
    to ask, stops (Stop) where a question would be needed. `prefer` (the judge of the last
    check) is chosen without asking when the newest results hold it among several; `store`
    (the MLflow store of the last check) likewise. `tracking_uri` names the MLflow store.
    """
    talk = talk or Talk(quiet=True)
    saved = _saved(Path(path)) if tool is None and tracking_uri is None else None
    if saved is not None and saved.source != "map":
        tool = saved.source
    if saved is not None and saved.judge not in (None, "*"):
        prefer = prefer or saved.judge
    if tracking_uri is not None:
        root, kind, results, signs = _given_store(talk, Path(path), tracking_uri)
    elif saved is not None and saved.source == "map":
        root, kind, results, signs = _mapped_source(talk, Path(path).resolve(), saved)
    else:
        root, kind, results, signs = _locate(talk, Path(path), tool)
    if kind == "mlflow":
        results = _choose_store(talk, root, results, experiment, store)
    newest = results[0]
    description = None
    name = None
    if kind == "mlflow":
        name, runs = _mlflow_runs(talk, newest, experiment, metric)
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
        if kind in ("records", "mapped"):  # every file (or run) the newest judge wrote
            loaded = (_read_records(talk, results) if kind == "records"
                      else _read_mapped(results[0], saved))
            if not loaded:
                raise StartError("none of the records files could be read")
            every = Loaded(_folder_of(newest), RecordList(r for x in loaded for r in x.records))
            metric = _choose_metric(talk, every, metric, prefer)
            loaded = [x for x in loaded
                      if any(r.annotator_kind == LLM and r.name == metric for r in x.records)]
            if not loaded:
                raise StartError(f"no judge named {metric!r} in {_folder_of(newest)}")
            if kind == "records":
                labels = [x.label for x in loaded]
                results = sorted((r for r in results if r.rel in labels),
                                 key=lambda r: labels.index(r.rel))
                newest = results[0]
            first, read_older = loaded[0], iter(loaded[1:])
        else:
            first = _read(newest)
            read_older = (_read(r) for r in results[1:])
    if kind in ("records", "mapped"):
        metrics = sorted({r.name for r in every.records if r.annotator_kind == LLM})
    else:
        metric = _choose_metric(talk, first, metric, prefer)
        metrics = sorted({r.name for r in first.records if r.annotator_kind == LLM})

    norm = Normaliser(pass_if=pass_if,
                      label_map={**first.records.label_map, **parse_label_map(label_map)})
    used = [first]
    pool = build_pool([(x.label, x.records) for x in used], metric, norm)
    identity = _identity(first.records, metric)
    for older in read_older:
        if len(pool.answers) >= MIN_POOL and kind != "records":
            break
        if _identity(older.records, metric) == identity:
            used.append(older)
            pool = build_pool([(x.label, x.records) for x in used], metric, norm)

    records = [r for x in used for r in x.records
               if r.annotator_kind == LLM and r.name == metric]
    known, _ = _consensus([a.fingerprint for a in pool.answers]) if pool.answers else ({}, [])
    fingerprint = make_fingerprint(known).to_dict()
    models = sorted({str(r.evaluator["model"]) for r in records if r.evaluator.get("model")})
    model_source = None
    if judge_model is not None:
        if models:
            raise StartError(f"{Path(first.label).name} already names the judge's model "
                             f"({', '.join(models)}): drop --judge-model")
        model_source = GIVEN_BY_YOU
        fingerprint.update(model=judge_model, model_source=model_source)
        models = [judge_model]
    elif not models and saved is not None and saved.model:
        model_source = f"given in {settings.FILE}"
        fingerprint.update(model=saved.model, model_source=model_source)
        models = [saved.model]
    rule = rule_of(records)
    one_rule = len({k for k in (_rule_key(r, kind) for r in records) if k is not None}) <= 1
    rubric = rubric_line(rule)
    judge = _judge_name(kind, metric, rubric, models, judge_model is not None,
                        Path(newest.rel).name)
    versions = sorted({a.agent["app_version"] for a in pool.answers if "app_version" in a.agent})
    score_judge = (norm.pass_if is not None or kind == "deepeval"  # score and threshold
                   or (kind == "mapped" and (saved.map or {}).get("kind", "score") == "score")
                   or any((r.metadata or {}).get("pass_mark") is not None for r in records))
    key = (saved.map.get("pass_mark_key") if kind == "mapped" else None)
    return Found(root=root, tool=kind, results=results, used=[x.label for x in used],
                 metric=metric, pool=pool, fingerprint=fingerprint, judge=judge, signs=signs,
                 rule=rule, description=description, metrics=metrics,
                 app_version=", ".join(versions) or None,
                 store=newest.rel if kind == "mlflow" else None,
                 check=judge_check.check(pool, kind, score_judge=score_judge),
                 pass_mark=pass_mark_of(pool, kind, norm.pass_if, key), one_rule=one_rule,
                 task_file=_task_file(newest.path) if kind == "inspect" else None,
                 rule_field=_inspect_field(records) if kind == "inspect" and rule else None,
                 models=models, model_source=model_source, experiment=name)


def _rule_key(r, kind: str) -> str | None:
    """What makes two verdicts' rules the same: the rule (None for a verdict with none, such
    as a failed call); for a DeepEval GEval its criteria, since the steps DeepEval writes from
    them differ from answer to answer, or the steps the person wrote when it has none."""
    rule = rule_of([r])
    if rule is None or kind != "deepeval":
        return rule
    return rule.split(GEVAL_PARTS)[0].strip()


def _inspect_field(records) -> str:
    """Which of model_graded_qa's options the rule is (rule_text): its instructions, unless
    only its template was set."""
    prompt = next((r.evaluator.get("prompt") for r in records if r.evaluator.get("prompt")),
                  None)
    try:
        options = json.loads(prompt) if isinstance(prompt, str) else {}
    except ValueError:
        options = {}
    text = options.get("instructions") if isinstance(options, dict) else None
    default = isinstance(text, str) and text.startswith(DEFAULT_PROMPT.split("{")[0])
    return "instructions" if isinstance(text, str) and not default else "template"


def _task_file(path: Path) -> str | None:
    """The task file an Inspect log names, or None."""
    from judgekeeper.readers.inspect_logs import eval_header

    task = eval_header(path).get("task_file")
    return task.strip() if isinstance(task, str) and task.strip() else None


SERVERS = ("http://", "https://", "databricks")


def _given_store(talk: Talk, path: Path, uri: str) -> tuple[Path, str, list, dict]:
    """--tracking-uri: the local MLflow store it names (mlflow.db, `sqlite:///...`, an
    mlruns/ folder or a `file:` address of one). A tracking server is read by
    `judgekeeper import mlflow`, not by start."""
    from judgekeeper.readers.mlflow_store import folder_of

    text = str(uri)
    if text.startswith(SERVERS):
        raise StartError(f"judgekeeper start reads an MLflow store in your project (mlflow.db "
                         f"or an mlruns/ folder); {uri} is a tracking server. To read it: "
                         f"judgekeeper import mlflow --tracking-uri {uri} --experiment NAME")
    if text.startswith("sqlite:///"):
        store = Path(text[len("sqlite:///"):])
    else:
        store = folder_of(text) or Path(text)
    if not store.exists():
        raise StartError(f"no MLflow store at {uri}")
    root = path.resolve() if path.is_dir() else path.resolve().parent
    store = store.resolve()
    rel = store.relative_to(root).as_posix() if store.is_relative_to(root) else str(store)
    talk.say(f"Looking in {root} ...")
    talk.say()
    return root, "mlflow", [find.Result("mlflow", store, rel)], {}


def _choose_store(talk: Talk, root: Path, stores: list, experiment: str | None,
                  prefer: str | None) -> list:
    """The MLflow store to read first, when the folder has several (mlflow.db and an
    mlruns/ folder, say): the last check's (`prefer`), the one MLFLOW_TRACKING_URI names,
    or the one that holds --experiment; else a question at a terminal, and without one the
    first (mlflow.db before a folder store, MLflow's own choice since 3.16; then the newest),
    naming how to read the other."""
    if len(stores) < 2:
        return stores

    def first(store):
        return [store, *[s for s in stores if s is not store]]

    named = find._tracking_store(root, os.environ.get("MLFLOW_TRACKING_URI"))
    for want in (root / prefer if prefer else None, named):
        hit = next((s for s in stores if want is not None and s.path == want.resolve()), None)
        if hit is not None:
            return first(hit)
    from judgekeeper.readers.mlflow_store import (
        experiments_with_traces,
        folder_store_allowed,
        quiet,
        store_uri,
    )

    stores = sorted(stores, key=lambda s: (s.path.is_dir(), -s.date().timestamp()))
    names = []
    for s in stores:
        uri = store_uri(s.path, say=talk.say)
        with quiet(), folder_store_allowed(uri, say=talk.say):
            names.append(experiments_with_traces(uri))
    if experiment is not None:
        having = [s for s, n in zip(stores, names, strict=True) if experiment in n]
        if not having:
            raise _no_experiment(experiment, list(zip(stores, names, strict=True)))
        if len(having) == 1:
            return first(having[0])
        names = [n for s, n in zip(stores, names, strict=True) if s in having]
        stores = having
    shown = [f"{_store_name(s)} ({', '.join(n) or 'no traces'})" for s, n in zip(
        stores, names, strict=True)]
    count = {2: "Two", 3: "Three"}.get(len(stores), str(len(stores)))
    title = f"{count} MLflow stores found: {_and(shown)}."
    if not _interactive():
        talk.say(f"{title} Using {_store_name(stores[0])}.")
        others = [talk.command_at(s.rel) for s in stores[1:]]
        talk.say(f"For the other one: {others[0]}" if len(others) == 1
                 else f"For another one: {_or(others)}")
        return stores
    chosen = stores[talk.choose(title, shown, "")]
    talk.say(f"(Next time: {talk.command_at(chosen.rel)})")
    return first(chosen)


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


def say_check(talk: Talk, found: Found) -> None:
    """Did the judge actually judge? Its lines (judge_check.terminal_lines)."""
    if found.check is not None:
        for line in judge_check.terminal_lines(found.check.block(), tick()):
            talk.say(line)


def when_words(d) -> str:
    """A date and time as the first block shows it: "3 Oct 2026, 10:00"."""
    return f"{d.day} {MONTHS_SHORT[d.month - 1]} {d.year}, {d:%H:%M}"


NOT_IN_FILE = "not in the file"
NO_MODEL = "not named in the results (add --judge-model NAME)"


def _tool_words(found: Found) -> str:
    if found.tool == "table":
        return f"a table ({Path(found.results[0].rel).name})"
    if found.tool == "records":
        return "your own code (judgekeeper.record())"
    if found.tool == "mapped":
        return f"your own format (read as {settings.FILE} says)"
    return find.NAMES[found.tool]


def _results_words(found: Found) -> str:
    newest = found.results[0]
    if found.tool == "mlflow":
        return f"{newest.rel} (experiment {found.experiment})"
    if found.tool == "records":
        return f"{_folder_of(newest)} ({_plural(len(found.used), 'file', 'files')})"
    return f"{newest.rel} (saved {when_words(newest.date())})"


def _checks_words(found: Found) -> str:
    line = rubric_line(found.rule)
    value = f'"{line}"' if line else NOT_IN_FILE
    if len(found.metrics) > 1:  # several judges in the results: say which one this is
        value = f"{found.metric}: {value}"
    return value


def _model_words(found: Found) -> str:
    if not found.models:
        return NO_MODEL
    model = ", ".join(found.models)
    if found.model_source == GIVEN_BY_YOU:
        return f"{model} (as you told me)"
    if found.model_source:
        return f"{model} ({found.model_source})"
    return model


def _pass_mark_words(pm: dict) -> str:
    mark = f"{pm['mark']:g}"
    words = {">=": f"{mark} or more", ">": f"more than {mark}", "<=": f"{mark} or less",
             "<": f"less than {mark}"}
    return f"score {words[pm['op']]}" if pm.get("op") in words else f"score {mark}"


def found_lines(found: Found) -> list[str]:
    """The first block `start` prints: what judgekeeper found, as a small table. The only
    place inside judgekeeper that says "LLM-as-a-judge"; everywhere else it is "your judge"."""
    pool = found.pool
    rows = [("Eval tool", _tool_words(found)), ("Results file", _results_words(found)),
            ("What it checks", _checks_words(found)), ("Judge model", _model_words(found)),
            ("Its decisions", (f"{_plural(len(pool.answers), 'answer', 'answers')}: "
                               f"{pool.n_pass} passed, {pool.n_fail} failed"))]
    if found.pass_mark:
        rows.append(("Pass mark", _pass_mark_words(found.pass_mark)))
    lines = ["judgekeeper found your LLM-as-a-judge:", ""]
    lines += [f"  {name:<{COLUMN}}{value}" for name, value in rows]
    if found.tool not in ("records", "mapped") and len(found.used) > 1:
        lines.append(f"  Fewer than {MIN_POOL} answers in the newest results, so older results "
                     f"from the same judge were added: {', '.join(found.used[1:])}")
    return lines


def say_found(talk: Talk, found: Found) -> None:
    """The first block, then the judge check and the notes on the pool."""
    pool = found.pool
    for line in found_lines(found):
        talk.say(line)
    if not pool.unmapped:  # else start stops below, and says why
        say_check(talk, found)
    if found.tool == "table":
        _first_rows(talk, found)
    if pool.n_merged:
        talk.say("  " + (f"{pool.n_merged} repeats of the same answer were merged."
                         if pool.n_merged != 1 else
                         "1 repeat of the same answer was merged."))
    if pool.unmapped:  # stop: a result without those answers would be wrong
        raise StartError(str(unmapped_error(pool.unmapped)))
    if pool.n_human:
        where = (f"{Path(found.used[0]).name} also holds" if len(found.used) == 1
                 else "These results also hold")
        talk.say(f"  {where} {_plural(pool.n_human, 'human label', 'human labels')}. "
                 "judgekeeper start does not use them: you mark the answers yourself.")


def _head_value(found: Found, pattern: re.Pattern) -> str | None:
    try:
        m = pattern.search(find._head(found.results[0].path))
    except OSError:
        m = None
    return quote_arg(m[1].decode("utf-8", errors="replace")) if m else None


COSTS = "  Running your eval again makes model calls, so it costs money."


def _inspect_eval(found: Found) -> tuple[str, str] | None:
    """(task file, the `inspect eval` command with the models and log folder of the newest
    log), or None when the log does not name its task file."""
    from judgekeeper.readers.inspect_logs import eval_header

    newest = found.results[0].path
    header = eval_header(newest)
    task = header.get("task_file")
    if not isinstance(task, str) or not task.strip():
        return None
    words = ["inspect eval", quote_arg(task)]
    if isinstance(header.get("model"), str):
        words += ["--model", quote_arg(header["model"])]
    roles = header.get("model_roles")
    for role, spec in (roles.items() if isinstance(roles, dict) else ()):
        model = spec.get("model") if isinstance(spec, dict) else spec
        if isinstance(model, str):
            words += ["--model-role", quote_arg(f"{role}={model}")]
    here, folder = Path.cwd().resolve(), newest.parent.resolve()
    if folder != here / "logs":  # Inspect's own default
        shown = folder.relative_to(here).as_posix() if folder.is_relative_to(here) else folder
        words += ["--log-dir", quote_arg(shown)]
    return task, " ".join(words)


def more_answers(found: Found) -> list[str]:
    """How to make more answers with the user's own tool, naming the files judgekeeper read
    (never a placeholder). judgekeeper runs none of it."""
    newest = found.results[0]
    if found.tool == "promptfoo":
        configs = [s for s in found.signs.get("promptfoo", [])
                   if Path(s).name in find.PROMPTFOO_CONFIGS]
        config = configs[0] if configs else "your promptfoo config"
        return [(f"  Add more tests to {config}, then run: promptfoo eval -o "
                 f"{quote_arg(newest.rel)}"), COSTS]
    if found.tool == "deepeval":
        test_file = _head_value(found, _TEST_FILE)
        add = (f"  Add more test cases to {test_file}, then run: deepeval test run {test_file}"
               if test_file else "  Add more test cases, then run them with deepeval test run.")
        kept = os.environ.get("DEEPEVAL_RESULTS_FOLDER") or any(
            find.DEEPEVAL_RUN.fullmatch(r.path.name) for r in found.results)
        tip = ("  Tip: set DEEPEVAL_RESULTS_FOLDER so DeepEval keeps every run, not only the "
               "latest.")
        return [add, COSTS] + ([] if kept else [tip])
    if found.tool == "inspect":
        inspect_eval = _inspect_eval(found)
        if inspect_eval is None:
            return ["  Add more samples to your Inspect task's dataset, then run it again.",
                    COSTS]
        task, command = inspect_eval
        return [f"  Add more samples to the dataset in {task}, then run: {command}", COSTS]
    if found.tool == "mlflow":
        return ["  Run your MLflow evaluation again on more data.", COSTS]
    if found.tool == "records":
        return [("  Run your eval on more answers: each judgekeeper.record() call saves one "
                 "more verdict."), COSTS]
    if found.tool == "mapped":
        return [f"  Run your eval on more answers: it adds them to {newest.rel}.", COSTS]
    return [f"  Add more rows to {newest.rel}."]


def picking_line(n_pass: int, n_fail: int) -> str:
    """How the page picks answers, from the real counts (start_label.build_queue: blocks of
    10, half from each group, the other group filling in once one runs out)."""
    from judgekeeper.start_label import BLOCK

    few, did, other = ((n_fail, "failed", "passed") if n_fail <= n_pass
                       else (n_pass, "passed", "failed"))
    if few >= ROUGH:
        return ("judgekeeper picks half from the judge's passes and half from its fails, so "
                "you see enough of both.")
    if not few:
        return f"You'll see only answers it {other}."
    within = min(-(-few // (BLOCK // 2)) * BLOCK, n_pass + n_fail)
    then = f", then answers it {other}" if n_pass + n_fail > within else ""
    return (f"You'll see {'the one' if few == 1 else f'all {few}'} it {did} among the first "
            f"{within}{then}.")


NEXT = ("Next: in your browser, mark each answer Pass or Fail.",
        "This shows how often your judge agrees with you.")


def _label_anyway(talk: Talk, found: Found) -> bool:
    """Too few answers for a rough check: say so, and how to make more; then ask."""
    n = len(found.pool.answers)
    talk.say()
    talk.say(f"You have {_plural(n, 'answer', 'answers')}. judgekeeper needs at least "
             f"{MIN_POOL} to show a result.")
    if talk.yes and not _interactive():
        talk.say("Going on anyway, as you asked (--yes).")
        return True
    talk.say()
    talk.say(f"Make more answers with your own eval, then run {talk.command()} again:")
    for line in more_answers(found):
        talk.say(line)
    talk.say()
    question = f"Mark the {n} you have anyway?"
    return talk.confirm(f"{question} The result will have wide ranges.",
                        default=False, with_yes=True,
                        hint=f"{question} Run {talk.command('--yes')} to say yes.")


def _few_note(talk: Talk, pool: Pool) -> None:
    """A judge that fails (or passes) few answers is the one most worth checking: go on, and
    say when its few fails (or passes) come up. One that fails (or passes) none was said with
    the judge check."""
    n = len(pool.answers)
    for count, did, too in ((pool.n_fail, "failed", "passes too much"),
                            (pool.n_pass, "passed", "fails too much")):
        if 0 < count < ROUGH:
            talk.say(f"Your judge {did} only {count} of {n} answers. That may mean it {too}: "
                     "your marks will show it.")
    if min(pool.n_pass, pool.n_fail) < ROUGH:
        for line in textwrap.wrap(picking_line(pool.n_pass, pool.n_fail), width=74):
            talk.say(line)


def label_found(talk: Talk, found: Found, port: int, open_browser: bool) -> int:
    """Say the pool and how labeling goes, then open the labeling page."""
    from judgekeeper import start_label

    say_found(talk, found)
    if found.check is not None and judge_check.has_rows(found.check.block()):
        start_label.save_judge_check(start_label.Workspace(found.root), found)  # it is named
    pool = found.pool
    if not pool.answers:
        raise StartError("no answer has a clear pass or fail from the judge, so there is "
                         "nothing to mark")
    if len(pool.answers) < MIN_POOL:
        if not _label_anyway(talk, found):
            return EXIT_OK
    else:
        _few_note(talk, pool)
    talk.say()
    for line in NEXT:
        talk.say(line)
    if open_browser:
        asked = "Open it now?"
        hint = f"Open it now? Run {talk.command('--yes')} to open it."
    else:
        asked = "Start it now? It prints a link."
        hint = f"Start it now? Run {talk.command('--yes')} to start it (it prints a link)."
    if not talk.confirm(asked, default=True, with_yes=True, hint=hint):
        talk.say(f"OK. Run {talk.command()} when you're ready.")
        return EXIT_OK
    return start_label.run_labeling(found, port=port, open_browser=open_browser, say=talk.say,
                                    command=talk.command())


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, tracking_uri: str | None = None,
        pass_if: str | None = None,
        label_map: str | None = None, judge_model: str | None = None,
        yes: bool = False, port: int = DEFAULT_PORT, no_browser: bool = False,
        new: bool = False, review: bool = False, label_more: bool = False,
        ask_again: bool = False, try_new_judge: bool = False, fix: bool = False,
        test_pass_mark: bool = False, times: int | None = None,
        python: str | None = None, rule_file: str | None = None,
        fields: str | None = None, judge_command: str | None = None,
        allow_calls: int | None = None) -> int:
    """`judgekeeper start`: say what was found, then open the labeling page and make the
    result. What is already saved in `.judgekeeper/` decides where it starts (start_again).
    `review`, `fix`, `ask_again`, `try_new_judge` and `label_more` answer the menu shown
    after a result (`test_pass_mark`, with `fix`, tests the pass mark in the terminal;
    `rule_file`, with `fix`, saves the new rule in that file); `times` (default 2, or 1 when
    trying a new judge), `python`, `fields`,
    `judge_command` and `allow_calls` shape asking the judge again. Returns the exit code."""
    from judgekeeper import start_again
    from judgekeeper.again import AgainOptions

    talk = Talk(yes=yes, path=path, flags=repeated_flags(
        path, port=port, no_browser=no_browser, tool=tool, metric=metric,
        experiment=experiment, tracking_uri=tracking_uri, pass_if=pass_if,
        label_map=label_map, judge_model=judge_model, times=times, python=python,
        fields=fields, judge_command=judge_command))
    again_options = AgainOptions(times=times, python=python, fields=fields,
                                 judge_command=judge_command, judge_model=judge_model,
                                 allow_calls=allow_calls)
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model}
    try:
        then = ("review" if review else "fix" if fix else "ask" if ask_again
                else "try" if try_new_judge else "label" if label_more else None)
        return start_again.run(Path(path), talk, options, port=port,
                               open_browser=not no_browser, new=new, then=then,
                               again_options=again_options, test_pass_mark=test_pass_mark,
                               rule_file=rule_file)
    except Stop as stop:
        return stop.code


__all__ = ["NEXT", "Answer", "Found", "Pool", "StartError", "Talk", "build_pool", "find_judge",
           "found_lines", "label_found", "more_answers", "picking_line", "run", "say_check",
           "say_found", "when_words"]
