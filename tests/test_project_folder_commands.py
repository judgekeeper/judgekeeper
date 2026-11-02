"""A line that says to run a command in your project folder names every path in it from the
project folder, the program typed as a path included; a line that doesn't know the project
folder names a program that runs from any folder."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest

from judgekeeper import fix, page
from judgekeeper.cli import main

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="a venv's scripts are .exe files there")
USER = "ann-x"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder at tmp/Users/ann-x, with judgekeeper in a venv of its own under it,
    started as a path from where the command runs, and no `judgekeeper` on the PATH."""
    folder = Path(os.path.realpath(tmp_path)) / "Users" / USER
    tool = folder / "Desktop" / "Tools" / "train" / ".venv" / "bin" / "judgekeeper"
    tool.parent.mkdir(parents=True)
    tool.write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    return folder


def _started(monkeypatch, home: Path) -> Path:
    """judgekeeper started as its path from here; that program's whole path."""
    tool = home / "Desktop" / "Tools" / "train" / ".venv" / "bin" / "judgekeeper"
    monkeypatch.setattr(sys, "argv", [os.path.relpath(tool, os.getcwd())])
    return tool


def _program_in(line: str, folder: Path, home: Path) -> Path:
    """The program a command names, as the shell finds it in `folder`."""
    typed = shlex.split(line)[0]
    if typed.startswith("~/"):
        return home / typed[2:]
    return (folder / typed).resolve()


def _run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


def _commands(text: str) -> list[str]:
    return text.split("`")[1::2]


def test_fix_from_the_folder_above_names_the_program_from_the_project(home, monkeypatch,
                                                                      capsys):
    """The table: "then in your project folder, run `<program> fix <new results file>`",
    filled in and run from the project."""
    from tests.test_regrade_files import project, regraded
    from tests.test_regrade_files import write as write_rows

    proj = home / "Desktop" / "Testing Judge" / "team" / "proj"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    ws = project(proj)
    write_rows(proj, "new.csv", regraded(ws))
    capsys.readouterr()
    monkeypatch.chdir(proj.parent)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, "fix", proj)
    nxt = out[out.rindex("Next: "):]
    assert "in your project folder, run `" in nxt, nxt
    (line,) = [c for c in _commands(nxt) if fix.NEW_RESULTS in c]
    assert _program_in(line, proj, home) == tool, line
    assert USER not in nxt
    argv = shlex.split(line.replace(fix.NEW_RESULTS, "new.csv"))[1:]
    monkeypatch.chdir(proj)  # where the line says it runs
    code, out = _run(capsys, *argv)
    assert code == 0 and "new.csv" in out, out


def test_fix_from_the_folder_above_names_the_steps_program_from_the_project(home, monkeypatch,
                                                                            capsys):
    """promptfoo's three steps: "3. Then, in your project folder: `<program> fix ...`"."""
    from tests.test_fix import project

    proj = home / "Desktop" / "Testing Judge" / "team" / "support-bot"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    project(proj)
    monkeypatch.chdir(proj.parent)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, "fix", proj)
    assert code == 0, out
    step = out[out.index("3. Then, in your project folder: "):]
    line = _commands(step)[0]
    assert line.endswith(" fix .judgekeeper/fix/new.json"), line
    assert _program_in(line, proj, home) == tool, line


def test_fix_from_the_project_still_names_the_program_as_typed(home, monkeypatch, capsys):
    from tests.test_regrade_files import project

    proj = home / "Desktop" / "Testing Judge" / "team" / "proj"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    project(proj)
    capsys.readouterr()
    _started(monkeypatch, home)
    code, out = _run(capsys, "fix")
    nxt = out[out.rindex("Next: "):]
    assert code == 0 and "in your project folder" not in nxt, out
    assert f"run `../../../Tools/train/.venv/bin/judgekeeper fix {fix.NEW_RESULTS}`" in nxt, nxt


@pytest.mark.parametrize("argv", [("check", "missing.csv"), ("check", "inner"),
                                  ("fix", "inner")])
def test_a_line_that_cant_name_the_project_names_a_program_that_runs_anywhere(home, monkeypatch,
                                                                             capsys, argv):
    """"run `<program> check` in your project folder", "give `<program> ...` your new results
    file, or run it in your project folder": the project folder isn't known, so the program
    runs from any folder (here `~/...`)."""
    from tests.test_regrade_files import project

    proj = home / "Desktop" / "Testing Judge" / "team" / "proj"
    (proj / "inner").mkdir(parents=True)
    monkeypatch.chdir(proj)
    project(proj)
    capsys.readouterr()
    monkeypatch.chdir(proj if argv[1] == "inner" else proj.parent)
    _started(monkeypatch, home)
    code, out = _run(capsys, *argv)
    nxt = out[out.rindex("Next: "):]
    assert code != 0 and "project folder" in nxt, out
    assert _commands(nxt)[0].startswith("~/Desktop/Tools/train/.venv/bin/judgekeeper "), nxt
    assert USER not in nxt


def test_the_marking_page_names_the_program_from_the_project(home, monkeypatch, capsys):
    """The page says to run it in your project folder (a mark it can't save, and once a
    result is ready): the program it is given is named from there."""
    from judgekeeper.start_label import Workspace
    from tests.test_regrade_files import project

    proj = home / "Desktop" / "Testing Judge" / "team" / "proj"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    project(proj)
    monkeypatch.chdir(proj.parent)
    tool = _started(monkeypatch, home)
    sent = {}
    monkeypatch.setattr(page.background, "start",
                        lambda folder, settings, token: sent.update(settings))
    assert page.open_new(Workspace(proj), 0, {}) is None  # none started: what it is given
    assert _program_in(sent["program"], proj, home) == tool, sent["program"]
    assert page.DONE.endswith("in your project folder.")
