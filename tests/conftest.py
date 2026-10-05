import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

pytest_plugins = ["pytester"]  # tests/test_pytest_plugin.py runs pytest inside pytest


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


@pytest.fixture(scope="session")
def mlflow_store(tmp_path_factory):
    """The MLflow fixture store, built once per session."""
    return build_mlflow_store(tmp_path_factory.mktemp("mlflow-store"))
