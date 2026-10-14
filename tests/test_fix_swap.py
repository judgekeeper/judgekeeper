# ruff: noqa: F811 - the fixtures come from test_again_python_run and test_check
"""A new rule swapped into the person's own judge when it is asked again (`AgainOptions.rule`):
promptfoo's assertion value, a DeepEval GEval's evaluation steps (or its criteria), an Inspect
scorer's instructions, an MLflow Guidelines text or make_judge instructions. The swapped rule's
grading prompt is never compared with the saved one. A judge whose rule can't be swapped (an
MLflow judge that is registered or built in) can't be asked with a new rule.
No test calls an API: the tools are the fakes of test_again_run and tests/again_stubs.py.
"""

from __future__ import annotations

import sys

import pytest

from judgekeeper import again, judge_setup, keys, start_label
from judgekeeper.again import AgainOptions
from judgekeeper.start_label import Workspace
from tests.start_projects import project_promptfoo
from tests.test_again_python_run import (  # noqa: F401
    _mlflow_ws,
    _saved,
    deepeval_ws,
    inspect_ws,
    keyed,
)
from tests.test_again_run import FakePromptfoo
from tests.test_check import _marked

NEW = "The answer must solve the problem, be polite and never promise a refund."


class _Quiet:
    quiet = True
    yes = False

    def say(self, text: str = "") -> None:
        pass


def _ask(ws, rule: str | None = NEW, **kw):
    opts = AgainOptions(times=1, python=sys.executable, rule=rule, **kw)
    plan = again.make_plan(ws, opts, dry=True)
    assert plan.status != again.CANT, plan.why
    return plan, again.run_tool(ws, plan, _Quiet())


@pytest.fixture
def promptfoo_ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_promptfoo(tmp_path)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    ws = _marked(tmp_path)
    fake = FakePromptfoo(Workspace(tmp_path), version="0.124.1")
    monkeypatch.setattr(again, "run_process", fake)
    return ws, fake


def test_promptfoo_gets_the_new_rule_as_its_assertion(promptfoo_ws):
    ws, fake = promptfoo_ws
    _, fresh = _ask(ws)
    tests = fake.files_seen["tests"]
    assert tests and all(t["assert"][0]["value"] == NEW for t in tests)
    assert fresh.not_counted == {}  # the new grading prompt is not compared with the saved one
    assert len(fresh.verdicts) == len(tests)


def test_promptfoo_without_a_rule_asks_the_judge_as_it_was(promptfoo_ws):
    ws, fake = promptfoo_ws
    _ask(ws, rule=None)
    assert all(t["assert"][0]["value"] != NEW for t in fake.files_seen["tests"])


def test_deepeval_gets_the_new_steps(deepeval_ws, stubs):
    _ask(deepeval_ws, rule="1. Is it kind?\n2. Is it short?",
         fields="input,actual_output")
    measured = stubs("measure")
    assert measured and all(e["steps"] == ["Is it kind?", "Is it short?"] for e in measured)


def test_inspect_gets_the_new_instructions(inspect_ws, stubs):
    _ask(inspect_ws, rule="Grade it C when it is kind, else I.")
    (created, *_) = stubs("registry_create")
    assert created["options"]["instructions"] == "Grade it C when it is kind, else I."


def test_mlflow_guidelines_get_the_new_text(tmp_path, stubs, monkeypatch):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="guidelines",
                                           guidelines=1, text="Be kind.")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    _ask(ws, rule="Be kind and short.")
    assert stubs("construct")[0]["kwargs"]["guidelines"] == "Be kind and short."


def test_mlflow_make_judge_gets_the_new_instructions(tmp_path, stubs, monkeypatch):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, name="tone",
                                           instructions=True, text="Is {{ outputs }} kind?")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    _ask(ws, rule="Is {{ outputs }} kind and short?")
    assert stubs("make_judge")[0]["instructions"] == "Is {{ outputs }} kind and short?"


@pytest.mark.parametrize("info", [{"name": "tone", "scorer_name": "tone", "scorer_version": "2"},
                                  {"name": "safety"}])
def test_a_registered_or_built_in_mlflow_judge_cant_take_a_new_rule(tmp_path, stubs,
                                                                    monkeypatch, info):
    ws, _, by_input, verdicts = _mlflow_ws(tmp_path, monkeypatch, **info)
    if info.get("scorer_name"):
        monkeypatch.setenv("STUB_REGISTERED", "tone")
    stubs.plan(verdicts=verdicts, by_input=by_input)
    plan = again.make_plan(ws, AgainOptions(times=1, python=sys.executable, rule=NEW),
                           dry=True)
    assert plan.status == again.CANT
    assert "can't take a new rule" in plan.why


def test_the_marks_judge_is_untouched(promptfoo_ws):
    ws, _ = promptfoo_ws
    before = judge_setup.read(ws)
    _ask(ws)
    assert judge_setup.read(ws) == before
    assert start_label.Workspace(ws.root).data()["rule"] != NEW
