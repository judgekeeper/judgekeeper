"""A path judgekeeper names in a line is never split where the line wraps: one with spaces stays
whole on one line, even when the line runs long."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from judgekeeper import textio
from tests.test_project_folder_commands import home

__all__ = ["home"]  # the fixture, used by name


def test_a_path_with_spaces_is_never_split(tmp_path, monkeypatch):
    folder = Path(os.path.realpath(tmp_path)) / "Testing Judge Keeper" / "e2e r3" / "proj s3"
    folder.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    shown = textio.shown_from_here(folder / ".judgekeeper" / "fix" / "marked-answers.csv")
    assert " " in shown
    text = (f"Next: change your rule, grade the answers in {shown} again, save the results, "
            "then run `judgekeeper fix <new results file>`.")
    lines = textio.wrap(text)
    assert any(shown in line for line in lines), lines
    assert " ".join(" ".join(lines).split()) == " ".join(text.split())


def test_other_words_still_wrap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = "word " * 40
    assert all(len(line) <= textio.WIDTH for line in textio.wrap(text))


@pytest.mark.skipif(sys.platform == "win32", reason="a venv's scripts are .exe files there")
def test_fix_from_the_root_keeps_each_path_on_one_line(home, monkeypatch, capsys):
    from tests.test_regrade_files import project

    proj = home / "Desktop" / "Testing Judge Keeper" / "e2e-1.1-r3" / "proj s3"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    project(proj)
    capsys.readouterr()
    monkeypatch.chdir("/")
    from judgekeeper.cli import main

    code = main(["fix", str(proj)])
    out = capsys.readouterr().out
    assert code == 0, out
    folder = "~/Desktop/Testing Judge Keeper/e2e-1.1-r3/proj s3/.judgekeeper/fix/"
    named = [line for line in out.splitlines() if ".judgekeeper/fix/" in line
             and "`" not in line]
    assert any("marked-answers.csv" in line for line in named), out
    assert any("saved in" in line for line in out.splitlines()), out
    for line in named:
        assert folder in line, (line, out)
    for line in out.splitlines():  # no line ends part way into the folder's name
        assert not line.rstrip().endswith(("Testing", "Testing Judge", "proj")), (line, out)
