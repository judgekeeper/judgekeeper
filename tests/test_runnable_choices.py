"""A choice between names (an LLM-as-a-judge, an eval tool, an MLflow experiment) with no
terminal ends in a Next: line whose commands run as printed: one per name, the name quoted,
at most five, then "and N more"."""

from __future__ import annotations

import re
import shlex

import pytest

from judgekeeper import front, start
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, records_project, split
from tests.test_front import assert_one_next_at_the_end


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def judges(here, *names):
    for pid, name in enumerate(names, 4101):
        records_project(here, split(16, 16), name=name, pid=pid)


def commands(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def test_two_judges_give_one_runnable_command_each(here, capsys):
    judges(here, "helpfulness", "safety")
    code, out, _ = run(capsys)
    assert code == 3
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which LLM-as-a-judge to check ('helpfulness', 'safety'), then run "
        "`judgekeeper --metric helpfulness` or `judgekeeper --metric safety`.")


def test_each_printed_command_runs_as_printed(here, capsys):
    judges(here, "helpfulness", "safety")
    _, out, _ = run(capsys)
    for command in commands(assert_one_next_at_the_end(out)):
        code, got, _ = run(capsys, *shlex.split(command)[1:])
        assert code == 0, (command, got)


def test_seven_judges_name_five_commands_then_how_many_more(here, capsys):
    judges(here, *(f"judge-{i}" for i in range(7)))
    _, out, _ = run(capsys)
    line = assert_one_next_at_the_end(out)
    assert commands(line) == [f"judgekeeper --metric judge-{i}" for i in range(5)]
    assert line.startswith("Next: choose which LLM-as-a-judge to check ('judge-0', 'judge-1'")
    assert "'judge-6')" in line  # every name is still said
    assert line.endswith("`judgekeeper --metric judge-4` and 2 more.")
    assert "NAME" not in line


def test_a_name_that_starts_with_a_dash_or_has_spaces_is_quoted(here, capsys):
    judges(here, "-odd", "two words")
    _, out, _ = run(capsys)
    got = commands(assert_one_next_at_the_end(out))
    assert got == ["judgekeeper --metric=-odd", "judgekeeper --metric 'two words'"] or got == [
        "judgekeeper --metric=-odd", 'judgekeeper --metric "two words"']
    for command in got:
        assert run(capsys, *shlex.split(command)[1:])[0] == 0


def test_two_eval_tools_give_one_runnable_command_each(here, capsys):
    promptfoo_project(here, split(20, 16))
    records_project(here, split(16, 16))
    _, out, _ = run(capsys)
    line = assert_one_next_at_the_end(out)
    assert commands(line) == ["judgekeeper --tool records", "judgekeeper --tool promptfoo"]
    assert "NAME" not in line


def test_experiments_give_one_runnable_command_each(capsys):
    talk = front.FrontTalk(False, ".", {})
    with pytest.raises(start.Stop):
        talk.choose("These results hold more than one experiment:", ["a", "b c"], "",
                    flag="--experiment", values=["a", "b c"], what="which experiment to read")
    out = capsys.readouterr().out
    assert commands(out) == ["judgekeeper --experiment a", "judgekeeper --experiment 'b c'"] or (
        commands(out) == ["judgekeeper --experiment a", 'judgekeeper --experiment "b c"'])


def test_all_is_always_one_of_the_commands_shown(capsys):
    talk = front.FrontTalk(False, ".", {})
    names = [f"j{i}" for i in range(9)]
    with pytest.raises(start.Stop):
        talk.choose("Which?", [*names, "All"], "", flag="--metric", values=[*names, "all"],
                    what="which LLM-as-a-judge to check", keep=1)
    out = " ".join(capsys.readouterr().out.split())
    assert commands(out) == [f"judgekeeper --metric j{i}" for i in range(4)] + [
        "judgekeeper --metric all"]
    assert "`judgekeeper --metric j3` and 5 more, or `judgekeeper --metric all`." in out
