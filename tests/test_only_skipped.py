"""Too early to tell with only skipped answers left to mark: the result line and Next say to
look at them again or run the eval on more questions, never just to mark more."""

from __future__ import annotations

import html
import re

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split

NEXT = ("Next: mark {answers} you skipped with `{mark}`, or run your eval on more questions and "
        "run it again. New answers are added to the ones you marked.")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _project(root, skip: int, left: int = 0):
    """60 answers; the first `skip` skipped, the last `left` not marked, the rest marked with
    one in six against the judge: too early to tell."""
    promptfoo_project(root, split(30, 30), tag=" SECRET-TEXT")
    ws = start_label.prepare(start.find_judge(root), say=lambda line: None)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    items = session.items
    for k, item in enumerate(items[:len(items) - left]):
        if k < skip:
            session.update({"id": item["id"], "deferred": True, "seconds": 3})
            continue
        g = groups[item["id"]]
        mark = g if k % 6 else ("fail" if g == "pass" else "pass")
        session.update({"id": item["id"], "label": mark, "seconds": 3})
    return ws


def _run(capsys) -> str:
    capsys.readouterr()
    main(["--no-browser", "--port", "0"])
    out = capsys.readouterr().out
    main(["--stop"])
    capsys.readouterr()
    return _flat(out)


@pytest.mark.parametrize("skip, line, answers", [
    (1, ("The only answer left is the one you skipped. Mark it now, or run your eval on more "
         "questions."), "the one"),
    (3, ("The only answers left are the 3 you skipped. Mark them now, or run your eval on more "
         "questions."), "the 3"),
])
def test_only_skipped_answers_left_says_to_look_again_or_run_the_eval(
        tmp_path, capsys, monkeypatch, skip, line, answers):
    monkeypatch.chdir(tmp_path)
    ws = _project(tmp_path, skip)
    out = _run(capsys)
    assert f"Result: too early to tell. {line}" in out, out
    assert start_label.MARK_MORE not in out and "to mark more answers" not in out, out
    mark = "judgekeeper mark --port 0 --no-browser"
    assert NEXT.format(answers=answers, mark=mark) in out, out
    report = _flat(html.unescape(re.sub(r"<[^>]+>", "", ws.report_html.read_text(encoding="utf-8"))))
    assert line in report and "to mark more answers" not in report, report
    then = NEXT.format(answers=answers, mark="judgekeeper mark").replace("`", "")
    assert then.replace("Next: mark", "Mark") in report, report


def test_an_answer_left_that_was_never_skipped_still_says_mark_more(tmp_path, capsys,
                                                                     monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, skip=1, left=1)
    out = _run(capsys)
    assert "skipped" not in out, out
    assert "to mark more answers" in out, out


def test_before_a_first_result_only_skipped_answers_left_say_the_same(tmp_path, capsys,
                                                                      monkeypatch):
    """15 Pass and 15 Fail answers, one Fail skipped: no result yet, and the skipped one is
    the only answer left that can bring it."""
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(15, 15), tag=" SECRET-TEXT")
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    skip = next(i for i in session.items if groups[i["id"]] == "fail")["id"]
    for item in session.items:
        session.update({"id": item["id"], "seconds": 3, **(
            {"deferred": True} if item["id"] == skip else {"label": groups[item["id"]]})})
    out = _run(capsys)
    line = ("The only answer left is the one you skipped. Mark it now, or run your eval on more "
            "questions.")
    assert line in out and "Next: mark answers on the page" not in out, out
    # the page where it can be marked, never the run just made again
    assert NEXT.format(answers="the one", mark="judgekeeper mark --port 0 --no-browser") in out, out
    assert not ws.report_html.exists()  # before a first result there is no report
    capsys.readouterr()
    main(["mark", "--no-browser", "--port", "0"])
    out = _flat(capsys.readouterr().out)
    main(["--stop"])
    assert line in out and "Next: mark answers on the page" not in out, out
    assert ("Next: mark the one you skipped on the page, or run your eval on more "
            "questions, then run `judgekeeper mark --port 0 --no-browser`. New answers are added "
            "to the ones you marked.") in out, out  # never `mark` again: its page is open


@pytest.mark.parametrize("pass_marks, fail_marks, side", [(10, 26, "Pass"), (26, 10, "Fail")])
def test_skipped_answers_that_cant_bring_a_result_are_named_as_skipped(
        tmp_path, capsys, monkeypatch, pass_marks, fail_marks, side):
    """40 answers, 4 skipped and the rest marked, one side 5 marks short: marking the 4 can't
    bring a result. The lines say so, and that the 4 are the ones skipped, as the page does."""
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(20, 20), tag=" SECRET-TEXT")
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    session = start_label.StartSession(ws)
    marks = ["pass"] * pass_marks + ["fail"] * fail_marks
    for k, item in enumerate(session.items):
        session.update({"id": item["id"], "seconds": 3, **(
            {"deferred": True} if k < 4 else {"label": marks[k - 4]})})
    out = _run(capsys)
    assert (f"Only 4 answers are left to mark, not enough to reach 15 {side} marks, so run "
            "your eval on more questions.") in out, out
    assert ("The only answers left are the 4 you skipped. Mark them now, or run your eval on "
            "more questions.") in out, out
    assert NEXT.format(answers="the 4", mark="judgekeeper mark --port 0 --no-browser") in out, out


@pytest.mark.parametrize("command", [["fix"], ["check"]])
def test_fix_and_check_name_the_skipped_answers_left_when_too_few(tmp_path, capsys, monkeypatch,
                                                                  command):
    """8 answers, 6 marked and 2 skipped: too few for a result, and the 2 left are the
    skipped ones. fix and check say so, in the page's words."""
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(4, 4), tag=" SECRET-TEXT")
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    session = start_label.StartSession(ws)
    for k, item in enumerate(session.items):
        session.update({"id": item["id"], "seconds": 3, **(
            {"deferred": True} if k >= 6 else {"label": "pass" if k % 2 else "fail"})})
    capsys.readouterr()
    assert main(command) == 3
    out = _flat(capsys.readouterr().out)
    assert ("The only answers left are the 2 you skipped. Mark them now, or run your eval on "
            "more questions.") in out, out
    assert NEXT.format(answers="the 2", mark="judgekeeper mark") in out, out
