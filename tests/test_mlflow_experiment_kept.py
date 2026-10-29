"""A store with two judged experiments: the one chosen with --experiment is kept with the marks,
so the runs after read it again with no terminal to ask at. Made by the installed MLflow in
another process (skipped without it)."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store

STORE = r"""
import os
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri("sqlite:///mlflow.db")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

@mlflow.trace(name="app")
def app(question):
    return f"answer to {question}"

for name in ("helper", "helper-tone"):
    mlflow.set_experiment(name)
    for i in range(30):
        app(f"{name} question {i}")
        mlflow.flush_trace_async_logging()
        mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="helpful",
                            value=i % 2 == 0, source=judge)
"""


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    pytest.importorskip("mlflow")
    out = tmp_path_factory.mktemp("two")
    (out / "make_store.py").write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, "make_store.py"], check=True, cwd=out, capture_output=True)
    return out / "mlflow.db"


@pytest.fixture
def project(made, tmp_path, monkeypatch):
    root = tmp_path / "helper-bot"
    root.mkdir()
    shutil.copy2(made, root / "mlflow.db")
    monkeypatch.chdir(root)
    yield root
    main(["--stop"])
    mlflow_store.remove_copies()


def _run(capsys, *argv) -> tuple[int, str]:
    code = main(list(argv))
    return code, " ".join("".join(capsys.readouterr()).split())


def test_the_experiment_chosen_is_kept_with_the_marks(project, capsys):
    """Plain `judgekeeper`, `mark` and the run after `--stop` asked for the experiment again
    every time (exit 3), and their Next lines left `--experiment` out."""
    code, out = _run(capsys, "--experiment", "helper", "--no-browser", "--port", "0")
    assert code == 0 and "experiment helper" in out, out
    for argv in (["--stop"], [], ["mark"], ["--stop"], []):
        code, out = _run(capsys, *argv, *([] if argv == ["--stop"] else
                                          ["--no-browser", "--port", "0"]))
        assert code == 0, (argv, out)
        assert "Several MLflow experiments" not in out, out

