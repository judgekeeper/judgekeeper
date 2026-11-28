"""No judge_model column. `check new-results.csv` took on another LLM-as-a-judge's grades;
results.csv, graded by the one the marks were made on, is read again. Only the marked answers
whose text is unchanged say which LLM-as-a-judge graded them: when each has the grade it was
marked on, and one at least differs from the grades taken on, it is "back to the one you
marked with". It was not seen as back: new answers waited and check said worse."""

import csv

import pytest

from tests.test_compare_after_check import (
    BACK_TO,
    WORSE,
    _checked,
    _flat,
    _run,
    _ten_new_answers,
    _write,
)

ADDED_10 = "Your newest results have 10 answers you haven't seen. They're added for marking."


def _said(capsys, *argv) -> tuple[int, str]:
    code, out = _run(capsys, *argv, "--no-browser", "--port", "0")
    _run(capsys, "--stop")
    return code, _flat(out)


def _rows(path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _taken_on_elsewhere(here) -> list[str]:
    """The answers results.csv grades otherwise than new-results.csv (taken on)."""
    new = {r["output"]: r["verdict"] for r in _rows(here / "new-results.csv")}
    return [r["output"] for r in _rows(here / "results.csv") if new.get(r["output"]) != r["verdict"]]


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_back_to_results_csv_is_back_and_its_new_answers_are_added(tmp_path, monkeypatch,
                                                                   capsys, ids):
    _checked(tmp_path, monkeypatch, capsys, ids, named=True)
    code, out = _said(capsys, "results.csv")
    assert code == 0 and BACK_TO in out and WORSE not in out, out
    _ten_new_answers(tmp_path / "results.csv", ids, None)
    monkeypatch.setenv("CI", "true")
    code, out = _said(capsys, "results.csv")
    assert code == 1, out  # a real change: 10 answers changed and fail
    assert ADDED_10 in out and "You have marks on all" not in out, out
    assert "questions in both results: fixed 0, broke 10," in out, out


@pytest.mark.parametrize("ids", [False, True], ids=["by-text", "by-id"])
def test_check_of_results_csv_after_a_take_on_says_back(tmp_path, monkeypatch, capsys, ids):
    _checked(tmp_path, monkeypatch, capsys, ids, named=True)
    code, out = _run(capsys, "check", "results.csv")
    assert code == 0 and BACK_TO in _flat(out), out
    assert "Worse" not in out, out


def test_grades_that_match_both_judges_say_nothing_new(tmp_path, monkeypatch, capsys):
    """Every answer the two LLM-as-a-judges grade otherwise changed its text: the marked
    answers left grade the same under both, so nothing says which one graded them."""
    _checked(tmp_path, monkeypatch, capsys, True, named=True)
    otherwise = set(_taken_on_elsewhere(tmp_path))
    assert otherwise
    rows = _rows(tmp_path / "results.csv")
    for r in rows:
        if r["output"] in otherwise:
            r["output"] += " Or not."
    _write(tmp_path / "results.csv", rows, True)
    _, out = _said(capsys, "results.csv")
    assert BACK_TO not in out, out


def test_a_mix_of_the_two_judges_grades_is_not_back(tmp_path, monkeypatch, capsys):
    """One answer graded as the LLM-as-a-judge taken on grades it, the others as the marks were
    made on: neither one's grades, so not back."""
    _checked(tmp_path, monkeypatch, capsys, True, named=True)
    otherwise = _taken_on_elsewhere(tmp_path)
    assert len(otherwise) >= 2
    new = {r["output"]: r["verdict"] for r in _rows(tmp_path / "new-results.csv")}
    rows = _rows(tmp_path / "results.csv")
    for r in rows:
        if r["output"] == otherwise[0]:
            r["verdict"] = new[r["output"]]
    _write(tmp_path / "results.csv", rows, True)
    _, out = _said(capsys, "results.csv")
    assert BACK_TO not in out, out
