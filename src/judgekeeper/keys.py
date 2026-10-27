"""The API key names of the LLM providers judgekeeper knows, and the hiding of key values.

judgekeeper never needs, holds, prints, stores, logs or passes on a key. These names tell
`redact` which variables hold a key, so a value that turns up in a results file or an error is
scrubbed before it is shown or written. So is every credential in the project's .env files and
promptfoo configs, as soon as the project is found (`hide_keys`): only to hide it. A `.env`
line is read as dotenv reads it (`NAME=value`, `NAME: value`, `export`, quotes).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import textio
from judgekeeper.redact import is_credential, register_secret

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class Provider:
    label: str  # "OpenAI", as in "your OpenAI key"
    keys: tuple[tuple[str, ...], ...] = ()  # alternatives; each a set of names all needed
    settings: tuple[str, ...] = ()


PROVIDERS = {
    "openai": Provider("OpenAI", (("OPENAI_API_KEY",),), (
        "OPENAI_TEMPERATURE", "OPENAI_MAX_TOKENS", "OPENAI_MAX_COMPLETION_TOKENS",
        "OPENAI_TOP_P", "OPENAI_BASE_URL", "OPENAI_API_HOST", "OPENAI_API_BASE_URL",
        "OPENAI_API_BASE")),
    "anthropic": Provider("Anthropic", (("ANTHROPIC_API_KEY",),), (
        "ANTHROPIC_TEMPERATURE", "ANTHROPIC_MAX_TOKENS", "ANTHROPIC_BASE_URL")),
    "azure": Provider("Azure OpenAI", (
        ("AZURE_OPENAI_API_KEY",), ("AZURE_API_KEY",),
        ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID")), (
        "AZURE_OPENAI_API_HOST", "AZURE_OPENAI_BASE_URL")),
    "google": Provider("Google AI Studio", (
        ("GOOGLE_API_KEY",), ("GEMINI_API_KEY",), ("PALM_API_KEY",))),
    "vertex": Provider("Google Vertex", (("VERTEX_API_KEY",), ("GOOGLE_API_KEY",)), (
        "VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "VERTEX_REGION", "GOOGLE_CLOUD_LOCATION")),
    "bedrock": Provider("AWS Bedrock", (
        ("AWS_BEARER_TOKEN_BEDROCK",), ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")), (
        "AWS_BEDROCK_REGION", "AWS_BEDROCK_TEMPERATURE", "AWS_BEDROCK_MAX_TOKENS",
        "AWS_BEDROCK_TOP_P")),
    "mistral": Provider("Mistral", (("MISTRAL_API_KEY",),), (
        "MISTRAL_TEMPERATURE", "MISTRAL_MAX_TOKENS", "MISTRAL_API_HOST",
        "MISTRAL_API_BASE_URL")),
    "groq": Provider("Groq", (("GROQ_API_KEY",),)),
    "openrouter": Provider("OpenRouter", (("OPENROUTER_API_KEY",),)),
    "ollama": Provider("Ollama", (), ("OLLAMA_BASE_URL",)),
    "xai": Provider("xAI", (("XAI_API_KEY",), ("GROK_API_KEY",))),
    "codex": Provider("Codex", (("CODEX_API_KEY",),)),
}
# Settings a tool reads for every provider.
TOOL_SETTINGS = {"deepeval": ("TEMPERATURE", "DEEPEVAL_MODEL_THINKING")}


def all_names() -> set[str]:
    """Every variable name this module looks at."""
    names = {n for p in PROVIDERS.values() for alt in p.keys for n in alt}
    names |= {n for p in PROVIDERS.values() for n in p.settings}
    names |= {n for s in TOOL_SETTINGS.values() for n in s}
    names |= {"AZURE_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME",
              "GOOGLE_APPLICATION_CREDENTIALS", "AWS_PROFILE", "CODEX_HOME"}
    return names


def key_names() -> set[str]:
    """The API key names of the providers judgekeeper knows."""
    return {n for p in PROVIDERS.values() for alt in p.keys for n in alt}


# Hiding the values in the project's files --------------------------------------------------

# dotenv's line (dotenv 17, lib/main.js LINE), which promptfoo, Inspect AI and DeepEval read
# alike: `NAME=value` or `NAME: value`, after `export ` or not; a value quoted with ', " or `
# (over several lines too), else up to a `#`.
_DOTENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z0-9_.-]+)(?:\s*=\s*?|:\s+?)(\s*'(?:\\'|[^'])*'|"
    r"\s*\"(?:\\\"|[^\"])*\"|\s*`(?:\\`|[^`])*`|[^#\r\n]+)?\s*(?:#.*)?$", re.MULTILINE)


# Where JavaScript's `^` and `$` see a line end, as dotenv's LINE does: U+2028 and U+2029 too
_JS_LINE_ENDS = re.compile("\r\n?|[\u2028\u2029]")


def _dotenv_lines(path: Path):
    """(name, the value as written) for each line dotenv reads in a .env file, in order. A
    byte order mark at its start is not part of the first name. Only a regular file is read:
    a named pipe would wait forever."""
    try:
        text = textio.read_regular(path).decode("utf-8-sig", errors="replace")
    except OSError:
        return
    for m in _DOTENV_LINE.finditer(_JS_LINE_ENDS.sub("\n", text)):
        yield m[1], m[2] or ""


def names_in(path: Path) -> set[str]:
    """The variable names a .env file sets; the values are never kept."""
    return {name for name, _ in _dotenv_lines(path) if NAME.match(name)}


def env_values(path: Path, names) -> dict[str, str]:
    """The values a .env file gives the names in `names`, as dotenv reads them (a later line
    wins). No other line's value is kept."""
    found = {}
    for name, value in _dotenv_lines(path):
        if name in names:
            value = value.strip()
            quote = value[:1]
            value = re.sub(r"^(['\"`])([\s\S]*)\1$", r"\2", value, flags=re.MULTILINE)
            if quote == '"':
                value = value.replace("\\n", "\n").replace("\\r", "\r")
            found[name] = value
    return found


def _scalar(text: str) -> str | None:
    """A YAML value written on its key's line, as text: quotes taken off, a comment cut;
    None when there is none (a nested block)."""
    text = text.strip()
    quoted = re.match(r"([\"'])(.*)\1\s*(#.*)?$", text)
    if quoted:
        return quoted[2]
    text = re.split(r"\s+#", text, maxsplit=1)[0].strip()
    return text or None


# The name config_env gives an `env:` block it can't read whole: it holds no value to hide
UNREAD = "env"
# A top-level `env` key in a form the line scan does not read: quoted, a space before the
# colon, an anchor, a tag or an alias after it, a flow mapping over several lines, a complex
# key (`? env`); a quoted key with an escape in it may be `env` too
_ENV_KEY = re.compile(r"""^(?:\?\s*)?(["']?)env\1\s*(?::|$)""")
_ESCAPED_KEY = re.compile(r"""^\??\s*"[^"]*\\""")
_READABLE = (re.compile(r"env:\s*(#.*)?$"), re.compile(r"env:\s*\{(.*)\}\s*(#.*)?$"))
_ENTRY = re.compile(r"""\s+["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s*:(.*)$""")
_FLOW_ENV = re.compile(r"""[{,]\s*["']?env["']?\s*:""")
_ANY_ENV = re.compile(r"""(?:^|[\s{,?])["']?env["']?\s*:""", re.MULTILINE)


def config_env(config: Path | None) -> dict[str, str | None]:
    """A promptfoo config's top-level `env:` block, {name: value}: from JSON (a `.json`
    file, or JSON in a `.yaml` one, which YAML reads the same), else with PyYAML when it can
    be imported, else a line scan for YAML, in block or one-line (`env: {A: x, B: y}`) form.
    A block the line scan can't read whole (another YAML form, js-yaml reads them all) gives
    UNREAD. A value it can't read as one line is None. Values are only hidden (hide_keys),
    never shown or passed on. Only a regular file is read."""
    if config is None:
        return {}
    try:
        text = textio.read_regular(config).decode("utf-8", errors="replace")
    except OSError:
        return {}
    text = text.removeprefix(textio.BOM)
    if str(config).endswith(".json") or text.lstrip().startswith("{"):
        try:
            env = json.loads(text).get("env")
        except (ValueError, AttributeError, RecursionError):
            env = None
        if isinstance(env, dict) or str(config).endswith(".json"):
            return ({str(k): (v if isinstance(v, str) else None) for k, v in env.items()
                     if NAME.match(str(k))} if isinstance(env, dict) else {})
    parsed = _yaml_env(text)
    return _scanned_env(text) if parsed is None else parsed


def _yaml_env(text: str) -> dict[str, str | None] | None:
    """The top-level `env:` block as PyYAML reads it (every name),
    or None when PyYAML can't be imported or can't read the text."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError, ValueError):
        return None
    env = data.get("env") if isinstance(data, dict) else None
    if env is None:
        return {}
    if not isinstance(env, dict):
        return {UNREAD: None}
    return {str(k): (v if isinstance(v, str) else None) for k, v in env.items()}


def _scanned_env(text: str) -> dict[str, str | None]:
    """config_env's line scan."""
    found, inside, indent = {}, False, None
    if text.lstrip().startswith("{") and _FLOW_ENV.search(text):
        return {UNREAD: None}  # a flow mapping as the whole document
    merges = any(re.match(r"<<\s*:", line) for line in text.splitlines())
    if merges and _ANY_ENV.search(text):
        return {UNREAD: None}  # `<<: *base` may bring in an env: block
    for line in text.splitlines():
        if line[:1] not in ("", " ", "\t", "#") and (
                _ENV_KEY.match(line) or _ESCAPED_KEY.match(line)) \
                and not any(r.match(line) for r in _READABLE):
            return {UNREAD: None}
    for line in text.splitlines():
        flow = _READABLE[1].match(line)
        if flow:  # the values may hold ":" (an address), so each entry is cut at its first one
            for entry in flow[1].split(","):
                name, _, value = entry.partition(":")
                name = name.strip().strip("'\"")
                if NAME.match(name):
                    found[name] = _scalar(value)
                elif name:
                    return {UNREAD: None}
            return found
        if _READABLE[0].match(line):
            inside = True
            continue
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            break  # the next top-level key
        width = len(line) - len(line.lstrip())
        indent = width if indent is None else indent
        if width != indent:
            continue  # a value over several lines
        m = _ENTRY.match(line)
        if not m:
            return {UNREAD: None}  # `? NAME`, an escaped name, `<<: *a`, a list
        found[m[1]] = _scalar(m[2])
    return found


def hide_keys(root: Path, configs=()) -> None:
    """Register with `redact` the value of every credential (an API key name, or a name
    ending in _API_KEY, _TOKEN or _SECRET) that the project's .env files and the promptfoo
    configs `configs` set, so it is hidden from the moment the project is found. Nothing is
    passed on, and no other value is kept."""
    root = Path(root)
    files = [root / ".env", root / ".env.local", _project_env(root)]
    if os.environ.get("APP_ENV"):
        files.append(root / f".env.{os.environ['APP_ENV'].strip()}")
    for path in dict.fromkeys(files):
        names = {n for n in names_in(path) if is_credential(n)}
        for name, value in env_values(path, names).items():
            register_secret(name, value)
    for config in configs:
        for name, value in config_env(config).items():
            if isinstance(value, str):
                register_secret(name, value)


def _project_env(folder: Path) -> Path:
    """The nearest .env from `folder` up to the project's own folder (find.is_project), never
    above it and never in the home folder; `folder`'s own when there is none."""
    from judgekeeper import find  # find imports this module

    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for parent in (folder, *folder.resolve().parents):
        if parent.resolve() == home:
            break
        if (parent / ".env").is_file():
            return parent / ".env"
        if find.is_project(parent):
            break
    return folder / ".env"
