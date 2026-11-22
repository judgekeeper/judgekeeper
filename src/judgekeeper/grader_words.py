"""The words for what judgekeeper checks.

Every printed line was written for an LLM-as-a-judge. When the check is something else (a
rule in code, a Label Studio prediction, an app's score), one function, `swap`, says "your
check" where those lines say "your LLM-as-a-judge". For an LLM-as-a-judge it returns the text
as it is: no released line changes. `use` says which one this run checks (find_judge).
"""

from __future__ import annotations

import re

LLM = "LLM"
_kind = LLM

_PHRASES = (
    (re.compile(r"\byour LLM-as-a-judge's"), "your check's"),
    (re.compile(r"\bYour LLM-as-a-judge's"), "Your check's"),
    (re.compile(r"\bYour (old|new) LLM-as-a-judge"), r"Your \1 check"),
    (re.compile(r"\byour (old|new) LLM-as-a-judge"), r"your \1 check"),
    (re.compile(r"\b[Yy]our LLM-as-a-judge"), lambda m: m[0][:5] + "check"),
    (re.compile(r"\bAn LLM-as-a-judge"), "A check"),
    (re.compile(r"\ban LLM-as-a-judge"), "a check"),
    (re.compile(r"\bThe LLM-as-a-judge"), "The check"),
    (re.compile(r"\bthe LLM-as-a-judge"), "the check"),
    (re.compile(r"\ba LLM-as-a-judge"), "a check"),
    (re.compile(r"LLM-as-a-judge"), "check"),
)


def use(kind: str) -> None:
    """This run checks a `kind` of line (start.grader_of): LLM, or CODE."""
    global _kind
    _kind = kind


def code() -> bool:
    """Whether this run checks something that is not an LLM-as-a-judge."""
    return _kind != LLM


def swap(text: str) -> str:
    """`text` as it is for an LLM-as-a-judge; for any other check, "your LLM-as-a-judge" said
    as "your check", and every other mention of it as "check"."""
    if _kind == LLM or "LLM-as-a-judge" not in text:
        return text
    for pattern, new in _PHRASES:
        text = pattern.sub(new, text)
    return text
