"""The LLM-as-a-judge's model, read from a results file of your own: one rule for a CSV and a
JSONL file. A field named for the model (model, judge_model) is read when each value is a
name; a value that is a grade, a number, a rule's name or a sentence is not, and then Find
says why and never lists the field as read."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from judgekeeper import mapper
from judgekeeper.cli import main
from tests.start_projects import answer, question


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def a_csv(root: Path, model: str, column: str = "model", n: int = 40) -> None:
    with (root / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict", column])
        for i in range(n):
            w.writerow([question(i), answer(i), "pass" if i % 2 else "fail", model])


def a_jsonl(root: Path, model: str, key: str = "judge_model", n: int = 40) -> None:
    with (root / "eval_out.jsonl").open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"question": question(i), "response": answer(i),
                                "judge_passed": bool(i % 2), key: model}) + "\n")


def judge_line(out: str) -> str:
    return next(x for x in out.splitlines() if x.startswith("LLM-as-a-judge:"))


def read_block(out: str) -> str:
    return out.split("judgekeeper has read from your file:\n", 1)[1].split("\n\n", 1)[0]


NAMES = ["acme", "judge-model-x", "my-grader-v2", "gpt-4o", "ollama/qwen2.5:3b",
         "claude-sonnet-5@20260101", "Acme_Grader"]
NOT_NAMES = ["string_match", "checks+judge", "pass", "0.5", "exact_match", "a long sentence"]


@pytest.mark.parametrize("value", NAMES)
def test_a_csv_model_column_that_names_a_model_is_the_judge_model(here, capsys, value):
    a_csv(here, value)
    code, out = run(capsys)
    assert code == 0, out
    assert judge_line(out) == f"LLM-as-a-judge:  {value}"
    assert "model not found" not in out
    assert "the model column" in read_block(out)


@pytest.mark.parametrize("value", NAMES)
def test_a_jsonl_judge_model_field_that_names_a_model_is_the_judge_model(here, capsys, value):
    a_jsonl(here, value)
    code, out = run(capsys, "--yes")
    assert code == 0, out
    assert f"  model:           judge_model ({value})\n" in out
    assert judge_line(out) == f"LLM-as-a-judge:  {value}"
    assert "model not found" not in out and "not in the file" not in out
    assert "judge_model" in read_block(out)


@pytest.mark.parametrize("value", NOT_NAMES)
def test_a_csv_model_column_of_no_names_is_said_and_not_listed_as_read(here, capsys, value):
    a_csv(here, value)
    code, out = run(capsys)
    assert code == 0, out
    assert "model not found in your results" in judge_line(out)
    assert value not in judge_line(out)
    assert out.count("The model column holds no model's name.") == 1
    assert out.index("The model column holds no model's name.") > out.index("LLM-as-a-judge:")
    assert "model" not in read_block(out)


@pytest.mark.parametrize("value", NOT_NAMES)
def test_a_jsonl_judge_model_field_of_no_names_is_said_and_not_listed_as_read(here, capsys,
                                                                             value):
    a_jsonl(here, value)
    code, out = run(capsys, "--yes")
    assert code == 0, out
    assert ("  model:           judge_model holds no model's name (add --judge-model NAME)\n"
            in out)
    assert "model not found in your results" in judge_line(out)
    assert "judge_model" not in read_block(out)


@pytest.mark.parametrize("value", NAMES + NOT_NAMES)
def test_csv_and_jsonl_take_the_same_values_as_a_model(value):
    """One rule for both readers: a CSV's model column and a JSONL's judge_model field take
    the same values."""
    rows = [{"question": "q", "response": "a", "judge_passed": True, "judge_model": value}]
    from_jsonl = mapper.guess(rows).model == value
    assert mapper.names_models([value]) == from_jsonl


def test_a_grader_key_still_needs_a_model_like_value():
    """judge.grader can hold a setting ("strict"); only a key named for the model takes any
    name."""
    units = [{"judge": {"name": "helpfulness", "grader": "strict"},
              "items": [{"question": "q", "answer": "a", "passed": True}]}]
    g = mapper.guess(units)
    assert g.model_key is None and g.model_refused is None
    units[0]["judge"] = {"name": "helpfulness", "model": "strict"}
    assert (mapper.guess(units).model_key, mapper.guess(units).model) == ("judge.model",
                                                                          "strict")


def test_a_csv_judge_model_column_is_read_before_a_model_column(here, capsys):
    """judge_model names the LLM-as-a-judge's model; a model column next to it may be the
    app's. Find reads the one it lists."""
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict", "model", "judge_model"])
        for i in range(40):
            w.writerow([question(i), answer(i), "pass" if i % 2 else "fail", "app-bot-1",
                        "acme-grader"])
    code, out = run(capsys)
    assert code == 0, out
    assert judge_line(out) == "LLM-as-a-judge:  acme-grader"
    assert "the judge_model column" in read_block(out)
