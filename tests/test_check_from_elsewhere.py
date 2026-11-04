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
    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
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


@pytest.mark.parametrize("where", ["above", "far"])
def test_judgekeeper_from_another_folder_after_worse_names_the_program_from_the_project(
        home, monkeypatch, capsys, where):
    """Plain `judgekeeper <project>` after "Worse": the terminal says "then in your project
    folder, run `<program> check <new results file>`"; report.html keeps the plain form, as it
    is read in the project folder."""
    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
    _worse_project(proj, monkeypatch, capsys)
    away = proj.parent if where == "above" else home.parent.parent
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    given = os.path.relpath(proj, away)
    code, out = _run(capsys, "check", given)
    assert code == 1 and "Worse" in out, out
    code, out = _run(capsys, given, "--no-browser", "--port", "0")
    assert code == 0, out
    nxt = out[out.rindex("Next: "):]
    assert CHECK_LINE in nxt, nxt
    check_line = _commands(nxt)[-1]
    assert _program_in(check_line, proj, home) == tool, check_line
    assert check_line.endswith(f" check {fix.NEW_RESULTS}"), check_line
    for line in _commands(nxt)[:-1]:  # `fix`, run where it is printed
        assert _program_in(line, away, home) == tool, line
    import html
    import re

    page = (proj / ".judgekeeper" / "report.html").read_text(encoding="utf-8")
    page = " ".join(html.unescape(re.sub(r"<[^>]+>", "", page)).split())
    assert "in your project folder" not in page
    assert f"then run judgekeeper check {fix.NEW_RESULTS}." in page, page


def test_check_from_the_project_keeps_its_lines(home, monkeypatch, capsys):
    proj = home / "Desktop" / "My Work" / "team" / "proj"
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

    proj = home / "Desktop" / "My Work" / "team" / "support-bot"
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
    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
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


@pytest.mark.parametrize("where", ["above", "far"])
def test_the_wait_line_from_another_folder_names_the_program_from_the_project(
        home, monkeypatch, capsys, where):
    """Marks wait after `check` took on a rule that graded only the marked answers. From
    another folder the terminal says "then in your project folder, run `<program> check <new
    results file>`", with the program as it is from there; result.json and report.html name
    it plainly and hold no path."""
    import json

    from tests.test_waiting_marks import adopt_records

    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    adopt_records(proj, monkeypatch, capsys)
    away = proj.parent if where == "above" else home.parent.parent
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, os.path.relpath(proj, away), "--no-browser", "--port", "0")
    assert code == 0, out
    nxt = out[out.rindex("Next: "):]
    assert ("Next: grade all your answers with your new LLM-as-a-judge, " + CHECK_LINE) in nxt
    check_line = _commands(nxt)[-1]
    assert _program_in(check_line, proj, home) == tool, check_line
    assert check_line.endswith(f" check {fix.NEW_RECORDS}"), check_line
    saved = json.loads((proj / ".judgekeeper" / "result.json").read_text(encoding="utf-8"))
    assert saved["waiting_check"] == f"judgekeeper check {fix.NEW_RECORDS}"
    import html
    import re

    page = (proj / ".judgekeeper" / "report.html").read_text(encoding="utf-8")
    assert "Tools" not in page and USER not in page
    page = " ".join(html.unescape(re.sub(r"<[^>]+>", "", page)).split())
    assert f"then run judgekeeper check {fix.NEW_RECORDS}." in page, page


@pytest.mark.parametrize("where", ["above", "far"])
def test_a_line_that_sends_you_to_a_project_names_the_program_from_there(home, monkeypatch,
                                                                         capsys, where):
    """A results file of a project with its own session, given from another folder: "To check
    them, run `<program>` in proj b3/", with the program as it is typed in proj b3/."""
    from tests.test_earlier_grades import adopt

    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    adopt(proj, capsys)
    away = proj.parent if where == "above" else home.parent.parent
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, os.path.relpath(proj / "v2.json", away), "--no-browser")
    assert code == 3 and "To check them, run `" in out, out
    for line in _commands(out[out.index("To check them"):]):
        assert _program_in(line, proj, home) == tool, (line, out)


@pytest.mark.parametrize("where", ["above", "far"])
def test_check_sending_you_to_a_project_names_the_program_from_there(home, monkeypatch,
                                                                     capsys, where):
    """`check` on a results file of a project with a session of its own, from another
    folder: the program in "run ... in <project>/" as it is typed there."""
    from tests.test_earlier_grades import adopt

    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    adopt(proj, capsys)
    away = proj.parent if where == "above" else home.parent.parent
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, "check", os.path.relpath(proj / "v2.json", away))
    lines = [x for x in _commands(out) if "judgekeeper" in x]
    assert code == 3 and lines and "proj b3/" in out, out
    for line in lines:
        assert _program_in(line, proj, home) == tool, (line, out)


TEAM = "~/Desktop/My Work/team/proj b3"


@pytest.mark.parametrize(("where", "named"), [
    ("above", "proj b3"), ("homes", TEAM), ("far", TEAM), ("top", TEAM)])
@pytest.mark.parametrize("command", [[], ["check"]])
def test_a_project_elsewhere_is_named_without_a_user_name(home, monkeypatch, capsys, where,
                                                          named, command):
    """Run from far above (the folder of home folders, a top folder) a project in the home
    folder is `~/...`: never a user name, and every command it names runs where it says."""
    from tests.test_earlier_grades import adopt

    proj = home / "Desktop" / "My Work" / "team" / "proj b3"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    adopt(proj, capsys)
    away = {"above": proj.parent, "homes": home.parent, "far": home.parent.parent,
            "top": Path("/")}[where]
    monkeypatch.chdir(away)
    tool = _started(monkeypatch, home)
    code, out = _run(capsys, *command, os.path.relpath(proj / "v2.json", away),
                     *([] if command else ["--no-browser"]))
    assert code == 3 and f"These results belong to the project in {named}/." in out, out
    assert USER not in out, out
    folder = home / named[2:] if named.startswith("~") else away / named
    for line in _commands(out):
        if "judgekeeper" in line:
            assert _program_in(line, folder, home) == tool, (line, out)


@pytest.mark.parametrize(("given", "said"), [
    ("{home}/Desktop/My Work/evals-new/missing.csv",
     "There is no file named missing.csv in ../evals-new/."),
    ("sub/missing.csv", "There is no file named missing.csv in sub/."),
    ("missing.csv", "There is no file named missing.csv here."),
    ("missing", "There is no file or folder named missing here."),
    ("../c9", "There is no file or folder named c9 in the folder above."),
    # a folder named from nowhere near: as typed from the top, never as one here
    ("/nonexistent-jk/x.csv", "There is no file named x.csv in /nonexistent-jk/."),
    ("/nonexistent-jk/deep/x.csv", "There is no file named x.csv in /\u2026/deep/."),
    ("/x.csv", "There is no file named x.csv in /."),
])
@pytest.mark.parametrize("command", ["check", "fix"])
def test_a_missing_path_names_the_folder_it_was_looked_for_in(home, monkeypatch, capsys, given,
                                                              said, command):
    proj = home / "Desktop" / "My Work" / "evals"
    proj.mkdir(parents=True)
    monkeypatch.chdir(proj)
    code, out = _run(capsys, command, given.format(home=home))
    assert code != 0 and said in out and USER not in out, out


@pytest.mark.parametrize(("given", "said"), [
    ("{home}/x.csv", "There is no file named x.csv in ~/."),
    ("{home}/Desktop/x.csv", "There is no file named x.csv in ~/Desktop/."),
])
def test_a_missing_path_in_home_named_from_outside_it_is_named_from_home(home, monkeypatch,
                                                                         capsys, given, said):
    monkeypatch.chdir(home.parent)
    (home / "Desktop").mkdir(exist_ok=True)
    code, out = _run(capsys, "check", given.format(home=home))
    assert code != 0 and said in out and USER not in out, out


@pytest.mark.parametrize(("folder", "at", "shown"), [
    ("{home}/Desktop/a b/p", "{home}/Desktop", "a b/p"),
    ("{home}/Desktop/p", "/", "~/Desktop/p"),
    ("{home}/Desktop/p", "{users}", "~/Desktop/p"),
    ("{users}/bob/work/p", "{home}", "/…/p"),
    ("{users}/bob/work/p", "/", "/…/p"),
    ("{top}/data/p", "{top}", "data/p"),
])
def test_a_folder_is_named_from_here_without_a_user_name(home, monkeypatch, folder, at, shown):
    """As a line names a folder to go to: from here, in the home folder as `~/...`, in
    another person's home folder cut short to its own name; and back again to the folder."""
    from judgekeeper import textio

    names = {"home": home, "users": home.parent, "top": home.parent.parent}
    folder, at = Path(folder.format(**names)), Path(at.format(**names))
    folder.mkdir(parents=True)
    monkeypatch.chdir(at)
    assert textio.folder_from_here(folder) == shown
    back = textio.folder_of(shown, at)
    assert back == textio.ANYWHERE if "…" in shown else Path(back).resolve() == folder
    if shown.startswith("~/"):
        assert textio.cd_word(shown) == "~/" + textio.quote_arg(shown[2:])
