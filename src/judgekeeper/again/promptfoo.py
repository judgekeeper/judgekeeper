"""The plan for asking a promptfoo judge again.

promptfoo itself re-grades: each labeled answer goes into a temporary config as a fixed answer
(`providerOutput`), with its own model-graded assertion and grader copied unchanged, and
promptfoo runs with its cache, database, sharing, telemetry and logs off. The plan reads the
saved results files again to rebuild that judge, and says:

- exactly your judge: the grader is named in the file and the same promptfoo version will run
  (the installed one when its version matches the file's `metadata.promptfooVersion`, else
  `npx promptfoo@<that version>`, which downloads it and is asked about first);
- a close copy: the file records no promptfoo version, or the grader is promptfoo's default,
  which the file never records (named "probably", from the key names present);
- can't: the grader was set with `--grader` (saved without its name), its settings hold a
  secret promptfoo hid (`[REDACTED]`), or the judge runs the user's own code (a `file://`,
  `exec:` or `python:` grader or rubric).

Answers are left out, and listed, when they are empty (promptfoo would call the provider
instead), or when a prompt-using judge type (factuality, closedqa, g-eval, answer-relevance,
context-*) would see template text (`{{`, `{%`, `{#`) that promptfoo fills in again.

`run` writes two temporary files next to the user's promptfoo config (so relative `file://`
and `exec:` paths work as in the original run): a config whose prompt is each answer's saved
prompt and whose provider is promptfoo's echo, and a tests file (kept separate, so promptfoo
does not fill `{{ env.X }}` into saved answers) with each labeled answer as `providerOutput`,
its saved vars and only its model-graded assertions and grader, copied unchanged. promptfoo
then runs with `--no-cache --no-write --no-share` and its telemetry, update check, sharing and
logs off; `--grader` is never passed. Both files are removed afterwards, also after an error or
Ctrl-C. Exit codes 0 and 100 (some test failed) both mean finished. An llm-rubric answer whose
new grading prompt is not byte for byte the saved one is not counted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from judgekeeper import again, find, keys, prices
from judgekeeper.again import CLOSE, EXACT, Plan, cant, left_out_line
from judgekeeper.again.fresh import AgainError, Fresh, new_folder
from judgekeeper.anchors import canonical_json
from judgekeeper.readers.promptfoo import (
    MODEL_GRADED,
    _components,
    _options,
    _text,
    grader_of,
    is_set_grader,
    read_promptfoo,
)
from judgekeeper.records import LLM, derive_record_id
from judgekeeper.redact import scrub
from judgekeeper.table import make_fingerprint

CALLS = {"llm-rubric": 1, "factuality": 1, "model-graded-factuality": 1,
         "model-graded-closedqa": 1, "context-recall": 1, "context-relevance": 1,
         "context-faithfulness": 2, "answer-relevance": 3, "search-rubric": 1}
AT_LEAST = {"conversation-relevance"}  # one call per message window
PROMPT_TYPES = {"factuality", "model-graded-factuality", "model-graded-closedqa", "g-eval",
                "answer-relevance", "context-faithfulness", "context-recall",
                "context-relevance"}
TEMPLATE_MARKS = ("{{", "{%", "{#")
CODE_PREFIXES = ("exec:", "python:", "file://", "golang:", "ruby:", "javascript:")
CONFIG = ".judgekeeper-regrade.promptfoo.json"
TESTS = ".judgekeeper-regrade.tests.json"
RUN_ENV = {"PROMPTFOO_CACHE_ENABLED": "false", "PROMPTFOO_DISABLE_TELEMETRY": "1",
           "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "1",
           "PROMPTFOO_DISABLE_DEBUG_LOG": "1", "PROMPTFOO_DISABLE_ERROR_LOG": "1"}
FLAGS = ("--no-cache", "--no-write", "--no-share", "--no-table", "--no-progress-bar")
# Test options that change the saved answer or prompt, which already hold their effect.
DROPPED_OPTIONS = ("transform", "postprocess", "prefix", "suffix", "provider", "storeOutputAs")
SIDE_EFFECT = "Your app is not run. Nothing is written to promptfoo's database or shared."
EXACT_WHY = "promptfoo re-grades your saved answers with your own settings"
NEW_WHY = "promptfoo grades your marked answers with your new judge's own settings"
NO_TEST = ("no test in your newest results matches it",
           "no test in your newest results matches them")


def calls_for(assertion: dict) -> int:
    kind = assertion.get("type")
    if kind == "g-eval":
        value = assertion.get("value")
        return 2 * (len(value) if isinstance(value, list) and value else 1)
    return CALLS.get(kind, 1)


def _grader_id(grader) -> str | None:
    if isinstance(grader, str):
        return grader
    if isinstance(grader, dict) and isinstance(grader.get("id"), str):
        return grader["id"]
    return None


def _code(values) -> bool:
    for v in values:
        if isinstance(v, list):
            if _code(v):
                return True
        elif isinstance(v, str) and ("file://" in v or v.startswith(CODE_PREFIXES)):
            return True
    return False


def _config(root: Path) -> Path | None:
    return next((root / n for n in find.PROMPTFOO_CONFIGS if (root / n).is_file()), None)


def _installed(root: Path) -> tuple[str, str] | None:
    """(command, version) of the project's promptfoo, else promptfoo on the PATH."""
    local = root / "node_modules" / ".bin" / "promptfoo"
    for command in ([str(local)] if local.exists() else []) + [again.which("promptfoo")]:
        if not command:
            continue
        proc = again.run_process([command, "--version"], cwd=root, timeout=60)
        out = (proc.stdout or "").strip().splitlines()
        if proc.returncode == 0 and out:
            return command, out[-1].strip()
    return None


def _rows(root: Path, files: list[str]) -> dict[str, tuple[dict, dict]]:
    """{answer id: (row, defaultTest)} from promptfoo results files, newest first: the newest
    row of an answer wins."""
    rows: dict[str, tuple[dict, dict]] = {}
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        default_test = (d.get("config") or {}).get("defaultTest") or {}
        for row in (d.get("results") or {}).get("results") or []:
            key = derive_record_id(row.get("vars"), _text((row.get("response") or {})
                                                           .get("output")))
            rows.setdefault(key, (row, default_test if isinstance(default_test, dict) else {}))
    return rows


def _judged(row: dict, metric: str) -> list[dict]:
    """The row's model-graded components of the judge `metric`."""
    return [c for c in _components(row.get("gradingResult"))
            if (c.get("assertion") or {}).get("type") in MODEL_GRADED
            and ((c["assertion"].get("metric") or c["assertion"].get("type")) == metric)]


def _new_rows(ws, answers: list[dict], metric: str) -> tuple[dict, int]:
    """For a new judge: {answer id: (row, defaultTest, components)}, each marked answer's own
    saved answer put into its test in the newest results, found by the test's vars, with the
    new judge's assertions and grader. When the assertion is the same on every test, an
    answer whose test is not in the newest results keeps its old test (if its old results
    file is still there). The new judge never graded these answers, so there is no saved
    grading prompt to compare. Returns those and how many answers have no test."""
    data = ws.data()
    newest = _rows(ws.root, data["results_files"])
    by_vars: dict[str, tuple[dict, dict, list]] = {}
    shapes = set()
    for row, default_test in newest.values():
        comps = _judged(row, metric)
        if comps:
            by_vars.setdefault(canonical_json(row.get("vars") or {}), (row, default_test, comps))
            shapes.add(canonical_json([c["assertion"] for c in comps]))
    common = next(iter(by_vars.values()))[2] if len(shapes) == 1 and by_vars else None
    old = _rows(ws.root, (data.get("saved") or {}).get("results_files") or [])
    out, missing = {}, 0
    for a in answers:
        match = by_vars.get(canonical_json(a["input"] if isinstance(a["input"], dict) else {}))
        if match is not None:
            row, default_test, comps = match
        elif common is not None and a["id"] in old:
            (row, default_test), comps = old[a["id"]], common
        else:
            missing += 1
            continue
        row = {**row, "response": {**(row.get("response") or {}), "output": a["output"]}}
        comps = [{**c, "metadata": {k: v for k, v in (c.get("metadata") or {}).items()
                                    if k not in ("renderedGradingPrompt", "cachedResponse")}}
                 for c in comps]
        out[a["id"]] = (row, default_test, comps)
    return out, missing


def plan(ws, answers: list[dict], opts, talk, dry: bool, new: bool = False) -> Plan:
    data = ws.data()
    root = ws.root
    metric = data["metric"]
    newest = json.loads((root / data["results_files"][0]).read_text(encoding="utf-8"))
    version = (newest.get("metadata") or {}).get("promptfooVersion")
    if new:
        matched, no_test = _new_rows(ws, answers, metric)
    else:
        rows, no_test = _rows(root, data["results_files"]), 0
        matched = {a["id"]: (*rows[a["id"]], _judged(rows[a["id"]][0], metric))
                   for a in answers if a["id"] in rows}

    judged, gone, empty, templated = [], 0, 0, 0
    graders: dict[str, object] = {}
    for a in answers:
        if a["id"] not in matched:
            gone += 0 if new else 1
            continue
        row, default_test, comps = matched[a["id"]]
        test_opts = _options(row.get("testCase"))
        if not comps:
            gone += 1
            continue
        output = (row.get("response") or {}).get("output")
        if output is None or output == "":
            empty += 1
            continue
        texts = [(row.get("prompt") or {}).get("raw") or ""]
        texts += [v for v in (row.get("vars") or {}).values() if isinstance(v, str)]
        if any(c["assertion"].get("type") in PROMPT_TYPES for c in comps) and any(
                m in t for t in texts for m in TEMPLATE_MARKS):
            templated += 1
            continue
        for c in comps:
            g = grader_of(c["assertion"], test_opts, default_test)
            graders.setdefault(canonical_json(g), g)
        judged.append((a, row, comps, test_opts, default_test))

    judge = f"{data['judge']} (promptfoo {version})" if version else data["judge"]
    for g in graders.values():
        if is_set_grader(g):
            return cant("promptfoo", judge,
                        "your grader was set with --grader, and promptfoo saves it without its "
                        "name. Put the grader in your config (defaultTest.options.provider) and "
                        "run your eval again", short="your grader was set with --grader")
        if g is not None and "[REDACTED]" in canonical_json(g):
            return cant("promptfoo", judge,
                        "your grader's settings hold a secret written in the config, which "
                        "promptfoo hides in the results", short="your grader holds a secret")
        if _code([_grader_id(g)]):
            return cant("promptfoo", judge, f"your judge runs your own code ({_grader_id(g)})",
                        short="your judge is your own code")
    for _, _, comps, test_opts, default_test in judged:
        for c in comps:
            a = c["assertion"]
            if _code([a.get("value"), a.get("rubricPrompt"), a.get("transform"),
                      a.get("contextTransform"), test_opts.get("rubricPrompt"),
                      _options(default_test).get("rubricPrompt")]):
                return cant("promptfoo", judge,
                            "your judge runs your own code (a file:// rubric or transform)",
                            short="your judge is your own code")
    if not judged:
        return cant("promptfoo", judge, "none of your labeled answers can be graded again",
                    short="no answer can be graded again")

    config = _config(root)
    grader = next(iter(graders.values()))
    reasons, notes = [], []
    key_env = None
    if grader is None:
        default = keys.promptfoo_default(root, config, version)
        model, provider = default.model, default.family
        reasons.append(f"{default.words}; the results file does not say which model graded")
    else:
        model = _grader_id(grader)
        provider = keys.provider_of(model)
        if isinstance(grader, dict):
            key_env = (grader.get("config") or {}).get("apiKeyEnvar")
    if len(graders) > 1:
        notes.append(f"Your answers were graded by {len(graders)} different graders; the "
                     "first is named here.")
    status, why = EXACT, NEW_WHY if new else EXACT_WHY
    runner, download = [], False
    if not version:
        reasons.append("promptfoo version not recorded")
    if dry:
        installed = _installed(root)
        runner = [installed[0]] if installed else []
        if version and (installed is None or installed[1] != version):
            npx = again.which("npx")
            if npx:
                runner, download = [npx, "--yes", f"promptfoo@{version}"], True
                notes.append(
                    (f"Your promptfoo is {installed[1]}; your results were made with promptfoo "
                     if installed else "promptfoo is not installed here; your results were "
                     "made with promptfoo ")
                    + f"{version}. judgekeeper would run npx --yes promptfoo@{version}, which "
                    "downloads it; it asks first.")
            elif installed:
                reasons.append(f"your promptfoo is {installed[1]} and your results were made "
                               f"with {version}")
            else:
                return cant("promptfoo", judge,
                            "promptfoo is not installed here, and npx (Node.js) was not found "
                            f"to fetch promptfoo {version}", short="promptfoo is not installed")
        elif not version and installed is None:
            return cant("promptfoo", judge, "promptfoo is not installed here",
                        short="promptfoo is not installed")
    if reasons:
        status, why = CLOSE, "; ".join(reasons)

    cached = any((c.get("metadata") or {}).get("cachedResponse") for j in judged for c in j[2])
    if cached or (newest.get("runtimeOptions") or {}).get("cache") is True:
        notes.append("Your saved verdicts may be old replies from promptfoo's cache. "
                     "judgekeeper turns the cache off when it asks again.")
    check = keys.check(model, "promptfoo", root, provider=provider, config=config,
                       key_env=key_env)

    calls_each, tokens, at_least, embeddings = [], [], False, False
    for _, row, comps, _, _ in judged:
        n, inp, out = 0, 0, 0
        for c in comps:
            a = c["assertion"]
            calls = calls_for(a)
            n += calls
            at_least |= a.get("type") in AT_LEAST
            embeddings |= a.get("type") == "answer-relevance"
            used = c.get("tokensUsed") or {}
            if used.get("prompt"):
                inp += int(used["prompt"])
                out += int(used.get("completion") or 0)
                continue
            rendered = (c.get("metadata") or {}).get("renderedGradingPrompt")
            text = rendered if isinstance(rendered, str) else " ".join(
                [_text(a.get("value")) or "", _text((row.get("response") or {})
                                                    .get("output")) or "",
                 canonical_json(row.get("vars") or {})])
            i, o = prices.tokens_from_text(text)
            inp, out = inp + i * calls, out + o * calls
        calls_each.append(n)
        tokens.append((inp, out))

    left = []
    if no_test:
        left.append(left_out_line(no_test, *NO_TEST))
    if gone:
        left.append(left_out_line(gone, "it is not in your results files any more",
                                  "they are not in your results files any more"))
    if empty:
        left.append(left_out_line(empty, "it is empty", "they are empty"))
    if templated:
        left.append(left_out_line(
            templated, "its saved prompt or input holds template text ({{ ... }}) that "
            "promptfoo would fill in again", "their saved prompts or inputs hold template text "
            "({{ ... }}) that promptfoo would fill in again"))
    where = config.name if config else "your results file"
    return Plan(tool="promptfoo", judge=judge, status=status, why=why, model=model,
                provider=provider, key_lines=check.lines, notes=notes,
                calls_each=calls_each, calls_note="at least" if at_least else "",
                extra_calls="plus 4 embedding calls per answer" if embeddings else "",
                tokens=tokens, left_out=left, settings=check.settings, key_ok=check.ok,
                tool_version=version, runner=runner, download=download, payload=judged,
                job={"metric": metric},
                side_effects=[SIDE_EFFECT, (f"Two temporary files are written next to {where} "
                                            "and removed afterwards.")])


# Asking again ---------------------------------------------------------------------------------

def test_entry(answer: dict, row: dict, comps: list, test_opts: dict, default_test: dict) -> dict:
    """One labeled answer as a promptfoo test: its saved answer and prompt, its vars, and only
    its model-graded assertions and grader, copied unchanged."""
    options = {k: v for k, v in test_opts.items() if k not in DROPPED_OPTIONS}
    grader = grader_of(comps[0]["assertion"], test_opts, default_test)
    if grader is not None:
        options["provider"] = grader
    rubric = test_opts.get("rubricPrompt") or _options(default_test).get("rubricPrompt")
    if rubric and "rubricPrompt" not in options:
        options["rubricPrompt"] = rubric
    variables = dict(row.get("vars") or {})
    variables["judgekeeper_prompt"] = (row.get("prompt") or {}).get("raw") or ""
    return {"description": answer["id"], "vars": variables,
            "providerOutput": (row.get("response") or {}).get("output"), "options": options,
            "assert": [dict(c["assertion"]) for c in comps]}


def regrade_config() -> dict:
    return {"description": "judgekeeper re-check (temporary file)",
            "prompts": ["{{judgekeeper_prompt}}"], "providers": ["echo"],
            "evaluateOptions": {"cache": False}, "tests": f"file://{TESTS}"}


def _rendered(comps) -> list:
    return [(c.get("metadata") or {}).get("renderedGradingPrompt") for c in comps]


def run(ws, plan: Plan, talk) -> Fresh:
    """Have promptfoo grade the labeled answers again, `plan.times` times each."""
    root, metric = ws.root, plan.job.get("metric") or ws.data()["metric"]
    config = _config(root)
    folder = plan.folder or new_folder(ws)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "promptfoo.json"
    rel_out = out.relative_to(root).as_posix()
    argv = [*plan.runner, "eval", "-c", CONFIG, "--repeat", str(plan.times), *FLAGS,
            "-o", rel_out]
    tests = [test_entry(*p) for p in plan.payload]
    talk.say(f"Writing {CONFIG} and {TESTS} next to "
             f"{config.name if config else 'your results'}; they are removed when promptfoo is "
             "done.")
    files = (root / CONFIG, root / TESTS)
    try:
        files[0].write_text(json.dumps(regrade_config(), indent=1), encoding="utf-8")
        files[1].write_text(json.dumps(tests, indent=1, ensure_ascii=False), encoding="utf-8")
        proc = again.run_process(argv, cwd=root, env={**os.environ, **RUN_ENV})
    finally:
        for path in files:
            path.unlink(missing_ok=True)
    if proc.returncode not in (0, 100) or not out.is_file():
        tail = [x for x in (proc.stderr or proc.stdout or "").strip().splitlines() if x.strip()]
        raise AgainError("promptfoo did not finish: "
                         + (scrub(tail[-1]) if tail else f"exit code {proc.returncode}"))

    text = out.read_text(encoding="utf-8")
    out.write_text(scrub(text), encoding="utf-8")  # a key that leaked into a reason, scrubbed
    new = json.loads(text)
    prompts: dict[str, list] = {}
    cached = 0
    for row in (new.get("results") or {}).get("results") or []:
        key = (row.get("testCase") or {}).get("description") or row.get("description")
        comps = [c for c in _components(row.get("gradingResult"))
                 if ((c.get("assertion") or {}).get("metric")
                     or (c.get("assertion") or {}).get("type")) == metric]
        prompts.setdefault(key, []).extend(_rendered(comps))
        cached += sum(bool((c.get("metadata") or {}).get("cachedResponse")) for c in comps)
    judged: dict[str, dict[int, object]] = {}
    for r in read_promptfoo(out):
        if r.annotator_kind == LLM and r.name == metric:
            judged.setdefault(r.target_id, {})[r.run or 1] = r
    fresh = Fresh(folder=folder, source={"kind": "promptfoo", "file": out.name})
    if cached:
        fresh.notes.append(f"{cached} new verdicts came from promptfoo's cache, although the "
                           "cache was off.")
    for answer, _, comps, _, _ in plan.payload:
        item_id = answer["id"]
        saved = [p for p in _rendered(comps) if isinstance(p, str)]
        if saved and any(p not in saved for p in prompts.get(item_id, []) if p is not None):
            fresh.not_counted[item_id] = "grading prompt differs"
            continue
        runs = judged.get(item_id, {})
        records = [runs.get(t + 1) for t in range(plan.times)]
        if any(r is None for r in records):
            fresh.not_counted[item_id] = "missing"
            continue
        if any(r.label not in ("pass", "fail") for r in records):
            fresh.not_counted[item_id] = "no clear verdict"
            continue
        fresh.verdicts[item_id] = [r.label for r in records]
        fresh.scores[item_id] = [r.score for r in records]
        fresh.reasons[item_id] = [r.explanation or "" for r in records]
        if not fresh.fingerprint:
            fresh.fingerprint = make_fingerprint(dict(records[0].evaluator)).to_dict()
    return fresh
