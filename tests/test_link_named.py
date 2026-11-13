"""A results file named by a link, its target outside the project: every command a line
prints names it as it was typed, so it reads the same file again; never a placeholder."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.start_projects import split, table_project
from tests.test_services_in_one_repo import _run, repo  # noqa: F401


def _link(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    assert link.is_file(), link


@pytest.fixture
def outside(repo, tmp_path_factory):  # noqa: F811
    """services/sym-out/results.csv, a link to a file outside the home folder."""
    away = tmp_path_factory.mktemp("away")
    table_project(away, split(12, 6), name="outside-results.csv", tag="o")
    folder = repo / "services" / "sym-out"
    folder.mkdir()
    _link(folder / "results.csv", away / "outside-results.csv")
    return folder


@pytest.fixture
def inside(repo):  # noqa: F811
    """services/sym-bot/results.csv, a link to ../my support bot/results.csv."""
    table_project(repo / "services" / "my support bot", split(12, 6), tag="m")
    folder = repo / "services" / "sym-bot"
    folder.mkdir()
    # A Path, so Windows gets backslashes: it cannot follow a relative link with "/".
    _link(folder / "results.csv", Path("..", "my support bot", "results.csv"))
    return folder


@pytest.mark.parametrize("layout", ["outside", "inside"])
def test_a_link_named_is_named_as_typed_in_every_command(request, capsys, monkeypatch,
                                                          layout):
    folder = request.getfixturevalue(layout)
    code, said = _run(capsys, monkeypatch, folder, "results.csv")
    assert code == 3, said  # 18 answers: too few
    assert "PATH" not in said, said
    assert ("Next: mark these 18 now with `judgekeeper mark results.csv --port 0 "
            "--no-browser`.") in said, said
    assert "run `judgekeeper results.csv --port 0 --no-browser` again." in said, said
    code, said = _run(capsys, monkeypatch, folder, "mark", "results.csv")
    assert "Step 2 of 5: Mark" in said and "PATH" not in said, said
