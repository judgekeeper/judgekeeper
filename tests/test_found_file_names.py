"""A found file is named in every Find line as the File: line names it: from the project folder
when the run is there, else from here; never through a top folder, `~/...` in the home
folder."""

from __future__ import annotations

import re
from pathlib import Path

from tests.test_project_folder_commands import USER, home
from tests.test_top_folder import _run, _written, top

__all__ = ["home", "top"]  # the fixtures, used by name


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
