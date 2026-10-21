"""Inspect AI's model_graded_qa(partial_credit=True) gives P as well as C and I. Before asking
whether P counts as Pass or Fail, judgekeeper says what it found: the eval tool and its logs,
and the judge."""

from __future__ import annotations

import json

import pytest

from tests.start_projects import inspect_data
from tests.test_front import assert_one_next_at_the_end, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_what_was_found_comes_before_the_question(here, capsys):
    path = here / "logs" / "2026-10-02_support.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(inspect_data([True] * 16 + [False] * 16 + ["P"] * 4)),
                    encoding="utf-8")
    code, out, _ = run(capsys)
    found = out.index("Eval tool:   Inspect AI")
    assert "File:        logs/2026-10-02_support.json" in out
    judge = out.index("Judge:       anthropic/claude-haiku-4-5")
    asked = out.index("Inspect gave partial credit (P) on 4 answers.")
    assert found < judge < asked
    assert "--label-map P=pass" in assert_one_next_at_the_end(out)
    assert code == 3
