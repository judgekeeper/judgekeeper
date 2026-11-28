"""A run starts its project in the folder it is run in, unless a project is found above it
(docs/reference.md: "With none, it starts one in the folder you run it in"). A folder that
holds DeepEval's saved runs under a name of its own (an app's folder, X/ beside Y/) is that
folder's project: two such folders beside each other never share one .judgekeeper/. Only a
results folder named as one (logs/, results/, .deepeval/...) keeps its marks in the folder
above it, so they stay when its files are cleared.

In CI, a run that stops at a question it can't ask exits 3, as without CI: a pipeline never
passes on nothing."""

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


# Named from the folder above (`judgekeeper Y`): as if run in it ------------------------------

@pytest.fixture(params=[True, False], ids=["with .deepeval", "runs only"])
def parent(request, tmp_path, monkeypatch):
    """parent/Y with DeepEval's saved run right in it (an empty .deepeval/ beside it, or not);
    X/ comes later."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("CI", "1")
    top = tmp_path / "parent"
    deepeval_project(top / "Y", split(10, 10), name=RUN)
    if request.param:
        (top / "Y" / ".deepeval").mkdir()
    return top


def test_a_folder_named_from_its_parent_keeps_its_project_in_it(parent, monkeypatch, capsys):
    code, out, err = _in(monkeypatch, parent, capsys, "Y", "--yes")
    assert code in (0, 3), out + err
    assert (parent / "Y" / ".judgekeeper").is_dir(), out + err
    assert not (parent / ".judgekeeper").exists(), out + err
    assert not (parent / "judgekeeper.toml").exists(), out + err


def test_two_folders_named_from_their_parent_never_share_or_compare(parent, monkeypatch,
                                                                     capsys):
    """rc14: X's results were compared with Y's ("broke 10", exit 1), and judgekeeper.toml in
    parent/ flipped from file = "Y" to "X"."""
    _in(monkeypatch, parent, capsys, "Y", "--yes")
    kept = _kept(parent / "Y")
    # X's answers are other answers: every grade turned, so a comparison would say "broke"
    deepeval_project(parent / "X", [not v for v in split(10, 10)], name=RUN)
    code, out, err = _in(monkeypatch, parent, capsys, "X", "--yes")
    said = " ".join((out + err).split())
    assert code in (0, 3), said
    assert "broke" not in said and "made it worse" not in said, said
    assert (parent / "X" / ".judgekeeper").is_dir(), said
    assert kept and _kept(parent / "Y") == kept  # Y's own, untouched
    assert not (parent / ".judgekeeper").exists() and not (parent / "judgekeeper.toml").exists()


def test_naming_the_folder_and_running_in_it_use_one_project(parent, monkeypatch, capsys):
    _in(monkeypatch, parent, capsys, "Y", "--yes")
    kept = _kept(parent / "Y")
    code, out, err = _in(monkeypatch, parent / "Y", capsys, "--yes")
    assert code in (0, 3), out + err
    assert _kept(parent / "Y").keys() >= kept.keys()  # the same session, carried on
    assert not (parent / ".judgekeeper").exists(), out + err


@pytest.mark.parametrize("name", ["results", "logs"])
def test_a_results_folder_named_from_above_keeps_its_marks_above(tmp_path, monkeypatch,
                                                                 capsys, name):
    """As before: `judgekeeper app/results` from the folder that holds app/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / "top" / "app"
    deepeval_project(app / name, split(10, 10), name=RUN)
    _in(monkeypatch, app, capsys, name, "--yes")
    assert (app / ".judgekeeper").is_dir()
    assert not (app / name / ".judgekeeper").exists()


@pytest.mark.parametrize("named", [False, True], ids=["run in it", "named from above"])
def test_the_folder_deepeval_results_folder_names_keeps_its_marks_above(
        tmp_path, monkeypatch, capsys, named):
    """DEEPEVAL_RESULTS_FOLDER=evalout: a folder under any name that DeepEval saves its runs
    in is cleared with old runs, so its marks stay in the folder that holds it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / "app"
    deepeval_project(app / "evalout", split(10, 10), name=RUN)
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(app / "evalout"))
    if named:
        _in(monkeypatch, app, capsys, "evalout", "--yes")
    else:
        _in(monkeypatch, app / "evalout", capsys, "--yes")
    assert (app / ".judgekeeper").is_dir()
    assert not (app / "evalout" / ".judgekeeper").exists()


# In CI ---------------------------------------------------------------------------------------
# Yes/no questions: a results file whose items have two answers each (nested_runs_project)
# asks "Count each as its own answer?" and two more. A choice: from deep4/, a plain run asks
# which folder's DeepEval results to check.

def _asked(kind, tmp_path, monkeypatch):
    """The folder to run in and the words after `judgekeeper`, for `kind` of question."""
    if kind == "yes/no":
        from tests.start_projects import nested_runs_project

        nested_runs_project(tmp_path)
        return tmp_path, ("--metric", "Safe wording")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "deep4"
    for name, start in (("X", 0), ("Y", 100)):
        deepeval_project(top / name, split(10, 10), name=RUN, start=start)
    return top, ()


ASKED = {"yes/no": "judgekeeper needs your answer to these 3 questions",
         "choice": "DeepEval results in more than one folder"}


@pytest.mark.parametrize("kind", ASKED)
def test_in_ci_a_question_left_unanswered_exits_3(tmp_path, monkeypatch, capsys, kind):
    folder, argv = _asked(kind, tmp_path, monkeypatch)
    monkeypatch.setenv("CI", "true")
    code, out, err = _in(monkeypatch, folder, capsys, *argv)
    said = " ".join((out + err).split())
    assert ASKED[kind] in said, said
    assert code == 3, said
    assert not (folder / ".judgekeeper" / "judge.json").exists()  # nothing kept: asked again


@pytest.mark.parametrize("kind", ASKED)
def test_in_ci_a_question_left_unanswered_exits_as_without_ci(tmp_path, monkeypatch, capsys,
                                                              kind):
    folder, argv = _asked(kind, tmp_path, monkeypatch)
    without, out, err = _in(monkeypatch, folder, capsys, *argv)
    assert without == 3, out + err
    monkeypatch.setenv("CI", "true")
    assert _in(monkeypatch, folder, capsys, *argv)[0] == without
