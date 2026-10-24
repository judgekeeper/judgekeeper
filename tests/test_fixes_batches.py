"""Batches: what new answers joining as batches got wrong.

- a later batch marked in two sittings gets the same share kept aside per stratum.
- after "Worse", a waiting batch never brings back the "re-check your changed LLM-as-a-judge" loop.
- new answers that came with changed grades wait, and the screen says so.
- "Your eval ran again" is said once, not on every run after a batch was added.
- the marks of a batch that doesn't count yet are named apart from the ones that do.
- one newer answer needs one mark.
- the result screen names the mark command once.
- A check of a partial eval says to run the eval on all the questions.
No test calls an AI API.
"""

from __future__ import annotations

import re

import pytest

from judgekeeper import batches, fix, start, start_label
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import flat, next_lines, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _index(value) -> int:
    text = value.get("question") if isinstance(value, dict) else value
    return int(re.search(r"Question (\d+)\?", str(text))[1])


def _mark(ws: Workspace, person=None, only=None) -> None:
    """The person marks answers on the page: as the LLM-as-a-judge did, or `person[i]` for answer i;
    `only`: just those answers."""
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        i = _index(session.raw[item["id"]]["input"])
        if only is not None and i not in only:
            continue
        session.update({"id": item["id"], "label": (person or {}).get(i, groups[item["id"]]),
                        "seconds": 6})


def _next(out: str) -> str:
    return next_lines(out)[-1]


# a later batch marked in two sittings ----------------------------------------------------

class _Marks:
    """Marks as fix.Marks gives them to current_split."""

    def __init__(self):
        self.person, self.judge, self.batch, self.order = {}, {}, {}, []

    def add(self, b: int, ids) -> None:
        for k in ids:
            i = f"{b}-{k}"
            self.judge[i] = "pass" if k % 2 else "fail"
            self.person[i] = self.judge[i] if k % 4 else ("fail" if k % 2 else "pass")
            self.batch[i] = b
            self.order.append(i)

    def keeps_aside(self) -> bool:
        return True


def _cells(m: _Marks, b: int) -> list[list[str]]:
    return [[i for i in m.person if m.batch[i] == b and m.judge[i] == g
             and (m.person[i] == g) == agrees]
            for g in ("pass", "fail") for agrees in (True, False)]


def test_a_later_batch_marked_in_two_sittings_gets_the_same_share_kept_aside(here):
    ws = Workspace(here)
    ws.dir.mkdir()
    m = _Marks()
    m.add(1, range(40))
    fix.current_split(ws, m)
    m.add(2, range(3))  # a first sitting of batch 2
    fix.current_split(ws, m)
    m.add(2, range(3, 40))  # and the rest of it
    split_ = fix.current_split(ws, m)
    hidden = set(split_.hidden)
    for cell in _cells(m, 2):
        want = -(-len(cell) * fix.HIDDEN_TENTHS // 10) if len(cell) > 1 else 0
        assert sum(i in hidden for i in cell) == want, cell
    first = sum(m.batch[i] == 1 for i in hidden)
    assert sum(m.batch[i] == 2 for i in hidden) >= first - 4  # about the first batch's share


# after "Worse", a waiting batch keeps one way out ----------------------------------------

NEXT_WORSE_TABLE = ("Next: go back to your old LLM-as-a-judge, or change its rule; then run your eval "
                    "and `judgekeeper check`.")


def _truth(i: int) -> bool:
    return i % 3 != 0


def test_after_worse_a_waiting_batch_does_not_bring_back_the_loop(here, capsys, pages):
    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(70)]
    table_project(here, old[:60])
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws, {i: "pass" if _truth(i) else "fail" for i in range(60)})
    run(capsys, "--no-browser")
    table_project(here, old)  # 10 more questions: a second batch
    run(capsys, "--no-browser")
    _mark(ws, {i: "pass" if _truth(i) else "fail" for i in range(70)}, only={60, 61, 62})
    new = [(not v) if i % 2 == 0 or i % 4 == 1 else v for i, v in enumerate(old)]
    table_project(here, new)
    code, out, _ = run(capsys, "check")
    assert code == 1 and "Worse" in out, out
    assert _next(out) == NEXT_WORSE_TABLE
    code, out, _ = run(capsys, "--no-browser")
    assert _next(out) == NEXT_WORSE_TABLE, out
    assert "re-check your changed LLM-as-a-judge" not in out


# new answers that came with changed grades wait ------------------------------------------

def test_new_answers_with_changed_grades_wait_and_the_screen_says_so(here, capsys, pages):
    table_project(here, split(20, 16))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    regraded = [(not v) if i % 6 == 0 else v for i, v in enumerate(split(20, 16))]
    table_project(here, regraded + split(10, 10))  # 20 new answers, and grades changed
    line = ("20 new answers came with changed grades, so they wait until your changed LLM-as-a-judge "
            "is checked.")
    for argv in (("mark", "--no-browser"), ("--no-browser",)):
        _, out, _ = run(capsys, *argv)
        assert line in flat(out), out
        assert "more questions" not in out
        assert "judgekeeper check" in _next(out), out
        assert len(ws.data()["queue"]) == 36  # they join no batch


# "Your eval ran again" once --------------------------------------------------------------

RAN_AGAIN = "Your eval ran again."


def test_ran_again_is_said_once_after_a_batch_from_a_new_file(here, capsys, pages):
    table_project(here, split(10, 30))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    table_project(here, split(5, 5), tag=" (new)")  # the file now holds only new answers
    _, out, _ = run(capsys, "--no-browser")
    assert "added for marking" in flat(out), out
    run(capsys, "--stop")
    _, out, _ = run(capsys, "--no-browser")
    assert RAN_AGAIN not in out, out


# a waiting batch's marks are named apart -------------------------------------------------

def test_a_waiting_batchs_marks_are_named_apart(here, capsys, pages):
    promptfoo_project(here, split(20, 14))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark(ws)
    promptfoo_project(here, split(20, 14) + split(5, 5))
    batches.add(ws, start.find_judge(here))
    _mark(ws, only={34, 39, 40})  # 1 Pass and 2 Fail in batch 2: it doesn't count yet
    _, out, _ = run(capsys, "--no-browser")
    text = flat(out)
    # the counts before "not enough" are the ones that count; the waiting batch's said apart
    assert ("You marked 37 answers so far: 20 Pass, 14 Fail count for a result, and 3 more "
            "are in a newer batch that doesn't count yet.") in text, out
    assert "21 Pass" not in text and "16 Fail" not in text
    assert "That's not enough for a result yet." in text
    assert text.index("count for a result") < text.index("not enough for a result yet")


def test_with_no_waiting_batch_the_count_line_is_as_before(here, capsys, pages):
    promptfoo_project(here, split(20, 14))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark(ws, only=set(range(10)) | set(range(20, 25)))  # 10 Pass and 5 Fail
    _, out, _ = run(capsys, "--no-browser")
    assert "You marked 15 answers so far: 10 Pass, 5 Fail." in out, out
    assert "newer batch" not in out


# one newer answer ------------------------------------------------------------------------

def test_one_newer_answer_needs_a_mark():
    assert batches.line({"counted": [1], "of": 2, "answers": 40, "waiting": 1}) == (
        "This result is on 1 of 2 batches (40 answers). 1 newer answer needs a mark first.")
    assert batches.line({"counted": [1], "of": 2, "answers": 40, "waiting": 3}) == (
        "This result is on 1 of 2 batches (40 answers). 3 newer answers need a few marks "
        "first.")


# the mark command once on the result screen ----------------------------------------------

def test_the_result_screen_names_the_mark_command_once(here, capsys, pages):
    promptfoo_project(here, split(30, 30))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    person = {i: ("fail" if i in (1, 2, 3) else "pass") if i < 30
              else ("pass" if i in (31, 32) else "fail") for i in range(60)}
    _mark(ws, person, only=set(range(20)) | set(range(30, 50)))
    promptfoo_project(here, split(30, 30) + split(5, 5))
    batches.add(ws, start.find_judge(here))
    _mark(ws, only={60, 65})  # a batch waiting
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    assert "Too early to tell" in out or "too early to tell" in out, out
    run(capsys, "--stop")
    _, out, _ = run(capsys, "--no-browser")
    assert flat(out).count("judgekeeper mark") == 1, out
    assert "The Next step below also lets you say why on these." in flat(out)
    assert _next(out) == "Next: run `judgekeeper mark --no-browser` to mark more answers."


# A check of a partial eval --------------------------------------------------------------------

def test_a_check_of_a_partial_eval_says_to_run_it_on_all_questions(here, capsys, pages):
    table_project(here, split(20, 16))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    partial = split(20, 16)[:10]
    partial[0] = not partial[0]
    table_project(here, partial)  # the eval ran on 10 questions, over the old file
    _, out, _ = run(capsys, "check", "--yes")
    assert "more questions" not in out, out
    assert _next(out) == ("Next: run your eval on all your questions, then run "
                          "`judgekeeper check`."), out
