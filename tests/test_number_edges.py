"""The numbers' edge cases: a rate of exactly 0.90 in floating point, a judge that passes (or
fails) every answer, a range narrower than one point, and a group of the judge with nothing
counted when it is asked again."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from judgekeeper import front, report_page, start_label, targets, weighted

SRC = Path(__file__).parents[1] / "src" / "judgekeeper"


def test_a_range_ending_exactly_on_the_bar_reaches_it():
    low = 0.4 * 2  # 0.8, worked out as 0.8000000000000002 one way, 0.7999999999999999 another
    end = 0.7 + 0.1
    assert end < 0.8 and round(end, 9) == 0.8
    assert targets.side([end, 0.95]) == "yes"  # green, not amber
    assert targets.side([low, 0.95]) == "yes"
    assert targets.side([0.7999, 0.95]) == "cant_tell"


def _r(pool, marked, out, left):
    """A result with these groups (judge passed, failed), numbers and count left to mark."""
    groups = {g: {"pool": n, "labeled": m} for g, n, m in zip(("pass", "fail"), pool, marked)}
    return {**out, "groups": groups, "left": left}


def test_a_number_with_no_range_says_why_and_never_exactly():
    """A range of no width is not shown: the number says why in brackets. Four ways."""
    # 1. every answer marked
    r = _r((40, 20), (40, 20), weighted.corrected(40, 20, 40, 31, 20, 4), left=0)
    assert report_page.why_for(r, "tpr") == report_page.why_for(r, "tnr") == \
        "you marked every answer"
    # 2. the judge gave every answer the same grade, some still unmarked
    r = _r((400, 0), (40, 0), weighted.corrected(400, 0, 40, 23, 0, 0), left=360)
    assert report_page.why_for(r, "tpr") == "it gave every answer the same grade"
    assert start_label.sentences({**r, "check": "result"})[0] == (
        "You passed: your LLM-as-a-judge also passed 100% (it gave every answer the same grade).")
    # 3. every answer it failed marked, all of them Fail: TPR 100%, TNR keeps a range
    out = weighted.corrected(900, 30, 25, 20, 30, 0)
    assert out["tpr_interval"] == [1.0, 1.0] and out["tnr_interval"][0] < out["tnr_interval"][1]
    r = _r((900, 30), (25, 30), out, left=875)
    assert front.estimate_lines(r)[1] == (
        "  When you say Pass, it also says Pass: 100% (you marked every answer it failed)")
    # 4. every answer it passed marked, all of them Pass: TNR 100%
    out = weighted.corrected(30, 900, 30, 30, 25, 5)
    assert out["tnr_interval"] == [1.0, 1.0]
    r = _r((30, 900), (30, 25), out, left=875)
    page = report_page._main_lines(r)
    assert "100% (you marked every answer it passed)" in page
    assert start_label.side_sentence("tnr", 1.0, [1.0, 1.0], report_page.why_for(r, "tnr")) == (
        "You failed: your LLM-as-a-judge also failed 100% (you marked every answer it passed).")
    # in every place a number is shown
    assert report_page.estimate(0.78, [0.78, 0.78], "you marked every answer") == (
        "78% (you marked every answer)", "–")
    every = {"tpr": 1.0, "tpr_interval": [1.0, 1.0], "tnr": 0.78, "tnr_interval": [0.78, 0.78],
             "left": 0}
    assert front.estimate_lines(every)[0] == (
        "How often your LLM-as-a-judge agrees with you:")  # no range: not "(estimates)"
    assert front.estimate_lines({**every, "tnr_interval": [0.6, 0.9], "left": 3})[0] == (
        "How often your LLM-as-a-judge agrees with you (estimates):")
    assert front.estimate_lines(every)[1:] == [
        "  When you say Pass, it also says Pass: 100% (you marked every answer)",
        "  When you say Fail, it also says Fail: 78% (you marked every answer)"]
    page = report_page._details({"kappa": 0.62, "kappa_interval": [0.62, 0.62], "left": 0})
    assert "0.62 (you marked every answer)" in page and "0.62 and 0.62" not in page
    assert targets.check(25, 25) == {"check": "result"}
    r = {"check": "result", "verdict_level": targets.level([1.0, 1.0], [0.0, 0.0])}
    assert start_label.status_line(r) == "Your result is ready."  # needs work, with no range


def _said(path: Path) -> list[str]:
    """Every string judgekeeper can print or show from one source file: its string constants
    but not its docstrings; a page or script file whole."""
    if path.suffix != ".py":
        return [path.read_text(encoding="utf-8")]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_no_output_says_exactly():
    """A number with no range says why ("you marked every answer"), never "exactly"."""
    files = [p for p in SRC.rglob("*") if p.suffix in (".py", ".html", ".js", ".css")]
    found = [f"{p.name}: {text[:60]!r}" for p in files for text in _said(p)
             if re.search(r"\bexactly\b", text, re.IGNORECASE)]
    assert not found


def test_a_range_never_shows_as_one_point():
    assert report_page.estimate(0.999, [0.997, 1.0]) == ("about 100%", "99.7% and 100.0%")
    assert report_page.estimate(0.8, [0.66, 0.93]) == ("about 80%", "66% and 93%")
