"""When nothing is found where judgekeeper looks: it says where it looked and how deep, names
the results-like files it left out (deeper down, a link, in the folder above) with the command
that reads one, and looks in the project folder above (pyproject.toml, package.json or .git).
It never says to run the eval again when results-like files are there."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from judgekeeper.textio import quote_arg
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import run


@pytest.fixture
def here(tmp_path, monkeypatch):
    folder = tmp_path / "support-bot"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_a_table_too_deep_is_named_with_the_command_that_reads_it(here, capsys):
    table_project(here, split(16, 16), name="evals/2026/october/judged.csv")
    code, out, _ = run(capsys, "--no-browser")
    text = _flat(out)
    assert ("No eval results found where judgekeeper looks: 4 folders down from support-bot "
            "(tables: 1 folder down).") in text
    assert "evals/2026/october/judged.csv (3 folders down)" in out
    path = quote_arg(Path("evals/2026/october/judged.csv"))  # as the shell in use writes it
    assert f"Next: if that is your results, run `judgekeeper {path} --no-browser`." in text
    assert "run your eval" not in text
    assert code == 3


def test_results_five_folders_down_are_named_not_exported(here, capsys):
    promptfoo_project(here / "a" / "b" / "c" / "d" / "e", split(20, 12), config=False)
    (here / "promptfooconfig.yaml").write_text("description: x\n", encoding="utf-8")
    code, out, _ = run(capsys, "--no-browser")
    assert "a/b/c/d/e/results.json (5 folders down)" in out
    assert "promptfoo export" not in out and "run your eval" not in _flat(out)
    assert code == 3


def test_a_linked_results_file_is_named(here, tmp_path, capsys):
    outside = tmp_path / "elsewhere"
    promptfoo_project(outside, split(20, 12), config=False)
    try:
        (here / "results.json").symlink_to(outside / "results.json")
    except OSError:
        pytest.skip("symbolic links not allowed here")
    code, out, _ = run(capsys, "--no-browser")
    assert "results.json (a link: judgekeeper doesn't follow links)" in _flat(out)
    assert "run your eval" not in _flat(out)
    assert code == 3


def test_results_in_the_project_folder_above_are_read(here, capsys, monkeypatch):
    (here / "pyproject.toml").write_text("[project]\nname = 'bot'\n", encoding="utf-8")
    table_project(here, split(16, 16))
    (here / "src").mkdir()
    monkeypatch.chdir(here / "src")
    code, out, _ = run(capsys, "--no-browser")
    assert ("No eval results in src. Reading the project folder above it (support-bot)."
            in _flat(out))
    assert "32 answers from your app" in out
    assert (here / ".judgekeeper").is_dir() and not (here / "src" / ".judgekeeper").exists()
    assert code == 0, out


def test_a_results_file_in_the_folder_above_is_named(tmp_path, capsys, monkeypatch):
    top = tmp_path / "work"
    promptfoo_project(top, split(20, 12), config=False)
    (top / "notes").mkdir()
    monkeypatch.chdir(top / "notes")
    code, out, _ = run(capsys, "--no-browser")
    assert "../results.json (in the folder above)" in out
    assert f"run `judgekeeper {quote_arg(Path('../results.json'))} --no-browser`" in _flat(out)
    assert code == 3


def test_nothing_results_like_says_where_it_looked(here, capsys):
    (here / "README.md").write_text("hi\n", encoding="utf-8")
    code, out, _ = run(capsys, "--no-browser")
    text = _flat(out)
    assert ("No eval results found in this folder (support-bot). judgekeeper looked 4 folders "
            "down (tables: 1 folder down).") in text
    assert "`judgekeeper PATH --no-browser`" in text
    assert code == 3


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links")
def test_files_that_are_not_results_like_are_not_named(here, capsys):
    (here / "deep" / "a" / "b" / "c" / "d").mkdir(parents=True)
    (here / "deep" / "a" / "b" / "c" / "d" / "notes.txt").write_text("x", encoding="utf-8")
    code, out, _ = run(capsys, "--no-browser")
    assert "notes.txt" not in out and "left out" not in out
    assert code == 3
