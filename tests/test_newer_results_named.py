"""A plain run or `mark` that reads newer results whose grades are not taken on (only `check`
takes them on): the line names the file whose grades the numbers use, or the grades from
before when the file read is that file graded again, and the check that compares them, or,
after a check that found them worse, that check. For every eval tool: a table, promptfoo."""

from __future__ import annotations

import os
import time

import pytest

from judgekeeper.start_label import Workspace
from tests.start_projects import promptfoo_data, split, table_project
from tests.test_check import MODEL, TAG, _flat, _marked, _write
from tests.test_check_claims import _regraded
from tests.test_flow_across_runs import _jk, _mark


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _truth(i: int) -> bool:
    return i % 3 != 0


def _newer(path, seconds: int = 60) -> None:
    later = time.time() + seconds
    os.utime(path, (later, later))


def _run(capsys, *argv) -> str:
    said = _flat(_jk(capsys, *argv, "--no-browser", "--port", "0")[1])
    _jk(capsys, "--stop")
    return said


OLD = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(60)]


def _table_marked(here, capsys) -> None:
    """A CSV table of 60 answers, every one marked, and its result."""
    table_project(here, OLD)
    _run(capsys)
    _mark(Workspace(here), {i: "pass" if _truth(i) else "fail" for i in range(60)})
    _run(capsys)


@pytest.mark.parametrize("command", [[], ["mark"]])
def test_a_regraded_table_beside_names_the_file_the_numbers_use(here, capsys, command):
    _table_marked(here, capsys)
    table_project(here, [(not v) if i % 10 == 0 else v for i, v in enumerate(OLD)],
                  name="new-results.csv")
    _newer(here / "new-results.csv")
    said = _run(capsys, *command)
    assert ("Your answers were graded again in new-results.csv, and 6 of your marked answers "
            "got a different grade. The numbers below still use the grades in results.csv. To "
            "compare, run `judgekeeper check`.") in said, said
    assert "the newest results here" not in said and "grades changed on" not in said, said


def test_a_table_graded_again_in_place_says_the_grades_from_before(here, capsys):
    _table_marked(here, capsys)
    table_project(here, [(not v) if i % 10 == 0 else v for i, v in enumerate(OLD)])
    _newer(here / "results.csv")
    said = _run(capsys)
    assert ("Your answers were graded again in results.csv, and 6 of your marked answers got "
            "a different grade. The numbers below still use the grades from before. To "
            "compare, run `judgekeeper check`.") in said, said


def test_after_a_worse_check_of_a_table_the_line_names_that_check(here, capsys):
    _table_marked(here, capsys)
    table_project(here, [(not v) if i % 2 == 0 or i % 4 == 1 else v for i, v in enumerate(OLD)],
                  name="worse.csv")
    _newer(here / "worse.csv")
    code, out = _jk(capsys, "check", "worse.csv")
    assert code == 1, out
    said = _run(capsys)
    assert ("Your LLM-as-a-judge's grades changed on 45 of your marked answers. Your last check "
            "found your LLM-as-a-judge in worse.csv worse, so the numbers below still use the "
            "grades in results.csv.") in said, said
    assert "the newest results here" not in said and "To compare" not in said, said
    assert said.count("Your last check found") == 1, said


@pytest.mark.parametrize("command", [[], ["mark"]])
def test_after_a_worse_check_of_a_same_rule_copy_the_line_names_that_check(here, capsys,
                                                                           command):
    """A copy graded again and taken on by a check, then one a check found worse: the
    numbers use the copy taken on, never the one read."""
    _marked(here)
    _regraded(here, [3], name="results-regraded.json")
    _newer(here / "results-regraded.json")
    assert _jk(capsys, "check", "results-regraded.json")[0] == 0
    verdicts = split(25, 25)
    for i in [*range(8), *range(25, 33)]:
        verdicts[i] = not verdicts[i]
    data = promptfoo_data(verdicts, model=MODEL, tag=TAG, created="2026-10-14T09:00:00Z")
    data["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "results-worse.json", data)
    _newer(here / "results-worse.json", 120)
    assert _jk(capsys, "check", "results-worse.json")[0] == 1
    said = _run(capsys, *command)
    assert ("Same model and rule as before, yet 15 of your marked answers got a different "
            "grade: your LLM-as-a-judge doesn't always grade the same answer the same way. Your "
            "last check found your LLM-as-a-judge in results-worse.json worse, so the numbers "
            "below still use the grades in results-regraded.json.") in said, said
    assert "the newest results here" not in said, said
    assert said.count("Your last check found") == 1, said


def test_a_changed_judge_in_newer_results_names_the_grades_the_numbers_use(here, capsys):
    from tests.test_check import HAIKU

    _marked(here)
    data = promptfoo_data(split(25, 25), model=HAIKU, tag=TAG, created="2026-10-14T09:00:00Z")
    data["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "results-haiku.json", data)
    _newer(here / "results-haiku.json")
    said = _run(capsys)
    assert "Your LLM-as-a-judge changed since your marks" in said, said
    assert "The numbers below still use the grades in results.json." in said, said
    assert "Next: run `judgekeeper check` to re-check your changed LLM-as-a-judge" in said, said
