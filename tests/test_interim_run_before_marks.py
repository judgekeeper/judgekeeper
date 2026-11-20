# ruff: noqa: F811 - the fixtures come from test_fixed_and_broke
"""A run between two sets of answers, before any of the second is marked, changes nothing
about the comparison. An answer the same, word for word, as one you marked keeps its mark and
is never new, whatever the run in between read: the counts, the verdict and the questions to
add depend only on the marks and the file now."""

from __future__ import annotations

import re

import pytest

from judgekeeper import no_grades
from tests.test_fixed_and_broke import _session, _write, _ws, here, project  # noqa: F401 (fixtures)

QUESTIONS, FAILS, CHANGED = 12, set(range(5)), range(7)  # all five Fails get a new answer

# What the run in between read, from the answers marked: {question: its answer then}.
INTERIM = {
    "all twelve different": lambda: {i: f"Interim {i}." for i in range(12)},
    "the five unchanged different": lambda: {i: f"Interim {i}." for i in range(7, 12)},
    "two more changed, to go back": lambda: {i: f"Interim {i}." for i in range(9)},
    "one more changed, to go back": lambda: {i: f"Interim {i}." for i in [*range(7), 11]},
}
SAME = {  # what the run in between read that was never a problem
    "none": dict,
    "the same seven changed again": lambda: {i: f"Interim {i}." for i in range(7)},
    "the file now": lambda: {i: f"Answer {i}, take 2." for i in range(7)},
}


def _result(project, interim: dict[int, str]):
    """Round 1 (12 questions, 5 Fails), a run on `interim` answers with nothing marked, then
    seven changed answers marked Pass and five the same as in round 1: what the result says
    (`compare`'s counts, the next step, the line the result gives)."""
    project.first(fails=FAILS, n=QUESTIONS)
    first = dict(project.outs)
    if interim:
        project.outs = {**first, **interim}
        _write(project.here, project.outs)
        project.run()
        project.outs = dict(first)  # the file a person marks from: the unchanged back as before
        _write(project.here, project.outs)
    said = project.again({i: "pass" for i in CHANGED})
    ws = _ws(project.here)
    c = no_grades.compare(ws, _session(project.here))
    return c, no_grades.result_line(c), said


def _counts(c: dict) -> tuple:
    """The five Fails are all in the seven changed: 4 of 7 Passes and 3 of 5 Fails are kept
    aside (half of each, rounded up), so 7 are compared, 3 fixed, none broke."""
    return tuple(c[k] for k in ("kept", "fixed", "broke", "same", "kept_fails", "fails",
                                "marked", "kind"))


A = (7, 3, 0, 4, 3, 5, 12, "leans better")


@pytest.mark.parametrize("name", list(SAME))
def test_a_run_in_between_that_changes_nothing_is_as_before(project, name):
    c, line, _ = _result(project, SAME[name]())
    assert _counts(c) == A, c
    assert "you had 3. Add about 29 more questions." in line, line  # 2 x (9 - 3) x 12 / 5


@pytest.mark.parametrize("name", list(INTERIM))
def test_a_run_in_between_changes_neither_the_counts_nor_the_questions_to_add(project, name):
    c, line, said = _result(project, INTERIM[name]())
    assert _counts(c) == A, c
    assert "you had 3. Add about 29 more questions." in line, line
    assert re.search(r"Add about 29 more questions", said), said


@pytest.mark.parametrize("name", ["none", *INTERIM])
def test_the_same_questions_are_compared_with_or_without_a_run_in_between(project, name):
    """What is compared is the set of kept-aside questions, the same ones either way."""
    interim = {} if name == "none" else INTERIM[name]()
    c = _result(project, interim)[0]
    assert c["kept"] == len(project.kept()) == 7, c
    assert c["fixed"] + c["broke"] + c["same"] == 7, c
