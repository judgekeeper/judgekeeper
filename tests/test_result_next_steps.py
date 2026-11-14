"""Every result with no grade ends with a Next line that is true for it: no Fail, a fix with
no Fail, and three changes tested on the questions kept aside."""
from __future__ import annotations

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
    assert _next(said) == _next(project.run()), said  # as the result says it


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
