"""Fixes from running judgekeeper on public projects: tables whose other columns were counted
as answers, the wrong column taken as the LLM-as-a-judge, error text quoted from logs, and the small
things around them. Every fixture here is made up, with the shape (column names, values) of
the real ones.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from judgekeeper import mapper
from judgekeeper.cli import main
from tests.start_projects import INSPECT, question
from tests.test_front import assert_one_next_at_the_end, flat


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def write_csv(path: Path, columns: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)
    return path


# Other columns counted as answers ---------------------------------------------------------

RAG_COLUMNS = ["variant", "question", "ground_truth", "generated_answer", "hit", "answer_correct",
               "judge_verdict", "generation_time_sec"]


def rag_rows(n: int) -> list[list]:
    return [["base", question(i), f"Truth {i}.", f"Generated answer {i}.", "1",
             "True" if i % 10 else "False", "1" if i % 11 else "0", f"{0.5 + i % 7 / 10:.2f}"]
            for i in range(n)]


def test_a_number_or_true_false_column_is_never_an_answer():
    rows = [dict(zip(RAG_COLUMNS, r, strict=True)) for r in rag_rows(40)]
    g = mapper.guess(rows)
    assert g.output == "generated_answer"
    assert g.sides == []
    assert g.score == "judge_verdict"


def test_a_keyword_list_column_is_never_an_answer():
    columns = ["prompt", "response_text", "answer_keywords", "keyword_score", "judge_verdict"]
    rows = [dict(zip(columns, [question(i), f"Response {i}.", '["alpha", "beta"]', "1",
                               "PASS" if i % 3 else "FAIL"], strict=True)) for i in range(40)]
    g = mapper.guess(rows)
    assert g.output == "response_text"
    assert g.sides == []


def test_the_rag_table_has_one_answer_side_and_no_count_question(here, capsys):
    write_csv(here / "results" / "eval_log_full.csv", RAG_COLUMNS, rag_rows(1509))
    code, out = run(capsys)
    assert code == 3, out
    assert "Count each as its own answer?" not in out
    assert "<side>" not in out
    assert "  answer:          generated_answer" in out
    assert "Answers:         1509 answers" in out
    assert "Each item has" not in out


def test_counts_wait_until_a_question_that_changes_them_is_answered(here, capsys):
    """Two answers per item (A and B): the counts depend on "Count each as its own answer?",
    so they are printed only once it is answered."""
    from tests.start_projects import nested_runs_project

    nested_runs_project(here)
    code, out = run(capsys, "--metric", "Safe wording")
    assert code == 3, out
    assert "Count each as its own answer?" in flat(out)
    assert "answers, each graded by your LLM-as-a-judge" not in out
    assert "Your LLM-as-a-judge's grades:" not in out
    assert "Checked:" not in out
    code, out = run(capsys, "--metric", "Safe wording", "--yes")
    assert code == 0, out
    assert "Answers:         42 answers" in out


# The wrong column taken as the judge ------------------------------------------------------

HARNESS_COLUMNS = ["id", "task", "prompt", "response", "grader", "check_verdict", "judge_verdict",
                   "verdict", "judge_reason", "latency_ms"]


def harness_rows() -> list[list]:
    rows = []
    for i in range(9):  # string-match rows: no LLM-as-a-judge
        rows.append([f"t{i}", "lookup", question(i), f"Answer {i}.", "string_match", "", "",
                     "PASS" if i % 2 else "FAIL", "", "120"])
    for i in range(9, 69):  # rows with code checks and a judge
        judge = "PASS" if i % 7 else "FAIL"
        check = "pass" if i % 5 else "fail"
        both = "PASS" if judge == "PASS" and check == "pass" else "FAIL"
        rows.append([f"t{i}", "reasoning", question(i), f"Answer {i}.", "checks+judge", check,
                     judge, both, f"reason {i}", "340"])
    return rows


def test_a_blank_first_row_does_not_drop_a_verdict_column():
    rows = [dict(zip(HARNESS_COLUMNS, r, strict=True)) for r in harness_rows()]
    g = mapper.guess(rows)
    assert "judge_verdict" in g.judges


def test_several_verdict_columns_are_listed_as_judges_judge_first(here, capsys):
    write_csv(here / "results.csv", HARNESS_COLUMNS, harness_rows())
    code, out = run(capsys)
    assert code == 3, out
    assert "LLM-as-a-judge:" not in out
    assert "string_match" not in out and "checks+judge" not in out
    assert "  model:           not in the file" in out
    assert out.index("judge_verdict (60 answers)") < out.index("check_verdict (60 answers)")
    assert out.index("check_verdict (60 answers)") < out.index("verdict (69 answers)")
    line = assert_one_next_at_the_end(out)
    assert "--metric NAME" in line
    assert "'judge_verdict', 'check_verdict', 'verdict', 'all'" in flat(line)  # quoted alike


def test_the_chosen_judge_column_is_read_alone(here, capsys):
    write_csv(here / "results.csv", HARNESS_COLUMNS, harness_rows())
    code, out = run(capsys, "--metric", "judge_verdict", "--yes")
    assert code == 0, out
    assert "Your LLM-as-a-judge passed 52 answers and failed 8." in out  # the 60 judged rows
    assert "9 empty decisions" in flat(out)  # the string-match rows have no LLM-as-a-judge
    assert "string_match" not in out and "checks+judge" not in out


# No placeholders on screen -------------------------------------------------------------

def test_the_screen_names_real_paths_never_placeholders(here, capsys):
    from tests.start_projects import nested_runs_project

    nested_runs_project(here)
    code, out = run(capsys, "--metric", "Safe wording")
    assert code == 3, out
    assert "<criterion>" not in out and "<side>" not in out
    assert '  cases[].A.scores."Safe wording".score' in out  # the first judge, for real
    assert "Plain language" not in out[:out.index("How judgekeeper reads it")]
    assert "  answer:          A.output and B.output" in out
    assert ('grade: A.scores."Safe wording".score (LLM-as-a-judge names: Safe wording, Plain language) and '
            "the same under B") in flat(out)
    code, out = run(capsys, "--metric", "Safe wording", "--yes")
    assert code == 0, out
    import shutil

    shutil.rmtree(here / ".judgekeeper")  # a fresh start reads the file as the toml says
    code, out = run(capsys, "--metric", "Safe wording", "--yes")
    assert "<side>" not in out and "<criterion>" not in out
    assert ("Read from your file: question prompt answer A.output and B.output grade "
            'A.scores."Safe wording".score: Pass at 0.5 or more model judge_model') in flat(out)


# A keyword or regex score is not an LLM judge ----------------------------------------

KEYWORD_COLUMNS = ["prompt", "response_text", "answer_keywords", "keyword_score", "judge_verdict"]


def keyword_rows(n: int = 40) -> list[dict]:
    return [dict(zip(KEYWORD_COLUMNS, [question(i), f"Response {i}.", '["alpha", "beta"]',
                                       "1" if i % 2 else "0", "PASS" if i % 3 else "FAIL"],
                     strict=True)) for i in range(n)]


def test_a_keyword_score_column_is_not_offered_as_a_judge():
    g = mapper.guess(keyword_rows())
    assert g.judges == []
    assert g.score == "judge_verdict"


@pytest.mark.parametrize("name", ["keyword_score", "regex_match", "exact_match", "contains_ok"])
def test_a_rule_column_alone_is_said_to_be_a_rule(name):
    rows = [{"prompt": question(i), "response": f"R {i}.", name: str(i % 2)} for i in range(20)]
    with pytest.raises(mapper.MapError) as e:
        mapper.guess(rows)
    assert name in str(e.value) and "rule" in str(e.value)


# Error text quoted from logs ------------------------------------------------------------

CANARY = "ZQCANARY-prompt-text"


def failed_inspect_log(root: Path, name: str = "logs/2026-10-02_support.json") -> Path:
    """An Inspect log whose run stopped with an error: 5 of 18 samples scored, 13 with a
    RuntimeError whose message holds the eval's own request (the canary)."""
    base = json.loads(INSPECT.read_text(encoding="utf-8"))
    sample0 = base["samples"][0]
    samples = []
    for i in range(18):
        s = json.loads(json.dumps(sample0))
        s.update(id=i, epoch=1, input=question(i))
        if i < 5:
            s["scores"] = {"model_graded_qa": {"value": "C" if i % 2 else "I",
                                               "explanation": f"reason {i}", "history": []}}
        else:
            s["scores"] = {}
            s["error"] = {"message": f"RuntimeError('\\nRequest:\\n{{\"content\": "
                                     f"\"{CANARY} {i}\"}}')", "traceback": f"... {CANARY}",
                          "traceback_ansi": f"... {CANARY}"}
        samples.append(s)
    spec = json.loads(json.dumps(base["eval"]))
    spec["scorers"] = [x for x in spec["scorers"] if x["name"] == "model_graded_qa"]
    data = {**base, "status": "error", "eval": spec, "samples": samples,
            "results": {**base["results"], "total_samples": 18, "completed_samples": 5},
            "error": {"message": f"RuntimeError('\\nRequest: {CANARY}')",
                      "traceback": f"Traceback ... {CANARY}",
                      "traceback_ansi": f"Traceback ... {CANARY}"}}
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_an_inspect_error_is_said_by_type_and_count_never_quoted(here, capsys):
    failed_inspect_log(here)
    _, out = run(capsys)
    assert CANARY not in out, out
    assert ("Your Inspect run stopped early (5 of 18 samples): RuntimeError on 13 samples."
            in flat(out)), out
    written = [p for p in (here / ".judgekeeper").rglob("*") if p.is_file()]
    for p in written:
        assert CANARY not in p.read_text(encoding="utf-8", errors="replace"), p


def test_a_run_error_with_no_sample_errors_names_the_type_alone():
    from judgekeeper.readers.inspect_logs import stopped_early

    data = {"status": "error", "samples": [{"scores": {"a": {"value": 1}}}] * 3,
            "results": {"total_samples": 10, "completed_samples": 3},
            "error": {"message": f"openai.RateLimitError: {CANARY}"}}
    assert stopped_early(data) == ("Your Inspect run stopped early (3 of 10 samples): "
                                   "openai.RateLimitError.")
    data["error"] = {"message": f"some words {CANARY}"}
    assert stopped_early(data) == "Your Inspect run stopped early (3 of 10 samples): an error."


# Promptfoo's table output is known at any depth ----------------------------------------

PROMPTFOO_TABLE = {"head": {"prompts": [{"raw": "{{question}}"}], "vars": ["question"]},
                   "body": [{"outputs": [{"pass": True, "score": 1, "text": "Answer 0."}],
                             "vars": ["Question 0?"], "test": {}}]}


def test_a_promptfoo_table_is_never_guessed_as_a_format_of_its_own(here, capsys, monkeypatch):
    from judgekeeper import find

    monkeypatch.setattr(find, "MAX_JSON", 1)  # the walk's JSON budget goes on another file
    (here / "a-config.json").write_text('{"name": "app", "version": 3}', encoding="utf-8")
    table = here / "evaluation" / "results" / "eval-single-turn-results.json"
    table.parent.mkdir(parents=True)
    table.write_text(json.dumps(PROMPTFOO_TABLE), encoding="utf-8")
    code, out = run(capsys)
    assert code == 2, out
    assert "format of its own" not in out
    assert flat(out).count("evaluation/results/eval-single-turn-results.json is promptfoo's "
                           "table output, which doesn't keep the LLM-as-a-judge's own decisions") == 1
    assert "promptfoo eval -o results.json" in flat(out)


# A virtual environment by any name is skipped ----------------------------------------

def test_a_folder_with_pyvenv_cfg_is_a_virtual_environment_and_skipped(here, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here / "env", split(20, 16))
    (here / "env" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "env/results.json" not in out
    assert "No eval results found in this folder" in flat(out)


# An Excel file found in the folder is named -------------------------------------------

def test_an_excel_file_in_the_folder_is_named(here, capsys):
    from tests.start_projects import table_project

    (here / "judged.xlsx").write_bytes(b"PK\x03\x04" + b"\0" * 40)
    code, out = run(capsys)
    assert code == 2, out
    assert "judged.xlsx is an Excel file: save it as CSV UTF-8 to use it." in flat(out)
    assert "save judged.xlsx as CSV UTF-8" in assert_one_next_at_the_end(out)
    table_project(here, [True] * 20 + [False] * 16)  # next to a table that is read
    code, out = run(capsys)
    assert code == 0, out
    assert "judged.xlsx is an Excel file: save it as CSV UTF-8 to use it." in flat(out)
    assert "so it was left out" not in flat(out)


# When the search stops early, it says so ----------------------------------------------

def test_a_search_that_stops_at_the_file_limit_says_so(here, capsys, monkeypatch):
    from judgekeeper import find

    monkeypatch.setattr(find, "MAX_FILES", 50)
    for i in range(60):
        (here / f"note{i:02}.txt").write_text("x", encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "judgekeeper stopped looking after 50 files." in flat(out)
    line = assert_one_next_at_the_end(out)
    assert "give the path of your results" in line and "judgekeeper PATH" in line


# Check's drop line gives both ends --------------------------------------------------

def test_the_drop_line_gives_both_ends_of_the_range():
    from judgekeeper import targets
    from judgekeeper.check import paired_lines

    g = targets.paired_verdict(0, 12, 30)
    assert paired_lines(g) == [
        "Worse: 12 answers went from right to wrong, and none from wrong to right.",
        "That is about 40 points lower (between 27 and 55).",
    ]


# Repeats with different grades are never merged silently --------------------------------

def test_repeats_with_different_grades_are_each_their_own_answer(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    rows = data["results"]["results"]
    again = [json.loads(json.dumps(rows[0])) for _ in range(2)]  # the first answer, twice more
    for r, v in zip(again, (False, False), strict=True):
        r["gradingResult"]["componentResults"][0]["pass"] = v
        r["gradingResult"]["pass"] = r["success"] = v
    data["results"]["results"] = rows + again
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "Answers:         38 answers" in out
    assert ("3 repeats of one answer got different grades (1 Pass, 2 Fail); each is its own "
            "answer.") in flat(out)
    assert "tied grade" not in out and "merged" not in out


def test_repeats_with_the_same_grade_are_still_merged(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    rows = data["results"]["results"]
    data["results"]["results"] = rows + [json.loads(json.dumps(rows[0]))]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "Answers:         36 different answers" in out
    assert "(your file has 37 results: some answers are in it more than once, so each is counted once)" in flat(out)
    assert "merged" not in out


# Promptfoo rows with no grading details and one llm-rubric ----------------------------

def test_a_null_grading_result_with_one_rubric_uses_the_rows_success(here, capsys):
    from tests.start_projects import RUBRIC, promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    for r in data["results"]["results"]:
        r["gradingResult"] = None
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC}]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "PROMPTFOO_STRIP_GRADING_RESULT" not in out
    assert "Answers:         36 answers" in out
    assert "Your LLM-as-a-judge passed 20 answers and failed 16." in out
    assert ("promptfoo didn't save the grader's details; the pass/fail of each row is used."
            in flat(out))


def test_a_null_grading_result_with_two_assertions_still_names_the_setting(here, capsys):
    from tests.start_projects import RUBRIC, promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    for r in data["results"]["results"]:
        r["gradingResult"] = None
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC},
                                   {"type": "contains", "value": "Answer"}]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 2, out
    assert "PROMPTFOO_STRIP_GRADING_RESULT" in flat(out)


# MLflow at the root without the extra -------------------------------------------------

def test_mlflow_db_at_the_root_without_the_extra_is_one_screen(here, capsys, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "mlflow", None)
    (here / "mlflow.db").write_bytes(b"SQLite format 3\0" + b"\0" * 100)
    (here / "mlruns" / "0").mkdir(parents=True)  # a folder store too, as at those roots
    (here / "mlruns" / "0" / "meta.yaml").write_text("experiment_id: '0'\n", encoding="utf-8")
    code, out = run(capsys, "--port", "9264")
    assert code == 3, out
    assert "error:" not in out and "reading MLflow needs mlflow" not in out
    assert "MLflow found (mlflow.db)." in flat(out)
    line = assert_one_next_at_the_end(out)
    assert "--port 9264" in line


# Old Inspect logs (format 1) without the extra -------------------------------------------

def inspect_v1_log(root: Path, n: int = 3) -> Path:
    samples = [{"id": i, "epoch": 1, "input": question(i), "target": "T",
                "output": {"completion": f"Answer {i}."},
                "score": {"value": "I", "answer": f"Answer {i}.", "explanation": f"why {i}"}}
               for i in range(n)]
    data = {"version": 1, "status": "success",
            "eval": {"task": "private_bench", "model": "openai/gpt-4", "created": "2024-05-01",
                     "dataset": {}, "config": {}},
            "plan": {"name": "plan", "steps": []},
            "results": {"scorer": {"name": "model_graded_fact", "params": {}}, "metrics": {}},
            "stats": {}, "samples": samples}
    path = root / "logs" / "2024-05-01T10-00-00_private-bench_abc.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_an_inspect_log_of_format_1_is_read_without_the_extra(here, capsys):
    inspect_v1_log(here)
    code, out = run(capsys)
    assert code == 3, out  # 3 answers: not enough for a first result
    assert "holds no decisions from an LLM-as-a-judge" not in out
    assert "needs the extra" not in out
    assert "Answers:         3 answers" in out
    assert "Your LLM-as-a-judge passed 0 answers and failed 3." in out


# Judge tables reported as nothing --------------------------------------------------------

@pytest.mark.parametrize("name, columns", [
    ("results/llm_judge.csv", ["variant", "scenario_id", "category", "llm_judge_score",
                               "llm_judge_pass", "llm_judge_reasoning", "judge_model"]),
    ("artifacts/human_validation/judge_results.csv", ["item_id", "judge_verdict",
                                                      "judge_main_issue", "judge_reason",
                                                      "judge_confidence", "judge_model"]),
])
def test_a_judge_table_with_no_answer_column_is_named(here, capsys, name, columns):
    rows = [[f"v{i}", f"s{i}", "cat", "0.8", "PASS" if i % 2 else "FAIL", f"why {i}",
             "gpt-4o-mini"][:len(columns)] for i in range(30)]
    write_csv(here / name, columns, rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "No eval results found" not in out
    assert (f"{name} has your LLM-as-a-judge's verdicts but no answer text, so there's nothing to show "
            "you for marking.") in flat(out)
    line = assert_one_next_at_the_end(out)
    assert "add the answer column (the text that was judged)" in flat(out)
    assert "`judgekeeper`" in line


def test_a_csv_with_the_judge_is_read_when_the_newer_json_has_none(here, capsys):
    import os
    import time

    rows = [{"prompt": question(i), "response": f"R {i}.", "score": "n/a"} for i in range(20)]
    (here / "results").mkdir()
    (here / "results" / "results_gpt4_stacked_all.json").write_text(json.dumps(rows),
                                                                      encoding="utf-8")
    csv_path = write_csv(here / "results" / "results_gpt4_llm_judge.csv",
                         ["prompt", "response", "judge_verdict", "judge_reason"],
                         [[question(i), f"R {i}.", "PASS" if i % 3 else "FAIL", f"why {i}"]
                          for i in range(40)])
    old = time.time() - 3600
    os.utime(csv_path, (old, old))  # the JSON is the newer file
    code, out = run(capsys)
    assert code == 3, out
    assert "results/results_gpt4_llm_judge.csv looks like your LLM-as-a-judge's results" in flat(out)
    assert "judgekeeper cannot read" not in out


# False "from another project" ------------------------------------------------------------

def test_a_folded_yaml_description_matches_the_results(here, capsys):
    from tests.start_projects import promptfoo_project, split

    text = "Test D — SGA V2 lookup-heavy workload — JS-only assertions — no LLM grader."
    promptfoo_project(here, split(20, 16), description=text, config=False)
    (here / "promptfooconfig.yaml").write_text(
        "description: >-\n  Test D — SGA V2 lookup-heavy workload —\n  JS-only assertions — "
        "no LLM grader.\nprompts:\n  - '{{question}}'\nproviders:\n  - echo\ntests: []\n",
        encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "another project" not in out


def test_a_results_file_with_no_judge_is_left_out_without_the_question(here, capsys):
    from tests.start_projects import promptfoo_data, promptfoo_project, split

    promptfoo_project(here, split(20, 16), description="support bot")
    data = promptfoo_data(split(5, 5), description="Test D — JS-only assertions",
                          created="2026-10-05T10:00:00.000Z")
    for r in data["results"]["results"]:  # a code assertion only: no LLM judge
        r["gradingResult"]["componentResults"][0]["assertion"] = {"type": "contains",
                                                                  "value": "Answer"}
    (here / "other.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "another project" not in out
    assert "other.json is left out: no LLM-as-a-judge in it." in flat(out)


# Paths relative to the project ------------------------------------------------------------

def test_a_log_with_no_samples_is_named_by_its_path_in_the_project(here, capsys):
    from tests.start_projects import inspect_data, inspect_project

    inspect_project(here, [True] * 20 + [False] * 16)
    empty = {**inspect_data([True]), "samples": []}
    (here / "logs" / "2026-10-03_empty.json").write_text(json.dumps(empty), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert str(here) not in out
    assert "logs/2026-10-03_empty.json: the log has no samples" in flat(out)


# Inspect manifests are never offered as results -----------------------------------------

def test_eval_set_manifests_are_never_offered_and_the_logs_are_named(here, capsys):
    deep = here / "data" / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "eval-set.json").write_text('{"eval_set_id": "x", "tasks": []}', encoding="utf-8")
    (deep / "logs.json").write_text('{"a.eval": {}}', encoding="utf-8")
    log = deep / "f" / "2025-11-26T01-23-23+00-00_task_abc.eval"
    log.parent.mkdir()
    log.write_bytes(b"PK\x03\x04" + b"\0" * 20)
    code, out = run(capsys)
    assert code == 3, out
    assert "eval-set.json" not in out and "logs.json" not in out
    assert "data/a/b/c/d/e/f/2025-11-26T01-23-23+00-00_task_abc.eval" in flat(out)
    assert "2025-11-26T01-23-23+00-00_task_abc.eval" in assert_one_next_at_the_end(out)


# Ctrl-C under --wait prints one Next line --------------------------------------------

def test_ctrl_c_under_wait_prints_one_next_line(here, capsys, monkeypatch):
    from judgekeeper import label
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    real = label.LabelServer.serve

    def interrupted(self, *args, **kwargs):
        self.stop()
        real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(label.LabelServer, "serve", interrupted)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)
    code, out = run(capsys, "--wait")
    assert code == 130, out
    assert out.count("Next:") == 1, out
    assert out.rstrip().splitlines()[-2:] == [
        "Stopped.", "Next: run `judgekeeper --wait` to carry on."]


# Small words ---------------------------------------------------------------------

def test_one_more_file_left_out_is_singular(here, capsys):
    from tests.start_projects import promptfoo_data, promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    for n in range(4):  # four newer files with code assertions only
        data = promptfoo_data(split(2, 2), created=f"2026-10-1{n}T10:00:00.000Z")
        for r in data["results"]["results"]:
            r["gradingResult"]["componentResults"][0]["assertion"] = {"type": "contains",
                                                                      "value": "Answer"}
        (here / f"smoke-{n}.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "1 more file is left out: no LLM-as-a-judge in it." in flat(out)
    assert "more files are" not in out


def test_no_default_grader_line_when_no_grade_is_clear(here, capsys):
    from tests.start_projects import promptfoo_data

    data = promptfoo_data([False, False], model=None)
    for r in data["results"]["results"]:
        c = r["gradingResult"]["componentResults"][0]
        c.update(reason="API error: 400 Bad Request", metadata={"graderError": True})
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "Your LLM-as-a-judge's calls failed on every answer" in flat(out)
    assert "grades came from promptfoo's default grader" not in flat(out)  # no grade to come


# The Next line of a file that can't be read keeps the flags --------------------------

def test_a_file_that_cannot_be_read_keeps_the_flags_in_its_next_line(here, capsys):
    rows = [{"prompt": question(i), "response": f"R {i}.", "score": "n/a"} for i in range(20)]
    (here / "judged.json").write_text(json.dumps(rows), encoding="utf-8")
    code, out = run(capsys, "--port", "9100")
    assert code == 3, out
    line = assert_one_next_at_the_end(out)
    assert "<the CSV>" not in line and "--port 9100" in line
    said = flat(out)  # "Or save..." comes after its first choice
    assert said.index("Turn it into a CSV, as the Next: line says.") < said.index("Or save")


# Judge-check files only when they list something ------------------------------------

def test_judge_check_files_are_written_only_when_they_list_something(here, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    code, out = run(capsys)
    assert code == 0, out
    assert not (here / ".judgekeeper" / "judge-check.csv").exists()
    assert not (here / ".judgekeeper" / "judge-check.json").exists()
    assert "The list is in" not in out
    promptfoo_project(here, split(20, 16) + [None] * 3)  # three failed calls
    import shutil

    shutil.rmtree(here / ".judgekeeper")
    code, out = run(capsys)
    assert code == 0, out
    assert (here / ".judgekeeper" / "judge-check.csv").exists()
    assert flat(out).count("The list is in .judgekeeper/judge-check.csv.") == 1


# The notes the reference promises ---------------------------------------------------

def test_cached_promptfoo_grades_are_said(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    for r in data["results"]["results"][:7]:
        r["gradingResult"]["componentResults"][0]["metadata"] = {"cachedResponse": True}
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "7 of these grades were cached by promptfoo" in flat(out)


def test_code_assertions_next_to_the_judge_are_said(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    for r in data["results"]["results"]:
        c = r["gradingResult"]["componentResults"][0]
        r["gradingResult"]["componentResults"] = [
            c, {"pass": True, "score": 1, "reason": "ok",
                "assertion": {"type": "contains", "value": "Answer"}},
            {"pass": True, "score": 1, "reason": "ok",
             "assertion": {"type": "javascript", "value": "output.length > 1"}}]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert ("Your tests also have 72 code assertions (contains, javascript): they are not an "
            "LLM-as-a-judge, so they are left out.") in flat(out)


def test_deepeval_positional_names_are_said(here, capsys):
    from tests.start_projects import deepeval_data

    data = deepeval_data([True] * 20 + [False] * 16)
    for i, case in enumerate(data["testCases"]):
        case["name"] = f"test_case_{i}"
    path = here / ".deepeval" / ".latest_run_full.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "DeepEval's default test case names (test_case_0, test_case_1, ...)" in flat(out)


# The install changed which logs are read, not the judge -------------------------------

@pytest.mark.parametrize("files, used, can_read_eval, expected", [
    (["logs/a.json"], ["logs/b.eval"], True, "keep"),  # the extra arrived: read the same logs
    (["logs/a.eval"], ["logs/b.json"], False, "cant"),  # the extra is gone: say so
    (["logs/a.json"], ["logs/a.json"], True, None),  # the same files
    (["logs/a.json"], ["logs/c.json"], True, None),  # a new run: a real change, if any
    (["r.json"], ["r2.json"], True, None),
])
def test_an_install_switch_between_json_and_eval_logs_is_known(files, used, can_read_eval,
                                                              expected):
    from judgekeeper.front import install_switch

    assert install_switch(files, used, can_read_eval) == expected


def test_marks_made_on_eval_logs_this_install_cannot_read_are_said(here, capsys, monkeypatch):
    from tests.start_projects import inspect_project

    for name in [n for n in sys.modules if n == "inspect_ai" or n.startswith("inspect_ai.")]:
        monkeypatch.setitem(sys.modules, name, None)  # an install without the extra
    monkeypatch.setitem(sys.modules, "inspect_ai", None)
    inspect_project(here, [True] * 20 + [False] * 16)
    code, out = run(capsys)
    assert code == 0, out
    start_json = here / ".judgekeeper" / "start.json"
    data = json.loads(start_json.read_text(encoding="utf-8"))
    data["results_files"] = ["logs/2026-10-03_support.eval"]  # marked with the extra
    start_json.write_text(json.dumps(data), encoding="utf-8")
    (here / "logs" / "2026-10-03_support.eval").write_bytes(b"PK\x03\x04" + b"\0" * 20)
    code, out = run(capsys)
    assert code == 3, out
    assert "Your LLM-as-a-judge changed" not in out
    assert ("Your marks were made on logs/2026-10-03_support.eval, which this install reads "
            "only with its Inspect extra. To keep checking the same answers,") in flat(out)
    assert "judgekeeper[inspect]" in assert_one_next_at_the_end(out)


# Kit follow-ups --------------------------------------------------------------------------------

def test_a_keyword_list_written_by_pandas_is_never_an_answer(here, capsys):
    columns = ["question", "answer_keywords", "response_text", "judge_verdict"]
    rows = [[question(i), str(["refund", "policy", "days"]),
             f"This is a full answer number {i} that explains the refund policy.",
             "FAIL" if i % 3 else "PASS"] for i in range(40)]
    write_csv(here / "results" / "results.csv", columns, rows)
    _, out = run(capsys, "results", "--metric", "judge_verdict")
    assert "Count each as its own answer" not in out, out
    assert "  answer:          response_text" in out


def test_a_standard_csv_with_two_verdict_columns_asks_which_judge(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", "pass" if i % 2 else "fail",
             "pass" if i % 3 else "fail"] for i in range(60)]
    write_csv(here / "results.csv", ["input", "output", "verdict", "judge_verdict"], rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "http://127.0.0.1" not in out
    assert out.index("judge_verdict (60 answers)") < out.index("verdict (60 answers)")
    line = assert_one_next_at_the_end(out)
    assert "--metric NAME" in line
    code, out = run(capsys, "--metric", "judge_verdict")
    assert code == 0, out
    assert "Your LLM-as-a-judge passed 40 answers and failed 20." in out
    assert "LLM-as-a-judge:  judge_verdict" in out


def test_a_standard_csv_model_column_of_rule_names_is_not_the_judge(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", "pass" if i % 2 else "fail",
             "string_match" if i < 9 else "checks+judge"] for i in range(60)]
    write_csv(here / "results.csv", ["input", "output", "verdict", "model"], rows)
    code, out = run(capsys)
    assert code == 0, out
    judge_line = next(x for x in out.splitlines() if x.startswith("LLM-as-a-judge:"))
    assert "checks+judge" not in judge_line and "string_match" not in judge_line
    assert "model not found in your results" in judge_line


@pytest.mark.skipif(not hasattr(__import__("os"), "geteuid") or __import__("os").geteuid() == 0,
                    reason="permissions mean nothing to root or on Windows")
def test_a_read_only_judgekeeper_folder_is_said_before_the_page_starts(here, capsys):
    import os

    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(20, 16))
    code, out = run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    try:
        for p in folder.rglob("*"):
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        os.chmod(folder, 0o555)
        code, out = run(capsys, "--no-browser")
    finally:
        os.chmod(folder, 0o755)
        for p in folder.rglob("*"):
            os.chmod(p, 0o755 if p.is_dir() else 0o644)
    assert code == 2, out
    assert "judgekeeper can't write in .judgekeeper/ (permission denied)" in flat(out)
    assert "could not start in the background" not in out and "page.log" not in out
    assert "remove the folder" not in out


def two_epoch_log(root: Path) -> Path:
    """An Inspect log with 2 epochs: 10 answers graded the same in both, 5 graded C then I."""
    base = json.loads(INSPECT.read_text(encoding="utf-8"))
    sample0 = base["samples"][0]
    samples = []
    for epoch in (1, 2):
        for i in range(15):
            s = json.loads(json.dumps(sample0))
            s.update(id=i, epoch=epoch, input=question(i))
            s["output"]["completion"] = f"Answer {i}."
            grade = "C" if i < 10 or epoch == 1 else "I"
            s["scores"] = {"model_graded_qa": {"value": grade, "explanation": "why",
                                               "history": []}}
            samples.append(s)
    spec = json.loads(json.dumps(base["eval"]))
    spec["scorers"] = [x for x in spec["scorers"] if x["name"] == "model_graded_qa"]
    path = root / "logs" / "2026-10-02_support.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**base, "eval": spec, "samples": samples}), encoding="utf-8")
    return path


def test_inspect_epochs_with_different_grades_are_said_and_counted(here, capsys):
    two_epoch_log(here)
    code, out = run(capsys)
    assert code == 3, out  # 20 answers: not enough for a first result
    assert "Answers:         20 different answers" in out
    assert ("(your file has 30 results: each answer was run 2 times, so each is counted once "
            "unless its grades differ)") in flat(out)
    assert ("5 answers got different grades when graded more than once (10 repeats in all); "
            "each repeat is its own answer.") in flat(out)


def test_the_judge_list_counts_answers_as_the_pool_does(here, capsys):
    """Two judges in a log with 2 epochs: the list says how many answers each has after
    repeats with the same grade are merged, the number the pool then shows."""
    path = two_epoch_log(here)
    data = json.loads(path.read_text(encoding="utf-8"))
    for s in data["samples"]:
        s["scores"]["rubric"] = {"value": "C", "explanation": "why", "history": []}
    data["eval"]["scorers"].append({"name": "rubric", "options": {}})
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "model_graded_qa (20 answers)" in out
    assert "rubric (15 answers)" in out


def test_no_answer_count_while_the_partial_credit_question_is_open(here, capsys):
    path = two_epoch_log(here)
    data = json.loads(path.read_text(encoding="utf-8"))
    for s in data["samples"][:4]:
        s["scores"]["model_graded_qa"]["value"] = "P"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "Inspect gave partial credit (P) on 4 answers." in flat(out)
    assert "Answers:" not in out
    assert "Eval tool:       Inspect AI" in out


# The Step 1 block ---------------------------------------------------------------------------

def block_of(out: str) -> list[str]:
    """The lines from "Eval tool:" up to the blank line after the read-from rows."""
    lines = out.splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("Eval tool:"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "")
    return lines[start:end]


def test_the_promptfoo_block_names_the_file_and_what_was_read(here, capsys):
    from tests.start_projects import RUBRIC, promptfoo_project, split

    promptfoo_project(here, split(23, 17))
    code, out = run(capsys)
    assert code == 0, out
    assert block_of(out) == [
        "Eval tool:       promptfoo",
        "File:            results.json",
        "Answers:         40 answers",
        "LLM-as-a-judge:  openai:gpt-4.1-mini",
        f'Rule:            "{" ".join(RUBRIC.split())}"',
        "Read from your file:",
        "  question   each test's vars",
        "  answer     each test's output",
        "  grade      your LLM-as-a-judge's Pass or Fail",
    ]
    assert "Your LLM-as-a-judge passed 23 answers and failed 17." in out
    assert "Your LLM-as-a-judge's grades" not in out and "(read from" not in out


def test_repeats_run_the_same_number_of_times_are_said_as_such(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(4, 2))
    rows = data["results"]["results"]
    data["results"]["results"] = rows + [json.loads(json.dumps(r)) for r in rows] * 2
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "Answers:         6 different answers" in out
    assert ("(your file has 18 results: each answer was run 3 times, so each is counted once)"
            in flat(out))
    assert "merged" not in out
    assert "Your LLM-as-a-judge passed 4 answers and failed 2." in out


def test_repeats_of_some_answers_only_are_said_as_such(here, capsys):
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(4, 2))
    rows = data["results"]["results"]
    data["results"]["results"] = rows + [json.loads(json.dumps(rows[0]))]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 3, out
    assert "Answers:         6 different answers" in out
    assert ("(your file has 7 results: some answers are in it more than once, so each is "
            "counted once)") in flat(out)


def test_the_deepeval_block_puts_the_pass_mark_in_the_grade_row(here, capsys):
    from tests.start_projects import deepeval_project, split

    deepeval_project(here, split(20, 16))
    code, out = run(capsys, "--metric", "Correctness [GEval]")
    assert code == 0, out
    block = block_of(out)
    assert "File:            .deepeval/.latest_run_full.json" in block
    assert "Answers:         36 answers" in block
    assert block[-5:] == [
        "Read from your file:",
        "  question   each test case's input",
        "  answer     each test case's actual_output",
        "  grade      the Correctness [GEval] score: Pass at 0.5 or more",
        "  reason     your LLM-as-a-judge's reason",
    ]
    assert "Pass mark:" not in out


def test_the_inspect_block_rows(here, capsys):
    from tests.start_projects import inspect_project, split

    inspect_project(here, split(20, 16))
    code, out = run(capsys)
    assert code == 0, out
    assert block_of(out)[-4:] == [
        "Read from your file:",
        "  question   each sample's input",
        "  answer     each sample's output",
        "  grade      the scorer's grade (C or I)",
    ]


def test_the_table_block_rows_name_the_columns_read(here, capsys):
    from tests.start_projects import split, table_project

    table_project(here, split(20, 16), model="gpt-4.1-mini", verdict_column="judge_verdict",
                  extra={"reason": [f"why {i}" for i in range(36)],
                         "human_label": ["pass"] * 36, "app_version": ["1.2"] * 36})
    code, out = run(capsys)
    assert code == 0, out
    assert block_of(out)[-8:] == [
        "Read from your file:",
        "  question      the input column",
        "  answer        the output column",
        "  grade         the judge_verdict column",
        "  reason        the reason column",
        "  model         the model column",
        "  version       the app_version column",
        "  your labels   the human_label column",
    ]
    assert "Read the columns" not in out


def test_a_promptfoo_exec_grader_is_your_own_script(here, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(20, 16), model="exec: python3 graders/grader.py")
    code, out = run(capsys)
    assert code == 0, out
    assert "LLM-as-a-judge:  your own script (python3 grader.py)" in out
    assert "exec:" not in out


def test_one_pass_is_said_in_the_singular(here, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(here, split(1, 17))
    code, out = run(capsys)
    assert code == 3, out
    assert "Your LLM-as-a-judge passed 1 answer and failed 17." in out


def test_deepeval_nothing_checked_is_said_plainly(here, capsys):
    from tests.start_projects import deepeval_data, split

    data = deepeval_data(split(26, 14))
    for case in data["testCases"][:8]:
        for md in case["metricsData"]:
            if md["name"] == "Correctness [GEval]":
                md.update(score=1.0, success=True, verboseLogs="Criteria:\nx \n \nVerdicts:\n[]")
    path = here / ".deepeval" / ".latest_run_full.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys, "--metric", "Correctness [GEval]")
    assert code == 0, out
    assert ("Checked: on 8 answers your LLM-as-a-judge found nothing to check, but DeepEval still gave "
            "them full marks, so they are left out.") in flat(out)
    assert "checked nothing" not in out
