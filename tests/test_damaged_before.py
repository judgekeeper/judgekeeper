"""A damaged fix/before.json (the last two answers of each question) is said in the run that
replaces it, and the result after those answers are marked says "Can't compare" (the one
change before it can't be compared); the next change is compared as usual."""

from __future__ import annotations

import json

import pytest

from tests.test_fixed_and_broke import Project, _before, _mark, _result, _write

DAMAGED = "Can't compare with your last answers: .judgekeeper/fix/before.json is damaged."
REPEATS = {30: "What is question 0?", 31: "What is question 1?"}  # asked twice


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def project(here, capsys, pages):
    return Project(here, capsys)


def _damage(project) -> None:
    path = _before(project.here)
    path.write_text(path.read_text(encoding="utf-8")[:40] + "{bad json", encoding="utf-8")


def _after_round_two(project, repeats: bool = False) -> list[int]:
    """Two rounds of answers marked; the questions kept aside that failed, as round two fixed
    some. With `repeats`, two questions are asked twice."""
    if repeats:
        project.outs = {i: f"First answer {i}." for i in range(32)}
        project.marks = {i: "fail" if i < 12 or i == 30 else "pass" for i in range(32)}
        _write(project.here, project.outs, REPEATS)
        project.run()
        _mark(project.here, {i: m for i, m in project.marks.items() if i < 30})
        project.run()
    else:
        project.first(fails=set(range(12)), n=30)
    kept = project.kept("fail")
    for i in kept[:4]:
        project.outs[i] = f"Answer {i}, take 2."
    _write(project.here, project.outs, REPEATS if repeats else None)
    project.run()
    _mark(project.here, {i: "pass" for i in kept[:4]})
    project.run()
    return kept


def _new_file(project, ids: list[int], take: int, repeats: bool = False) -> str:
    for i in ids:
        project.outs[i] = f"Answer {i}, take {take}."
    _write(project.here, project.outs, REPEATS if repeats else None)
    return project.run()


def _since(project) -> dict | None:
    return _result(project.here).get("since")


def test_the_run_that_replaces_a_damaged_before_says_so_and_keeps_it_said_until_a_result(project):
    kept = _after_round_two(project)
    _damage(project)
    said = _new_file(project, kept[4:7] + project.shown()[:3], 3)
    assert DAMAGED in said
    assert json.loads(_before(project.here).read_text(encoding="utf-8")).get("repaired") is True


def test_the_result_after_marking_says_it_cant_compare_and_the_next_change_compares(project):
    kept = _after_round_two(project)
    _damage(project)
    changed = kept[4:7] + project.shown()[:3]
    _new_file(project, changed, 3)
    _mark(project.here, {i: "pass" for i in changed})
    said = project.run()
    assert DAMAGED in said
    assert _since(project) == {"damaged": True}
    left = project.kept("fail")
    _new_file(project, left[:3], 4)
    _mark(project.here, {i: "pass" for i in left[:3]})
    said = project.run()
    assert DAMAGED not in said
    assert (_since(project) or {}).get("kept") and "damaged" not in _since(project)


def test_a_damaged_before_with_a_question_asked_twice_says_it_and_compares_next(project):
    kept = _after_round_two(project, repeats=True)
    _damage(project)
    changed = kept[4:7] + [30, 31]
    said = _new_file(project, changed, 3, repeats=True)
    assert DAMAGED in said
    _mark(project.here, {i: "pass" for i in [*changed[:3], 0, 1]})  # the repeats: by question
    said = project.run()
    assert DAMAGED in said and _since(project) == {"damaged": True}
    left = project.kept("fail")
    _new_file(project, left[:2], 4, repeats=True)
    _mark(project.here, {i: "pass" for i in left[:2]})
    project.run()
    assert (_since(project) or {}).get("fixed") is not None


def test_nothing_is_said_when_before_is_not_damaged(project):
    kept = _after_round_two(project)
    said = _new_file(project, kept[4:7], 3)
    assert "damaged" not in said
    assert not json.loads(_before(project.here).read_text(encoding="utf-8")).get("repaired")
