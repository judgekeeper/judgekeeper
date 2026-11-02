"""Labels files: numbers that equal 1 or 0, two columns for the same thing, and the flags a
start-over question keeps."""

from __future__ import annotations

import json

import pytest

from judgekeeper.start_label import Workspace
from tests.start_projects import answer
from tests.test_labels_import import by_output, flat, here, run, table, write_labels

__all__ = ["here"]  # the fixture, used by name


# A number that equals 1 or 0 -------------------------------------------------------------------

@pytest.mark.parametrize("one,zero", [("1.0", "0.0"), ("1.00", "-0.0"), (" 1.0 ", "0.0")])
def test_a_csv_label_that_equals_1_or_0_reads_as_1_or_0(here, capsys, one, zero):
    table(here)
    write_labels(here / "mine.csv", [{"answer": answer(i), "label": one if i < 20 else zero}
                                     for i in range(40)])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 0, out
    assert "Added 40 marks from mine.csv (20 Pass, 20 Fail)" in flat(out), out
    marks = by_output(Workspace(here))
    assert marks[answer(0)] == "pass" and marks[answer(39)] == "fail"


def test_a_jsonl_label_that_equals_1_or_0_reads_as_1_or_0(here, capsys):
    table(here)
    (here / "mine.jsonl").write_text("".join(
        json.dumps({"output": answer(i), "label": 1.0 if i < 20 else 0.0}) + "\n"
        for i in range(40)), encoding="utf-8")
    code, out = run(capsys, "--labels", "mine.jsonl")
    assert code == 0, out
    assert "Added 40 marks from mine.jsonl (20 Pass, 20 Fail)" in flat(out), out


@pytest.mark.parametrize("value", ["0.7", "2.0", "2"])
def test_other_numbers_are_still_refused(here, capsys, value):
    table(here)
    write_labels(here / "mine.csv", [{"answer": answer(0), "label": value},
                                     {"answer": answer(1), "label": "1.0"}])
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3 and "Labels must be Pass or Fail, not numbers." in flat(out), out


# Two columns for the same thing ---------------------------------------------------------------

@pytest.mark.parametrize("columns,kind,pair", [
    (["output", "label", "Label", "OUTPUT"], "label", "label and Label"),
    (["output", "OUTPUT", "label"], "answer", "output and OUTPUT"),
    (["answer", "output", "label"], "answer", "answer and output"),
    (["output", "label", "human_label"], "label", "label and human_label"),
    (["input", "Question", "output", "label"], "question", "input and Question"),
    (["id", " ID ", "output", "label"], "id", "id and ID"),
])
def test_two_columns_for_the_same_thing_stop_before_anything_is_written(here, capsys, columns,
                                                                       kind, pair):
    from tests.test_labels_import import _nothing_written

    table(here)
    rows = [{c: (answer(i) if c.strip().lower() in ("output", "answer")
                 else "pass" if c.strip().lower() in ("label", "human_label")
                 else f"Question {i}?" if c.strip().lower() in ("input", "question")
                 else str(i)) for c in columns} for i in range(3)]
    write_labels(here / "mine.csv", rows, columns)
    code, out = run(capsys, "--labels", "mine.csv")
    assert code == 3, out
    text = flat(out)
    assert f"mine.csv has two {kind} columns ({pair}). Keep one, then run: " in text, text
    command = text[text.index("Keep one, then run: ") + len("Keep one, then run: "):]
    assert "--labels mine.csv" in command, command
    _nothing_written(Workspace(here))
