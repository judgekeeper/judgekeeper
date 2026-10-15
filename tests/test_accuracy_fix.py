"""The numbers around `judgekeeper fix` and `check`: hidden marks set aside at the first
result and kept out of sight while in use, every fix test counted, few mistakes said up front,
how many changes the marks have helped pick, the person's own slips, a range that stays honest
while the person is still marking, and paid re-checks that ask twice.

No test calls an API: the judge is the faked promptfoo of tests/test_fix.py.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import fix, targets
from tests import test_fix as base
from tests.test_fix import NEW_RULE, _split, _write_rule, project, run

here, judge = base.here, base.judge  # the fixtures: a project folder, and its faked judge


def _flat(text: str) -> str:
    return " ".join(text.split())


# Every fix test counts ------------------------------------------------------------------------

@pytest.mark.parametrize("k,safe,better", [(1, 3, 6), (2, 4, 7), (3, 5, 7), (4, 5, 8)])
def test_each_extra_test_on_the_same_hidden_marks_is_stricter(k, safe, better):
    """On 10 hidden marks, with nothing broken: the fewest fixed for "safe to try" and for
    "better" at the k-th test."""
    def fewest(kinds):
        return next(f for f in range(11) if targets.fix_verdict(f, 0, 10, test=k).kind in kinds)

    assert fewest(("safe", "better")) == safe
    assert fewest(("better",)) == better


def test_every_test_counts_whatever_the_last_verdict():
    split = fix.Split(seed=1, seen=[], hidden=[], tests=[
        {"kind": "rule", "verdict": "safe"}, {"kind": "rule", "verdict": "leans better"}])
    assert fix.next_test(split) == 3


def test_few_mistakes_hidden_are_said_before_the_question(here, capsys, judge, monkeypatch):
    monkeypatch.setattr(base, "WRONG_PASSES", 3)  # 3 + 1 mistakes: about 1 of them hidden
    monkeypatch.setattr(base, "WRONG_FAILS", 1)
    ws = project(here)
    run(capsys)
    split, marks = _split(ws), fix.Marks(ws)
    wrong = sum(marks.judge[i] != marks.person[i] for i in split["hidden"])
    assert wrong < 3
    _write_rule(ws)
    code, out = run(capsys)
    assert code == 3  # no terminal: the question stops it
    n = len(split["hidden"])
    safe = next(f for f in range(n + 1) if targets.fix_verdict(f, 0, n).kind in ("safe",
                                                                                  "better"))
    better = next(f for f in range(n + 1) if targets.fix_verdict(f, 0, n).kind == "better")
    said = (f"Your hidden marks hold only {wrong} {'answer' if wrong == 1 else 'answers'} "
            f"your judge got wrong. A new rule needs at least {safe} of those fixed to be "
            f"called safe to try, and about {better} to be called better, so this test can "
            "only catch a worse rule.")
    assert said in _flat(out)
    assert _flat(out).index(said) < _flat(out).index("To test it, judgekeeper asks")


def test_enough_mistakes_hidden_say_nothing_more(here, capsys, judge):
    ws = project(here)
    run(capsys)
    _write_rule(ws)
    _, out = run(capsys)
    assert "Your hidden marks hold only" not in out
    assert json.dumps(NEW_RULE) not in out


def test_the_guide_says_how_extra_tests_stay_fair():
    from pathlib import Path

    guide = (Path(__file__).parent.parent / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "under about 1 in 20" in guide


# Hidden marks from the first result on ---------------------------------------------------------

def _hidden_texts(ws, split) -> list[str]:
    from tests.start_projects import question
    from tests.test_fix import TAG, _index

    return [question(_index(ws, i), TAG) for i in split["hidden"]]


def test_the_hidden_marks_are_set_aside_when_the_first_result_appears(here, capsys):
    from judgekeeper.cli import main

    ws = project(here)
    assert not (ws.dir / "fix" / "split.json").exists()
    assert main(["--no-browser"]) == 0  # the first result
    out = capsys.readouterr().out
    split = _split(ws)
    assert len(split["hidden"]) >= 10
    report = ws.report_html.read_text(encoding="utf-8")
    for text in _hidden_texts(ws, split):
        assert text not in report and text not in out
    for i in split["hidden"]:
        assert i not in report and i not in out


def test_hidden_marks_never_show_while_the_set_is_in_use(here, capsys):
    from judgekeeper.cli import main

    ws = project(here)
    main(["--no-browser"])
    run(capsys)  # fix's first run: mistakes.md
    split = _split(ws)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    section = fix.report_section(ws)
    shown = json.dumps(section)
    for text in _hidden_texts(ws, split):
        assert text not in md and text not in shown


def test_a_retired_set_may_show_its_answers(here, capsys, judge):
    """A rule tested on the set is now the judge's rule: the hidden marks are seen again, and
    the next marks make a new set."""
    from judgekeeper import judge_setup
    from judgekeeper.fingerprint import rule_hash

    ws = project(here)
    run(capsys)
    _write_rule(ws)
    run(capsys, "--yes")
    hidden = _split(ws)["hidden"]
    saved = judge_setup.read(ws)
    setup = {**saved["setup"], "rule_hash": rule_hash(NEW_RULE)}
    judge_setup.save(ws, setup, saved.get("metric"))
    split = fix.current_split(ws, fix.Marks(ws))
    assert split.hidden == [] and set(hidden) <= set(split.seen)
    assert split.fresh == {"want": fix.FRESH}
    wrong = [i for i in hidden if fix.Marks(ws).judge[i] != fix.Marks(ws).person[i]]
    shown = json.dumps(fix.report_section(ws))
    assert wrong and all(fix.Marks(ws).row(i)["input"][:40] in shown for i in wrong)


def test_three_rules_retire_the_set(here, capsys, judge):
    ws = project(here)
    run(capsys)
    split = fix.read_split(ws)
    split.tests = [{"kind": "rule", "rule_hash": f"sha256:{n}", "verdict": "leans worse"}
                   for n in range(3)]
    fix.save_split(ws, split)
    split = fix.current_split(ws, fix.Marks(ws))
    assert split.hidden == [] and split.fresh == {"want": fix.FRESH}


# How many changes the marks have helped pick ---------------------------------------------------

def _marked_some(root, first: int):
    """A promptfoo project marked as the judge graded, the first `first` answers only."""
    from judgekeeper import judge_setup, start, start_label
    from judgekeeper.start_label import StartSession
    from tests.start_projects import split as both
    from tests.test_check import _results

    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _results(root, both(25, 25))
    found = start.find_judge(root)
    ws = start_label.Workspace(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=lambda line: None)
    session = StartSession(ws)
    queue = ws.data()["queue"]
    for q in queue[:first]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    return ws, session, queue


def _pick(ws, kind: str = "fix") -> None:
    from judgekeeper import marks
    from judgekeeper.fingerprint import utc_now

    line = {"time": utc_now(), "kind": kind}
    if kind == "check":
        line.update(changed=["rule changed"], groups={})
    marks.append(ws.history_jsonl, line)


def test_three_picks_ask_for_new_marks_and_ten_new_marks_end_it(tmp_path, monkeypatch):
    import time

    from judgekeeper import check

    monkeypatch.chdir(tmp_path)
    ws, session, queue = _marked_some(tmp_path, 40)
    assert check.picks(ws)["n"] == 0
    for kind in ("fix", "check", "fix"):
        _pick(ws, kind)
    p = check.picks(ws)
    assert p["n"] == 3 and p["ask"]
    assert check.picks_lines(p) == [
        "These marks have helped pick 3 changes.",
        ("Your marks have been used to pick 3 changes, so they may now flatter your judge. "
        "Mark 10 new answers to keep the check honest.")]
    time.sleep(1.1)  # marks are stamped to the second
    for q in queue[40:50]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    p = check.picks(ws)
    assert p["n"] == 3 and not p["ask"]
    assert check.picks_lines(p) == ["These marks have helped pick 3 changes."]


def test_a_model_update_is_not_a_pick(tmp_path, monkeypatch):
    from judgekeeper import check, marks
    from judgekeeper.fingerprint import utc_now

    monkeypatch.chdir(tmp_path)
    ws, _, _ = _marked_some(tmp_path, 40)
    marks.append(ws.history_jsonl, {"time": utc_now(), "kind": "check",
                                    "changed": ["model a -> b"], "groups": {}})
    assert check.picks(ws)["n"] == 0
    assert check.picks_lines(check.picks(ws)) == []


def test_check_asks_for_new_marks_after_three_picks(here, capsys):
    from judgekeeper.cli import main
    from tests.test_check import MARKED, _marked, _results

    ws = _marked(here)
    for kind in ("fix", "fix", "check"):
        _pick(ws, kind)
    _results(here, MARKED, rubric="Is polite, correct and short.")  # a rule change: a pick
    code = main(["check"])
    out = _flat(capsys.readouterr().out)
    assert "These marks have helped pick 4 changes." in out
    assert "Mark 10 new answers to keep the check honest." in out
    assert out.endswith("Next: run `judgekeeper mark` to mark 10 new answers, then run "
                        "`judgekeeper check` again.")
    assert code == 0


def test_the_report_says_how_many_changes_the_marks_helped_pick(tmp_path, monkeypatch):
    from judgekeeper import start_label

    monkeypatch.chdir(tmp_path)
    ws, session, _ = _marked_some(tmp_path, 40)
    _pick(ws)
    _pick(ws, "check")
    start_label.store_result(ws, session)
    assert "These marks have helped pick 2 changes." in ws.report_html.read_text(encoding="utf-8")


def test_fix_new_counts_the_picks_again(tmp_path, monkeypatch):
    import time

    from judgekeeper import check

    monkeypatch.chdir(tmp_path)
    ws, _, _ = _marked_some(tmp_path, 40)
    for _ in range(3):
        _pick(ws)
    assert check.picks(ws)["n"] == 3
    time.sleep(1.1)
    fix.current_split(ws, fix.Marks(ws), new=True)
    assert check.picks(ws)["n"] == 0
