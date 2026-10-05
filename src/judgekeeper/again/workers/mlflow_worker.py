"""judgekeeper's MLflow worker, run with the user's own Python in the project folder:

    python mlflow_worker.py job.json out.jsonl

Standard library plus the user's installed MLflow. Mode "dry" writes MLflow's version, whether
the job's judge is registered (`get_scorer`) and whether it is one of MLflow's built-in judges.
No judge is called and nothing is written to the store; `mlflow.genai.evaluate()` is never
called in any mode. MLflow's telemetry is off.
"""

import json
import os
import sys

os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"


def emit(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def class_name(name):
    return "".join(part.capitalize() for part in str(name).split("_"))


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") != "dry":
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
    registered = False
    try:
        kwargs = {"name": job["name"]}
        if job.get("version"):
            kwargs["version"] = int(job["version"])
        registered = scorers.get_scorer(**kwargs) is not None
    except Exception:  # noqa: BLE001 - not registered, or no registry here
        registered = False
    emit(out_path, {"ok": True, "version": getattr(mlflow, "__version__", None),
                    "registered": registered,
                    "builtin": hasattr(scorers, class_name(job["name"]))})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
