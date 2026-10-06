"""Rough edges found before publication: files that are not UTF-8, unwritable output, a judge
that fails on every item, `--version`, Windows terminals and shells, and rare wordings.

Windows itself is not run here. What depends on it is reached by setting `sys.platform`.
"""

from __future__ import annotations

import errno
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import __version__, check_table, textio
from judgekeeper.anchors import freeze
from judgekeeper.cli import main
from judgekeeper.custom import exec_judge
from judgekeeper.label import LabelError, LabelSession
from judgekeeper.normalise import NormaliseError, unmapped_error
from judgekeeper.report import label_quality
from judgekeeper.table import TableError, read_table
from tests.conftest import FIXTURES

CHECK_CSV = FIXTURES / "check" / "results.csv"
MIG = FIXTURES / "migrate"
EXEC = FIXTURES / "exec"
TABLE = "id,input,output,verdict,label\na,caf\u00e9,o,pass,pass\nb,q,o,fail,fail\n"
SHEET = "id,input,output,human_label,notes\na,caf\u00e9,o,pass,\nb,q,o,fail,\n"
ENCODINGS = ("cp1252", "utf-16")
RECORDS = ["import", "records", str(FIXTURES / "records" / "export.csv"), "--map",
           ("target_id=trace_id,name=metric,label=value,explanation=comment,"
            "annotator_kind=source,input=question,output=answer,evaluator.model=judge_model")]


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture(autouse=True)
def label_server_gives_up_at_once(monkeypatch):
    """`label` is run here only to see it refuse; if it ever starts, it must not wait."""
    from judgekeeper import label

    monkeypatch.setattr(label, "IDLE_TIMEOUT", 0.2)


def _label(sheet, out) -> list[str]:
    return ["label", str(sheet), "--out", str(out), "--no-browser", "--port", "0"]


def _write(path, text: str, encoding: str = "utf-8"):
    path.write_bytes(text.encode(encoding))
    return path


def _anchors(tmp_path, n: int = 10):
    path = tmp_path / "anchors.jsonl"
    items = [{"id": f"s{i}", "input": f"q{i}", "output": ("good " if i % 2 == 0 else "bad ")
              + str(i), "human_label": "pass" if i % 2 == 0 else "fail"} for i in range(n)]
    path.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    freeze(path)
    return path


def _plain_error(capsys, *needles: str) -> str:
    """The one error line on stderr: no exception name, no traceback, no --debug pointer."""
    err = capsys.readouterr().err
    lines = [x for x in err.splitlines() if x.strip()]
    assert len(lines) == 1 and lines[0].startswith("error: "), err
    for bad in ("Traceback", "Error:", "Errno", "--debug", "codec"):
        assert bad not in err, err
    for needle in needles:
        assert needle in err, err
    return lines[0]


# 1. A file that is not UTF-8 -----------------------------------------------------------------

@pytest.mark.parametrize("encoding", ENCODINGS)
def test_check_says_a_spreadsheet_file_is_not_utf8_and_how_to_fix_it(tmp_path, capsys,
                                                                    encoding):
    path = _write(tmp_path / "results.csv", TABLE, encoding)
    assert main(["check", str(path), "--out", str(tmp_path / "o")]) == 2
    _plain_error(capsys, str(path), "not saved as UTF-8",
                 'In Excel, save it again as "CSV UTF-8 (Comma delimited)"',
                 "in Google Sheets")
    with pytest.raises(TableError, match="UTF-8"):
        check_table(path, out=tmp_path / "o2")


def test_utf16_without_a_byte_order_mark_is_not_read_as_text(tmp_path):
    path = _write(tmp_path / "results.csv", TABLE, "utf-16-le")
    with pytest.raises(TableError, match="UTF-8"):
        read_table(path)


def test_a_utf8_file_with_a_byte_order_mark_still_reads(tmp_path):
    for name in ("t.csv", "t.jsonl"):
        text = TABLE if name.endswith(".csv") else '{"id": "a", "input": "caf\u00e9"}\n'
        rows = read_table(_write(tmp_path / name, text, "utf-8-sig"))
        assert rows[0]["id"] == "a" and rows[0]["input"] == "caf\u00e9"


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("command", ["label", "template", "import-labels", "import --labels"])
def test_every_reader_of_a_table_says_it_is_not_utf8(tmp_path, capsys, command, encoding):
    sheet = _write(tmp_path / "sheet.csv", SHEET, encoding)
    argv = {
        "label": _label(sheet, tmp_path / "l.csv"),
        "template": ["template", str(sheet), "-o", str(tmp_path / "t.csv")],
        "import-labels": ["import-labels", str(sheet), "-o", str(tmp_path / "a.jsonl")],
        "import --labels": [*RECORDS, "--labels", str(sheet), "--out", str(tmp_path / "o")],
    }[command]
    assert main(argv) == 2
    _plain_error(capsys, str(sheet), "UTF-8", "CSV UTF-8 (Comma delimited)")


def test_the_label_session_raises_its_own_error_for_a_file_that_is_not_utf8(tmp_path):
    with pytest.raises(LabelError, match="UTF-8"):
        LabelSession(_write(tmp_path / "items.csv", SHEET, "cp1252"), tmp_path / "l.csv")


@pytest.mark.parametrize("tool,name", [("promptfoo", "results.json"),
                                       ("deepeval", "test_run_1.json"),
                                       ("inspect", "log.json"), ("records", "records.jsonl")])
def test_the_framework_readers_say_a_file_is_not_utf8(tmp_path, capsys, monkeypatch, tool,
                                                      name):
    monkeypatch.setitem(sys.modules, "inspect_ai", None)  # the plain JSON reader
    path = _write(tmp_path / name, '{"note": "caf\u00e9"}\n', "cp1252")
    assert main(["import", tool, str(path), "--out", str(tmp_path / "o")]) == 2
    line = _plain_error(capsys, str(path), "not saved as UTF-8")
    assert "Excel" not in line  # the spreadsheet advice is for spreadsheet files


def test_anchors_runs_prompt_report_and_config_say_they_are_not_utf8(tmp_path, capsys,
                                                                    pairwise_dir):
    anchors, runs = pairwise_dir / "anchors.jsonl", pairwise_dir / "runs"
    report = tmp_path / "rep"
    assert main(["validate", str(anchors), str(runs), "--out", str(report)]) == 0
    capsys.readouterr()
    bad = '{"caf\u00e9": 1}\n'.encode("cp1252")

    config = tmp_path / "judgekeeper.toml"
    config.write_bytes('# caf\u00e9\n[gate]\n'.encode("cp1252"))
    assert main(["gate", str(report / "report.json"), "--config", str(config)]) == 2
    _plain_error(capsys, str(config), "UTF-8")

    prompt = tmp_path / "prompt.md"
    prompt.write_bytes("---\nrubric_version: v1\n---\ncaf\u00e9 {{input}}\n".encode("cp1252"))
    for source in (["--callable", "tests.judges_for_tests:pick_good"],
                   ["--runner", "anthropic", "--model", "m"]):
        assert main(["judge", str(anchors), *source, "--prompt", str(prompt),
                     "--out", str(tmp_path / "r")]) == 2
        _plain_error(capsys, str(prompt), "UTF-8")

    (report / "report.json").write_bytes(bad)
    assert main(["gate", str(report / "report.json")]) == 2
    _plain_error(capsys, "report.json", "UTF-8")

    run = runs / "run-01.jsonl"
    run.write_bytes(bad)
    assert main(["validate", str(anchors), str(runs), "--out", str(tmp_path / "r2")]) == 2
    _plain_error(capsys, str(run), "UTF-8")
    assert main(["judge", str(anchors), "--runner", "replay", "--fixture", str(run),
                 "--out", str(tmp_path / "r3")]) == 2
    _plain_error(capsys, str(run), "UTF-8")

    anchors.write_bytes(bad)
    assert main(["freeze", str(anchors)]) == 2
    _plain_error(capsys, str(anchors), "UTF-8")


# 2 and 3. --version, and --debug with no command ---------------------------------------------

def test_version_flag_prints_the_version(capsys):
    assert main(["--version"]) == 0
    out, err = capsys.readouterr()
    assert out == f"judgekeeper {__version__}\n" and err == ""


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(monkeypatch):
    out = io.StringIO()  # what an embedding program may put in place of stdout
    monkeypatch.setattr(sys, "stdout", out)
    assert main(["--version"]) == 0
    assert out.getvalue() == f"judgekeeper {__version__}\n"


def test_the_help_lists_the_version_flag(capsys):
    assert main(["--help"]) == 0
    assert "  --version " in capsys.readouterr().out


def test_debug_with_no_command_prints_the_help(capsys):
    assert main([]) == 0
    usual = capsys.readouterr().out
    assert main(["--debug"]) == 0
    out, err = capsys.readouterr()
    assert out == usual and err == ""


# 4. A judge that fails ------------------------------------------------------------------------

def _judge(anchors, out, *source, runs: int = 1) -> int:
    return main(["judge", str(anchors), *source, "--runs", str(runs), "--out", str(out)])


def test_a_mistyped_judge_program_is_a_failure_not_a_success(tmp_path, capsys):
    anchors, runs = _anchors(tmp_path), tmp_path / "runs"
    assert _judge(anchors, runs, "--exec", "nonexistent-prog-for-judgekeeper-tests") == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "--debug" not in err
    last = err.splitlines()[-1]
    assert last.startswith("error: the judge failed on every item (10 of 10 judgments were "
                           "errors)")
    assert "First error: cannot run 'nonexistent-prog-for-judgekeeper-tests'" in last


def test_a_judge_function_that_always_raises_is_a_failure(tmp_path, capsys):
    anchors = _anchors(tmp_path)
    assert _judge(anchors, tmp_path / "runs", "--callable",
                  "tests.judges_for_tests:always_raises", runs=3) == 1
    last = capsys.readouterr().err.splitlines()[-1]
    assert "the judge failed on every item (30 of 30 judgments were errors)" in last
    # One line, even when the judge's own message has several.
    assert last.endswith("First error: RuntimeError: the judge service is down (try again "
                         "later)")


def test_the_first_error_of_a_failed_judge_is_scrubbed(tmp_path, capsys):
    assert _judge(_anchors(tmp_path), tmp_path / "runs", "--callable",
                  "tests.judges_for_tests:raises_with_a_key") == 1
    err = capsys.readouterr().err
    assert "sk-ant-api03" not in err and "[REDACTED]" in err


def test_some_errors_are_counted_and_the_run_still_succeeds(tmp_path, capsys):
    anchors = _anchors(tmp_path, n=12)
    command = f'"{sys.executable}" "{EXEC / "fails_some.py"}"'
    assert _judge(anchors, tmp_path / "runs", "--exec", command, runs=2) == 0
    lines = capsys.readouterr().err.splitlines()
    assert lines[-1].startswith("warning: 4 of 24 judgments were errors")
    assert "First error: exit 3: judge crashed" in lines[-1]


def test_a_judge_run_with_no_errors_prints_what_it_always_did(tmp_path, capsys):
    anchors, runs = _anchors(tmp_path), tmp_path / "runs"
    assert _judge(anchors, runs, "--callable", "tests.judges_for_tests:keyword_judge",
                  runs=3) == 0
    assert capsys.readouterr().err.splitlines() == [
        "30 judge calls (10 items x 3 runs)",
        *(f"wrote {runs / f'run-{n:02d}.jsonl'} (10 judgments)" for n in (1, 2, 3)),
    ]


def test_replaying_a_run_of_errors_is_a_failure_too(tmp_path, capsys):
    anchors, runs = _anchors(tmp_path), tmp_path / "runs"
    assert _judge(anchors, runs, "--callable", "tests.judges_for_tests:always_raises") == 1
    capsys.readouterr()
    assert main(["judge", str(anchors), "--runner", "replay", "--fixture",
                 str(runs / "run-01.jsonl"), "--out", str(tmp_path / "again")]) == 1
    assert "the judge failed on every item" in capsys.readouterr().err


# 5. An output location that cannot be written -------------------------------------------------

def _report(tmp_path) -> str:
    out = tmp_path / "made"
    assert main(["check", str(CHECK_CSV), "--out", str(out)]) == 0
    return str(out / "report.json")


def _output_commands(tmp_path, pairwise_dir, target: str) -> dict[str, list[str]]:
    """Every command that writes, with its output at `target`."""
    anchors, runs = str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs")
    sheet = str(_write(tmp_path / "sheet.csv", SHEET))
    report = _report(tmp_path)
    return {
        "check": ["check", str(CHECK_CSV), "--out", target],
        "validate": ["validate", anchors, runs, "--out", target],
        "judge": ["judge", anchors, "--runner", "replay", "--fixture",
                  str(pairwise_dir / "runs" / "run-01.jsonl"), "--out", target],
        "gate": ["gate", report, "--out", target],
        "attribute": ["attribute", report, "--baseline", report, "--out", target],
        "migrate": ["migrate", str(MIG / "anchors.jsonl"), str(MIG / "old"),
                    str(MIG / "new-better"), "--out", target],
        "import": [*RECORDS, "--out", target],
        "init": ["init", "--out", f"{target}/judge.md"],
        "template": ["template", sheet, "-o", f"{target}/labels.csv"],
        "import-labels": ["import-labels", sheet, "-o", f"{target}/anchors.jsonl"],
        "label": _label(sheet, f"{target}/labels.csv"),
        "export": ["export", "records", str(tmp_path / "made"), "-o", f"{target}/r.jsonl"],
        "baseline": ["baseline", "set", report, "--path", f"{target}/baseline.json"],
    }


COMMANDS_THAT_WRITE = ("check", "validate", "judge", "gate", "attribute", "migrate",
                       "import", "init", "template", "import-labels", "label", "export",
                       "baseline")


@pytest.mark.parametrize("command", COMMANDS_THAT_WRITE)
def test_a_file_where_the_output_folder_should_be_is_said_plainly(tmp_path, capsys,
                                                                 pairwise_dir, command):
    blocker = _write(tmp_path / "in-the-way", "a file\n")
    argv = _output_commands(tmp_path, pairwise_dir, str(blocker))[command]
    capsys.readouterr()
    assert main(argv) == 2
    _plain_error(capsys, str(blocker), "is a file, but a folder is needed there")
    assert blocker.read_text(encoding="utf-8") == "a file\n"


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs a folder this user cannot write to")
@pytest.mark.parametrize("command", COMMANDS_THAT_WRITE)
def test_a_folder_without_write_permission_is_said_plainly(tmp_path, capsys, pairwise_dir,
                                                           command):
    locked = tmp_path / "locked"
    locked.mkdir()
    argv = _output_commands(tmp_path, pairwise_dir, str(locked / "out"))[command]
    capsys.readouterr()
    locked.chmod(0o555)
    try:
        assert main(argv) == 2
    finally:
        locked.chmod(0o755)
    _plain_error(capsys, str(locked), "cannot write", "permission denied",
                 "Choose a location you can write to")


def test_a_folder_where_a_file_should_be_is_said_plainly(tmp_path, capsys):
    sheet = _write(tmp_path / "sheet.csv", SHEET)
    folder = tmp_path / "a-folder"
    folder.mkdir()
    for argv in (["template", str(sheet), "-o", str(folder)],
                 _label(sheet, folder),
                 ["init", "--out", str(folder), "--force"]):
        assert main(argv) == 2, argv
        _plain_error(capsys, str(folder), "is a folder, but a file is needed there")


def test_debug_adds_the_traceback_to_the_plain_line(tmp_path, capsys):
    blocker = _write(tmp_path / "in-the-way", "a file\n")
    assert main(["--debug", "check", str(CHECK_CSV), "--out", str(blocker)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" in err
    assert err.splitlines()[-1].startswith(f"error: {blocker} is a file, but a folder")


def test_file_errors_in_plain_words(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")  # each system's wording, on every system

    def message(cls, code, path="out/x"):
        return textio.describe_os_error(cls(code, os.strerror(code), path))

    denied = ("cannot write out/x: permission denied. Choose a location you can write to, or "
              "change the folder's permissions.")
    assert message(PermissionError, errno.EACCES) == denied
    assert message(OSError, errno.ENOSPC) == (
        f"cannot use out/x: {os.strerror(errno.ENOSPC)}. Check the path, or choose another "
        "location.")
    assert message(FileNotFoundError, errno.ENOENT) == "file or folder not found: out/x"
    # An error that names no path (a network error, say) is not a file problem.
    assert textio.describe_os_error(OSError("connection reset")) is None
    assert textio.describe_os_error(ConnectionRefusedError(errno.ECONNREFUSED, "refused")) is None
    monkeypatch.setattr(sys, "platform", "win32")
    assert message(PermissionError, errno.EACCES) == (
        f"{denied} If the file is open in Excel or another program, close it first.")


def test_on_windows_opening_a_folder_as_a_file_is_not_called_a_permission_problem(tmp_path,
                                                                                 windows):
    # Windows answers "permission denied" where other systems say "is a directory".
    e = PermissionError(errno.EACCES, "Permission denied", str(tmp_path))
    assert "is a folder, but a file is needed there" in textio.describe_os_error(e)


# 6. Windows -----------------------------------------------------------------------------------

def _terminal(encoding: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding)


def test_a_terminal_that_cannot_show_a_character_gets_a_question_mark(tmp_path, monkeypatch):
    out, err = _terminal("cp1252"), _terminal("cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    rule = tmp_path / "rule \u2192.md"
    assert main(["init", "--out", str(rule)]) == 0
    assert main(["check", str(tmp_path / "missing \u2192.csv")]) == 2
    out.flush()
    err.flush()
    assert b"rule ?.md" in out.buffer.getvalue()
    assert b"missing ?.csv" in err.buffer.getvalue()


def test_a_utf8_terminal_gets_the_characters_unchanged(tmp_path, monkeypatch):
    out = _terminal("utf-8")
    monkeypatch.setattr(sys, "stdout", out)
    assert main(["init", "--out", str(tmp_path / "rule \u2192.md")]) == 0
    out.flush()
    assert "rule \u2192.md".encode() in out.buffer.getvalue()


def test_migrate_prints_on_a_cp1252_terminal(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run(
        [sys.executable, "-m", "judgekeeper", "migrate", str(MIG / "anchors.jsonl"),
         str(MIG / "old"), str(MIG / "new-better"), "--out", str(tmp_path / "m")],
        capture_output=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(b"BETTER: ") and b"kappa 0.60 ? 1.00" in proc.stdout
    assert "\u00b1".encode("cp1252") in proc.stdout  # cp1252 has this one


def test_printed_commands_quote_paths_for_the_shell_in_use(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")  # both shells' quoting, on every system
    assert textio.quote_arg("labels.csv") == "labels.csv"
    assert textio.quote_arg("my folder/labels.csv") == "'my folder/labels.csv'"
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.quote_arg("labels.csv") == "labels.csv"
    assert textio.quote_arg(r"C:\data\labels.csv") == r"C:\data\labels.csv"
    assert textio.quote_arg(r"C:\my data\labels.csv") == r'"C:\my data\labels.csv"'


def test_the_label_next_command_uses_double_quotes_on_windows(tmp_path, monkeypatch):
    out = tmp_path / "my labels.csv"
    session = LabelSession(_write(tmp_path / "items.csv", SHEET), out)
    command = session.summary()["next_command"]
    assert shlex.split(command) == ["judgekeeper", "import-labels", str(out), "-o",
                                    "anchors.jsonl"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert session.summary()["next_command"] == (f'judgekeeper import-labels "{out}" '
                                                 "-o anchors.jsonl")


def test_init_quotes_a_rule_path_that_needs_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")  # both shells' quoting, on every system
    rule = str(Path("my folder/judge.md"))  # printed with \ on Windows
    assert main(["init", "--out", "my folder/judge.md"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(f"wrote {rule}: fill in every")
    assert f" --prompt {shlex.quote(rule)} --runs 3 " in printed
    monkeypatch.setattr(sys, "platform", "win32")
    assert main(["init", "--out", "my folder/judge.md", "--force"]) == 0
    assert f' --prompt "{rule}" --runs 3 ' in capsys.readouterr().out
    assert main(["init"]) == 0
    assert f" --prompt {Path('prompts/judge.md')} --runs 3 " in capsys.readouterr().out


def test_other_printed_commands_quote_their_paths_too(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")  # both shells' quoting, on every system
    sheet = _write(tmp_path / "sheet.csv", SHEET)
    assert main(["template", str(sheet), "-o", "my labels.csv"]) == 0
    assert "`judgekeeper import-labels 'my labels.csv' -o anchors.jsonl`" in \
        capsys.readouterr().out
    monkeypatch.setattr(sys, "platform", "win32")
    assert main(["template", str(sheet), "-o", "my labels.csv"]) == 0
    assert '`judgekeeper import-labels "my labels.csv" -o anchors.jsonl`' in \
        capsys.readouterr().out
    monkeypatch.setattr(sys, "platform", "linux")
    assert main(["template", str(sheet), "-o", "labels.csv"]) == 0
    assert capsys.readouterr().out == (
        "wrote labels.csv (2 rows): fill in human_label (pass or fail), then run `judgekeeper "
        "import-labels labels.csv -o anchors.jsonl`\n")


def test_exec_command_keeps_backslashes_on_windows(monkeypatch):
    assert textio.split_command('python "my judge.py" --fast') == ["python", "my judge.py",
                                                                    "--fast"]
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.split_command(r"python C:\x\judge.py") == ["python", r"C:\x\judge.py"]
    assert textio.split_command(r'"C:\Program Files\py\python.exe" "C:\my judges\judge.py" -v') \
        == [r"C:\Program Files\py\python.exe", r"C:\my judges\judge.py", "-v"]
    assert textio.split_command("node 'judge one.js'") == ["node", "judge one.js"]


def test_exec_judge_sends_and_reads_utf8_whatever_the_locale(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 0, stdout="pass", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert exec_judge("judge-prog --flag")({"id": "a", "input": "caf\u00e9"}) == "pass"
    assert seen["argv"] == ["judge-prog", "--flag"]
    assert seen["encoding"] == "utf-8"
    assert "caf\u00e9" in seen["input"]
    # A Python judge would read stdin in the locale's encoding: it is told to use UTF-8 too,
    # unless the user chose an encoding.
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"
    assert seen["env"]["PATH"] == os.environ["PATH"]
    monkeypatch.setenv("PYTHONIOENCODING", "latin-1")
    exec_judge("judge-prog")({"id": "a"})
    assert seen["env"]["PYTHONIOENCODING"] == "latin-1"


def test_exec_judge_passes_non_ascii_text_both_ways(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text(
        "import json, sys\n"
        "item = json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
        "sys.stdout.buffer.write(json.dumps({'verdict': 'pass', 'reason': item['input']},"
        " ensure_ascii=False).encode('utf-8'))\n", encoding="utf-8")
    judge = exec_judge(f'"{sys.executable}" "{script}"')
    assert judge({"id": "a", "input": "caf\u00e9 \u2192"}) == {"verdict": "pass",
                                                               "reason": "caf\u00e9 \u2192"}
    # The ordinary way to write a Python judge: text streams, no encoding named.
    script.write_text("import json, sys\nprint('pass: ' + json.load(sys.stdin)['input'])\n",
                      encoding="utf-8")
    assert judge({"id": "a", "input": "caf\u00e9 \u2192"}) == "pass: caf\u00e9 \u2192"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_install_hints_use_quotes_that_work_in_every_shell(tmp_path, monkeypatch, provider):
    from judgekeeper.runners import AnthropicRunner, OpenAIRunner

    prompt = _write(tmp_path / "p.md", "---\nrubric_version: v1\n---\n{{input}} {{output}}\n")
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "test-key-not-real")
    monkeypatch.setitem(sys.modules, provider, None)  # the import fails
    cls = AnthropicRunner if provider == "anthropic" else OpenAIRunner
    with pytest.raises(RuntimeError) as e:
        cls(model="m", prompt_path=prompt)
    assert f'pip install "judgekeeper[{provider}]"' in str(e.value)
    assert "'" not in str(e.value)


# 7. Wording of rare cases ---------------------------------------------------------------------

def test_one_labeled_item_is_singular():
    def message(n: int) -> str:
        return label_quality({"label_distribution": {"pass": n}})["flags"][0]["message"]

    assert message(1) == "Only 1 labeled item: error bars are wide; aim for about 100."
    assert message(10) == "Only 10 labeled items: error bars are wide; aim for about 100."


def test_one_item_and_one_run_are_singular(tmp_path, capsys):
    anchors = _anchors(tmp_path, n=1)
    assert _judge(anchors, tmp_path / "runs", "--callable",
                  "tests.judges_for_tests:keyword_judge") == 0
    assert capsys.readouterr().err.splitlines() == [
        "1 judge call (1 item x 1 run)",
        f"wrote {tmp_path / 'runs' / 'run-01.jsonl'} (1 judgment)",
    ]
    assert _judge(_anchors(tmp_path), tmp_path / "runs", "--callable",
                  "tests.judges_for_tests:keyword_judge") == 0
    assert capsys.readouterr().err.splitlines()[0] == "10 judge calls (10 items x 1 run)"


def test_import_labels_and_template_count_one_in_the_singular(tmp_path, capsys):
    sheet = _write(tmp_path / "sheet.csv", "id,input,output,human_label,notes\na,q,o,pass,\n"
                                           "b,q,o,,\n")
    assert main(["import-labels", str(sheet), "-o", str(tmp_path / "a.jsonl")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"wrote {tmp_path / 'a.jsonl'}: 1 labeled item (pass 1), frozen")
    assert out[1] == "  1 unlabeled row skipped: b"
    one = _write(tmp_path / "one.csv", "id,input,output\na,q,o\n")
    assert main(["template", str(one), "-o", str(tmp_path / "t.csv")]) == 0
    assert f"wrote {tmp_path / 't.csv'} (1 row): " in capsys.readouterr().out


def _kappa_flag(report: dict) -> dict:
    (flag,) = [f for f in report["verdict"]["flags"] if "appa" in f["message"]]
    return flag


def test_kappa_that_cannot_be_computed_is_not_compared_with_a_number(tmp_path):
    same = [{"id": f"i{n}", "verdict": "pass", "label": "pass"} for n in range(6)]
    flag = _kappa_flag(check_table(same, out=tmp_path / "same"))
    assert flag == {"code": "no_kappa", "message": (
        "Kappa vs human labels could not be computed: the human labels and the judge's "
        "verdicts are all the same single answer, so agreement cannot be told from chance. "
        "Not trustworthy as a gate.")}

    errors = [{"id": f"i{n}", "verdict": "", "label": "pass" if n % 2 else "fail"}
              for n in range(6)]
    report = check_table(errors, out=tmp_path / "errors")
    assert _kappa_flag(report)["message"] == (
        "Kappa vs human labels could not be computed: every judgment was a judge error, so "
        "nothing was scored. Not trustworthy as a gate.")
    assert "n/a (below" not in json.dumps(report)
    assert report["verdict"]["level"] == "not_trustworthy"


def test_a_low_kappa_keeps_its_wording(tmp_path):
    rows = [{"id": f"i{n}", "verdict": "pass", "label": "pass" if n % 2 else "fail"}
            for n in range(6)]
    assert _kappa_flag(check_table(rows, out=tmp_path)) == {
        "code": "low_kappa",
        "message": "Kappa vs human labels is 0.00 (below 0.6): not trustworthy as a gate."}


@pytest.mark.parametrize("separator", [";", "\t"])
def test_a_csv_with_another_separator_is_read(tmp_path, capsys, separator):
    """Excel in many European locales writes semicolons under the name CSV."""
    text = CHECK_CSV.read_text(encoding="utf-8")
    assert '"' not in text  # no quoted cells, so every comma in the fixture is a separator
    other = _write(tmp_path / "results.csv", text.replace(",", separator))
    assert read_table(other) == read_table(CHECK_CSV)
    printed = []
    for table in (other, CHECK_CSV):
        assert main(["check", str(table), "--out", str(tmp_path / "o")]) == 0
        printed.append(capsys.readouterr().out)
    assert printed[0] == printed[1] and "TPR 0.89" in printed[0]


def test_a_comma_csv_with_semicolons_in_its_text_is_still_a_comma_csv(tmp_path):
    path = _write(tmp_path / "t.csv", 'id,note; more,verdict,label\na,"x; y",pass,pass\n')
    assert read_table(path) == [{"id": "a", "note; more": "x; y", "verdict": "pass",
                                 "label": "pass"}]


def test_numbers_in_the_judge_column_point_at_pass_if(tmp_path, capsys):
    path = _write(tmp_path / "t.csv", "id,verdict,label\na,0.9,pass\nb,0.2,fail\n")
    assert main(["check", str(path), "--out", str(tmp_path / "o")]) == 2
    line = _plain_error(capsys, "'0.9'", "'0.2'", '--pass-if "score>=0.5"')
    assert "--label-map" not in line
    assert main(["check", str(path), "--pass-if", "score>=0.5", "--out",
                 str(tmp_path / "o")]) == 0


def test_numbers_and_words_get_both_hints_and_human_labels_only_the_map():
    mixed = str(unmapped_error(["0.9", "good", 0.2, "bad"], "judge verdict"))
    assert '--pass-if "score>=0.5"' in mixed and '--label-map "good=pass,bad=fail"' in mixed
    words = str(unmapped_error(["good", "bad"], "judge verdict"))
    assert "--pass-if" not in words and '--label-map "good=pass,bad=fail"' in words
    human = str(unmapped_error(["4", "2"], "human label", pass_if=False))
    assert "--pass-if" not in human and '--label-map "4=pass,2=fail"' in human
    assert isinstance(unmapped_error([0.5]), NormaliseError)
    assert "'" not in str(unmapped_error([0.5]))  # no single quotes: cmd.exe does not strip them


def test_init_gives_the_same_label_counts_as_the_website(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == ("  1. label real items (30 to 60 for a first look, about 100 for a "
                        "firmer result) and freeze the labels:")
    assert "50 to 100" not in "\n".join(lines)
