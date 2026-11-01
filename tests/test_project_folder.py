"""One project folder for every command, and no dead ends in the flow across runs.

- A results file given by path keeps `.judgekeeper/` in the project the command runs from;
  every command finds the same marks and page from the project and from a folder inside it.
- Every answer marked with too few of one kind is said plainly, in the same words everywhere.
- A table judge whose grades changed in the newest results is re-checked on them (judgekeeper
  only reads files), and after a check the result and `fix` describe the newest
  LLM-as-a-judge.
- `fix` for a table judge writes the marked answers to grade again with your own code, and
  tests the new grades from a results file.
- Edge cases: read-only `.judgekeeper/`, two runs at once, exit codes, wrong flags and a
  `--judge-model` remembered.
No test calls an AI API.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import pytest

from judgekeeper import check, fix, judge_setup, page, start, start_label, textio
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data, promptfoo_project, split, table_project
from tests.test_front import flat, next_lines, run
from tests.test_only_reads import only_reads

LINK = page.LINK
ALL_MARKED = ("You've marked every answer: 28 Pass, 12 Fail. A result needs at least 15 of "
              "each.")
NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
                   "answers join the ones you marked.")
RULE_A = "Is polite and correct."
RULE_B = "Is polite, correct and short."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def no_calls(monkeypatch):
    """No program started and no network reached while the test runs."""
    with only_reads(monkeypatch):
        yield


def _index(value) -> int:
    text = value.get("question") if isinstance(value, dict) else value
    return int(re.search(r"Question (\d+)\?", str(text))[1])


def _mark(ws: Workspace, person=None, only=None) -> None:
    """The person marks the answers on the page: as the LLM-as-a-judge did, or `person[i]` for answer
    i; `only`: just those answers."""
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        i = _index(session.raw[item["id"]]["input"])
        if only is not None and i not in only:
            continue
        mark = (person or {}).get(i, groups[item["id"]])
        session.update({"id": item["id"], "label": mark, "seconds": 6})


def _next(out: str) -> str:
    return next_lines(out)[-1]


# One project folder -------------------------------------------------------------------------

def test_a_results_file_given_by_path_keeps_the_marks_in_the_project(here, capsys,
                                                                      monkeypatch):
    (here / ".git").mkdir()
    deep = "data/a/b/c/d/deep.csv"  # deeper than the search looks
    table_project(here, split(20, 16), name=deep)
    code, out, err = run(capsys, deep)
    assert code == 0, out + err
    assert (here / ".judgekeeper" / "start.json").is_file()
    assert not (here / "data" / "a" / "b" / "c" / "d" / ".judgekeeper").exists()
    assert "File:            data/a/b/c/d/deep.csv" in out
    _mark(Workspace(here), only=range(6))
    (here / "src").mkdir()
    for folder in (here, here / "src"):
        monkeypatch.chdir(folder)
        code, out, err = run(capsys)
        assert code == 0, out + err
        assert "You marked 6 answers so far: 6 Pass, 0 Fail." in out
        code, out, err = run(capsys, "mark")
        assert code == 0, out + err
        assert "You marked 6 answers so far: 6 Pass, 0 Fail." in out
        code, out, err = run(capsys, "--stop")
        assert code == 0
        assert "Closed the marking page. Your marks are saved." in out
    _mark(Workspace(here))
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    assert "Your LLM-as-a-judge has not changed since you marked your answers." in out
    assert "You have not marked enough" not in run(capsys, "fix")[1]
    assert not (here / "src" / ".judgekeeper").exists()


def test_a_results_file_outside_the_project_keeps_the_marks_here(tmp_path, capsys,
                                                                  monkeypatch):
    project, other = tmp_path / "proj", tmp_path / "other"
    (project / ".git").mkdir(parents=True)
    table_project(other, split(20, 16), name="r.csv")
    monkeypatch.chdir(project)
    code, out, err = run(capsys, "../other/r.csv")
    assert code == 0, out + err
    assert (project / ".judgekeeper" / "start.json").is_file()
    assert not (other / ".judgekeeper").exists()
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert "No eval results found" not in out


def test_stop_and_check_from_a_folder_inside_the_project(here, capsys, monkeypatch):
    (here / ".git").mkdir()
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    (here / "src" / "app").mkdir(parents=True)
    monkeypatch.chdir(here / "src" / "app")
    assert "Closed the marking page." in run(capsys, "--stop")[1]
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    assert "Your LLM-as-a-judge has not changed since you marked your answers." in out
    code, out, _ = run(capsys, "fix")
    assert "You have not marked enough answers yet" not in out


@pytest.mark.parametrize("config", [False, True])
def test_a_folder_with_two_projects_says_which_it_read(here, capsys, config):
    """A tool's config here: this folder is a project that reads the newest results below;
    with none, the two are projects of their own, and judgekeeper says to go to one."""
    if config:
        (here / "promptfooconfig.yaml").write_text("prompts: []\n", encoding="utf-8")
    for name in ("a", "b"):
        (here / name / ".git").mkdir(parents=True)
        table_project(here / name, split(20, 16))
    later = time.time() + 60
    os.utime(here / "b" / "results.csv", (later, later))
    code, out, err = run(capsys)
    if not config:
        assert code == 3 and "a/ and b/ hold eval results" in flat(out), out + err
        return
    assert code == 0, out + err
    assert ("These results are from the project in b/. The project in a/ has results too: to "
            "check them, run `judgekeeper a`.") in flat(out)


def _session_in(child, capsys, monkeypatch, marked: int) -> None:
    """A project in `child` whose session holds `marked` marks."""
    table_project(child, split(20, 16))
    monkeypatch.chdir(child)
    code, out, err = run(capsys)
    assert code == 0, out + err
    _mark(Workspace(child), only=range(marked))


@pytest.mark.parametrize("project_file", [False, True])
def test_the_folder_above_a_projects_session_says_where_it_is(here, capsys, monkeypatch,
                                                                project_file):
    """With no project file, or with results only in the session's folder, judgekeeper doesn't
    start a second session above it from the files it finds there."""
    if project_file:
        (here / ".git").mkdir()
    _session_in(here / "promptfoo", capsys, monkeypatch, 6)
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "--no-browser")
    assert code == 3, out + err
    assert ("promptfoo/ already holds your judgekeeper session (6 marks): judgekeeper keeps a "
            "project's marks in its own folder.") in flat(out), out
    assert _next(out) == ("Next: go to that folder (`cd promptfoo`), then run `judgekeeper` "
                          "there.")
    assert not (here / ".judgekeeper").exists()


@pytest.mark.parametrize("project_file", [False, True])
@pytest.mark.parametrize("command", ["fix", "check"])
def test_fix_and_check_above_a_projects_session_say_where_it_is(here, capsys, monkeypatch,
                                                                command, project_file):
    if project_file:
        (here / ".git").mkdir()
    _session_in(here / "promptfoo", capsys, monkeypatch, 6)
    monkeypatch.chdir(here)
    code, out, err = run(capsys, command)
    assert code == 3, out + err
    assert ("promptfoo/ already holds your judgekeeper session (6 marks): judgekeeper keeps a "
            "project's marks in its own folder.") in flat(out), out
    assert _next(out) == (f"Next: go to that folder (`cd promptfoo`), then run "
                          f"`judgekeeper {command}` there.")
    assert not (here / ".judgekeeper").exists()


def test_a_project_with_its_own_results_above_a_session_is_read(here, capsys, monkeypatch):
    (here / ".git").mkdir()
    _session_in(here / "promptfoo", capsys, monkeypatch, 6)
    table_project(here, split(20, 16), name="mine.csv")
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert (here / ".judgekeeper" / "start.json").is_file()


@pytest.mark.parametrize("command", [[], ["mark"]])
def test_a_folder_above_two_projects_never_run_says_to_go_to_one(here, capsys, command):
    """Results in two folders below, none here: two projects, never one session above them."""
    table_project(here / "gym", split(20, 16))
    promptfoo_project(here / "dental", split(20, 16))
    code, out, err = run(capsys, *command, "--no-browser")
    assert code == 3, out + err
    assert ("dental/ and gym/ hold eval results: judgekeeper keeps a project's marks in its "
            "own folder, so it checks one at a time.") in flat(out), out
    assert _next(out) == ("Next: go to one of those folders (`cd dental`), then run "
                          "`judgekeeper` there.")
    assert not (here / ".judgekeeper").exists()
    assert not list((here / "gym").glob(".judgekeeper*"))


@pytest.mark.parametrize("case", ["one folder", "a project", "results here too"])
def test_results_in_one_folder_below_or_a_project_are_read_as_before(here, capsys, case):
    table_project(here / "gym", split(20, 16))
    if case == "a project":
        (here / ".git").mkdir()
        table_project(here / "dental", split(20, 16))
    if case == "results here too":
        table_project(here / "dental", split(20, 16))
        table_project(here, split(20, 16), name="mine.csv")
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err


# Every answer marked, too few of one kind ---------------------------------------------------

def test_every_answer_marked_with_too_few_fails_says_so(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    started = len(pages[0])
    code, out, _ = run(capsys)
    assert code == 3, out
    assert ALL_MARKED in flat(out)
    assert _next(out) == NEXT_ALL_MARKED
    assert "keep marking" not in out and "is open" not in out
    assert len(pages[0]) == started  # no page: nothing is left to mark on it


def test_a_step_for_more_marks_than_are_left_says_run_your_eval(here, capsys):
    """After `check`, "mark 10 new answers" with one answer left, skipped: never more marks than
    the answers there are to mark."""
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws, only=range(1, 40))
    session = StartSession(ws)
    session.update({"id": next(i["id"] for i in session.items if not i["label"]),
                    "deferred": True})  # Skip
    step = "run `judgekeeper mark` to mark 10 new answers, then run `judgekeeper check` again."
    assert start_label.next_marks(ws, step, need=10) == NEXT_ALL_MARKED.removeprefix("Next: ")
    assert start_label.next_marks(ws, step, need=1) == step  # the skipped one is left to mark


def test_the_mark_command_never_repeats_the_pages_flags(here, capsys):
    promptfoo_project(here, split(28, 12))
    assert run(capsys, "--no-browser", "--port", "0")[0] == 0
    _mark(Workspace(here))
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert code == 3
    assert _next(out) == NEXT_ALL_MARKED


def test_mark_says_the_same_when_every_answer_is_marked(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    code, out, _ = run(capsys, "mark")
    assert code == 3, out
    assert ALL_MARKED in flat(out)
    assert _next(out) == NEXT_ALL_MARKED


def test_the_page_says_it_on_its_end_card(here, capsys):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws)
    status = page.marking_status(StartSession(ws))
    assert status["ready"] is False
    assert status["done"] == [ALL_MARKED, NEXT_ALL_MARKED]


def test_measure_with_every_answer_marked_does_not_offer_the_page(here, capsys):
    """Every answer marked, enough of each kind: the numbers are exact, so there is a result,
    never "the page is still open", "mark more" or "too wide to tell"."""
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    person = {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (20, 21, 22)}
    _mark(Workspace(here), person)
    code, out, _ = run(capsys)
    assert "Step 3 of 5: Measure" in out
    assert "Result: your LLM-as-a-judge is good enough to use." in out
    assert "still open" not in out and "To mark more answers" not in out
    assert "How often your LLM-as-a-judge agrees with you (estimates):" in out  # the numbers too
    assert "too wide" not in flat(out) and "too few" not in flat(out)
    assert code == 0


# Re-checks ---------------------------------------------------------------------------------

def test_a_table_judge_whose_grades_changed_is_re_checked(here, capsys, no_calls):
    verdicts = split(20, 20)
    table_project(here, verdicts)
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    flipped = list(verdicts)
    for i in (0, 4, 8, 12, 24, 28, 32):
        flipped[i] = not flipped[i]
    table_project(here, flipped)
    out = run(capsys)[1]
    assert "Your LLM-as-a-judge is the same" not in out
    assert "Your LLM-as-a-judge's grades changed on 7 of your marked answers." in flat(out)
    assert _next(out) == ("Next: run `judgekeeper check` to re-check your changed LLM-as-a-judge on "
                          "your marks.")
    _, out, _ = run(capsys, "check")
    assert "Your LLM-as-a-judge's grades changed on 7 of your marked answers." in flat(out)
    assert "Agreed with you:" in out
    assert "has not changed" not in out


def test_a_table_judge_made_worse_stays_worse(here, capsys, no_calls):
    """A "Worse" keeps the old grades as the reference: every later run says it again."""
    table_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    table_project(here, split(20, 20)[::-1])  # every grade the other way
    assert run(capsys, "check")[0] == 1
    code, out, _ = run(capsys, "check")
    assert code == 1 and "Worse" in out
    out = run(capsys)[1]
    assert "Your LLM-as-a-judge's grades changed on 40 of your marked answers." in flat(out)
    assert "Your LLM-as-a-judge is the same" not in out


def _rule_project(root, verdicts, rule):
    data = promptfoo_data(verdicts, rubric=rule)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def test_marks_added_after_a_check_are_re_checked(here, capsys, no_calls):
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rule_project(here, split(25, 25), RULE_A)
    assert run(capsys)[0] == 0
    _mark(Workspace(here), only=range(5, 45))
    _rule_project(here, split(25, 25), RULE_B)
    out = run(capsys, "check")[1]
    assert "Agreed with you:" in out
    _mark(Workspace(here), only=[*range(5), *range(45, 50)])
    _, out, _ = run(capsys, "check")
    assert "has not changed" not in out, out
    assert "You added 10 marks since your last check." in out
    assert "Agreed with you:" in out


def test_after_a_check_the_result_and_fix_are_about_the_new_judge(here, capsys, no_calls,
                                                                  monkeypatch):
    monkeypatch.setattr(fix, "make_split", lambda m, seed: (sorted(m.person), []))
    monkeypatch.setattr(fix, "_split_problem", lambda ws, d: None)  # none kept aside: by hand
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rule_project(here, split(25, 25), RULE_A)
    assert run(capsys)[0] == 0
    person = {i: "pass" for i in range(25, 31)}  # the old judge is too strict on 6
    _mark(Workspace(here), person)
    assert "You and your LLM-as-a-judge disagreed on 6 of 50 answers." in flat(run(capsys)[1])
    new = split(25, 25)
    new[25:31] = [True] * 6  # the new rule fixes those 6
    new[0] = False  # and breaks 1
    _rule_project(here, new, RULE_B)
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    code, out, _ = run(capsys)
    assert "You and your LLM-as-a-judge disagreed on 1 of 50 answers." in flat(out)
    assert "This result is about your LLM-as-a-judge as it was" not in out
    assert "Your LLM-as-a-judge is the same" in out or "Your LLM-as-a-judge changed" not in out
    run(capsys, "fix")
    mistakes = (here / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert RULE_B in mistakes and RULE_A not in mistakes
    assert mistakes.count("## [M") == 1


# fix for a table judge --------------------------------------------------------------------

def _table_needs_work(root, capsys):
    """A table judge that needs work: it passes 12 of the answers the person fails."""
    table_project(root, split(30, 30))
    assert run(capsys)[0] == 0
    _mark(Workspace(root), PERSON)
    _, out, _ = run(capsys)
    assert "Result: your LLM-as-a-judge needs work." in out, out


PERSON = {i: "fail" for i in range(12)} | {i: "pass" for i in range(30, 34)}


def test_fix_for_a_table_judge_tests_new_grades_from_a_file(here, capsys, no_calls):
    _table_needs_work(here, capsys)
    code, first, _ = run(capsys, "fix")
    assert code == 0, first
    assert fix.OWN in flat(first) and "can't ask" not in first and "rule.txt" not in first
    assert _next(first) == (
        "Next: change your LLM-as-a-judge's rule in your eval tool, grade the answers in "
        ".judgekeeper/fix/marked-answers.csv again, save the results, then run "
        "`judgekeeper fix <new results file>`.")
    # graded again as the person marked them, in a table of the same shape
    graded = [PERSON.get(i, "pass" if i < 30 else "fail") == "pass" for i in range(60)]
    table_project(here, graded, name="regraded.csv")
    code, out, _ = run(capsys, "fix", "regraded.csv")
    assert code == 0, out
    (test,) = fix.read_split(Workspace(here)).tests
    n = test["hidden"]
    assert test["n"] == n and test["broke"] == 0
    assert f"tested on the {n} marks kept aside" in flat(out)
    sides = re.findall(r"When you say \w+: agrees on (\d+) of (\d+)", out)
    assert sum(int(b) for _, b in sides[2:]) == n  # the new rule, both sides
    assert all(a == b for a, b in sides[2:])  # it agrees on every one


def test_the_report_says_where_to_run_fix(here, capsys):
    _table_needs_work(here, capsys)
    report = flat((here / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))
    assert "can&#x27;t re-run" not in report
    assert ("<p>Next, in your terminal, in your project folder:</p>"
            '<div class="cmd"><code>judgekeeper fix</code>') in report


# The folder and the page ---------------------------------------------------------------------

def test_a_read_only_folder_never_says_to_remove_it():
    assert "remove" not in textio.WORKSPACE_DENIED_NEXT
    assert textio.WORKSPACE_DENIED_NEXT == ("give your user permission to write in "
                                            ".judgekeeper/, then run `{command}`.")


def test_no_browser_again_prints_the_link(here, capsys):
    promptfoo_project(here, split(20, 16))
    assert LINK in run(capsys, "--no-browser")[1]
    _mark(Workspace(here), only=range(3))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0
    assert LINK in out and "http://127.0.0.1:" in out
    assert "still open in your browser" not in out


def test_a_second_run_waits_for_the_first_to_open_the_page(here, capsys):
    promptfoo_project(here, split(20, 16))
    ws = Workspace(here)
    start_label.make_folder(ws)
    opening = ws.dir / page.OPENING
    opening.write_text(str(os.getpid()), encoding="utf-8")
    threading.Timer(0.5, opening.unlink).start()
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "judgekeeper is already opening the marking page for this folder." in out
    assert LINK in out and "in use" not in out


# The same next step in the terminal and the report --------------------------------------------

def test_too_early_with_mistakes_says_mark_more_as_the_report_does(here, capsys):
    promptfoo_project(here, split(25, 25))
    assert run(capsys)[0] == 0
    person = {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (25, 26, 27)}
    _mark(Workspace(here), person, only=[*range(20), *range(25, 45)])
    _, out, _ = run(capsys)
    assert "Result: too early to tell." in out
    assert _next(out) == "Next: run `judgekeeper mark` to mark more answers."
    report = (here / ".judgekeeper" / "report.html").read_text(encoding="utf-8")
    assert "<code>judgekeeper mark</code> to mark more answers." in report
    assert "judgekeeper fix" not in report


# Words and exit codes --------------------------------------------------------------------------

def test_check_with_its_table_gone_says_so_in_a_sentence(here, capsys):
    table_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    (here / "results.csv").unlink()
    code, out, _ = run(capsys, "check")
    assert f"judgekeeper finds no results in this folder ({here.name})." in flat(out)
    assert "no a plain table" not in out
    assert code == 3


def test_no_results_exits_3_as_the_reference_says(here, capsys):
    from pathlib import Path

    code, out, _ = run(capsys)
    assert code == 3
    assert "No eval results found" in out
    reference = (Path(__file__).parent.parent / "docs" / "reference.md").read_text(
        encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in reference.splitlines()
            if re.match(r"\| [0-9]+ \|", line)}
    assert "nothing it can use found" not in rows["2"]
    assert "no eval results found" in rows["3"]


# A wrong flag, or a flag before the command ------------------------------------------------------

@pytest.mark.parametrize("command", ["mark", "fix", "check"])
def test_a_wrong_flag_prints_the_commands_own_usage(here, capsys, command):
    code = main([command, "--bogus"])
    _out, err = capsys.readouterr()
    assert code == 2
    assert f"usage: judgekeeper {command} " in err
    assert "usage: judgekeeper [-h] [--debug] command" not in err
    assert err.rstrip().splitlines()[-1] == (f"Next: run `judgekeeper {command} --help` to see "
                                             "the options.")


def test_a_flag_before_the_command_works(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    code, out, err = run(capsys, "--no-browser", "mark")
    assert code == 0, out + err
    assert "is not a judgekeeper command" not in out + err
    assert LINK in out


# --judge-model remembered --------------------------------------------------------------------------

def test_a_judge_model_given_once_is_remembered(here, capsys):
    table_project(here, split(20, 16))
    code, out, _ = run(capsys, "--judge-model", "openai:gpt-4")
    assert code == 0, out
    assert "openai:gpt-4 (as you said)" in out
    _mark(Workspace(here), only=range(4))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "changed" not in out
    assert _next(out) == 'Next: keep marking until "See your result" appears, then click it.'


def test_check_then_judgekeeper_keeps_the_given_model(here, capsys):
    table_project(here, split(20, 20))
    assert run(capsys, "--judge-model", "openai:gpt-4")[0] == 0
    _mark(Workspace(here))
    assert "changed" not in run(capsys)[1]
    assert judge_setup.read(Workspace(here))["setup"]["models"] == ["openai:gpt-4"]
    assert check.full(".", check.Said()) == 0
    assert start.GIVEN_BY_YOU in json.dumps(Workspace(here).data())


def _remembered_model(here, capsys, model="openai:gpt-4"):
    """A table project marked after --judge-model, so the model is remembered, not in the file."""
    table_project(here, split(20, 20))
    assert run(capsys, "--judge-model", model)[0] == 0
    _mark(Workspace(here))
    assert check.full(".", check.Said()) == 0
    capsys.readouterr()


def test_check_reads_a_new_file_that_names_the_same_model_as_the_one_given_before(here, capsys):
    _remembered_model(here, capsys)
    table_project(here, split(20, 20), name="regrade.csv", model="openai:gpt-4")
    code, out, err = run(capsys, "check", "regrade.csv")
    assert code == 0, out + err
    assert "drop --judge-model" not in out + err
    assert "model changed" not in flat(out)


def test_check_names_a_model_change_in_a_new_file_after_a_model_was_given(here, capsys):
    _remembered_model(here, capsys)
    table_project(here, split(20, 20), name="regrade.csv", model="openai:gpt-4.1")
    _, out, err = run(capsys, "check", "regrade.csv")
    assert "drop --judge-model" not in out + err
    assert "model changed: openai:gpt-4 -> openai:gpt-4.1" in flat(out).replace("'s model", " model")


def test_fix_reads_a_new_file_that_names_its_model_after_a_model_was_given(here, capsys):
    _remembered_model(here, capsys)
    table_project(here, split(20, 20), name="regrade.csv", model="openai:gpt-4")
    _, out, err = run(capsys, "fix", "regrade.csv")
    assert "drop --judge-model" not in out + err
    assert "can't read regrade.csv" not in flat(out + err)


def test_a_model_given_now_still_conflicts_with_the_files_model_column(here, capsys):
    table_project(here, split(20, 20), model="openai:gpt-4.1")
    code, _, err = run(capsys, "--judge-model", "openai:gpt-4")
    assert code == 2
    assert ("results.csv already names the LLM-as-a-judge's model (openai:gpt-4.1): drop "
            "--judge-model") in flat(err)
