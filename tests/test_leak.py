"""No credential reaches disk, stdout or stderr, whatever the judge returns or raises.

Sentinel values sit in ANTHROPIC_API_KEY, OPENAI_API_KEY, the Langfuse keys and a custom
variable named with --api-key-env. One fake client echoes the key it was given and both standard keys into its
rationale; another raises an error whose message carries them. Then every command that writes
files runs over the results. Each command starts with no variables registered by an earlier
one, as separate processes would.
"""

import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from judgekeeper import redact
from judgekeeper.cli import main

SENTINELS = {
    "ANTHROPIC_API_KEY": "sentinel-anthropic-4f1c9e",
    "OPENAI_API_KEY": "sentinel-openai-7d2b8a",
    "MY_GATEWAY_KEY": "sentinel-gateway-3e5a01",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-sentinel-public-9b41",
    "LANGFUSE_SECRET_KEY": "sk-lf-sentinel-secret-c27e",
}

PROMPT = """---
rubric_version: leak-v1
---
{{input}} / {{output_a}} / {{output_b}}
"""


def _echoing_text(model: str, api_key: str) -> str:
    keys = " ".join([api_key, os.environ["ANTHROPIC_API_KEY"], os.environ["OPENAI_API_KEY"]])
    # The two judges disagree on every item, so migrate lists changed items with rationales.
    verdict = "A" if model == "judge-old" else "B"
    return (f"Debug dump: keys {keys}; header Authorization: Bearer {SENTINELS['OPENAI_API_KEY']}"
            f"\nVerdict: {verdict}")


class EchoingAnthropic:
    """Returns a rationale containing every sentinel."""

    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        text = _echoing_text(kwargs["model"], self.api_key)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            model=kwargs["model"],
        )


class FailingOpenAI:
    """Raises, as an SDK does after its retries, with the key in the message."""

    def __init__(self, **kwargs):
        self.api_key = kwargs["api_key"]
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        raise PermissionError(
            f"Error code: 401 - Incorrect API key provided: {self.api_key}. "
            f"Request headers: {{'Authorization': 'Bearer {self.api_key}', "
            f"'X-Other': '{SENTINELS['ANTHROPIC_API_KEY']}'}}"
        )


@pytest.fixture
def env(monkeypatch, tmp_path, pairwise_dir):
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name, value)
    for name in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    anthropic = ModuleType("anthropic")
    anthropic.Anthropic = EchoingAnthropic
    openai = ModuleType("openai")
    openai.OpenAI = FailingOpenAI
    anthropic.DefaultHttpxClient = openai.DefaultHttpxClient = SimpleNamespace
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    monkeypatch.setitem(sys.modules, "openai", openai)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (work / "prompt.md").write_text(PROMPT, encoding="utf-8")
    return SimpleNamespace(work=work, anchors=str(pairwise_dir / "anchors.jsonl"))


def cli(*argv):
    """One command, as its own process would see it: no key variable registered yet."""
    redact._named_vars.clear()
    return main(list(argv))


def judge(env, runner, model, out, *extra):
    return cli("judge", env.anchors, "--runner", runner, "--model", model,
               "--prompt", "prompt.md", "--runs", "3", "--out", out, *extra)


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


def run_pipeline(env, capsys) -> list[str]:
    """Every command, in the order a user would run them. Returns captured stdout+stderr."""
    captured = []

    def step(code, expected):
        out = capsys.readouterr()
        captured.extend([out.out, out.err])
        assert code == expected, out.err

    step(judge(env, "anthropic", "judge-old", "runs/old"), 0)
    step(judge(env, "anthropic", "judge-new", "runs/new",
               "--base-url", "https://gateway.example.com/v1",
               "--api-key-env", "MY_GATEWAY_KEY"), 0)
    # A provider call that fails after the SDK's retries: never scored, exit 1, scrubbed.
    step(judge(env, "openai", "judge-x", "runs/failed"), 1)
    step(cli("--debug", "judge", env.anchors, "--runner", "openai", "--model", "judge-x",
             "--prompt", "prompt.md", "--out", "runs/failed-debug"), 1)
    step(cli("validate", env.anchors, "runs/old", "--out", "reports/old"), 0)
    step(cli("validate", env.anchors, "runs/new", "--out", "reports/new"), 0)
    step(cli("baseline", "set", "reports/old/report.json"), 0)
    step(cli("baseline", "show"), 0)
    step(cli("gate", "reports/old/report.json"), 1)  # kappa 0: every verdict is A
    step(cli("gate", "reports/new/report.json"), 5)  # different model and endpoint
    step(cli("migrate", env.anchors, "runs/old", "runs/new", "--out", "migration",
             "--rebase"), 0)
    step(cli("gate", "reports/new/report.json"), 1)  # rebased: no longer JUDGE_CHANGED
    step(cli("attribute", "reports/new/report.json"), 0)
    step(cli("attribute", "reports/old/report.json", "--out", "attribution-old"), 6)
    step(cli("attribute", "reports/new/report.json", "--app-score-before", "0.7",
             "--app-score-after", "0.5", "--out", "attribution-app"), 7)
    return captured


def test_no_key_leaks_anywhere(env, capsys):
    captured = run_pipeline(env, capsys)
    assert_no_sentinel(env.work, *captured)
    # The echoed keys were really there and really replaced, not just missing.
    run = (env.work / "runs" / "old" / "run-01.jsonl").read_text(encoding="utf-8")
    assert "[REDACTED]" in run
    migration = (env.work / "migration" / "migration.json").read_text(encoding="utf-8")
    assert "old_rationale" in migration and "[REDACTED]" in migration
    assert list((env.work / ".judgekeeper" / "migrations").glob("*.json"))
    assert not (env.work / "runs" / "failed").exists() or not any(
        (env.work / "runs" / "failed").iterdir())


def test_failed_call_message_is_scrubbed_and_has_no_traceback(env, capsys):
    assert judge(env, "openai", "judge-x", "runs/failed") == 1
    err = capsys.readouterr().err
    assert "error:" in err and "[REDACTED]" in err and "401" in err
    assert "Traceback" not in err
    assert "--debug" in err
    for value in SENTINELS.values():
        assert value not in err


def test_debug_shows_a_scrubbed_traceback(env, capsys):
    assert cli("--debug", "judge", env.anchors, "--runner", "openai", "--model", "judge-x",
               "--prompt", "prompt.md", "--out", "runs/failed") == 1
    err = capsys.readouterr().err
    assert "Traceback" in err
    for value in SENTINELS.values():
        assert value not in err


def test_import_and_export_never_write_a_key(env, capsys, tmp_path):
    """Judge rationales and human comments in imported files may echo a key, as above. Only
    the standard variables: nothing names a custom one with --api-key-env here."""
    import json

    from tests.conftest import FIXTURES

    keys = f"{SENTINELS['ANTHROPIC_API_KEY']} {SENTINELS['OPENAI_API_KEY']}"
    data = json.loads((FIXTURES / "promptfoo" / "results.json").read_text(encoding="utf-8"))
    for row in data["results"]["results"]:
        for c in row["gradingResult"]["componentResults"]:
            c["reason"] = f"{c['reason']} (debug: {keys})"
            if "comment" in c:
                c["comment"] = f"Authorization: Bearer {SENTINELS['OPENAI_API_KEY']}"
    src = tmp_path / "in"
    src.mkdir()
    (src / "results.json").write_text(json.dumps(data), encoding="utf-8")
    (src / "records.csv").write_text(
        "id,metric,value,why,kind\n"
        f"a,q,pass,saw {SENTINELS['ANTHROPIC_API_KEY']},llm\nb,q,fail,ok,llm\n"
        "a,q,pass,,human\nb,q,fail,,human\n", encoding="utf-8")
    captured = []

    def step(code, expected):
        out = capsys.readouterr()
        captured.extend([out.out, out.err])
        assert code == expected, out.err

    step(cli("import", "promptfoo", str(src / "results.json"), "--metric", "helpfulness",
             "--out", "imported/promptfoo"), 0)
    step(cli("import", "records", str(src / "records.csv"), "--map",
             "target_id=id,name=metric,label=value,explanation=why,annotator_kind=kind",
             "--out", "imported/records"), 0)
    step(cli("export", "records", "imported/promptfoo", "-o", "exported/promptfoo.jsonl"), 0)
    step(cli("export", "records", "imported/records", "-o", "exported/records.jsonl"), 0)
    # a usage error that echoes what the user typed
    step(cli("import", "promptfoo", str(src / "results.json"), "--metric",
             SENTINELS["OPENAI_API_KEY"], "--out", "imported/bad"), 2)
    assert_no_sentinel(env.work, *captured)
    run = (env.work / "imported" / "promptfoo" / "runs" / "run-01.jsonl").read_text(
        encoding="utf-8")
    assert "[REDACTED]" in run
    assert "[REDACTED]" in (env.work / "exported" / "records.jsonl").read_text(encoding="utf-8")


def test_mlflow_import_never_writes_a_key(env, capsys, tmp_path):
    """Judge rationales in a real MLflow store echo the keys."""
    from tests.conftest import build_mlflow_store

    keys = " ".join(SENTINELS[k] for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                                           "LANGFUSE_SECRET_KEY"))
    uri = build_mlflow_store(tmp_path / "store", note=f" (debug: {keys})")
    captured = []

    def step(code, expected):
        out = capsys.readouterr()
        captured.extend([out.out, out.err])
        assert code == expected, out.err

    step(cli("import", "mlflow", "--experiment", "qa-judge", "--tracking-uri", uri,
             "--metric", "correctness", "--anchors-out", "anchors/mlflow.jsonl",
             "--out", "imported/mlflow"), 0)
    step(cli("export", "records", "imported/mlflow", "-o", "exported/mlflow.jsonl"), 0)
    step(cli("import", "mlflow", "--experiment", "qa-judge", "--tracking-uri", uri,
             "--metric", SENTINELS["OPENAI_API_KEY"], "--out", "imported/bad"), 2)
    assert_no_sentinel(env.work, *captured)
    assert "[REDACTED]" in (env.work / "imported" / "mlflow" / "runs" / "run-01.jsonl").read_text(
        encoding="utf-8")


def test_langfuse_import_never_writes_a_key(env, capsys, monkeypatch):
    """Judge comments echo the keys and the Authorization header; a 401 body echoes it too.
    Not MY_GATEWAY_KEY: nothing names it with --api-key-env here."""
    import base64

    from judgekeeper.readers import langfuse_api
    from tests.langfuse_stub import LangfuseStub, score_pages

    monkeypatch.setattr(langfuse_api, "_sleep", lambda s: None)
    basic = base64.b64encode(f"{SENTINELS['LANGFUSE_PUBLIC_KEY']}:"
                             f"{SENTINELS['LANGFUSE_SECRET_KEY']}".encode()).decode()
    keys = " ".join(v for k, v in SENTINELS.items() if k != "MY_GATEWAY_KEY")
    pages = score_pages()
    for page in pages:
        for s in page["data"]:
            s["comment"] = f"debug {keys} Authorization: Basic {basic}"
    captured = []

    def step(code, expected):
        out = capsys.readouterr()
        captured.extend([out.out, out.err])
        assert code == expected, out.err

    def langfuse(*extra):
        return cli("import", "langfuse", "--judge-score", "helpfulness", "--human-score",
                   "helpfulness_human", "--pass-if", "score>=0.5", "--max-items", "100",
                   *extra)

    with LangfuseStub(pages=pages) as stub:
        monkeypatch.setenv("LANGFUSE_HOST", stub.url)
        step(langfuse("--anchors-out", "anchors/langfuse.jsonl", "--out", "imported/lf"), 0)
    step(cli("export", "records", "imported/lf", "-o", "exported/lf.jsonl"), 0)
    with LangfuseStub(status=401) as stub:
        monkeypatch.setenv("LANGFUSE_HOST", stub.url)
        step(langfuse("--out", "imported/denied"), 1)
        step(cli("--debug", "import", "langfuse", "--judge-score", "helpfulness",
                 "--human-score", "h", "--max-items", "5", "--out", "imported/denied2"), 1)
    # a host with credentials in it is refused without echoing them
    monkeypatch.setenv("LANGFUSE_HOST",
                       f"https://u:{SENTINELS['LANGFUSE_SECRET_KEY']}@langfuse.example.com")
    step(langfuse("--out", "imported/badhost"), 2)
    assert_no_sentinel(env.work, *captured)
    for text in captured + [p.read_text(
        encoding="utf-8") for p in env.work.rglob("*") if p.is_file()]:
        assert basic not in text
    assert "[REDACTED]" in (env.work / "imported" / "lf" / "runs" / "run-01.jsonl").read_text(
        encoding="utf-8")


# --- the fingerprint (security review, finding 5) ----------------------------------------------


class KeyInModelAnthropic(EchoingAnthropic):
    """A gateway that reports the model it served as "served-<the key it was sent>"."""

    def _create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Verdict: A")],
                               model=f"served-{self.api_key}")


def test_key_in_the_served_model_id_never_reaches_a_file(env, capsys, monkeypatch):
    monkeypatch.setattr(sys.modules["anthropic"], "Anthropic", KeyInModelAnthropic)
    captured = []

    def step(code, expected):
        out = capsys.readouterr()
        captured.extend([out.out, out.err])
        assert code == expected, out.err

    step(judge(env, "anthropic", "judge-old", "runs/old"), 0)
    step(cli("validate", env.anchors, "runs/old", "--out", "reports/old"), 0)
    step(cli("baseline", "set", "reports/old/report.json"), 0)
    step(cli("baseline", "show"), 0)
    step(cli("gate", "reports/old/report.json"), 1)
    assert_no_sentinel(env.work, *captured)
    served = f"served-{redact.REDACTED}"
    import json
    header, first = map(json.loads, (env.work / "runs/old/run-01.jsonl").read_text(encoding="utf-8")
                        .splitlines()[:2])
    assert header["fingerprint"]["snapshot"] == first["fingerprint"]["snapshot"] == served
    report = json.loads((env.work / "reports/old/report.json").read_text(encoding="utf-8"))
    assert report["fingerprint"]["snapshot"] == served
    assert report["snapshots_seen"] == [served]
    assert served in (env.work / "reports/old/report.html").read_text(encoding="utf-8")
    # In Markdown the brackets are escaped, so the marker cannot start a link.
    assert "served-\\[REDACTED\\]" in (env.work / "reports/old/gate.md").read_text(encoding="utf-8")


def test_old_files_with_a_key_in_the_fingerprint_render_without_it(pairwise_dir, monkeypatch):
    """A run file written before fingerprints were scrubbed: the key is in it already."""
    from judgekeeper.gate import evaluate, render_markdown
    from judgekeeper.html_report import render_html
    from judgekeeper.report import build_report

    key = SENTINELS["OPENAI_API_KEY"]
    for run in (pairwise_dir / "runs").glob("run-*.jsonl"):
        text = run.read_text(encoding="utf-8")
        assert '"model": "claude-haiku-4-5-20251001"' in text
        run.write_text(text.replace('"model": "claude-haiku-4-5-20251001"',
                                    f'"model": "served-{key}"')
                       .replace('"snapshot": "claude-haiku-4-5-20251001"',
                                f'"snapshot": "snap-{key}"'), encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", key)
    report = build_report(pairwise_dir / "anchors.jsonl", pairwise_dir / "runs")
    import json
    assert key not in json.dumps(report)
    assert report["fingerprint"]["model"] == f"served-{redact.REDACTED}"
    # And a report.json that already holds the key (built by an older version) renders clean.
    report["fingerprint"]["model"] = f"served-{key}"
    report["snapshots_seen"] = [f"snap-{key}"]
    assert key not in render_html(report)
    assert key not in render_markdown(evaluate(report))
