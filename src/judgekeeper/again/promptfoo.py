"""The plan for asking a promptfoo LLM-as-a-judge again, and the run.

The plan rebuilds the LLM-as-a-judge from the saved results. Exactly your LLM-as-a-judge when
the grader is named and the same promptfoo version runs (installed, or fetched with npx after
a yes); a close copy otherwise. It can't when the grader was set with `--grader`, holds a
hidden secret, or runs the user's own code: anything but a model provider promptfoo calls over
HTTP, an agent with tools, a rule, var, saved prompt or transform that loads a file or package,
template code in the rule, rubric prompt or grader, or a grader setting outside a list known to
be safe. Each provider promptfoo would load from a grader is checked, also in a map by output
type ({"text": ...}). It can't either when the config's `env:` block sets a name other than a
key, or a `.env` sets one that starts a program or points the calls elsewhere. An answer whose
saved prompt or vars hold template code is left out. A version goes into
`npx promptfoo@<version>` only when it reads as one.

`run` writes a temporary config and tests file next to the user's config, each answer as a
fixed `providerOutput` with its saved vars and only its model-graded assertions. promptfoo runs
with no cache, no writes, no sharing and telemetry off; the keys in the config's `env:` block
go into promptfoo's environment, never into a file. Both files are removed afterwards, also on
Ctrl-C.
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
from judgekeeper.textio import make_private, read_json, write_replacing

CALLS = {"llm-rubric": 1, "factuality": 1, "model-graded-factuality": 1,
         "model-graded-closedqa": 1, "context-recall": 1, "context-relevance": 1,
         "context-faithfulness": 2, "answer-relevance": 3, "search-rubric": 1}
AT_LEAST = {"conversation-relevance"}  # one call per message window
TRAJECTORY = "trajectory:goal-success"
AGENT_WHY = ("your LLM-as-a-judge is an agent, which may look at things that changed since your "
             "eval ran")
PROMPT_TYPES = {"factuality", "model-graded-factuality", "model-graded-closedqa", "g-eval",
                "answer-relevance", "context-faithfulness", "context-recall",
                "context-relevance"}
TEMPLATE_MARKS = ("{{", "{%", "{#")
# A rule or rubric that starts with one of these is code or a file promptfoo loads
CODE_PREFIXES = ("exec:", "python:", "file://", "golang:", "ruby:", "javascript:", "package:")
PROMPT_VAR = "judgekeeper_prompt"  # the var each test's saved prompt goes in
# promptfoo fills templates in (nunjucks, which can call anything) in the saved prompt, the
# vars, a file a var loads, the rule, the rubric prompt and the grader's settings. Template
# code is a tag ({% %}), a comment ({# #}) or a {{ }} holding more than a plain or dotted
# name: {{ output }} and {{ vars.topic }} only fill in a value. {{ env.NAME }} counts as code:
# it reads promptfoo's environment, where the keys are.
_FILL = re.compile(r"\{\{-?\s*(?!env\b)[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*-?\}\}")
# A plain {{ name }} or {{ vars.name }}: where a var's value goes
_PLAIN = re.compile(r"\{\{-?\s*(?:vars\.)?([A-Za-z_]\w*)\s*-?\}\}")
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
# The kinds of provider, after its name (`openai:codex-sdk`), that run an agent with tools
# instead of sending a prompt to a model and reading its text back: never asked again.
AGENT_TYPES = frozenset({
    "claude-agent-sdk", "claude-code", "agents", "agents-api", "assistant", "chatkit", "codex",
    "codex-sdk", "codex-app-server", "codex-desktop", "codex-security", "foundry-agent"})
# In a grader's settings: a key that points it at another server (apiBaseUrl, apiHost,
# baseURL, endpoint, proxy...) or a value that is an address or a file
ADDRESS_KEY = re.compile(r"url|host|base|endpoint|proxy", re.IGNORECASE)
ADDRESS_VALUES = ("http://", "https://", "ws://", "wss://", "file://")
# Grader settings that run the user's code or read another server's reply
CODE_KEYS = ("functionToolCallbacks", "responseParser")
# The only settings a grader may have: promptfoo 0.124's model providers read each of them as
# a model setting that never loads a file, starts a program or names another server. A
# number, or a word of the shape its key takes (a region goes into the server's address, so
# it is only letters, digits and dashes). Any other setting (mcp, tools, headers, a new one)
# is not asked: the person can ask for one to be added.
GRADER_KEYS = ("id", "label", "config")
GRADER_TYPES = ("text", "embedding", "classification", "moderation")  # a grader per kind
NUMBER_SETTINGS = frozenset({
    "temperature", "max_tokens", "maxTokens", "max_completion_tokens", "top_p", "topP",
    "top_k", "topK", "seed", "presence_penalty", "frequency_penalty"})
WORD_SETTINGS = {
    "reasoning_effort": re.compile(r"minimal|low|medium|high"),
    "region": re.compile(r"[a-z]{2,}(-[a-z0-9]+)+"),
    "location": re.compile(r"[a-z]{2,}(-[a-z0-9]+)+"),
    "projectId": re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
    "apiVersion": re.compile(r"\d{4}-\d{2}-\d{2}(-preview)?|v\d+(alpha|beta)?\d*"),
    "organization": re.compile(r"org-[A-Za-z0-9]{1,64}"),
    "apiKeyEnvar": re.compile(r"[A-Za-z_][A-Za-z0-9_]*"),  # which one: _other_key
}
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?")
CONFIG = ".judgekeeper-regrade.promptfoo.json"
TESTS = ".judgekeeper-regrade.tests.json"
RUN_ENV = {"PROMPTFOO_CACHE_ENABLED": "false", "PROMPTFOO_DISABLE_TELEMETRY": "1",
           "PROMPTFOO_DISABLE_UPDATE": "1", "PROMPTFOO_DISABLE_SHARING": "1",
           "PROMPTFOO_DISABLE_DEBUG_LOG": "1", "PROMPTFOO_DISABLE_ERROR_LOG": "1"}
FLAGS = ("--no-cache", "--no-write", "--no-share", "--no-table", "--no-progress-bar")
# Test options that change the saved answer or prompt, which already hold their effect.
DROPPED_OPTIONS = ("transform", "postprocess", "prefix", "suffix", "provider", "storeOutputAs")
SIDE_EFFECT = ("Your eval's code is not run. Nothing is written to promptfoo's database or "
               "shared.")
EXACT_WHY = "promptfoo re-grades your saved answers with your own settings"
NEW_WHY = "promptfoo grades your marked answers with your new LLM-as-a-judge's own settings"
NO_TEST = ("no test in your newest results matches it",
           "no test in your newest results matches them")
TEMPLATED = (("its saved prompt or input holds template text ({{ ... }}) that promptfoo would "
              "fill in again"),
             ("their saved prompts or inputs hold template text ({{ ... }}) that promptfoo "
              "would fill in again"))


def calls_for(assertion: dict) -> int:
    kind = judge_type(assertion.get("type"))
    if kind == "g-eval":
        value = assertion.get("value")
        return 2 * (len(value) if isinstance(value, list) and value else 1)
    return CALLS.get(kind, 1)


def _text_grader(grader):
    """The grader promptfoo grades text with: the grader, or the "text" one of a map by
    output type."""
    while isinstance(grader, dict) and grader.get("text") is not None:
        grader = grader["text"]
    return grader


def _grader_id(grader) -> str | None:
    grader = _text_grader(grader)
    if isinstance(grader, str):
        return grader
    if isinstance(grader, dict) and isinstance(grader.get("id"), str):
        return grader["id"]
    return None


def loaded(grader) -> tuple[list[str], list[dict]]:
    """(every provider id promptfoo would load from a grader, every settings dict with an
    id). promptfoo takes a grader as text, as {id, config...}, or as a map by output type
    ({"text": ..., "embedding": ...}), whose values are graders too; it looks in the map
    before the id."""
    ids: list[str] = []
    settings: list[dict] = []

    def walk(value) -> None:
        if isinstance(value, str):
            ids.append(value)
        elif isinstance(value, dict):
            for kind in GRADER_TYPES:
                if value.get(kind) is not None:
                    walk(value[kind])
            if "id" in value:
                settings.append(value)
                if isinstance(value["id"], str):
                    ids.append(value["id"])
    walk(grader)
    return ids, settings


def _code(values) -> bool:
    for v in values:
        if isinstance(v, list):
            if _code(v):
                return True
        elif isinstance(v, str) and ("file://" in v.lower()
                                     or v.strip().lower().startswith(CODE_PREFIXES)):
            return True
    return False


def template_code(text) -> bool:
    """Whether `text` holds template code promptfoo would run (_FILL)."""
    return isinstance(text, str) and (
        "{%" in text or "{#" in text or "{{" in _FILL.sub("", text))


def split_code(test: dict) -> bool:
    """Whether the saved prompt, the rule or the rubric of a test holds template code only once
    its own vars are filled in, once: {{a}}{{b}} with a = "{" and b = "{ env.X }}". Each part
    alone is clean; a promptfoo that fills templates in twice would run the whole."""
    variables = test.get("vars") or {}

    def filled(text: str) -> str:
        return _PLAIN.sub(lambda m: v if isinstance(v := variables.get(m[1]), str) else m[0],
                          text)
    texts = [variables.get(PROMPT_VAR), (test.get("options") or {}).get("rubricPrompt"),
             [[a.get("value"), a.get("rubricPrompt")] for a in test.get("assert") or []]]
    return any(template_code(filled(t)) and not template_code(t) for t in _strings(texts))


def _strings(value):
    """Every string in `value`, inside lists and objects too."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def loads_code(test: dict) -> str | None:
    """What in a test judgekeeper hands to promptfoo would make promptfoo run code, or None:
    a value that loads a file or a package, or template code. Every string in it is looked
    at: the saved prompt, the answer, the vars, the assertions and the grader. promptfoo never
    fills in the answer, so only it may hold template code."""
    for name, value in (test.get("vars") or {}).items():
        if _code(_strings(value)):
            return ("a saved prompt that loads a file or script" if name == PROMPT_VAR
                    else "a var that loads a file or script")
    if _code(_strings(test.get("providerOutput"))):
        return "a saved answer that loads a file or script"
    if _code(_strings({k: v for k, v in test.items() if k not in ("vars", "providerOutput")})):
        return "a rule or grader setting that loads a file or script"
    if any(template_code(v) for v in _strings({k: v for k, v in test.items()
                                                if k != "providerOutput"})) or split_code(test):
        return "template code, which promptfoo would run"
    return None


def _model(provider_id: str) -> bool:
    """Whether a grader's id names a model provider promptfoo calls over HTTP (an agent is
    not one: _agent)."""
    plain = provider_id.strip().lower()
    return ":" in plain and plain.split(":", 1)[0] in MODEL_PROVIDERS and not _code([plain])


def _agent(grader) -> str | None:
    """The id in a grader of a provider that runs an agent with tools, or None."""
    for i in loaded(grader)[0]:
        parts = i.strip().lower().split(":")
        if len(parts) > 1 and parts[0] in MODEL_PROVIDERS and parts[1] in AGENT_TYPES:
            return i
    return None


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
    ids, settings = loaded(grader)
    for i in ids:
        if not _model(i):
            return i
    found = _key(grader, CODE_KEYS)
    if found:
        return f"{found} in your grader's settings"
    if _transforms(grader):
        return "a transform in your grader's settings"
    for g in settings:
        found = _elsewhere({k: v for k, v in g.items() if k != "id"}) or _other_key(g)
        if found:
            return f"{found} in your grader's settings"
    return None


def _unknown_setting(grader) -> str | None:
    """Why a grader holds a setting judgekeeper does not know is safe (GRADER_KEYS,
    NUMBER_SETTINGS, WORD_SETTINGS), or None."""
    if grader is None:
        return None
    if isinstance(grader, str):
        return ("its setting `id` holds template code, which promptfoo would run"
                if template_code(grader) else None)
    if not isinstance(grader, dict):
        return "its grader is not a setting judgekeeper knows is safe"
    if "id" not in grader:
        for k, v in grader.items():
            found = (_unknown_setting(v) if k in GRADER_TYPES
                     else f"its setting `{k}` is not one judgekeeper knows is safe")
            if found:
                return found
        return None
    for k, v in grader.items():
        if k not in GRADER_KEYS or (k == "config" and v is not None and not isinstance(v, dict)):
            return f"its setting `{k}` is not one judgekeeper knows is safe"
        if k != "config" and not isinstance(v, str):
            return f"its setting `{k}` has a value judgekeeper doesn't know is safe"
        if template_code(v):
            return f"its setting `{k}` holds template code, which promptfoo would run"
    for k, v in (grader.get("config") or {}).items():
        if k in NUMBER_SETTINGS:
            known = isinstance(v, int | float) and not isinstance(v, bool)
        elif k in WORD_SETTINGS:
            known = isinstance(v, str) and bool(WORD_SETTINGS[k].fullmatch(v))
        else:
            return f"its setting `{k}` is not one judgekeeper knows is safe"
        if not known:
            return f"its setting `{k}` has a value judgekeeper doesn't know is safe"
    return None


def grader_refusal(grader) -> tuple[str, str] | None:
    """(why, short) when a grader is not asked again: an agent, the user's own code or
    another server, or a setting not known to be safe. Checked on each provider promptfoo
    would load from it (loaded), in the plan and again on the tests handed to promptfoo."""
    agent = _agent(grader)
    if agent:
        return (f"your LLM-as-a-judge is an agent that can use tools ({agent})",
                "your LLM-as-a-judge is an agent")
    own = _grader_code(grader)
    if own:
        return (f"your LLM-as-a-judge runs your own code ({own})",
                "your LLM-as-a-judge is your own code")
    unknown = _unknown_setting(grader)
    if unknown:
        return unknown, "your grader has a setting judgekeeper doesn't know is safe"
    return None


# A name in the project's .env (which promptfoo reads itself) that starts a program or points
# the calls at another server. NO_PROXY can only skip a proxy, so it is allowed.
STARTS = ("NODE_", "LD_", "DYLD_", "NPM_CONFIG_", "PYTHON")
PROGRAMS = {"PATH", "COMSPEC", "SHELL", "BASH_ENV", "ENV"}
REDIRECTS = ("BASE_URL", "API_BASE", "HOST", "ENDPOINT", "PROXY")


def _passed_on(graders) -> set[str]:
    """The names of the config's `env:` block passed on to promptfoo: the key names of the
    providers judgekeeper knows and each grader's apiKeyEnvar (checked by _other_key). Any
    other can start a program (NODE_OPTIONS, PATH) or send the calls elsewhere."""
    names = {n for provider in keys.PROVIDERS.values() for alt in provider.keys for n in alt}
    for g in graders:
        for s in loaded(g)[1]:
            config = s.get("config")
            if isinstance(config, dict) and isinstance(config.get("apiKeyEnvar"), str):
                names.add(config["apiKeyEnvar"])
    return names


def env_refusal(root: Path, config: Path | None, graders) -> str | None:
    """Why promptfoo is not run with this project's environment, or None: the config's `env:`
    block sets a name judgekeeper does not pass on, or a .env promptfoo reads sets a name that
    starts a program or redirects the calls. Names only; no value is read from a .env."""
    allowed = _passed_on(graders)
    for name in keys.config_env(config):
        if name not in allowed:
            return f"its config sets `{name}`, which judgekeeper does not pass on"
    for name, path in sorted(keys.Sources.read("promptfoo", root, config).in_files.items()):
        upper = name.upper()
        if upper == "NO_PROXY":
            continue
        if upper in PROGRAMS or upper.startswith(STARTS) or any(w in upper for w in REDIRECTS):
            return (f"your {path.name} sets `{name}`, which can start a program or send the "
                    "calls to another server")
    return None


def _config(root: Path) -> Path | None:
    return next((root / n for n in find.PROMPTFOO_CONFIGS if (root / n).is_file()), None)


def _installed(root: Path) -> tuple[str, str] | None:
    """(command, version) of the project's promptfoo, else promptfoo on the PATH. It runs
    before "Go ahead?", so with the real run's settings: telemetry and update check off."""
    for command in (again.node_bin(root, "promptfoo"), again.which("promptfoo")):
        if not command:
            continue
        proc = again.run_process([command, "--version"], cwd=root,
                                 env={**os.environ, **RUN_ENV}, timeout=60)
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
        d = read_json(path, AgainError)
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
    newest = read_json(root / data["results_files"][0], AgainError)
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
                m in t for t in texts for m in TEMPLATE_MARKS) or any(
                template_code(t) for t in _strings([texts[0], row.get("vars")])) or split_code(
                test_entry(a, row, comps, test_opts, default_test)):
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
        refused = grader_refusal(g)
        if refused:
            return cant("promptfoo", judge, refused[0], short=refused[1])
    config = _config(root)
    refused = env_refusal(root, config, graders.values())
    if refused:
        return cant("promptfoo", judge, refused,
                    short="your project sets a name judgekeeper does not pass on")
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
                            "your LLM-as-a-judge runs your own code (a rule that loads a file or "
                            "package, or a transform)",
                            short="your LLM-as-a-judge is your own code")
            for where, value in (("rule", a.get("value")),
                                 ("rubricPrompt", [a.get("rubricPrompt"),
                                                   test_opts.get("rubricPrompt"),
                                                   _options(default_test).get("rubricPrompt")])):
                if any(template_code(v) for v in _strings(value)):
                    return cant("promptfoo", judge,
                                f"its {where} holds template code, which promptfoo would run",
                                short="your LLM-as-a-judge holds template code")
    for _, row, _, _, _ in judged:
        if _code(_strings(row.get("vars"))):
            return cant("promptfoo", judge,
                        "your LLM-as-a-judge runs your own code (a var that loads a file or "
                        "script)", short="your LLM-as-a-judge is your own code")
        if _code([(row.get("prompt") or {}).get("raw")]):
            return cant("promptfoo", judge,
                        "your LLM-as-a-judge runs your own code (a saved prompt that loads a "
                        "file or script)", short="your LLM-as-a-judge is your own code")
    for p in judged:
        found = loads_code(test_entry(*p))
        if found:
            return cant("promptfoo", judge, f"your LLM-as-a-judge runs your own code ({found})",
                        short="your LLM-as-a-judge is your own code")
    if not judged and templated:
        return cant("promptfoo", judge, f"your marked answers: {TEMPLATED[1]}",
                    short="your saved prompts hold template text")
    if not judged:
        return not_marked("promptfoo", judge)
    types = {judge_type(c["assertion"].get("type")) for j in judged for c in j[2]}
    if TRAJECTORY in types:
        return cant("promptfoo", judge,
                    "your LLM-as-a-judge reads the trace of your app or agent's run, which your "
                    "results don't keep",
                    short="your LLM-as-a-judge reads a trace")

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
        text = _text_grader(grader)
        if isinstance(text, dict) and isinstance(text.get("config"), dict):
            key_env = text["config"].get("apiKeyEnvar")
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
        left.append(left_out_line(templated, *TEMPLATED))
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
    variables[PROMPT_VAR] = (row.get("prompt") or {}).get("raw") or ""
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
            "prompts": [f"{{{{{PROMPT_VAR}}}}}"], "providers": ["echo"],
            "evaluateOptions": {"cache": False}, "tests": f"file://{TESTS}"}


def _config_env(config: Path | None, graders) -> dict[str, str]:
    """The keys in the person's config's `env:` block (the values it can read; _passed_on),
    which promptfoo uses over the shell in their own runs: a key set there is the one their
    judge uses. Passed in promptfoo's environment, never written; each is scrubbed from
    everything judgekeeper writes or prints."""
    allowed = _passed_on(graders)
    env = {k: v for k, v in keys.config_env(config).items()
           if isinstance(v, str) and k in allowed}
    for name, value in env.items():
        register_secret(name, value)
    return env


def _rendered(comps) -> list:
    return [(c.get("metadata") or {}).get("renderedGradingPrompt") for c in comps]


def run(ws, plan: Plan, talk) -> Fresh:
    """Have promptfoo grade the labeled answers again, `plan.times` times each."""
    root, metric = ws.root, plan.job.get("metric") or ws.data()["metric"]
    tests = [test_entry(*p) for p in plan.payload]
    found = next((f for f in map(loads_code, tests) if f), None)
    if found:  # the plan refuses these; this is the last look before promptfoo reads them
        raise AgainError(f"your LLM-as-a-judge runs your own code ({found})")
    graders = [t["options"].get("provider") for t in tests]
    refused = next((r[0] for r in map(grader_refusal, graders) if r), None)
    config = _config(root)
    refused = refused or env_refusal(root, config, graders)
    if refused:
        raise AgainError(refused)
    folder = plan.folder or new_folder(ws)
    make_private(folder)
    out = folder / "promptfoo.json"
    rel_out = out.relative_to(root).as_posix()
    argv = [*plan.runner, "eval", "-c", CONFIG, "--repeat", str(plan.times), *FLAGS,
            "-o", rel_out]
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
                                     env={**os.environ, **_config_env(config, graders), **RUN_ENV})
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
            fresh.errors += [r.explanation or "" for r in records if r.mark.problem == "error"]
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
