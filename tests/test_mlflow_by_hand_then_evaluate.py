"""Grades first logged by hand (`mlflow.log_feedback`, no run id), then graded again with
`mlflow.genai.evaluate()` on the same traces under the same name: the evaluate run is the
newer one, so `fix mlflow.db` and `check mlflow.db` read it. Both stores are made by the
installed MLflow (no model call); the test skips when mlflow is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from judgekeeper import fix
from judgekeeper.cli import main

HEAD = r"""
import os, inspect, time
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "true"
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"
import mlflow
from mlflow.entities import AssessmentSource, Feedback

mlflow.set_tracking_uri("sqlite:///mlflow.db")
"""

BY_HAND = HEAD + r"""
mlflow.set_experiment("qa")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="my-judge-v1")

@mlflow.trace
def app(question):
    return f"Answer to {question.lower()}"

for i in range(32):
    app(f"Question {i}?")
    mlflow.flush_trace_async_logging()
    mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="correctness",
                        value=i % 2 == 0, source=judge, rationale="by hand")
mlflow.flush_trace_async_logging()
"""

EVALUATE = HEAD + r"""
from mlflow.genai.scorers import scorer

exp = mlflow.set_experiment("qa")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="my-judge-v2")

@scorer
def correctness(inputs, outputs):  # passes every answer: other grades than by hand
    return Feedback(value=True, source=judge, rationale="graded again")

scope = ("locations" if "locations" in inspect.signature(mlflow.search_traces).parameters
         else "experiment_ids")
traces = mlflow.search_traces(**{scope: [exp.experiment_id]})
result = mlflow.genai.evaluate(data=traces, scorers=[correctness])
deadline = time.monotonic() + 60
while True:
    mlflow.flush_trace_async_logging()
    done = [t for t in mlflow.search_traces(**{scope: [exp.experiment_id]}, return_type="list")
            if len(t.info.assessments or []) >= 2]
    if len(done) >= 32:
        break
    if time.monotonic() > deadline:
        raise SystemExit(f"after 60 s, {len(done)} of 32 traces graded again")
    time.sleep(0.3)
"""


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    """mlflow.db as first graded by hand, and the same store graded again with evaluate()."""
    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("build")
    for name, script in (("by_hand.py", BY_HAND), ("evaluate.py", EVALUATE)):
        (build / name).write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, "by_hand.py"], cwd=build, check=True, capture_output=True)
    first = tmp_path_factory.mktemp("first") / "mlflow.db"
    shutil.copy2(build / "mlflow.db", first)
    subprocess.run([sys.executable, "evaluate.py"], cwd=build, check=True, capture_output=True)
    return first, build / "mlflow.db"


def test_an_evaluate_run_after_grades_by_hand_is_read_as_the_newer(stores, tmp_path,
                                                                    monkeypatch, capsys):
    from judgekeeper import fix, start, start_label
    from judgekeeper.readers import mlflow_store
    from judgekeeper.start_label import StartSession
    from tests.start_projects import save_result

    first, graded_again = stores
    monkeypatch.setattr(mlflow_store, "_walked", {})
    monkeypatch.setattr(fix.secrets, "randbelow", lambda n: 0)  # the same queue and split
    shutil.copy2(first, tmp_path / "mlflow.db")
    monkeypatch.chdir(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    session = StartSession(ws)
    seen = {"pass": 0, "fail": 0}
    for q in ws.data()["queue"]:  # 1 in 5 of each marked the other way
        seen[q["group"]] += 1
        session.update({"id": q["id"], "label": q["group"] if seen[q["group"]] % 5 else
                        {"pass": "fail", "fail": "pass"}[q["group"]]})
    save_result(ws, session, say=lambda line="": None)
    main(["fix"])
    capsys.readouterr()

    shutil.copy2(graded_again, tmp_path / "mlflow.db")
    main(["fix", "mlflow.db"])
    said = " ".join(capsys.readouterr().out.split())
    assert "New results: mlflow.db" in said, said
    assert fix.SAME_GRADES not in said, said  # the new run is read, not the by-hand one
    assert "New rule: When you say Pass: agrees on 9 of 9" in said, said
    main(["check", "mlflow.db"])
    said = " ".join(capsys.readouterr().out.split())
    assert "has not changed" not in said, said
    assert "my-judge-v1 -> my-judge-v2" in said, said
    mlflow_store.remove_copies()
