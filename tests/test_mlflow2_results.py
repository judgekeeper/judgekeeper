"""MLflow 2's `mlflow.evaluate()` logs judge scores as run metrics (`<metric>/v1/mean`) and an
`eval_results_table.json`; judgekeeper reads judges run with `mlflow.genai.evaluate()` and
scorers (MLflow 3). Such results are not read: judgekeeper says what it found and why, in place
of "no MLflow experiment has judge assessments"."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.test_front import assert_one_next_at_the_end, run

OLD_EVALUATE = r"""
import os, sys
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow

mlflow.set_tracking_uri(sys.argv[1])
mlflow.set_experiment("rag-eval")
with mlflow.start_run():
    for name in ("faithfulness/v1", "answer_relevance/v1"):
        mlflow.log_metric(f"{name}/mean", 3.5)
        mlflow.log_metric(f"{name}/variance", 0.25)
    mlflow.log_table({"inputs": ["q"], "outputs": ["a"], "faithfulness/v1/score": [4],
                      "faithfulness/v1/justification": ["fine"]},
                     artifact_file="eval_results_table.json")
"""


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_judge_scores_from_mlflow_evaluate_are_named_and_not_read(here, capsys):
    pytest.importorskip("mlflow")
    script = here.parent / f"{here.name}-old-evaluate.py"
    script.write_text(OLD_EVALUATE, encoding="utf-8")
    subprocess.run([sys.executable, str(script), "sqlite:///mlflow.db"], check=True, cwd=here,
                   capture_output=True)
    code, out, err = run(capsys)
    assert ("Your MLflow runs hold judge scores from mlflow.evaluate() (answer_relevance/v1, "
            "faithfulness/v1). judgekeeper reads judges run with mlflow.genai.evaluate() and "
            "scorers (MLflow 3). Reading these older results isn't supported.") in out
    assert "no MLflow experiment" not in out + err
    assert assert_one_next_at_the_end(out).startswith("Next: tell the person ")
    assert code == 3
