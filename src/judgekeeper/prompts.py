"""Judge prompt files: markdown with a `rubric_version` frontmatter and {{placeholders}}."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from judgekeeper.textio import decode_utf8

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
# What `judgekeeper init` leaves for the user to write; `judge --prompt` refuses a file that
# still has one.
FILL_IN = "[FILL IN"
_FILL_IN = re.compile(r"\[FILL IN[^\]]*\]?")


def unfilled_marker(text: str) -> tuple[int, str] | None:
    """(line number, marker) of the first `[FILL IN: ...]` left in a prompt, or None."""
    for n, line in enumerate(text.splitlines(), 1):
        m = _FILL_IN.search(line)
        if m:
            return n, m.group(0)
    return None


class PromptError(Exception):
    pass


def prompt_text(path: str | Path) -> str:
    """A prompt file's text as it is hashed: UTF-8, with line endings as \\n."""
    return decode_utf8(Path(path).read_bytes(), path, PromptError).replace("\r\n", "\n")


@dataclass(frozen=True)
class Prompt:
    template: str
    rubric_version: str
    prompt_hash: str
    path: str

    def render(self, **values: str) -> str:
        def sub(m: re.Match) -> str:
            key = m.group(1)
            if key not in values:
                raise PromptError(f"prompt {self.path} uses {{{{{key}}}}} but no value given")
            return str(values[key])

        # single pass, so braces inside substituted content are never re-interpreted
        return _PLACEHOLDER.sub(sub, self.template)


def load_prompt(path: str | Path) -> Prompt:
    path = Path(path)
    if not path.is_file():
        raise PromptError(f"prompt file not found: {path}")
    text = prompt_text(path)
    m = _FRONTMATTER.match(text)
    meta: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip().strip("\"'")
    if not meta.get("rubric_version"):
        raise PromptError(f"prompt {path} needs frontmatter with rubric_version")
    template = text[m.end():]
    return Prompt(
        template=template,
        rubric_version=meta["rubric_version"],
        prompt_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        path=str(path),
    )


def parse_verdict(text: str, allowed: tuple[str, ...]) -> str | None:
    """Return the last `Verdict: X` in the text, normalised to one of `allowed`, or None."""
    pattern = re.compile(r"\bverdict\b[\s:*#_=-]{1,8}(?:output\s+)?\(?([a-z]+)\b", re.IGNORECASE)
    lookup = {a.lower(): a for a in allowed}
    matches = pattern.findall(text)
    if not matches:
        return None
    return lookup.get(matches[-1].lower())
