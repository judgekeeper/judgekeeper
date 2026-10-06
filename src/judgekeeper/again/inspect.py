"""The plan for asking an Inspect AI judge again.

A worker (`workers/inspect_worker.py`) rebuilds the recorded `model_graded_qa` or
`model_graded_fact` scorer from `eval.scorers[].options` and the grader from
`eval.model_roles`, and re-scores a copy of the log in the user's own Python, with the
grader's cache off; the original log is never opened for writing.

- Exactly your judge when the scorer is Inspect's own and the installed Inspect version is
  the one that made the log. With another version it is a close copy until the run's grading
  prompts match the saved ones (`metadata.grading`).
- No grader set: the judge is the model under test, called as a judge (the plan says so).
- Can't: a custom scorer (Inspect would import the user's task file), a template given as a
  file path that is not here, `include_history` given as a function, and rule scorers
  (`match`, `includes`, ...), which are not judges: asking again gives the same verdicts.

Inspect's Python API loads no `.env`, so the worker calls Inspect's own loader (the function
the `inspect` command uses: the nearest `.env` from the project folder upward) when the user's
Inspect has it; without it the key must be in the shell, and the plan says how to set it.

In run mode (`run`, after the yes) the worker reads the log (never writing it), keeps only the
labeled samples, and calls `score_async(..., action="append", copy=True)` once per time
asked, with every model role rebuilt with its cache off. When a grader is set, the model
under test is replaced by Inspect's `mockllm/model`, so it can't be called. An answer whose
new grading prompt differs from the saved one (`metadata.grading`) is not counted; when every
counted answer's prompt matched, a close copy made by another Inspect version is exactly the
judge.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import again, keys, prices
from judgekeeper.again import CLOSE, EXACT, Plan, cant, left_out_line, worker_run
from judgekeeper.again.fresh import Fresh
from judgekeeper.anchors import canonical_json
from judgekeeper.normalise import Normaliser, UnmappedValue
from judgekeeper.readers.inspect_logs import DEFAULT_LABELS, _load, _model, scorer_prompt
from judgekeeper.records import derive_record_id
from judgekeeper.table import make_fingerprint

MODEL_GRADED = {"model_graded_qa", "model_graded_fact"}
RULES = {"match", "includes", "exact", "pattern", "answer", "choice", "f1", "math"}
TEMPLATE_FILE = (".txt", ".md", ".jinja", ".j2", ".tmpl")


def cant_reason(name: str, options: dict, builtin: bool) -> str | None:
    base = name.split("/")[-1]
    if base in RULES:
        return (f"your judge is a rule ({base}), not a model, so asking again gives the same "
                "verdicts")
    if not builtin:
        return (f"your judge is a custom scorer ({name}): asking again would import your task "
                "file, which runs your code")
    template = options.get("template")
    if isinstance(template, str) and "{" not in template and (
            template.endswith(TEMPLATE_FILE) or "/" in template) and not Path(template).exists():
        return f"your scorer's template is a template file ({template}) that is not here"
    history = options.get("include_history")
    if isinstance(history, str):
        return (f"your scorer's include_history was a function ({history}), which the log "
                "saves only by name")
    return None


def _models(value) -> list[str]:
    if isinstance(value, list):
        return [m for v in value for m in _models(v)]
    if isinstance(value, dict):
        return [value["model"]] if value.get("model") else []
    return [value] if isinstance(value, str) and value else []


def _cache_on(log: dict) -> bool:
    spec = log.get("eval") or {}
    configs = [(log.get("plan") or {}).get("config") or {}, spec.get("model_generate_config")
               or {}]
    configs += [(r or {}).get("config") or {} for r in (spec.get("model_roles") or {}).values()
                if isinstance(r, dict)]
    return any(isinstance(c, dict) and c.get("cache") for c in configs)


def _text(content) -> str | None:
    """A grading message's text, as the log saves it."""
    if isinstance(content, dict):
        content = content.get("content")
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else None


def saved_prompt(sample: dict, metric: str) -> str | None:
    """The grading prompt the judge saw for this sample in the saved run, when saved."""
    grading = (((sample.get("scores") or {}).get(metric) or {}).get("metadata") or {}).get(
        "grading") or []
    return _text(grading[0]) if grading else None


def _targets(root, files: list[str]) -> tuple[dict, dict]:
    """({input as JSON: target}, {answer id: target}) of the samples in Inspect logs."""
    by_input, by_id = {}, {}
    for rel in files:
        if not (root / rel).is_file():
            continue
        for s in _load(root / rel).get("samples") or []:
            target = s.get("target")
            by_input.setdefault(canonical_json(s.get("input")), target)
            by_id.setdefault(derive_record_id(s.get("input"),
                                              (s.get("output") or {}).get("completion")), target)
    return by_input, by_id


def plan(ws, answers: list[dict], opts, talk, dry: bool, new: bool = False) -> Plan:
    data = ws.data()
    root, metric = ws.root, data["metric"]
    log = _load(root / data["results_files"][0])
    spec = log.get("eval") or {}
    made_with = (spec.get("packages") or {}).get("inspect_ai")
    judge = f"{data['judge']} (Inspect {made_with})" if made_with else data["judge"]
    scorer = next((s for s in spec.get("scorers") or [] if isinstance(s, dict)
                   and s.get("name") == metric), None)
    if scorer is None:
        return cant("inspect", judge, f"your log no longer lists the scorer {metric}",
                    short="the scorer is not in your log")
    options = scorer.get("options") or {}
    python = again.user_python(root, opts.python)
    installed, builtin = None, metric.split("/")[-1] in MODEL_GRADED | RULES
    loads_env = True  # without a dry run: as Inspect's own loader would
    if dry:
        out = again.run_worker("inspect", python, {"mode": "dry", "scorer": metric}, root)
        if not out.get("ok"):
            if out.get("missing"):
                return cant("inspect", judge, f"Inspect AI is not installed in {python}. Use "
                            "--python to point at the Python you run your evals with",
                            short="Inspect AI is not installed here")
            return cant("inspect", judge, f"Inspect AI could not load your scorer in {python}: "
                        f"{out.get('error')}", short="Inspect AI could not load your scorer")
        installed, builtin, loads_env = out["version"], out["builtin"], out.get("dotenv", False)
    reason = cant_reason(metric, options, builtin)
    if reason:
        return cant("inspect", judge, reason, short=reason.split(" (")[0].split(":")[0])

    roles = spec.get("model_roles") or {}
    graders = _models(roles.get("grader")) or _models(options.get("model"))
    notes = []
    if not graders:
        graders = _models(spec.get("model"))
        notes.append(f"Your judge is your model under test, {', '.join(graders) or 'unknown'}; "
                     "asking again calls it as a judge and needs its key.")
    if _cache_on(log):
        notes.append("Inspect's cache is on in your log; judgekeeper turns it off for this "
                     "run, so each answer is really asked again.")
    if new and installed and made_with and installed != made_with:
        status, why = CLOSE, (f"your Python has Inspect {installed} and your newest log was "
                              f"made with {made_with}")
    elif new:
        status, why = EXACT, ("Inspect scores your marked answers with your new judge's scorer "
                              "and grader")
    elif installed and made_with and installed != made_with:
        status, why = CLOSE, (f"your Python has Inspect {installed} and your log was made with "
                              f"{made_with}; if the grading prompts match after the run, it is "
                              "exactly your judge")
    else:
        status, why = EXACT, "Inspect re-scores a copy of your log with the same scorer and grader"

    samples = {}
    for s in log.get("samples") or []:
        key = derive_record_id(s.get("input"), (s.get("output") or {}).get("completion"))
        samples.setdefault(key, s)
    if new:  # the marked answers, placed into the newest log's samples by the worker
        by_input, _ = _targets(root, data["results_files"])
        _, old_targets = _targets(root, (data.get("saved") or {}).get("results_files") or [])
        found = [(a, {"input": a["input"], "output": {"completion": a["output"]},
                      "target": by_input.get(canonical_json(a["input"]),
                                             old_targets.get(a["id"], ""))})
                 for a in answers]
    else:
        found = [(a, samples[a["id"]]) for a in answers if a["id"] in samples]
    calls = max(1, len(graders))
    tokens = []
    for a, s in found:
        text = saved_prompt(s, metric) or canonical_json(
            [s.get("input"), (s.get("output") or {}).get("completion")])
        i, o = prices.tokens_from_text(text)
        tokens.append((i * calls, o * calls))
    model = graders[0] if graders else None
    check = keys.check(model, "inspect", root, loads_env=loads_env)
    left = []
    if len(found) < len(answers):
        n = len(answers) - len(found)
        left.append(left_out_line(n, "it is not in your log any more",
                                  "they are not in your log any more"))
    if new:
        payload = [(a, {"id": a["id"], "input": s["input"], "output": a["output"],
                        "target": s["target"]}, None) for a, s in found]
    else:
        payload = [(a, {"id": a["id"], "sample": s.get("id"), "epoch": s.get("epoch")},
                    saved_prompt(s, metric)) for a, s in found]
    return Plan(tool="inspect", judge=judge, status=status, why=why, model=model,
                provider=check.provider, key_lines=check.lines, notes=notes,
                calls_each=[calls] * len(found), tokens=tokens, left_out=left,
                settings=check.settings, key_ok=check.ok, tool_version=installed or made_with,
                runner=[python], payload=payload,
                job={"log": str(root / data["results_files"][0]), "scorer": metric,
                     "new": new},
                side_effects=[(f"Your app is not run. Inspect re-scores a copy of your log in "
                               f"your Python ({python}); your log is never changed.")])


def _fingerprint(log: dict, metric: str) -> dict:
    """The judge's fingerprint, as the Inspect reader makes it from the log."""
    spec = log.get("eval") or {}
    options = next((s.get("options") or {} for s in spec.get("scorers") or []
                    if isinstance(s, dict) and s.get("name") == metric), {})
    model, temperature = _model((spec.get("model_roles") or {}).get("grader"))
    if model is None and options.get("model"):
        model, temperature = _model(options["model"])[0], None
    evaluator = {"prompt": scorer_prompt(metric, options)}
    if model:
        evaluator["model"] = model
        if "/" in model and "+" not in model:
            evaluator["provider"] = model.split("/", 1)[0]
    if temperature is not None:
        evaluator["temperature"] = temperature
    return make_fingerprint(evaluator).to_dict()


def run(ws, plan: Plan, talk) -> Fresh:
    """Re-score the labeled samples `plan.times` times with the user's own Inspect AI."""
    norm = Normaliser(label_map=DEFAULT_LABELS)

    def verdict(item, line):
        try:
            return norm(line.get("value")).verdict
        except UnmappedValue:
            return None

    def differs(entry, lines):
        return entry[2] is not None and any(x.get("prompt") != entry[2] for x in lines)

    fresh, got, done = worker_run.ask(ws, plan, talk, "Inspect AI")
    worker_run.count(fresh, plan, got, "Inspect AI", verdict, differs)
    log = _load(Path(plan.job["log"]))
    made_with = ((log.get("eval") or {}).get("packages") or {}).get("inspect_ai")
    version = done.get("version") or plan.tool_version
    counted = [e for e in plan.payload if e[0]["id"] in fresh.verdicts]
    if plan.status == CLOSE and counted and all(e[2] is not None for e in counted):
        plan.status = EXACT
        plan.why = (f"the grading prompts matched your saved ones on every answer (Inspect "
                    f"{version} here; your log was made with {made_with})")
    fresh.fingerprint = _fingerprint(log, plan.job["scorer"])
    plan.tool_version = version
    return fresh
