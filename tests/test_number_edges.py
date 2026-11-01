"""The numbers' edge cases: a rate of exactly 0.90 in floating point, a judge that passes (or
fails) every answer, a range narrower than one point, and a group of the judge with nothing
counted when it is asked again."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from judgekeeper import front, report_page, start_label, targets

SRC = Path(__file__).parents[1] / "src" / "judgekeeper"


def test_a_range_ending_exactly_on_the_bar_reaches_it():
    low = 0.4 * 2  # 0.8, worked out as 0.8000000000000002 one way, 0.7999999999999999 another
    end = 0.7 + 0.1
    assert end < 0.8 and round(end, 9) == 0.8
    assert targets.side([end, 0.95]) == "yes"  # green, not amber
    assert targets.side([low, 0.95]) == "yes"
    assert targets.side([0.7999, 0.95]) == "cant_tell"


def test_a_number_with_no_range_says_why_and_never_exactly():
    """Every answer marked: "78% (you marked every answer)". A judge that passes (or fails)
    every answer, with answers still unmarked: "100% (with no range)". Never "exactly"."""
    assert report_page.estimate(1.0, [1.0, 1.0]) == ("100% (with no range)", "–")
    assert report_page.estimate(0.0, [0.0, 0.0]) == ("0% (with no range)", "–")
    assert report_page.estimate(0.78, [0.78, 0.78], every=True) == (
        "78% (you marked every answer)", "–")
    assert start_label.side_sentence("tnr", 0.78, [0.78, 0.78], every=True) == (
        "You failed: your LLM-as-a-judge also failed 78% (you marked every answer).")
    assert start_label.side_sentence("tpr", 1.0, [1.0, 1.0]) == (
        "You passed: your LLM-as-a-judge also passed 100% (with no range).")
    assert front.estimate_lines({"tpr": 1.0, "tpr_interval": [1.0, 1.0], "tnr": 0.78,
                                 "tnr_interval": [0.78, 0.78], "left": 0})[1:] == [
        "  When you say Pass, it also says Pass: 100% (you marked every answer)",
        "  When you say Fail, it also says Fail: 78% (you marked every answer)"]
    page = report_page._details({"kappa": 0.62, "kappa_interval": [0.62, 0.62], "left": 0})
    assert "0.62 (you marked every answer)" in page and "0.62 and 0.62" not in page
    page = report_page._main_lines({"tpr": 0.78, "tpr_interval": [0.78, 0.78], "tnr": 0.5,
                                    "tnr_interval": [0.5, 0.5], "left": 0})
    assert "78% (you marked every answer)" in page and "exact" not in page.lower()
    check = targets.check(25, 25, [1.0, 1.0], [0.0, 0.0])
    assert check == {"check": "rough", "wide": {}}  # never "reliable" from no width at all
    r = {"check": "rough", "wide": {}, "tpr_interval": [1.0, 1.0], "tnr_interval": [0.0, 0.0]}
    assert start_label.status_line(r) == "You can see your result now."


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
