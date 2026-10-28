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
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from judgekeeper.readers import mlflow_store
from judgekeeper.readers.mlflow_store import ALLOW, HINT
from judgekeeper.records import Damaged
from judgekeeper.textio import quote_arg
from tests.test_front import assert_one_next_at_the_end
from tests.test_mark_background import stop_page

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
    yield project
    stop_page(project)  # a run in its own process opens a real marking page


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for name in (ALLOW, HINT, "MLFLOW_TRACKING_URI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(mlflow_store, "_noted", False)
    monkeypatch.setattr(mlflow_store, "_walked", set())


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


# A store moved from another computer ------------------------------------------------------

def test_a_moved_folder_store_is_read_from_its_own_folder(folder_only, capsys):
    found = start.find_judge(folder_only, talk=start.Talk())
    out = capsys.readouterr().out
    assert found.tool == "mlflow" and found.metric == "faithful"
    assert sorted(a.output for a in found.pool.answers) == [
        "answer to four", "answer to one", "answer to three", "answer to two"]
    assert "missing" not in out


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


def test_the_chosen_store_is_kept_for_check(two, capsys):
    found = start.find_judge(two / "mlruns", talk=start.Talk())
    ws = start_label.prepare(found, say=lambda line="": None)
    assert ws.data()["mlflow_store"] == "mlruns"


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


# MLflow's usage tracking -------------------------------------------------------------------

TELEMETRY = ("MLFLOW_DISABLE_TELEMETRY", "DO_NOT_TRACK")
READ = r"""
import json, sys
from judgekeeper import start
start.find_judge(sys.argv[1])
import os, mlflow
try:
    from mlflow.telemetry.client import get_telemetry_client
    client = get_telemetry_client() is not None
except ImportError:  # an MLflow with no usage tracking
    client = False
print(json.dumps({"env": {n: os.environ.get(n) for n in sys.argv[2:]}, "client": client}))
"""


def test_mlflow_usage_tracking_is_off_in_the_reader(tmp_path):
    from tests.conftest import build_mlflow_folder_store

    build_mlflow_folder_store(tmp_path / "mlruns")
    env = {k: v for k, v in os.environ.items()
           if k not in TELEMETRY and k not in (HINT, ALLOW, "PYTEST_CURRENT_TEST")}
    out = subprocess.run([sys.executable, "-c", READ, str(tmp_path), *TELEMETRY], env=env,
                         capture_output=True, text=True, check=True, cwd=tmp_path).stdout
    seen = json.loads(out.strip().splitlines()[-1])
    assert seen["env"] == {"MLFLOW_DISABLE_TELEMETRY": "true", "DO_NOT_TRACK": "1"}
    assert seen["client"] is False  # MLflow made no usage-tracking client


def test_two_stores_print_nothing_of_mlflows_own(two):
    """Choosing between mlflow.db and mlruns/ checks for MLflow without importing it before
    its hint is switched off."""
    env = {k: v for k, v in os.environ.items() if k not in (ALLOW, HINT)}
    env.update(CLAUDECODE="1", PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-m", "judgekeeper", str(two), "--no-browser"],
                            capture_output=True, text=True, env=env,
                            stdin=subprocess.DEVNULL, timeout=300, check=False)
    out = result.stdout + result.stderr
    assert "MLflow stores found" in out, out
    assert "MLFLOW_DISABLE_AGENT_HINT" not in out and "skill" not in out, out
    assert "INFO" not in out and "WARNING" not in out, out


def test_a_tracking_uri_mlflow_cannot_write_in_names_that_folder(tmp_path, monkeypatch, capsys):
    pytest.importorskip("mlflow")
    if os.name == "nt":
        pytest.skip("folder permissions work differently on Windows")
    locked = tmp_path / "locked"
    (locked / "0").mkdir(parents=True)  # a folder store's shape (find.is_mlflow_folder)
    (locked / "0" / "meta.yaml").write_text("name: Default\n", encoding="utf-8")
    locked.chmod(0o500)
    if os.access(locked, os.W_OK):
        locked.chmod(0o700)
        pytest.skip("this user can write anywhere")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    try:
        code, out = run(capsys, "--tracking-uri", locked.as_uri(), "--yes", "--no-browser")
    finally:
        locked.chmod(0o700)
    assert code == 2, out
    flat = " ".join(out.split())
    assert f"MLflow couldn't use {locked}" in flat, out
    assert ".judgekeeper" not in out and "make this folder writable" not in out, out
    assert "Reading your mlruns/ folder" not in flat, out  # it was never read
    nxt = flat[flat.index("Next:"):]
    assert locked.as_uri() not in nxt and str(locked) not in nxt, out  # not the same bad flag
    assert "--tracking-uri PATH" in nxt and "with PATH your MLflow folder" in nxt, out


def test_mlflows_root_logger_says_nothing_for_an_extra_folder_in_mlruns(folder_only):
    """MLflow's folder store logs a broken experiment folder through Python's root logger,
    with tracebacks: muted too while judgekeeper reads. In its own process, as for a person
    (pytest's log capture would hide it here)."""
    (folder_only / "mlruns" / "7").mkdir()  # an experiment folder with no meta.yaml
    env = {k: v for k, v in os.environ.items() if not k.startswith("MLFLOW_")}
    env["PYTHONPATH"] = str(ROOT / "src")
    done = subprocess.run([sys.executable, "-m", "judgekeeper", "--no-browser", "--port", "0"],
                          cwd=folder_only, env=env, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, check=False)
    out = done.stdout + done.stderr
    assert done.returncode in (0, 3), out
    assert "Traceback" not in out and "WARNING:root" not in out and "Malformed" not in out, out


def test_the_root_logger_is_put_back_after_mlflow():
    root = logging.getLogger()
    before = (root.level, list(root.handlers))
    with mlflow_store.quiet():
        logging.warning("from MLflow")  # noqa: LOG015 - as MLflow logs
        assert root.level == logging.CRITICAL
    assert (root.level, list(root.handlers)) == before


@pytest.mark.parametrize("value", ["", " ", ".", "./", "PROJECT", "OTHER"])
def test_a_tracking_uri_that_is_no_store_is_refused_plainly(value, tmp_path, monkeypatch,
                                                            capsys):
    pytest.importorskip("mlflow")
    project = tmp_path / "docs-qa"
    (project / ".judgekeeper").mkdir(parents=True)  # MLflow would read it as an experiment
    (tmp_path / "other" / "notes").mkdir(parents=True)
    monkeypatch.chdir(project)
    value = {"PROJECT": str(project), "OTHER": str(tmp_path / "other")}.get(value, value)
    code, out = run(capsys, "--no-browser", "--port", "0", "--tracking-uri", value)
    said = " ".join(out.split())
    assert code == 2, said
    assert "didn't expect" not in said and "report it" not in said, said
    assert ("--tracking-uri is empty" if not value.strip() else "is not an MLflow store") in said


# Files MLflow must not open ---------------------------------------------------------------
# MLflow's folder store reads each tag, setting and assessment file whole and follows links:
# a link to /dev/zero used GBs in a second, a pipe waited forever, and a link out of the
# project put that file's text in judgekeeper's files. Git keeps links, so a cloned project
# can carry one. Before MLflow opens a folder store, judgekeeper looks at every file in it.

POSIX = pytest.mark.skipif(os.name == "nt", reason="links and pipes need rights on Windows")


def _trace_folder(project):
    return min((project / "mlruns").glob("*/traces/tr-*"))


def _in_store(project, part):
    """The file `part` of the first trace (tags/NAME, request_metadata/NAME or the first
    assessment), and its path as judgekeeper names it."""
    trace = _trace_folder(project)
    path = min((trace / "assessments").iterdir()) if part == "assessment" else trace / part
    return path, path.relative_to(project).as_posix()


@POSIX
@pytest.mark.parametrize("part", ["tags/mlflow.traceName", "request_metadata/mlflow.traceInputs",
                                  "assessment"])
def test_a_link_in_the_store_is_refused_and_named(folder_only, capsys, tmp_path, part):
    canary = tmp_path / "outside.txt"
    canary.write_text("canary-text-from-outside", encoding="utf-8")
    path, rel = _in_store(folder_only, part)
    path.unlink()
    path.symlink_to(canary)
    code, out = run(capsys, folder_only, "--no-browser")
    flat = " ".join(out.split())
    assert code == 2, out
    assert f"judgekeeper didn't let MLflow read mlruns/: {rel} is a link" in flat, out
    assert "canary-text" not in out
    assert not any("canary-text" in p.read_text(encoding="utf-8", errors="replace")
                   for p in folder_only.rglob("*") if p.is_file() and not p.is_symlink())
    assert f"Next: replace {rel} with a copy of the file it links to" in flat, out


@POSIX
def test_a_link_to_a_device_is_found_without_reading_it(tmp_path):
    tags = tmp_path / "mlruns" / "1" / "traces" / "tr-1" / "tags"
    tags.mkdir(parents=True)
    (tags / "mlflow.traceName").symlink_to("/dev/zero")
    assert mlflow_store.unsafe_file(tmp_path / "mlruns") == (
        tags / "mlflow.traceName", "link")


@POSIX
@pytest.mark.parametrize("part", ["tags/mlflow.artifactLocation", "trace_info.yaml",
                                  "assessment"])
def test_a_pipe_in_the_store_is_refused_not_waited_on(folder_only, part):
    path, rel = _in_store(folder_only, part)
    path.unlink()
    os.mkfifo(path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("MLFLOW_")}
    env["PYTHONPATH"] = str(ROOT / "src")
    done = subprocess.run([sys.executable, "-m", "judgekeeper", "--no-browser", "--port", "0"],
                          cwd=folder_only, env=env, capture_output=True, text=True,
                          timeout=120, stdin=subprocess.DEVNULL, check=False)
    flat = " ".join((done.stdout + done.stderr).split())
    assert done.returncode == 2, flat
    assert f"{rel} is not a plain file (a pipe or a device)" in flat


@pytest.mark.parametrize("part", ["tags/mlflow.traceName", "assessment", "trace_info.yaml"])
def test_a_tag_or_assessment_over_1_mb_is_refused(folder_only, capsys, part):
    path, rel = _in_store(folder_only, part)
    path.write_bytes(b"x" * (2**20 + 1))
    code, out = run(capsys, folder_only, "--no-browser")
    flat = " ".join(out.split())
    assert code == 2, out
    assert f"{rel} is over 1 MB, more than MLflow keeps there" in flat, out


def test_a_big_artifact_is_not_a_tag(folder_only, capsys):
    """Run artifacts (a model, a dataset) can be any size: only the files MLflow reads whole
    are capped."""
    (folder_only / "mlruns" / "0" / "big-artifact.bin").write_bytes(b"x" * (2**20 + 1))
    _, out = run(capsys, folder_only, "--no-browser")
    assert "Store:           mlruns, experiment qa-folder" in out, out


# Size rules only where MLflow keeps a file it reads whole: an artifact, a logged dataset or a
# folder a run's artifacts happen to name "params" can be any size.

def _store_file(root, rel, size):
    path = root / "mlruns" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)  # sparse: no space on disk
    return path


METRIC_PLACES = ["1/a1b2/metrics/loss", "1/datasets/d-1/meta.yaml", "1/a1b2/inputs/i-1/meta.yaml"]


@pytest.mark.parametrize("rel", [
    "1/meta.yaml", "1/tags/team", "1/tags/mlflow/note", "1/a1b2/meta.yaml", "1/a1b2/tags/k",
    "1/a1b2/params/p", "1/traces/tr-1/trace_info.yaml", "1/traces/tr-1/tags/k",
    "1/traces/tr-1/request_metadata/k", "1/traces/tr-1/assessments/a-1", ".trash/2/meta.yaml"])
def test_a_file_over_1_mb_where_mlflow_keeps_a_small_value_is_refused(tmp_path, rel):
    path = _store_file(tmp_path, rel, 2**20 + 1)
    assert mlflow_store.unsafe_file(tmp_path / "mlruns") == (path, "big")


@pytest.mark.parametrize("rel", [
    *METRIC_PLACES, "1/a1b2/artifacts/out/params/w.bin", "1/a1b2/artifacts/meta.yaml",
    "1/a1b2/artifacts/data/tags/t", "1/traces/tr-1/artifacts/traces.json",
    "1/models/m-1/artifacts/tags/t", "0/notes/big.txt", "models/m/params/p"])
def test_any_other_file_over_1_mb_is_left_to_mlflow(tmp_path, rel):
    _store_file(tmp_path, rel, 2**20 + 1)
    assert mlflow_store.unsafe_file(tmp_path / "mlruns") is None


@pytest.mark.parametrize("rel", METRIC_PLACES)
def test_a_metric_or_logged_dataset_file_over_100_mb_is_refused(tmp_path, rel):
    _store_file(tmp_path, rel, 100 * 2**20 + 1)
    with pytest.raises(Damaged) as e:
        mlflow_store.check_folder_store(tmp_path / "mlruns")
    assert f"mlruns/{rel} is over 100 MB, more than MLflow keeps there" in str(e.value)


@POSIX
def test_a_runs_artifacts_are_not_looked_into(tmp_path):
    """MLflow doesn't open them to read traces (judgekeeper reads a trace's spans itself)."""
    artifacts = tmp_path / "mlruns" / "1" / "a1b2" / "artifacts"
    artifacts.mkdir(parents=True)
    os.mkfifo(artifacts / "pipe")
    (artifacts / "model").symlink_to("/dev/zero")
    assert mlflow_store.unsafe_file(tmp_path / "mlruns") is None


def test_the_store_is_looked_at_once_however_many_experiments(folder_only, capsys, monkeypatch):
    walks = []
    walk = mlflow_store.unsafe_file
    monkeypatch.setattr(mlflow_store, "unsafe_file", lambda folder: walks.append(1) or walk(folder))
    _, out = run(capsys, folder_only, "--no-browser")
    assert "Store:           mlruns, experiment qa-folder" in out, out
    assert len(walks) == 1


def test_a_windows_junction_is_a_link_on_every_python():
    """os.path.isjunction is Python 3.12's: on 3.11 the junction's reparse tag tells it."""
    reparse = stat.FILE_ATTRIBUTE_REPARSE_POINT
    junction = SimpleNamespace(st_file_attributes=reparse,
                               st_reparse_tag=mlflow_store.JUNCTION)
    onedrive = SimpleNamespace(st_file_attributes=reparse, st_reparse_tag=0x9000601A)
    assert mlflow_store._junction(Path("j"), junction)
    assert not mlflow_store._junction(Path("f"), onedrive)  # a OneDrive file: a plain file
    assert not mlflow_store._junction(Path(__file__), os.lstat(__file__))


@pytest.mark.skipif(os.name != "nt", reason="a junction is Windows'")
def test_a_junction_in_the_store_is_refused(tmp_path):
    tags = tmp_path / "mlruns" / "1" / "traces" / "tr-1" / "tags"
    tags.mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(tags / "mlflow"), str(tmp_path / "outside")],
                   check=True, capture_output=True)
    assert mlflow_store.unsafe_file(tmp_path / "mlruns") == (tags / "mlflow", "link")


# Limits on what one read takes ------------------------------------------------------------
# 120 sparse trace files of 99 MB (3 MB on disk) took 3.7 GB; 2,000 empty experiments took
# half a minute. The trace files' real sizes count, not their space on disk.

def test_trace_files_over_the_limit_together_are_refused(folder_only, capsys, monkeypatch):
    sizes = [p.stat().st_size for p in _trace_files(folder_only)]
    monkeypatch.setattr(mlflow_store, "TRACES_LIMIT", sum(sizes) - 1)
    code, out = run(capsys, folder_only, "--no-browser")
    flat = " ".join(out.split())
    assert code == 2, out
    assert "the trace files judgekeeper would read from mlruns are over" in flat, out
    assert "judgekeeper reads at most" in flat and "Next:" in flat, out


def test_trace_files_under_the_limit_are_read(folder_only, capsys, monkeypatch):
    sizes = [p.stat().st_size for p in _trace_files(folder_only)]
    monkeypatch.setattr(mlflow_store, "TRACES_LIMIT", sum(sizes))
    _, out = run(capsys, folder_only, "--no-browser")
    assert "Store:           mlruns, experiment qa-folder" in out, out


def test_a_store_with_more_experiments_than_the_limit_is_refused(folder_only, capsys,
                                                                 monkeypatch):
    monkeypatch.setattr(mlflow_store, "MAX_EXPERIMENTS", 1)  # this store holds 2
    code, out = run(capsys, folder_only, "--no-browser")
    flat = " ".join(out.split())
    assert code == 2, out
    assert ("mlruns has more than 1 experiments: judgekeeper reads at most 1 experiments from "
            "one store.") in flat, out
    assert "--experiment NAME" in flat[flat.index("Next:"):], out
    code, out = run(capsys, folder_only, "--no-browser", "--experiment", "qa-folder")
    assert "Store:           mlruns, experiment qa-folder" in out, out  # one, named: read


def test_listing_two_stores_leaves_no_trash_folder(two, capsys):
    """MLflow makes mlruns/.trash when it opens a folder store without one: judgekeeper removes
    it again, as when it reads the store, so nothing is left outside .judgekeeper/."""
    shutil.rmtree(two / "mlruns" / ".trash", ignore_errors=True)
    _, out = run(capsys, two, "--no-browser")
    assert "Two MLflow stores found" in out, out
    assert not (two / "mlruns" / ".trash").exists()


def test_a_cloned_folder_store_beside_mlflow_db_is_read_by_name(two, capsys):
    """A git clone has no mlruns/.trash: MLflow keeps the store it opened for the whole run, so
    the .trash it made stays until judgekeeper ends."""
    shutil.rmtree(two / "mlruns" / ".trash")
    code, out = run(capsys, two, "--no-browser", "--experiment", "qa-folder")
    assert code in (0, 3) and "Store:           mlruns, experiment qa-folder" in out, out
    assert not (two / "mlruns" / ".trash").exists()


def test_a_cloned_folder_store_beside_mlflow_db_is_read_when_chosen(two, capsys, monkeypatch):
    shutil.rmtree(two / "mlruns" / ".trash")
    answers = ["2", ""]  # mlruns; save
    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt="": answers.pop(0))
    code, out = run(capsys, two)
    assert code in (0, 3) and "Store:           mlruns, experiment qa-folder" in out, out
    assert not (two / "mlruns" / ".trash").exists()


def test_the_limits_are_said_in_the_reference():
    flat = " ".join((ROOT / "docs" / "reference.md").read_text(encoding="utf-8").split())
    assert (f"From an MLflow store it reads at most {mlflow_store.MAX_EXPERIMENTS:,} experiments "
            f"and {mlflow_store.TRACES_LIMIT // 10**9} GB of trace files in one go, and the "
            f"newest {mlflow_store.MAX_TRACES:,} traces of an experiment.") in flat
    assert (f"an `mlflow.db` over {mlflow_store.STORE_LIMIT // 10**9} GB with its `-wal` and "
            "`-shm` files") in flat
    assert (mlflow_store.SMALL_LIMIT, mlflow_store.LARGE_LIMIT) == (2**20, 100 * 2**20)
    assert "a tag, setting or assessment file over 1 MB or a metric file over 100 MB" in flat


# Messages that say what is true -----------------------------------------------------------

@POSIX
@pytest.mark.parametrize("uri", ["/dev/null", "sqlite:////dev/null"])
def test_a_tracking_uri_naming_a_device_is_not_a_store(tmp_path, monkeypatch, capsys, uri):
    pytest.importorskip("mlflow")
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "--tracking-uri", uri, "--no-browser")
    flat = " ".join(out.split())
    assert code == 2, out
    assert f"{uri} is not an MLflow store: it is not a plain file (a pipe or a device)" in flat
    assert "holds no decisions" not in flat and "remove" not in flat, out
    nxt = flat[flat.index("Next:"):]
    assert "/dev/null" not in nxt and "--tracking-uri PATH" in nxt, nxt


def test_an_empty_tracking_uri_is_not_repeated_in_the_next_line(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = run(capsys, "--tracking-uri", "", "--no-browser")
    flat = " ".join(out.split())
    assert code == 2 and "--tracking-uri is empty" in flat, out
    nxt = flat[flat.index("Next:"):]
    assert "--tracking-uri ''" not in nxt and '--tracking-uri ""' not in nxt, nxt
    assert "--tracking-uri PATH" in nxt, nxt


def test_a_read_only_mlruns_found_in_the_project_gets_a_next_line_that_helps(folder_only,
                                                                              capsys):
    if os.name == "nt":
        pytest.skip("folder permissions work differently on Windows")
    store = folder_only / "mlruns"
    shutil.rmtree(store / ".trash", ignore_errors=True)
    store.chmod(0o500)
    if os.access(store, os.W_OK):
        store.chmod(0o700)
        pytest.skip("this user can write anywhere")
    try:
        code, out = run(capsys, folder_only, "--no-browser")
    finally:
        store.chmod(0o700)
    flat = " ".join(out.split())
    assert code == 2, out
    nxt = flat[flat.index("Next:"):]
    assert "make mlruns/ writable" in nxt and "--tracking-uri PATH" not in nxt, nxt
