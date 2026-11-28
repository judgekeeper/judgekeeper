"""The headline, as the website says it: "Check agents and chatbots with human judgment."
The README, `judgekeeper --help`, the PyPI summary, CITATION.cff, the reference and the
package's docstring open with it, the README says it once, and none still says the sub-line it
replaced. The README's first paragraph names agents and chatbots, not an LLM-as-a-judge, first."""

from __future__ import annotations

from pathlib import Path

from judgekeeper.cli import main

ROOT = Path(__file__).resolve().parent.parent
HEADLINE = "Check agents and chatbots with human judgment."
OLD = "Human judgment decides what's right."
FIRST_PARAGRAPH = ("judgekeeper checks your AI agent or chatbot with human judgment. You mark what's "
                   "right, and it shows how often an agent-as-a-judge or an LLM-as-a-judge (an AI "
                   "model that grades another model's work) agrees with you, and where it goes "
                   "wrong.")


def _abstract() -> str:
    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("abstract: "))
    return line.removeprefix("abstract: ").strip('"')


def test_the_readme_opens_with_the_headline_once():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    header, rest = readme.split("</div>", 1)
    assert f"<p><strong>{HEADLINE}</strong><br>Read. Measure. Fix. Re-check.</p>" in header
    assert readme.count(HEADLINE) == 1 and OLD not in readme
    first = rest.strip().split("\n\n", 1)[0]
    assert not first.startswith(("LLM-as-a-judge", "An LLM-as-a-judge"))
    assert first == FIRST_PARAGRAPH


def test_help_says_the_headline_first(capsys):
    assert main(["--help"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == [HEADLINE, "", "Read. Measure. Fix. Re-check."]
    assert OLD not in " ".join(lines)


def test_the_pypi_summary_says_the_headline():
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["description"] == HEADLINE + " Read. Measure. Fix. Re-check."


def test_the_citation_abstract_says_the_headline():
    assert _abstract() == HEADLINE + " Read. Measure. Fix. Re-check."


def test_the_reference_and_the_docstring_open_with_the_headline():
    import judgekeeper

    reference = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8").splitlines()
    assert reference[2].startswith(HEADLINE + " Read. Measure. Fix. Re-check. ")
    assert reference[4].startswith("When an AI model grades your eval's answers by a rule you "
                                   "wrote, it is called an LLM-as-a-judge. Each run ends with")
    assert judgekeeper.__doc__.startswith(HEADLINE)
