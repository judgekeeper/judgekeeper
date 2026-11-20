"""A CSV that Python's csv module wrote is never refused as "a quote that never closes"
because an answer holds lines with amounts such as `$50,000`; a real open quote still is."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import mapper, table

MONEY = ("Plan A\nLoans: 4 years x $50,000 = $200,000\nHousing: 3 years x $12,000 = $36,000"
         "\nTotal: 4 x $50,000 + $36,000 = $236,000")


@pytest.fixture
def here(tmp_path):
    return tmp_path


def _write(path, header, rows, delimiter=","):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=delimiter)
        w.writerow(header)
        w.writerows(rows)
    return path


def test_money_lines_with_a_verdict_column_are_read(here):
    path = _write(here / "results.csv", ["input", "output", "verdict"],
                  [["q1", "fine", "pass"], ["q2", MONEY, "fail"], ["q3", "ok", "pass"]])
    assert table.open_quote(path) is None
    assert len(mapper.load_numbered(path)) == 3


def test_money_lines_with_a_score_column_are_read(here):
    path = _write(here / "results.csv", ["input", "output", "score"],
                  [["q1", "fine", "1"], ["q2", MONEY, "0"], ["q3", "ok", "1"]])
    assert table.open_quote(path) is None
    assert len(mapper.load_numbered(path)) == 3


def test_money_lines_in_a_labels_file_are_read(here):
    path = _write(here / "labels.csv", ["question", "answer", "label"],
                  [["q1", MONEY, "Pass"], ["q2", "ok", "Fail"]])
    assert table.open_quote(path) is None


def test_a_real_open_quote_over_graded_rows_is_still_found(here):
    rows = [[f"q{i}", f"answer {i}", "pass"] for i in range(10)]
    path = _write(here / "results.csv", ["input", "output", "verdict"], rows)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[3] = 'q2,"answer 2,pass'  # its quote swallows the rows that follow
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert table.open_quote(path) == 4
    with pytest.raises(mapper.MapError, match="line 4 of results.csv has a quote that never "
                                              "closes, so the rows after it can't be read"):
        mapper.load_numbered(path)


def test_money_lines_in_a_tsv_file_are_read(here):
    path = _write(here / "results.tsv", ["input", "output", "verdict"],
                  [["q1", MONEY, "pass"], ["q2", MONEY, "fail"]], delimiter="\t")
    assert table.open_quote(path) is None
    assert len(mapper.load_numbered(path)) == 2


def test_a_bare_number_is_not_a_grade_where_the_rows_hold_grade_words(here):
    # three values per line, the last one a number: a row only if numbers were grades
    note = "Plan\nitem, cost, 50\nitem, cost, 60\nitem, cost, 70"
    path = _write(here / "results.csv", ["input", "output", "verdict"],
                  [["q1", "fine", "pass"], ["q2", note, "fail"], ["q3", "ok", "pass"]])
    assert table.open_quote(path) is None
