"""The result page and failed-answers.md show an answer the way the marking page does: a blank
one (or only spaces) as "(empty answer)", and `**bold**` and "- " lists rendered. On the live
page a cell's text stays the answer's own, so words marked in it keep their place."""

from __future__ import annotations

import csv
import re
from html import unescape

import pytest

from judgekeeper import no_grades, start_label
from tests.test_answers_without_grades import _live, _session
from tests.test_front import run

RICH = "Call us:\n- **Phone:** extension 4400\n- **Email:** help desk"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _with_fails(here, capsys, outs: dict[int, str]) -> start_label.StartSession:
    """20 answers, the ones in `outs` with that text; every one of them failed, so some are
    shown on the result."""
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output"])
        for i in range(20):
            w.writerow([f"What is question {i}?", outs.get(i, f"Answer {i}.")])
    run(capsys, "--no-browser")
    page = _session(here)
    for item in page.items:
        out = page.raw[item["id"]]["output"]
        bad = out in outs.values() or out == "" or out.startswith(("Bad", "   "))
        page.update({"id": item["id"], "label": "fail" if bad else "pass", "seconds": 3})
    run(capsys, "--no-browser")
    return page


def _cells(html: str) -> list[str]:
    return re.findall(r'<td data-label="Answer"[^>]*>(.*?)</td>', html, flags=re.DOTALL)


def test_a_blank_answer_reads_empty_answer(here, capsys, pages):
    outs = {i: "" for i in range(6)} | {i: "   " for i in range(6, 12)}
    _with_fails(here, capsys, outs)
    ws = start_label.Workspace(here)
    for html in (_live(here), ws.report_html.read_text(encoding="utf-8")):
        cells = _cells(html)
        assert cells and all("(empty answer)" in c for c in cells), cells
    text = no_grades.failed_path(ws).read_text(encoding="utf-8")
    assert "(empty answer)" in text


def test_markdown_is_rendered_and_the_live_cell_keeps_the_answer_text(here, capsys, pages):
    outs = {i: RICH.replace("4400", f"44{i:02d}") for i in range(12)}
    _with_fails(here, capsys, outs)
    ws = start_label.Workspace(here)
    for html in (_live(here), ws.report_html.read_text(encoding="utf-8")):
        cells = _cells(html)
        assert cells and all("<strong>" in c and "<li>" in c and "**" not in re.sub(
            r"<span hidden>.*?</span>", "", c) for c in cells), cells
    for cell in _cells(_live(here)):
        text = unescape(re.sub(r"<[^>]+>", "", cell))  # what the page's script counts in
        assert text in outs.values(), text
