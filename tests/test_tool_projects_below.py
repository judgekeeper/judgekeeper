"""A folder above projects of their own (no project file, no session of its own): files
inside a project below (a project file or its own .judgekeeper/) are never read or merged
there, with --tool NAME or with one tool's results found. When every file is in a project
below, they are named and the run stops; files in no project below are read as before, and the
projects below with files of that tool are named. A project folder (a git repository's top)
reads its own as before."""

from __future__ import annotations

import pytest

from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import (
    deepeval_project,
    inspect_project,
    promptfoo_project,
    split,
    table_project,
)
from tests.test_services_in_one_repo import _run, repo  # noqa: F401

ONE_AT_A_TIME = ("größe-prüfung/, multi/ and my service/ hold eval results: judgekeeper keeps a "
                 "project's marks in its own folder, so it checks one at a time.")


def _own_judgekeeper(capsys, monkeypatch, folder) -> None:
    """A run there with too few answers: its own .judgekeeper/ with judge.json."""
    code, said = _run(capsys, monkeypatch, folder)
    assert code == 3 and (folder / ".judgekeeper" / "judge.json").is_file(), said


@pytest.fixture
def services(repo, capsys, monkeypatch):  # noqa: F811
    """services/: pf-svc/ (promptfoo, no project), de-svc/ (DeepEval), insp-svc/ (Inspect
    AI), and größe-prüfung/, my service/ and multi/ (CSV files), each of these with its own
    .judgekeeper/."""
    top = repo / "services"
    promptfoo_project(top / "pf-svc", split(14, 6), name="evals/out.json")
    deepeval_project(top / "de-svc", split(11, 5), tag="de")
    inspect_project(top / "insp-svc", split(8, 4), tag="insp")
    table_project(top / "größe-prüfung", split(8, 4), tag="g")
    table_project(top / "my service", split(10, 4), tag="m")
    table_project(top / "multi", split(7, 3), tag="x")
    table_project(top / "multi", split(7, 3), name="results-v2.csv", tag="y")
    for name in ("de-svc", "insp-svc", "größe-prüfung", "my service", "multi"):
        _own_judgekeeper(capsys, monkeypatch, top / name)
    return top


def test_the_plain_run_lists_the_tools_as_before(services, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, services)
    assert code == 3, said
    assert "Saved results from more than one eval tool:" in said, said
    assert "--tool NAME" in said, said
    assert not (services / ".judgekeeper").exists()


def test_tool_table_names_the_projects_below_and_stops(services, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, services, "--tool", "table")
    assert code == 3, said
    assert ONE_AT_A_TIME in said, said
    assert "Answers:" not in said and "Next: go to one of those folders" in said, said
    assert not (services / ".judgekeeper").exists()


@pytest.mark.parametrize(("tool", "folder"), [("deepeval", "de-svc"), ("inspect", "insp-svc")])
def test_tool_with_its_files_in_one_project_below_names_it_and_stops(services, capsys,
                                                                     monkeypatch, tool, folder):
    code, said = _run(capsys, monkeypatch, services, "--tool", tool)
    assert code == 3, said
    assert (f"These results belong to the project in {folder}/. To check them, run "
            f"`judgekeeper` in {folder}/.") in said, said
    assert "Answers:" not in said, said
    assert not (services / ".judgekeeper").exists()


def test_tool_with_its_files_in_no_project_below_reads_them_as_before(services, capsys,
                                                                      monkeypatch):
    code, said = _run(capsys, monkeypatch, services, "--tool", "promptfoo")
    assert code == 3, said  # 20 answers: too few
    assert "File: pf-svc/evals/out.json" in said, said
    assert "results too" not in said, said
    assert (services / ".judgekeeper" / "judge.json").is_file()


def test_files_in_no_project_are_read_and_the_projects_with_that_tools_files_named(
        repo, capsys, monkeypatch):  # noqa: F811
    top = repo / "services"
    table_project(top / "plain", split(8, 4), tag="p")
    table_project(top / "multi", split(7, 3), tag="x")
    deepeval_project(top / "de-svc", split(11, 5), tag="de")
    for name in ("multi", "de-svc"):
        _own_judgekeeper(capsys, monkeypatch, top / name)
    code, said = _run(capsys, monkeypatch, top, "--tool", "table")
    assert code == 3, said  # 12 answers: too few
    assert "File: plain/results.csv" in said and "Answers: 12 answers" in said
    assert ("The project in multi/ has results too: to check them, run `judgekeeper multi`."
            in said), said
    assert "de-svc" not in said, said  # no CSV file there


def test_a_folder_with_only_its_own_results_reads_them_with_tool_table(repo, capsys,  # noqa: F811
                                                                       monkeypatch):
    folder = repo / "services" / "solo"
    table_project(folder, split(8, 4), tag="s")
    code, said = _run(capsys, monkeypatch, folder, "--tool", "table")
    assert code == 3, said  # 12 answers: too few
    assert "File: results.csv" in said and "Answers: 12 answers" in said
    assert "results too" not in said and "hold eval results" not in said, said


def test_the_next_run_with_no_tool_keeps_to_the_same_files(repo, capsys, monkeypatch):  # noqa: F811
    top = repo / "services"
    table_project(top, split(24, 16), tag="p")  # services/results.csv, its own
    table_project(top / "multi", split(7, 3), tag="x")
    _own_judgekeeper(capsys, monkeypatch, top / "multi")
    code, said = _run(capsys, monkeypatch, top, "--tool", "table")
    assert code == 0, said
    assert "File: results.csv" in said and "Answers: 40 answers" in said, said
    assert ("The project in multi/ has results too: to check them, run `judgekeeper "
            "multi`.") in said, said
    table_project(top / "multi", split(7, 3), name="results-v2.csv", tag="y")  # newer answers
    code, said = _run(capsys, monkeypatch, top)  # the tool kept in the session
    assert code == 0 and "new answers" not in said, said
    assert len(StartSession(Workspace(top)).raw) == 40, said


# The plain run: one tool's results found ------------------------------------------------------

MULTI_TOO = "The project in multi/ has results too: to check them, run `judgekeeper multi`."


def test_the_plain_run_reads_its_own_file_and_names_the_project_below(repo, capsys,  # noqa: F811
                                                                      monkeypatch):
    top = repo / "services"
    table_project(top, split(8, 4), name="own.csv", tag="p")
    table_project(top / "multi", split(7, 3), tag="x")
    _own_judgekeeper(capsys, monkeypatch, top / "multi")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said  # 12 answers: too few
    assert "File: own.csv" in said and "Answers: 12 answers" in said, said
    assert MULTI_TOO in said, said


def test_the_plain_run_with_its_files_in_one_project_below_names_it_and_stops(
        repo, capsys, monkeypatch):  # noqa: F811
    top = repo / "services"
    deepeval_project(top / "de-svc", split(11, 5), tag="de")
    _own_judgekeeper(capsys, monkeypatch, top / "de-svc")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert ("These results belong to the project in de-svc/. To check them, run "
            "`judgekeeper` in de-svc/.") in said, said
    assert "Answers:" not in said and not (top / ".judgekeeper").exists(), said


def test_the_plain_run_with_only_projects_below_stops_as_before(repo, capsys,  # noqa: F811
                                                                 monkeypatch):
    top = repo / "services"
    for name, tag in (("gym", "g"), ("dental", "d")):
        table_project(top / name, split(8, 4), tag=tag)
        _own_judgekeeper(capsys, monkeypatch, top / name)
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert ("dental/ and gym/ hold eval results: judgekeeper keeps a project's marks in its own "
            "folder, so it checks one at a time.") in said, said
    assert not (top / ".judgekeeper").exists()


def test_the_plain_run_in_a_folder_with_only_its_own_results_reads_them(repo, capsys,  # noqa: F811
                                                                        monkeypatch):
    folder = repo / "services" / "solo"
    table_project(folder, split(8, 4), tag="s")
    table_project(folder / "evals", split(7, 3), name="more.csv", tag="t")  # in no project
    code, said = _run(capsys, monkeypatch, folder)
    assert code == 3, said
    assert "Files: results.csv and 1 older file (evals/more.csv)" in said or \
        "Files: evals/more.csv and 1 older file (results.csv)" in said, said
    assert "results too" not in said and "hold eval results" not in said, said


def test_a_repository_top_reads_its_own_and_names_the_project_below_as_before(
        repo, capsys, monkeypatch):  # noqa: F811
    table_project(repo, split(8, 4), name="own.csv", tag="p")
    table_project(repo / "services" / "multi", split(7, 3), tag="x")
    _own_judgekeeper(capsys, monkeypatch, repo / "services" / "multi")
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert "File: own.csv" in said and "Answers: 12 answers" in said, said
    assert ("The project in services/multi/ has results too: to check them, run `judgekeeper "
            "services/multi`.") in said, said


def test_the_next_plain_run_keeps_to_its_own_file(repo, capsys, monkeypatch):  # noqa: F811
    top = repo / "services"
    table_project(top, split(24, 16), name="own.csv", tag="p")
    table_project(top / "multi", split(7, 3), tag="x")
    _own_judgekeeper(capsys, monkeypatch, top / "multi")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 0, said
    assert "File: own.csv" in said and "Answers: 40 answers" in said and MULTI_TOO in said, said
    table_project(top / "multi", split(7, 3), name="results-v2.csv", tag="y")  # newer answers
    code, said = _run(capsys, monkeypatch, top)
    assert code == 0 and "new answers" not in said, said
    assert len(StartSession(Workspace(top)).raw) == 40, said


def test_a_session_with_marks_keeps_to_its_own_file(repo, capsys, monkeypatch):  # noqa: F811
    top = repo / "services"
    table_project(top, split(24, 16), name="own.csv", tag="p")
    table_project(top / "multi", split(7, 3), tag="x")
    _own_judgekeeper(capsys, monkeypatch, top / "multi")
    assert _run(capsys, monkeypatch, top)[0] == 0
    page = StartSession(Workspace(top))
    for n, item in enumerate(page.items):
        page.update({"id": item["id"], "label": "pass" if n % 2 else "fail", "seconds": 3})
    table_project(top / "multi", split(7, 3), name="results-v2.csv", tag="y")  # newer answers
    code, said = _run(capsys, monkeypatch, top)
    assert code == 0 and "own.csv has LLM-as-a-judge grades" in said, said
    assert "multi/results" not in said, said
    assert len(StartSession(Workspace(top)).raw) == 40, said
