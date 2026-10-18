"""`--stop` closes the page even when server.json is gone: the page records itself in a second
file in .judgekeeper/. A page nobody can close any more stops by itself after 30 minutes
without a request."""

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


def test_both_records_are_the_same_and_gone_once_the_page_stops(here, capsys, pages):
    code, out = _run(capsys, "--no-browser")
    assert code == 0, out
    folder = here / ".judgekeeper"
    copy = (folder / label.LOCK_COPY).read_text(encoding="utf-8")
    assert copy == (folder / label.LOCK).read_text(encoding="utf-8")
    assert _run(capsys, "--stop")[0] == 0
    assert not (folder / label.LOCK).exists() and not (folder / label.LOCK_COPY).exists()


def test_an_idle_page_closes_after_30_minutes():
    assert label.IDLE_TIMEOUT == 30 * 60


# Ctrl-C --------------------------------------------------------------------------------------

def test_ctrl_c_before_the_link_is_printed_stops_the_page_too(here, capsys, pages, monkeypatch):
    from judgekeeper import page

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(page, "show", interrupted)
    code, out = _run(capsys, "--no-browser")
    assert code == 130
    assert "\nStopped.\n" in out and "token=" not in out
    assert not label.is_open(here / ".judgekeeper")  # no page left running


def test_ctrl_c_on_wait_says_stopped_and_exits_130(here, capsys, monkeypatch):
    real = label.LabelServer.serve

    def interrupted(self, *args, **kwargs):  # Ctrl-C while the page is served
        self.stop()
        real(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(label.LabelServer, "serve", interrupted)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)
    code, out = _run(capsys, "--wait")
    assert code == 130, out
    assert out.rstrip().splitlines()[-2:] == [
        "Stopped.", "Next: run `judgekeeper --wait` to carry on."]
    assert not label.is_open(here / ".judgekeeper")
