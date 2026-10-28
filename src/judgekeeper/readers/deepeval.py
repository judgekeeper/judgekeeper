"""DeepEval: `.deepeval/.latest_run_full.json`, or `test_run_<timestamp>.json` in a results folder.

DeepEval overwrites `.latest_run_full.json` on every run, and writes one `test_run_*.json` per
run when a results folder is set. Each file is one run; DeepEval stores no human verdict.

- A default `test_case_<n>` name is not an id: such cases get one derived from input and
  output, with a warning.
- The GEval rubric is saved only inside `verboseLogs`; the prompt hash covers its criteria,
  steps and rubric, not the per-answer score.
- A failed LLM-as-a-judge call is saved as `success: false, score: null`, and a metric whose
  LLM-as-a-judge returned no verdicts scores 1.0; both are marked for the judge check.
- `evaluationModel` names the provider as a suffix (`(Anthropic)`, `(Azure)`); a bare name is
  OpenAI's, and an unknown suffix leaves it unknown.
"""

from __future__ import annotations

import re
from pathlib import Path

from judgekeeper import table
from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    LLM,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    all_damaged,
    damaged,
    derive_record_id,
    load_json,
    read_rows,
)
from judgekeeper.textio import error_type

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
SUFFIX = re.compile(r"\(([^()]+)\)\s*\Z")


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


LINK_ONLY = "{file} only links to Confident AI; your results aren't saved on this computer."


class LinkOnly(RecordsError):
    """The file holds only DeepEval's link to the run on Confident AI (LINK_ONLY)."""

    next_step = ("set DEEPEVAL_RESULTS_FOLDER=results and run your eval once (DeepEval saves "
                 "its results there too), then run `{command}` again.")


def is_link_only(data) -> bool:
    """Whether DeepEval saved only the link to the run on Confident AI: `testRunLink`, no
    test cases."""
    return isinstance(data, dict) and "testRunLink" in data and not any(
        k in data for k in ("testCases", "conversationalTestCases", "testRunData"))


def _load(path: Path) -> dict:
    data = load_json(path, "DeepEval")
    if is_link_only(data):
        raise LinkOnly(LINK_ONLY.format(file=path))
    if isinstance(data, dict) and isinstance(data.get("testRunData"), dict):
        data = data["testRunData"]  # the wrapper DeepEval's save_test_run(save_under_key=...)
    if not isinstance(data, dict) or not ("testCases" in data
                                          or "conversationalTestCases" in data):
        raise damaged(path, "DeepEval", "is not a DeepEval test run file (no testCases)")
    return data


def _listed(value) -> list:
    """A list of cases as the file holds it; anything else is no cases."""
    return value if isinstance(value, list) else []


def read_deepeval(path: str | Path) -> RecordList:
    """ScoreRecords from one DeepEval test run file: one LLM record per metric per case."""
    path = Path(path)
    data = _load(path)
    m = STAMP.search(path.name)
    created_at = f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}" if m else None
    records = RecordList()
    thresholds: dict[str, set] = {}
    strict: set[str] = set()  # metrics in strict mode: a score of 1 or 0, the threshold fixed
    cases = [(c, False) for c in _listed(data.get("testCases"))]
    cases += [(c, True) for c in _listed(data.get("conversationalTestCases"))]
    cases = table.capped(cases, path)

    def read_case(row: tuple[dict, bool]) -> None:
        case, conversational = row
        if conversational:
            item_input = case.get("scenario") or canonical_json(case.get("turns") or [])
            output = ""
        else:
            item_input, output = case.get("input"), case.get("actualOutput")
        name = case.get("name")
        if not (name is None or isinstance(name, str | int)) or isinstance(name, bool):
            raise TypeError("a case's name")
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
            threshold = md.get("threshold")
            if isinstance(threshold, int | float) and not isinstance(threshold, bool):
                thresholds.setdefault(md["name"], set()).add(threshold)
            if md.get("strictMode") is True:
                strict.add(md["name"])
            label = None if not isinstance(success, bool) else ("pass" if success else "fail")
            records.append(ScoreRecord(
                target_id=item_id, name=md["name"], annotator_kind=LLM, label=label,
                score=md.get("score"), explanation=md.get("reason") or (error_type(md["error"]) if md.get("error")
                                                 else None),
                input=item_input, output=output, evaluator=evaluator, created_at=created_at,
                mark=_mark(md, label, conversational)))

    read_rows(records, enumerate(cases, 1), read_case)
    all_damaged(path, "DeepEval", records)
    if records.ids_derived:
        records.warnings.append(POSITIONAL_WARNING)
    records.per_metric = {name: {"threshold": next(iter(ts)) if len(ts) == 1 else sorted(ts)}
                          for name, ts in thresholds.items()}
    for name in strict:
        records.per_metric.setdefault(name, {})["strict_mode"] = True
    return records
