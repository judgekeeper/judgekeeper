"""Fixes from running judgekeeper on public projects that need a real MLflow store: a store
whose traces point at an artifact server, code scorers only, a judge whose calls all failed,
the store's own date, and the notes the reference promises. Every store is built here by
MLflow itself (no model call); the tests skip when mlflow is not installed.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from judgekeeper.cli import main
from tests.conftest import build_mlflow_folder_store
from tests.start_projects import deepeval_project, split
from tests.test_front import assert_one_next_at_the_end, flat

STORE = r"""
import os, sys, inspect, time
from pathlib import Path
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "true"
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"
import mlflow
from mlflow.entities import AssessmentSource, Feedback
from mlflow.genai.scorers import scorer

mlflow.set_tracking_uri("sqlite:///mlflow.db")
exp_id = mlflow.create_experiment("qa", artifact_location=Path(sys.argv[1]).resolve().as_uri())
mlflow.set_experiment("qa")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1-mini")

@mlflow.trace
def app(question):
    return f"Answer to {question.lower()}"

@scorer
def correctness(inputs, outputs):
    ok = int(inputs["question"][-2]) % 3 != 0
    return Feedback(value=ok, source=judge, rationale="checked")

@scorer
def safety(inputs, outputs):  # a judge whose every call fails: MLflow saves it as CODE
    raise RuntimeError("the judge's provider refused the call")

@scorer
def has_answer(outputs):
    return bool(outputs)

data = [{"inputs": {"question": f"Question {i}?"}} for i in range(8)]
result = mlflow.genai.evaluate(data=data, predict_fn=app, scorers=[correctness, safety, has_answer])
scope = ("locations" if "locations" in inspect.signature(mlflow.search_traces).parameters
         else "experiment_ids")
deadline = time.monotonic() + 60
while True:
    mlflow.flush_trace_async_logging()
    traces = mlflow.search_traces(**{scope: [exp_id]}, run_id=result.run_id, return_type="list")
    done = [t for t in traces if len(t.info.assessments or []) >= 3]
    if len(done) >= 8:
        break
    if time.monotonic() > deadline:
        raise SystemExit(f"after 60 s, {len(done)} of 8 traces saved")
    time.sleep(0.3)
app("Question 9?")  # a trace outside evaluate, judged by hand
mlflow.flush_trace_async_logging()
mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="correctness", value=True,
                    source=judge, rationale="checked")
mlflow.flush_trace_async_logging()
"""


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Path:
    """mlflow.db with the "qa" experiment: 8 judged answers plus one judged outside evaluate,
    a judge whose calls all failed, and a code scorer."""
    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("build")
    (build / "make.py").write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, "make.py", str(build / "artifacts")], check=True,
                   cwd=build, capture_output=True)
    return build / "mlflow.db"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def edit(db: Path, *statements: str) -> None:
    with closing(sqlite3.connect(db)) as con:
        for statement in statements:
            con.execute(statement)
        con.commit()


# The store's own date; a store with no assessments is not offered ----------------------

def test_the_store_date_is_its_newest_run_time_not_the_files(here, capsys, store):
    deepeval_project(here, split(20, 16))
    shutil.copy2(store, here / "mlflow.db")
    old = datetime(2020, 1, 2, 3, 4).timestamp()
    os.utime(here / "mlflow.db", (old, old))  # when the project was cloned, not run
    with closing(sqlite3.connect(store)) as con:
        (newest,) = con.execute("select max(start_time) from runs").fetchone()
    when = datetime.fromtimestamp(newest / 1000).astimezone()
    code, out = run(capsys)
    assert code == 3, out
    assert f"MLflow (mlflow.db, saved {when:%Y-%m-%d %H:%M})" in flat(out)
    assert "2020" not in out


def test_a_store_with_no_assessments_is_not_offered_as_a_second_tool(here, capsys, store):
    deepeval_project(here, split(20, 16))
    shutil.copy2(store, here / "mlflow.db")
    edit(here / "mlflow.db", "delete from assessments")
    code, out = run(capsys)
    assert code == 0, out
    assert "--tool" not in out and "Saved results from more than one" not in out
    assert "Eval tool:   DeepEval" in out
    assert "mlflow.db holds no judge assessments, so it was left out." in flat(out)


# Code scorers only ---------------------------------------------------------------------

def test_a_store_with_code_scorers_only_is_said_like_deepeval(here, capsys, store):
    shutil.copy2(store, here / "mlflow.db")
    edit(here / "mlflow.db", "delete from assessments where source_type = 'LLM_JUDGE'",
         "delete from assessments where error is not null")  # code scorers' own verdicts only
    code, out = run(capsys)
    assert code == 3, out
    assert "error:" not in out and "fix what the line above says" not in out
    assert ("mlflow.db holds no decisions from an LLM judge. These scorers are rules in code, "
            "not an LLM judge. judgekeeper checks LLM judges.") in flat(out)
    assert "add an LLM judge to your eval" in assert_one_next_at_the_end(out)


# A judge whose every call failed, saved as CODE ------------------------------

def test_a_judge_whose_calls_all_failed_is_listed_and_said(here, capsys, store):
    shutil.copy2(store, here / "mlflow.db")
    edit(here / "mlflow.db", "delete from assessments where trace_id in (select request_id "
                             "from trace_info where request_preview like '%Question 9%')")
    code, out = run(capsys)
    assert code == 3, out
    assert "safety" in out and "correctness" in out  # both judges are listed
    code, out = run(capsys, "--metric", "safety")
    assert code == 3, out
    assert "Your judge's calls failed on every answer, so there is nothing to mark." in flat(out)
    assert "RuntimeError" not in out and "refused the call" not in out


# The notes the reference promises ---------------------------------------------

def test_mlflow_notes_are_printed(here, capsys, store):
    shutil.copy2(store, here / "mlflow.db")
    code, out = run(capsys, "--metric", "correctness")
    assert code == 3, out  # 9 answers: not enough for a first result
    assert ("8 assessments from code scorers (has_answer) are rules in code, not an LLM "
            "judge: left out.") in flat(out)
    assert ("Some judge assessments carry no MLflow run id (logged by hand, outside an "
            "evaluate run): they form one run, listed last.") in flat(out)
    assert "Runs are MLflow runs in start order" not in out
    assert "MLFLOW_ALLOW_FILE_STORE" not in out


# Traces saved to a tracking server (mlflow-artifacts:) ------------------------------------

def _points_at_a_server(db: Path) -> None:
    """The traces' spans live on an artifact server that isn't there (an older MLflow kept
    spans in artifacts)."""
    edit(db, "update trace_tags set value = 'mlflow-artifacts:/1/traces/' || request_id || "
             "'/artifacts' where key = 'mlflow.artifactLocation'",
         "update experiments set artifact_location = 'mlflow-artifacts:/1'",
         "delete from trace_tags where key = 'mlflow.trace.spansLocation'")


def test_a_store_whose_spans_are_on_a_server_is_read_from_what_it_holds(here, capsys, store):
    shutil.copy2(store, here / "mlflow.db")
    _points_at_a_server(here / "mlflow.db")
    code, out = run(capsys, "--metric", "correctness")
    assert code == 3, out
    assert "a problem it didn't expect" not in out and "--debug" not in out
    assert "Answers:     9 answers" in out


def test_a_store_whose_text_is_only_on_a_server_says_to_start_it(here, capsys, store):
    shutil.copy2(store, here / "mlflow.db")
    _points_at_a_server(here / "mlflow.db")
    edit(here / "mlflow.db", "update trace_info set request_preview = NULL, "
                             "response_preview = NULL",
         "delete from trace_request_metadata where key in ('mlflow.traceInputs', "
         "'mlflow.traceOutputs')")  # nothing of the text is left in the store
    code, out = run(capsys, "--metric", "correctness")
    assert code in (2, 3), out
    assert "a problem it didn't expect" not in out
    assert ("These MLflow traces were saved to a tracking server (mlflow-artifacts:)."
            in flat(out))
    line = assert_one_next_at_the_end(out)
    assert "MLFLOW_TRACKING_URI" in line and "--metric correctness" in line


# The folder-store line only when a folder store is read ---------------------------------

def test_the_folder_store_line_is_said_only_when_one_is_read(here, capsys, store, monkeypatch):
    from judgekeeper.readers import mlflow_store

    monkeypatch.setattr(mlflow_store, "_noted", False)  # said once per run: a fresh run here
    shutil.copy2(store, here / "mlflow.db")
    build_mlflow_folder_store(here / "mlruns")
    code, out = run(capsys)
    assert code == 3, out
    assert "Two MLflow stores found" in flat(out)
    assert "MLFLOW_ALLOW_FILE_STORE" not in out
    code, out = run(capsys, "mlruns")
    assert code == 3, out
    assert "MLFLOW_ALLOW_FILE_STORE" in out
