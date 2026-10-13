"""`--stop` closes the page even when server.json is gone: the page records itself in a second
file in .judgekeeper/."""

from __future__ import annotations

import pytest

from judgekeeper import label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    return tmp_path


def _run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, _ = capsys.readouterr()
    return code, out


def test_stop_closes_the_page_when_server_json_is_gone(here, capsys, pages):
    code, out = _run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    (folder / label.LOCK).unlink()
    assert label.is_open(folder)  # found through the second record
    code, out = _run(capsys, "--stop")
    assert code == 0, out
    assert "Closed the marking page." in out
    assert not label.is_open(folder)
    assert not (folder / label.LOCK_COPY).exists()


def test_both_records_hold_the_stop_secret_never_the_token(here, capsys, pages):
    code, out = _run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    copy = (folder / label.LOCK_COPY).read_text(encoding="utf-8")
    assert copy == (folder / label.LOCK).read_text(encoding="utf-8")
    assert "token" not in copy

