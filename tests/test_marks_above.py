"""Every command uses the nearest .judgekeeper/ that holds your marks: a run in the folder of
the results never starts a second, empty session, and one left by an earlier version is passed
over by every command. Nothing moves or deletes marks."""

from __future__ import annotations

import pytest

from judgekeeper import project, start, start_label
from judgekeeper.label import is_open
from judgekeeper.start_label import Workspace
from tests.start_projects import split, table_project
from tests.test_front import flat, run
from tests.test_project_folder import _mark, _marker

PAGE = ("--no-browser", "--port", "0")
MARKERS = [".git", "pyproject.toml", None]


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _marked_above(root, capsys, marker) -> bytes:
    """A session in `root` that found evals/results.csv by itself, with 5 marks."""
    _marker(root, marker)
    table_project(root, split(20, 16), name="evals/results.csv")
    assert run(capsys, *PAGE)[0] == 0
    _mark(Workspace(root), only=range(5))
    run(capsys, "--stop")
    return (root / ".judgekeeper" / "marks.jsonl").read_bytes()


def _empty_session_in(folder) -> None:
    """What a run in `folder` left before: a session of its own with no marks."""
    start_label.prepare(start.find_judge(folder), say=lambda line: None)
    project.forget()
    assert (folder / ".judgekeeper" / "start.json").is_file()


def _said(capsys, *argv) -> tuple[int, str]:
    page = () if argv[:1] in (("check",), ("fix",)) else PAGE
    code, out, err = run(capsys, *argv, *page)
    run(capsys, "--stop")
    return code, flat(out + err)


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("command", [[], ["mark"]])
def test_a_run_in_the_folder_of_the_results_uses_the_marks_above(here, capsys, monkeypatch, marker,
                                                                 command):
    before = _marked_above(here, capsys, marker)
    monkeypatch.chdir(here / "evals")
    code, said = _said(capsys, *command)
    assert code == 0, said
    assert "You marked 5 answers so far" in said, said
    assert "keeps its own marks" not in said, said
    assert not (here / "evals" / ".judgekeeper").exists(), said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("folder", ["evals", "."])
@pytest.mark.parametrize("command", [[], ["mark"], ["evals/results.csv"]])
def test_a_project_left_with_an_empty_session_finds_its_marks_again(here, capsys, monkeypatch,
                                                                    marker, folder, command):
    before = _marked_above(here, capsys, marker)
    _empty_session_in(here / "evals")
    empty = (here / "evals" / ".judgekeeper" / "start.json").read_bytes()
    monkeypatch.chdir(here / folder)
    argv = [a.removeprefix("evals/") if folder == "evals" else a for a in command]
    code, said = _said(capsys, *argv)
    assert code == 0, said
    assert "You marked 5 answers so far" in said, said
    assert "already holds your judgekeeper session" not in said, said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
    assert (here / "evals" / ".judgekeeper" / "start.json").read_bytes() == empty  # left as it is


@pytest.mark.parametrize("folder", ["evals", "."])
@pytest.mark.parametrize("command", ["fix", "check"])
def test_fix_and_check_reach_the_marks_past_an_empty_session(here, capsys, monkeypatch, folder,
                                                             command):
    _marked_above(here, capsys, ".git")
    _empty_session_in(here / "evals")
    monkeypatch.chdir(here / folder)
    _, said = _said(capsys, command)
    assert "already holds" not in said and "go to that folder" not in said, said
    assert "You've marked 0" not in said and "(0 marks)" not in said, said


def test_stop_closes_a_page_left_open_on_an_empty_session(here, capsys, monkeypatch):
    from judgekeeper import page

    _marked_above(here, capsys, ".git")
    _empty_session_in(here / "evals")
    ws = Workspace(here / "evals")
    opened = page.open_new(ws, 0, {}, say=lambda line: None)
    assert opened is not None and is_open(ws.dir)
    monkeypatch.chdir(here / "evals")
    assert "Closed the marking page." in run(capsys, "--stop")[1]
    assert not is_open(ws.dir)


def test_a_session_of_its_own_that_holds_marks_stays_in_use(here, capsys, monkeypatch):
    """The nearest that holds marks: marks in evals/ are never passed over."""
    _marked_above(here, capsys, ".git")
    _empty_session_in(here / "evals")
    _mark(Workspace(here / "evals"), only=range(2))
    monkeypatch.chdir(here / "evals")
    code, said = _said(capsys)
    assert code == 0 and "You marked 2 answers so far" in said, said


def test_a_project_of_its_own_below_keeps_its_own_marks(here, capsys, monkeypatch):
    """A project file in evals/ makes it a project: an empty session there is its own."""
    _marked_above(here, capsys, ".git")
    (here / "evals" / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(here / "evals")
    code, said = _said(capsys)
    assert code == 0 and "You marked" not in said, said
    assert (here / "evals" / ".judgekeeper" / "start.json").is_file()
    assert project.project_of(here / "evals") == (here / "evals").resolve()


def test_an_empty_session_for_other_results_is_kept(here, capsys, monkeypatch):
    """Results above marked, other results in a folder of their own: its session, marks or
    none, is theirs."""
    _marked_above(here, capsys, ".git")
    table_project(here / "other", split(20, 16), tag="other")
    monkeypatch.chdir(here / "other")
    assert _said(capsys)[0] == 0
    code, said = _said(capsys)
    assert code == 0 and "You marked" not in said, said
    assert project.project_of(here / "other") == (here / "other").resolve()


def test_no_marks_anywhere_stays_as_it_was(here, capsys, monkeypatch):
    """A first run in evals/, then one at the root: the session below is still the one."""
    (here / ".git").mkdir()
    table_project(here, split(20, 16), name="evals/results.csv")
    monkeypatch.chdir(here / "evals")
    assert _said(capsys)[0] == 0
    monkeypatch.chdir(here)
    code, said = _said(capsys)
    assert code == 3 and "evals/ already holds your judgekeeper session (0 marks)" in said, said
