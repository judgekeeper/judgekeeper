"""The judge's setup: everything about the judge that can change its verdicts (the eval tool
and its version, the kind of judge, its models and vote, the rule, the grading prompt, the
temperature, the pass mark, the endpoint), read from the results, saved in
.judgekeeper/judge.json, and compared in words."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import front, judge_setup, start, start_label
from judgekeeper.readers import read_promptfoo
from judgekeeper.records import CODE, LLM
from tests.conftest import FIXTURES
from tests.start_projects import (
    deepeval_project,
    inspect_data,
    promptfoo_data,
    split,
)


def _quiet(line=""):
    pass


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _promptfoo(root: Path, version="0.124.1", **kwargs) -> Path:
    data = promptfoo_data(split(20, 16), **kwargs)
    if version:
        data["metadata"]["promptfooVersion"] = version
    return _write(root / "results.json", data)


def _setup(root: Path, **kwargs) -> dict:
    return judge_setup.of(start.find_judge(root, **kwargs))


def _component(data, i=None):
    rows = data["results"]["results"]
    return [r["gradingResult"]["componentResults"][0] for r in (rows if i is None else [rows[i]])]


# What each reader fills ---------------------------------------------------------------------

def test_a_promptfoo_setup(tmp_path):
    _promptfoo(tmp_path)
    setup = _setup(tmp_path)
    assert setup["tool"] == "promptfoo"
    assert (setup["tool_version"], setup["version_from"]) == ("0.124.1", "results")
    assert setup["kind"] == "one call"
    assert setup["models"] == ["openai:gpt-4.1-mini"]
    assert setup["vote"] is None and setup["agent"] is None
    assert setup["rule_hash"].startswith("sha256:")
    assert setup["temperature"] == 0
    assert setup["pass_mark"] is None and setup["endpoint"] == "unknown"  # as the fingerprint
    assert "prompt_hash" in setup


def test_promptfoo_reads_not_llm_rubric_as_a_judge(tmp_path):
    data = promptfoo_data(split(20, 16))
    for c in _component(data):
        c["assertion"]["type"] = "not-llm-rubric"
    _write(tmp_path / "results.json", data)
    found = start.find_judge(tmp_path)
    assert found.metric == "not-llm-rubric"
    assert (found.pool.n_pass, found.pool.n_fail) == (20, 16)  # saved already flipped
    assert judge_setup.of(found)["kind"] == "one call"


def test_promptfoo_reads_an_agent_rubric_as_an_agent_judge(tmp_path):
    data = promptfoo_data(split(20, 16))
    for c in _component(data):
        c["assertion"]["type"] = "agent-rubric"
        c["metadata"] = {"agentProvider": "anthropic:claude-agent-sdk"}
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"] = {"id": "anthropic:claude-agent-sdk",
                                                  "config": {}}
    _write(tmp_path / "results.json", data)
    setup = _setup(tmp_path)
    assert setup["kind"] == "agent"
    assert setup["agent"] == {"runtime": "anthropic:claude-agent-sdk", "can_write": "unknown",
                              "looks_at": "unknown"}


def test_an_agent_judge_set_read_only_cannot_write(tmp_path):
    data = promptfoo_data(split(20, 16))
    for c in _component(data):
        c["assertion"]["type"] = "not-agent-rubric"
    for row in data["results"]["results"]:
        row["testCase"]["options"]["provider"] = {
            "id": "openai:codex-sdk", "config": {"sandbox_mode": "read-only",
                                                 "working_dir": "./app"}}
    _write(tmp_path / "results.json", data)
    agent = _setup(tmp_path)["agent"]
    assert agent == {"runtime": "openai:codex-sdk", "can_write": False, "looks_at": "files"}


def test_trajectory_goal_success_is_read_as_a_judge(tmp_path):
    data = promptfoo_data(split(20, 16))
    for c in _component(data):
        c["assertion"]["type"] = "trajectory:goal-success"
    _write(tmp_path / "results.json", data)
    found = start.find_judge(tmp_path)
    assert found.metric == "trajectory:goal-success"
    assert len(found.pool.answers) == 36


def test_assert_set_as_promptfoo_0_124_1_saves_it():
    """The set has no assertion key (its marker is metadata.assertionSet) and its children
    appear twice: nested, then flat. Each child is read once."""
    records = read_promptfoo(FIXTURES / "promptfoo" / "assert-set-0.124.1.json")
    judged = [r for r in records if r.annotator_kind == LLM]
    assert [(r.name, r.label) for r in judged] == [("polite", "pass"), ("polite", "fail")]
    code = [r.name for r in records if r.annotator_kind == CODE]
    assert code == ["contains", "contains"]


def test_an_older_assert_set_is_still_flattened(tmp_path):
    data = json.loads((FIXTURES / "promptfoo" / "assert-set-0.124.1.json").read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        comps = row["gradingResult"]["componentResults"]
        aset = comps[0]
        aset["assertion"] = {"type": "assert-set"}
        del aset["metadata"]
        row["gradingResult"]["componentResults"] = [aset]  # the children only nested
    records = read_promptfoo(_write(tmp_path / "r.json", data))
    assert [r.name for r in records if r.annotator_kind == LLM] == ["polite", "polite"]


def _panel(log, models, reducer="majority"):
    log["eval"]["model_roles"] = {}
    log["eval"]["scorers"][0]["options"] = {
        "model": [{"model": m, "config": {}} for m in models], "reducer": reducer}
    return log


def test_an_inspect_panel_is_its_models_and_its_vote(tmp_path):
    log = _panel(inspect_data(split(20, 16)), ["openai/gpt-4.1-mini", "anthropic/claude-haiku-4-5",
                                                "google/gemini-2.5-flash"])
    log["eval"]["packages"] = {"inspect_ai": "0.3.278"}
    _write(tmp_path / "logs" / "a.json", log)
    setup = _setup(tmp_path)
    assert setup["kind"] == "panel"
    assert setup["models"] == ["openai/gpt-4.1-mini", "anthropic/claude-haiku-4-5",
                               "google/gemini-2.5-flash"]
    assert setup["vote"] == "majority"
    assert (setup["tool_version"], setup["version_from"]) == ("0.3.278", "results")


def test_an_inspect_grader_role_is_one_model(tmp_path):
    _write(tmp_path / "logs" / "a.json", inspect_data(split(20, 16)))
    setup = _setup(tmp_path, label_map="P=pass")
    assert setup["kind"] == "one call"
    assert setup["models"] == ["anthropic/claude-haiku-4-5"]


def test_deepeval_without_a_lockfile_has_no_version(tmp_path):
    deepeval_project(tmp_path, split(20, 16))
    setup = _setup(tmp_path)
    assert (setup["tool_version"], setup["version_from"]) == (None, None)


@pytest.mark.parametrize("name, text", [
    ("uv.lock", 'version = 1\n\n[[package]]\nname = "deepeval"\nversion = "4.2.8"\n'),
    ("poetry.lock", '[[package]]\nname = "DeepEval"\nversion = "4.2.8"\n'),
    ("requirements.txt", "anthropic\ndeepeval==4.2.8  # pinned\n"),
    ("requirements-dev.txt", "deepeval == 4.2.8\n"),
])
def test_deepeval_version_from_the_lockfile(tmp_path, name, text):
    deepeval_project(tmp_path, split(20, 16))
    (tmp_path / name).write_text(text, encoding="utf-8")
    setup = _setup(tmp_path)
    assert (setup["tool_version"], setup["version_from"]) == ("4.2.8", "lockfile")


def test_a_range_is_not_a_pin(tmp_path):
    deepeval_project(tmp_path, split(20, 16))
    (tmp_path / "requirements.txt").write_text("deepeval>=4.2\n", encoding="utf-8")
    assert _setup(tmp_path)["tool_version"] is None


def test_promptfoo_version_from_package_lock_when_the_results_lack_it(tmp_path):
    _promptfoo(tmp_path, version=None)
    _write(tmp_path / "package-lock.json", {"lockfileVersion": 3, "packages": {
        "node_modules/promptfoo": {"version": "0.124.1"}}})
    setup = _setup(tmp_path)
    assert (setup["tool_version"], setup["version_from"]) == ("0.124.1", "lockfile")


def _mlflow_found(root, rule="Is the answer polite? {{ outputs }}"):
    store = root / "mlflow.db"
    store.write_bytes(b"")
    return SimpleNamespace(
        root=root, tool="mlflow", results=[SimpleNamespace(path=store, rel="mlflow.db")],
        used=["run-1"], metric="polite", rule=rule, models=["openai:/gpt-4.1-mini"],
        pass_mark=None, fingerprint={"model": "openai:/gpt-4.1-mini"})


def test_mlflow_without_and_with_a_lockfile(tmp_path):
    assert judge_setup.of(_mlflow_found(tmp_path))["tool_version"] is None
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "mlflow"\nversion = "3.17.0"\n',
                                      encoding="utf-8")
    setup = judge_setup.of(_mlflow_found(tmp_path))
    assert (setup["tool_version"], setup["version_from"]) == ("3.17.0", "lockfile")
    assert setup["kind"] == "one call"


def test_an_mlflow_trace_judge_is_an_agent_that_reads_the_trace(tmp_path):
    setup = judge_setup.of(_mlflow_found(tmp_path, rule="Did it finish the task? {{ trace }}"))
    assert setup["kind"] == "agent"
    assert setup["agent"] == {"runtime": "mlflow", "can_write": False, "looks_at": "trace"}


# judge.json ---------------------------------------------------------------------------------

def test_judge_json_holds_the_setup_and_its_hash(tmp_path):
    _promptfoo(tmp_path)
    found = start.find_judge(tmp_path)
    ws = start_label.Workspace(tmp_path)
    assert judge_setup.save(ws, judge_setup.of(found)) is True
    data = json.loads((ws.dir / "judge.json").read_text(encoding="utf-8"))
    assert set(data) == {"setup", "setup_hash", "first_seen", "judgekeeper_version"}
    assert data["setup"] == judge_setup.of(found)
    assert data["setup_hash"] == judge_setup.hash_of(data["setup"])
    assert data["first_seen"].endswith("Z")


def test_judge_json_is_not_rewritten_for_the_same_judge(tmp_path):
    _promptfoo(tmp_path)
    ws = start_label.Workspace(tmp_path)
    judge_setup.save(ws, _setup(tmp_path))
    before = (ws.dir / "judge.json").read_bytes()
    _promptfoo(tmp_path, created="2026-10-11T08:00:00Z")  # another run, the same judge
    assert judge_setup.save(ws, _setup(tmp_path)) is False
    assert (ws.dir / "judge.json").read_bytes() == before


def test_two_runs_of_judgekeeper_leave_judge_json_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _promptfoo(tmp_path)
    front.run()
    before = (tmp_path / ".judgekeeper" / "judge.json").read_bytes()
    _promptfoo(tmp_path, created="2026-10-11T08:00:00Z")
    front.run()
    assert (tmp_path / ".judgekeeper" / "judge.json").read_bytes() == before


def test_while_marking_judge_json_keeps_the_judge_of_the_marks(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _promptfoo(tmp_path)
    front.run()  # marking starts
    _promptfoo(tmp_path, model="anthropic:claude-haiku-4-5")
    front.run()
    saved = json.loads((tmp_path / ".judgekeeper" / "judge.json").read_text(encoding="utf-8"))
    assert saved["setup"]["models"] == ["openai:gpt-4.1-mini"]


def test_an_older_judge_json_is_read_from_the_marks(tmp_path):
    """judge.json from 1.0.0b1 has no setup: the judge of the marks stands in (what start.json
    keeps), and only what it knows is compared."""
    _promptfoo(tmp_path)
    found = start.find_judge(tmp_path)
    ws = start_label.prepare(found, say=_quiet)
    (ws.dir / "judge.json").write_text(json.dumps({"tool": "promptfoo", "model": "x"}),
                                       encoding="utf-8")
    old = judge_setup.read(ws)["setup"]
    assert old["models"] == ["openai:gpt-4.1-mini"] and "tool_version" not in old
    assert judge_setup.changes(old, judge_setup.of(found)) == []


# What changed, in words -----------------------------------------------------------------------

BASE = {"tool": "promptfoo", "tool_version": "0.124.1", "version_from": "results",
        "kind": "one call", "models": ["openai:gpt-4o-mini"], "vote": None, "agent": None,
        "rule_hash": "sha256:a", "prompt_hash": "sha256:p", "temperature": 0,
        "pass_mark": None, "endpoint": None}


def _with(**changes):
    return {**copy.deepcopy(BASE), **changes}


@pytest.mark.parametrize("changes, words", [
    ({"models": ["anthropic:claude-haiku-4-5"]},
     ["model openai:gpt-4o-mini -> anthropic:claude-haiku-4-5"]),
    ({"tool_version": "0.125.0"}, ["promptfoo 0.124.1 -> 0.125.0"]),
    ({"pass_mark": {"mark": 0.7, "op": ">="}}, ["pass mark not set -> 0.7"]),
    ({"rule_hash": "sha256:b"}, ["rule changed"]),
    ({"prompt_hash": "sha256:q"}, ["grading prompt changed"]),
    ({"temperature": 0.7}, ["temperature 0 -> 0.7"]),
    ({"endpoint": "gateway.example.com"}, ["endpoint default -> gateway.example.com"]),
    ({"kind": "panel", "vote": "majority",
      "models": ["openai:gpt-4o-mini", "anthropic:claude-haiku-4-5", "google:gemini-2.5-flash"]},
     ["now a panel of 3 (majority)"]),
    ({"models": [], "rule_hash": "sha256:b"}, ["model openai:gpt-4o-mini -> not written down",
                                                "rule changed"]),
])
def test_what_changed_in_words(changes, words):
    assert judge_setup.changes(BASE, _with(**changes)) == words


def test_pass_marks_in_words():
    old = _with(pass_mark={"mark": 0.5, "op": ">="})
    assert judge_setup.changes(old, _with(pass_mark={"mark": 0.7, "op": ">="})) == [
        "pass mark 0.5 -> 0.7"]


def test_where_the_version_was_read_is_not_a_change():
    assert judge_setup.changes(BASE, _with(version_from="lockfile")) == []
    assert judge_setup.hash_of(BASE) == judge_setup.hash_of(_with(version_from="lockfile"))


def test_the_same_setup_has_the_same_hash():
    assert judge_setup.hash_of(BASE) == judge_setup.hash_of(copy.deepcopy(BASE))
    assert judge_setup.hash_of(BASE) != judge_setup.hash_of(_with(temperature=1))


def test_only_the_eval_tool_changed():
    assert judge_setup.tool_only(BASE, _with(tool_version="0.125.0"))
    assert judge_setup.tool_only(BASE, _with(tool_version="0.125.0", prompt_hash="sha256:q"))
    assert not judge_setup.tool_only(BASE, _with(tool_version="0.125.0", rule_hash="sha256:b"))
    assert not judge_setup.tool_only(BASE, _with(prompt_hash="sha256:q"))


# The two new free checks ----------------------------------------------------------------------

def test_promptfoo_with_no_grader_written_down_is_said(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _promptfoo(tmp_path, model=None)
    front.run()
    out = capsys.readouterr().out
    block = out[out.index("Checked first (no AI call):"):]
    assert ("Your judge's model isn't written in your config. promptfoo picks it from whichever "
            "API key is set, so it can change without any file changing. Write it in your "
            "config (`defaultTest.options.provider`).") in block


def test_a_grader_written_down_is_not_said(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _promptfoo(tmp_path)
    front.run()
    assert "isn't written in your config" not in capsys.readouterr().out


def test_an_unknown_tool_version_is_said(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    deepeval_project(tmp_path, split(20, 16))
    front.run()
    out = capsys.readouterr().out
    assert ("judgekeeper can't see your eval tool's version, so an update to it won't be "
            "noticed. Pin it in your project (e.g. `deepeval==4.2.8`).") in out


def test_a_pinned_tool_version_is_not_said(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    deepeval_project(tmp_path, split(20, 16))
    (tmp_path / "requirements.txt").write_text("deepeval==4.2.8\n", encoding="utf-8")
    front.run()
    assert "can't see your eval tool's version" not in capsys.readouterr().out
