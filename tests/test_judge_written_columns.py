"""What the LLM-as-a-judge writes beside its grade (its explanation, critique, confidence, a
score of its own) and what is the same on every row of a file (a run number, the day it was
graded) say nothing of the answers: a pure re-grade with those changed is "Only the grades
changed", never "broke 10". The rest a row holds, such as its context, still counts."""

import csv
import json

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import _flat, _run

N = 40
FLIPS = [i for i in range(N) if i % 4 and i < 14]  # 10 passing answers fail when re-graded


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _value(column: str, take: int, i: int) -> str:
    return {"judged_on": f"2026-11-2{6 + take}", "run": str(take), "Run": str(take)}.get(
        column, f"the judge's words, take {take}, on {i}")


def _table(here, columns: list[str], take: int, context_changed: bool = False) -> None:
    """id,input,output,verdict and `columns`; take 2 re-grades: FLIPS fail. A `context`
    column holds each row's own documents, new on the FLIPS rows with `context_changed`."""
    with (here / "results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "verdict", *columns])
        for i in range(N):
            verdict = "fail" if i % 4 == 0 or (take == 2 and i in FLIPS) else "pass"
            cells = [(f"Documents for {i}." + (" Moved." if context_changed and i in FLIPS
                                               else "")) if c == "context"
                     else _value(c, take, i) for c in columns]
            w.writerow([f"q-{i:02}", f"Question {i}?", f"Answer {i}.", verdict, *cells])


def _regraded(here, monkeypatch, capsys, columns, context_changed=False) -> tuple[int, str]:
    monkeypatch.chdir(here)
    monkeypatch.setenv("CI", "true")
    _table(here, columns, 1)
    assert _said(capsys)[0] == 0
    _table(here, columns, 2, context_changed)
    return _said(capsys)


@pytest.mark.parametrize("column", [
    "explanation", "rationale", "reasoning", "critique", "feedback", "comments", "notes",
    "confidence", "gpt4_score", "grader_notes", "Judge Notes", "eval-comment", "judged_on",
    "run"])
def test_a_column_the_judge_writes_or_one_per_run_is_not_the_answer(tmp_path, monkeypatch,
                                                                    capsys, column):
    code, out = _regraded(tmp_path, monkeypatch, capsys, [column])
    assert code == 0 and before_after.ONLY_GRADES in out, out


def test_a_context_changed_on_the_rows_that_flip_is_compared(tmp_path, monkeypatch, capsys):
    code, out = _regraded(tmp_path, monkeypatch, capsys, ["context"], context_changed=True)
    assert code == 1 and "fixed 0, broke 10," in out, out


def test_a_run_column_beside_a_changed_context_is_compared(tmp_path, monkeypatch, capsys):
    code, out = _regraded(tmp_path, monkeypatch, capsys, ["Run", "context"],
                          context_changed=True)
    assert code == 1 and "fixed 0, broke 10," in out, out


def _records(path, take: int) -> None:
    """Records with what the judge said and the run in `metadata`."""
    with path.open("w", encoding="utf-8") as f:
        for i in range(N):
            verdict = "fail" if i % 4 == 0 or (take == 2 and i in FLIPS) else "pass"
            f.write(json.dumps({
                "schema_version": 2, "target_id": f"run-{i:02}", "name": "correct",
                "annotator_kind": "LLM", "label": verdict, "input": f"Question {i}?",
                "output": f"Answer {i}.",
                "metadata": {"critique": f"take {take} on {i}", "run_number": take,
                             "Grader-Confidence": 0.5 + take / 10},
            }) + "\n")


def test_what_the_judge_wrote_in_records_metadata_is_not_the_answer(tmp_path, monkeypatch,
                                                                   capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _records(tmp_path / "records.jsonl", 1)
    assert _said(capsys, "records.jsonl")[0] == 0
    _records(tmp_path / "records.jsonl", 2)
    code, out = _said(capsys, "records.jsonl")
    assert code == 0 and before_after.ONLY_GRADES in out, out


@pytest.mark.parametrize("name", ["x-request-id", "openai-processing-ms", "created",
                                  "system_fingerprint", "systemFingerprint", "Request Id"])
def test_a_field_an_api_call_gives_each_row_is_not_the_answer(tmp_path, monkeypatch, capsys,
                                                             name):
    """Spelled with "-" or spaces too: an API call's own id, time or fingerprint, new on every
    row and every run."""
    def write(take: int) -> None:
        with (tmp_path / "records.jsonl").open("w", encoding="utf-8") as f:
            for i in range(N):
                verdict = "fail" if i % 4 == 0 or (take == 2 and i in FLIPS) else "pass"
                f.write(json.dumps({
                    "schema_version": 2, "target_id": f"run-{i:02}", "name": "correct",
                    "annotator_kind": "LLM", "label": verdict, "input": f"Question {i}?",
                    "output": f"Answer {i}.", "metadata": {name: f"{take}-{i}-{take * i}"},
                }) + "\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    write(1)
    assert _said(capsys, "records.jsonl")[0] == 0
    write(2)
    code, out = _said(capsys, "records.jsonl")
    assert code == 0 and before_after.ONLY_GRADES in out, out
