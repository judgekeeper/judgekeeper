"""A first run that stopped before marking leaves only judge.json in its .judgekeeper/. A
folder below it with results of its own keeps its own run, as before 1.2.0; an empty folder
below it still reads the folder above. Files found beside the ones read are named from the
folder the command runs in. No page opens: the page is served in a thread (conftest's
pages)."""

from __future__ import annotations

import os

from tests.start_projects import split, table_project
from tests.test_services_in_one_repo import _run

JUDGE_ONLY = [".gitignore", "judge.json"]


def _kept(folder):
    return sorted(p.name for p in (folder / ".judgekeeper").iterdir())


def _stopped(tmp_path, capsys, monkeypatch):
    """repo/a/: 3 graded answers, too few: the run stops and saves judge.json only."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    a = tmp_path / "repo" / "a"
    table_project(a, split(2, 1), tag="a")
    code, said = _run(capsys, monkeypatch, a)
    assert code == 3 and "mark these 3 now" in said, said
    assert _kept(a) == JUDGE_ONLY, said
    return a


def test_a_folder_with_results_of_its_own_keeps_its_run_from_a_judge_setup_above(
        tmp_path, capsys, monkeypatch):
    a = _stopped(tmp_path, capsys, monkeypatch)
    sub = a / "sub"
    table_project(sub, split(16, 16), tag="sub")
    code, said = _run(capsys, monkeypatch, sub)
    assert code == 0, said
    assert "Answers: 32 answers" in said, said
    assert "Also found" not in said, said
    assert (sub / ".judgekeeper" / "start.json").is_file(), said
    assert _kept(a) == JUDGE_ONLY, said


def test_the_folder_above_still_marks_its_own_answers_after_one_below_ran(
        tmp_path, capsys, monkeypatch):
    """The Next line of the first run (`judgekeeper mark`, "these 3") marks a/'s 3 answers,
    never the 32 of the folder below."""
    a = _stopped(tmp_path, capsys, monkeypatch)
    table_project(a / "sub", split(16, 16), tag="sub")
    assert _run(capsys, monkeypatch, a / "sub")[0] == 0
    code, said = _run(capsys, monkeypatch, a, "mark")
    assert code == 3, said  # too few for a result: said so
    assert "looks like another eval" not in said, said
    assert "Only 3 answers are left to mark" in said, said


def test_an_empty_folder_below_a_judge_setup_still_reads_the_folder_above(
        tmp_path, capsys, monkeypatch):
    a = _stopped(tmp_path, capsys, monkeypatch)
    (a / "e").mkdir()
    said = _run(capsys, monkeypatch, a / "e")[1]
    assert "File: ../results.csv" in said, said
    assert not (a / "e" / ".judgekeeper").exists(), said


def test_files_found_beside_the_ones_read_are_named_from_the_folder_run_in(
        tmp_path, capsys, monkeypatch):
    """p/ (a project) holds results.csv (newest), older.csv (the same questions) and
    other.csv (other questions); a run in the empty p/e/ reads p/ and names both from e/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    p = tmp_path / "repo" / "p"
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    p.mkdir()
    (p / "pyproject.toml").write_text("[project]\nname = 'p'\n", encoding="utf-8")
    for name, tag in (("older.csv", "r"), ("other.csv", "other")):
        table_project(p, split(16, 16), tag=tag, name=name)
        os.utime(p / name, (1e9, 1e9))
    table_project(p, split(16, 16), tag="r")
    (p / "e").mkdir()
    code, said = _run(capsys, monkeypatch, p / "e")
    assert code == 0 and "File: ../results.csv" in said, said
    assert "Also found ../older.csv. To check it, run `judgekeeper ../older.csv" in said, said
    assert "Also found ../other.csv, with other questions." in said, said
