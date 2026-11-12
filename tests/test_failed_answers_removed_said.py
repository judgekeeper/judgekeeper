"""failed-answers.md goes when the result lists no answer failed. However it goes (a run, a mark
on the page, the page's result), the next run says so once."""

from __future__ import annotations

from judgekeeper import start_label
from tests.test_answers_without_grades import _session
from tests.test_fixed_and_broke import Project, _mark, _write, here, project  # noqa: F401

REMOVED = ("No answer you marked Fail is listed now, so judgekeeper removed "
           ".judgekeeper/fix/failed-answers.md.")


def _path(p: Project):
    return p.here / ".judgekeeper" / "fix" / "failed-answers.md"


def _new_answers(p: Project, questions) -> None:
    p.round += 1
    for i in questions:
        p.outs[i] = f"Answer {i}, take {p.round + 1}."
    _write(p.here, p.outs)


def _see_result(p: Project) -> None:
    """The page's "See your result": the result stored from the marks so far."""
    ws = start_label.Workspace(p.here)
    start_label.live_result(ws, _session(p.here))


def test_removed_by_page_marks_and_the_page_result_is_said_by_the_next_run(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5, 6, 7}, n=20)
    assert _path(project).is_file()
    shown, kept = project.shown("fail"), project.kept("fail")
    assert kept  # Fails kept aside stay Fails
    _new_answers(project, shown + kept)
    project.run()  # the page opens on the new answers
    _mark(project.here, {i: "pass" for i in shown} | {i: "fail" for i in kept})
    assert not _path(project).is_file()  # the page's marks removed it
    _see_result(project)  # and stored a result that lists none
    said = project.run()
    assert said.count(REMOVED) == 1 and said.index(REMOVED) < said.index("Next:"), said
    assert REMOVED not in project.run()


def test_removed_in_a_later_round_with_every_answer_passed_is_said(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5, 6, 7}, n=20)
    _new_answers(project, range(20))
    project.run()
    _mark(project.here, dict.fromkeys(range(20), "pass"))
    _see_result(project)
    said = project.run()
    assert "You passed 20 of 20 answers." in said and said.count(REMOVED) == 1, said
    assert not _path(project).is_file()


def test_removed_by_page_marks_alone_is_said_once(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5, 6, 7}, n=20)
    shown = project.shown("fail")
    _mark(project.here, {})  # nothing
    page = _session(project.here)
    for item in page.items:  # each visible Fail changed to Pass on the page
        if item["label"] == "fail" and int(page.raw[item["id"]]["input"].split()[3][:-1]) in shown:
            page.update({"id": item["id"], "label": "pass", "seconds": 3})
    assert not _path(project).is_file()
    said = project.run()
    assert said.count(REMOVED) == 1, said
    assert REMOVED not in project.run()


def test_back_before_a_run_is_not_said(project):  # noqa: F811
    project.first(fails={0, 1, 2, 3, 4, 5, 6, 7}, n=20)
    shown = project.shown("fail")
    page = _session(project.here)
    items = [i for i in page.items if i["label"] == "fail"
             and int(page.raw[i["id"]]["input"].split()[3][:-1]) in shown]
    for item in items:
        page.update({"id": item["id"], "label": "pass", "seconds": 3})
    assert not _path(project).is_file()
    page.update({"id": items[0]["id"], "label": "fail", "seconds": 3})  # one Fail again
    assert _path(project).is_file()
    assert REMOVED not in project.run()
