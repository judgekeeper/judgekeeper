"""Run from far above a project, a line names the home folder as `~/`, never by the user's
name; a project in another person's home folder is said plainly to be there, with no command
that can't run as printed (a cut name to go to, or PATH)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from judgekeeper import textio
from judgekeeper.start_label import Workspace
from tests.start_projects import split, table_project
from tests.test_project_folder import _mark
from tests.test_project_folder_commands import USER, _run, _started, home

__all__ = ["home"]  # the fixture, used by name

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="a venv's scripts are .exe files there")
PAGE = ("--no-browser", "--port", "0")
OTHERS = "in another person's home folder, which judgekeeper doesn't name in full"


def _session(proj: Path, monkeypatch, capsys) -> None:
    """A project with 8 marks on results.csv, and new results v2.csv beside them."""
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".git").mkdir(exist_ok=True)
    monkeypatch.chdir(proj)
    table_project(proj, split(20, 16), tag=proj.name)
    assert _run(capsys, *PAGE)[0] == 0
    _mark(Workspace(proj), only=range(8))
    _run(capsys, "--stop")
    table_project(proj, split(20, 16), name="v2.csv", tag=proj.name)


@pytest.mark.parametrize("at", ["homes", "top", "root"])
def test_the_home_folder_from_far_above_is_named_by_tilde(home, monkeypatch, at):
    where = {"homes": home.parent, "top": home.parent.parent, "root": Path("/")}[at]
    monkeypatch.chdir(where)
    assert textio.folder_from_here(home) == "~"
    assert textio.folder_of("~", where) == home
    assert textio.cd_word("~") == "~"


@pytest.mark.parametrize("at", ["homes", "top"])
def test_a_project_in_the_home_folder_from_far_above_is_in_tilde(home, monkeypatch, capsys, at):
    _session(home, monkeypatch, capsys)
    where = {"homes": home.parent, "top": home.parent.parent}[at]
    monkeypatch.chdir(where)
    _started(monkeypatch, home)
    for argv in ([os.path.relpath(home / "v2.csv"), *PAGE],
                 ["check", os.path.relpath(home / "v2.csv")]):
        code, out = _run(capsys, *argv)
        _run(capsys, "--stop")
        assert code == 3, out
        assert "These results belong to the project in ~/. To check them, run " in out, out
        assert "/…/" not in out and USER not in out, out


def test_a_project_in_another_persons_home_folder_is_said_plainly(home, monkeypatch, capsys):
    bob = home.parent / "bob" / "work" / "proj two"
    _session(bob, monkeypatch, capsys)
    monkeypatch.chdir(home.parent)
    _started(monkeypatch, home)
    for argv in (["bob/work/proj two/v2.csv", *PAGE], ["check", "bob/work/proj two/v2.csv"]):
        code, out = _run(capsys, *argv)
        _run(capsys, "--stop")
        assert code == 3, out
        assert f"These results belong to the project in /…/proj two/, {OTHERS}." in out, out
        assert "in that folder." in out and "` in /…/" not in out and "cd " not in out, out


@pytest.mark.parametrize("command", ["check", "fix"])
def test_marking_more_in_a_folder_it_cant_name_gives_no_path_to_type(home, monkeypatch, capsys,
                                                                     command):
    bob = home.parent / "bob" / "work" / "proj two"
    _session(bob, monkeypatch, capsys)
    monkeypatch.chdir(home.parent)
    _started(monkeypatch, home)
    code, out = _run(capsys, command, "bob/work/proj two")
    assert code == 3, out
    assert " PATH" not in out, out
    assert "Next: go to your project folder, then run `" in out, out
    assert out.endswith(" mark` there to mark more answers."), out
