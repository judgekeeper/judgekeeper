"""A results file in the same folder as one the session above reads belongs to that session:
from that folder every command uses the marks above, as it does from the project folder,
and never starts a second .judgekeeper/ there. Results in a folder of their own still get
their own marks."""

from __future__ import annotations

import pytest

from judgekeeper.start_label import Workspace
from tests import test_project_folder
from tests.start_projects import split, table_project
from tests.test_front import flat, run
from tests.test_project_folder import _mark, _marker

here = test_project_folder.here  # the fixture: a project folder

PAGE = ("--no-browser", "--port", "0")


def _store(root, capsys, marker) -> bytes:
    """A session in `root` on sub2/results.csv with 5 marks, and new results of the same
    answers beside it, sub2/results-v2.csv."""
    _marker(root, marker)
    table_project(root, split(20, 16), name="sub2/results.csv", tag="sub2")
    assert run(capsys, "sub2/results.csv", *PAGE)[0] == 0
    _mark(Workspace(root), only=range(5))
    run(capsys, "--stop")
    table_project(root, split(20, 16), name="sub2/results-v2.csv", tag="sub2")
    return (root / ".judgekeeper" / "marks.jsonl").read_bytes()


def _said(capsys, *argv) -> tuple[int, str]:
    code, out, err = run(capsys, *argv, *PAGE)
    run(capsys, "--stop")
    return code, flat(out + err)


@pytest.mark.parametrize("marker", [".git", "pyproject.toml", None])
@pytest.mark.parametrize("command", [["mark", "results-v2.csv"], ["results-v2.csv"], []])
def test_from_the_folder_of_the_results_every_command_uses_the_marks_above(
        here, capsys, monkeypatch, marker, command):
    before = _store(here, capsys, marker)
    monkeypatch.chdir(here / "sub2")
    code, said = _said(capsys, *command)
    assert code == 0, said
    assert "get their own marks" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists(), said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


@pytest.mark.parametrize("command", [["mark", "results-v2.csv"], ["results-v2.csv"]])
def test_from_the_folder_of_the_results_it_says_what_the_project_folder_says(
        here, capsys, monkeypatch, command):
    _store(here, capsys, ".git")
    monkeypatch.chdir(here)
    there = _said(capsys, command[0], f"sub2/{command[-1]}") if len(command) == 2 \
        else _said(capsys, f"sub2/{command[-1]}")
    monkeypatch.chdir(here / "sub2")
    beside = _said(capsys, *command)
    assert beside[0] == there[0], (beside, there)
    assert ("You marked 5 answers" in beside[1]) == ("You marked 5 answers" in there[1]), (
        beside, there)


def test_from_the_project_folder_nothing_changes(here, capsys, monkeypatch):
    before = _store(here, capsys, ".git")
    monkeypatch.chdir(here)
    code, said = _said(capsys, "sub2/results-v2.csv")
    assert code == 0 and "get their own marks" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


def test_results_in_a_folder_of_their_own_still_get_their_own_marks(here, capsys,
                                                                   monkeypatch):
    before = _store(here, capsys, ".git")
    table_project(here / "evals3", split(20, 16), tag="evals3")
    monkeypatch.chdir(here / "evals3")
    code, said = _said(capsys)
    assert code == 0, said
    assert ("These results get their own marks here. The marks in ../ are for "
            "sub2/results.csv.") in said, said
    assert (here / "evals3" / ".judgekeeper" / "start.json").is_file()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
