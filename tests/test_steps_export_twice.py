"""A Label Studio export where one run is in more than one task (label-these.json imported
twice, or a newer one on top) is refused like a runs file with an id used twice: each run
would count more than once, and the picks keyed by run would overwrite each other. It says
how many runs repeat and the first one's task ids, never a step's text. Synthetic data only."""

from __future__ import annotations

import copy

import pytest

from tests.test_steps import (
    annotation,
    people_first,
    prediction,
    project,
    reviewer_first,
    run,
    save,
    task,
)


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


FAKE_KEY = "sk-ant-api03-FAKEKEYaaaaaaaaaaaaaaaaaaaa"
NEXT = ("Next: export again from a Label Studio project where you imported "
        ".judgekeeper/steps/label-these.json once, then run `judgekeeper steps EXPORT.json`.")


def twice(tasks: list[dict]) -> list[dict]:
    """The tasks, then a copy of each as a second import makes them: Label Studio's next ids."""
    again = copy.deepcopy(tasks)
    for k, t in enumerate(again):
        t["id"] = 100 + len(tasks) + k
    return tasks + again


def error_lines(out: str, err: str) -> list[str]:
    return [x for x in (out + err).splitlines() if x.startswith(("error: ", "Next: "))]


def test_the_same_export_twice_is_refused_and_says_where(here, capsys):
    save(here, twice(project()))
    code, out, err = run(capsys, "steps", "export.json")
    assert code == 2, out + err
    assert error_lines(out, err) == [
        ("error: 40 runs are each in more than one task of export.json (r0 is in tasks 100 "
         "and 140), so their labels would count more than once."),
        NEXT]
    assert "Runs you say went wrong" not in out and "made up step" not in out + err
    assert not (here / ".judgekeeper" / "steps" / "result.json").exists()


def test_one_run_again_with_another_label_is_refused_too(here, capsys):
    tasks = project()
    tasks.append(task(40, [annotation(2, 2)], [prediction("reviewer-a", 2)], run_id="r30"))
    save(here, tasks)
    code, out, err = run(capsys, "steps", "export.json")
    assert code == 2, out + err
    assert error_lines(out, err)[0] == (
        "error: 1 run is in more than one task of export.json (r30 is in tasks 130 and 140), "
        "so its labels would count more than once.")


def test_three_copies_name_every_task(here, capsys):
    tasks = project(4)
    tasks += [task(4 + k, [annotation(2, 0)], run_id="r1") for k in range(2)]
    save(here, tasks)
    _, out, err = run(capsys, "steps", "export.json")
    assert "(r1 is in tasks 101, 104 and 105)" in error_lines(out, err)[0]


def test_a_key_shaped_run_id_is_never_said(here, capsys):
    tasks = [task(i, [annotation(2, people_first(i))], [prediction("m", reviewer_first(i))],
                  run_id=FAKE_KEY if i in (0, 1) else f"r{i}") for i in range(4)]
    save(here, tasks)
    code, out, err = run(capsys, "steps", "export.json")
    assert code == 2 and FAKE_KEY not in out + err
    assert "([REDACTED] is in tasks 100 and 101)" in error_lines(out, err)[0]


def test_an_export_with_each_run_once_still_reads(here, capsys):
    save(here, project())
    code, out, err = run(capsys, "steps", "export.json")
    assert code == 0 and "Read 40 runs from export.json" in out, out + err
