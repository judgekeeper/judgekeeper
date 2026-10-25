"""The README and the docs folder: what each holds, in the agreed words. The README's numbers
come from the committed reports in docs/examples/.
"""

from __future__ import annotations

import re

from tests.website_pages import ROOT

README = ROOT / "README.md"
STEPS = (("Find", "`judgekeeper`"), ("Mark", "the page opens by itself"),
         ("Measure", "`judgekeeper`"), ("Fix", "`judgekeeper fix`"),
         ("Re-check", "`judgekeeper check`"))


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


def _flat(text: str) -> str:
    return " ".join(text.split())


# The README --------------------------------------------------------------------------------

def test_the_readme_is_short_and_in_order():
    text = _readme()
    assert len(text.splitlines()) < 70
    assert text.startswith('<p align="center"><img ')
    top = text[:text.index("\n## ")]
    for needed in ("**Check your LLM-as-a-judge in 5 steps.**",
                   "Find. Mark. Measure. Fix. Re-check.", "docs/assets/demo.webp"):
        assert needed in top, needed
    assert (ROOT / "docs" / "assets" / "demo.webp").stat().st_size < 1_000_000
    heads = list(_sections(text))
    wanted = ["Install", "The 5 steps", "What the numbers mean", "Checked on public data",
              "More", "License"]
    assert [h for h in heads if h in wanted] == wanted


def test_the_readme_has_each_step_with_its_command():
    steps = _sections(_readme())["The 5 steps"]
    for n, (step, command) in enumerate(STEPS, 1):
        line = next(x for x in steps.splitlines() if x.startswith(f"{n}. **{step}** ("))
        assert command in line, step


EXAMPLES = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/"


def test_the_readme_numbers_are_in_the_reports_they_link():
    """Each public-data line links its report, and every % and decimal on the line is in it."""
    lines = [x for x in _sections(_readme())["Checked on public data"].splitlines()
             if x.startswith("- ")]
    linked = {}
    for line in lines:
        found = re.findall(rf"\]\({re.escape(EXAMPLES)}([\w./-]+)\)", line)
        if not found:
            continue
        report = (ROOT / "docs" / "examples" / found[0]).read_text(encoding="utf-8")
        for figure in re.findall(r"\d+\.\d+|\d+%", line):
            assert figure in report, (found[0], figure)
        linked[found[0]] = line
    assert sorted(linked) == ["coverage/coverage.md", "jailbreakbench/report.md",
                              "probes/report.md", "ragtruth/report.md"]
    assert "In 20 of 20 draws" in linked["jailbreakbench/report.md"]
    assert "Each draw marks 250 of the same 300 answers" in linked["jailbreakbench/report.md"]
    draws = (ROOT / "docs" / "examples" / "jailbreakbench" / "two-batches" / "draws.csv")
    rows = [x.split(",") for x in draws.read_text(encoding="utf-8").splitlines()
            if re.match(r"d\d", x)]
    assert len(rows) == 20 and {r[8] for r in rows} == {"250"}  # marks_counted
    summary = draws.with_name("summary.json").read_text(encoding="utf-8")
    assert '"rows": 300' in summary
    assert "needs work" in linked["ragtruth/report.md"]
    for gone in ("LLMBar", "MT-Bench", "real-data-check"):
        assert gone not in _readme(), gone


def test_the_readme_keeps_to_the_agreed_words():
    text = _readme()
    assert "judgekeeper.com" not in text
    for word in (r"luck(y)?", r"chance", r"integrates? with", r"rough(ly)?",
                 r"AI judges?", r"trusted", r"proven", r"judgekeeper start"):
        assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), word


def test_the_guide_and_the_tool_pages_are_gone_and_nothing_links_them():
    assert not (ROOT / "docs" / "guide.md").exists()
    assert not (ROOT / "docs" / "integrations").exists()
    sources = [README, ROOT / "SECURITY.md", ROOT / "pyproject.toml",
               *(ROOT / "docs").glob("*.md"), *(ROOT / ".github").rglob("*.*"),
               *(ROOT / "src").rglob("*.py")]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for gone in ("guide.md", "docs/integrations"):
            assert gone not in text, (path.relative_to(ROOT).as_posix(), gone)


def test_checking_names_the_llm_as_a_judge_in_full():
    """"Judge" alone can read like a court judge, so checking it names the LLM-as-a-judge."""
    sources = [README, *(ROOT / "docs").glob("*.md"), *(ROOT / "src").rglob("*.py")]
    for path in sources:
        text = _flat(path.read_text(encoding="utf-8")).lower()
        for words in ("check your judge", "checks your judge", "check a judge"):
            assert words not in text, (path.relative_to(ROOT).as_posix(), words)


def test_the_readme_has_three_badges_version_tests_and_licence():
    badges = re.findall(r"!\[([^\]]+)\]\(([^)]+)\)", README.read_text(encoding="utf-8"))
    assert [alt for alt, src in badges if "shields.io" in src or "badge.svg" in src] == [
        "PyPI version", "Tests", "MIT license"]
