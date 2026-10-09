"""promptfoo: the file `promptfoo eval -o results.json` writes.

Shape (promptfoo src/types/index.ts, `OutputFile`, `EvaluateSummaryV3`, `EvaluateResult`,
`GradingResult`): `results.results[]` rows with `testIdx`, `promptIdx`, `testCase`, `vars`,
`response.output`, `success` and `gradingResult.componentResults[]`, one per assertion, each
with `pass`, `score`, `reason` and the `assertion` that produced it.

Traps handled here:
- A human rating in the web UI adds a component with `assertion.type == "human"` and overrides
  the row's `success`/`pass`. The judge verdict is read from the model-graded component only.
- `--repeat N` rows carry no repeat index (promptfoo strips `__repeatIndex` before saving) and
  each repeat gets its own `testIdx`, with the same `promptIdx` and identical vars. Rows are
  grouped by item id and promptIdx and numbered in order of appearance; a derived id hashes
  vars only, so the repeats of one test share it even when their outputs differ.
- The grader is the assertion's `provider`, then the test's or `defaultTest`'s
  `options.provider`, then `defaultTest.provider` (the model under test, which promptfoo
  also uses as the judge when no grader is set). With none of them, promptfoo used its
  built-in default grader and the file does not say which model that was.
- A grader set with `--grader` is saved as an object with no `id`, only a `modelName`: its
  model is known, its provider is not. It is not the default grader.
- llm-rubric saves the exact text it sent (`metadata.renderedGradingPrompt`). With the answer
  and the test's vars put back as placeholders it is the grading template, which also changes
  when promptfoo changes its own grading prompt; when every judged row of a metric gives the
  same template, its hash is the prompt hash. The rule shown to the person stays the rubric.
- `metadata.cachedResponse` marks a verdict promptfoo replayed from its cache: a warning.
- A grader that failed (its call errored, or its reply could not be read) is saved as a plain
  fail: `graderFail(reason)` in src/matchers/shared.ts is fail(reason) plus
  `metadata.graderError`. The record keeps it as promptfoo saved it and gets an in-memory
  mark (records.Mark) for `start`'s judge check; older files have no flag, so the reasons
  promptfoo writes (src/matchers/rubric.ts, llmGrading.ts) are read instead. A row whose app
  call failed (`response.error`, or `failureReason` 2, ERROR in src/types/index.ts) is marked
  too.
- promptfoo's PROMPTFOO_STRIP_RESPONSE_OUTPUT, PROMPTFOO_STRIP_TEST_VARS and
  PROMPTFOO_STRIP_GRADING_RESULT settings remove the answers, the inputs or the grading from
  every row, in `eval -o` and `export` files alike. When most rows lack one of them, the file
  is not an empty result: a warning (answers, inputs) or an error (grading, so no verdicts)
  names the setting.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    CODE,
    HUMAN,
    LLM,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    derive_record_id,
)
from judgekeeper.textio import read_utf8

# Assertion types graded by a model (promptfoo src/types/index.ts, BaseAssertionTypesSchema).
MODEL_GRADED = frozenset({
    "llm-rubric", "g-eval", "factuality", "model-graded-closedqa", "model-graded-factuality",
    "answer-relevance", "context-faithfulness", "context-recall", "context-relevance",
    "conversation-relevance", "search-rubric",
})
DEFAULT_GRADER = ("default grader model not recorded by promptfoo: {n} judgments had no grader "
                  "provider on the assertion, the test or defaultTest, so promptfoo used its "
                  "built-in default grader; its model is recorded as unknown.")
SET_GRADER = ("{n} judgments were graded by a grader set with --grader (provider unknown): "
              "promptfoo saves only its model name.")
CACHED = ("{n} judgments in {file} came from promptfoo's cache: they may be old replies, not "
          "fresh verdicts.")


# How promptfoo words a grader failure (graderFail callers in src/matchers/rubric.ts,
# llmGrading.ts and rag.ts): a reply it could not read, or a call that failed. Read by these
# words only when the file has no graderError flag (older promptfoo), so they are kept narrow.
UNREADABLE_REASONS = ("Could not extract JSON from ", "Error parsing output:")
ERROR_REASONS = ("Could not perform remote grading:",)
NO_OUTPUT = "No output"
MALFORMED = re.compile(r"\A(\S+ |Model grader )?produced (a )?malformed response")
FAILURE_ERROR = 2  # ResultFailureReason.ERROR: the app's call failed


def grader_problem(component: dict, metadata: dict) -> str | None:
    """"unreadable" or "error" when the grader made no real decision, else None."""
    reason = component.get("reason")
    reason = reason if isinstance(reason, str) else ""
    flagged = metadata.get("graderError") is True
    if reason.startswith(UNREADABLE_REASONS) or (flagged and MALFORMED.match(reason)):
        return "unreadable"
    if flagged or reason.startswith(ERROR_REASONS) or reason == NO_OUTPUT:
        return "error"
    return None


def app_failed(row: dict) -> bool:
    """The app's own call failed for this row."""
    return bool((row.get("response") or {}).get("error")) or \
        row.get("failureReason") == FAILURE_ERROR


STRIPPED = ("The {what} are missing from {file}. promptfoo leaves them out when {setting} is "
            "on, in your environment or in the config's env: block. Turn it off and write the "
            "file again.")
STRIP_SETTINGS = {"output": ("answers", "PROMPTFOO_STRIP_RESPONSE_OUTPUT"),
                  "vars": ("inputs", "PROMPTFOO_STRIP_TEST_VARS"),
                  "grading": ("judge's verdicts", "PROMPTFOO_STRIP_GRADING_RESULT")}


def _stripped(rows: list[dict]) -> list[str]:
    """The parts (output, vars, grading) that most rows lack, as a strip setting leaves them."""
    missing = {
        "output": lambda r: (r.get("response") or {}).get("output") is None,
        "vars": lambda r: r.get("vars") is None and (r.get("testCase") or {}).get("vars") is None,
        "grading": lambda r: not r.get("gradingResult"),
    }
    return [part for part, lacks in missing.items()
            if rows and sum(map(lacks, rows)) * 2 > len(rows)]


def stripped_message(part: str, path: Path) -> str:
    what, setting = STRIP_SETTINGS[part]
    return STRIPPED.format(what=what, file=path.name, setting=setting)


def is_stripped_warning(text: str) -> bool:
    return any(setting in text for _, setting in STRIP_SETTINGS.values())


def _load(path: Path) -> dict:
    try:
        data = json.loads(read_utf8(path, RecordsError))
    except json.JSONDecodeError as e:
        raise RecordsError(f"{path}: not JSON ({e.msg})") from None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, dict) or not isinstance(results.get("results"), list):
        raise RecordsError(f"{path}: not a promptfoo results file (no results.results[]); "
                           "write one with `promptfoo eval -o results.json`")
    return data


def _text(v) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else canonical_json(v)


def _components(grading: dict | None) -> list[dict]:
    """componentResults, with nested assert-set results flattened."""
    out = []
    for c in (grading or {}).get("componentResults") or []:
        if not isinstance(c, dict):
            continue
        nested = c.get("componentResults")
        if nested and (c.get("assertion") or {}).get("type") == "assert-set":
            out += _components(c)
        else:
            out.append(c)
    return out


def _options(obj) -> dict:
    opts = (obj or {}).get("options") if isinstance(obj, dict) else None
    return opts if isinstance(opts, dict) else {}


def _provider(value) -> dict:
    """{provider, model, temperature} from a promptfoo provider: an id or {id, config}; a
    grader set with --grader ({modelName, config}, no id) gives its model alone."""
    if isinstance(value, dict) and "id" not in value and isinstance(value.get("text"), dict | str):
        value = value["text"]  # {text: ..., embedding: ...}
    if isinstance(value, str):
        pid, config = value, {}
    elif isinstance(value, dict) and isinstance(value.get("id"), str):
        pid, config = value["id"], value.get("config") or {}
    elif is_set_grader(value):
        ev = {"model": value["modelName"]}
        config = value.get("config") or {}
        if isinstance(config, dict) and config.get("temperature") is not None:
            ev["temperature"] = config["temperature"]
        return ev
    else:
        return {}
    ev = {"provider": pid.split(":", 1)[0], "model": pid}
    if isinstance(config, dict) and config.get("temperature") is not None:
        ev["temperature"] = config["temperature"]
    return ev


def is_set_grader(value) -> bool:
    """A grader set with `promptfoo eval --grader`: saved with a modelName and no id."""
    return (isinstance(value, dict) and "id" not in value
            and isinstance(value.get("modelName"), str) and bool(value["modelName"]))


def grader_of(assertion: dict, test_options: dict, default_test: dict):
    """The grader one model-graded assertion used, as the file holds it, or None for
    promptfoo's default grader."""
    return (assertion.get("provider") or test_options.get("provider")
            or _options(default_test).get("provider") or default_test.get("provider")
            or None)


def grading_template(rendered: str, output, variables) -> str:
    """A rendered grading prompt with the answer and the test's vars put back as placeholders.
    The prompt is usually JSON (chat messages), so each value is also looked for as it reads
    inside a JSON string. Longest values first, so a value inside another stays."""
    values = [("output", output)] + list((variables or {}).items())
    values = [(k, v if isinstance(v, str) else canonical_json(v)) for k, v in values
              if v is not None]
    for name, value in sorted(values, key=lambda kv: len(kv[1]), reverse=True):
        if not value:
            continue
        for form in (json.dumps(value)[1:-1], value):
            rendered = rendered.replace(form, f"{{{{{name}}}}}")
    return rendered


def _ids(rows: list[dict], id_var: str | None, path: Path) -> tuple[list[str], bool]:
    """The item id of each row, and whether the ids were derived.

    Repeats of one test have the same vars (and description) but each its own testIdx, so ids
    never come from testIdx. A derived id hashes vars only: outputs may differ between repeats.
    """
    several_prompts = len({r.get("promptIdx") for r in rows}) > 1

    def suffix(base: str, r: dict) -> str:
        return f"{base}#prompt{r.get('promptIdx')}" if several_prompts else base

    if id_var is not None:
        ids = []
        for r in rows:
            value = (r.get("vars") or {}).get(id_var)
            if value is None or value == "":
                raise RecordsError(f"{path}: test {r.get('testIdx')} has no var {id_var!r} "
                                   "(--id-var)")
            ids.append(suffix(str(value), r))
        return ids, False
    descs = [(r.get("testCase") or {}).get("description") or r.get("description") for r in rows]
    vars_of: dict[str, set] = defaultdict(set)
    for d, r in zip(descs, rows):
        vars_of[d].add(canonical_json(r.get("vars") or {}))
    if all(isinstance(d, str) and d for d in descs) and all(len(v) == 1 for v in vars_of.values()):
        return [suffix(d, r) for d, r in zip(descs, rows)], False
    return [suffix(derive_record_id(r.get("vars"), None), r) for r in rows], True


def read_promptfoo(path: str | Path, id_var: str | None = None) -> RecordList:
    """ScoreRecords from a promptfoo `-o results.json`.

    Item id: `vars[id_var]` with `id_var`; else `testCase.description` when every test has a
    unique one (repeats of a test share it); else a hash of vars. With several prompts the id
    gets `#prompt<n>`. Repeats are grouped by (id, promptIdx) and numbered in order of
    appearance: promptfoo gives each repeat its own testIdx and no repeat index.
    """
    path = Path(path)
    data = _load(path)
    summary = data["results"]
    rows = [r for r in summary["results"] if isinstance(r, dict)]
    default_test = (data.get("config") or {}).get("defaultTest") or {}
    default_test = default_test if isinstance(default_test, dict) else {}
    created_at = summary.get("timestamp")
    stripped = _stripped(rows)
    if "grading" in stripped:
        raise RecordsError(stripped_message("grading", path))
    ids, derived = _ids(rows, id_var, path)

    records = RecordList(version=summary.get("version"), ids_derived=derived,
                         warnings=[stripped_message(part, path) for part in stripped])
    seen: Counter = Counter()
    n_default: Counter = Counter()  # judgments by the default grader, per metric name
    n_set: Counter = Counter()  # judgments by a grader set with --grader, per metric name
    templates: dict[str, list] = defaultdict(list)  # metric -> (record, template or None)
    n_cached = 0
    for r, item_id in zip(rows, ids):
        seen[(item_id, r.get("promptIdx"))] += 1
        run = seen[(item_id, r.get("promptIdx"))]
        test_opts = _options(r.get("testCase"))
        content = {"input": r.get("vars"), "output": _text((r.get("response") or {}).get("output"))}
        per_row = defaultdict(int)
        for c in _components(r.get("gradingResult")):
            a = c.get("assertion") or {}
            kind = a.get("type")
            label = None if not isinstance(c.get("pass"), bool) else (
                "pass" if c["pass"] else "fail")
            if kind == "human":
                records.append(ScoreRecord(
                    target_id=item_id, name="human", annotator_kind=HUMAN, label=label,
                    score=c.get("score"), explanation=c.get("comment") or None, **content,
                    created_at=created_at))
                continue
            name = a.get("metric") or kind or "unknown"
            if kind not in MODEL_GRADED:
                records.append(ScoreRecord(target_id=item_id, name=name, annotator_kind=CODE,
                                           label=label, score=c.get("score"), run=run, **content))
                continue
            per_row[name] += 1
            if per_row[name] > 1:
                raise RecordsError(f"{path}: test {r.get('testIdx')} has more than one {name!r} "
                                   "component; name them with metric: in each assertion")
            grader = grader_of(a, test_opts, default_test)
            evaluator = _provider(grader)
            if not evaluator:
                n_default[name] += 1
            elif is_set_grader(grader):
                n_set[name] += 1
            metadata = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
            n_cached += metadata.get("cachedResponse") is True
            rubric_prompt = (a.get("rubricPrompt") or test_opts.get("rubricPrompt")
                             or _options(default_test).get("rubricPrompt"))
            prompt = _text(a.get("value"))
            if rubric_prompt:
                prompt = f"{prompt or ''}\n\n{_text(rubric_prompt)}"
            if prompt is not None:
                evaluator["prompt"] = prompt
            problem = grader_problem(c, metadata)
            mark = Mark(problem=problem, tool_counted_as=label if problem else None,
                        app_error=app_failed(r))
            record = ScoreRecord(
                target_id=item_id, name=name, annotator_kind=LLM, label=label,
                score=c.get("score"), explanation=c.get("reason") or None, run=run, **content,
                evaluator=evaluator, created_at=created_at,
                mark=mark)
            records.append(record)
            rendered = metadata.get("renderedGradingPrompt")
            templates[name].append((record, grading_template(
                rendered, (r.get("response") or {}).get("output"), r.get("vars"))
                if isinstance(rendered, str) else None))
    for judged in templates.values():
        found = {t for _, t in judged}
        if len(found) == 1 and None not in found:
            digest = hashlib.sha256(found.pop().encode("utf-8")).hexdigest()
            for record, _ in judged:
                record.evaluator["prompt_hash"] = digest
    if n_cached:
        records.warnings.append(CACHED.format(n=n_cached, file=path.name))
    per_metric: dict[str, dict] = defaultdict(lambda: {"warnings": []})
    for name, n in n_default.items():
        per_metric[name]["warnings"].append(DEFAULT_GRADER.format(n=n))
    for name, n in n_set.items():
        per_metric[name]["warnings"].append(SET_GRADER.format(n=n))
    records.per_metric = dict(per_metric)
    return records
