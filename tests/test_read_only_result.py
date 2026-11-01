"""A result page while .judgekeeper/ can't be written. The page shows the result from the marks
(nothing is saved, and no disagreement is listed: the hidden marks can't be set aside). A file
that can't be written is named by its own name, never the temporary file it was written
through, and the line has one full stop where its parts meet."""

from __future__ import annotations

import os
import sys

import pytest

from judgekeeper import textio

posix = pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                           reason="file permissions: POSIX, not as root")


@posix
def test_a_file_in_a_folder_that_cant_be_written_is_named_itself(tmp_path):
    folder = tmp_path / ".judgekeeper"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError) as e:
            textio.write_replacing(folder / "anchors.jsonl", "x")
    finally:
        folder.chmod(0o755)
    assert e.value.filename == str(folder / "anchors.jsonl")
    said = textio.describe_os_error(e.value)
    assert ".tmp" not in said and "anchors.jsonl" in said


def test_a_refused_rename_names_the_file_not_the_temporary_one(tmp_path, monkeypatch):
    path = tmp_path / "result.json"

    def refuse(src, dst):
        raise PermissionError(13, "Permission denied", src, dst)

    monkeypatch.setattr(textio, "is_windows", lambda: False)
    monkeypatch.setattr(textio.os, "replace", refuse)
    with pytest.raises(PermissionError) as e:
        textio.write_replacing(path, "x")
    assert e.value.filename == str(path) and e.value.filename2 is None
    assert ".tmp" not in textio.describe_os_error(e.value)
    assert list(tmp_path.iterdir()) == []  # no temporary file left
