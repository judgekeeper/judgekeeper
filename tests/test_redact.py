"""scrub(): credential env values and key-shaped strings become [REDACTED]."""

import pytest

from judgekeeper import redact
from judgekeeper.redact import REDACTED, scrub


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_standard_key_vars_are_redacted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-value-123")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-value-456")
    text = "a=anthropic-value-123 o=openai-value-456 end"
    assert scrub(text) == f"a={REDACTED} o={REDACTED} end"


@pytest.mark.parametrize("name", ["GATEWAY_API_KEY", "HF_TOKEN", "MY_CLIENT_SECRET",
                                  "lower_api_key"])
def test_suffixed_vars_are_redacted(monkeypatch, name):
    monkeypatch.setenv(name, "value-from-suffix-var")
    assert scrub("x value-from-suffix-var y") == f"x {REDACTED} y"


def test_named_var_is_redacted(monkeypatch):
    monkeypatch.setenv("MY_GATEWAY_KEY", "gateway-credential-789")
    assert scrub("gateway-credential-789") == "gateway-credential-789"
    redact.register_key_env("MY_GATEWAY_KEY")
    assert scrub("gateway-credential-789") == REDACTED


def test_unrelated_vars_are_left_alone(monkeypatch):
    monkeypatch.setenv("HOME_DIRECTORY", "not-a-secret-value")
    assert scrub("not-a-secret-value") == "not-a-secret-value"


def test_short_values_are_left_alone(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "short")
    monkeypatch.setenv("X_TOKEN", "1234567")
    assert scrub("short and 1234567 stay") == "short and 1234567 stay"


def test_longer_value_wins_over_its_prefix(monkeypatch):
    monkeypatch.setenv("A_TOKEN", "prefix-value")
    monkeypatch.setenv("B_TOKEN", "prefix-value-and-more")
    assert scrub("prefix-value-and-more") == REDACTED


@pytest.mark.parametrize("text,expected", [
    ("key sk-ant-api03-AbCdEf0123456789_xyz-ABC rest", f"key {REDACTED} rest"),
    ("key sk-proj-AbCdEf0123456789abcdefXYZ rest", f"key {REDACTED} rest"),
    ("Authorization: Bearer abc.DEF-123_456~xyz", f"Authorization: Bearer {REDACTED}"),
    ("authorization: bearer abcdefgh12345678", f"authorization: bearer {REDACTED}"),
])
def test_key_shaped_strings_are_redacted(text, expected):
    assert scrub(text) == expected


@pytest.mark.parametrize("text", [
    "Output A follows the instruction; Verdict: A",
    "This is a risk-adjusted-performance-measure-for-tasks.",
    "ask-the-user-before-acting is the right call",
    "sk-short",
    "The bearer of bad news",
    "The Bearer responsibility-for-everything",
    "",
])
def test_ordinary_text_is_unchanged(text):
    assert scrub(text) == text


def test_none_passes_through():
    assert scrub(None) is None


def test_write_run_scrubs_rationales_and_errors(tmp_path, monkeypatch):
    import json

    from judgekeeper.fingerprint import JudgeFingerprint
    from judgekeeper.judgments import write_run

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-anthropic-key")
    fp = JudgeFingerprint(provider="anthropic", model="m", snapshot="m", prompt_hash="h",
                          rubric_version="v1", temperature=0.0, created_at="t")
    rec = {"type": "judgment", "id": "i1", "verdict": "A", "raw_score": None,
           "rationale": "saw sentinel-anthropic-key", "verdict_ba": "A", "raw_score_ba": None,
           "rationale_ba": "Bearer abcdef0123456789xyz", "error": "401 sentinel-anthropic-key",
           "fingerprint": fp.to_dict()}
    path = tmp_path / "run-01.jsonl"
    write_run(path, 1, "0" * 64, fp, [rec])
    text = path.read_text(encoding="utf-8")
    assert "sentinel-anthropic-key" not in text and "abcdef0123456789xyz" not in text
    line = json.loads(text.splitlines()[1])
    assert line["rationale"] == f"saw {REDACTED}"
    assert line["rationale_ba"] == f"Bearer {REDACTED}"
    assert line["error"] == f"401 {REDACTED}"
    assert line["id"] == "i1"


def test_html_report_scrubs_rationales(pairwise_dir, tmp_path, monkeypatch):
    """A run file that still holds a key (written unscrubbed) renders without it."""
    import json

    from judgekeeper.html_report import render_html
    from judgekeeper.report import build_report

    run = pairwise_dir / "runs" / "run-01.jsonl"
    run.write_text(run.read_text(
        encoding="utf-8").replace("run1 i4 AB", "leaked sentinel-openai-key-0001"),
                   encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-openai-key-0001")
    report = build_report(pairwise_dir / "anchors.jsonl", pairwise_dir / "runs")
    assert "sentinel-openai-key-0001" in json.dumps(report)  # the old file really had it
    html = render_html(report)
    assert "sentinel-openai-key-0001" not in html
    assert "leaked [REDACTED]" in html


@pytest.mark.parametrize("name", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
                                  "MLFLOW_TRACKING_PASSWORD", "DATABRICKS_TOKEN"])
def test_platform_credential_vars_are_redacted(monkeypatch, name):
    monkeypatch.setenv(name, "platform-credential-value")
    assert scrub("x platform-credential-value y") == f"x {REDACTED} y"


@pytest.mark.parametrize("text,expected", [
    ("Authorization: Basic cGstbGYtMTIzNDU2Nzg6c2stbGYtYWJjZGVm",
     f"Authorization: Basic {REDACTED}"),
    ("tracking https://alice:hunter2pass@mlflow.example.com/api rest",
     f"tracking https://{REDACTED}@mlflow.example.com/api rest"),
    ("postgresql://user:pw@db.example.com:5432/mlflow",
     f"postgresql://{REDACTED}@db.example.com:5432/mlflow"),
])
def test_basic_auth_and_url_credentials_are_redacted(text, expected):
    assert scrub(text) == expected


def test_basic_word_in_prose_is_left_alone():
    assert scrub("a basic check of the answer") == "a basic check of the answer"


def test_scrub_is_fast_on_long_dotted_text():
    """A URL scheme with no length limit would make this quadratic (about two seconds for
    80 KB, minutes for a megabyte)."""
    import time

    text = "a." * 500_000
    start = time.perf_counter()
    assert scrub(text) == text
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("text,expected", [
    ("postgres://user:pass@host/db", f"postgres://{REDACTED}@host/db"),
    ("see git+ssh://bob:hunter2@code.example.com/repo.git",
     f"see git+ssh://{REDACTED}@code.example.com/repo.git"),
])
def test_url_credentials_are_still_redacted(text, expected):
    assert scrub(text) == expected
