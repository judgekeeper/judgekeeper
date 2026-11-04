"""A file a person is told to open, as the short path judgekeeper prints.

The path is plain text, in a terminal too. A clickable link would hide the whole path, and
with it the user name, in its target, and no printed line shows a user name.
"""

from __future__ import annotations


def link(path, shown: str | None = None, line: int | None = None) -> str:
    """`shown` (the path as given by default), with `:line` after it. `path` is where the file
    is; editors and terminals that open a file or go to a line read it from the text."""
    text = str(path) if shown is None else shown
    return text if line is None else f"{text}:{line}"


def said(text: str) -> str:
    """A line judgekeeper says, ready to print: credentials scrubbed and control characters
    dropped (redact.one_line)."""
    from judgekeeper.redact import one_line, scrub

    return one_line(scrub(text))
