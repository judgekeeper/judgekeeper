"""An MLflow experiment whose name looks like a secret is hidden wherever it is shown or saved,
yet fix and check still find it: the store is read by its real name, worked out again from the
hidden one."""

from __future__ import annotations

import json

import pytest

import tests.test_only_reads as only_reads
from tests.test_only_reads import project, run

pytest.importorskip("mlflow")

NAMES = {"Basic QuestionAnswering": "Basic [REDACTED]",  # hidden as a Basic login
         "eval-sk-learn-pipeline-baseline": "eval-[REDACTED]"}  # as a key after -


@pytest.fixture(params=sorted(NAMES))
def name(request):
    return request.param


@pytest.fixture
def here(tmp_path, monkeypatch, name):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(only_reads, "MLFLOW_STORE", only_reads.MLFLOW_STORE.replace(
        'mlflow.set_experiment("support")', f"mlflow.set_experiment({name!r})"))
    for var in ("MLFLOW_TRACKING_URI", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("DO_NOT_TRACK", "true")
    return root


def test_fix_and_check_find_an_experiment_whose_name_is_hidden(here, name, capsys, monkeypatch):
    ws = project("mlflow", here, monkeypatch)
    saved = json.loads(ws.start.read_text(encoding="utf-8"))
    assert saved["experiment"] == NAMES[name]  # saved hidden, as before
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    code, out = run(capsys, "check")
    assert code != 2, out
    assert "no MLflow experiment named" not in out, out
    assert name not in out and name.split()[-1].split("-sk-")[-1] not in out
