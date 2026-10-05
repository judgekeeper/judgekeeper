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
- With no `provider` on the assertion, the test or `defaultTest`, promptfoo used its built-in
  default grader and the file does not say which model that was.
- promptfoo's PROMPTFOO_STRIP_RESPONSE_OUTPUT, PROMPTFOO_STRIP_TEST_VARS and
  PROMPTFOO_STRIP_GRADING_RESULT settings remove the answers, the inputs or the grading from
  every row, in `eval -o` and `export` files alike. When most rows lack one of them, the file
  is not an empty result: a warning (answers, inputs) or an error (grading, so no verdicts)
  names the setting.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    CODE,
    HUMAN,
    LLM,
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
    """{provider, model, temperature} from a promptfoo provider: an id or {id, config}."""
    if isinstance(value, dict) and "id" not in value and isinstance(value.get("text"), dict | str):
        value = value["text"]  # {text: ..., embedding: ...}
    if isinstance(value, str):
        pid, config = value, {}
    elif isinstance(value, dict) and isinstance(value.get("id"), str):
        pid, config = value["id"], value.get("config") or {}
    else:
        return {}
    ev = {"provider": pid.split(":", 1)[0], "model": pid}
    if isinstance(config, dict) and config.get("temperature") is not None:
        ev["temperature"] = config["temperature"]
    return ev


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
    default_opts = _options((data.get("config") or {}).get("defaultTest"))
    created_at = summary.get("timestamp")
    stripped = _stripped(rows)
    if "grading" in stripped:
        raise RecordsError(stripped_message("grading", path))
    ids, derived = _ids(rows, id_var, path)

    records = RecordList(version=summary.get("version"), ids_derived=derived,
                         warnings=[stripped_message(part, path) for part in stripped])
    seen: Counter = Counter()
    n_default: Counter = Counter()  # judgments by the default grader, per metric name
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
            evaluator = _provider(a.get("provider") or test_opts.get("provider")
                                  or default_opts.get("provider"))
            if not evaluator:
                n_default[name] += 1
            rubric_prompt = (a.get("rubricPrompt") or test_opts.get("rubricPrompt")
                             or default_opts.get("rubricPrompt"))
            prompt = _text(a.get("value"))
            if rubric_prompt:
                prompt = f"{prompt or ''}\n\n{_text(rubric_prompt)}"
            if prompt is not None:
                evaluator["prompt"] = prompt
            records.append(ScoreRecord(
                target_id=item_id, name=name, annotator_kind=LLM, label=label,
                score=c.get("score"), explanation=c.get("reason") or None, run=run, **content,
                evaluator=evaluator, created_at=created_at))
    records.per_metric = {name: {"warnings": [DEFAULT_GRADER.format(n=n)]}
                          for name, n in n_default.items()}
    return records
