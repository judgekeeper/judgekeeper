"""An answer that is the same in both results never counts as fixed or broke, whether or not
the results name the model that graded them: an agent change changes answers. With the same
model named and only grades changed, it says only the grades changed (the same LLM-as-a-judge
may grade otherwise); with another model named, the two setups are not compared, as before.
In a mix, the questions left out that way are said in a line of their own."""


import pytest

from judgekeeper import before_after
from tests.test_compare_after_check import WORSE, N, _flat, _lenient, _row, _run, _write


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _rows(model: str, flips: int = 0, changed: int = 0) -> list[dict]:
    """`flips` right answers graded fail now, their text the same; `changed` others get new
    text and keep their grade."""
    rows = [{**_row(i), "verdict": _lenient(i), "id": f"q-{i:02}"} for i in range(N)]
    right = [r for r in rows if r["right"]]
    for r in right[:flips]:
        r["verdict"] = "fail"
    for r in right[flips:flips + changed]:
        r["output"] += " Said another way."
    return rows


@pytest.mark.parametrize("ids", [True, False], ids=["by-id", "by-text"])
def test_the_same_model_regrading_the_same_answers_is_only_grades(tmp_path, monkeypatch,
                                                                  capsys, ids):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _write(tmp_path / "results.csv", _rows("judge-a"), ids, "judge-a")
    _write(tmp_path / "main.csv", _rows("judge-a"), ids, "judge-a")
    _said(capsys)
    _write(tmp_path / "results.csv", _rows("judge-a", flips=14), ids, "judge-a")
    code, out = _said(capsys)
    assert code == 0 and WORSE not in out, out
    assert before_after.ONLY_GRADES in out, out
    code, out = _said(capsys, "results.csv", "--before", "main.csv")
    assert code == 3 and before_after.ONLY_GRADES_BEFORE in out, out


def test_another_model_named_is_still_another_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _write(tmp_path / "main.csv", _rows("judge-a"), True, "judge-a")
    _write(tmp_path / "results.csv", _rows("judge-b", flips=14), True, "judge-b")
    code, out = _said(capsys, "results.csv", "--before", "main.csv")
    assert code == 3 and before_after.OTHER_SETUP in out, out


def test_a_mix_says_how_many_questions_were_left_out(tmp_path, monkeypatch, capsys):
    """7 answers the same and graded otherwise, 10 others changed (graded as before)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CI", "true")
    _write(tmp_path / "main.csv", _rows("judge-a"), True, "judge-a")
    _write(tmp_path / "results.csv", _rows("judge-a", flips=7, changed=10), True, "judge-a")
    code, out = _said(capsys, "results.csv", "--before", "main.csv")
    assert code == 0 and f"On the {N - 7} questions in both results: fixed 0, broke 0," in out, out
    assert ("7 questions with the same answers and other grades are left out." in out), out
