"""The plan for asking an MLflow judge again.

A worker (`workers/mlflow_worker.py`) gets the user's judge back in the user's own Python and
calls it directly, `judge(inputs=..., outputs=..., expectations=...)`, never
`mlflow.genai.evaluate()`, which would add a run and assessments to the user's store. The
worker runs with MLflow's telemetry off.

- Exactly your judge: a registered judge with its version saved in the assessment; a built-in
  judge (its model is in the assessment's `source_id`); `Guidelines` with one guideline. Each
  only with the MLflow version the user ran with, which the store does not record, so it is
  asked at a terminal; otherwise a close copy.
- Close copy: a registered judge with no version saved (the latest version is used); an
  unregistered `make_judge` (MLflow 3.14 or later), whose output type and temperature are not
  saved.
- Can't: a custom `@scorer`, `make_judge` before 3.14, `Guidelines` with several guidelines,
  and Databricks judges ("Run judgekeeper inside your Databricks workspace").

A judge that reads the whole trace (`{{ trace }}`) makes up to 30 calls per answer. MLflow's
Python API loads no `.env`: the key must be in the shell.

In run mode (`run`, after the yes) the worker gets the judge back (`get_scorer` for a
registered judge, the built-in class, `Guidelines`, or `make_judge` with the saved
instructions) and, once per time asked, calls it on each labeled answer's saved inputs and
outputs, with the expectations saved on its trace (read-only); a judge that reads the whole
trace is given the trace. Each answer's trace comes from the store the check was made from,
opened read-only; an answer whose trace is no longer there is left out.
"""

from __future__ import annotations

import os
import re

from judgekeeper import again, keys, prices
from judgekeeper.again import (
    CANT,
    CLOSE,
    EXACT,
    Plan,
    cant,
    left_out_line,
    not_marked,
    worker_run,
)
from judgekeeper.again.fresh import Fresh
from judgekeeper.normalise import Normaliser, UnmappedValue
from judgekeeper.start_label import display
from judgekeeper.table import make_fingerprint
from judgekeeper.textio import get_extra

WORKER_ENV = {"MLFLOW_DISABLE_TELEMETRY": "true", "MLFLOW_DISABLE_AGENT_HINT": "1"}


def worker_env(uri) -> dict:
    """The worker's extra environment: for a folder store (mlruns/), MLflow's folder-store
    setting too, in the worker's environment only, unless the user set it themselves (then
    the worker inherits their value)."""
    from judgekeeper.readers.mlflow_store import ALLOW, is_folder_store

    if is_folder_store(uri) and ALLOW not in os.environ:
        return {**WORKER_ENV, ALLOW: "true"}
    return WORKER_ENV
TRACE_CALLS = 30
SCORER_NAME = "mlflow.assessment.scorerName"
SCORER_VERSION = "mlflow.assessment.scorerVersion"
TRACE = re.compile(r"\{\{\s*trace\s*\}\}")


def _version(text: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def here(info: dict, instructions: str | None) -> dict:
    """What the dry worker would say about the judge's version and built-in judges, from the
    MLflow in judgekeeper's own Python (usually the same): {} without it. Never whether it is
    registered, which needs the store. For the menu's quick plan, which starts no worker, so
    its line says what the plan will."""
    from judgekeeper.readers.mlflow_store import quiet

    with quiet():
        try:
            import mlflow
            from mlflow.genai import scorers
        except ImportError:
            return {}
        builtin = is_builtin(scorers, info.get("name"), instructions)
    return {"version": getattr(mlflow, "__version__", None), "builtin": builtin}


def is_builtin(scorers, name, instructions=None) -> bool:
    """The worker's is_builtin (workers/mlflow_worker.py, which runs on its own): one of
    MLflow's built-in judges has this name and, when instructions were saved, they are its
    own."""
    cls = getattr(scorers, "".join(part.capitalize() for part in str(name).split("_")), None)
    if not isinstance(cls, type):
        return False
    if not instructions:
        return True
    try:
        own = cls().instructions
    except Exception:  # noqa: BLE001 - no instructions of its own: not this judge
        return False
    return isinstance(own, str) and own.strip() == str(instructions).strip()


def classify(info: dict, worker: dict) -> tuple[str, str]:
    """(status, why) for an MLflow judge, from one of its assessments (`info`) and what the
    worker found in the user's Python."""
    source = info.get("source_id") or ""
    if source == "databricks" or source.startswith("endpoints:/"):
        return CANT, ("your LLM-as-a-judge runs on Databricks. Run judgekeeper inside your "
                      "Databricks workspace")
    name = info.get("scorer_name") or info.get("name")
    if info.get("scorer_name") and worker.get("registered"):
        if info.get("scorer_version"):
            return EXACT, (f"MLflow calls your registered LLM-as-a-judge {name}, version "
                           f"{info['scorer_version']}")
        return CLOSE, ("no version was saved with your assessments, so the latest registered "
                       "version is used")
    if info.get("name") == "guidelines":
        n = info.get("guidelines")
        if n == 1:
            return EXACT, "MLflow's built-in Guidelines LLM-as-a-judge with your one guideline"
        if n:
            return CANT, ("your Guidelines LLM-as-a-judge has several guidelines, which MLflow "
                          "saves as one text")
        return CANT, "your Guidelines LLM-as-a-judge's guidelines were not saved"
    if worker.get("builtin"):
        return EXACT, (f"MLflow's built-in {info.get('name')} LLM-as-a-judge with the model saved "
                       "with your assessments")
    if info.get("instructions"):
        if worker.get("version") is None or _version(worker.get("version")) >= (3, 14):
            return CLOSE, ("an unregistered make_judge: its instructions and model are saved; "
                           "its output type and temperature are not saved")
        return CANT, "a make_judge from MLflow before 3.14 does not save its instructions"
    return CANT, "your LLM-as-a-judge is a custom scorer, which runs your own code"


def judge_meta(meta: dict) -> dict:
    """What a judge assessment's metadata says about its judge: {guidelines (how many),
    instructions (a make_judge's, whose text holds template variables such as
    {{ outputs }}), trace (the instructions read the whole trace), text}. MLflow saves a
    list of guidelines joined by line breaks, so each line is one guideline."""
    from judgekeeper.readers.mlflow_store import judge_instructions

    guideline = meta.get("guideline") if meta.get("guideline") is not None else meta.get(
        "guidelines")
    instructions = judge_instructions(meta)
    if instructions is not None and meta.get("instructions") is None:  # saved as `guideline`
        guideline = None
    count, text = None, None
    if isinstance(guideline, list) and guideline:
        count, text = len(guideline), guideline[0] if len(guideline) == 1 else None
    elif isinstance(guideline, str) and guideline:
        count, text = len(guideline.splitlines()), guideline
    if instructions:
        text = str(instructions)
    return {"guidelines": count, "instructions": bool(instructions),
            "trace": bool(TRACE.search(str(instructions or ""))), "text": text}


def assessment_info(ws, metric: str, run: str | None = None) -> dict:
    """The judge named `metric` in the project's MLflow store, read-only: one of its
    assessments {source_id, name, scorer_name, scorer_version, guidelines, instructions,
    trace, text, experiment}, the `uri` of a temporary copy of the store (or of the mlruns/
    folder), `traces`: {answer id: trace id} for every trace that holds one of its
    assessments (answer ids as `start` makes them), and `all_traces`: the same for every
    trace. `run` (an MLflow run id) takes the assessment from that run, the newest results of
    a new judge."""
    from judgekeeper import find
    from judgekeeper.readers.mlflow_store import (
        NO_RUN,
        SOURCE_RUN_ID,
        TRACE_SOURCE_RUN,
        _content,
        _traces,
        folder_of,
        folder_store_allowed,
        quiet,
        store_uri,
    )
    from judgekeeper.records import derive_record_id

    saved = ws.data().get("mlflow_store") if ws.start.is_file() else None
    if saved and (ws.root / saved).exists():  # the store the check was made from
        path = ws.root / saved
    else:
        path = next(iter(find.search(ws.root).readable("mlflow"))).path
    uri = store_uri(path)  # a temporary copy of mlflow.db, kept for the worker
    with folder_store_allowed(uri), quiet():  # mlruns/: the folder-store setting, this read
        from mlflow import MlflowClient

        client = MlflowClient(tracking_uri=uri)
        info, traces, every = None, {}, {}
        for exp in client.search_experiments():
            for trace in _traces(client, exp.experiment_id, folder_of(uri)):
                key = derive_record_id(*_content(trace))
                every.setdefault(key, trace.info.trace_id)
                trace_run = (trace.info.trace_metadata or {}).get(TRACE_SOURCE_RUN)
                for a in trace.info.assessments or []:
                    d = a.to_dictionary()
                    source = d.get("source") or {}
                    if d.get("assessment_name") != metric or source.get("source_type") not in (
                            "LLM_JUDGE", "AI_JUDGE"):
                        continue
                    meta = d.get("metadata") or {}
                    if run not in (None, NO_RUN) and (meta.get(SOURCE_RUN_ID) or trace_run) != run:
                        continue
                    traces.setdefault(key, trace.info.trace_id)
                    if info is None:
                        info = {"source_id": source.get("source_id"), "name": metric,
                                "scorer_name": meta.get(SCORER_NAME),
                                "scorer_version": meta.get(SCORER_VERSION),
                                "experiment": exp.experiment_id, **judge_meta(meta)}
    if info is None:
        raise ValueError(f"no LLM-as-a-judge assessment named {metric} in your MLflow store")
    return {**info, "uri": uri, "traces": traces, "all_traces": every}


def judge_job(info: dict, worker: dict) -> dict:
    """How the worker gets the judge back, as `classify` sorted it."""
    base = {"name": info.get("scorer_name") or info.get("name"),
            "model": info.get("source_id"), "trace": bool(info.get("trace"))}
    if info.get("scorer_name") and worker.get("registered"):
        return {**base, "kind": "registered", "version": info.get("scorer_version"),
                "experiment": info.get("experiment")}
    if info.get("name") == "guidelines":
        return {**base, "kind": "guidelines", "text": info.get("text")}
    if worker.get("builtin"):
        return {**base, "kind": "builtin"}
    return {**base, "kind": "make_judge", "text": info.get("text")}


NEEDS_TRACE = (("its trace is not in your MLflow store, and your LLM-as-a-judge reads the whole "
                "trace"),
               ("their traces are not in your MLflow store, and your LLM-as-a-judge reads the "
                "whole trace"))


def plan(ws, answers: list[dict], opts, talk, dry: bool, new: bool = False) -> Plan:
    data = ws.data()
    root, metric, judge = ws.root, data["metric"], data["judge"]
    try:
        info = (assessment_info(ws, metric, run=data["results_files"][0]) if new
                else assessment_info(ws, metric))
    except ImportError:
        return cant("mlflow", judge, f"reading MLflow needs mlflow: {get_extra('mlflow')}",
                    short="the mlflow extra is not installed")
    python = again.user_python(root, opts.python)
    saved = info.get("text") if info.get("instructions") else None
    worker = {}
    if not dry:  # the menu's quick plan starts no worker
        worker = here(info, saved)
    else:
        worker = again.run_worker("mlflow", python, {
            "mode": "dry", "name": info.get("scorer_name") or info.get("name"),
            "version": info.get("scorer_version"), "uri": info.get("uri"),
            "experiment": info.get("experiment"), "instructions": saved}, root,
            env=worker_env(info.get("uri")))
        if not worker.get("ok"):
            if worker.get("missing"):
                return cant("mlflow", judge, f"MLflow is not installed in {again.python_name(python)}. Activate "
                            "the virtual environment you run your evals with, then try again",
                            short="MLflow is not installed here")
            return cant("mlflow", judge, "MLflow could not load your LLM-as-a-judge in "
                                         f"{again.python_name(python)}: {worker.get('error')}",
                        short="MLflow could not load your LLM-as-a-judge")
    status, why = classify(info, worker)
    if status == CANT:
        return cant("mlflow", judge, why, short=re.split(r"[.,](?:\s|$)", why)[0])
    job = judge_job(info, worker)
    if opts.rule is not None:
        if job["kind"] not in ("guidelines", "make_judge"):
            return cant("mlflow", judge, again.NO_SWAP.format(
                what="an MLflow LLM-as-a-judge that is registered or built in"), short="no rule to "
                                                                                       "swap")
        job = {**job, "text": opts.rule}
    version = worker.get("version")
    if status == EXACT:
        confirmed = dry and bool(version) and talk is not None and talk.ask_yes(
            f"Is MLflow {version} the version you ran your eval with?")
        if not confirmed:
            status, why = CLOSE, f"{why}; the MLflow version was not confirmed"
    model = info.get("source_id")
    calls = TRACE_CALLS if info.get("trace") else 1
    check = keys.check(model, "mlflow", root)
    if new:  # a new judge never graded these answers: their traces, where still kept
        traces = info.get("all_traces") or {}
        found = [a for a in answers if a["id"] in traces or not info.get("trace")]
    else:
        traces = info.get("traces") or {}
        found = [a for a in answers if a["id"] in traces]
    if not found:
        return not_marked("mlflow", judge)
    tokens = []
    for a in found:
        i, o = prices.tokens_from_text(f"{display(a['input'])}\n{display(a['output'])}")
        tokens.append((i * calls, o * calls))
    left = []
    if len(found) < len(answers):
        left.append(left_out_line(len(answers) - len(found), *(
            NEEDS_TRACE if new else ("it is not in your MLflow store any more",
                                     "they are not in your MLflow store any more"))))
    payload = [(a, {"id": a["id"], "trace": traces.get(a["id"]), "inputs": a["input"],
                    "outputs": a["output"]}) for a in found]
    return Plan(tool="mlflow", judge=f"{judge} (MLflow {version})" if version else judge,
                status=status, why=why, model=model, provider=check.provider,
                key_lines=check.lines, calls_each=[calls] * len(found),
                calls_note="up to" if info.get("trace") else "", tokens=tokens,
                settings=check.settings, key_ok=check.ok, key_step=check.step,
                tool_version=version, left_out=left, runner=[python], payload=payload,
                job={"uri": info.get("uri"), "judge": job},
                side_effects=[("Your eval's code is not run. MLflow calls your LLM-as-a-judge "
                               f"directly in {again.your_python(python)}; never "
                               "mlflow.genai.evaluate(), so nothing is added to your MLflow "
                               "store.")])


def run(ws, plan: Plan, talk) -> Fresh:
    """Call the user's MLflow judge on each labeled answer, `plan.times` times."""
    from judgekeeper.readers.mlflow_store import _model

    norm = Normaliser()

    def verdict(item, line):
        try:
            return norm(line.get("value")).verdict
        except UnmappedValue:
            return None

    fresh, got, done = worker_run.ask(ws, plan, talk, "MLflow",
                                      env=worker_env(plan.job.get("uri")))
    worker_run.count(fresh, plan, got, "MLflow", verdict)
    judge = plan.job["judge"]
    evaluator = _model(judge.get("model"))
    if judge["kind"] == "registered":
        evaluator["rubric_version"] = "@".join(
            str(x) for x in (judge["name"], judge.get("version")) if x)
    fresh.fingerprint = make_fingerprint(evaluator).to_dict()
    plan.tool_version = done.get("version") or plan.tool_version
    return fresh
