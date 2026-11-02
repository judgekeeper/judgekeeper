"""`judgekeeper` run in a top folder (`/`, a drive, /private) or a folder above the home folder:
no search below, which would walk into home folders; it says to go to the project folder,
exits 3 and writes nothing. `--stop` still works there, and home and project folders are
searched as before."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from judgekeeper import textio
from judgekeeper.cli import main
from tests.start_projects import flat_jsonl
from tests.test_project_folder_commands import USER, home

__all__ = ["home"]  # the fixture, used by name

GO_TO = ("judgekeeper reads eval results in your project folder. Go to it (`cd <your project "
         "folder>`), then run `judgekeeper` there.")


def _run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


@pytest.fixture
def top(home, monkeypatch) -> Path:
    """The folder above a fake home's parent (tmp/, holding Users/ann-x), seen as a top
    folder, with an own-format results file in the home folder."""
    folder = home.parent.parent
    real = textio._is_top
    monkeypatch.setattr(textio, "_is_top", lambda f: f == str(folder) or real(f))
    monkeypatch.setattr("judgekeeper.start._interactive", lambda: False)
    flat_jsonl(home / "jk-try" / "anchors.jsonl")
    return folder


def _written(folder: Path) -> list[str]:
    """What judgekeeper writes anywhere below `folder`."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.name in (".judgekeeper", "judgekeeper.toml"))


@pytest.mark.parametrize("where", ["top", "above home"])
def test_from_a_top_folder_or_above_home_nothing_is_searched(top, home, monkeypatch, capsys,
                                                              where):
    monkeypatch.chdir(top if where == "top" else home.parent)
    code, out = _run(capsys, "--no-browser", "--port", "0")
    assert code == 3, out
    assert GO_TO in out, out
    assert "looks like" not in out and "anchors.jsonl" not in out and USER not in out, out
    assert _written(top) == []


def test_given_a_top_folder_nothing_is_searched(top, home, monkeypatch, capsys):
    monkeypatch.chdir(home)
    code, out = _run(capsys, str(top), "--no-browser", "--port", "0")
    assert code == 3 and GO_TO in out, out
    assert _written(top) == []


def test_stop_still_works_from_a_top_folder(top, monkeypatch, capsys):
    monkeypatch.chdir(top)
    code, out = _run(capsys, "--stop")
    assert code == 0, out
    assert "No marking page is open." in out and GO_TO not in out, out
    assert _written(top) == []


def test_from_home_the_search_goes_on(top, home, monkeypatch, capsys):
    monkeypatch.chdir(home)
    out = _run(capsys, "--no-browser", "--port", "0")[1]
    assert GO_TO not in out, out
    assert "jk-try/anchors.jsonl looks like your LLM-as-a-judge's results" in out, out
    assert USER not in out, out


@pytest.mark.skipif(sys.platform == "win32", reason="no /dev there")
def test_from_dev_it_says_there_are_no_results(monkeypatch, capsys):
    """/dev is neither a top folder nor above home: Find looks, and finds nothing."""
    if not Path("/dev").is_dir():
        pytest.skip("no /dev here")
    monkeypatch.chdir("/dev")
    code, out = _run(capsys, "--no-browser", "--port", "0")
    assert code == 3, out
    assert "No eval results found in this folder" in out and GO_TO not in out, out
    assert "Traceback" not in out


@pytest.mark.skipif(sys.platform != "win32", reason="a drive's top folder is Windows'")
def test_from_a_drive_top_nothing_is_searched(tmp_path, monkeypatch, capsys):
    """From the top of a real drive (C:\\): the go-to-project line, exit 3, nothing written."""
    drive = Path(tmp_path.anchor)
    monkeypatch.setattr("judgekeeper.start._interactive", lambda: False)
    made = (".judgekeeper", "judgekeeper.toml")
    before = [(drive / name).exists() for name in made]
    monkeypatch.chdir(drive)
    code, out = _run(capsys, "--no-browser", "--port", "0")
    assert code == 3 and GO_TO in out, out
    assert [(drive / name).exists() for name in made] == before
