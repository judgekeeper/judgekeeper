"""Ready for agents: the readers keep what agent graders need, and `start` passes it through.

- Inspect: each sample's `messages` become the record's `trajectory` (OpenAI-style: role,
  content, tool_calls with id, name and arguments, tool_call_id); a score whose value is a
  dict (how rubric graders report) is one judge per key, named scorer.key.
- MLflow: an assessment's `span_id` goes into `metadata`; only trace-level assessments (or
  ones on the root span, where mlflow.genai.evaluate puts them) are the judge's verdicts,
  unless --metric names a judge that is only on spans.
- start: the trajectory, the outcome and the app version go into the pool and the anchor set,
  never onto a page; a re-check says when the app's version changed.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from judgekeeper import start, start_label
from judgekeeper.again import inspect as again_inspect
from judgekeeper.cli import main
from judgekeeper.normalise import Normaliser
from judgekeeper.readers import read_inspect
from judgekeeper.readers.inspect_logs import sample_key, trajectory
from judgekeeper.start_label import StartSession, save_result
from tests.start_projects import inspect_data, split, table_project

STEPS = [
    {"id": "m1", "role": "user", "content": "Refund order 7", "source": "input"},
    {"id": "m2", "role": "assistant", "source": "generate", "model": "gpt-4.1",
     "content": [{"type": "reasoning", "reasoning": "look it up"}],
     "tool_calls": [{"id": "call_1", "function": "lookup_order", "arguments": {"order": 7},
                     "type": "function"}]},
    {"id": "m3", "role": "tool", "content": "{\"status\": \"delivered\"}",
     "tool_call_id": "call_1", "function": "lookup_order", "error": None},
    {"id": "m4", "role": "assistant", "source": "generate",
     "content": [{"type": "text", "text": "Your refund is on its way."}]},
]
EXPECTED = [
    {"role": "user", "content": "Refund order 7"},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "call_1", "name": "lookup_order", "arguments": {"order": 7}}]},
    {"role": "tool", "content": "{\"status\": \"delivered\"}", "tool_call_id": "call_1"},
    {"role": "assistant", "content": "Your refund is on its way."},
]


def _quiet(line=""):
    pass


# Inspect ---------------------------------------------------------------------------------

def test_inspect_messages_become_the_trajectory():
    assert trajectory({"messages": STEPS}) == EXPECTED
    assert trajectory({"messages": []}) is None
    assert trajectory({}) is None


def _inspect_log(tmp_path, samples):
    data = inspect_data([True])
    data["samples"] = samples
    path = tmp_path / "logs" / "agent.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def _sample(i, value, steps=STEPS, scorer="model_graded_qa"):
    return {"id": i, "epoch": 1, "input": "Refund order 7",
            "output": {"completion": "Your refund is on its way."}, "messages": steps,
            "scores": {scorer: {"value": value, "explanation": f"reason {i}", "history": []}}}


def test_the_inspect_reader_keeps_the_trajectory(tmp_path):
    path, _ = _inspect_log(tmp_path, [_sample(1, "C")])
    (r,) = [r for r in read_inspect(path) if r.annotator_kind == "LLM"]
    assert r.trajectory == EXPECTED


def test_two_inspect_runs_with_the_same_answer_stay_two_answers(tmp_path):
    shorter = [STEPS[0], STEPS[3]]
    path, data = _inspect_log(tmp_path, [_sample(1, "C"), _sample(2, "I", steps=shorter)])
    records = read_inspect(path)
    pool = start.build_pool([("agent.json", records)], "model_graded_qa",
                            Normaliser(label_map={"C": "pass", "I": "fail"}))
    assert len(pool.answers) == 2 and pool.n_merged == 0
    # asking again finds each answer's sample by the same key
    assert {a.id for a in pool.answers} == {sample_key(s) for s in data["samples"]}


def test_dict_valued_scores_are_one_judge_per_key(tmp_path):
    sample = _sample(1, {"accuracy": "C", "tone": "I", "steps": 0.5}, scorer="rubric")
    path, _ = _inspect_log(tmp_path, [sample])
    by_name = {r.name: r for r in read_inspect(path) if r.annotator_kind == "LLM"}
    assert set(by_name) == {"rubric.accuracy", "rubric.tone", "rubric.steps"}
    assert by_name["rubric.accuracy"].label == "C"
    assert by_name["rubric.tone"].label == "I"
    assert by_name["rubric.steps"].score == 0.5
    assert by_name["rubric.tone"].explanation == "reason 1"
    prompts = {r.evaluator["prompt"] for r in by_name.values()}
    assert len(prompts) == 1  # one scorer, one prompt


def test_asking_again_about_one_key_of_a_dict_score_says_why_not():
    spec = {"scorers": [{"name": "rubric", "options": {}}]}
    assert "several verdicts at once" in again_inspect.several_verdicts("rubric.tone", spec)
    assert again_inspect.several_verdicts("model_graded_qa", spec) is None
    assert again_inspect.several_verdicts("other.tone", spec) is None


# MLflow ----------------------------------------------------------------------------------

STORE = r'''
import os, sys
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri(sys.argv[1])
mlflow.set_experiment("agent")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")
person = AssessmentSource(source_type="HUMAN", source_id="reviewer")

@mlflow.trace(name="tool")
def tool(n):
    return n * 2

@mlflow.trace(name="agent")
def agent(question):
    return f"answer {tool(len(question))}"

for i, question in enumerate(["one", "three", "seven", "eleven"]):
    agent(question)
    mlflow.flush_trace_async_logging()
    trace_id = mlflow.get_last_active_trace_id()
    spans = mlflow.get_trace(trace_id).data.spans
    span = next(s for s in spans if s.name == "tool")
    root = next(s for s in spans if s.parent_id is None)
    ok = i % 2 == 0
    mlflow.log_feedback(trace_id=trace_id, name="helpful", value=ok, source=judge)
    # mlflow.genai.evaluate logs its assessments on the root span: trace-level all the same
    mlflow.log_feedback(trace_id=trace_id, name="on_root", value=ok, source=judge,
                        span_id=root.span_id)
    mlflow.log_feedback(trace_id=trace_id, name="helpful", value=not ok, source=judge,
                        span_id=span.span_id)
    mlflow.log_feedback(trace_id=trace_id, name="tool_ok", value=ok, source=judge,
                        span_id=span.span_id)
    mlflow.log_feedback(trace_id=trace_id, name="helpful", value=ok, source=person)
    mlflow.log_feedback(trace_id=trace_id, name="tool_ok", value=ok, source=person,
                        span_id=span.span_id)
    print(span.span_id)
'''


@pytest.fixture(scope="module")
def span_store(tmp_path_factory):
    pytest.importorskip("mlflow")
    root = tmp_path_factory.mktemp("span-store")
    script = root / "make.py"
    script.write_text(STORE, encoding="utf-8")
    uri = f"sqlite:///{(root / 'mlflow.db').as_posix()}"
    done = subprocess.run([sys.executable, str(script), uri], capture_output=True, text=True,
                          check=True, cwd=root)
    return uri, done.stdout.split()


def _judge_records(files):
    return [r for label, recs in files if label != "human assessments" for r in recs]


def test_mlflow_uses_trace_level_verdicts_when_a_trace_has_both(span_store):
    from judgekeeper.readers import read_mlflow

    uri, _ = span_store
    files = read_mlflow("agent", tracking_uri=uri)
    judged = [r for r in _judge_records(files) if r.name != "on_root"]
    assert {r.name for r in judged} == {"helpful"}
    assert len(judged) == 4
    assert sorted(r.label for r in judged) == ["fail", "fail", "pass", "pass"]
    assert all("span_id" not in r.metadata for r in judged)
    on_root = [r for r in _judge_records(files) if r.name == "on_root"]
    assert len(on_root) == 4 and all(r.metadata.get("span_id") for r in on_root)
    notes = " ".join(n for _, recs in files for n in recs.notes)
    assert "span" in notes and "--metric" in notes


def test_mlflow_reads_a_span_level_judge_when_metric_names_it(span_store):
    from judgekeeper.readers import read_mlflow

    uri, span_ids = span_store
    files = read_mlflow("agent", tracking_uri=uri, metric="tool_ok")
    judged = [r for r in _judge_records(files) if r.name == "tool_ok"]
    assert len(judged) == 4
    assert {r.metadata["span_id"] for r in judged} == set(span_ids)
    humans = [r for label, recs in files if label == "human assessments" for r in recs
              if r.name == "tool_ok"]
    assert len(humans) == 4 and all(r.metadata.get("span_id") for r in humans)


def test_mlflow_never_mixes_span_verdicts_into_a_trace_level_judge(span_store):
    from judgekeeper.readers import read_mlflow

    uri, _ = span_store
    files = read_mlflow("agent", tracking_uri=uri, metric="helpful")
    judged = [r for r in _judge_records(files) if r.name == "helpful"]
    assert len(judged) == 4 and all("span_id" not in r.metadata for r in judged)


def test_import_mlflow_checks_a_span_level_judge(span_store, tmp_path):
    uri, _ = span_store
    out = tmp_path / "rep"
    assert main(["import", "mlflow", "--experiment", "agent", "--tracking-uri", uri,
                 "--metric", "tool_ok", "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["anchors"]["n_items"] == 4
    assert report["runs"][0]["kappa"] == pytest.approx(1)


# start: the pool and the anchor set -------------------------------------------------------

def _inspect_project(root):
    data = inspect_data(split(20, 16))
    for s in data["samples"]:
        s["messages"] = [{"role": "user", "content": s["input"]},
                         {"role": "assistant", "content": s["output"]["completion"]}]
    path = root / "logs" / "2026-10-02_support.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_start_keeps_the_trajectory_in_the_pool_and_the_anchors_not_the_page(tmp_path):
    _inspect_project(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    pool = [json.loads(line) for line in ws.pool.read_text().splitlines()]
    assert all(p["trajectory"][0]["role"] == "user" for p in pool)
    session = StartSession(ws)
    assert set(session.state()["items"][0]) == {"id", "input", "output", "label", "skipped"}
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    save_result(ws, session, say=_quiet)
    anchors = [json.loads(line) for line in ws.anchors.read_text().splitlines()]
    assert all(a["trajectory"][1]["role"] == "assistant" for a in anchors)


def _table_check(root, version):
    table_project(root, split(20, 16), extra={"app_version": [version] * 36})
    found = start.find_judge(root)
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    save_result(ws, session, say=_quiet)
    return found, ws


def test_start_saves_the_app_version(tmp_path):
    found, ws = _table_check(tmp_path, "support-agent 2.3")
    assert found.app_version == "support-agent 2.3"
    assert ws.data()["app_version"] == "support-agent 2.3"


def _recheck(root, capsys, version):
    verdicts = split(20, 16)
    verdicts[0] = False  # one new verdict: a re-check, not the menu
    table_project(root, verdicts, extra={"app_version": [version] * 36})
    code = main(["start", str(root), "--yes", "--no-browser"])
    return code, capsys.readouterr().out


def test_a_recheck_says_when_the_app_version_changed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(start_label, "serve_workspace", lambda *a, **k: 0)
    _table_check(tmp_path, "support-agent 2.3")
    capsys.readouterr()
    code, out = _recheck(tmp_path, capsys, "support-agent 2.4")
    assert code == 0
    assert ("Your app changed since your last check: its version was support-agent 2.3, "
            "now support-agent 2.4.") in out


def test_a_recheck_says_nothing_when_the_app_version_is_the_same(tmp_path, capsys,
                                                                 monkeypatch):
    monkeypatch.setattr(start_label, "serve_workspace", lambda *a, **k: 0)
    _table_check(tmp_path, "support-agent 2.3")
    capsys.readouterr()
    code, out = _recheck(tmp_path, capsys, "support-agent 2.3")
    assert code == 0
    assert "Your app changed" not in out


def test_a_check_saved_before_app_versions_says_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(start_label, "serve_workspace", lambda *a, **k: 0)
    _, ws = _table_check(tmp_path, "support-agent 2.3")
    data = ws.data()
    del data["app_version"]
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    code, out = _recheck(tmp_path, capsys, "support-agent 2.4")
    assert code == 0
    assert "Your app changed" not in out
