"""An agent-as-a-judge's name comes from the data: a picks file's `model` or a Label Studio
prediction's `model_version`. A key pasted there is never said in the terminal, as it is
never shown on the page or written to result.json. Synthetic data and a fake key only."""

from __future__ import annotations

import json

import pytest

from tests.test_steps import project, reviewer_first, run, save
from tests.test_steps_marks import marked_project
from tests.test_steps_recheck import better, write_picks

FAKE_KEY = "sk-ant-api03-" + "Q" * 80
REDACTED = "[REDACTED]"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")  # no page and no browser
    return tmp_path


def said(capsys, *argv) -> tuple[int, str]:
    code, out, err = run(capsys, "steps", *argv)
    return code, out + err


def test_a_key_as_the_picks_model_is_never_said(here, capsys):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    code, out = said(capsys, "runs.jsonl", "--reviewer", "picks.jsonl")
    assert code == 0, out
    assert FAKE_KEY not in out and "QQQQQQQQ" not in out, out
    assert f'Agent-as-a-judge "{REDACTED}" against your marks' in out, out


def test_a_key_as_the_model_version_in_an_export_is_never_said(here, capsys):
    save(here, project(model=FAKE_KEY))
    code, out = said(capsys, "export.json")
    assert code == 0, out
    assert FAKE_KEY not in out and "QQQQQQQQ" not in out, out
    assert f'Agent-as-a-judge "{REDACTED}" against the people marking' in out, out


def test_a_key_as_the_earlier_name_is_never_said(here, capsys):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    said(capsys, "runs.jsonl", "--reviewer", "picks.jsonl")
    write_picks(here, "new.jsonl", better, model="reviewer-b")
    code, out = said(capsys, "runs.jsonl", "--reviewer", "new.jsonl")
    assert code == 0, out
    assert FAKE_KEY not in out and "QQQQQQQQ" not in out, out
    assert f'Since the last check (then "{REDACTED}"), on the same marks:' in out, out


def test_a_key_in_the_names_a_wrong_model_lists_is_never_said(here, capsys):
    marked_project(here)
    write_picks(here, "picks.jsonl", reviewer_first, model=FAKE_KEY)
    code, out = said(capsys, "runs.jsonl", "--reviewer", "picks.jsonl", "--model", "other")
    assert code == 2, out
    assert FAKE_KEY not in out and "QQQQQQQQ" not in out, out


def test_two_judges_one_named_by_a_key_never_say_it(here, capsys):
    marked_project(here)
    lines = [json.dumps({"id": f"r{i}", "first_wrong_step": reviewer_first(i), "model": m})
             for i in range(40) for m in (FAKE_KEY, "reviewer-b")]
    (here / "picks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for extra in ([], ["--model", "reviewer-b"], ["--model", FAKE_KEY]):
        _, out = said(capsys, "runs.jsonl", "--reviewer", "picks.jsonl", *extra)
        assert FAKE_KEY not in out and "QQQQQQQQ" not in out, (extra, out)
