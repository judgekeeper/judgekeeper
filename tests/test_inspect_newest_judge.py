"""Inspect AI: a project often has logs that hold no judge decisions (a run with --no-score,
say) beside the ones that do. The newest log that holds judge decisions is used; when the
newest has none, one line says so and names the log used. Only when no log has a judge is it
an error, which says how to check one log."""

from __future__ import annotations

import json

import pytest

from tests.start_projects import inspect_data, split
from tests.test_front import run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _log(here, name, created, judged=True, n=(18, 18)):
    data = inspect_data(split(*n))
    data["eval"]["created"] = created
    if not judged:  # run with `inspect eval --no-score`: no scorer, no scores
        data["eval"]["scorers"] = []
        for s in data["samples"]:
            s.pop("scores", None)
    path = here / "logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_newest_log_with_a_judge_is_used(here, capsys):
    _log(here, "2026-10-01_support.json", "2026-10-01T10:00:00+00:00")
    _log(here, "2026-10-02_exact.json", "2026-10-02T10:00:00+00:00", judged=False)
    code, out, _ = run(capsys)
    assert ("Your newest Inspect log, logs/2026-10-02_exact.json, holds no judge decisions. "
            "Using logs/2026-10-01_support.json, the newest that does.") in out
    assert "Eval tool:   Inspect AI" in out and "36 answers from your app" in out
    assert "(read from logs/2026-10-01_support.json)" in out
    assert code == 0, out


def test_no_log_with_a_judge_says_how_to_check_one(here, capsys):
    _log(here, "2026-10-01_exact.json", "2026-10-01T10:00:00+00:00", judged=False)
    _log(here, "2026-10-02_exact.json", "2026-10-02T10:00:00+00:00", judged=False)
    code, _, err = run(capsys)
    assert "none of your 2 Inspect logs holds decisions from an LLM judge." in err
    assert "To check one log, run judgekeeper with its path." in err
    assert code == 2
