"""A session started on a file named by a link, and a --tool run that finds nothing: the
projects a top folder names include it, the line after --stop carries on the file it was
started with, and no Next line repeats the command that just failed."""

from __future__ import annotations

import re
import shlex

import pytest

from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import next_lines
from tests.test_services_in_one_repo import _run, repo  # noqa: F401


def _link(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    assert link.is_file(), link


@pytest.fixture
def linked(repo, tmp_path_factory):  # noqa: F811
    """symlink-out/: pyproject.toml and results.csv, a link to a file outside the project."""
    away = tmp_path_factory.mktemp("away")
    table_project(away, split(24, 16), name="shared-results.csv", tag="s")
    folder = repo / "symlink-out"
    folder.mkdir()
    (folder / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    _link(folder / "results.csv", away / "shared-results.csv")
    return folder


def _continue(said: str) -> list[str]:
    return shlex.split(re.search(r"Next: run `([^`]+)` when you want to continue\.", said)[1])


def test_stop_carries_on_the_file_the_session_was_started_with(linked, capsys, monkeypatch):
    code, said = _run(capsys, monkeypatch, linked, "results.csv")
    assert code == 0 and "File: " in said, said
    code, said = _run(capsys, monkeypatch, linked, "--stop")
    assert code == 0 and "Closed the marking page." in said, said
    command = _continue(said)
    assert command[:2] == ["judgekeeper", "results.csv"], said
    code, said = _run(capsys, monkeypatch, linked, *command[1:])  # as printed: it reads it
    main(["--stop"])
    assert code == 0 and "No eval results found" not in said, said


def test_the_top_folder_names_a_project_whose_results_file_is_a_link(linked, capsys,
                                                                       monkeypatch):
    other = linked.parent / "bot"
    other.mkdir()
    (other / "pyproject.toml").write_text("[project]\nname = 'bot'\n", encoding="utf-8")
    table_project(other, split(24, 16), tag="b")
    assert _run(capsys, monkeypatch, linked, "results.csv")[0] == 0
    _run(capsys, monkeypatch, linked, "--stop")
    code, said = _run(capsys, monkeypatch, linked.parent)
    assert code == 3, said
    assert ("These results belong to the projects in bot/ and symlink-out/." in said
            and "Next: run `judgekeeper` in bot/ or symlink-out/." in said), said
    assert not (linked.parent / ".judgekeeper").exists(), said


def test_a_tool_found_nowhere_never_says_to_run_the_same_command(tmp_path, capsys,
                                                                 monkeypatch):
    table_project(tmp_path, split(24, 16))
    monkeypatch.chdir(tmp_path)
    code = main(["--tool", "promptfoo", "--no-browser", "--port", "0"])
    out = capsys.readouterr()
    said = " ".join((out.out + out.err).split())
    assert code == 2 and "No saved promptfoo results found in this folder." in said, said
    assert all("--tool promptfoo" not in line for line in next_lines(out.out + out.err)), said
    assert said.endswith("Next: run `judgekeeper --no-browser --port 0` to read the results "
                         "found here."), said


def test_a_tool_found_only_in_a_project_below_names_it(repo, capsys, monkeypatch):  # noqa: F811
    """services/ (its own session for loose/) and pf-bot/ (promptfoo results, its own session):
    --tool promptfoo from services/ reads nothing below, and says where they are."""
    services = repo / "services"
    table_project(services / "loose", split(24, 16), tag="l")
    assert _run(capsys, monkeypatch, services)[0] == 0
    main(["--stop"])
    bot = services / "pf-bot"
    promptfoo_project(bot, split(24, 16))
    (bot / "app.py").write_text("", encoding="utf-8")
    assert _run(capsys, monkeypatch, bot)[0] == 0  # its own session, as T6 had it
    main(["--stop"])
    code, said = _run(capsys, monkeypatch, services, "--tool", "promptfoo")
    assert code == 2 and "No saved promptfoo results found in this folder." in said, said
    assert said.endswith("Next: run `judgekeeper pf-bot --tool promptfoo --port 0 --no-browser` "
                         "to check the promptfoo results in pf-bot/."), said
    code, said = _run(capsys, monkeypatch, services, "pf-bot", "--tool", "promptfoo")
    main(["--stop"])
    assert code == 0 and "pf-bot/results.json has LLM-as-a-judge grades" in said, said


def test_a_tool_found_nowhere_says_where_to_run_it(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = main(["--tool", "promptfoo", "--no-browser"])
    out = capsys.readouterr()
    said = " ".join((out.out + out.err).split())
    assert code == 2 and "No saved promptfoo results found in this folder." in said, said
    assert said.endswith("Next: run `judgekeeper --tool promptfoo --no-browser` in the folder "
                         "that holds your promptfoo results."), said


def test_mark_stop_carries_on_mark_with_the_file(linked, capsys, monkeypatch):
    assert _run(capsys, monkeypatch, linked, "results.csv")[0] == 0  # the first run: Find
    _run(capsys, monkeypatch, linked, "--stop")
    assert _run(capsys, monkeypatch, linked, "mark", "results.csv")[0] == 0
    code, said = _run(capsys, monkeypatch, linked, "mark", "--stop")
    assert code == 0 and _continue(said)[:3] == ["judgekeeper", "mark", "results.csv"], said
