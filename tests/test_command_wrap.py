"""A command on a page breaks only between its words, never inside a flag such as
--no-browser, on a laptop or a phone: each word sits in a span that doesn't wrap (a word
longer than look.LONG_WORD, such as a long path, may still wrap, so it stays on the page). The
text of the command, which Copy takes, is unchanged. Marking page footer, result page and
report.html."""

from __future__ import annotations

import re
from html import unescape

from judgekeeper import look, mark_page, start_label
from tests.test_product_pages import NOT_GATE_TNR, _result

WORD = '<span class="cw">{}</span>'


def _commands(html: str) -> list[str]:
    """Every <code> on the page that holds a judgekeeper command (not the .judgekeeper folder)."""
    return [c for c in re.findall(r"<code>(.*?)</code>", html, re.DOTALL)
            if re.search(r"(^|\s)judgekeeper\b", _plain(c))]


def _plain(code: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", code))


def test_each_word_of_a_command_is_kept_whole():
    shown = look.command("judgekeeper mark --port 9602 --no-browser")
    assert shown == " ".join(WORD.format(w) for w in
                             ("judgekeeper", "mark", "--port", "9602", "--no-browser"))
    assert _plain(shown) == "judgekeeper mark --port 9602 --no-browser"


def test_a_very_long_word_may_still_wrap():
    path = "results/" + "x" * look.LONG_WORD + ".json"
    shown = look.command(f"judgekeeper {path} --no-browser")
    assert f"{WORD.format('judgekeeper')} {path} {WORD.format('--no-browser')}" == shown


def test_the_words_are_escaped_once():
    shown = look.command("judgekeeper 'a &amp; b' &lt;x&gt;")  # already escaped by the page
    assert "&amp;amp;" not in shown and WORD.format("&lt;x&gt;") in shown


def test_every_command_on_the_pages_breaks_only_between_words():
    pages = {"marking footer": mark_page.label_page("support bot",
                                                    "judgekeeper mark --port 9602 --no-browser"),
             "result page": start_label.result_html(_result(*NOT_GATE_TNR), back="/?token=t"),
             "report.html": start_label.result_html(_result(*NOT_GATE_TNR))}
    for name, html in pages.items():
        assert re.search(r"\.cw\s*\{\s*white-space:\s*nowrap;?\s*\}", html), name
        codes = _commands(html)
        assert codes, name
        for code in codes:  # words in spans, one space between them; a long one may be bare
            for part in re.split(r" (?![^<]*>)", code):  # the spaces outside tags
                assert re.fullmatch(r'<span class="cw">[^<\s]+</span>', part) or (
                    "<" not in part and len(unescape(part)) > look.LONG_WORD), (name, code)
