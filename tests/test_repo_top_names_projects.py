"""From the top of a repository with services below it: the projects below are named when they
hold results, answers with no grade included, and after the top reads results of its own it
says which projects below have results too. A folder with code and answers with no grade says
how to read the results in the folder above."""

from __future__ import annotations

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
            "`judgekeeper services/support-bot`.") in said, said


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
