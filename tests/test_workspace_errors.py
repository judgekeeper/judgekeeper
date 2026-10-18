"""judgekeeper keeps its files in .judgekeeper/. When it can't write there (the folder
belongs to another user, or .judgekeeper is a file), the message names .judgekeeper/, never
a temporary file or a whole path, and says what to do there: there is no other location to
choose."""

from __future__ import annotations

import os
import sys

import pytest

from judgekeeper import textio
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


# A file another process has open (Windows) ------------------------------------------------

def _refusing(monkeypatch, times: int) -> list:
    """os.replace refuses `times` times, as Windows does while another process has the file
    open, then works; each try is kept."""
    real, tries = os.replace, []

    def replace(src, dst):
        tries.append(dst)
        if len(tries) <= times:
            raise PermissionError(13, "Access is denied", str(dst))
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(textio.time, "sleep", lambda s: None)
    return tries


def test_on_windows_a_file_in_use_is_replaced_after_a_short_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(textio, "is_windows", lambda: True)
    tries = _refusing(monkeypatch, 3)
    path = tmp_path / ".judgekeeper" / "server.json"
    path.parent.mkdir()
    path.write_text("old", encoding="utf-8")
    textio.write_replacing(path, "new")
    assert path.read_text(encoding="utf-8") == "new" and len(tries) == 4
    assert [p.name for p in path.parent.iterdir()] == ["server.json"]  # no temporary file left


def test_on_windows_a_file_still_in_use_is_said_so_not_permission_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(textio, "is_windows", lambda: True)
    tries = _refusing(monkeypatch, 10**6)
    path = tmp_path / ".judgekeeper" / "server.json"
    path.parent.mkdir()
    path.write_text("old", encoding="utf-8")
    with pytest.raises(textio.FileBusyError) as e:
        textio.write_replacing(path, "new")
    assert len(tries) == textio.REPLACE_TRIES  # a short, bounded wait
    assert not isinstance(e.value, PermissionError)
    error, then = textio.workspace_problem(e.value)
    assert error == ("Another program had a file in .judgekeeper/ open, so judgekeeper could "
                     "not save it.")
    assert "permission" not in (error + then).lower()
    assert "permission" not in textio.describe_os_error(e.value).lower()
    assert [p.name for p in path.parent.iterdir()] == ["server.json"]


def test_a_file_that_really_cant_be_written_still_says_permission_denied(tmp_path, monkeypatch):
    """A read-only file is no file in use: no wait, and the message stays."""
    monkeypatch.setattr(textio, "is_windows", lambda: True)
    tries = _refusing(monkeypatch, 10**6)
    path = tmp_path / ".judgekeeper" / "server.json"
    path.parent.mkdir()
    path.write_text("old", encoding="utf-8")
    monkeypatch.setattr(textio.os, "access", lambda p, mode: False)
    with pytest.raises(PermissionError) as e:
        textio.write_replacing(path, "new")
    assert len(tries) == 1
    assert textio.workspace_problem(e.value)[0] == textio.WORKSPACE_DENIED


def test_off_windows_a_refused_replace_is_not_tried_again(tmp_path, monkeypatch):
    monkeypatch.setattr(textio, "is_windows", lambda: False)
    tries = _refusing(monkeypatch, 1)
    with pytest.raises(PermissionError):
        textio.write_replacing(tmp_path / "server.json", "new")
    assert len(tries) == 1


def test_each_process_writes_its_own_temporary_file(tmp_path, monkeypatch):
    prefixes, real = [], textio.tempfile.mkstemp

    def mkstemp(*args, **kwargs):
        prefixes.append(kwargs["prefix"])
        return real(*args, **kwargs)

    monkeypatch.setattr(textio.tempfile, "mkstemp", mkstemp)
    textio.write_replacing(tmp_path / "server.json", "new")
    assert prefixes == [f".server.json.{os.getpid()}."]
