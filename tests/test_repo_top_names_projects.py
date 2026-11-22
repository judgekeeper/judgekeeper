"""From the top of a repository with services below it: the projects below are named when they
hold results, answers with no grade included, and after the top reads results of its own it
says which projects below have results too. A folder with code and answers with no grade says
how to read the results in the folder above."""

from __future__ import annotations

import pytest

from tests.start_projects import split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_services_in_one_repo import ABOVE, _run, rag, repo, support_bot  # noqa: F401

BELONG = "These results belong to"


def _plain(top):
    """plain/: graded results, no code, no project file, no session: the top's own."""
    folder = top / "plain"
    folder.mkdir(parents=True)
    write_answers(folder, 20, grades=(["pass"] * 4 + ["fail"]) * 4)
    return folder


def _own_project(folder):
    (folder / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")


# M2: results read at the top, projects below with results of their own -----------------------

def test_the_top_reading_results_below_names_the_projects_with_results_too(repo, capsys,  # noqa: F811
                                                                          monkeypatch):
    _plain(repo)
    bot = support_bot(repo)
    _own_project(bot)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3 and "File: plain/results.csv" in said, said  # 20 answers: too few
    assert BELONG not in said, said
    assert ("The project in services/support-bot/ has results too: to check them, run "
            "`judgekeeper services/support-bot --no-browser`.") in said, said


def test_the_top_reading_results_below_names_no_project_without_results(repo, capsys,  # noqa: F811
                                                                         monkeypatch):
    _plain(repo)
    bot = repo / "services" / "empty"
    bot.mkdir()
    _own_project(bot)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3 and "File: plain/results.csv" in said, said  # 20 answers: too few
    assert BELONG not in said and "results too" not in said, said


# M1(a): projects below whose results are answers with no grade -------------------------------

def test_the_top_names_a_project_below_with_answers_with_no_grade(repo, capsys,  # noqa: F811
                                                                  monkeypatch):
    bot, folder = support_bot(repo), rag(repo)
    _own_project(bot)
    _own_project(folder)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert (f"{BELONG} the projects in services/rag/ and services/support-bot/.") in said, said


def test_the_top_names_every_session_below_answers_with_no_grade_too(repo, capsys,  # noqa: F811
                                                                     monkeypatch):
    bot, folder = support_bot(repo, graded=40), rag(repo)
    assert _run(capsys, monkeypatch, bot)[0] == 0
    assert _run(capsys, monkeypatch, folder)[0] == 0
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert ("services/rag/ (0 marks) and services/support-bot/ (0 marks) already hold your "
            "judgekeeper sessions") in said, said


# L1: a folder with code and answers with no grade --------------------------------------------

def test_a_code_folder_with_answers_names_the_results_above_once(repo, capsys,  # noqa: F811
                                                                 monkeypatch):
    bot = support_bot(repo, graded=40)
    assert _run(capsys, monkeypatch, bot)[0] == 0  # the session above, with its results
    (bot / "src" / "app.py").write_text("", encoding="utf-8")
    code, said = _run(capsys, monkeypatch, bot / "src")
    assert code == 0 and "File: fixtures/qa.csv" in said, said
    assert said.count(ABOVE) == 1, said
    code, said = _run(capsys, monkeypatch, bot / "src")
    assert ABOVE not in said, said  # said with Find only


# Every project below named, the same way each time -------------------------------------------

def _session(capsys, monkeypatch, folder, *argv):
    """A run in `folder` starts its session (a page, 0 marks)."""
    code, said = _run(capsys, monkeypatch, folder, *argv)
    assert code == 0, said


def _linked(capsys, monkeypatch, top, name):
    """name/: pyproject.toml, results.csv a link to a graded file away from the repo, and a
    session from `judgekeeper results.csv` (the walk passes over the link)."""
    away = top.parent / f"{name}-data"
    table_project(away, split(20, 20), tag=name)
    folder = top / name
    folder.mkdir()
    _own_project(folder)
    try:
        (folder / "results.csv").symlink_to(away / "results.csv")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    _session(capsys, monkeypatch, folder, "results.csv")


def _answers_over_a_project(capsys, monkeypatch, folder, tag):
    """folder/: answers with no grade and a session, over proj/ (a project with its own)."""
    proj = folder / "proj"
    proj.mkdir(parents=True)
    _own_project(proj)
    table_project(proj, split(20, 20), tag=tag)
    _session(capsys, monkeypatch, proj)
    write_answers(folder, 40, name="answers")
    _session(capsys, monkeypatch, folder)


def _listed(said):
    return said.split("Step 1 of 4: Read ")[1].split(" hold eval results")[0]


@pytest.mark.parametrize("loose", [False, True], ids=["alone", "beside-a-loose-folder"])
@pytest.mark.parametrize("rounds", [False, True], ids=["other-questions", "same-questions"])
def test_the_top_names_every_project_below_whatever_the_plain_folders_hold(
        tmp_path, capsys, monkeypatch, rounds, loose):
    """b/, c/ and jj/ (plain, graded) hold other questions or rounds of one eval; a/ and h/
    hold a session on graded results, n/ and n2/ one on answers with no grade over a project
    of their own, sl/ and sl2/ one on a linked file. The top names each the same way, with
    or without a loose folder of other questions (_data/)."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo"
    (top / ".git").mkdir(parents=True)
    (top / "a").mkdir()
    _own_project(top / "a")
    table_project(top / "a", split(20, 20), tag="a")
    _session(capsys, monkeypatch, top / "a")
    table_project(top / "h", split(20, 20), tag="h", name="own.csv")
    _session(capsys, monkeypatch, top / "h")
    for name in ("b", "c", "jj"):
        table_project(top / name, split(5, 5), tag="r" if rounds else name)
    for name in ("n", "n2"):
        _answers_over_a_project(capsys, monkeypatch, top / name, name)
    for name in ("sl", "sl2"):
        _linked(capsys, monkeypatch, top, name)
    if loose:
        table_project(top / "_data", split(5, 5), tag="d", name="in-repo.csv")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    names = "a/, b/, c/, h/, jj/, n/, n2/, sl/ and sl2/"
    assert _listed(said) == ("_data/, " if loose else "") + names, said


def test_the_top_with_one_plain_folder_names_a_linked_session_and_an_answers_session(
        tmp_path, capsys, monkeypatch):
    """sl/ (a session on a linked file), b/results.csv and n/ (answers with no grade and a
    session, over proj/): the top names b/, n/ and sl/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo"
    (top / ".git").mkdir(parents=True)
    _linked(capsys, monkeypatch, top, "sl")
    table_project(top / "b", split(5, 5), tag="b")
    _answers_over_a_project(capsys, monkeypatch, top / "n", "n")
    code, said = _run(capsys, monkeypatch, top)
    assert code == 3, said
    assert _listed(said) == "b/, n/ and sl/", said
