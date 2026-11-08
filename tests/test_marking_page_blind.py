"""The marking page never shows the LLM-as-a-judge's hidden grade: nothing on it changes in a way
that depends on the grade of the answer just marked. While its groups still lack marks, it says
only KEEP_MARKING, with the count of marks and the bar (the person's own Pass and Fail)."""

from __future__ import annotations

import json
import shutil

import pytest

from judgekeeper import judge_setup, start, start_label
from judgekeeper.start_label import KEEP_MARKING, StartSession, Workspace
from tests.start_projects import promptfoo_data, split


def _quiet(line=""):
    pass


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _project(root):
    """60 answers the LLM-as-a-judge passed and 17 it failed: a result needs all 17."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    (root / "results.json").write_text(json.dumps(promptfoo_data(split(60, 17))),
                                       encoding="utf-8")
    found = start.find_judge(root)
    ws = Workspace(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    return start_label.prepare(found, say=_quiet)


def _page(session) -> dict:
    """What the page gets after a mark: the status line, the counts and the bar. Not the list
    of answers and where it goes on (they name the answer just marked, which the person sees),
    nor the state's version (a time)."""
    state = session.state()
    return {k: v for k, v in state.items() if k not in ("items", "start", "version")}


def _to_the_keep_line(ws):
    """Mark in the page's order, as the LLM-as-a-judge graded, until the page asks for more
    marks with its groups short: 15 Pass and 15 Fail of the person's, but not all 17 failed."""
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
        status = session.current_status()
        if status.get("group"):
            return session
    raise AssertionError("the page never asked for more marks")


def test_the_page_says_keep_marking_with_no_count_by_grade(here):
    ws = _project(here / "p")
    session = _to_the_keep_line(ws)
    status = session.current_status()
    assert status["group"] == KEEP_MARKING == "Keep marking. Your result needs more answers."
    page = json.dumps(_page(session))
    assert "your LLM-as-a-judge passed" not in page and "failed only" not in page


def test_marking_a_passed_or_a_failed_answer_shows_the_same_page(here):
    ws = _project(here / "p")
    session = _to_the_keep_line(ws)
    marked = {i["id"] for i in session.items if i["label"]}
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    left = [i for i in groups if i not in marked]
    passed = next(i for i in left if groups[i] == "pass")
    failed = next(i for i in left if groups[i] == "fail")
    pages = []
    for name, answer in (("a", passed), ("b", failed)):
        shutil.copytree(here / "p", here / name)
        copy = StartSession(Workspace(here / name))
        copy.update({"id": answer, "label": "fail", "seconds": 5})  # the same mark each time
        pages.append(_page(copy))
    assert pages[0] == pages[1]


def test_no_page_state_on_the_way_names_a_grade(here):
    ws = _project(here / "p")
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
        page = json.dumps(_page(session))
        assert "your LLM-as-a-judge passed" not in page and "failed only" not in page, page
        assert "your LLM-as-a-judge failed" not in page, page
