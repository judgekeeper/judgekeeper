"""`judgekeeper steps` again when an agent-as-a-judge is named by a key: its earlier numbers are
its own, matched by the name it has, never by the "[REDACTED]" result.json shows, so they are
never shown as another agent-as-a-judge's, and the key itself is never written. Synthetic data
only; no test calls an AI."""

from __future__ import annotations

import pytest

from tests.test_steps import reviewer_first
from tests.test_steps_key_names import FAKE_KEY, said
from tests.test_steps_marks import marked_project
from tests.test_steps_recheck import (
    BETTER,
    better,
    model_lines,
    since,
    write_judges,
    write_picks,
)

OTHER_KEY = "sk-ant-api03-" + "Z" * 80


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_key_judge_numbers_are_never_another_judge_numbers(here):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    model_lines(here, "picks.jsonl")
    write_judges(here, "two.jsonl", **{FAKE_KEY: reviewer_first, "judge-B": lambda i: 0})
    model_lines(here, "two.jsonl")
    lines = model_lines(here, "two.jsonl", "judge-B")
    assert since(lines) == [], lines
    assert not any("(then" in x for x in lines), lines


def test_a_judge_beside_a_key_judge_is_compared_with_its_own_numbers(here):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    model_lines(here, "picks.jsonl")
    write_judges(here, "two.jsonl", **{FAKE_KEY: lambda i: 0, "judge-B": reviewer_first})
    model_lines(here, "two.jsonl")
    write_judges(here, "two.jsonl", **{FAKE_KEY: lambda i: 0, "judge-B": better})
    lines = model_lines(here, "two.jsonl", "judge-B")
    at = lines.index(BETTER[0])
    assert lines[at:at + len(BETTER)] == BETTER, lines


def test_a_key_judge_checked_again_is_its_own_then(here):
    """rc14: '(then "[REDACTED]")' on every run though nothing changed."""
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    model_lines(here, "picks.jsonl")
    again = model_lines(here, "picks.jsonl")
    assert not any("(then" in x for x in again), again
    write_picks(here, "picks.jsonl", better, model=FAKE_KEY)
    lines = model_lines(here, "picks.jsonl")
    at = lines.index(BETTER[0])
    assert lines[at:at + len(BETTER)] == BETTER, lines


def test_two_key_judges_are_told_apart(here):
    marked_project(here)
    write_judges(here, "two.jsonl", **{FAKE_KEY: reviewer_first, OTHER_KEY: lambda i: 0})
    model_lines(here, "two.jsonl")
    write_judges(here, "two.jsonl", **{FAKE_KEY: better, OTHER_KEY: lambda i: 0})
    lines = model_lines(here, "two.jsonl")
    caught = [x for x in lines if x.startswith("  Runs you say went wrong, caught:")]
    assert caught[0] == "  Runs you say went wrong, caught: 75% (15 of 20) -> 90% (18 of 20).", \
        lines
    assert not any("(then" in x for x in lines), lines


def test_the_key_is_never_written(here, capsys):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    said(capsys, "runs.jsonl", "--reviewer", "picks.jsonl")
    write_judges(here, "two.jsonl", **{FAKE_KEY: better, "judge-B": lambda i: 0})
    code, out = said(capsys, "runs.jsonl", "--reviewer", "two.jsonl", "--model", "judge-B")
    assert FAKE_KEY not in out and "QQQQQQQQ" not in out, out
    assert code == 0, out
    for path in (here / ".judgekeeper").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert FAKE_KEY not in text and "QQQQQQQQ" not in text, path
