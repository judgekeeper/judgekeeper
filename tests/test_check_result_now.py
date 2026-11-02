"""When `check` takes on the new LLM-as-a-judge and the overall result changes, it says so in one
line after its result; a result now too early to tell asks for more marks, not "nothing to do"."""

from __future__ import annotations

import json

import pytest

from judgekeeper import judge_setup, start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer, split
from tests.test_check import HAIKU, TAG, _quiet, _results, run
from tests.test_front import assert_one_next_at_the_end


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _checked(root, capsys, size: int, marked: int, against: int, changed: int) -> str:
    """`size` answers of each kind, the first `marked` in the queue marked, `against` of the
    ones the LLM-as-a-judge passed marked Fail; then a new judge that passes `changed` more of
    the answers marked Fail, and `check`."""
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _results(root, split(size, size))
    found = start.find_judge(root)
    judge_setup.save(Workspace(root), judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    rows = {json.loads(x)["id"]: json.loads(x)
            for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    said, flipped = {}, 0
    for q in ws.data()["queue"][:marked]:
        mark = q["group"]
        if mark == "pass" and flipped < against:
            mark, flipped = "fail", flipped + 1
        said[rows[q["id"]]["output"]] = mark
        session.update({"id": q["id"], "label": mark, "seconds": 5})
    main(["--no-browser", "--port", "0"])
    main(["--stop"])
    verdicts = split(size, size)
    for i, v in enumerate(verdicts):
        if changed and not v and said.get(answer(i, TAG)) == "fail":
            verdicts[i], changed = True, changed - 1
    _results(root, verdicts, model=HAIKU)
    capsys.readouterr()
    code, out = run(capsys)
    assert code == 0, out
    return out


def _level(root) -> str:
    return json.loads(Workspace(root).result_json.read_text(encoding="utf-8"))["verdict_level"]


def test_a_result_that_changes_is_said_after_the_check(here, capsys):
    out = _checked(here, capsys, size=30, marked=60, against=7, changed=1)
    assert _level(here) == "not_gate"
    assert "Result: no drop bigger than 20" in out, out
    assert "Your result is now: your LLM-as-a-judge needs work.\n" in out, out
    assert assert_one_next_at_the_end(out).startswith("Next: nothing to do."), out


def test_a_result_now_too_early_to_tell_asks_for_more_marks(here, capsys):
    out = _checked(here, capsys, size=100, marked=60, against=1, changed=1)
    assert _level(here) == "check"
    assert "Your result is now: too early to tell.\n" in out, out
    assert assert_one_next_at_the_end(out) == (
        "Next: the result after this change is too early to tell. Mark more answers with "
        "`judgekeeper mark`.")


def test_a_result_that_stays_the_same_is_not_said_again(here, capsys):
    out = _checked(here, capsys, size=30, marked=60, against=4, changed=1)
    assert _level(here) == "gate"
    assert "Your result is now" not in out, out
    assert assert_one_next_at_the_end(out).startswith("Next: nothing to do."), out


def test_the_caveat_on_marks_used_to_write_the_rule_is_said_once(here, capsys):
    """A rule written from the marks with `fix` and taken on by `check` changes the result:
    the line that it may read a few points high comes once, not again after "Your result is
    now"."""
    from judgekeeper import check
    from tests.test_earlier_grades import FIRST, N, _mark, person
    from tests.test_fix import closed
    from tests.test_flow_across_runs import _jk, _rubric

    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(here, [i < 30 for i in range(N)], "V1 rule.")
    _jk(capsys, "--no-browser")
    ws = Workspace(here)
    closed(ws)
    _mark(ws, FIRST)
    _jk(capsys, "--no-browser", "--port", "0")
    closed(ws)
    _jk(capsys, "fix")
    _rubric(here, [person(i) for i in range(N)], "V2 rule.", name="v2.json", only=FIRST)
    _jk(capsys, "fix", "v2.json")
    code, out = _jk(capsys, "check", "v2.json")
    said = " ".join(out.split())
    assert code == 0 and "Your result is now: your LLM-as-a-judge is good enough to use." in said
    assert said.count(check.WRITTEN_FROM) == 1, out


def test_a_result_that_changes_is_said_when_no_result_was_saved(here, capsys):
    """Marked on the page only, so no result was saved: `check` works out the result before
    the change from the marks, and says the new one when it differs."""
    from tests.test_earlier_grades import FIRST, N, _mark, person
    from tests.test_fix import closed
    from tests.test_flow_across_runs import _jk, _rubric

    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(here, [i < 30 for i in range(N)], "V1 rule.")
    _jk(capsys, "--no-browser")
    ws = Workspace(here)
    closed(ws)
    _mark(ws, FIRST)
    assert not ws.result_json.is_file()
    _jk(capsys, "fix")
    _rubric(here, [person(i) for i in range(N)], "V2 rule.", name="v2.json", only=FIRST)
    _jk(capsys, "fix", "v2.json")
    code, out = _jk(capsys, "check", "v2.json")
    said = " ".join(out.split())
    assert code == 0, out
    assert "Your result is now: your LLM-as-a-judge is good enough to use." in said, out
