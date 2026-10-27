"""The API key names judgekeeper knows: names only, never a value. They tell redaction which
variables hold a key."""

from __future__ import annotations

import pytest

from judgekeeper import keys, redact

FAKE = "sk-proj-FAKEVALUEthatmustneverbeprinted0123456789"


def test_the_key_names_are_the_providers_keys():
    names = keys.key_names()
    assert {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY",
            "AWS_BEARER_TOKEN_BEDROCK", "AWS_SECRET_ACCESS_KEY"} <= names
    assert "OPENAI_TEMPERATURE" not in names  # a setting is no key


@pytest.mark.parametrize("name", sorted(keys.key_names()))
def test_every_key_names_value_is_scrubbed(name, monkeypatch):
    monkeypatch.setenv(name, FAKE)
    assert FAKE not in redact.scrub(f"error: bad key {FAKE}")


def test_the_new_aws_names_are_scrubbed(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKE1234")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fakeSecretValue/1234567890abcdefXYZ")
    text = redact.scrub("id AKIAFAKEFAKEFAKE1234 secret fakeSecretValue/1234567890abcdefXYZ")
    assert "AKIAFAKE" not in text and "fakeSecretValue" not in text
