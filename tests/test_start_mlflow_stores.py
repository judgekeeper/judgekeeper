"""`judgekeeper start` on MLflow stores: MLflow's own log lines stay out of what `start` says,
two stores in one folder are both named and can be chosen (a question at a terminal, a path
or --tracking-uri otherwise), and a folder store (`mlruns/`) that was moved or cloned from
another computer is read from its own folder.

MLflow saves where each trace's files are as a full path. A store made on one computer and
copied to another (a cloned repository) points at the first computer's folders, so MLflow
drops every trace it cannot download, with one warning each. judgekeeper reads the trace files
from the store's own folder instead, and says so when they are not there either.

Every store here is made by the installed MLflow in another process (skipped without it).
"""

from __future__ import annotations

import builtins
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import start, start_label
from judgekeeper.again import mlflow as mf
from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store
from judgekeeper.readers.mlflow_store import ALLOW, HINT
from judgekeeper.textio import quote_arg

ROOT = Path(__file__).resolve().parent.parent

STORE = r"""
import os, sys
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri(sys.argv[1])
mlflow.set_experiment(sys.argv[2])
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="anthropic:/claude-haiku-4-5")

@mlflow.trace(name="app")
def app(question):
    return f"answer to {question}"

for i, question in enumerate(["one", "two", "three", "four"]):
    app(question)
    mlflow.flush_trace_async_logging()
    trace_id = mlflow.get_last_active_trace_id()
    mlflow.log_feedback(trace_id=trace_id, name="faithful", value=i % 2 == 0, source=judge)
"""


def _make(folder: Path, uri: str, experiment: str) -> None:
    script = folder / "make_store.py"
    script.write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, str(script), uri, experiment], check=True, cwd=folder,
                   capture_output=True)
    script.unlink()


@pytest.fixture(scope="session")
def made(tmp_path_factory):
    """mlflow.db (experiment qa-db) and mlruns/ (experiment qa-folder), each made in a folder
    that is then removed: both stores point at folders that no longer exist, as a store
    cloned from another computer does."""
    pytest.importorskip("mlflow")
    out = tmp_path_factory.mktemp("made")
    for name, uri, experiment in (("db", "sqlite:///mlflow.db", "qa-db"),
                                  ("folder", "mlruns", "qa-folder")):
        build = tmp_path_factory.mktemp(f"build-{name}")
        _make(build, uri, experiment)
        target = "mlflow.db" if name == "db" else "mlruns"
        if name == "db":
            shutil.copy2(build / target, out / target)
        else:
            shutil.copytree(build / target, out / target)
        shutil.rmtree(build)
    return out


@pytest.fixture
def two(made, tmp_path):
    """A project with both stores."""
    project = tmp_path / "docs-qa"
    shutil.copytree(made, project)
    return project


@pytest.fixture
def folder_only(made, tmp_path):
    project = tmp_path / "docs-qa"
    project.mkdir()
    shutil.copytree(made / "mlruns", project / "mlruns")
    return project


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in (ALLOW, HINT, "MLFLOW_TRACKING_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mlflow_store, "_noted", False)


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out + err


# MLflow's own lines -----------------------------------------------------------------------

def test_mlflow_prints_nothing_of_its_own(folder_only):
    """In a fresh process, as a coding agent runs it (MLflow then prints a hint for agents
    on import), on a moved store (MLflow then warns once per trace)."""
    env = {k: v for k, v in os.environ.items() if k not in (ALLOW, HINT)}
    env.update(CLAUDECODE="1", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-m", "judgekeeper", "start", str(folder_only),
                             "--no-browser"], capture_output=True, text=True, env=env,
                            stdin=subprocess.DEVNULL, timeout=300, check=False)
    out = result.stdout + result.stderr
    assert "Your eval tool: MLflow (mlruns, experiment qa-folder)" in out, out
    assert "mlflow." not in out and "INFO" not in out and "WARNING" not in out, out
    assert "MLFLOW_DISABLE_AGENT_HINT" not in out


def test_the_settings_are_put_back_after_the_read(folder_only):
    logger = logging.getLogger("mlflow")
    level = logger.level
    start.find_judge(folder_only)
    assert HINT not in os.environ and ALLOW not in os.environ
    assert logger.level == level


def test_a_value_the_user_set_is_kept(folder_only, monkeypatch):
    monkeypatch.setenv(HINT, "0")
    start.find_judge(folder_only)
    assert os.environ[HINT] == "0"


def test_quiet_sets_both_for_its_block_only():
    with mlflow_store.quiet():
        assert os.environ[HINT] == "1"
        assert logging.getLogger("mlflow").getEffectiveLevel() >= logging.ERROR
    assert HINT not in os.environ


def test_the_worker_runs_with_mlflow_quiet(tmp_path):
    env = mf.worker_env(str(tmp_path))
    assert env[HINT] == "1" and env["MLFLOW_DISABLE_TELEMETRY"] == "true"
    assert mf.worker_env("sqlite:////tmp/x/mlflow.db")[HINT] == "1"
    text = (ROOT / "src" / "judgekeeper" / "again" / "workers" / "mlflow_worker.py").read_text(
        encoding="utf-8")
    assert 'logging.getLogger("mlflow").setLevel(logging.ERROR)' in text


# A store moved from another computer ------------------------------------------------------

def test_a_moved_folder_store_is_read_from_its_own_folder(folder_only, capsys):
    found = start.find_judge(folder_only, talk=start.Talk())
    out = capsys.readouterr().out
    assert found.tool == "mlflow" and found.metric == "faithful"
    assert sorted(a.output for a in found.pool.answers) == [
        "answer to four", "answer to one", "answer to three", "answer to two"]
    assert "missing" not in out


def test_asking_again_finds_the_traces_of_a_moved_store(folder_only):
    info = mf.assessment_info(start_label.Workspace(folder_only), "faithful")
    assert len(info["traces"]) == 4 and info["uri"] == str(folder_only / "mlruns")


def test_the_worker_reads_a_trace_of_a_moved_store(folder_only):
    spec = importlib.util.spec_from_file_location(
        "mlflow_worker", ROOT / "src" / "judgekeeper" / "again" / "workers" / "mlflow_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    info = mf.assessment_info(start_label.Workspace(folder_only), "faithful")
    uri = info["uri"]
    from mlflow import MlflowClient

    with mlflow_store.folder_store_allowed(uri), mlflow_store.quiet():
        client = MlflowClient(tracking_uri=uri)
        trace = worker.get_trace(client, uri, next(iter(info["traces"].values())), {})
    assert trace.data.spans and trace.info.assessments
    assert str(trace.data.response).startswith(('"answer to', "answer to"))


def _trace_files(project):
    return sorted((project / "mlruns").glob("*/traces/*/artifacts/traces.json"))


def test_trace_files_missing_everywhere_are_said_plainly(folder_only):
    for path in _trace_files(folder_only):
        path.unlink()
    with pytest.raises(start.StartError) as e:
        start.find_judge(folder_only)
    text = str(e.value)
    assert "qa-folder" in text and "mlruns" in text
    assert "the files of its 4 traces are missing" in text
    assert "judge assessments" not in text


def test_some_missing_trace_files_leave_those_answers_out(folder_only, capsys):
    for path in _trace_files(folder_only)[:2]:
        path.unlink()
    found = start.find_judge(folder_only, talk=start.Talk())
    out = capsys.readouterr().out
    assert len(found.pool.answers) == 2
    assert "2 answers were left out: their trace files are missing from mlruns/." in out


# Two stores in one folder -----------------------------------------------------------------

def test_two_stores_without_a_terminal_use_mlflow_db_and_name_the_other(two, capsys):
    code, out = run(capsys, two)
    assert code == start.EXIT_QUESTION  # the labeling question, as for any project
    assert ("Two MLflow stores found: mlflow.db (qa-db) and mlruns/ (qa-folder). Using "
            "mlflow.db.") in out
    assert f"For the other one: judgekeeper start {quote_arg(two / 'mlruns')}" in out
    assert "Your eval tool: MLflow (mlflow.db, experiment qa-db)" in out


def test_two_stores_at_a_terminal_ask(two, capsys, monkeypatch):
    monkeypatch.setattr(start, "_interactive", lambda: True)
    answers = ["2"]
    monkeypatch.setattr(builtins, "input", lambda prompt="": answers.pop(0))
    found = start.find_judge(two, talk=start.Talk(path=two, flags=(str(two),)))
    out = capsys.readouterr().out
    assert "Two MLflow stores found: mlflow.db (qa-db) and mlruns/ (qa-folder)." in out
    assert "  1. mlflow.db (qa-db)\n  2. mlruns/ (qa-folder)" in out
    assert found.store == "mlruns"
    assert f"(Next time: judgekeeper start {quote_arg(two / 'mlruns')})" in out


@pytest.mark.parametrize("name, experiment", [("mlruns", "qa-folder"),
                                              ("mlflow.db", "qa-db")])
def test_start_reads_the_store_it_is_given(two, capsys, name, experiment):
    found = start.find_judge(two / name, talk=start.Talk())
    out = capsys.readouterr().out
    assert found.root == two.resolve()  # .judgekeeper/ goes next to the store, not inside
    assert found.store == name
    assert "Two MLflow stores" not in out
    assert f"Your eval tool: MLflow ({name}, experiment {experiment})" in out


def test_the_workspace_of_a_store_path_is_the_project(two):
    from judgekeeper import start_again

    assert start_again._project(two / "mlruns") == two.resolve()
    assert start.known_tool(two / "mlruns") == "mlflow"


def test_the_tracking_uri_variable_picks_the_store(two, capsys, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", str(two / "mlruns"))
    found = start.find_judge(two, talk=start.Talk())
    out = capsys.readouterr().out
    assert found.store == "mlruns" and "Two MLflow stores" not in out


@pytest.mark.parametrize("uri", ["sqlite:///{db}", "{folder}", "{folder_uri}"])
def test_the_tracking_uri_flag_picks_the_store(two, capsys, uri):
    uri = uri.format(db=(two / "mlflow.db").as_posix(), folder=(two / "mlruns").as_posix(),
                     folder_uri=(two / "mlruns").as_uri())
    found = start.find_judge(two, tracking_uri=uri, talk=start.Talk())
    assert found.store == ("mlflow.db" if "sqlite" in uri else "mlruns")
    assert "Two MLflow stores" not in capsys.readouterr().out


def test_a_server_tracking_uri_says_what_start_reads(two, capsys):
    code, out = run(capsys, two, "--tracking-uri", "http://localhost:5000")
    assert code == start.EXIT_USAGE
    assert "judgekeeper start reads an MLflow store in your project" in out
    assert "judgekeeper import mlflow --tracking-uri http://localhost:5000" in out


def test_the_experiment_picks_the_store_that_has_it(two, capsys):
    found = start.find_judge(two, experiment="qa-folder", talk=start.Talk())
    out = capsys.readouterr().out
    assert found.store == "mlruns" and "Two MLflow stores" not in out


def test_an_unknown_experiment_names_each_store_and_its_experiments(two):
    with pytest.raises(start.StartError) as e:
        start.find_judge(two, experiment="qa-mlruns")
    assert str(e.value) == ("no MLflow experiment named 'qa-mlruns' in mlflow.db (its "
                            "experiments: qa-db) or mlruns/ (its experiments: qa-folder)")


def test_an_unknown_experiment_in_one_store(folder_only):
    with pytest.raises(start.StartError) as e:
        start.find_judge(folder_only, experiment="nope")
    assert str(e.value) == ("no MLflow experiment named 'nope' in mlruns/ (its experiments: "
                            "qa-folder)")


def test_the_chosen_store_is_kept_for_asking_again(two, capsys):
    found = start.find_judge(two / "mlruns", talk=start.Talk())
    ws = start_label.prepare(found, say=lambda line="": None)
    assert ws.data()["mlflow_store"] == "mlruns"
    info = mf.assessment_info(ws, "faithful")
    assert info["uri"] == str(two / "mlruns")


def test_a_re_check_keeps_the_chosen_store(two, capsys):
    found = start.find_judge(two / "mlruns", talk=start.Talk())
    start_label.prepare(found, say=lambda line="": None)
    capsys.readouterr()
    again = start.find_judge(two, store="mlruns", talk=start.Talk())
    assert again.store == "mlruns"
    assert "Two MLflow stores" not in capsys.readouterr().out
