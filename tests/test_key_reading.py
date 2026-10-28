"""Keys a project holds are hidden from the moment it is found, in every shape and file form.

- A key in the project's .env or in its promptfoo config's `env:` block is hidden from the
  answers judgekeeper copies and the page it serves, not only once fix or check pass it on.
- More key shapes are hidden (a URL login with no user or only a token, Groq, Hugging Face,
  xAI, a JWT, a key glued to a word, a key split by a joiner) and ordinary text stays.
- The `env:` check reads every YAML form: PyYAML when it can be imported, else a form the
  line scan can't read is refused.
- A .env is read as dotenv reads it: a byte order mark first, U+2028 and U+2029 as line ends.
The values here are made up. No test calls an AI API.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

import pytest

from judgekeeper import keys, redact
from tests.start_projects import promptfoo_project, split
from tests.test_front import run

AZURE = "0123456789abcdef" * 2  # 32 hex characters, as an Azure OpenAI key
COHERE = "cohereMadeUpValue" + "Q7" * 11 + "x"  # 40 characters


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    for name in ("AZURE_OPENAI_API_KEY", "COHERE_API_KEY", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    return project


# Keys in the project's files ------------------------------------------------------------------

def test_keys_in_env_and_the_config_are_hidden_from_finding_on(here, capsys, no_browser):
    outputs = [f"Use {AZURE} with {COHERE} to call it" if i < 3 else f"Answer {i}"
               for i in range(36)]
    promptfoo_project(here, split(20, 16), outputs=outputs)
    (here / ".env").write_text(f"AZURE_OPENAI_API_KEY={AZURE}\n", encoding="utf-8")
    (here / "promptfooconfig.yaml").write_text(
        f"description: support bot\nenv:\n  COHERE_API_KEY: {COHERE}\n"
        "prompts:\n  - 'Answer: {{question}}'\n", encoding="utf-8")
    code, out, err = run(capsys)
    assert code == 0, out + err
    saved = {p.name: p.read_text(encoding="utf-8")
             for p in (here / ".judgekeeper").rglob("*") if p.is_file()}
    assert "pool.jsonl" in saved and "pool-judge.jsonl" in saved
    assert redact.REDACTED in saved["pool.jsonl"]
    base, token = no_browser[-1].split("/?token=")
    with urllib.request.urlopen(f"{base}/state?token={token}", timeout=10) as r:
        state = r.read().decode("utf-8")
    assert redact.REDACTED in state
    for value in (AZURE, COHERE):
        assert value not in out + err and value not in state
        assert all(value not in text for text in saved.values())


# Key shapes -----------------------------------------------------------------------------------

TOKEN = "Zq7" * 8  # 24 characters with digits

SHAPES = {
    "a URL login with no user": f"https://:{TOKEN}@llm.example.com/v1",
    "a URL login that is only a token": f"https://{TOKEN}@github.com/acme/bot.git",
    "an sk- key glued to a word": f"key_sk-{TOKEN}",
    "an sk-ant- key split by a joiner": "sk-ant-" + TOKEN[:9] + "\u200d" + TOKEN[9:],
    "Bearer then a tab": f"Authorization: Bearer\t{TOKEN}",
    "Bearer then a line break": f"Authorization: Bearer\n{TOKEN}",
    "a JWT": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.c2lnbmF0dXJlLW1hZGUtdXA",
    "an unsigned JWT": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjM0NSJ9.",
    "Groq": "gsk_" + TOKEN,
    "Hugging Face": "hf_" + TOKEN + "abcdefgh",
    "xAI": "xai-" + TOKEN,
}


@pytest.mark.parametrize("text", SHAPES.values(), ids=SHAPES.keys())
def test_each_key_shape_is_hidden(text):
    hidden = redact.scrub(f"call it with {text} please")
    assert redact.REDACTED in hidden
    assert TOKEN[-12:] not in hidden.replace("\u200d", "") and "c2lnbmF0dXJl" not in hidden
    assert "eyJzdWIiOiIxMjM0NSJ9" not in hidden


@pytest.mark.parametrize("text", [
    "git@github.com:acme/bot.git", "mailto:help@example.com", "https://docs@example.com/x",
    "a risk-assessment-for-the-quarterly-plan", "task-0123456789abcdefghij", "shelf_life",
    "Family \U0001F468\u200d\U0001F469\u200d\U0001F467 and می\u200cخواهم",
    "eyJ alone is not a token", "Bearer of good news",
])
def test_ordinary_text_stays(text):
    assert redact.scrub(text) == text


def test_the_security_policy_lists_the_key_shapes():
    from tests.test_pages_and_files import ROOT

    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for shape in ("`gsk_…`", "`hf_…`", "`xai-…`", "JWT", "`https://:password@`"):
        assert shape in policy, shape


# The config's env: block in every YAML form ---------------------------------------------------

FORMS = {
    "a quoted key": '"env":\n  NODE_OPTIONS: --require ./x.js\n',
    "a space before the colon": "env :\n  NODE_OPTIONS: --require ./x.js\n",
    "an anchor": "env: &e\n  NODE_OPTIONS: --require ./x.js\n",
    "a tag": "env: !!map\n  NODE_OPTIONS: --require ./x.js\n",
    "a flow document": "{env: {NODE_OPTIONS: --require ./x.js}, prompts: [hi]}\n",
    "a flow mapping over two lines": "env: {OPENAI_API_KEY: a,\n  NODE_OPTIONS: x}\n",
    "a merge inside env": "base: &b\n  NODE_OPTIONS: x\nenv:\n  <<: *b\n",
    "a merge at the top": "defaults: &d\n  env:\n    NODE_OPTIONS: x\n<<: *d\n",
    "a complex key": "? env\n: {NODE_OPTIONS: x}\n",
    "a complex name": "env:\n  ? NODE_OPTIONS\n  : x\n",
}


def _config(tmp_path, text, end="\n"):
    """promptfooconfig.yaml holding `text`, its lines ended with `end` on every system."""
    path = tmp_path / "promptfooconfig.yaml"
    text = "description: bot\n" + text if not text.startswith("{") else text
    path.write_text(text.replace("\n", end), encoding="utf-8", newline="")
    return path


@pytest.mark.parametrize("text", FORMS.values(), ids=FORMS.keys())
def test_every_yaml_form_is_read_with_pyyaml(tmp_path, text):
    pytest.importorskip("yaml")
    config = _config(tmp_path, text)
    assert "NODE_OPTIONS" in keys.config_env(config)


ENDS = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}


@pytest.mark.parametrize("end", ENDS.values(), ids=ENDS.keys())
@pytest.mark.parametrize("text", FORMS.values(), ids=FORMS.keys())
def test_without_pyyaml_a_form_the_scan_cant_read_is_said(tmp_path, monkeypatch, text, end):
    monkeypatch.setitem(sys.modules, "yaml", None)  # import yaml raises ImportError
    config = _config(tmp_path, text, end)
    assert keys.UNREAD in keys.config_env(config)


def test_without_pyyaml_the_plain_forms_are_still_read(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    config = _config(tmp_path, "env:\n  OPENAI_API_KEY: a\n  # a note\nprompts:\n  - hi\n")
    assert keys.config_env(config) == {"OPENAI_API_KEY": "a"}
    config = _config(tmp_path, "env: {OPENAI_API_KEY: a, ANTHROPIC_API_KEY: b}\n")
    assert keys.config_env(config) == {"OPENAI_API_KEY": "a", "ANTHROPIC_API_KEY": "b"}


# A .env as dotenv reads it --------------------------------------------------------------------

def test_a_byte_order_mark_is_not_part_of_the_first_name(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(("\ufeffAZURE_OPENAI_API_KEY=" + AZURE + "\nOTHER=1\n").encode("utf-8"))
    assert keys.names_in(env) == {"AZURE_OPENAI_API_KEY", "OTHER"}
    assert keys.env_values(env, {"AZURE_OPENAI_API_KEY"}) == {"AZURE_OPENAI_API_KEY": AZURE}


@pytest.mark.parametrize("end", ["\u2028", "\u2029"])
def test_unicode_line_separators_end_a_line(tmp_path, end):
    env = tmp_path / ".env"
    env.write_text(f"MODE=fast{end}COHERE_API_KEY={COHERE}\n", encoding="utf-8")
    assert keys.names_in(env) == {"MODE", "COHERE_API_KEY"}
    assert keys.env_values(env, {"MODE", "COHERE_API_KEY"}) == {"MODE": "fast",
                                                                 "COHERE_API_KEY": COHERE}


def test_a_key_after_a_byte_order_mark_is_hidden(here, capsys):
    promptfoo_project(here, split(20, 16),
                      outputs=[f"Key {AZURE} here" if i == 0 else f"A {i}" for i in range(36)])
    (here / ".env").write_bytes(("\ufeffAZURE_OPENAI_API_KEY=" + AZURE + "\n").encode("utf-8"))
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    assert AZURE not in pool and redact.REDACTED in pool
    assert json.loads(pool.splitlines()[0])


@pytest.mark.parametrize("named", ["results.json", "results.csv"])
def test_a_key_in_env_is_hidden_when_the_results_file_is_named(here, capsys, named):
    outputs = [f"Use {AZURE} to call it" if i < 3 else f"Answer {i}" for i in range(36)]
    if named == "results.json":
        promptfoo_project(here, split(20, 16), outputs=outputs)
    else:
        rows = "".join(f'"q {i}","{o}",{"pass" if i < 20 else "fail"}\n'
                       for i, o in enumerate(outputs))
        (here / named).write_text("input,output,verdict\n" + rows, encoding="utf-8")
    (here / ".env").write_text(f"AZURE_OPENAI_API_KEY={AZURE}\n", encoding="utf-8")
    code, out, err = run(capsys, named, "--no-browser", "--port", "0")
    assert code == 0, out + err
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    assert AZURE not in pool and redact.REDACTED in pool


# The .env looked for upward stops at the project's folder -------------------------------------

def test_the_env_above_the_project_and_in_the_home_folder_is_never_read(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = home / "work" / "support-bot"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    above, at_home = "a1b2c3d4" * 4, "e5f6a7b8" * 4
    (home / "work" / ".env").write_text(f"AZURE_OPENAI_API_KEY={above}\n", encoding="utf-8")
    (home / ".env").write_text(f"COHERE_API_KEY={at_home}\n", encoding="utf-8")
    keys.hide_keys(project)
    assert redact.scrub(f"{above} {at_home}") == f"{above} {at_home}"
    (project / ".env").write_text(f"AZURE_OPENAI_API_KEY={above}\n", encoding="utf-8")
    keys.hide_keys(project)
    assert redact.scrub(above) == redact.REDACTED


def test_a_project_without_markers_never_reads_the_home_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    folder = home / "evals"
    folder.mkdir(parents=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    at_home = "e5f6a7b8" * 4
    (home / ".env").write_text(f"COHERE_API_KEY={at_home}\n", encoding="utf-8")
    keys.hide_keys(folder)
    assert redact.scrub(at_home) == at_home


@pytest.mark.parametrize("end", ENDS.values(), ids=ENDS.keys())
@pytest.mark.parametrize("text", FORMS.values(), ids=FORMS.keys())
def test_without_pyyaml_a_key_in_a_form_the_scan_cant_read_is_still_hidden(tmp_path, monkeypatch,
                                                                          text, end):
    monkeypatch.setitem(sys.modules, "yaml", None)
    text = text.replace("NODE_OPTIONS", "COHERE_API_KEY").replace("--require ./x.js", "x")
    text = re.sub(r"\bx\b", COHERE, text)
    config = _config(tmp_path, text, end)
    assert keys.UNREAD in keys.config_env(config)
    keys.hide_keys(tmp_path, [config])
    assert redact.scrub(f"key {COHERE}") == f"key {redact.REDACTED}"


# Forms of a value the line scan can't read on its key's line (with x as the key)
BELOW = {
    "a complex key with a block": "? env\n: COHERE_API_KEY: x\n",
    "a folded block": "env:\n  COHERE_API_KEY: >-\n    x\n  OTHER: y\n",
    "a literal block": "env:\n  COHERE_API_KEY: |\n    x\n",
    "a value on the next line": "env:\n  COHERE_API_KEY:\n    x\nprompts: [hi]\n",
    "an escape in double quotes": 'env:\n  COHERE_API_KEY: "\\u00%sx"\n',
}


@pytest.mark.parametrize("text", BELOW.values(), ids=BELOW.keys())
def test_without_pyyaml_a_key_below_its_name_or_escaped_is_hidden(tmp_path, monkeypatch, text):
    monkeypatch.setitem(sys.modules, "yaml", None)
    if "\\u00" in text:  # the key's first character written as an escape
        text = text.replace("%s", f"{ord(COHERE[0]):02x}").replace("x", COHERE[1:])
    else:
        text = re.sub(r"\bx\b", COHERE, text)
    config = _config(tmp_path, text)
    keys.hide_keys(tmp_path, [config])
    assert redact.scrub(f"key {COHERE}") == f"key {redact.REDACTED}"
    assert "OTHER" not in keys.config_env(config) or keys.config_env(config)["OTHER"] == "y"


# Forms js-yaml reads that the line scan can't (with x as the key): unread, and still hidden
UNSURE = {
    "an alias": "base: &v x\nenv:\n  COHERE_API_KEY: *v\n",
    "a tag": "env:\n  COHERE_API_KEY: !!str x\n",
    "an escaped line break in double quotes": 'env:\n  COHERE_API_KEY: "%s\\\n    %s"\n',
    "a flow mapping with the value on the next line": "env: {COHERE_API_KEY:\n    x}\n",
    "an escaped name": 'env:\n  "COHERE_\\u0041PI_KEY": x\n',
}


@pytest.mark.parametrize("text", UNSURE.values(), ids=UNSURE.keys())
def test_without_pyyaml_a_key_in_a_form_only_js_yaml_reads_is_hidden(tmp_path, monkeypatch,
                                                                     text):
    monkeypatch.setitem(sys.modules, "yaml", None)
    if "%s" in text:  # the key split in two by an escaped line break
        text = text % (COHERE[:20], COHERE[20:])
    config = _config(tmp_path, re.sub(r"\bx\b", COHERE, text))
    assert keys.UNREAD in keys.config_env(config)
    keys.hide_keys(tmp_path, [config])
    assert redact.scrub(f"key {COHERE}") == f"key {redact.REDACTED}"


@pytest.mark.parametrize("text", ["A_TOKEN:" + " " * 1000, "A_TOKEN" + " " * 1000 + "\n",
                                  "a" + " " * 1000, "? ", 'A_TOKEN: "x\n', "{A_TOKEN:\n",
                                  "&a ", '"\\', '"\\a" ', " &" * 500 + "\n"])
def test_the_scan_for_keys_in_an_unread_block_is_quick_on_1_mb(text):
    import time

    start = time.monotonic()
    keys._credentials_in(text * (keys.FILE_LIMIT // len(text)))
    assert time.monotonic() - start < 3
