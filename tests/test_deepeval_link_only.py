"""DeepEval, logged in to Confident AI, can save `.deepeval/.latest_test_run.json` holding only
`testRunLink`: the results are on Confident AI. That file is said in one plain line, the same
way wherever it is met; `.latest_run_full.json` beside it is read instead."""

from __future__ import annotations

import json
import os

import pytest

from tests.start_projects import deepeval_project, split
from tests.test_front import run

LINK = {"testRunLink": "https://app.confident-ai.com/project/p/evaluation/test-runs/r"}
SAID = (".deepeval/.latest_test_run.json only links to Confident AI; your results aren't saved "
        "on this computer.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _link_only(here, newer_than=None):
    path = here / ".deepeval" / ".latest_test_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(LINK), encoding="utf-8")
    if newer_than is not None:
        stamp = newer_than.stat().st_mtime + 60
        os.utime(path, (stamp, stamp))
    return path


@pytest.mark.parametrize("named", [False, True], ids=["found", "named"])
def test_a_link_only_file_is_said_in_plain_words(here, capsys, named):
    _link_only(here)
    code, out, err = run(capsys, *([".deepeval/.latest_test_run.json"] if named else []))
    assert SAID.removeprefix(".deepeval/") in err
    assert "testCases" not in out + err
    assert code == 2


def test_the_full_run_beside_it_is_read(here, capsys):
    full = deepeval_project(here, split(18, 18))
    _link_only(here, newer_than=full)
    code, out, err = run(capsys)
    assert "Eval tool:   DeepEval" in out and "36 answers from your app" in out
    assert "(read from .deepeval/.latest_run_full.json)" in out
    assert "Confident AI" not in out + err
    assert code == 0, out + err


def test_beside_saved_runs_it_is_no_different_run(here, capsys):
    saved = deepeval_project(here, split(18, 18), name="results/test_run_20261002_100000.json")
    _link_only(here, newer_than=saved)
    code, out, err = run(capsys)
    assert "holds a different run" not in out
    assert "results/test_run_20261002_100000.json" in out
    assert code == 0, out + err
