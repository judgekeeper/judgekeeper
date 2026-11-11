"""What the result says of answers kept aside: when every answer failed is kept aside, it says
so where the list would be; once the set kept aside has tested 3 changes, it says they are all
shown now, and says "tested 3 changes" only once."""

from __future__ import annotations

from html import unescape

from tests.test_answers_without_grades import _live, _seen
from tests.test_fixed_and_broke import Project, _report, here, project  # noqa: F401

ALL_SHOWN = "The questions kept aside are all shown now."
TESTED = "tested 3 changes"


def _page(folder) -> str:
    return " ".join(unescape(_seen(_live(folder))).split())


def test_one_fail_kept_aside_says_it_is(project):  # noqa: F811
    project.first(fails={0, 1}, n=12)  # 2 Fails: 1 kept aside, 1 shown
    shown = project.shown("fail")
    project.again({i: "pass" for i in shown})  # the shown Fail fixed: only the kept one left
    page = _page(project.here)
    assert "You failed 1 answer. It is kept aside to test your next change." in page, page
    assert "Answers you failed" not in page


def test_fails_all_kept_aside_say_they_are(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3}, n=12)  # 4 Fails: 2 kept aside, 2 shown
    project.again({i: "pass" for i in project.shown("fail")})
    page = " ".join(unescape(_seen(_report(project.here))).split())
    assert "You failed 2 answers. They are kept aside to test your next change." in page, page


def test_after_the_set_is_used_up_it_says_all_are_shown(project):  # noqa: F811
    project.first(fails=set(range(12)), n=20)
    kept = project.kept("fail")
    for m in ("pass", "fail", "pass"):
        said = project.again({i: m for i in kept})
    assert ALL_SHOWN not in said  # still kept aside: the 3 changes line says what to do
    said = project.again({i: "fail" for i in kept})  # the set is used up now
    page = _page(project.here)
    for seen in (said, page):
        assert seen.count(ALL_SHOWN) == 1, seen
        assert seen.count(TESTED) == 1, seen  # the 3 changes line says it; this one does not
