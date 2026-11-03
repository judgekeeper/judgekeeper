"""Lines that say only what is true and what a person needs: why a result still waits, the
results file a check reads, a path that is not there, and a --port the open page kept."""

from __future__ import annotations

from judgekeeper.start_label import StartSession, Workspace
from tests import test_fix
from tests.start_projects import split, table_project
from tests.test_fix import _main

here = test_fix.here  # the fixture: a project folder


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_marks_short_on_one_group_say_how_many_each_has(here, capsys):
    """19 Pass and 19 Fail meet the 15 of each; 10 marks on answers the LLM-as-a-judge failed
    don't meet the 20: the line says how many each group has."""
    table_project(here, split(50, 20))
    _main(capsys, "--no-browser", "--port", "0")
    session = StartSession(Workspace(here))
    passed = [i for i in session.items if session.groups[i["id"]] == "pass"][:28]
    failed = [i for i in session.items if session.groups[i["id"]] == "fail"][:10]
    for k, item in enumerate(passed + failed):
        label = "pass" if k < 19 else "fail"
        session.update({"id": item["id"], "label": label, "seconds": 4})
    _, said = _main(capsys, "--no-browser", "--port", "0")
    said = _flat(said)
    assert "That's not enough for a result yet." in said, said
    assert ("You marked 10 answers your LLM-as-a-judge failed. A result needs 20."
            ) in said, said


def test_a_check_of_the_marked_file_names_it_as_results(here, capsys):
    table_project(here, split(30, 30))
    _main(capsys, "--no-browser", "--port", "0")
    session = StartSession(Workspace(here))
    for item in session.items:
        session.update({"id": item["id"], "label": session.groups[item["id"]], "seconds": 4})
    _main(capsys, "--no-browser", "--port", "0")
    _, said = _main(capsys, "check")
    assert "Results: results.csv" in said and "New results:" not in said, said
    other = table_project(here / "v2", split(30, 30), name="results.csv")
    _, said = _main(capsys, "check", str(other.relative_to(here)))
    assert "New results: v2/results.csv" in said, said


def test_a_path_that_is_not_there_says_no_step(here, capsys):
    code, said = _main(capsys, "banana")
    assert code != 0 and "Step 1 of 5" not in said and "banana" in said, said


def test_a_port_the_open_page_kept_is_said(here, capsys):
    table_project(here, split(30, 30))
    _main(capsys, "--no-browser", "--port", "9781")
    _, said = _main(capsys, "--no-browser", "--port", "9783")
    assert "so --port 9783 was not used." in _flat(said), said


def test_check_with_too_few_answers_left_says_what_the_plain_run_says(here, capsys):
    """24 answers, 20 marked (6 Fail), 4 left: no mark can bring 15 Fail marks, so check and
    fix, as the plain run, say to run the eval on more questions, never to mark more."""
    table_project(here, split(12, 12))
    _main(capsys, "mark", "--no-browser", "--port", "0")
    session = StartSession(Workspace(here))
    for k, item in enumerate(session.items[:20]):
        session.update({"id": item["id"], "label": "fail" if k < 6 else "pass", "seconds": 4})
    _, plain = _main(capsys, "--no-browser", "--port", "0")
    _, said = _main(capsys, "check")
    _, fixing = _main(capsys, "fix")
    line = ("Only 4 answers are left to mark, not enough to reach 15 Fail marks, so run your "
            "eval on more questions.")
    for out in (plain, said, fixing):
        assert line in _flat(out), out
    for out in (said, fixing):
        assert "to mark more" not in out and "Next: run your eval on more questions" in out, out
