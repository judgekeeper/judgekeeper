"""Counts read as people say them: "1 answer", "2 answers", "mark this one now". Every module
uses one helper, textio.plural; outputs with a count of 1 are scanned for "1 answers"-style
slips."""

from __future__ import annotations

import copy
import json
import re

import pytest

from judgekeeper import (
    check,
    front,
    judge_check,
    records,
    start,
    start_fix,
    start_label,
    start_review,
    textio,
)
from tests.start_projects import inspect_data, promptfoo_data, split
from tests.test_front import run

WORDS = ("answers", "files", "older files", "marks", "lines", "logs", "judges", "questions",
         "verdicts", "repeats", "labels", "tests", "calls", "samples", "human labels")
SLIP = re.compile(rf"\b1 ({'|'.join(WORDS)})\b|\bthese 1\b")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_plural():
    assert textio.plural(1, "answer") == "1 answer"
    assert textio.plural(0, "answer") == "0 answers"
    assert textio.plural(2, "repeat") == "2 repeats"
    assert textio.plural(1, "was", "were") == "1 was"
    assert textio.plural(3, "copy", "copies") == "3 copies"


def test_one_helper_everywhere():
    helpers = [check._n, front._n, judge_check._n, records._plural, start._plural,
               start_fix._plural, start_label._plural, start_review._plural]
    assert all(h is textio.plural for h in helpers)


def test_one_answer(here, capsys):
    _write(here / "results.json", promptfoo_data(split(1, 0)))
    _, out, _ = run(capsys)
    assert "You have 1 answer with a clear grade." in out
    assert "mark this one now" in out
    assert not SLIP.search(out), out


def test_a_judge_with_one_answer(here, capsys):
    data = promptfoo_data(split(18, 18))
    row = data["results"]["results"][0]
    tone = copy.deepcopy(row["gradingResult"]["componentResults"][0])
    tone["assertion"]["metric"] = "tone"
    row["gradingResult"]["componentResults"].append(tone)
    _write(here / "results.json", data)
    _, out, _ = run(capsys)
    assert "tone (1 answer)" in out
    assert not SLIP.search(out), out


def test_partial_credit_on_one_answer(here, capsys):
    _write(here / "logs" / "2026-10-02_support.json", inspect_data([True] * 18 + [False] * 17
                                                                   + ["P"]))
    _, out, _ = run(capsys)
    assert "Inspect gave partial credit (P) on 1 answer." in out
    assert not SLIP.search(out), out
