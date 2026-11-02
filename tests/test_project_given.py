"""A project folder given as the path is the project, from any folder: its own results file
(given in full when marking started) is read from there, nothing new is made where the
command runs, and its lines name no user folder. A folder below that can't be told apart
(/dev/fd/3 from /) is skipped."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from judgekeeper import background, find
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.test_regrade_files import COLUMNS, _row, _write, closed

PAGE = ("--no-browser", "--port", "0", "--yes")
USER = "ann-x"  # the user name in the home folder's path: no line may hold it


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder at tmp/Users/ann-x."""
    folder = Path(os.path.realpath(tmp_path)) / "Users" / USER
    (folder / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    return folder


@pytest.fixture
def given(home, monkeypatch):
    """A project whose results file was given in full when marking started (from outside
    the project), with 10 answers marked."""
    proj, ext = home / "Desktop" / "proj", home / "ext"
    proj.mkdir()
    ext.mkdir()
    _write(ext / "results.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(proj)
    assert main([str(ext / "results.csv"), *PAGE]) == 0
    ws = Workspace(proj)
    background.stop(ws.dir)
    closed(ws)
    session = StartSession(ws)
    for item in session.items[:10]:
        session.update({"id": item["id"], "label": "pass", "seconds": 5})
    assert json.loads(ws.start.read_text(encoding="utf-8"))["given"] == "../../ext/results.csv"
    yield proj
    background.stop(ws.dir)


def _run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def test_a_project_given_from_another_folder_is_the_project(given, home, tmp_path_factory,
                                                             monkeypatch, capsys):
    other = Path(os.path.realpath(tmp_path_factory.mktemp("elsewhere")))
    capsys.readouterr()
    for cwd in (Path(given.anchor), home / "Desktop", other):
        monkeypatch.chdir(cwd)
        before = sorted(os.listdir(cwd))
        code, out = _run(capsys, given, *PAGE)
        background.stop(given / ".judgekeeper")
        assert code == 0, (cwd, out)
        assert sorted(os.listdir(cwd)) == before, (cwd, out)  # nothing new where it ran
        assert "You marked 10 answers so far" in " ".join(out.split()), (cwd, out)
        assert USER not in out, (cwd, out)


def test_the_file_line_for_a_project_given_from_the_top_folder_names_no_user(
        home, monkeypatch, capsys):
    """The first run, from `/`, of a project holding its results: File: is named as
    shown_folder names a folder (`~/...`), never Users/<name>/..."""
    from judgekeeper import textio

    proj = home / "Desktop" / "proj"
    proj.mkdir()
    _write(proj / "results.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(Path(proj.anchor))
    code, out = _run(capsys, proj, *PAGE)
    background.stop(proj / ".judgekeeper")
    assert code == 0, out
    file = next(line for line in out.splitlines() if line.startswith("File:"))
    assert file.split(None, 1)[1] == textio._home_shown("Desktop/proj/results.csv"), file
    assert USER not in out, out


def test_check_with_no_marks_from_the_top_folder_names_this_folder(home, monkeypatch, capsys):
    results = home / "ext" / "results.csv"
    results.parent.mkdir()
    _write(results, [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(Path(home.anchor))
    _, out = _run(capsys, "check", results)
    assert "No marks in this folder ()" not in out, out
    assert "No marks in this folder." in out, out


class _Unknown:
    """An entry the walk can't tell the kind of: /dev/fd/3 seen from / (Bad file
    descriptor)."""

    name = "3"

    def __init__(self, folder: str):
        self.path = os.path.join(folder, self.name)

    def _bad(self, *args, **kwargs):
        raise OSError(errno.EBADF, "Bad file descriptor", self.path)

    is_symlink = is_dir = is_file = stat = _bad


@pytest.mark.parametrize("below", [("dev", "fd"), ()])  # as from /, and in this folder
def test_a_folder_below_that_cant_be_told_apart_is_skipped(below, tmp_path, monkeypatch,
                                                           capsys):
    real, fd = os.scandir, Path(os.path.realpath(tmp_path), *below)
    fd.mkdir(parents=True, exist_ok=True)

    class _Os:
        def __getattr__(self, name):
            return getattr(os, name)

        @staticmethod
        def scandir(folder="."):
            entries = list(real(folder))
            return entries + [_Unknown(str(fd))] if Path(folder).resolve() == fd else entries

    monkeypatch.setattr(find, "os", _Os())
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys, "--stop")
    assert code == 0 and "No marking page is open." in out, out
    assert "cannot use" not in out
    code, out = _run(capsys, *PAGE)
    assert "cannot use" not in out and "error" not in out.lower(), out
