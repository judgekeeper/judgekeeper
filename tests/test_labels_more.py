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
    assert code == 3 and "Labels must be Pass or Fail, or 1 and 0, not other numbers." in flat(out), out
    assert "Next: say what each one means, then run" in flat(out), out
    assert '--labels mine.csv --label-map "WORD=pass,WORD=fail"' in flat(out), out


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
    assert f"mine.csv has two {kind} columns ({pair}). Keep one, then run `" in text, text
    command = text[text.index("Keep one, then run `") + len("Keep one, then run `"):]
    assert "--labels mine.csv" in command, command
    _nothing_written(Workspace(here))


@pytest.mark.parametrize("header,kind,pair", [
    ("output,label,label", "label", "label and label"),
    ("output,output,label", "answer", "output and output"),
    ("question,output,question,label", "question", "question and question"),
    ("id,output,label,id", "id", "id and id"),
])
@pytest.mark.parametrize("suffix", [".csv", ".tsv"])
def test_the_same_column_name_twice_stops_too(here, capsys, header, kind, pair, suffix):
    """The same name twice is never read as its last column."""
    from tests.test_labels_import import _nothing_written

    table(here)
    names = header.split(",")
    cells = {"output": answer(0), "label": "pass", "question": "Question 0?", "id": "0"}
    sep = "\t" if suffix == ".tsv" else ","
    row = [cells[c] if names.index(c) == k else ("fail" if c == "label" else cells[c])
           for k, c in enumerate(names)]
    (here / f"mine{suffix}").write_text(sep.join(names) + "\n" + sep.join(row) + "\n",
                                        encoding="utf-8")
    code, out = run(capsys, "--labels", f"mine{suffix}")
    assert code == 3, out
    text = flat(out)
    assert f"mine{suffix} has two {kind} columns ({pair}). Keep one, then run `" in text, text
    _nothing_written(Workspace(here))


# Starting over with --labels -------------------------------------------------------------------

@pytest.mark.parametrize("given", ["new labels.csv", "in results"])
def test_the_start_over_question_keeps_the_labels_flag(here, capsys, given):
    import shlex

    from judgekeeper.cli import main
    from tests.test_front import next_lines
    from tests.test_labels_import import labelled

    table(here, extra={"human_label": ["pass"] * 20 + ["fail"] * 20})
    write_labels(here / "old.csv", labelled(range(40)))
    assert main(["--labels", "old.csv", "--no-browser", "--port", "0"]) == 0
    capsys.readouterr()
    write_labels(here / "new labels.csv", labelled(range(20, 40)))
    flags = ["--labels", "new labels.csv"] if given != "in results" else ["--labels"]
    code = main(["--new", *flags, "--no-browser", "--port", "9522"])
    out = capsys.readouterr().out
    assert code == 3, out
    (nxt,) = next_lines(out)
    again, yes = nxt.split("`")[1::2]
    for command in (again, yes):
        words = shlex.split(command)[1:]
        assert words[words.index("--labels"):][:len(flags)] == flags, command
        assert "--new" in words and "--no-browser" in words and "9522" in words, command
    assert yes.endswith("--yes")
    code = main(shlex.split(yes)[1:])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Added " in out, out


# The import gate looks at the batches the result is on -----------------------------------------

def _labelled_table(root, n: int) -> None:
    """A table of `n` answers, each with a person's label: the judge is wrong on every third
    one it passed."""
    from tests.start_projects import table_project

    verdicts = [i % 2 == 0 for i in range(n)]
    humans = ["fail" if v and i % 3 == 0 else "pass" if v else "fail"
              for i, v in enumerate(verdicts)]
    table_project(root, verdicts, extra={"human_label": humans})


def test_new_answers_never_bring_back_the_import_gate(here, capsys):
    from judgekeeper.cli import main

    _labelled_table(here, 300)
    assert main(["--labels", "--no-browser", "--port", "0"]) == 0
    out = flat(capsys.readouterr().out)
    assert "Added 300 marks from your results" in out and "needs work" in out, out
    _labelled_table(here, 350)
    code = main(["--no-browser", "--port", "0"])
    out = flat(capsys.readouterr().out)
    assert code == 0, out
    assert "needs work" in out, out
    assert "on 1 of 2 batches" in out, out
    assert "Mark at least" not in out, out
    assert "too early" not in out.lower(), out
