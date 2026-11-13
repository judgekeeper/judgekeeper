"""Answers saved under other column names (question and answer, say) and no grades: judgekeeper
names the columns and says to rename them input and output, never to add grades or to turn a
CSV into a CSV. A file that is graded under other names is switched by its own grade column.
--tool table says its results file in words that read."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper import front, own_map
from judgekeeper.cli import main
from tests.test_front import flat, next_lines, run

RENAME = ("rename the question column in res.csv to input and the answer column to output, "
          "then run `judgekeeper {args}`")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(path, columns: list[str], grades: bool = False) -> None:
    rows = [[f"What is {i} plus {i}?", f"It is {2 * i}."] + (["pass" if i % 3 else "fail"]
                                                            if grades else [])
            for i in range(12)]
    if path.suffix == ".jsonl":
        path.write_text("".join(json.dumps(dict(zip(columns, r, strict=True))) + "\n"
                                for r in rows), encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)


def test_a_plain_run_names_the_file_and_says_to_rename_its_columns(here, capsys):
    _write(here / "res.csv", ["question", "answer"])
    code, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert code == 3, out
    assert ("It left out res.csv (columns question and answer): to check the answers in it, "
            "rename the question column to input and the answer column to output.") in said, said
    assert front.QUESTIONS_INTRO not in said, said  # it has answers
    assert next_lines(out) == [f"Next: {RENAME.format(args='--no-browser')} again."], out


def test_a_plain_run_with_no_such_file_still_offers_the_prompt(here, capsys):
    (here / "prices.csv").write_text("item,price\napple,1\n", encoding="utf-8")
    code, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert code == 3 and front.QUESTIONS_INTRO in said, said
    assert "It left out" not in said, said


def test_a_named_file_says_its_columns_and_what_to_rename(here, capsys):
    _write(here / "res.csv", ["question", "answer"])
    code, out, _ = run(capsys, "res.csv", "--no-browser")
    said = flat(out)
    assert code == 3, out
    assert ("res.csv has the columns question and answer, and no LLM-as-a-judge grades. "
            + own_map.ANSWER_COLUMNS) in said, said
    assert "Turn it into a CSV" not in said and "verdict (pass or fail)" not in said, said
    assert next_lines(out) == [f"Next: {RENAME.format(args='res.csv --no-browser')}."], out


def test_a_named_file_with_an_input_column_says_only_the_answer_column(here, capsys):
    _write(here / "res.csv", ["input", "reply"])
    _, out, _ = run(capsys, "res.csv", "--no-browser")
    step = "rename the answer column in res.csv to output, then run `judgekeeper res.csv"
    assert next_lines(out) == [f"Next: {step} --no-browser`."], out


def test_a_named_jsonl_file_is_never_turned_into_a_csv(here, capsys):
    _write(here / "res.jsonl", ["question", "answer"])
    _, out, _ = run(capsys, "res.jsonl", "--no-browser")
    said = flat(out)
    assert "res.jsonl has the columns question and answer" in said, said
    assert "CSV" not in said.split("Next:")[1], said


def test_the_switch_line_names_the_grade_column(here, capsys):
    _write(here / "res.csv", ["prompt", "reply", "grade"], grades=True)
    _, out, _ = run(capsys, "res.csv", "--no-browser", "--port", "0")
    main(["--stop"])
    said = flat(out)
    assert ("To check your AI's answers instead, use a copy of the file without the grade "
            "column.") in said, said
    assert "verdict column" not in said, said


def test_tool_table_found_nowhere_names_the_results_file(here, capsys):
    code = main(["--tool", "table", "--no-browser"])
    out = capsys.readouterr()
    said = " ".join((out.out + out.err).split())
    assert code == 2 and "No CSV, TSV or JSONL results file found" in said, said
    assert said.endswith("Next: run `judgekeeper --tool table --no-browser` in the folder that "
                         "holds your CSV, TSV or JSONL results file."), said
    assert "your a CSV" not in said, said


def test_no_line_puts_a_table_after_a_or_your():
    """A table's results by name ("a CSV, TSV or JSONL file") never follows "your" or "a"."""
    from pathlib import Path

    from judgekeeper import check, start

    assert start.results_of("table") == "CSV, TSV or JSONL results file"
    assert start.results_of("promptfoo") == "promptfoo results"
    assert check._new_results("table") == "your new results file"
    assert check._new_results("deepeval") == "your new DeepEval results"
    said = str(start.unreadable(Path("res.csv"), "table"))
    assert "from your eval tool" in said and "from a CSV" not in said, said
