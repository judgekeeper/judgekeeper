"""An LLM-as-a-judge that gave every answer the same grade. Its numbers are exact (no range):
judging everything Pass, it agrees on every answer the person passes and on none the person
fails. So once one answer is marked the other way, the result is there, "needs work", with no
more marks to wait for. Before that, the usual count rule. The disagreements are listed from
the usual count on, once the hidden marks can be set aside."""

from __future__ import annotations

import pytest

from judgekeeper import start_label, targets, weighted
from tests.start_projects import promptfoo_project, split
from tests.test_front import flat, run


@pytest.mark.parametrize(("correct", "wrong", "groups"), [
    (44, 1, {"pass": (45, 1000), "fail": (0, 0)}),  # it passed every answer; 1 marked Fail
    (1, 44, {"pass": (0, 0), "fail": (45, 1000)}),  # it failed every answer; 1 marked Pass
    (1, 1, {"pass": (2, 30), "fail": (0, 0)}),
])
def test_one_answer_marked_the_other_way_is_a_result(correct, wrong, groups):
    assert targets.check(correct, wrong, groups)["check"] == "result"


@pytest.mark.parametrize(("correct", "wrong", "groups"), [
    (45, 0, {"pass": (45, 1000), "fail": (0, 0)}),  # nothing marked the other way yet
    (0, 45, {"pass": (0, 0), "fail": (45, 1000)}),
    (14, 1, {"pass": (10, 100), "fail": (5, 100)}),  # two grades: the usual rule
    (14, 1, None),
])
def test_otherwise_the_usual_count_rule(correct, wrong, groups):
    assert targets.check(correct, wrong, groups)["check"] == "too_few"


def test_the_numbers_from_the_first_mark_the_other_way_say_needs_work():
    r = start_label.describe(weighted.stratified([(1, "pass", 1000, 45, 44),
                                                  (1, "fail", 0, 0, 0)]))
    assert r["check"] == "result" and r["verdict_level"] == "not_gate"
    assert r["tpr_interval"] == [1.0, 1.0] or tuple(r["tpr_interval"]) == (1.0, 1.0)
    assert tuple(r["tnr_interval"]) == (0.0, 0.0)
    assert start_label.strata_status([(1, "pass", 1000, 45, 44), (1, "fail", 0, 0, 0)])["ready"]


@pytest.fixture
def one_grade(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    promptfoo_project(tmp_path, split(60, 0))  # it passed all 60
    return tmp_path


def _mark(here, marks: list[str]) -> start_label.StartSession:
    page = start_label.StartSession(start_label.Workspace(here))
    for item, mark in zip(page.items, marks, strict=False):
        page.update({"id": item["id"], "label": mark, "seconds": 3})
    return page


def test_the_page_and_the_terminal_say_needs_work_after_one_fail(one_grade, capsys, pages):
    run(capsys, "--no-browser")
    page = _mark(one_grade, ["pass"] * 4)
    assert not page.summary()["status"]["first"]  # only Pass so far: the usual rule
    page = _mark(one_grade, ["pass"] * 4 + ["fail"])
    status = page.summary()["status"]
    assert status["ready"] and status["headline"] == start_label.VERDICTS["not_gate"]
    _, out, _ = run(capsys)
    said = flat(out)
    assert "Result: your LLM-as-a-judge needs work." in said, said


def test_its_disagreements_wait_for_the_usual_count(one_grade, capsys, pages):
    run(capsys, "--no-browser")
    ws = start_label.Workspace(one_grade)
    page = _mark(one_grade, ["pass"] * 4 + ["fail"])
    html = start_label.live_result(ws, page, back="/?token=t")
    assert 'class="verdict' in html and "needs" in html
    assert 'id="g-easy"' not in html and 'id="g-strict"' not in html  # none listed yet
    assert not (ws.dir / "fix" / "split.json").exists()


def test_measure_names_fix_only_once_fix_can_run(one_grade, capsys, pages):
    """Fix needs 15 marks of each kind: before that, Measure's Next line is the mark one, with
    fix's own reason."""
    run(capsys, "--no-browser")
    _mark(one_grade, ["pass"] * 4 + ["fail"])
    _, out, _ = run(capsys)
    lines = out.splitlines()
    assert "Result: your LLM-as-a-judge needs work." in flat(out)
    assert "judgekeeper fix" not in out
    assert lines[-5:] == ["", "You have not marked enough answers yet to fix your",
                          "LLM-as-a-judge.", "",
                          "Next: run `judgekeeper mark` to mark more answers."], out


def test_no_ranges_to_narrow_when_none_is_shown(one_grade, capsys, pages):
    run(capsys, "--no-browser")
    _mark(one_grade, ["pass"] * 4 + ["fail"])
    _, out, _ = run(capsys)
    assert "make these ranges narrower" not in flat(out)
    assert "\n\n\n" not in out  # no empty line left in its place
