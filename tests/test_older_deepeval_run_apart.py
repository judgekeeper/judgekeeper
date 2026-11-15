"""DeepEval's older run, named beside the newest one read: once answers are marked, an older
run with other questions is another eval, so the line gives the step that works for it (a
folder of its own), not a command that stops."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from tests.start_projects import _write_json, deepeval_data, split
from tests.test_folder_matrix import _marked
from tests.test_front import flat, run

PAGE = ("--no-browser", "--port", "0")
NEWER = "deepeval-results/test_run_20261101_100000.json"
OLDER = ".deepeval/.latest_run_full.json"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    return tmp_path


def _two_runs(root, start: int) -> None:
    """The newest run in the results folder and an older one in DeepEval's hidden copy, on
    the questions from `start` (0: the same questions)."""
    _write_json(root / NEWER, deepeval_data(split(30, 30)))
    older = _write_json(root / OLDER, deepeval_data(split(32, 28), start=start))
    then = datetime(2026, 10, 1, 12).timestamp()  # before the newest run's day, in its name
    os.utime(older, (then, then))


def _marked_run_again(root, capsys) -> str:
    code, out, err = run(capsys, *PAGE)
    run(capsys, "--stop")
    assert code == 0, out + err
    _marked(root, 60)
    code, out, err = run(capsys, *PAGE)
    run(capsys, "--stop")
    assert code == 0, out + err
    return flat(out)


def test_an_older_run_with_other_questions_is_named_with_a_folder_of_its_own(here, capsys):
    _two_runs(here, start=100)
    said = _marked_run_again(here, capsys)
    assert f"Read DeepEval's newest run, {NEWER}" in said, said
    assert (f"{OLDER} holds an older run" in said and "with other questions. To check it, put "
            "it in a folder of its own and run `judgekeeper --no-browser` there." in said), said
    assert f"run `judgekeeper {OLDER}`" not in said, said


def test_an_older_run_of_the_same_questions_keeps_its_command_and_it_works(here, capsys):
    _two_runs(here, start=0)
    said = _marked_run_again(here, capsys)
    assert f"{OLDER} holds an older run" in said, said
    assert f"To check it, run `judgekeeper {OLDER}`." in said, said
    code, out, err = run(capsys, OLDER, *PAGE)
    run(capsys, "--stop")
    assert code == 0, out + err
