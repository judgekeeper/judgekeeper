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
"""

from __future__ import annotations

import json
from pathlib import Path

from judgekeeper import again, find, keys, prices
from judgekeeper.again import CLOSE, EXACT, Plan, cant, left_out_line
from judgekeeper.anchors import canonical_json
from judgekeeper.readers.promptfoo import (
    MODEL_GRADED,
    _components,
    _options,
    _text,
    grader_of,
    is_set_grader,
)
from judgekeeper.records import derive_record_id

CALLS = {"llm-rubric": 1, "factuality": 1, "model-graded-factuality": 1,
         "model-graded-closedqa": 1, "context-recall": 1, "context-relevance": 1,
         "context-faithfulness": 2, "answer-relevance": 3, "search-rubric": 1}
AT_LEAST = {"conversation-relevance"}  # one call per message window
PROMPT_TYPES = {"factuality", "model-graded-factuality", "model-graded-closedqa", "g-eval",
                "answer-relevance", "context-faithfulness", "context-recall",
                "context-relevance"}
TEMPLATE_MARKS = ("{{", "{%", "{#")
CODE_PREFIXES = ("exec:", "python:", "file://", "golang:", "ruby:", "javascript:")
SIDE_EFFECT = "Your app is not run. Nothing is written to promptfoo's database or shared."
EXACT_WHY = "promptfoo re-grades your saved answers with your own settings"


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


def plan(ws, answers: list[dict], opts, talk, dry: bool) -> Plan:
    data = ws.data()
    root = ws.root
    metric = data["metric"]
    loaded = [json.loads((root / rel).read_text(encoding="utf-8"))
              for rel in data["results_files"]]
    newest = loaded[0]
    version = (newest.get("metadata") or {}).get("promptfooVersion")
    rows: dict[str, tuple[dict, dict]] = {}
    for d in loaded:  # newest first: the newest row of an answer wins
        default_test = (d.get("config") or {}).get("defaultTest") or {}
        for row in (d.get("results") or {}).get("results") or []:
            key = derive_record_id(row.get("vars"), _text((row.get("response") or {})
                                                           .get("output")))
            rows.setdefault(key, (row, default_test if isinstance(default_test, dict) else {}))

    judged, gone, empty, templated = [], 0, 0, 0
    graders: dict[str, object] = {}
    for a in answers:
        if a["id"] not in rows:
            gone += 1
            continue
        row, default_test = rows[a["id"]]
        test_opts = _options(row.get("testCase"))
        comps = [c for c in _components(row.get("gradingResult"))
                 if (c.get("assertion") or {}).get("type") in MODEL_GRADED
                 and ((c["assertion"].get("metric") or c["assertion"].get("type")) == metric)]
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
    status, why = EXACT, EXACT_WHY
    if not version:
        reasons.append("promptfoo version not recorded")
    if dry:
        installed = _installed(root)
        if version and (installed is None or installed[1] != version):
            if again.which("npx"):
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
                tokens=tokens, left_out=left, settings=check.settings,
                side_effects=[SIDE_EFFECT, (f"Two temporary files are written next to {where} "
                                            "and removed afterwards.")])
