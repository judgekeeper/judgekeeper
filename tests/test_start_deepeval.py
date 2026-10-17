"""`judgekeeper` on DeepEval results: the judge's rule when GEval was built with
evaluation steps and no criteria, which file is read when DeepEval saved both its hidden
copies and a results folder, and when the DEEPEVAL_RESULTS_FOLDER tip is shown.

DeepEval 4.2 writes `.deepeval/.latest_test_run.json` (the run under a "testRunData" key)
and `.deepeval/.latest_run_full.json` on every run, and one `test_run_<time>.json` per run
in DEEPEVAL_RESULTS_FOLDER when it is set. The hidden folder is often git-ignored, so the
results folder is what a project keeps.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import start
from tests.start_projects import deepeval_data, deepeval_project, split

STEPS_ONLY = ('Criteria:\nNone \n \nEvaluation Steps:\n[\n    "Check whether the final answer '
              'matches the expected output.",\n    "Penalise heavily any wrong working.",\n    '
              '"Penalise rounded answers.",\n    "Penalise words a 12-year-old would not '
              'know."\n] \n \nRubric:\nNone \n \nScore: 0.9')


@pytest.fixture(autouse=True)
def no_results_variable(monkeypatch):
    monkeypatch.delenv("DEEPEVAL_RESULTS_FOLDER", raising=False)


def _steps_only(data: dict) -> dict:
    for case in data["testCases"]:
        for metric in case["metricsData"]:
            metric["verboseLogs"] = STEPS_ONLY
    return data


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# The rule -----------------------------------------------------------------------------------

def test_evaluation_steps_and_no_criteria_show_the_first_step_never_none(tmp_path):
    _write(tmp_path / "results" / "test_run_20261006_154129.json",
           _steps_only(deepeval_data(split(49, 1), model="claude-haiku-4-5-20251001 "
                                                          "(Anthropic)")))
    found = start.find_judge(tmp_path)
    assert '"None"' not in found.judge and "None" not in (found.rule or "")
    assert found.judge.startswith('Correctness [GEval] "Check whether the final answer')
    assert found.judge.endswith("with claude-haiku-4-5-20251001 (Anthropic)")
    assert found.rule.splitlines() == [
        "1. Check whether the final answer matches the expected output.",
        "2. Penalise heavily any wrong working.", "3. Penalise rounded answers.",
        "4. Penalise words a 12-year-old would not know."]


def test_criteria_still_come_first_when_there_are_some(tmp_path):
    deepeval_project(tmp_path, split(20, 12))
    found = start.find_judge(tmp_path)
    assert found.judge.startswith('Correctness [GEval] "Is the actual output factually correct')


@pytest.mark.parametrize("prompt, rule", [
    ("Criteria:\nNone \n \nEvaluation Steps:\n[] \n \nRubric:\nNone", None),
    ("Criteria:\nNone", None),
    ('Criteria:\nNone \n \nEvaluation Steps:\n["Only step."]', "1. Only step."),
    ("Criteria:\nNone \n \nEvaluation Steps:\nnot a list", "not a list"),
])
def test_a_rule_of_none_is_no_rule(prompt, rule):
    assert start.rule_text(prompt) == rule
    assert "None" not in (start.rubric_line(prompt) or "")


def test_the_rubric_line_drops_the_step_number():
    assert start.rubric_line(STEPS_ONLY) == ("Check whether the final answer matches the "
                                             "expected output.")


# Which file -----------------------------------------------------------------------------------


# The DEEPEVAL_RESULTS_FOLDER tip ------------------------------------------------------------


