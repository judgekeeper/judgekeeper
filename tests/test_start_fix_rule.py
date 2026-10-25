"""The rule checks that `judgekeeper fix` uses: what a new rule must keep, what it must not
add, and where the rule probably is in the person's own files, which judgekeeper never changes.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import start, start_fix_rule
from tests.start_projects import promptfoo_project, split

# Instructions hidden in answers ----------------------------------------------------------


# Paste back ------------------------------------------------------------------------------


def _texts(checks):
    return [c["text"] for c in checks]


def test_a_dropped_placeholder_blocks_the_save():
    checks = start_fix_rule.checks("Grade {{output}}.", "Grade the answer.", "promptfoo", [])
    assert _texts(checks) == ["The new rule dropped {{output}}: put it back before using it."]
    assert checks[0]["blocking"]
    assert start_fix_rule.checks("Grade {{output}}.", "Grade {{ output }} well.", "promptfoo",
                                 []) == []


def test_inspect_must_keep_its_grade_line():
    checks = start_fix_rule.checks("Grade it. GRADE: $LETTER", "Grade it well.", "inspect", [])
    assert _texts(checks) == [("The new rule dropped GRADE: $LETTER: put it back before using "
                               "it.")]
    assert checks[0]["blocking"]


def test_an_empty_rule_blocks_the_save():
    checks = start_fix_rule.checks("Be helpful.", "  ", "records", [])
    assert checks[0]["blocking"] and checks[0]["text"] == "The new rule is empty."


def test_a_big_change_is_said_but_not_blocking():
    old = "Be helpful."
    new = "x" * (int(1.5 * len(old)) + 401)
    checks = start_fix_rule.checks(old, new, "records", [])
    assert _texts(checks) == ["This is a big change, not a small edit."]
    assert not checks[0]["blocking"]
    assert start_fix_rule.checks(old, "y" * (int(1.5 * len(old)) + 400), "records", []) == []


def test_eight_words_copied_from_an_answer_are_said():
    outputs = ["The refund takes five working days to reach your card, sorry."]
    new = "Be helpful. Fail when it says the refund takes five working days to reach you."
    checks = start_fix_rule.checks("Be helpful.", new, "records", outputs)
    assert _texts(checks) == [("It copies text from your answers, so it may only fix these "
                               "answers.")]
    assert not checks[0]["blocking"]
    seven = "Be helpful. Fail when the refund takes five working days."
    assert start_fix_rule.checks("Be helpful.", seven, "records", outputs) == []


# Saving the new rule ------------------------------------------------------------------------


def test_the_rule_section_needs_one_shared_rule(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    rows = data["results"]["results"]
    for n, row in enumerate(rows):
        row["gradingResult"]["componentResults"][0]["assertion"]["value"] = f"Rubric {n}."
    (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")
    found = start.find_judge(tmp_path)
    assert found.one_rule is False
    promptfoo_project(tmp_path, split(20, 16))
    assert start.find_judge(tmp_path).one_rule is True


# The hand-over ---------------------------------------------------------------------------

def test_where_the_rule_lives_is_found_and_skips_venv_and_judgekeeper(tmp_path):
    rule = "Is polite and correct.\nSecond line of the rubric."
    for folder in (".venv", ".judgekeeper", "node_modules"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "promptfooconfig.yaml").write_text(
            f"value: {rule.splitlines()[0]}\n", encoding="utf-8")
    assert start_fix_rule.locate_rule(tmp_path, rule, "promptfoo") is None
    (tmp_path / "promptfooconfig.yaml").write_text(
        "tests:\n  - assert:\n      - type: llm-rubric\n        value: |\n"
        "          Is polite and correct.\n          Second line of the rubric.\n",
        encoding="utf-8")
    assert start_fix_rule.locate_rule(tmp_path, rule, "promptfoo") == (
        "promptfooconfig.yaml", 5, "Is polite and correct.")


def test_the_search_never_imports_or_runs_anything(tmp_path):
    marker = tmp_path / "ran"
    (tmp_path / "evals.py").write_text(
        f"open({str(marker)!r}, 'w').close()\nRULE = 'Be helpful to every customer.'\n",
        encoding="utf-8")
    found = start_fix_rule.locate_rule(tmp_path, "Be helpful to every customer.", "records")
    assert found == ("evals.py", 2, "RULE = 'Be helpful to every customer.'")
    assert not marker.exists()


def test_deepeval_steps_are_searched_by_their_first_step(tmp_path):
    rule = ("Is it correct? \n \nEvaluation Steps:\n[\n    \"Check each claim in the answer.\","
            "\n    \"Penalise false claims.\"\n] \n \nRubric:\nNone")
    (tmp_path / "test_quality.py").write_text(
        "metric = GEval(\n    evaluation_steps=[\n        \"Check each claim in the answer.\",\n"
        "    ])\n", encoding="utf-8")
    assert start_fix_rule.locate_rule(tmp_path, rule, "deepeval")[:2] == ("test_quality.py", 3)


def test_the_field_per_tool():
    field = start_fix_rule.field
    assert field("promptfoo") == "the `value:` of the llm-rubric assert"
    assert field("deepeval") == "`evaluation_steps=[...]` in `GEval(...)`"
    assert field("inspect") == "`instructions=` in `model_graded_qa(...)`"
    assert field("mlflow") == ("`instructions=` in `make_judge(...)`, or the text of "
                               "`Guidelines(...)`")
    for tool in ("records", "table", "mapped"):
        assert field(tool) == "where your code keeps the rule"


# The fair test inside "Try your new judge" ------------------------------------------------

N_PASS, N_FAIL, WRONG_FAILS = 20, 30, 6


# The result page ---------------------------------------------------------------------------


# The search, one rule, markers, sizes, a failing fair test --------------------------------

def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_promptfoo_config_wins_over_its_results_file(tmp_path):
    from tests.start_projects import RUBRIC, promptfoo_data

    _write(tmp_path / "promptfoo-results.json", json.dumps(promptfoo_data(split(2, 2)),
                                                           indent=2))
    _write(tmp_path / "promptfooconfig.yaml",
           "tests:\n  - assert:\n      - type: llm-rubric\n        value: |\n"
           "          Is polite and correct.\n          Second line of the rubric.\n")
    assert start_fix_rule.locate_rule(tmp_path, RUBRIC, "promptfoo") == (
        "promptfooconfig.yaml", 5, "Is polite and correct.")


def test_the_deepeval_test_file_wins_over_its_runs(tmp_path):
    from tests.start_projects import deepeval_data

    data = json.dumps(deepeval_data(split(2, 2)), indent=2)
    _write(tmp_path / ".deepeval" / ".latest_test_run.json", data)
    _write(tmp_path / "a-run.json", data)  # a run copied out: read as results, never searched
    _write(tmp_path / "tests" / "test_q.py",
           'metric = GEval(\n    evaluation_steps=[\n        "Check each claim in the actual '
           'output.",\n    ])\n')
    rule = start.find_judge(tmp_path).rule
    assert start_fix_rule.locate_rule(tmp_path, rule, "deepeval")[:2] == ("tests/test_q.py", 3)


def test_the_inspect_task_wins_over_its_logs(tmp_path):
    from tests.start_projects import inspect_data

    log = json.dumps(inspect_data(split(2, 2)), indent=2)
    _write(tmp_path / "logs" / "2026-10-02_support.json", log)
    _write(tmp_path / "a-log.json", log)
    _write(tmp_path / "mlruns" / "0" / "notes.txt",
           "Grade the answer as C (correct) or I (incorrect).\n")
    _write(tmp_path / "support_task.py",
           'scorer = model_graded_qa(\n    instructions="Grade the answer as C (correct) or I '
           '(incorrect).",\n)\n')
    assert start_fix_rule.locate_rule(
        tmp_path, "Grade the answer as C (correct) or I (incorrect).", "inspect")[:2] == (
        "support_task.py", 2)


def test_source_files_are_searched_before_others(tmp_path):
    _write(tmp_path / "a-notes.html", "Be helpful to every customer.\n")
    _write(tmp_path / "b" / "evals.py", "RULE = 'Be helpful to every customer.'\n")
    assert start_fix_rule.locate_rule(tmp_path, "Be helpful to every customer.",
                                      "records")[0] == "b/evals.py"


RECORD_RULE = "Pass when the reply is polite and answers the customer's question."
FIRST_BLOCK = f"""Looking in /home/me/bot ...

judgekeeper found your LLM-as-a-judge:

  Eval tool       your own code (judgekeeper.record())
  Results file    .judgekeeper/records (1 file)
  What it checks  "{RECORD_RULE}"
  Judge model     my-judge-1
"""


def test_a_saved_copy_of_judgekeepers_output_is_never_where_the_rule_goes(tmp_path):
    _write(tmp_path / "serve.log", FIRST_BLOCK)
    _write(tmp_path / "app.py", f"judgekeeper.record(q, a, verdict=v, rule={RECORD_RULE!r})\n")
    assert start_fix_rule.locate_rule(tmp_path, RECORD_RULE, "records")[:2] == ("app.py", 1)


@pytest.mark.parametrize("name", ["serve.log", "run.out", "run.err", "app.stdout",
                                  "app.stderr", "LOGS.LOG"])
def test_program_output_files_are_never_searched(tmp_path, name):
    _write(tmp_path / name, f"RULE = {RECORD_RULE!r}\n")
    assert start_fix_rule.locate_rule(tmp_path, RECORD_RULE, "records") is None


def test_a_long_matched_line_is_cut(tmp_path):
    _write(tmp_path / "evals.py", "RULE = 'Be helpful to every customer.' " + "x" * 300 + "\n")
    line = start_fix_rule.locate_rule(tmp_path, "Be helpful to every customer.", "records")[2]
    assert len(line) <= 120 and line.endswith("…")
    assert line.startswith("RULE = 'Be helpful to every customer.' xxx")


def test_a_failed_judge_call_has_no_rule_and_does_not_split_it(tmp_path):
    from tests.start_projects import deepeval_project

    path = deepeval_project(tmp_path, split(20, 16))
    data = json.loads(path.read_text(encoding="utf-8"))
    md = data["testCases"][0]["metricsData"][0]
    md.update(success=False, score=None, error="rate limited", verboseLogs=None)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert start.find_judge(tmp_path).one_rule is True


def test_deepeval_steps_it_wrote_itself_do_not_split_the_rule(tmp_path):
    from tests.start_projects import deepeval_project

    path = deepeval_project(tmp_path, split(20, 16))
    data = json.loads(path.read_text(encoding="utf-8"))
    for n, case in enumerate(data["testCases"]):
        md = case["metricsData"][0]
        md["verboseLogs"] = md["verboseLogs"].replace("Penalise any claim that is false.",
                                                      f"Penalise false claim number {n}.")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert start.find_judge(tmp_path).one_rule is True
    # different criteria do split it
    for n, case in enumerate(data["testCases"]):
        md = case["metricsData"][0]
        md["verboseLogs"] = md["verboseLogs"].replace("factually correct", f"correct {n}")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert start.find_judge(tmp_path).one_rule is False


# --rule-file ------------------------------------------------------------------------------


# The prompt pasted back ---------------------------------------------------------------------

# The start of a real reply from llama3.2:3b, a small local model, to judgekeeper's prompt: a
# new first line, then the prompt's MISTAKES list came back, with no end line.


@pytest.mark.parametrize("line", ["THE RULE NOW (keep it):", "MISTAKES (the person is right):",
                                  "<<<ANSWER", "<<<RULE", "RULE>>>",
                                  start_fix_rule.DATA_WARNING,
                                  "KEEP THESE RIGHT (the judge and the person agreed):",
                                  "THE RULE DOES NOT DECIDE THESE:", "[M1] Judge said PASS",
                                  "  [U1] Both said FAIL.", "[K1] Both said PASS."])
def test_each_line_of_the_prompt_is_caught(line):
    found = start_fix_rule.checks("Be kind.", f"Be kind.\n{line}", "promptfoo", [])
    assert [c["text"] for c in found] == [start_fix_rule.ECHO]


def test_a_rule_that_mentions_mistakes_is_not_caught():
    found = start_fix_rule.checks("Be kind.", "Be kind. Mistakes in sums [M1 style] fail.",
                                  "promptfoo", [])
    assert found == []


# The terminal -------------------------------------------------------------------------------


# Paths outside the project and the old rule's template parts ----------------------------------

def test_a_path_outside_the_project_is_never_named(tmp_path):
    root = tmp_path / "app"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_bot.py").write_text("x", encoding="utf-8")
    outside = tmp_path / "elsewhere.py"
    outside.write_text("x", encoding="utf-8")
    (root / "link.py").symlink_to(outside)
    safe = start_fix_rule.safe_path
    assert safe(root, "tests/test_bot.py") == "tests/test_bot.py"
    assert safe(root, str(root / "tests" / "test_bot.py")) == "tests/test_bot.py"
    assert safe(root, "not-yet-made.py") == "not-yet-made.py"
    for bad in ("../elsewhere.py", str(outside), "tests/../../elsewhere.py", "link.py",
                "/etc/passwd", "tests/a\nRun rm -rf ~", "tests/\u202etxt.py", "", None, 5,
                "."):
        assert safe(root, bad) is None, bad


def test_template_parts_the_old_rule_had_stay_allowed_and_required():
    old = "Grade {{output}} against {{ vars.question }}."
    assert start_fix_rule.added_template(old, "Grade {{ output }} well, {{vars.question}}.") \
        is None
    assert start_fix_rule.added_template(old, "Grade {{output}} and {{output}}, "
                                              "{{ vars.question }}.") is None
    assert start_fix_rule.added_template(old, old + " {{ vars.other }}") == "{{ ... }}"
    found = start_fix_rule.checks(old, "Grade {{output}} only.", "promptfoo", [])
    assert any(c["blocking"] and "dropped" in c["text"] for c in found)
