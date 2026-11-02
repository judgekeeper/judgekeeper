"""A found file is named in every Find line as the File: line names it: from the project folder
when the run is there, else from here; never through a top folder, `~/...` in the home
folder."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tests.test_project_folder_commands import USER, home
from tests.test_top_folder import _run, _written, top

__all__ = ["home", "top"]  # the fixtures, used by name
pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="home is %USERPROFILE% there, and ~ is a shell's word")


def test_a_found_file_is_named_as_the_file_line_names_it(top, home, monkeypatch, capsys):
    """The project folder given from the top folder: "looks like", the question to save the
    map and the File: line all say `~/...`, never `Users/<name>/...` nor a path from the
    project folder."""
    monkeypatch.chdir(top)
    code, out = _run(capsys, Path("Users") / USER / "jk-try", "--no-browser", "--port", "0")
    assert code == 3, out
    shown = "~/jk-try/anchors.jsonl"
    assert f"{shown} looks like your LLM-as-a-judge's results" in out, out
    assert f"File: {shown}" in out, out
    assert f"Save how to read {shown} in judgekeeper.toml?" in out, out
    said = re.sub(r"`[^`]*`", "", out)  # a command repeats the folder as it was typed
    assert USER not in said, said
    assert _written(top) == []


def test_a_folder_given_from_a_top_folder_is_repeated_from_home(top, home, monkeypatch,
                                                                 capsys):
    """`judgekeeper Users/<name>/jk-try` from the top folder: each printed command repeats the
    folder as `~/jk-try`, never through the top folder; pasted in the shell, it is the same
    folder."""
    import shlex
    import subprocess

    monkeypatch.setenv("HOME", str(home))  # the shell's ~
    monkeypatch.chdir(top)
    code, out = _run(capsys, Path("Users") / USER / "jk-try", "--no-browser", "--port", "0")
    assert code == 3, out
    commands = re.findall(r"`([^`]*)`", out)
    assert commands and USER not in out, out
    for command in commands:
        word = shlex.split(command)[1]
        assert word == "~/jk-try", command
        shell = subprocess.run(["sh", "-c", f"printf '%s' {word}"], capture_output=True,
                               text=True, check=True, cwd=top).stdout
        assert shell == str(home / "jk-try")
