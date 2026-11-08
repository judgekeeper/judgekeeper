"""A field whose name is itself a key (a promptfoo var named after one) is hidden like any other
secret: on the marking page and in the files judgekeeper writes."""

from __future__ import annotations

import json

from judgekeeper import judge_setup, start, start_label
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data, split

FAKE = "sk-proj-FAKEVALUEthatmustneverbeprinted0123456789"


def test_a_var_named_after_a_key_is_hidden(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = promptfoo_data(split(20, 20))
    for row in data["results"]["results"]:
        row["vars"] = {**row["vars"], FAKE: "x"}
        row["testCase"]["vars"] = row["vars"]
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")
    found = start.find_judge(tmp_path)
    ws = Workspace(tmp_path)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    start_label.prepare(found, say=lambda line="": None)
    session = StartSession(ws)
    shown = json.dumps(session.state())
    assert FAKE[:20] not in shown, "the page state"
    for path in ws.dir.rglob("*"):
        if path.is_file():
            assert FAKE[:20] not in path.read_text(encoding="utf-8", errors="replace"), path.name


def test_an_mlflow_input_named_after_a_key_is_hidden(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("mlflow")
    import tests.test_only_reads as only_reads

    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    for var in ("MLFLOW_TRACKING_URI", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MLFLOW_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("DO_NOT_TRACK", "true")
    store = only_reads.MLFLOW_STORE.replace(
        "    def app(question):\n        return a\n    app(q)",
        f"    def app(question, **more):\n        return a\n    app(q, **{{{FAKE!r}: 'x'}})")
    assert store != only_reads.MLFLOW_STORE
    monkeypatch.setattr(only_reads, "MLFLOW_STORE", store)
    ws = only_reads.project("mlflow", root, monkeypatch)
    shown = json.dumps(StartSession(ws).state())
    assert FAKE[:20] not in shown, "the page state"
    for path in ws.dir.rglob("*"):
        if path.is_file():
            assert FAKE[:20] not in path.read_text(encoding="utf-8", errors="replace"), path.name
