"""Escape untrusted text for Markdown.

Model ids, provider names, rubric versions, item ids and anchor hashes come from the user's
data or from the provider's response. gate.md and attribution.md are rendered into GitHub job
summaries and PR comments, so a value containing `|`, `<`, a backtick, `[`, `!` or a newline
could break the table, start a heading or inject a link or an image. Every such value in a
table goes through `md_cell` first; a sentence that quotes one goes through `md_text`.
"""

from __future__ import annotations

from judgekeeper.redact import printable

_TEXT = (
    ("\\", "\\\\"),
    ("|", "\\|"),
    ("[", "\\["),
    ("]", "\\]"),
    ("!", "\\!"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ("\r", " "),
    ("\n", " "),
)
_CELL = (*_TEXT[:2], ("`", "\\`"), *_TEXT[2:])


def _escape(value, replacements) -> str:
    text = printable(value)  # no control characters: the file is also shown in terminals
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def md_cell(value) -> str:
    """Return `value` as text that is safe inside one Markdown table cell."""
    return _escape(value, _CELL)


def md_text(value) -> str:
    """Return a sentence judgekeeper wrote, which may quote a value from a file, as one safe
    Markdown paragraph. Like `md_cell`, but backticks stay: the sentence's own code spans."""
    return _escape(value, _TEXT)
