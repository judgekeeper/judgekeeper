"""judgekeeper's DeepEval worker, run with the user's own Python in the project folder:

    python deepeval_worker.py job.json out.jsonl

Standard library plus the user's installed DeepEval. Mode "dry" builds the metric the job
describes and writes DeepEval's version and the model the metric will use: no judge call,
`measure()` is not called. `deepeval.evaluate()` is never called in any mode. DeepEval's
telemetry is off, and CONFIDENT_API_KEY and DEEPEVAL_RESULTS_FOLDER are removed before
DeepEval is imported, so nothing is uploaded or written to a results folder.
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
            model=None, threshold=m["threshold"], strict_mode=m["strict"], async_mode=False,
            _include_g_eval_suffix=m["suffix"])
    cls = getattr(metrics, m["class"])
    return cls(model=None, threshold=m.get("threshold", 0.5), strict_mode=m.get("strict", False),
               include_reason=False, async_mode=False)


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") != "dry":
        emit(out_path, {"ok": False, "error": f"unknown mode {job.get('mode')!r}"})
        return 0
    try:
        import deepeval
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] == "deepeval":
            emit(out_path, {"ok": False, "missing": "deepeval"})
            return 0
        raise
    try:
        metric = build(job["metric"])
    except Exception as e:  # noqa: BLE001 - the user's DeepEval refused the metric: say why
        emit(out_path, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 0
    emit(out_path, {"ok": True, "version": getattr(deepeval, "__version__", None),
                    "evaluation_model": metric.evaluation_model})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
