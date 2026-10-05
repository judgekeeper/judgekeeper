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
"""

from __future__ import annotations

import re

from judgekeeper import again, keys, prices
from judgekeeper.again import CANT, CLOSE, EXACT, Plan, cant
from judgekeeper.start_label import display

WORKER_ENV = {"MLFLOW_DISABLE_TELEMETRY": "true"}
TRACE_CALLS = 30
SCORER_NAME = "mlflow.assessment.scorerName"
SCORER_VERSION = "mlflow.assessment.scorerVersion"


def _version(text: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def classify(info: dict, worker: dict) -> tuple[str, str]:
    """(status, why) for an MLflow judge, from one of its assessments (`info`) and what the
    worker found in the user's Python."""
    source = info.get("source_id") or ""
    if source == "databricks" or source.startswith("endpoints:/"):
        return CANT, ("your judge runs on Databricks. Run judgekeeper inside your Databricks "
                      "workspace")
    name = info.get("scorer_name") or info.get("name")
    if info.get("scorer_name") and worker.get("registered"):
        if info.get("scorer_version"):
            return EXACT, (f"MLflow calls your registered judge {name}, version "
                           f"{info['scorer_version']}")
        return CLOSE, ("no version was saved with your assessments, so the latest registered "
                       "version is used")
    if info.get("name") == "guidelines":
        n = info.get("guidelines")
        if n == 1:
            return EXACT, "MLflow's built-in Guidelines judge with your one guideline"
        if n:
            return CANT, ("your Guidelines judge has several guidelines, which MLflow saves as "
                          "one text")
        return CANT, "your Guidelines judge's guidelines were not saved"
    if worker.get("builtin"):
        return EXACT, (f"MLflow's built-in {info.get('name')} judge with the model saved with "
                       "your assessments")
    if info.get("instructions"):
        if _version(worker.get("version")) >= (3, 14):
            return CLOSE, ("an unregistered make_judge: its instructions and model are saved; "
                           "its output type and temperature are not saved")
        return CANT, "a make_judge from MLflow before 3.14 does not save its instructions"
    return CANT, "your judge is a custom scorer, which runs your own code"


def assessment_info(ws, metric: str) -> dict:
    """One judge assessment named `metric` from the project's MLflow store, read-only:
    {source_id, name, scorer_name, scorer_version, guidelines, instructions, trace}."""
    from mlflow import MlflowClient

    from judgekeeper import find
    from judgekeeper.readers.mlflow_store import _trace_scope

    store = next(iter(find.search(ws.root).readable("mlflow")))
    uri = (str(store.path) if store.path.is_dir() else
           f"sqlite:///file:{store.path.as_posix()}?mode=ro&uri=true")
    client = MlflowClient(tracking_uri=uri)
    for exp in client.search_experiments():
        scope = _trace_scope(client.search_traces, exp.experiment_id)
        for trace in client.search_traces(**scope, max_results=100):
            for a in trace.info.assessments or []:
                d = a.to_dictionary()
                source = d.get("source") or {}
                if d.get("assessment_name") != metric or source.get("source_type") not in (
                        "LLM_JUDGE", "AI_JUDGE"):
                    continue
                meta = d.get("metadata") or {}
                guideline = meta.get("guideline") or meta.get("guidelines")
                instructions = meta.get("instructions")
                return {"source_id": source.get("source_id"), "name": metric,
                        "scorer_name": meta.get(SCORER_NAME),
                        "scorer_version": meta.get(SCORER_VERSION),
                        "guidelines": (len(guideline) if isinstance(guideline, list)
                                       else 1 if guideline else None),
                        "instructions": bool(instructions),
                        "trace": "{{ trace }}" in str(instructions or "")}
    raise ValueError(f"no judge assessment named {metric} in your MLflow store")


def plan(ws, answers: list[dict], opts, talk, dry: bool) -> Plan:
    data = ws.data()
    root, metric, judge = ws.root, data["metric"], data["judge"]
    try:
        info = assessment_info(ws, metric)
    except ImportError:
        return cant("mlflow", judge, 'reading MLflow needs pip install "judgekeeper[mlflow]"',
                    short="the mlflow extra is not installed")
    python = again.user_python(root, opts.python)
    worker = {}
    if dry:
        worker = again.run_worker("mlflow", python, {
            "mode": "dry", "name": info.get("scorer_name") or info.get("name"),
            "version": info.get("scorer_version")}, root, env=WORKER_ENV)
        if not worker.get("ok"):
            if worker.get("missing"):
                return cant("mlflow", judge, f"MLflow is not installed in {python}. Use "
                            "--python to point at the Python you run your evals with",
                            short="MLflow is not installed here")
            return cant("mlflow", judge, f"MLflow could not load your judge in {python}: "
                        f"{worker.get('error')}", short="MLflow could not load your judge")
    status, why = classify(info, worker)
    if status == CANT:
        return cant("mlflow", judge, why, short=why.split(".")[0].split(",")[0])
    version = worker.get("version")
    if status == EXACT:
        confirmed = bool(version) and talk is not None and talk.ask_yes(
            f"Is MLflow {version} the version you ran your eval with?")
        if not confirmed:
            status, why = CLOSE, f"{why}; the MLflow version was not confirmed"
    model = info.get("source_id")
    calls = TRACE_CALLS if info.get("trace") else 1
    check = keys.check(model, "mlflow", root)
    tokens = []
    for a in answers:
        i, o = prices.tokens_from_text(f"{display(a['input'])}\n{display(a['output'])}")
        tokens.append((i * calls, o * calls))
    return Plan(tool="mlflow", judge=f"{judge} (MLflow {version})" if version else judge,
                status=status, why=why, model=model, provider=check.provider,
                key_lines=check.lines, calls_each=[calls] * len(answers),
                calls_note="up to" if info.get("trace") else "", tokens=tokens,
                settings=check.settings,
                side_effects=[(f"Your app is not run. MLflow calls your judge directly in "
                               f"your Python ({python}); never mlflow.genai.evaluate(), so "
                               "nothing is added to your MLflow store.")])
