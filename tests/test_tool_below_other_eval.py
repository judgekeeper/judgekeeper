"""`judgekeeper --tool X` in a folder with no results of its own names the project below that
holds X's results, unless that project's session reads another eval (a table of answers) and
the results of X beside it are never read there: the step then says to put them in a folder of
their own, and that step reads them."""

from __future__ import annotations

import re
import shlex
import shutil

import pytest

from tests.start_projects import deepeval_project, inspect_project, promptfoo_project, split
from tests.test_answers_without_grades import write_answers
from tests.test_services_in_one_repo import _run

OTHER_EVAL = "shares few questions with the results you marked"
OF_ITS_OWN = "in a folder of its own"


@pytest.fixture
def services(tmp_path, monkeypatch):
    """A folder of services that is a project of its own (a git top), with no results in it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "services"
    (top / ".git").mkdir(parents=True)
    return top


def _session_on_answers(capsys, monkeypatch, folder) -> None:
    """folder/answers.csv (no grades) and a session started on it, with no marks."""
    folder.mkdir()
    write_answers(folder, 12, name="answers")
    code, said = _run(capsys, monkeypatch, folder, "mark", "answers.csv")
    assert code == 0, said


def _pf_bot(capsys, monkeypatch, services):
    bot = services / "pf-bot"
    _session_on_answers(capsys, monkeypatch, bot)
    promptfoo_project(bot, split(20, 20), name="evals/out.json", config=False, tag="pf")
    return bot / "evals" / "out.json"


def _de_bot(capsys, monkeypatch, services):
    bot = services / "de-bot"
    _session_on_answers(capsys, monkeypatch, bot)
    return deepeval_project(bot, split(20, 20), tag="de")


def _printed_step(said: str) -> tuple[str, list[str]]:
    """(the file the step puts in a folder of its own, the arguments of the command it runs
    there), as the stop prints them."""
    step = re.search(r"put (\S+) in a folder of its own, then run `([^`]*)` there", said)
    assert step, said
    program, *args = shlex.split(step[2])
    assert program == "judgekeeper", said
    return step[1], args


@pytest.mark.parametrize("tool, build, shown", [
    ("promptfoo", _pf_bot, "pf-bot/evals/out.json"),
    ("deepeval", _de_bot, "de-bot/.deepeval/.latest_run_full.json"),
])
def test_a_session_on_another_eval_is_not_named_for_the_tools_results(
        tmp_path, capsys, monkeypatch, services, tool, build, shown):
    build(capsys, monkeypatch, services)
    code, said = _run(capsys, monkeypatch, services, "--tool", tool)
    assert code == 2, said
    assert f"{shown} {OTHER_EVAL} (" in said, said
    assert f"put {shown} {OF_ITS_OWN}" in said, said
    assert f"--tool {tool}" not in said, said  # the command that only stops again


@pytest.mark.parametrize("tool, build", [("promptfoo", _pf_bot), ("deepeval", _de_bot)])
def test_the_printed_step_reads_the_results_when_pasted(
        tmp_path, capsys, monkeypatch, services, tool, build):
    path = build(capsys, monkeypatch, services)
    code, said = _run(capsys, monkeypatch, services, "--tool", tool)
    assert code == 2, said
    file, args = _printed_step(said)
    own = services / "of-its-own"
    own.mkdir()
    shutil.copy(services / file, own / path.name)  # "put it in a folder of its own"
    code, said = _run(capsys, monkeypatch, own, *args)
    assert code == 0, said
    assert OTHER_EVAL not in said, said
    assert f"{path.name} has LLM-as-a-judge grades" in said, said  # read, as it is


def test_a_project_with_no_session_is_still_named_for_the_tools_results(
        tmp_path, capsys, monkeypatch, services):
    bot = services / "insp-bot"
    bot.mkdir()
    write_answers(bot, 12, name="answers")
    inspect_project(bot, split(20, 20))
    assert _run(capsys, monkeypatch, bot, "--tool", "inspect")[0] == 0  # its judge.json
    code, said = _run(capsys, monkeypatch, services, "--tool", "inspect")
    assert code == 2, said
    assert "run `judgekeeper insp-bot --tool inspect" in said, said
    assert OTHER_EVAL not in said, said
    code, said = _run(capsys, monkeypatch, services, "insp-bot", "--tool", "inspect")
    assert code == 0, said  # the printed command works
    assert "insp-bot/logs/2026-10-02_support.json" in said, said


def test_a_session_on_the_tools_own_results_is_still_named_with_its_command(
        tmp_path, capsys, monkeypatch, services):
    bot = services / "pf-bot"
    bot.mkdir()
    promptfoo_project(bot, split(20, 20), name="evals/out.json", config=False, tag="pf")
    code, said = _run(capsys, monkeypatch, bot, "mark", "evals/out.json")
    assert code == 0, said  # a session on the promptfoo results themselves
    assert (bot / ".judgekeeper" / "start.json").is_file()
    code, said = _run(capsys, monkeypatch, services, "--tool", "promptfoo")
    assert code == 2, said
    assert "run `judgekeeper pf-bot --tool promptfoo" in said, said
    assert OTHER_EVAL not in said, said
    code, said = _run(capsys, monkeypatch, services, "pf-bot", "--tool", "promptfoo")
    assert OTHER_EVAL not in said, said  # the printed command reads its own results
    assert "Step 2 of 5: Mark" in said, said


def test_the_project_whose_session_reads_the_results_is_named_beside_one_that_does_not(
        tmp_path, capsys, monkeypatch, services):
    _pf_bot(capsys, monkeypatch, services)  # sorts before the other, but its file is another eval
    own = services / "pf-own"
    own.mkdir()
    promptfoo_project(own, split(20, 20), name="results.json", config=False, tag="own")
    code, said = _run(capsys, monkeypatch, own, "mark", "results.json")
    assert code == 0, said
    code, said = _run(capsys, monkeypatch, services, "--tool", "promptfoo")
    assert code == 2, said
    assert "run `judgekeeper pf-own --tool promptfoo" in said, said
    assert OTHER_EVAL not in said, said
