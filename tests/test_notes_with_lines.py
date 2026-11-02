"""A CSV that Python's csv module reads cleanly is never refused as "a quote that never
closes" because a notes cell holds lines with as many commas as a row; a real stray quote
still is."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import table
from tests.start_projects import answer, question, table_project
from tests.test_labels_import import flat, run

NOTES = ("Reviewed twice.\nChecked tone, units, rounding, spelling.\nAsked Bo, Ana, Chen, Dee."
         "\nOk.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _labels(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question", "answer", "label", "notes"])
        w.writerows(rows)
    return path


def test_notes_over_lines_with_commas_import(here, capsys):
    table_project(here, [True] * 20 + [False] * 20)
    _labels(here / "labels.csv", [[question(1), answer(1), "Pass", NOTES],
                                   [question(2), answer(2), "Fail", "fine"]])
    assert table.open_quote(here / "labels.csv") is None
    _, out = run(capsys, "--labels", "labels.csv")
    assert "never closes" not in out
    assert "Added 2 marks from labels.csv (1 Pass, 1 Fail)." in flat(out), out


def test_a_results_file_with_such_notes_is_read(here):
    path = table_project(here, [True] * 20 + [False] * 20,
                         extra={"notes": [NOTES] + ["ok"] * 39})
    assert table.open_quote(path) is None


def test_a_label_quote_closed_rows_later_is_still_found(here):
    rows = [[question(i), answer(i), "pass", "ok"] for i in range(10)]
    path = _labels(here / "labels.csv", rows)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[3] = f'{question(2)},{answer(2)},"pass,ok'  # its label swallows the rows to line 6
    lines[6] = f'{question(5)},{answer(5)},pass,ok"'
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert table.open_quote(path) == 4


def test_a_table_with_no_grade_column_is_not_guessed(here):
    path = here / "notes.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["a", "b", "c", "d"], ["1", "2", "3", NOTES]])
    assert table.open_quote(path) is None
