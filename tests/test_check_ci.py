"""`judgekeeper check` in CI (the GitHub Action, action.yml).

`mode: fast` runs `check --fast` on a checkout that holds only what judgekeeper commits:
.judgekeeper/judge.json (the judge last checked, and its name) and history.jsonl (the results,
with how many marks). `mode: full` runs `check --ci`: the team committed the marks too, and
the workflow (with the key as a secret) is their permission to ask the judge; `--ci` runs
only in GitHub Actions. No test calls an API.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from judgekeeper import judge_setup
from judgekeeper.cli import main
from tests import test_check
from tests.test_check import (
    HAIKU,
    LENIENT,
    MARKED,
    MODEL,
    _history,
    _marked,
    _new_outputs,
    _on,
    _results,
    run,
)

here, judge, no_calls = test_check.here, test_check.judge, test_check.no_calls  # fixtures

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "action"
COMMITTED = {".gitignore", "judge.json", "history.jsonl"}


def _result_line(ws, n_pass=25, n_fail=25) -> None:
    line = {"time": "2026-10-12T09:30:00Z", "kind": "result", "marks": n_pass + n_fail,
            "pass": n_pass, "fail": n_fail}
    with open(ws.dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def _checkout(ws) -> None:
    """Only what judgekeeper commits is left, as in a fresh checkout."""
    for p in ws.dir.iterdir():
        if p.name not in COMMITTED:
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def test_judge_json_keeps_the_judges_name(here, capsys):
    ws = _marked(here)
    assert json.loads((ws.dir / "judge.json").read_text(encoding="utf-8"))["metric"] == \
        "llm-rubric"
    assert "metric" not in judge_setup.read(ws)["setup"]  # the name is not part of the hash


def test_fast_with_only_judge_json_and_history_committed(here, capsys, no_calls):
    ws = _marked(here)
    _result_line(ws)
    _checkout(ws)
    assert run(capsys, "--fast") == (0, "")
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys, "--fast")
    assert code == 3
    assert out == (f"Your judge changed: model {MODEL} -> {HAIKU}.\n"
                   "Next: run `judgekeeper check`.\n")


def test_fast_in_a_checkout_without_enough_marks_says_nothing(here, capsys):
    ws = _marked(here)
    _result_line(ws, n_pass=10, n_fail=25)
    _checkout(ws)
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys, "--fast") == (0, "")


def test_fast_in_a_checkout_with_no_result_says_nothing(here, capsys):
    ws = _marked(here)
    _checkout(ws)
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys, "--fast") == (0, "")


def test_ci_runs_only_in_github_actions(here, capsys, monkeypatch, no_calls):
    _marked(here)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    code, out = run(capsys, "--ci")
    assert code == 2
    assert "`--ci` is for judgekeeper's GitHub Action" in out


def test_ci_without_the_marks_committed_says_what_to_commit(here, capsys, monkeypatch):
    ws = _marked(here)
    _result_line(ws)
    _checkout(ws)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    code, out = run(capsys, "--ci")
    assert code == 3
    assert ("Your marks are not in this checkout: `mode: full` needs .judgekeeper/start.json, "
            "marks.jsonl and pool.jsonl committed.") in out


def test_ci_asks_the_judge_and_says_ci_in_the_history(here, capsys, monkeypatch, judge):
    ws = _marked(here)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys, "--ci")
    assert code == 0, out
    assert "Re-checked on your 50 marks (50 asked again)." in out
    assert _history(ws)[-1]["trigger"] == "ci"


def test_ci_never_runs_a_judge_that_can_change_files(here, capsys, monkeypatch, no_calls):
    _marked(here, agent=True)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _results(here, MARKED, model=HAIKU, agent=True, outputs=_new_outputs())
    code, out = run(capsys, "--ci")
    assert code == 3
    assert "judgekeeper doesn't run a judge that can change files by itself." in out


def test_ci_keeps_the_persons_checks_off_choice_out_of_it(here, capsys, monkeypatch, judge):
    """checks.json is the person's, on their computer: --ci never writes it."""
    ws = _marked(here)
    _on(ws, on=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    before = (ws.dir / "checks.json").read_text(encoding="utf-8")
    assert run(capsys, "--ci")[0] == 0
    assert (ws.dir / "checks.json").read_text(encoding="utf-8") == before


def test_ci_is_hidden_from_the_help(capsys):
    assert main(["check", "--help"]) == 0
    assert "--ci" not in capsys.readouterr().out


# The fixture the `action` CI job runs the action on ----------------------------------------------

def test_the_action_fixture_is_a_checkout_with_a_judge_and_marks(tmp_path, capsys,
                                                                monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    assert {p.name for p in (project / ".judgekeeper").iterdir()} == COMMITTED
    monkeypatch.chdir(project)
    assert main(["check", "--fast"]) == 0
    assert capsys.readouterr().out == ""
    shutil.copyfile(project / "changed" / "results.json", project / "results.json")
    assert main(["check", "--fast"]) == 3
    assert capsys.readouterr().out.startswith("Your judge changed: model ")


@pytest.mark.parametrize("name", ["results.json", "changed/results.json"])
def test_the_action_fixture_holds_no_real_answers(name):
    text = (FIXTURE / name).read_text(encoding="utf-8")
    assert "Question 0" in text and "@" not in text
