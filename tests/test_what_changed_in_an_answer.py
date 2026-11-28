"""Results that don't say who graded them: a question counts as fixed or broke only when its
answers changed (test_grades_only_changed.py). An answer is all the agent gave and was asked:
its text, its steps (trajectory), its outcome, and the whole question. A change in any of them
is a change of the agent's, compared as usual; "only the grades changed" is said only when
every answer is the same."""

import json

import pytest

from judgekeeper import before_after
from judgekeeper.cli import main
from tests.test_compare_after_check import _flat

N = 40
BROKE_10 = "On the 40 questions in both results: fixed 0, broke 10, same 30."


def _said(capsys, *argv) -> tuple[int, str]:
    code = main([*argv, "--no-browser", "--port", "0"])
    main(["--stop"])
    return code, _flat(capsys.readouterr().out)


def _steps(i: int, middle: str) -> list[dict]:
    return [{"role": "user", "content": f"Question {i}?"},
            {"role": "assistant", "content": middle},
            {"role": "assistant", "content": f"Answer {i}."}]


def _records(here, verdicts, middle: str = "Looked it up.", outcome=True) -> None:
    """A records file (schema 2) whose evaluator names nothing: each answer with its steps."""
    folder = here / ".judgekeeper" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "Safe-wording-2026-10-05-4101.jsonl").open("w", encoding="utf-8") as f:
        for i, v in enumerate(verdicts):
            f.write(json.dumps({
                "schema_version": 2, "target_id": None, "name": "Safe wording",
                "annotator_kind": "LLM", "label": "pass" if v else "fail", "score": None,
                "explanation": f"reason {i}", "run": None, "input": f"Question {i}?",
                "output": f"Answer {i}.", "trajectory": _steps(i, middle), "outcome": {"passed": outcome},
                "evaluator": {}, "created_at": "2026-10-05T10:00:00Z"}) + "\n")


def _inspect(here, verdicts, middle: str = "Looked it up.") -> None:
    """An Inspect AI log that names no grader model and no instructions: each sample with its
    messages (its trajectory)."""
    from tests.start_projects import _write_json, inspect_data

    data = inspect_data(verdicts)
    data["eval"].pop("model_roles", None)
    for scorer in data["eval"]["scorers"]:
        scorer["options"] = {}
    for i, s in enumerate(data["samples"]):
        s["messages"] = _steps(i, middle)
    _write_json(here / "logs" / "support.json", data)


CHANGES = {  # the same input and output each time, 10 right answers now wrong
    "steps": lambda here, v: _records(here, v, middle="Guessed."),
    "outcome": lambda here, v: _records(here, v, outcome=False),
}


@pytest.mark.parametrize("change", CHANGES)
def test_an_agent_change_in_its_steps_or_outcome_is_compared(tmp_path, monkeypatch, capsys,
                                                             change):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _records(tmp_path, [True] * N)
    _said(capsys)
    CHANGES[change](tmp_path, [False] * 10 + [True] * 30)
    code, out = _said(capsys)
    assert code == 1, out
    assert BROKE_10 in out and before_after.ONLY_GRADES not in out, out


def test_an_inspect_log_with_changed_steps_is_compared(tmp_path, monkeypatch, capsys):
    """A guard: an Inspect AI log always says which prompt graded it (the scorer's template
    and instructions, or Inspect's defaults), so its setups decide, with or without a model."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _inspect(tmp_path, [True] * N)
    _said(capsys)
    _inspect(tmp_path, [False] * 10 + [True] * 30, middle="Guessed.")
    code, out = _said(capsys)
    assert code == 1 and BROKE_10 in out, out


def test_the_same_steps_graded_otherwise_are_only_grades(tmp_path, monkeypatch, capsys):
    """A guard: the same answers, steps and outcome, graded otherwise."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _records(tmp_path, [True] * N)
    _said(capsys)
    _records(tmp_path, [False] * 10 + [True] * 30)
    code, out = _said(capsys)
    assert code == 0 and before_after.ONLY_GRADES in out, out


def _table(path, prompt: str, verdicts, outputs=None) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output", "verdict"])
        for i, v in enumerate(verdicts):
            w.writerow([f"q-{i:02}", f"{prompt} Question {i}?",
                        outputs[i] if outputs else f"Answer {i}.", "pass" if v else "fail"])


def test_a_changed_prompt_under_the_same_ids_is_a_change(tmp_path, monkeypatch, capsys):
    """The prompt inside each question changed, the ids and answers did not: the agent was
    asked something else, so its grades are compared."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "before.csv", "Prompt v1.", [True] * N)
    _table(tmp_path / "results.csv", "Prompt v2.", [False] * 10 + [True] * 30)
    code, out = _said(capsys, "results.csv", "--before", "before.csv")
    assert code == 1, out
    assert BROKE_10 in out and before_after.ONLY_GRADES_BEFORE not in out, out


def test_some_answers_changed_and_others_graded_otherwise_are_compared(tmp_path, monkeypatch,
                                                                      capsys):
    """10 answers changed and kept their grade, 12 others stayed the same and were graded
    otherwise: not only the grades changed. The changed ones are compared, the 12 left out."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _table(tmp_path / "before.csv", "Ask.", [True] * N)
    outputs = [f"Answer {i}." + (" In short." if i >= 30 else "") for i in range(N)]
    _table(tmp_path / "results.csv", "Ask.", [False] * 12 + [True] * 28, outputs)
    code, out = _said(capsys, "results.csv", "--before", "before.csv")
    assert before_after.ONLY_GRADES_BEFORE not in out and code == 0, out
    assert "On the 28 questions in both results: fixed 0, broke 0, same 28." in out, out
