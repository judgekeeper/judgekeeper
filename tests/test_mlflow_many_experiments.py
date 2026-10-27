"""A store with more experiments than MLflow returns in one call (1,000): every one is read.
The judged experiments are the oldest, behind 2,000 newer empty ones. Made by the installed
MLflow in another process (skipped without it); the empty ones are added to the database."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store

JUDGED = 3
EMPTY = 2000

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

for e in range(%d):
    mlflow.set_experiment(f"judged{e}")
    for i in range(2):
        app(f"question {e}-{i}")
        mlflow.flush_trace_async_logging()
        mlflow.log_feedback(trace_id=mlflow.get_last_active_trace_id(), name="helpful",
                            value=i == 0, source=judge)
"""


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    pytest.importorskip("mlflow")
    out = tmp_path_factory.mktemp("many")
    (out / "make_store.py").write_text(STORE % JUDGED, encoding="utf-8")
    subprocess.run([sys.executable, "make_store.py"], check=True, cwd=out, capture_output=True)
    with closing(sqlite3.connect(out / "mlflow.db")) as con:
        top, location, created = con.execute(
            "select experiment_id, artifact_location, creation_time from experiments "
            "order by experiment_id desc limit 1").fetchone()
        con.executemany(
            "insert into experiments values (?, ?, ?, 'active', ?, ?, 'default')",
            [(top + 1 + i, f"empty{i:04d}", f"{location}-{i}", created + 1 + i, created + 1 + i)
             for i in range(EMPTY)])
        con.commit()
    return out / "mlflow.db"


@pytest.fixture
def project(made, tmp_path, monkeypatch):
    root = tmp_path / "docs-qa"
    root.mkdir()
    shutil.copy2(made, root / "mlflow.db")
    monkeypatch.chdir(root)
    yield root
    mlflow_store.remove_copies()


def test_judged_experiments_behind_2000_newer_ones_are_found(project, capsys):
    code = main(["--no-browser", "--port", "0"])
    out = " ".join("".join(capsys.readouterr()).split())
    assert code == 3, out  # no terminal to choose one at
    assert "Several MLflow experiments have LLM-as-a-judge results" in out, out
    assert all(f"judged{e}" in out for e in range(JUDGED)), out
    assert "holds no decisions" not in out


def test_the_experiments_with_traces_are_found_on_every_page(project):
    uri = mlflow_store.store_uri(project / "mlflow.db")
    with mlflow_store.quiet():
        names = mlflow_store.experiments_with_traces(uri)
    assert sorted(names) == [f"judged{e}" for e in range(JUDGED)]
