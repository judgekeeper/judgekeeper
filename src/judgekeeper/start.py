"""Find the LLM-as-a-judge's saved results for `judgekeeper` and `mark`, and make the pool.

No AI call and no API key: everything comes from files the user's eval tool already saved
(see judgekeeper.find). judgekeeper never runs the user's app, eval or code; when there are
too few answers it prints the command that makes more, and the user runs it.

The pool is every answer with a clear pass or fail. A repeat of the same answer (input,
output and any agent steps) counts once: the newest results file wins, and inside it the
majority of its verdicts, a tie going to fail. An answer with no real decision (judge_check)
is left out, counted and said.

Questions are asked only at a terminal. Without one, judgekeeper prints the question as the
flag that answers it and exits 3; `--yes` takes the default of a yes/no question, but never
picks between tools or judges.
"""

from __future__ import annotations

import json
import math
import operator
import os
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from judgekeeper import find, judge_check, mapper, settings, targets, textio
from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.links import said
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, parse_label_map
from judgekeeper.readers import read_deepeval, read_inspect, read_mlflow, read_promptfoo
from judgekeeper.readers.inspect_logs import DEFAULT_PROMPT
from judgekeeper.readers.promptfoo import is_stripped_warning
from judgekeeper.records import (
    CODE,
    CUT_END,
    HUMAN,
    LLM,
    NO_MARK,
    Damaged,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    _consensus,
    _verdict_value,
    damaged,
    derive_record_id,
    fingerprint_known,
    left_out_note,
    load_json,
    read_records,
)
from judgekeeper.redact import one_line
from judgekeeper.table import (
    KNOWN_COLUMNS,
    _blank,
    make_fingerprint,
    open_quote,
    read_table,
    sheet_id,
)
from judgekeeper.textio import flush_stdout, held_lines, plural, quote_arg, read_utf8, tick

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_QUESTION = 3  # stopped at a question it cannot ask (no terminal); nothing went wrong

ROUGH = targets.ROUGH  # the label targets every command shares
MIN_POOL = 2 * ROUGH  # a rough check needs ROUGH of each
RUBRIC_WIDTH = 70  # characters of the rule's first line shown in the first block
GIVEN_BY_YOU = "given by you"
POINT_ME = "Point me at the results: {program} path/to/results.json"
RECORDS_ABOVE = ("Nothing to read here, but judgekeeper.record() saves your LLM-as-a-judge's "
                 "decisions at the project root: reading them in {root}.")
PAIRWISE = "These are A/B comparisons. judgekeeper handles pass/fail answers for now."
HUMAN_COLUMNS = ("human_label", "label")
FILE_READERS = {"promptfoo": read_promptfoo, "deepeval": read_deepeval, "inspect": read_inspect}
_DESCRIPTION = re.compile(r"^description:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_YAML_BLOCK = re.compile(r"^[>|][+-]?$")  # a folded (>) or literal (|) block scalar


def yaml_description(text: str) -> str | None:
    """The top-level `description:` of a YAML config, with no YAML reader: a plain or quoted
    value, or a folded (`>-`) or literal (`|`) block, its lines joined with spaces."""
    m = _DESCRIPTION.search(text)
    if not m:
        return None
    value = m[1].strip()
    if _YAML_BLOCK.fullmatch(value):
        lines = []
        for line in text[m.end():].splitlines()[1:]:
            if line.strip() and not line.startswith((" ", "\t")):
                break
            lines.append(line.strip())
        value = " ".join(x for x in lines if x)
    elif len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value.strip() or None


def same_words(a: str | None, b: str | None) -> bool:
    """Two descriptions are the same when they differ only in spaces and line breaks."""
    return a is not None and b is not None and " ".join(a.split()) == " ".join(b.split())


class StartError(Exception):
    """`start` cannot go on: a usage error (exit 2). `next_step`: the words of its Next: line
    (cli.main), where {command} is the command as it was run, without the flag `drop`."""

    def __init__(self, message: str = "", next_step: str | None = None,
                 drop: str | None = None):
        super().__init__(message)
        self.next_step, self.drop = next_step, drop


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
# flag). --port and --no-browser follow them. Left out on purpose (NOT_REPEATED): --yes, which
# each hint adds when it needs it, and --new, --wait and --stop, which do one thing once.
REPEATED = (("tool", "--tool"), ("metric", "--metric"), ("experiment", "--experiment"),
            ("tracking_uri", "--tracking-uri"), ("pass_if", "--pass-if"), ("label_map", "--label-map"),
            ("judge_model", "--judge-model"))
NOT_REPEATED = frozenset({"new", "wait", "stop", "yes"})
DEFAULT_PORT = 8765


def repeated_flags(path: str | Path = ".", port: int = DEFAULT_PORT, no_browser: bool = False,
                   kept: bool = False, **values) -> tuple[str, ...]:
    """The words a printed command repeats: the path (unless this folder), each REPEATED flag
    that was given, then --port (unless the default) and --no-browser. `kept`: for a command
    kept in a file or on the page (quote_arg)."""
    words = [] if str(path) == "." else [quote_arg(path, kept)]
    for name, flag in REPEATED:
        if values.get(name) is not None:
            words += [flag, quote_arg(str(values[name]), kept)]
    if port != DEFAULT_PORT:
        words += ["--port", str(port)]
    if no_browser:
        words.append("--no-browser")
    return tuple(words)


def run_flags(path: str | Path = ".", port: int = DEFAULT_PORT, no_browser: bool = False,
              **values) -> dict:
    """The path and the flags a printed command repeats (repeated_flags), as data: what
    result.json and the page keep, so each command they show is rebuilt (command_from)."""
    flags = {"path": str(path), "port": port, "no_browser": no_browser}
    flags.update({name: str(values[name]) for name, _ in REPEATED
                  if values.get(name) is not None})
    return flags


def saved_flags(flags) -> dict:
    """`flags` (run_flags) as read back from a file: only what run_flags writes, each of its
    kind and on one line; anything else is left out."""
    if not isinstance(flags, dict):
        return {}

    def ok(value) -> bool:
        return isinstance(value, str) and value.isprintable()

    port = flags.get("port")
    out = {"path": flags["path"]} if ok(flags.get("path")) else {}
    if isinstance(port, int) and not isinstance(port, bool) and 0 <= port <= 65535:
        out["port"] = port
    if flags.get("no_browser") is True:
        out["no_browser"] = True
    out.update({name: flags[name] for name, _ in REPEATED if ok(flags.get(name))})
    return out


def command_from(flags, subcommand: str = "", kept: bool = False) -> str:
    """textio.program(subcommand) and the flags `flags` keep (run_flags, checked by
    saved_flags), written again by repeated_flags: never a command's text read from a file."""
    return " ".join((textio.program(subcommand),
                     *repeated_flags(kept=kept, **saved_flags(flags))))


def held_values(flags) -> list[str]:
    """The values a kept command made from `flags` shows as NAME (quote_arg), in order: on
    Windows, each is said beside it as data."""
    flags = saved_flags(flags)
    values = [flags.get("path", "."), *(flags[name] for name, _ in REPEATED if name in flags)]
    return list(dict.fromkeys(v for v in values if v != "." and textio.held_back(v)))


class Talk:
    """What finding the judge says, and the questions it asks when there is a person to
    answer. `flags` (repeated_flags) are what every printed command repeats."""

    subcommand = ""  # every printed command starts with textio.program(subcommand)
    asks_everything = False  # without a terminal, ask instead of taking a default (front.py)

    def __init__(self, yes: bool = False, quiet: bool = False, flags: tuple[str, ...] = (),
                 path: str | Path = "."):
        self.yes = yes
        self.quiet = quiet
        self.flags = flags
        self.path = str(path)  # the path the person gave; flags[0] when it is not "."
        self._blank = True  # the last line said was empty: never two in a row

    @property
    def program(self) -> str:
        """`judgekeeper`, or `uvx judgekeeper@<version>` when uvx started it."""
        return textio.program(self.subcommand)

    def command(self, *extra: str) -> str:
        """`judgekeeper` with the person's flags, then `extra`: run as printed, it gets
        past the question it answers."""
        return " ".join((self.program, *self.flags, *extra))

    def command_at(self, where: str | Path, *extra: str) -> str:
        """`command`, with `where` (a path inside the folder the person gave) as the path,
        written with forward slashes on every system, as the lines that name it write it."""
        given = self.flags[:1] == (quote_arg(self.path),) and self.path != "."
        flags = self.flags[1:] if given else self.flags
        path = Path(where) if self.path == "." else Path(self.path) / where
        return " ".join((self.program, quote_arg(path.as_posix()), *flags, *extra))

    def say(self, text: str = "") -> None:
        if self.quiet or (not text and self._blank):
            return
        print(said(text))
        for line in held_lines(text):  # a name left out of the command above, as data
            print(said(line))
        flush_stdout()  # piped or in the background, lines must not wait in a buffer
        self._blank = not text

    def choose(self, title: str, options: list[str], flag_hint: str,
               ask: str = "Which one?", flag: str | None = None, values=(),
               what: str | None = None) -> int:
        """The index of the option the person picks. Without a terminal: the hint, exit 8.
        `flag` (with `values`, one per option) answers it, and `what` says what is chosen;
        `judgekeeper` (front.py) words its Next: line from them."""
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

    def looking(self, root: Path) -> None:
        """Say which folder is searched."""
        self.say(f"Looking in {root} ...")
        self.say()

    def remember(self, flag: str, chosen: str, line: str | None = None) -> None:
        """After the person picks at "Which one?": the flag that picks it without asking."""
        self.say(line or f"(Next time: {flag} {quote_arg(chosen)})")

    def stop(self, code: int, next_step: str | None = None) -> Stop:
        """The Stop to raise once the lines that say why were said. `next_step` is what
        `judgekeeper` (front.py) puts in its Next: line; `start` says its own."""
        return Stop(code)

    def _input(self, prompt: str) -> str:
        try:
            return input(one_line(prompt)).strip()
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
    n_unmapped: dict = field(default_factory=dict)  # how many verdicts had each unmapped value
    n_merged: int = 0
    n_results: int = 0  # grades read for the chosen judge, repeats counted each
    repeat_sizes: set = field(default_factory=set)  # how many times each answer was graded
    n_human: int = 0
    # answers graded more than once with different grades, each repeat its own answer:
    # id -> (repeats, passes, fails)
    split: dict = field(default_factory=dict)
    left: dict = field(default_factory=dict)  # answer id: (judge_check kind, its record)
    unread: set = field(default_factory=set)  # answers whose grades no label map reads yet

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
        return mark, r.metadata.get("pass_op") or ">="
    return _number(threshold), None


def build_pool(files: list[tuple[str, RecordList]], metric: str, norm: Normaliser,
               own_ids: bool = False) -> Pool:
    """The pool from the judge `metric`'s verdicts in `files`, newest file first. An answer
    whose verdicts are all no real decision (the reader's mark, or nothing the normaliser can
    read) goes to `left` with its kind instead. An answer's id is made from its text, or with
    `own_ids` (a table, an own format) the file's own id when the reader kept it. Repeats of
    an answer with the same grade count once; with different grades, each repeat is its own
    answer (`split`): they are never merged into one grade silently."""
    pool = Pool()
    chosen: dict[str, Answer] = {}
    for source, records in files:

        def key_of(r, records=records) -> str:
            if own_ids and not records.ids_derived and r.target_id:
                return str(r.target_id)
            return derive_record_id(r.input, r.output, r.trajectory)

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
                    pool.unread.add(key_of(r))
                    if e.value not in pool.unmapped:
                        pool.unmapped.append(e.value)
                    key = repr(e.value)
                    pool.n_unmapped[key] = pool.n_unmapped.get(key, 0) + 1
                    continue
                if v.verdict == ERROR:
                    kind = judge_check.EMPTY
            groups.setdefault(key_of(r), []).append((r, v, kind))
        for key, seen in groups.items():
            judged = [(r, v) for r, v, kind in seen if kind is None]
            if key in chosen or key in pool.left:  # a newer file has this answer
                pool.n_merged += len(judged)
                continue
            if not judged:
                pool.left[key] = (seen[0][2], seen[0][0])
                continue
            passes = sum(v.verdict == "pass" for _, v in judged)
            pool.n_results += len(judged)
            pool.repeat_sizes.add(len(judged))
            if passes in (0, len(judged)):  # the same grade every time: one answer
                pool.n_merged += len(judged) - 1
                judged = judged[-1:]
            else:
                pool.split[key] = (len(judged), passes, len(judged) - passes)
            for n, (r, v) in enumerate(judged, 1):
                score = v.raw_score if v.raw_score is not None else _number(r.score)
                pass_mark, pass_op = _mark_of(r, v, norm, threshold)
                answer_id = key if n == 1 else f"{key}#{n}"
                chosen[answer_id] = Answer(
                    id=answer_id, input=r.input, output=r.output, verdict=v.verdict,
                    reason=v.rationale or r.explanation or "", score=score,
                    fingerprint=make_fingerprint(_known(r.evaluator), r.created_at),
                    source=source, agent=r.agent(), mark=r.mark, pass_mark=pass_mark,
                    pass_op=pass_op)
    pool.answers = list(chosen.values())
    return pool


# Reading ---------------------------------------------------------------------------------

MADE_IDS = "The id column has blank or repeated ids, so judgekeeper made its own."


def read_results_table(path: Path) -> RecordList:
    """A plain table (input, output and a verdict column) as judge records; a human label
    column, when there is one, as human records (counted, not used). A `model` (or
    `judge_model`) column names the judge's model, an `app_version` column the app's, and a
    `score` column the score --pass-if reads in place of the verdict. A quote that never
    closes stops it: the rows after it would be read as one cell."""
    line = open_quote(path)
    if line is not None:
        raise StartError(f"line {line} of {path.name} has a quote that never closes, so the "
                         "rows after it can't be read.",
                         f"close the quote on line {line} of {path.name}, then run "
                         "`{command}`.")
    rows = read_table(path)
    if not rows:  # a header and nothing under it
        raise StartError(f"{path.name} has no rows")
    ids = [None if _blank(row.get("id")) else sheet_id(row["id"]) for row in rows]
    own = "id" in rows[0] and None not in ids and len(set(ids)) == len(ids)
    columns = list(dict.fromkeys(k for row in rows for k in row))
    if "output_a" in columns and "output_b" in columns:
        raise StartError(PAIRWISE)
    verdicts = [c for c in find.VERDICT_COLUMNS if c in columns]  # each one is a judge
    if verdicts:  # and a 0/1 column named for a judge (llm_judge), the judge-named first
        verdicts = mapper._judge_first(verdicts + [
            c for c in columns if c not in verdicts and c not in KNOWN_COLUMNS
            and mapper._judge_column((c,), [row.get(c) for row in rows])])
    verdict = verdicts[0] if verdicts else None
    if verdict is None or "input" not in columns or "output" not in columns:
        raise StartError(f"{path.name} needs input, output and verdict columns; columns are: "
                         f"{', '.join(columns)}")
    header = path.suffix.lower() in (".csv", ".tsv")  # a CSV's first line names the columns
    for n, row in enumerate(rows, 1):  # a JSON object or list: no grade (CSV values are text)
        if any(isinstance(row.get(v), dict | list) for v in verdicts):
            raise StartError(f"line {n + header} of {path.name} has a verdict judgekeeper "
                             "can't read: an object or a list, not a grade.",
                             f"write a grade (pass or fail) in the verdict of line {n + header} "
                             f"of {path.name}, then run `{{command}}`.")
    human = next((c for c in HUMAN_COLUMNS if c in columns), None)
    records = RecordList(ids_derived=not own)
    if "id" in columns and not own:
        records.per_metric = {v: {"warnings": [MADE_IDS]} for v in verdicts}
    for n, row in enumerate(rows, 1):
        textio.reading(n)
        content = {"target_id": ids[n - 1] if own else derive_record_id(row.get("input"),
                                                                        row.get("output")),
                   "input": row.get("input"), "output": row.get("output")}
        model = row.get("model") if not _blank(row.get("model")) else row.get("judge_model")
        if not mapper._model_like(model):  # "string_match": a rule's name, not a model's
            model = None
        score = _number(mapper.number(row.get("score"))) if "score" in columns else None
        for verdict in verdicts:
            records.append(ScoreRecord(
                name=verdict, annotator_kind=LLM, score=score,
                label=None if _blank(row.get(verdict)) else row[verdict],
                explanation=None if _blank(row.get("reason")) else str(row["reason"]),
                evaluator={} if _blank(model) else {"model": str(model)},
                app_version=None if _blank(row.get("app_version")) else str(row["app_version"]),
                **content))
        if human and not _blank(row.get(human)):
            records.append(ScoreRecord(name=verdicts[0], annotator_kind=HUMAN,
                                       label=row[human], **content))
    return records


@dataclass
class Loaded:
    """One results file (or one MLflow run), read."""

    label: str
    records: RecordList


# What a reader can meet in a damaged file that is not its own RecordsError
UNREADABLE = (RecursionError, OverflowError, UnicodeDecodeError, sqlite3.DatabaseError)


def unreadable(path: Path, tool: str) -> RecordsError:
    """A reader stopped on a damaged file: said in plain words, never the error's text."""
    return damaged(path, find.NAMES.get(tool, tool), "is damaged: judgekeeper can't read it")


def usage_error(e: Exception, text: str | None = None) -> StartError:
    """A reader's error as a usage error, with its Next: line when it has one."""
    return StartError(str(e) if text is None else text, getattr(e, "next_step", None))


def _read(result: find.Result) -> Loaded:
    try:
        if result.tool == "table":
            records = read_results_table(result.path)
        elif result.tool == "inspect":  # a sample that errored before it was scored, too
            records = read_inspect(result.path, with_errors=True)
        else:
            records = FILE_READERS[result.tool](result.path)
    except UNREADABLE:
        raise unreadable(result.path, result.tool) from None
    stripped = [w for w in records.warnings if is_stripped_warning(w)]
    if stripped:
        raise StartError(stripped[0])
    return Loaded(result.rel, records)


def _readable(talk: Talk, results: list[find.Result], root: Path):
    """Each of `results` read (_read), newest first; one that can't be read is said and
    left out."""
    for r in results:
        try:
            yield _read(r)
        except RecordsError as e:
            _note(talk, f"{_unread(e, r, root)} It is left out.")


def _unread(error: RecordsError, result: find.Result, root: Path) -> str:
    """Why `result` can't be read, in one line, by its path in the project, wherever it is
    met: a DeepEval file that only links to Confident AI; a promptfoo test with two judges of
    one name, with the config file it is in."""
    from judgekeeper.readers.deepeval import LINK_ONLY, LinkOnly
    from judgekeeper.readers.promptfoo import TwoJudges, two_judges

    if isinstance(error, LinkOnly):
        return LINK_ONLY.format(file=result.rel)
    if isinstance(error, TwoJudges):
        config = _config_named(root, result)
        default = error.default or _default_test_has(root / config, error.name)
        return two_judges(result.rel, error.test, error.name, f" in {config}", default)
    return str(error).replace(str(result.path), result.rel)  # never the full path


def _read_records(talk: Talk, results: list[find.Result]) -> list[Loaded]:
    """The records files judgekeeper.record() wrote, newest first. A file that cannot be
    read is left out, with how to see why; a last line cut short is left out too."""
    loaded = []
    for r in results:
        try:
            try:
                records = read_records(r.path, cut_end_ok=True, bad_lines_ok=True)
            except UNREADABLE:
                raise unreadable(r.path, "records") from None
        except RecordsError as e:
            text = str(e).removeprefix(f"{r.path.name} is damaged: ")
            text = text[text.find("line "):] if "line " in text else text
            talk.say(f"  {r.rel} could not be read ({text.rstrip('.')}), so it was left out.")
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
    """The results file judgekeeper.toml maps: no search. Only a file inside the project, as
    for every other results file (find._inside): a judgekeeper.toml comes with the project."""
    path = root / saved.file
    inside = find._inside(root.resolve(), saved.file)
    if Path(saved.file).is_absolute() or ".." in Path(saved.file).parts or inside is None:
        raise StartError(f"{settings.FILE} names a file outside this project "
                         f"({one_line(saved.file)}); judgekeeper reads results only "
                         "inside the project.")
    if not path.is_file():
        raise StartError(f"{settings.FILE} says your LLM-as-a-judge's results are in {saved.file}, "
                         f"which is not there. Run {textio.program()} again to set it up.")
    talk.looking(root)
    return root, "mapped", [find.Result("mapped", path, saved.file, path.stat().st_size)], {}


def _read_mapped(result: find.Result, saved) -> list[Loaded]:
    from judgekeeper.readers.mapped import read_mapped

    m = {**saved.map, "judge": saved.judge, "pass_mark": saved.pass_mark,
         "pass_op": saved.pass_op, "model": saved.model}
    try:
        read = read_mapped(result.path, m, label=result.rel)
    except UNREADABLE:
        raise unreadable(result.path, "your own tool") from None
    return [Loaded(label, records) for label, records in read]


def _where(result: find.Result) -> str:
    """The file, and when it was saved: for DeepEval only the run's own time (a file's time
    can be when the project was copied), else no date."""
    date = result.run_date() if result.tool in ("deepeval", "mlflow") else result.date()
    return result.rel if date is None else f"{result.rel}, saved {date:%Y-%m-%d %H:%M}"


def _folder_of(result: find.Result) -> str:
    parent = Path(result.rel).parent.as_posix()
    return result.rel if parent == "." else f"{parent}/"


EVAL_SKIPPED = ("Your newest Inspect AI log, {eval}, is a .eval log, which judgekeeper reads only "
                "with its Inspect extra, so it read {json}, an older one. To read the newest, "
                "{get}.")


def _get_extra(talk: Talk, extra: str) -> str:
    """How to get `extra` and read again with the same flags, as the end of a sentence: the
    uvx command that has it, else the install line and the command."""
    if textio.started_by_uvx():
        return "run `" + " ".join((textio.uvx_with(extra), *filter(None, [talk.subcommand]),
                                   *talk.flags)) + "`"
    return f"install the extra ({textio.install_extra(extra)}), then run `{talk.command()}` again"


def _needs_extra(talk: Talk, tool: str, where: str) -> Stop:
    """Reading `tool` needs an extra: started by uvx, the uvx command that has it (pip would
    not reach uvx's environment); else pip install, then the same command again."""
    extra = find.EXTRAS[tool]
    _note(talk, f"{find.NAMES[tool]} found ({where}). Reading {find.NAMES[tool]} results needs "
                f"judgekeeper's {extra} extra.")  # the command is in the Next: line, once
    if textio.started_by_uvx():
        command = " ".join((textio.uvx_with(extra), *filter(None, [talk.subcommand]),
                            *talk.flags))
        return talk.stop(EXIT_USAGE, f"run `{command}`.")
    install = textio.install_extra(extra)
    return talk.stop(EXIT_USAGE, f"add judgekeeper's {extra} extra ({install} in your "
                                 f"project's environment), then run `{talk.command()}` "
                                 "again.")


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
    from judgekeeper.readers import mlflow_store

    with mlflow_store.quiet():
        if not _has("mlflow"):
            raise _needs_extra(talk, "mlflow", _store_name(store))
        uri = mlflow_store.store_uri(store.path, say=talk.say)
        trash = store.path / ".trash" if store.path.is_dir() else None  # MLflow makes it
        made = trash is not None and not trash.exists()
        try:
            with mlflow_store.folder_store_allowed(uri, say=talk.say), \
                    mlflow_store.store_damage(uri):
                return _mlflow_experiment(talk, store, experiment, metric, uri)
        finally:
            if made:  # left as it was: nothing is written outside .judgekeeper/
                try:
                    trash.rmdir()
                except OSError:
                    pass


OLD_EVALUATE = ("Your MLflow runs hold LLM-as-a-judge scores from mlflow.evaluate() ({names}). "
                "judgekeeper reads LLM-as-a-judge results from mlflow.genai.evaluate() and scorers "
                "(MLflow 3). Reading these older results isn't supported. To check this "
                "LLM-as-a-judge, run it with mlflow.genai.evaluate() and scorers, or save its "
                "verdicts as a CSV with input, output and verdict columns.")
OLD_EVALUATE_NEXT = ("run your LLM-as-a-judge with mlflow.genai.evaluate() and scorers, then run "
                     "`{command}` again; or save its verdicts as a CSV and run `{csv_command}`, "
                     "with PATH the path of your CSV.")
# The run metrics mlflow.evaluate() logs for a judged metric: faithfulness/v1/mean, ...
_OLD_METRIC = re.compile(r"(.+/v\d+)/(mean|variance|p90)")


def _old_evaluate(uri: str) -> list[str]:
    """The judged metrics mlflow.evaluate() (MLflow 2) logged in the store's runs, by name
    (faithfulness/v1); [] when there are none."""
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=uri)
    names = set()
    for exp in client.search_experiments():
        for run in client.search_runs([exp.experiment_id], max_results=100):
            names.update(m[1] for m in map(_OLD_METRIC.fullmatch, run.data.metrics) if m)
    return sorted(names)


def _no_experiment(experiment: str,stores: list[tuple[find.Result, list[str]]]) -> StartError:
    """--experiment names none of the experiments: say each store searched and its own."""
    where = [f"{_store_name(s)} (its experiments: {', '.join(names) or 'none'})"
             for s, names in stores]
    return StartError(f"no MLflow experiment named {experiment!r} in {_or(where)}")


def _mlflow_experiment(talk: Talk, store: find.Result, experiment: str | None,
                       metric: str | None, uri: str) -> tuple[str, list[Loaded]]:
    from judgekeeper.readers.mlflow_store import (
        ArtifactServer,
        JudgeCallsFailed,
        TracesMissing,
        experiments_with_traces,
    )

    if experiment is not None:
        try:
            found = [(experiment, read_mlflow(experiment, tracking_uri=uri, metric=metric))]
        except (TracesMissing, JudgeCallsFailed, ArtifactServer) as e:
            raise usage_error(e) from None
        except RecordsError as e:
            if not str(e).startswith("no MLflow experiment named"):
                raise
            raise _no_experiment(experiment, [(store, experiments_with_traces(uri))]) from None
    else:
        from mlflow import MlflowClient

        found, missing, code_only = [], [], False
        for exp in MlflowClient(tracking_uri=uri).search_experiments():
            try:
                runs = read_mlflow(exp.name, tracking_uri=uri, metric=metric)
            except (TracesMissing, JudgeCallsFailed, ArtifactServer) as e:
                missing.append(e)
                continue
            except Damaged:
                raise
            except RecordsError:  # an experiment with no traces
                continue
            if any(r.annotator_kind == LLM for _, recs in runs for r in recs):
                found.append((exp.name, runs))
            elif any(r.annotator_kind == CODE for _, recs in runs for r in recs):
                code_only = True
        if not found and missing:
            raise usage_error(missing[0])
        old = [] if found else _old_evaluate(uri)
        if old:
            _note(talk, OLD_EVALUATE.format(names=", ".join(old)))
            raise talk.stop(EXIT_USAGE, OLD_EVALUATE_NEXT.format(
                command=talk.command(), csv_command=talk.command_at("PATH")))
        if not found:  # the same words as DeepEval's, and a real next step
            raise _no_judge(talk, "mlflow", [_store_name(store)], rules=code_only)
        if len(found) > 1:
            names = [name for name, _ in found]
            found = [found[talk.choose(
                "Several MLflow experiments have LLM-as-a-judge results:", names,
                "Several MLflow experiments have LLM-as-a-judge results; choose one with "
                f"{_or([f'--experiment {quote_arg(n)}' for n in names])}",
                flag="--experiment", values=names, what="which MLflow experiment to read")]]
            _next_time(talk, "--experiment", found[0][0])
    name, runs = found[0]
    for label, recs in runs:
        for note in recs.notes if label == "human assessments" else ():
            if not note.startswith(("Runs are MLflow runs", "MLflow does not save")):
                _note(talk, note)
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
    stopped: list[str] = field(default_factory=list)  # Inspect runs that stopped early; rows left out
    label_map: str | dict | None = None  # --label-map as given, kept in start.json
    # a results file (or MLflow store) given by path: where it is from `root`, kept in
    # start.json, so later runs without a path read it again (rebased)
    given: str | None = None
    warnings: list[str] = field(default_factory=list)  # the reader's, about this judge
    n_rules: int = 1  # how many rules the judge's verdicts have (one per test, say)
    reference: bool = False  # it compares each answer with its test's reference answer


def rebased(found: Found, root: Path) -> Found:
    """`found` read from a results file (or MLflow store) given by path, with `root` as its
    project folder: .judgekeeper/ stays in the project, never next to the file. Each file is
    named from `root`, and `given` says where the file is."""
    root = Path(root).resolve()

    def rel(path: Path) -> str:
        path = path.resolve()
        return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)

    results = [replace(r, rel=rel(r.path)) for r in found.results]
    given = rel(found.results[0].path) if found.tool != "mapped" else None
    return replace(found, root=root, results=results, given=given)


def results_path(root: Path, data: dict) -> Path:
    """Where the results of the marks in `root` are read: the file (or MLflow store) given by
    path when marking started, while it is there; else the project folder."""
    given = data.get("given") if isinstance(data, dict) else None
    if isinstance(given, str) and given:
        path = Path(root) / given
        if path.exists():
            return path
    return Path(root)


PASS_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt,
            "==": operator.eq}


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
                "its logs in logs/), then run {program} again."),
    "mlflow": "but it has no saved LLM-as-a-judge assessments in this folder yet.",
}


def _nothing_found(talk: Talk, root: Path, signs: dict) -> None:
    from judgekeeper import own_format

    talk.say(f"No saved eval results found in {root}. judgekeeper looked "
             f"{find.looked(root).replace(' from ' + root.name, '')}.")
    for tool, where in signs.items():
        talk.say(f"{find.NAMES[tool]} is used here ({where[0]}), "
                 + NO_RESULTS.get(tool, "but it has no saved results in this folder yet.")
                 .format(program=textio.program()))
    own = own_format.search(root)
    how = (f"turn it into a table with input, output and verdict columns (see "
           f"{own_format.OWN_FORMAT_URL}), or ask your coding agent with the prompt below.")
    if own is not None:
        setup = textio.program() + ("" if talk.path == "." else f" {quote_arg(talk.path)}")
        talk.say(f"{own.rel} looks like saved LLM-as-a-judge results in your own format.")
        talk.say(f"To use it as it is, run {setup}: it asks how to read it and saves that in "
                 "judgekeeper.toml.")
        talk.say(f"Or {how}")
    elif "deepeval" in signs:
        talk.say("If your LLM-as-a-judge saves its results in a format of its own: "
                 + how.replace("turn it into", "turn them into"))
    if own is not None or "deepeval" in signs:
        talk.say()
        talk.say("Paste this into your coding agent (Claude Code, Cursor or Codex):")
        talk.say()
        for line in own_format.agent_prompt().splitlines():
            talk.say(line)
        talk.say()
        talk.say("Or save your LLM-as-a-judge's decisions from now on with one "
                 f"judgekeeper.record() line where it runs: {own_format.RECORD_URL} shows the "
                 "line.")
    talk.say("judgekeeper reads the results that promptfoo, DeepEval, Inspect AI and "
             "MLflow save, or a CSV or JSONL file with input, output and verdict columns.")
    talk.say(POINT_ME.format(program=talk.program))


SAVE = "promptfoo eval -o promptfoo-results.json"
EXPORT = "promptfoo export eval <id> -o promptfoo-results.json"
LIST = "promptfoo list evals"


def _promptfoo_save(talk: Talk) -> None:
    """How to save promptfoo's results to a file: judgekeeper runs nothing itself."""
    for line in (
        "  Save your results to a file. Run your eval with -o:",
        "",
        f"    {SAVE}",
        "",
        "  or, for a run you already made, list your evals and export one by its id:",
        "",
        f"    {LIST}",
        f"    {EXPORT}",
        "",
        f"  Then run {talk.program} again.",
    ):
        talk.say(line)


def _export(talk: Talk, root: Path, config: str):
    """promptfoo found by its config, with its results only in promptfoo's own database: how
    to save them to a file, then stop. Nothing is run."""
    _misshapen(root)
    screens = getattr(talk, "screens", False)  # `judgekeeper`'s own words (front.FrontTalk)
    if screens:
        talk.para(f"Found promptfoo in this folder ({config}), but no saved results file yet. "
                  "promptfoo keeps its results in its own database.")
    else:
        talk.say(f"{tick()} Your eval tool: promptfoo ({config})")
        talk.say("  No promptfoo results file in this folder. promptfoo keeps them in its own "
                 "database.")
    if screens:
        talk.say()
        talk.para(f"Save them with `{SAVE}`, or list your evals with `{LIST}` and run "
                  f"`{EXPORT}`.")
        raise talk.stop(EXIT_OK, f"save your promptfoo results to a file as said above, then "
                                 f"run `{talk.command()}` again.")
    _promptfoo_save(talk)
    raise talk.stop(EXIT_OK, f"save your promptfoo results to a file as said above, then run "
                             f"`{talk.command()}` again.")


def _misshapen(root: Path) -> None:
    """A results file promptfoo would write beside its config that isn't one: named, never
    taken for no file at all."""
    from judgekeeper.readers.promptfoo import not_results, not_results_error

    for name in ("results.json", "promptfoo-results.json"):
        path = root / name
        if not path.is_file():
            continue
        why = not_results(load_json(path, "promptfoo"))  # Damaged when it isn't JSON
        if why:
            raise not_results_error(path, why)


def _locate(talk: Talk, path: Path, tool: str | None) -> tuple[Path, str, list, dict]:
    """(project folder, tool, its readable results newest first, tool signs)."""
    if not path.exists():
        raise StartError(f"file or folder not found: {path}")
    if find.is_mlflow_folder(path) and tool in (None, "mlflow"):  # a store, like a file
        path = path.resolve()
        return path.parent, "mlflow", [find.Result("mlflow", path, path.name)], {}
    if path.is_file():
        _read_anyway(talk, path)
        kind = tool or find.classify_file(path)
        if kind is None and path.suffix.lower() in find.TABLE_SUFFIXES:
            read_utf8(path, StartError)  # not UTF-8 (a UTF-16 export): how to save it again
        if kind is None and find.is_promptfoo_table(path):
            raise table_output(path.name)
        if kind is None and find.title_row(path):
            raise title_row(path.name)
        if kind is None and path.suffix.lower() in find.EXCEL:
            raise StartError(EXCEL.format(file=path.name),
                             f"save {path.name} as CSV UTF-8, then run "
                             f"`{textio.program()} {quote_arg(path.with_suffix('.csv').name)}`.")
        if kind is None:
            raise StartError(f"{path.name} is not a results file judgekeeper can read "
                             "(promptfoo, DeepEval, Inspect AI, an MLflow store, or a table "
                             "with input, output and verdict columns)")
        path = path.resolve()
        return path.parent, kind, [find.Result(kind, path, path.name, path.stat().st_size)], {}
    root = path.resolve()
    talk.looking(root)
    found = find.search(root)
    for note in found.notes:
        _note(talk, note)
    for big in found.too_big():
        talk.say(big.too_big_message(talk.command_at(big.rel, "--yes")))
    available = [t for t in find.TOOLS if found.readable(t)]
    if found.unreadable and (available or found.too_big()):
        for rel, how in found.unreadable:
            _note(talk, f"{rel} {how}." if how == find.EXCEL_FOUND
                  else f"{rel} {how}, so it was left out.")
    if "records" not in available and (tool == "records" or tool is None and not available):
        above = find.records_above(root)
        if above is not None:  # record() saves at the project root, from any subfolder
            talk.say(RECORDS_ABOVE.format(root=above))
            talk.say()
            return _locate(talk, above, tool)
    if not available and tool is None and not found.too_big() and not found.unreadable:
        above = find.results_above(root)
        if above is not None:  # run from a subfolder (src/, say) of the project
            _note(talk, f"No eval results in {root.name}. Reading the project folder above it "
                        f"({above.name}).")
            talk.say()
            return _locate(talk, above, tool)
    if tool is not None:
        if tool not in available:
            if any(r.tool == tool for r in found.too_big()):
                raise _too_big(talk, found)
            if tool == "promptfoo" and "promptfoo" in found.signs:
                return _export(talk, root, found.signs["promptfoo"][0])
            raise StartError(f"No saved {find.NAMES[tool]} results found in {root}.")
        available = [tool]
    if not available:
        if found.too_big():  # said above, with how to read them anyway
            raise _too_big(talk, found)
        if found.unreadable:
            raise _unreadable(found)
        if found.skipped:
            raise _left_out(talk, root, found)
        if found.stopped:  # only when nothing was found: results found are what was asked
            talk.say(f"{found.stopped} {POINT_ME.format(program=talk.program)}")
        if "promptfoo" in found.signs:
            return _export(talk, root, found.signs["promptfoo"][0])
        _nothing_found(talk, root, found.signs)
        raise Stop(EXIT_USAGE)
    by_date = {t: sorted(found.readable(t), key=lambda r: r.date(), reverse=True)
               for t in available}
    kind = available[0]
    if len(available) > 1:
        options = [f"{find.NAMES[t]} ({_where(by_date[t][0])})" for t in available]
        kind = available[talk.choose(
            "Saved results from more than one eval tool:", options,
            f"Several tools found; choose one with {_or([f'--tool {t}' for t in available])}",
            flag="--tool", values=available, what="which eval tool's results to check")]
        _next_time(talk, "--tool", kind)
    if root.name == find.HIDDEN_KEPT:  # a .deepeval/ folder: its project is the one it is in
        root = root.parent
        return root, kind, [replace(r, rel=r.path.relative_to(root).as_posix())
                            for r in by_date[kind]], found.signs
    return root, kind, by_date[kind], found.signs


def _eval_folder(result: find.Result) -> str | None:
    """The folder DeepEval saved a results file in (a .deepeval/ or results folder): one
    eval. None for a file under a name of its own (a run copied out), read with any. For
    Inspect AI, the folder a log is in (its logs/ folder)."""
    if result.tool == "inspect":
        return Path(result.rel).parent.as_posix()
    name = result.path.name
    if name in find.DEEPEVAL_COPIES or find.DEEPEVAL_RUN.fullmatch(name):
        return Path(result.rel).parent.as_posix()
    return None


def _link_only(result: find.Result) -> bool:
    from judgekeeper.readers.deepeval import is_link_only

    if result.size > 4096:  # a link-only file is a few lines
        return False
    try:
        return is_link_only(textio.read_json(result.path, ValueError))
    except (OSError, ValueError):
        return False


def _choose_folder(talk: Talk, results: list[find.Result], prefer: str | None,
                   kind: str = "deepeval") -> list:
    """DeepEval results (or Inspect AI logs) in more than one folder are separate evals,
    never one pool: the results of one folder, the last check's (`prefer`) or the one the
    person picks."""
    folders = list(dict.fromkeys(f for f in map(_eval_folder, results) if f))  # newest first
    if len(folders) < 2:
        return results
    what = "Inspect logs" if kind == "inspect" else "DeepEval results"
    if kind == "deepeval" and all(_link_only(r) for r in results):
        from judgekeeper.readers.deepeval import LinkOnly

        raise StartError(f"Each DeepEval results folder here ({', '.join(folders)}) only links "
                         "to Confident AI; your results aren't saved on this computer.",
                         LinkOnly.next_step)
    if prefer not in folders:
        shown = [f"{f}/ ({_where(next(r for r in results if _eval_folder(r) == f))})"
                 for f in folders]
        commands = [talk.command_at(f) for f in folders]
        prefer = folders[talk.choose(
            f"{what} in more than one folder:", shown,
            f"{what} in more than one folder; choose one with {_or(commands)}",
            flag="PATH", values=folders, what=f"which {what} to check")]
        talk.remember("PATH", prefer, f"(Next time: {talk.command_at(prefer)})")
    return [r for r in results if _eval_folder(r) in (prefer, None)]


TITLE_ROW = "{file}: Row 2 looks like the header. Delete row 1 and run again."
EXCEL = "{file}: Excel files aren't read. Save it as CSV UTF-8 and run again."


def title_row(rel: str) -> Damaged:
    """A table whose first row is a title: row 2 is its header."""
    return Damaged(TITLE_ROW.format(file=rel),
                   f"delete row 1 of {rel}, then run `{{command}}` again.")


def table_output(rel: str) -> Damaged:
    """promptfoo's table output: each test's overall pass, never the judge's own decision."""
    return Damaged(f"{rel} {find.TABLE_OUTPUT}.",
                   "save the full results with `promptfoo eval -o results.json`, then run "
                   "`{command}` again.")


def _unreadable(found: find.Search) -> Damaged:
    """The results-like file judgekeeper found but could not read, when it found no other."""
    rel, how = found.unreadable[0]
    if how == find.TABLE_OUTPUT:
        return table_output(rel)
    if how == find.TITLE_ROW:
        return title_row(rel)
    if how == find.EXCEL_FOUND:
        return Damaged(f"{rel} {how}.", f"save {rel} as CSV UTF-8, then run `{{command}}`.")
    if how == find.NO_ASSESSMENTS:
        return Damaged(f"{rel} {how}.", NO_JUDGE_NEXT)
    if how != "is empty":
        return Damaged(f"{rel} {how}.", f"give your user permission to read {rel}, then run "
                                        "`{command}` again.")
    if "promptfoo" in found.signs and rel.endswith(".json"):
        return Damaged(f"{rel} is empty, so judgekeeper can't read it.",
                       f"save your promptfoo results to it with `promptfoo eval -o {rel}`, "
                       "then run `{command}` again.")
    return Damaged(f"{rel} is empty, so judgekeeper can't read it.",
                   f"save your results to {rel} again, then run `{{command}}` again.")


def _left_out(talk: Talk, root: Path, found: find.Search) -> Stop:
    """Nothing found where judgekeeper looks, but results-like files elsewhere: name them
    and the command that reads the first."""
    _note(talk, f"No eval results found where judgekeeper looks: {find.looked(root)}. It "
                "left out:")
    for rel, why in found.skipped[:5]:
        talk.say(f"  {rel} ({why})")
    if len(found.skipped) > 5:
        talk.say(f"  and {len(found.skipped) - 5} more")
    which = "that is" if len(found.skipped) == 1 else "one of these is"
    first, why = found.skipped[0]
    if why == find.NOT_UTF8:  # running it as it is would only say to save it as UTF-8
        which = "that is" if len(found.skipped) == 1 else f"{first} is"
        next_step = (f"if {which} your results, save it as UTF-8, then run "
                     f"`{talk.command_at(first)}` again.")
    else:
        next_step = f"if {which} your results, run `{talk.command_at(first)}`."
    if not getattr(talk, "screens", False):
        talk.say(f"Next: {next_step[0].upper()}{next_step[1:]}")
    return talk.stop(EXIT_USAGE, next_step)


def _too_big(talk: Talk, found: find.Search) -> Stop:
    big = found.too_big()[0]
    return talk.stop(EXIT_USAGE, f"to read {big.rel} anyway, run "
                                 f"`{talk.command_at(big.rel, '--yes')}`.")


def _read_anyway(talk: Talk, path: Path) -> None:
    """A file named on the command line over find.MAX_BYTES: read only after a yes (at a
    terminal, or --yes without one), as a found one is. Asked before anything is read. A
    quiet talk (check and fix reading the marked results again) asks nothing."""
    size = path.stat().st_size
    if size <= find.MAX_BYTES or talk.quiet:
        return
    said = f"{path.name} is {find.megabytes(size)}."
    anyway = f"to read {path.name} anyway, run `{talk.command('--yes')}`."
    if getattr(talk, "screens", False) and not _interactive() and not talk.yes:
        raise _stop_with(talk, said, anyway)
    if talk.confirm(f"{said} Read it anyway?", default=False, with_yes=True,
                    hint=f"{said} {anyway[0].upper()}{anyway[1:]}"):
        return
    raise _stop_with(talk, f"{path.name} was left alone.", anyway, EXIT_OK)


def results_description(result: find.Result) -> str | None:
    """The `config.description` of a promptfoo results file, or None."""
    try:
        data = json.loads(result.path.read_text(encoding="utf-8", errors="replace"))
        theirs = (data.get("config") or {}).get("description")
    except (OSError, ValueError, AttributeError, RecursionError):
        return None
    return (theirs.strip() or None) if isinstance(theirs, str) else None


def _check_description(talk: Talk, root: Path, theirs: str | None,
                       result: find.Result, others: list[find.Result] = ()) -> None:
    """Ask before using promptfoo results whose description is in none of the project's
    promptfoo configs (when they have one), before anything is read. After No: the newest
    of `others` from this project, or how to name your own."""
    mine = _project_descriptions(root)
    if theirs is None or not mine or any(same_words(theirs, d) for d in mine):
        return
    said = (f'{result.rel} looks like it is from another project (its description is '
            f'"{theirs}", and no promptfoo config here has it).')
    own = f"`{talk.command_at('PATH')}` with the path of your own results file"
    question = f"{said} Use it anyway?"
    if getattr(talk, "screens", False) and not _interactive() and not talk.yes:
        raise _stop_with(talk, question, f"run `{talk.command('--yes')}` to use it anyway, or "
                                         f"{own}.")
    if talk.confirm(question, default=False, with_yes=False,
                    hint=f"{question} Run {textio.program()} in a terminal to answer, "
                         "or point me at the right results file."):
        return
    other = next((r for r in others if r.path != result.path
                  and results_description(r) in mine), None)
    if other is not None:
        raise _stop_with(talk, f"{result.rel} was left alone.",
                         f"run `{talk.command_at(other.rel)}` to read {other.rel}, the newest "
                         "results from this project.", EXIT_OK)
    raise _stop_with(talk, f"{result.rel} was left alone.", f"run {own}.", EXIT_OK)


# A promptfoo config: `prompts` and `providers` or `tests` at the top
_CONFIG_KEY = re.compile(r"^(prompts|providers|tests)\s*:", re.MULTILINE)
CONFIG_SUFFIXES = (".yaml", ".yml", ".json")
MAX_CONFIGS = 200  # files looked at for promptfoo configs


def _promptfoo_config(path: Path) -> tuple[bool, str | None]:
    """(whether `path` is a promptfoo config: named promptfooconfig.*, or with its keys; its
    top-level `description` or None). YAML by a line scan, no YAML reader."""
    try:
        if path.stat().st_size > find.HEAD_BYTES * 16:
            return False, None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            return False, None
        keys = set(data) if isinstance(data, dict) else set()
        value = data.get("description") if isinstance(data, dict) else None
    else:
        keys = {m[1] for m in _CONFIG_KEY.finditer(text)}
        value = yaml_description(text)
    named = path.name.lower() in find.PROMPTFOO_CONFIGS
    if not named and ("prompts" not in keys or not keys & {"providers", "tests"}):
        return False, None
    return True, (value.strip() or None if isinstance(value, str) else None)


def _project_descriptions(root: Path) -> set[str]:
    """The descriptions of every promptfoo config in the project (_promptfoo_configs)."""
    return {d for d in _promptfoo_configs(root).values() if d}


def _default_test_has(path: Path, name: str) -> bool:
    """Whether the promptfoo config at `path` gives defaultTest a judge named `name` (its type
    or metric): JSON read as JSON, YAML scanned line by line (no YAML parser)."""
    from judgekeeper.readers.promptfoo import _in_default

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        default = data.get("defaultTest")
        return isinstance(default, dict) and _in_default(default, name)
    lines = text.splitlines()
    value = re.compile(rf"""(?:type|metric)\s*:\s*['"]?{re.escape(name)}['"]?\s*(?:#.*)?$""")
    for i, line in enumerate(lines):
        head = re.match(r"(\s*)defaultTest\s*:", line)
        if not head:
            continue
        for more in lines[i + 1:]:
            if more.strip() and len(more) - len(more.lstrip()) <= len(head[1]):
                break
            if value.search(more):
                return True
    return False


def _config_named(root: Path, result: find.Result) -> str:
    """The promptfoo config `result` was made from, as a path in the project: the only one,
    else the one with its description, else the one in its folder; else promptfoo's own
    name for it, promptfooconfig.yaml."""
    configs = _promptfoo_configs(root)
    if len(configs) == 1:
        return next(iter(configs))
    theirs = results_description(result)
    same = [rel for rel, mine in configs.items() if theirs is not None and mine == theirs]
    folder = Path(result.rel).parent
    beside = [rel for rel in configs if Path(rel).parent == folder]
    return next((x[0] for x in (same, beside) if len(x) == 1), find.PROMPTFOO_CONFIGS[0])


def _promptfoo_configs(root: Path) -> dict[str, str | None]:
    """{path in the project: its description} for every promptfoo config, at most
    find.TABLE_DEPTH folders deep (the folders find skips are skipped, links never
    followed)."""
    found, looked, queue = {}, 0, [root]
    while queue and looked < MAX_CONFIGS:
        folder = queue.pop(0)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if find._walked(entry.name) and len(path.relative_to(root).parts) < \
                        find.TABLE_DEPTH:
                    queue.append(path)
            elif path.suffix.lower() in CONFIG_SUFFIXES and looked < MAX_CONFIGS:
                looked += 1
                config, description = _promptfoo_config(path)
                if config:
                    found[path.relative_to(root).as_posix()] = description
    return found


def config_description(path: Path) -> str | None:
    """The top-level `description:` of the promptfoo config at `path`: a line scan, no YAML."""
    if not path.is_file() or path.is_symlink():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(text).get("description")
        except (ValueError, AttributeError, RecursionError):
            return None
        return value.strip() if isinstance(value, str) else None
    return yaml_description(text)


def _judges(records, kind: str | None = None) -> Counter:
    """How many answers each LLM judge in `records` graded, counted as the pool counts them:
    repeats of one answer with the same grade once, with different grades each. A DeepEval
    metric with no model (Exact Match, a check written in Python) is a rule in code, not a
    judge."""
    grades: dict[tuple, list] = {}
    for r in records:
        if r.annotator_kind == LLM:
            key = (r.name, r.target_id if r.target_id and not getattr(records, "ids_derived", True)
                   else derive_record_id(r.input, r.output, r.trajectory))
            grades.setdefault(key, []).append(r.label)
    counts: Counter = Counter()
    for (name, _), labels in grades.items():
        counts[name] += len(labels) if len(set(labels)) > 1 else 1
    if kind == "deepeval":
        judged = {r.name for r in records
                  if r.annotator_kind == LLM and (r.evaluator or {}).get("model")}
        counts = Counter({n: c for n, c in counts.items() if n in judged})
    return counts


def _rules_in_code(records, kind: str | None) -> bool:
    """`records` hold checks, but each is a rule in code."""
    return any(r.annotator_kind == CODE for r in records) or (
        kind == "deepeval" and any(r.annotator_kind == LLM for r in records))


NO_JUDGE_NOUN = {"inspect": "Inspect logs", "table": "results tables"}
RULES_WORD = {"deepeval": "metrics", "inspect": "scorers", "mlflow": "scorers"}
NO_JUDGE_NEXT = "add an LLM-as-a-judge to your eval and run it once, then run `{command}` again."


def _run_has_no_cases(result: find.Result) -> bool:
    """A DeepEval run file that holds no test case at all."""
    cases = find._run_of(result.path)
    return cases is not None and not any(cases)


def _no_judge(talk: Talk, kind: str, files: list, rules: bool, empty: bool = False) -> Stop:
    """None of `files` (rels, newest first) holds an LLM judge's decisions: said once. A run
    with no test case at all (`empty`) is said as that: no judge was missing."""
    if empty:
        text = (f"{files[0]}: The run has no test cases." if len(files) == 1 else
                f"None of your {len(files)} runs has a test case.")
        return _stop_with(talk, text,
                          f"run your eval with its test cases, then run `{talk.command()}`.")
    if len(files) == 1:
        text = f"{files[0]} holds no decisions from an LLM-as-a-judge."
    else:
        noun = NO_JUDGE_NOUN.get(kind, f"{find.NAMES.get(kind, kind)} results files")
        text = f"None of your {len(files)} {noun} holds decisions from an LLM-as-a-judge."
    if rules:
        text += (f" These {RULES_WORD.get(kind, 'checks')} are rules in code, not an "
                 "LLM-as-a-judge. judgekeeper checks an LLM-as-a-judge.")
    return _stop_with(talk, text, NO_JUDGE_NEXT.format(command=talk.command()))


def _stop_with(talk: Talk, text: str, next_step: str, code: int = EXIT_USAGE) -> Stop:
    """Say `text`, then stop with `next_step` (`judgekeeper` says it in its Next: line)."""
    _note(talk, text)
    if not getattr(talk, "screens", False):
        talk.say(f"Next: {next_step}")
    return talk.stop(code, next_step)


def _note(talk: Talk, text: str) -> None:
    """One line of the finder's, wrapped on `judgekeeper`'s screens."""
    getattr(talk, "para", talk.say)(text)


def _choose_metric(talk: Talk, newest: Loaded, metric: str | None,
                   prefer: str | None = None, kind: str | None = None) -> str:
    counts = _judges(newest.records, kind)
    names = sorted(counts)
    if not names:
        raise _no_judge(talk, kind, [newest.label], _rules_in_code(newest.records, kind))
    if metric is None and prefer in counts:
        return prefer
    if metric is not None:
        if metric not in counts:
            raise StartError(f"no LLM-as-a-judge named {metric!r}; the names are: "
                             f"{', '.join(repr(n) for n in names)}",
                             f"run `{{command}} --metric {quote_arg(names[0])}`.", "--metric")
        return metric
    if len(names) == 1:
        return names[0]
    options = [f"{n} ({_plural(counts[n], 'answer', 'answers')})" for n in names]
    name = names[talk.choose(
        "These results hold more than one LLM-as-a-judge:", options,
        "Several LLM-as-a-judge metrics found; choose one with "
        f"{_or([f'--metric {quote_arg(n)}' for n in names])}",
        flag="--metric", values=names, what="which LLM-as-a-judge to check")]
    _next_time(talk, "--metric", name)
    return name


def _next_time(talk: Talk, flag: str, chosen: str) -> None:
    """After the person picks at "Which one?": the flag that picks it without asking."""
    talk.remember(flag, chosen)


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
        return "promptfoo's default grader (no model written in your config)"
    if tool == "records":
        return f"{metric}{quoted} (your records do not say which model: pass judge= to record())"
    return f"{metric}{quoted} (the results file does not say which model)"


def find_judge(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
               experiment: str | None = None, pass_if: str | None = None,
               label_map: str | dict | None = None, judge_model: str | None = None,
               talk: Talk | None = None, prefer: str | None = None,
               tracking_uri: str | None = None, store: str | None = None,
               saved: settings.StartSettings | None = None,
               only: list[str] | None = None) -> Found:
    """Find the results, choose what to use, make the pool and name the judge.

    `talk` says each step and asks the questions; the default says nothing and, with no one
    to ask, stops (Stop) where a question would be needed. `prefer` (the judge of the last
    check) is chosen without asking when the newest results hold it among several; `store`
    (the MLflow store of the last check) likewise. `tracking_uri` names the MLflow store.
    `saved` stands in for judgekeeper.toml's [start] table (a map not saved yet). `only`
    (paths in the project) keeps to those results files: the ones the marks were made on.
    """
    talk = talk or Talk(quiet=True)
    if saved is None and tool is None and tracking_uri is None:
        saved = _saved(Path(path))
    if saved is not None and saved.source != "map":
        tool = saved.source
    if saved is not None and saved.judge not in (None, "*"):
        prefer = prefer or saved.judge
    if saved is not None and saved.source == "mlflow":  # the store and experiment asked once
        store, experiment = store or saved.file, experiment or saved.experiment
    if saved is not None and saved.source in ("deepeval", "inspect"):  # the folder asked once
        store = store or saved.file
    if tracking_uri is not None:
        root, kind, results, signs = _given_store(talk, Path(path), tracking_uri)
    elif saved is not None and saved.source == "map":
        root, kind, results, signs = _mapped_source(talk, Path(path).resolve(), saved)
    else:
        root, kind, results, signs = _locate(talk, Path(path), tool)
    if only:
        results = [r for r in results if r.rel in only] or results
    if kind == "mlflow":
        results = _choose_store(talk, root, results, experiment, store)
    elif kind in ("deepeval", "inspect"):
        results = _choose_folder(talk, results, store, kind)
    newest = results[0]
    description = None
    name = None
    if kind == "mlflow":
        name, runs = _mlflow_runs(talk, newest, experiment, metric)
        read_older = iter(runs[1:])
        first = runs[0] if runs else None
        if first is None:
            raise StartError(f"MLflow experiment {name!r} has no LLM-as-a-judge assessments")
    else:
        if kind == "inspect" and not _has("inspect_ai"):
            json_logs = [r for r in results if r.path.suffix.lower() != ".eval"]
            if not json_logs:
                raise _needs_extra(talk, "inspect", _folder_of(newest))
            if newest.path.suffix.lower() == ".eval":  # never read an older log in silence
                _note(talk, EVAL_SKIPPED.format(eval=newest.rel, json=json_logs[0].rel,
                                                get=_get_extra(talk, "inspect")))
                talk.say()
            results, newest = json_logs, json_logs[0]
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
                raise StartError(f"no LLM-as-a-judge named {metric!r} in {_folder_of(newest)}")
            if kind == "records":
                labels = [x.label for x in loaded]
                results = sorted((r for r in results if r.rel in labels),
                                 key=lambda r: labels.index(r.rel))
                newest = results[0]
            first, read_older = loaded[0], iter(loaded[1:])
        else:
            first, rest = None, list(results)
            unjudged, rules = [], True  # files with no judge's decisions (a smoke test, say)
            empty = True  # every one of them holds no test case at all
            while first is None:  # a file that can't be read never hides a good one beside it
                newest = rest.pop(0)
                try:
                    first = _read(newest)
                except RecordsError as e:
                    if not rest and not unjudged:
                        raise usage_error(e, _unread(e, newest, root)) from None
                    _note(talk, f"{_unread(e, newest, root)} It is left out.")
                    if not rest:
                        raise _no_judge(talk, kind, [r.rel for r in unjudged], rules,
                                        False) from None
                    continue
                if not _judges(first.records, kind):
                    unjudged.append(newest)
                    rules = rules and _rules_in_code(first.records, kind)
                    empty = empty and kind == "deepeval" and _run_has_no_cases(newest)
                    if not rest:
                        raise _no_judge(talk, kind, [r.rel for r in unjudged], rules, empty)
                    first = None
            for r in unjudged[:3]:
                _note(talk, f"{r.rel} is left out: no LLM-as-a-judge in it.")
            if len(unjudged) > 3:
                more = len(unjudged) - 3
                _note(talk, f"{more} more {'file is' if more == 1 else 'files are'} left out: no "
                            f"LLM-as-a-judge in {'it' if more == 1 else 'them'}.")
            if unjudged:
                talk.say()
            if kind == "promptfoo":  # asked about the file read, never one left out
                description = results_description(newest)
                _check_description(talk, root, description, newest, results)
            results = [newest, *rest]
            read_older = _readable(talk, rest, root)
    if kind in ("records", "mapped"):
        metrics = sorted({r.name for r in every.records if r.annotator_kind == LLM})
    else:
        metric = _choose_metric(talk, first, metric, prefer, kind)
        metrics = sorted(_judges(first.records, kind))

    norm = Normaliser(pass_if=pass_if,
                      label_map={**first.records.label_map, **parse_label_map(label_map)})
    used = [first]
    own_ids = kind in ("table", "mapped")
    pool = build_pool([(x.label, x.records) for x in used], metric, norm, own_ids)
    identity = _identity(first.records, metric)
    for older in read_older:
        if len(pool.answers) >= MIN_POOL and kind != "records":
            break
        if _identity(older.records, metric) == identity:
            used.append(older)
            pool = build_pool([(x.label, x.records) for x in used], metric, norm, own_ids)

    records = [r for x in used for r in x.records
               if r.annotator_kind == LLM and r.name == metric]
    known, _ = _consensus([a.fingerprint for a in pool.answers]) if pool.answers else ({}, [])
    fingerprint = make_fingerprint(known).to_dict()
    models = sorted({str(r.evaluator["model"]) for r in records if r.evaluator.get("model")})
    model_source = None
    if judge_model is not None:
        if models:
            raise StartError(f"{Path(first.label).name} already names the LLM-as-a-judge's model "
                             f"({', '.join(models)}): drop --judge-model")
        model_source = GIVEN_BY_YOU
        fingerprint.update(model=judge_model, model_source=model_source)
        models = [judge_model]
    elif not models and saved is not None and saved.model:
        model_source = f"given in {settings.FILE}"
        fingerprint.update(model=saved.model, model_source=model_source)
        models = [saved.model]
    rule = rule_of(records)
    n_rules = len({k for k in (_rule_key(r, kind) for r in records) if k is not None})
    one_rule = n_rules <= 1
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
                 n_rules=n_rules, reference=bool(records) and all(
                     (r.metadata or {}).get("reference") for r in records),
                 task_file=_task_file(newest.path) if kind == "inspect" else None,
                 rule_field=_inspect_field(records) if kind == "inspect" and rule else None,
                 models=models, model_source=model_source, experiment=name,
                 stopped=list(dict.fromkeys(n for x in used for n in x.records.notes))
                 + [n for x in used if (n := left_out_note(x.records, x.label))],
                 label_map=label_map or None,
                 warnings=[w for w in first.records.warnings if not is_stripped_warning(w)]
                 + list(first.records.per_metric.get(metric, {}).get("warnings") or []))


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
TRACKING_SERVER = ("{uri} is a tracking server. judgekeeper reads a local MLflow store instead: "
                   "an mlflow.db file or an mlruns/ folder in your project.")


def _given_store(talk: Talk, path: Path, uri: str) -> tuple[Path, str, list, dict]:
    """--tracking-uri: the local MLflow store it names (mlflow.db, `sqlite:///...`, an
    mlruns/ folder or a `file:` address of one). A tracking server is not read."""
    from judgekeeper.readers.mlflow_store import folder_of

    text = str(uri)
    if text.startswith(SERVERS):
        raise StartError(TRACKING_SERVER.format(uri=uri))
    if text.startswith("sqlite:///"):
        store = Path(text[len("sqlite:///"):])
    else:
        store = folder_of(text) or Path(text)
    if not store.exists():
        raise StartError(f"no MLflow store at {uri}")
    root = path.resolve() if path.is_dir() else path.resolve().parent
    store = store.resolve()
    rel = store.relative_to(root).as_posix() if store.is_relative_to(root) else str(store)
    talk.looking(root)
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
        store_damage,
        store_uri,
    )

    stores = sorted(stores, key=lambda s: (s.path.is_dir(), -s.date().timestamp()))
    if not _has("mlflow"):  # the same screen as for one store: never a bare error
        raise _needs_extra(talk, "mlflow", _store_name(stores[0]))
    names = []
    for s in stores:
        uri = store_uri(s.path, say=talk.say)
        with quiet(), folder_store_allowed(uri, say=None), store_damage(uri):  # said when read
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
    if not _interactive() and not talk.asks_everything:
        talk.say(f"{title} Using {_store_name(stores[0])}.")
        others = [talk.command_at(s.rel) for s in stores[1:]]
        talk.say(f"For the other one: {others[0]}" if len(others) == 1
                 else f"For another one: {_or(others)}")
        return stores
    chosen = stores[talk.choose(f"{count} MLflow stores found:", shown, "", flag="PATH",
                                values=[s.rel for s in stores],
                                what="which MLflow store to read")]  # each said once: listed
    talk.remember("PATH", chosen.rel, f"(Next time: {talk.command_at(chosen.rel)})")
    return first(chosen)


# What `start` says after finding ---------------------------------------------------------

_plural = plural  # textio.plural


def _pass_mark_words(pm: dict) -> str:
    mark = f"{pm['mark']:g}"
    words = {">=": f"{mark} or more", ">": f"more than {mark}", "<=": f"{mark} or less",
             "<": f"less than {mark}"}
    return f"score {words[pm['op']]}" if pm.get("op") in words else f"score {mark}"


def pass_at(pm: dict) -> str:
    """"Pass at 0.6 or more": the pass mark, as the Read-from-your-file rows say it."""
    return "Pass at " + _pass_mark_words(pm).removeprefix("score ")


SENTENCE = re.compile(r"[.!?;:]")  # punctuation a grade word does not hold


def verdict_like(value) -> bool:
    """Whether a decision value looks like a grade word, so it may be shown: at most 3 words,
    under 30 characters, no sentence punctuation. Anything longer may be the judge's reason
    or an answer's text (a CSV quote that never closes puts them there)."""
    text = " ".join(str(value).split())
    return len(text) < 30 and len(text.split()) <= 3 and not SENTENCE.search(text)


def shown_value(value) -> str:
    """A decision value on one line; quoted when it holds a comma."""
    text = " ".join(str(value).split())
    return f'"{text}"' if "," in text else text


__all__ = ["Answer", "Found", "Pool", "StartError", "Talk", "build_pool", "find_judge"]
