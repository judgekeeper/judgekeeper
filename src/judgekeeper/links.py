"""A file a person is told to open, as a link they can click in the terminal.

`link` wraps the printed path in an OSC 8 hyperlink (Cmd+click or Ctrl+click opens the file).
The text shown stays the short path printed today, so line widths do not change. Anywhere
else (a pipe, --json, a log, CI, TERM=dumb, NO_COLOR or JUDGEKEEPER_NO_LINKS set, the old
Windows console) it is that same text, byte for byte. What judgekeeper says keeps these
links through its clean-up of control characters (keep) and wraps them by their text
(stand_ins). Standard library only.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import sys
from urllib.parse import quote

from judgekeeper.textio import is_windows

OPT_OUTS = ("NO_COLOR", "JUDGEKEEPER_NO_LINKS")
STAND_IN = 0xF0000  # wrap measures link k as len(its text) of chr(STAND_IN + k) (private use)

_made: dict[str, tuple[str, str]] = {}  # each link `link` made: (its URL, its text)


def link(path, shown: str | None = None, line: int | None = None, stream=None) -> str:
    """`shown` (the path as given by default), with `:line` after it, linked to the file.

    `path` is where the file is: absolute, or relative to the current folder. The URL is the
    file, never the line: terminals and editors that can go to a line read it from the text.
    """
    text = str(path) if shown is None else shown
    if line is not None:
        text = f"{text}:{line}"
    if not text or not _links_show(sys.stdout if stream is None else stream):
        return text
    url = file_url(path)
    made = _osc8(url, text)
    _made[made] = (url, text)
    return made


def said(text: str) -> str:
    """A line judgekeeper says, ready to print: credentials scrubbed and control characters
    dropped (redact.one_line), the links `link` made kept."""
    from judgekeeper.redact import one_line, scrub

    return keep(text, lambda part: one_line(scrub(part)))


def keep(text: str, clean) -> str:
    """`clean(text)` (which drops control characters, ESC among them) with each link `link`
    made kept whole, its text cleaned too. Escape codes from anywhere else are dropped."""
    found = _found(text)
    if found is None:
        return clean(text)
    out, end = [], 0
    for m in found.finditer(text):
        url, shown = _made[m[0]]
        out += [clean(text[end:m.start()]), _osc8(url, clean(shown))]
        end = m.end()
    return "".join([*out, clean(text[end:])])


def stand_ins(text: str):
    """(`text` with each link `link` made as a stand-in as long as its text, a function that
    puts the links back in a line of it): wrapping then counts only what is seen."""
    found = _found(text)
    if found is None:
        return text, lambda line: line
    made = {}

    def stand_in(m):
        made.setdefault(m[0], chr(STAND_IN + len(made)) * len(_made[m[0]][1]))
        return made[m[0]]

    text = found.sub(stand_in, text)
    back = {v: k for k, v in made.items()}
    again = re.compile("|".join(map(re.escape, sorted(back, key=len, reverse=True))))
    return text, lambda line: again.sub(lambda m: back[m[0]], line)


def _found(text: str):
    """A pattern for the links `link` made that are in `text`; None when there is none."""
    if "\x1b" not in text:
        return None
    here = [made for made in _made if made in text]
    if not here:
        return None
    return re.compile("|".join(map(re.escape, sorted(here, key=len, reverse=True))))


def _osc8(url: str, text: str) -> str:
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


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
