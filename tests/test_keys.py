"""Which key a judge will use: names only, never a value."""

from __future__ import annotations

import sys

import pytest

from judgekeeper import keys, redact
from judgekeeper.keys import check, names_in, promptfoo_default, provider_of

FAKE = "sk-proj-FAKEVALUEthatmustneverbeprinted0123456789"


# The provider, from each tool's way of naming the model -----------------------------------

@pytest.mark.parametrize("model, provider, expected", [
    ("openai:gpt-4.1-mini", None, "openai"),                 # promptfoo
    ("openai:chat:gpt-4.1-mini", None, "openai"),
    ("anthropic:messages:claude-sonnet-4-6", None, "anthropic"),
    ("azure:chat:my-deployment", None, "azure"),
    ("bedrock:anthropic.claude-haiku", None, "bedrock"),
    ("vertex:gemini-3.8-flash", None, "vertex"),
    ("google:gemini-3.8-flash", None, "google"),
    ("claude-sonnet-4-6 (Anthropic)", None, "anthropic"),    # DeepEval
    ("my-deployment (Azure)", None, "azure"),
    ("gemini-3.8-flash (Gemini)", None, "google"),
    ("gpt-4.1", None, "openai"),                             # DeepEval: bare is OpenAI
    ("anthropic/claude-sonnet-4-6", None, "anthropic"),      # Inspect
    ("openai/gpt-4o", None, "openai"),
    ("grok/grok-4.3", None, "xai"),
    ("openai:/gpt-4.1-mini", None, "openai"),                # MLflow
    ("anthropic:/claude-haiku-4-5", None, "anthropic"),
    ("whatever", "anthropic", "anthropic"),                  # the fingerprint's provider
    ("mystery-model", None, None),
    (None, None, None),
])
def test_the_provider_comes_from_the_model(model, provider, expected):
    assert provider_of(model, provider) == expected


# .env names ----------------------------------------------------------------------------

def test_env_files_give_names_only(tmp_path):
    (tmp_path / ".env").write_text(
        "# a comment\n"
        f"OPENAI_API_KEY={FAKE}\n"
        f"export ANTHROPIC_API_KEY = '{FAKE}'\n"
        "  SPACED=1\n"
        "not a line\n"
        "9BAD=1\n"
        "=novalue\n", encoding="utf-8")
    names = names_in(tmp_path / ".env")
    assert names == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SPACED"}
    assert all(FAKE not in n for n in names)


def test_a_missing_env_file_has_no_names(tmp_path):
    assert names_in(tmp_path / ".env") == set()


def test_the_promptfoo_env_block_by_a_line_scan(tmp_path):
    config = tmp_path / "promptfooconfig.yaml"
    config.write_text("description: x\nenv:\n  OPENAI_API_KEY: " + FAKE + "\n"
                      "  # skipped\n  OPENAI_TEMPERATURE: 0.2\n    NESTED: no\n"
                      "prompts:\n  - hi\n", encoding="utf-8")
    assert keys.config_env_names(config) == {"OPENAI_API_KEY", "OPENAI_TEMPERATURE"}


def test_the_promptfoo_env_block_of_a_json_config(tmp_path):
    config = tmp_path / "promptfooconfig.json"
    config.write_text('{"env": {"ANTHROPIC_API_KEY": "' + FAKE + '"}}', encoding="utf-8")
    assert keys.config_env_names(config) == {"ANTHROPIC_API_KEY"}


# Messages --------------------------------------------------------------------------------

@pytest.fixture
def clean(monkeypatch, tmp_path):
    """No key variables in the shell, and no credential files in the home folder."""
    for name in list(keys.all_names()) + ["APP_ENV", "DOTENV_PATH", "DOTENV_CONFIG_PATH"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "HOME", tmp_path / "home")
    return monkeypatch


def test_a_key_in_the_shell(clean, tmp_path):
    clean.setenv("OPENAI_API_KEY", FAKE)
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path)
    assert k.ok and k.name == "OPENAI_API_KEY"
    assert k.lines == [("Your judge will use your OpenAI key (OPENAI_API_KEY, set in your "
                        "shell).")]


def test_a_key_in_env_that_the_tool_loads(clean, tmp_path):
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE}\n")
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path)
    assert k.ok
    assert k.lines == [("Your judge will use your OpenAI key (OPENAI_API_KEY, in .env in this "
                        "folder; promptfoo loads it).")]


def test_the_shell_wins_over_env(clean, tmp_path):
    clean.setenv("OPENAI_API_KEY", FAKE)
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE}\n")
    assert "set in your shell" in check("gpt-4.1", "deepeval", tmp_path).lines[0]


def test_the_promptfoo_config_env_block_wins(clean, tmp_path):
    clean.setenv("OPENAI_API_KEY", FAKE)
    config = tmp_path / "promptfooconfig.yaml"
    config.write_text("env:\n  OPENAI_API_KEY: x\n")
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path, config=config)
    assert k.lines[0] == ("Your judge will use your OpenAI key (OPENAI_API_KEY, in the env: "
                          "block of promptfooconfig.yaml; promptfoo uses it).")


def test_deepeval_also_reads_env_local_and_the_app_env_file(clean, tmp_path):
    (tmp_path / ".env.local").write_text("ANTHROPIC_API_KEY=x\n")
    k = check("claude-sonnet-4-6 (Anthropic)", "deepeval", tmp_path)
    assert k.ok and "in .env.local in this folder; DeepEval loads it" in k.lines[0]
    clean.setenv("APP_ENV", "staging")
    (tmp_path / ".env.local").unlink()
    (tmp_path / ".env.staging").write_text("ANTHROPIC_API_KEY=x\n")
    assert "in .env.staging in this folder" in check(
        "claude-sonnet-4-6 (Anthropic)", "deepeval", tmp_path).lines[0]


def test_mlflow_needs_the_key_in_the_shell(clean, tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=x\n")
    k = check("openai:/gpt-4.1-mini", "mlflow", tmp_path)
    assert not k.ok
    (line,) = k.lines
    assert line.startswith("Your judge needs OPENAI_API_KEY. It is in .env in this folder, but "
                           "MLflow does not load .env files: set it in your shell (")
    how = "$env:OPENAI_API_KEY = '...'" if sys.platform == "win32" else "export OPENAI_API_KEY=..."
    assert how in line


def test_a_missing_key(clean, tmp_path):
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path)
    assert not k.ok
    assert k.lines == [("Your judge needs OPENAI_API_KEY. It is not set in your shell or in "
                        ".env.")]


def test_a_key_named_by_the_grader(clean, tmp_path):
    clean.setenv("MY_JUDGE_KEY", FAKE)
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path, key_env="MY_JUDGE_KEY")
    assert k.ok and k.name == "MY_JUDGE_KEY"


def test_one_of_several_names(clean, tmp_path):
    clean.setenv("GEMINI_API_KEY", FAKE)
    k = check("google:gemini-3.8-flash", "promptfoo", tmp_path)
    assert k.ok and k.name == "GEMINI_API_KEY"
    clean.delenv("GEMINI_API_KEY")
    assert check("google:gemini-3.8-flash", "promptfoo", tmp_path).lines == [
        ("Your judge needs GOOGLE_API_KEY (or GEMINI_API_KEY or PALM_API_KEY). It is not set "
         "in your shell or in .env.")]


def test_credential_files_are_named_never_read(clean, tmp_path):
    aws = keys.HOME / ".aws"
    aws.mkdir(parents=True)
    (aws / "credentials").write_text(f"[default]\naws_secret_access_key = {FAKE}\n")
    k = check("bedrock:anthropic.claude-haiku", "promptfoo", tmp_path)
    assert k.ok and k.lines == ["AWS profile found; your judge will use it."]
    gcloud = keys.HOME / ".config" / "gcloud"
    gcloud.mkdir(parents=True)
    (gcloud / "application_default_credentials.json").write_text("{}")
    k = check("vertex:gemini-3.8-flash", "promptfoo", tmp_path)
    assert k.ok and k.lines == ["Google default credentials found; your judge will use them."]


def test_ollama_needs_no_key(clean, tmp_path):
    k = check("ollama:chat:llama3.3", "promptfoo", tmp_path)
    assert k.ok and k.lines == ["Your judge runs on Ollama; it needs no key."]


def test_an_unknown_provider_is_said(clean, tmp_path):
    k = check("mystery-model", "inspect", tmp_path)
    assert k.ok and k.provider is None
    assert k.lines == [("I can't tell which key your judge needs (its model is "
                        "mystery-model); your tool looks for it itself.")]


def test_setting_variables_are_named(clean, tmp_path):
    clean.setenv("OPENAI_API_KEY", FAKE)
    clean.setenv("OPENAI_TEMPERATURE", "0.7")
    (tmp_path / ".env").write_text("OPENAI_BASE_URL=http://proxy\n")
    k = check("openai:gpt-4.1-mini", "promptfoo", tmp_path)
    assert k.settings == ["OPENAI_BASE_URL", "OPENAI_TEMPERATURE"]
    assert "OPENAI_BASE_URL and OPENAI_TEMPERATURE are set; they change your judge." in k.lines


def test_one_setting_variable(clean, tmp_path):
    clean.setenv("AWS_BEDROCK_TEMPERATURE", "1")
    clean.setenv("AWS_BEARER_TOKEN_BEDROCK", FAKE)
    k = check("bedrock:x", "promptfoo", tmp_path)
    assert "AWS_BEDROCK_TEMPERATURE is set; it changes your judge." in k.lines


def test_no_value_ever_reaches_any_output(clean, tmp_path, capsys):
    clean.setenv("OPENAI_API_KEY", FAKE)
    (tmp_path / ".env").write_text(f"ANTHROPIC_API_KEY={FAKE}\nOPENAI_TEMPERATURE={FAKE}\n")
    config = tmp_path / "promptfooconfig.yaml"
    config.write_text(f"env:\n  MISTRAL_API_KEY: {FAKE}\n")
    seen = []
    for model, tool in (("openai:gpt-4.1-mini", "promptfoo"), ("claude-x (Anthropic)",
                                                                "deepeval"),
                        ("mistral:large", "promptfoo"), ("openai:/gpt-4.1", "mlflow")):
        k = check(model, tool, tmp_path, config=config)
        seen.append(repr(k))
    seen.append(repr(promptfoo_default(tmp_path, config, "0.123.1")))
    out, err = capsys.readouterr()
    assert FAKE not in "".join(seen) + out + err


def test_names_found_are_registered_for_scrubbing(clean, tmp_path):
    clean.setenv("MY_JUDGE_KEY", FAKE)
    check("openai:gpt-4.1-mini", "promptfoo", tmp_path, key_env="MY_JUDGE_KEY")
    assert FAKE not in redact.scrub(f"error: bad key {FAKE}")


def test_the_new_aws_names_are_scrubbed(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKE1234")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fakeSecretValue/1234567890abcdefXYZ")
    text = redact.scrub("id AKIAFAKEFAKEFAKE1234 secret fakeSecretValue/1234567890abcdefXYZ")
    assert "AKIAFAKE" not in text and "fakeSecretValue" not in text


# promptfoo's default grader ---------------------------------------------------------------

@pytest.mark.parametrize("names, family, model", [
    ({"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}, "openai", "gpt-5.6-sol"),
    ({"ANTHROPIC_API_KEY"}, "anthropic", "claude-sonnet-4-6"),
    ({"GEMINI_API_KEY", "MISTRAL_API_KEY"}, "google", "gemini-3.8-flash"),
    ({"MISTRAL_API_KEY", "XAI_API_KEY"}, "mistral", "mistral-large-latest"),
    ({"XAI_API_KEY"}, "xai", None),
    ({"AZURE_OPENAI_API_KEY", "AZURE_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME"},
     "azure", None),
    ({"AZURE_OPENAI_API_KEY"}, "openai", "gpt-5.6-sol"),  # no deployment names: OpenAI
    (set(), "openai", "gpt-5.6-sol"),
])
def test_the_default_grader_follows_promptfoos_order(clean, tmp_path, names, family, model):
    for name in names:
        clean.setenv(name, "x")
    d = promptfoo_default(tmp_path, None, "0.123.1")
    assert (d.family, d.model) == (family, model)


def test_the_default_grader_reads_env_files_and_the_config(clean, tmp_path):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=x\n")
    assert promptfoo_default(tmp_path, None, "0.123.1").family == "anthropic"
    config = tmp_path / "promptfooconfig.yaml"
    config.write_text("env:\n  OPENAI_API_KEY: x\n")
    assert promptfoo_default(tmp_path, config, "0.123.1").family == "openai"


def test_the_default_grader_for_an_unknown_version(clean, tmp_path):
    d = promptfoo_default(tmp_path, None, "0.200.0")
    assert d.family == "openai" and d.model is None
    assert d.words == "promptfoo's default grader for your promptfoo version"
    known = promptfoo_default(tmp_path, None, "0.123.1")
    assert known.words == ("promptfoo's default grader, probably gpt-5.6-sol with promptfoo "
                           "0.123.1")
