"""An mlflow.db never makes MLflow fetch a trace's data from elsewhere.

Each trace in an mlflow.db names where its data is kept (its `mlflow.artifactLocation` tag, and
`mlflow.trace.archiveLocation` for an archived one). MLflow downloads the data from there, with
the MLflow login in the environment, for any trace whose spans are not in the database itself.
judgekeeper reads only its own temporary copy of mlflow.db, and in that copy every location is
pointed into the copy's own folder unless it is a local folder inside the folder that holds
mlflow.db. Those traces are read from the short previews the store keeps, and said. While
judgekeeper reads a store, and in every MLflow worker, the MLflow login is not in the
environment: a local store never needs it.

Every store is made by the installed MLflow in another process (skipped without it); a local
listener counts every request that would have gone elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from judgekeeper import again, keys, start, start_label
from judgekeeper.again import AgainOptions
from judgekeeper.again import mlflow as mf
from judgekeeper.readers import mlflow_store
from judgekeeper.start_label import StartSession
from tests.start_projects import save_result

LOGIN = ("MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD", "MLFLOW_TRACKING_TOKEN",
         "MLFLOW_TRACKING_CLIENT_CERT_PATH", "MLFLOW_TRACKING_SERVER_CERT_PATH",
         "MLFLOW_TRACKING_INSECURE_TLS")
PREVIEWS = "36 answers read from their short previews; their full data is stored elsewhere."
N = 36

STORE = r"""
import os, sys
from pathlib import Path
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.create_experiment("qa", artifact_location=Path("mlartifacts").resolve().as_uri())
mlflow.set_experiment("qa")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1-mini")
for i in range(int(sys.argv[1])):
    with mlflow.start_span(name="app") as span:
        span.set_inputs({"question": f"Question {i}?"})
        span.set_outputs({"answer": f"Answer {i}."})
        trace_id = span.trace_id
    mlflow.flush_trace_async_logging()
    mlflow.log_feedback(trace_id=trace_id, name="correctness", value=i < 20, rationale="r",
                        source=judge)
mlflow.flush_trace_async_logging()
"""

OLDER = r"""
import json, os, sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
from mlflow import MlflowClient

# As an older MLflow kept them: each trace's spans as a file in its artifact folder
client = MlflowClient("sqlite:///mlflow.db")
exp = client.get_experiment_by_name("qa").experiment_id
for trace in client.search_traces(locations=[exp], max_results=1000):
    folder = Path(url2pathname(urlparse(trace.info.tags["mlflow.artifactLocation"]).path))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "traces.json").write_text(json.dumps(trace.data.to_dict()), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """mlflow.db with N judged traces whose spans are in the database (MLflow 3.17's way), and
    the same store as an older MLflow kept it, spans as files under ./mlartifacts."""
    pytest.importorskip("mlflow")
    build = tmp_path_factory.mktemp("build")
    (build / "make.py").write_text(STORE, encoding="utf-8")
    subprocess.run([sys.executable, "make.py", str(N)], check=True, cwd=build,
                   capture_output=True)
    (build / "older.py").write_text(OLDER, encoding="utf-8")
    subprocess.run([sys.executable, "older.py"], check=True, cwd=build, capture_output=True)
    return build


def edit(db: Path, *statements) -> None:
    """Run each statement, a text or (text, its parameters), on the store."""
    with closing(sqlite3.connect(db)) as con:
        for statement in statements:
            con.execute(*((statement,) if isinstance(statement, str) else statement))
        con.commit()


def _project(made: Path, root: Path) -> Path:
    """A project holding the store, its trace locations moved to where it now is."""
    shutil.copy2(made / "mlflow.db", root / "mlflow.db")
    shutil.copytree(made / "mlartifacts", root / "mlartifacts")
    edit(root / "mlflow.db", (("update trace_tags set value = replace(value, ?, ?) where key = "
                              "'mlflow.artifactLocation'"),
                              (made.resolve().as_uri(), root.resolve().as_uri())))
    return root


def _elsewhere(db: Path, address: str) -> None:
    """The hostile edit: no spans in the database, each trace's data "on" another server."""
    edit(db, (("update trace_tags set value = ? || request_id where key = "
              "'mlflow.artifactLocation'"), (f"{address}/api/2.0/mlflow-artifacts/artifacts/x/",)),
         "delete from trace_tags where key = 'mlflow.trace.spansLocation'", "delete from spans")


@pytest.fixture
def listener(monkeypatch):
    """A local HTTP server that keeps every request it gets: (path, Authorization)."""
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
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1")
    yield f"http://127.0.0.1:{server.server_address[1]}", asked
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    """The MLflow login a person may have in their shell for a server, and a judge key."""
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    for name in ("MLFLOW_TRACKING_URI", mlflow_store.ALLOW):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MLFLOW_TRACKING_USERNAME", "someone")
    monkeypatch.setenv("MLFLOW_TRACKING_PASSWORD", "not-a-real-password")
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "not-a-real-token")
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    yield
    mlflow_store.remove_copies()


def _marked(root: Path):
    found = start.find_judge(root)
    ws = start_label.prepare(found, say=lambda line="": None)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=lambda line="": None)
    return ws


# A store whose traces point at a server --------------------------------------------------------

def test_find_fetches_nothing_and_reads_the_previews(made, tmp_path, listener, capsys):
    address, asked = listener
    root = _project(made, tmp_path)
    _elsewhere(root / "mlflow.db", address)
    before = (root / "mlflow.db").read_bytes()
    found = start.find_judge(root, talk=start.Talk())
    out = " ".join(capsys.readouterr().out.split())
    assert asked == []
    assert len(found.pool.answers) == N
    assert PREVIEWS in out, out
    assert (root / "mlflow.db").read_bytes() == before  # the person's store: same bytes


def test_the_plan_and_the_run_fetch_nothing(made, tmp_path, listener, stubs, monkeypatch):
    from tests.test_again_run import ask_again

    address, asked = listener
    root = _project(made, tmp_path)
    ws = _marked(root)
    _elsewhere(root / "mlflow.db", address)
    before = (root / "mlflow.db").read_bytes()
    mlflow_store.remove_copies()
    envs = []
    real = again.run_process

    def spy(argv, cwd, env=None, timeout=None):
        envs.append(dict(env or {}))
        return real(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", spy)
    plan = again.make_plan(ws, AgainOptions(python=sys.executable))
    assert asked == []
    assert plan.status != again.CANT, plan.why
    assert plan.answers == N
    code, out = ask_again(ws, "--python", sys.executable, "--times", "1")
    assert code == 0, out
    assert asked == []
    assert envs and all(not set(LOGIN) & set(env) for env in envs)
    assert all(env.get("OPENAI_API_KEY") == "x" * 30 for env in envs)  # the judge's own key
    assert (root / "mlflow.db").read_bytes() == before


def test_the_mlflow_login_is_out_of_the_environment_while_a_store_is_read(made, tmp_path,
                                                                       monkeypatch):
    root = _project(made, tmp_path)
    seen = []
    real = mlflow_store._traces

    def spy(*args, **kwargs):
        seen.append({n for n in LOGIN if n in os.environ})
        yield from real(*args, **kwargs)

    monkeypatch.setattr(mlflow_store, "_traces", spy)
    start.find_judge(root)
    mf.assessment_info(start_label.Workspace(root), "correctness")
    assert seen and all(s == set() for s in seen)
    assert os.environ["MLFLOW_TRACKING_PASSWORD"] == "not-a-real-password"  # put back after


def test_the_worker_reads_a_trace_kept_elsewhere_from_the_store_alone(made, tmp_path,
                                                                     listener):
    address, asked = listener
    root = _project(made, tmp_path)
    _elsewhere(root / "mlflow.db", address)
    info = mf.assessment_info(start_label.Workspace(root), "correctness")
    spec = importlib.util.spec_from_file_location(
        "jk_mlflow_worker", Path(again.__file__).parent / "workers" / "mlflow_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=info["uri"])
    trace_id = next(iter(info["traces"].values()))
    trace = worker.get_trace(client, info["uri"], trace_id, {})
    assert asked == []
    assert trace.info.trace_id == trace_id and not trace.data.spans
    assert trace.info.assessments  # the expectations come from the trace's own assessments


def test_a_trigger_in_the_store_cant_put_a_location_back(made, tmp_path, listener):
    address, asked = listener
    root = _project(made, tmp_path)
    _elsewhere(root / "mlflow.db", address)
    edit(root / "mlflow.db", "create trigger back after update on trace_tags begin "
         f"update trace_tags set value = '{address}/x/' where key = new.key and "
         "request_id = new.request_id; end")
    found = start.find_judge(root)
    assert asked == [] and len(found.pool.answers) == N


# Which locations are kept ----------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "http://127.0.0.1:9/x", "https://example.invalid/x", "s3://bucket/x", "gs://bucket/x",
    "wasbs://c@a.blob.core.windows.net/x", "mlflow-artifacts:/1/traces/x", "dbfs:/x",
    "file://server/share/x", r"\\server\share\x", "//server/share/x", "/elsewhere/x",
    "file:///elsewhere/x", "inside/../../x", "",
])
def test_a_location_outside_the_stores_folder_is_not_kept(tmp_path, value):
    assert mlflow_store.kept_location(value, tmp_path) is None


def test_a_location_inside_the_stores_folder_is_kept(tmp_path):
    inside = tmp_path / "mlartifacts" / "traces" / "tr-1" / "artifacts"
    want = inside.resolve()
    assert mlflow_store.kept_location(inside.as_uri(), tmp_path) == want
    assert mlflow_store.kept_location(str(inside), tmp_path) == want
    assert mlflow_store.kept_location("mlartifacts/traces/tr-1/artifacts", tmp_path) == want


def test_a_link_inside_the_stores_folder_that_leads_out_is_not_kept(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "store").mkdir()
    try:
        (tmp_path / "store" / "mlartifacts").symlink_to(tmp_path / "out")
    except OSError:
        pytest.skip("no symbolic links here")
    assert mlflow_store.kept_location("mlartifacts/x", tmp_path / "store") is None


# An older store keeps its spans as files next to mlflow.db -------------------------------------

def test_an_older_store_with_spans_under_mlartifacts_is_read_in_full(made, tmp_path, listener,
                                                                   capsys):
    _address, asked = listener
    root = _project(made, tmp_path)
    edit(root / "mlflow.db", "delete from trace_tags where key = 'mlflow.trace.spansLocation'",
         "delete from spans")
    found = start.find_judge(root, talk=start.Talk())
    out = " ".join(capsys.readouterr().out.split())
    assert len(found.pool.answers) == N and "short previews" not in out, out
    uri = mlflow_store.store_uri(root / "mlflow.db")
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=uri)
    exp = client.get_experiment_by_name("qa").experiment_id
    with mlflow_store.quiet():
        traces = list(mlflow_store._traces(client, exp))
    assert len(traces) == N and all(t.data.spans for t in traces)
    info = mf.assessment_info(start_label.Workspace(root), "correctness")
    assert len(info["traces"]) == N
    assert asked == []


def test_a_store_with_spans_in_the_database_is_read_in_full(made, tmp_path):
    root = _project(made, tmp_path)
    shutil.rmtree(root / "mlartifacts")
    uri = mlflow_store.store_uri(root / "mlflow.db")
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=uri)
    exp = client.get_experiment_by_name("qa").experiment_id
    with mlflow_store.quiet():
        traces = list(mlflow_store._traces(client, exp))
    assert len(traces) == N and all(t.data.spans for t in traces)
    assert json.loads(json.dumps(traces[0].data.to_dict()))["spans"]
