"""No credential reaches disk, stdout or stderr, whatever the LLM-as-a-judge's results hold.

Sentinel values sit in ANTHROPIC_API_KEY, OPENAI_API_KEY, the Langfuse keys and a custom
variable whose name ends in _API_KEY. The LLM-as-a-judge's saved results echo every one of them
in the questions, the answers, the LLM-as-a-judge's reasons and the model it names. Then `start`
reads them, the page's marks are saved and the result is written, and every file and every line
printed is searched.
"""

import json
from pathlib import Path

import pytest

from judgekeeper import redact, start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, save_result, split

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
    assert main([]) == 0  # the page opens in the background
    printed = capsys.readouterr()
    assert "Your LLM-as-a-judge passed " in printed.out
    # What the page does next: save the marks and the result.
    said = []
    ws = start_label.prepare(start.find_judge(env), say=said.append)
    save_result(ws, _label_everything(ws), say=said.append)
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

    monkeypatch.setitem(cli.COMMANDS, None, fails)
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "error: judgekeeper hit a problem it didn't expect" in err and "401" not in err
    assert "Traceback" not in err and "--debug" in err
    assert main(["--debug"]) == 2
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
    assert main(["--metric", "correctness"]) == 3  # too few answers for a result
    printed = capsys.readouterr()
    assert "Your LLM-as-a-judge passed " in printed.out
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


# A name or rule that key hiding changes is still the same name or rule ------------------------

URL_METRIC = "helpfulness, see https://wiki:S3cretWikiPass@wiki.example.com/rubric"
KEY_RULE = "Be polite. sk-ant-api03-FAKERULEaaaaaaaaaaaaaaaa"
KEY_MODEL = "claude-opus-5 sk-ant-api03-FAKEMODELaaaaaaaaaaaaaaa"


def _records(root: Path, metric: str, rule: str, n: int = 40,
             model: str = "claude-opus-5") -> None:
    """judgekeeper.record()'s lines: the LLM-as-a-judge passes the first half."""
    from tests.start_projects import answer, question

    folder = root / ".judgekeeper" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "helpfulness-2026-10-05-1.jsonl").open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({
                "schema_version": 2, "target_id": None, "name": metric, "annotator_kind": "LLM",
                "label": "pass" if i < n // 2 else "fail", "score": None,
                "explanation": f"reason {i}", "run": None, "input": question(i),
                "output": answer(i), "evaluator": {"model": model, "rule": rule},
                "created_at": "2026-10-05T10:00:00Z"}) + "\n")


def _marked_records(root: Path, capsys, metric: str, rule: str,
                    model: str = "claude-opus-5") -> str:
    """Every answer marked (four the other way), then `judgekeeper` again: what it says."""
    from judgekeeper.start_label import StartSession, Workspace
    from tests.test_fix import closed

    _records(root, metric, rule, model=model)
    assert main(["--no-browser"]) == 0
    ws = Workspace(root)
    closed(ws)
    session = StartSession(ws)
    for n, item in enumerate(session.items):
        label = session.groups[item["id"]]
        if n < 4:
            label = {"pass": "fail", "fail": "pass"}[label]
        session.update({"id": item["id"], "label": label, "seconds": 5})
    capsys.readouterr()
    code = main(["--no-browser"])
    closed(ws)
    out, err = capsys.readouterr()
    assert code in (0, 3), out + err  # 3: too early to tell
    return " ".join((out + err).split())


def test_a_metric_name_with_a_url_login_reaches_a_result(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    said = _marked_records(tmp_path, capsys, URL_METRIC, "Be polite.")
    assert "Your marks are for other results" not in said
    assert "Result:" in said and "S3cretWikiPass" not in said
    code = main(["check"])
    out = " ".join(capsys.readouterr().out.split())
    assert code == 0 and "You have not marked enough answers" not in out, out


def test_a_key_in_the_rule_is_not_a_rule_change(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    said = _marked_records(tmp_path, capsys, "helpfulness", KEY_RULE)
    assert "This result is about your LLM-as-a-judge as it was" not in said
    assert "Result:" in said and "FAKERULE" not in said


@pytest.mark.parametrize("value", ["promptfoo", "one call", "gpt-4.1-mini"])
def test_a_credential_equal_to_a_setup_name_hides_only_the_model(tmp_path, monkeypatch, value):
    """A credential's value that happens to be the tool's name or the kind of judge never
    changes them: only what comes from the results (the model here) is hidden."""
    from judgekeeper import judge_setup, start
    from tests.start_projects import promptfoo_project, split

    monkeypatch.setenv("X_TOKEN", value)
    promptfoo_project(tmp_path, split(20, 12), model="openai:gpt-4.1-mini")
    setup = judge_setup.of(start.find_judge(tmp_path))
    assert setup["tool"] == "promptfoo" and setup["kind"] == judge_setup.ONE_CALL
    assert setup["rule_hash"].startswith("sha256:") and "REDACTED" not in setup["rule_hash"]
    model = "openai:[REDACTED]" if value == "gpt-4.1-mini" else "openai:gpt-4.1-mini"
    assert setup["models"] == [model]


def test_a_key_in_the_model_is_not_a_judge_change(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    said = _marked_records(tmp_path, capsys, "helpfulness", "Be polite.", model=KEY_MODEL)
    assert "This result is about your LLM-as-a-judge as it was" not in said
    assert "Result:" in said and "FAKEMODEL" not in said
    code = main(["check"])
    out = " ".join(capsys.readouterr().out.split())
    assert code == 0 and "has not changed since you marked" in out and "FAKEMODEL" not in out, out
