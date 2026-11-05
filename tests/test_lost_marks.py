"""marks.jsonl damaged from outside. Deleted: no marks, and the page opens. Cut or emptied with a
result saved: said, with how many the result had and how many can be read; the run goes on and
the marks stay as they are. A page that never answers is not called a busy port."""

from __future__ import annotations

import subprocess

import pytest

from judgekeeper import background, marks, page, start_label
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import split, table_project
from tests.test_front import flat, run
from tests.test_project_folder import _mark

PAGE = ("--no-browser", "--port", "0")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    return tmp_path


def _started(root, capsys) -> Workspace:
    table_project(root, split(20, 20))
    assert run(capsys, *PAGE)[0] == 0
    run(capsys, "--stop")
    return Workspace(root)


def _with_a_result(root, capsys) -> Workspace:
    ws = _started(root, capsys)
    _mark(ws)
    assert run(capsys, *PAGE)[0] == 0
    run(capsys, "--stop")
    assert ws.result_json.is_file()
    return ws


def _said(capsys, *argv) -> tuple[int, str]:
    code, out, err = run(capsys, *argv, *PAGE)
    run(capsys, "--stop")
    return code, flat(out + err)


def _keep_lines(ws: Workspace, n: int) -> None:
    lines = ws.marks.read_text(encoding="utf-8").splitlines(keepends=True)
    ws.marks.write_text("".join(lines[:n]), encoding="utf-8")


# A deleted marks.jsonl ---------------------------------------------------------------------

def test_a_session_with_no_marks_file_is_a_session_with_no_marks(here, capsys):
    ws = _started(here, capsys)
    ws.marks.unlink()
    session = StartSession(ws)
    assert session.page_marked == set() and session._due() is None
    assert session.current_status()


@pytest.mark.real_page
@pytest.mark.parametrize("command", [[], ["mark"]])
def test_the_page_opens_with_marks_jsonl_deleted(here, capsys, command):
    ws = _started(here, capsys)
    ws.marks.unlink()
    code, said = _said(capsys, *command)
    assert code == 0, said
    assert "is in use" not in said and "http://127.0.0.1" in said, said


def test_a_mark_after_marks_jsonl_was_deleted_is_kept(here, capsys):
    ws = _started(here, capsys)
    ws.marks.unlink()
    session = StartSession(ws)
    session.update({"id": session.items[0]["id"], "label": "pass", "seconds": 4})
    assert len(marks.read(ws.marks).counted()) == 1


# A page that never answers -----------------------------------------------------------------

class _Stuck:
    """A page process that runs on and never answers."""

    def __init__(self):
        self.stdin = self
        self.killed = self.waited = False

    def write(self, data):
        pass

    def close(self):
        pass

    def poll(self):
        return None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = self.killed
        return -9


@pytest.mark.real_page
def test_a_page_given_up_on_has_let_go_of_its_port_when_start_returns(tmp_path, monkeypatch):
    stuck = _Stuck()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: stuck)
    assert background.start(tmp_path, {}, "t" * 32, timeout=0) is None
    assert stuck.killed and stuck.waited


def test_a_page_that_does_not_start_is_not_a_busy_port(here, capsys, monkeypatch):
    _started(here, capsys)
    monkeypatch.setattr(background, "start", lambda *a, **k: None)
    code, said = _said(capsys)
    assert code == 3, said
    assert "is in use" not in said, said
    assert ("The marking page could not start in the background (what went wrong is in "
            ".judgekeeper/page.log).") in said, said


def test_a_port_that_is_really_taken_is_still_said(here, capsys, monkeypatch):
    _started(here, capsys)
    monkeypatch.setattr(background, "start", lambda *a, **k: None)
    monkeypatch.setattr(page, "port_free", lambda port: False)
    code, out, err = run(capsys, "--no-browser", "--port", "8901")
    assert code == 3 and "Port 8901 is in use" in flat(out + err), out + err


# Lost marks --------------------------------------------------------------------------------

def test_marks_cut_short_are_said_with_both_counts(here, capsys):
    ws = _with_a_result(here, capsys)
    _keep_lines(ws, 21)  # the header and 20 marks
    before = ws.marks.read_bytes()
    code, said = _said(capsys)
    assert code == 0, said
    assert ("Your last result had 40 marks, but only 20 can be read now. The rest are gone from "
            ".judgekeeper/marks.jsonl.") in said, said
    assert ws.marks.read_bytes().startswith(before)


@pytest.mark.parametrize("how", ["emptied", "deleted"])
def test_marks_all_gone_are_said(here, capsys, how):
    ws = _with_a_result(here, capsys)
    if how == "emptied":
        ws.marks.write_text("", encoding="utf-8")
    else:
        ws.marks.unlink()
    code, said = _said(capsys)
    assert code == 0, said
    assert ("Your last result had 40 marks, but none can be read now. They are gone from "
            ".judgekeeper/marks.jsonl.") in said, said


def test_a_mark_taken_back_is_no_lost_mark(here, capsys):
    """Fewer marks than the result, each answer still in the file: the person's own change."""
    ws = _with_a_result(here, capsys)
    session = StartSession(ws)
    session.update({"id": session.items[0]["id"], "deferred": True, "seconds": 4})
    _, said = _said(capsys)
    assert "Your last result had" not in said, said


def test_nothing_is_said_when_every_mark_is_there(here, capsys):
    _with_a_result(here, capsys)
    _, said = _said(capsys)
    assert "Your last result had" not in said, said


def test_a_result_it_cannot_read_says_nothing_about_lost_marks(here, capsys):
    ws = _with_a_result(here, capsys)
    ws.result_json.write_text("{}", encoding="utf-8")
    assert start_label.lost_marks_line(ws) is None
    ws.result_json.write_text("not json", encoding="utf-8")
    assert start_label.lost_marks_line(ws) is None
