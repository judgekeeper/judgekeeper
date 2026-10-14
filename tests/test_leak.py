"""No credential reaches disk, stdout or stderr, whatever the judge's results hold.

Sentinel values sit in ANTHROPIC_API_KEY, OPENAI_API_KEY, the Langfuse keys and a custom
variable whose name ends in _API_KEY. The judge's saved results echo every one of them in the
questions, the answers, the judge's reasons and the model it names. Then `start` reads them,
the page's marks are saved and the result is written, and every file and every line printed
is searched.
"""

import json
from pathlib import Path

import pytest

from judgekeeper import redact, start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split

SENTINELS = {
    "ANTHROPIC_API_KEY": "sentinel-anthropic-4f1c9e",
    "OPENAI_API_KEY": "sentinel-openai-7d2b8a",
    "MY_GATEWAY_API_KEY": "sentinel-gateway-3e5a01",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-sentinel-public-9b41",
    "LANGFUSE_SECRET_KEY": "sk-lf-sentinel-secret-c27e",
}
KEYS = " ".join(SENTINELS.values())


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name, value)
    redact._named_vars.clear()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def assert_no_sentinel(root: Path, *texts: str):
    for text in texts:
        for value in SENTINELS.values():
            assert value not in text
    files = [p for p in root.rglob("*") if p.is_file()]
    assert files
    for p in files:
        content = p.read_text(encoding="utf-8")
        for value in SENTINELS.values():
            assert value not in content, f"{value} leaked into {p}"


def _results_with_keys(root: Path) -> Path:
    path = promptfoo_project(root, split(20, 12), tag=f" (debug: {KEYS})",
                             model=f"openai:served-{SENTINELS['OPENAI_API_KEY']}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            c["reason"] = (f"{c['reason']} Authorization: Bearer {SENTINELS['OPENAI_API_KEY']}"
                           f" {KEYS}")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _label_everything(ws):
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in json.loads(ws.start.read_text(
        encoding="utf-8"))["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    return session


def test_no_key_leaks_anywhere(env, capsys):
    results = _results_with_keys(env)
    assert main(["start"]) == 3  # no terminal: it stops at the first question
    printed = capsys.readouterr()
    assert "Its decisions" in printed.out
    # What the page does next: save the marks and the result.
    said = []
    ws = start_label.prepare(start.find_judge(env), say=said.append)
    start_label.save_result(ws, _label_everything(ws), say=said.append)
    saved = [p for p in ws.dir.rglob("*") if p.is_file()]
    assert len(saved) >= 8
    results.unlink()  # the judge's own file holds the keys; judgekeeper's files must not
    (env / "promptfooconfig.yaml").unlink()
    assert_no_sentinel(env, printed.out, printed.err, *said)
    # The echoed keys were really there and really replaced, not just missing.
    pool = (ws.dir / "pool-judge.jsonl").read_text(encoding="utf-8")
    assert redact.REDACTED in pool
    result = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert result["fingerprint"]["model"] == f"openai:served-{redact.REDACTED}"


def test_a_failure_message_is_scrubbed_and_has_no_traceback(env, capsys, monkeypatch):
    from judgekeeper import cli

    def fails(args):
        raise PermissionError(f"Error code: 401 - Incorrect API key provided: "
                              f"{SENTINELS['OPENAI_API_KEY']}. Request headers: "
                              f"{{'X-Other': '{SENTINELS['MY_GATEWAY_API_KEY']}'}}")

    monkeypatch.setitem(cli.COMMANDS, "start", fails)
    assert main(["start"]) == 2
    err = capsys.readouterr().err
    assert "error: judgekeeper hit a problem it didn't expect" in err and "401" not in err
    assert "Traceback" not in err and "--debug" in err
    assert main(["--debug", "start"]) == 2
    debug = capsys.readouterr().err
    assert "Traceback" in debug
    for value in SENTINELS.values():
        assert value not in err and value not in debug


def test_an_mlflow_store_with_keys_never_shows_them(env, capsys, monkeypatch):
    """Judge rationales in a real MLflow store echo the keys."""
    from judgekeeper.readers import mlflow_store
    from tests.conftest import build_mlflow_store

    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.setattr(mlflow_store, "_noted", False)
    build_mlflow_store(env, note=f" (debug: {KEYS})")
    assert main(["start", "--metric", "correctness"]) == 3
    printed = capsys.readouterr()
    assert "Its decisions" in printed.out
    for value in SENTINELS.values():
        assert value not in printed.out + printed.err
    said = []
    ws = start_label.prepare(start.find_judge(env, metric="correctness"), say=said.append)
    for path in ws.dir.rglob("*"):
        if path.is_file():
            for value in SENTINELS.values():
                assert value not in path.read_text(encoding="utf-8"), path.name


def test_the_sentinels_are_credentials_to_redact(env):
    """The custom variable is caught by its name's ending, not by being named on a flag."""
    for value in SENTINELS.values():
        assert redact.scrub(f"x {value} y") == f"x {redact.REDACTED} y"
