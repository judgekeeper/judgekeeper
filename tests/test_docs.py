"""The README and the docs folder: what each holds, in the agreed words. The README's numbers
come from the committed report in docs/examples/llmbar-haiku.
"""

from __future__ import annotations

import json
import re

from tests.website_pages import ROOT

README = ROOT / "README.md"
STEPS = (("Find", "`judgekeeper`"), ("Mark", "`judgekeeper mark`"),
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
                   "Find. Mark. Measure. Fix. Re-check.", "readme-label.png"):
        assert needed in top, needed
    heads = list(_sections(text))
    wanted = ["Install", "The 5 steps", "Numbers", "Status", "Issues", "License"]
    assert [h for h in heads if h in wanted] == wanted


def test_the_readme_has_each_step_with_its_command():
    steps = _sections(_readme())["The 5 steps"]
    for n, (step, command) in enumerate(STEPS, 1):
        line = next(x for x in steps.splitlines() if x.startswith(f"{n}. **{step}.**"))
        assert command in line, step


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def test_the_readme_numbers_are_the_llmbar_reports():
    """LLMBar is pairwise (which of two answers is better), so no Pass, Fail, TPR or TNR."""
    report = json.loads((ROOT / "docs/examples/llmbar-haiku/report.json").read_text(
        encoding="utf-8"))
    h = report["headline"]
    numbers = _flat(_sections(_readme())["Numbers"])
    needed = (f"**A real judge, checked.** Claude Haiku 4.5 on the LLMBar benchmark: "
              f"{report['anchors']['n_items']} pairs of answers where the benchmark's authors "
              f"marked the better one. It picked the same one {_pct(h['accuracy_mean'])} of the "
              f"time (kappa {h['kappa_mean']:.2f}), over {report['n_runs']} runs. [Report](")
    assert needed in numbers
    llmbar = numbers[numbers.index(needed):numbers.index("**Its ranges hold")]
    for word in ("Pass", "Fail", "TPR", "TNR"):
        assert word not in llmbar, word


def test_the_readme_keeps_to_the_agreed_words():
    text = _readme()
    assert "can read results from" in text
    assert "judgekeeper.com" not in text
    for word in (r"luck(y)?", r"chance", r"works with", r"integrates? with", r"rough(ly)?",
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
