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
  expectations (ground truth) are not verdicts.
- `mlflow.override_feedback` marks the judge's assessment `valid: false` and logs the human's
  with `overrides` = its id: the overridden value is still the judge's verdict. A human
  assessment that is itself overridden (`valid: false`) is dropped.
- Each judge assessment's run is its `mlflow.assessment.sourceRunId` metadata (set by
  `mlflow.genai.evaluate`, also when it scores existing traces), else the trace's
  `mlflow.sourceRun`. Runs are ordered by start time.
- Trace ids change on every evaluation run, so the item id is derived from the trace's request
  input (`table.derive_id`), unless `id_from` names a trace tag or request input key.
- Fingerprint: model from `source.source_id` (`openai:/gpt-4.1-mini` gives provider
  `openai`); `mlflow.assessment.scorerName`/`scorerVersion` metadata as the rubric version.
  The prompt lives in the scorer's own trace, which this reader does not fetch: prompt unknown.
"""

from __future__ import annotations

import inspect
import json
import os

from judgekeeper.records import (
    CODE,
    HUMAN,
    LLM,
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


def _client(tracking_uri):
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
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


def _trace_scope(search_traces, experiment_id: str) -> dict:
    """The keyword that scopes `search_traces` to one experiment, by its signature."""
    if "locations" in inspect.signature(search_traces).parameters:
        return {"locations": [experiment_id]}
    return {"experiment_ids": [experiment_id]}


def _traces(client, experiment_id: str):
    scope = _trace_scope(client.search_traces, experiment_id)
    token = None
    while True:
        page = client.search_traces(**scope, max_results=PAGE_SIZE, page_token=token)
        yield from page
        token = page.token
        if not token:
            return


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
                id_from: str | None = None, temperature: float | None = None
                ) -> list[tuple[str, RecordList]]:
    """ScoreRecords from the traces of one MLflow experiment.

    Returns [(MLflow run id, judge records of that run)] in run start order, then
    ("human assessments", the human records): each run is one judgekeeper run. `run_ids` keeps
    only those runs' judge assessments.
    """
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
    missing_ids = 0
    n_traces = 0
    for trace in _traces(client, exp.experiment_id):
        n_traces += 1
        request, response = _content(trace)
        item_id = _item_id(trace, request, id_from)
        if item_id is None:
            missing_ids += 1
            continue
        trace_run = (trace.info.trace_metadata or {}).get(TRACE_SOURCE_RUN)
        for a in trace.info.assessments or []:
            d = a.to_dictionary()
            feedback = d.get("feedback")
            source = d.get("source") or {}
            kind = KINDS.get(str(source.get("source_type")).upper())
            if feedback is None or kind is None:
                continue
            label, score, error = _value(feedback)
            meta = d.get("metadata") or {}
            common = {"target_id": item_id, "name": d.get("assessment_name"),
                      "label": label, "score": score, "input": request, "output": response,
                      "created_at": d.get("create_time")}
            if kind == CODE:
                humans.append(ScoreRecord(annotator_kind=CODE, **common))
                continue
            if kind == HUMAN:
                if d.get("valid") is False:
                    continue  # overridden by a later human assessment
                humans.append(ScoreRecord(annotator_kind=HUMAN, **common))
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
            judged.setdefault(run, RecordList()).append(ScoreRecord(
                annotator_kind=LLM, explanation=explanation, evaluator=evaluator, **common))

    if n_traces == 0:
        raise RecordsError(f"MLflow experiment {exp.name!r} has no traces")
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
    humans.notes.append("MLflow keeps the judge's prompt in the scorer's own trace, which "
                        "this import does not read: prompt hash unknown.")
    files.append(("human assessments", humans))
    return files
