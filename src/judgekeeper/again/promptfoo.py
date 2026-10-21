"""The plan for asking a promptfoo judge again.

promptfoo itself grades again (see `run` below). The plan reads the saved results files
again to rebuild the judge, and says:

- exactly your judge: the grader is named in the file and the same promptfoo version will run
  (the installed one when its version matches the file's `metadata.promptfooVersion`, else
  `npx promptfoo@<that version>`, which downloads it: the download is in the same yes/no
  question as the calls; with neither, the plan names `npm install promptfoo@<that version>`);
- a close copy: the file records no promptfoo version, or the grader is promptfoo's default,
  which the file never records (named "probably", from the key names present);
- can't: the grader was set with `--grader` (saved without its name), its settings hold a
  secret promptfoo hid (`[REDACTED]`), or the judge runs the user's own code: a grader that
  is not a model provider promptfoo calls over HTTP (MODEL_PROVIDERS, in any case: so never
  `package:`, `exec:`, `python:`, `file://`, or a URL or `webhook:`, which gets the answers),
  a rubric or rule that starts with `package:`, `file://` or another code prefix, a
  `transform` or `contextTransform` on the assertion, or a `transform...` option on the test
  or in the grader's settings (JavaScript promptfoo runs).

A version from the results file is used only when it reads as one (`1.2.3`, `1.2.3-beta.1`):
it goes into `npx promptfoo@<version>`, so anything else (an npm alias, a git URL, shell
characters) is said to be unreadable and never downloaded.

Answers are left out, and listed, when they are empty (promptfoo would call the provider
instead), or when a prompt-using judge type (factuality, closedqa, g-eval, answer-relevance,
context-*) would see template text (`{{`, `{%`, `{#`) that promptfoo fills in again.

`run` writes two temporary files next to the user's promptfoo config (so relative `file://` and
`exec:` paths work as in the original run): a config whose prompt is each answer's saved prompt
and whose provider is promptfoo's echo, and a tests file (kept separate, so promptfoo does not
fill `{{ env.X }}` into saved answers) with each labeled answer as a fixed answer
(`providerOutput`), its saved vars and only its model-graded assertions and grader, copied
unchanged. promptfoo then runs with `--no-cache --no-write --no-share` and its telemetry,
update check, sharing and logs off; `--grader` is never passed. The `env:` block of the user's
config (where a key may be set) goes into promptfoo's environment, never into a file. Both files are removed
afterwards, also after an error or Ctrl-C. Exit codes 0 and 100 (some test failed) both mean
finished. An llm-rubric answer whose new grading prompt is not byte for byte the saved one is
not counted.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from judgekeeper import again, find, keys, prices
from judgekeeper.again import CLOSE, EXACT, Plan, cant, left_out_line, not_marked
from judgekeeper.again.fresh import AgainError, Fresh, new_folder
from judgekeeper.anchors import canonical_json
from judgekeeper.readers.promptfoo import (
    AGENT_GRADED,
    _components,
    _options,
    _text,
    grader_of,
    is_set_grader,
    judge_type,
    read_promptfoo,
)
from judgekeeper.records import LLM, derive_record_id
from judgekeeper.redact import register_secret, scrub
from judgekeeper.table import make_fingerprint
from judgekeeper.textio import make_private, write_replacing

CALLS = {"llm-rubric": 1, "factuality": 1, "model-graded-factuality": 1,
         "model-graded-closedqa": 1, "context-recall": 1, "context-relevance": 1,
         "context-faithfulness": 2, "answer-relevance": 3, "search-rubric": 1}
AT_LEAST = {"conversation-relevance"}  # one call per message window
TRAJECTORY = "trajectory:goal-success"
AGENT_WHY = "your judge is an agent, which may look at things that changed since your eval ran"
PROMPT_TYPES = {"factuality", "model-graded-factuality", "model-graded-closedqa", "g-eval",
                "answer-relevance", "context-faithfulness", "context-recall",
                "context-relevance"}
TEMPLATE_MARKS = ("{{", "{%", "{#")
# A rule or rubric that starts with one of these is code or a file promptfoo loads
CODE_PREFIXES = ("exec:", "python:", "file://", "golang:", "ruby:", "javascript:", "package:")
# The providers in promptfoo's list (0.120 to 0.124) that call a model over HTTP: the only
# graders asked again. Any other (package:, exec:, a file, a URL, echo, an unknown name) is
# the person's own code, or sends the answers elsewhere.
MODEL_PROVIDERS = frozenset({
    "openai", "anthropic", "azure", "azureopenai", "bedrock", "vertex", "google", "gemini",
    "palm", "mistral", "ollama", "groq", "togetherai", "openrouter", "huggingface", "hf",
    "cohere", "deepseek", "perplexity", "xai", "ai21", "aimlapi", "alibaba", "alicloud",
    "aliyun", "dashscope", "cerebras", "cloudflare-ai", "cloudflare-gateway", "cometapi",
    "databricks", "fireworks", "github", "helicone", "hyperbolic", "litellm", "llamaapi",
    "localai", "minimax", "moonshot", "novita", "nscale", "nvidia", "portkey", "replicate",
    "sagemaker", "snowflake", "truefoundry", "vercel", "voyage", "watsonx"})
# In a grader's settings: a key that points it at another server (apiBaseUrl, apiHost,
# baseURL, endpoint, proxy...) or a value that is an address or a file
ADDRESS_KEY = re.compile(r"url|host|base|endpoint|proxy", re.IGNORECASE)
ADDRESS_VALUES = ("http://", "https://", "ws://", "wss://", "file://")
# Grader settings that run the user's code or read another server's reply
CODE_KEYS = ("functionToolCallbacks", "responseParser")
VERSION = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?")
CONFIG = ".judgekeeper-regrade.promptfoo.json"
TESTS = ".judgekeeper-regrade.tests.json"
RUN_ENV = {"PROMPTFOO_CACHE_ENABLED": "false", "PROMPTFOO_DISABLE_TELEMETRY": "1",
           "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "1",
           "PROMPTFOO_DISABLE_DEBUG_LOG": "1", "PROMPTFOO_DISABLE_ERROR_LOG": "1"}
FLAGS = ("--no-cache", "--no-write", "--no-share", "--no-table", "--no-progress-bar")
# Test options that change the saved answer or prompt, which already hold their effect.
DROPPED_OPTIONS = ("transform", "postprocess", "prefix", "suffix", "provider", "storeOutputAs")
SIDE_EFFECT = ("Your app or agent is not run. Nothing is written to promptfoo's database or "
               "shared.")
EXACT_WHY = "promptfoo re-grades your saved answers with your own settings"
NEW_WHY = "promptfoo grades your marked answers with your new judge's own settings"
NO_TEST = ("no test in your newest results matches it",
           "no test in your newest results matches them")


def calls_for(assertion: dict) -> int:
    kind = judge_type(assertion.get("type"))
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
        elif isinstance(v, str) and ("file://" in v.lower()
                                     or v.strip().lower().startswith(CODE_PREFIXES)):
            return True
    return False


def _model(provider_id: str) -> bool:
    """Whether a grader's id names a model provider promptfoo calls over HTTP."""
    plain = provider_id.strip().lower()
    return ":" in plain and plain.split(":", 1)[0] in MODEL_PROVIDERS and not _code([plain])


def _ids(value):
    """The provider ids in a grader: the grader itself when it is text, else every "id"."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k == "id" and isinstance(v, str):
                yield v
            elif isinstance(v, dict | list):
                yield from _ids(v)
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, dict):
                yield from _ids(v)


def _transforms(value) -> bool:
    """Whether a key anywhere in `value` starts with "transform" (JavaScript promptfoo runs)."""
    if isinstance(value, dict):
        return any(str(k).lower().startswith("transform") or _transforms(v)
                   for k, v in value.items())
    if isinstance(value, list):
        return any(_transforms(v) for v in value)
    return False


def _elsewhere(value) -> str | None:
    """The first key at any depth of a grader's settings that sends it to another server: a
    key naming an address, or a value that is an address or a file. None when there is none.
    The grader's own id is checked by _grader_code."""
    if isinstance(value, dict):
        for k, v in value.items():
            if ADDRESS_KEY.search(str(k)) or (
                    isinstance(v, str) and v.strip().lower().startswith(ADDRESS_VALUES)):
                return str(k)
            found = _elsewhere(v) if isinstance(v, dict | list) else None
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str) and v.strip().lower().startswith(ADDRESS_VALUES):
                return "a list"
            found = _elsewhere(v) if isinstance(v, dict | list) else None
            if found:
                return found
    return None


def _key(value, names) -> str | None:
    """The first key at any depth of `value` that is one of `names`."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in names:
                return str(k)
            found = _key(v, names) if isinstance(v, dict | list) else None
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _key(v, names)
            if found:
                return found
    return None


def _graders(value):
    """Each provider setting in a grader: the grader, and every dict in it with an "id"."""
    if isinstance(value, dict):
        if "id" in value:
            yield value
        for v in value.values():
            if isinstance(v, dict | list):
                yield from _graders(v)
    elif isinstance(value, list):
        for v in value:
            yield from _graders(v)


def _other_key(grader: dict) -> str | None:
    """apiKeyEnvar when it names a variable that is not the provider's own key."""
    name = (grader.get("config") or {}).get("apiKeyEnvar") if isinstance(
        grader.get("config"), dict) else None
    if name is None:
        return None
    provider = keys.PROVIDERS.get(keys.provider_of(_grader_id(grader)) or "")
    own = {n for alt in provider.keys for n in alt} if provider else set()
    return None if name in own else f"apiKeyEnvar {name}"


def _grader_code(grader) -> str | None:
    """What in a grader runs the user's code or sends the answers or the key elsewhere, or
    None. A results file comes with a project someone else may have written: a grader that
    reads another key or talks to another server is not your judge as you know it."""
    for i in _ids(grader):
        if not _model(i):
            return i
    found = _key(grader, CODE_KEYS)
    if found:
        return f"{found} in your grader's settings"
    if _transforms(grader):
        return "a transform in your grader's settings"
    for g in _graders(grader):
        found = _elsewhere({k: v for k, v in g.items() if k != "id"}) or _other_key(g)
        if found:
            return f"{found} in your grader's settings"
    return None


def _config(root: Path) -> Path | None:
    return next((root / n for n in find.PROMPTFOO_CONFIGS if (root / n).is_file()), None)


def _installed(root: Path) -> tuple[str, str] | None:
    """(command, version) of the project's promptfoo, else promptfoo on the PATH."""
    for command in (again.node_bin(root, "promptfoo"), again.which("promptfoo")):
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
            if judge_type((c.get("assertion") or {}).get("type")) is not None
            and ((c["assertion"].get("metric") or c["assertion"].get("type")) == metric)]


def _new_rows(ws, answers: list[dict], metric: str) -> tuple[dict, int]:
    """For a new judge: {answer id: (row, defaultTest, components)}, each marked answer's own
    saved answer put into its test in the newest results, found by the test's vars, with the
    new judge's assertions and grader. When the assertion is the same on every test, an
    answer whose test is not in the newest results keeps its old test's vars and prompt (if
    its old results file is still there), graded as the newest results grade (_with_grader).
    The new judge never graded these answers, so there is no saved
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
    template = next(iter(by_vars.values())) if len(shapes) == 1 and by_vars else None
    old = _rows(ws.root, (data.get("saved") or {}).get("results_files") or [])
    out, missing = {}, 0
    for a in answers:
        match = by_vars.get(canonical_json(a["input"] if isinstance(a["input"], dict) else {}))
        if match is not None:
            row, default_test, comps = match
        elif template is not None and a["id"] in old:
            row, default_test, comps = _with_grader(old[a["id"]][0], template)
        else:
            missing += 1
            continue
        row = {**row, "response": {**(row.get("response") or {}), "output": a["output"]}}
        comps = [{**c, "metadata": {k: v for k, v in (c.get("metadata") or {}).items()
                                    if k not in ("renderedGradingPrompt", "cachedResponse")}}
                 for c in comps]
        out[a["id"]] = (row, default_test, comps)
    return out, missing


GRADER_OPTIONS = ("provider", "rubricPrompt")  # a test's options that set how it is graded


def _with_grader(row: dict, template: tuple[dict, dict, list]) -> tuple[dict, dict, list]:
    """An old row whose test is not in the newest results, graded as the newest results grade:
    the grader and rubric prompt from a newest row's options, its defaultTest and its
    assertions. Nothing about grading comes from the old file."""
    new_row, default_test, comps = template
    old_opts = {k: v for k, v in _options(row.get("testCase")).items() if k not in GRADER_OPTIONS}
    new_opts = {k: v for k, v in _options(new_row.get("testCase")).items()
                if k in GRADER_OPTIONS}
    test_case = {**(row.get("testCase") or {}), "options": {**old_opts, **new_opts}}
    return {**row, "testCase": test_case}, default_test, comps


def plan(ws, answers: list[dict], opts, talk, dry: bool, new: bool = False) -> Plan:
    data = ws.data()
    root = ws.root
    metric = data["metric"]
    newest = json.loads((root / data["results_files"][0]).read_text(encoding="utf-8"))
    version = (newest.get("metadata") or {}).get("promptfooVersion")
    unreadable = bool(version) and not (isinstance(version, str) and VERSION.fullmatch(version))
    if unreadable:
        version = None
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
        if any(judge_type(c["assertion"].get("type")) in PROMPT_TYPES for c in comps) and any(
                m in t for t in texts for m in TEMPLATE_MARKS):
            templated += 1
            continue
        for c in comps:
            g = grader_of(c["assertion"], test_opts, default_test)
            graders.setdefault(canonical_json(g), g)
        judged.append((a, row, comps, test_opts, default_test))

    if opts.rule is not None:
        judged = _swapped(judged, opts.rule)
        if judged is None:
            return cant("promptfoo", data["judge"], again.NO_SWAP.format(
                what="this kind of promptfoo grader"), short="no rule to swap")
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
        own = _grader_code(g)
        if own:
            return cant("promptfoo", judge, f"your judge runs your own code ({own})",
                        short="your judge is your own code")
    for _, _, comps, test_opts, default_test in judged:
        for c in comps:
            a = c["assertion"]
            if (a.get("transform") or a.get("contextTransform")
                    or any(str(k).lower().startswith("transform") for k in test_opts
                           if k not in DROPPED_OPTIONS)
                    or _code([a.get("value"), a.get("rubricPrompt"),
                              test_opts.get("rubricPrompt"),
                              _options(default_test).get("rubricPrompt")])):
                return cant("promptfoo", judge,
                            "your judge runs your own code (a rule that loads a file or "
                            "package, or a transform)",
                            short="your judge is your own code")
    if not judged:
        return not_marked("promptfoo", judge)
    types = {judge_type(c["assertion"].get("type")) for j in judged for c in j[2]}
    if TRAJECTORY in types:
        return cant("promptfoo", judge, "your judge reads the trace of your app or agent's run, "
                                        "which your results don't keep",
                    short="your judge reads a trace")

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
    if unreadable:
        reasons.append("the promptfoo version in your results file can't be read")
    elif not version:
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
                plan = cant("promptfoo", judge,
                            "promptfoo is not installed here, and npx (Node.js) was not found "
                            f"to fetch promptfoo {version}", short="promptfoo is not installed")
                plan.install = f"npm install promptfoo@{version}"
                return plan
        elif not version and installed is None:
            return cant("promptfoo", judge, "promptfoo is not installed here",
                        short="promptfoo is not installed")
    if types & AGENT_GRADED:
        reasons.append(AGENT_WHY)
    if reasons:
        status, why = CLOSE, "; ".join(reasons)

    cached = any((c.get("metadata") or {}).get("cachedResponse") for j in judged for c in j[2])
    if cached or (newest.get("runtimeOptions") or {}).get("cache") is True:
        notes.append("Your saved decisions may be old replies from promptfoo's cache. "
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
            at_least |= judge_type(a.get("type")) in AT_LEAST | AGENT_GRADED
            embeddings |= judge_type(a.get("type")) == "answer-relevance"
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
                key_step=check.step, tool_version=version, runner=runner, download=download, payload=judged,
                job={"metric": metric},
                side_effects=[SIDE_EFFECT, (f"Two temporary files are written next to {where} "
                                            "and removed afterwards.")])


RULE_TYPES = frozenset({"llm-rubric", "g-eval", "model-graded-closedqa", "search-rubric"})


def _swapped(judged: list, rule: str) -> list | None:
    """`judged` with `rule` as the value of each grader that takes a rule, and no saved grading
    prompt to compare with (the new rule makes a new one); None when an answer has none."""
    out = []
    for a, row, comps, test_opts, default_test in judged:
        swapped = [{**c, "assertion": {**c["assertion"], "value": rule},
                    "metadata": {k: v for k, v in (c.get("metadata") or {}).items()
                                 if k != "renderedGradingPrompt"}}
                   if judge_type(c["assertion"].get("type")) in RULE_TYPES else c
                   for c in comps]
        if swapped == comps:
            return None
        out.append((a, row, swapped, test_opts, default_test))
    return out


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


def graders_handed(plan: Plan) -> set[str]:
    """The grader of each test judgekeeper hands to promptfoo (test_entry), by its id; the
    default grader, which the file never names, is left out."""
    ids = {_grader_id(test_entry(*p)["options"].get("provider")) for p in plan.payload}
    return {i for i in ids if i}


def _downloaded_version(plan: Plan) -> str | None:
    """The promptfoo version npx fetches for this plan (`promptfoo@<version>`), or None."""
    if not plan.download:
        return None
    return next((w.split("@", 1)[1] for w in plan.runner if w.startswith("promptfoo@")), None)


def _before(version: str, than: tuple[int, ...]) -> bool:
    parts = tuple(int(x) for x in re.findall(r"\d+", version)[:len(than)])
    return bool(parts) and parts < than


def regrade_config() -> dict:
    return {"description": "judgekeeper re-check (temporary file)",
            "prompts": ["{{judgekeeper_prompt}}"], "providers": ["echo"],
            "evaluateOptions": {"cache": False}, "tests": f"file://{TESTS}"}


def _config_env(config: Path | None) -> dict[str, str]:
    """The person's config's `env:` block (the values it can read), which promptfoo uses
    over the shell in their own runs: a key set there is the one their judge uses. Passed in
    promptfoo's environment, never written; each credential among them is scrubbed from
    everything judgekeeper writes or prints."""
    env = {k: v for k, v in keys.config_env(config).items() if isinstance(v, str)}
    for name, value in env.items():
        register_secret(name, value)
    return env


def _rendered(comps) -> list:
    return [(c.get("metadata") or {}).get("renderedGradingPrompt") for c in comps]


def run(ws, plan: Plan, talk) -> Fresh:
    """Have promptfoo grade the labeled answers again, `plan.times` times each."""
    root, metric = ws.root, plan.job.get("metric") or ws.data()["metric"]
    config = _config(root)
    folder = plan.folder or new_folder(ws)
    make_private(folder)
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
        write_replacing(files[0], json.dumps(regrade_config(), indent=1))
        write_replacing(files[1], json.dumps(tests, indent=1, ensure_ascii=False))
        if again.local_model(plan):
            talk.say(again.LOCAL_MODEL)
        progress = again.Progress(talk, None)  # promptfoo writes its results at the end
        with again.watching(progress.tick):
            proc = again.run_process(argv, cwd=root,
                                     env={**os.environ, **_config_env(config), **RUN_ENV})
    finally:
        for path in files:
            path.unlink(missing_ok=True)
    if proc.returncode not in (0, 100) or not out.is_file():
        version = _downloaded_version(plan)
        if version and _before(version, (0, 121)):  # 0.120 crashes right after npx fetches it
            raise AgainError(f"promptfoo {version} doesn't start after download. Run your eval "
                             "again with promptfoo 0.121 or newer.")
        tail = [x for x in (proc.stderr or proc.stdout or "").strip().splitlines() if x.strip()]
        raise AgainError("promptfoo did not finish: "
                         + (scrub(tail[-1]) if tail else f"exit code {proc.returncode}"))

    text = out.read_text(encoding="utf-8")
    write_replacing(out, scrub(text))  # a key that leaked into a reason, scrubbed
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
        fresh.notes.append(f"{cached} new decisions came from promptfoo's cache, although the "
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
        problems = [r.mark.problem for r in records]  # a grader error promptfoo saved as a fail
        if "error" in problems:
            fresh.not_counted[item_id] = "error"
            continue
        if any(problems) or any(r.label not in ("pass", "fail") for r in records):
            fresh.not_counted[item_id] = "no clear verdict"
            continue
        fresh.verdicts[item_id] = [r.label for r in records]
        fresh.scores[item_id] = [r.score for r in records]
        fresh.reasons[item_id] = [r.explanation or "" for r in records]
        fresh.models += [r.evaluator.get("model") for r in records]
        if not fresh.fingerprint:
            fresh.fingerprint = make_fingerprint(dict(records[0].evaluator)).to_dict()
    return fresh
