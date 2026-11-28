"""The website's hidden lines say the headline, "Check agents and chatbots with human
judgment.", and the README's first paragraph: llms.txt opens with them, and no description,
share line or llms.txt line still says the old sub-line or opens with an LLM-as-a-judge. The
home page's titles say the headline, and the Guide's Read step names the marking first."""

from __future__ import annotations

import re
from pathlib import Path

WEBSITE = Path(__file__).resolve().parent.parent / "website"
HEADLINE = "Check agents and chatbots with human judgment."
PARAGRAPH = ("judgekeeper checks your AI agent or chatbot with human judgment. You mark what's "
             "right, and it shows how often an agent-as-a-judge or an LLM-as-a-judge (an AI model "
             "that grades another model's work) agrees with you, and where it goes wrong.")
OLD = "Human judgment decides what's right."


def test_llms_txt_opens_with_the_headline_and_the_paragraph():
    lines = (WEBSITE / "llms.txt").read_text(encoding="utf-8").splitlines()
    assert lines[2] == (f"> {HEADLINE} Read. Measure. Fix. Re-check. {PARAGRAPH} It is an "
                        "open-source command-line tool that runs on your own computer.")


def test_no_hidden_line_says_the_old_sub_line_or_opens_with_an_llm_as_a_judge():
    for page in [*sorted(WEBSITE.rglob("*.html")), WEBSITE / "llms.txt"]:
        text = page.read_text(encoding="utf-8")
        assert OLD not in text, page.name
        hidden = re.findall(r'(?:content="|"description":")([^"]*)"', text)
        if page.suffix == ".txt":
            hidden = [x.lstrip("-> ") for x in text.splitlines()]
        for line in hidden:
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                assert not re.match(r"(?:An |Your |The )?LLM-as-a-judge", sentence), (
                    page.name, sentence)


def test_the_home_page_titles_say_the_headline():
    page = (WEBSITE / "index.html").read_text(encoding="utf-8")
    want = "Check agents and chatbots with human judgment | judgekeeper"
    assert f"<title>{want}</title>" in page
    assert f'<meta property="og:title" content="{want}">' in page
    assert f'<meta name="twitter:title" content="{want}">' in page
    assert "The keeper of human judgment for AI |" not in page


def test_the_guide_says_the_grade_stays_hidden_while_you_mark():
    text = re.sub(r"<[^>]+>", "", (WEBSITE / "start.html").read_text(encoding="utf-8"))
    assert "While you mark, the grade from your LLM-as-a-judge stays hidden." in text
    assert "grade stays hidden while you mark" not in text
