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
        "Next: ask the person which DeepEval results to check (app2/.deepeval, "
        f"app1/.deepeval), then run `judgekeeper {app2}` or `judgekeeper {app1}`.")
    assert code == 3


def test_the_folder_named_is_read_alone_in_its_own_project(two_apps, capsys):
    code, out, _ = run(capsys, "app1/.deepeval")
    assert "Found your eval tool: DeepEval (.deepeval/.latest_run_full.json, 20 answers)" in out
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
    assert "app1/.deepeval/.latest_run_full.json, 20 answers" in out


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
