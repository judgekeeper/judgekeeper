"""docs/examples/ai-check/: a real run on a made-up shop help bot's answers, with no grades.
Every figure the README, the reference and the website give for checking an AI's answers
comes from this run, and the prompts they quote are the ones judgekeeper prints."""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from pathlib import Path

from judgekeeper import front, no_grades
from judgekeeper.metrics import wilson
from judgekeeper.report_page import estimate

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "docs" / "examples" / "ai-check"
FIRST_LINE = ("A made-up example: the questions, answers and marks were written for this example, "
              "not taken from a real AI or real users.")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _rows() -> list[dict]:
    with (EXAMPLE / "results.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _last_marks() -> dict[str, str]:
    """Each answer's last mark in marks.jsonl (its first line is the header)."""
    last = {}
    for line in _text(EXAMPLE / "marks.jsonl").splitlines()[1:]:
        d = json.loads(line)
        if "mark" in d:
            last[d["id"]] = d["mark"]
    return {i: m for i, m in last.items() if m in ("pass", "fail")}


def _between(k: int, n: int) -> str:
    w = wilson(k, n)
    return estimate(w["p"], [w["lo"], w["hi"]])[1]


def test_the_example_says_it_is_made_up_in_its_first_line():
    assert _text(EXAMPLE / "README.md").splitlines()[0] == FIRST_LINE


def test_the_answers_have_no_grades():
    rows = _rows()
    assert len(rows) == 20 and list(rows[0]) == ["input", "output"]


def test_every_answer_was_marked_and_12_of_20_passed():
    marked = _last_marks()
    assert len(marked) == 20
    assert Counter(marked.values()) == {"pass": 12, "fail": 8}


def test_the_ranges_the_docs_give():
    assert _between(12, 20) == "39% and 78%"
    assert _between(6, 10) == "31% and 83%"


def test_the_run_printed_and_wrote_those_figures():
    said = _flat(_text(EXAMPLE / "terminal-1.txt"))
    assert "You passed 12 of 20 answers." in said
    page = _flat(re.sub(r"<[^>]+>", "", html.unescape(_text(EXAMPLE / "report.html"))))
    assert "You passed 12 of 20 answers." in page and "between 39% and 78%" in page
    assert ("You failed 4 answers here. 4 more answers you failed are kept aside to test your next "
            "change.") in _text(EXAMPLE / "failed-answers.md")


def test_the_docs_give_the_figures_of_the_run():
    example = _flat(_text(EXAMPLE / "README.md"))
    assert "12 of 20 answers passed, about 60%, between 39% and 78%" in example
    reference = _flat(_text(ROOT / "docs" / "reference.md"))
    assert "12 of 20 passed: about 60%, between 39% and 78%" in reference
    assert reference.count("6 of 10 passed gives between 31% and 83%") == 2


def test_the_docs_quote_the_prompts_judgekeeper_prints():
    fix = no_grades.FIX_PROMPT.format(file=".judgekeeper/fix/failed-answers.md",
                                      with_reasons=", with my reasons")
    assert fix in _text(ROOT / "docs" / "reference.md")
    questions = front.QUESTIONS_PROMPT.format(program="judgekeeper")
    assert questions in html.unescape(_text(ROOT / "website" / "start.html"))


def test_the_second_run_answered_the_same_questions_again():
    with (EXAMPLE / "results-after.csv").open(encoding="utf-8", newline="") as f:
        after = list(csv.DictReader(f))
    assert len(after) == 20 and list(after[0]) == ["input", "output"]
    assert [r["input"] for r in after] == [r["input"] for r in _rows()]
    changed = sum(a["output"] != b["output"] for a, b in zip(after, _rows(), strict=True))
    assert changed == 20  # every answer worded anew: every question is compared


def test_the_second_run_printed_fixed_broke_and_same():
    said = _flat(_text(EXAMPLE / "terminal-2.txt"))
    compared = no_grades.COMPARED.format(n="10 questions", fixed=3, broke=1, same=6)
    lean = f"{no_grades.CHANGE['leans better']} {_clear_line()}"
    assert "You passed 16 of 20 answers." in said and compared in said and lean in said


def _clear_line() -> str:
    """What a clear answer needs, from the run's figures: 20 marked, 8 failed, 4 of them kept
    aside, the first change tested on them."""
    return no_grades.clear_line({"kept": 10, "fixed": 3, "broke": 1, "same": 6, "test": 1,
                                 "kept_fails": 4, "fails": 8, "marked": 20})


def test_every_run_says_which_path_it_took():
    line = front.PATH_NO_GRADES.format(file="results.csv") + " " + front.PATH_TO_GRADES
    for name in ("terminal-1.txt", "terminal-2.txt"):
        assert _flat(_text(EXAMPLE / name)).count(line) == 2, name


def test_the_docs_give_the_second_run_as_judgekeeper_says_it():
    example = _flat(_text(EXAMPLE / "README.md"))
    assert "16 of 20 answers passed" in example
    assert "3 were fixed, 1 broke and 6 stayed the same" in example
    assert f'"{_clear_line()}"' in example
    assert "This example uses 20 questions, so a clear answer was not possible." in example
    reference = _flat(_text(ROOT / "docs" / "reference.md"))
    assert "3 were fixed, 1 broke and 6 stayed the same" in reference
    assert f'"{no_grades.CHANGE["leans better"]}"' in reference
    for words in (no_grades.CHANGE["helped"].split(".")[0],
                  no_grades.CHANGE["worse"].split(".")[0], no_grades.BROKE):
        assert f'"{words}' in reference, words
    assert f"fewer than {no_grades.FEW_COMPARED} kept-aside questions" in reference
