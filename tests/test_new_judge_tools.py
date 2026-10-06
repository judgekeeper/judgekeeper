"""Trying a new DeepEval, Inspect AI or MLflow judge: each tool's new judge is rebuilt from its
newest results and grades the answers the person already marked.

The workers run against the stub packages of tests/again_stubs.py (the `stubs` fixture); no
tool is installed and no model is called.
"""

from __future__ import annotations

import json
import sys

import pytest

from judgekeeper import again, keys, new_judge, start, start_label
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again import deepeval as de
from judgekeeper.again import mlflow as mf
from judgekeeper.start_label import StartSession, save_result
from tests.start_projects import (
    deepeval_data,
    deepeval_project,
    inspect_data,
    inspect_project,
    split,
)

FIELDS = AgainOptions(python=sys.executable, fields="input,actual_output")


def _quiet(line=""):
    pass


def _checked(root, maker):
    maker(root, split(20, 16))
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)


def _items(plan) -> dict:
    return {a["input"]: item for a, item, *_ in plan.payload}


# DeepEval --------------------------------------------------------------------------------------

STEPS = '[\n    "Check each claim in the actual output.",\n    "Penalise any claim that is false."\n]'


def _deepeval_new(root, rows=None, steps_for=None):
    """The next DeepEval run: new answers, new criteria; `rows` keeps only the first rows;
    `steps_for` gives some inputs their own steps."""
    data = deepeval_data(split(20, 16))
    cases = data["testCases"][:rows] if rows else data["testCases"]
    for case in cases:
        case["actualOutput"] += " (v2)"
        md = case["metricsData"][0]
        md["verboseLogs"] = md["verboseLogs"].replace(
            "Is the actual output factually correct given the input?", "Is it right and short?")
        if steps_for and case["input"] in steps_for:
            md["verboseLogs"] = md["verboseLogs"].replace(
                STEPS, f'[\n    "{steps_for[case["input"]]}"\n]')
    data["testCases"] = cases
    (root / ".deepeval" / ".latest_run_full.json").write_text(json.dumps(data), encoding="utf-8")
    return new_judge.View(start_label.Workspace(root), start.find_judge(root))


def test_deepeval_uses_the_steps_of_the_newest_row_with_the_same_input(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    view = _deepeval_new(tmp_path, steps_for={"Question 3?": "Check every word."})
    plan = make_plan(ws, FIELDS, new=view)
    items = _items(plan)
    assert items["Question 3?"]["metric"]["steps"] == ["Check every word."]
    assert items["Question 4?"]["metric"]["steps"] == ["Check each claim in the actual output.",
                                                       "Penalise any claim that is false."]
    assert items["Question 4?"]["metric"]["criteria"] == "Is it right and short?"
    assert de.STEPS_DIFFER in plan.why and plan.status == "close"
    assert plan.times == 1 and plan.calls == 36


def test_deepeval_old_answers_keep_their_own_output(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    plan = make_plan(ws, FIELDS, new=_deepeval_new(tmp_path))
    for a, item, *_ in plan.payload:
        assert item["case"]["actual_output"] == a["output"] and "(v2)" not in a["output"]
    assert de.STEPS_DIFFER not in plan.why  # every row has the same steps


def test_deepeval_without_a_matching_input_takes_the_steps_most_rows_share(tmp_path, stubs):
    ws = _checked(tmp_path, deepeval_project)
    view = _deepeval_new(tmp_path, rows=10,
                         steps_for={"Question 0?": "One.", "Question 1?": "Two."})
    plan = make_plan(ws, FIELDS, new=view)
    items = _items(plan)
    assert len(items) == 36  # every marked answer, matched by input or not
    assert items["Question 0?"]["metric"]["steps"] == ["One."]
    assert items["Question 30?"]["metric"]["steps"] == ["Check each claim in the actual output.",
                                                        "Penalise any claim that is false."]


# Inspect AI ------------------------------------------------------------------------------------

def _inspect_new(root):
    data = inspect_data(split(20, 16))
    data["eval"]["packages"] = {"inspect_ai": "0.3.273"}
    data["eval"]["scorers"][0]["options"]["instructions"] = "Grade it strictly."
    for s in data["samples"]:
        s["output"]["completion"] += " (v2)"
        s["target"] = f"target of {s['input']}"
    (root / "logs" / "2026-10-02_support.json").write_text(json.dumps(data), encoding="utf-8")
    return new_judge.View(start_label.Workspace(root), start.find_judge(root))


def test_inspect_is_exactly_the_new_judge_only_by_scorer_and_version(tmp_path, stubs,
                                                                     monkeypatch):
    ws = _checked(tmp_path, inspect_project)
    view = _inspect_new(tmp_path)
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    assert plan.status == "exact"
    assert plan.why == "Inspect scores your marked answers with your new judge's scorer and grader"
    monkeypatch.setenv("STUB_VERSION", "0.3.300")
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    assert plan.status == "close"
    assert plan.why == ("your Python has Inspect 0.3.300 and your newest log was made with "
                        "0.3.273")  # no prompt check can make it exact: never graded these


def test_inspect_places_the_marked_answers_into_the_newest_log(tmp_path, stubs):
    ws = _checked(tmp_path, inspect_project)
    view = _inspect_new(tmp_path)
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    assert plan.job["new"] is True
    item = _items(plan)["Question 3?"]
    assert item["output"] == "Answer 3." and item["target"] == "target of Question 3?"
    stubs.plan(verdicts={a["input"]: a["verdict"] == "pass" for a in again.labeled_answers(ws)})
    plan.folder = ws.dir / "new-judge-test"
    fresh = again.run_tool(view, plan, start.Talk(quiet=True))
    assert len(fresh.verdicts) == 36 and not fresh.not_counted
    (shown,) = stubs("samples")
    first = next(s for s in shown["samples"] if s["input"] == "Question 3?")
    assert first["output"] == "Answer 3." and first["target"] == "target of Question 3?"
    assert first["messages"] == [["user", "Question 3?"], ["assistant", "Answer 3."]]
    assert first["scores"] == []
    scored = stubs("registry_create")[0]
    assert scored["options"]["instructions"] == "Grade it strictly."  # the new judge
    assert stubs("log-written") == []


# MLflow ----------------------------------------------------------------------------------------

def _mlflow(root, monkeypatch, keep=0, **info):
    ws = _checked(root, inspect_project)
    data = ws.data()
    data["tool"] = "mlflow"
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    answers = again.labeled_answers(ws)
    kept = {a["id"]: f"tr-{n}" for n, a in enumerate(answers[:keep])}
    seen = {}

    def info_of(ws, metric, run=None):
        seen["run"] = run
        return {"source_id": "openai:/gpt-4.1-mini", "scorer_name": None,
                "scorer_version": None, "name": "safety", "guidelines": None,
                "instructions": False, "trace": False, "text": None, "experiment": "1",
                "uri": "sqlite:////tmp/judgekeeper-mlflow-x/mlflow.db", "traces": {},
                "all_traces": kept, **info}

    monkeypatch.setattr(mf, "assessment_info", info_of)
    found = start.find_judge(root)
    found.tool, found.used = "mlflow", ["run-new"]
    return ws, new_judge.View(ws, found), answers, kept, seen


def test_mlflow_takes_the_judge_from_the_newest_run(tmp_path, stubs, monkeypatch):
    ws, view, answers, _, seen = _mlflow(tmp_path, monkeypatch, keep=3)
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    assert seen["run"] == "run-new" and plan.answers == 36
    traces = {a["id"]: item["trace"] for a, item, *_ in plan.payload}
    assert [traces[a["id"]] for a in answers[:4]] == ["tr-0", "tr-1", "tr-2", None]


def test_mlflow_calls_the_new_judge_without_a_trace_when_none_is_kept(tmp_path, stubs,
                                                                     monkeypatch):
    ws, view, answers, *_ = _mlflow(tmp_path, monkeypatch, keep=2)
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    stubs.plan(by_input={str(a["input"]): f"key-{a['id']}" for a in answers})
    plan.folder = ws.dir / "new-judge-test"
    fresh = again.run_tool(view, plan, start.Talk(quiet=True))
    assert len(fresh.verdicts) == 36
    assert sorted(e["trace"] for e in stubs("get_trace")) == ["tr-0", "tr-1"]
    assert all(c["expectations"] is None for c in stubs("judge"))


def test_a_new_trace_judge_needs_the_answers_traces(tmp_path, stubs, monkeypatch):
    ws, view, *_ = _mlflow(tmp_path, monkeypatch, keep=5, name="tone", instructions=True,
                           trace=True, text="Look at {{ trace }}")
    plan = make_plan(ws, AgainOptions(python=sys.executable), new=view)
    assert plan.answers == 5
    assert ("31 answers are left out: their traces are not in your MLflow store, and your "
            "judge reads the whole trace.") in plan.left_out
