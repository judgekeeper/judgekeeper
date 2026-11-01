"""The numbers around `judgekeeper fix` and `check`: hidden marks set aside at the first
result and kept out of sight while in use, every fix test counted, how many changes the marks
have helped pick, the person's own slips, and a range that stays honest while the person is
still marking.

No test calls an API: new grades come from results files, as tests/test_fix.py writes them.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import fix, targets
from tests import test_fix as base
from tests.test_fix import _split, project, regraded, run

here = base.here  # the fixture: a project folder


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


def test_the_reference_says_how_extra_tests_stay_fair():
    from pathlib import Path

    reference = (Path(__file__).parent.parent / "docs" / "reference.md").read_text(encoding="utf-8")
    assert "the levels divided by the number of tests" in reference
    fixing = reference[reference.index("## fix:"):reference.index("## check:")]
    assert "1 in 20" not in fixing  # a figure with no report behind it is not stated


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
    capsys.readouterr()
    run(capsys)  # fix's first run: mistakes.md
    split = _split(ws)
    md = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    section = fix.report_section(ws)
    shown = json.dumps(section)
    for text in _hidden_texts(ws, split):
        assert text not in md and text not in shown


def test_a_retired_set_may_show_its_answers(here, capsys):
    """A rule tested on the set is now the LLM-as-a-judge's rule: the hidden marks are seen again, and
    the next marks make a new set."""
    from judgekeeper import judge_setup, start

    ws = project(here)
    run(capsys)
    run(capsys, regraded(here).name)
    hidden = _split(ws)["hidden"]
    (here / "regraded.json").unlink()
    regraded(here, name="results.json")  # the tested LLM-as-a-judge is the project's now
    found = start.find_judge(here)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    split = fix.current_split(ws, fix.Marks(ws))
    assert split.hidden == [] and set(hidden) <= set(split.seen)
    assert split.fresh == {"want": fix.FRESH, "adopted": True}
    wrong = [i for i in hidden if fix.Marks(ws).judge[i] != fix.Marks(ws).person[i]]
    shown = json.dumps(fix.report_section(ws))
    m = fix.Marks(ws)
    assert wrong and all(fix._question(m, m.row(i))[:40] in shown for i in wrong)


def test_three_rules_retire_the_set(here, capsys):
    ws = project(here)
    run(capsys)
    split = fix.read_split(ws)
    n = len(split.hidden)
    split.tests = [{"kind": "rule", "rule_hash": f"sha256:{k}", "n": n, "fixed": 0, "broke": 1,
                    "test": k, "verdict": targets.fix_verdict(0, 1, n, test=k).kind}
                   for k in (1, 2, 3)]
    fix.save_split(ws, split)
    split = fix.current_split(ws, fix.Marks(ws))
    assert split.hidden == [] and split.fresh == {"want": fix.FRESH}


# How many changes the marks have helped pick ---------------------------------------------------

def _marked_some(root, first: int):
    """A promptfoo project marked as the LLM-as-a-judge graded, the first `first` answers only."""
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
        ("You've used these marks to choose 3 changes, so they may now make your "
         "LLM-as-a-judge look better than it is. Mark some new answers.")]
    time.sleep(1.1)  # marks are stamped to the second
    for q in queue[40:50]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    p = check.picks(ws)
    assert p["n"] == 3 and not p["ask"]
    assert check.picks_lines(p) == []  # said only with the warning


def test_a_model_update_is_not_a_pick(tmp_path, monkeypatch):
    from judgekeeper import check, marks
    from judgekeeper.fingerprint import utc_now

    monkeypatch.chdir(tmp_path)
    ws, _, _ = _marked_some(tmp_path, 40)
    marks.append(ws.history_jsonl, {"time": utc_now(), "kind": "check",
                                    "changed": ["model a -> b"], "groups": {}})
    assert check.picks(ws)["n"] == 0
    assert check.picks_lines(check.picks(ws)) == []


def test_check_after_three_picks_with_every_answer_marked(here, capsys):
    """Every answer is marked, so there are none to mark: never "mark 10 new answers"."""
    from judgekeeper.cli import main
    from tests.test_check import MARKED, _marked, _results

    ws = _marked(here)
    for kind in ("fix", "check"):
        _pick(ws, kind)
    _results(here, MARKED, rubric="Is polite, correct and short.")
    _tested_by_fix(here, ws)  # a rule fix tested (a pick), and its check (another)
    code = main(["check"])
    out = _flat(capsys.readouterr().out)
    assert ("You've used these marks to choose 4 changes, so they may now make your "
            "LLM-as-a-judge look better than it is.") in out
    assert "Mark some new answers" not in out and "honest" not in out
    assert out.endswith("Next: run your eval on more questions, then run `judgekeeper mark`: "
                        "the new answers join the ones you marked.")
    assert code == 0


def test_the_result_keeps_how_many_changes_the_marks_helped_pick(tmp_path, monkeypatch):
    from judgekeeper import start_label

    monkeypatch.chdir(tmp_path)
    ws, session, _ = _marked_some(tmp_path, 40)
    _pick(ws)
    _pick(ws, "check")
    start_label.store_result(ws, session)
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["picks"] == []  # two picks: no warning yet, so nothing is said


def test_fix_new_does_not_count_the_picks_again(tmp_path, monkeypatch):
    """`fix --new` makes no new marks: the picks made on these marks still count."""
    import time

    from judgekeeper import check

    monkeypatch.chdir(tmp_path)
    ws, _, _ = _marked_some(tmp_path, 40)
    for _ in range(3):
        _pick(ws)
    assert check.picks(ws)["n"] == 3
    time.sleep(1.1)
    fix.current_split(ws, fix.Marks(ws), new=True)
    assert check.picks(ws)["n"] == 3


# After a rule change: numbers on marks made after it ---------------------------------------------

WARN = ("This includes marks you looked at to write this rule, so it may read a few points "
        "high.")
NONE_YET = "On marks made after this change: none."  # every answer is marked: none is left


def _rule_change(here, lenient: bool = True):
    """A rule change `fix` tested (written by looking at the marks)."""
    from tests.test_check import LENIENT, MARKED, _marked, _results

    ws = _marked(here)
    _results(here, LENIENT if lenient else MARKED, rubric="Is polite, correct and short.")
    _tested_by_fix(here, ws)
    return ws


def _tested_by_fix(root, ws) -> None:
    """`fix` tested the rule in the newest results: a history line, as fix writes it."""
    from judgekeeper import judge_setup, marks, start
    from judgekeeper.fingerprint import utc_now

    rule = judge_setup.of(start.find_judge(root))["rule_hash"]
    marks.append(ws.history_jsonl, {"time": utc_now(), "kind": "fix", "rule_hash": rule})


def _backdate(ws, before: int) -> None:
    """The first check's line goes back to 2026-01-01, and `before` marks to 2025, half from
    each group by id (never the page's order, which is shuffled): the rest were made after the
    change was first seen."""
    path = ws.history_jsonl
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    for x in lines:
        if x.get("kind") == "check":
            x["time"] = "2026-01-01T00:00:00Z"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    queue = ws.data()["queue"]
    first = {i for group in ("pass", "fail")
             for i in sorted(q["id"] for q in queue if q["group"] == group)[:before // 2]}
    rows = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()]
    for x in rows:
        if x.get("id") in first:
            x["at"] = "2025-06-01T00:00:00Z"
    ws.marks.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


def test_a_rule_change_says_its_marks_helped_write_it(here, capsys):
    from judgekeeper.cli import main

    _rule_change(here)
    main(["check"])
    out = _flat(capsys.readouterr().out)
    assert WARN in out and NONE_YET in out and "Mark more" not in out


def test_a_model_change_says_none_of_it(here, capsys):
    from judgekeeper.cli import main
    from tests.test_check import HAIKU, LENIENT, _marked, _results

    _marked(here)
    _results(here, LENIENT, model=HAIKU)
    main(["check"])
    out = _flat(capsys.readouterr().out)
    assert WARN not in out and "made after this change" not in out


def test_ten_of_each_made_after_the_change_show_their_numbers(here, capsys):
    from judgekeeper.cli import main

    ws = _rule_change(here)
    main(["check"])  # worse: the old judge stays the reference, the change stays open
    capsys.readouterr()
    _backdate(ws, 28)  # 22 marks after the change, at least 10 of each kind
    main(["check"])
    out = capsys.readouterr().out
    flat = _flat(out)
    assert "On marks made after this change (" in flat
    assert "  You passed: your LLM-as-a-judge also passed about " in out
    assert flat.index("Agreed with you:") < flat.index("On marks made after this change (")
    assert WARN in flat


def test_fifteen_of_each_made_after_the_change_become_the_headline(here, capsys):
    from judgekeeper.cli import main

    ws = _rule_change(here)
    main(["check"])
    capsys.readouterr()
    _backdate(ws, 10)  # 40 marks after the change
    code = main(["check"])
    flat = _flat(capsys.readouterr().out)
    head = "Re-checked on the 40 marks you made after this change:"
    assert head in flat
    assert flat.index(head) < flat.index("On all 50 of your marks:") < flat.index(WARN)
    assert code == 1  # the verdict now comes from the new marks: still worse


def test_checking_the_same_change_again_is_not_another_pick(here, capsys):
    from judgekeeper import check
    from judgekeeper.cli import main
    from judgekeeper.start_label import Workspace

    _rule_change(here)
    main(["check"])  # worse: the change stays open
    main(["check"])
    capsys.readouterr()
    assert check.picks(Workspace(here))["n"] == 2  # the fix test, and one check of it


# The person's own slips ----------------------------------------------------------------------

@pytest.mark.parametrize("p,e,tnr", [(0.9, 0.05, 68), (0.8, 0.05, 83), (0.9, 0.10, 50),
                                     (0.8, 0.10, 69), (0.5, 0.05, 95)])
def test_the_best_a_perfect_judge_could_show(p, e, tnr):
    assert round(targets.best_possible(p, e)["tnr"] * 100) == tnr


def test_the_slip_rate_from_repeats():
    assert targets.slip_rate(0.0) == 0.0
    e = targets.slip_rate(0.1)  # 1 in 10 repeats marked differently
    assert 2 * e * (1 - e) == pytest.approx(0.1)


# A range that stays honest while the person is still marking ---------------------------------------

def _misses_at_some_look(rng, p: float, first: int = 15, last: int = 200) -> bool:
    """Whether the anytime range misses the true rate p at some look, marking one answer at
    a time and looking after each from the `first`-th to the `last`-th."""
    k = 0
    for n in range(1, last + 1):
        k += rng.random() < p
        if n >= first and not targets.anytime_holds(p, k, n):
            return True
    return False


@pytest.mark.parametrize("p", [0.70, 0.80, 0.90, 0.95])
def test_the_anytime_range_misses_at_most_5_in_100_however_often_one_looks(p):
    import random

    rng = random.Random(int(p * 100))
    runs = 1000
    assert sum(_misses_at_some_look(rng, p) for _ in range(runs)) / runs <= 0.05


def test_the_anytime_range_holds_the_share_and_is_wider_than_the_fixed_one():
    from judgekeeper import weighted

    lo, hi = targets.anytime_range(40, 50)
    assert lo < 0.8 < hi
    assert targets.anytime_holds(0.8, 40, 50) and not targets.anytime_holds(0.3, 40, 50)
    import random

    rng = random.Random(1)
    draws = sorted(rng.betavariate(40.5, 10.5) for _ in range(20000))
    fixed = weighted.middle(draws, weighted.LEVEL, 0.8)
    ratio = (hi - lo) / (fixed[1] - fixed[0])
    assert 1.4 <= ratio <= 1.7  # about 1.4 to 1.6 times the fixed range


def test_no_message_while_marking_compares_a_number_with_the_bar():
    """The line under the page's meters says how far along the marks are, by the widths of
    the ranges, never "good enough" or a bar: such a line would need the anytime range."""
    from judgekeeper import start_label

    texts = {start_label.progress_status(900, 100, n_p, c_p, n_f, c_f)["text"]
             for n_p in (5, 15, 30, 60) for c_p in (0, n_p // 2, n_p)
             for n_f in (5, 15, 30, 60) for c_f in (0, n_f // 2, n_f)}
    texts.add(start_label.page_template({}))
    for text in texts:
        for word in ("80%", "good enough", "clearly", "below the", "above the"):
            assert word not in text, (word, text)
