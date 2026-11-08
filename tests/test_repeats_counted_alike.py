"""Repeats that got different grades are each their own answer: Measure and check count them
the same way, so a check of the very file that was marked finds no change."""

from __future__ import annotations

import json

import pytest

from judgekeeper import judge_setup, start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data, split

AGAIN = (20, 21, 22)  # failed in the first run, passed in the second


def _quiet(line=""):
    pass


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _marked_with_repeats(root):
    """40 answers, 3 of them graded again in a second run with the other grade, every copy
    marked by a person who fails those 3 both times (so the second run's Pass disagrees)."""
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    data = promptfoo_data(split(20, 20))
    rows = data["results"]["results"]
    again = [json.loads(json.dumps(rows[i])) for i in AGAIN]
    for r in again:
        r["gradingResult"]["componentResults"][0]["pass"] = True
        r["gradingResult"]["pass"] = r["success"] = True
    data["results"]["results"] = rows + again
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")
    found = start.find_judge(root)
    ws = Workspace(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=_quiet)
    queue = ws.data()["queue"]
    assert len(queue) == 43
    session = StartSession(ws)
    for q in queue:
        mark = "fail" if "#" in q["id"] else q["group"]
        session.update({"id": q["id"], "label": mark, "seconds": 5})
    return ws


def _run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, " ".join((out + err).split())


def test_measure_on_the_file_just_marked_says_nothing_was_graded_again(here, capsys):
    _marked_with_repeats(here)
    code, out = _run(capsys)
    assert code == 0, out
    assert "graded again" not in out
    assert "disagreed on 3 of 43 answers" in out


def test_check_on_the_same_file_finds_no_change(here, capsys):
    _marked_with_repeats(here)
    _run(capsys)
    code, out = _run(capsys, "check")
    assert code == 0, out
    assert "worse" not in out.lower(), out
    assert "different grade" not in out, out
    assert "has not changed since you marked your answers" in out, out
    code, out = _run(capsys)
    assert "worse" not in out.lower() and "graded again" not in out, out


def test_a_copy_graded_again_counts_at_its_own_new_grade(here, capsys):
    """The second run graded again: its 3 copies now fail, as the person does. Each copy is
    compared with its own new grade, never with the other run's."""
    _marked_with_repeats(here)
    _run(capsys)
    data = json.loads((here / "results.json").read_text(encoding="utf-8"))
    for r in data["results"]["results"][40:]:
        r["gradingResult"]["componentResults"][0]["pass"] = False
        r["gradingResult"]["pass"] = r["success"] = False
    data["results"]["results"][40]["gradingResult"]["componentResults"][0]["reason"] = "again"
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    _, out = _run(capsys, "check")
    assert "worse" not in out.lower(), out
    assert "20 of 23" in out and "23 of 23" in out and "17 of 23" not in out, out
