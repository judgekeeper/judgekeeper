"""The plan for asking a DeepEval judge again.

A worker (`workers/deepeval_worker.py`) builds the user's metric in the user's own Python and
calls `metric.measure()` directly, never `deepeval.evaluate()` (which overwrites
`.deepeval/.latest_run_full.json` and may upload to Confident AI). The worker runs with
DeepEval's telemetry off and without CONFIDENT_API_KEY or DEEPEVAL_RESULTS_FOLDER.

- GEval: each answer's own saved steps, criteria and rubric come back from its `verboseLogs`,
  so no steps call is made and the scoring prompt is the one the original run used. Which
  fields the judge reads is not saved: `--fields`, or a question at a terminal that lists
  every field the saved answers have, with input and actual_output pre-selected. Exactly your
  judge when the fields and the DeepEval version are confirmed and the model DeepEval builds
  is the saved `evaluationModel`; otherwise a close copy, naming what was not confirmed.
- The model: the results do not say how the user's code chose it, so the worker first lets
  DeepEval's own settings pick it. When that gives another model, the judge is built again
  from the saved name (`by_name`): a bare name (OpenAI) as `model="<name>"`, a name with a
  provider DeepEval writes after it ("claude-x (Anthropic)", "(Gemini)", "(Deepseek)",
  "(Grok)", "(KIMI)") with that provider's model class. It is used only when DeepEval then
  reports exactly the saved name. A judge that needs more than a name (Azure, a local or
  Ollama server, a gateway, an AWS Bedrock id) stops the plan, as does a name DeepEval builds
  as another model.
- Built-in metrics: always a close copy (options the file does not save; prompts that change
  between DeepEval versions).
- Can't: DAG metrics, custom metric classes, conversational metrics, no `evaluationModel`;
  and Hallucination, Bias or Toxicity scores saved by a DeepEval on the other side of 4.2.0
  from the user's (DeepEval turned these scores round in 4.2.0, so a pass means another
  thing on each side).

In dry mode the worker builds the metric and reports DeepEval's version and the model it
would use, with no judge call. In run mode (`run`, after the yes) it measures each answer
`times` times; a verdict is DeepEval's own `success`, which applies the threshold the way the
user's DeepEval version does. DeepEval's own `evaluation_cost`, when it reports one, is summed
and shown as the real cost.
"""

from __future__ import annotations

import json
import re

from judgekeeper import again, keys, prices
from judgekeeper.again import CANT, CLOSE, EXACT, Plan, cant, left_out_line, worker_run
from judgekeeper.again.fresh import Fresh
from judgekeeper.readers.deepeval import (
    SEPARATOR,
    SUFFIX,
    _load,
    provider_of,
    rubric_from_verbose_logs,
)
from judgekeeper.records import derive_record_id
from judgekeeper.table import make_fingerprint

BUILTINS = {  # saved name: (class, judge calls per answer, None: retrieved chunks + 1)
    "Answer Relevancy": ("AnswerRelevancyMetric", 3),
    "Faithfulness": ("FaithfulnessMetric", 4),
    "Hallucination": ("HallucinationMetric", 2),
    "Bias": ("BiasMetric", 3),
    "Toxicity": ("ToxicityMetric", 3),
    "Contextual Relevancy": ("ContextualRelevancyMetric", None),
    "Contextual Precision": ("ContextualPrecisionMetric", 0),
    "Contextual Recall": ("ContextualRecallMetric", 0),
}
FIELDS = ("input", "actual_output", "expected_output", "context", "retrieval_context",
          "tools_called", "expected_tools")
SAVED_AS = {"input": "input", "actual_output": "actualOutput",
            "expected_output": "expectedOutput", "context": "context",
            "retrieval_context": "retrievalContext", "tools_called": "toolsCalled",
            "expected_tools": "expectedTools"}
LISTED = ("input", "actual_output", "expected_output", "context", "retrieval_context")
DEFAULT_FIELDS = ("input", "actual_output")
TOOL_FIELDS = ("tools_called", "expected_tools")
# Scored the other way round from DeepEval 4.2.0 on: a higher score passes, the threshold is
# a minimum. Before, a lower score passed.
TURNED = {"HallucinationMetric", "BiasMetric", "ToxicityMetric", "MisuseMetric"}
TURNED_IN = (4, 2, 0)
# DeepEval's model classes that need only a model name (the key comes from the environment),
# by the provider label DeepEval writes after the name in `evaluationModel`.
BY_NAME = {"Anthropic": "AnthropicModel", "Gemini": "GeminiModel", "Deepseek": "DeepSeekModel",
           "Grok": "GrokModel", "KIMI": "KimiModel"}
_BEDROCK = re.compile(r"[a-z][a-z0-9-]*\.[a-z]")  # "anthropic.claude-...", "us.amazon.nova-..."
NOT_CONFIRMED = "which fields your judge reads was not confirmed"
WORKER_ENV = {"DEEPEVAL_TELEMETRY_OPT_OUT": "1"}
WORKER_DROP = ("CONFIDENT_API_KEY", "DEEPEVAL_RESULTS_FOLDER")
_RUBRIC = re.compile(r"(\d+)(?:-(\d+))?: (.*)\Z")


def _at_least(version: str | None, than: tuple) -> bool:
    return tuple(int(x) for x in re.findall(r"\d+", version or "")[:3]) >= than


def direction(md: dict) -> str | None:
    """Which way a saved score passes: "low" (a lower score passes), "high", or None when the
    saved score, threshold and verdict do not tell."""
    score, ok, threshold = md.get("score"), md.get("success"), md.get("threshold")
    if not isinstance(ok, bool) or not all(isinstance(x, int | float) and not isinstance(
            x, bool) for x in (score, threshold)) or score == threshold:
        return None
    return "low" if ok == (score < threshold) else "high"


def verdict_of(line: dict, job: dict, version: str | None) -> str | None:
    """A fresh verdict: DeepEval's own `success`; without it, the score against the threshold
    the way DeepEval `version` applies it."""
    if isinstance(line.get("success"), bool):
        return "pass" if line["success"] else "fail"
    score = line.get("score")
    if not isinstance(score, int | float) or isinstance(score, bool):
        return None
    threshold = job.get("threshold", 0.5)
    if job.get("class") in TURNED and not _at_least(version, TURNED_IN):
        return "pass" if score <= threshold else "fail"
    return "pass" if score >= threshold else "fail"


def classify(md: dict) -> str:
    name = str(md.get("name") or "")
    if name.endswith(" [DAG]"):
        return "dag"
    if name.endswith(" [Conversational GEval]"):
        return "conversational"
    if name.endswith(" [GEval]") or str(md.get("verboseLogs") or "").startswith("Criteria:"):
        return "geval"
    return "builtin" if name in BUILTINS else "custom"


def cant_reason(md: dict) -> str | None:
    kind = classify(md)
    if kind == "dag":
        return "your judge is a DAG metric, built from your own code"
    if kind == "conversational":
        return "conversational metrics can't be asked again yet"
    if kind == "custom":
        return f"your judge is a custom metric ({md.get('name')}), which runs your own code"
    if not md.get("evaluationModel"):
        return "your results do not say which model judged"
    return None


def parse_geval(logs: str | None) -> dict | None:
    """{criteria, steps, rubric} from a GEval `verboseLogs`, or None when the steps or rubric
    cannot be read back to exactly the saved text."""
    parts = {}
    for part in (logs or "").split(SEPARATOR):
        for head in ("Criteria:\n", "Evaluation Steps:\n", "Rubric:\n"):
            if part.startswith(head):
                parts[head] = part[len(head):]
    if "Evaluation Steps:\n" not in parts:
        return None
    criteria = parts.get("Criteria:\n")
    text = parts["Evaluation Steps:\n"]
    if text in ("[]", "[\n]"):
        steps = []
    else:
        if not (text.startswith('[\n    "') and text.endswith('"\n]')):
            return None
        steps = text[len('[\n    "'):-len('"\n]')].split('",\n    "')
        rebuilt = "[\n" + ",\n".join(f'    "{s}"' for s in steps) + "\n]"
        if rebuilt != text or any("\n" in s for s in steps):
            return None
    rubric = []
    rubric_text = parts.get("Rubric:\n", "None")
    if rubric_text != "None":
        for line in rubric_text.split("\n"):
            m = _RUBRIC.match(line)
            if not m:
                return None
            low, high = int(m[1]), int(m[2] or m[1])
            rubric.append([[low, high], m[3]])
    return {"criteria": None if criteria in (None, "None") else criteria, "steps": steps,
            "rubric": rubric}


def by_name(model: str) -> tuple[dict | None, str]:
    """How the worker can build the saved judge model from its name: ({"name"} for a bare,
    OpenAI name, {"class", "name"} for a provider DeepEval writes after the name), or
    (None, why not) for a judge that needs more than its name."""
    m = SUFFIX.search(model)
    if m:
        label = m[1].strip()
        if label in BY_NAME:
            return {"class": BY_NAME[label], "name": model[:m.start()]}, ""
        if label == "Azure":
            return None, "an Azure judge needs its endpoint and deployment as well as its name"
        article = "an" if label[:1].upper() in "AEIOU" else "a"
        return None, f"{article} {label} judge needs more than its name"
    if "/" in model or ":" in model or _BEDROCK.match(model):
        return None, "this judge needs more than its name"
    return {"name": model}, ""


def metric_job(md: dict, fields, model: dict | None = None) -> dict:
    """The worker's description of the metric to build for one saved answer. `model`, from
    `by_name`, builds the judge model from its saved name instead of DeepEval's settings."""
    name = str(md["name"])
    threshold, strict = float(md.get("threshold", 0.5)), bool(md.get("strictMode", False))
    if classify(md) == "geval":
        g = parse_geval(md.get("verboseLogs"))
        job = {"kind": "geval", "class": "GEval", "name": name.removesuffix(" [GEval]"),
               "suffix": name.endswith(" [GEval]"), **g, "fields": list(fields or ()),
               "threshold": threshold, "strict": strict}
    else:
        job = {"kind": "builtin", "class": BUILTINS[name][0], "name": name,
               "threshold": threshold, "strict": strict}
    return {**job, "model": model} if model else job


def case_job(case: dict, fields) -> dict:
    """The saved test case, as the worker passes it to LLMTestCase: every field it has (tool
    calls only when the judge reads them)."""
    return {f: case[SAVED_AS[f]] for f in FIELDS
            if case.get(SAVED_AS[f]) not in (None, "", [])
            and (f not in TOOL_FIELDS or f in (fields or ()))}


def case_fields(case: dict) -> list[str]:
    """The fields a saved test case has, of those the question lists."""
    return [f for f in LISTED if case.get(SAVED_AS[f]) not in (None, "", [])]


def _check_fields(fields: list[str], have: list[str]) -> str | None:
    bad = [f for f in fields if f not in FIELDS]
    if bad:
        return f"{', '.join(bad)} is not one of {', '.join(FIELDS)}"
    missing = [f for f in fields if f in LISTED and f not in have]
    if missing:
        return f"your saved answers have no {', '.join(missing)}"
    return None


def _fields(opts, talk, dry: bool, have: list[str]) -> tuple[list[str], bool, str | None]:
    """(fields, confirmed, error). `have`: the fields the saved answers have."""
    if opts.fields:
        fields = [f.strip() for f in opts.fields.split(",") if f.strip()]
        error = _check_fields(fields, have)
        return (fields, True, None) if error is None else ([], False, f"--fields: {error}")
    answer = None
    if talk is not None and dry:
        if not talk.quiet and start_interactive():
            talk.say(f"Your saved answers have: {', '.join(have)}.")
        answer = talk.ask("Which fields does your judge read?", ", ".join(DEFAULT_FIELDS))
    if answer is None:
        return list(DEFAULT_FIELDS), False, None
    fields = [f.strip() for f in answer.split(",") if f.strip()]
    error = _check_fields(fields, have)
    return (fields, True, None) if error is None else ([], False, error)


def start_interactive() -> bool:
    from judgekeeper.start import _interactive

    return _interactive()


def plan(ws, answers: list[dict], opts, talk, dry: bool) -> Plan:
    data = ws.data()
    root, metric, judge = ws.root, data["metric"], data["judge"]
    cases = {}
    for rel in data["results_files"]:
        run = _load(root / rel)
        for case in run.get("testCases") or []:
            key = derive_record_id(case.get("input"), case.get("actualOutput"))
            md = next((m for m in case.get("metricsData") or [] if m.get("name") == metric),
                      None)
            if md is not None:
                cases.setdefault(key, (case, md))
    found = [(a, *cases[a["id"]]) for a in answers if a["id"] in cases]
    if not found:
        return cant("deepeval", judge, "none of your labeled answers is in your results files "
                    "any more", short="your answers are not in your results files")
    first_md = found[0][2]
    reason = cant_reason(first_md)
    if reason:
        return cant("deepeval", judge, reason, short=reason.split(",")[0])
    kind = classify(first_md)
    model = first_md["evaluationModel"]
    unreadable = 0
    if kind == "geval":
        readable = [x for x in found if parse_geval(x[2].get("verboseLogs")) is not None]
        unreadable, found = len(found) - len(readable), readable
        if not found:
            return cant("deepeval", judge, "your saved evaluation steps can't be read back "
                        "exactly", short="your saved steps can't be read back")
    have = [f for f in LISTED if any(f in case_fields(case) for _, case, _ in found)]
    fields, fields_ok, error = (_fields(opts, talk, dry, have) if kind == "geval"
                                else ([], True, None))
    if error:
        return cant("deepeval", judge, error, short="unknown fields")

    python = again.user_python(root, opts.python)
    version, version_ok, built, notes = None, False, None, []
    if dry:
        out = again.run_worker("deepeval", python, {"mode": "dry", "metric": metric_job(
            found[0][2], fields)}, root, env=WORKER_ENV, drop=WORKER_DROP)
        if not out.get("ok"):
            if out.get("missing"):
                return cant("deepeval", judge, f"DeepEval is not installed in {python}. Use "
                            "--python to point at the Python you run your evals with",
                            short="DeepEval is not installed here")
            return cant("deepeval", judge, f"DeepEval could not build your judge in {python}: "
                        f"{out.get('error')}", short="DeepEval could not build your judge")
        version = out["version"]
        turned = _turned(found, version)
        if turned:
            return cant("deepeval", judge, turned, short="your saved scores point the other way")
        picked = out["evaluation_model"]
        if picked != model:
            head = (f"your DeepEval settings pick {picked} now, but your saved verdicts came "
                    f"from {model}")
            short = "your DeepEval settings pick another model"
            built, why_not = by_name(model)
            if built is None:
                return cant("deepeval", judge, f"{head}; {why_not}, so judgekeeper can't build "
                            "it again", short=short)
            out = again.run_worker("deepeval", python, {"mode": "dry", "metric": metric_job(
                found[0][2], fields, built)}, root, env=WORKER_ENV, drop=WORKER_DROP)
            if not out.get("ok"):
                return cant("deepeval", judge, f"{head}; DeepEval could not build {model} by "
                            f"name: {out.get('error')}", short=short)
            if out["evaluation_model"] != model:
                return cant("deepeval", judge, f"{head}; built with that name, DeepEval "
                            f"reports {out['evaluation_model']}", short=short)
            notes.append(f"Your DeepEval settings pick {picked}; judgekeeper builds your judge "
                         f"with the model your results name, {model}, and DeepEval confirms it.")
        if talk is not None:
            version_ok = talk.ask_yes(f"Is DeepEval {version} the version you ran your eval "
                                      "with?")
    reasons = []
    if kind == "builtin":
        reasons.append("built-in metrics keep settings the results file does not save, and "
                       "their prompts change between DeepEval versions")
    if not fields_ok:
        reasons.append(NOT_CONFIRMED)
    if not version_ok:
        reasons.append("the DeepEval version was not confirmed")
    status = CLOSE if reasons else EXACT
    why = "; ".join(reasons) if reasons else (
        f"DeepEval {version} measures your GEval metric with each answer's own saved steps")

    calls_each, tokens, at_least = [], [], False
    for a, case, md in found:
        if kind == "geval":
            n = 1
        else:
            n = BUILTINS[md["name"]][1]
            if n is None:
                n = len(case.get("retrievalContext") or []) + 1
            elif n == 0:
                n, at_least = 1, True
        calls_each.append(n)
        if md.get("inputTokenCount"):
            tokens.append((int(md["inputTokenCount"]), int(md.get("outputTokenCount") or 0)))
        else:
            text = " ".join(str(x) for x in (md.get("verboseLogs") or "", case.get("input"),
                                             case.get("actualOutput"), json.dumps(
                                                 case.get("expectedOutput"))))
            i, o = prices.tokens_from_text(text)
            tokens.append((i * n, o * n))
    check = keys.check(model, "deepeval", root)
    left = []
    gone = len(answers) - len(found) - unreadable
    if gone:
        left.append(left_out_line(gone, "it is not in your results files any more",
                                  "they are not in your results files any more"))
    if unreadable:
        left.append(left_out_line(unreadable, "its saved steps can't be read back exactly",
                                  "their saved steps can't be read back exactly"))
    payload = [(a, {"id": a["id"], "case": case_job(case, fields),
                    "metric": metric_job(md, fields, built)}) for a, case, md in found]
    return Plan(tool="deepeval", judge=f"{judge} (DeepEval {version})" if version else judge,
                status=status, why=why, model=model, provider=check.provider,
                key_lines=check.lines, notes=notes, calls_each=calls_each,
                calls_note="at least" if at_least else "", tokens=tokens, left_out=left,
                settings=check.settings, key_ok=check.ok, tool_version=version,
                runner=[python], payload=payload,
                side_effects=[(f"Your app is not run. DeepEval measures your metric directly "
                               f"in your Python ({python}); never deepeval.evaluate(), so "
                               "nothing is written to .deepeval/ or sent to Confident AI.")])


def _turned(found: list, version: str | None) -> str | None:
    """Why a Hallucination, Bias or Toxicity judge can't be asked again: its saved scores point
    the other way from the user's DeepEval version."""
    md = found[0][2]
    if classify(md) != "builtin" or BUILTINS[md["name"]][0] not in TURNED:
        return None
    want = "high" if _at_least(version, TURNED_IN) else "low"
    seen = {direction(m) for _, _, m in found} - {None}
    if not seen or seen == {want}:
        return None
    made = "a DeepEval before 4.2.0" if want == "high" else "DeepEval 4.2.0 or later"
    return (f"your saved {md['name']} scores come from {made}, which scores {md['name']} the "
            f"other way round from your DeepEval {version}")


def run(ws, plan: Plan, talk) -> Fresh:
    """Measure each labeled answer `plan.times` times with the user's own DeepEval."""
    fresh, got, done = worker_run.ask(ws, plan, talk, "DeepEval", env=WORKER_ENV,
                                      drop=WORKER_DROP)
    version = done.get("version") or plan.tool_version
    firsts = worker_run.count(fresh, plan, got, "DeepEval",
                              lambda item, line: verdict_of(line, item["metric"], version))
    evaluator = {"model": firsts[0].get("model") or plan.model}
    if provider := provider_of(evaluator["model"]):
        evaluator["provider"] = provider
    if prompt := rubric_from_verbose_logs(firsts[0].get("logs")):
        evaluator["prompt"] = prompt
    fresh.fingerprint = make_fingerprint(evaluator).to_dict()
    costs = [x["cost"] for runs in got.values() for x in runs.values()
             if isinstance(x.get("cost"), int | float)]
    if costs:
        fresh.notes.append(f"DeepEval says these calls cost {prices.money(sum(costs))} in all.")
    plan.tool_version = version
    return fresh


__all__ = ["CANT", "classify", "metric_job", "parse_geval", "plan", "run"]
