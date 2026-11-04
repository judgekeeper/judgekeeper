"""After `check` switches to a rule tested on the kept-aside marks, the marks made next form a
new set. `fix` reads the split.json it wrote for them, also when one of those answers was
skipped before the switch, and `fix --new` always starts a new set."""

from __future__ import annotations

import json
import re

from judgekeeper import fix
from judgekeeper.start_label import StartSession, Workspace
from tests.test_earlier_grades import FIRST, LATER, N, _mark, person
from tests.test_fix import closed
from tests.test_flow_across_runs import _jk, _rubric


def _skip(ws: Workspace, i: int) -> None:
    session = StartSession(ws)
    for item in session.items:
        if int(re.search(r"Question (\d+)\?",
                         json.dumps(session.raw[item["id"]]["input"]))[1]) == i:
            session.update({"id": item["id"], "deferred": True, "seconds": 2})


def _undo(ws: Workspace, i: int) -> None:
    """Answer `i` marked, then the mark taken back (a null mark): left unmarked."""
    _mark(ws, [i])
    session = StartSession(ws)
    for item in session.items:
        if int(re.search(r"Question (\d+)\?",
                         json.dumps(session.raw[item["id"]]["input"]))[1]) == i:
            session.update({"id": item["id"], "label": None, "seconds": 2})


def _switched(tmp_path, capsys, skipped: int | None, undone: int | None = None) -> Workspace:
    """`skipped` skipped (or `undone` marked and taken back), FIRST marked, a rule tested on
    them and switched to by `check`, then 13 of LATER marked, that one too."""
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                  encoding="utf-8")
    _rubric(tmp_path, [i < 30 for i in range(N)], "V1 rule.")
    assert _jk(capsys, "--no-browser")[0] == 0
    ws = Workspace(tmp_path)
    closed(ws)
    if skipped is not None:  # skipped before any of the marks the first set holds
        _skip(ws, skipped)
    if undone is not None:  # marked and taken back before them
        _undo(ws, undone)
    _mark(ws, FIRST)
    assert _jk(capsys, "fix")[0] == 0
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="v2.json", only=FIRST)
    assert _jk(capsys, "fix", "v2.json")[0] == 0
    assert _jk(capsys, "check", "v2.json")[0] == 0
    _mark(ws, LATER[:13])  # a new set of 13, under a third of the marks
    return ws


def test_fix_reads_the_new_set_when_an_answer_in_it_was_skipped_before(tmp_path, monkeypatch,
                                                                       capsys):
    monkeypatch.chdir(tmp_path)
    ws = _switched(tmp_path, capsys, skipped=LATER[0])
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    assert lines[0]["mark"] == "skip", lines[:3]  # its first line, before the first set's marks
    code, out = _jk(capsys, "fix")
    assert code == 0, out
    assert "can't use" not in out, out
    split = fix.read_split(ws)
    assert split.set == 2 and len(split.hidden) == 13, split


def test_fix_reads_the_new_set_when_an_answer_in_it_was_marked_and_taken_back_before(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ws = _switched(tmp_path, capsys, skipped=None, undone=LATER[0])
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    assert lines[0]["mark"] in ("pass", "fail") and lines[1]["mark"] is None, lines[:3]
    code, out = _jk(capsys, "fix")
    assert code == 0, out
    split = fix.read_split(ws)
    assert split.set == 2 and len(split.hidden) == 13, split
    code, out = _jk(capsys, "fix")  # the split.json it wrote is read again
    assert code == 0 and "can't use" not in out, out


def test_fix_new_starts_a_new_set_even_from_a_split_it_cannot_use(tmp_path, monkeypatch,
                                                                    capsys):
    monkeypatch.chdir(tmp_path)
    ws = _switched(tmp_path, capsys, skipped=None)
    path = ws.dir / "fix" / "split.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    d["seed"] += 1  # changed by hand
    path.write_text(json.dumps(d), encoding="utf-8")
    code, out = _jk(capsys, "fix")
    assert code == 2 and "can't use" in out, out
    code, out = _jk(capsys, "fix", "--new")  # 7 answers left: fewer than a new set needs
    assert code == 3 and "can't use" not in out and "Only 7 answers are left" in out, out
    split = fix.read_split(ws)
    assert split.hidden == [] and len(split.seen) == len(FIRST) + 13, split


def test_fix_reads_the_new_set_when_a_mark_kept_aside_in_it_is_taken_back(tmp_path,
                                                                          monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ws = _switched(tmp_path, capsys, skipped=None)
    assert _jk(capsys, "fix")[0] == 0
    split = fix.read_split(ws)
    assert split.set == 2 and split.hidden, split
    taken = split.hidden[-1]
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    mark = [x for x in lines if x.get("id") == taken][-1]["mark"]
    StartSession(ws).update({"id": taken, "label": None, "seconds": 2})  # taken back
    code, out = _jk(capsys, "fix")
    assert code == 0 and "can't use" not in out, out
    StartSession(ws).update({"id": taken, "label": mark, "seconds": 2})  # marked again
    code, out = _jk(capsys, "fix")
    assert code == 0 and "can't use" not in out, out
    assert fix.read_split(ws).set == 2


def test_fix_reads_the_new_set_when_every_mark_kept_aside_in_it_is_taken_back(tmp_path,
                                                                              monkeypatch,
                                                                              capsys):
    monkeypatch.chdir(tmp_path)
    ws = _switched(tmp_path, capsys, skipped=None)
    assert _jk(capsys, "fix")[0] == 0
    split = fix.read_split(ws)
    assert split.set == 2 and split.hidden, split
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    was = {x["id"]: x["mark"] for x in lines if x.get("id") in split.hidden}
    for taken in split.hidden:
        StartSession(ws).update({"id": taken, "label": None, "seconds": 2})  # taken back
    code, out = _jk(capsys, "fix")
    assert code == 0 and "can't use" not in out, out
    assert fix.read_split(ws).set == 2
    for taken, mark in was.items():
        StartSession(ws).update({"id": taken, "label": mark, "seconds": 2})  # marked again
    code, out = _jk(capsys, "fix")
    assert code == 0 and "can't use" not in out, out
    again = fix.read_split(ws)
    assert again.set == 2 and again.hidden, again
