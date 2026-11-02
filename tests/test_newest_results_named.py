"""When plain `judgekeeper` reads another results file than the last run did (a newer one
saved in the folder), one line names it."""

from __future__ import annotations

import os

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import split, table_project

NEWEST = "Reading new-rule.csv, the newest results here."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(capsys) -> str:
    main(["--no-browser", "--port", "0"])
    main(["--stop"])
    return " ".join(capsys.readouterr().out.split())


def _newer(path):
    st = path.stat()
    os.utime(path, (st.st_atime + 60, st.st_mtime + 60))


@pytest.mark.parametrize("marked", [0, 10])
def test_a_newer_results_file_is_named(here, capsys, marked):
    table_project(here, split(40, 40))
    first = _run(capsys)
    assert "Reading" not in first
    session = StartSession(Workspace(here))
    for item in session.items[:marked]:
        session.update({"id": item["id"], "label": session.groups[item["id"]], "seconds": 4})
    _newer(table_project(here, split(30, 50), name="new-rule.csv"))
    assert NEWEST in _run(capsys)


def test_the_same_file_again_is_not_named(here, capsys):
    table_project(here, split(40, 40))
    _run(capsys)
    assert "Reading" not in _run(capsys)
