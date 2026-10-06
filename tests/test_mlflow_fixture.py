"""tests/fixtures/mlflow/make_store.py waits until every trace has its row_id tag before it
reads them: MLflow saves a trace's tags in the background, so right after a flush some may
not be saved yet (seen on Windows as KeyError: 'row_id'). Fake traces here, no MLflow."""

import importlib.util
from types import SimpleNamespace

import pytest

from tests.conftest import FIXTURES


def _module():
    spec = importlib.util.spec_from_file_location("make_mlflow_store",
                                                  FIXTURES / "mlflow" / "make_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trace(tags):
    return SimpleNamespace(info=SimpleNamespace(tags=tags))


def test_it_waits_until_the_tags_are_saved():
    looks = []

    def search():  # the tags show up on the third look, the third trace on the second
        looks.append(1)
        n = len(looks)
        traces = [_trace({"row_id": "Q0"}), _trace({"row_id": "Q1"} if n >= 3 else {})]
        return traces + ([_trace({"row_id": "Q2"})] if n >= 2 else [])

    traces = _module().wait_for_row_ids(search, expected=3, limit=5, poll=0.01)
    assert len(looks) == 3 and len(traces) == 3


def test_it_gives_up_with_a_clear_error():
    with pytest.raises(RuntimeError, match=r"1 of 2 traces have their row_id tag"):
        _module().wait_for_row_ids(lambda: [_trace({"row_id": "Q0"}), _trace({})],
                                   expected=2, limit=0.05, poll=0.01)
