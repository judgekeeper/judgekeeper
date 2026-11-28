"""A run starts its project in the folder it is run in, unless a project is found above it
(docs/reference.md: "With none, it starts one in the folder you run it in"). A folder that
holds DeepEval's saved runs under a name of its own (an app's folder, X/ beside Y/) is that
folder's project: two such folders beside each other never share one .judgekeeper/. Only a
results folder named as one (logs/, results/, .deepeval/...) keeps its marks in the folder
above it, so they stay when its files are cleared."""

from __future__ import annotations

import pytest

from tests.start_projects import deepeval_project, split
from tests.test_front import run

RUN = "test_run_20261128_100000.json"


@pytest.fixture
def two_folders(tmp_path, monkeypatch):
    """deep4/X and deep4/Y, each with DeepEval's saved run right in it and an empty
    .deepeval/ (as DeepEval leaves in the folder it ran in), and nothing above."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "deep4"
    for name, start in (("X", 0), ("Y", 100)):
        deepeval_project(top / name, split(10, 10), name=RUN, start=start)
        (top / name / ".deepeval").mkdir()
    return top


def _in(monkeypatch, folder, capsys, *argv):
    monkeypatch.chdir(folder)
    return run(capsys, *argv, "--no-browser", "--port", "0")


def test_a_run_in_a_folder_of_saved_runs_keeps_its_project_there(two_folders, monkeypatch,
                                                                    capsys):
    x = two_folders / "X"
    code, out, err = _in(monkeypatch, x, capsys, "--yes")
    assert code in (0, 3), out + err
    assert (x / ".judgekeeper").is_dir(), out + err
    assert not (two_folders / "judgekeeper.toml").exists(), out + err
    assert not (two_folders / ".judgekeeper").exists(), out + err


def _kept(folder) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted((folder / ".judgekeeper").rglob("*")) if p.is_file()}


def test_two_folders_beside_each_other_never_share_a_project(two_folders, monkeypatch,
                                                              capsys):
    x, y = two_folders / "X", two_folders / "Y"
    _in(monkeypatch, x, capsys, "--yes")
    kept = _kept(x)
    code, out, err = _in(monkeypatch, y, capsys, "--yes")
    assert code in (0, 3), out + err
    assert (y / ".judgekeeper").is_dir(), out + err
    assert kept and _kept(x) == kept  # X's own, untouched
    assert not (two_folders / ".judgekeeper").exists(), out + err
    assert "setup changed" not in " ".join((out + err).split())


def test_a_folder_of_saved_runs_with_no_deepeval_folder_is_its_project_too(
        tmp_path, monkeypatch, capsys):
    """deep/DEx: the saved run only, under a name of its own."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    dex = tmp_path / "deep" / "DEx"
    deepeval_project(dex, split(10, 10), name=RUN)
    code, out, err = _in(monkeypatch, dex, capsys, "--yes")
    assert code in (0, 3), out + err
    assert (dex / ".judgekeeper").is_dir(), out + err
    assert not (tmp_path / "deep" / ".judgekeeper").exists(), out + err


@pytest.mark.parametrize("name", ["results", "logs", "runs"])
def test_a_results_folder_named_as_one_keeps_its_marks_above(tmp_path, monkeypatch, capsys,
                                                             name):
    """As before: app/results/ (DEEPEVAL_RESULTS_FOLDER=results) is cleared with old runs;
    its marks stay in app/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / "app"
    deepeval_project(app / name, split(10, 10), name=RUN)
    _in(monkeypatch, app / name, capsys, "--yes")
    assert (app / ".judgekeeper").is_dir()
    assert not (app / name / ".judgekeeper").exists()


def test_a_project_found_above_is_still_used(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / "app"
    (app / "pyproject.toml").parent.mkdir(parents=True)
    (app / "pyproject.toml").write_text("[project]\nname = 'app'\n", encoding="utf-8")
    deepeval_project(app / "X", split(10, 10), name=RUN)
    _in(monkeypatch, app / "X", capsys, "--yes")
    assert (app / ".judgekeeper").is_dir()
    assert not (app / "X" / ".judgekeeper").exists()
