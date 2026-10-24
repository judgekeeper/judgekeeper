"""Did your judge actually judge? `start` checks the judge's own decisions before anyone
labels: no real decision (the call failed, the reply could not be read, nothing at all), a
check of nothing that the tool still gave full marks, an empty answer passed, the same
decision for every answer, and a reason that says the opposite of the decision.

The fixtures are shaped like each tool's real output (the source files are named next to each
detector in the readers): promptfoo's graderFail (src/matchers/shared.ts), DeepEval's errored
metric (often with `error` empty: no score and `success` false) and its empty `Verdicts:` list
scored 1.0 (deepeval/metrics/utils/qag.py), Inspect's `Score.unscored(reason="grader_failed")`,
its older INCORRECT shape (inspect_ai/scorer/_model.py) and a sample whose grader call failed
(`samples[].error`, no scores), MLflow's `feedback.error`.
"""

from __future__ import annotations

import csv
import json
import math

import pytest

from judgekeeper import judge_check, start, start_label
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.readers import read_deepeval, read_inspect, read_promptfoo
from judgekeeper.records import LLM, RecordList, ScoreRecord, read_records
from tests.start_projects import (
    _write_json,
    deepeval_data,
    inspect_data,
    promptfoo_data,
    promptfoo_project,
    records_project,
    save_result,
    split,
)


def run(capsys, *argv):
    code = main([*map(str, argv), "--yes"])
    out, err = capsys.readouterr()
    return code, out, err


# Shaped like each tool's output ----------------------------------------------------------

def grader_fail(row: dict, reason: str, flag: bool = True) -> None:
    """A promptfoo row whose llm-rubric grader failed: graderFail(reason) is fail(reason)
    (pass false, score 0) plus metadata.graderError; older versions have no flag."""
    component = row["gradingResult"]["componentResults"][0]
    component.update({"pass": False, "score": 0, "reason": reason})
    if flag:
        component["metadata"] = {"graderError": True}
    row["gradingResult"].update({"pass": False, "score": 0})
    row["success"] = False
    row["failureReason"] = 1


def promptfoo_with_problems(verdicts, errors=(), unreadable=(), old=()):
    data = promptfoo_data(verdicts)
    rows = data["results"]["results"]
    for i in errors:
        grader_fail(rows[i], "Could not perform remote grading: timeout")
    for i in unreadable:
        grader_fail(rows[i], "Could not extract JSON from llm-rubric response")
    for i in old:
        grader_fail(rows[i], "Error parsing output: Unexpected token", flag=False)
    return data


def deepeval_with_problems(verdicts, errors=(), nothing=(), silent=(), refused=()):
    data = deepeval_data(verdicts)
    for i in errors:  # DeepEval's MetricData for a metric that raised (ignore_errors=True)
        data["testCases"][i]["metricsData"][0].update(
            success=False, score=None, reason=None, verboseLogs=None,
            error="RateLimitError: Error code: 429")
    for i in refused:  # an empty actual_output, refused before any call
        data["testCases"][i]["actualOutput"] = ""
        data["testCases"][i]["metricsData"][0].update(
            success=False, score=None, reason=None, verboseLogs=None,
            error="'actual_output' cannot be empty for the 'Correctness [GEval]' metric")
    for i in silent:  # an unreadable reply or an HTTP 400, as DeepEval 4.2.8 saved it
        data["testCases"][i]["metricsData"][0].update(
            success=False, score=None, reason=None, verboseLogs=None, error=None)
    for i in nothing:  # score_qag_verdicts(..., empty_score=1) with no verdicts
        data["testCases"][i]["metricsData"][0].update(
            success=True, score=1.0, reason="The score is 1.00 because there are no "
            "contradictions.", verboseLogs=("Truths (limit=None):\n[] \n \nClaims:\n[] \n \n"
                                            "Verdicts:\n[]"))
    return data


def unscored(sample: dict, new: bool = True, legacy: bool = False) -> None:
    """An Inspect sample whose model_graded_qa grader gave no grade it could read."""
    explanation = "Grade not found in model output: I think the answer is fine."
    if new:  # Score.unscored: NaN value, reason grader_failed (0.3.245+)
        score = {"value": math.nan, "reason": "grader_failed", "explanation": explanation,
                 "history": []}
        if legacy:  # before `reason` existed: metadata.unscored_reason
            score = {"value": math.nan, "explanation": explanation, "history": [],
                     "metadata": {"unscored_reason": "grader_failed"}}
    else:  # older versions: INCORRECT with the same explanation
        score = {"value": "I", "explanation": explanation, "history": []}
    sample["scores"] = {"model_graded_qa": score}


# The contradiction check -----------------------------------------------------------------

@pytest.mark.parametrize("reason, stated", [
    ("PASS: the answer is polite.", ["pass"]),
    ("Pass", ["pass"]),
    ("passed - every claim checks out", ["pass"]),
    ("FAIL. It is rude.", ["fail"]),
    ("Failed: wrong number", ["fail"]),
    ("**FAIL**: the refund window is wrong", ["fail"]),
    ("The answer is fine.\nVerdict: pass", ["pass"]),
    ("Grade: incorrect", ["fail"]),
    ("Final verdict: correct", ["pass"]),
    ("Result = FAILED", ["fail"]),
    ("decision: Passed", ["pass"]),
    ("Final answer: incorrect.", ["fail"]),
    ("The answer names the right day.\n\nGRADE: C", ["pass"]),
    ("The answer is wrong.\nGRADE: I", ["fail"]),
    ("Verdict: fail at first, but after a second look\nVerdict: pass", ["pass"]),
    ("FAIL: the sum is wrong.\nGRADE: C", ["fail", "pass"]),
])
def test_a_stated_decision_is_read(reason, stated):
    assert judge_check.stated_decisions(reason) == stated


@pytest.mark.parametrize("reason", [
    "does not fail the rule",
    "the passage is quoted correctly",
    "Result: partially correct",
    "This answer passes.",
    "Passable, but short.",
    "Yes",
    "no",
    "It does not meet the criteria.",
    "The score is 0.2 because the answer fails to cite a source.",
    "GRADE: I think it is fine",
    "",
    None,
])
def test_near_misses_state_no_decision(reason):
    assert judge_check.stated_decisions(reason) == []


def test_the_reason_says_the_opposite_only_when_it_states_the_other_decision():
    assert judge_check.says_opposite("FAIL: rude", "pass")
    assert judge_check.says_opposite("Looks right.\nGRADE: C", "fail")
    assert judge_check.says_opposite("FAIL: the sum is wrong.\nGRADE: C", "pass")  # Inspect
    assert not judge_check.says_opposite("FAIL: rude", "fail")
    assert not judge_check.says_opposite("does not fail", "pass")
    assert not judge_check.says_opposite("Result: partially correct", "fail")


# What the terminal says ------------------------------------------------------------------


# Readers mark problems, in memory only ---------------------------------------------------

def _marks(records, name=None):
    return [(r.mark.problem, r.mark.tool_counted_as) for r in records
            if r.annotator_kind == LLM and (name is None or r.name == name)]


def test_promptfoo_grader_errors_are_marked(tmp_path):
    data = promptfoo_with_problems(split(4, 4), errors=[0], unreadable=[1], old=[2])
    records = read_promptfoo(_write_json(tmp_path / "r.json", data))
    assert _marks(records)[:4] == [("error", "fail"), ("unreadable", "fail"),
                                   ("unreadable", "fail"), (None, None)]


def test_promptfoo_older_files_are_read_by_the_reason_alone(tmp_path):
    reasons = ["Could not extract JSON from llm-rubric response", "Error parsing output: x",
               "No output", "Could not perform remote grading: 503",
               "API error: 400 Bad Request", "No output was given, so it fails",
               "The answer does not fail the rule but is rude"]
    data = promptfoo_data(split(0, len(reasons)))
    for row, reason in zip(data["results"]["results"], reasons, strict=True):
        row["gradingResult"]["componentResults"][0]["reason"] = reason
    records = read_promptfoo(_write_json(tmp_path / "r.json", data))
    assert _marks(records) == [("unreadable", "fail"), ("unreadable", "fail"),
                               ("error", "fail"), ("error", "fail"), ("error", "fail"),
                               (None, None), (None, None)]


def test_promptfoo_rows_error_and_failure_reason_are_not_used(tmp_path):
    """`error` also holds the reason of an ordinary fail, and a grader error has
    failureReason 1 like any fail: only the component says it was the grader."""
    data = promptfoo_data(split(1, 1))
    for row in data["results"]["results"]:
        row["error"], row["failureReason"] = "reason", 2
    records = read_promptfoo(_write_json(tmp_path / "r.json", data))
    assert _marks(records) == [(None, None), (None, None)]


def test_deepeval_errors_and_empty_checks_are_marked(tmp_path):
    data = deepeval_with_problems(split(3, 2), errors=[0], nothing=[1], silent=[4])
    records = read_deepeval(_write_json(tmp_path / "test_run_20261009_120000.json", data))
    assert _marks(records) == [("error", "fail"), ("nothing_checked", "pass"), (None, None),
                               (None, None), ("error", "fail")]
    assert records[0].explanation == "RateLimitError"  # the type only, never the message


def test_a_deepeval_score_below_full_marks_with_no_verdicts_is_not_marked(tmp_path):
    data = deepeval_with_problems(split(1, 0), nothing=[0])
    data["testCases"][0]["metricsData"][0]["score"] = 0.5
    records = read_deepeval(_write_json(tmp_path / "test_run_20261009_120000.json", data))
    assert _marks(records) == [(None, None)]


def test_deepeval_conversations_keep_their_answer_elsewhere(tmp_path):
    data = deepeval_data(split(1, 0))
    case = data["testCases"].pop()
    data["conversationalTestCases"] = [{**case, "turns": [{"role": "user", "content": "hi"}]}]
    records = read_deepeval(_write_json(tmp_path / "test_run_20261009_120000.json", data))
    assert records[0].output == "" and records[0].mark.output_elsewhere


def test_inspect_grader_failures_are_marked(tmp_path):
    data = inspect_data(split(2, 2))
    unscored(data["samples"][0])
    unscored(data["samples"][1], legacy=True)
    unscored(data["samples"][2], new=False)
    path = tmp_path / "log.json"
    path.write_text(json.dumps(data), encoding="utf-8")  # NaN as Inspect writes it
    records = read_inspect(path)
    assert _marks(records) == [("unreadable", "left out"), ("unreadable", "left out"),
                               ("unreadable", "fail"), (None, None)]


def test_an_inspect_grader_failure_without_the_explanation_is_an_error(tmp_path):
    data = inspect_data(split(1, 0))
    data["samples"][0]["scores"] = {"model_graded_qa": {
        "value": float("nan"), "reason": "grader_failed", "explanation": "refused",
        "history": []}}
    records = read_inspect(_write_json(tmp_path / "log.json", data))
    assert _marks(records) == [("error", "left out")]


def grader_call_failed(sample: dict) -> None:
    """An Inspect sample whose grader call failed: samples[].error, no scores."""
    sample["scores"] = {}
    sample["error"] = {"message": "ModelGenerateError: Error code: 400 - invalid request",
                       "traceback": "", "traceback_ansi": ""}


def test_inspect_samples_that_errored_before_scoring(tmp_path):
    data = inspect_data(split(2, 0))
    grader_call_failed(data["samples"][0])
    path = _write_json(tmp_path / "log.json", data)
    assert _marks(read_inspect(path)) == [(None, None)]  # import reads them as before
    records = read_inspect(path, with_errors=True)
    assert _marks(records) == [("not_scored", "left out"), (None, None)]  # not a failed call
    assert records[0].label is None and records[0].output == "Answer 0."
    assert records[0].explanation.startswith("ModelGenerateError")


def test_mlflow_feedback_errors_are_marked(mlflow_store):
    from judgekeeper.readers import read_mlflow

    runs = read_mlflow("qa-judge", tracking_uri=mlflow_store, metric="concise")
    marked = [(r.mark.problem, r.mark.tool_counted_as, r.explanation) for _, recs in runs
              for r in recs if r.annotator_kind == LLM and r.mark.problem]
    assert marked == [("error", None, "TIMEOUT")]


def test_the_mark_is_never_written_and_never_compared():
    record = ScoreRecord(target_id="1", name="j", annotator_kind=LLM, label="fail",
                         mark=judge_check_mark("error", "fail"))
    plain = ScoreRecord(target_id="1", name="j", annotator_kind=LLM, label="fail")
    assert record == plain
    assert "mark" not in record.to_dict() and record.to_dict() == plain.to_dict()
    assert "mark" not in repr(record)


def judge_check_mark(problem, counted):
    from judgekeeper.records import Mark

    return Mark(problem=problem, tool_counted_as=counted)


# The pool --------------------------------------------------------------------------------

def _pool(records, tool="table", score_judge=False):
    pool = start.build_pool([("r", RecordList(records))], "j", Normaliser())
    return pool, judge_check.check(pool, tool, score_judge=score_judge)


def _rec(i, label, output=None, reason="", mark=None, **kw):
    extra = {"mark": mark} if mark is not None else {}
    return ScoreRecord(target_id=str(i), name="j", annotator_kind=LLM, label=label,
                       input=f"q{i}", output=f"a{i}" if output is None else output,
                       explanation=reason or None, **extra, **kw)


def test_the_pool_leaves_the_four_kinds_out_and_the_counts_add_up():
    from judgekeeper.records import Mark

    records = [_rec(0, "fail", mark=Mark("error", "fail")),
               _rec(1, "fail", mark=Mark("unreadable", "fail")),
               _rec(2, None),
               _rec(3, "pass", mark=Mark("nothing_checked", "pass")),
               _rec(4, "pass"), _rec(5, "fail")]
    pool, result = _pool(records, tool="promptfoo")
    assert len(pool.answers) == 2
    counts = result.block()
    assert (counts["error"], counts["unreadable"], counts["empty"],
            counts["nothing_checked"]) == (1, 1, 1, 1)
    assert pool.n_unclear == 4 and counts["answers"] == 6
    assert counts["tool_counted_as"] is None  # the empty one: promptfoo did not count it
    _, errors_only = _pool(records[:2], tool="promptfoo")
    assert errors_only.block()["tool_counted_as"] == "fail"


def test_a_repeat_with_a_real_decision_keeps_the_answer():
    from judgekeeper.records import Mark

    pool, result = _pool([_rec(0, "fail", mark=Mark("error", "fail")), _rec(0, "pass"),
                          _rec(1, "fail")])
    assert sorted(a.verdict for a in pool.answers) == ["fail", "pass"]
    assert result.block()["error"] == 0 and pool.n_unclear == 0


def test_empty_answers_stay_and_a_pass_on_one_is_flagged():
    from judgekeeper.records import Mark

    records = [_rec(0, "pass", output="  "), _rec(1, "fail", output=""), _rec(2, "pass"),
               _rec(3, "pass", output="", mark=Mark(output_elsewhere=True))]
    pool, result = _pool(records)
    assert len(pool.answers) == 4
    assert result.block()["empty_answer_passed"] == 1
    assert {f.id for f in result.findings} == {pool.answers[0].id}


def test_a_missing_answer_is_not_an_empty_one():
    from judgekeeper.records import Mark

    mark = Mark()
    assert judge_check.is_empty_answer("  \n", mark) and judge_check.is_empty_answer([], mark)
    assert judge_check.is_empty_answer({}, mark)
    assert not judge_check.is_empty_answer(None, mark)  # unknown, never flagged
    missing = ScoreRecord(target_id="0", name="j", annotator_kind=LLM, label="pass",
                          input="q0", output=None)
    pool, result = _pool([missing, _rec(1, "fail")])
    assert len(pool.answers) == 2 and result.block()["empty_answer_passed"] == 0


def test_the_same_decision_for_everything_also_below_thirty():
    assert _pool([_rec(i, "pass") for i in range(4)])[1].block()["same_decision"] == "pass"
    assert _pool([_rec(i, "fail") for i in range(4)])[1].block()["same_decision"] == "fail"
    assert _pool([_rec(0, "fail"), _rec(1, "pass")])[1].block()["same_decision"] is None
    assert _pool([_rec(0, "pass")])[1].block()["same_decision"] is None


def test_a_reason_that_says_the_opposite_is_flagged():
    records = [_rec(0, "pass", reason="FAIL: the answer is rude."),
               _rec(1, "fail", reason="Result: partially correct"),
               _rec(2, "fail", reason="Looks right.\nGRADE: C")]
    _, result = _pool(records)
    assert result.block()["reason_says_opposite"] == 2


def test_score_judges_with_a_pass_mark_skip_the_contradiction_check():
    records = [_rec(0, "pass", reason="FAIL: the answer is rude."), _rec(1, "fail")]
    _, result = _pool(records, score_judge=True)
    assert result.block()["reason_says_opposite"] == 0


# `judgekeeper`, end to end ---------------------------------------------------------------


def test_the_saved_files(tmp_path, capsys):
    secret = "sk-ant-" + "q" * 40
    data = promptfoo_with_problems(split(20, 13), errors=[32])
    rows = data["results"]["results"]
    rows[0]["gradingResult"]["componentResults"][0]["reason"] = f"FAIL: rude {secret}"
    rows[1]["gradingResult"]["componentResults"][0]["reason"] = "=HYPERLINK(1)"
    rows[1]["response"]["output"] = ""
    _write_json(tmp_path / "results.json", data)
    code, _, _ = run(capsys, tmp_path)
    assert code == 0
    folder = tmp_path / ".judgekeeper"
    saved = json.loads((folder / "judge-check.json").read_text(encoding="utf-8"))
    assert saved["counts"]["error"] == 1 and saved["counts"]["reason_says_opposite"] == 1
    assert saved["counts"]["empty_answer_passed"] == 1
    problems = sorted(f["problem"] for f in saved["findings"])
    assert problems == ["empty_answer_passed", "error", "reason_says_opposite"]
    assert all(set(f) == {"id", "problem", "tool_counted_as", "judge_decision",
                          "judge_reason"} for f in saved["findings"])
    with (folder / "judge-check.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["id", "problem", "tool_counted_as", "judge_decision",
                             "judge_reason", "input", "output"]
    assert len(rows) == 3
    text = (folder / "judge-check.csv").read_text(encoding="utf-8")
    assert secret not in text and secret not in json.dumps(saved)
    assert "'=HYPERLINK(1)" in text
    error = next(r for r in rows if r["problem"] == "error")
    assert error["tool_counted_as"] == "fail" and error["judge_decision"] == "fail"
    assert error["judge_reason"] == "Could not perform remote grading: timeout"
    start_json = json.loads((folder / "start.json").read_text(encoding="utf-8"))
    assert start_json["judge_check"]["error"] == 1


def test_nothing_is_written_outside_the_judgekeeper_folder(tmp_path, capsys):
    data = promptfoo_with_problems(split(20, 13), errors=[32])
    _write_json(tmp_path / "results.json", data)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    run(capsys, tmp_path)
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")
             if ".judgekeeper" not in p.relative_to(tmp_path).parts}
    assert after == before


def test_the_result_carries_the_counts_and_the_page_says_how_many_are_left_out(tmp_path,
                                                                              capsys):
    data = promptfoo_with_problems(split(20, 13), errors=[32])
    _write_json(tmp_path / "results.json", data)
    run(capsys, tmp_path)
    ws = start_label.Workspace(tmp_path)
    session = start_label.StartSession(ws)
    r = save_result(ws, session, say=lambda line: None)
    assert r["judge_check"]["error"] == 1
    html = ws.report_html.read_text(encoding="utf-8")
    assert ('<p class="left-out band">Your judge gave no Pass or Fail on 1 answer. It is left '
            "out.</p>") in html
    assert judge_check.TITLE not in html  # the full findings: the terminal and the CSV file


def test_a_clean_result_page_has_no_left_out_line(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    run(capsys, tmp_path)
    ws = start_label.Workspace(tmp_path)
    save_result(ws, start_label.StartSession(ws), say=lambda line: None)
    html = ws.report_html.read_text(encoding="utf-8")
    assert 'class="left-out' not in html and judge_check.EVERY_ANSWER not in html


def test_an_old_result_without_the_block_shows_nothing_new():
    assert 'class="left-out' not in start_label.result_html(_old_result())


def _old_result():
    from judgekeeper import weighted

    return start_label.describe(weighted.corrected(100, 100, 20, 19, 20, 1))


def test_a_records_file_keeps_no_mark(tmp_path):
    """read_records marks nothing: a blank label is the pool's own "empty"."""
    records = read_records(records_project(tmp_path, [True, None]))
    assert all(r.mark.problem is None for r in records)


