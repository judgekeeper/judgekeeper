"""The user's files and shell, in plain words. Standard library only.

Four things every command shares:

- reading a text file the user supplied. A spreadsheet saved by Excel's default "CSV" option
  is cp1252 or UTF-16, not UTF-8; `read_utf8` turns that into one line that says how to save
  it, raised as the caller's own usage error. JSONL is split into lines by `jsonl_lines`.
- writing a file judgekeeper owns: `write_replacing` writes a new file and renames it over the
  old one, so a link there is replaced, never written through; `link_in` finds a link in a
  folder before anything is written.
- saying a file-system error (no permission, a file where a folder should be) as one line
  that names the path and what to do: `describe_os_error`.
- printing a command the user can paste: `quote_arg` and `open_command` write it for the
  shell in use, and `split_command` reads `--exec` the way that shell would. On Windows that
  is cmd.exe or PowerShell: double quotes, backslashes in paths, `start` instead of `open`.

`tick()` is the mark in front of a line that says something was found or is ready.
"""

from __future__ import annotations

import os
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


def read_utf8(path: str | Path, error: type[Exception]) -> str:
    """The text of a file the user supplied, without a byte order mark.

    Raises `error` (the caller's usage error) with one plain line when the file is not UTF-8.
    """
    return decode_utf8(Path(path).read_bytes(), path, error).removeprefix(BOM)


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


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path)


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
    return shlex.quote(str(arg))


def split_command(command: str) -> list[str]:
    """A command line as arguments.

    POSIX rules elsewhere. On Windows a backslash is a path separator, not an escape, so
    `python C:\\x\\judge.py` keeps its path; quotes around an argument are dropped.
    """
    if not is_windows():
        return shlex.split(command)
    return [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a
            for a in shlex.split(command, posix=False)]
