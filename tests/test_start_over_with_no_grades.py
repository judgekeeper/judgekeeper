"""`--new` on answers with no grades, as on the LLM-as-a-judge path: with marks and no terminal
it asks first (exit 3) and moves nothing; with --yes the marks move to previous-<date>/ and
marking starts over."""

from __future__ import annotations

import pytest

from judgekeeper import front, marks, start_label
from tests.test_answers_without_grades import mark, write_answers
from tests.test_front import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _marked(here, capsys):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 8 + ["fail"] * 4)
    run(capsys, "--no-browser")
    return start_label.Workspace(here)


def test_new_with_no_terminal_asks_first_and_moves_nothing(here, capsys, pages):
    ws = _marked(here, capsys)
    code, out, err = run(capsys, "--new", "--no-browser")
    said = flat(out)
    assert code == 3, out + err
    assert front.START_OVER in said and "--new --yes" in said
    assert not list(ws.dir.glob("previous-*")) and ws.marks.is_file()


def test_new_with_yes_moves_the_marks_and_starts_over(here, capsys, pages):
    ws = _marked(here, capsys)
    code, out, err = run(capsys, "--new", "--yes", "--no-browser")
    assert code == 0, out + err
    moved = list(ws.dir.glob("previous-*"))
    assert len(moved) == 1 and (moved[0] / "marks.jsonl").is_file()
    assert not ws.marks.is_file() or not marks.read(ws.marks).counted()
    assert "Step 2 of 5: Mark" in flat(out)
    code, out, err = run(capsys, "--no-browser")  # the next run goes on: nothing to move
    assert code == 0 and len(list(ws.dir.glob("previous-*"))) == 1, out + err
