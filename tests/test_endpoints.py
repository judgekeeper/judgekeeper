"""--base-url and --api-key-env: what reaches the SDK client, the endpoint in the fingerprint."""

import json
import sys
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from judgekeeper.cli import main
from judgekeeper.fingerprint import JudgeFingerprint, endpoint_host, plaintext_warning
from judgekeeper.runners import AnthropicRunner, OpenAIRunner
from judgekeeper.runners.base import PLACEHOLDER_KEY

PROMPT = """---
rubric_version: test-v1
---
{{input}} / {{output_a}} / {{output_b}}
"""


class FakeHttpClient:
    """Stands in for the SDKs' DefaultHttpxClient: records how it was configured."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAnthropicClient:
    instances: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeAnthropicClient.instances.append(self)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Verdict: A")],
                               model=kwargs["model"])


class FakeOpenAIClient:
    instances: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeOpenAIClient.instances.append(self)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        msg = SimpleNamespace(content="Verdict: A")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model=kwargs["model"])


@pytest.fixture
def sdks(monkeypatch):
    """Fake `anthropic` and `openai` modules whose client classes record their kwargs."""
    FakeAnthropicClient.instances = []
    FakeOpenAIClient.instances = []
    anthropic = ModuleType("anthropic")
    anthropic.Anthropic = FakeAnthropicClient
    openai = ModuleType("openai")
    openai.OpenAI = FakeOpenAIClient
    anthropic.DefaultHttpxClient = openai.DefaultHttpxClient = FakeHttpClient
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    monkeypatch.setitem(sys.modules, "openai", openai)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL",
                 "MY_GATEWAY_KEY"):
        monkeypatch.delenv(name, raising=False)
    return SimpleNamespace(anthropic=FakeAnthropicClient, openai=FakeOpenAIClient)


@pytest.fixture
def prompt(tmp_path):
    p = tmp_path / "prompt.md"
    p.write_text(PROMPT)
    return p


# --- endpoint_host ---------------------------------------------------------------------------


@pytest.mark.parametrize("url,host", [
    (None, None),
    ("", None),
    ("https://openrouter.ai/api/v1", "openrouter.ai"),
    ("http://localhost:11434/v1", "localhost"),
    ("https://My-Res.openai.azure.com/openai/v1/?api-version=x", "my-res.openai.azure.com"),
    ("http://127.0.0.1:8000", "127.0.0.1"),
])
def test_endpoint_host(url, host):
    assert endpoint_host(url) == host


@pytest.mark.parametrize("url", [
    "https://user:hunter2-password@gateway.example.com/v1",
    "https://token-only@gateway.example.com/v1",
])
def test_endpoint_with_userinfo_rejected_without_echoing_it(url):
    with pytest.raises(ValueError) as e:
        endpoint_host(url)
    assert "credentials" in str(e.value)
    assert "hunter2" not in str(e.value) and "token-only" not in str(e.value)


@pytest.mark.parametrize("url", ["gateway.example.com/v1", "ftp://host/x", "https:///nohost"])
def test_endpoint_must_be_http_url(url):
    with pytest.raises(ValueError):
        endpoint_host(url)


def test_fingerprint_without_endpoint_reads_as_default():
    old = {"provider": "anthropic", "model": "m", "snapshot": None, "prompt_hash": "h",
           "rubric_version": "v1", "temperature": 0.0, "created_at": "2026-10-01T00:00:00Z"}
    fp = JudgeFingerprint.from_dict(old)
    assert fp.endpoint is None
    assert fp.to_dict()["endpoint"] is None
    assert fp.identity() != fp.with_(endpoint="gateway.example.com").identity()


# --- runners ---------------------------------------------------------------------------------


def test_anthropic_base_url_and_key_env_reach_client(sdks, prompt, monkeypatch):
    monkeypatch.setenv("MY_GATEWAY_KEY", "gateway-key-value")
    runner = AnthropicRunner(model="m", prompt_path=prompt, base_url="https://gw.example.com/a",
                             api_key_env="MY_GATEWAY_KEY")
    kwargs = sdks.anthropic.instances[-1].kwargs
    assert kwargs["api_key"] == "gateway-key-value"
    assert kwargs["base_url"] == "https://gw.example.com/a"
    assert runner.fingerprint.endpoint == "gw.example.com"
    assert not runner.used_placeholder_key


def test_openai_base_url_and_key_env_reach_client(sdks, prompt, monkeypatch):
    monkeypatch.setenv("MY_GATEWAY_KEY", "gateway-key-value")
    runner = OpenAIRunner(model="m", prompt_path=prompt, base_url="https://openrouter.ai/api/v1",
                          api_key_env="MY_GATEWAY_KEY")
    kwargs = sdks.openai.instances[-1].kwargs
    assert kwargs["api_key"] == "gateway-key-value"
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert runner.fingerprint.endpoint == "openrouter.ai"


def test_default_key_env_and_no_base_url(sdks, prompt, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-value")
    runner = OpenAIRunner(model="m", prompt_path=prompt)
    kwargs = sdks.openai.instances[-1].kwargs
    assert kwargs["api_key"] == "openai-key-value"
    assert "base_url" not in kwargs
    assert runner.fingerprint.endpoint is None


def test_sdk_base_url_env_var_still_works(sdks, prompt, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key-value")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env-gw.example.com")
    runner = AnthropicRunner(model="m", prompt_path=prompt)
    assert sdks.anthropic.instances[-1].kwargs["base_url"] == "https://env-gw.example.com"
    assert runner.fingerprint.endpoint == "env-gw.example.com"


def test_base_url_flag_wins_over_env_var(sdks, prompt, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example.com/v1")
    runner = OpenAIRunner(model="m", prompt_path=prompt, base_url="http://localhost:8000/v1")
    assert sdks.openai.instances[-1].kwargs["base_url"] == "http://localhost:8000/v1"
    assert runner.fingerprint.endpoint == "localhost"


def test_base_url_without_key_uses_placeholder(sdks, prompt):
    runner = OpenAIRunner(model="m", prompt_path=prompt, base_url="http://localhost:11434/v1")
    assert sdks.openai.instances[-1].kwargs["api_key"] == PLACEHOLDER_KEY
    assert runner.used_placeholder_key


def test_no_base_url_and_no_key_fails(sdks, prompt):
    with pytest.raises(RuntimeError, match="MY_GATEWAY_KEY is not set"):
        AnthropicRunner(model="m", prompt_path=prompt, api_key_env="MY_GATEWAY_KEY")
    assert sdks.anthropic.instances == []


def test_userinfo_base_url_rejected_by_runner(sdks, prompt, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-value")
    with pytest.raises(ValueError, match="credentials"):
        OpenAIRunner(model="m", prompt_path=prompt, base_url="https://u:p@h.example.com/v1")


# --- CLI -------------------------------------------------------------------------------------


def judge(pairwise_dir, tmp_path, *extra):
    return main(["judge", str(pairwise_dir / "anchors.jsonl"), "--model", "m",
                 "--prompt", str(tmp_path / "prompt.md"), "--out", str(tmp_path / "runs"),
                 *extra])


def test_cli_flags_reach_client_and_fingerprint(sdks, prompt, pairwise_dir, tmp_path,
                                                monkeypatch):
    monkeypatch.setenv("MY_GATEWAY_KEY", "gateway-key-value")
    assert judge(pairwise_dir, tmp_path, "--runner", "openai",
                 "--base-url", "https://openrouter.ai/api/v1",
                 "--api-key-env", "MY_GATEWAY_KEY") == 0
    kwargs = sdks.openai.instances[-1].kwargs
    assert kwargs["api_key"] == "gateway-key-value"
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
    lines = (tmp_path / "runs" / "run-01.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["fingerprint"]["endpoint"] == "openrouter.ai"
    assert all(json.loads(x)["fingerprint"]["endpoint"] == "openrouter.ai" for x in lines[1:])


def test_cli_placeholder_key_prints_one_note(sdks, prompt, pairwise_dir, tmp_path, capsys):
    assert judge(pairwise_dir, tmp_path, "--runner", "openai",
                 "--base-url", "http://localhost:11434/v1") == 0
    err = capsys.readouterr().err
    assert err.count("note:") == 1
    assert "OPENAI_API_KEY" in err and "local servers need no key" in err


def test_cli_missing_key_without_base_url_is_usage_error(sdks, prompt, pairwise_dir, tmp_path):
    assert judge(pairwise_dir, tmp_path, "--runner", "anthropic") == 2
    assert judge(pairwise_dir, tmp_path, "--runner", "openai", "--api-key-env", "NOPE_KEY") == 2


def test_cli_userinfo_base_url_is_usage_error(sdks, prompt, pairwise_dir, tmp_path, capsys,
                                              monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key-value")
    assert judge(pairwise_dir, tmp_path, "--runner", "anthropic",
                 "--base-url", "https://me:hunter2-pass@gw.example.com") == 2
    err = capsys.readouterr().err
    assert "credentials" in err and "hunter2" not in err
    assert not (tmp_path / "runs").exists()


def test_cli_api_key_env_must_be_a_name_not_a_value(sdks, prompt, pairwise_dir, tmp_path,
                                                    capsys):
    assert judge(pairwise_dir, tmp_path, "--runner", "anthropic",
                 "--api-key-env", "sk-ant-api03-pasted-a-key-here") == 2
    err = capsys.readouterr().err
    assert "name of an environment variable" in err
    assert "pasted-a-key" not in err


def test_cli_flags_rejected_for_replay(pairwise_dir, tmp_path):
    assert main(["judge", str(pairwise_dir / "anchors.jsonl"), "--runner", "replay",
                 "--fixture", str(pairwise_dir / "runs" / "run-01.jsonl"),
                 "--base-url", "https://x.example.com", "--out", str(tmp_path / "r")]) == 2


def test_help_says_there_is_no_key_flag(capsys):
    assert main(["judge", "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "--api-key-env" in out and "--base-url" in out
    assert "no flag that takes a key value" in out


def test_base_url_env_var_alone_still_needs_a_key(sdks, prompt, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        OpenAIRunner(model="m", prompt_path=prompt)


# --- plain http:// to a remote host (security audit item 6) ------------------------------------


@pytest.mark.parametrize("url", [
    None, "", "https://openrouter.ai/api/v1", "http://localhost:11434/v1",
    "http://127.0.0.1:8000", "http://[::1]:8000/v1", "http://ollama.localhost:11434",
])
def test_no_plaintext_warning_for_https_or_local(url):
    assert plaintext_warning(url) is None


def test_plaintext_warning_names_the_host_not_the_url():
    w = plaintext_warning("http://gateway.example.com/v1?trace=abc")
    assert "gateway.example.com" in w and "unencrypted" in w
    assert "trace=abc" not in w and "/v1" not in w


def test_cli_warns_about_plain_http_gateway(sdks, prompt, pairwise_dir, tmp_path, capsys,
                                           monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-value")
    assert judge(pairwise_dir, tmp_path, "--runner", "openai",
                 "--base-url", "http://gateway.example.com/v1") == 0
    err = capsys.readouterr().err
    assert err.count("warning:") == 1 and "unencrypted" in err


def test_cli_does_not_warn_about_local_http(sdks, prompt, pairwise_dir, tmp_path, capsys):
    assert judge(pairwise_dir, tmp_path, "--runner", "openai",
                 "--base-url", "http://localhost:11434/v1") == 0
    assert "unencrypted" not in capsys.readouterr().err


# --- redirects (security review, finding 4) -----------------------------------------------------


@pytest.mark.parametrize("cls,sdk", [(AnthropicRunner, "anthropic"), (OpenAIRunner, "openai")])
def test_sdk_client_is_built_not_to_follow_redirects(sdks, prompt, monkeypatch, cls, sdk):
    monkeypatch.setenv(cls.key_env, "some-key-value")
    cls(model="m", prompt_path=prompt, base_url="https://gw.example.com/v1")
    http_client = getattr(sdks, sdk).instances[-1].kwargs["http_client"]
    assert isinstance(http_client, FakeHttpClient)
    assert http_client.kwargs == {"follow_redirects": False}


@pytest.mark.parametrize("cls,sdk", [(AnthropicRunner, "anthropic"), (OpenAIRunner, "openai")])
def test_sdk_that_cannot_turn_redirects_off_is_refused(sdks, prompt, monkeypatch, cls, sdk):
    """An SDK too old to take the setting: no client, so no key is ever sent with it."""
    monkeypatch.delattr(sys.modules[sdk], "DefaultHttpxClient")
    monkeypatch.setenv(cls.key_env, "some-key-value")
    with pytest.raises(RuntimeError, match="redirects") as e:
        cls(model="m", prompt_path=prompt)
    assert "some-key-value" not in str(e.value)
    assert getattr(sdks, sdk).instances == []
