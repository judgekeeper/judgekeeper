"""Several services in one git repository, each run in its own folder: which folder a run
reads, which sessions below it names (and from where), the line on results in a folder above,
and the lines of Find that name files and columns."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import front, project
from tests.test_answers_without_grades import write_answers
from tests.test_front import flat, run

HERE = "This folder already holds your judgekeeper session (0 marks)."
ABOVE = "Results in the folder above? Run `judgekeeper .. "  # then the run's flags
ABOVE_2 = "Results in a folder above? Run `judgekeeper ../.. "
SAVED = "judgekeeper saved your LLM-as-a-judge's setup in .judgekeeper/judge.json."


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository below the home folder, holding no results of its own."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "repo"
    (top / ".git").mkdir(parents=True)
    (top / "services").mkdir()
    return top


def support_bot(repo, graded: int = 20, evals: bool = True):
    """services/support-bot: bot.py, evals/results.csv (graded), src/fixtures/qa.csv (answers
    with no grade)."""
    bot = repo / "services" / "support-bot"
    (bot / "src" / "fixtures").mkdir(parents=True)
    (bot / "bot.py").write_text("", encoding="utf-8")
    write_answers(bot / "src" / "fixtures", 12, name="qa")
    if evals:
        (bot / "evals").mkdir()
        write_answers(bot / "evals", graded, grades=(["pass"] * 4 + ["fail"]) * (graded // 5))
    return bot


def rag(repo):
    """services/rag: rag.py, answers.csv (no grade), an empty scratch/."""
    folder = repo / "services" / "rag"
    (folder / "scratch").mkdir(parents=True)
    (folder / "rag.py").write_text("", encoding="utf-8")
    write_answers(folder, 14, name="answers")
    return folder


def _run(capsys, monkeypatch, folder, *argv) -> tuple[int, str]:
    monkeypatch.chdir(folder)
    project.forget()
    code, out, err = run(capsys, *argv, "--no-browser", "--port", "0")
    return code, flat(out + err)


# Sessions below, named from the folder run in ------------------------------------

def test_the_session_in_the_folder_run_in_is_this_folder(repo, capsys, monkeypatch):
    bot = support_bot(repo, evals=False)
    assert _run(capsys, monkeypatch, bot / "src")[0] == 0
    code, said = _run(capsys, monkeypatch, bot / "src", "..")
    assert code == 3, said
    assert HERE in said, said
    assert "./" not in said and "cd ." not in said, said
    assert "Next: run `judgekeeper`." in said, said


def test_a_folder_with_nothing_to_read_names_every_session_below(repo, capsys, monkeypatch):
    bot = support_bot(repo)
    assert _run(capsys, monkeypatch, bot / "src")[0] == 0
    assert _run(capsys, monkeypatch, bot / "evals")[0] == 3  # 20 answers: judge.json only
    code, said = _run(capsys, monkeypatch, bot)
    assert code == 3, said
    assert ("evals/ (0 marks) and src/ (0 marks) already hold your judgekeeper sessions"
            in said), said
    code, said = _run(capsys, monkeypatch, bot / "src", "..")
    assert code == 3, said
    assert ("../evals/ (0 marks) and this folder (0 marks) already hold your judgekeeper "
            "sessions") in said, said


def test_a_first_run_that_saved_only_judge_json_does_not_stop_the_line(repo, capsys,
                                                                        monkeypatch):
    bot = support_bot(repo)
    for folder in (bot, bot / "src", bot / "evals"):
        _run(capsys, monkeypatch, folder)
    for argv in ((), (".",)):
        code, said = _run(capsys, monkeypatch, bot, *argv)
        assert code == 3, said
        assert ("evals/ (0 marks) and src/ (0 marks) already hold your judgekeeper sessions"
                in said), said


def test_a_folder_with_its_own_session_reads_its_results(repo, capsys, monkeypatch):
    bot = support_bot(repo, graded=40)
    assert _run(capsys, monkeypatch, bot)[0] == 0  # a page: its own session, 0 marks
    assert _run(capsys, monkeypatch, bot / "src")[0] == 0
    for argv in ((), (".",)):
        code, said = _run(capsys, monkeypatch, bot, *argv)
        assert code == 0, said
        assert "already holds" not in said and "evals/results.csv" in said, said


def test_a_folder_with_results_of_its_own_is_not_sent_below(repo, capsys, monkeypatch):
    bot = support_bot(repo, evals=False)
    write_answers(bot, 40, grades=["pass", "fail"] * 20)
    assert _run(capsys, monkeypatch, bot / "src")[0] == 0
    code, said = _run(capsys, monkeypatch, bot)
    assert code == 0, said
    assert "already holds" not in said and "File: results.csv" in said, said


# The repository's top never reads a service's own file --------------------------------

def test_the_top_names_the_projects_below_and_reads_none_of_their_files(repo, capsys,
                                                                       monkeypatch):
    two = repo / "services" / "two"
    two.mkdir()
    write_answers(two, 12, grades=["pass", "fail"] * 6)
    with (two / "results-v4.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["prompt", "completion", "label"])
        w.writerows([f"Question {i}?", f"Answer {i}.", "pass" if i % 2 else "fail"]
                    for i in range(10))
    mine = repo / "services" / "mine"
    mine.mkdir()
    write_answers(mine, 12, grades=["pass", "fail"] * 6)
    for folder in (two, mine):
        _run(capsys, monkeypatch, folder)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert "format of its own" not in said and "judgekeeper.toml" not in said, said
    assert "services/mine/ and services/two/" in said, said
    assert not (repo / "judgekeeper.toml").exists() and not (repo / ".judgekeeper").exists()


def test_a_link_left_out_does_not_hide_the_projects_below(repo, capsys, monkeypatch):
    bot = support_bot(repo)
    mine = repo / "services" / "mine"
    mine.mkdir()
    write_answers(mine, 12, grades=["pass", "fail"] * 6)
    link = repo / "services" / "link"
    link.mkdir()
    try:
        (link / "results.csv").symlink_to(bot / "evals" / "results.csv")
    except OSError:
        pytest.skip("no symbolic links here")
    for folder in (bot / "evals", mine):
        _run(capsys, monkeypatch, folder)
    code, said = _run(capsys, monkeypatch, repo)
    assert code == 3, said
    assert "projects in services/mine/ and services/support-bot/evals/." in said, said
    assert "link" not in said, said


# Results in a folder above, up to the project folder -----------------------------------

def test_an_empty_folder_below_a_session_names_the_folder_above(repo, capsys, monkeypatch):
    folder = rag(repo)
    assert _run(capsys, monkeypatch, folder)[0] == 0
    code, said = _run(capsys, monkeypatch, folder / "scratch")
    assert code == 3 and "No answers yet?" in said, said
    assert said.count(ABOVE) == 1, said
    (folder / "scratch" / "deeper").mkdir()
    code, said = _run(capsys, monkeypatch, folder / "scratch" / "deeper")
    assert code == 3 and said.count(ABOVE_2) == 1, said


def test_answers_read_below_graded_results_name_the_folder_above(repo, capsys, monkeypatch):
    bot = support_bot(repo)
    code, said = _run(capsys, monkeypatch, bot / "src")
    assert code == 0 and "fixtures/qa.csv" in said, said
    assert said.count(ABOVE) == 1, said
    for argv in ((), ("mark",)):  # said once, with Find: never on the runs after it
        code, said = _run(capsys, monkeypatch, bot / "src", *argv)
        assert code == 0 and "Results in" not in said, said


def test_no_folder_above_line_with_nothing_above(repo, capsys, monkeypatch):
    folder = rag(repo)
    code, said = _run(capsys, monkeypatch, folder / "scratch")
    assert code == 3, said  # rag/ has answers but no session yet: a run there reads them
    assert said.count(ABOVE) == 1, said
    (folder / "answers.csv").unlink()
    code, said = _run(capsys, monkeypatch, folder / "scratch")
    assert code == 3 and "Results in" not in said, said


# What a first run saved ----------------------------------------------------------------

def test_too_few_answers_say_what_was_saved(repo, capsys, monkeypatch):
    bot = support_bot(repo)
    code, said = _run(capsys, monkeypatch, bot)
    assert code == 3 and "That is not enough answers for a first result." in said, said
    assert said.count(SAVED) == 1, said
    assert said.index("not enough answers") < said.index(SAVED) < said.index("Next:")


# Find's lines on files and columns ----------------------------------------------------------

def test_the_older_files_read_are_named(tmp_path, capsys, monkeypatch):
    write_answers(tmp_path, 12, grades=["pass", "fail"] * 6)
    write_answers(tmp_path, 10, name="results-v2", grades=["pass", "fail"] * 5)
    code, said = _run(capsys, monkeypatch, tmp_path)
    assert code == 3, said  # 22 answers: too few for a first result
    assert "Files: results-v2.csv and 1 older file (results.csv)" in said, said
    write_answers(tmp_path, 10, name="results-v3", grades=["pass", "fail"] * 5)
    code, said = _run(capsys, monkeypatch, tmp_path)
    assert "Files: results-v3.csv and 2 older files (results-v2.csv and results.csv)" in said, said


def test_a_table_of_its_own_counts_rows_and_says_its_columns_once(tmp_path, capsys,
                                                                   monkeypatch):
    with (tmp_path / "results-v3.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question", "response", "grade"])
        w.writerows([f"Question {i}?", f"Answer {i}.", "pass" if i % 2 else "fail"]
                    for i in range(10))
    code, said = _run(capsys, monkeypatch, tmp_path, "results-v3.csv")
    assert code == 3, said  # asks to save how to read it
    assert "results-v3.csv (10 rows):" in said and "What one row holds:" in said, said
    assert said.count("How judgekeeper reads it:") == 1, said
    assert "judgekeeper has read from your file:" not in said, said


def test_a_jsonl_file_of_its_own_counts_lines(tmp_path, capsys, monkeypatch):
    import json

    (tmp_path / "graded.jsonl").write_text("".join(
        json.dumps({"q": f"Question {i}?", "a": f"Answer {i}.", "grade": "pass"}) + "\n"
        for i in range(10)), encoding="utf-8")
    code, said = _run(capsys, monkeypatch, tmp_path, "graded.jsonl")
    assert code == 3, said
    assert "graded.jsonl (10 lines):" in said and "What one line holds:" in said, said


def test_front_has_the_lines():
    assert front.SAVED_SETUP.format(folder=".judgekeeper") == SAVED
