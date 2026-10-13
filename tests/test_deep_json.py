"""A JSON results file nested deeper than Python's JSON reader goes is said in one plain line
(exit 2), never as a RecursionError."""

from __future__ import annotations

import pytest

from tests.test_front import run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


DEEP = 100_000  # deeper than Python's JSON reader goes before 3.14


@pytest.mark.parametrize("name, head", [
    ("results.json", '{"evalId": "x", "results": {"results": '),
    (".deepeval/.latest_run_full.json", '{"testCases": '),
    ("logs/2026-10-02_support.json", '{"eval": {}, "status": "success", "samples": '),
], ids=["promptfoo", "deepeval", "inspect"])
@pytest.mark.parametrize("given", [False, True], ids=["found", "named"])
def test_json_nested_too_deep_is_said_in_plain_words(here, capsys, name, head, given):
    path = here / name
    path.parent.mkdir(parents=True, exist_ok=True)
    closing = "}" * (head.count("{") - head.count("}"))
    path.write_text(head + "[" * DEEP + "]" * DEEP + closing, encoding="utf-8")
    code, out, err = run(capsys, *([name] if given else []))
    assert code == 2, out + err
    assert "RecursionError" not in out + err
    assert "isn't valid JSON that judgekeeper can read." in err
    assert path.name in err
