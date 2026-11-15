"""A plain folder inside a repository, above projects that each hold a session, names every
one of them, as the repository top does: a session on answers with no grade, on a file read
by a saved mapping (judgekeeper.toml) or on a linked file, and one on graded results. No page
opens: the page is served in a thread (conftest's pages)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.start_projects import split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_services_in_one_repo import _run


def _session(capsys, monkeypatch, folder, *argv):
    code, said = _run(capsys, monkeypatch, folder, *argv)
    assert code == 0, said


def _below(capsys, monkeypatch, mid: Path) -> None:
    """mid/: x/ (graded, a session), l/ and l2/ (graded, other questions), o/ (answers with
    no grade, a session), m/ (other column names, saved with --yes, a session) and s/ (a
    linked results file, a session from `judgekeeper results.csv`)."""
    table_project(mid / "x", split(20, 20), tag="x")
    _session(capsys, monkeypatch, mid / "x")
    table_project(mid / "l", split(5, 5), tag="l")
    table_project(mid / "l2", split(5, 5), tag="l2")
    (mid / "o").mkdir()
    write_answers(mid / "o", 40, name="answers")
    _session(capsys, monkeypatch, mid / "o")
    table_project(mid / "m", split(20, 20), tag="m", verdict_column="grade")
    path = mid / "m" / "results.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "input,output,grade", "question,response,grade", 1), encoding="utf-8")
    _session(capsys, monkeypatch, mid / "m", "results.csv", "--yes")
    assert (mid / "m" / "judgekeeper.toml").is_file()
    away = Path.home() / "linked-away"
    table_project(away, split(20, 20), tag="s")
    (mid / "s").mkdir()
    (mid / "s" / "app.py").write_text("", encoding="utf-8")
    try:
        (mid / "s" / "results.csv").symlink_to(away / "results.csv")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    _session(capsys, monkeypatch, mid / "s", "results.csv")


@pytest.mark.parametrize("where", ["a-plain-folder", "the-repository-top"])
def test_every_session_below_is_named(tmp_path, capsys, monkeypatch, where):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo"
    (top / ".git").mkdir(parents=True)
    mid = top / "g" / "mid" if where == "a-plain-folder" else top
    mid.mkdir(parents=True, exist_ok=True)
    _below(capsys, monkeypatch, mid)
    code, said = _run(capsys, monkeypatch, mid)
    assert code == 3, said
    assert "Find l/, l2/, m/, o/, s/ and x/ hold eval results" in said, said
    assert not (mid / ".judgekeeper").exists(), said


def test_a_project_below_that_stopped_before_marking_is_named_too(tmp_path, capsys,
                                                                  monkeypatch):
    """a/ (code, evals/results.csv two folders down, a first run that stopped before marking:
    judge.json only) is named with b/ and c/, and the command that goes there is given."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo"
    (top / ".git").mkdir(parents=True)
    mid = top / "services"
    table_project(mid / "b", split(5, 5), tag="b")
    table_project(mid / "c", split(5, 5), tag="c")
    a = mid / "a"
    table_project(a / "evals", split(5, 5), tag="a")  # too few answers to mark
    (a / "code.py").write_text("", encoding="utf-8")
    code, said = _run(capsys, monkeypatch, a)
    assert code == 3 and (a / ".judgekeeper" / "judge.json").is_file(), said
    assert not (a / ".judgekeeper" / "start.json").exists()
    for argv in ((), (".",)):
        code, said = _run(capsys, monkeypatch, mid, *argv)
        assert code == 3, said
        assert "Find a/, b/ and c/ hold eval results" in said, said
        assert "`cd a`" in said, said
        assert not (mid / ".judgekeeper").exists(), said
