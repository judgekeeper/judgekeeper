"""judgekeeper's Inspect AI worker, run with the user's own Python in the project folder:

    python inspect_worker.py job.json out.jsonl

Standard library plus the user's installed Inspect AI. Mode "dry" writes Inspect's version,
whether the job's scorer is one of Inspect's own (found in its registry without importing the
user's task file), and whether Inspect's own `.env` loader is there (`init_dotenv`, the
function the `inspect` command calls), which asking again uses so the key can stay in `.env`.
The dry run does not call it. No model is called, and no log is read or written.

Mode "run" calls that loader (when it is there), reads the log with `read_eval_log` (never
writing it), keeps the job's samples (for a new judge, which never graded the person's
marked answers: puts those answers into copies of the log's first sample) and rebuilds the
recorded scorer from Inspect's own
registry with its saved options. Then, once per time asked, `score_async(log, [scorer],
action="append", copy=True)` re-scores a copy in memory, with every model role (and a grader
given as a scorer option) rebuilt with its cache off, so each time is really asked. When a
grader is set, the model under test is `mockllm/model`, Inspect's stand-in that can't call
anything; without one, the judge is the model under test, rebuilt with its cache off. One line
per sample per time: the new score's value, explanation and grading prompt. `inspect score
--overwrite` is never used.
"""

import asyncio
import copy
import json
import sys


def emit(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def text(message):
    """The text of a grading message: a ChatMessage, or a dict as read from a log."""
    content = message.get("content") if isinstance(message, dict) else getattr(
        message, "content", message)
    if isinstance(content, list):
        return "".join(str((p.get("text") if isinstance(p, dict) else getattr(p, "text", ""))
                           or "") for p in content)
    return content if isinstance(content, str) else None


def plain(value):
    return value if isinstance(value, (str, bool, int, float)) or value is None else str(value)


def uncached(model, GenerateConfig, get_model):
    """A model as the log saved it (a name, a role's ModelConfig, or a scorer option's dict),
    rebuilt with the same settings and its cache off."""
    if isinstance(model, list):
        return [uncached(m, GenerateConfig, get_model) for m in model]
    if isinstance(model, str):
        return get_model(model, config=GenerateConfig(cache=False))
    if isinstance(model, dict):
        name, config = model.get("model"), model.get("config") or {}
        base_url, args = model.get("base_url"), model.get("model_args") or model.get("args")
    else:
        name, config = model.model, model.config
        base_url, args = getattr(model, "base_url", None), getattr(model, "args", None)
    if hasattr(config, "model_dump"):
        config = config.model_dump(exclude_none=True)
    config = {**(config or {}), "cache": False}
    return get_model(name, config=GenerateConfig(**config), base_url=base_url, **(args or {}))


def scorer_from_registry(registry_create, name, options):
    """The recorded scorer from Inspect's own registry (never from the user's task file)."""
    names = [name] if "/" in name else [f"inspect_ai/{name}", name]
    error = None
    for candidate in names:
        try:
            return registry_create("scorer", candidate, **options)
        except Exception as e:  # noqa: BLE001 - try the next spelling
            error = e
    raise error


def new_samples(log, answers):
    """The marked answers as samples shaped like the newest log's first sample, for a new
    judge that never graded them: their own input, answer and target; no scores."""
    from inspect_ai.model import (
        ChatMessageAssistant,
        ChatMessageSystem,
        ChatMessageUser,
        ModelOutput,
    )

    roles = {"user": ChatMessageUser, "system": ChatMessageSystem,
             "assistant": ChatMessageAssistant}
    template, samples, wanted = log.samples[0], [], {}
    for n, answer in enumerate(answers):
        sample = copy.deepcopy(template)
        given = answer["input"]
        if isinstance(given, list):
            given = [roles.get(m.get("role"), ChatMessageUser)(content=m.get("content") or "")
                     if isinstance(m, dict) else m for m in given]
            messages = list(given)
        else:
            messages = [ChatMessageUser(content=str(given))]
        sample.id, sample.epoch, sample.input = f"judgekeeper-{n}", 1, given
        sample.target = answer.get("target") or ""
        sample.output = ModelOutput.from_content(model=str(log.eval.model),
                                                 content=answer["output"] or "")
        sample.messages = messages + [ChatMessageAssistant(content=answer["output"] or "")]
        sample.scores = {}
        samples.append(sample)
        wanted[(sample.id, 1)] = answer["id"]
    return samples, wanted


def run(job, out_path, version):
    try:
        from inspect_ai._util.dotenv import init_dotenv
    except ImportError:
        init_dotenv = None
    if init_dotenv is not None:
        init_dotenv()
    from inspect_ai import score_async
    from inspect_ai.log import read_eval_log
    from inspect_ai.model import GenerateConfig, get_model
    from inspect_ai.util import registry_create

    log = read_eval_log(job["log"])
    if job.get("new"):
        log.samples, wanted = new_samples(log, job["answers"])
    else:
        wanted = {(str(a["sample"]), a["epoch"]): a["id"] for a in job["answers"]}
        log.samples = [s for s in log.samples or [] if (str(s.id), s.epoch) in wanted]
    before = {(str(s.id), s.epoch): set(s.scores or {}) for s in log.samples}
    spec = next(s for s in log.eval.scorers if s.name == job["scorer"])
    options = dict(spec.options or {})
    if options.get("model") is not None:
        options["model"] = uncached(options["model"], GenerateConfig, get_model)
    scorer = scorer_from_registry(registry_create, job["scorer"], options)
    roles = {name: uncached(config, GenerateConfig, get_model)
             for name, config in (log.eval.model_roles or {}).items()}
    if options.get("model") is not None or options.get("model_role", "grader") in roles:
        model = get_model("mockllm/model")
    else:
        model = uncached({"model": log.eval.model, "config": log.eval.model_generate_config,
                          "base_url": getattr(log.eval, "model_base_url", None),
                          "args": getattr(log.eval, "model_args", None)},
                         GenerateConfig, get_model)
    for time in range(job["times"]):
        try:
            new = asyncio.run(score_async(log, [scorer], action="append", copy=True,
                                          model_roles=roles or None, model=model))
        except Exception as e:  # noqa: BLE001 - this time failed for every sample: say why
            for item in wanted.values():
                emit(out_path, {"id": item, "time": time, "ok": False,
                                "error": f"{type(e).__name__}: {e}"})
            continue
        for sample in new.samples:
            key = (str(sample.id), sample.epoch)
            added = [n for n in (sample.scores or {}) if n not in before[key]]
            if not added:
                emit(out_path, {"id": wanted[key], "time": time, "ok": False,
                                "error": "Inspect gave no new score"})
                continue
            score = sample.scores[added[-1]]
            grading = (score.metadata or {}).get("grading") or []
            emit(out_path, {"id": wanted[key], "time": time, "ok": True,
                            "value": plain(score.value), "reason": score.explanation,
                            "prompt": text(grading[0]) if grading else None})
    emit(out_path, {"ok": True, "done": True, "version": version})


def main(job_path, out_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    if job.get("mode") not in ("dry", "run"):
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
    if job["mode"] == "run":
        try:
            run(job, out_path, getattr(inspect_ai, "__version__", None))
        except Exception as e:  # noqa: BLE001 - the log or scorer could not be loaded: say why
            emit(out_path, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 0
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
