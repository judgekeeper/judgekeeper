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


# After a rule change: numbers on marks made after it ---------------------------------------------

WARN = ("This includes marks you looked at to write this rule, so it may read a few points "
        "high.")
NONE_YET = ("On marks made after this change: none yet. Mark more answers to see it on answers "
            "it was not written for.")


def _rule_change(here, lenient: bool = True):
    from tests.test_check import LENIENT, MARKED, _marked, _results

    ws = _marked(here)
    _results(here, LENIENT if lenient else MARKED, rubric="Is polite, correct and short.")
    return ws


def _backdate(ws, before: int) -> None:
    """The first check's line goes back to 2026-01-01, and the first `before` marks in the
    page's order to 2025: the rest were made after the change was first seen."""
    path = ws.history_jsonl
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    for x in lines:
        if x.get("kind") == "check":
            x["time"] = "2026-01-01T00:00:00Z"
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    first = {q["id"] for q in ws.data()["queue"][:before]}
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
    assert WARN in out and NONE_YET in out


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
    assert "  You passed: your judge also passed about " in out
    assert flat.index("Re-checked on all 50 of your marks:") < flat.index(
        "On marks made after this change (")
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
    assert check.picks(Workspace(here))["n"] == 1


# The person's own slips ----------------------------------------------------------------------

@pytest.mark.parametrize("p,e,tnr", [(0.9, 0.05, 68), (0.8, 0.05, 83), (0.9, 0.10, 50),
                                     (0.8, 0.10, 69), (0.5, 0.05, 95)])
def test_the_best_a_perfect_judge_could_show(p, e, tnr):
    assert round(targets.best_possible(p, e)["tnr"] * 100) == tnr


def test_the_slip_rate_from_repeats():
    assert targets.slip_rate(0.0) == 0.0
    e = targets.slip_rate(0.1)  # 1 in 10 repeats marked differently
    assert 2 * e * (1 - e) == pytest.approx(0.1)


def _result(p_pass=0.9):
    from judgekeeper import start_label, weighted

    n_pass = round(1000 * p_pass)
    return start_label.describe(weighted.corrected(n_pass, 1000 - n_pass, 40, 39, 40, 10))


def test_the_details_always_say_slips_lower_the_fail_side():
    from html import unescape

    from judgekeeper import start_label

    html = _flat(unescape(start_label.result_html(_result())))
    assert ("If you sometimes slip when marking, the number for answers you failed looks lower "
            "than it is, most when few answers fail.") in html
    assert "even a perfect judge" not in html  # no repeats


def test_repeats_give_the_best_possible_line_and_change_no_number():
    from html import unescape

    from judgekeeper import start_label

    r = _result()
    plain = {k: r[k] for k in ("tpr", "tnr", "kappa")}
    with_repeats = {**r, "repeats": {"same": 9, "of": 10}}
    html = _flat(unescape(start_label.result_html(with_repeats)))
    e = targets.slip_rate(0.1)
    best = targets.best_possible(r["real_pass_rate"], e)
    assert (f"You gave the same mark on 9 of 10 repeats. With slips like that, even a perfect "
            f"judge would show about {best['tnr']:.0%} here.") in html
    assert {k: with_repeats[k] for k in ("tpr", "tnr", "kappa")} == plain


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


# Paid re-checks ask the judge twice ------------------------------------------------------------

ASK_TWICE = ("To re-check, judgekeeper asks your new judge about your 50 marked answers, twice "
             "each. That is 100 AI calls, paid with your own key. Asking twice shows how much "
             "the judge varies by itself.")


@pytest.fixture
def check_judge(monkeypatch, here):
    from tests import test_check

    return test_check.judge.__wrapped__(monkeypatch, here)


def _new_judge(here):
    from tests.test_check import HAIKU, LENIENT, _marked, _new_outputs, _results

    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    return ws


def test_a_paid_recheck_says_it_asks_twice(here, capsys, check_judge):
    from judgekeeper.cli import main

    _new_judge(here)
    assert main(["check"]) == 3  # no terminal, no --yes: nothing is asked
    assert ASK_TWICE in _flat(capsys.readouterr().out)


def test_asked_twice_the_wobble_is_said_and_the_first_grades_decide(here, capsys, check_judge):
    from judgekeeper import start_label
    from judgekeeper.cli import main
    from tests.test_again_run import FakePromptfoo

    ws = _new_judge(here)
    fake = check_judge["fake"] = FakePromptfoo(start_label.Workspace(here), version="0.124.1")
    ids = [q["id"] for q in ws.data()["queue"]]
    fake.flips = {(i, 1) for i in ids[:3]}  # 3 answers get another grade the second time
    assert main(["check", "--yes"]) == 1
    out = _flat(capsys.readouterr().out)
    evals = [c.argv for c in fake.calls if "eval" in c.argv]
    assert len(evals) == 1 and evals[0][evals[0].index("--repeat") + 1] == "2"
    assert ("Asked twice, your new judge changed its own grade on 3 of your 50 answers. "
            "Differences that small can come from that alone.") in out
    assert "Worse: 9 turned wrong and none turned right." in out  # the first grades


def test_a_free_recheck_asks_nothing_extra(here, capsys):
    from judgekeeper.cli import main
    from tests.test_check import HAIKU, LENIENT, _marked, _results

    _marked(here)
    _results(here, LENIENT, model=HAIKU)
    main(["check"])
    out = _flat(capsys.readouterr().out)
    assert "Asked twice" not in out and "twice each" not in out
