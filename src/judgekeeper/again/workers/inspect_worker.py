"""judgekeeper's Inspect AI worker, run with the user's own Python in the project folder:

    python inspect_worker.py job.json out.jsonl

Standard library plus the user's installed Inspect AI. Mode "dry" writes Inspect's version,
whether the job's scorer is one of Inspect's own (found in its registry without importing the
user's task file), and whether Inspect's own `.env` loader is there (`init_dotenv`, the
function the `inspect` command calls), which asking again uses so the key can stay in `.env`.
The dry run does not call it. No model is called, and no log is read or written.
"""

import json
import sys


def emit(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") != "dry":
        emit(out_path, {"ok": False, "error": f"unknown mode {job.get('mode')!r}"})
        return 0
    try:
        import inspect_ai
        from inspect_ai._util.registry import registry_lookup
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] == "inspect_ai":
            emit(out_path, {"ok": False, "missing": "inspect_ai"})
            return 0
        raise
    name = job["scorer"]
    names = [name] if "/" in name else [name, f"inspect_ai/{name}"]
    builtin = False
    for candidate in names:
        try:
            found = registry_lookup("scorer", candidate) is not None
        except Exception:  # noqa: BLE001 - a lookup error means it is not registered
            found = False
        builtin = builtin or found
    try:
        from inspect_ai._util.dotenv import init_dotenv  # noqa: F401 - only whether it is there
        dotenv = True
    except ImportError:
        dotenv = False
    emit(out_path, {"ok": True, "version": getattr(inspect_ai, "__version__", None),
                    "builtin": builtin, "dotenv": dotenv})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
