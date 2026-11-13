"""Which files a run reads, by layout: a file belongs to the nearest project of its own between
its folder and the folder run in (a project file, or its own .judgekeeper/). A run never reads
a file of a project below; files from two subfolders that share no questions are never pooled
(it stops and names them), at a git top or not; an empty folder of a project reads that
project."""

from __future__ import annotations

import json
import os
import time

import pytest

from tests.start_projects import split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_files_in_projects_below import own  # noqa: F401
from tests.test_services_in_one_repo import _run, repo  # noqa: F401

STOPS = "hold eval results: judgekeeper keeps a project's marks in its own folder, so it " \
        "checks one at a time."


def _judged_only(folder):
    """A .judgekeeper/ holding only the judge.json of a run that stopped before marking."""
    (folder / ".judgekeeper").mkdir(parents=True, exist_ok=True)
    (folder / ".judgekeeper" / "judge.json").write_text("{}", encoding="utf-8")


def _code_project(folder, tag):
    """app.py, results.csv (12, graded) and its own .judgekeeper/ (judge.json only)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app.py").write_text("", encoding="utf-8")
    table_project(folder, split(6, 6), tag=tag)
    _judged_only(folder)


@pytest.fixture
def repo2(tmp_path, monkeypatch):
    """A git top: a/ a project with its own .judgekeeper/, b/ and c/ plain folders with
    results that share no questions."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo2"
    (top / ".git").mkdir(parents=True)
    _code_project(top / "a", "a")
    table_project(top / "b", split(5, 5), tag="b")
    table_project(top / "c", split(5, 5), tag="c")
    return top


def _wrote_nothing(folder):
    assert not (folder / ".judgekeeper").exists(), list((folder / ".judgekeeper").iterdir())


def test_a_git_top_never_pools_two_plain_subfolders(repo2, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, repo2)
    assert code == 3, said
    assert f"a/, b/ and c/ {STOPS}" in said, said
    assert "Answers:" not in said, said
    _wrote_nothing(repo2)


def test_an_empty_folder_at_a_git_top_stops_there_too(repo2, capsys, monkeypatch):
    (repo2 / "n3a").mkdir()
    code, said = _run(capsys, monkeypatch, repo2 / "n3a")
    assert code == 3, said
    assert "Answers:" not in said, said
    _wrote_nothing(repo2)
    _wrote_nothing(repo2 / "n3a")


def test_a_folder_with_its_own_judgekeeper_is_never_read_from_the_top(tmp_path, capsys,
                                                                       monkeypatch):
    """T6's own top: h1b/ (own.csv, a judge.json-only .judgekeeper/), n4/ and shared-data/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t6"
    (top / ".git").mkdir(parents=True)
    table_project(top / "h1b", split(6, 6), name="own.csv", tag="h")
    _judged_only(top / "h1b")
    table_project(top / "n4", split(1, 1), tag="n")
    table_project(top / "shared-data", split(6, 6), tag="s")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert "h1b/own.csv" not in said and "Answers:" not in said, said
    assert f"h1b/, n4/ and shared-data/ {STOPS}" in said, said
    _wrote_nothing(top)


@pytest.mark.parametrize("session", ["judged", "none"])
def test_own_answers_are_read_never_a_project_below(tmp_path, capsys, monkeypatch, session):
    """n4b/ (answers.csv with no grades, a judge.json-only .judgekeeper/) and n4b2/ (no
    .judgekeeper/), each with proj/ below: app.py, results.csv, its own .judgekeeper/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    folder = tmp_path / "n4b"
    folder.mkdir()
    write_answers(folder, 12, name="answers")
    if session == "judged":
        _judged_only(folder)
    _code_project(folder / "proj", "p")
    said = _run(capsys, monkeypatch, folder)[1]
    assert "File: answers.csv" in said, said
    assert "proj/results.csv" not in said, said
    assert "judgekeeper proj" in said, said  # named, with the command that checks it
    assert not (folder / "proj" / ".judgekeeper" / "start.json").exists()


def test_an_empty_folder_of_a_project_points_at_that_project(repo, capsys,  # noqa: F811
                                                              monkeypatch):
    """services/rag/scratch: rag/ has rag.py, answers.csv and its own .judgekeeper/; the
    repository's top holds results. The run never reads past rag/: it names rag/ (`..`)."""
    rag = repo / "services" / "rag"
    (rag / "scratch").mkdir(parents=True)
    (rag / "rag.py").write_text("", encoding="utf-8")
    write_answers(rag, 15, name="answers")
    _judged_only(rag)
    table_project(repo / "loose", split(5, 5), tag="l")
    code, said = _run(capsys, monkeypatch, rag / "scratch")
    assert code == 3, said
    assert "Results in the folder above? Run `judgekeeper .. " in said, said
    assert "Reading the project folder above" not in said and "loose" not in said, said
    _wrote_nothing(repo)
    _wrote_nothing(repo / "services")


@pytest.mark.parametrize("where", ["", "more/"])
def test_an_unrelated_newer_file_never_replaces_the_marked_answers(own, capsys,  # noqa: F811
                                                                    monkeypatch, where):
    """40 answers marked; then other.jsonl, 15 answers sharing no question, newest: beside
    them or in a folder below (T4's b4/sub). It is another eval, wherever it sits."""
    folder = own / where
    folder.mkdir(exist_ok=True)
    (folder / "other.jsonl").write_text("".join(
        json.dumps({"input": f"Unrelated question {i}?", "output": f"Other answer {i}."}) + "\n"
        for i in range(15)), encoding="utf-8")
    later = time.time() + 60
    os.utime(folder / "other.jsonl", (later, later))
    code, said = _run(capsys, monkeypatch, own)
    assert code == 0, said
    assert f"{where}other.jsonl shares few questions with the results you marked" in said, said
    assert "new answers" not in said and "15 of 15" not in said, said
    assert "Full report: .judgekeeper/report.html" in said, said


@pytest.mark.parametrize("stray", ["script.py", ".judgekeeper/judge.json"])
def test_a_shared_folder_with_a_script_is_never_read_from_an_empty_folder_below(
        tmp_path, capsys, monkeypatch, stray):
    """work/ holds a script of its own (or a .judgekeeper/ from a run there once) and two
    folders with results; a run in work/new/ (empty) never reads them."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    (work / stray).parent.mkdir(parents=True, exist_ok=True)
    (work / stray).write_text("{}", encoding="utf-8")
    _code_project(work / "a", "a")
    table_project(work / "b", split(5, 5), tag="b")
    (work / "new").mkdir()
    code, said = _run(capsys, monkeypatch, work / "new")
    assert code == 3, said
    assert "Reading the project folder above" not in said and "Answers:" not in said, said
    assert not (work / "new" / ".judgekeeper").exists()
