"""Results that don't say who graded them: a grade that changed while the final answer stayed
word for word the same is the LLM-as-a-judge's doing only when nothing else the grade can
follow changed either. An agent run's steps (trajectory) or its outcome, or with ids the
question asked, can change under the same answer: those are changes to compare, never "Only
the grades changed". And a run where some answers changed is never "not the answers"."""

import csv
import json

import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import WORSE, _flat, _run

N = 40
FLIPS = 10  # right answers that fail now


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _verdict(i: int, flips: int) -> str:
    """Odd questions are answered right; the first `flips` right ones fail now."""
    right = i % 2 == 1
    return "fail" if not right or (i // 2) < flips else "pass"


def _records(path, *, steps: str = "A", outcome: bool = True, flips: int = 0) -> str:
    """A records file of agent runs (no evaluator: nothing says who graded them). Each run's
    final answer is the same whatever `steps` or `outcome` say."""
    with path.open("w", encoding="utf-8") as f:
        for i in range(1, N + 1):
            question, answer = f"Question {i}: what is {i} times 3?", f"It is {3 * i}."
            f.write(json.dumps({
                "schema_version": 2, "target_id": f"run-{i:02}", "name": "correct",
                "annotator_kind": "LLM", "label": _verdict(i, flips),
                "input": question, "output": answer,
                "trajectory": [{"role": "user", "content": question},
                               {"role": "assistant", "content": f"Plan {steps} for {i}."},
                               {"role": "assistant", "content": answer}],
                "outcome": {"passed": outcome if (i // 2) < flips else True},
            }) + "\n")
    return path.name


def _table(path, *, asked: str = "", flips: int = 0, changed: int = 0, regraded: int = 0) -> str:
    """id,input,output,verdict. `asked` is added to every question. `changed` right answers get
    new text and keep their Pass; the next `regraded` right ones keep their text and fail."""
    rows, right = [], 0
    for i in range(1, N + 1):
        output, verdict = f"It is {3 * i}.", _verdict(i, flips)
        if i % 2 == 1 and verdict == "pass":
            if right < changed:
                output += " Shown in full."
            elif right < changed + regraded:
                verdict = "fail"
            right += 1
        rows.append([f"q-{i:02}", f"Question {i}: what is {i} times 3?{asked}", output, verdict])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "verdict"])
        w.writerows(rows)
    return path.name


def _compared(here, monkeypatch, capsys, before: bool, write) -> tuple[int, str]:
    """`write(path, changed)` writes the results before (changed=False) and after. A plain run
    reads the first, then the second; or, with `before`, --before compares the two files."""
    monkeypatch.chdir(here)
    monkeypatch.setenv("CI", "true")
    name = write(here / "now", False)
    if before:
        old = write(here / "old", False)
        name = write(here / "now", True)
        return _said(capsys, name, "--before", old)
    assert _said(capsys, name)[0] == 0
    write(here / "now", True)
    return _said(capsys, name)


def _hidden(out: str) -> bool:
    return before_after.ONLY_GRADES in out or before_after.ONLY_GRADES_BEFORE in out


def _broke(code: int, out: str, n: int = N) -> None:
    assert code == 1, out
    assert not _hidden(out), out
    assert f"On the {n} questions in both results: fixed 0, broke {FLIPS}," in out, out
    assert WORSE in out, out


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
def test_other_steps_under_the_same_answer_are_an_agent_change(tmp_path, monkeypatch, capsys,
                                                               before):
    """Every run's steps changed, its final answer did not, and 10 runs fail now."""
    def write(stem, changed):
        path = stem.with_suffix(".jsonl")
        return (_records(path, steps="B", flips=FLIPS) if changed else _records(path))

    _broke(*_compared(tmp_path, monkeypatch, capsys, before, write))


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
def test_another_outcome_under_the_same_answer_is_an_agent_change(tmp_path, monkeypatch, capsys,
                                                                  before):
    """The same steps and final answers; 10 runs' outcomes turn to failed, and they fail now."""
    def write(stem, changed):
        path = stem.with_suffix(".jsonl")
        return (_records(path, outcome=False, flips=FLIPS) if changed else _records(path))

    _broke(*_compared(tmp_path, monkeypatch, capsys, before, write))


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
def test_a_new_question_under_the_same_id_and_answer_is_compared(tmp_path, monkeypatch, capsys,
                                                                 before):
    """With ids, every question asks something more (a new prompt written into each one), the
    answers stay the same, and 10 of them fail now."""
    def write(stem, changed):
        path = stem.with_suffix(".csv")
        return (_table(path, asked=" Answer in words.", flips=FLIPS) if changed
                else _table(path))

    _broke(*_compared(tmp_path, monkeypatch, capsys, before, write))


@pytest.mark.parametrize("before", [False, True], ids=["plain", "before"])
def test_changed_answers_with_the_same_grades_are_not_only_grades(tmp_path, monkeypatch,
                                                                  capsys, before):
    """10 answers changed and kept their Pass; 12 others kept their text and fail now. Some
    answers did change, so it never says that only the grades did."""
    def write(stem, changed):
        path = stem.with_suffix(".csv")
        return _table(path, changed=10, regraded=12) if changed else _table(path)

    _, out = _compared(tmp_path, monkeypatch, capsys, before, write)
    assert not _hidden(out), out
    assert WORSE not in out, out
