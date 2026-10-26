"""judgekeeper's Inspect AI worker, run with the user's own Python in the project folder:

    python inspect_worker.py job.json out.jsonl

Standard library plus the user's installed Inspect AI. Mode "dry" reports Inspect's version,
whether the job's scorer is one of Inspect's own (found without importing the user's task
file) and whether Inspect's `.env` loader is there; it calls no model and touches no log.

Mode "run" calls that loader, reads the log without writing it, keeps the job's samples and
rebuilds the recorded scorer from Inspect's registry with its saved options. Once per time
asked, `score_async(..., copy=True)` re-scores a copy in memory, with every model role rebuilt
with its cache off so each time is really asked: by its name and settings only, never with a
server (`base_url`) or `args` from the log. When a grader is set, the model under test is
`mockllm/model`, which can't call anything. `inspect score --overwrite` is never used.
"""

import asyncio
import copy
import json
import os
import sys


def emit(path, record):
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags, 0o600), "a", encoding="utf-8") as f:  # owner's only
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
    rebuilt with the same generate settings and its cache off. The log's server (`base_url`)
    and `args` are never passed: a log can come from someone else (the plan refuses them)."""
    if isinstance(model, list):
        return [uncached(m, GenerateConfig, get_model) for m in model]
    if isinstance(model, str):
        return get_model(model, config=GenerateConfig(cache=False))
    if isinstance(model, dict):
        name, config = model.get("model"), model.get("config") or {}
    else:
        name, config = model.model, model.config
    if hasattr(config, "model_dump"):
        config = config.model_dump(exclude_none=True)
    config = {**(config or {}), "cache": False}
    return get_model(name, config=GenerateConfig(**config))


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


def guarded(scorer, failed):
    """The scorer, with each sample's judge call on its own: a call that fails (an HTTP 400,
    say) leaves that sample with no new score and its error's type in `failed`, keyed by
    (sample id, epoch); the other samples are still scored. Never the error's text: it can
    quote the grading prompt. The scorer itself when this Inspect has no registry helpers."""
    try:
        from inspect_ai._util.registry import (
            has_registry_params,
            registry_info,
            registry_params,
            set_registry_info,
            set_registry_params,
        )
    except ImportError:
        return scorer

    async def score(state, target):
        try:
            return await scorer(state, target)
        except Exception as e:  # noqa: BLE001 - this answer's call failed; Ctrl-C still stops
            failed[(str(state.sample_id), state.epoch)] = type(e).__name__
            return None

    set_registry_info(score, registry_info(scorer))
    if has_registry_params(scorer):
        set_registry_params(score, registry_params(scorer))
    return score


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


def read_log(path, wanted, new):
    """The log, with only the samples asked about (`wanted`), or for a `new` judge only its
    first sample (the template). A `.eval` log is read as its header, then one sample at a
    time, when this Inspect can: never every sample in memory at once."""
    from inspect_ai.log import read_eval_log

    try:
        from inspect_ai.log import read_eval_log_samples
    except ImportError:
        read_eval_log_samples = None
    if read_eval_log_samples is None or not str(path).lower().endswith(".eval"):
        return read_eval_log(path)
    log = read_eval_log(path, header_only=True)
    log.samples = []
    for sample in read_eval_log_samples(path, all_samples_required=False):
        if new or (str(sample.id), sample.epoch) in wanted:
            log.samples.append(sample)
            if new:
                break
    return log


def usage_of(sample):
    """{model: its usage as text}: what Inspect counted for a sample, by model."""
    usage = getattr(sample, "model_usage", None) or {}
    return {str(m): repr(u) for m, u in usage.items()} if isinstance(usage, dict) else {}


def run(job, out_path, version):
    try:
        from inspect_ai._util.dotenv import init_dotenv
    except ImportError:
        init_dotenv = None
    if init_dotenv is not None:
        init_dotenv()
    from inspect_ai import score_async
    from inspect_ai.model import GenerateConfig, get_model
    from inspect_ai.util import registry_create

    if job.get("new"):
        log = read_log(job["log"], {}, True)
        log.samples, wanted = new_samples(log, job["answers"])
    else:
        wanted = {(str(a["sample"]), a["epoch"]): a["id"] for a in job["answers"]}
        log = read_log(job["log"], wanted, False)
        log.samples = [s for s in log.samples or [] if (str(s.id), s.epoch) in wanted]
    before = {(str(s.id), s.epoch): set(s.scores or {}) for s in log.samples}
    usage = {(str(s.id), s.epoch): usage_of(s) for s in log.samples}
    spec = next(s for s in log.eval.scorers if s.name == job["scorer"])
    options = dict(spec.options or {})
    if job.get("rule") is not None:  # judgekeeper fix: a new rule in place of the saved one
        options[job.get("rule_field") or "instructions"] = job["rule"]
    if options.get("model") is not None:
        options["model"] = uncached(options["model"], GenerateConfig, get_model)
    scorer = scorer_from_registry(registry_create, job["scorer"], options)
    roles = {name: uncached(config, GenerateConfig, get_model)
             for name, config in (log.eval.model_roles or {}).items()}
    if options.get("model") is not None or options.get("model_role", "grader") in roles:
        model = get_model("mockllm/model")
    else:
        model = uncached({"model": log.eval.model, "config": log.eval.model_generate_config},
                         GenerateConfig, get_model)
    for time in range(job["times"]):
        failed = {}
        try:
            new = asyncio.run(score_async(log, [guarded(scorer, failed)], action="append",
                                          copy=True, model_roles=roles or None, model=model))
        except Exception as e:  # noqa: BLE001 - this time failed for every sample: its type
            for item in wanted.values():
                emit(out_path, {"id": item, "time": time, "ok": False,
                                "error": type(e).__name__})
            continue
        for sample in new.samples:
            key = (str(sample.id), sample.epoch)
            added = [n for n in (sample.scores or {}) if n not in before[key]]
            if key in failed:
                emit(out_path, {"id": wanted[key], "time": time, "ok": False,
                                "error": failed[key], "call_failed": True})
                continue
            if not added:
                emit(out_path, {"id": wanted[key], "time": time, "ok": False,
                                "error": "Inspect gave no new score"})
                continue
            score = sample.scores[added[-1]]
            grading = (score.metadata or {}).get("grading") or []
            line = {"id": wanted[key], "time": time, "ok": True, "value": plain(score.value),
                    "reason": score.explanation,
                    "prompt": text(grading[0]) if grading else None}
            models = [m for m, u in usage_of(sample).items() if usage[key].get(m) != u]
            if models:  # the models Inspect counted for this scoring: the ones that answered
                line["models"] = models
            emit(out_path, line)
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
