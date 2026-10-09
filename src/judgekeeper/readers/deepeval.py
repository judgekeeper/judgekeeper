"""DeepEval: `.deepeval/.latest_run_full.json`, or `test_run_<timestamp>.json` in a results folder.

DeepEval has no --output-file flag. It always overwrites `.deepeval/.latest_run_full.json`,
and writes one `test_run_<YYYYMMDD_HHMMSS>.json` per run when `results_folder` (or
`DEEPEVAL_RESULTS_FOLDER`) is set (deepeval/evaluate/local_store.py). Each file is one run.

Shape (deepeval/test_run/api.py and tracing/api.py, dumped with `by_alias=True`):
`testCases[]` and `conversationalTestCases[]`, each with `name`, `input`, `actualOutput` and
`metricsData[]`: `name`, `threshold`, `success`, `score`, `reason`, `evaluationModel`, `error`,
`verboseLogs`. DeepEval stores no human verdict; labels come from --labels.

Traps handled here:
- `name` defaults to the positional `test_case_<order>` (deepeval/test_case/api.py), which is
  not an id: such cases get an id derived from input and actual output, with a warning.
- The GEval rubric is persisted only inside `verboseLogs` (deepeval/metrics/g_eval/g_eval.py):
  steps "Criteria:", "Evaluation Steps:", "Rubric:" and "Score: <x>" joined with " \\n \\n".
  The prompt hash covers the first three; the score differs per item and is left out.
- A metric whose judge call failed is saved with `success: false` and `score: null`, often
  with `error` empty too (an unreadable reply or an HTTP 400 in Faithfulness). DeepEval also
  refuses an empty `actual_output` this way, before any call, with the error
  "'actual_output' cannot be empty for the '<metric>' metric"
  (deepeval/metrics/utils/test_case.py): marked "empty_answer_refused". A QAG metric whose judge returned no verdicts at
  all scores a full 1.0 and passes (`score_qag_verdicts(...,
  empty_score=1)` in deepeval/metrics/utils/qag.py; its verboseLogs then hold an empty
  "Verdicts:\n[]" part, built by construct_verbose_logs in deepeval/metrics/utils/verbose.py
  from `f"Verdicts:\n{prettify_list(self.verdicts)}"`, e.g. metrics/faithfulness). Both are
  read as DeepEval saved them, with an in-memory mark (records.Mark) for `start`'s judge
  check.
- `evaluationModel` is the model's name as DeepEval's model class gives it: the provider is a
  suffix (`claude-sonnet-4-6 (Anthropic)`, `my-deployment (Azure)`, `gemini-x (Gemini)`), and
  a bare name is OpenAI's, since DeepEval builds an OpenAI model for any plain string. A
  suffix judgekeeper does not know (`(Local Model)`, a custom class) leaves it unknown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    LLM,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    derive_record_id,
)
from judgekeeper.textio import read_utf8

POSITIONAL = re.compile(r"(conversational_)?test_case_\d+")
STAMP = re.compile(r"test_run_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
PROMPT_PARTS = ("Criteria:", "Evaluation Steps:", "Rubric:")
SEPARATOR = " \n \n"
POSITIONAL_WARNING = ("DeepEval's default test case names (test_case_0, test_case_1, ...) are "
                      "positional, not ids: ids were derived from each case's input and actual "
                      "output instead. Set LLMTestCase(name=...) for stable ids.")
# The suffix DeepEval's model classes add to the name (deepeval/models/llms/*.py).
SUFFIXES = {"anthropic": "anthropic", "azure": "azure", "gemini": "google",
            "ollama": "ollama", "grok": "xai", "deepseek": "deepseek", "kimi": "moonshot"}
SUFFIX = re.compile(r"\s*\(([^()]+)\)\s*\Z")


def provider_of(model: str | None) -> str | None:
    if not model:
        return None
    m = SUFFIX.search(model)
    if m:
        return SUFFIXES.get(m[1].strip().lower())
    if model.startswith("claude-"):  # not DeepEval's own spelling, but leaves no doubt
        return "anthropic"
    return "openai"


def rubric_from_verbose_logs(logs: str | None) -> str | None:
    """The Criteria, Evaluation Steps and Rubric parts of a GEval `verboseLogs`, or None."""
    if not logs:
        return None
    parts = [p for p in logs.split(SEPARATOR) if p.startswith(PROMPT_PARTS)]
    return SEPARATOR.join(parts) or None


NO_VERDICTS = "Verdicts:\n[]"  # prettify_list([]) is "[]"
FULL_MARKS = 1.0  # score_qag_verdicts' empty_score


def checked_nothing(md: dict) -> bool:
    """The metric's judge returned no verdicts, and DeepEval scored that as full marks."""
    logs = md.get("verboseLogs")
    return (md.get("score") == FULL_MARKS and isinstance(logs, str)
            and any(part.strip() == NO_VERDICTS for part in logs.split(SEPARATOR)))


def failed(md: dict) -> bool:
    """The metric's judge made no decision: `error` set, or no score and `success` false."""
    return bool(md.get("error")) or (md.get("score") is None and md.get("success") is False)


EMPTY_REFUSED = "'actual_output' cannot be empty"


def _mark(md: dict, label, conversational: bool) -> Mark:
    problem = None
    if failed(md):
        refused = str(md.get("error") or "").startswith(EMPTY_REFUSED)
        problem = "empty_answer_refused" if refused else "error"
    elif checked_nothing(md):
        problem = "nothing_checked"
    return Mark(problem=problem, tool_counted_as=label if problem else None,
                output_elsewhere=conversational)


def _load(path: Path) -> dict:
    try:
        data = json.loads(read_utf8(path, RecordsError))
    except json.JSONDecodeError as e:
        raise RecordsError(f"{path}: not JSON ({e.msg})") from None
    if isinstance(data, dict) and isinstance(data.get("testRunData"), dict):
        data = data["testRunData"]  # the wrapper DeepEval's save_test_run(save_under_key=...)
    if not isinstance(data, dict) or not ("testCases" in data
                                          or "conversationalTestCases" in data):
        raise RecordsError(f"{path}: not a DeepEval test run file (no testCases)")
    return data


def read_deepeval(path: str | Path) -> RecordList:
    """ScoreRecords from one DeepEval test run file: one LLM record per metric per case."""
    path = Path(path)
    data = _load(path)
    m = STAMP.search(path.name)
    created_at = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}" if m else None
    records = RecordList()
    thresholds: dict[str, set] = {}
    strict: set[str] = set()  # metrics in strict mode: a score of 1 or 0, the threshold fixed
    cases = [(c, False) for c in data.get("testCases") or []]
    cases += [(c, True) for c in data.get("conversationalTestCases") or []]
    for case, conversational in cases:
        if conversational:
            item_input = case.get("scenario") or canonical_json(case.get("turns") or [])
            output = ""
        else:
            item_input, output = case.get("input"), case.get("actualOutput")
        name = case.get("name")
        if not name or POSITIONAL.fullmatch(str(name)):
            item_id = derive_record_id(item_input, output)
            records.ids_derived = True
        else:
            item_id = str(name)
        for md in case.get("metricsData") or []:
            success = md.get("success")
            evaluator = {}
            if md.get("evaluationModel"):
                evaluator["model"] = md["evaluationModel"]
                if provider := provider_of(md["evaluationModel"]):
                    evaluator["provider"] = provider
            prompt = rubric_from_verbose_logs(md.get("verboseLogs"))
            if prompt:
                evaluator["prompt"] = prompt
            if md.get("threshold") is not None:
                thresholds.setdefault(md["name"], set()).add(md["threshold"])
            if md.get("strictMode") is True:
                strict.add(md["name"])
            label = None if not isinstance(success, bool) else ("pass" if success else "fail")
            records.append(ScoreRecord(
                target_id=item_id, name=md["name"], annotator_kind=LLM, label=label,
                score=md.get("score"), explanation=md.get("reason") or md.get("error") or None,
                input=item_input, output=output, evaluator=evaluator, created_at=created_at,
                mark=_mark(md, label, conversational)))
    if records.ids_derived:
        records.warnings.append(POSITIONAL_WARNING)
    records.per_metric = {name: {"threshold": next(iter(ts)) if len(ts) == 1 else sorted(ts)}
                          for name, ts in thresholds.items()}
    for name in strict:
        records.per_metric.setdefault(name, {})["strict_mode"] = True
    return records
