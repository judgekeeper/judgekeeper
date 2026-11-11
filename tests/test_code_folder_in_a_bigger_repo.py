"""A folder with code but no results, inside a bigger git repository that holds results: the
folder is the project. With no PATH it gets the question prompt and one line on how to read
the folder above; a PATH given (`.` or a folder) never climbs. record() and the command line
take a folder for a project's own by the same files."""

from __future__ import annotations

import pytest

from judgekeeper import find, project, recorder
from tests.test_answers_without_grades import write_answers
from tests.test_front import flat, run

HINT = "Results in the folder above? Run `judgekeeper .."
CLIMB = "Reading the project folder above it"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repository below the home folder, with graded results at its root."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "tests"
    (top / ".git").mkdir(parents=True)
    write_answers(top, 40, grades=["pass", "fail"] * 20)
    return top


def _folder(repo, files: tuple[str, ...]):
    folder = repo / "my-bot"
    folder.mkdir()
    for name in files:
        (folder / name).write_text("", encoding="utf-8")
    (folder / "docs").mkdir()
    return folder


def _run(capsys, monkeypatch, folder, *argv) -> tuple[int, str]:
    monkeypatch.chdir(folder)
    project.forget()
    code, out, err = run(capsys, *argv, "--no-browser")
    return code, flat(out + err)


CODE = [("bot.py",), ("bot.py", "requirements.txt"), ("requirements-dev.txt",), ("app.js",),
        ("index.ts",), ("pyproject.toml",), ("package.json",)]


@pytest.mark.parametrize("files", CODE)
def test_a_code_folder_gets_the_question_prompt_and_the_way_above(repo, capsys, monkeypatch,
                                                                   files):
    code, said = _run(capsys, monkeypatch, _folder(repo, files))
    assert code == 3 and "No answers yet?" in said, said
    assert CLIMB not in said and "Answers:" not in said
    assert said.count(HINT) == 1, said
    assert said.index("No answers yet?") < said.index(HINT)


@pytest.mark.parametrize("files", [("bot.py",), ()])
def test_a_path_given_never_climbs(repo, capsys, monkeypatch, files):
    code, said = _run(capsys, monkeypatch, _folder(repo, files), ".")
    assert code == 3 and "No answers yet?" in said, said
    assert CLIMB not in said and "Answers:" not in said


def test_the_way_above_reads_the_results_there(repo, capsys, monkeypatch):
    folder = _folder(repo, ("bot.py",))
    code, said = _run(capsys, monkeypatch, folder, "..")
    assert code == 0 and "results.csv" in said, said


def test_a_folder_with_no_code_still_reads_the_project_folder_above(repo, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, _folder(repo, ("notes.md",)))
    assert code == 0 and CLIMB in said, said


def test_no_way_above_when_the_folder_above_holds_no_results(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / "tests" / ".git").mkdir(parents=True)
    code, said = _run(capsys, monkeypatch, _folder(tmp_path / "tests", ("bot.py",)))
    assert code == 3 and "No answers yet?" in said and HINT not in said, said


@pytest.mark.parametrize("name", ["requirements.txt", "requirements-dev.txt", "package.json",
                                  "pyproject.toml", "setup.py", "judgekeeper.toml", ".git"])
def test_record_and_the_command_line_take_the_same_project_folders(tmp_path, monkeypatch, name):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    folder = tmp_path / "bot"
    (folder / "src").mkdir(parents=True)
    (folder / name).write_text("", encoding="utf-8")
    assert find.is_project(folder)
    assert find.project_folder(folder / "src") == folder
    assert recorder.project_root(folder / "src") == folder
