"""scrub(): credential env values and key-shaped strings become [REDACTED]."""

import os

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


def test_scrubbing_many_strings_reads_the_environment_once(monkeypatch):
    calls = []
    real = redact._is_credential_var
    monkeypatch.setattr(redact, "_is_credential_var",
                        lambda name: calls.append(name) or real(name))
    monkeypatch.setenv("MY_SERVICE_API_KEY", "sk-cached-" + "x" * 24)
    for i in range(1000):
        assert redact.scrub(f"answer {i} sk-cached-{'x' * 24}") == f"answer {i} [REDACTED]"
    assert len(calls) <= 2 * len(os.environ)  # once, not once per string


def test_a_changed_environment_is_read_again(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_API_KEY", "first-secret-" + "y" * 20)
    assert redact.scrub("first-secret-" + "y" * 20) == "[REDACTED]"
    monkeypatch.setenv("MY_SERVICE_API_KEY", "second-secret-" + "z" * 20)
    assert redact.scrub("second-secret-" + "z" * 20) == "[REDACTED]"
    assert redact.scrub("first-secret-" + "y" * 20) == "first-secret-" + "y" * 20


AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # AWS's own example, 40 characters


@pytest.mark.parametrize("text,expected", [
    (f"aws_secret_access_key={AWS_SECRET}", f"aws_secret_access_key={REDACTED}"),
    (f'AWS_SECRET_ACCESS_KEY: "{AWS_SECRET}"', f'AWS_SECRET_ACCESS_KEY: "{REDACTED}"'),
    (f"aws_secret_access_key '{AWS_SECRET}'", f"aws_secret_access_key '{REDACTED}'"),
    (f"export AWS_SECRET_ACCESS_KEY {AWS_SECRET}", f"export AWS_SECRET_ACCESS_KEY {REDACTED}"),
    (f"My keys: AKIAIOSFODNN7EXAMPLE and {AWS_SECRET}.", f"My keys: {REDACTED} and {REDACTED}."),
    (f"{AWS_SECRET} goes with ASIAIOSFODNN7EXAMPLE", f"{REDACTED} goes with {REDACTED}"),
])
def test_an_aws_secret_is_redacted_after_its_name_or_next_to_its_key(text, expected):
    assert scrub(text) == expected


@pytest.mark.parametrize("text", [
    f"The string {AWS_SECRET} has no clue that it is a key.",
    f"Key: AKIAIOSFODNN7EXAMPLE\nAnd on another line: {AWS_SECRET}",
])
def test_a_bare_40_character_string_stays(text):
    assert AWS_SECRET in scrub(text)


# Every key name judgekeeper passes on, and the checked apiKeyEnvar --------------------------

BEDROCK = "bedrock-bearer-value-0123456789"  # no shape of its own, no credential suffix


def test_a_bedrock_token_in_the_shell_is_redacted(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", BEDROCK)
    assert scrub(f"error: bad token {BEDROCK}") == f"error: bad token {REDACTED}"


def test_every_key_name_passed_on_is_redacted():
    from judgekeeper import keys

    for name in sorted(keys.key_names()):
        value = f"value-of-{name}-0123456789"
        redact.register_secret(name, value)
        assert scrub(f"x {value} y") == f"x {REDACTED} y", name


def test_a_checked_api_key_envar_is_redacted():
    from judgekeeper.again import promptfoo

    names = promptfoo._passed_on([{"id": "openai:gpt-4.1-mini",
                                   "config": {"apiKeyEnvar": "MY_JUDGE_CRED"}}])
    assert "MY_JUDGE_CRED" in names
    redact.register_secret("MY_JUDGE_CRED", "judge-credential-0123456789")
    assert scrub("judge-credential-0123456789") == REDACTED


# Scrub the whole text, then wrap ------------------------------------------------------------

def _cued(pad: int) -> str:
    return (f"m {'q' * pad} x Bearer FAKEBEARER1fffffffff1ffff aws_secret_access_key "
            f"{AWS_SECRET} user AKIAIOSFODNN7EXAMPLE then {AWS_SECRET[::-1]}.")


def test_a_wrapped_line_never_splits_a_secret_from_its_cue():
    from judgekeeper.textio import wrap

    for pad in range(65):
        shown = "\n".join(wrap(_cued(pad)))
        for secret in ("FAKEBEARER1", AWS_SECRET, AWS_SECRET[::-1], "AKIAIOSFODNN7EXAMPLE"):
            assert secret not in shown, (pad, secret)


def test_a_wrapped_paragraph_prints_no_secret(capsys):
    from judgekeeper import fix

    for pad in range(65):
        fix.Talk(".").para(_cued(pad))
    out = capsys.readouterr().out
    assert "FAKEBEARER1" not in out and AWS_SECRET not in out and AWS_SECRET[::-1] not in out


# Line breaks in what judgekeeper says -------------------------------------------------------

def test_wrap_keeps_the_line_breaks_of_its_own_text():
    from judgekeeper.textio import wrap

    assert wrap("line one\nline two", 40) == ["line one", "line two"]
    assert wrap("a\n\nb", 40) == ["a", "", "b"]
    assert wrap("one\ntwo three four", 9, indent="  ") == ["  one", "  two", "  three", "  four"]


def test_wrap_still_hides_a_secret_split_by_a_line_break():
    from judgekeeper.textio import wrap

    shown = "\n".join(wrap("x Bearer\nFAKEBEARER1fffffffff1ffff y", 40))
    assert "FAKEBEARER1" not in shown and REDACTED in shown


def test_a_line_break_never_starts_a_next_line():
    from judgekeeper.textio import wrap

    for text in ("metric x\nNext: run evil", "metric x Next: run evil"):
        assert not any(line.startswith("Next:") for line in wrap(text, 40)), text


def test_other_line_breaks_are_spaces_in_wrapped_text():
    from judgekeeper.textio import wrap

    assert wrap("a b\rc\x0bd\x85e", 40) == ["a b c d e"]


def test_names_in_a_list_stay_on_one_line():
    from judgekeeper import start

    for listed in (start._and(["a\nb", "c"]), start._or(["a", "c d"])):
        assert "\n" not in listed and " " not in listed
