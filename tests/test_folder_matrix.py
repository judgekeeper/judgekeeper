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
import shlex
import time
from pathlib import Path

import pytest

from judgekeeper import front, project
from tests.start_projects import split, table_project
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


# The folder review's trees: a tool's folder, the walk's limits, a code folder, .judgekeeper/ --


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
    """H3: `judgekeeper logs`, as the choice of folders prints it, marks in proj/, never in
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
    """H3, DeepEval: a results folder named as PATH is no project of its own."""
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


def test_many_json_files_never_hide_the_results(tmp_path, capsys, monkeypatch, reads):
    """H2 (a): 250 JSON documents in data/ use up no budget the eval's folder needs."""
    from tests.start_projects import promptfoo_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    _many(proj / "data", 250, ".json", '{"text": "a document"}')
    promptfoo_project(proj / "evals", split(6, 6), tag="e")
    said = _say(capsys, monkeypatch, proj)[1]
    assert reads and reads[-1][1] == [(proj / "evals" / "results.json").resolve()], said


def test_the_sessions_own_file_is_always_found(tmp_path, capsys, monkeypatch, reads):
    """H2 (b): after marking, 250 JSON files sorted before the results never make plain,
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
    """H2 (c): over 5,000 files: the folder named like results is looked in first, and the
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
    """M2: from proj/scripts/ (code), plain and `mark` agree with `check`: the marks are in
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
    """M4: run in proj/.judgekeeper/, pool.jsonl is never read as answers and no
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
    """L1: on a disk that ignores case, Logs/ is the known logs/ folder: one folder."""
    from tests.start_projects import inspect_project

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    proj = tmp_path / "proj"
    _kind(proj, "file")
    inspect_project(proj, split(6, 6), name="Logs/2026-10-02_support.json")
    said = _say(capsys, monkeypatch, proj)[1]
    assert "more than one folder" not in said, said
    assert "Answers:" in said, said
