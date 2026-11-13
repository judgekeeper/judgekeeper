"""A fix/split-answers.json that can't be used, with no LLM-as-a-judge: never a false "removed"
line and never failed-answers.md lost. One that is damaged starts again, as a set used up by 3
changes does: every answer marked is shown, and new questions make the next set kept aside.
A link is never written through: the run refuses it, and the file of failed answers stays."""

from __future__ import annotations

import json
import os
from html import unescape

import pytest

from judgekeeper import no_grades
from tests import test_fix_your_ai
from tests.test_fix_your_ai import LEAD, _failed, _split, _split_file, _ws
from tests.test_front import flat, run

here, marked = test_fix_your_ai.here, test_fix_your_ai.marked  # the fixtures

MARKS = ["pass"] * 6 + ["fail"] * 4
REMOVED = "No answer you marked Fail is listed now"
AGAIN = (".judgekeeper/fix/split-answers.json was damaged ({why}), so judgekeeper started it "
         "again, and the questions kept aside before no longer give a fair test.")


def _fails_listed(here) -> int:
    return _failed(here).read_text(encoding="utf-8").count("] You said FAIL.")


def _cut(here, size: int = 50) -> None:
    path = _split_file(here)
    path.write_bytes(path.read_bytes()[:size])


def test_a_damaged_split_starts_again_and_lists_every_answer_failed(here, capsys, marked):
    marked(MARKS)
    kept = len(_split(here).hidden)
    assert kept and _fails_listed(here) < 4  # some Fails kept aside
    _cut(here)
    code, out, err = run(capsys, "--no-browser")
    said = flat(out)
    assert code == 0, out + err
    assert REMOVED not in said, said
    assert AGAIN.format(why="it can't be read as JSON") in said, said
    assert no_grades.ALL_SHOWN in said and LEAD in out, said
    assert _fails_listed(here) == 4  # the old set is gone: every Fail listed
    split = _split(here)  # a file judgekeeper can use again
    assert split.hidden == [] and split.fresh and split.fresh["want"] > 0
    page = " ".join(unescape((_ws(here).report_html).read_text(encoding="utf-8")).split())
    assert AGAIN.format(why="it can't be read as JSON") in page, page
    code, out, _ = run(capsys, "--no-browser")  # said while the new set waits, as after 3
    assert AGAIN.format(why="it can't be read as JSON") in flat(out)
    _, out, _ = run(capsys, "fix")
    assert "can't use" not in flat(out) and LEAD in out


def test_a_split_changed_by_hand_starts_again(here, capsys, marked):
    marked(MARKS)
    path = _split_file(here)
    d = json.loads(path.read_text(encoding="utf-8"))
    d["hidden"], d["visible"] = d["visible"], d["hidden"]  # changed by hand
    path.write_text(json.dumps(d), encoding="utf-8")
    _, out, _ = run(capsys, "fix")  # before any run: said, nothing written
    assert ("judgekeeper can't use .judgekeeper/fix/split-answers.json: it was changed by "
            "hand. The next result starts it again, with every answer you marked shown."
            in flat(out)), out
    assert json.loads(path.read_text(encoding="utf-8"))["hidden"] == d["hidden"]
    _, out, _ = run(capsys, "--no-browser")
    assert AGAIN.format(why="it was changed by hand") in flat(out), out
    assert _split(here).hidden == [] and _fails_listed(here) == 4


def test_a_split_that_is_a_link_is_refused_and_keeps_the_failed_answers(here, capsys,
                                                                        marked):
    marked(MARKS)
    listed = _failed(here).read_text(encoding="utf-8")
    path = _split_file(here)
    real = path.with_name("elsewhere.json")
    os.replace(path, real)
    try:
        path.symlink_to(real.name)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    code, out, err = run(capsys, "--no-browser")
    said = flat(out + err)
    assert code == 2 and "split-answers.json is a link to another file." in said, said
    assert REMOVED not in said, said
    assert _failed(here).read_text(encoding="utf-8") == listed  # never lost
    assert path.is_symlink() and real.read_text(encoding="utf-8")  # never written through
