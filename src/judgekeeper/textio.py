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
from contextlib import contextmanager
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


# The marking page's own process: the program the run that started it names (page.main)
_typed: str | None = None
_plain = False  # inside plainly()
ANYWHERE = ""  # run_from(ANYWHERE): a line for a folder judgekeeper can't name
_from: str | None = None  # inside run_from(): the folder a printed command is run in
SCRIPT_NAMES = ("judgekeeper", "judgekeeper.exe", "judgekeeper-script.py")
_imports: dict[str, bool] = {}


IMPORTED = "import judgekeeper, os; print(os.path.realpath(judgekeeper.__file__))"


def imports_judgekeeper(python: str) -> bool:
    """Whether `python` on the PATH imports this judgekeeper, not another install (asked once
    per program found)."""
    import shutil

    found = shutil.which(python)
    if found is None:
        return False
    if found not in _imports:
        this = _same(os.path.join(os.path.dirname(os.path.realpath(__file__)), "__init__.py"))
        try:
            done = subprocess.run([found, "-P", "-c", IMPORTED], timeout=30, text=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, check=False)
            _imports[found] = done.returncode == 0 and _same(done.stdout.strip()) == this
        except (OSError, subprocess.SubprocessError):
            _imports[found] = False
    return _imports[found]


def _started_as_judgekeeper() -> bool:
    """Whether this process is `python -m judgekeeper` or the `judgekeeper` command itself
    (not, say, a test runner that imported it)."""
    typed = sys.argv[0] if sys.argv else ""
    return started_with_python_m() or os.path.basename(typed).lower() in SCRIPT_NAMES


def command_path(path: str, climb: bool = True) -> str:
    """`path` as a program to run from this folder (or run_from's), quoted: relative when the
    two share a folder below the top and the home folder's parents (shares_below_home), with
    a folder in it so the shell never looks it up on the PATH; else under the home folder as
    `~/...`: never the user name; else, or on another drive, the path as it is. From
    ANYWHERE: never relative. On Windows, never `%USERPROFILE%` (PowerShell doesn't read it):
    the shorter form cmd.exe and PowerShell both run (in_both_shells), from here or the path
    as it is; else from here, quoted (else the path as it is). Without `climb`, never a
    path from here that climbs with `..` (a python run so warns, Python 3.14 with the home
    path in it). A whole path is named without `..` in it (sys.executable may hold one), as
    relpath names it from here."""
    if os.path.isabs(path):
        path = os.path.normpath(path)
    try:
        here = os.getcwd() if _from is None else _from
        shown = os.path.relpath(path, here) if here != ANYWHERE else None
        shared = os.path.commonpath([here, path]) if here != ANYWHERE else os.sep
    except (OSError, ValueError):
        shown = shared = None
    if not climb and shown is not None and shown.replace("\\", "/").split("/")[0] == os.pardir:
        shown = None
    if shown is not None and os.sep not in shown and "/" not in shown:
        shown = os.path.join(os.curdir, shown)
    if is_windows():  # never %USERPROFILE%: PowerShell doesn't read it
        runs = [quote_arg(f) for f in (shown, path) if f is not None
                and in_both_shells(quote_arg(f))]
        if runs:
            return min(runs, key=len)  # from here unless the whole path is shorter
        return quote_arg(shown if shown is not None else path)  # quoted: cmd.exe runs it
    if shared is None:
        return quote_arg(path)
    if shown is not None and shares_below_home(shared):  # more than the top in common
        return quote_arg(shown)
    inside = _in_home(path)
    return quote_arg(path) if inside is None else (_home_command(inside) or quote_arg(path))


def in_both_shells(program: str) -> bool:
    """Whether a program, as command_path gives it, runs as printed in cmd.exe and in
    PowerShell: unquoted (PowerShell runs a quoted program only after `&`, which cmd.exe
    doesn't know) and without %USERPROFILE% (PowerShell doesn't read it)."""
    return (not program.startswith(('"', "'")) and HOME_FORMS[1] not in program
            and program != PLACEHOLDER)


HOME_FORMS = ("~/", "%USERPROFILE%\\")  # a path in the home folder, as a shell reads it


def _in_home(path: str) -> str | None:
    """`path` from the home folder when it is inside it, else None."""
    try:
        home = os.path.realpath(Path.home())
        inside = os.path.relpath(path, home)
    except (OSError, RuntimeError, ValueError):
        return None
    first = inside.replace("\\", "/").split("/")[0]
    return None if inside == os.curdir or first == os.pardir else inside


def _home_shown(inside: str) -> str:
    """A path in the home folder as a line shows it: `~/...` (`%USERPROFILE%\\...` on
    Windows), never the user name."""
    if is_windows():
        return HOME_FORMS[1] + inside.replace("/", "\\")
    return HOME_FORMS[0] + inside.replace(os.sep, "/")


def home_folder_shown(path) -> str | None:
    """A folder that is the home folder or inside it, as a line names it (_home_shown, with
    its separator at the end: `~/`, `~/Desktop/`); else None."""
    try:
        real = os.path.realpath(path)
        home = os.path.realpath(Path.home())
    except (OSError, RuntimeError, ValueError):
        return None
    if os.path.normcase(real) == os.path.normcase(home):
        return _home_shown("")
    inside = _in_home(real)
    if inside is None:
        return None
    shown = _home_shown(inside)
    return shown + ("\\" if is_windows() else "/")


def _home_command(inside: str) -> str | None:
    """`_home_shown`, quoted for a shell with the home part left outside the quotes (the
    shell reads it there; cmd reads %USERPROFILE% inside double quotes too). None when the
    rest can't be in a command (Windows: held back)."""
    if is_windows():
        rest = quote_arg(inside.replace("/", "\\"))
        if rest == PLACEHOLDER or "%" in inside:
            return None
        if rest.startswith('"'):
            return '"' + HOME_FORMS[1] + rest[1:]
        return HOME_FORMS[1] + rest
    return HOME_FORMS[0] + quote_arg(inside.replace(os.sep, "/"))


def off_path(any_start: bool = False) -> str | None:
    """judgekeeper as it runs again when no `judgekeeper` command is on the PATH: the program
    as typed when that was a path from here (`venv/bin/judgekeeper`); else `python3 -P -m
    judgekeeper` when that python can import it (-P: a project's json.py never runs); else
    the program's path from here. None when judgekeeper can't tell how it was started (and
    not `any_start`)."""
    if _typed is not None:
        return _typed
    typed = sys.argv[0] if sys.argv else ""
    python_m = started_with_python_m()
    script = not python_m and _started_as_judgekeeper()
    if not (python_m or script or any_start):
        return None
    if script and not os.path.isabs(typed) and (os.path.isfile(typed)
                                                 or os.path.isfile(typed + ".exe")):
        return quote_arg(typed) if _from is None else command_path(os.path.abspath(typed))
    python = "py" if is_windows() else "python3"
    if imports_judgekeeper(python):
        return f"{python} -P -m judgekeeper"
    python = f"{command_path(sys.executable, climb=False)} -P -m judgekeeper"
    if script:
        shown = command_path(os.path.abspath(typed))
        if is_windows() and not in_both_shells(shown) and in_both_shells(python):
            return python  # its own python runs it, and in either shell
        return shown
    return python


def program(subcommand: str = "") -> str:
    """judgekeeper as the person runs it again: `uvx judgekeeper` when uvx started it (uvx
    puts no `judgekeeper` command on the PATH), `@<version>` only for a beta (uvx and pip skip
    betas unless the version is named), with the extras it was started with (uvx_with);
    when the `judgekeeper` command on the PATH is not this program (_on_path), the form that
    runs (off_path); else `judgekeeper`; then the subcommand. Inside plainly(): never a path
    or a python."""
    from judgekeeper import __version__

    name = "judgekeeper"
    if _typed is not None and not _plain:
        name = _typed
    elif started_by_uvx():
        pin = f"@{__version__}" if is_prerelease() else ""
        name = uvx_with() if extras_here() else f"uvx judgekeeper{pin}"
    elif not _plain and _started_as_judgekeeper() and not _on_path():
        name = off_path() or name
    return f"{name} {subcommand}" if subcommand else name


def _on_path() -> bool:
    """Whether the `judgekeeper` command the shell finds on the PATH is this program: the
    script that started it (a link to it too), or one in this python's scripts folder (where
    its python is, in a venv). Another install first on the PATH (an older one) would run
    instead."""
    import shutil

    found = shutil.which("judgekeeper")
    if not found:
        return False
    try:
        real = _same(os.path.realpath(found))
        typed = sys.argv[0] if sys.argv else ""
        if typed and _same(os.path.realpath(typed)) == real:
            return True
        folders = {_same(os.path.dirname(os.path.abspath(found))), _same(os.path.dirname(real))}
        return bool(folders & _scripts_folders())
    except (OSError, ValueError):
        return False


def _same(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _scripts_folders() -> set[str]:
    """The folders this python's scripts are in: its own folder (a venv's bin or Scripts),
    and sysconfig's scripts folder."""
    folders = {_same(os.path.dirname(os.path.abspath(sys.executable)))} if sys.executable \
        else set()
    try:
        import sysconfig

        scripts = sysconfig.get_path("scripts")
    except Exception:  # noqa: BLE001 - a python that can't say where its scripts go
        scripts = None
    if scripts:
        folders |= {_same(scripts), _same(os.path.realpath(scripts))}
    return folders


@contextmanager
def run_from(folder: str | Path):
    """Within it, program() names judgekeeper as it is typed in `folder` (a line that says
    to go there and run it), or in any folder (ANYWHERE: a folder it can't name)."""
    global _from
    was, _from = _from, (ANYWHERE if folder == ANYWHERE else os.path.abspath(folder))
    try:
        yield
    finally:
        _from = was


def program_in(folder: str | Path, subcommand: str = "") -> str:
    """program() for a line that says to run it in `folder` (the project folder), or in a
    folder it can't name (ANYWHERE): every path in it from there."""
    with run_from(folder):
        return program(subcommand)


@contextmanager
def plainly():
    """Within it, program() names judgekeeper plainly (`judgekeeper`, or uvx's form): for a
    file people share, such as report.html, where a path typed to start it means nothing."""
    global _plain
    was, _plain = _plain, True
    try:
        yield
    finally:
        _plain = was


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
next_said = False  # a Next: line was said, the run's last word: a Ctrl-C after it adds none


ctrl_c: list[bool] = []  # holds True once this run noted a Ctrl-C (note_ctrl_c)


def note_ctrl_c(signum, frame) -> None:
    """Python's own Ctrl-C (KeyboardInterrupt), noted first (cli.main puts it in for the run):
    a library that swallows the KeyboardInterrupt (raised inside its import, where Python
    would say "Exception ignored" with a traceback and go on) can't make the run carry on, and
    nothing is printed for it: the run says "Stopped."."""
    ctrl_c.append(True)
    sys.unraisablehook = _unsaid
    raise KeyboardInterrupt


def _unsaid(unraisable) -> None:
    """An error Python could only print (a Ctrl-C swallowed, what it left half done): the run
    is stopping, so it is not printed."""


def stop_if_noted() -> None:
    """A Ctrl-C a library swallowed stops the run here (cli._stopped), before its next line
    or the next check of a long read, unless the run has said its Next: line."""
    if ctrl_c and not next_said:
        ctrl_c.clear()
        raise KeyboardInterrupt


def said_next(text: str) -> None:
    """Note a line about to be printed: a Next: line ends what the command says. After a
    Ctrl-C a library swallowed, the run stops instead, before this line."""
    global next_said
    stop_if_noted()
    if text.startswith("Next:"):
        next_said = True
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
    stop_if_noted()  # a swallowed Ctrl-C: the read stops, not after the whole file
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


def utf8_lines(path: str | Path, error: type[Exception], newline: str = ""):
    """The lines of a file the user supplied, one at a time, as read_utf8 reads it (UTF-8, no
    byte order mark, the same `error`s) but never held whole: split as open() splits them
    with `newline`. Close it (contextlib.closing) when not read to the end."""
    import io

    global last_read
    last_read = Path(path).name
    _reading.update(since=_clock(), said=None)
    try:
        raw = open_regular(path)
    except NotAFile as e:
        raise error(not_a_file_message(path, e.kind)) from None
    with io.TextIOWrapper(raw, encoding="utf-8", newline=newline) as text:
        first = True
        try:
            for line in text:
                if "\x00" in line:  # UTF-16 without a byte order mark (decode_utf8)
                    raise ValueError("NUL byte")
                yield line.removeprefix(BOM) if first else line
                first = False
        except ValueError:  # UnicodeDecodeError is one
            raise error(not_utf8_message(path)) from None


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


def loads(text: str):
    """json.loads for a file in judgekeeper's own folder: JSON nested deeper than MAX_NESTING
    (a project can come with that folder) is a ValueError, as damaged JSON is, on every
    Python version."""
    try:
        data = json.loads(text)
    except RecursionError:
        raise ValueError("nested too deep") from None
    if too_deep(data):
        raise ValueError("nested too deep")
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
    An error names `path`, never the temporary file: that is the file the person knows.
    """
    path = Path(path)
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.{os.getpid()}.", suffix=".tmp",
                                   dir=path.parent)
    except OSError as e:
        _named(e, path)
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        _replace(tmp, path)
    except BaseException as e:
        Path(tmp).unlink(missing_ok=True)
        if isinstance(e, OSError) and e.filename == tmp:
            _named(e, path)
        raise


def _named(e: OSError, path: Path) -> None:
    """`e` said of `path` alone (not of a temporary file next to it)."""
    e.filename, e.filename2 = str(path), None


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
    with another name too (a hard link) is refused: what is added would land there as well. So
    is a symlink, even one made after the folder was looked at (O_NOFOLLOW; not on Windows)."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0))
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


ANOTHER_DRIVE = ("<file>", "PATH")  # a path no Next: line can give from here


def from_here(value: str, labels: bool, command: bool = False) -> str:
    """_from_here, kept whole where a line wraps (_spaced)."""
    shown = _from_here(value, labels, command)
    if " " in shown:
        _spaced.pop(shown, None)
        _spaced[shown] = None
        while len(_spaced) > SPACED_KEPT:
            _spaced.pop(next(iter(_spaced)))
    return shown


def _from_here(value: str, labels: bool, command: bool = False) -> str:
    """A path given in full, as a Next: line repeats it: from the folder the command runs in
    when the two share a folder below the home folder's parents (shares_below_home); else in
    the home folder, `~/...` (_home_shown); else, or on another drive, `<file>` for --labels
    and PATH for the rest. Never the whole path, nor the user name, but in a Windows
    `command`: it runs in cmd.exe and PowerShell, and PowerShell doesn't read %USERPROFILE%,
    so when nothing shorter runs it is the path as given (only ever printed, never kept)."""
    if not Path(value).anchor:  # on Windows, \x\r.csv has no drive but is not relative
        return value
    real = os.path.realpath(value)
    rel = _from_below_home(real, os.getcwd())
    if rel is not None:
        return rel
    if command and is_windows():
        return value
    if (inside := _in_home(real)) is not None:
        return _home_shown(inside)
    return ANOTHER_DRIVE[0 if labels else 1]


def _is_top(folder: str) -> bool:
    """`/`, a drive, or on macOS /private (where /tmp, /var and /etc really are)."""
    return os.path.dirname(folder) == folder or (sys.platform == "darwin"
                                                 and folder == "/private")


def shares_below_home(shared: str) -> bool:
    """Whether two paths whose deepest shared folder is `shared` may be named one from the
    other: `shared` is neither a top folder (_is_top) nor a folder above the home folder, so
    the climb names neither the whole path nor the user name, and stays short."""
    if _is_top(shared):
        return False
    try:
        home = os.path.realpath(Path.home())
        return not (home != shared and os.path.commonpath([home, shared]) == shared)
    except (OSError, RuntimeError, ValueError):
        return True


def above_projects(folder) -> bool:
    """Whether `folder` is a top folder (_is_top) or a folder above the home folder: no
    project's folder, and a search below it would walk into home folders."""
    try:
        return not shares_below_home(os.path.realpath(folder))
    except (OSError, ValueError):
        return False


def through_top(path) -> bool:
    """Whether `path`, typed from here, climbs through a top folder or a folder above the home
    folder (shares_below_home): a printed command names it as from_here does instead."""
    try:
        return _from_below_home(os.path.realpath(path), os.getcwd()) is None
    except OSError:
        return False


def shown_in(path, root) -> str:
    """A file found in the project folder `root` as Find's lines name it (File:, "looks
    like", the question to save how to read it): from the project folder when this runs
    there, else from here (shown_from_here)."""
    try:
        real, top = Path(path).resolve(), Path(root).resolve()
        if real.is_relative_to(top) and Path.cwd().resolve() == top:
            return real.relative_to(top).as_posix()
    except (OSError, RuntimeError, ValueError):
        pass
    return shown_from_here(path)


def _from_below_home(real: str, start) -> str | None:
    """`real` from the folder `start` (`..` allowed, `/` between folders) when they share a
    folder below the home folder's parents (shares_below_home), else None."""
    try:
        start = os.path.realpath(start)
        rel = os.path.relpath(real, start)
        shared = os.path.commonpath([real, start])
    except ValueError:  # another drive (Windows)
        return None
    return rel.replace(os.sep, "/") if shares_below_home(shared) else None


CUT = "\u2026"  # a folder in another person's home folder, cut short (folder_from_here)


def home_word() -> str:
    """The home folder itself as folder_from_here names it: `~`, `%USERPROFILE%` on Windows."""
    return HOME_FORMS[1].rstrip("\\") if is_windows() else HOME_FORMS[0].rstrip("/")


def _is_home(real: str) -> bool:
    try:
        return os.path.normcase(real) == os.path.normcase(os.path.realpath(Path.home()))
    except (OSError, RuntimeError):
        return False


def cut_short(shown: str) -> bool:
    """Whether a folder_from_here name is one in another person's home folder, cut short:
    no line can send the person there by it."""
    return CUT in shown


def folder_from_here(path) -> str:
    """A folder as a line names it, to go to: from here when the two share a folder below the
    home folder's parents (_from_below_home); else in the home folder, `~/...`; else in
    another person's home folder (beside this one), `/.../its name`; else from here (another
    drive: the path as it is). The home folder itself is `~` (`%USERPROFILE%` on Windows).
    Never a user name. folder_of turns it back into the folder."""
    real = os.path.realpath(path)
    rel = _from_below_home(real, os.getcwd())
    if rel is not None:
        return rel
    if (inside := _in_home(real)) is not None:
        return _home_shown(inside)
    if _is_home(real):
        return home_word()
    try:
        homes = os.path.dirname(os.path.realpath(Path.home()))
        if os.path.commonpath([homes, real]) == homes and real != homes:
            return f"{Path(real).anchor}{CUT}/{Path(real).name}".replace("\\", "/")
        return os.path.relpath(real, os.getcwd()).replace(os.sep, "/")
    except (OSError, RuntimeError, ValueError):  # another drive (Windows)
        return Path(real).as_posix()


def folder_of(shown: str, base) -> Path | str:
    """The folder a folder_from_here name (from `base`) stands for; ANYWHERE when it was cut
    short, so a command for it is one that runs in any folder."""
    if shown == home_word():
        return Path.home()
    for form in HOME_FORMS:
        if shown.startswith(form):
            return Path.home() / shown[len(form):]
    if CUT in shown:
        return ANYWHERE
    return Path(base) / shown


def cd_word(shown: str) -> str:
    """A folder_from_here name as `cd` is given it: quoted, with `~/` outside the quotes."""
    if shown == home_word():
        return shown
    for form in HOME_FORMS:
        if shown.startswith(form):
            return _home_command(shown[len(form):]) or quote_arg(shown)
    return quote_arg(shown)


def kept_path(path, root) -> str:
    """`path` as a file in .judgekeeper/ keeps it, to find it again (kept_at): from the
    project folder `root` when the two share a folder below the home folder's parents (`..`
    allowed, `/` between folders); else in the home folder, `~/...`; else, outside the home
    folders, its whole path when it names no person (name_only_why); else (in another
    person's home folder, say) its base name. Never the user name."""
    real = os.path.realpath(path)
    rel = _from_below_home(real, root)
    if rel is not None:
        return rel
    inside = _in_home(real)
    if inside is not None:
        return HOME_FORMS[0] + inside.replace(os.sep, "/")
    if name_only_why(real) is None:
        return Path(real).as_posix()
    return Path(os.fsdecode(path)).name


def name_only_why(real: str) -> str | None:
    """Why the whole path `real` can't be kept, as it names a person: "theirs" when it is in
    the folder of home folders (another person's home folder, say), "yours" when a folder in
    it holds the user's name (the home folder's, or the login's: a temporary folder can hold
    it), on any drive; else None."""
    import getpass

    try:
        home = os.path.realpath(Path.home())
    except (OSError, RuntimeError):
        home = ""
    try:
        homes = os.path.dirname(home)
        if home and os.path.normcase(os.path.commonpath([homes, real])) == os.path.normcase(homes):
            return "theirs"
    except ValueError:  # another drive (Windows): not under them
        pass
    try:
        login = getpass.getuser()
    except (OSError, KeyError, ImportError):  # no login name to be had
        login = ""
    names = {n.lower() for n in (os.path.basename(home), login) if n}
    return "yours" if any(n in part.lower() for n in names for part in Path(real).parts) else None


def found_again(path, root) -> bool:
    """Whether the path .judgekeeper/ keeps for `path` (kept_path) leads back to it."""
    try:
        return os.path.samefile(kept_at(kept_path(path, root), root), path)
    except OSError:
        return False


def kept_at(kept: str, root) -> str:
    """A path a file in .judgekeeper/ keeps (kept_path), as a path to read: `~/...` in the
    home folder, else from the project folder `root`; an older file's whole path stays as it
    is."""
    if kept.startswith(HOME_FORMS[0]):
        return os.path.normpath(os.path.join(Path.home(), kept[len(HOME_FORMS[0]):]))
    return os.path.normpath(os.path.join(root, kept))


def shown_from_here(value) -> str:
    """A path as a line names it (not a command): from the folder the command runs in, else
    (another drive) its base name. Never the whole path."""
    text = os.fsdecode(value)
    shown = from_here(text, labels=False)
    return Path(text).name if shown in ANOTHER_DRIVE else shown


def folder_words(shown: str) -> str:
    """A folder from here as a sentence says it: never only dots before its full stop. "."
    is "this folder", ".." "the folder above", "../.." "2 folders above"; else as it is."""
    if shown in (".", "./"):
        return "this folder"
    parts = shown.replace("\\", "/").rstrip("/").split("/")
    if parts and all(p == ".." for p in parts):
        return "the folder above" if len(parts) == 1 else f"{len(parts)} folders above"
    return shown


def runnable(value: str, labels: bool) -> str:
    """from_here, quoted for a shell unless it stands for a path (ANOTHER_DRIVE); a path in
    the home folder keeps its `~/` outside the quotes."""
    shown = from_here(value, labels, command=True)
    if shown in ANOTHER_DRIVE:
        return shown
    for form in HOME_FORMS:
        if shown.startswith(form):
            return _home_command(shown[len(form):]) or ANOTHER_DRIVE[0 if labels else 1]
    return quote_arg(shown)


# File-system errors --------------------------------------------------------------------------

def shown_path(path) -> str:
    """A path as an error shows it, never the whole path from the root: from .judgekeeper/ on
    for a file in it, else from the folder the command runs in, else its name alone."""
    text = os.fsdecode(path)
    p = Path(text)
    if not p.anchor:  # on Windows, \x\r.csv has no drive but is not relative
        return text
    if WORKSPACE in p.parts:
        return "/".join(p.parts[p.parts.index(WORKSPACE):])
    try:
        rel = p.relative_to(Path.cwd().resolve())
    except (ValueError, OSError):
        try:
            rel = p.resolve().relative_to(Path.cwd().resolve())
        except (ValueError, OSError):
            return p.name or text
    return rel.as_posix() if rel.parts else "."


def _folder_needed(path) -> str:
    return (f"{shown_path(path)} is a file, but a folder is needed there. Choose another location, or "
            "move the file.")


def _file_needed(path) -> str:
    return f"{shown_path(path)} is a folder, but a file is needed there. Add a file name to the path."


def _cannot_write(path) -> str:
    message = (f"cannot write {shown_path(path)}: permission denied. Choose a location you can write to, "
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
    `judgekeeper check --fast` (a command that no longer exists), else None. The hook is only
    read: judgekeeper never edits it."""
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
    try:
        is_file, is_dir = folder.is_file(), folder.is_dir()
    except OSError:  # in a folder that can't be read (/lost+found): not judgekeeper's own
        return None
    if is_file:
        return WORKSPACE_FILE, WORKSPACE_FILE_NEXT
    if isinstance(e, NotAFile):
        shown = "/".join(parts[parts.index(WORKSPACE):]).replace("{", "(").replace("}", ")")
        return (NOT_A_FILE.format(path=shown, kind=e.kind),
                NOT_A_FILE_NEXT.replace("{path}", shown))
    if isinstance(e, FileBusyError):
        return WORKSPACE_BUSY, WORKSPACE_BUSY_NEXT
    if isinstance(e, PermissionError) and is_dir:  # else the project folder's
        return WORKSPACE_DENIED, WORKSPACE_DENIED_NEXT
    return None


def describe_os_error(e: OSError) -> str | None:
    """One plain line for a file-system error, naming the path and what to do.

    None when the error names no path (a network error, say): that is not a file problem.
    """
    if not isinstance(e.filename, str | bytes | os.PathLike):
        return None  # no path, or a file descriptor
    path = shown_path(e.filename)
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
        real = os.fsdecode(e.filename)
        if is_windows() and os.path.isdir(real):
            return _file_needed(path)  # Windows says "permission denied" for this
        if os.path.isfile(real) and not os.access(real, os.R_OK):
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
    (held_back) is shown as PLACEHOLDER, and said as data under the line (held_lines), as
    quote_arg does: between quotes it could still be pasted."""
    if held_back(value):
        return quote_arg(value)
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
_spaced: dict[str, None] = {}  # the paths with spaces from_here named: never split either
SPACED_KEPT = 256
WHOLE = ("Inspect AI", "left out")  # never split either: a name, and the words a line that
# leaves a file out is found by


def wrap(text: str, width: int = WIDTH, indent: str = "") -> list[str]:
    """`text` as lines of at most `width` characters (a longer command, or a path with
    spaces judgekeeper named, stays whole on its own line), each starting with `indent`. Each line break in `text` (\\n) starts a new line;
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
    text = text[:1] + re.sub(r"(?<!\s)\s+(?=Next:)", "\0", text[1:])
    keep = (re.findall(r"`[^`]*`", text) + [w for w in WHOLE if w in text]
            + sorted((p for p in _spaced if p in text), key=len, reverse=True))
    for part in keep:
        text = text.replace(part, part.replace(" ", "\0"))
    lines = []
    for piece in text.split("\n"):
        lines += textwrap.wrap(piece, width, initial_indent=indent, subsequent_indent=indent,
                               break_long_words=False, break_on_hyphens=False) or [indent.rstrip()]
    return [links_back(line.replace("\0", " ")) for line in lines]
