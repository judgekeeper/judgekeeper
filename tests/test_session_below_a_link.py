"""A repository top that reads a loose results file names a project below whose session reads
a linked file, as it names one whose results file is a real file: the same questions are
never in two sessions. A session's results file may be a link inside the repository or away
from it, or a link to nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.start_projects import split, table_project
from tests.test_services_in_one_repo import _run

NAMED = "ext/ and sl/ hold eval results"
LINK = str(Path("..") / "ext" / "graded.csv")  # Windows reads a link's target with backslashes


def _top(tmp_path, monkeypatch, name: str) -> Path:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / name
    (top / ".git").mkdir(parents=True)
    return top


def _sl(capsys, monkeypatch, top: Path, results: Path, link: str | None) -> Path:
    """top/sl/: a project file and a session from `judgekeeper mark results.csv`, the results file
    a link to `link` (a path from sl/), or a copy of `results` when `link` is None."""
    sl = top / "sl"
    sl.mkdir()
    (sl / "pyproject.toml").write_text('[project]\nname="sl"\n', encoding="utf-8")
    if link is None:
        (sl / "results.csv").write_bytes(results.read_bytes())
    else:
        try:
            (sl / "results.csv").symlink_to(link)
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links not allowed here")
    code, said = _run(capsys, monkeypatch, sl, "mark", "results.csv")
    assert code == 0, said
    return sl


def _v5(tmp_path, capsys, monkeypatch, name: str, link: str | None = LINK):
    """The repository top: ext/graded.csv (loose, 40 rows) and sl/ with a session."""
    top = _top(tmp_path, monkeypatch, name)
    loose = table_project(top / "ext", split(20, 20), name="graded.csv", tag="v5q")
    return top, _sl(capsys, monkeypatch, top, loose, link)


def test_a_session_on_a_linked_file_is_named_beside_a_loose_results_file(
        tmp_path, capsys, monkeypatch):
    top, sl = _v5(tmp_path, capsys, monkeypatch, "linked")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert NAMED in said, said
    assert (sl / ".judgekeeper").is_dir()
    assert not (top / ".judgekeeper").exists()


def test_a_session_on_a_copy_is_named_the_same_way(tmp_path, capsys, monkeypatch):
    top, sl = _v5(tmp_path, capsys, monkeypatch, "copied", link=None)
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert NAMED in said, said
    linked, _ = _v5(tmp_path, capsys, monkeypatch, "linked")
    assert _run(capsys, monkeypatch, linked) == (code, said)
    assert (sl / ".judgekeeper").is_dir()
    assert not (top / ".judgekeeper").exists()


def test_a_session_on_a_link_to_a_file_away_from_the_repository_is_named_from_the_top(
        tmp_path, capsys, monkeypatch):
    away = table_project(tmp_path / "targets", split(20, 20), name="graded.csv", tag="away")
    top = _top(tmp_path, monkeypatch, "repo")
    sl = _sl(capsys, monkeypatch, top, away, str(Path("..") / ".." / "targets" / "graded.csv"))
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert "sl/ already holds your judgekeeper session (0 marks)" in said, said
    assert (sl / ".judgekeeper").is_dir()
    assert not (top / ".judgekeeper").exists()


def test_a_session_on_a_link_to_nothing_is_named_beside_a_loose_results_file(
        tmp_path, capsys, monkeypatch):
    top, sl = _v5(tmp_path, capsys, monkeypatch, "dangling")
    (sl / "results.csv").unlink()
    (sl / "results.csv").symlink_to(str(Path("..") / "ext" / "missing.csv"))
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert NAMED in said, said
    assert not (top / ".judgekeeper").exists()
