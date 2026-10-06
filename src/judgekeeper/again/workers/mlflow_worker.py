"""judgekeeper's MLflow worker, run with the user's own Python in the project folder:

    python mlflow_worker.py job.json out.jsonl

Standard library plus the user's installed MLflow. Mode "dry" writes MLflow's version, whether
the job's judge is registered (`get_scorer`) and whether it is one of MLflow's built-in judges.
No judge is called and nothing is written to the store. Mode "run" gets the judge back and
calls it directly, `judge(inputs=..., outputs=..., expectations=...)` (or `judge(trace=...)`
for a judge that reads the whole trace), once per answer per time, and writes one line each:
the Feedback's value and rationale, or its error. The traces are only read
(`MlflowClient.get_trace`, on the read-only store address judgekeeper gives).
`mlflow.genai.evaluate()` is never called in any mode: it would add a run and assessments to
the user's store. MLflow's telemetry is off.
"""

import inspect
import json
import os
import sys

os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"


def emit(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def class_name(name):
    return "".join(part.capitalize() for part in str(name).split("_"))


def plain(value):
    return value if isinstance(value, (str, bool, int, float)) or value is None else str(value)


def build(judge, scorers):
    model = judge.get("model") if judge.get("model") not in (None, "default") else None
    if judge["kind"] == "registered":
        kwargs = {"name": judge["name"], "experiment_id": judge.get("experiment")}
        if judge.get("version"):
            kwargs["version"] = int(judge["version"])
        return scorers.get_scorer(**kwargs)
    if judge["kind"] == "guidelines":
        return scorers.Guidelines(guidelines=judge["text"], model=model)
    if judge["kind"] == "builtin":
        return getattr(scorers, class_name(judge["name"]))(model=model)
    from mlflow.genai.judges import make_judge

    return make_judge(name=judge["name"], instructions=judge["text"], model=model)


def expectations(trace):
    found = {}
    for a in trace.info.assessments or []:
        d = a.to_dictionary()
        if d.get("expectation") is not None and d.get("valid") is not False:
            found[d.get("assessment_name")] = (d["expectation"] or {}).get("value")
    return found or None


def call(judge, **kwargs):
    """Call the judge with the arguments its own call takes (built-in judges take fewer: for
    example RelevanceToQuery takes no expectations)."""
    try:
        params = inspect.signature(judge.__call__).parameters
    except (TypeError, ValueError):
        return judge(**kwargs)
    if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return judge(**kwargs)


def feedback(result):
    """(value, rationale, error) from what a judge returned."""
    if isinstance(result, list):
        if len(result) != 1:
            return None, None, f"the judge gave {len(result)} feedbacks"
        result = result[0]
    if hasattr(result, "value"):
        error = getattr(result, "error", None)
        if error:
            return None, None, getattr(error, "error_message", None) or str(error)
        return result.value, getattr(result, "rationale", None), None
    return result, None, None


def run(job, out_path, version):
    import mlflow
    from mlflow import MlflowClient
    from mlflow.genai import scorers

    mlflow.set_tracking_uri(job["uri"])
    client = MlflowClient(tracking_uri=job["uri"])
    judge = build(job["judge"], scorers)
    traces = {}
    for time in range(job["times"]):
        for answer in job["answers"]:
            line = {"id": answer["id"], "time": time}
            try:
                if answer["id"] not in traces:  # None: a new judge's answer, no trace kept
                    traces[answer["id"]] = (client.get_trace(answer["trace"])
                                            if answer.get("trace") else None)
                trace = traces[answer["id"]]
                if job["judge"].get("trace"):
                    result = call(judge, trace=trace)
                else:
                    result = call(judge, inputs=answer["inputs"], outputs=answer["outputs"],
                                  expectations=expectations(trace) if trace else None)
                value, reason, error = feedback(result)
            except Exception as e:  # noqa: BLE001 - one failed call: say why, go on
                value, reason, error = None, None, f"{type(e).__name__}: {e}"
            if error:
                line.update(ok=False, error=error)
            else:
                line.update(ok=True, value=plain(value), reason=reason)
            emit(out_path, line)
    emit(out_path, {"ok": True, "done": True, "version": version})


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") not in ("dry", "run"):
        emit(out_path, {"ok": False, "error": f"unknown mode {job.get('mode')!r}"})
        return 0
    try:
        import mlflow
        from mlflow.genai import scorers
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] == "mlflow":
            emit(out_path, {"ok": False, "missing": "mlflow"})
            return 0
        raise
    version = getattr(mlflow, "__version__", None)
    if job["mode"] == "run":
        try:
            run(job, out_path, version)
        except Exception as e:  # noqa: BLE001 - the judge could not be got back: say why
            emit(out_path, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 0
    if job.get("uri"):
        mlflow.set_tracking_uri(job["uri"])
    registered = False
    try:
        kwargs = {"name": job["name"], "experiment_id": job.get("experiment")}
        if job.get("version"):
            kwargs["version"] = int(job["version"])
        registered = scorers.get_scorer(**kwargs) is not None
    except Exception:  # noqa: BLE001 - not registered, or no registry here
        registered = False
    emit(out_path, {"ok": True, "version": version,
                    "registered": registered,
                    "builtin": hasattr(scorers, class_name(job["name"]))})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
