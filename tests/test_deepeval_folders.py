"""DeepEval results in more than one folder (two apps, each with its own `.deepeval/`) are
separate evals: never merged into one pool. judgekeeper asks which, as it asks which judge;
the answer is the folder's path, and judgekeeper.toml keeps it after a yes. Its project is
the folder `.deepeval/` is in."""

from __future__ import annotations

import copy
import json
import os
import tomllib
from pathlib import Path

import pytest

from judgekeeper.textio import quote_arg
from tests.start_projects import deepeval_data, deepeval_project, split
from tests.test_front import assert_one_next_at_the_end, run, terminal  # noqa: F401


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def two_apps(here):
    old = deepeval_project(here / "app1", split(10, 10))
    new = deepeval_project(here / "app2", split(9, 9), start=100)
    os.utime(old, (new.stat().st_mtime - 60,) * 2)
    return here


def test_two_deepeval_folders_are_asked_about_not_merged(two_apps, capsys):
    code, out, _ = run(capsys)
    assert "DeepEval results in more than one folder:" in out
    assert "older file" not in out
    app1, app2 = (quote_arg(Path(f"{a}/.deepeval")) for a in ("app1", "app2"))
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which DeepEval results to check (app2/.deepeval, "
        f"app1/.deepeval), then run `judgekeeper {app2}` or `judgekeeper {app1}`.")
    assert code == 3


def test_the_folder_named_is_read_alone_in_its_own_project(two_apps, capsys):
    code, out, _ = run(capsys, "app1/.deepeval")
    assert "Eval tool:   DeepEval" in out and "20 answers, each graded by your judge" in out
    assert "(read from .deepeval/.latest_run_full.json)" in out
    assert (two_apps / "app1" / ".judgekeeper" / "judge.json").is_file()
    assert not (two_apps / "app1" / ".deepeval" / ".judgekeeper").exists()
    assert code == 3  # 20 answers: fewer than a first result needs


def test_at_a_terminal_the_folder_is_asked_and_kept(two_apps, capsys, terminal):  # noqa: F811
    answers, _ = terminal
    answers += ["2", ""]  # app1/.deepeval; save? yes
    run(capsys)
    saved = tomllib.loads((two_apps / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["source"] == "deepeval" and saved["file"] == "app1/.deepeval"
    _, out, _ = run(capsys)  # asked once
    assert "more than one folder" not in out
    assert "(read from app1/.deepeval/.latest_run_full.json)" in out
    assert "20 answers, each graded by your judge" in out


def test_a_file_with_several_metrics_asks_which(here, capsys):
    data = deepeval_data(split(5, 5))
    for case in data["testCases"]:
        other = copy.deepcopy(case["metricsData"][0])
        other["name"] = "Relevancy [GEval]"
        case["metricsData"].append(other)
    (here / ".deepeval").mkdir()
    (here / ".deepeval" / ".latest_run_full.json").write_text(json.dumps(data),
                                                              encoding="utf-8")
    code, out, _ = run(capsys)
    assert "These results hold more than one judge:" in out
    assert "--metric NAME" in assert_one_next_at_the_end(out)
    assert code == 3


def test_a_folder_is_listed_with_its_run_time_never_the_files_time(two_apps, capsys):
    code, out, _ = run(capsys)  # .latest_run_full.json: no time inside, so no date
    assert "  app1/.deepeval/ (app1/.deepeval/.latest_run_full.json)\n" in out
    assert "saved" not in out
    assert code == 3


def test_a_saved_run_is_listed_with_the_time_in_its_name(here, capsys):
    for app, stamp in (("app1", "20261001_090000"), ("app2", "20261002_100000")):
        deepeval_project(here / app, split(9, 9), name=f"results/test_run_{stamp}.json")
    code, out, _ = run(capsys)
    assert ("  app2/results/ (app2/results/test_run_20261002_100000.json, saved "
            "2026-10-02 10:00)\n") in out
    assert code == 3


def test_every_folder_only_linking_to_confident_ai_is_said_not_asked(here, capsys):
    for app in ("app1", "app2"):
        path = here / app / ".deepeval" / ".latest_test_run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"testRunLink": "https://app.confident-ai.com/r"}),
                        encoding="utf-8")
    code, out, err = run(capsys)
    text = " ".join((out + err).split())
    assert "more than one folder" not in text
    assert "Each DeepEval results folder here (app" in text
    assert ("/.deepeval) only links to Confident AI; your results aren't saved on this "
            "computer.") in text
    assert "Next: set DEEPEVAL_RESULTS_FOLDER=results and run your eval once" in text
    assert code == 2
