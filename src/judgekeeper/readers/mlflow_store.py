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
- `source_type` LLM_JUDGE is the judge, HUMAN the human, CODE ignored. Only feedback counts;
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
  The judge's prompt is not saved with the assessment, and scorer tracing is off by default,
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
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    derive_record_id,
)

NEEDS_EXTRA = ("reading MLflow needs mlflow. Install the extra "
               "(pip install \"judgekeeper[mlflow]\").")
KINDS = {"LLM_JUDGE": LLM, "AI_JUDGE": LLM, "HUMAN": HUMAN, "CODE": CODE}
SOURCE_RUN_ID = "mlflow.assessment.sourceRunId"
SCORER_NAME = "mlflow.assessment.scorerName"
SCORER_VERSION = "mlflow.assessment.scorerVersion"
TRACE_SOURCE_RUN = "mlflow.sourceRun"
TRACE_INPUTS = "mlflow.traceInputs"
TRACE_OUTPUTS = "mlflow.traceOutputs"
PAGE_SIZE = 100
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
    MLFLOW_DISABLE_AGENT_HINT=1, and its loggers show errors only (it warns once per trace it
    cannot download, for example). Both are put back afterwards, also after an error; a
    value the user set is left as it is. Never for the user's shell, never in a file."""
    set_hint = HINT not in os.environ
    if set_hint:
        os.environ[HINT] = "1"
    try:
        import mlflow  # noqa: F401 - MLflow sets its loggers' level on import
    except ImportError:
        pass
    logger = logging.getLogger("mlflow")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
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


def _client(tracking_uri):
    try:
        from mlflow import MlflowClient
    except ImportError:
        raise RecordsError(NEEDS_EXTRA) from None
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
    local = folder is not None and "include_spans" in inspect.signature(
        client.search_traces).parameters
    token = None
    while True:
        extra = {"include_spans": False} if local else {}
        page = client.search_traces(**scope, max_results=PAGE_SIZE, page_token=token, **extra)
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
        code, message = error.get("error_code"), error.get("error_message")
        return None, None, ": ".join(str(x) for x in (code, message) if x) or "error"
    v = feedback.get("value")
    if isinstance(v, bool):
        return ("pass" if v else "fail"), None, None
    if isinstance(v, int | float):
        return None, float(v), None
    if isinstance(v, str):
        return v, None, None
    return None, None, None  # dict, list or None: no single verdict


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
    with folder_store_allowed(uri, say=said.append), quiet():
        files = _read_mlflow(experiment, run_ids, tracking_uri, id_from, temperature, metric,
                             folder_of(uri))
    files[-1][1].notes[:0] = said
    return files


class TracesMissing(RecordsError):
    """The experiment's traces are listed, but the files that hold them are not there."""


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
    on_spans: list[tuple[str | None, ScoreRecord]] = []  # (run, record) of span assessments
    missing_ids = 0
    n_traces = 0
    missing: list[str] = []
    for trace in _traces(client, exp.experiment_id, folder, missing):
        n_traces += 1
        request, response = _content(trace)
        item_id = _item_id(trace, request, id_from)
        if item_id is None:
            missing_ids += 1
            continue
        trace_run = (trace.info.trace_metadata or {}).get(TRACE_SOURCE_RUN)
        root = _root_span(trace)
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
            common = {"target_id": item_id, "name": d.get("assessment_name"),
                      "label": label, "score": score, "input": request, "output": response,
                      "created_at": d.get("create_time"),
                      "metadata": {"span_id": span} if span else {}}
            if span == root:
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

    if n_traces == 0 and missing:
        where = f"{folder.name}/" if folder is not None else "the store"
        raise TracesMissing(
            f"MLflow experiment {exp.name!r} in {where}: the files of its {len(missing)} "
            f"traces are missing (MLflow keeps each trace's question and answer in "
            f"{where}{exp.experiment_id}/traces/), so there is nothing to read. Run your "
            "evaluation again on this computer, or point judgekeeper at a store that has them.")
    if n_traces == 0:
        raise RecordsError(f"MLflow experiment {exp.name!r} has no traces")
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
    humans.notes.append(f"Runs are MLflow runs in start order: {', '.join(shown)}.")
    if NO_RUN in judged:
        humans.notes.append("Some judge assessments carry no MLflow run id (logged outside "
                            "mlflow.genai.evaluate): they form one run, listed last.")
    humans.notes.append("MLflow does not save the judge's prompt with its assessments: prompt "
                        "hash unknown.")
    if left_out:
        what = "assessment" if left_out == 1 else "assessments"
        humans.notes.append(f"{left_out} span-level {what} (on one step inside a trace, not "
                            "on the answer) left out. To check a judge that is only on spans, "
                            "name it with --metric.")
    if missing:
        humans.notes.append(missing_line(len(missing), folder.name if folder else "the store"))
    files.append(("human assessments", humans))
    return files
