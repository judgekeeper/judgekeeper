"""What the readers give asking a judge again: promptfoo's grader, grading prompt and cached
replies, and where MLflow keeps the judge's prompt."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from judgekeeper.readers import read_promptfoo
from judgekeeper.readers.promptfoo import grading_template
from judgekeeper.records import LLM
from tests.conftest import FIXTURES

REAL = FIXTURES / "promptfoo" / "real" / "results.json"
RESULTS = FIXTURES / "promptfoo" / "results.json"


def _write(tmp_path, data, name="results.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _judged(records, name=None):
    return [r for r in records if r.annotator_kind == LLM and (name is None or r.name == name)]


# promptfoo: a grader set with --grader ----------------------------------------------------

def test_a_grader_object_without_an_id_is_a_set_grader_not_the_default(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    grader = {"modelName": "gpt-4.1-mini", "config": {"temperature": 0}, "mcpClient": None}
    data["config"]["defaultTest"]["options"]["provider"] = grader
    for row in data["results"]["results"]:
        row["testCase"].setdefault("options", {})["provider"] = grader
    records = read_promptfoo(_write(tmp_path, data))
    judged = _judged(records, "helpfulness")
    assert {r.evaluator.get("model") for r in judged} == {"gpt-4.1-mini"}
    assert all("provider" not in r.evaluator for r in judged)
    warnings = records.per_metric["helpfulness"]["warnings"]
    assert not any("default grader" in w for w in warnings)
    assert any("--grader" in w and "only the model's name" in w for w in warnings)


CONFIG_GRADER = FIXTURES / "promptfoo" / "default-test-grader-0.124.0.json"
HAIKU = "anthropic:messages:claude-haiku-4-5-20251001"


def test_a_grader_set_in_default_test_is_read_from_the_config(tmp_path):
    # promptfoo 0.124 saves the grader in each testCase as the provider it made, with no id
    records = read_promptfoo(CONFIG_GRADER)
    judged = _judged(records, "friendly-hours-next-step")
    assert len(judged) == 6
    assert {(r.evaluator.get("provider"), r.evaluator.get("model"),
             r.evaluator.get("temperature")) for r in judged} == {("anthropic", HAIKU, 0)}
    warnings = records.per_metric.get("friendly-hours-next-step", {}).get("warnings", [])
    assert not any("--grader" in w or "default grader" in w for w in warnings)


def test_a_config_grader_of_another_model_leaves_the_set_grader(tmp_path):
    data = json.loads(CONFIG_GRADER.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"]["provider"] = "openai:gpt-4.1-mini"
    records = read_promptfoo(_write(tmp_path, data))
    judged = _judged(records, "friendly-hours-next-step")
    assert {r.evaluator.get("model") for r in judged} == {"claude-haiku-4-5-20251001"}
    assert all("provider" not in r.evaluator for r in judged)
    assert any("--grader" in w for w in records.per_metric["friendly-hours-next-step"]["warnings"])


# Providers as promptfoo 0.124 makes them (JSON.stringify of each class), for one model name
MODEL = "llama-3.3-70b"
MADE_OPENAI = {"modelName": MODEL, "config": {}, "mcpClient": None,
               "initializationPromise": {}, "loadedFunctionCallbacks": {}, "label": ""}
MADE_TOGETHER = {**MADE_OPENAI, "config": {"apiBaseUrl": "https://api.together.xyz/v1",
                                           "apiKeyEnvar": "TOGETHER_API_KEY", "passthrough": {}}}
MADE_OLLAMA = {"modelName": MODEL, "config": {}, "label": ""}
MADE_ANTHROPIC = {"modelName": MODEL, "config": {}, "env": {}, "apiKey": "[REDACTED]",
                  "anthropic": {}, "label": "", "mcpClient": None}
MADE_VERTEX = {**MADE_OPENAI, "config": {"vertexai": True}, "isVertexMode": True}
OWN_KEY = {"apiKeyEnvar": "MY_KEY"}
OTHER_PROVIDER = [
    (f"openai:chat:{MODEL}", MADE_ANTHROPIC), (f"togetherai:{MODEL}", MADE_OPENAI),
    (f"openai:{MODEL}", MADE_TOGETHER), (f"openai:chat:{MODEL}", MADE_OLLAMA),
    (f"ollama:chat:{MODEL}", MADE_OPENAI), (f"google:{MODEL}", MADE_VERTEX)]
SAME_PROVIDER = [
    (f"openai:chat:{MODEL}", MADE_OPENAI), (f"togetherai:{MODEL}", MADE_TOGETHER),
    (f"ollama:chat:{MODEL}", MADE_OLLAMA), (f"vertex:{MODEL}", MADE_VERTEX),
    (f"anthropic:messages:{MODEL}", MADE_ANTHROPIC),
    ({"id": f"openai:chat:{MODEL}", "config": OWN_KEY}, {**MADE_OPENAI, "config": OWN_KEY})]


def _graded_by(tmp_path, configured, made):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"]["provider"] = configured
    for row in data["results"]["results"]:
        row["testCase"].setdefault("options", {})["provider"] = made
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"].pop("provider", None)
    return _judged(read_promptfoo(_write(tmp_path, data)), "helpfulness")


@pytest.mark.parametrize("configured, made", OTHER_PROVIDER)
def test_a_config_grader_of_another_provider_leaves_the_set_grader(tmp_path, configured, made):
    judged = _graded_by(tmp_path, configured, made)
    assert {(r.evaluator.get("provider"), r.evaluator.get("model")) for r in judged} == {
        (None, MODEL)}


@pytest.mark.parametrize("configured, made", SAME_PROVIDER)
def test_a_config_grader_of_the_same_provider_names_the_set_grader(tmp_path, configured, made):
    pid = configured["id"] if isinstance(configured, dict) else configured
    judged = _graded_by(tmp_path, configured, made)
    assert {(r.evaluator.get("provider"), r.evaluator.get("model")) for r in judged} == {
        (pid.split(":")[0], pid)}


def test_the_same_config_grader_saved_two_ways_is_no_model_change(tmp_path):
    from judgekeeper import judge_setup, start

    first, again = tmp_path / "first", tmp_path / "again"
    data = json.loads(CONFIG_GRADER.read_text(encoding="utf-8"))
    for root in (first, again):
        root.mkdir()
        (root / "promptfooconfig.yaml").write_text("description: Kettle & Leaf tea shop helper\n",
                                                   encoding="utf-8")
    _write(first, data)
    grader = {"id": HAIKU, "config": {"temperature": 0}}  # a regrade.yaml with {id, config}
    data["config"]["defaultTest"]["options"]["provider"] = grader
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"] = grader
    _write(again, data)
    old, new = (judge_setup.of(start.find_judge(root)) for root in (first, again))
    assert old["models"] == new["models"] == [HAIKU]
    assert judge_setup.changes(old, new) == []


def test_default_test_provider_is_the_last_grader_fallback(tmp_path):
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"].pop("provider", None)
    data["config"]["defaultTest"]["provider"] = "anthropic:messages:claude-haiku-4-5"
    for row in data["results"]["results"]:
        (row.get("testCase") or {}).get("options", {}).pop("provider", None)
        for c in row["gradingResult"]["componentResults"]:
            c["assertion"].pop("provider", None)
    records = read_promptfoo(_write(tmp_path, data))
    judged = _judged(records, "helpfulness")
    assert {r.evaluator.get("model") for r in judged} == {"anthropic:messages:claude-haiku-4-5"}
    assert "helpfulness" not in records.per_metric or not any(
        "default grader" in w for w in records.per_metric["helpfulness"].get("warnings", []))


# promptfoo: the grading prompt --------------------------------------------------------------

def test_the_saved_grading_prompt_is_hashed_as_its_template(tmp_path):
    records = read_promptfoo(REAL)
    judged = _judged(records)
    hashes = {r.evaluator.get("prompt_hash") for r in judged}
    assert len(hashes) == 1 and None not in hashes
    data = json.loads(REAL.read_text(encoding="utf-8"))
    row = data["results"]["results"][0]
    comp = next(c for c in row["gradingResult"]["componentResults"]
                if "renderedGradingPrompt" in (c.get("metadata") or {}))
    template = grading_template(comp["metadata"]["renderedGradingPrompt"],
                                row["response"]["output"], row["vars"])
    assert "{{output}}" in template and row["response"]["output"] not in template
    assert hashes == {hashlib.sha256(template.encode()).hexdigest()}
    # the rule shown to the person stays the rubric
    assert all(r.evaluator["prompt"].startswith("The answer is helpful") for r in judged)


def test_a_changed_grading_template_changes_the_hash(tmp_path):
    data = json.loads(REAL.read_text(encoding="utf-8"))
    before = {r.evaluator["prompt_hash"] for r in _judged(read_promptfoo(REAL))}
    changed = copy.deepcopy(data)
    for row in changed["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            m = c.get("metadata") or {}
            if "renderedGradingPrompt" in m:
                m["renderedGradingPrompt"] = m["renderedGradingPrompt"].replace(
                    "You are grading output", "You grade output")
    after = {r.evaluator["prompt_hash"] for r in _judged(read_promptfoo(_write(tmp_path,
                                                                               changed)))}
    assert len(after) == 1 and after != before


def test_templates_that_differ_by_row_keep_the_rubric_hash(tmp_path):
    data = json.loads(REAL.read_text(encoding="utf-8"))
    rows = data["results"]["results"]
    for c in rows[0]["gradingResult"]["componentResults"]:
        m = c.get("metadata") or {}
        if "renderedGradingPrompt" in m:
            m["renderedGradingPrompt"] = "something else entirely"
    records = read_promptfoo(_write(tmp_path, data))
    judged = _judged(records)
    assert len({r.evaluator.get("prompt_hash") for r in judged}) == 1
    assert all("prompt_hash" not in r.evaluator for r in judged)


# promptfoo: cached replies ------------------------------------------------------------------

def test_cached_replies_are_warned_about(tmp_path):
    data = json.loads(REAL.read_text(encoding="utf-8"))
    for row in data["results"]["results"][:3]:
        for c in row["gradingResult"]["componentResults"]:
            c.setdefault("metadata", {})["cachedResponse"] = True
    records = read_promptfoo(_write(tmp_path, data))
    assert any("3 of these grades were cached by promptfoo" in w for w in records.warnings)
    assert not any("cache" in w for w in read_promptfoo(REAL).warnings)


# MLflow: the docstring on where the judge's prompt lives ---------------------------------

def test_the_mlflow_reader_does_not_claim_the_prompt_is_in_a_scorer_trace():
    from judgekeeper.readers import mlflow_store

    text = mlflow_store.__doc__ + "".join(mlflow_store.read_mlflow.__doc__ or "")
    assert "lives in the scorer's own trace" not in text
    assert "scorer tracing is off by default" in text
