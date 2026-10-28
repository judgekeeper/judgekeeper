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
from pathlib import Path

from judgekeeper import textio
from judgekeeper.redact import is_credential, printable, register_secret, register_value

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


# The API key names of each provider (some take a set of names together).
PROVIDERS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_API_KEY", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
              "AZURE_TENANT_ID"),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY", "PALM_API_KEY"),
    "vertex": ("VERTEX_API_KEY", "GOOGLE_API_KEY"),
    "bedrock": ("AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "xai": ("XAI_API_KEY", "GROK_API_KEY"),
    "codex": ("CODEX_API_KEY",),
}


def key_names() -> set[str]:
    """The API key names of the providers judgekeeper knows."""
    return {n for names in PROVIDERS.values() for n in names}


# Hiding the values in the project's files --------------------------------------------------

# dotenv's line (dotenv 17, lib/main.js LINE), which promptfoo, Inspect AI and DeepEval read
# alike: `NAME=value` or `NAME: value`, after `export ` or not; a value quoted with ', " or `
# (over several lines too), else up to a `#`.
_DOTENV_LINE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z0-9_.-]+)(?:\s*=\s*?|:\s+?)(\s*'(?:\\'|[^'])*'|"
    r"\s*\"(?:\\\"|[^\"])*\"|\s*`(?:\\`|[^`])*`|[^#\r\n]+)?\s*(?:#.*)?$", re.MULTILINE)


# Where JavaScript's `^` and `$` see a line end, as dotenv's LINE does: U+2028 and U+2029 too
_JS_LINE_ENDS = re.compile("\r\n?|[\u2028\u2029]")

# A .env file or a promptfoo config is a few KB: one over this is not read
FILE_LIMIT = 2**20
LINKED = "{file} is a link: judgekeeper doesn't follow links, so the keys in it are not hidden."
TOO_BIG = "{file} is over 1 MB, so judgekeeper didn't read it: the keys in it are not hidden."
# A folder holds a few .env files: in one with more, only this many are read
ENV_FILES_LIMIT = 50
TOO_MANY = ("{folder} holds {count} .env files: judgekeeper read 50 of them, so the keys in the "
            "others are not hidden.")
_notes: list[str] = []  # one per file not read, for the finder's notes
_noted: set[str] = set()
_said: set[str] = set()


def notes() -> list[str]:
    """A note for each file not read (a link, or too big), once each."""
    return _notes[:]


def said(lines) -> None:
    """These notes were said: unsaid() leaves them out."""
    _said.update(lines)


def unsaid() -> list[str]:
    """The notes not said yet, now counted as said."""
    out = [n for n in _notes if n not in _said]
    said(out)
    return out


def _skipped(path: Path, why: str, **more) -> None:
    where = os.path.abspath(path)  # not resolved: that would follow the link
    try:
        shown = Path(os.path.relpath(where, os.path.abspath(Path.cwd()))).as_posix()
    except (ValueError, OSError):
        shown = path.name
    if shown == "." or shown.startswith("../"):
        shown = Path(where).name
    if where not in _noted:
        _noted.add(where)
        _notes.append(why.format(file=printable(shown), folder=printable(shown), **more))


def _small_file(path: Path) -> bytes | None:
    """The bytes of `path` when it is a regular file of at most FILE_LIMIT; else None. A link
    is never followed (it may lead out of the project, or to a huge file), and a bigger file
    is not read: either is noted once (notes). A named pipe would wait forever: not read."""
    try:
        if os.path.islink(path):
            _skipped(path, LINKED)
            return None
        data = textio.read_regular(path, FILE_LIMIT + 1)
    except OSError:
        return None
    if len(data) > FILE_LIMIT:
        _skipped(path, TOO_BIG)
        return None
    return data


def _dotenv_lines(path: Path):
    """(name, the value as written) for each line dotenv reads in a .env file, in order. A
    byte order mark at its start is not part of the first name. Only a small regular file is
    read, never through a link (_small_file)."""
    data = _small_file(path)
    if data is None:
        return
    text = data.decode("utf-8-sig", errors="replace")
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
    """A YAML value written on its key's line, as text: quotes taken off (a double-quoted
    one's escapes read), a comment cut, a tag or an anchor before it left out; None when there
    is none (a nested block)."""
    text = _PROPERTIES.sub("", text.strip())
    quoted = re.match(r"([\"'])(.*)\1\s*(#.*)?$", text)
    if quoted:
        return _unescaped(quoted[2]) if quoted[1] == '"' else quoted[2].replace("''", "'")
    comment = re.search(r"\s#", text)  # one space is enough: no run of them read again
    text = (text[:comment.start()] if comment else text).strip()
    return text or None


# A tag (`!!str`) or an anchor (`&v`) before a value
_PROPERTIES = re.compile(r"^(?:[!&]\S*[ \t]+)+")
# A value js-yaml reads that the line scan can't: a tag, an alias (`*v`, the value of the
# anchor `&v` elsewhere) or a quoted value not closed on its line
_UNSURE = re.compile(r"""[!*]|"(?:[^"\\]|\\.)*\\?$|'(?:[^']|'')*$""")

# YAML's escapes in a double-quoted value
_ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")
_ESCAPED = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
            "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
            "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}


def _unescaped(text: str) -> str:
    def one(m):
        if len(m[1]) > 1:
            code = int(m[1][1:], 16)
            return chr(code) if code < 0x110000 else m[0]
        return _ESCAPED.get(m[1], m[0])

    return _ESCAPE.sub(one, text)


# The name config_env gives an `env:` block it can't read whole: it holds no value to hide
UNREAD = "env"
# The start of the name config_env gives an anchored value (`&v VALUE`) when the block is
# unread: an alias in it may stand for that value, whatever its name
ANCHORED = "&"
# A top-level `env` key in a form the line scan does not read: quoted, a space before the
# colon, an anchor, a tag or an alias after it, a flow mapping over several lines, a complex
# key (`? env`); a quoted key with an escape in it may be `env` too
_ENV_KEY = re.compile(r"""^(?:\?\s*)?(["']?)env\1\s*(?::|$)""")
_ESCAPED_KEY = re.compile(r"""^\??\s*"[^"]*\\""")
# A top-level key's node properties: tags (`!!str`, `!<tag:...>`) and anchors (`&k`) before it
_PROPERTIES = re.compile(r"(?:[!&]\S*\s+)+")
_READABLE = (re.compile(r"env:\s*(#.*)?$"), re.compile(r"env:\s*\{(.*)\}\s*(#.*)?$"))
_ENTRY = re.compile(r"""\s+["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s*:(.*)$""")
_FLOW_ENV = re.compile(r"""[{,]\s*["']?env["']?\s*:""")
_ANY_ENV = re.compile(r"""(?:^|[\s{,?])["']?env["']?\s*:""", re.MULTILINE)


def config_env(config: Path | None) -> dict[str, str | None]:
    """A promptfoo config's top-level `env:` block, {name: value}: from JSON (a `.json`
    file, or JSON in a `.yaml` one, which YAML reads the same), else with PyYAML when it can
    be imported, else a line scan for YAML, in block or one-line (`env: {A: x, B: y}`) form.
    A block the line scan can't read whole (another YAML form, js-yaml reads them all) gives
    UNREAD, and so does a value below its name (a block scalar, or on the next line), a tag,
    an alias or a double-quoted value over several lines, which is None (or the value with
    its tag left out). Then every credential-named value in the file is given, and every
    anchored value (named ANCHORED and the anchor). Values are only hidden (hide_keys), never
    shown or passed on. Only a small regular file is read, never through a link
    (_small_file)."""
    if config is None:
        return {}
    data = _small_file(Path(config))
    if data is None:
        return {}
    text = data.decode("utf-8", errors="replace")
    text = text.removeprefix(textio.BOM).replace("\r\n", "\n").replace("\r", "\n")  # as YAML
    if str(config).endswith(".json") or text.lstrip().startswith("{"):
        try:
            env = json.loads(text).get("env")
        except (ValueError, AttributeError, RecursionError):
            env = None
        if isinstance(env, dict) or str(config).endswith(".json"):
            return ({str(k): (v if isinstance(v, str) else None) for k, v in env.items()
                     if NAME.match(str(k))} if isinstance(env, dict) else {})
    parsed = _yaml_env(text)
    env = _scanned_env(text) if parsed is None else parsed
    if UNREAD in env:  # still hidden: every credential-named `NAME: value` in the file
        env.update({k: v for k, v in _credentials_in(text).items() if env.get(k) is None})
    return env


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


# A credential-named value could be under an escaped name (`"A_\u0054OKEN": value`)
_ESCAPED_NAME = re.compile(r"""(?:^|[\s{,?])"((?:[^"\\\n]|\\.)*\\(?:[^"\\\n]|\\.)*)"[ \t]*:"""
                           r"""[ \t]+("[^"\n]*"|'[^'\n]*'|[^,{}\[\]#\n]+)""", re.MULTILINE)
# In a flow mapping, a value on the line below its name (`{A_TOKEN:` then `value}`)
_FLOW_BELOW = re.compile(r"""[{,][ \t]*["']?([A-Za-z_][A-Za-z0-9_]*)["']?[ \t]*:[ \t]*\n[ \t]*"""
                         r"""("[^"\n]*"|'[^'\n]*'|[^,{}\[\]#\n]+)""")
# An anchored value on its line (`&v VALUE`)
_ANCHOR = re.compile(r"""(?:^|[\s{,\[])&([^\s,{}\[\]]+)[ \t]+("[^"\n]*"|'[^'\n]*'|[^,{}\[\]#\n]+)""",
                     re.MULTILINE)
# A quoted value not closed on its line, after a name (it goes on below)
_OPEN_QUOTE = re.compile(r"""(?:^|[\s{,?])["']?([A-Za-z_][A-Za-z0-9_]*)["']?[ \t]*:[ \t]+"""
                         r"""("(?:[^"\\]|\\.)*\\?|'(?:[^']|'')*)$""")
# The end of a quoted value on a line below its name: the closing quote
_CLOSE_QUOTE = {'"': re.compile(r"""^((?:[^"\\]|\\.)*\\?)("?)"""),
                "'": re.compile(r"""^((?:[^']|'')*)('?)""")}
# A plain value on its name's line (it may go on below, on lines indented more)
_PLAIN = re.compile(r"""([ \t]*)(?:\?[ \t]*|:[ \t]+|-[ \t]+)?["']?([A-Za-z_][A-Za-z0-9_]*)["']?"""
                    r"""[ \t]*:[ \t]+([^\s"'|>#&*!{\[].*)$""")

# `NAME: value` anywhere: in a block, after `{` or `,` in a flow mapping, or as `? NAME` with
# `: value` on the next line
_LOOSE = re.compile(r"""(?:^|[\s{,?])["']?([A-Za-z_][A-Za-z0-9_]*)["']?[ \t]*(?:\n[ \t]*)?:"""
                    r"""[ \t]+("[^"\n]*"|'[^'\n]*'|[^,{}\[\]#\n]+)""", re.MULTILINE)
# A complex key's value that is a `NAME: value` (`? env` then `: NAME: value`): the `: ` is
# blanked out, so the name is found, not taken as the value of the key above it
_VALUE_OF_KEY = re.compile(r"""^([ \t]*):[ \t]+(?=["']?[A-Za-z_][A-Za-z0-9_]*["']?[ \t]*:)""",
                           re.MULTILINE)
_BLOCK = re.compile(r"[|>][-+0-9]*")  # a block scalar's first line: its value is below
# `NAME:` with its value on the lines below (nothing after it, or a block scalar's `|` or `>`)
_HEAD = re.compile(r"""([ \t]*)(?:\?[ \t]*|:[ \t]+)?["']?([A-Za-z_][A-Za-z0-9_]*)["']?[ \t]*:"""
                   r"""[ \t]*([|>][-+0-9]*)?[ \t]*(?:#.*)?$""")


def _credentials_in(text: str) -> dict[str, str]:
    """Every credential-named `NAME: value` in a config, wherever it is: only to hide it
    when its `env:` block can't be read whole."""
    found = {}
    for regex in (_LOOSE, _ESCAPED_NAME, _FLOW_BELOW):
        for m in regex.finditer(_VALUE_OF_KEY.sub(lambda m: " " * len(m[0]), text)):
            name = _unescaped(m[1]) if regex is _ESCAPED_NAME else m[1]
            value = _scalar(m[2])
            if is_credential(name) and value and not _BLOCK.fullmatch(value) \
                    and not value.startswith("*"):
                found[name] = value
    for m in _ANCHOR.finditer(text):
        value = _scalar(m[2])
        if value and not _BLOCK.fullmatch(value):
            found[ANCHORED + m[1]] = value
    lines = text.split("\n")
    at = 0
    while at < len(lines):  # a line inside a value is never read as a name
        m = _OPEN_QUOTE.search(lines[at])
        plain = None if m else _PLAIN.match(lines[at])
        if m and is_credential(m[1]):
            found[m[1]], at = _quoted_below(m[2], lines, at + 1)
        elif plain and is_credential(plain[2]):
            value, at = _plain_below(plain, lines, at + 1)
            found[plain[2]] = value or found.get(plain[2])
        at += 1
    for at, line in enumerate(lines):
        m = _HEAD.match(line)
        if m is None or not is_credential(m[2]):
            continue
        parts, end = [], at + 1
        while end < len(lines):  # the lines indented more than the name
            after = lines[end].strip()
            if after and len(lines[end]) - len(lines[end].lstrip()) <= len(m[1]):
                break
            if after:
                parts.append(after)
            end += 1
        if parts:  # a literal block (`|`) keeps its line breaks; the others fold them
            found[m[2]] = ("\n" if (m[3] or "").startswith("|") else " ").join(parts)
    return found


def _quoted_below(first: str, lines: list[str], at: int) -> tuple[str, int]:
    """The quoted value that starts with `first` (its opening quote and the rest of its line)
    and goes on in `lines` from `at`, read as YAML reads it: a line break folded into a space,
    or into nothing after a backslash in double quotes; the escapes read (`''` in single
    quotes). A space at either end is left out: the key is hidden wherever it is. With the
    index of its last line."""
    quote, text = first[0], first[1:]
    while at < len(lines):
        m = _CLOSE_QUOTE[quote].match(lines[at].strip())
        text = text[:-1] + m[1] if quote == '"' and text.endswith("\\") \
            and not text.endswith("\\\\") else f"{text} {m[1]}"
        if m[2]:
            break
        at += 1
    text = _unescaped(text) if quote == '"' else text.replace("''", "'")
    return text.strip(), at


def _plain_below(m: re.Match, lines: list[str], at: int) -> tuple[str | None, int]:
    """The plain value on a name's line (`m`, _PLAIN) with the lines below it indented more
    than the name, each line break folded into a space; None when it ends on its line. With
    the index of its last line."""
    parts = [_scalar(m[3]) or ""]
    while at < len(lines) and lines[at].strip() and not lines[at].lstrip().startswith("#") \
            and len(lines[at]) - len(lines[at].lstrip()) > len(m[1]):
        parts.append(_scalar(lines[at]) or "")
        at += 1
    return (" ".join(parts) if len(parts) > 1 else None), at - 1


def _entry(found: dict, name: str, raw: str) -> None:
    """`NAME: raw` read into `found`: unread (UNREAD) when it is a tag, an alias or a quoted
    value that goes on below, or a block scalar or nothing (its value is below)."""
    value = _scalar(raw)
    found[name] = value
    if value is None or _BLOCK.fullmatch(value) or _UNSURE.match(raw.strip()):
        found[UNREAD] = None
        if value is None or not raw.strip().startswith("!"):
            found[name] = None


def _scanned_env(text: str) -> dict[str, str | None]:
    """config_env's line scan."""
    found, inside, indent, last = {}, False, None, None
    if text.lstrip().startswith("{") and _FLOW_ENV.search(text):
        return {UNREAD: None}  # a flow mapping as the whole document
    merges = any(re.match(r"<<\s*:", line) for line in text.splitlines())
    if merges and _ANY_ENV.search(text):
        return {UNREAD: None}  # `<<: *base` may bring in an env: block
    for line in text.splitlines():
        if line[:1] in ("", " ", "\t", "#"):
            continue
        properties = _PROPERTIES.match(line)
        key = line[properties.end():] if properties else line
        if key.startswith("*"):
            return {UNREAD: None}  # an alias as a key may stand for `env`
        if (_ENV_KEY.match(key) or _ESCAPED_KEY.match(key)) \
                and (properties or not any(r.match(line) for r in _READABLE)):
            return {UNREAD: None}  # `&k env:`, `!!str env:`: env, with its block unread
    for line in text.splitlines():
        flow = _READABLE[1].match(line)
        if flow:  # the values may hold ":" (an address), so each entry is cut at its first one
            for entry in flow[1].split(","):
                name, _, value = entry.partition(":")
                name = name.strip().strip("'\"")
                if NAME.match(name):
                    _entry(found, name, value)
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
        if width > indent and last is not None:  # the value above goes on here
            found[last], found[UNREAD] = None, None
        if width != indent:
            continue
        m = _ENTRY.match(line)
        if not m:
            return {UNREAD: None}  # `? NAME`, an escaped name, `<<: *a`, a list
        _entry(found, m[1], m[2])
        last = m[1]
    return found


def hide_keys(root: Path, configs=()) -> None:
    """Register with `redact` the value of every credential (an API key name, or a name
    ending in _API_KEY, _TOKEN or _SECRET) that the project's .env files and the promptfoo
    configs `configs` set, so it is hidden from the moment the project is found. Nothing is
    passed on, and no other value is kept."""
    for path in [p for folder in _env_folders(Path(root)) for p in _env_files(folder)]:
        found = {n for n in names_in(path) if is_credential(n)}
        for name, value in env_values(path, found).items():
            register_secret(name, value)
    for config in configs:
        for name, value in config_env(config).items():
            if isinstance(value, str) and name.startswith(ANCHORED):
                register_value(value)
            elif isinstance(value, str):
                register_secret(name, value)


def _env_names(folder: Path) -> list[str]:
    """The names of the .env and .env.* files in `folder` (links too: they are noted, never
    followed), the ones most tools read first."""
    try:
        with os.scandir(folder) as entries:
            names = [e.name for e in entries if (e.name == ".env" or e.name.startswith(".env."))
                     and not e.is_dir(follow_symlinks=False)]
    except OSError:
        return []
    first = [".env", ".env.local", f".env.{os.environ.get('APP_ENV', '').strip()}"]
    return sorted(names, key=lambda n: (first.index(n) if n in first else len(first), n))


def _env_files(folder: Path) -> list[Path]:
    """The .env files read in `folder`: at most ENV_FILES_LIMIT, and a note when there are
    more."""
    names = _env_names(folder)
    if len(names) > ENV_FILES_LIMIT:
        _skipped(folder, TOO_MANY, count=len(names))
    return [folder / name for name in names[:ENV_FILES_LIMIT]]


def _env_folders(folder: Path) -> list[Path]:
    """`folder` and each folder above it up to the project's own folder (find.is_project),
    never above it and never the home folder: where a tool run in `folder` may read .env
    files. With no project above, `folder` and the nearest folder above it with a .env file."""
    from judgekeeper import find  # find imports this module

    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    folders = []
    for parent in (folder, *folder.resolve().parents):
        if parent.resolve() == home:
            break
        folders.append(parent)
        if find.is_project(parent):
            return folders
    nearest = next((f for f in folders[1:] if _env_names(f)), folder)
    return list(dict.fromkeys((folder, nearest)))
