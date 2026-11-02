"""`check` given the project folder from another folder: a Next line that names a file from
the project says to run it in your project folder, with the program named from there; a
command with no such file is given the project folder, so it runs where it is printed."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import pytest

from judgekeeper import fix
from judgekeeper.start_label import Workspace
from tests.test_project_folder_commands import USER, _commands, _program_in, _run, _started, home

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="a venv's scripts are .exe files there")
__all__ = ["home"]  # the fixture, used by name

CHECK_LINE = "then in your project folder, run `"


def _truth(i: int) -> bool:
    return i % 3 != 0


def _worse_project(proj: Path, monkeypatch, capsys) -> None:
    """A table judge marked on, then new grades that are worse (as tests/test_verdict_words
    makes them)."""
    from tests.start_projects import table_project
    from tests.test_flow_across_runs import _mark

    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(60)]
    table_project(proj, old)
    assert _run(capsys, "--no-browser")[0] == 0
    _mark(Workspace(proj), {i: "pass" if _truth(i) else "fail" for i in range(60)})
    _run(capsys, "--no-browser")
    table_project(proj, [(not v) if i % 2 == 0 or i % 4 == 1 else v
                         for i, v in enumerate(old)])


def _new_results(proj: Path) -> None:
    """marked-answers.csv graded again, as the old judge graded it: no drop."""
    import csv

    with (proj / ".judgekeeper" / "fix" / "marked-answers.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with (proj / "new.csv").open("w", encoding="utf-8", newline="") as f:
        out = csv.writer(f)
        out.writerow(["input", "output", "verdict"])
        for r in rows:
            i = int(r["question"].split("Question ")[1].split("?")[0])
            out.writerow([r["question"], r["answer"],
                          "pass" if ((not _truth(i)) if i % 4 == 1 else _truth(i)) else "fail"])


def _typed(line: str, home: Path) -> list[str]:
    """The arguments a command passes to the program, `~/` made the home folder by the
    shell."""
    return [str(home / x[2:]) if x.startswith("~/") else x for x in shlex.split(line)[1:]]


@pytest.mark.parametrize("where", ["above", "far"])
def test_check_from_another_folder_names_its_lines_from_the_project(home, monkeypatch, capsys,
                                                                     where):
    """"Worse" for a table judge: `fix` given the project, then "then in your project folder,
    run `<program> check <new results file>`"; each filled in and run as it says."""
    proj = home / "Desktop" / "Testing Judge" / "team" / "proj s3"
    _worse_project(proj, monkeypatch, capsys)
    away = proj.parent if where == "above" else home.parent.parent
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    given = os.path.relpath(proj, away)
    code, out = _run(capsys, "check", given)
    assert code == 1 and "Worse" in out, out
    nxt = out[out.rindex("Next: "):]
    assert CHECK_LINE in nxt, nxt
    fix_line, check_line = _commands(nxt)
    assert _program_in(fix_line, away, home) == tool, fix_line
    assert _program_in(check_line, proj, home) == tool, check_line
    assert check_line.endswith(f" check {fix.NEW_RESULTS}"), check_line
    assert USER not in check_line

    code, out = _run(capsys, *_typed(fix_line, home))  # where it was printed
    assert code == 0, out
    code, out = _run(capsys, "check", given)
    nxt = out[out.rindex("Next: "):]
    assert CHECK_LINE in nxt, nxt
    (check_line,) = _commands(nxt)
    assert _program_in(check_line, proj, home) == tool, check_line
    _new_results(proj)
    monkeypatch.chdir(proj)  # where the line says it runs
    code, out = _run(capsys, *shlex.split(check_line.replace(fix.NEW_RESULTS, "new.csv"))[1:])
    assert code in (0, 1) and "No marks in this folder" not in out, out
    assert "new.csv" in out, out


def test_check_from_the_project_keeps_its_lines(home, monkeypatch, capsys):
    proj = home / "Desktop" / "Testing Judge" / "team" / "proj"
    _worse_project(proj, monkeypatch, capsys)
    _started(monkeypatch, home)
    code, out = _run(capsys, "check")
    nxt = out[out.rindex("Next: "):]
    assert code == 1 and "in your project folder" not in nxt, out
    assert "run `../../../Tools/train/.venv/bin/judgekeeper fix` to write" in nxt, nxt


def test_check_steps_from_the_folder_above_name_the_program_from_the_project(home, monkeypatch,
                                                                             capsys):
    """promptfoo's three steps after check: "3. Then, in your project folder: `<program>
    check .judgekeeper/fix/new.json`", and `--new` given the project."""
    from tests.test_only_reads import project as any_project
    from tests.test_regrade_yaml import _none_in

    proj = home / "Desktop" / "Testing Judge" / "team" / "support-bot"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    any_project("promptfoo", proj, monkeypatch)
    _none_in(proj)
    capsys.readouterr()
    monkeypatch.chdir(proj.parent)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, "check", "support-bot")  # its newest results: new.json
    assert code == 3, out
    step = out[out.index("3. Then, in your project folder: "):]
    line = _commands(step)[0]
    assert line.endswith(" check .judgekeeper/fix/new.json"), line
    assert _program_in(line, proj, home) == tool, line
    fresh = _commands(out[out.rindex("Next: "):])[-1]
    assert shlex.split(fresh)[1:] == ["--new", "support-bot"], fresh
    assert _program_in(fresh, proj.parent, home) == tool, fresh


@pytest.mark.parametrize("where", ["root", "above", "far"])
def test_mistakes_md_names_the_program_plainly(home, monkeypatch, capsys, where):
    """mistakes.md is a file in .judgekeeper/: it names `judgekeeper check`, never a path."""
    proj = home / "Desktop" / "Testing Judge" / "team" / "proj s3"
    _worse_project(proj, monkeypatch, capsys)
    away = {"root": Path("/"), "above": proj.parent, "far": home.parent.parent}[where]
    monkeypatch.chdir(away)
    _started(monkeypatch, home)
    given = str(proj) if where == "root" else os.path.relpath(proj, away)
    code, out = _run(capsys, "check", given)
    assert code == 1 and "Worse" in out, out
    code, out = _run(capsys, "fix", given)
    assert code == 0, out
    text = (proj / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert "`judgekeeper check` found it worse" in text, text
    for part in ("/", "venv", "~"):
        assert part not in text, part
