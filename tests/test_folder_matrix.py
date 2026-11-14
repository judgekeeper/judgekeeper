"""The folder rules, held over generated layouts. Each layout is a top folder of one kind
(plain, code, a project file, a git top, a judge.json-only .judgekeeper/), with, below it,
x/ (plain, code, a project file, a judge.json-only .judgekeeper/ or a session of its own,
holding graded results or answers with no grade), y/ (plain, graded results) and e/ (empty);
the top holds answers of its own or nothing. Every run (from the top, from e/, from x/, with
and without `.`, and naming y/'s file) holds:

I1 it never reads a file inside a folder below the folder it reads that is a project of its
   own (a project file, or its own .judgekeeper/);
I2 it never pools files from two subfolders (their questions differ) unless they were named;
I3 from an empty folder it reads that folder or the nearest project above, never past it;
I4 it writes only in the .judgekeeper/ of the folder it read;
I5 a command its last Next line names, pasted, reads results (no "No ... found");
I6 with a session in x/, a newer file of other questions (beside its results or in a folder
   below) never replaces the files it reads.
No page opens: the page is served in a thread (conftest's pages)."""

from __future__ import annotations

import itertools
import json
import os
import re
import shlex
import time
from pathlib import Path

import pytest

from judgekeeper import front, project
from tests.start_projects import (
    answer,
    deepeval_project,
    inspect_project,
    own_format_project,
    promptfoo_project,
    question,
    records_project,
    split,
    table_project,
)
from tests.test_answers_without_grades import write_answers
from tests.test_front import flat, run

TOPS = ("plain", "code", "file", "git", "judged")
XS = ("plain", "code", "file", "judged", "session")
CONTENTS = ("graded", "answers")


def _kind(folder: Path, kind: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if kind == "code":
        (folder / "app.py").write_text("", encoding="utf-8")
    elif kind == "file":
        (folder / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    elif kind == "git":
        (folder / ".git").mkdir()
    elif kind == "judged":
        (folder / ".judgekeeper").mkdir()
        (folder / ".judgekeeper" / "judge.json").write_text("{}", encoding="utf-8")


def _own(folder: Path) -> bool:
    """A project of its own for I1: a project file, or its own .judgekeeper/ holding more
    than its .gitignore."""
    if any((folder / name).exists() for name in project_files()):
        return True
    jk = folder / ".judgekeeper"
    return jk.is_dir() and any(p.name != ".gitignore" for p in jk.iterdir())


def project_files() -> tuple[str, ...]:
    from judgekeeper import recorder

    return recorder.MARKERS


def _project_above(folder: Path, home: Path) -> Path | None:
    """I3's project above: a project file, code or its own .judgekeeper/."""
    for above in folder.parents:
        if above == home:
            return None
        if _own(above) or any(above.glob("*.py")):
            return above
    return None


def _files(top: Path) -> dict[str, tuple[int, int]]:
    return {p.relative_to(top).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in top.rglob("*") if p.is_file() and ".git" not in p.parts}


@pytest.fixture
def reads(monkeypatch):
    """The project and the files of every pool found in a run (front.find_found)."""
    seen: list[tuple[Path, list[Path]]] = []
    real = front.find_found

    def spy(talk, path):
        found, saved = real(talk, path)
        used = [r.path for r in found.results if r.rel in found.used] or \
            [r.path for r in found.results]
        seen.append((Path(found.root).resolve(), [Path(p).resolve() for p in used]))
        return found, saved

    monkeypatch.setattr(front, "find_found", spy)
    return seen


def _layout(home: Path, top_kind: str, x_kind: str, x_content: str, top_answers: bool,
            capsys, monkeypatch) -> Path:
    top = home / "top"
    _kind(top, top_kind)
    x = top / "x"
    _kind(x, "plain" if x_kind == "session" else x_kind)
    if x_content == "answers":  # a session's: 40, enough to mark (its file is results.csv)
        write_answers(x, 40, name="results") if x_kind == "session" \
            else write_answers(x, 12, name="answers")
    else:
        table_project(x, split(20, 20) if x_kind == "session" else split(6, 6), tag="x")
    table_project(top / "y", split(5, 5), tag="y")
    (top / "e").mkdir()
    if top_answers:
        write_answers(top, 12, name="answers")
    if x_kind == "session":  # a run in x/ starts its session (a page, 0 marks)
        assert _say(capsys, monkeypatch, x)[0] == 0
    return top


def _say(capsys, monkeypatch, folder: Path, *argv: str) -> tuple[int, str]:
    monkeypatch.chdir(folder)
    project.forget()
    code, out, err = run(capsys, *argv, "--no-browser", "--port", "0")
    return code, flat(out + err)


def _commands(said: str) -> list[tuple[str, list[str]]]:
    """(the folder to run in, the arguments) of each judgekeeper command in the last Next
    line: "run `judgekeeper` in x/" runs in x/."""
    if "Next:" not in said:
        return []
    last = said[said.rindex("Next:"):]
    out = []
    for i, part in enumerate(last.split("`")):
        if i % 2 == 0 or not part.startswith("judgekeeper"):
            continue
        rest = last.split("`")[i + 1] if i + 1 < len(last.split("`")) else ""
        where = rest.split(" in ", 1)[1].split("/")[0] if rest.startswith(" in ") else "."
        args = shlex.split(part)[1:]
        if args and args[0] in ("mark", "check", "fix", "--stop", "measure"):
            continue  # another step: not a reading of results
        out.append((where, [a for a in args if a not in ("--no-browser",)]))
    return out


def _check(top: Path, home: Path, run_in: Path, argv: tuple, seen, before, said: str,
           code: int) -> None:
    named = any(a.endswith(".csv") for a in argv)
    after = _files(top)
    changed = {p for p in after if before.get(p) != after[p]}
    if not seen:
        assert not changed, (changed, said)  # I4: nothing read, nothing written
        return
    root, files = seen[-1]
    for f in files:  # I1
        folder = f.parent
        while folder != root and folder.is_relative_to(root):
            assert not _own(folder), (f"I1: read {f} inside {folder}", said)
            folder = folder.parent
    if not named:  # I2
        tops = {f.relative_to(root).parts[0] for f in files
                if f.is_relative_to(root) and len(f.relative_to(root).parts) > 1}
        assert len(tops) <= 1, (f"I2: pooled {sorted(tops)} from {run_in.name} {argv}", said)
    if run_in.name == "e" and not argv:  # I3
        assert root in (run_in.resolve(), _project_above(run_in.resolve(), home)), \
            (f"I3: read {root}", said)
    jk = root / ".judgekeeper"
    for p in changed:  # I4
        assert (top / p).resolve().is_relative_to(jk), (f"I4: wrote {p}, read {root}", said)


LAYOUTS = list(itertools.product(TOPS, XS, CONTENTS, (False, True)))


@pytest.mark.parametrize(("top_kind", "x_kind", "x_content", "top_answers"), LAYOUTS)
def test_the_folder_rules_hold(tmp_path, capsys, monkeypatch, reads, top_kind, x_kind,
                               x_content, top_answers):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = _layout(tmp_path, top_kind, x_kind, x_content, top_answers, capsys, monkeypatch)
    runs = [(top, ()), (top, (".",)), (top, ("y/results.csv",)), (top / "e", ()),
            (top / "x", ()), (top / "x", (".",))]
    for run_in, argv in runs:
        before = _files(top)
        reads.clear()
        code, said = _say(capsys, monkeypatch, run_in, *argv)
        assert code in (0, 3), (run_in, argv, said)
        _check(top, tmp_path, run_in, argv, list(reads), before, said, code)
        if code != 3 or run_in != top or argv:
            continue
        for where, args in _commands(said):  # I5
            reads.clear()
            said2 = _say(capsys, monkeypatch, (run_in / where).resolve(), *args)[1]
            assert "No eval results found" not in said2 and "No saved" not in said2, \
                (f"I5: `judgekeeper {' '.join(args)}` in {where}", said, said2)


@pytest.mark.parametrize("where", ["", "more/"])
@pytest.mark.parametrize("x_content", CONTENTS)
@pytest.mark.parametrize("top_kind", TOPS)
def test_an_unrelated_file_never_replaces_a_sessions_files(tmp_path, capsys, monkeypatch,
                                                           reads, top_kind, x_content, where):
    """I6."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = _layout(tmp_path, top_kind, "session", x_content, False, capsys, monkeypatch)
    x = top / "x"
    (x / where).mkdir(exist_ok=True)
    other = x / where / "other.jsonl"
    other.write_text("".join(json.dumps({"input": f"Unrelated {i}?", "output": f"Other {i}."})
                             + "\n" for i in range(15)), encoding="utf-8")
    later = time.time() + 60
    os.utime(other, (later, later))
    for argv in ((), (".",)):
        reads.clear()
        before = _files(top)
        code, said = _say(capsys, monkeypatch, x, *argv)
        assert code in (0, 3), said
        _check(top, tmp_path, x, argv, list(reads), before, said, code)
        assert reads and reads[-1][1] == [(x / "results.csv").resolve()], \
            (f"I6: read {reads[-1][1] if reads else None}", said)


# A results file that is a link, --stop and --tool -----------------------------------------


def _linked(home: Path, capsys, monkeypatch) -> Path:
    """home/symlink-out/: pyproject.toml, results.csv a link to a file in a folder away from
    home (40 graded), and its own session from `judgekeeper results.csv`."""
    away = home.parent / f"{home.name}-data"
    table_project(away, split(20, 20), tag="s")
    folder = home / "symlink-out"
    _kind(folder, "file")
    try:
        (folder / "results.csv").symlink_to(away / "results.csv")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links not allowed here")
    assert _say(capsys, monkeypatch, folder, "results.csv")[0] == 0
    return folder


def test_after_stop_the_next_line_runs_the_command_the_session_started_with(
        tmp_path, capsys, monkeypatch):
    """I5 (M-4): the plain command finds nothing there (the file is a link)."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    folder = _linked(tmp_path, capsys, monkeypatch)
    said = _say(capsys, monkeypatch, folder, "--stop")[1]
    assert "run `judgekeeper results.csv" in said, said


def test_a_project_with_a_session_is_named_from_the_top_when_its_file_is_a_link(
        tmp_path, capsys, monkeypatch):
    """M-3: the top's list names every project with results or a session."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, "git")
    _linked(top, capsys, monkeypatch)
    for name in ("a", "b"):
        _kind(top / name, "file")
        table_project(top / name, split(5, 5), tag=name)
    said = _say(capsys, monkeypatch, top)[1]
    assert "symlink-out/" in said, said


def test_a_tool_with_no_results_never_says_to_run_the_same_command_again(
        tmp_path, capsys, monkeypatch):
    """I5 (the --tool line): its Next line says what to do, not the command that failed."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, "git")
    table_project(top, split(5, 5), tag="t")
    said = _say(capsys, monkeypatch, top, "--tool", "promptfoo")[1]
    assert "No saved promptfoo results found" in said, said
    assert "run `judgekeeper --tool promptfoo" not in said[said.rindex("Next:"):], said


# A tool's folder, the walk's limits, a code folder, .judgekeeper/ ----------------------------


def _marked(folder: Path, n: int) -> None:
    """The first n answers of the session in `folder` marked, Pass and Fail in turn."""
    from judgekeeper import start_label

    page = start_label.StartSession(start_label.Workspace(folder))
    for i, item in enumerate(page.items[:n]):
        page.update({"id": item["id"], "label": "pass" if i % 2 == 0 else "fail", "seconds": 3})


def _many(folder: Path, n: int, suffix: str, text: str = "") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (folder / f"doc{i:04}{suffix}").write_text(text, encoding="utf-8")


def _older(path: Path, days: int = 300) -> None:
    then = time.time() - days * 86400
    os.utime(path, (then, then))


def test_the_chosen_inspect_logs_folder_keeps_the_session_in_the_project(
        tmp_path, capsys, monkeypatch):
    """`judgekeeper logs`, as the choice of folders prints it, marks in proj/, never in
    proj/logs/ (cleared with old logs), and `check` in proj/ never says `cd logs`."""
    from tests.start_projects import inspect_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    inspect_project(proj, split(6, 6), tag="a")
    inspect_project(proj, split(6, 6), name="old/logs/2026-10-02_support.json", tag="b")
    said = _say(capsys, monkeypatch, proj)[1]
    assert "`judgekeeper logs " in said, said
    code, said = _say(capsys, monkeypatch, proj, "logs", "--yes")
    assert code in (0, 3) and "Answers:" in said, said
    assert not (proj / "logs" / ".judgekeeper").exists(), said
    assert (proj / ".judgekeeper" / "judge.json").is_file(), said
    assert str(tmp_path) not in said, said  # every path from here
    monkeypatch.chdir(proj)
    project.forget()
    code, out, err = run(capsys, "check")
    assert "cd logs" not in flat(out + err), out + err


def test_a_named_deepeval_results_folder_keeps_the_session_in_the_project(
        tmp_path, capsys, monkeypatch):
    """DeepEval: a results folder named as PATH is no project of its own."""
    from tests.start_projects import deepeval_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    deepeval_project(proj, split(6, 6), name="results-a/test_run_20261002_120000.json")
    deepeval_project(proj, split(6, 6), name="results-b/test_run_20261001_120000.json")
    code, said = _say(capsys, monkeypatch, proj, "results-a", "--yes")
    assert code in (0, 3) and "Answers:" in said, said
    assert not (proj / "results-a" / ".judgekeeper").exists(), said
    assert (proj / ".judgekeeper" / "judge.json").is_file(), said
    assert str(tmp_path) not in said, said
    code, said = _say(capsys, monkeypatch, proj / "results-b", "--yes")  # run from inside it
    assert code in (0, 3) and "Answers:" in said, said
    assert not (proj / "results-b" / ".judgekeeper").exists(), said
    assert str(tmp_path) not in said, said


def test_a_named_logs_folder_with_no_project_file_above_keeps_the_session_out(
        tmp_path, capsys, monkeypatch):
    """No project file: `judgekeeper logs` from a plain folder, or `judgekeeper
    a/b/logs` from the project, never makes the logs folder a project of its own."""
    from tests.start_projects import inspect_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    plain = tmp_path / "plain"
    inspect_project(plain, split(6, 6), tag="a")
    code, said = _say(capsys, monkeypatch, plain, "logs", "--yes")
    assert code in (0, 3) and "Answers:" in said, said
    assert not (plain / "logs" / ".judgekeeper").exists(), said
    assert (plain / ".judgekeeper" / "judge.json").is_file(), said
    said = _say(capsys, monkeypatch, plain, "mark", "logs")[1]
    assert not (plain / "logs" / ".judgekeeper").exists(), said
    assert (plain / ".judgekeeper" / "start.json").is_file(), said
    proj = tmp_path / "proj"
    _kind(proj, "file")
    inspect_project(proj / "a" / "b", split(6, 6), tag="b")
    code, said = _say(capsys, monkeypatch, proj, "a/b/logs", "--yes")
    assert code in (0, 3) and "Answers:" in said, said
    assert not (proj / "a" / "b" / "logs" / ".judgekeeper").exists(), said
    assert (proj / ".judgekeeper" / "judge.json").is_file(), said


def test_many_json_files_never_hide_the_results(tmp_path, capsys, monkeypatch, reads):
    """250 JSON documents in data/ use up no budget the eval's folder needs."""
    from tests.start_projects import promptfoo_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    _many(proj / "data", 250, ".json", '{"text": "a document"}')
    promptfoo_project(proj / "evals", split(6, 6), tag="e")
    said = _say(capsys, monkeypatch, proj)[1]
    assert reads and reads[-1][1] == [(proj / "evals" / "results.json").resolve()], said


def test_the_sessions_own_file_is_always_found(tmp_path, capsys, monkeypatch, reads):
    """After marking, 250 JSON files sorted before the results never make plain,
    `mark` or `check` say there are no saved results (a loop)."""
    from tests.start_projects import promptfoo_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    promptfoo_project(proj / "bench", split(20, 20), tag="b")
    _say(capsys, monkeypatch, proj)
    assert (proj / ".judgekeeper" / "start.json").is_file()
    _marked(proj, 10)
    _many(proj / "aaa", 250, ".json", '{"text": "a document"}')
    for argv in ((), ("mark",)):
        reads.clear()
        said = _say(capsys, monkeypatch, proj, *argv)[1]
        assert "no saved results file yet" not in said, (argv, said)
        assert reads and reads[-1][1][0] == (proj / "bench" / "results.json").resolve(), said
    monkeypatch.chdir(proj)
    project.forget()
    _, out, err = run(capsys, "check")
    assert "no saved results file yet" not in flat(out + err), out + err


def test_a_walk_that_stopped_says_so_even_when_it_read_something(tmp_path, capsys,
                                                                 monkeypatch, reads):
    """Over 5,000 files: the folder named like results is looked in first, and the
    run says it stopped looking, so an older file is never read in silence."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    _many(proj / "assets", 5100, ".png")
    table_project(proj / "runs", split(6, 6), tag="r")
    _older(table_project(proj, split(6, 6), name="old_results.csv", tag="o"))
    said = _say(capsys, monkeypatch, proj)[1]
    assert reads and reads[-1][1][0] == (proj / "runs" / "results.csv").resolve(), said
    assert "stopped looking after 5,000 files" in said, said
    (proj / "runs" / "results.csv").rename(proj / "zz-later.csv")
    (proj / "runs").rmdir()
    _many(proj / "zz", 1, ".txt")
    said = _say(capsys, monkeypatch, proj)[1]
    assert "stopped looking after 5,000 files" in said, said


def test_a_code_folder_under_a_project_with_marks_names_the_project(tmp_path, capsys,
                                                                    monkeypatch):
    """From proj/scripts/ (code), plain and `mark` agree with `check`: the marks are in
    the project above, run there; never "they come back when your results file is back"."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    table_project(proj / "evals", split(20, 20), tag="p")
    assert _say(capsys, monkeypatch, proj)[0] == 0
    _marked(proj, 14)
    _kind(proj / "scripts", "code")
    for argv in ((), ("mark",)):
        said = _say(capsys, monkeypatch, proj / "scripts", *argv)[1]
        assert "come back when your results file is back" not in said, (argv, said)
        assert "saved in the project above, in ../.judgekeeper/." in said, (argv, said)
        assert f"Next: run `judgekeeper {' '.join((*argv, '..'))} --port 0" in said, (argv, said)
    for argv in (("check",), ("fix",)):
        monkeypatch.chdir(proj / "scripts")
        project.forget()
        _, out, err = run(capsys, *argv)
        said = flat(out + err)
        assert "come back when your results file is back" not in said, (argv, said)
        assert "no saved results" not in said.lower(), (argv, said)
    assert not (proj / "scripts" / ".judgekeeper").exists()


def test_a_run_inside_judgekeepers_folder_never_reads_its_files(tmp_path, capsys,
                                                                monkeypatch):
    """Run in proj/.judgekeeper/, pool.jsonl is never read as answers and no
    .judgekeeper/ is made inside it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    table_project(proj / "evals", split(20, 20), tag="p")
    assert _say(capsys, monkeypatch, proj)[0] == 0
    _marked(proj, 6)
    jk = proj / ".judgekeeper"
    said = _say(capsys, monkeypatch, jk)[1]
    assert "pool.jsonl" not in said and "pool-judge.jsonl" not in said, said
    assert "Next: run `judgekeeper .. " in said, said
    assert not (jk / ".judgekeeper").exists(), said


def test_a_logs_folder_named_with_a_capital_is_found_once(tmp_path, capsys, monkeypatch):
    """On a disk that ignores case, Logs/ is the known logs/ folder: one folder."""
    from tests.start_projects import inspect_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    inspect_project(proj, split(6, 6), name="Logs/2026-10-02_support.json")
    said = _say(capsys, monkeypatch, proj)[1]
    assert "more than one folder" not in said, said
    assert "Answers:" in said, said


# Layouts the random trees found (tests/test_folder_fuzz.py) --------------------------------

def _tool_results(folder: Path, tool: str, n: int, tag: str) -> Path:
    """`tool`'s results in `folder` (promptfoo with its config: a sign the folder is one
    project), `n` answers of the questions `tag`."""
    verdicts = split(n // 2, n - n // 2)
    if tool == "promptfoo":
        return promptfoo_project(folder, verdicts, tag=tag)
    if tool == "deepeval":
        return deepeval_project(folder, verdicts, tag=tag)
    pytest.importorskip("inspect_ai")
    return inspect_project(folder, verdicts, tag=tag)


def _read_below(seen, top: Path, name: str) -> list[Path]:
    return [f for _, files in seen for f in files
            if f.is_relative_to((top / name).resolve())]


@pytest.mark.parametrize("tool", ["promptfoo", "deepeval", "inspect"])
def test_a_tools_results_in_a_project_below_are_never_read(tmp_path, capsys, monkeypatch,
                                                          reads, tool):
    """I1: top/ holds a tool's results; sub/, a git top of its own, the same tool's results
    of other questions. They are sub/'s: named, never read."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _tool_results(top, tool, 12, "t0")
    _kind(top / "sub", "git")
    _tool_results(top / "sub", tool, 6, "t1")
    said = _say(capsys, monkeypatch, top)[1]
    assert not _read_below(reads, top, "sub"), said
    assert "judgekeeper sub" in said, said


@pytest.mark.parametrize("run_in", [".", "sub"])
def test_a_projects_own_results_never_pool_folders_of_other_questions(tmp_path, capsys,
                                                                     monkeypatch, reads,
                                                                     run_in):
    """I2: top/ (pyproject.toml, results.csv) with c/ and data/, each a results.csv of its
    own questions, and sub/ empty. From top/ or sub/, they are named, never pooled."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, "file")
    table_project(top, split(3, 3), tag="t0")
    table_project(top / "c", split(3, 3), tag="t1")
    table_project(top / "data", split(3, 3), tag="t4")
    (top / "sub").mkdir()
    code, said = _say(capsys, monkeypatch, top / run_in)
    assert code == 3, said
    assert not _read_below(reads, top, "c") and not _read_below(reads, top, "data"), said
    up = "" if run_in == "." else "../"
    assert f"{up}c/ and {up}data/ hold eval results" in said, said
    assert not (top / ".judgekeeper").exists() and not (top / "sub" / ".judgekeeper").exists()


def test_a_tool_run_names_the_folder_above_only_when_that_tool_has_results_there(
        tmp_path, capsys, monkeypatch):
    """I5: c/ (judgekeeper.toml) holds DeepEval results in runs/; c/c/ answers.csv. `--tool
    table` in c/c reads answers.csv and never says to run `.. --tool table`, which finds no
    table there."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    c = tmp_path / "top" / "c"
    c.mkdir(parents=True)
    (c / "judgekeeper.toml").write_text("", encoding="utf-8")
    (c / "c").mkdir()
    write_answers(c / "c", 6, name="answers")
    deepeval_project(c / "runs", split(3, 3))
    said = _say(capsys, monkeypatch, c / "c", "--tool", "table")[1]
    assert "File: answers.csv" in said, said
    assert "Results in the folder above" not in said, said


def test_a_tool_with_no_results_says_so_in_plain_words(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    deepeval_project(top, split(3, 3))
    _kind(top, "git")
    said = _say(capsys, monkeypatch, top, "--tool", "table")[1]
    assert "No CSV, TSV or JSONL results file found in this folder." in said, said


@pytest.mark.parametrize("kind", ["judged", "file", "session"])
def test_a_named_file_of_a_project_below_is_checked_there(tmp_path, capsys, monkeypatch,
                                                          reads, kind):
    """I1/I4: `judgekeeper a/results.csv` from top/, a/ a project of its own (a project file,
    its own .judgekeeper/, or a session): stops and names the command to run in a/; nothing
    is written in top/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    a = top / "my evals" / "a"
    table_project(a, split(20, 20) if kind == "session" else split(3, 3), tag="a")
    _kind(a, "plain" if kind == "session" else kind)
    if kind == "session":
        assert _say(capsys, monkeypatch, a)[0] == 0
        reads.clear()
    before = _files(top)
    code, said = _say(capsys, monkeypatch, top, "my evals/a/results.csv", "--yes")
    assert code == 3, said
    assert "judgekeeper results.csv" in said and "a/" in said, said
    assert not reads, said
    assert _files(top) == before, said


def test_a_named_file_in_a_plain_folder_below_is_read_as_before(tmp_path, capsys,
                                                                monkeypatch, reads):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    table_project(top / "b", split(3, 3), tag="b")
    code, said = _say(capsys, monkeypatch, top, "b/results.csv")
    assert code in (0, 3) and "File: b/results.csv" in said, said
    assert reads and reads[-1][1] == [(top / "b" / "results.csv").resolve()], said


def _every_command_reads(capsys, monkeypatch, folder: Path, said: str) -> None:
    """I5 for every command `said` prints (test_folder_fuzz.commands), each pasted where its
    line says: none finds nothing."""
    from tests.test_folder_fuzz import NONE_FOUND, READS_ELSEWHERE, commands

    found = commands(said)
    assert found, said
    for where, args in found:
        if args[:1] and args[0] in READS_ELSEWHERE:
            continue
        said2 = _say(capsys, monkeypatch, (folder / where).resolve(),
                     *(a for a in args if a not in ("--no-browser", "--port", "0")))[1]
        assert not any(s in said2 for s in NONE_FOUND), (args, where, said, said2)


def test_a_tool_asked_for_pools_no_folders_of_other_questions(tmp_path, capsys, monkeypatch,
                                                              reads):
    """I2: top/ DeepEval results of its own; c/ and proj/ promptfoo results of other
    questions each. `--tool promptfoo` names them, never pools them."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    deepeval_project(top, split(3, 3), tag="t0")
    promptfoo_project(top / "c", split(3, 3), tag="t3", config=False)
    promptfoo_project(top / "proj", split(3, 3), tag="t0", config=False)
    code, said = _say(capsys, monkeypatch, top, "--tool", "promptfoo")
    assert code == 3, said
    assert not (_read_below(reads, top, "c") and _read_below(reads, top, "proj")), said
    assert "c/ and proj/ hold eval results" in said, said


def test_after_a_climb_every_printed_command_reads_from_where_it_ran(tmp_path, capsys,
                                                                    monkeypatch):
    """I5: data/b/ is empty; the git top above holds results.csv and data/ DeepEval results.
    The run reads the top and asks which tool: each command it prints, pasted in data/b/,
    reads them."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, "git")
    table_project(top, split(3, 3), tag="t0")
    deepeval_project(top / "data", split(3, 3), tag="t1")
    (top / "data" / "b").mkdir()
    said = _say(capsys, monkeypatch, top / "data" / "b")[1]
    assert "Reading the project folder above it" in said, said
    _every_command_reads(capsys, monkeypatch, top / "data" / "b", said)


def test_after_a_climb_the_folders_to_choose_from_are_named_from_where_it_ran(
        tmp_path, capsys, monkeypatch):
    """I5: proj/a/ is empty; the git top holds DeepEval results in proj/c/ and proj/my
    evals/: the folders it asks about are named from proj/a/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, "git")
    deepeval_project(top / "proj" / "c", split(3, 3), tag="t3")
    deepeval_project(top / "proj" / "my evals", split(3, 3), tag="t2")
    (top / "proj" / "a").mkdir()
    said = _say(capsys, monkeypatch, top / "proj" / "a")[1]
    _every_command_reads(capsys, monkeypatch, top / "proj" / "a", said)


def test_projects_nested_two_deep_are_named_all_the_way_down(tmp_path, capsys, monkeypatch):
    """I5: runs/ and runs/evals/ are git tops; runs/evals/my evals/ holds the results. From
    the top, each project named names the next, down to the results."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    top.mkdir()
    _kind(top / "runs", "git")
    _kind(top / "runs" / "evals", "git")
    inner = top / "runs" / "evals" / "my evals"
    _kind(inner, "file")
    deepeval_project(inner, split(3, 3))
    said = _say(capsys, monkeypatch, top)[1]
    _every_command_reads(capsys, monkeypatch, top, said)


def test_a_project_below_with_folder_asked_results_never_lets_two_folders_pool(
        tmp_path, capsys, monkeypatch, reads):
    """I2: top/ results.csv; evals/ a project of its own with DeepEval results (asked about
    by folder); c/ and runs/ results.csv files, c/'s of other questions. evals/'s results
    are its own and never let c/ and runs/ pool."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    table_project(top, split(3, 3), tag="t0")
    table_project(top / "c", split(3, 3), tag="t4")
    _kind(top / "evals", "file")
    deepeval_project(top / "evals", split(3, 3), tag="t0")
    table_project(top / "runs", split(3, 3), tag="t0")
    code, said = _say(capsys, monkeypatch, top)
    assert code == 3, said
    assert not (_read_below(reads, top, "c") and _read_below(reads, top, "runs")), said
    assert not _read_below(reads, top, "evals"), said


def test_a_tools_config_never_lets_folders_of_other_questions_pool(tmp_path, capsys,
                                                                   monkeypatch, reads):
    """I2: top/ promptfooconfig.yaml and results.json; proj/proj/ and sub/runs/ promptfoo
    results of other questions each. The config makes top/ one project, but those folders
    are other evals: named, never pooled."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    promptfoo_project(top, split(6, 6), tag="t0")
    promptfoo_project(top / "proj" / "proj", split(3, 3), tag="t5", config=False)
    promptfoo_project(top / "sub" / "runs", split(3, 3), tag="t2", config=False)
    code, said = _say(capsys, monkeypatch, top)
    assert code == 3, said
    assert not (_read_below(reads, top, "proj") and _read_below(reads, top, "sub")), said
    assert "proj/ and sub/" in said, said


def test_a_tools_config_still_pools_rounds_of_one_eval(tmp_path, capsys, monkeypatch, reads):
    """top/ promptfooconfig.yaml and results.json; runs/a/ and runs/b/ promptfoo results of
    the same questions: rounds of one eval, read together as before."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    promptfoo_project(top, split(6, 6), tag="t0")
    promptfoo_project(top / "a", split(3, 3), tag="t0", config=False)
    promptfoo_project(top / "b", split(3, 3), tag="t0", config=False)
    said = _say(capsys, monkeypatch, top)[1]
    assert "hold eval results" not in said, said
    assert _read_below(reads, top, "a") or _read_below(reads, top, "b"), said


def test_a_tools_config_pools_folders_that_share_questions(tmp_path, capsys, monkeypatch,
                                                           reads):
    """A test set that grew between runs: top/ promptfooconfig.yaml and results.json (6
    questions); a/ and b/ results of 12 and 9 questions, the first 6 the same. One eval."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    promptfoo_project(top, split(3, 3), tag="t0")
    promptfoo_project(top / "a", split(6, 6), tag="t0", config=False)
    promptfoo_project(top / "b", split(5, 4), tag="t0", config=False)
    said = _say(capsys, monkeypatch, top)[1]
    assert "hold eval results" not in said, said
    assert _read_below(reads, top, "a") and _read_below(reads, top, "b"), said


def test_a_tools_config_pools_dated_output_folders(tmp_path, capsys, monkeypatch, reads):
    """top/ promptfooconfig.yaml; outputs/2026-11-01/ and outputs/2026-11-02/ hold its
    results: one output folder, read together."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    promptfoo_project(top / "outputs" / "2026-11-01", split(3, 3), tag="t0")
    (top / "outputs" / "2026-11-01" / "promptfooconfig.yaml").rename(
        top / "promptfooconfig.yaml")
    promptfoo_project(top / "outputs" / "2026-11-02", split(3, 3), tag="t1", config=False)
    said = _say(capsys, monkeypatch, top)[1]
    assert "hold eval results" not in said, said
    assert _read_below(reads, top, "outputs"), said


@pytest.mark.parametrize("answers_here", [False, True])
def test_a_project_below_with_folder_asked_results_never_lets_folders_pool_from_above(
        tmp_path, capsys, monkeypatch, reads, answers_here):
    """I2: top/ (no results of its own, or answers with no grade); evals/ and proj/
    results.csv files of other questions; proj/data/ a project of its own with DeepEval
    results. evals/ and proj/ are named, never pooled."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    top.mkdir()
    if answers_here:
        write_answers(top, 6, name="answers")
    table_project(top / "evals", split(3, 3), tag="t1")
    table_project(top / "proj", split(3, 3), tag="t0")
    _kind(top / "proj" / "data", "file")
    deepeval_project(top / "proj" / "data", split(3, 3), tag="t3")
    code, said = _say(capsys, monkeypatch, top)
    assert code == 3, said
    assert not (_read_below(reads, top, "evals") and _read_below(reads, top, "proj")), said
    assert not _read_below(reads, top, "proj/data"), said


@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("top_kind", ["file", "git"])
def test_a_project_below_never_stops_a_folder_reading_the_project_above(
        tmp_path, capsys, monkeypatch, reads, top_kind, session):
    """I3: top/ (a project file or a git top) holds graded results, with a session on them or not;
    top/sub/ holds nothing but sub/q/, a project of its own with results. A run in sub/ reads
    top/ as with no q/ (only q/ named), and never q/'s file."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top, top_kind)
    results = table_project(top, split(20, 20), tag="t")
    if session:
        assert _say(capsys, monkeypatch, top)[0] == 0  # its session (a page, 0 marks)
    _kind(top / "sub" / "q", "file")
    table_project(top / "sub" / "q", split(6, 6), tag="q")
    reads.clear()
    _code, said = _say(capsys, monkeypatch, top / "sub")
    assert not _read_below(reads, top, "sub/q"), said
    assert reads and reads[-1][1] == [results.resolve()], said
    assert "The project in q/ has results too: to check them, run `judgekeeper q --no-browser`." \
        in said, said


@pytest.mark.parametrize("q_kind", ["file", "judged"])
def test_a_projects_own_format_file_below_is_never_read_from_a_plain_folder(
        tmp_path, capsys, monkeypatch, reads, q_kind):
    """I1: top/ (plain) holds nothing; q/, a project of its own, keeps scores in a format of
    its own. A run in top/ never reads q/'s file."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top / "q", q_kind)
    own_format_project(top / "q")
    _code, said = _say(capsys, monkeypatch, top)
    assert not _read_below(reads, top, "q"), said
    assert "q/data/prompt_evals.jsonl" not in said, said


def test_a_project_below_never_hides_a_folders_own_format_file(tmp_path, capsys, monkeypatch,
                                                                 reads):
    """I3: top/ (plain) keeps its scores in a format of its own; q/, a project of its own,
    holds a results.csv. A run in top/ maps top/'s file as with no q/, and never reads q/'s."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    top.mkdir()
    own_format_project(top)
    (top / "requirements.txt").unlink()  # no project: a plain folder
    (top / "evals" / "run_evals.py").unlink()
    _kind(top / "q", "file")
    table_project(top / "q", split(6, 6), tag="q")
    _code, said = _say(capsys, monkeypatch, top)
    assert "data/prompt_evals.jsonl looks like your LLM-as-a-judge's results" in said, said
    assert not _read_below(reads, top, "q"), said


@pytest.mark.parametrize("names", [("c", "proj"), ("a", "runs")])
def test_a_judge_setup_with_no_results_is_never_a_session_to_go_to(tmp_path, capsys,
                                                                   monkeypatch, names):
    """I8: t/ holds c/ (a .judgekeeper/ with only judge.json, no results) and proj/ (40
    answers, its session). A run in t/ sends the person to proj/ only, where the next run
    finds its results."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t"
    empty, kept = names
    _kind(top / empty, "judged")
    _kind(top / kept, "plain")
    write_answers(top / kept, 40, name="results")
    assert _say(capsys, monkeypatch, top / kept)[0] == 0  # its session (a page, 0 marks)
    code, said = _say(capsys, monkeypatch, top)
    assert code == 3, said
    assert f"{kept}/ already holds your judgekeeper session" in said, said
    assert f"`cd {kept}`" in said and f"{empty}/" not in said, said
    assert "No eval results found" not in _say(capsys, monkeypatch, top / kept)[1]


# Two evals are never one pool, wherever the files are ---------------------------------------


def _older(path: Path) -> Path:
    """`path` changed a day ago: the newest file is another."""
    then = time.time() - 86400
    os.utime(path, (then, then))
    return path


def _jsonl(folder: Path, n: int, tag: str) -> Path:
    path = folder / "results.jsonl"
    path.write_text("".join(json.dumps({"input": question(i, tag), "output": answer(i, tag),
                                        "verdict": "pass" if i % 2 else "fail"}) + "\n"
                            for i in range(n)), encoding="utf-8")
    return path


def _two_evals(proj: Path, layout: str, same: bool) -> tuple[Path, Path]:
    """(the newest file, an older one): of one eval when `same`, else of other questions."""
    other = "a" if same else "b"
    if layout == "top-and-archive":  # promptfoo at the top, an archived run two folders down
        _kind(proj, "git")
        newest = promptfoo_project(proj, split(6, 6), tag="a")
        older = promptfoo_project(proj / "archive" / "2025", split(6, 6), tag=other,
                                  config=False)
    elif layout == "top-and-old":  # a CSV at the top and one in old/
        _kind(proj, "file")
        newest = table_project(proj, split(5, 5), tag="a")
        older = table_project(proj / "old", split(5, 5), tag=other)
    elif layout == "jsonl-and-api":  # JSONL at the top, a CSV in api/
        _kind(proj, "git")
        newest = _jsonl(proj, 12, "a")
        older = table_project(proj / "api", split(6, 6), tag=other)
    else:  # one folder: results.csv and an older old_results.csv
        _kind(proj, "file")
        newest = table_project(proj, split(5, 5), tag="a")
        older = table_project(proj, split(5, 5), tag=other, name="old_results.csv")
    return newest, _older(older)


LAYOUTS = ["top-and-archive", "top-and-old", "jsonl-and-api", "one-folder"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_an_older_file_of_other_questions_never_joins_the_pool(tmp_path, capsys, monkeypatch,
                                                                reads, layout):
    """I2: the newest file is read alone; an older one of other questions is named, never
    pooled because the LLM-as-a-judge is the same."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    newest, older = _two_evals(proj, layout, same=False)
    said = _say(capsys, monkeypatch, proj)[1]
    assert reads and reads[-1][1] == [newest.resolve()], said
    assert older.relative_to(proj).as_posix() in said, said


@pytest.mark.parametrize("layout", LAYOUTS)
def test_an_older_round_of_the_same_eval_still_joins_the_pool(tmp_path, capsys, monkeypatch,
                                                               reads, layout):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    newest, older = _two_evals(proj, layout, same=True)
    said = _say(capsys, monkeypatch, proj)[1]
    assert reads and reads[-1][1] == [newest.resolve(), older.resolve()], said
    assert "1 older file" in said, said


@pytest.mark.parametrize("marker", [False, True])
def test_a_table_in_a_folder_named_logs_never_lets_two_evals_pool(tmp_path, capsys,
                                                                   monkeypatch, reads, marker):
    """I2: logs/ is Inspect AI's folder, not a CSV's: logs/ and b/ of other questions
    are named as a/ and b/ would be."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    _kind(work, "file" if marker else "plain")
    table_project(work / "logs", split(5, 5), tag="a")
    _older(table_project(work / "b", split(5, 5), tag="b"))
    code, said = _say(capsys, monkeypatch, work)
    assert code == 3, said
    assert "b/ and logs/ hold eval results" in said, said
    assert not reads, said


def _answers_csv(folder: Path, n: int, tag: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "answers.csv"
    path.write_text("input,output\n" + "".join(f"{question(i, tag)},{answer(i, tag)}\n"
                                                for i in range(n)), encoding="utf-8")
    return path


@pytest.mark.parametrize("above", [False, True])
@pytest.mark.parametrize("where", ["beside", "more"])
def test_a_newer_file_of_other_questions_never_replaces_a_sessions_answers(
        tmp_path, capsys, monkeypatch, reads, above, where):
    """I6: runs/ holds a session on answers.csv (6 answers with no grade), and t/ above it
    one of its own or not; a newer other.jsonl of other questions beside it or in more/ is
    named as another eval, never read in its place."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t"
    runs = top / "runs"
    marked = _answers_csv(runs, 6, "t2")
    if above:  # its session started while runs/ had none
        _answers_csv(top, 6, "t0")
        assert _say(capsys, monkeypatch, top)[0] == 0
    assert _say(capsys, monkeypatch, runs)[0] == 0
    other = runs / ("more" if where == "more" else "") / "other.jsonl"
    other.parent.mkdir(exist_ok=True)
    other.write_text("".join(json.dumps({"input": f"Unrelated {i}?", "output": f"Other {i}."})
                             + "\n" for i in range(15)), encoding="utf-8")
    later = time.time() + 60
    os.utime(other, (later, later))
    reads.clear()
    said = _say(capsys, monkeypatch, runs)[1]
    assert all(files == [marked.resolve()] for _, files in reads), said
    assert "looks like another eval" in said, said


@pytest.mark.parametrize("where", ["beside", "more"])
def test_a_newer_file_below_a_file_marked_from_above_is_another_eval(
        tmp_path, capsys, monkeypatch, reads, where):
    """I6 (seed 35831): t/'s session marks runs/answers.csv (runs/ holds code, no session of
    its own); a newer other.jsonl of other questions beside it or in runs/more/ never starts
    a session of its own in runs/: it looks like another eval."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t"
    _older(_answers_csv(top, 40, "t0"))
    _kind(top / "runs", "code")
    marked = _answers_csv(top / "runs", 12, "t2")
    assert _say(capsys, monkeypatch, top)[0] == 0  # t/'s session, on the newest: runs/'s
    other = top / "runs" / ("more" if where == "more" else "") / "other.jsonl"
    other.parent.mkdir(exist_ok=True)
    other.write_text("".join(json.dumps({"input": f"Unrelated {i}?", "output": f"Other {i}."})
                             + "\n" for i in range(15)), encoding="utf-8")
    later = time.time() + 60
    os.utime(other, (later, later))
    reads.clear()
    said = _say(capsys, monkeypatch, top / "runs")[1]
    assert all(files == [marked.resolve()] for _, files in reads), said
    assert "looks like another eval" in said, said
    assert not (top / "runs" / ".judgekeeper").exists(), said


def test_the_marked_file_overwritten_by_another_eval_adds_none_of_its_answers(
        tmp_path, capsys, monkeypatch):
    """I6: the session's results.csv is written again by another eval (other questions,
    the same ids): its answers are never added to the pool; it looks like another eval."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    ids = {"id": [f"r{i}" for i in range(40)]}
    path = table_project(proj, split(20, 20), tag="a", extra=ids)
    assert _say(capsys, monkeypatch, proj)[0] == 0  # its session (a page, 0 marks)
    pool = (proj / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8")
    table_project(proj, split(20, 20), tag="b", extra=ids)
    later = time.time() + 60
    os.utime(path, (later, later))
    said = _say(capsys, monkeypatch, proj)[1]
    assert "added for marking" not in said, said
    assert "looks like another eval" in said, said
    assert (proj / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8") == pool


# A tool's folder named by its variable, inside a project below, is that project's -----------


def _mono(tmp_path: Path, monkeypatch) -> Path:
    """mono/ (a git top) with results.csv of its own; svc/ a project of its own below."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    mono = tmp_path / "mono"
    _kind(mono, "git")
    table_project(mono, split(6, 6), tag="m")
    _kind(mono / "svc", "file")
    return mono


@pytest.mark.parametrize("argv", [(), ("--tool", "TOOL")])
@pytest.mark.parametrize("tool", ["inspect", "deepeval"])
def test_a_results_variable_into_a_project_below_is_never_read(tmp_path, capsys, monkeypatch,
                                                                reads, tool, argv):
    """I1: INSPECT_LOG_DIR or DEEPEVAL_RESULTS_FOLDER naming a folder in svc/ (a project
    below) is never read from mono/: svc/ is named, as with no variable."""
    mono = _mono(tmp_path, monkeypatch)
    if tool == "inspect":
        pytest.importorskip("inspect_ai")
        inspect_project(mono / "svc", split(6, 6), tag="s")
        monkeypatch.setenv("INSPECT_LOG_DIR", "svc/logs")
    else:
        deepeval_project(mono / "svc", split(6, 6), tag="s",
                         name="results/test_run_20261002_101010.json")
        monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", "svc/results")
    said = _say(capsys, monkeypatch, mono, *(a.replace("TOOL", tool) for a in argv))[1]
    assert not _read_below(reads, mono, "svc"), said
    assert "Saved results from more than one eval tool" not in said, said
    assert "svc" in said, said


def test_a_tracking_store_in_a_project_below_is_never_read(tmp_path, capsys, monkeypatch,
                                                           reads):
    """I1: MLFLOW_TRACKING_URI naming svc/mlruns (svc/ a project below) is never read
    from mono/ with --tool mlflow."""
    from tests.conftest import build_mlflow_folder_store

    mono = _mono(tmp_path, monkeypatch)
    build_mlflow_folder_store(mono / "svc" / "mlruns")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "svc/mlruns")
    said = _say(capsys, monkeypatch, mono, "--tool", "mlflow")[1]
    assert not _read_below(reads, mono, "svc"), said
    assert "svc" in said, said


def test_records_at_the_project_top_never_beat_a_nearer_session(tmp_path, capsys, monkeypatch,
                                                                reads):
    """I3: proj/ (a project file) keeps judgekeeper.record()'s files; proj/exp/ holds a
    session on another eval. A run in proj/exp/empty/ reads exp/, the nearest project."""
    from judgekeeper import start_label

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    records_project(proj, split(6, 6), tag="r")
    exp = proj / "exp"
    results = table_project(exp, split(20, 20), tag="e")
    (exp / ".judgekeeper").mkdir()
    assert _say(capsys, monkeypatch, exp)[0] == 0  # its session (a page)
    session = start_label.StartSession(start_label.Workspace(exp))
    for item in session.items[:4]:
        session.update({"id": item["id"], "label": "pass", "seconds": 3})
    (exp / "empty").mkdir()
    reads.clear()
    said = _say(capsys, monkeypatch, exp / "empty")[1]
    assert reads and reads[-1] == (exp.resolve(), [results.resolve()]), said
    assert "record()" not in said, said
    monkeypatch.chdir(exp / "empty")  # --stop there closes the page that run opened
    _, out, err = run(capsys, "--stop")
    assert "No marking page is open" not in out + err, out + err


@pytest.mark.parametrize("between", ["code", "records"])
def test_an_empty_folder_never_reads_a_session_past_a_nearer_project(tmp_path, capsys,
                                                                      monkeypatch, reads,
                                                                      between):
    """I3 (seeds 52010, 54496): t/ holds a session; t/mid/ is a project of its own (code, or
    judgekeeper.record()'s files). A run in the empty t/mid/empty/ never reads t/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t"
    table_project(top, split(3, 3), tag="t0")
    assert _say(capsys, monkeypatch, top)[0] == 3  # its session (judge.json)
    mid = top / "mid"
    if between == "code":
        _kind(mid, "code")
    else:
        records_project(mid, split(3, 3), tag="r")
    (mid / "empty").mkdir()
    reads.clear()
    said = _say(capsys, monkeypatch, mid / "empty")[1]
    assert all(root != top.resolve() for root, _ in reads), said


# A project below's file it can't read never decides the folder above ------------------------


def test_an_empty_file_in_a_project_below_never_stops_the_folder_above(tmp_path, capsys,
                                                                       monkeypatch, reads):
    """work/ holds nothing of its own; a/ (a project file) an empty results.json. The run
    in work/ names a/, never says a/'s file is empty from here."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    _kind(work / "a", "file")
    (work / "a" / "results.json").write_text("", encoding="utf-8")
    said = _say(capsys, monkeypatch, work)[1]
    assert "is empty" not in said and "a/results.json" not in said, said
    assert not reads, said


def test_a_too_big_file_in_a_project_below_is_never_offered_from_above(tmp_path, capsys,
                                                                       monkeypatch, reads):
    """work/ holds results.csv of its own; a/ (a project file) one over find.MAX_BYTES.
    The run reads work/'s file and offers no `--yes` for a/'s."""
    from judgekeeper import find

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    _kind(work, "plain")
    own = table_project(work, split(6, 6), tag="w")
    _kind(work / "a", "file")
    big = table_project(work / "a", split(20, 20), tag="a")
    monkeypatch.setattr(find, "MAX_BYTES", big.stat().st_size - 1)
    said = _say(capsys, monkeypatch, work)[1]
    assert "--yes" not in said and "to read it anyway" not in said, said
    assert reads and reads[-1][1] == [own.resolve()], said


def test_a_too_big_file_named_in_a_project_below_keeps_its_yes(tmp_path, capsys, monkeypatch):
    """`judgekeeper a/results.csv --yes` from work/ sends the person to a/ with a command
    that keeps --yes, so it reads the file there."""
    from judgekeeper import find

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    _kind(work / "a", "file")
    big = table_project(work / "a", split(20, 20), tag="a")
    monkeypatch.setattr(find, "MAX_BYTES", big.stat().st_size - 1)
    said = _say(capsys, monkeypatch, work, "a/results.csv", "--yes")[1]
    assert "belong to the project in a/" in said, said
    assert re.search(r"`judgekeeper results\.csv[^`]*--yes[^`]*` in a/", said), said


@pytest.mark.parametrize("given", [False, True])
def test_a_file_named_after_reading_the_session_above_is_named_from_here(tmp_path, capsys,
                                                                         monkeypatch, given):
    """I8 (seed 50210): evals/ holds a session; a run in evals/b/ reads evals/ and names the
    file it did not read by its path from b/, so the printed command finds it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    evals = tmp_path / "t" / "runs" / "evals"
    _older(table_project(evals, split(3, 3), tag="t2"))
    (evals / "b").mkdir()
    _jsonl(evals / "b", 6, "t1")
    assert _say(capsys, monkeypatch, evals)[0] == 3  # its judge.json
    run_in, args = (evals.parent, ("evals/b",)) if given else (evals / "b", ())
    said = _say(capsys, monkeypatch, run_in, *args)[1]
    _every_command_reads(capsys, monkeypatch, run_in, said)


# Folder corner cases -----------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["plain", "file"])
@pytest.mark.parametrize("sub", ["logs", "mlruns"])
@pytest.mark.parametrize("top", [False, True])
def test_a_table_in_a_folder_named_like_a_tools_is_found(tmp_path, capsys, monkeypatch, reads,
                                                         kind, sub, top):
    """A graded CSV in mlruns/ (no MLflow store) is found as one in logs/ is: the newest file,
    read before an older top.csv, and read when it is all there is."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    ml = tmp_path / "ml"
    _kind(ml, kind)
    if top:
        _older(table_project(ml, split(5, 5), tag="t", name="top.csv"))
    graded = table_project(ml / sub, split(6, 6), tag="g", name="graded.csv")
    said = _say(capsys, monkeypatch, ml)[1]
    assert reads and reads[-1][1] == [graded.resolve()], said


@pytest.mark.parametrize("argv", [(), ("..",)])
def test_a_run_from_an_empty_folder_stops_as_the_folder_above_does(tmp_path, capsys,
                                                                   monkeypatch, reads, argv):
    """repo/ (a git top) holds a/ (a project with a session), b/ and c/ on the same
    questions, and an empty folder. From the empty folder, the plain run does what
    `judgekeeper ..` does: it stops and names a/, b/ and c/, reading and writing nothing."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    repo = tmp_path / "repo"
    _kind(repo, "git")
    a = repo / "a"
    table_project(a, split(20, 20), tag="a")
    (a / ".judgekeeper").mkdir()
    assert _say(capsys, monkeypatch, a)[0] == 0  # its session (a page)
    _older(table_project(repo / "b", split(5, 5), tag="s"))
    table_project(repo / "c", split(5, 5), tag="s")
    (repo / "empty").mkdir()
    reads.clear()
    code, said = _say(capsys, monkeypatch, repo / "empty", *argv)
    assert code == 3, said
    assert not reads, said
    assert all(f"{name}/" in said for name in "abc"), said
    assert not (repo / ".judgekeeper").exists(), said
    assert not (repo / "empty" / ".judgekeeper").exists(), said


@pytest.mark.parametrize("kind", ["plain", "file"])
def test_a_folder_holding_only_a_linked_file_says_it_is_a_link(tmp_path, capsys, monkeypatch,
                                                                reads, kind):
    """repo/ (a git top) holds data/real-results.csv; names/link/ holds only results.csv, a
    link to it. A run in link/ says the file is a link judgekeeper doesn't follow, and never
    reads its target by another path (the repo top's) or writes in the repo top."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    repo = tmp_path / "repo"
    _kind(repo, "git")
    target = table_project(repo / "data", split(20, 20), tag="r", name="real-results.csv")
    link = repo / "names" / "link"
    _kind(link, kind)
    try:
        (link / "results.csv").symlink_to(target)
    except OSError:
        pytest.skip("no symbolic links here")
    said = _say(capsys, monkeypatch, link)[1]
    assert "results.csv (a link: judgekeeper doesn't follow links)" in said, said
    assert not any(target.resolve() in files for _, files in reads), said
    assert not (repo / ".judgekeeper").exists(), said


# Every command a run prints works where its line says --------------------------------------


def _every_command_works(capsys, monkeypatch, folder: Path, said: str) -> None:
    """Each command `said` prints, pasted where its line says, reads results: it never stops
    because they belong to another project or look like another eval (the fuzz's I9)."""
    from tests.test_folder_fuzz import NONE_FOUND, READS_ELSEWHERE, REFUSES, commands

    found = commands(said)
    assert found, said
    for where, args in found:
        if args[:1] and args[0] in READS_ELSEWHERE:
            continue
        code, said2 = _say(capsys, monkeypatch, (folder / where).resolve(),
                           *(a for a in args if a not in ("--no-browser", "--port", "0")))
        assert not any(s in said2 for s in NONE_FOUND), (args, where, said, said2)
        assert code != 3 or not any(s in said2 for s in REFUSES), (args, where, said, said2)


def test_a_project_whose_file_was_named_is_read_by_its_folder_from_above(tmp_path, capsys,
                                                                         monkeypatch, reads):
    """services/ holds loose/ (graded results) and rag/ (code and answers.csv, no grade).
    After `judgekeeper answers.csv` in rag/, the command the run in services/ prints for rag/
    reads rag/'s answers."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    table_project(tmp_path / "services" / "loose", split(5, 5), tag="l")
    rag = tmp_path / "services" / "rag"
    _kind(rag, "code")
    answers = _answers_csv(rag, 40, "r")
    _say(capsys, monkeypatch, rag, "answers.csv")
    assert (rag / ".judgekeeper" / "start.json").is_file()
    said = _say(capsys, monkeypatch, rag.parent)[1]
    assert "`judgekeeper rag" in said, said
    _every_command_works(capsys, monkeypatch, rag.parent, said)
    above = {p: p.stat().st_mtime_ns for p in (rag.parent / ".judgekeeper").rglob("*")}
    reads.clear()
    said = _say(capsys, monkeypatch, rag.parent, "rag")[1]
    assert reads and reads[-1] == (rag.resolve(), [answers.resolve()]), said
    assert above == {p: p.stat().st_mtime_ns for p in (rag.parent / ".judgekeeper").rglob("*")}


@pytest.mark.parametrize("layout", ["logs", "old"])
def test_another_eval_a_folder_away_is_named_as_one(tmp_path, capsys, monkeypatch, reads,
                                                    layout):
    """proj/ holds the newest results (in logs/, or at the top with an older file of other
    questions in old/) and another eval's file a folder away. The first run says it has
    other questions, as for one beside it, and prints no command that stops at it."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "plain")
    if layout == "logs":
        table_project(proj / "logs", split(5, 5), tag="a", name="graded.csv")
        other = _older(table_project(proj, split(3, 3), tag="b", name="top.csv"))
    else:
        table_project(proj, split(5, 5), tag="a")
        other = _older(table_project(proj / "old", split(3, 3), tag="b", name="other.csv"))
    said = _say(capsys, monkeypatch, proj)[1]
    rel = other.relative_to(proj).as_posix()
    assert f"Also found {rel}, with other questions" in said, said
    assert f"`judgekeeper {rel}" not in said, said


def test_a_file_left_out_in_a_project_below_names_the_project(tmp_path, capsys, monkeypatch,
                                                              reads):
    """top/ (plain) holds q/ (a project file) with data/prompt_evals.jsonl, too deep to read
    from top/. `judgekeeper .` in top/ names q/, and the command it prints reads the file."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    q = top / "q"
    _kind(q, "file")
    (q / "data").mkdir()
    path = _jsonl(q / "data", 6, "q")
    path = path.rename(q / "data" / "prompt_evals.jsonl")
    said = _say(capsys, monkeypatch, top, ".")[1]
    assert "q/data/prompt_evals.jsonl" in said, said
    assert "`judgekeeper q/data/prompt_evals.jsonl" not in said, said
    reads.clear()
    _every_command_works(capsys, monkeypatch, top, said)
    assert reads and reads[-1][1] == [path.resolve()]


def test_a_judge_set_up_by_a_named_file_never_sends_runs_back_and_forth(tmp_path, capsys,
                                                                       monkeypatch, reads):
    """data/ holds results.csv, named once (too few answers: only its judge.json is written),
    and a/ and data/ below it results of other questions. A run in data/ reads its own
    folder, as a run in a/ does (it uses the judge.json above), and every command either
    prints works."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    data = tmp_path / "t" / "data"
    table_project(data, split(3, 3), tag="t0")
    table_project(data / "a", split(3, 3), tag="t2")
    table_project(data / "data", split(3, 3), tag="t2")
    _say(capsys, monkeypatch, data, "results.csv")
    assert (data / ".judgekeeper" / "judge.json").is_file()
    assert not (data / ".judgekeeper" / "start.json").exists()
    for folder in (data, data / "a"):
        reads.clear()
        said = _say(capsys, monkeypatch, folder)[1]
        assert reads and reads[-1][0] == data.resolve(), said
        if "`judgekeeper" in said.replace("`judgekeeper mark", ""):
            _every_command_works(capsys, monkeypatch, folder, said)


def test_an_empty_folder_never_reads_a_named_file_past_a_nearer_project(tmp_path, capsys,
                                                                         monkeypatch, reads):
    """I3: t/ holds a session on answers.csv, named; t/b/ holds code. A run in the empty
    t/b/runs/ never reads t/'s file past b/."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "t"
    _answers_csv(top, 6, "t0")
    _say(capsys, monkeypatch, top, "answers.csv")
    assert (top / ".judgekeeper" / "start.json").is_file()
    _kind(top / "b", "code")
    (top / "b" / "runs").mkdir()
    reads.clear()
    said = _say(capsys, monkeypatch, top / "b" / "runs")[1]
    assert all(root != top.resolve() for root, _ in reads), said
