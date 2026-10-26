"""`judgekeeper` on MLflow stores: MLflow's own log lines stay out of what judgekeeper says,
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
from types import SimpleNamespace

import pytest

from judgekeeper import start, start_label
from judgekeeper.again import mlflow as mf
from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store
from judgekeeper.readers.mlflow_store import ALLOW, HINT
from judgekeeper.textio import quote_arg
from tests.test_front import assert_one_next_at_the_end

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
    code = main([*map(str, argv)])
    out, err = capsys.readouterr()
    return code, out + err


# MLflow's own lines -----------------------------------------------------------------------

def test_mlflow_prints_nothing_of_its_own(folder_only):
    """In a fresh process, as a coding agent runs it (MLflow then prints a hint for agents
    on import), on a moved store (MLflow then warns once per trace)."""
    env = {k: v for k, v in os.environ.items() if k not in (ALLOW, HINT)}
    env.update(CLAUDECODE="1", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-m", "judgekeeper", str(folder_only),
                             "--no-browser"], capture_output=True, text=True, env=env,
                            stdin=subprocess.DEVNULL, timeout=300, check=False)
    out = result.stdout + result.stderr
    assert "Store:           mlruns, experiment qa-folder" in out, out
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


# `judgekeeper` (no command): two stores are a question, answered by naming one -------------

def test_judgekeeper_asks_which_store_without_a_terminal(two, capsys, monkeypatch):
    code = main([str(two)])
    out = capsys.readouterr().out
    assert code == 3
    assert "Two MLflow stores found" in out
    db, folder = (quote_arg((two / n).as_posix()) for n in ("mlflow.db", "mlruns"))  # as listed
    assert assert_one_next_at_the_end(out) == (
        f"Next: choose which MLflow store to read (mlflow.db, mlruns), then run "
        f"`judgekeeper {db}` or `judgekeeper {folder}`.")
    monkeypatch.chdir(two)  # a store given by path: .judgekeeper/ is made where it runs
    code = main([str(two / "mlruns")])
    out = capsys.readouterr().out
    assert code in (0, 3) and "Eval tool:       MLflow" in out
    assert "Store:           mlruns, experiment qa-folder" in out
    assert "Two MLflow stores" not in out


def test_judgekeeper_asks_which_store_at_a_terminal_and_saves_it(two, capsys, monkeypatch):
    import tomllib

    answers = ["2", ""]  # mlruns; save
    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt="": answers.pop(0))
    main([str(two)])
    out = capsys.readouterr().out
    assert "Eval tool:       MLflow" in out and "Store:           mlruns, experiment qa-folder" in out
    saved = tomllib.loads((two / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved == {"source": "mlflow", "file": "mlruns"}
    monkeypatch.setattr(start, "_interactive", lambda: False)
    main([str(two)])  # asked once: read from judgekeeper.toml now
    assert "Store:           mlruns, " in capsys.readouterr().out


# A very big experiment: the newest traces, said ----------------------------------------------

def test_a_big_experiment_is_read_up_to_the_newest_traces_and_said(made, tmp_path, capsys,
                                                                   monkeypatch):
    monkeypatch.setattr(mlflow_store, "MAX_TRACES", 3)
    project = tmp_path / "docs-qa"
    project.mkdir()
    shutil.copy2(made / "mlflow.db", project / "mlflow.db")
    runs = mlflow_store.read_mlflow("qa-db", tracking_uri=f"sqlite:///{project / 'mlflow.db'}")
    assert sum(len(recs) for label, recs in runs if label != "human assessments") == 3
    _, out = run(capsys, project, "--yes", "--no-browser")
    assert ("qa-db has more than 3 traces: judgekeeper read the newest 3 (reading every "
            "trace of a very big experiment takes minutes).") in " ".join(out.split())


def test_the_limit_is_thirty_thousand():
    assert mlflow_store.MAX_TRACES == 30_000


# Reading a folder store reads only its own files --------------------------------------------


@pytest.fixture
def listener():
    """A local HTTP server that keeps every request it gets: (path, Authorization)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    asked = []

    class Keep(BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append((self.path, self.headers.get("Authorization")))
            self.send_response(404)
            self.end_headers()

        do_HEAD = do_POST = do_PUT = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Keep)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", asked
    server.shutdown()
    server.server_close()


def test_a_missing_trace_file_is_never_fetched_from_where_the_store_points(folder_only,
                                                                           listener):
    """A trace without its traces.json whose mlflow.artifactLocation names a server: MLflow
    would download it from there, with the MLflow login in the environment. It is left out."""
    address, asked = listener
    trace = _trace_files(folder_only)[0].parent.parent
    (trace / "artifacts" / "traces.json").unlink()
    (trace / "tags" / "mlflow.artifactLocation").write_text(f"{address}/{trace.name}",
                                                            encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in (ALLOW, HINT)}
    env.update(PYTHONPATH=str(ROOT / "src"), MLFLOW_TRACKING_USERNAME="someone",
               MLFLOW_TRACKING_PASSWORD="not-a-real-password", NO_PROXY="127.0.0.1",
               no_proxy="127.0.0.1")
    result = subprocess.run([sys.executable, "-m", "judgekeeper", str(folder_only),
                             "--no-browser"], capture_output=True, text=True, env=env,
                            stdin=subprocess.DEVNULL, timeout=300, check=False)
    out = " ".join((result.stdout + result.stderr).split())
    assert asked == []
    assert "1 answer was left out: their trace files are missing from mlruns/." in out, out


class _Page(list):
    token = None


class _Client:
    """search_traces (without spans) finds traces with these ids; get_trace is kept."""

    def __init__(self, ids):
        self.ids, self.fetched = ids, []

    def search_traces(self, locations, max_results=100, page_token=None, include_spans=True):
        return _Page(SimpleNamespace(info=SimpleNamespace(trace_id=i)) for i in self.ids)

    def get_trace(self, trace_id):
        self.fetched.append(trace_id)
        raise LookupError(trace_id)


GOOD_ID = "tr-" + "0123456789abcdef" * 2
OLD_ID = "fedcba9876543210" * 2  # MLflow 2's request ids
OUTSIDE = "outside the experiment"  # stands for the absolute path of a folder outside it


def _plant(experiment, trace_id):
    path = experiment.joinpath("traces", trace_id, "artifacts", "traces.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # a name this system can't hold (Windows: tr-*): nothing to plant
        return
    path.write_text('{"spans": []}', encoding="utf-8")


@pytest.mark.parametrize("trace_id", ["../../../outside", "..\\..\\..\\outside", OUTSIDE,
                                      "tr-0a/../../../outside", "tr-*", "TR-0A", "tr-"])
def test_a_trace_id_is_a_path_only_in_mlflow_shape(tmp_path, trace_id):
    """A trace id from the store that is not MLflow's shape (tr- and hex, or 32 hex) is never
    joined into a path, on any system: the trace is left out, even when a file is where it
    points. The traces beside it are read."""
    pytest.importorskip("mlflow")
    if trace_id == OUTSIDE:
        trace_id = str(tmp_path / "outside")
    experiment = tmp_path / "mlruns" / "1"
    for each in (trace_id, GOOD_ID, OLD_ID):
        _plant(experiment, each)
    client, missing = _Client([trace_id, GOOD_ID, OLD_ID]), []
    read = mlflow_store._traces(client, "1", tmp_path / "mlruns", missing)
    assert [t.info.trace_id for t in read] == [GOOD_ID, OLD_ID]
    assert missing == [trace_id] and client.fetched == []


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links")
def test_a_trace_folder_that_leads_outside_the_experiment_is_left_out(tmp_path):
    pytest.importorskip("mlflow")
    outside = tmp_path / "outside" / "artifacts"
    outside.mkdir(parents=True)
    (outside / "traces.json").write_text('{"spans": []}', encoding="utf-8")
    traces = tmp_path / "mlruns" / "1" / "traces"
    traces.mkdir(parents=True)
    try:
        (traces / GOOD_ID).symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need rights here")
    client, missing = _Client([GOOD_ID]), []
    assert list(mlflow_store._traces(client, "1", tmp_path / "mlruns", missing)) == []
    assert missing == [GOOD_ID] and client.fetched == []


def _worker():
    spec = importlib.util.spec_from_file_location(
        "mlflow_worker", ROOT / "src" / "judgekeeper" / "again" / "workers" / "mlflow_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


class _WorkerClient(_Client):
    def search_traces(self, locations, max_results=100, page_token=None, include_spans=True):
        return _Page(SimpleNamespace(trace_id=i) for i in self.ids)


@pytest.mark.parametrize("trace_id", ["../../outside", "..\\..\\outside", "*"])
def test_the_worker_uses_a_trace_id_in_a_path_only_in_mlflow_shape(tmp_path, trace_id):
    pytest.importorskip("mlflow")
    store = tmp_path / "mlruns"
    (store / "1" / "traces" / GOOD_ID / "artifacts").mkdir(parents=True)
    (store / "1" / "traces" / GOOD_ID / "artifacts" / "traces.json").write_text(
        '{"spans": []}', encoding="utf-8")
    if trace_id != "*":
        planted = store.joinpath("1", "traces", trace_id, "artifacts", "traces.json")
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text('{"spans": []}', encoding="utf-8")
    with pytest.raises(LookupError):
        _worker().get_trace(_WorkerClient([trace_id]), str(store), trace_id, {})


# A damaged store ---------------------------------------------------------------------------


def test_a_meta_yaml_mlflow_refuses_is_a_damaged_store(folder_only, capsys):
    """MLflow reads meta.yaml with yaml.safe_load: a python tag is refused (never run). The
    words and exit code of a damaged mlflow.db (a file it can't read)."""
    experiment = next(p for p in (folder_only / "mlruns").iterdir()
                      if p.is_dir() and p.name not in ("0", ".trash"))
    (experiment / "meta.yaml").write_text(
        "artifact_location: !!python/object/apply:os.getcwd []\nname: qa-folder\n",
        encoding="utf-8")
    code, out = run(capsys, folder_only, "--no-browser")
    assert code == 2, out
    assert "mlruns can't be read: it's damaged. Save it again from MLflow." in out
    assert "please report" not in out.lower() and "didn't expect" not in out
