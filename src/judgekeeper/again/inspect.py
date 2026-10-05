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
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper import again, keys, prices
from judgekeeper.again import CLOSE, EXACT, Plan, cant, left_out_line
from judgekeeper.anchors import canonical_json
from judgekeeper.readers.inspect_logs import _load
from judgekeeper.records import derive_record_id

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


def plan(ws, answers: list[dict], opts, talk, dry: bool) -> Plan:
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
    if installed and made_with and installed != made_with:
        status, why = CLOSE, (f"your Python has Inspect {installed} and your log was made with "
                              f"{made_with}; if the grading prompts match after the run, it is "
                              "exactly your judge")
    else:
        status, why = EXACT, "Inspect re-scores a copy of your log with the same scorer and grader"

    samples = {}
    for s in log.get("samples") or []:
        key = derive_record_id(s.get("input"), (s.get("output") or {}).get("completion"))
        samples.setdefault(key, s)
    found = [(a, samples[a["id"]]) for a in answers if a["id"] in samples]
    calls = max(1, len(graders))
    tokens = []
    for a, s in found:
        grading = (((s.get("scores") or {}).get(metric) or {}).get("metadata") or {}).get(
            "grading") or []
        first = grading[0] if grading and isinstance(grading[0], dict) else {}
        text = first.get("content") if isinstance(first.get("content"), str) else \
            canonical_json([s.get("input"), (s.get("output") or {}).get("completion")])
        i, o = prices.tokens_from_text(text)
        tokens.append((i * calls, o * calls))
    model = graders[0] if graders else None
    check = keys.check(model, "inspect", root, loads_env=loads_env)
    left = []
    if len(found) < len(answers):
        n = len(answers) - len(found)
        left.append(left_out_line(n, "it is not in your log any more",
                                  "they are not in your log any more"))
    return Plan(tool="inspect", judge=judge, status=status, why=why, model=model,
                provider=check.provider, key_lines=check.lines, notes=notes,
                calls_each=[calls] * len(found), tokens=tokens, left_out=left,
                settings=check.settings,
                side_effects=[(f"Your app is not run. Inspect re-scores a copy of your log in "
                               f"your Python ({python}); your log is never changed.")])
