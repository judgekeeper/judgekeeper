"""The user's files and shell, in plain words. Standard library only.

- Reading a file the user supplied: a "CSV" saved by Excel's default option is cp1252 or
  UTF-16, not UTF-8; `read_utf8` turns that into one line that says how to save it.
- Writing a file judgekeeper owns: `write_replacing` writes a new file and renames it over the
  old one, so a link there is replaced, never written through. What it makes in .judgekeeper/
  is its owner's only: files 0600, folders 0700.
- Saying a file-system error as one line that names the path and what to do.
- Printing a command the user can paste (`program`, `quote_arg`, `open_command`), written for
  the shell in use: on Windows, cmd.exe or PowerShell.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
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


def flush_stdout(err: bool = False) -> None:
    """Flush stdout (`err`: stderr). When it can't take the output (the program reading it
    stopped, as `| head` does, the disk is full, or it was closed), the rest goes to the null
    device from here on and the command carries on to its own exit code. A stream closed
    before judgekeeper started is None: nothing to flush."""
    stream = sys.stderr if err else sys.stdout
    if stream is None:
        return
    try:
        stream.flush()
    except (OSError, ValueError):  # BrokenPipeError and io.UnsupportedOperation are OSErrors
        try:
            with open(os.devnull, "w", encoding="utf-8") as null:
                os.dup2(null.fileno(), stream.fileno())
        except (AttributeError, OSError, ValueError):  # io.UnsupportedOperation is an OSError
            pass


def started_by_uvx() -> bool:
    """uvx sets UV and runs judgekeeper from a folder `archive-v<N>/<id>` in uv's cache, on
    every system and with a cache folder of the person's own. `uv run` and `uv tool install`
    set UV too, but run it from a project's environment or a tool folder."""
    return bool(os.environ.get("UV")) and Path(
        sys.prefix.replace("\\", "/")).parent.name.startswith("archive-v")


# The marking page's own process runs as `python -m judgekeeper.page`: the command that
# started it says whether it was `python -m judgekeeper` itself (page.main sets this)
_python_m = False


def started_with_python_m() -> bool:
    """Whether this process is `python -m judgekeeper`, or the marking page of one."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return _python_m or getattr(spec, "name", None) == "judgekeeper.__main__"


def program(subcommand: str = "") -> str:
    """judgekeeper as the person runs it again: `uvx judgekeeper` when uvx started it (uvx
    puts no `judgekeeper` command on the PATH), `@<version>` only for a beta (uvx and pip skip
    betas unless the version is named), with the extras it was started with (uvx_with);
    `python3 -P -m judgekeeper` (`py` on Windows) when `python -m` started it and the
    `judgekeeper` command is not on the PATH (-P: a project's json.py never runs); else
    `judgekeeper`; then the subcommand."""
    import shutil

    from judgekeeper import __version__

    name = "judgekeeper"
    if started_by_uvx():
        pin = f"@{__version__}" if is_prerelease() else ""
        name = uvx_with() if extras_here() else f"uvx judgekeeper{pin}"
    elif started_with_python_m() and not shutil.which("judgekeeper"):
        name = f"{'py' if is_windows() else 'python3'} -P -m judgekeeper"
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
    """The uvx command that runs judgekeeper with `extras` and the extras it has now (uvx
    keeps its own environment, which `pip install` never reaches): this version for a beta."""
    from judgekeeper import __version__

    names = ",".join(sorted({*extras, *extras_here()}))
    pin = f"=={__version__}" if is_prerelease() else ""
    return f'uvx --from "judgekeeper[{names}]{pin}" judgekeeper'


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


_ERROR_TYPE = re.compile(r"\s*([A-Za-z_][\w.]*?(?:Error|Exception|Interrupt|Timeout|Exit|"
                         r"Refused|Failure))\b")


def error_type(message) -> str:
    """The type of an error an eval tool saved ("RuntimeError", "openai.RateLimitError"),
    from the start of its message, else "an error". Never the message itself: it can hold
    the eval's prompt, a request or a header."""
    m = _ERROR_TYPE.match(str(message or ""))
    return m.group(1) if m else "an error"


# Reading -------------------------------------------------------------------------------------

def not_utf8_message(path: str | Path) -> str:
    message = f"{Path(path).name} is not saved as UTF-8 text, so it cannot be read."
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


class NotAFile(OSError):
    """A path judgekeeper reads or keeps a file at is a folder, a named pipe (FIFO) or another
    special file. Reading a named pipe would wait for a writer forever."""

    def __init__(self, path: str | Path, kind: str):
        super().__init__(errno.EINVAL, f"it is a {kind}, not a file", str(path))
        self.kind = kind


def file_kind(mode: int) -> str | None:
    """What a path with the stat mode `mode` is, in words, when it is not a regular file."""
    if stat.S_ISREG(mode):
        return None
    if stat.S_ISDIR(mode):
        return "folder"
    if stat.S_ISFIFO(mode):
        return "named pipe"
    return "special file"


def not_a_file(path: str | Path) -> NotAFile | None:
    """NotAFile when something other than a regular file is at `path` (a link is not
    followed), else None (a regular file, a link or nothing)."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return None
    kind = None if stat.S_ISLNK(mode) else file_kind(mode)
    return None if kind is None else NotAFile(path, kind)


def open_regular(path: str | Path):
    """`path` opened for reading as bytes, only when it is a regular file; else NotAFile. It
    is opened without waiting (a named pipe would wait for a writer), then checked."""
    nonblock = getattr(os, "O_NONBLOCK", 0)  # none on Windows, where a file never waits
    fd = os.open(path, os.O_RDONLY | nonblock | getattr(os, "O_BINARY", 0))
    try:
        kind = file_kind(os.fstat(fd).st_mode)
        if kind is not None:
            raise NotAFile(path, kind)
        if nonblock:
            os.set_blocking(fd, True)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "rb")


def read_regular(path: str | Path, limit: int = -1) -> bytes:
    """The bytes of a regular file (open_regular), at most `limit` of them when given."""
    with open_regular(path) as f:
        return f.read(limit)


def not_a_file_message(path: str | Path, kind: str) -> str:
    return f"{Path(path).name} is a {kind}, not a file, so judgekeeper can't read it."


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

    Raises `error` (the caller's usage error) with one plain line when the file is not UTF-8,
    or is not a regular file (a named pipe would never end).
    """
    global last_read
    last_read = Path(path).name
    _reading.update(since=_clock(), said=None)
    try:
        data = read_regular(path)
    except NotAFile as e:
        raise error(not_a_file_message(path, e.kind)) from None
    return decode_utf8(data, path, error).removeprefix(BOM)


NOT_JSON = "{file} isn't valid JSON that judgekeeper can read."
NOT_TEXT = ("{file} holds a character that isn't text (a lone surrogate such as \\ud800), so "
            "judgekeeper can't read it.")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
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
    if lone_surrogate(data):
        raise error(NOT_TEXT.format(file=Path(path).name))
    return data


def lone_surrogate(data) -> bool:
    """Whether a string in `data` (keys too, inside lists and objects) holds a lone surrogate:
    a JSON escape such as \\ud800 reads as one, and it can't be written as UTF-8. Walked
    without recursion."""
    stack = [data]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            if not value.isascii() and _SURROGATE.search(value):
                return True
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


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


# What read_cached keeps: (path, parse) -> (the file's stamp, what parse gave). A few files.
_CACHED: dict = {}
CACHED_FILES = 16


def file_stamp(path: str | Path) -> tuple | None:
    """What changes when a file is written: its size, times and inode; None when it is not
    there."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino


def read_cached(path: str | Path, parse):
    """`parse(path)`, read again only when the file changed (file_stamp); else what it gave
    last time. Callers never change what it returns: it is shared."""
    stamp = file_stamp(path)
    key = (str(path), parse)
    hit = _CACHED.get(key)
    if stamp is not None and hit is not None and hit[0] == stamp:
        return hit[1]
    value = parse(path)
    if stamp is not None:
        _CACHED.pop(key, None)
        while len(_CACHED) >= CACHED_FILES:
            _CACHED.pop(next(iter(_CACHED)))
        _CACHED[key] = (stamp, value)
    return value


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


# Windows refuses to replace a file another process has open (a second judgekeeper run
# reading it): tried again for a moment, REPLACE_TRIES times REPLACE_PAUSE seconds at most.
REPLACE_TRIES, REPLACE_PAUSE = 40, 0.05


class FileBusyError(OSError):
    """A file another program kept open, so it was not replaced: not a permission problem."""


def write_replacing(path: str | Path, text: str, newline: str | None = None) -> None:
    """Write `text` (UTF-8) to a temporary file next to `path`, then rename it over `path`.

    A link at `path` is replaced by the new file, never written through, and a reader never
    sees half a file. `newline` is `open()`'s: None writes "\n" as the system's line ending.
    The temporary file's name holds this process's id, so two processes never share one.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.{os.getpid()}.", suffix=".tmp",
                               dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        _replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _replace(tmp: str, path: Path) -> None:
    """os.replace. On Windows a refusal while `path` is open in another process is tried
    again for a moment, then said as FileBusyError: the folder took the temporary file, so
    writing there is allowed. A read-only file is a real permission problem, said at once."""
    for tries in range(REPLACE_TRIES, 0, -1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            if not is_windows() or (path.exists() and not os.access(path, os.W_OK)):
                raise
            if tries == 1:
                raise FileBusyError(e.errno, "in use by another program", str(path)) from e
            time.sleep(REPLACE_PAUSE)


PRIVATE_FILE, PRIVATE_FOLDER = 0o600, 0o700


def open_private(path: str | Path, mode: str = "a", **kwargs):
    """`path` opened to add to ("a", or "ab"); a new file is its owner's only (0600). A file
    with another name too (a hard link) is refused: what is added would land there as well."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, PRIVATE_FILE)
    if os.fstat(fd).st_nlink > 1:
        os.close(fd)
        raise OSError(errno.EMLINK, "it has a second name (a hard link)", str(path))
    return os.fdopen(fd, mode, **kwargs)


def hard_linked(path: str | Path) -> bool:
    """Whether `path` is a file with more than one name (a hard link)."""
    try:
        return os.lstat(path).st_nlink > 1 and not os.path.islink(path)
    except OSError:
        return False


def make_private(folder: str | Path) -> None:
    """Make `folder` and each parent it lacks, each its owner's only (0700). A folder that is
    there keeps its mode."""
    folder = Path(folder)
    missing, up = [], folder
    while not os.path.lexists(up) and up != up.parent:
        missing.append(up)
        up = up.parent
    for f in reversed(missing):
        f.mkdir(mode=PRIVATE_FOLDER, exist_ok=True)
    folder.mkdir(mode=PRIVATE_FOLDER, exist_ok=True)  # a file there raises, as mkdir does


def link_in(folder: str | Path) -> Path | None:
    """`folder` itself, or the first file or folder in it, that is a link (a symlink, or on
    Windows a junction), or None. Links are not followed. A named pipe or other special file
    in it is NotAFile: reading it would wait forever."""
    folder = Path(folder)
    if _is_link(folder):
        return folder
    for top, dirs, files in os.walk(folder):
        for name in sorted(dirs + files):
            if _is_link(Path(top) / name):
                return Path(top) / name
            if name in files and (odd := not_a_file(Path(top) / name)) is not None:
                raise odd
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
NOT_A_FILE = "{path} is a {kind}, but judgekeeper keeps a file of its own there."
NOT_A_FILE_NEXT = "move or rename {path}, then run `{command}`."
WORKSPACE_DENIED = ("judgekeeper can't write in .judgekeeper/ (permission denied): it keeps "
                    "its files there.")
OLD_HOOK = ("Your git pre-commit hook still runs `judgekeeper check --fast`, which was removed. "
            "Delete that line from .git/hooks/pre-commit.")


def old_hook(path: str | Path) -> str | None:
    """OLD_HOOK when the git pre-commit hook of the repository `path` is in still runs
    `judgekeeper check --fast` (gone in 1.0), else None. The hook is only read: judgekeeper
    never edits it."""
    here = Path(path).resolve()
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            try:
                text = (folder / ".git" / "hooks" / "pre-commit").read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                return None
            return OLD_HOOK if any(_OLD_HOOK_LINE.search(line) for line in text.splitlines()
                                   if not line.lstrip().startswith("#")) else None
    return None


_OLD_HOOK_LINE = re.compile(r"\bjudgekeeper\b.*\bcheck\s+--fast\b")


WORKSPACE_DENIED_NEXT = ("give your user permission to write in .judgekeeper/, then run "
                         "`{command}`.")  # never "remove it": it holds the marks
WORKSPACE_BUSY = ("Another program had a file in .judgekeeper/ open, so judgekeeper could not "
                  "save it.")
WORKSPACE_BUSY_NEXT = ("wait for the other program (often another judgekeeper run) to finish, "
                       "then run `{command}`.")


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
    if isinstance(e, NotAFile):
        shown = "/".join(parts[parts.index(WORKSPACE):]).replace("{", "(").replace("}", ")")
        return (NOT_A_FILE.format(path=shown, kind=e.kind),
                NOT_A_FILE_NEXT.replace("{path}", shown))
    if isinstance(e, FileBusyError):
        return WORKSPACE_BUSY, WORKSPACE_BUSY_NEXT
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
    if isinstance(e, NotAFile):
        return f"{path} is a {e.kind}, not a file. Move or rename it, then try again."
    if isinstance(e, FileBusyError):
        return f"cannot save {path}: another program has it open. Close it, then try again."
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

# On Windows, letters, digits, spaces and these go in a command as they are (list2cmdline).
_WINDOWS_PLAIN = re.compile(r"[^\W_]|[ _.\-:/\\]")
# Inside double quotes cmd.exe still expands % and !, and PowerShell $ and the backtick; it
# also ends the quotes at a curly double quote.
_WINDOWS_EXPANDS = re.compile('["%!$`\u201c\u201d\u201e]')
PLACEHOLDER = "NAME"
_held: dict[str, None] = {}  # what quote_arg left out, in order, until a line shows NAME


def _plain_on_windows(arg: str) -> bool:
    return all(_WINDOWS_PLAIN.fullmatch(c) for c in arg)


def held_back(arg: str | Path) -> bool:
    """Whether `quote_arg` leaves `arg` out of a command: on Windows, when cmd.exe or
    PowerShell would act on it inside double quotes, or it holds a control character or line
    break."""
    return is_windows() and (bool(_WINDOWS_EXPANDS.search(str(arg)))
                             or not str(arg).isprintable())


def quote_arg(arg: str | Path, kept: bool = False) -> str:
    """`arg` as one argument of a command the user pastes; quoted only when it needs it. On
    Windows an argument quotes can't keep as text stays out of the command: PLACEHOLDER
    stands in its place, and `held_lines` says it as data under the line that shows it.
    `kept`: the command is kept in a file or on the page, which say the value beside it
    themselves (start.held_values), so no line here says it."""
    text = str(arg)
    if is_windows():
        if _plain_on_windows(text):
            return subprocess.list2cmdline([text])  # double quotes: cmd.exe and PowerShell
        if held_back(text):
            if not kept:
                _held[text] = None
            return PLACEHOLDER
        backslashes = text[len(text.rstrip("\\")):]  # doubled: they don't escape the quote
        return f'"{text}{backslashes}"'
    if "`" in text:  # $'...' with \x60: no backtick, so it survives inside `...`
        escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("`", "\\x60")
        return f"$'{escaped}'"
    return shlex.quote(text)


def quoted_name(value: str) -> str:
    """A name read from a file (a metric, an LLM-as-a-judge) in a line or list that names
    it, as it can be pasted: quoted for the shell (quote_arg), in its quotes even when it
    needs none, so the names read alike and none reads as a line judgekeeper says (double
    on Windows, where cmd.exe and PowerShell read them). One Windows leaves out of commands
    (held_back) is shown between single quotes, as data."""
    if held_back(value):
        return f"'{value}'"
    quoted = quote_arg(value)
    mark = '"' if is_windows() else "'"
    return f"{mark}{value}{mark}" if quoted == value else quoted


def held_lines(text: str) -> list[str]:
    """A line for each value `quote_arg` left out of a command, as data, once `text` (a line
    about to be said) shows PLACEHOLDER; scrubbed, as every line said is, and on one line, so
    a value can't start a line of its own. Each is said once."""
    from judgekeeper.redact import one_line, scrub

    if not _held or not re.search(rf"\b{PLACEHOLDER}\b", text):
        return []
    lines = [one_line(scrub(f"  {PLACEHOLDER}: {v}")) for v in _held]
    _held.clear()
    return lines


WIDTH = 64  # what judgekeeper says wraps here; a command in backticks is never split
WHOLE = ("Inspect AI", "left out")  # never split either: a name, and the words a line that
# leaves a file out is found by


def wrap(text: str, width: int = WIDTH, indent: str = "") -> list[str]:
    """`text` as lines of at most `width` characters (a longer command stays whole on its
    own line), each starting with `indent`. Each line break in `text` (\\n) starts a new line;
    every other one (\\r, U+2028...) is a space. A value read from a file goes in as one line
    (redact.one_line: a name, a model id, a held value), so only judgekeeper's own text breaks
    a line. Only a text that starts with "Next:" gives a line that starts with it: a name read
    from a file can't pass for judgekeeper's Next: line. The whole text is scrubbed first: a
    line break between "Bearer" and its token would hide the token from a scrub of each line
    (links.said, with the line breaks kept)."""
    import re
    import textwrap

    from judgekeeper.links import keep as keep_links
    from judgekeeper.links import stand_ins
    from judgekeeper.redact import one_line, scrub

    text, links_back = stand_ins(keep_links(
        text, lambda part: "\n".join(one_line(x) for x in (scrub(part) or "").split("\n"))))
    text = text[:1] + re.sub(r"\s+(?=Next:)", "\0", text[1:])
    keep = re.findall(r"`[^`]*`", text) + [w for w in WHOLE if w in text]
    for part in keep:
        text = text.replace(part, part.replace(" ", "\0"))
    lines = []
    for piece in text.split("\n"):
        lines += textwrap.wrap(piece, width, initial_indent=indent, subsequent_indent=indent,
                               break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]
    return [links_back(line.replace("\0", " ")) for line in lines]
