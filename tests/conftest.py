"""Fixtures shared by the tests: fixture copies, no real browser, and the MLflow stores."""

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# pytester: tests/test_pytest_plugin.py runs pytest inside pytest. again_stubs: the stub
# DeepEval, Inspect AI and MLflow packages (the `stubs` fixture) for the ask-again workers.
pytest_plugins = ["pytester", "tests.again_stubs"]


@pytest.fixture
def pairwise_dir(tmp_path):
    """A writable copy of the pairwise fixture: anchors, manifest and three replay runs."""
    dst = tmp_path / "pairwise"
    shutil.copytree(FIXTURES / "pairwise", dst)
    return dst


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    """No test opens the browser of the machine it runs on. The links it would have opened
    are kept, for a test that wants to see them."""
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    return opened


@pytest.fixture(autouse=True)
def keyboard_limit():
    """Each test starts with the fake keyboard's count of unanswered questions at zero."""
    from tests import keyboard

    keyboard.reset()


@pytest.fixture(autouse=True)
def fresh_key_registry(monkeypatch):
    """Variables named with --api-key-env are registered for the life of a process; give each
    test its own registry so one test cannot hide a leak in another."""
    from judgekeeper import redact

    monkeypatch.setattr(redact, "_named_vars", set())


def build_mlflow_store(root, note: str = "") -> str:
    """A real MLflow SQLite store under `root`, made by tests/fixtures/mlflow/make_store.py
    (about ten seconds); returns its tracking URI. Skips when mlflow is not installed."""
    pytest.importorskip("mlflow")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_mlflow_store", FIXTURES / "mlflow" / "make_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build(root, note=note)


FOLDER_STORE = r"""
import os, sys
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
from mlflow.entities import AssessmentSource

mlflow.set_tracking_uri(sys.argv[1])
mlflow.set_experiment("folder-store")
judge = AssessmentSource(source_type="LLM_JUDGE", source_id="openai:/gpt-4.1")

@mlflow.trace(name="app")
def app(question):
    return f"answer to {question}"

for i, question in enumerate(["one", "two", "three", "four"]):
    app(question)
    mlflow.flush_trace_async_logging()
    trace_id = mlflow.get_last_active_trace_id()
    mlflow.log_feedback(trace_id=trace_id, name="helpful", value=i % 2 == 0, source=judge)
"""


def build_mlflow_folder_store(folder):
    """A real MLflow folder store (mlruns/) at `folder`, made in another process by the
    installed MLflow: experiment "folder-store", 4 traces, a judge "helpful" (openai:/gpt-4.1)
    passing the first and third. Skips when mlflow is not installed."""
    import subprocess
    import sys

    pytest.importorskip("mlflow")
    folder.parent.mkdir(parents=True, exist_ok=True)
    script = folder.parent / "make_folder_store.py"
    script.write_text(FOLDER_STORE, encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(folder)], check=True,
                   cwd=folder.parent, capture_output=True)
    script.unlink()
    return folder


@pytest.fixture(scope="session")
def mlflow_store(tmp_path_factory):
    """The MLflow fixture store, built once per session."""
    return build_mlflow_store(tmp_path_factory.mktemp("mlflow-store"))
