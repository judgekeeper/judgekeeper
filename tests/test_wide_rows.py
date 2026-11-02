"""A CSV row with more cells than its header: a stray quote closed by a later quote makes one
row of two, and the second row's answer and label would be lost without a word. judgekeeper
stops and names the line. Empty cells past the header (a spreadsheet's trailing commas) are
fine."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import table
from tests.start_projects import answer, question, table_project
from tests.test_freecheck_odd_files import NODE, browser
from tests.test_labels_import import flat, run

STRAY = "this note opens a quote and never closes it"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _labels(path, n: int = 8, stray_at: int | None = 4, trailing: str = ""):
    """A labels file: answer, label and notes, every cell quoted. Row `stray_at` opens a
    quote in its note that the next row's first quote closes."""
    lines = ["answer,label,notes"]
    for i in range(n):
        note = f'"{STRAY}' if i == stray_at else f'"note {i}"'
        lines.append(f'"{answer(i)}",{"Pass" if i % 2 else "Fail"},{note}{trailing}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_wide_row_names_the_line_the_row_starts_on(here):
    path = _labels(here / "labels.csv")
    with path.open(encoding="utf-8", newline="") as f:
        widths = [len(r) for r in csv.reader(f)]
    assert max(widths) > 3  # Python's csv reads one row of two, as the person's file has it
    assert table.wide_row(path) == 6  # the header is line 1; row 4 is line 6


@pytest.mark.parametrize("trailing", [",", ",,", ", ,"])
def test_empty_cells_past_the_header_are_fine(here, trailing):
    assert table.wide_row(_labels(here / "labels.csv", stray_at=None, trailing=trailing)) is None


def test_a_file_with_no_stray_quote_has_no_wide_row(here):
    assert table.wide_row(_labels(here / "labels.csv", stray_at=None)) is None


def test_labels_with_a_wide_row_stop_and_name_the_line(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    _labels(here / "labels.csv")
    code, out = run(capsys, "--labels", "labels.csv")
    assert code == 3, out
    assert ("labels.csv has more cells than its header (line 6): a quote may be closed in the "
            "wrong place. Fix it, then run `judgekeeper` again.") in flat(out), out
    assert not (here / ".judgekeeper" / "marks.jsonl").exists()


@pytest.mark.parametrize("stray", ["wide", "open"])
def test_the_labels_stop_names_the_program_as_typed(here, capsys, monkeypatch, stray):
    """Run by a path, the stop line says to run that path again, as every other line does."""
    from judgekeeper import textio

    table_project(here, [True] * 20 + [False] * 20)
    path = _labels(here / "labels.csv", stray_at=7 if stray == "open" else 4)
    if stray == "open":  # the last row's quote never closes
        path.write_text(path.read_text(encoding="utf-8").rstrip('"\n') + "\n", encoding="utf-8")
    monkeypatch.setattr(textio, "_typed", "venv/bin/judgekeeper")
    code, out = run(capsys, "--labels", "labels.csv")
    assert code == 3, out
    assert "Fix it, then run `venv/bin/judgekeeper` again." in flat(out), out
    assert "run judgekeeper again" not in flat(out)


def test_labels_with_trailing_empty_cells_import(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    _labels(here / "labels.csv", stray_at=None, trailing=",,")
    code, out = run(capsys, "--labels", "labels.csv")
    assert code == 0, out
    assert "more cells than its header" not in out
    assert "Added 8 marks from labels.csv" in flat(out), out


def _results(here, stray: bool = True):
    lines = ["input,output,verdict,reason"]
    for i in range(40):
        reason = f'"{STRAY}' if stray and i == 10 else f'"reason {i}"'
        lines.append(f'"{question(i)}","{answer(i)}",{"pass" if i % 2 else "fail"},{reason}')
    path = here / "results.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_results_with_a_wide_row_stop_and_name_the_line(here, capsys):
    _results(here)
    code, out = run(capsys)
    assert code == 2, out
    text = flat(out)
    assert ("results.csv has more cells than its header (line 12): a quote may be closed in "
            "the wrong place.") in text, out
    assert "Next: fix line 12 of results.csv, then run `judgekeeper" in text, out


@pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")
def test_the_free_check_names_the_same_line(here):
    result = browser(_results(here))
    assert result["ok"] is False
    assert result["message"] == ("Line 12 of this file has more cells than its header: a quote "
                                 "may be closed in the wrong place.")
    assert browser(_results(here, stray=False))["ok"] is True


def test_a_file_of_its_own_format_with_a_wide_row_stops_and_names_the_line(here, capsys):
    lines = ["question,response,judge_passed,notes"]
    for i in range(40):
        note = f'"{STRAY}' if i == 10 else f'"note {i}"'
        lines.append(f'"{question(i)}","{answer(i)}",{"true" if i % 2 else "false"},{note}')
    (here / "eval_out.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, out = run(capsys)
    text = flat(out)
    assert code == 2, out
    assert ("Line 12 of eval_out.csv has more cells than its header: a quote may be closed in "
            "the wrong place.") in text, out
    assert "Next: fix line 12 of eval_out.csv, then run `judgekeeper" in text, out
