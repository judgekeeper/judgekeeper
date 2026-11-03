"""Path lines as Windows shows them, on any machine: a path from here has `/` between folders
(a typed one too), a path in the home folder is `%USERPROFILE%\\...` as every line shows it."""

import os
import pathlib
import re
from pathlib import Path

import pytest

from judgekeeper import project, textio

SRC = Path(__file__).parents[1] / "src" / "judgekeeper"
HOME_FILE = "%USERPROFILE%\\Desktop\\proj\\results.csv"


@pytest.fixture
def windows(tmp_path, monkeypatch):
    """Windows' way with paths: is_windows, and as_posix turning `\\` into `/`. The home folder
    is tmp/Users/ann-x; the command runs in the folder above it. Its results file."""
    monkeypatch.setattr(textio, "is_windows", lambda: True)
    monkeypatch.setattr(pathlib.PosixPath, "as_posix",
                        lambda self: str(self).replace("\\", "/"), raising=False)
    home = Path(os.path.realpath(tmp_path)) / "Users" / "ann-x"
    (home / "Desktop" / "proj").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(home.parent)
    results = home / "Desktop" / "proj" / "results.csv"
    results.write_text("id,score\n", encoding="utf-8")
    return results


def test_a_file_line_names_the_home_folder_as_every_line(windows):
    assert textio.shown_in(windows, windows.parent) == HOME_FILE  # run from elsewhere
    assert textio.line_path(windows) == HOME_FILE


def test_a_typed_path_has_slashes_as_a_path_from_here(windows):
    assert textio.line_path("evals\\other.csv") == "evals/other.csv"


def test_the_other_eval_line_names_both_files_as_every_line(windows):
    line = project.other_eval_line(Path("evals\\other.csv"), windows)
    assert line.startswith(f"evals/other.csv shares no answers with the results you marked "
                           f"({HOME_FILE}),"), line


def test_no_line_turns_a_shown_path_into_slashes_itself():
    """A path from shown_from_here keeps the home folder's form: line_path names it."""
    turned = [f"{f.name}: {m[0]}" for f in sorted(SRC.rglob("*.py"))
              for m in re.finditer(r"shown_from_here\([^\n]*\)\)\.as_posix\(\)",
                                   f.read_text(encoding="utf-8"))]
    assert turned == []
