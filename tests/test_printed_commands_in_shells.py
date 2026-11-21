"""A command judgekeeper prints is safe to paste into any shell.

- `quote_arg` never prints the `$'...'` form (dash does not read it); a value with a backtick
  is said as data under the line, as on Windows.
- A path that starts with "-" is printed as `./name`: the command reads it as a file.
- Every printed command, for hostile file names, is run in the shells installed (dash and sh
  among them) with the program swapped for a script that records its arguments: one argument
  with the exact value, and no other command runs.
No test calls an AI API.
"""

from __future__ import annotations

import csv
import os
import random
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from judgekeeper import start, textio
from judgekeeper.cli import main

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells' quoting")

MARKER = "PWNED"  # all a payload below does: create this file in the folder the test runs in
SHELLS = [s for s in ("/bin/dash", "/bin/sh", "/bin/bash", "/bin/zsh") if os.path.exists(s)]
HOSTILE = [
    "a`b'; touch PWNED #",
    "`touch PWNED`",
    "it's; touch PWNED",
    "x;touch PWNED;y",
    "x # y",
    "$(touch PWNED)",
    "a\nb",
    "-x",
    "--labels=extra.csv",
    "--new",
    "a\\",
    "\\'; touch PWNED; '",
    "&& touch PWNED",
    "$'\\x60touch PWNED\\x60'",
]


def recorder(folder: Path) -> Path:
    """A script that writes its arguments, each ended by NUL, to `record-args.args`."""
    script = folder / "record-args"
    script.write_text("#!/bin/sh\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > \"$0.args\"\n",
                      encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def shell_args(shell: str, line: str, folder: Path) -> list[str]:
    """`line` run by `shell` in `folder` (the recorder is in its parent): the arguments the
    recorder got. No payload may have run."""
    got = folder.parent / "record-args.args"
    got.unlink(missing_ok=True)
    done = subprocess.run([shell, "-c", line], cwd=folder, capture_output=True, text=True,
                          check=False)
    assert not (folder / MARKER).exists(), f"{shell} ran a payload: {line!r}"
    assert done.returncode == 0, (shell, line, done.stderr)
    return got.read_text(encoding="utf-8").split("\0")[:-1]


def swapped(command: str, tmp_path: Path) -> str:
    """A printed command with its program (`judgekeeper`) swapped for the recorder."""
    program, _, rest = command.partition(" ")
    assert program == "judgekeeper", command
    return f"{shlex.quote(str(recorder(tmp_path)))} {rest}"


# quote_arg --------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", HOSTILE)
def test_quote_arg_never_prints_the_dollar_quote_form(value):
    textio._held.clear()
    quoted = textio.quote_arg(value)
    textio._held.clear()
    if "`" in value:  # no quotes carry it for every shell: said as data under the line
        assert quoted == textio.PLACEHOLDER
    else:
        assert quoted == shlex.quote(value)


@pytest.mark.parametrize("value", [v for v in HOSTILE if "`" not in v])
@pytest.mark.parametrize("shell", SHELLS)
def test_quote_arg_gives_one_argument_with_the_exact_value(tmp_path, shell, value):
    work = tmp_path / "work"
    work.mkdir()
    line = f"{shlex.quote(str(recorder(tmp_path)))} {textio.quote_arg(value)}"
    assert shell_args(shell, line, work) == [value]


@pytest.mark.parametrize("value", [v for v in HOSTILE if "`" in v])
def test_a_value_with_a_backtick_is_said_as_data_under_the_line(value):
    textio._held.clear()
    assert textio.quote_arg(value) == textio.PLACEHOLDER
    line = f"Next: run `judgekeeper {textio.PLACEHOLDER} --no-browser`."
    assert len(textio.held_lines(line)) == 1
    assert textio.held_lines(line) == []  # said once


def test_a_kept_command_leaves_its_backtick_value_to_be_said_beside_it():
    textio._held.clear()
    assert textio.quote_arg("a`b", kept=True) == textio.PLACEHOLDER
    assert textio._held == {}
    assert textio.held_back("a`b") and not textio.held_back("a'b")
    assert start.held_values({"path": "a`b", "metric": "m"}) == ["a`b"]


def flag_words(value: str) -> list[str]:
    """What start.command_from prints after `mark` for the same `value` as the path, the
    metric, the model and the label map, as each shell must read it."""
    words = ["./" + value if value.startswith("-") else value]
    for name, flag in start.REPEATED:
        if name in ("metric", "label_map", "judge_model"):
            words += [f"{flag}={value}"] if value.startswith("-") else [flag, value]
    return words


@pytest.mark.parametrize("value", [v for v in HOSTILE if "\n" not in v and "`" not in v])
@pytest.mark.parametrize("shell", ["/bin/dash", "/bin/sh"])
def test_a_path_a_metric_a_model_and_a_label_map_each_run_as_one_argument(tmp_path, shell,
                                                                         value):
    if shell not in SHELLS:
        pytest.skip(f"{shell} is not installed")
    work = tmp_path / "work"
    work.mkdir()
    command = start.command_from({"path": value, "metric": value, "judge_model": value,
                                  "label_map": value}, "mark")
    assert shell_args(shell, swapped(command, tmp_path), work) == ["mark", *flag_words(value)]


def test_a_backtick_in_a_metric_or_model_name_is_said_as_data():
    textio._held.clear()
    command = start.command_from({"path": ".", "metric": "m`x`", "judge_model": "j`y"}, "mark")
    assert command == "judgekeeper mark --metric NAME --judge-model NAME"
    assert list(textio._held) == ["m`x`", "j`y"]
    textio._held.clear()


# Printed commands for hostile file names -------------------------------------------------------

def write_results(path: Path, seed: int = 1) -> None:
    rnd = random.Random(seed)
    with path.open("w", newline="", encoding="utf-8") as f:
        out = csv.writer(f)
        out.writerow(["input", "output", "verdict"])
        for i in range(40):
            out.writerow([f"Q{i}", f"A{i}", rnd.choice(["pass", "fail"])])


def project_with(tmp_path: Path, other: str) -> Path:
    """A project folder with results.csv and an older second results file named `other`."""
    work = tmp_path / "work"
    work.mkdir()
    write_results(work / "results.csv")
    write_results(work / other, seed=2)
    old = time.time() - 3600
    os.utime(work / other, (old, old))
    return work


def printed_commands(out: str) -> list[str]:
    """Each `judgekeeper ...` in backticks, with the wrapping undone."""
    return re.findall(r"`(judgekeeper(?: [^`]*)?)`", " ".join(out.split()))


FILE_NAMES = ["--labels=x.csv", "--new.csv", "-x.csv", "a`b'; touch PWNED #.csv",
              "it's; touch PWNED.csv", "$(touch PWNED).csv", "x;touch PWNED;y.csv",
              "a #b.csv"]


@pytest.mark.parametrize("name", FILE_NAMES)
def test_the_command_for_another_results_file_reads_it_as_a_file(tmp_path, monkeypatch,
                                                                 capsys, name):
    work = project_with(tmp_path, name)
    monkeypatch.chdir(work)
    textio._held.clear()
    assert main(["--no-browser", "--port", "0"]) == 0
    out = capsys.readouterr().out
    shown = [c for c in printed_commands(out) if "results.csv" not in c]
    assert shown, out
    for command in shown:
        if textio.PLACEHOLDER in command:  # a backtick: the value is said as data
            assert "`" in name and f"  NAME: {name}\n" in out, out
            continue
        want = ["./" + name if name.startswith("-") else name, "--port", "0", "--no-browser"]
        for shell in SHELLS:
            assert shell_args(shell, swapped(command, tmp_path), work) == want, command


def test_a_flag_named_file_is_read_as_a_file_with_nothing_imported(tmp_path, monkeypatch,
                                                                    capsys):
    """The command printed for a file named `--labels=extra.csv`, run as printed, reads that
    file and imports no marks from another."""
    work = project_with(tmp_path, "--labels=extra.csv")
    write_results(work / "extra.csv", seed=3)
    monkeypatch.chdir(work)
    assert main(["--no-browser", "--port", "0"]) == 0
    out = capsys.readouterr().out
    assert "judgekeeper ./--labels=extra.csv" in " ".join(out.split()), out
    assert main(["./--labels=extra.csv", "--no-browser", "--port", "0"]) == 0
    out = capsys.readouterr().out
    assert "Added" not in out and "marks from extra.csv" not in out, out
    assert "--labels=extra.csv has LLM-as-a-judge grades" in " ".join(out.split()), out


@pytest.mark.parametrize("name", ["x;touch PWNED", "my project", "-proj"])
def test_the_command_for_the_project_above_a_code_folder_is_one_argument(
        tmp_path, monkeypatch, capsys, name):
    """Run from outside, on a code folder of a marked project: the command names the project
    folder, whatever it is called."""
    from judgekeeper import project
    from tests.start_projects import split, table_project
    from tests.test_folder_matrix import _kind, _marked, _say

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    work = tmp_path / "work"
    proj = work / name
    _kind(proj, "file")
    table_project(proj / "evals", split(20, 20), tag="p")
    _say(capsys, monkeypatch, proj)
    _marked(proj, 14)
    _kind(proj / "scripts", "code")
    said = _say(capsys, monkeypatch, work, f"./{name}/scripts")[1]
    commands = printed_commands(said)
    assert commands, said
    project.forget()
    for command in commands:
        for shell in SHELLS:
            got = shell_args(shell, swapped(command, tmp_path), work)
            assert got[0] == f"./{name}/scripts", (command, got)


# The address of a store read with sqlite3 ----------------------------------------------------

def make_store(path: Path, runs: int) -> None:
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table runs(start_time)")
    con.execute("create table assessments(x)")
    con.executemany("insert into runs values(?)", [(1_700_000_000_000 + i,) for i in range(runs)])
    con.executemany("insert into assessments values(?)", [(i,) for i in range(runs)])
    con.commit()
    con.close()


@pytest.mark.parametrize("folder", ["%2e%2e", "a#b", "a?b=c", "x%23y", "%2e%2e/made-here#"])
def test_a_store_in_a_folder_with_odd_characters_is_the_one_read(tmp_path, folder):
    """The path is a path, not an address: `%2e%2e` is not `..`, `#` and `?` end nothing, and
    nothing is made outside the project."""
    from judgekeeper import find

    base = tmp_path / "base"
    proj = base / "proj"
    make_store(base / "outside" / "mlflow.db", runs=7)
    inside = proj / folder / "outside" / "mlflow.db"
    make_store(inside, runs=1)
    before = sorted(p.relative_to(base).as_posix() for p in base.rglob("*"))
    when, count = find.store_facts(inside)
    assert when is not None and count == 1  # the store in the project, not the one outside
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("*")) == before
    assert not (base / "outside" / "made-here#").exists()


def test_a_relative_store_path_is_read_too(tmp_path, monkeypatch):
    from judgekeeper import find

    make_store(tmp_path / "x" / "mlflow.db", runs=2)
    monkeypatch.chdir(tmp_path)
    assert find.store_facts(Path("x/mlflow.db"))[1] == 2


# The python3 looked up to name a command -----------------------------------------------------

def planted_python(folder: Path, marker: Path) -> Path:
    """A `python3` that records it was started."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "python3"
    script.write_text(f"#!/bin/sh\necho started > '{marker}'\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def reach(monkeypatch, path_value: str) -> None:
    monkeypatch.setenv("PATH", path_value)
    textio._imports.clear()


@pytest.mark.parametrize("entry", ["tools", "./tools", "", ".", "tools/", "../proj/tools"])
def test_a_python3_in_the_project_is_not_started_through_a_relative_path_entry(
        tmp_path, monkeypatch, entry):
    proj = tmp_path / "proj"
    marker = tmp_path / "STARTED"
    planted_python(proj / "tools", marker)
    if entry in ("", "."):
        planted_python(proj, marker)
    monkeypatch.chdir(proj)
    reach(monkeypatch, f"/nonexistent{os.pathsep}{entry}")
    assert textio.imports_judgekeeper("python3") is False
    assert not marker.exists()


@pytest.mark.parametrize("how", ["absolute", "link"])
def test_a_python3_anywhere_under_the_project_is_not_started(tmp_path, monkeypatch, how):
    proj = tmp_path / "proj"
    marker = tmp_path / "STARTED"
    other = planted_python(tmp_path / "elsewhere", marker)
    planted_python(proj / "node_modules" / ".bin", marker)
    if how == "link":
        (proj / "bin").mkdir()
        (proj / "bin" / "python3").symlink_to(other)
    (proj / "sub").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(proj / "sub")  # run from a folder inside the project
    monkeypatch.setattr(textio, "_work", [])
    textio.keep_programs_out_of(proj)  # as cli does, with the project folder
    folder = {"absolute": proj / "node_modules" / ".bin", "link": proj / "bin"}[how]
    reach(monkeypatch, str(folder))
    assert textio.imports_judgekeeper("python3") is False
    assert not marker.exists()


def test_a_python3_in_the_project_given_from_elsewhere_is_not_started(tmp_path, monkeypatch):
    """The project is the folder given, not the one run in (keep_programs_out_of)."""
    proj, here = tmp_path / "proj", tmp_path / "here"
    here.mkdir()
    marker = tmp_path / "STARTED"
    planted_python(proj / "tools", marker)
    monkeypatch.chdir(here)
    monkeypatch.setattr(textio, "_work", [])
    reach(monkeypatch, str(proj / "tools"))
    textio.keep_programs_out_of(proj)
    assert textio.imports_judgekeeper("python3") is False
    assert not marker.exists()


def test_a_python3_outside_the_project_is_still_asked(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    marker = tmp_path / "STARTED"
    planted_python(tmp_path / "bin", marker)
    monkeypatch.chdir(proj)
    monkeypatch.setattr(textio, "_work", [])
    reach(monkeypatch, str(tmp_path / "bin"))
    assert textio.imports_judgekeeper("python3") is False  # it printed nothing: another install
    assert marker.exists()


def test_naming_the_command_never_starts_a_planted_python3(tmp_path, monkeypatch):
    """How judgekeeper names its own command, with a relative PATH entry into the folder it
    reads."""
    work = project_with(tmp_path, "other.csv")
    marker = tmp_path / "STARTED"
    planted_python(work / "tools", marker)
    monkeypatch.chdir(work)
    reach(monkeypatch, f"/nonexistent{os.pathsep}tools")
    monkeypatch.setattr(textio, "_typed", None)
    assert textio.off_path(any_start=True) is not None
    assert not marker.exists()
