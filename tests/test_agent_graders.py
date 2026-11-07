"""regrade.yaml carries a plain model call, never a coding agent.

A grader named in a results file can be a local coding agent that promptfoo starts in the
project folder. The results file may come from someone else, and the person runs regrade.yaml
with their keys set, so `fix` writes no file for one and prints the steps instead.
"""

from __future__ import annotations

import pytest

from judgekeeper import fix


@pytest.mark.parametrize("grader", [
    "openai:codex", "openai:codex-sdk", "openai:codex-app-server", "openai:codex-desktop",
    "openai:codex-security", "openai:agents:x", "anthropic:claude-agent-sdk",
    "anthropic:claude-code"])
def test_a_coding_agent_is_no_plain_grader(grader):
    assert not fix._plain_grader(grader.split(":")[0], grader)


@pytest.mark.parametrize("grader", [
    "openai:gpt-5", "openai:chat:gpt-4o", "openai:responses:gpt-5",
    "anthropic:claude-sonnet-5-5", "anthropic:messages:claude-opus-5-5"])
def test_a_model_is_still_a_plain_grader(grader):
    assert fix._plain_grader(grader.split(":")[0], grader)


@pytest.mark.parametrize("kind", ["agent-rubric", "not-agent-rubric", "trajectory:goal-success"])
def test_an_agent_assertion_gets_no_regrade_file(monkeypatch, kind):
    monkeypatch.setattr(fix, "_promptfoo_grader", lambda ws, data: (kind, None, {}))
    data = {"fingerprint": {"provider": "openai", "model": "openai:gpt-5"}, "rule": "Be polite."}
    assert fix._regrade_yaml(None, data) is None
