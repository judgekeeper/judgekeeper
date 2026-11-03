"""When plain `judgekeeper` reads another results file than the last run did (a newer one
saved in the folder), one line names it."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import split, table_project
from tests.test_project_folder_commands import USER, home

__all__ = ["home"]  # the fixture, used by name

NEWEST = "Reading new-rule.csv, the newest results here."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(capsys, *given: str) -> str:
    main(["--no-browser", "--port", "0", *given])
    main(["--stop", *given])
    return " ".join(capsys.readouterr().out.split())


def _newer(path):
    st = path.stat()
    os.utime(path, (st.st_atime + 60, st.st_mtime + 60))


@pytest.mark.parametrize("marked", [0, 10])
def test_a_newer_results_file_is_named(here, capsys, marked):
    table_project(here, split(40, 40))
    first = _run(capsys)
    assert "Reading" not in first
    session = StartSession(Workspace(here))
    changed = False  # answers 30 to 39 get another grade in new-rule.csv
    for item in session.items[:marked]:
        session.update({"id": item["id"], "label": session.groups[item["id"]], "seconds": 4})
        changed |= 30 <= int(re.search(r"Question (\d+)", str(session.raw[item["id"]]["input"]))[1]) < 40
    _newer(table_project(here, split(30, 50), name="new-rule.csv"))
    said = _run(capsys)  # with other grades on marked answers, the line that says whose
    assert (NEWEST if not changed else "Your answers were graded again in new-rule.csv,") in said


def test_the_same_file_again_is_not_named(here, capsys):
    table_project(here, split(40, 40))
    _run(capsys)
    assert "Reading" not in _run(capsys)



def test_the_newer_file_is_named_from_home_never_by_the_user_name(home, monkeypatch, capsys):
    """Run from the folder above the home folder, with the project given by its path: the
    line names the file as `~/...`, as Find's lines do, never through the user's name."""
    project = home / "jk-try"
    project.mkdir()
    table_project(project, split(40, 40))
    monkeypatch.chdir(home.parent)
    given = str(Path(USER) / "jk-try")
    _run(capsys, given)
    _newer(table_project(project, split(30, 50), name="new-rule.csv"))
    out = _run(capsys, given)
    shown = ("%USERPROFILE%\\jk-try\\new-rule.csv" if sys.platform == "win32"
             else "~/jk-try/new-rule.csv")  # the home folder as each names it
    assert f"Reading {shown}, the newest results here." in out, out
    assert USER not in re.sub(r"`[^`]*`", "", out), out
