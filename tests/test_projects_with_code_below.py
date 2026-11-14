"""A folder above projects of their own names every one below that holds results or a
session, its folder holding code (bot.py) or not, as a repository's top does."""

from __future__ import annotations

import pytest

from tests.start_projects import deepeval_project, split, table_project
from tests.test_answers_without_grades import write_answers
from tests.test_services_in_one_repo import _run, repo  # noqa: F401

BOTH_TOO = ("The projects in a/ and a2/ have results too: to check them, run "
            "`judgekeeper a --no-browser` or `judgekeeper a2 --no-browser`.")


@pytest.fixture
def services2(repo, capsys, monkeypatch):  # noqa: F811
    """services/: a/ (bot.py, evals/results.csv, its own .judgekeeper/), a2/ (rag.py,
    answers.csv with no grade, its own .judgekeeper/) and b/results.csv in no project."""
    top = repo / "services"
    (top / "a").mkdir()
    (top / "a" / "bot.py").write_text("", encoding="utf-8")
    table_project(top / "a" / "evals", split(24, 16), tag="a")
    (top / "a2").mkdir()
    (top / "a2" / "rag.py").write_text("", encoding="utf-8")
    write_answers(top / "a2", 20, name="answers")
    for name in ("a", "a2"):
        said = _run(capsys, monkeypatch, top / name)[1]
        assert (top / name / ".judgekeeper" / "start.json").is_file(), said  # a session
    table_project(top / "b", split(10, 5), tag="b")
    return top


def test_the_plain_run_names_the_projects_with_code_below(services2, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, services2)
    assert code == 3, said  # 15 answers: too few
    assert "File: b/results.csv" in said and "Answers: 15 answers" in said, said
    assert BOTH_TOO in said, said


def test_after_a_run_named_from_above_the_plain_run_still_reads_b(services2, capsys,
                                                                  monkeypatch):
    assert _run(capsys, monkeypatch, services2)[0] == 3  # .judgekeeper/judge.json here
    assert _run(capsys, monkeypatch, services2, "a")[0] == 0  # a/'s session, from here
    code, said = _run(capsys, monkeypatch, services2)
    assert code == 3, said
    assert "hold eval results" not in said, said
    assert "File: b/results.csv" in said and BOTH_TOO in said, said


THREE_TOO = ("The projects in a/, a2/ and de-bot/ have results too: to check them, run "
             "`judgekeeper a --no-browser`, `judgekeeper a2 --no-browser` or "
             "`judgekeeper de-bot --no-browser`.")


@pytest.fixture
def with_de_bot(services2, capsys, monkeypatch):
    """services2, and de-bot/ (DeepEval, no code) with its own .judgekeeper/."""
    deepeval_project(services2 / "de-bot", split(11, 5), tag="de")
    code, said = _run(capsys, monkeypatch, services2 / "de-bot")
    assert code == 3 and (services2 / "de-bot" / ".judgekeeper" / "judge.json").is_file(), said
    return services2


def test_projects_with_code_or_not_are_named_together(with_de_bot, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, with_de_bot)
    assert code == 3, said
    assert "File: b/results.csv" in said and THREE_TOO in said, said


def test_tool_table_names_the_projects_with_csv_files(with_de_bot, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, with_de_bot, "--tool", "table")
    assert code == 3, said
    assert "File: b/results.csv" in said and BOTH_TOO in said, said
    assert "de-bot" not in said, said
