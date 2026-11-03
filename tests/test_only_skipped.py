"""Too early to tell with only skipped answers left to mark: the result line and Next say to
look at them again or run the eval on more questions, never just to mark more."""

from __future__ import annotations

import html
import re

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split

NEXT = ("Next: look at your skipped {answers} again with `{mark}`, or run your eval on more "
        "questions, then run `{mark}`: the new answers join the ones you marked.")


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
    (1, ("Only your 1 skipped answer is left to mark: look at it again, or run your eval on "
         "more questions."), "answer"),
    (3, ("Only your 3 skipped answers are left to mark: look at them again, or run your eval "
         "on more questions."), "answers"),
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
    report = _flat(html.unescape(re.sub(r"<[^>]+>", "", ws.report_html.read_text("utf-8"))))
    assert line in report and "to mark more answers" not in report, report
    then = NEXT.format(answers=answers, mark="judgekeeper mark").replace("`", "")
    assert then.replace("Next: look", "Look") in report, report


def test_an_answer_left_that_was_never_skipped_still_says_mark_more(tmp_path, capsys,
                                                                     monkeypatch):
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, skip=1, left=1)
    out = _run(capsys)
    assert "skipped" not in out, out
    assert "to mark more answers" in out, out
