"""`judgekeeper start` on DeepEval results: the judge's rule when GEval was built with
evaluation steps and no criteria, which file is read when DeepEval saved both its hidden
copies and a results folder, and when the DEEPEVAL_RESULTS_FOLDER tip is shown.

DeepEval 4.2 writes `.deepeval/.latest_test_run.json` (the run under a "testRunData" key)
and `.deepeval/.latest_run_full.json` on every run, and one `test_run_<time>.json` per run
in DEEPEVAL_RESULTS_FOLDER when it is set. The hidden folder is often git-ignored, so the
results folder is what a project keeps.
"""

from __future__ import annotations

import json
import os

import pytest

from judgekeeper import find, start
from judgekeeper.cli import main
from tests.start_projects import deepeval_data, deepeval_project, split

STEPS_ONLY = ('Criteria:\nNone \n \nEvaluation Steps:\n[\n    "Check whether the final answer '
              'matches the expected output.",\n    "Penalise heavily any wrong working.",\n    '
              '"Penalise rounded answers.",\n    "Penalise words a 12-year-old would not '
              'know."\n] \n \nRubric:\nNone \n \nScore: 0.9')


@pytest.fixture(autouse=True)
def no_results_variable(monkeypatch):
    monkeypatch.delenv("DEEPEVAL_RESULTS_FOLDER", raising=False)


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    """These tests stop where labeling starts."""
    monkeypatch.setattr("judgekeeper.start_label.run_labeling",
                        lambda found, port, open_browser, say, command="": 0)


def run(capsys, *argv):
    code = main(["start", *map(str, argv), "--yes"])
    out, err = capsys.readouterr()
    return code, out + err


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

def _hidden_copies(root, data, which=(".latest_test_run.json", ".latest_run_full.json")):
    for name in which:
        wrapped = {"testRunData": data} if name == ".latest_test_run.json" else data
        _write(root / ".deepeval" / name, wrapped)


def test_the_results_folder_wins_over_the_hidden_copies(tmp_path, capsys):
    data = deepeval_data(split(20, 12))
    _write(tmp_path / "results" / "test_run_20261006_154129.json", data)
    _hidden_copies(tmp_path, data)
    code, out = run(capsys, tmp_path)
    assert code == 0
    assert "  Results file    results/test_run_20261006_154129.json (saved " in out
    assert ".deepeval" not in out  # the same run: nothing to say
    assert "repeats" not in out


def test_a_different_run_in_the_hidden_copy_is_named(tmp_path, capsys):
    _write(tmp_path / "results" / "test_run_20261006_154129.json", deepeval_data(split(20, 12)))
    _hidden_copies(tmp_path, deepeval_data(split(30, 2), tag=" (later)"),
                   which=(".latest_test_run.json",))
    code, out = run(capsys, tmp_path)
    assert code == 0
    assert "  Results file    results/test_run_20261006_154129.json" in out
    assert ("DeepEval's hidden copy .deepeval/.latest_test_run.json holds a different run. "
            "Using the newest file in your results folder, results/test_run_20261006_154129."
            "json; to use the other: judgekeeper start .deepeval/.latest_test_run.json") in out


def test_the_two_hidden_copies_count_once(tmp_path, capsys):
    _hidden_copies(tmp_path, deepeval_data(split(20, 12)))
    found = find.search(tmp_path)
    assert len(found.readable("deepeval")) == 1
    code, out = run(capsys, tmp_path)
    assert code == 0 and "repeats" not in out
    assert "Its decisions   32 answers: 20 passed, 12 failed" in out


def test_the_hidden_copy_alone_is_read_as_before(tmp_path, capsys):
    _hidden_copies(tmp_path, deepeval_data(split(20, 12)), which=(".latest_test_run.json",))
    code, out = run(capsys, tmp_path)
    assert code == 0
    assert "  Results file    .deepeval/.latest_test_run.json (saved " in out


# The DEEPEVAL_RESULTS_FOLDER tip ------------------------------------------------------------

TIP = "DEEPEVAL_RESULTS_FOLDER"


def _more(root):
    return " ".join(start.more_answers(start.find_judge(root)))


def test_the_tip_shows_when_only_the_hidden_copy_exists(tmp_path):
    deepeval_project(tmp_path, split(10, 6))
    assert TIP in _more(tmp_path)


def test_no_tip_when_a_results_folder_exists(tmp_path):
    deepeval_project(tmp_path, split(10, 6), name="results/test_run_20261006_154129.json")
    assert TIP not in _more(tmp_path)


def test_no_tip_when_the_file_is_given_from_a_results_folder(tmp_path):
    path = deepeval_project(tmp_path, split(10, 6), name="results/test_run_20261006_154129.json")
    assert TIP not in _more(path)


def test_no_tip_when_the_variable_is_set(tmp_path, monkeypatch):
    deepeval_project(tmp_path, split(10, 6))
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", os.fspath(tmp_path / "results"))
    assert TIP not in _more(tmp_path)


def test_no_tip_in_the_too_few_message_when_runs_are_kept(tmp_path, capsys):
    deepeval_project(tmp_path, split(10, 6), name="results/test_run_20261006_154129.json")
    code = main(["start", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == start.EXIT_QUESTION
    assert "You have 16 answers. judgekeeper needs at least 30 to show a result." in out
    assert TIP not in out
