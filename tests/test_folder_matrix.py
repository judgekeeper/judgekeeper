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
from tests.start_projects import (
    deepeval_project,
    inspect_project,
    own_format_project,
    promptfoo_project,
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
    code, said = _say(capsys, monkeypatch, top / "sub")
    assert not _read_below(reads, top, "sub/q"), said
    assert reads and reads[-1][1] == [results.resolve()], said
    assert "The project in q/ has results too: to check them, run `judgekeeper q`." in said, said


@pytest.mark.parametrize("q_kind", ["file", "judged"])
def test_a_projects_own_format_file_below_is_never_read_from_a_plain_folder(
        tmp_path, capsys, monkeypatch, reads, q_kind):
    """I1: top/ (plain) holds nothing; q/, a project of its own, keeps scores in a format of
    its own. A run in top/ never reads q/'s file."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    top = tmp_path / "top"
    _kind(top / "q", q_kind)
    own_format_project(top / "q")
    code, said = _say(capsys, monkeypatch, top)
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
    code, said = _say(capsys, monkeypatch, top)
    assert "data/prompt_evals.jsonl looks like your LLM-as-a-judge's results" in said, said
    assert not _read_below(reads, top, "q"), said
