"""An MLflow make_judge's rule: its instructions, which MLflow saves with each assessment.

They are the judge's rule everywhere `start` uses one (the first block, Fix your judge's
prompt, --rule-file's template-part checks, where the rule probably is) and part of the
judge's identity, so a changed rule is a new judge for Try your new judge.

The store is made by the installed MLflow in another process (skipped without it), with a real
`make_judge` whose model call is replaced: MLflow itself saves the instructions.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

from judgekeeper import keys, start, start_fix, start_label
from judgekeeper.cli import main
from judgekeeper.readers.mlflow_store import judge_instructions
from judgekeeper.start_label import StartSession, save_result
from judgekeeper.start_review import ReviewSession

OLD = "Pass only if the sum is right. Question: {{ inputs }} Answer: {{ outputs }}"
NEW = ("Pass only if the sum is right, written as a number. Question: {{ inputs }} "
       "Answer: {{ outputs }}")

STORE = r"""
import os, sys
from pathlib import Path
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "true"
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"  # one writer for SQLite
import mlflow
from mlflow.entities import AssessmentSource, Feedback
from mlflow.genai.judges import instructions_judge, make_judge

def model_call(model_uri, prompt, assessment_name, **_):
    ok = "wrong" not in prompt[-1].content
    return Feedback(name=assessment_name, value="pass" if ok else "fail", rationale="checked",
                    source=AssessmentSource(source_type="LLM_JUDGE", source_id=model_uri))

instructions_judge.invoke_judge_model = model_call  # no model is called
mlflow.set_tracking_uri("sqlite:///mlflow.db")
if mlflow.get_experiment_by_name("quiz") is None:
    mlflow.create_experiment("quiz", artifact_location=Path(sys.argv[2]).resolve().as_uri())
mlflow.set_experiment("quiz")
judge = make_judge(name="sum_check", instructions=sys.argv[1], model="openai:/gpt-4.1-mini")
data = [{"inputs": {"question": f"What is {i} + {i}?"},
         "outputs": f"It is {2 * i if i % 3 else 'wrong'}."} for i in range(1, 25)]

def wait_until_saved(run_id, scorer, expected=24, limit=60):
    # MLflow saves traces and assessments in the background: wait until every trace of the
    # run has its assessment from `scorer`, or stop and say how many are there.
    import inspect, time
    scope = ("locations" if "locations" in inspect.signature(mlflow.search_traces).parameters
             else "experiment_ids")
    exp = mlflow.get_experiment_by_name("quiz").experiment_id
    deadline = time.monotonic() + limit
    while True:
        mlflow.flush_trace_async_logging()
        traces = mlflow.search_traces(**{scope: [exp]}, run_id=run_id, return_type="list")
        done = [t for t in traces if any(a.name == scorer for a in t.info.assessments or [])]
        if len(done) >= expected:
            return
        if time.monotonic() > deadline:
            raise SystemExit(f"after {limit} s, {len(done)} of {expected} traces saved")
        time.sleep(0.3)

result = mlflow.genai.evaluate(data=data, scorers=[judge])
wait_until_saved(result.run_id, "sum_check")
"""


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    """mlflow.db after one run with OLD ("old") and after a second run with NEW ("both")."""
    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("build")
    out = tmp_path_factory.mktemp("stores")
    (build / "make.py").write_text(STORE, encoding="utf-8")
    for rule, name in ((OLD, "old"), (NEW, "both")):
        subprocess.run([sys.executable, "make.py", rule, str(out / "artifacts")], check=True,
                       cwd=build, capture_output=True)
        shutil.copy2(build / "mlflow.db", out / f"{name}.db")
    return out


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)


def _project(root, stores, which="old"):
    shutil.copy2(stores / f"{which}.db", root / "mlflow.db")
    (root / "quiz_eval.py").write_text(
        "from mlflow.genai.judges import make_judge\n\n"
        f"judge = make_judge(\n    name=\"sum_check\",\n    instructions={OLD!r},\n"
        "    model=\"openai:/gpt-4.1-mini\",\n)\n", encoding="utf-8")
    return root


def _checked(root):
    """The project checked: every answer marked as the judge said except four, and the
    review done, the judge wrong on those four."""
    ws = start_label.prepare(start.find_judge(root), say=lambda line="": None)
    session = StartSession(ws)
    flip = {"pass": "fail", "fail": "pass"}
    for n, q in enumerate(ws.data()["queue"]):
        session.update({"id": q["id"], "label": flip[q["group"]] if n < 4 else q["group"]})
    save_result(ws, session, say=lambda line="": None)
    review = ReviewSession(ws)
    for item in review.items:
        review.update({"id": item["id"], "second": item["first"]})
    for item in review.items:
        if item["disagreement"]:
            review.update({"id": item["id"], "choice": "judge_wrong"})
    assert start_fix.ready(ws)
    return ws


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_the_instructions_are_the_rule_and_in_the_prompt_hash(tmp_path, stores):
    found = start.find_judge(_project(tmp_path, stores))
    assert found.rule == OLD and found.one_rule
    line = next(x for x in start.found_lines(found) if "What it checks" in x)
    assert '"Pass only if the sum is right.' in line and start.NOT_IN_FILE not in line
    assert found.fingerprint["prompt_hash"]


def test_fix_writes_the_prompt_and_a_rule_file_is_checked_and_saved(tmp_path, stores, capsys,
                                                                    monkeypatch):
    monkeypatch.chdir(tmp_path)
    ws = _checked(_project(tmp_path, stores))
    prompt = start_fix.Fix(ws).prompt()
    assert f"<<<RULE\n{OLD}\nRULE>>>" in prompt
    assert "KEEP EXACTLY these template parts: {{ inputs }} {{ outputs }}" in prompt
    assert "--rule-file" in start_fix.Fix(ws).agent_prompt()

    rule_file = tmp_path / "agent-rule.txt"
    rule_file.write_text("Pass only if the sum is right. Question: {{ inputs }}\n",
                         encoding="utf-8")
    code, out, _ = run(capsys, "--fix", "--rule-file", rule_file)
    assert code != 0 and "dropped {{ outputs }}" in out
    rule_file.write_text(NEW + "\n", encoding="utf-8")
    code, out, _ = run(capsys, "--fix", "--rule-file", rule_file)
    assert code == 0 and "Saved" in out
    hand = json.loads((ws.dir / "fix" / "rule.json").read_text(encoding="utf-8"))["hand_over"]
    assert hand["where_short"] == "Probably in quiz_eval.py, line 5."


def test_a_changed_rule_is_a_new_judge(tmp_path, stores, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _checked(_project(tmp_path, stores))
    shutil.copy2(stores / "both.db", tmp_path / "mlflow.db")  # the eval ran with NEW
    found = start.find_judge(tmp_path)
    assert found.rule == NEW
    code, out, _ = run(capsys, "--try-new-judge", "--no-browser")
    assert "Your judge changed since your last check: the prompt changed." in out
    assert "same judge as your last check" not in out
    assert code == 8 and "judge calls" in out and "make_judge" in out  # the plan, then stop


@pytest.mark.parametrize(("meta", "want"), [
    ({"guideline": OLD}, OLD),  # MLflow 3.16
    ({"instructions": OLD}, OLD),
    ({"guidelines": f"  {OLD}\n"}, OLD),
    ({"guideline": "Be polite."}, None),  # a Guidelines judge: no template part
    ({"guideline": ["Be polite.", "{{ outputs }}"]}, None),
    ({}, None),
    ({"instructions": "   "}, None),
])
def test_the_instructions_in_an_assessments_metadata(meta, want):
    assert judge_instructions(meta) == want


# A make_judge named like a built-in judge, and the menu's line --------------------------------

def test_a_make_judge_named_correctness_is_not_the_built_in_one(tmp_path):
    pytest.importorskip("mlflow")
    from mlflow.genai import scorers

    from judgekeeper import again
    from judgekeeper.again import mlflow as mf

    def dry(**job):
        out = again.run_worker("mlflow", sys.executable, {"mode": "dry", **job}, tmp_path,
                               env=mf.WORKER_ENV)
        assert out["ok"], out
        return out["builtin"]

    fluency = scorers.Fluency().instructions  # a built-in judge that saves its instructions
    assert dry(name="correctness") is True  # nothing saved: MLflow's own Correctness
    assert dry(name="correctness", instructions=OLD) is False  # a make_judge
    assert dry(name="fluency", instructions=fluency) is True
    assert dry(name="sum_check", instructions=OLD) is False
    for name, saved, want in (("correctness", None, True), ("correctness", OLD, False),
                              ("fluency", fluency, True), ("sum_check", OLD, False)):
        assert mf.is_builtin(scorers, name, saved) is want  # the copy says the same
    info = {"name": "correctness", "instructions": True}
    assert mf.classify(info, {"version": "3.17.0", "builtin": False})[0] == "close"


def test_the_menu_says_what_asking_again_will_do(tmp_path, stores, monkeypatch):
    from judgekeeper import again
    from judgekeeper.again import AgainOptions

    monkeypatch.chdir(tmp_path)
    ws = _checked(_project(tmp_path, stores))
    _, note = again.menu_text(again.make_plan(ws, AgainOptions(), dry=False))
    assert "can't" not in note and "calls" in note, note


# Failed judge calls ------------------------------------------------------------------------

FAILING = r"""
import os, sys
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "true"
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"  # one writer for SQLite
from pathlib import Path
import mlflow
from mlflow.entities import AssessmentSource, Feedback
from mlflow.genai.scorers import scorer

failing = set(int(x) for x in sys.argv[1].split(",") if x)
mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.create_experiment("quiz", artifact_location=Path(sys.argv[2]).resolve().as_uri())
mlflow.set_experiment("quiz")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1-mini")

@scorer
def sum_check(inputs, outputs):
    n = int(inputs["question"].split()[2])
    if n in failing:
        raise RuntimeError(f"the judge gave no reply for question {n}")
    return Feedback(value="wrong" not in outputs, rationale="checked", source=judge)

data = [{"inputs": {"question": f"What is {i} + {i}?"},
         "outputs": f"It is {2 * i if i % 3 else 'wrong'}."} for i in range(1, 25)]

def wait_until_saved(run_id, scorer, expected=24, limit=60):
    # MLflow saves traces and assessments in the background: wait until every trace of the
    # run has its assessment from `scorer`, or stop and say how many are there.
    import inspect, time
    scope = ("locations" if "locations" in inspect.signature(mlflow.search_traces).parameters
             else "experiment_ids")
    exp = mlflow.get_experiment_by_name("quiz").experiment_id
    deadline = time.monotonic() + limit
    while True:
        mlflow.flush_trace_async_logging()
        traces = mlflow.search_traces(**{scope: [exp]}, run_id=run_id, return_type="list")
        done = [t for t in traces if any(a.name == scorer for a in t.info.assessments or [])]
        if len(done) >= expected:
            return
        if time.monotonic() > deadline:
            raise SystemExit(f"after {limit} s, {len(done)} of {expected} traces saved")
        time.sleep(0.3)

result = mlflow.genai.evaluate(data=data, scorers=[sum_check])
wait_until_saved(result.run_id, "sum_check")
"""


@pytest.fixture(scope="module")
def failing_stores(tmp_path_factory):
    """mlflow.db where 5 of 24 judge calls failed ("some"), and where all failed ("all")."""
    pytest.importorskip("mlflow")
    out = tmp_path_factory.mktemp("failing")
    for name, which in (("some", "2,5,8,11,14"), ("all", ",".join(map(str, range(1, 25))))):
        build = tmp_path_factory.mktemp(f"build-{name}")
        (build / "make.py").write_text(FAILING, encoding="utf-8")
        subprocess.run([sys.executable, "make.py", which, str(out / f"artifacts-{name}")],
                       check=True, cwd=build, capture_output=True)
        shutil.copy2(build / "mlflow.db", out / f"{name}.db")
    return out


def test_failed_judge_calls_are_counted(tmp_path, failing_stores, capsys):
    shutil.copy2(failing_stores / "some.db", tmp_path / "mlflow.db")
    _, out, _ = run(capsys, tmp_path, "--no-browser")
    assert "Its decisions   19 answers" in out, out
    assert "Your judge gave a Pass or Fail on every answer" not in out
    assert re.search(r"5 calls failed", out), out
    found = start.find_judge(tmp_path)
    errors = [r for r in found.pool.answers if r.verdict not in ("pass", "fail")]
    assert not errors  # failed calls give no decision: they are not in the pool


def test_every_judge_call_failed_says_why(tmp_path, failing_stores, capsys):
    shutil.copy2(failing_stores / "all.db", tmp_path / "mlflow.db")
    code, out, err = run(capsys, tmp_path, "--no-browser")
    said = out + err
    assert code != 0
    assert "every call of your judge sum_check failed (24 saved as errors)" in said, said
    assert "First error: SCORER_ERROR: the judge gave no reply for question" in said
    assert "has no judge assessments" not in said
