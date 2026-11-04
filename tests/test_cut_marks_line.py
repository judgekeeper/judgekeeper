"""A marks.jsonl whose last line was cut (a full disk, a power cut during a write): the next
mark starts on a line of its own, and the cut line is said once."""

from __future__ import annotations

import json

import pytest

from judgekeeper import marks, start, start_label
from judgekeeper.start_label import StartSession
from tests.start_projects import promptfoo_project, split
from tests.test_batches import _index
from tests.test_front import flat, run

UNREADABLE = "1 line in .judgekeeper/marks.jsonl could not be read. The others are used."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _mark_some(ws, count: int, start_at: int = 0) -> None:
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    todo = sorted(session.items, key=lambda x: _index(session.raw[x["id"]]["input"]))
    for item in todo[start_at:start_at + count]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 4})


def _valid(path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def test_a_cut_last_line_never_swallows_the_next_mark(here, capsys):
    promptfoo_project(here, split(20, 16))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark_some(ws, 20)
    data = ws.marks.read_bytes()
    ws.marks.write_bytes(data[:-25])
    before = len(_valid(ws.marks))
    assert len(marks.read(ws.marks).last) == 19

    _mark_some(ws, 5, start_at=20)
    lines = _valid(ws.marks)
    assert len(lines) == before + 5  # 5 new lines, each one whole
    assert ws.marks.read_bytes().endswith(b"\n")
    assert len(marks.read(ws.marks).last) == 24

    code, out, _ = run(capsys, "mark", "--no-browser")
    assert code == 0, out
    assert "You marked 24 answers so far" in flat(out)
    assert flat(out).count(UNREADABLE) == 1, out


def test_appending_to_a_file_with_no_last_newline_starts_a_new_line(tmp_path):
    path = tmp_path / ".judgekeeper" / "history.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"a": 1}\n{"b": 2')
    marks.append(path, {"c": 3})
    marks.append_all(path, [{"d": 4}, {"e": 5}])
    assert path.read_bytes().splitlines()[1:] == [b'{"b": 2', b'{"c": 3}', b'{"d": 4}',
                                                  b'{"e": 5}']


def test_appending_to_an_empty_file_adds_no_blank_line(tmp_path):
    path = tmp_path / ".judgekeeper" / "history.jsonl"
    path.parent.mkdir()
    path.write_bytes(b"")
    marks.append(path, {"c": 3})
    assert path.read_bytes() == b'{"c": 3}\n'


def test_a_whole_file_says_nothing_about_unreadable_lines(here, capsys):
    promptfoo_project(here, split(20, 16))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark_some(ws, 5)
    code, out, _ = run(capsys, "mark", "--no-browser")
    assert code == 0, out
    assert "could not be read" not in out


def test_measure_says_the_cut_line_once(here, capsys):
    promptfoo_project(here, split(20, 16))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark_some(ws, 36)
    ws.marks.write_bytes(ws.marks.read_bytes()[:-25])
    _mark_some(ws, 1, start_at=35)  # the cut answer marked again
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    assert "Step 3 of 5: Measure" in out
    assert flat(out).count(UNREADABLE) == 1, out
    assert "not made on the page" not in out
