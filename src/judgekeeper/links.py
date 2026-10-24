"""A file a person is told to open, as a link they can click in the terminal.

`link` wraps the printed path in an OSC 8 hyperlink (Cmd+click or Ctrl+click opens the file).
The text shown stays the short path printed today, so line widths do not change. Anywhere
else (a pipe, --json, a log, CI, TERM=dumb, NO_COLOR or JUDGEKEEPER_NO_LINKS set, the old
Windows console) it is that same text, byte for byte. Standard library only.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import sys
from urllib.parse import quote

from judgekeeper.textio import is_windows

OPT_OUTS = ("NO_COLOR", "JUDGEKEEPER_NO_LINKS")


def link(path, shown: str | None = None, line: int | None = None, stream=None) -> str:
    """`shown` (the path as given by default), with `:line` after it, linked to the file.

    `path` is where the file is: absolute, or relative to the current folder. The URL is the
    file, never the line: terminals and editors that can go to a line read it from the text.
    """
    text = str(path) if shown is None else shown
    if line is not None:
        text = f"{text}:{line}"
    if not _links_show(sys.stdout if stream is None else stream):
        return text
    return f"\x1b]8;;{file_url(path)}\x1b\\{text}\x1b]8;;\x1b\\"


def file_url(path, windows: bool | None = None) -> str:
    """The absolute `file://` URL of `path`, spaces and non-ASCII percent-encoded.
    `windows`: read it as a Windows path (the default on Windows)."""
    if windows if windows is not None else is_windows():
        full = ntpath.abspath(os.fspath(path))
        drive, rest = ntpath.splitdrive(full)
        if drive.startswith("\\\\"):  # a network share: file://server/share/...
            return "file:" + quote(full.replace("\\", "/"))
        return f"file:///{drive}{quote(rest.replace(chr(92), '/'))}"
    return "file://" + quote(os.fsencode(posixpath.abspath(os.fspath(path))))


def _links_show(stream) -> bool:
    """A person reads `stream` at a terminal that draws links: on Windows that is Windows
    Terminal (WT_SESSION) or one that names itself (TERM_PROGRAM, as for `tick`)."""
    if any(os.environ.get(name) for name in OPT_OUTS) or os.environ.get("TERM") == "dumb":
        return False
    if is_windows() and not (os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")):
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):  # no isatty, or a closed stream
        return False
