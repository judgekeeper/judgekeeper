"""The user's files and shell, in plain words. Standard library only.

Four things every command shares:

- reading a text file the user supplied. A spreadsheet saved by Excel's default "CSV" option
  is cp1252 or UTF-16, not UTF-8; `read_utf8` turns that into one line that says how to save
  it, raised as the caller's own usage error. JSONL is split into lines by `jsonl_lines`;
  `read_json` says JSON nested too deep to read in one plain line too.
- writing a file judgekeeper owns: `write_replacing` writes a new file and renames it over the
  old one, so a link there is replaced, never written through; `link_in` finds a link in a
  folder before anything is written.
- saying a file-system error (no permission, a file where a folder should be) as one line
  that names the path and what to do: `describe_os_error`.
- printing a command the user can paste: `program` says how judgekeeper was started
  (`uvx judgekeeper@<version>` or `judgekeeper`), `quote_arg` and `open_command` write it for the
  shell in use. On Windows that is cmd.exe or PowerShell: double quotes, backslashes in paths, `start` instead of `open`.

`tick()` is the mark in front of a line that says something was found or is ready, and
`plural` says a count as people say it ("1 answer", "2 answers").
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

BOM = "\ufeff"
SPREADSHEET_SUFFIXES = (".csv", ".tsv")


def is_windows() -> bool:
    return sys.platform == "win32"


TICK = "\u2713"  # a check mark from the Dingbats block, never an emoji


def tick(stream=None) -> str:
    """The check mark, or `OK` where it may not show.

    It needs a stream encoding that has it, and on Windows a terminal that draws it (Windows
    Terminal sets WT_SESSION; VS Code and others set TERM_PROGRAM); the old console host does
    not. The words after it always say the same thing, so nothing depends on the symbol.
    """
    stream = sys.stdout if stream is None else stream
    try:
        TICK.encode(getattr(stream, "encoding", None) or "ascii")
    except (LookupError, UnicodeEncodeError):
        return "OK"
    if is_windows() and not (os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")):
        return "OK"
    return TICK


def lenient_streams() -> None:
    """Make stdout and stderr replace a character they cannot encode instead of raising.

    A Windows terminal on a legacy code page (cp1252) has no arrow; printing one must not
    stop a command. A UTF-8 terminal encodes everything, so nothing changes there.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):  # closed or detached: leave it as it is
            pass


def started_by_uvx() -> bool:
    """uvx sets UV and runs judgekeeper from a folder `archive-v<N>/<id>` in uv's cache, on
    every system and with a cache folder of the person's own. `uv run` and `uv tool install`
    set UV too, but run it from a project's environment or a tool folder."""
    return bool(os.environ.get("UV")) and Path(
        sys.prefix.replace("\\", "/")).parent.name.startswith("archive-v")


def program(subcommand: str = "") -> str:
    """judgekeeper as the person runs it again: `uvx judgekeeper@<version>` when uvx started
    it (uvx and pip skip betas unless the version is named, and uvx puts no `judgekeeper`
    command on the PATH), with the extras it was started with (uvx_with); else
    `judgekeeper`; then the subcommand."""
    from judgekeeper import __version__

    name = "judgekeeper"
    if started_by_uvx():
        name = uvx_with() if extras_here() else f"uvx judgekeeper@{__version__}"
    return f"{name} {subcommand}" if subcommand else name


# judgekeeper's extras, and the module each one installs
EXTRA_MODULES = {"inspect": "inspect_ai", "mlflow": "mlflow"}


def extras_here() -> tuple[str, ...]:
    """The extras whose module this Python can import (without importing it)."""
    import importlib.util

    here = []
    for extra, module in EXTRA_MODULES.items():
        try:
            if importlib.util.find_spec(module) is not None:
                here.append(extra)
        except (ImportError, ValueError):  # ValueError: set to None in sys.modules
            continue
    return tuple(here)


def is_prerelease(version: str | None = None) -> bool:
    """Whether `version` (judgekeeper's own by default) is a beta, alpha, rc or dev release."""
    from judgekeeper import __version__

    return re.search(r"\d(a|b|rc|\.dev)\d*$", version or __version__) is not None


def uvx_with(*extras: str) -> str:
    """The uvx command that runs this version of judgekeeper with `extras` and the extras it
    has now: uvx keeps its own environment, which `pip install` never reaches."""
    from judgekeeper import __version__

    names = ",".join(sorted({*extras, *extras_here()}))
    return f'uvx --from "judgekeeper[{names}]=={__version__}" judgekeeper'


def install_extra(extra: str) -> str:
    """`pip install "judgekeeper[<extra>]"`, pinned to this version while it is a beta (pip
    skips betas unless the version is named)."""
    from judgekeeper import __version__

    pin = f"=={__version__}" if is_prerelease() else ""
    return f'pip install "judgekeeper[{extra}]{pin}"'


def get_extra(extra: str) -> str:
    """How to get `extra`, as the end of a sentence: the uvx command when uvx started
    judgekeeper, else the install line."""
    if started_by_uvx():
        return f"run `{uvx_with(extra)}`"
    return f"install the extra ({install_extra(extra)})"


def plural(n: int, one: str, many: str | None = None) -> str:
    """`n` and the word for it: `one` for 1, else `many` (by default `one` + "s")."""
    return f"{n} {one if n == 1 else many or one + 's'}"


# Reading -------------------------------------------------------------------------------------

def not_utf8_message(path: str | Path) -> str:
    message = f"{path} is not saved as UTF-8 text, so it cannot be read."
    if Path(path).suffix.lower() in SPREADSHEET_SUFFIXES:
        return (f'{message} In Excel, save it again as "CSV UTF-8 (Comma delimited)"; in '
                "Google Sheets, use File > Download > Comma-separated values (.csv).")
    return f"{message} Save it again as UTF-8."


def decode_utf8(data: bytes, path: str | Path, error: type[Exception]) -> str:
    """`data` as text, byte order mark kept. Raises `error` when it is not UTF-8.

    A NUL byte means UTF-16 without a byte order mark: it decodes, but not as the text meant.
    """
    try:
        if b"\x00" in data:
            raise ValueError("NUL byte")
        return data.decode("utf-8")
    except ValueError:  # UnicodeDecodeError is one
        raise error(not_utf8_message(path)) from None


last_read: str | None = None  # the name of the last file read_utf8 read, for an error
PROGRESS_AFTER = 2  # seconds of reading before the first "Reading ..." line
PROGRESS_EVERY = 5  # seconds between those lines
_reading = {"since": 0.0, "said": None}


def _clock() -> float:
    import time

    return time.monotonic()


def reading(n: int, name: str | None = None) -> None:
    """While a file (or a store, `name`) takes long to read (`n` answers so far): after
    PROGRESS_AFTER seconds, a line on stderr every PROGRESS_EVERY seconds, so a person or an
    agent sees it working."""
    if n == 1 and name is not None:  # a store: read_utf8 never starts its clock
        _reading.update(since=_clock(), said=None)
    if n % 500:
        return
    now, said = _clock(), _reading["said"]
    if now - _reading["since"] < PROGRESS_AFTER or (said is not None
                                                    and now - said < PROGRESS_EVERY):
        return
    _reading["said"] = now
    print(f"Reading {name or last_read or 'your results'} ({n:,} answers so far)...",
          file=sys.stderr, flush=True)


def read_utf8(path: str | Path, error: type[Exception]) -> str:
    """The text of a file the user supplied, without a byte order mark.

    Raises `error` (the caller's usage error) with one plain line when the file is not UTF-8.
    """
    global last_read
    last_read = Path(path).name
    _reading.update(since=_clock(), said=None)
    return decode_utf8(Path(path).read_bytes(), path, error).removeprefix(BOM)


NOT_JSON = "{file} isn't valid JSON that judgekeeper can read."
MAX_NESTING = 500  # lists and objects inside each other; Python before 3.14 stops near 1000


def read_json(path: str | Path, error: type[Exception]):
    """The JSON in a file the user supplied (read_utf8). Raises `error` with one plain line
    when it is nested deeper than MAX_NESTING (on every Python version, whether or not its JSON
    reader stops first); json.JSONDecodeError as usual."""
    text = read_utf8(path, error)
    try:
        data = json.loads(text)
    except RecursionError:
        raise error(NOT_JSON.format(file=path)) from None
    if too_deep(data):
        raise error(NOT_JSON.format(file=path))
    return data


def too_deep(data) -> bool:
    """Whether lists and objects are nested deeper than MAX_NESTING, walked without
    recursion."""
    stack = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_NESTING:
            return True
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values() if isinstance(v, (dict, list)))
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value if isinstance(v, (dict, list)))
    return False


def jsonl_lines(text: str) -> list[str]:
    """The lines of JSONL text, split at "\n" only (a "\r" before it is dropped).

    Not `str.splitlines()`: that also splits at U+2028, U+2029, U+0085 and other characters a
    JSON string may hold as they are (text copied from web pages and PDFs often does).
    """
    return [line.removesuffix("\r") for line in text.split("\n")]


def line_ending(text: str) -> str:
    """The line ending `text` uses: "\r\n" (Windows) when it has one, else "\n"."""
    return "\r\n" if "\r\n" in text else "\n"


def write_keeping(path: str | Path, text: str) -> None:
    """Write a user's file back as `text` says, byte for byte: UTF-8, no line-ending
    translation (so a file read with read_utf8 keeps its own endings on every system), and
    the byte order mark the file had."""
    path = Path(path)
    bom = path.is_file() and path.read_bytes().startswith(BOM.encode("utf-8"))
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(text)


def write_replacing(path: str | Path, text: str, newline: str | None = None) -> None:
    """Write `text` (UTF-8) to a temporary file next to `path`, then rename it over `path`.

    A link at `path` is replaced by the new file, never written through, and a reader never
    sees half a file. `newline` is `open()`'s: None writes "\n" as the system's line ending.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def link_in(folder: str | Path) -> Path | None:
    """`folder` itself, or the first file or folder in it, that is a link (a symlink, or on
    Windows a junction), or None. Links are not followed."""
    folder = Path(folder)
    if _is_link(folder):
        return folder
    for top, dirs, files in os.walk(folder):
        for name in sorted(dirs + files):
            if _is_link(Path(top) / name):
                return Path(top) / name
    return None


def is_link(path: Path) -> bool:
    """Whether `path` is a link: a symlink, or on Windows a junction."""
    return path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path)


_is_link = is_link


# File-system errors --------------------------------------------------------------------------

def _folder_needed(path) -> str:
    return (f"{path} is a file, but a folder is needed there. Choose another location, or "
            "move the file.")


def _file_needed(path) -> str:
    return f"{path} is a folder, but a file is needed there. Add a file name to the path."


def _cannot_write(path) -> str:
    message = (f"cannot write {path}: permission denied. Choose a location you can write to, "
               "or change the folder's permissions.")
    if is_windows():
        message += " If the file is open in Excel or another program, close it first."
    return message


WORKSPACE = ".judgekeeper"  # where judgekeeper keeps its files, in the project
WORKSPACE_FILE = (".judgekeeper is a file, but judgekeeper keeps its files in a .judgekeeper/ "
                  "folder there.")
WORKSPACE_FILE_NEXT = "move or rename the file .judgekeeper, then run `{command}`."
WORKSPACE_DENIED = ("judgekeeper can't write in .judgekeeper/ (permission denied): it keeps "
                    "its files there.")
WORKSPACE_DENIED_NEXT = ("give your user permission to write in .judgekeeper/ (or remove the "
                         "folder: judgekeeper makes it again), then run `{command}`.")


def workspace_problem(e: OSError) -> tuple[str, str] | None:
    """(the error, the Next: step) when `e` is about .judgekeeper/: named so, never a
    temporary file inside it or a whole path. None for any other path."""
    if not isinstance(e.filename, str | bytes | os.PathLike):
        return None
    parts = Path(os.fsdecode(e.filename)).parts
    if WORKSPACE not in parts:
        return None
    folder = Path(*parts[:parts.index(WORKSPACE) + 1])
    if folder.is_file():
        return WORKSPACE_FILE, WORKSPACE_FILE_NEXT
    if isinstance(e, PermissionError) and folder.is_dir():  # else the project folder's
        return WORKSPACE_DENIED, WORKSPACE_DENIED_NEXT
    return None


def describe_os_error(e: OSError) -> str | None:
    """One plain line for a file-system error, naming the path and what to do.

    None when the error names no path (a network error, say): that is not a file problem.
    """
    if not isinstance(e.filename, str | bytes | os.PathLike):
        return None  # no path, or a file descriptor
    path = os.fsdecode(e.filename)
    if isinstance(e, FileExistsError):
        return _folder_needed(path)
    if isinstance(e, NotADirectoryError):
        return (f"cannot use {path}: part of that path is a file, not a folder. Choose "
                "another location.")
    if isinstance(e, IsADirectoryError):
        return _file_needed(path)
    if isinstance(e, PermissionError):
        if is_windows() and os.path.isdir(path):
            return _file_needed(path)  # Windows says "permission denied" for this
        if os.path.isfile(path) and not os.access(path, os.R_OK):
            return f"cannot read {path}: permission denied. Check the file's permissions."
        return _cannot_write(path)
    if isinstance(e, FileNotFoundError):
        return f"file or folder not found: {path}"
    return (f"cannot use {path}: {e.strerror or e}. Check the path, or choose another "
            "location.")


def unwritable_file(path: str | Path) -> str | None:
    """Why a file at `path` clearly cannot be written, or None. Nothing is created.

    For a command that writes only later (the labeling page writes on the first label): a
    folder at the path, a file where one of its parent folders should be, or a parent that
    refuses writes.
    """
    path = Path(path)
    if path.is_dir():
        return _file_needed(path)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.is_dir():
        return _folder_needed(parent)
    if not os.access(parent, os.W_OK | os.X_OK):
        return _cannot_write(path)
    return None


# Commands for the shell in use ---------------------------------------------------------------

def quote_arg(arg: str | Path) -> str:
    """`arg` as one argument of a command the user pastes; quoted only when it needs it."""
    if is_windows():
        return subprocess.list2cmdline([str(arg)])  # double quotes: cmd.exe and PowerShell
    if "`" in str(arg):  # $'...' with \x60: no backtick, so it survives inside `...`
        escaped = str(arg).replace("\\", "\\\\").replace("'", "\\'").replace("`", "\\x60")
        return f"$'{escaped}'"
    return shlex.quote(str(arg))


WIDTH = 64  # what judgekeeper says wraps here; a command in backticks is never split
WHOLE = ("Inspect AI",)  # names never split either


def wrap(text: str, width: int = WIDTH, indent: str = "") -> list[str]:
    """`text` as lines of at most `width` characters (a longer command stays whole on its
    own line), each starting with `indent`. Only a text that starts with "Next:" gives a line
    that starts with it: a name read from a file can't pass for judgekeeper's Next: line."""
    import re
    import textwrap

    keep = re.findall(r"`[^`]*`", text) + [w for w in WHOLE if w in text]
    for part in keep:
        text = text.replace(part, part.replace(" ", "\0"))
    text = text[:1] + re.sub(r"\s+(?=Next:)", "\0", text[1:])
    lines = textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent,
                          break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]
    return [line.replace("\0", " ") for line in lines]
