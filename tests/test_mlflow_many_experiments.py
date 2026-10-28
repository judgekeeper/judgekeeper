"""A store with more experiments than MLflow returns in one call (1,000): every one is read,
up to judgekeeper's limit (MAX_EXPERIMENTS, set above this store's size here; past it the read
stops and says so). The judged experiments are the oldest, behind 2,000 newer empty ones. Made
by the installed MLflow in another process (skipped without it); the empty ones are added to
the database."""

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
    monkeypatch.setattr(mlflow_store, "MAX_EXPERIMENTS", 3 * mlflow_store.EXPERIMENT_PAGE)
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


def test_past_the_limit_the_read_stops_and_says_so(project, capsys, monkeypatch):
    monkeypatch.setattr(mlflow_store, "MAX_EXPERIMENTS", 1000)
    code = main(["--no-browser", "--port", "0"])
    out = " ".join("".join(capsys.readouterr()).split())
    assert code == 2, out
    assert "mlflow.db has more than 1,000 experiments" in out, out


# Lists of experiments are capped ---------------------------------------------------------------

def test_an_experiment_not_there_lists_at_most_20_names(tmp_path):
    from judgekeeper import find, start

    store = find.Result("mlflow", tmp_path / "mlflow.db", "mlflow.db", 1)
    names = [f"exp{i:02d}" for i in range(25)]
    said = str(start._no_experiment("nope", [(store, names)]))
    assert "exp19" in said and "exp20" not in said and "and 5 more" in said, said


def test_the_line_naming_each_stores_experiments_lists_at_most_20(tmp_path, monkeypatch,
                                                                  capsys):
    from judgekeeper import find, start
    from judgekeeper.readers import mlflow_store as store_module

    (tmp_path / "sub").mkdir()
    stores = []
    for rel in ("mlflow.db", "sub/mlflow.db"):
        (tmp_path / rel).write_bytes(b"")
        stores.append(find.Result("mlflow", tmp_path / rel, rel, 0))
    names = [f"exp{i:02d}" for i in range(25)]
    monkeypatch.setattr(store_module, "store_uri", lambda path, say=None: "sqlite:///x.db")
    monkeypatch.setattr(store_module, "experiments_with_traces", lambda uri: names)
    monkeypatch.setattr(start, "_has", lambda name: True)
    monkeypatch.setattr(start, "_interactive", lambda: False)
    start._choose_store(start.Talk(), tmp_path, stores, None, None)
    said = " ".join(capsys.readouterr().out.split())
    assert said.count("and 5 more") == 2 and "exp20" not in said, said
