"""judgekeeper keeps its files in .judgekeeper/. When it can't write there (the folder
belongs to another user, or .judgekeeper is a file), the message names .judgekeeper/, never
a temporary file or a whole path, and says what to do there: there is no other location to
choose."""

from __future__ import annotations

import os
import sys

import pytest

from tests.start_projects import promptfoo_project, split
from tests.test_front import run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(30, 30))
    return tmp_path


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="file permissions: POSIX, not as root")
def test_a_judgekeeper_folder_that_cant_be_written(here, capsys):
    (here / ".judgekeeper").mkdir()
    (here / ".judgekeeper").chmod(0o555)
    try:
        code, out, err = run(capsys, "--no-browser")
    finally:
        (here / ".judgekeeper").chmod(0o755)
    text = _flat(out + err)
    assert ("judgekeeper can't write in .judgekeeper/ (permission denied): it keeps its files "
            "there.") in text
    assert ("Next: give your user permission to write in .judgekeeper/, then run "
            "`judgekeeper --no-browser`.") in text
    assert "remove" not in text  # the folder holds the marks
    assert ".tmp" not in text and str(here) not in text and "location" not in text
    assert code == 2


def test_a_judgekeeper_file_where_the_folder_goes(here, capsys):
    (here / ".judgekeeper").write_text("x\n", encoding="utf-8")
    code, out, err = run(capsys, "--no-browser")
    text = _flat(out + err)
    assert (".judgekeeper is a file, but judgekeeper keeps its files in a .judgekeeper/ "
            "folder there.") in text
    assert ("Next: move or rename the file .judgekeeper, then run "
            "`judgekeeper --no-browser`.") in text
    assert str(here) not in text and "location" not in text
    assert code == 2
