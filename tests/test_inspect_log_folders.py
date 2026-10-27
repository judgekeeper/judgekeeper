"""Inspect logs in the project folder and in logs/, after marking started: the folder (or a
log) named as PATH is a choice within the project that holds the marks, never a new project
inside logs/, and judgekeeper.toml keeps it after a yes, so plain commands stop asking."""

from __future__ import annotations

import os
import tomllib

import pytest

from tests.start_projects import inspect_project, split
from tests.test_front import assert_one_next_at_the_end, run


@pytest.fixture
def two_folders(tmp_path, monkeypatch, capsys):
    """A project marked on logs/, then a newer log saved in the project folder itself (an
    `inspect score … --output-file new.json` run from there)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'quiz'\n", encoding="utf-8")
    old = inspect_project(tmp_path, split(20, 16))
    _, out, _ = run(capsys, "--no-browser")
    assert (tmp_path / ".judgekeeper" / "start.json").is_file(), out
    new = inspect_project(tmp_path, split(22, 14), name="new.json")
    os.utime(old, (new.stat().st_mtime - 60,) * 2)
    return tmp_path


def _flat(out: str) -> str:
    return " ".join(out.split())


def test_the_choice_names_a_command_for_each_folder_that_picks_it(two_folders, capsys):
    code, out, _ = run(capsys, "--no-browser")
    assert code == 3 and "Inspect logs in more than one folder:" in out, out
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which Inspect logs to check (new.json, logs), then run "
        "`judgekeeper new.json --no-browser` or `judgekeeper logs --no-browser`.")


def test_a_logs_folder_named_is_read_in_the_project_that_holds_the_marks(two_folders, capsys):
    _, out, _ = run(capsys, "logs", "--no-browser")
    assert not (two_folders / "logs" / ".judgekeeper").exists(), out
    assert "for another project" not in out and "Step 1 of 5" not in out, out
    assert "Inspect logs in more than one folder" not in out, out
    assert assert_one_next_at_the_end(out).endswith(
        "or `judgekeeper logs --no-browser --yes` to say yes."), out
    run(capsys, "logs", "--no-browser", "--yes")
    saved = tomllib.loads((two_folders / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert saved["start"] == {"source": "inspect", "file": "logs"}
    _, out, _ = run(capsys, "--no-browser")
    assert "more than one folder" not in out and "File:" not in out, out
    _, out, _ = run(capsys, "check")
    assert "need a choice first" not in _flat(out), out


def test_a_log_in_the_project_folder_named_keeps_that_folder(two_folders, capsys):
    run(capsys, "new.json", "--no-browser")
    _, out, _ = run(capsys, "new.json", "--no-browser", "--yes")
    saved = tomllib.loads((two_folders / "judgekeeper.toml").read_text(encoding="utf-8"))
    assert saved["start"] == {"source": "inspect", "file": "."}, out
    _, out, _ = run(capsys, "--no-browser")
    assert "more than one folder" not in out, out


def test_a_folder_named_with_no_marks_above_is_still_its_own_eval(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    inspect_project(tmp_path, split(20, 16), name="evals/quiz/logs/2026-10-01_quiz.json")
    run(capsys, "evals/quiz/logs", "--no-browser")
    assert not (tmp_path / ".judgekeeper").exists()


def test_the_folder_kept_is_not_asked_about_again(two_folders, capsys):
    run(capsys, "logs", "--no-browser", "--yes")
    _, out, _ = run(capsys, "logs", "--no-browser")
    assert "judgekeeper.toml" not in out and "--yes" not in out, out
