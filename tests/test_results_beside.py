"""A results file in the same folder as one the session above reads belongs to that session
when it is the same eval (read the same way, with questions the session holds): from that
folder every command uses the marks above, as it does from the project folder, and never
starts a second .judgekeeper/ there. Another eval beside them never joins, never gets its own
marks and is never taken as a changed LLM-as-a-judge: a run says so, and keeps reading the
marked file. Results in a folder of their own still get their own marks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper.start_label import Workspace
from tests import test_project_folder
from tests.start_projects import (
    _write_json,
    answer,
    deepeval_project,
    inspect_data,
    promptfoo_data,
    promptfoo_project,
    question,
    split,
    table_project,
)
from tests.test_front import flat, run
from tests.test_project_folder import _mark, _marker

here = test_project_folder.here  # the fixture: a project folder

PAGE = ("--no-browser", "--port", "0")


def _store(root, capsys, marker) -> bytes:
    """A session in `root` on sub2/results.csv with 5 marks, and new results of the same
    answers beside it, sub2/results-v2.csv."""
    _marker(root, marker)
    table_project(root, split(20, 16), name="sub2/results.csv", tag="sub2")
    assert run(capsys, "sub2/results.csv", *PAGE)[0] == 0
    _mark(Workspace(root), only=range(5))
    run(capsys, "--stop")
    table_project(root, split(20, 16), name="sub2/results-v2.csv", tag="sub2")
    return (root / ".judgekeeper" / "marks.jsonl").read_bytes()


def _said(capsys, *argv) -> tuple[int, str]:
    code, out, err = run(capsys, *argv, *(PAGE if argv[:1] not in (("check",), ("fix",)) else ()))
    run(capsys, "--stop")
    return code, flat(out + err)


@pytest.mark.parametrize("marker", [".git", "pyproject.toml", None])
@pytest.mark.parametrize("command", [["mark", "results-v2.csv"], ["results-v2.csv"], []])
def test_from_the_folder_of_the_results_every_command_uses_the_marks_above(
        here, capsys, monkeypatch, marker, command):
    before = _store(here, capsys, marker)
    monkeypatch.chdir(here / "sub2")
    code, said = _said(capsys, *command)
    assert code == 0, said
    assert "get their own marks" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists(), said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


@pytest.mark.parametrize("command", [["mark", "results-v2.csv"], ["results-v2.csv"]])
def test_from_the_folder_of_the_results_it_says_what_the_project_folder_says(
        here, capsys, monkeypatch, command):
    _store(here, capsys, ".git")
    monkeypatch.chdir(here)
    there = _said(capsys, command[0], f"sub2/{command[-1]}") if len(command) == 2 \
        else _said(capsys, f"sub2/{command[-1]}")
    monkeypatch.chdir(here / "sub2")
    beside = _said(capsys, *command)
    assert beside[0] == there[0], (beside, there)
    assert ("You marked 5 answers" in beside[1]) == ("You marked 5 answers" in there[1]), (
        beside, there)


def test_from_the_project_folder_nothing_changes(here, capsys, monkeypatch):
    before = _store(here, capsys, ".git")
    monkeypatch.chdir(here)
    code, said = _said(capsys, "sub2/results-v2.csv")
    assert code == 0 and "get their own marks" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


def test_results_in_a_folder_of_their_own_still_get_their_own_marks(here, capsys,
                                                                   monkeypatch):
    before = _store(here, capsys, ".git")
    table_project(here / "evals3", split(20, 16), tag="evals3")
    monkeypatch.chdir(here / "evals3")
    code, said = _said(capsys)
    assert code == 0, said
    assert ("These results get their own marks here. The marks in ../ are for "
            "sub2/results.csv.") in said, said
    assert (here / "evals3" / ".judgekeeper" / "start.json").is_file()
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


def _other_eval(file: str, marked: str) -> str:
    return (f"{file} shares few questions with the results you marked ({marked}), so it looks like "
            "another eval. To mark it, put it in a folder of its own and run `judgekeeper` "
            "there.")


def _refused(file: str, marked: str) -> str:
    """The same, for a command that stops at the file: what to do is its Next line."""
    return (f"{file} shares few questions with the results you marked ({marked}), so it looks like "
            f"another eval. Next: put {file} in a folder of its own, then run `judgekeeper` "
            "there.")


def _write_other(here, other: str) -> str:
    """Another eval beside the session's sub2/results.csv: other questions in a CSV, or a
    promptfoo file. Its name."""
    if other == "csv":
        table_project(here, split(20, 16), name="sub2/other.csv", tag="another eval")
        return "other.csv"
    promptfoo_project(here / "sub2", split(20, 16), name="pf.json", config=False)
    return "pf.json"


@pytest.mark.parametrize("other", ["csv", "promptfoo"])
@pytest.mark.parametrize("command", [["mark"], [], ["check"], ["fix"]])
@pytest.mark.parametrize("inside", [True, False])
def test_another_eval_beside_the_results_is_said_and_changes_nothing(here, capsys, monkeypatch,
                                                                     other, command, inside):
    """Given by path, from sub2/ or the project folder: the line, exit 3, and no marks, start
    or second .judgekeeper/ anywhere; never asked to start over."""
    before = _store(here, capsys, ".git")
    start = (here / ".judgekeeper" / "start.json").read_bytes()
    name = _write_other(here, other)
    monkeypatch.chdir(here / "sub2" if inside else here)
    file = name if inside else f"sub2/{name}"
    code, said = _said(capsys, *command, file)
    assert code == 3, said
    assert _refused(file, "results.csv" if inside else "sub2/results.csv") in said, said
    assert "Start over" not in said and "changed since your marks" not in said, said
    assert "own marks" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists(), said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
    assert (here / ".judgekeeper" / "start.json").read_bytes() == start


def test_the_other_eval_line_shows_a_typed_path_as_it_shows_the_marked_one(tmp_path,
                                                                           monkeypatch):
    """A typed path is joined with the system's separator (`sub2\\other.csv` on Windows),
    the marked file is found whole: both are shown with `/`, as every path line is."""
    from judgekeeper import project, textio

    monkeypatch.chdir(tmp_path)
    line = project.other_eval_line(Path("sub2") / "other.csv",
                                   tmp_path.resolve() / "sub2" / "results.csv")
    assert _other_eval("sub2/other.csv", "sub2/results.csv") in line, line
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert textio.shown_in(Path("sub2") / "results.json", elsewhere) == "sub2/results.json"


@pytest.mark.parametrize("other", ["csv", "promptfoo"])
@pytest.mark.parametrize("command", [["mark"], []])
def test_a_plain_run_beside_another_eval_reads_the_marked_file(here, capsys, monkeypatch,
                                                              other, command):
    before = _store(here, capsys, ".git")
    name = _write_other(here, other)
    monkeypatch.chdir(here / "sub2")
    code, said = _said(capsys, *command)
    assert code == 0, said
    assert _other_eval(name, "results.csv") in said, said
    assert "own marks" not in said and "Start over" not in said, said
    assert not (here / "sub2" / ".judgekeeper").exists(), said
    assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before


def test_the_newest_file_being_another_eval_beside_never_moves_the_plain_run(here, capsys,
                                                                            monkeypatch):
    """A session started by a plain run, which found evals/results.csv; later the newest
    results in the project are evals/second.csv, another eval beside it. Run after run, the
    plain run reads evals/results.csv and says why it leaves second.csv alone."""
    _marker(here, ".git")
    table_project(here, split(20, 16), name="evals/results.csv", tag="first")
    assert run(capsys, *PAGE)[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    before = (here / ".judgekeeper" / "marks.jsonl").read_bytes()
    table_project(here, split(20, 16), name="evals/second.csv", tag="another eval")
    monkeypatch.chdir(here)
    for _ in range(2):
        code, said = _said(capsys)
        assert code == 0, said
        assert _other_eval("evals/second.csv", "evals/results.csv") in said, said
        assert "Read: evals/results.csv" in said or "(evals/results.csv" in said, said
        assert "second.csv)" not in said and "Start over" not in said, said
        assert "newer results" not in said.lower(), said
        data = Workspace(here).data()
        assert data["results_files"] == ["evals/results.csv"], data
        assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
    code, said = _said(capsys, "check")
    assert "second.csv" not in said.replace(_other_eval("evals/second.csv",
                                                        "evals/results.csv"), ""), said


@pytest.mark.parametrize("given", [True, False])
def test_check_in_a_folder_of_other_results_says_they_get_their_own_marks(here, capsys,
                                                                          monkeypatch, given):
    """The session reads results.csv in the project folder; evals/ holds other results. From
    evals/, `check` says what `mark` and a plain run do there: these get their own marks,
    to be made with a plain run. It starts nothing itself."""
    _marker(here, ".git")
    table_project(here, split(20, 16), tag="top")
    assert run(capsys, *PAGE)[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    table_project(here, split(20, 16), name="evals/results-v2.csv", tag="top")
    monkeypatch.chdir(here / "evals")
    code, out, err = run(capsys, "check", *(["results-v2.csv"] if given else []))
    said = flat(out + err)
    assert code == 3, said
    assert ("No marks for these results yet: they get their own marks here. The marks in ../ "
            "are for results.csv.") in said, said
    assert "Next: run `judgekeeper` here to mark answers for them." in said, said
    assert "Your marks are in" not in said and "check .." not in said, said
    assert not (here / "evals" / ".judgekeeper").exists()


def _chat(verdicts, tag: str) -> dict:
    """An Inspect AI log whose questions are chat messages, not text."""
    data = inspect_data(verdicts, tag=tag)
    for sample in data["samples"]:
        sample["input"] = [{"role": "user", "content": sample["input"]}]
    return data


BESIDE = {  # tool: (the session's file, the file beside it, a writer of one)
    "promptfoo": ("a.json", "b.json",
                  lambda path, tag: promptfoo_project(path.parent, split(20, 16), name=path.name,
                                                      config=False, tag=tag)),
    "inspect": ("a.json", "b.json", lambda path, tag: _write_json(path, _chat(split(20, 16), tag))),
    "deepeval": ("test_run_20261001_143217.json", "test_run_20261002_143217.json",
                 lambda path, tag: deepeval_project(path.parent, split(20, 16), name=path.name,
                                                    tag=tag)),
}


@pytest.mark.parametrize("same", [True, False])
@pytest.mark.parametrize("tool", list(BESIDE))
def test_results_of_one_tool_beside_join_when_they_share_questions(here, capsys, monkeypatch,
                                                                   tool, same):
    """A session on evals/<first> (promptfoo's questions are a dict of vars, Inspect's here a
    list of chat messages), and a second file of the same tool beside it: with the same
    questions it joins the session, from the project folder and from evals/; with other
    questions it is another eval, said so, and never read or marked. Never an error."""
    first, second, write = BESIDE[tool]
    _marker(here, ".git")
    write(here / "evals" / first, "one")
    assert run(capsys, f"evals/{first}", *PAGE)[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    before = (here / ".judgekeeper" / "marks.jsonl").read_bytes()
    write(here / "evals" / second, "one" if same else "other")
    for folder, argv in ((here, [f"evals/{second}"]), (here, ["mark", f"evals/{second}"]),
                         (here, ["check", f"evals/{second}"]), (here / "evals", [second]),
                         (here / "evals", [])):
        monkeypatch.chdir(folder)
        code, said = _said(capsys, *argv)
        assert "didn't expect" not in said, (argv, said)
        said_as = _refused if argv else _other_eval
        line = (said_as(f"evals/{second}", f"evals/{first}") if folder == here
                else said_as(second, first))
        if same:  # check: 5 marks are too few for a re-check
            assert code == (3 if argv[:1] == ["check"] else 0), (argv, said)
            assert "another eval" not in said, (argv, said)
        else:
            assert code == (3 if argv else 0), (argv, said)
            assert line in said, (argv, said)
        assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
        assert not (here / "evals" / ".judgekeeper").exists(), (argv, said)


SHARED = ["I am not able to help with that. Please ask someone else.",
          "Your order ships the same day, with no wait at all."]


def _with_shared(tag: str, verdicts=None, outputs_tag: str | None = None) -> dict:
    """promptfoo results of 36 questions tagged `tag`, the first two answered with the SHARED
    answers (a refusal, a stock line) and the rest with answers tagged `outputs_tag`."""
    outputs = [*SHARED, *(answer(i, tag if outputs_tag is None else outputs_tag)
                          for i in range(2, 36))]
    return promptfoo_data(split(20, 16) if verdicts is None else verdicts, tag=tag,
                          outputs=outputs)


def _more_questions() -> dict:
    """The 36 marked questions, as marked, then 100 new ones: the eval run on more questions."""
    outputs = [*SHARED, *(answer(i, "one") for i in range(2, 136))]
    return promptfoo_data(split(68, 68), tag="one", outputs=outputs)


@pytest.mark.parametrize("second", ["other questions", "graded again", "new answers",
                                    "more questions"])
def test_a_file_beside_is_the_same_eval_only_when_it_shares_its_questions(here, capsys,
                                                                          monkeypatch, second):
    """A promptfoo file beside the marked one with other questions is another eval, though a
    few answers (a refusal) are word for word the same: never read, marked or added. The same
    questions graded again, answered again, or with 100 more after them, join the session."""
    _marker(here, ".git")
    _write_json(here / "evals" / "a.json", _with_shared("one"))
    assert run(capsys, "evals/a.json", *PAGE)[0] == 0
    _mark(Workspace(here), only=range(5))
    run(capsys, "--stop")
    before = (here / ".judgekeeper" / "marks.jsonl").read_bytes()
    pool = (here / ".judgekeeper" / "pool.jsonl").read_bytes()
    _write_json(here / "evals" / "b.json", {
        "other questions": lambda: _with_shared("other"),
        "graded again": lambda: _with_shared("one", verdicts=split(26, 10)),
        "new answers": lambda: _with_shared("one", outputs_tag="again"),
        "more questions": _more_questions}[second]())
    for argv in (["evals/b.json"], ["mark", "evals/b.json"], ["check", "evals/b.json"],
                 ["fix", "evals/b.json"], []):
        code, said = _said(capsys, *argv)
        assert "didn't expect" not in said, (argv, said)
        if second == "other questions":
            assert code == (3 if argv else 0), (argv, said)
            line = (_refused if argv else _other_eval)("evals/b.json", "evals/a.json")
            assert line in said, (argv, said)
            assert (here / ".judgekeeper" / "pool.jsonl").read_bytes() == pool, (argv, said)
        else:
            assert "another eval" not in said, (argv, said)
        assert (here / ".judgekeeper" / "marks.jsonl").read_bytes() == before
        assert not (here / "evals" / ".judgekeeper").exists(), (argv, said)
    if second in ("new answers", "more questions"):  # its new answers join the pool
        assert (here / ".judgekeeper" / "pool.jsonl").read_bytes() != pool


@pytest.mark.parametrize(("typed", "shown"), [
    ("../../venv/bin/judgekeeper", "judgekeeper"),
    ("venv/bin/python -P -m judgekeeper", "judgekeeper"),
    ("~/venv/bin/judgekeeper", "judgekeeper"),
    ("/opt/jk/bin/judgekeeper", "judgekeeper"),
    ("..\\venv\\Scripts\\judgekeeper.exe", "judgekeeper"),
    ("python3 -P -m judgekeeper", "python3 -P -m judgekeeper"),
    ("uvx judgekeeper", "uvx judgekeeper"),
    ("judgekeeper", "judgekeeper")])
def test_the_other_eval_line_names_a_program_that_runs_in_the_new_folder(monkeypatch, typed,
                                                                        shown):
    """The line sends the person to a folder of its own: a program typed with a path in it
    (from here, from home or whole) is plain `judgekeeper` there, never a path."""
    from judgekeeper import project, textio

    monkeypatch.setattr(textio, "program", lambda *a: typed)
    line = project.other_eval_line(Path("evals/second.csv"), Path("evals/results.csv"))
    assert line.endswith(f"put it in a folder of its own and run `{shown}` there."), line


def _store_and_file(root, held: list[tuple[str, str]], rows: list[tuple[str, str]]):
    """A session holding `held` (question, answer) pairs, and a CSV beside it of `rows`."""
    import csv

    ws = Workspace(root)
    ws.dir.mkdir(parents=True)
    ws.start.write_text(json.dumps({"tool": "table"}), encoding="utf-8")
    ws.pool.write_text("".join(json.dumps({"id": f"a{k}", "input": q, "output": a}) + "\n"
                               for k, (q, a) in enumerate(held)), encoding="utf-8")
    path = root / "other.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        w.writerows([q, a, "pass" if k % 2 else "fail"] for k, (q, a) in enumerate(rows))
    return path, root


@pytest.mark.parametrize(("held", "rows", "same"), [
    # marked at 3 answers a question, run again once each on all 20 and 25 new ones
    ([(question(i), answer(i, f"e{e}")) for i in range(20) for e in range(3)],
     [(question(i), answer(i, "again")) for i in range(45)], True),
    # 3 rows a question (one per assertion), only 16 of 60 questions marked
    ([(question(i), answer(i)) for i in range(60)],
     [(question(i if i < 16 else 100 + i), answer(i)) for i in range(60) for _ in range(3)],
     False),
    ([(question(i), answer(i)) for i in range(60)],
     [(question(i if i < 30 else 100 + i), answer(i)) for i in range(60)], True),
    ([(question(i), answer(i)) for i in range(60)],
     [(question(i if i < 29 else 100 + i), answer(i)) for i in range(60)], False),
], ids=["epochs then more questions", "3 assertions, 16 of 60", "30 of 60", "29 of 60"])
def test_the_same_eval_counts_distinct_questions(tmp_path, monkeypatch, held, rows, same):
    """Half the distinct questions of the smaller side: never rows, which repeats (epochs) or
    one row per assertion multiply."""
    from judgekeeper import project

    monkeypatch.chdir(tmp_path)
    path, store = _store_and_file(tmp_path, held, rows)
    assert project._same_eval(path, store) is same
