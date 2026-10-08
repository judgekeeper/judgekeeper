"""judgekeeper's DeepEval worker, run with the user's own Python in the project folder:

    python deepeval_worker.py job.json out.jsonl

Standard library plus the user's installed DeepEval. Mode "dry" builds the metric the job
describes and writes DeepEval's version and the model the metric will use: no judge call,
`measure()` is not called. Mode "run" measures each of the job's answers `times` times with
its own metric (a GEval answer keeps its own saved steps) and writes one line per answer per
time, then a "done" line. `metric.measure()` is called directly, never `deepeval.evaluate()`
(which would overwrite the user's .deepeval/ files and may upload).
DeepEval's telemetry is off, and CONFIDENT_API_KEY and DEEPEVAL_RESULTS_FOLDER are removed
before DeepEval is imported, so nothing is uploaded or written to a results folder.
"""

import json
import os
import sys

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
for _name in ("CONFIDENT_API_KEY", "DEEPEVAL_RESULTS_FOLDER"):
    os.environ.pop(_name, None)


def emit(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def judge_model(spec):
    """The judge model: None lets DeepEval's own settings pick it; else built from its saved
    name, as a name or with the provider's model class."""
    if not spec:
        return None
    if spec.get("class"):
        from deepeval import models

        return getattr(models, spec["class"])(model=spec["name"])
    return spec["name"]


def build(m):
    from deepeval import metrics

    if m["kind"] == "geval":
        from deepeval.metrics.g_eval import Rubric
        from deepeval.test_case import SingleTurnParams

        rubric = [Rubric(score_range=tuple(r), expected_outcome=o) for r, o in m["rubric"]]
        return metrics.GEval(
            name=m["name"], criteria=m["criteria"], evaluation_steps=m["steps"],
            rubric=rubric or None,
            evaluation_params=[SingleTurnParams(f) for f in m["fields"]],
            model=judge_model(m.get("model")), threshold=m["threshold"],
            strict_mode=m["strict"], async_mode=False,
            _include_g_eval_suffix=m["suffix"])
    cls = getattr(metrics, m["class"])
    return cls(model=judge_model(m.get("model")), threshold=m.get("threshold", 0.5),
               strict_mode=m.get("strict", False), include_reason=False, async_mode=False)


def test_case(fields):
    from deepeval.test_case import LLMTestCase

    kwargs = dict(fields)
    for name in ("tools_called", "expected_tools"):
        if kwargs.get(name):
            from deepeval.test_case import ToolCall

            kwargs[name] = [ToolCall(**t) for t in kwargs[name]]
    return LLMTestCase(**kwargs)


def number(x):
    return x if isinstance(x, bool) or x is None else float(x)


def run(job, out_path, version):
    built = {}
    for time in range(job["times"]):
        for answer in job["answers"]:
            key = json.dumps(answer["metric"], sort_keys=True)
            try:
                if key not in built:
                    built[key] = build(answer["metric"])
                metric = built[key]
                metric.measure(test_case(answer["case"]), _show_indicator=False)
                success = metric.success if isinstance(metric.success, bool) else None
                line = {"id": answer["id"], "time": time, "ok": True, "success": success,
                        "score": number(metric.score), "reason": metric.reason,
                        "model": metric.evaluation_model,
                        "cost": number(getattr(metric, "evaluation_cost", None)),
                        "logs": getattr(metric, "verbose_logs", None)}
            except Exception as e:  # noqa: BLE001 - one failed call: say why, go on
                line = {"id": answer["id"], "time": time, "ok": False,
                        "error": f"{type(e).__name__}: {e}"}
            emit(out_path, line)
    emit(out_path, {"ok": True, "done": True, "version": version})


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") not in ("dry", "run"):
        emit(out_path, {"ok": False, "error": f"unknown mode {job.get('mode')!r}"})
        return 0
    try:
        import deepeval
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] == "deepeval":
            emit(out_path, {"ok": False, "missing": "deepeval"})
            return 0
        raise
    version = getattr(deepeval, "__version__", None)
    if job["mode"] == "run":
        run(job, out_path, version)
        return 0
    try:
        metric = build(job["metric"])
    except Exception as e:  # noqa: BLE001 - the user's DeepEval refused the metric: say why
        emit(out_path, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 0
    emit(out_path, {"ok": True, "version": version,
                    "evaluation_model": metric.evaluation_model})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
