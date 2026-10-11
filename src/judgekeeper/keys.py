"""Which key a judge will use, and whether it is set: names only, never a value.

Before judgekeeper asks a user's judge again, it says which key the judge's tool will read and
where that key is: "Your judge will use your OpenAI key (OPENAI_API_KEY, set in your shell)."
The judge's tool reads the key itself; judgekeeper never needs, holds, prints, stores, logs or
passes on a key value.

- The provider comes from the judge's model, in each tool's spelling (`provider_of`), never
  from which keys happen to exist. The one exception is promptfoo's default grader, which
  promptfoo picks from the key names present, in its own order (`promptfoo_default`).
- In the shell: `bool(os.environ.get(NAME))`, used only as true or false.
- In files, names only (`names_in`): `.env` in the folder the tool runs in (DeepEval also reads
  `.env.<APP_ENV>` and `.env.local`), and promptfoo's config `env:` block (a line scan). Each
  line is cut at the first `=` (or `:` in the config) and the rest is dropped at once. No
  dotenv library: it would parse the values.
- Who loads what: promptfoo and DeepEval load `.env` themselves, and the shell wins over the
  file (promptfoo's config `env:` block wins over both). Inspect AI's Python API loads no
  `.env`, so judgekeeper's worker calls Inspect's own loader (the one the `inspect` command
  uses: the nearest `.env` from the project folder upward) when the user's Inspect has it;
  the plan says which (`loads_env`). MLflow's Python API loads no `.env`: its key must be in
  the shell. Either way the message says how to set it there.
- Settings that change a judge without changing a file (`OPENAI_TEMPERATURE`, `*_MAX_TOKENS`,
  `*_TOP_P`, `AWS_BEDROCK_*`, `*_BASE_URL`) are named when set.
- Credential files (Google default credentials, an AWS profile) are checked for existence only.
- Every key name found set in the shell is registered with `redact`, so its value is scrubbed
  from anything a tool prints.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper.redact import register_key_env

HOME = Path.home()
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class Provider:
    label: str  # "OpenAI", as in "your OpenAI key"
    keys: tuple[tuple[str, ...], ...] = ()  # alternatives; each a set of names all needed
    settings: tuple[str, ...] = ()
    credentials: str | None = None  # "google" or "aws": a credential file may do instead


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
        "VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "VERTEX_REGION", "GOOGLE_CLOUD_LOCATION"),
        credentials="google"),
    "bedrock": Provider("AWS Bedrock", (
        ("AWS_BEARER_TOKEN_BEDROCK",), ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")), (
        "AWS_BEDROCK_REGION", "AWS_BEDROCK_TEMPERATURE", "AWS_BEDROCK_MAX_TOKENS",
        "AWS_BEDROCK_TOP_P"), credentials="aws"),
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
ALIASES = {
    "openai": "openai", "anthropic": "anthropic", "azure": "azure", "azureopenai": "azure",
    "azureai": "azure", "google": "google", "gemini": "google", "vertex": "vertex",
    "vertexai": "vertex", "bedrock": "bedrock", "aws": "bedrock", "mistral": "mistral",
    "groq": "groq", "openrouter": "openrouter", "ollama": "ollama", "xai": "xai",
    "grok": "xai",
}
# DeepEval writes the provider as a suffix: "claude-sonnet-4-6 (Anthropic)".
SUFFIX = re.compile(r"\s*\(([^()]+)\)\s*\Z")
BARE = (("gpt-", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
        ("claude-", "anthropic"), ("gemini-", "google"), ("mistral-", "mistral"),
        ("grok-", "xai"))
TOOLS = {"promptfoo": "promptfoo", "deepeval": "DeepEval", "inspect": "Inspect AI",
         "mlflow": "MLflow"}
LOADS_ENV = {"promptfoo", "deepeval"}
# promptfoo's default grader, per promptfoo version: family -> model (checked 2026-10-05).
DEFAULT_GRADERS = {
    "0.123.1": {"openai": "gpt-5.6-sol", "anthropic": "claude-sonnet-4-6",
                "google": "gemini-3.8-flash", "vertex": "gemini-3.8-flash",
                "mistral": "mistral-large-latest"},
}


def all_names() -> set[str]:
    """Every variable name this module looks at."""
    names = {n for p in PROVIDERS.values() for alt in p.keys for n in alt}
    names |= {n for p in PROVIDERS.values() for n in p.settings}
    names |= {n for s in TOOL_SETTINGS.values() for n in s}
    names |= {"AZURE_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME",
              "GOOGLE_APPLICATION_CREDENTIALS", "AWS_PROFILE", "CODEX_HOME"}
    return names


def provider_of(model: str | None, provider: str | None = None) -> str | None:
    """The provider of a judge's model, from the way each tool writes it: promptfoo
    `openai:gpt-4.1-mini`, DeepEval `claude-x (Anthropic)` (a bare name is OpenAI), Inspect
    `openai/gpt-4o`, MLflow `openai:/gpt-4.1-mini`. A known `provider` wins."""
    if provider and ALIASES.get(str(provider).lower()):
        return ALIASES[str(provider).lower()]
    if not model:
        return None
    model = str(model).strip()
    m = SUFFIX.search(model)
    if m:
        return ALIASES.get(m[1].lower().replace(" ", ""))
    for sep in (":/", ":", "/"):  # Inspect's "ollama/llama3.2:3b" has a colon after the slash
        if sep in model and model.split(sep, 1)[0].lower() in ALIASES:
            return ALIASES[model.split(sep, 1)[0].lower()]
    if any(sep in model for sep in (":", "/")):
        return None
    for prefix, name in BARE:
        if model.lower().startswith(prefix):
            return name
    return None


# Names in files ---------------------------------------------------------------------------

def names_in(path: Path) -> set[str]:
    """The variable names a .env file sets. Each line is cut at its first `=`; the rest of the
    line is never kept."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    names = set()
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.partition("=")[0].strip()
        if NAME.match(name):
            names.add(name)
    return names


def config_env_names(config: Path | None) -> set[str]:
    """The names in a promptfoo config's top-level `env:` block: a line scan for YAML, the
    block's keys for JSON."""
    if config is None or not Path(config).is_file():
        return set()
    text = Path(config).read_text(encoding="utf-8", errors="replace")
    if str(config).endswith(".json"):
        try:
            env = json.loads(text).get("env")
        except (ValueError, AttributeError):
            return set()
        return {k for k in env if NAME.match(str(k))} if isinstance(env, dict) else set()
    names, inside, indent = set(), False, None
    for line in text.splitlines():
        if re.match(r"env:\s*(#.*)?$", line):
            inside = True
            continue
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            break  # the next top-level key
        width = len(line) - len(line.lstrip())
        indent = width if indent is None else indent
        m = re.match(r"\s+([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if m and width == indent:
            names.add(m[1])
    return names


def _nearest_env(folder: Path) -> Path:
    """The nearest .env from `folder` upward, as Inspect AI finds it; `folder`'s own when
    there is none."""
    for parent in (folder, *folder.resolve().parents):
        if (parent / ".env").is_file():
            return parent / ".env" if parent != folder.resolve() else folder / ".env"
    return folder / ".env"


def _env_files(tool: str, folder: Path) -> list[Path]:
    if tool == "inspect":
        return [_nearest_env(folder)]
    files = [folder / ".env"]
    if tool == "promptfoo":
        for name in ("DOTENV_PATH", "DOTENV_CONFIG_PATH"):
            if os.environ.get(name):
                files.insert(0, Path(os.environ[name]))
    if tool == "deepeval":
        if os.environ.get("APP_ENV"):
            files.append(folder / f".env.{os.environ['APP_ENV']}")
        files.append(folder / ".env.local")
    return files


def _shown(path: Path, folder: Path) -> str:
    try:
        return path.relative_to(folder).as_posix()
    except ValueError:
        return Path(os.path.relpath(path, folder)).as_posix()


def set_in_shell(name: str) -> str:
    """How to set a variable in the shell, for the platform judgekeeper runs on."""
    return f"$env:{name} = '...'" if sys.platform == "win32" else f"export {name}=..."


@dataclass
class Sources:
    """Where each name is set: the config's env: block, the shell, or an .env file."""

    folder: Path
    config: Path | None
    env_files: list[Path]
    in_config: set[str] = field(default_factory=set)
    in_files: dict[str, Path] = field(default_factory=dict)  # name -> the first file

    @classmethod
    def read(cls, tool: str, folder: Path, config: Path | None = None) -> Sources:
        folder = Path(folder)
        s = cls(folder, config, _env_files(tool, folder))
        s.in_config = config_env_names(config) if tool == "promptfoo" else set()
        for path in reversed(s.env_files):  # earlier files win when listed again below
            for name in names_in(path):
                s.in_files[name] = path
        return s

    def shell(self, name: str) -> bool:
        return bool(os.environ.get(name))

    def anywhere(self, name: str) -> bool:
        return name in self.in_config or self.shell(name) or name in self.in_files


def _credentials(kind: str | None) -> str | None:
    if kind == "google":
        found = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or (
            HOME / ".config" / "gcloud" / "application_default_credentials.json").is_file()
        return "Google default credentials found; your judge will use them." if found else None
    if kind == "aws":
        found = os.environ.get("AWS_PROFILE") or (HOME / ".aws" / "credentials").is_file() \
            or (HOME / ".aws" / "config").is_file()
        return "AWS profile found; your judge will use it." if found else None
    return None


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


# The check -----------------------------------------------------------------------------------

@dataclass
class KeyCheck:
    provider: str | None
    name: str | None  # the key name the judge will use (or needs)
    ok: bool
    lines: list[str]
    settings: list[str] = field(default_factory=list)  # setting names that are set


def check(model: str | None, tool: str, folder: Path, provider: str | None = None,
          config: Path | None = None, key_env: str | None = None,
          loads_env: bool | None = None) -> KeyCheck:
    """Which key `model`'s provider needs when `tool` runs in `folder`, and where it is.
    `loads_env` says whether the tool will load `.env` when judgekeeper runs it (default: as
    the tool does on its own)."""
    loads_env = tool in LOADS_ENV if loads_env is None else loads_env
    folder = Path(folder)
    family = provider_of(model, provider)
    src = Sources.read(tool, folder, config)
    settings = sorted({n for n in (*(PROVIDERS[family].settings if family else ()),
                                   *TOOL_SETTINGS.get(tool, ()))
                       if src.anywhere(n)})
    setting_lines = []
    if settings:
        verb = "is" if len(settings) == 1 else "are"
        pronoun = "it changes" if len(settings) == 1 else "they change"
        setting_lines = [f"{_and(settings)} {verb} set; {pronoun} your judge."]
    if family is None:
        unknown = (f"I can't tell which key your judge needs (its model is {model}); your tool "
                   "looks for it itself.")
        return KeyCheck(None, None, True, [unknown, *setting_lines], settings)
    p = PROVIDERS[family]
    if family == "ollama":
        return KeyCheck(family, None, True, ["Your judge runs on Ollama; it needs no key.",
                                             *setting_lines], settings)
    alternatives = [(key_env,)] if key_env else list(p.keys)
    loader = TOOLS.get(tool, tool)
    for alt in alternatives:
        if all(src.shell(n) for n in alt):
            for n in alt:
                register_key_env(n)
    for alt in alternatives:
        name = " + ".join(alt)
        where = None
        if tool == "promptfoo" and all(n in src.in_config for n in alt) and config:
            where = (f"in the env: block of {_shown(Path(config), folder)}; promptfoo uses it")
        elif all(src.shell(n) for n in alt):
            where = "set in your shell"
        elif all(n in src.in_files for n in alt):
            file = _shown(src.in_files[alt[0]], folder)
            here = "in this folder" if "/" not in file else "above this folder"
            if not loads_env:
                how = ", ".join(set_in_shell(n) for n in alt)
                return KeyCheck(family, name, False, [
                    f"Your judge needs {name}. It is in {file} {here}, but {loader} does not "
                    "load .env files"
                    + (" when judgekeeper runs it" if tool == "inspect" else "")
                    + f": set it in your shell ({how}).", *setting_lines], settings)
            where = f"in {file} {here}; {loader} loads it"
        if where:
            return KeyCheck(family, name, True, [
                f"Your judge will use your {p.label} key ({name}, {where}).", *setting_lines],
                settings)
    creds = _credentials(p.credentials)
    if creds:
        return KeyCheck(family, None, True, [creds, *setting_lines], settings)
    names = [" + ".join(alt) for alt in alternatives]
    needed = names[0] + (f" (or {' or '.join(names[1:])})" if len(names) > 1 else "")
    return KeyCheck(family, names[0], False, [
        f"Your judge needs {needed}. It is not set in your shell or in .env.", *setting_lines],
        settings)


# promptfoo's default grader ------------------------------------------------------------------

@dataclass
class DefaultGrader:
    family: str
    model: str | None
    version: str | None

    @property
    def words(self) -> str:
        if self.model is None:
            return "promptfoo's default grader for your promptfoo version"
        return (f"promptfoo's default grader, probably {self.model} with promptfoo "
                f"{self.version}")


def promptfoo_default(folder: Path, config: Path | None, version: str | None) -> DefaultGrader:
    """The family promptfoo picks its default grader from, by which key names are present, in
    promptfoo's own order; and its model for the promptfoo versions judgekeeper knows."""
    src = Sources.read("promptfoo", Path(folder), config)
    has = src.anywhere
    openai, anthropic = has("OPENAI_API_KEY"), has("ANTHROPIC_API_KEY")
    azure_key = has("AZURE_OPENAI_API_KEY") or has("AZURE_API_KEY") or all(
        has(n) for n in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID"))
    google = any(has(n) for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "PALM_API_KEY"))
    codex = has("CODEX_API_KEY") or (Path(os.environ.get("CODEX_HOME") or HOME / ".codex")
                                     / "auth.json").is_file()
    if not openai and azure_key and has("AZURE_DEPLOYMENT_NAME") \
            and has("AZURE_OPENAI_DEPLOYMENT_NAME"):
        family = "azure"
    elif anthropic and not openai:
        family = "anthropic"
    elif google and not openai and not anthropic:
        family = "google"
    elif not openai and _credentials("google"):
        family = "vertex"
    elif not openai and has("MISTRAL_API_KEY"):
        family = "mistral"
    elif not openai and has("XAI_API_KEY"):
        family = "xai"
    elif not openai and codex:
        family = "codex"
    else:
        family = "openai"
    model = DEFAULT_GRADERS.get(version or "", {}).get(family)
    return DefaultGrader(family, model, version)
