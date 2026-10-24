"""MLflow: assessments on traces in an MLflow tracking store, read with MLflow's own client.

Needs the optional extra (`pip install "judgekeeper[mlflow]"`). The tracking URI is
`tracking_uri` when given, otherwise whatever MLflow resolves (`MLFLOW_TRACKING_URI`, then its
default), so a local `mlruns` folder, a SQL store, a tracking server and Databricks
(`DATABRICKS_HOST`, `DATABRICKS_TOKEN`) all work, with MLflow handling the credentials.

Shape (mlflow 3.16: entities/assessment.py, assessment_source.py, tracing/constant.py), from
`Assessment.to_dictionary()`: `assessment_id`, `assessment_name`, `trace_id`,
`source: {source_type, source_id}`, `feedback: {value, error: {error_code, error_message}}`
or `expectation`, `rationale`, `metadata`, `overrides`, `valid`.

- Traces come from `MlflowClient.search_traces`, the paged call behind `mlflow.search_traces`,
  one page of 100 at a time, scoped with `locations` where it takes that parameter (MLflow
  3.16 deprecates `experiment_ids`) and `experiment_ids` otherwise.
- `source_type` LLM_JUDGE is the judge, HUMAN the human, CODE ignored, except a judge call
  that failed: `mlflow.genai.evaluate` saves it as a CODE assessment named after the scorer,
  with error code SCORER_ERROR. Where that name is also an LLM judge's, it is that judge's
  failed call (its error text kept, so the judge check counts "calls failed"); when every
  call of a judge failed, that is the error, with MLflow's first error text. Only feedback counts;
  expectations (ground truth) are not verdicts. A judge assessment with `feedback.error` has
  no verdict; its error text is the explanation, and an in-memory mark (records.Mark) tells
  `start`'s judge check the judge's call failed.
- `mlflow.override_feedback` marks the judge's assessment `valid: false` and logs the human's
  with `overrides` = its id: the overridden value is still the judge's verdict. A human
  assessment that is itself overridden (`valid: false`) is dropped.
- Each judge assessment's run is its `mlflow.assessment.sourceRunId` metadata (set by
  `mlflow.genai.evaluate`, also when it scores existing traces), else the trace's
  `mlflow.sourceRun`. Runs are ordered by start time.
- Trace ids change on every evaluation run, so the item id is derived from the trace's request
  input (`table.derive_id`), unless `id_from` names a trace tag or request input key.
- An assessment can be on the whole trace or on one span inside it (`span_id`, kept in the
  record's `metadata`). Only trace-level assessments are verdicts on the answer, so span-level
  ones are left out, with a note, unless `metric` names a judge that is only on spans; a
  judge on both never mixes them. An assessment on the root span is trace-level:
  `mlflow.genai.evaluate` logs every assessment there.
- A folder store keeps each trace's files at the full path saved when it was made; once the
  store is copied or cloned to another computer, MLflow cannot find them and drops the trace.
  Here they are read from the store's own folder (`_traces`); traces whose files are in
  neither place are left out and counted (TracesMissing when that is all of them).
- MLflow's own log lines (its hint for coding agents, a warning per trace) are kept out of
  judgekeeper's output while it reads (`quiet`).
- Fingerprint: model from `source.source_id` (`openai:/gpt-4.1-mini` gives provider
  `openai`); `mlflow.assessment.scorerName`/`scorerVersion` metadata as the rubric version.
  A `make_judge` (MLflow 3.14 and later) saves its instructions in the assessment's metadata
  (`guideline`, or `instructions`): they are the judge's rule (`evaluator.rule`), so they are
  hashed into the prompt hash and a changed rule is a new judge (judge_instructions). Other
  judges' prompts are not saved with the assessment, and scorer tracing is off by default,
  so there is usually no trace of the judge's own call either: prompt unknown.
"""

from __future__ import annotations

import atexit
import gc
import inspect
import json
import logging
import os
import shutil
import tempfile
import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from judgekeeper.records import (
    CODE,
    HUMAN,
    LLM,
    NO_MARK,
    Damaged,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    check_record,
    derive_record_id,
)
from judgekeeper.textio import get_extra, reading

# The loggers MLflow's reading goes through: MLflow's own, and the database layers under it
LOGGERS = ("mlflow", "alembic", "sqlalchemy")

NEEDS_EXTRA = "reading MLflow needs mlflow. To read it, {get}."
KINDS = {"LLM_JUDGE": LLM, "AI_JUDGE": LLM, "HUMAN": HUMAN, "CODE": CODE}
SOURCE_RUN_ID = "mlflow.assessment.sourceRunId"
SCORER_NAME = "mlflow.assessment.scorerName"
SCORER_VERSION = "mlflow.assessment.scorerVersion"
TRACE_SOURCE_RUN = "mlflow.sourceRun"
TRACE_INPUTS = "mlflow.traceInputs"
TRACE_OUTPUTS = "mlflow.traceOutputs"
SCORER_ERROR = "SCORER_ERROR"  # how mlflow.genai.evaluate saves a scorer that raised
PAGE_SIZE = 100
# Traces read from one experiment, newest first (MLflow's order): reading takes about 1 ms
# each, so 100,000 took minutes. Past it, CAPPED says so.
MAX_TRACES = 30_000
CAPPED = ("{experiment} has more than {n:,} traces: judgekeeper read the newest {n:,} (reading "
          "every trace of a very big experiment takes minutes).")
NO_RUN = "(no run)"
BIG_STORE = 1_000_000_000  # bytes: a store this big gets a line before it is copied
SQLITE_SIDE_FILES = ("-wal", "-shm")  # SQLite keeps recent writes there until a checkpoint

ALLOW = "MLFLOW_ALLOW_FILE_STORE"
HINT = "MLFLOW_DISABLE_AGENT_HINT"  # MLflow's hint for coding agents, logged on import
FOLDER_NOTE = ("Reading your mlruns/ folder with MLflow's folder-store setting switched on for "
               "this read only (MLFLOW_ALLOW_FILE_STORE).")
_noted = False  # FOLDER_NOTE was said in this run

_copies: dict[tuple, Path] = {}  # (store path, size, modified) -> its copy, this process
_copies_lock = threading.Lock()


def store_uri(path: Path, say=None) -> str:
    """The tracking URI to read the local store at `path` with.

    An `mlflow.db` file is never opened through MLflow: it is copied once per process (with
    its `-wal` and `-shm` files when present) into a temporary folder, removed when the
    process ends, and the copy is read with a plain `sqlite:///` address. Read-only SQLite
    addresses (`sqlite:///file:...?mode=ro&uri=true`) do not work on Windows, where MLflow
    takes them as a file name. The asking-again worker reads the same copy later, so the
    copy lives until the process ends, not until this function returns.

    A folder store (`mlruns/`) is read where it is: copying it would copy every artifact.
    MLflow 3.16's FileStore opens it only when MLFLOW_ALLOW_FILE_STORE=true is set (see
    folder_store_allowed), and creates `mlruns/.trash` when it is missing (a store MLflow
    wrote always has it); it writes nothing else on reading
    (mlflow/store/tracking/file_store.py, FileStore.__init__).
    """
    path = Path(path)
    if path.is_dir():
        return str(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _copies_lock:
        if key not in _copies:
            if stat.st_size >= BIG_STORE and say is not None:
                say(f"Reading a copy of {path.name} ({stat.st_size / 1e9:.1f} GB)…")
            folder = Path(tempfile.mkdtemp(prefix="judgekeeper-mlflow-"))
            try:
                for suffix in ("", *SQLITE_SIDE_FILES):
                    part = path.with_name(path.name + suffix)
                    if part.is_file():
                        shutil.copy2(part, folder / part.name)
            except BaseException:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            _copies[key] = folder / path.name
        copy = _copies[key]
    return f"sqlite:///{copy.as_posix()}"


def folder_of(uri) -> Path | None:
    """The folder of a local folder store (`mlruns/`) that a tracking URI names: a folder
    path, or a file: address of one. None for mlflow.db (`sqlite:///...`) or a server."""
    if not uri:
        return None
    text = str(uri)
    if text.startswith("file:"):
        path = Path(url2pathname(urlparse(text).path))
    elif "://" in text:
        return None
    else:
        path = Path(text)
    return path if path.is_dir() else None


def is_folder_store(uri) -> bool:
    """Whether a tracking URI is a local folder store (`mlruns/`) (folder_of)."""
    return folder_of(uri) is not None


@contextmanager
def quiet() -> Iterator[None]:
    """Around judgekeeper's own MLflow calls: MLflow says nothing of its own. Its hint for
    coding agents (logged on `import mlflow` when an agent runs it) is switched off with
    MLFLOW_DISABLE_AGENT_HINT=1, and its loggers (and the database layers' under it) show
    only CRITICAL: it warns once per trace it cannot download, and logs a traceback that
    holds the stored text when a trace has a byte that isn't UTF-8. Both are put back
    afterwards, also after an error; a value the user set is left as it is. Never for the
    user's shell, never in a file."""
    set_hint = HINT not in os.environ
    if set_hint:
        os.environ[HINT] = "1"
    try:
        import mlflow  # noqa: F401 - MLflow sets its loggers' level on import
    except ImportError:
        pass
    loggers = [logging.getLogger(name) for name in LOGGERS]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)
        if set_hint:
            os.environ.pop(HINT, None)


@contextmanager
def folder_store_allowed(uri, say=None) -> Iterator[None]:
    """Around MLflow calls that read the store at `uri`: when it is a folder store, set
    MLFLOW_ALLOW_FILE_STORE=true for these calls only (MLflow 3.16 and later open a folder
    store only with it; older versions ignore it), then remove it again, also after an
    error. A value the user set is left as it is. `say` gets FOLDER_NOTE the first time in
    a run. The variable is never set for mlflow.db or a server, and never written anywhere."""
    global _noted
    if not is_folder_store(uri) or ALLOW in os.environ:
        yield
        return
    if say is not None and not _noted:
        _noted = True
        say(FOLDER_NOTE)
    os.environ[ALLOW] = "true"
    try:
        yield
    finally:
        os.environ.pop(ALLOW, None)


def _close_engines(folders: list[Path]) -> None:
    """Close MLflow's database connections to the copies: Windows cannot delete a file that
    is still open."""
    try:
        from sqlalchemy.engine import Engine
    except ImportError:
        return
    marks = [f.as_posix() for f in folders]
    for obj in gc.get_objects():
        try:
            if isinstance(obj, Engine) and any(m in str(obj.url) for m in marks):
                obj.dispose()
        except Exception:  # noqa: BLE001, S112 - closing what can be closed is enough
            continue


def remove_copies() -> None:
    """Remove every copy this process made (also at exit, after an error or Ctrl-C)."""
    with _copies_lock:
        folders = [copy.parent for copy in _copies.values()]
        _copies.clear()
    if folders:
        _close_engines(folders)
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)


atexit.register(remove_copies)


@contextmanager
def _tracking(uri) -> Iterator[None]:
    """MLflow's own tracking URI set to the store read, for this read only: MLflow resolves
    where a trace's files are against it, and its default (./mlruns) is never the store the
    person chose."""
    try:
        import mlflow
    except ImportError:
        yield
        return
    before = mlflow.get_tracking_uri()
    try:
        if uri:
            mlflow.set_tracking_uri(uri)
        yield
    finally:
        mlflow.set_tracking_uri(before)


def _client(tracking_uri):
    try:
        from mlflow import MlflowClient
    except ImportError:
        raise RecordsError(NEEDS_EXTRA.format(get=get_extra("mlflow"))) from None
    return MlflowClient(tracking_uri=tracking_uri) if tracking_uri else MlflowClient()


def _experiment(client, name_or_id: str):
    from mlflow.exceptions import MlflowException

    exp = client.get_experiment_by_name(name_or_id)
    if exp is None and name_or_id.isdigit():
        try:
            exp = client.get_experiment(name_or_id)
        except MlflowException:
            exp = None
    if exp is None:
        raise RecordsError(f"no MLflow experiment named (or with id) {name_or_id!r} at the "
                           "tracking URI; set MLFLOW_TRACKING_URI or pass --tracking-uri")
    return exp


def experiments_with_traces(uri: str) -> list[str]:
    """The names of the experiments in the store at `uri` that hold at least one trace, in
    MLflow's order. Call it inside folder_store_allowed and quiet."""
    client = _client(uri)
    names = []
    for exp in client.search_experiments():
        scope = _trace_scope(client.search_traces, exp.experiment_id)
        if "include_spans" in inspect.signature(client.search_traces).parameters:
            scope["include_spans"] = False
        if len(client.search_traces(**scope, max_results=1)):
            names.append(exp.name)
    return names


def _trace_scope(search_traces, experiment_id: str) -> dict:
    """The keyword that scopes `search_traces` to one experiment, by its signature."""
    if "locations" in inspect.signature(search_traces).parameters:
        return {"locations": [experiment_id]}
    return {"experiment_ids": [experiment_id]}


def _traces(client, experiment_id: str, folder: Path | None = None,
            missing: list | None = None):
    """Every trace of an experiment, with its spans. In a folder store (`folder`), each
    trace's files are read from the store's own folder: MLflow looks for them at the full
    path saved when the trace was made, which points at another computer's folders once the
    store is copied or cloned, and then drops the trace. A trace whose files are in neither
    place is left out, its id added to `missing`."""
    scope = _trace_scope(client.search_traces, experiment_id)
    can_skip = "include_spans" in inspect.signature(client.search_traces).parameters
    local = folder is not None and can_skip
    server_only = False  # the spans are on an artifact server that isn't there
    token = None
    while True:
        extra = {"include_spans": False} if local or server_only else {}
        try:
            page = client.search_traces(**scope, max_results=PAGE_SIZE, page_token=token,
                                        **extra)
        except Exception as e:  # MLflow's own error, read for one cause only
            if server_only or not can_skip or "mlflow-artifacts" not in str(e):
                raise
            server_only = True  # read what the store itself holds (the previews)
            continue
        for trace in page:
            if local:
                page_trace_id = trace.info.trace_id
                trace = _with_spans(client, trace, folder / str(experiment_id))
                if trace is None:
                    if missing is not None:
                        missing.append(page_trace_id)
                    continue
            yield trace
        token = page.token
        if not token:
            return


TRACE_FILE = ("traces", "artifacts", "traces.json")  # inside an experiment's folder


def _with_spans(client, trace, experiment_folder: Path):
    """`trace` (found without its spans) with its spans: from the experiment's own folder,
    else where MLflow saved it; None when neither has them."""
    from mlflow.entities import Trace, TraceData

    trace_id = trace.info.trace_id
    path = experiment_folder.joinpath(TRACE_FILE[0], trace_id, *TRACE_FILE[1:])
    try:
        if path.is_file():
            return Trace(trace.info, TraceData.from_dict(json.loads(
                path.read_text(encoding="utf-8"))))
        return client.get_trace(trace_id)
    except Exception:  # noqa: BLE001 - files missing or unreadable: left out, and said
        return None


def _json(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _content(trace) -> tuple:
    """(request input, response) of a trace: the root span's, else the metadata copies."""
    data = getattr(trace, "data", None)
    request = getattr(data, "request", None) if data is not None else None
    response = getattr(data, "response", None) if data is not None else None
    meta = trace.info.trace_metadata or {}
    if request is None:
        request = meta.get(TRACE_INPUTS)
    if response is None:
        response = meta.get(TRACE_OUTPUTS)
    if request is None and response is None:  # no spans: what the store keeps of them
        request = getattr(trace.info, "request_preview", None)
        response = getattr(trace.info, "response_preview", None)
    return _json(request), _json(response)


def _root_span(trace) -> str | None:
    """The id of the trace's root span (the one with no parent), or None."""
    spans = getattr(getattr(trace, "data", None), "spans", None) or []
    return next((s.span_id for s in spans if getattr(s, "parent_id", None) is None), None)


def _item_id(trace, request, id_from: str | None) -> str | None:
    if id_from is None:
        return derive_record_id(request, None)
    tags = trace.info.tags or {}
    if id_from in tags and tags[id_from] not in (None, ""):
        return str(tags[id_from])
    if isinstance(request, dict) and request.get(id_from) not in (None, ""):
        return str(request[id_from])
    return None


def _value(feedback: dict) -> tuple:
    """(label, score, error text) from an assessment's feedback."""
    error = feedback.get("error")
    if error:
        code = error.get("error_code") if isinstance(error, dict) else None
        return None, None, str(code) if code else "error"  # never the message: it can quote data
    v = feedback.get("value")
    if isinstance(v, bool):
        return ("pass" if v else "fail"), None, None
    if isinstance(v, int | float):
        return None, float(v), None
    if isinstance(v, str):
        return v, None, None
    return None, None, None  # dict, list or None: no single verdict


def judge_instructions(meta: dict) -> str | None:
    """A make_judge's instructions in an assessment's metadata, or None. MLflow 3.16 saves
    them as `guideline` (mlflow/genai/judges/instructions_judge, so its UI shows them), some
    versions as `instructions`. A Guidelines judge's guideline is saved there too: a
    make_judge's instructions always hold a template part such as {{ outputs }}."""
    instructions = meta.get("instructions")
    if instructions is None:
        guideline = meta.get("guideline") if meta.get("guideline") is not None else meta.get(
            "guidelines")
        if isinstance(guideline, str) and "{{" in guideline:
            instructions = guideline
    if isinstance(instructions, str) and instructions.strip():
        return instructions.strip()
    return None


def _model(source_id: str | None) -> dict:
    if not source_id or source_id == "default":
        return {}
    ev = {"model": source_id}
    if ":/" in source_id:
        ev["provider"] = source_id.split(":/", 1)[0]
    return ev


def read_mlflow(experiment: str, run_ids=None, tracking_uri: str | None = None,
                id_from: str | None = None, temperature: float | None = None,
                metric: str | None = None) -> list[tuple[str, RecordList]]:
    """ScoreRecords from the traces of one MLflow experiment.

    Returns [(MLflow run id, judge records of that run)] in run start order, then
    ("human assessments", the human records): each run is one judgekeeper run. `run_ids` keeps
    only those runs' judge assessments. `metric` (--metric) may name a judge whose
    assessments are all on spans: then those are read too. A folder store is read with
    MLFLOW_ALLOW_FILE_STORE set for this read only (folder_store_allowed), said in a note.
    """
    said: list[str] = []
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
    with folder_store_allowed(uri, say=said.append), quiet(), _tracking(uri):
        try:
            files = _read_mlflow(experiment, run_ids, tracking_uri, id_from, temperature,
                                 metric, folder_of(uri))
        except Exception as e:  # never MLflow's words: they can hold the text
            if not is_damage(e):
                raise
            raise damaged_store(uri) from None
    for _, records in files:
        records.source = store_name(uri)
    files[-1][1].notes[:0] = said
    return files


def _unreadable() -> tuple[type[BaseException], ...]:
    """What reading a damaged store raises: a byte that isn't text, a database that isn't
    one; and SQLAlchemy's own errors, which wrap them."""
    import sqlite3

    found: list[type[BaseException]] = [UnicodeDecodeError, sqlite3.DatabaseError,
                                        RecursionError, OverflowError]
    try:
        from sqlalchemy.exc import DatabaseError
    except ImportError:
        pass
    else:
        found.append(DatabaseError)
    return tuple(found)


UNREADABLE = _unreadable()


def is_damage(e: BaseException | None) -> bool:
    """Whether `e`, or an error it came from, is the store's damage (UNREADABLE), MLflow's
    own error wrapping it included."""
    seen = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, UNREADABLE) or (type(e).__name__ == "MlflowException" and str(
                e).startswith(("(sqlite3.", "(sqlalchemy."))) or _in_mlflow(e):
            return True
        e = e.__cause__ or e.__context__
    return False


def _in_mlflow(e: BaseException) -> bool:
    """A value MLflow could not take from the store (a meta.yaml that lacks a field, trace
    metadata that isn't JSON): raised inside MLflow's own code while it read the store."""
    if not isinstance(e, TypeError | KeyError | ValueError | AttributeError):
        return False
    tb = e.__traceback__
    while tb is not None:
        if "mlflow" in Path(tb.tb_frame.f_code.co_filename).parts:
            return True
        tb = tb.tb_next
    return False


@contextmanager
def store_damage(uri) -> Iterator[None]:
    """Damage met while the store at `uri` is read, said as damaged_db, never in MLflow's
    words."""
    try:
        yield
    except Damaged:
        raise
    except Exception as e:
        if not is_damage(e):
            raise
        raise damaged_db(uri) from None


def store_name(uri) -> str:
    """The store at `uri` as the person knows it: mlflow.db, or the mlruns folder."""
    folder = folder_of(uri)
    if folder is not None:
        return folder.name
    return Path(str(uri).removeprefix("sqlite:///")).name if uri else "Your MLflow store"


def damaged_db(uri) -> Damaged:
    """A store that can't be opened or listed: damaged."""
    name = store_name(uri)
    return Damaged(f"{name} can't be read: it's damaged. Save it again from MLflow.",
                   f"save {name} again from MLflow (log your evaluation again), then run "
                   "`{command}`.")


def damaged_store(uri) -> Damaged:
    """A store judgekeeper can't read, in plain words: its name, never MLflow's error."""
    return Damaged(f"{store_name(uri)} is damaged: judgekeeper can't read one of its traces.",
                   "find the damaged trace with `mlflow ui` (or log your evaluation again), "
                   "then run `{command}`.")


class JudgeCallsFailed(RecordsError):
    """Every call of the experiment's judge failed: MLflow saved only errors. The errors'
    text is never said: it can hold an answer's text."""

    next_step = ("fix your LLM-as-a-judge's calls (MLflow keeps each error with its trace), run "
                 "your evaluation again, then run `{command}`.")


def _add_failed(judged: dict[str, RecordList], failed: list, wanted: list, experiment,
                code_names: set | None = None) -> None:
    """The failed calls (SCORER_ERROR) of each LLM judge, as its verdicts with no decision:
    the same judge (evaluator) as its other verdicts, the error's code as the explanation.
    A scorer that only ever failed (no verdict of its name, from a judge or from code) is
    taken for a judge whose every call failed, never dropped in silence; one that also has
    code verdicts is a code scorer. With no LLM judge verdict at all: RecordsError."""
    evaluators: dict[tuple, dict] = {}
    for run, recs in judged.items():
        for r in recs:
            evaluators.setdefault((run, r.name), r.evaluator)
            evaluators.setdefault((None, r.name), r.evaluator)
    code_names = code_names or set()
    gone = [f for f in failed if (not wanted or f[0] in wanted)
            and not (f[1]["name"] in code_names and (None, f[1]["name"]) not in evaluators)]
    if not judged and gone:
        names = sorted({str(f[1]["name"]) for f in gone})
        raise JudgeCallsFailed(
            f"MLflow experiment {experiment!r}: every call of your LLM-as-a-judge "
            f"{', '.join(names)} failed ({len(gone)} saved as errors).")
    for run, fields, error in gone:
        evaluator = evaluators.get((run, fields["name"])) or evaluators.get(
            (None, fields["name"])) or {}  # a judge that only failed: its model unknown
        judged.setdefault(run, RecordList()).append(ScoreRecord(
            annotator_kind=LLM, explanation=error, evaluator=dict(evaluator), label=None,
            score=None, metadata={}, mark=Mark(problem="error"), **fields))


class TracesMissing(RecordsError):
    """The experiment's traces are listed, but the files that hold them are not there."""


class ArtifactServer(RecordsError):
    """The traces' text lives on a tracking server (mlflow-artifacts:) that isn't running,
    and the store itself holds none of it."""

    next_step = "start that server, then run `{command}` with MLFLOW_TRACKING_URI set to it."


SERVER_ONLY = ("These MLflow traces were saved to a tracking server (mlflow-artifacts:). "
               "Their text isn't in {store}, so there is nothing to show you for marking.")


def missing_line(n: int, folder: str) -> str:
    """The note for answers left out because their trace files are missing."""
    what = "1 answer was" if n == 1 else f"{n} answers were"
    return f"{what} left out: their trace files are missing from {folder}/."


def _read_mlflow(experiment, run_ids, tracking_uri, id_from, temperature, metric,
                 folder: Path | None = None) -> list[tuple[str, RecordList]]:
    client = _client(tracking_uri)
    exp = _experiment(client, str(experiment))
    runs = {r.info.run_id: r for r in client.search_runs([exp.experiment_id])}
    wanted = list(dict.fromkeys(run_ids or []))
    unknown = [r for r in wanted if r not in runs]
    if unknown:
        raise RecordsError(f"no run {', '.join(unknown)} in MLflow experiment "
                           f"{exp.name!r}")

    judged: dict[str, RecordList] = {}
    humans = RecordList()
    failed: list[tuple[str, dict, str]] = []  # (run, record fields, error) of SCORER_ERROR
    on_spans: list[tuple[str | None, ScoreRecord]] = []  # (run, record) of span assessments
    missing_ids = 0
    n_traces = 0
    no_text = 0  # traces with neither spans nor previews: their text is elsewhere
    missing: list[str] = []
    damaged: list[str] = []  # the ids of traces left out for a damaged field
    capped = False
    for trace in _traces(client, exp.experiment_id, folder, missing):
        if n_traces >= MAX_TRACES:
            capped = True
            break
        n_traces += 1
        reading(n_traces, store_name(tracking_uri))
        sizes = (len(humans), len(failed), len(on_spans),
                 {run: len(recs) for run, recs in judged.items()})
        try:
            request, response = _content(trace)
            if request is None and response is None:
                no_text += 1
                continue
            item_id = _item_id(trace, request, id_from)
            if item_id is None:
                missing_ids += 1
                continue
            trace_run = (trace.info.trace_metadata or {}).get(TRACE_SOURCE_RUN)
            root = _root_span(trace)
            # no spans at all (their files are on a server): every assessment is on the answer
            no_spans = not (getattr(getattr(trace, "data", None), "spans", None) or [])
            for a in trace.info.assessments or []:
                d = a.to_dictionary()
                feedback = d.get("feedback")
                source = d.get("source") or {}
                kind = KINDS.get(str(source.get("source_type")).upper())
                if feedback is None or kind is None:
                    continue
                label, score, error = _value(feedback)
                meta = d.get("metadata") or {}
                span = d.get("span_id")
                if kind == CODE and (feedback.get("error") or {}).get("error_code") == SCORER_ERROR:
                    run = meta.get(SOURCE_RUN_ID) or trace_run or NO_RUN
                    if not span or span == root:
                        failed.append((run, {
                            "target_id": item_id, "name": d.get("assessment_name"),
                            "input": request, "output": response,
                            "created_at": d.get("create_time")}, error))
                    continue
                common = {"target_id": item_id, "name": d.get("assessment_name"),
                          "label": label, "score": score, "input": request, "output": response,
                          "created_at": d.get("create_time"),
                          "metadata": {"span_id": span} if span else {}}
                if span == root or no_spans:
                    span = None  # on the root span: a verdict on the whole answer
                if kind == HUMAN and d.get("valid") is False:
                    continue  # overridden by a later human assessment
                if kind in (CODE, HUMAN):
                    record = ScoreRecord(annotator_kind=kind, **common)
                    if span:
                        on_spans.append((None, record))
                    else:
                        humans.append(record)
                    continue
                run = meta.get(SOURCE_RUN_ID) or trace_run or NO_RUN
                if wanted and run not in wanted:
                    continue
                evaluator = _model(source.get("source_id"))
                instructions = judge_instructions(meta)
                if instructions:
                    evaluator["rule"] = instructions
                if meta.get(SCORER_NAME) or meta.get(SCORER_VERSION):
                    evaluator["version"] = "@".join(
                        str(x) for x in (meta.get(SCORER_NAME), meta.get(SCORER_VERSION)) if x)
                if temperature is not None:
                    evaluator["temperature"] = temperature
                explanation = error or d.get("rationale") or None
                record = ScoreRecord(annotator_kind=LLM, explanation=explanation,
                                     evaluator=evaluator, **common,
                                     mark=Mark(problem="error") if error else NO_MARK)
                if span:
                    on_spans.append((run, record))
                else:
                    judged.setdefault(run, RecordList()).append(record)

            for r in [*humans[sizes[0]:], *(r for _, r in on_spans[sizes[2]:]),
                      *(r for run, recs in judged.items() for r in recs[sizes[3].get(run, 0):])]:
                check_record(r)
        except Exception:  # noqa: BLE001 - MLflow's own errors on one damaged trace too:
            # this trace is left out, the others are read
            del humans[sizes[0]:], failed[sizes[1]:], on_spans[sizes[2]:]
            for run in list(judged):
                del judged[run][sizes[3].get(run, 0):]
                if not judged[run]:
                    del judged[run]
            damaged.append(str(getattr(trace.info, "trace_id", n_traces)))

    if n_traces == 0 and missing:
        where = f"{folder.name}/" if folder is not None else "the store"
        raise TracesMissing(
            f"MLflow experiment {exp.name!r} in {where}: the files of its {len(missing)} "
            f"traces are missing (MLflow keeps each trace's question and answer in "
            f"{where}{exp.experiment_id}/traces/), so there is nothing to read. Run your "
            "evaluation again on this computer, or point judgekeeper at a store that has them.")
    if n_traces == 0:
        raise RecordsError(f"MLflow experiment {exp.name!r} has no traces")
    _add_failed(judged, failed, wanted, exp.name,
                code_names={r.name for r in humans if r.annotator_kind == CODE})
    if no_text and no_text == n_traces:
        raise ArtifactServer(SERVER_ONLY.format(store=store_name(tracking_uri)))
    on_traces = {r.name for recs in judged.values() for r in recs}
    left_out = 0
    for run, record in on_spans:
        if metric is None or record.name != metric or metric in on_traces:
            left_out += 1
        elif run is None:
            humans.append(record)
        else:
            judged.setdefault(run, RecordList()).append(record)
    if id_from is not None and missing_ids:
        raise RecordsError(f"--id-from {id_from}: {missing_ids} of {n_traces} traces have no "
                           f"tag or request input key {id_from!r}")

    def start(run_id):
        r = runs.get(run_id)
        return (r is None, r.info.start_time if r else 0, run_id)

    files = []
    shown = []
    for n, run_id in enumerate(sorted(judged, key=start), 1):
        recs = judged[run_id]
        for r in recs:
            r.run = n
        recs.ids_derived = id_from is None
        name = runs[run_id].info.run_name if run_id in runs else None
        shown.append(f"{n} = {run_id}" + (f" ({name})" if name else ""))
        files.append((run_id, recs))
    humans.ids_derived = id_from is None
    code_counts = Counter(r.name for r in humans if r.annotator_kind == CODE)
    if code_counts:
        n = sum(code_counts.values())
        humans.notes.append(f"{n} {'assessment' if n == 1 else 'assessments'} from code scorers "
                            f"({', '.join(sorted(map(str, code_counts)))}) are rules in code, not "
                            "an LLM-as-a-judge: left out.")
    humans.notes.append(f"Runs are MLflow runs in start order: {', '.join(shown)}.")
    if NO_RUN in judged:
        humans.notes.append("Some LLM-as-a-judge assessments carry no MLflow run id (logged by "
                            "hand, outside an evaluate run): they form one run, listed last.")
    if not any(r.evaluator.get("rule") for recs in judged.values() for r in recs):
        humans.notes.append("MLflow does not save the LLM-as-a-judge's prompt with its "
                            "assessments: prompt hash unknown.")
    if left_out:
        what = "assessment" if left_out == 1 else "assessments"
        humans.notes.append(f"{left_out} span-level {what} (on one step inside a trace, not "
                            "on the answer) left out. To check an LLM-as-a-judge that is only on "
                            "spans, name it with --metric.")
    if missing:
        humans.notes.append(missing_line(len(missing), folder.name if folder else "the store"))
    if capped:
        humans.notes.append(CAPPED.format(experiment=exp.name, n=MAX_TRACES))
    if files and damaged:
        files[0][1].left_out, files[0][1].unit = damaged, "trace"
    files.append(("human assessments", humans))
    return files
