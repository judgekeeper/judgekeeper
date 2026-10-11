"""Plain words on the website: no word that sounds like marketing copy, no time estimates and
no "AI judge" ("your judge" or "the judge"; "LLM-as-a-judge" outside the tool).

reference.html is left out for now: it is generated from docs/reference.md, which another
change is rewriting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.website_pages import WEBSITE, in_output, pages, parse

NEVER = ("seamless", "seamlessly", "effortless", "effortlessly", "empower", "empowers",
         "unlock", "unlocks", "leverage", "leverages", "supercharge", "supercharges", "elevate",
         "elevates", "robust", "powerful", "cutting-edge", "game-changer", "revolutionary",
         "delve", "harness", "streamline", "streamlines", "trusted", "proven")
PHRASES = (r"in today's", r"whether you're", r"not just [^.]*?, it's", r"say goodbye to",
           r"take [^.]*? to the next level", r"peace of mind")
CHECKED = [p for p in pages() if p.name != "reference.html"]


def _all_text(page: Path) -> str:
    """Everything a visitor can read: the text, the alt text, labels and the meta lines."""
    parts = []
    for el in parse(page).iter():
        parts.extend(c for c in el.children if isinstance(c, str))
        for attr in ("alt", "aria-label", "title", "content"):
            if attr in el.attrs:
                parts.append(el.attrs[attr])
    return " ".join(parts)


def _shown(page: Path) -> str:
    """The text outside what a program printed (that is quoted as it is)."""
    return " ".join(c for el in parse(page).iter() if not in_output(el)
                    for c in el.children if isinstance(c, str))


def test_the_pages_checked_are_every_page_but_the_reference():
    assert {p.name for p in CHECKED} == {p.name for p in pages()} - {"reference.html"}
    assert (WEBSITE / "index.html") in CHECKED


@pytest.mark.parametrize("page", CHECKED, ids=lambda p: p.name)
def test_no_word_from_the_never_use_list(page):
    text = _all_text(page)
    for word in NEVER:
        assert not re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.IGNORECASE), word
    for phrase in PHRASES:
        assert not re.search(phrase, text, re.IGNORECASE), phrase


@pytest.mark.parametrize("page", CHECKED, ids=lambda p: p.name)
def test_no_time_estimate_and_no_ai_judge(page):
    text = _shown(page)
    assert not re.search(r"\bminutes?\b", text, re.IGNORECASE)
    assert not re.search(r"\bAI judge\b", text, re.IGNORECASE)
    assert not re.search(r"\bhow sure\b", text, re.IGNORECASE)


def test_the_test_finds_a_word_when_there_is_one(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<p>A <b>Robust</b> check.</p><img alt="It is seamless">', encoding="utf-8")
    text = _all_text(page)
    assert re.search(r"(?<![\w-])robust(?![\w-])", text, re.IGNORECASE)
    assert "seamless" in text
