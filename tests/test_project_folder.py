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

from judgekeeper import __version__, check, find, fix, judge_setup, page, start, start_label, textio
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data, promptfoo_project, split, table_project, unwrapped
from tests.test_flow_across_runs import now_part
from tests.test_front import flat, next_lines, run
from tests.test_only_reads import only_reads

LINK = page.LINK
ALL_MARKED = ("You've marked every answer: 28 Pass, 12 Fail. A result needs at least 15 of "
              "each.")
NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`. New answers "
                   "are added to the ones you marked.")
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


@pytest.mark.parametrize("marker", [".git", "pyproject.toml"])
@pytest.mark.parametrize("path_first", [True, False])
def test_a_file_given_in_a_folder_inside_the_project_keeps_one_set_of_marks(
        here, capsys, monkeypatch, marker, path_first):
    """With no marks above, a results file given by path starts them in the folder you run
    in, as plain `judgekeeper` does there: one set of marks either way."""
    if marker == ".git":
        (here / ".git").mkdir()
    else:
        (here / marker).write_text("", encoding="utf-8")
    table_project(here / "evals", split(20, 16))
    monkeypatch.chdir(here / "evals")
    first, then = (["results.csv"], []) if path_first else ([], ["results.csv"])
    code, out, err = run(capsys, *first, "--no-browser")
    assert code == 0, out + err
    assert (here / "evals" / ".judgekeeper" / "start.json").is_file()
    assert not (here / ".judgekeeper").exists()
    _mark(Workspace(here / "evals"), only=range(3))
    assert run(capsys, "--stop")[0] == 0
    code, out, err = run(capsys, *then, "--no-browser")
    assert code == 0, out + err
    assert "You marked 3 answers so far: 3 Pass, 0 Fail." in out
    assert not (here / ".judgekeeper").exists()


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


# A git repository is one project ---------------------------------------------------------

MARKERS = ("pyproject.toml", "package.json", ".git", "judgekeeper.toml", "setup.py")


def _marker(folder, marker) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if marker == ".git":
        (folder / ".git").mkdir()
    elif marker is not None:
        (folder / marker).write_text("", encoding="utf-8")


def _repo_with_sessions(root, capsys, monkeypatch, names=("a", "b"), marker=".git"):
    """A folder `root` (a project of its own by `marker`, or none) whose results are only in
    folders below that each hold a session of their own."""
    _marker(root, marker)
    for i, name in enumerate(names):
        _session_in(root / name, capsys, monkeypatch, 2 + i)
    monkeypatch.chdir(root)


def _outer_with_marks(here, capsys) -> bytes:
    (here / "pyproject.toml").write_text("", encoding="utf-8")
    table_project(here, split(20, 16), name="outer.csv", tag="outer")
    assert run(capsys, "--no-browser")[0] == 0
    _mark(Workspace(here), only=range(8))
    return (here / ".judgekeeper" / "marks.jsonl").read_bytes()


@pytest.mark.parametrize("names", [("a", "b"), ("a",)])
@pytest.mark.parametrize("marker", MARKERS)
def test_a_project_folder_never_reads_the_project_above_it(here, capsys, monkeypatch, names,
                                                           marker):
    before = _outer_with_marks(here, capsys)
    _repo_with_sessions(here / "inner", capsys, monkeypatch, names, marker)
    code, out, err = run(capsys, "--no-browser")
    assert code == 3, out + err
    assert "Reading the project folder above" not in out
    assert "already hold" in flat(out) and "your judgekeeper session" in flat(out), out
    assert not (here / "inner" / ".judgekeeper").exists()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
    assert "--stop" not in out
    stop = flat(run(capsys, "--stop")[1])  # the pages below, never the one above
    assert ("Marking pages are open in a/ and b/." if len(names) > 1
            else "Closed the marking page.") in stop, stop
    assert page.is_open(here / ".judgekeeper")


@pytest.mark.parametrize("names", [("a", "b"), ("a",)])
def test_a_folder_inside_a_project_never_starts_marks_on_another_folders_answers(
        here, capsys, monkeypatch, names):
    before = _outer_with_marks(here, capsys)
    _repo_with_sessions(here / "inner", capsys, monkeypatch, names, marker=None)
    code, out, err = run(capsys, "--no-browser")
    assert code == 3, out + err
    assert out.splitlines()[:3] == [f"judgekeeper {__version__}", "", "Step 1 of 5: Find"], out
    assert "already hold" in flat(out) and "your judgekeeper session" in flat(out), out
    assert "To check it, run" not in flat(out)
    assert not (here / "inner" / ".judgekeeper").exists()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


def test_results_in_one_folder_of_a_git_repo_are_read_as_before(here, capsys, monkeypatch):
    (here / "pyproject.toml").write_text("", encoding="utf-8")
    table_project(here, split(20, 16), name="outer.csv", tag="outer")
    (here / "inner" / ".git").mkdir(parents=True)
    table_project(here / "inner" / "evals", split(20, 16))
    monkeypatch.chdir(here / "inner")
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "File:            evals/results.csv" in out
    assert (here / "inner" / ".judgekeeper" / "start.json").is_file()
    assert not (here / ".judgekeeper").exists()


def test_a_session_below_and_results_in_another_folder_are_two_projects(here, capsys,
                                                                          monkeypatch):
    (here / ".git").mkdir()
    _session_in(here / "sub1", capsys, monkeypatch, 4)
    table_project(here / "sub2", split(20, 16), tag="two")
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "--no-browser")
    assert code == 3, out + err
    assert "belong to" not in out
    assert ("sub1/ and sub2/ hold eval results: judgekeeper keeps a project's marks in its "
            "own folder, so it checks one at a time.") in flat(out), out
    assert _next(out) == ("Next: go to one of those folders (`cd sub1`), then run "
                          "`judgekeeper` there.")
    assert not (here / ".judgekeeper").exists()


@pytest.mark.parametrize("command", [[], ["mark"]])
def test_a_file_in_a_project_with_its_own_session_is_never_added_here(here, capsys,
                                                                     monkeypatch, command):
    (here / ".git").mkdir()
    _session_in(here / "sub1", capsys, monkeypatch, 4)
    table_project(here / "sub2", split(20, 16), tag="two")
    monkeypatch.chdir(here)
    assert run(capsys, "sub2/results.csv", "--no-browser")[0] == 0
    _mark(Workspace(here), only=range(3))
    start_json = (here / ".judgekeeper" / "start.json").read_bytes()
    marks_before = (here / "sub1" / ".judgekeeper" / "marks.jsonl").read_bytes()
    code, out, err = run(capsys, *command, "sub1/results.csv", "--no-browser")
    assert code == 3, out + err
    assert ("These results belong to the project in sub1/. To check them, run `judgekeeper` "
            "in sub1/.") in flat(out), out
    assert "haven't seen" not in out
    assert (here / ".judgekeeper" / "start.json").read_bytes() == start_json
    assert (here / "sub1" / ".judgekeeper" / "marks.jsonl").read_bytes() == marks_before


@pytest.mark.parametrize("session", [False, True])
def test_a_file_in_a_nearby_project_is_refused_with_or_without_its_session(
        here, capsys, monkeypatch, session):
    """From a folder with no project, a results file in a project below belongs to that
    project, whether it has been used or not: never a session here."""
    (here / "f02").mkdir()
    (here / "f02" / "pyproject.toml").write_text("[project]\nname = 'f02'\n", encoding="utf-8")
    if session:
        _session_in(here / "f02" / "evals", capsys, monkeypatch, 0)
        run(capsys, "--stop")
    else:
        table_project(here / "f02" / "evals", split(20, 16))
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "f02/evals/results.csv", "--no-browser")
    assert code == 3, out + err
    assert "These results belong to the project in f02/" in flat(out), out
    assert not (here / ".judgekeeper").exists()


@pytest.mark.parametrize("session", [False, True])
def test_check_of_a_file_in_a_nearby_project_names_that_project(here, capsys, monkeypatch,
                                                                session):
    """`check f02/evals/results.csv` from a folder with no project says whose results they
    are and where to check them, as the plain run does."""
    (here / "f02").mkdir()
    (here / "f02" / "pyproject.toml").write_text("[project]\nname = 'f02'\n", encoding="utf-8")
    if session:
        _session_in(here / "f02" / "evals", capsys, monkeypatch, 0)
        run(capsys, "--stop")
    else:
        table_project(here / "f02" / "evals", split(20, 16))
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "check", "f02/evals/results.csv")
    assert code == 3, out + err
    owner = "f02/evals" if session else "f02"  # where the session is, else the project
    assert (f"These results belong to the project in {owner}/. To check them, run "
            f"`judgekeeper` in {owner}/.") in flat(out), out
    assert "No marks in" not in out and not (here / ".judgekeeper").exists()


def test_one_project_below_and_none_here_is_checked_in_its_own_folder(here, capsys,
                                                                       monkeypatch):
    """A folder with no project and one project below it with results: the plain run sends
    you there, never starts a session here."""
    (here / "p2").mkdir()
    (here / "p2" / "pyproject.toml").write_text("[project]\nname = 'p2'\n", encoding="utf-8")
    table_project(here / "p2", split(20, 16))
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert code == 3, out + err
    assert ("These results belong to the project in p2/. To check them, run `judgekeeper` "
            "in p2/.") in flat(out), out
    assert not (here / ".judgekeeper").exists()


def _projects_in_outer(here, names) -> None:
    for name in names:
        (here / "outer" / name).mkdir(parents=True)
        (here / "outer" / name / "pyproject.toml").write_text(
            f"[project]\nname = '{name}'\n", encoding="utf-8")
        table_project(here / "outer" / name, split(20, 16), tag=name)


def test_one_project_below_a_folder_given_by_path_is_named_from_here(here, capsys,
                                                                      monkeypatch):
    _projects_in_outer(here, ["p2"])
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "outer", "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert code == 3, out + err
    assert ("These results belong to the project in outer/p2/. To check them, run "
            "`judgekeeper` in outer/p2/.") in flat(out), out
    assert _next(out) == "Next: run `judgekeeper` in outer/p2/."


def test_projects_below_a_folder_given_by_path_are_named_from_here(here, capsys, monkeypatch):
    _projects_in_outer(here, ["a", "b"])
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "outer", "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert code == 3, out + err
    assert "outer/a/ and outer/b/ hold eval results" in flat(out), out
    assert _next(out) == ("Next: go to one of those folders (`cd outer/a`), then run "
                          "`judgekeeper` there.")


def test_a_session_below_a_folder_given_by_path_is_named_from_here(here, capsys, monkeypatch):
    (here / "outer" / ".git").mkdir(parents=True)
    _session_in(here / "outer" / "sub1", capsys, monkeypatch, 4)
    run(capsys, "--stop")
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "outer", "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert code == 3, out + err
    assert "outer/sub1/ already holds your judgekeeper session (4 marks)" in flat(out), out
    assert _next(out) == ("Next: go to that folder (`cd outer/sub1`), then run `judgekeeper` "
                          "there.")


def test_results_in_one_plain_folder_below_still_start_here(here, capsys, monkeypatch):
    """evals/ is no project of its own: its results are this folder's."""
    table_project(here / "evals", split(20, 16))
    monkeypatch.chdir(here)
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert code == 0, out + err
    assert (here / ".judgekeeper" / "start.json").is_file()


@pytest.mark.parametrize(("where", "command", "given", "shown"), [
    ("p11/sub", "fix", "..", ".."), ("", "fix", "p11", "p11"), ("", "check", "p11", "p11")])
def test_too_few_marks_name_the_project_in_the_mark_command(here, capsys, monkeypatch, where,
                                                             command, given, shown):
    """Run from another folder, the mark command it prints runs in the project, named from
    where you are."""
    (here / "p11" / "sub").mkdir(parents=True)
    (here / "p11" / "pyproject.toml").write_text("[project]\nname = 'p11'\n", encoding="utf-8")
    table_project(here / "p11", split(20, 16))
    monkeypatch.chdir(here / "p11")
    assert run(capsys, "--no-browser", "--port", "0")[0] == 0
    run(capsys, "--stop")
    _mark(Workspace(here / "p11"), only=range(3))
    monkeypatch.chdir(here / where)
    code, out, err = run(capsys, command, given)
    assert code != 0, out + err
    assert f"Next: run `judgekeeper mark {shown}` to mark more answers." in flat(out), out


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
    the answers there are to mark, and the skipped one is to look at again."""
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws, only=range(1, 40))
    session = StartSession(ws)
    session.update({"id": next(i["id"] for i in session.items if not i["label"]),
                    "deferred": True})  # Skip
    step = "run `judgekeeper mark` to mark 10 new answers, then run `judgekeeper check` again."
    skipped = start_label.next_only_skipped(1, "judgekeeper mark")
    assert start_label.next_marks(ws, step, need=10) == skipped
    assert start_label.next_marks(ws, step, need=1) == skipped  # only the skipped one is left


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
    assert "How often your LLM-as-a-judge agrees with you:" in out  # the numbers too
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
    assert ("Your answers were graded again in results.csv, and 7 of your marked answers got a "
            "different grade. The numbers below still use the grades from before.") in flat(out)
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


FLIP = (0, 4, 8, 12, 24, 28, 32)  # the person disagrees with the first grades on these


def _checked_outside(here, capsys, worse: bool) -> None:
    """Marked against a table judge in evals/; a check passes on evals/support-evals-v2.csv,
    graded as the person marks (`worse`: then a check finds a file outside the project worse);
    or (not `worse`) the passing check is of a file outside the project."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/support-evals.csv")
    assert run(capsys)[0] == 0
    person = [(not v) if i in FLIP else v for i, v in enumerate(verdicts)]
    _mark(Workspace(here), {i: "pass" if v else "fail" for i, v in enumerate(person)})
    run(capsys)
    if worse:
        table_project(here, person, name="evals/support-evals-v2.csv")
        assert run(capsys, "check", "evals/support-evals-v2.csv")[0] == 0
        outside = table_project(here.parent / "outside", [not v for v in person])
        assert run(capsys, "check", str(outside))[0] == 1
    else:
        outside = table_project(here.parent / "outside", person)
        assert run(capsys, "check", str(outside))[0] == 0


def test_after_a_worse_check_the_judge_is_the_one_before_it(here, capsys, no_calls):
    """The last check found its LLM-as-a-judge worse, so it was not taken on: the one marks
    test is the one from before that check, not the one it re-tested."""
    _checked_outside(here, capsys, worse=True)
    out = flat(run(capsys)[1])
    assert "the one your last check re-tested" not in out, out
    assert ("Your answers were graded again. Your LLM-as-a-judge is the one you had before your "
            "last check, so your marks still test it.") in out, out


def test_a_table_judge_back_on_the_marked_model_says_so(here, capsys, no_calls):
    """A check took on another model from a file outside the project; a plain run keeps that
    result, and the project's own file, typed, graded by the model the marks were made with,
    is read again: "back", as for promptfoo."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]  # the other model differs on one answer: not worse
    outside = table_project(here.parent / "outside", other, model="bike-grader-v2")
    assert run(capsys, "check", str(outside))[0] == 0
    out = flat(run(capsys)[1])
    assert "back to the one you marked with" not in out, out
    assert "in ../outside/results.csv, the file your last check read." in out, out
    out = flat(run(capsys, "evals/results.csv")[1])
    assert ("Your LLM-as-a-judge is back to the one you marked with (bike-grader-v1). The result "
            "from your marks still stands.") in out, out
    assert "changed since your marks" not in out


def test_a_plain_check_reads_the_file_the_last_check_read_as_a_plain_run_does(
        here, capsys, no_calls):
    """A check took on another model from a file outside the project, which the search never
    finds: a plain `check` keeps it, as a plain run does, never moving the marks back to the
    project's older file. Newer results of the eval are read instead."""
    import os

    verdicts = split(20, 20)
    mine = table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]
    outside = table_project(here.parent / "outside", other, model="bike-grader-v2")
    assert run(capsys, "check", str(outside))[0] == 0
    code, out = run(capsys, "check")[:2]
    out = flat(out)
    assert code == 0 and "back to the one you marked with" not in out, out
    assert "has not changed since your last check" in out, out
    got = run(capsys)
    out = flat(got[1])
    assert "in ../outside/results.csv, the file your last check read." in out, got
    later = outside.stat().st_mtime + 10
    os.utime(mine, (later, later))  # the eval ran again: its newest results are read
    out = flat(run(capsys, "check")[1])
    assert ("Your LLM-as-a-judge is back to the one you marked with (bike-grader-v1). The result "
            "from your marks still stands.") in out, out


def test_a_check_back_on_the_marked_file_names_the_file_the_last_check_read(
        here, capsys, no_calls):
    """`check` took on evals/results-v2.csv; `check evals/results.csv` goes back to the
    marked LLM-as-a-judge and says the result is no longer about results-v2.csv."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]  # not worse: taken on
    table_project(here, other, name="evals/results-v2.csv", model="bike-grader-v2")
    assert run(capsys, "check", "evals/results-v2.csv")[0] == 0
    code, out, _ = run(capsys, "check", "evals/results.csv")
    out = flat(out)
    assert code == 0 and "back to the one you marked with (bike-grader-v1)" in out, out
    assert ("Your last check read evals/results-v2.csv; this result is about "
            "evals/results.csv now.") in out, out
    later = [flat(run(capsys, "check", "evals/results.csv")[1]) for _ in range(2)]
    assert ("An earlier check read evals/results-v2.csv; this result is about "
            "evals/results.csv now.") in later[0], later[0]
    assert "Your last check read" not in later[0] and later[1] == later[0], later


def test_mark_on_an_older_file_names_the_file_the_result_is_about(here, capsys, no_calls):
    """Checks took on evals/new1.csv, then the newer evals/new2.csv. `mark evals/new1.csv`
    says its result is about new2.csv, the file the last check read: every command it then
    gives names new2.csv, never the older new1.csv."""
    import os

    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]  # not worse: taken on
    new1 = table_project(here, other, name="evals/new1.csv", model="bike-grader-v2")
    assert run(capsys, "check", "evals/new1.csv")[0] == 0
    new2 = table_project(here, other, name="evals/new2.csv", model="bike-grader-v3")
    later = new1.stat().st_mtime + 10
    os.utime(new2, (later, later))
    assert run(capsys, "check", "evals/new2.csv")[0] == 0
    code, out, err = run(capsys, "mark", "evals/new1.csv", "--no-browser", "--port", "0")
    run(capsys, "--stop")
    out = flat(out + err)
    assert code == 0, out
    assert "in evals/new2.csv, the file your last check read." in out, out
    assert "evals/new1.csv`" not in out and "new1.csv " not in out, out
    assert "evals/new2.csv`" in out, out


def test_a_check_back_after_a_worse_one_never_says_the_last_check_read_the_kept_file(
        here, capsys, no_calls):
    """results-v2.csv was taken on, then a check of results-v3.csv was worse: the last check
    read results-v3.csv, so going back names results-v2.csv as an earlier check's."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]
    table_project(here, other, name="evals/results-v2.csv", model="bike-grader-v2")
    assert run(capsys, "check", "evals/results-v2.csv")[0] == 0
    worse = [v if k % 3 == 0 else not v for k, v in enumerate(verdicts)]
    table_project(here, worse, name="evals/results-v3.csv", model="bike-grader-v3")
    assert run(capsys, "check", "evals/results-v3.csv")[0] == 1
    out = flat(run(capsys, "check", "evals/results.csv")[1])
    assert "back to the one you marked with (bike-grader-v1)" in out, out
    assert ("An earlier check read evals/results-v2.csv; this result is about "
            "evals/results.csv now.") in out, out
    assert "Your last check read" not in out, out


def _taken_on_v2(here, capsys) -> Workspace:
    """Marks made on evals/results.csv (bike-grader-v1), then a check that took on
    evals/results-v2.csv (bike-grader-v2)."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]
    table_project(here, other, name="evals/results-v2.csv", model="bike-grader-v2")
    assert run(capsys, "check", "evals/results-v2.csv")[0] == 0
    return Workspace(here)


CLOSED_BACK = ("Your marking page closed. It was for the LLM-as-a-judge your marks tested before this check, and they now test a different "
               "one. To open the page for it, run `judgekeeper mark evals/results.csv`.")


def _page_open(monkeypatch, stops=True) -> list:
    """A marking page open on the old LLM-as-a-judge: `background.stop` closes it, or with
    `stops` False finds it still there."""
    from judgekeeper import background, label

    stopped = []
    monkeypatch.setattr(label, "is_open", lambda folder: True)
    monkeypatch.setattr(background, "stop", lambda folder: stopped.append(folder) or stops)
    return stopped


def test_a_plain_run_back_on_the_marked_file_names_the_page_after_its_step(
        here, capsys, no_calls, monkeypatch):
    _taken_on_v2(here, capsys)
    stopped = _page_open(monkeypatch)
    code, said, err = run(capsys, "evals/results.csv", "--no-browser", "--port", "0")
    out = flat(said)
    assert code == 0 and stopped, out + err
    assert CLOSED_BACK in out, out
    assert out.index("Step 3 of 5: Measure") < out.index(CLOSED_BACK), out
    assert out.index("back to the one you marked with") < out.index(CLOSED_BACK), out
    _page_line_stands_apart(said)


def test_mark_back_on_the_marked_file_says_nothing_of_the_page(here, capsys, no_calls,
                                                                 monkeypatch):
    _taken_on_v2(here, capsys)
    stopped = _page_open(monkeypatch)
    _, out, _ = run(capsys, "mark", "evals/results.csv", "--no-browser", "--port", "0")
    run(capsys, "--stop")
    assert stopped and "Your marking page" not in flat(out), flat(out)


def test_a_check_back_on_the_marked_file_names_that_file_for_the_page(here, capsys, no_calls,
                                                                        monkeypatch):
    _taken_on_v2(here, capsys)
    _page_open(monkeypatch)
    code, out, _ = run(capsys, "check", "evals/results.csv")
    assert code == 0 and CLOSED_BACK in flat(out), flat(out)
    _page_line_stands_apart(out)


def _page_line_stands_apart(out: str) -> None:
    """The page's line is a paragraph of its own: a blank line before it."""
    lines = out.splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith("Your marking page closed"))
    assert lines[at - 1] == "", out


def test_a_check_that_takes_on_a_given_file_names_it_for_the_page(here, capsys, no_calls,
                                                                    monkeypatch):
    """`mark` alone reads the newest results, which may not be the file the check took on."""
    verdicts = split(20, 20)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    other = list(verdicts)
    other[0] = not other[0]
    table_project(here, other, name="evals/results-v2.csv", model="bike-grader-v2")
    _page_open(monkeypatch)
    code, out, _ = run(capsys, "check", "evals/results-v2.csv")
    assert code == 0 and ("Your marking page closed. It was for the LLM-as-a-judge your marks tested before this check, and "
                          "they now test a different one. To open the page for it, run `judgekeeper mark "
                          "evals/results-v2.csv`.") in flat(out), flat(out)


def test_a_page_that_is_still_there_after_it_was_closed_is_said_so(here, capsys, no_calls,
                                                                     monkeypatch):
    _taken_on_v2(here, capsys)
    _page_open(monkeypatch, stops=False)
    _, out, _ = run(capsys, "check", "evals/results.csv")
    out = flat(out)
    assert ("Your marking page didn't answer, so it may still show a different LLM-as-a-judge. "
            "To open it with this one, run `judgekeeper --stop`, then `judgekeeper mark "
            "evals/results.csv`.") in out, out
    assert "page closed" not in out, out


def _first_and_new(tool: str, root, verdicts, new: bool) -> str:
    """`tool`'s results for `verdicts`: the first ones in the project (False), or ones graded
    by another LLM-as-a-judge in .judgekeeper/fix/ (True). Where they are, from `root`."""
    from tests.start_projects import deepeval_data

    if tool == "table":
        name = ".judgekeeper/fix/new.csv" if new else "evals/results.csv"
        table_project(root, verdicts, name=name, model="bike-grader-v2" if new else "bike-grader-v1")
        return name
    name = ".judgekeeper/fix/new.json" if new else (
        "results.json" if tool == "promptfoo" else ".deepeval/.latest_run_full.json")
    data = (promptfoo_data(verdicts, rubric="A new rule." if new else "The old rule.")
            if tool == "promptfoo" else deepeval_data(verdicts, model="gpt-4.1-mini" if new
                                                      else "gpt-4.1"))
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(data), encoding="utf-8")
    return name


@pytest.mark.parametrize("tool", ["table", "promptfoo", "deepeval"])
def test_a_plain_run_after_a_check_of_a_file_in_fix_keeps_reading_it(here, capsys, no_calls,
                                                                       tool):
    """A check took on results in .judgekeeper/fix/, which the search never reads: a plain
    run keeps its result, never goes back to the older results here."""
    verdicts = split(20, 20)
    _first_and_new(tool, here, verdicts, new=False)
    assert run(capsys, "--no-browser", "--port", "0")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser", "--port", "0")  # the result
    run(capsys, "--stop")
    other = list(verdicts)
    other[0] = not other[0]
    name = _first_and_new(tool, here, other, new=True)
    assert run(capsys, "check", name)[0] == 0
    kept = judge_setup.read(ws)["setup_hash"], ws.data()["fingerprint"]
    for _ in range(2):
        code, out, err = run(capsys, "--no-browser", "--port", "0")
        run(capsys, "--stop")
        out = flat(out)
        assert code == 0, out + err
        assert "back to the one you marked with" not in out, out
        assert (f"This result is about your LLM-as-a-judge in {name}, the file your last check "
                "read.") in out, out
        assert (judge_setup.read(ws)["setup_hash"], ws.data()["fingerprint"]) == kept
    first = here / _first_and_new(tool, here, verdicts, new=False)  # the eval run again
    later = (here / name).stat().st_mtime + 10
    os.utime(first, (later, later))
    out = flat(run(capsys, "--no-browser", "--port", "0")[1])
    run(capsys, "--stop")
    assert "back to the one you marked with" in out, out


def test_after_a_check_of_a_file_outside_the_project_its_file_is_not_the_newest(
        here, capsys, no_calls):
    """The check read a newer file outside the project: a plain run on the project's file
    says "Reading evals/support-evals.csv.", never "the newest results here"."""
    _checked_outside(here, capsys, worse=False)
    out = flat(run(capsys)[1])
    assert "Reading evals/support-evals.csv." in out and "the newest" not in out, out


def test_after_a_check_of_a_file_outside_plain_runs_name_that_file(here, capsys, no_calls):
    """The marks test the LLM-as-a-judge of a file outside the project; the project's own
    file is older: every plain run says the result is about the file the check read, never
    "grades changed" nor a plain `check` (that would re-check the older file)."""
    _checked_outside(here, capsys, worse=False)
    for _ in range(2):
        out = flat(run(capsys)[1])
        assert ("This result is about your LLM-as-a-judge in ../outside/results.csv, the file "
                "your last check read.") in out, out
        assert "grades changed" not in out and "the newest" not in out, out
        assert ("Next: nothing to do. After you change your LLM-as-a-judge again, run "
                "`judgekeeper check <new results file>`.") in out, out


def _held_table(here, capsys, verdict: str) -> None:
    """Marked as the person; a check took on v2; v3 graded 11 marks wrong, and `check` held it
    (its saved verdict set to `verdict`, still held: "not_sure" with a big drop)."""
    person = split(15, 15)

    def flip(idx):
        return [(not x) if i in idx else x for i, x in enumerate(person)]

    table_project(here, flip({0, 1, 15, 16}), name="results.csv")
    run(capsys)
    _mark(Workspace(here), {i: "pass" if v else "fail" for i, v in enumerate(person)})
    run(capsys)
    table_project(here, flip({2, 3, 17, 18}), name="results-v2.csv")
    assert run(capsys, "check", "results-v2.csv")[0] == 0
    table_project(here, flip(set(range(6)) | set(range(15, 20))), name="results-v3.csv")
    assert run(capsys, "check", "results-v3.csv")[0] == 1
    history = Workspace(here).history_jsonl
    lines = history.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    for g in last["groups"].values():
        if isinstance(g, dict) and g.get("verdict") == "worse":
            g["verdict"] = verdict
    history.write_text("\n".join([*lines[:-1], json.dumps(last)]) + "\n", encoding="utf-8")


@pytest.mark.parametrize("verdict", ["worse", "not_sure"])
def test_after_a_held_check_every_plain_run_says_which_judge_it_is_about(here, capsys, no_calls,
                                                                         verdict):
    """The check found the new results worse (or not sure, with a big drop), so the marks
    still test the LLM-as-a-judge from before it: every plain run on those results says so."""
    _held_table(here, capsys, verdict)
    for _ in range(2):
        out = flat(run(capsys)[1])
        assert "This result is about your LLM-as-a-judge as it was" in out, out


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
    assert RULE_B in mistakes and RULE_A not in now_part(mistakes)
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
    report = flat(unwrapped((here / ".judgekeeper" / "report.html").read_text(encoding="utf-8")))
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
    report = unwrapped((here / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))
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
    assert _next(out) == 'Next: mark answers on the page until a "See the numbers so far" link appears, then click it.'


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


# A store above is for its own results only ------------------------------------------------

@pytest.mark.parametrize("marker", [".git", "pyproject.toml", None])
def test_new_results_below_a_store_get_their_own_marks(here, capsys, monkeypatch, marker):
    _marker(here, marker)
    table_project(here, split(20, 16), name="sub2/results.csv", tag="sub2")
    assert run(capsys, "sub2/results.csv", "--no-browser")[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    before = (here / ".judgekeeper" / "marks.jsonl").read_bytes()
    table_project(here / "evals3", split(20, 16), tag="evals3")
    monkeypatch.chdir(here / "evals3")
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert ("These results get their own marks here. The marks in ../ are for "
            "sub2/results.csv.") in flat(out), out
    assert "You marked 5 answers" not in out and "File:            results.csv" in out
    assert (here / "evals3" / ".judgekeeper" / "start.json").is_file()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
    run(capsys, "--stop")
    code, out, _ = run(capsys, "--no-browser")  # the next run says nothing more about it
    assert code == 0 and "get their own marks" not in out
    run(capsys, "--stop")


@pytest.mark.parametrize("marker", [".git", "pyproject.toml", None])
def test_the_store_above_stays_for_the_results_it_reads(here, capsys, monkeypatch, marker):
    _marker(here, marker)
    table_project(here, split(20, 16), name="sub2/results.csv", tag="sub2")
    assert run(capsys, "sub2/results.csv", "--no-browser")[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    (here / "src").mkdir()
    for folder in (here / "sub2", here / "src"):
        monkeypatch.chdir(folder)
        code, out, err = run(capsys, "--no-browser")
        assert code == 0, out + err
        assert "You marked 5 answers so far" in out and "get their own marks" not in out
        assert not (folder / ".judgekeeper").exists()
        assert "Closed the marking page." in run(capsys, "--stop")[1]


# --stop closes the page a run from the same folder opened -------------------------------

@pytest.mark.parametrize("marker", MARKERS)
def test_stop_closes_the_page_a_run_from_a_subfolder_opened(here, capsys, monkeypatch, marker):
    _marker(here, marker)
    table_project(here, split(20, 16))
    (here / "src").mkdir()
    monkeypatch.chdir(here / "src")
    code, out, err = run(capsys, "--no-browser")  # reads the project folder above
    assert code == 0, out + err
    assert "Reading the project folder above it" in flat(out)
    assert page.is_open(here / ".judgekeeper")
    assert "Closed the marking page." in run(capsys, "--stop")[1]
    assert not page.is_open(here / ".judgekeeper")


@pytest.mark.parametrize("marker", MARKERS)
def test_stop_in_a_project_below_leaves_the_page_above_open(here, capsys, monkeypatch, marker):
    _marker(here, ".git")
    table_project(here, split(20, 16))
    assert run(capsys, "--no-browser")[0] == 0
    _marker(here / "pkg", marker)
    monkeypatch.chdir(here / "pkg")
    code, out, _ = run(capsys, "--no-browser")  # a project of its own: never the one above
    assert code != 0 and "Reading the project folder above it" not in flat(out)
    assert "No marking page is open." in run(capsys, "--stop")[1]
    assert page.is_open(here / ".judgekeeper")
    monkeypatch.chdir(here)
    assert "Closed the marking page." in run(capsys, "--stop")[1]


def _reads_any_project_above(root):  # stand-in rule: reads any project folder above
    up = find.project_folder(root)
    found = None if up is None else find.search(up)
    return up if found is not None and any(found.readable(t) for t in find.TOOLS) else None


@pytest.mark.parametrize("marker", ["pyproject.toml", ".git"])
def test_stop_finds_the_store_the_run_read_whatever_rule_found_it(here, capsys, monkeypatch,
                                                                   marker):
    monkeypatch.setattr(find, "results_above", _reads_any_project_above)
    _marker(here, ".git")
    table_project(here, split(20, 16))
    _marker(here / "pkg", marker)
    monkeypatch.chdir(here / "pkg")
    code, out, err = run(capsys, "--no-browser")  # a page served from the store above
    assert code == 0 and "Reading the project folder above it" in flat(out), out + err
    assert "Closed the marking page." in run(capsys, "--stop")[1]
    assert not page.is_open(here / ".judgekeeper")


# --stop also finds a page opened from a folder right below ------------------------------

def _evals_with_labels(folder, capsys):
    from tests.test_labels_import import labelled, write_labels
    table_project(folder, split(20, 20))
    labels = write_labels(folder.parent / f"{folder.name}-labels.csv", labelled(range(10)))
    code, out, err = run(capsys, folder.name, "--labels", labels.name, "--no-browser")
    assert code == 0, out + err
    assert page.is_open(folder / ".judgekeeper") and not (folder.parent / ".judgekeeper").exists()


@pytest.mark.parametrize("marker", [".git", None])
def test_stop_closes_the_page_opened_from_the_folder_below(here, capsys, marker):
    _marker(here, marker)
    _evals_with_labels(here / "evals", capsys)  # judgekeeper evals --labels evals-labels.csv
    code, out, _ = run(capsys, "--stop")
    assert code == 0 and "Closed the marking page. Your marks are saved." in flat(out), out
    assert not page.is_open(here / "evals" / ".judgekeeper")


def test_stop_names_the_pages_open_in_folders_below(here, capsys):
    _marker(here, ".git")
    for name in ("a", "b"):
        _evals_with_labels(here / name, capsys)
    code, out, _ = run(capsys, "--stop")
    assert code == 3, out
    assert "Marking pages are open in a/ and b/." in flat(out)
    assert next_lines(out) == [("Next: go to one of those folders (`cd a`), then run "
                                "`judgekeeper --stop` there.")]
    assert page.is_open(here / "a" / ".judgekeeper") and page.is_open(here / "b" / ".judgekeeper")
    for name in ("a", "b"):
        assert "Closed the marking page." in run(capsys, f"{name}", "--stop")[1]


def test_a_plain_check_and_a_plain_run_weigh_the_last_read_file_against_the_same_files(
        here, capsys, no_calls, monkeypatch):
    """Two results files in the project, and a check that read a third outside it: a plain
    `check`, its results remembered or read, and a plain run ask about the file that check
    read with the same files found here, so they can't pick different files."""
    import os
    from pathlib import Path

    from judgekeeper import check as checking

    verdicts = split(20, 20)
    older = table_project(here, verdicts, name="evals/older.csv", model="bike-grader-v1")
    os.utime(older, (older.stat().st_mtime - 100,) * 2)
    table_project(here, verdicts, name="evals/results.csv", model="bike-grader-v1")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    assert run(capsys, "check")[0] == 0  # remembers what it read here, for the next check
    other = list(verdicts)
    other[0] = not other[0]
    outside = table_project(here.parent / "outside", other, model="bike-grader-v2")
    assert run(capsys, "check", str(outside))[0] == 0
    asked = []
    real = checking.last_read_file
    monkeypatch.setattr(checking, "last_read_file", lambda ws, results: asked.append(
        sorted(Path(r).resolve() for r in results)) or real(ws, results))
    for argv in (["check"], ["check"], []):
        run(capsys, *argv)
    assert len(asked) == 3 and asked[0] == asked[1] == asked[2], asked
    assert len(asked[0]) == 2, asked
