"""MLflow folder stores (`mlruns/`) read with MLflow 3.16 and later.

From MLflow 3.16 a folder store opens only when MLFLOW_ALLOW_FILE_STORE=true is set. When
judgekeeper reads a folder store, it sets the variable only for that read: around its own
MLflow calls (then removes it again, also after an error), and in the asking-again worker's
environment only. It says so once per run. A value the user set is left as it is, with
nothing said. mlflow.db and server stores are never given it. The folder stays byte for byte
as it was.
"""

from __future__ import annotations

import os

import pytest

from judgekeeper import start, start_label
from judgekeeper.again import mlflow as mf
from judgekeeper.readers import mlflow_store
from judgekeeper.readers.mlflow_store import ALLOW, FOLDER_NOTE

NOTE = ("Reading your mlruns/ folder with MLflow's folder-store setting switched on for this "
        "read only (MLFLOW_ALLOW_FILE_STORE).")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """No value from the shell, and a run that has said nothing yet."""
    monkeypatch.delenv(ALLOW, raising=False)
    monkeypatch.setattr(mlflow_store, "_noted", False)


def _state(folder):
    return {p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*")) if p.is_file()}


# The setting, around a read ---------------------------------------------------------------

def test_the_line_says_what_it_does():
    assert FOLDER_NOTE == NOTE


def test_set_for_the_read_then_removed(tmp_path):
    said = []
    with mlflow_store.folder_store_allowed(str(tmp_path), say=said.append):
        assert os.environ[ALLOW] == "true"
    assert ALLOW not in os.environ
    assert said == [NOTE]


def test_removed_after_an_error_too(tmp_path):
    with pytest.raises(RuntimeError), mlflow_store.folder_store_allowed(str(tmp_path)):
        raise RuntimeError("MLflow failed")
    assert ALLOW not in os.environ


def test_said_once_per_run(tmp_path):
    said = []
    for _ in range(3):
        with mlflow_store.folder_store_allowed(str(tmp_path), say=said.append):
            pass
    assert said == [NOTE]


@pytest.mark.parametrize("value", ["true", "false", "1", ""])
def test_a_value_the_user_set_is_kept_and_nothing_is_said(tmp_path, monkeypatch, value):
    monkeypatch.setenv(ALLOW, value)
    said = []
    with mlflow_store.folder_store_allowed(str(tmp_path), say=said.append):
        assert os.environ[ALLOW] == value
    assert os.environ[ALLOW] == value and said == []


@pytest.mark.parametrize("uri", ["sqlite:////tmp/judgekeeper-mlflow-x/mlflow.db",
                                 "http://localhost:5000", "databricks", None])
def test_never_for_mlflow_db_or_a_server(uri):
    said = []
    with mlflow_store.folder_store_allowed(uri, say=said.append):
        assert ALLOW not in os.environ
    assert said == []


def test_a_folder_given_as_a_file_address_counts(tmp_path):
    assert mlflow_store.is_folder_store(str(tmp_path))
    assert mlflow_store.is_folder_store(tmp_path.as_uri())
    assert not mlflow_store.is_folder_store(str(tmp_path / "missing"))
    assert not mlflow_store.is_folder_store(f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")


def test_the_worker_gets_it_in_its_own_environment_only(tmp_path, monkeypatch):
    env = mf.worker_env(str(tmp_path))
    assert env[ALLOW] == "true" and env["MLFLOW_DISABLE_TELEMETRY"] == "true"
    assert ALLOW not in os.environ
    assert ALLOW not in mf.worker_env("sqlite:////tmp/x/mlflow.db")
    monkeypatch.setenv(ALLOW, "false")  # the user's own value reaches the worker as it is
    assert ALLOW not in mf.worker_env(str(tmp_path))


# A real mlruns/ folder made by the installed MLflow -------------------------------------------

@pytest.fixture
def project(tmp_path):
    from tests.conftest import build_mlflow_folder_store

    build_mlflow_folder_store(tmp_path / "mlruns")
    return tmp_path


def test_start_reads_a_real_folder_store_and_leaves_it_as_it_was(project, capsys):
    before = _state(project / "mlruns")
    talk = start.Talk()
    found = start.find_judge(project, talk=talk)
    out = capsys.readouterr().out
    assert found.tool == "mlflow" and found.metric == "helpful"
    assert found.judge == "helpful with openai:/gpt-4.1"
    assert len(found.pool.answers) == 4
    lines = start.found_lines(found)
    assert "  Eval tool       MLflow" in lines
    assert "  Results file    mlruns (experiment folder-store)" in lines
    assert out.count(NOTE) == 1
    assert ALLOW not in os.environ
    assert _state(project / "mlruns") == before


def test_start_says_nothing_when_the_user_set_it(project, capsys, monkeypatch):
    monkeypatch.setenv(ALLOW, "true")
    start.find_judge(project, talk=start.Talk())
    assert NOTE not in capsys.readouterr().out
    assert os.environ[ALLOW] == "true"


def test_asking_again_reads_a_real_folder_store(project):
    before = _state(project / "mlruns")
    info = mf.assessment_info(start_label.Workspace(project), "helpful")
    assert info["source_id"] == "openai:/gpt-4.1" and len(info["traces"]) == 4
    assert info["uri"] == str(project / "mlruns")
    assert ALLOW not in os.environ
    assert _state(project / "mlruns") == before


def test_the_asking_again_plan_gives_the_worker_the_setting(project, monkeypatch):
    found = start.find_judge(project)
    ws = start_label.prepare(found, say=lambda line="": None)
    seen = []

    def worker(tool, python, job, cwd, env=None, **kwargs):
        seen.append((job.get("uri"), dict(env or {})))
        return {"ok": False, "error": "stopped here by the test"}

    monkeypatch.setattr("judgekeeper.again.run_worker", worker)
    answers = [{"id": a.id, "input": a.input, "output": a.output} for a in found.pool.answers]
    from judgekeeper.again import AgainOptions

    mf.plan(ws, answers, AgainOptions(times=1), talk=None, dry=True)
    ((uri, env),) = seen
    assert uri == str(project / "mlruns") and env[ALLOW] == "true"
    assert ALLOW not in os.environ
