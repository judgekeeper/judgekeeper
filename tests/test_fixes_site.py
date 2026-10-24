"""The browser's free check (website/assets/freecheck.js) on files it read
differently from the tool: two verdict columns, a quote that never closes, a model on
a row the tool doesn't name, an OpenDocument spreadsheet, one answer run three times, and
fields of the wrong type. Each file is made up here; where the tool reads it, the page must
say the same (tests/test_freecheck_parity.py compares the two the same way).

Needs node; skipped with the reason when it is missing.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from judgekeeper import front, start
from tests.test_freecheck_parity import NODE, _page, browser, tool

pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")


def _csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _lines(result: dict, key: str) -> list[str]:
    return next(j["lines"] for j in result["judges"] if j["key"] == key)


# two verdict columns are both listed, judge-named first, as the tool lists them -------

@pytest.mark.parametrize("header, cells, keys", [
    ("input,output,verdict,judge_verdict", ["fail,fail", "pass,pass", "fail,pass", "pass,fail"],
     ["judge_verdict", "verdict"]),
    ("input,output,verdict,llm_judge", ["fail,0", "pass,1", "fail,1", "pass,0"],
     ["llm_judge", "verdict"]),
])
def test_two_verdict_columns_are_both_listed(tmp_path, header, cells, keys):
    path = _csv(tmp_path / "judged.csv", header,
                [f"question {i},answer {i},{c}" for i, c in enumerate(cells * 3)])
    result = browser(path)
    assert [j["key"] for j in result["judges"]] == keys  # the page's picker asks which
    assert _page(result) == tool(path)
    with pytest.raises(start.Stop):  # the tool asks too
        start.find_judge(path)
    for key in keys:  # each judge's grade is read from its own column
        assert any(line.startswith("  grade") and line.endswith(f"the {key} column")
                   for line in _lines(result, key))


def test_a_judge_named_column_of_words_is_not_a_second_judge(tmp_path):
    path = _csv(tmp_path / "judged.csv", "input,output,verdict,judge_notes",
                [f"q {i},a {i},{'pass' if i % 2 else 'fail'},looks fine" for i in range(4)])
    assert [j["key"] for j in browser(path)["judges"]] == ["verdict"]
    assert _page(browser(path)) == tool(path)


# a quote that never closes stops the page and names its line --------------------------

def test_a_quote_that_never_closes_names_its_line(tmp_path):
    rows = [f"question {i},answer {i},{'pass' if i % 2 else 'fail'}" for i in range(12)]
    rows[4] = 'question 4,"answer 4 has a quote that never closes,fail'
    path = _csv(tmp_path / "judged.csv", "input,output,verdict", rows)
    with pytest.raises(start.StartError, match="line 6 of judged.csv has a quote that never"):
        start.read_results_table(path)
    result = browser(path)
    assert result["ok"] is False
    assert result["message"] == ("Line 6 of this file has a quote that never closes, so the "
                                 "rows after it can't be read.")


def test_an_answer_over_several_lines_is_read(tmp_path):
    path = tmp_path / "judged.csv"
    path.write_text('input,output,verdict\nq 1,"one line,\nand a second",pass\nq 2,a 2,fail\n',
                    encoding="utf-8")
    result = browser(path)
    assert result["ok"] is True and result["judges"][0]["answers"] == 2
    assert _page(result) == tool(path)


# the Judge line names the models the tool names -------------------------------------

def test_the_judge_line_names_the_models_the_tool_names(tmp_path):
    rows = [f"q {i},a {i},{'pass' if i % 2 else 'fail'},gpt-4.1" for i in range(6)]
    path = _csv(tmp_path / "judged.csv", "input,output,verdict,judge_model",
                [*rows, "q 6,a 6,,old-model-made-up"])
    (judge,) = browser(path)["judges"]
    assert judge["models"] == ["gpt-4.1"]
    assert "Judge:       gpt-4.1" in judge["lines"]
    assert _page(browser(path)) == tool(path)


# an OpenDocument spreadsheet is named as a spreadsheet ---------------------------------

def test_an_ods_file_is_named_as_a_spreadsheet(tmp_path):
    path = tmp_path / "sheet.ods"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", "<office:document-content/>")
    result = browser(path)
    assert result["ok"] is False
    assert "Inspect AI" not in result["message"]
    assert result["message"] == "Spreadsheet files aren't read. Save it as CSV UTF-8."


# one answer run three times is "1 answer" ----------------------------------------------

def test_one_answer_run_three_times_is_one_answer(tmp_path):
    path = _csv(tmp_path / "judged.csv", "input,output,verdict", ["q,a,pass"] * 3)
    (judge,) = browser(path)["judges"]
    assert "Answers:     1 answer" in judge["lines"]
    lines = front.found_block(start.find_judge(path))
    assert "Answers:     1 answer" in lines


# fields of the wrong type: the same "damaged" call as the tool -------------------------

def _promptfoo(rows: list) -> dict:
    return {"evalId": "x", "results": {"version": 3, "results": rows}, "config": {}}


def _pf_row(i: int, **over) -> dict:
    row = {"testIdx": i, "vars": {"question": f"q {i}"}, "response": {"output": f"a {i}"},
           "gradingResult": {"pass": True, "componentResults": [
               {"pass": i % 2 == 0, "score": 1, "reason": "fine",
                "assertion": {"type": "llm-rubric", "value": "Is it right?",
                              "provider": "openai:gpt-4.1"}}]},
           "success": True}
    row.update(over)
    return row


@pytest.mark.parametrize("over", [{"vars": 1}, {"response": False}, {"promptIdx": [0]},
                                  {"gradingResult": {"componentResults": 5}}])
def test_a_promptfoo_row_of_the_wrong_shape_is_damaged(tmp_path, over):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_promptfoo([_pf_row(0, **over)])), encoding="utf-8")
    assert tool(path) == {"ok": False}
    result = browser(path)
    assert result["ok"] is False
    assert result["message"] == ("This file is damaged: its only row has a damaged field. "
                                 "Save it again from promptfoo.")


def test_damaged_promptfoo_rows_are_left_out_as_the_tool_leaves_them(tmp_path):
    rows = [_pf_row(i) for i in range(4)]
    rows[1]["gradingResult"]["componentResults"][0]["reason"] = {"why": "an object"}
    rows[2]["vars"] = "not an object"
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_promptfoo(rows)), encoding="utf-8")
    assert _page(browser(path)) == tool(path)
    assert browser(path)["judges"][0]["answers"] == 2


def _deepeval(metrics: list) -> dict:
    return {"testCases": [{"input": f"q {i}", "actualOutput": f"a {i}", "metricsData": [m]}
                          for i, m in enumerate(metrics)]}


def _metric(i: int, **over) -> dict:
    md = {"name": "Correctness", "score": 0.9 if i % 2 else 0.1, "threshold": 0.5,
          "success": bool(i % 2), "reason": "ok", "evaluationModel": "gpt-4.1"}
    md.update(over)
    return md


def test_a_deepeval_metric_with_no_name_is_never_a_judge_named_undefined(tmp_path):
    metrics = [_metric(i) for i in range(4)]
    del metrics[0]["name"]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_deepeval(metrics)), encoding="utf-8")
    result = browser(path)
    assert [j["key"] for j in result["judges"]] == ["Correctness"]
    assert _page(result) == tool(path)
    del metrics[1]["name"], metrics[2]["name"], metrics[3]["name"]
    path.write_text(json.dumps(_deepeval(metrics)), encoding="utf-8")
    assert tool(path) == {"ok": False}
    result = browser(path)
    assert result["ok"] is False
    assert result["message"] == ("This file is damaged: each of its 4 rows has a damaged "
                                 "field. Save it again from DeepEval.")


@pytest.mark.parametrize("over", [{"name": 5}, {"evaluationModel": ["gpt-4.1"]},
                                  {"reason": 3}, {"verboseLogs": 7}])
def test_a_deepeval_field_of_the_wrong_type_is_left_out_as_the_tool_does(tmp_path, over):
    metrics = [_metric(i) for i in range(4)]
    metrics[0].update(over)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_deepeval(metrics)), encoding="utf-8")
    assert _page(browser(path)) == tool(path)
    assert "undefined" not in json.dumps(browser(path))


# a promptfoo row whose call to the model under test failed: the same words as the tool -------

def _failed_row(i: int) -> dict:
    """A row as promptfoo saves it when the model under test never answered."""
    message = "API call error: Request failed after 0 retries: fetch failed"
    return {"testIdx": i, "vars": {"question": f"q {i}"}, "response": {"error": message},
            "error": message, "success": False, "score": 0, "failureReason": 2,
            "gradingResult": None,
            "testCase": {"vars": {"question": f"q {i}"},
                         "assert": [{"type": "llm-rubric", "value": "Is it right?"}],
                         "options": {"provider": "openai:gpt-4.1-mini"}}}


def _one_rubric_row(i: int) -> dict:
    row = _failed_row(i)
    row.update(response={"output": f"a {i}"}, success=i % 3 != 0, score=int(i % 3 != 0),
               failureReason=0 if i % 3 else 1)
    del row["error"]
    return row


def test_a_failed_call_to_the_tested_model_is_said_as_the_tool_says_it(tmp_path):
    from judgekeeper import judge_check

    rows = [_failed_row(i) for i in range(6)] + [_one_rubric_row(i) for i in range(6, 40)]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(_promptfoo(rows)), encoding="utf-8")
    page = browser(path)
    assert _page(page) == tool(path)
    (judge,) = page["judges"]
    line = (f"6 answers have{judge_check.MODEL_FAILED_LINE.split('{n}')[1]} They are left out "
            "here.")
    assert line in judge["findings"]
    assert not any("calls failed" in f for f in judge["findings"])


def test_every_call_to_the_tested_model_failed_says_what_to_do(tmp_path):
    from judgekeeper import judge_check

    path = tmp_path / "results.json"
    path.write_text(json.dumps(_promptfoo([_failed_row(i) for i in range(2)])), encoding="utf-8")
    (judge,) = browser(path)["judges"]
    assert judge_check.ALL_MODEL_FAILED in judge["lines"]
    page = (Path(__file__).parent.parent / "website" / "assets" / "freecheck.js").read_text(
        encoding="utf-8")
    words = judge_check.MODEL_FAILED_NEXT.split(", then run")[0]  # the page names no flags
    assert f"var MODEL_FAILED_NEXT = '{words}, then run judgekeeper" in page
    assert "fix your judge" not in " ".join(judge["lines"])


# repeated answers: the page counts and says them as the tool does ----------------------------

def _repeats(path: Path, times: int = 3, flips=(), extra=()) -> Path:
    """A promptfoo file of 6 answers (4 Pass, 2 Fail), each run `times` times. `flips` gives
    the grade of chosen repeats the other way ((answer, run) pairs); `extra` adds one more run
    of an answer, with the grade given."""
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(4, 2))
    rows = data["results"]["results"]

    def run_of(i: int, run: int, verdict: bool | None = None) -> dict:
        row = json.loads(json.dumps(rows[i]))
        row["testIdx"] = 100 * run + i
        if verdict is not None:
            row["success"] = row["gradingResult"]["pass"] = verdict
            row["gradingResult"]["componentResults"][0]["pass"] = verdict
        return row

    flipped = set(flips)
    data["results"]["results"] = [
        run_of(i, run, not rows[i]["success"] if (i, run) in flipped else None)
        for run in range(times) for i in range(len(rows))] + [
        run_of(i, times, verdict) for i, verdict in extra]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


ALL = "(your file has 18 results: 6 answers, each run 3 times"
SAME = "Repeats with the same grade count once."
UNEVEN = "(your file has 7 results: some answers are in it more than once"


@pytest.mark.parametrize("shape, answers, note", [
    # Sathvik's file: 6 prompts run 3 times, one of them graded 1 Pass and 2 Fail
    ({"flips": [(0, 1), (0, 2)]}, 8,
     f"{ALL}. {SAME} 1 answer got different grades, so its 3 repeats each count.)"),
    ({"flips": [(0, 1), (0, 2), (1, 1), (1, 2)]}, 10,
     f"{ALL}. {SAME} 2 answers got different grades, so their 6 repeats each count.)"),
    ({}, 6, f"{ALL}, so each counts once.)"),
    ({"times": 1, "extra": [(0, True)]}, 6, f"{UNEVEN}, so each counts once.)"),
    ({"times": 1, "extra": [(0, False)]}, 7,
     f"{UNEVEN}. {SAME} 1 answer got different grades, so its 2 repeats each count.)"),
])
def test_the_page_and_the_tool_say_repeated_answers_in_the_same_lines(tmp_path, shape, answers,
                                                                       note):
    path = _repeats(tmp_path / "results.json", **shape)
    (judge,) = browser(path)["judges"]
    found = start.find_judge(path)
    expected = [f"Answers:     {answers} answers", f"{front.INDENT}{note}"]
    for lines in (judge["lines"], front.found_block(found)):
        at = lines.index(expected[0])
        assert lines[at:at + 2] == expected, lines
    # said once, under Answers: no second line about the repeats among the notes
    for lines in (judge["lines"], front._notes(found)):
        assert not any("its own answer" in line or "repeats in all" in line for line in lines)
