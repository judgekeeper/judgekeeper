"""A results file read, and a newer file beside it under other column names: named, never
read in its place, with the command that reads it (a table with grades) or what to rename (a
table of answers with none). The shape of a folder where the results file is the oldest of
three: input/output/verdict, then question/response/grade, then prompt/completion/label."""

from __future__ import annotations

import csv
import os
import re
import shlex
import time

import pytest

from judgekeeper import project
from tests.start_projects import answer, question
from tests.test_front import flat, run

PAGE = ("--no-browser", "--port", "0")


def _table(path, columns, graded: bool, n: int = 20, tag: str = "", age: int = 0):
    """A CSV of `n` answers under `columns` (a grade last when `graded`), `age` minutes old."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for i in range(n):
            w.writerow([question(i, tag), answer(i, tag)] + (["pass" if i % 3 else "fail"]
                                                           if graded else []))
    then = time.time() - age * 60
    os.utime(path, (then, then))
    return path


def _say(capsys, monkeypatch, folder, *argv):
    monkeypatch.chdir(folder)
    project.forget()
    code, out, err = run(capsys, *argv, *PAGE)
    return code, flat(out + err)


def _two2(tmp_path):
    """results.csv (the oldest), results-v3.csv, results-v4.csv (the newest)."""
    _table(tmp_path / "results.csv", ["input", "output", "verdict"], True, tag="a", age=30)
    _table(tmp_path / "results-v3.csv", ["question", "response", "grade"], True, 25, "b", 20)
    _table(tmp_path / "results-v4.csv", ["prompt", "completion", "label"], True, 25, "c", 10)
    return tmp_path


def _commands(said: str) -> list[str]:
    return re.findall(r"`(judgekeeper [^`]+)`", said)


def test_the_results_file_is_read_and_the_newer_files_with_other_columns_are_named(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = _two2(tmp_path / "two2")
    said = _say(capsys, monkeypatch, folder)[1]
    assert "File: results.csv" in said and "Answers: 20 answers" in said, said
    for name, columns in (("results-v3.csv", "question, response and grade"),
                          ("results-v4.csv", "prompt, completion and label")):
        assert (f"{name} is newer than results.csv but has other column names ({columns}), "
                "so it was not read.") in said, said
    commands = [c for c in _commands(said) if "results-v" in c]
    assert sorted(c.split()[1] for c in commands) == ["results-v3.csv", "results-v4.csv"], said


@pytest.mark.parametrize("name", ["results-v3.csv", "results-v4.csv"])
def test_the_command_it_prints_reads_the_file_it_names(tmp_path, capsys, monkeypatch, name):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = _two2(tmp_path / "two2")
    said = _say(capsys, monkeypatch, folder)[1]
    (command,) = [c for c in _commands(said) if c.split()[1] == name]
    again = _say(capsys, monkeypatch, folder, *shlex.split(command)[1:])[1]
    assert f"File: {name}" in again and "Answers: 25 answers" in again, again


def test_a_table_of_answers_with_no_grade_is_named_with_what_to_rename(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = tmp_path / "proj"
    _table(folder / "results.csv", ["input", "output", "verdict"], True, tag="a", age=30)
    _table(folder / "answers-v5.csv", ["question", "response"], False, 20, "e", 5)
    said = _say(capsys, monkeypatch, folder)[1]
    assert "File: results.csv" in said, said
    assert ("answers-v5.csv is newer than results.csv but has answers under other column "
            "names (question and response), so it was not read.") in said, said
    assert ("rename the question column in answers-v5.csv to input and the answer column to "
            "output, then run `judgekeeper answers-v5.csv") in said, said


@pytest.mark.parametrize("case", ["older", "below", "one-column", "no-answers"])
def test_it_stays_quiet_when_the_file_is_not_one_the_person_would_expect_read(
        tmp_path, capsys, monkeypatch, case):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = tmp_path / "proj"
    _table(folder / "results.csv", ["input", "output", "verdict"], True, tag="a", age=30)
    if case == "older":  # older than the file read
        _table(folder / "results-old.csv", ["prompt", "completion", "label"], True, 20, "b", 90)
    elif case == "below":  # not in the folder of the file read
        _table(folder / "more" / "results-v4.csv", ["prompt", "completion", "label"], True,
               20, "c", 5)
    elif case == "one-column":  # a question and no answer
        _table(folder / "notes.csv", ["question", "topic", "grade"], True, 20, "d", 5)
    else:  # no question and no answer
        _table(folder / "scores.csv", ["id", "score", "label"], True, 20, "d", 5)
    said = _say(capsys, monkeypatch, folder)[1]
    assert "File: results.csv" in said, said
    assert "so it was not read" not in said and "other column names" not in said, said


def test_a_file_given_by_name_is_read_as_asked_with_no_note(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    folder = _two2(tmp_path / "two2")
    said = _say(capsys, monkeypatch, folder, "results.csv")[1]
    assert "File: results.csv" in said, said
    assert "other column names" not in said, said
