"""Plain words on the website: no word that sounds like marketing copy, no time estimates and
no "AI judge" ("your judge" or "the judge"; "LLM-as-a-judge" outside the tool). Every page.
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
CHECKED = pages()


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


def test_the_pages_checked_are_every_page():
    assert (WEBSITE / "index.html") in CHECKED and (WEBSITE / "start.html") in CHECKED


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
    assert not re.search(r"\bAI judges?\b", text, re.IGNORECASE)
    assert not re.search(r"\bhow sure\b", text, re.IGNORECASE)


def test_the_test_finds_a_word_when_there_is_one(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<p>A <b>Robust</b> check.</p><img alt="It is seamless">', encoding="utf-8")
    text = _all_text(page)
    assert re.search(r"(?<![\w-])robust(?![\w-])", text, re.IGNORECASE)
    assert "seamless" in text


@pytest.mark.parametrize("page", [*CHECKED, WEBSITE / "errors/404.html"], ids=lambda p: p.name)
def test_no_raw_markdown_in_what_a_page_shows(page):
    """A link or bold text the page generator missed shows as `[text](link)` or `**text**`."""
    hidden = {"pre", "code", "script", "style"}
    text = " ".join(c for el in parse(page).iter()
                    if not hidden & {el.tag, *(a.tag for a in el.ancestors())}
                    for c in el.children if isinstance(c, str))
    assert "](" not in text and "**" not in text, page.name


# The site's own word rules (every page, the page for a wrong address and llms.txt)

WRITTEN = [*pages(), WEBSITE / "errors/404.html"]
BANNED = [  # (pattern, what to say instead)
    (r"\bfree\b", 'nothing has a price: no "free", "for free" or "free check"'),
    (r"\byour app\b", 'never "your app": "your answers", "whatever made the answers"'),
    (r"\bcheck (?:your|the|a|an) judge\b", '"check your LLM-as-a-judge"'),
    (r"\bhidden marks?\b|\bmarks? (?:set aside and )?hidden\b", '"kept aside"'),
    (r"\bluck(?:y|ily)?\b", '"coincidence"'),
]


def _visible(page: Path) -> str:
    """What the site says on a page, with the alt text, labels and meta lines. Not what
    judgekeeper prints (the terminal screens quote it as it is), and not the demo's sample
    answers in its data block."""
    parts = []
    for el in parse(page).iter():
        if el.tag not in {"script", "style"} and not in_output(el):
            parts.extend(c for c in el.children if isinstance(c, str))
        for attr in ("alt", "aria-label", "title", "content"):
            if attr in el.attrs:
                parts.append(el.attrs[attr])
    return " ".join(" ".join(parts).split())


@pytest.mark.parametrize("page", WRITTEN, ids=lambda p: p.name)
def test_the_sites_word_rules(page):
    text = _visible(page)
    for pattern, instead in BANNED:
        found = re.search(pattern, text, re.IGNORECASE)
        assert not found, f"{page.name}: {found and found[0]!r}: {instead}"


def test_llms_txt_follows_the_word_rules():
    text = (WEBSITE / "llms.txt").read_text(encoding="utf-8")
    for pattern, instead in BANNED:
        found = re.search(pattern, text, re.IGNORECASE)
        assert not found, f"llms.txt: {found and found[0]!r}: {instead}"


def test_the_pages_use_the_words_the_rules_ask_for():
    words = {p.name: _visible(p) for p in pages()}
    assert "Check your LLM-as-a-judge" in words["index.html"]
    assert "Check your LLM-as-a-judge" in words["check.html"]
    assert "kept aside" in words["index.html"]  # Home's Fix step


def test_the_word_rules_find_a_banned_word(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<p>Check your judge for free on your app.</p>"
                    '<script type="application/json">["a free replacement"]</script>',
                    encoding="utf-8")
    text = _visible(page)
    hits = [p for p, _ in BANNED if re.search(p, text, re.IGNORECASE)]
    assert hits == [BANNED[0][0], BANNED[1][0], BANNED[2][0]]
    assert "replacement" not in text
