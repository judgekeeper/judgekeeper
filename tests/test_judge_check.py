"""Did your judge actually judge? `start` checks the judge's own decisions before anyone
labels: no real decision (the call failed, the reply could not be read, nothing at all), a
check of nothing that the tool still gave full marks, an empty answer passed, the same
decision for every answer, and a reason that says the opposite of the decision.

The fixtures are shaped like each tool's real output (the source files are named next to each
detector in the readers): promptfoo's graderFail (src/matchers/shared.ts), DeepEval's errored
metric and its empty `Verdicts:` list scored 1.0 (deepeval/metrics/utils/qag.py), Inspect's
`Score.unscored(reason="grader_failed")` and its older INCORRECT shape
(inspect_ai/scorer/_model.py), MLflow's `feedback.error`.
"""

from __future__ import annotations

import csv
import json
import math

import pytest

from judgekeeper import judge_check, start, start_label, textio
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
    split,
    table_project,
)


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    """These tests stop where labeling starts."""
    calls = []

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append(found)
        start_label.prepare(found, say)
        say("(labeling page)")
        return 0

    monkeypatch.setattr("judgekeeper.start_label.run_labeling", run_labeling)
    return calls


def run(capsys, *argv):
    code = main(["start", *map(str, argv), "--yes"])
    out, err = capsys.readouterr()
    return code, out, err


def ok() -> str:
    return textio.tick()


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


def app_error(row: dict) -> None:
    """A promptfoo row whose app call failed: response.error and failureReason ERROR (2)."""
    row["response"] = {"error": "API error: 500 Internal Server Error", "output": None}
    row["failureReason"] = 2


def promptfoo_with_problems(verdicts, errors=(), unreadable=(), old=(), app_errors=()):
    data = promptfoo_data(verdicts)
    rows = data["results"]["results"]
    for i in errors:
        grader_fail(rows[i], "Could not perform remote grading: timeout")
    for i in unreadable:
        grader_fail(rows[i], "Could not extract JSON from llm-rubric response")
    for i in old:
        grader_fail(rows[i], "Error parsing output: Unexpected token", flag=False)
    for i in app_errors:
        app_error(rows[i])
    return data


def deepeval_with_problems(verdicts, errors=(), nothing=()):
    data = deepeval_data(verdicts)
    for i in errors:  # DeepEval's MetricData for a metric that raised (ignore_errors=True)
        data["testCases"][i]["metricsData"][0].update(
            success=False, score=None, reason=None, verboseLogs=None,
            error="RateLimitError: Error code: 429")
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

@pytest.mark.parametrize("reason, decision", [
    ("PASS: the answer is polite.", "pass"),
    ("Pass", "pass"),
    ("passed - every claim checks out", "pass"),
    ("FAIL. It is rude.", "fail"),
    ("Failed: wrong number", "fail"),
    ("**FAIL**: the refund window is wrong", "fail"),
    ("The answer is fine.\nVerdict: pass", "pass"),
    ("Grade: incorrect", "fail"),
    ("Final verdict: correct", "pass"),
    ("Result = FAILED", "fail"),
    ("decision: Passed", "pass"),
    ("Final answer: incorrect.", "fail"),
    ("The answer names the right day.\n\nGRADE: C", "pass"),
    ("The answer is wrong.\nGRADE: I", "fail"),
    ("Verdict: fail at first, but after a second look\nVerdict: pass", "pass"),
])
def test_a_stated_decision_is_read(reason, decision):
    assert judge_check.stated_decision(reason) == decision


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
    assert judge_check.stated_decision(reason) is None


def test_the_reason_says_the_opposite_only_when_it_states_the_other_decision():
    assert judge_check.says_opposite("FAIL: rude", "pass")
    assert judge_check.says_opposite("Looks right.\nGRADE: C", "fail")
    assert not judge_check.says_opposite("FAIL: rude", "fail")
    assert not judge_check.says_opposite("does not fail", "pass")
    assert not judge_check.says_opposite("Result: partially correct", "fail")


# What the terminal says ------------------------------------------------------------------

def _block(**counts):
    block = {"answers": 57, "error": 0, "unreadable": 0, "empty": 0, "nothing_checked": 0,
             "passed_empty_answer": 0, "reason_says_opposite": 0, "same_decision": None,
             "tool": "promptfoo", "tool_counted_as": None}
    block.update(counts)
    return block


def test_nothing_found_is_one_line():
    assert judge_check.terminal_lines(_block(), "✓") == [
        "  ✓ Your judge made a real decision on every answer."]


def test_every_finding_has_its_line():
    block = _block(error=5, unreadable=2, nothing_checked=4, passed_empty_answer=3,
                   reason_says_opposite=2, same_decision="pass", tool_counted_as="fail")
    lines = judge_check.terminal_lines(block, "✓")
    assert lines == [
        ("  ! Your judge made no real decision on 7 of 57 answers: 5 errors, 2 replies it "
         "could not read."),
        "    promptfoo counted them as fails. They are left out here.",
        ("  ! On 4 answers your judge checked nothing, and promptfoo gave them full marks. "
         "They are left out here."),
        "  ! Your judge passed 3 empty answers.",
        "  ! On 2 answers, your judge's reason says the opposite of its decision.",
        ("  ! Your judge passed every answer. It may not be checking anything: your marks will "
         "show it."),
        "    See them: .judgekeeper/judge-check.csv",
    ]


def test_deepeval_gave_full_marks():
    lines = judge_check.terminal_lines(_block(nothing_checked=4, tool="deepeval"), "✓")
    assert lines[0] == ("  ! On 4 answers your judge checked nothing, and DeepEval gave them "
                        "full marks. They are left out here.")


def test_the_fail_version_of_the_same_decision():
    lines = judge_check.terminal_lines(_block(same_decision="fail"), "✓")
    assert lines == [("  ! Your judge failed every answer. It may be too strict, or not "
                      "checking anything: your marks will show it.")]


@pytest.mark.parametrize("counted, said", [
    ("pass", "promptfoo counted them as passes."),
    ("fail", "promptfoo counted them as fails."),
    ("pass and fail", "promptfoo counted them as some passes and some fails."),
    ("left out", "promptfoo left them out."),
])
def test_what_the_tool_counted_them_as(counted, said):
    lines = judge_check.terminal_lines(_block(error=2, tool_counted_as=counted), "✓")
    assert lines[1] == f"    {said} They are left out here."


def test_tables_and_records_say_only_that_they_are_left_out():
    for tool in ("table", "records", "mapped"):
        lines = judge_check.terminal_lines(_block(empty=2, tool=tool), "✓")
        assert lines == [("  ! Your judge made no real decision on 2 of 57 answers: 2 empty "
                          "decisions."), "    They are left out here.",
                         "    See them: .judgekeeper/judge-check.csv"]


def test_one_of_each_is_said_in_the_singular():
    block = _block(error=1, nothing_checked=1, passed_empty_answer=1, reason_says_opposite=1,
                   tool="deepeval", tool_counted_as="fail")
    assert judge_check.terminal_lines(block, "✓") == [
        "  ! Your judge made no real decision on 1 of 57 answers: 1 error.",
        "    DeepEval counted it as a fail. It is left out here.",
        ("  ! On 1 answer your judge checked nothing, and DeepEval gave it full marks. It is "
         "left out here."),
        "  ! Your judge passed 1 empty answer.",
        "  ! On 1 answer, your judge's reason says the opposite of its decision.",
        "    See them: .judgekeeper/judge-check.csv",
    ]


def test_the_three_kinds_of_no_decision_are_listed():
    lines = judge_check.terminal_lines(_block(error=1, unreadable=1, empty=3), "✓")
    assert lines[0] == ("  ! Your judge made no real decision on 5 of 57 answers: 1 error, "
                        "1 reply it could not read, 3 empty decisions.")


def test_the_words_follow_the_agreed_rules():
    block = _block(error=5, unreadable=2, empty=1, nothing_checked=4, passed_empty_answer=3,
                   reason_says_opposite=2, same_decision="fail", tool_counted_as="fail")
    text = " ".join(judge_check.terminal_lines(block, "✓") + judge_check.page_lines(block))
    assert "verdict" not in text.lower() and "minute" not in text


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
    data = promptfoo_data(split(0, 5))
    reasons = ["Could not extract JSON from llm-rubric response", "Error parsing output: x",
               "No output", "Could not perform remote grading: 503",
               "The answer does not fail the rule but is rude"]
    for row, reason in zip(data["results"]["results"], reasons, strict=True):
        row["gradingResult"]["componentResults"][0]["reason"] = reason
    records = read_promptfoo(_write_json(tmp_path / "r.json", data))
    assert _marks(records) == [("unreadable", "fail"), ("unreadable", "fail"),
                               ("error", "fail"), ("error", "fail"), (None, None)]


def test_promptfoo_app_errors_are_marked(tmp_path):
    data = promptfoo_with_problems(split(3, 0), app_errors=[0])
    data["results"]["results"][1]["failureReason"] = 2
    records = [r for r in read_promptfoo(_write_json(tmp_path / "r.json", data))
               if r.annotator_kind == LLM]
    assert [r.mark.app_error for r in records] == [True, True, False]


def test_deepeval_errors_and_empty_checks_are_marked(tmp_path):
    data = deepeval_with_problems(split(3, 1), errors=[0], nothing=[1])
    records = read_deepeval(_write_json(tmp_path / "test_run_20261009_120000.json", data))
    assert _marks(records) == [("error", "fail"), ("nothing_checked", "pass"), (None, None),
                               (None, None)]
    assert records[0].explanation == "RateLimitError: Error code: 429"


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
        "value": None, "reason": "grader_failed", "explanation": "refused", "history": []}}
    records = read_inspect(_write_json(tmp_path / "log.json", data))
    assert _marks(records) == [("error", "left out")]


def test_inspect_sample_errors_are_marked(tmp_path):
    data = inspect_data(split(2, 0))
    data["samples"][0]["error"] = {"message": "RuntimeError: the app crashed",
                                   "traceback": "", "traceback_ansi": ""}
    records = read_inspect(_write_json(tmp_path / "log.json", data))
    assert [r.mark.app_error for r in records] == [True, False]


def test_mlflow_feedback_errors_are_marked(mlflow_store):
    from judgekeeper.readers import read_mlflow

    runs = read_mlflow("qa-judge", tracking_uri=mlflow_store, metric="concise")
    marked = [(r.mark.problem, r.mark.tool_counted_as, r.explanation) for _, recs in runs
              for r in recs if r.annotator_kind == LLM and r.mark.problem]
    assert marked == [("error", None, "TIMEOUT: judge timed out")]


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


def test_import_reads_the_same_files_as_before(tmp_path):
    """`import`'s output never shows the marks: a grader error stays a fail there."""
    data = promptfoo_with_problems(split(16, 16), errors=[0, 1])
    path = _write_json(tmp_path / "results.json", data)
    labels = tmp_path / "labels.csv"
    labels.write_text("id,human_label\n" + "".join(f"t{i},pass\n" for i in range(32)),
                      encoding="utf-8")
    out = tmp_path / "rep"
    assert main(["import", "promptfoo", str(path), "--labels", str(labels), "--out",
                 str(out)]) == 0
    run1 = [json.loads(x) for x in (out / "runs" / "run-01.jsonl").read_text(
        encoding="utf-8").splitlines()][1:]
    assert sum(r["verdict"] == "fail" for r in run1) == 18  # 16, and the 2 grader errors
    assert not any("mark" in r or "problem" in r for r in run1)


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
               _rec(3, "pass", output=None, mark=Mark(app_error=True)),
               _rec(4, "pass", output="", mark=Mark(output_elsewhere=True))]
    records[3].output = "There was an error."
    pool, result = _pool(records)
    assert len(pool.answers) == 5
    assert result.block()["passed_empty_answer"] == 2
    assert {f.id for f in result.findings} == {pool.answers[0].id, pool.answers[3].id}


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


# `judgekeeper start`, end to end ---------------------------------------------------------

def test_a_clean_judge_gets_one_line(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    lines = out.splitlines()
    where = lines.index(f"{ok()} 32 answers with a verdict: the judge passed 20 and failed 12")
    assert lines[where + 1] == f"  {ok()} Your judge made a real decision on every answer."
    assert "no clear verdict" not in out


def test_promptfoo_grader_errors_are_left_out_and_named(tmp_path, capsys, no_labeling):
    data = promptfoo_with_problems(split(25, 32), errors=range(25, 30), unreadable=[30, 31])
    _write_json(tmp_path / "results.json", data)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                   encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert (f"{ok()} 50 answers with a verdict: the judge passed 25 and failed 25\n"
            "  ! Your judge made no real decision on 7 of 57 answers: 5 errors, 2 replies it "
            "could not read.\n"
            "    promptfoo counted them as fails. They are left out here.\n"
            "    See them: .judgekeeper/judge-check.csv\n") in out
    (found,) = no_labeling
    assert found.pool.n_fail == 25
    saved = json.loads((tmp_path / ".judgekeeper" / "start.json").read_text(encoding="utf-8"))
    assert saved["left_out"]["no_clear_verdict"] == 7
    assert saved["judge_check"]["error"] == 5 and saved["judge_check"]["unreadable"] == 2
    assert saved["pool"] == {"answers": 50, "pass": 25, "fail": 25}


def test_deepeval_checks_of_nothing_are_left_out(tmp_path, capsys):
    data = deepeval_with_problems(split(30, 20), errors=[40], nothing=[0, 1, 2, 3])
    _write_json(tmp_path / ".deepeval" / ".latest_run_full.json", data)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("  ! Your judge made no real decision on 1 of 50 answers: 1 error.\n"
            "    DeepEval counted it as a fail. It is left out here.\n"
            "  ! On 4 answers your judge checked nothing, and DeepEval gave them full marks. "
            "They are left out here.\n") in out
    assert f"{ok()} 45 answers with a verdict: the judge passed 26 and failed 19" in out


def test_inspect_grader_failures_are_left_out(tmp_path, capsys):
    data = inspect_data(split(16, 18))
    unscored(data["samples"][0])
    unscored(data["samples"][1], new=False)
    path = tmp_path / "logs" / "2026-10-02_support.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    # Inspect left the new shape out and counted the old one as a fail: no one sentence fits
    assert ("  ! Your judge made no real decision on 2 of 34 answers: 2 replies it could not "
            "read.\n    They are left out here.\n") in out


def test_a_table_with_blank_decisions(tmp_path, capsys):
    table_project(tmp_path, split(20, 12) + [None, None])
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("  ! Your judge made no real decision on 2 of 34 answers: 2 empty decisions.\n"
            "    They are left out here.\n") in out
    assert "no clear verdict" not in out


def test_a_records_file_with_a_blank_decision(tmp_path, capsys):
    records_project(tmp_path, split(16, 16) + [None])
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("  ! Your judge made no real decision on 1 of 33 answers: 1 empty decision.\n"
            "    It is left out here.\n") in out


def test_passing_every_answer_is_said_below_thirty_too(tmp_path, capsys):
    promptfoo_project(tmp_path, split(12, 0))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ("  ! Your judge passed every answer. It may not be checking anything: your marks "
            "will show it.") in out
    assert "none of your" not in out


def test_failing_every_answer(tmp_path, capsys):
    promptfoo_project(tmp_path, split(0, 40))
    _, out, _ = run(capsys, tmp_path)
    assert ("  ! Your judge failed every answer. It may be too strict, or not checking "
            "anything: your marks will show it.") in out
    assert "none of your" not in out and "See them" not in out


def test_the_only_c_of_n_note_stays(tmp_path, capsys):
    promptfoo_project(tmp_path, split(37, 3))
    _, out, _ = run(capsys, tmp_path)
    assert ("Your judge failed only 3 of 40 answers. That may mean it passes too much: your "
            "labels will show it.") in out


def test_an_empty_answer_passed_is_flagged_and_kept(tmp_path, capsys, no_labeling):
    data = promptfoo_with_problems(split(20, 12), app_errors=[0])
    data["results"]["results"][1]["response"]["output"] = "   "
    _write_json(tmp_path / "results.json", data)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  ! Your judge passed 2 empty answers.\n" in out
    assert len(no_labeling[0].pool.answers) == 32


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
    assert saved["counts"]["passed_empty_answer"] == 1
    problems = sorted(f["problem"] for f in saved["findings"])
    assert problems == ["error", "passed_empty_answer", "reason_says_opposite"]
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


def test_the_result_carries_the_counts_and_the_page_shows_the_card(tmp_path, capsys):
    data = promptfoo_with_problems(split(20, 13), errors=[32])
    _write_json(tmp_path / "results.json", data)
    run(capsys, tmp_path)
    ws = start_label.Workspace(tmp_path)
    session = start_label.StartSession(ws)
    r = start_label.save_result(ws, session, say=lambda line: None)
    assert r["judge_check"]["error"] == 1
    html = ws.result_html.read_text(encoding="utf-8")
    assert "Did your judge actually judge?" in html
    assert ("Your judge made no real decision on 1 of 33 answers: 1 error. promptfoo counted "
            "it as a fail. It is left out here.") in html
    assert ".judgekeeper/judge-check.csv" in html


def test_a_clean_result_page_has_one_quiet_line(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    run(capsys, tmp_path)
    ws = start_label.Workspace(tmp_path)
    start_label.save_result(ws, start_label.StartSession(ws), say=lambda line: None)
    html = ws.result_html.read_text(encoding="utf-8")
    assert "<details" in html and "Your judge made a real decision on every answer." in html
    assert "Did your judge actually judge?" in html.split("<details")[1]


def test_an_old_result_without_the_block_shows_nothing_new():
    content = start_label.page_content(_old_result())
    assert content["judge_check"] is None and content["judge_check_quiet"] is None


def _old_result():
    from judgekeeper import weighted

    return start_label.describe(weighted.corrected(100, 100, 20, 19, 20, 1))


def test_a_recheck_runs_the_check_again_and_keeps_the_old_files(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12))
    run(capsys, tmp_path)
    ws = start_label.Workspace(tmp_path)
    session = start_label.StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": "pass"})
    start_label.save_result(ws, session, say=lambda line: None)
    first = (ws.dir / "judge-check.json").read_text(encoding="utf-8")
    data = promptfoo_with_problems(split(20, 12) + [False], errors=[32])
    data["results"]["results"][0]["gradingResult"]["componentResults"][0]["pass"] = False
    data["results"]["results"][0]["success"] = False
    _write_json(tmp_path / "results.json", data)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "  ! Your judge made no real decision on 1 of 33 answers: 1 error." in out
    archived = list((ws.dir / "history").glob("check-*/judge-check.json"))
    assert len(archived) == 1 and archived[0].read_text(encoding="utf-8") == first
    assert json.loads((ws.dir / "judge-check.json").read_text(
        encoding="utf-8"))["counts"]["error"] == 1


def test_a_records_file_keeps_no_mark(tmp_path):
    """read_records marks nothing: a blank label is the pool's own "empty"."""
    records = read_records(records_project(tmp_path, [True, None]))
    assert all(r.mark.problem is None for r in records)


def test_unmapped_words_still_stop_and_say_no_check(tmp_path, capsys):
    table_project(tmp_path, split(20, 12) + ["maybe"])
    code, out, err = run(capsys, tmp_path)
    assert code == 2
    assert "--label-map" in out + err
    assert "real decision" not in out
