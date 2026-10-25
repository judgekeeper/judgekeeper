"""`judgekeeper fix` while a rule test waits for more marks (the top-up after "can't tell yet,
leans better") never prints an empty step: it says why it waits, then shows what a first run
shows (the clues with your reasons, mistakes.md, where the rule is, the marks kept aside).
"""

from __future__ import annotations

import json

import pytest

from judgekeeper.start_label import StartSession
from tests.test_front import assert_one_next_at_the_end
from tests.test_review_fixes import _fix, _leans_better

WAITING = ("Your last rule test is waiting for more marks: it couldn't tell yet. Run your eval "
           "on more questions and mark the new answers, and `judgekeeper fix` tests that rule "
           "again on them.")
NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
                   "answers join the ones you marked.")


@pytest.fixture
def fixing(tmp_path, monkeypatch):
    """A promptfoo project whose judge is faked (tests/test_fix.py's judge)."""
    from tests.test_fix import judge as fake_judge

    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project, fake_judge.__wrapped__(project, monkeypatch)


def _waiting_top_up(root, holder, capsys, clear: str = "empty"):
    """Every answer marked, a reason given on one mistake, a rule tested that leans toward
    better (so a top-up waits), then rule.txt emptied or removed to write a different one."""
    from judgekeeper import fix
    from tests.test_fix import _write_rule, project

    ws = project(root)  # every answer marked
    _fix(capsys)
    split, m = fix.read_split(ws), fix.Marks(ws)
    seen = next(i for i in split.seen if m.person[i] != m.judge[i] == "pass")  # asked there
    StartSession(ws).update({"id": seen, "reasons": ["wrong_fact"]})
    _write_rule(ws, _leans_better(ws, holder))
    code, flat = _fix(capsys, "--yes")
    assert code == 0 and "That leans toward better" in flat, flat
    assert fix.read_split(ws).topup is not None
    if clear == "empty":
        (ws.dir / "fix" / "rule.txt").write_text("", encoding="utf-8")
    else:
        (ws.dir / "fix" / "rule.txt").unlink()
    return ws


def _run(capsys):
    from tests.test_fix import run

    code, out = run(capsys)
    assert out.splitlines()[2:4] == ["Step 4 of 5: Fix", ""], out
    assert out.splitlines()[4].strip(), f"an empty step:\n{out}"
    return code, out, " ".join(out.split())


@pytest.mark.parametrize("clear", ["empty", "removed"])
def test_a_waiting_rule_test_shows_why_and_the_clues(fixing, capsys, clear):
    root, holder = fixing
    ws = _waiting_top_up(root, holder, capsys, clear)
    code, out, flat = _run(capsys)
    assert code == 0, out
    assert flat.index(WAITING) < flat.index("Your reasons for your LLM-as-a-judge's mistakes: it has a wrong fact (1)")
    assert "Where your LLM-as-a-judge goes wrong:" in out and ".judgekeeper/fix/mistakes.md" in flat
    assert "Your LLM-as-a-judge's rule is in promptfooconfig.yaml" in flat
    assert "kept aside to test your new rule fairly" in flat
    assert "Your new rule is waiting" not in flat  # no new rule in rule.txt
    assert assert_one_next_at_the_end(out) == NEXT_ALL_MARKED
    assert holder["evals"] == 2  # nothing asked
    assert (ws.dir / "fix" / "mistakes.md").is_file()


def test_a_different_rule_while_a_test_waits_is_named_after_the_clues(fixing, capsys):
    from judgekeeper import targets
    from tests.test_fix import _split, _write_rule

    root, holder = fixing
    ws = _waiting_top_up(root, holder, capsys)
    more = targets.top_up(len(_split(ws)["hidden"]))
    _write_rule(ws, "Another rule.")
    code, out, flat = _run(capsys)
    assert code == 0 and "testing your new rule" not in flat, out
    assert flat.index(WAITING) < flat.index("Where your LLM-as-a-judge goes wrong:") < flat.index(
        f"Your new rule is waiting: first mark {more} more answers")
    assert assert_one_next_at_the_end(out) == NEXT_ALL_MARKED
    assert holder["evals"] == 2


def test_a_judge_fix_cant_ask_shows_its_clues_not_the_wait(fixing, capsys):
    """The LLM-as-a-judge stopped being one fix can ask (here: its results now hold a rule per test),
    so the waiting test can't run again: the screen of an LLM-as-a-judge fix can't ask, with the clues."""
    from judgekeeper import fix

    root, holder = fixing
    ws = _waiting_top_up(root, holder, capsys)
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    data["one_rule"] = False
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    code, out, flat = _run(capsys)
    assert code == 3, out
    assert WAITING not in flat and "Where your LLM-as-a-judge goes wrong:" in out
    assert "Your reasons for your LLM-as-a-judge's mistakes: it has a wrong fact (1)" in flat
    assert fix.CANT_ASK in flat
    assert assert_one_next_at_the_end(out).startswith("Next: change its rule where your eval")
