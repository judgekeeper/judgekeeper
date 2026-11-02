"""Lines a first-time user meets: each says only what is true for their project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import background
from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.test_regrade_files import COLUMNS, _row, _write

PAGE = ("--no-browser", "--port", "0", "--yes")


def _run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


@pytest.fixture
def evals(tmp_path, monkeypatch):
    """A project with pyproject.toml and its results in evals/results.csv."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (tmp_path / "evals").mkdir()
    _write(tmp_path / "evals" / "results.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    background.stop(tmp_path / ".judgekeeper")


# Naming the same results file again: nothing was graded again -------------------------------

def test_the_same_results_file_named_again_is_not_graded_again(evals, capsys):
    code, out = _run(capsys, *PAGE)
    assert code == 0, out
    code, out = _run(capsys, "evals/results.csv", *PAGE)
    assert code == 0, out
    assert "graded again" not in out, out


def _mark(root: Path, n: int) -> None:
    from judgekeeper.start_label import StartSession

    session = StartSession(Workspace(root))
    for item in session.items[:n]:
        session.update({"id": item["id"], "label": "pass", "seconds": 5})


def test_the_same_file_named_again_after_marks_is_not_graded_again(evals, capsys):
    assert _run(capsys, *PAGE)[0] == 0
    _mark(evals, 5)
    for named in ("evals/results.csv", str(evals / "evals" / "results.csv")):
        code, out = _run(capsys, named, *PAGE)
        assert code == 0 and "graded again" not in out, (named, out)


def test_new_grades_before_any_mark_are_not_graded_again(evals, capsys):
    assert _run(capsys, *PAGE)[0] == 0
    _write(evals / "evals" / "results.csv", [_row(i, 3) for i in range(60)], COLUMNS)
    code, out = _run(capsys, *PAGE)
    assert code == 0 and "graded again" not in out, out


# check on a file with only some of the marked answers ----------------------------------------

@pytest.fixture
def marked(tmp_path, monkeypatch):
    """200 answers in results.csv, every one marked."""
    from tests.test_regrade_files import project

    monkeypatch.chdir(tmp_path)
    project(tmp_path, n=200)
    return tmp_path


def test_check_on_some_of_the_marked_answers_says_to_grade_every_one_again(marked, capsys):
    _write(marked / "partial.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    code, out = _run(capsys, "check", "partial.csv")
    assert code == 0, out
    assert "140 of your 200 marked answers had no grade" in out, out
    nxt = out[out.rindex("Next: "):]
    assert "mark the new answers" not in nxt, nxt
    assert "grade every answer in .judgekeeper/fix/marked-answers.csv again" in nxt, nxt
    assert "`judgekeeper check <new results file>`" in nxt, nxt


def test_check_on_some_marked_answers_and_new_ones_says_to_mark_the_new_ones(marked, capsys):
    _write(marked / "partial.csv", [_row(i, 5) for i in (*range(60), *range(200, 220))],
           COLUMNS)
    code, out = _run(capsys, "check", "partial.csv")
    nxt = out[out.rindex("Next: "):]
    assert code == 0 and "mark the new answers" in nxt, nxt


# A folder that is only dots is said in words before a full stop ---------------------------

@pytest.mark.parametrize("shown, said", [
    (".", "this folder"), ("..", "the folder above"), ("../..", "2 folders above"),
    ("../../..", "3 folders above"), ("../evals", "../evals"), ("evals", "evals")])
def test_a_folder_of_dots_is_said_in_words(shown, said):
    from judgekeeper import textio

    assert textio.folder_words(shown) == said


def test_no_results_of_a_tool_here_names_this_folder(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "results.csv", [_row(i, 5) for i in range(60)], COLUMNS)
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys, "--tool", "promptfoo", *PAGE)
    assert code != 0 and "No saved promptfoo results found in this folder." in out, out
    assert "found in .." not in out


# Starting over with no marks: nothing of yours moved, and Find is said once ---------------

def _scored(path: Path, n: int = 50) -> None:
    rows = [{"input": f"Question {i}?", "output": f"Answer {i}.", "verdict":
             "pass" if i % 2 else "fail", "score": f"{(i % 10) / 10:.1f}"} for i in range(n)]
    _write(path, rows, ("input", "output", "verdict", "score"))


def test_a_new_pass_mark_before_any_mark_moves_nothing_of_yours(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    _scored(proj / "results.csv")
    monkeypatch.chdir(proj)
    assert _run(capsys, *PAGE)[0] == 0
    code, out = _run(capsys, "--pass-if", "score>=0.5", *PAGE)
    background.stop(proj / ".judgekeeper")
    assert code == 0, out
    assert "Moved" not in out and out.count("Step 1 of 5: Find") == 1, out
    assert list((proj / ".judgekeeper").glob("previous-*"))  # still moved aside


def test_an_import_that_starts_over_says_find_once(tmp_path, monkeypatch, capsys):
    from tests.test_labels_import import write_labels

    proj = tmp_path / "proj"
    proj.mkdir()
    _scored(proj / "results.csv")
    write_labels(tmp_path / "mine.csv", [{"answer": f"Answer {i}.", "label": "pass"}
                                         for i in range(10)])
    monkeypatch.chdir(proj)
    assert _run(capsys, "--pass-if", "score>=0.5", *PAGE)[0] == 0
    monkeypatch.chdir(tmp_path)
    code, out = _run(capsys, "proj", "--labels", "mine.csv", *PAGE)
    background.stop(proj / ".judgekeeper")
    assert code == 0 and out.count("Step 1 of 5: Find") == 1 and "Moved" not in out, out


# fix --new never asks for more marks than there are answers left ---------------------------

def _marked_but(root: Path, n: int, left: int) -> None:
    """`n` answers in results.csv, all but `left` marked as the person sees them."""
    from judgekeeper.start_label import StartSession

    _write(root / "results.csv", [_row(i, 5) for i in range(n)], COLUMNS)
    assert main(["--no-browser", "--port", "0", "--yes"]) == 0
    ws = Workspace(root)
    background.stop(ws.dir)
    pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
    session = StartSession(ws)
    for item in session.items[:n - left]:
        bad = "BAD" in pool[item["id"]]["output"]
        session.update({"id": item["id"], "label": "fail" if bad else "pass", "seconds": 5})


def test_fix_new_with_few_answers_left_asks_for_no_more_than_are_left(tmp_path, monkeypatch,
                                                                      capsys):
    monkeypatch.chdir(tmp_path)
    _marked_but(tmp_path, 50, 6)
    capsys.readouterr()
    code, out = _run(capsys, "fix", "--new")
    assert code == 3 and "Mark about 40" not in out, out
    assert "Only 6 answers are left to mark. Mark them, or add more answers to your results." \
        in out, out
    assert "(at least 10 more)" not in out, out


# check with none of the marked answers in the new file: the Next line alone says it -------

def test_check_with_none_of_the_marked_answers_says_grade_them_once(marked, capsys):
    rows = [_row(i, 5) | {"output": f"Another answer {i}."} for i in range(200)]
    _write(marked / "other.csv", rows, COLUMNS)
    code, out = _run(capsys, "check", "other.csv")
    assert "None of your 200 marked answers is in your new results." in out, out
    assert "Grade the answers you marked instead:" not in out, out
    assert "Your eval wrote new answers, so there's nothing to compare." in out, out
    assert out[out.rindex("Next: "):].startswith(
        "Next: grade every answer in .judgekeeper/fix/marked-answers.csv again") or \
        out[out.rindex("Next: "):].startswith(
            "Next: grade the answers in .judgekeeper/fix/marked-answers.csv again"), out
    assert code != 0


# How many marks fix keeps aside: as the reference says ------------------------------------

def test_fix_keeps_aside_half_of_each_group_by_grade_and_mark(tmp_path, monkeypatch, capsys):
    """60 marks: the LLM-as-a-judge passed 30 and failed 30; you agree on 17 and 15. Half of
    each of the 4 groups, rounded up: 9 + 7 + 8 + 8 = 32 (half of each grade alone: 30)."""
    import math

    from judgekeeper.start_label import StartSession

    cells = {("pass", "pass"): 17, ("pass", "fail"): 13, ("fail", "fail"): 15,
             ("fail", "pass"): 15}  # (its grade, your mark): how many
    rows, mine = [], {}
    for (judge, person), n in cells.items():
        for _ in range(n):
            i = len(rows)
            rows.append({"input": f"Question {i}?", "output": f"Answer {i}: {person}.",
                         "verdict": judge})
            mine[f"Answer {i}: {person}."] = person
    _write(tmp_path / "results.csv", rows, ("input", "output", "verdict"))
    monkeypatch.chdir(tmp_path)
    assert main(["--no-browser", "--port", "0", "--yes"]) == 0
    ws = Workspace(tmp_path)
    background.stop(ws.dir)
    pool = {r["id"]: r for r in map(json.loads, ws.pool.read_text(encoding="utf-8").splitlines())}
    session = StartSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "label": mine[pool[item["id"]]["output"]],
                        "seconds": 5})
    capsys.readouterr()
    code, out = _run(capsys, "fix")
    assert code == 0, out
    split = json.loads((ws.dir / "fix" / "split.json").read_text(encoding="utf-8"))
    want = sum(math.ceil(n / 2) for n in cells.values())
    assert want == 32 and len(split["hidden"]) == want
    assert f"The other {want} are kept aside" in out, out
    reference = " ".join((Path(__file__).parent.parent / "docs" / "reference.md").read_text(
        encoding="utf-8").split())
    assert ("**Marks kept aside:** half of each group, by your LLM-as-a-judge's grade and your "
            "mark, rounded up") in reference


def test_fix_new_with_many_answers_left_asks_for_about_40(tmp_path, monkeypatch, capsys):
    from judgekeeper import fix

    monkeypatch.chdir(tmp_path)
    _marked_but(tmp_path, 100, 50)
    capsys.readouterr()
    code, out = _run(capsys, "fix", "--new")
    assert code == 3 and " ".join(fix.CLEAR_LINE.split()) in out, out
    assert "(at least 10 more)" in out and "left to mark" not in out, out
