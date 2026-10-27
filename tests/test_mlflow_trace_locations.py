"""An mlflow.db never makes MLflow fetch a trace's data from elsewhere.

Each trace in an mlflow.db names where its data is kept (its `mlflow.artifactLocation` tag, and
`mlflow.trace.archiveLocation` for an archived one). MLflow downloads the data from there, with
the MLflow login in the environment, for any trace whose spans are not in the database itself.
judgekeeper reads only its own temporary copy of mlflow.db, and in that copy every location is
pointed into the copy's own folder unless it is a local folder inside the folder that holds
mlflow.db. Those traces are read from the short previews the store keeps, and said. While
judgekeeper reads a store (also when `judgekeeper check` reads it again), the MLflow login is
not in the environment: a local store never needs it.

Every store is made by the installed MLflow in another process (skipped without it); a local
listener counts every request that would have gone elsewhere.
"""

from __future__ import annotations

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

from judgekeeper import keys, start, start_label
from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store
from judgekeeper.records import Damaged
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
    for name in keys.key_names():
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


def test_check_reads_the_store_again_and_fetches_nothing(made, tmp_path, listener, monkeypatch,
                                                       capsys):
    address, asked = listener
    root = _project(made, tmp_path)
    _marked(root)
    _elsewhere(root / "mlflow.db", address)
    before = (root / "mlflow.db").read_bytes()
    mlflow_store.remove_copies()
    monkeypatch.chdir(root)
    capsys.readouterr()
    code = main(["check"])
    out = " ".join(capsys.readouterr().out.split())
    assert asked == []
    assert code == 0 and "Your LLM-as-a-judge has not changed" in out, out
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
    assert seen and all(s == set() for s in seen)
    assert os.environ["MLFLOW_TRACKING_PASSWORD"] == "not-a-real-password"  # put back after


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


# A trigger in the store ------------------------------------------------------------------------

def _no_locations(db: Path, address: str, trigger: str) -> None:
    """No location rows, the default experiment gone (MLflow adds it again when it opens the
    store), and a trigger that names `address` as every trace's location when it fires."""
    edit(db, "delete from trace_tags where key = 'mlflow.artifactLocation'",
         "delete from experiments where experiment_id = 0",
         f"create trigger jk_poc {trigger} begin "
         "delete from trace_tags where key = 'mlflow.trace.spansLocation'; "
         "insert into trace_tags(key, value, request_id) select 'mlflow.artifactLocation', "
         f"'{address}/trig', request_id from trace_info; end")


def _triggers(db: Path) -> list:
    with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as con:
        return con.execute("select name from sqlite_master where type = 'trigger'").fetchall()


def test_a_trigger_in_a_store_with_no_location_rows_fetches_nothing(made, tmp_path, listener):
    address, asked = listener
    root = _project(made, tmp_path)
    _no_locations(root / "mlflow.db", address, "after insert on experiments")
    before = (root / "mlflow.db").read_bytes()
    try:
        found = start.find_judge(root)
    finally:
        assert asked == []
    assert len(found.pool.answers) == N
    assert (root / "mlflow.db").read_bytes() == before  # the person's store: same bytes


@pytest.mark.parametrize("trigger", [
    "after insert on experiments", "after update on experiments", "after insert on trace_tags",
    "after update on trace_tags", "after insert on runs", "after update on runs",
])
def test_the_copy_holds_no_trigger(made, tmp_path, trigger):
    root = _project(made, tmp_path)
    _no_locations(root / "mlflow.db", "http://127.0.0.1:9", trigger)
    uri = mlflow_store.store_uri(root / "mlflow.db")
    assert _triggers(Path(uri.removeprefix("sqlite:///"))) == []
    assert _triggers(root / "mlflow.db")  # the person's store keeps what it holds


def test_a_location_written_after_the_copy_is_made_is_never_fetched(made, tmp_path, listener):
    """A location that reaches the copy once it was made (MLflow writes to the copy when it
    opens it) is kept or pointed nowhere again before any trace is read."""
    address, asked = listener
    root = _project(made, tmp_path)
    uri = mlflow_store.store_uri(root / "mlflow.db")
    _elsewhere(Path(uri.removeprefix("sqlite:///")), address)
    try:
        found = start.find_judge(root)
    finally:
        assert asked == []
    assert len(found.pool.answers) == N
    assert asked == []


# A store that hides its locations ----------------------------------------------------------------

def test_a_trace_tags_table_named_in_capitals_is_kept_local(made, tmp_path, listener):
    """SQLite finds a table whatever the case of its name, as MLflow's queries do."""
    address, asked = listener
    root = _project(made, tmp_path)
    _elsewhere(root / "mlflow.db", address)
    edit(root / "mlflow.db", "alter table trace_tags rename to tags_for_now",
         "alter table tags_for_now rename to TRACE_TAGS")
    try:
        found = start.find_judge(root)
    finally:
        assert asked == []
    assert len(found.pool.answers) == N


FK_ON = "(select foreign_keys from pragma_foreign_keys) = 1"  # MLflow switches it on


@pytest.mark.parametrize("view", [
    # what MLflow reads differs from what judgekeeper's own check reads
    ("select key, value, request_id from real_tags where not (key = 'mlflow.artifactLocation' "
     f"and {FK_ON}) union all select 'mlflow.artifactLocation', '{{address}}/view/', "
     f"request_id from trace_info where {FK_ON}"),
    # a view over a table that is gone: it can't be read at all
    "select key, value, request_id from gone",
])
def test_a_store_holding_a_view_is_damaged(made, tmp_path, listener, view):
    """Also with no trigger in the store (MLflow 3.1 makes none)."""
    address, asked = listener
    root = _project(made, tmp_path)
    edit(root / "mlflow.db", "drop trigger if exists prevent_secrets_aad_mutation",
         "delete from trace_tags where key = 'mlflow.trace.spansLocation'",
         "delete from spans", "alter table trace_tags rename to real_tags",
         "create table gone (key, value, request_id)",
         f"create view trace_tags as {view.format(address=address)}", "drop table gone")
    try:
        with pytest.raises(Damaged, match="mlflow.db can't be read: it's damaged"):
            start.find_judge(root)
    finally:
        assert asked == []
