"""Every result with no grade ends with a Next line that is true for it: no Fail, a fix with
no Fail, and three changes tested on the questions kept aside."""
from __future__ import annotations

import re

import pytest

from tests.test_answers_without_grades import here, mark, write_answers  # noqa: F401
from tests.test_front import flat, run


def _say(capsys, *argv) -> tuple[int, str]:
    code, out, err = run(capsys, *argv, "--no-browser", "--port", "0")
    return code, out + err


def _last(said: str) -> str:
    return [line for line in said.splitlines() if line.strip()][-1]


@pytest.mark.parametrize("n", [10, 14])
def test_a_result_with_no_fail_ends_with_a_next_line(here, capsys, n):  # noqa: F811
    write_answers(here, n)
    assert _say(capsys)[0] in (0, 3)  # the session
    mark(here, ["pass"] * n)
    code, said = _say(capsys)
    assert code == 0, said
    assert "You passed" in flat(said), said
    assert "Next: " in said.split("Full report:")[-1], said


# After changes tested on the questions kept aside -----------------------------------------

from tests.test_fixed_and_broke import NEW_SET, Project, _ws

SURER = "for a surer number"


@pytest.fixture
def project(here, capsys, pages):  # noqa: F811
    return Project(here, capsys)


def _next(said: str) -> str:
    return said.rsplit("Next: ", 1)[1]


def test_fix_with_no_fail_left_gives_the_next_step_for_answers_with_no_grade(project):
    project.first(fails=set(range(12)), n=20)
    said = project.again({i: "pass" for i in project.kept("fail") + project.shown("fail")})
    assert "You passed 20 of 20" in said, said
    _code, out, err = run(project.capsys, "fix")
    said = flat(out + err)
    assert "verdict column" not in said, said
    # as the result says it, each with the flags of its own run (fix takes no page flags)
    assert _next(said) == _next(project.run()).replace(" --no-browser", ""), said


def test_after_three_changes_the_one_next_step_is_new_questions(project):
    project.first(fails=set(range(12)), n=20)
    kept = project.kept("fail")
    project.again({i: "pass" for i in kept})
    project.again({i: "fail" for i in kept})
    said = project.again({i: "pass" for i in kept})
    assert NEW_SET in said, said
    assert SURER not in said, said
    assert "new questions" in _next(said) or "harder questions" in _next(said), said
    report = flat(_ws(project.here).report_html.read_text(encoding="utf-8"))
    assert NEW_SET in report and SURER not in report, report


def test_the_since_heading_is_left_out_when_it_has_nothing_under_it(project):
    project.first(fails=set(range(12)), n=20)
    kept = project.kept("fail")
    for m in ("pass", "fail", "pass", "fail"):  # a fourth change: the set is used up
        said = project.again({i: m for i in kept})
    report = _ws(project.here).report_html.read_text(encoding="utf-8")
    section = report.split('id="since-h"', 1)[1].split("</section>", 1)[0] \
        if 'id="since-h"' in report else ""
    assert not section or "<p" in section, (said, section)


# "Can't tell yet" with too few kept-aside Fails: the step its line asks for, the one step ----

HARDER = "Add harder questions, ones your agent or chatbot may get wrong, and mark their answers."


def _without_page_flags(step: str) -> str:
    """`step` as `fix` gives it: fix takes no page flags (--no-browser, --port N)."""
    return re.sub(r" --(?:no-browser|port \d+)(?= |`)", "", step)


def _one_step(project, said: str, step: str) -> None:
    """`step` is the Next of the terminal, `mark` (every answer marked), `fix` (no answer
    failed is left to fix) and the page, never more answers to the same questions."""
    assert SURER not in said, said
    assert step in _next(said), said
    _code, out, err = run(project.capsys, "mark", "--no-browser")
    assert _next(flat(out + err)) == _next(said), out + err
    _code, out, err = run(project.capsys, "fix")  # fix takes no page flags
    assert _next(flat(out + err)) == _without_page_flags(_next(said)), out + err
    report = flat(_ws(project.here).report_html.read_text(encoding="utf-8"))
    assert SURER not in report, report
    after = report.split("What next", 1)[1]
    assert step[0].upper() + step[1:] in after, report
    assert "After you change the prompt" not in after, report  # the one step, no other


def test_too_few_kept_aside_fails_for_a_clear_answer_the_step_is_harder_questions(project):
    project.first(fails=set(range(4)), n=40)  # 4 in 40 fail: new ones would rarely fail
    said = project.again({i: "pass" for i in project.kept("fail") + project.shown("fail")})
    assert "Can't tell yet" in said and HARDER in said, said  # the line as it was
    _one_step(project, said, "add harder questions, ones your agent or chatbot may get wrong, to ")


def test_kept_aside_fails_short_of_a_clear_answer_the_step_is_the_questions_it_asks(project):
    project.first(fails=set(range(12)), n=20)
    said = project.again({i: "pass" for i in project.kept("fail")[:2] + project.shown("fail")})
    assert "Can't tell yet" in said, said
    extra = said.split("Add about ", 1)[1].split(" more questions.", 1)[0]
    assert extra.isdigit(), said
    _one_step(project, said, f"add about {extra} more questions to ")


def test_with_no_answer_failed_the_one_step_is_harder_questions(here, capsys):  # noqa: F811
    write_answers(here, 10)
    _say(capsys)
    mark(here, ["pass"] * 10)
    said = flat(_say(capsys)[1])
    assert "You passed 10 of 10" in said and SURER not in said, said
    step = "add harder questions, ones your agent or chatbot may get wrong, to "
    assert _next(said).startswith(step + "results.csv, then run "), said
    _code, out, err = run(capsys, "fix")  # fix takes no page flags
    assert _next(flat(out + err)) == _without_page_flags(_next(said)), out + err
    report = flat(_ws(here).report_html.read_text(encoding="utf-8"))
    assert SURER not in report, report
    assert step[0].upper() + step[1:] in report.split("What next", 1)[1], report


def test_with_failed_answers_left_to_fix_the_one_step_is_still_the_questions_it_asks(
        project):
    project.first(fails=set(range(6)), n=12)  # 3 Fails kept aside, 3 shown
    said = project.again({i: project.marks[i] for i in project.kept()})  # nothing changed
    assert "fixed 0, broke 0, same 6. Can't tell yet." in said, said
    assert "you had 3. Add about 24 more questions." in said, said  # the line as it was
    _one_step(project, said, "add about 24 more questions to ")


def test_with_no_kept_aside_answer_changed_the_one_step_is_the_change_to_test(project):
    project.first(fails=set(range(6)), n=12)
    said = project.again({i: "fail" for i in project.shown("fail")})  # none kept aside
    assert "your change can't be tested yet" in said, said
    step = ("paste the prompt above into your coding agent. After it changes the prompt of your "
            "agent or chatbot,")
    assert _next(said).startswith(step), said
    _code, out, err = run(project.capsys, "mark", "--no-browser")
    assert _next(flat(out + err)) == _next(said), out + err
    assert "Paste this into your coding agent" in out, out  # the prompt it names, above it
    _code, out, err = run(project.capsys, "fix")  # fix takes no page flags
    assert _next(flat(out + err)) == _without_page_flags(_next(said)), out + err
    after = flat(_ws(project.here).report_html.read_text(encoding="utf-8")).split(
        "What next", 1)[1]
    assert "After you change the prompt, run your agent or chatbot again" in after, after
    assert "for a surer number" not in after, after


def test_with_failed_answers_left_to_fix_the_one_step_is_still_harder_questions(project):
    project.first(fails=set(range(4)), n=40)  # 2 Fails kept aside, 2 shown
    said = project.again({i: "pass" for i in project.kept("fail")})  # the shown ones still fail
    assert "Can't tell yet" in said and HARDER in said, said  # the line as it was
    _one_step(project, said, "add harder questions, ones your agent or chatbot may get wrong, to ")

