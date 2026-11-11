"""Answers with no grades in a folder of their own below a project, or beside another project:
the folder with its own .judgekeeper/ is its own project. A run there or in the folder above
never loops between the two, and the folder above keeps reading its own results."""

from __future__ import annotations

import json

import pytest

from judgekeeper import project
from tests.test_answers_without_grades import mark
from tests.test_front import flat, run


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder for the walk to stop at, with the projects below it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def _answers(folder, word: str, n: int = 12) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{"input": f"{word} question {i}?", "output": f"{word} answer {i}."} for i in range(n)]
    (folder / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                          encoding="utf-8")


def _run(capsys, monkeypatch, folder) -> str:
    monkeypatch.chdir(folder)
    project.forget()
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    return flat(out)


def test_answers_in_their_own_subfolder_run_twice_there_and_above(home, capsys, monkeypatch,
                                                                     pages):
    main = home / "bot"
    (main / ".git").mkdir(parents=True)
    _answers(main, "Main")
    _answers(main / "json-run", "Json")
    for _ in range(2):
        said = _run(capsys, monkeypatch, main / "json-run")
        assert "results.jsonl" in said
    assert (main / "json-run" / ".judgekeeper").is_dir()
    for _ in range(2):
        said = _run(capsys, monkeypatch, main)
        assert "json-run/results.jsonl" not in said
        assert "Reading results.jsonl" in said or "results.jsonl has no" in said, said


def test_sibling_projects_with_marks_never_loop(home, capsys, monkeypatch, pages):
    top = home / "tests"
    (top / ".git").mkdir(parents=True)
    for name in ("one", "two"):
        _answers(top / name, name.title())
        _run(capsys, monkeypatch, top / name)
        mark(top / name, ["pass"] * 6 + ["fail"] * 4)
    for name in ("one", "two"):
        said = _run(capsys, monkeypatch, top / name)
        assert "../" not in said
    monkeypatch.chdir(top)  # its own answers are none: the question prompt, no crash
    project.forget()
    code, out, err = run(capsys, "--no-browser")
    assert code == 3 and "No answers yet?" in flat(out), out + err
