"""Rough edges: files that are not UTF-8, unwritable output, `--version`, Windows terminals
and shells, and rare wordings.

Windows itself is not run here. What depends on it is reached by setting `sys.platform`.
"""

from __future__ import annotations

import errno
import io
import os
import subprocess
import sys

import pytest

from judgekeeper import __version__, textio
from judgekeeper.anchors import AnchorError, load_anchors
from judgekeeper.cli import main
from judgekeeper.custom import exec_judge
from judgekeeper.judgments import JudgmentsError, read_run
from judgekeeper.label import LabelError, LabelSession, make_server
from judgekeeper.normalise import NormaliseError, unmapped_error
from judgekeeper.readers import read_deepeval, read_inspect, read_promptfoo, read_records
from judgekeeper.records import RecordsError
from judgekeeper.table import TableError, read_table
from tests.start_projects import promptfoo_project, split, table_project

TABLE = "id,input,output,verdict,label\na,caf\u00e9,o,pass,pass\nb,q,o,fail,fail\n"
SHEET = "id,input,output,human_label,notes\na,caf\u00e9,o,pass,\nb,q,o,fail,\n"
ENCODINGS = ("cp1252", "utf-16")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def _write(path, text: str, encoding: str = "utf-8"):
    path.write_bytes(text.encode(encoding))
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


# A file that is not UTF-8 --------------------------------------------------------------------

@pytest.mark.parametrize("encoding", ENCODINGS)
def test_start_says_a_spreadsheet_file_is_not_utf8_and_how_to_fix_it(tmp_path, capsys,
                                                                    monkeypatch, encoding):
    table_project(tmp_path, split(20, 20))
    path = tmp_path / "results.csv"
    _write(path, path.read_text(encoding="utf-8").replace("Answer", "Answ\u00e9r"), encoding)
    monkeypatch.chdir(tmp_path)
    assert main(["start", "results.csv", "--no-browser"]) == 2
    _plain_error(capsys, "results.csv", "not saved as UTF-8",
                 'In Excel, save it again as "CSV UTF-8 (Comma delimited)"',
                 "in Google Sheets")
    with pytest.raises(TableError, match="UTF-8"):
        read_table(path)


def test_utf16_without_a_byte_order_mark_is_not_read_as_text(tmp_path):
    path = _write(tmp_path / "results.csv", TABLE, "utf-16-le")
    with pytest.raises(TableError, match="UTF-8"):
        read_table(path)


def test_a_utf8_file_with_a_byte_order_mark_still_reads(tmp_path):
    for name in ("t.csv", "t.jsonl"):
        text = TABLE if name.endswith(".csv") else '{"id": "a", "input": "caf\u00e9"}\n'
        rows = read_table(_write(tmp_path / name, text, "utf-8-sig"))
        assert rows[0]["id"] == "a" and rows[0]["input"] == "caf\u00e9"


def test_the_label_session_raises_its_own_error_for_a_file_that_is_not_utf8(tmp_path):
    with pytest.raises(LabelError, match="UTF-8"):
        LabelSession(_write(tmp_path / "items.csv", SHEET, "cp1252"), tmp_path / "l.csv")


@pytest.mark.parametrize("reader,name", [(read_promptfoo, "results.json"),
                                         (read_deepeval, "test_run_1.json"),
                                         (read_inspect, "log.json"),
                                         (read_records, "records.jsonl")])
def test_the_framework_readers_say_a_file_is_not_utf8(tmp_path, monkeypatch, reader, name):
    monkeypatch.setitem(sys.modules, "inspect_ai", None)  # the plain JSON reader
    path = _write(tmp_path / name, '{"note": "caf\u00e9"}\n', "cp1252")
    with pytest.raises(RecordsError, match="not saved as UTF-8") as e:
        reader(path)
    assert str(path) in str(e.value)
    assert "Excel" not in str(e.value)  # the spreadsheet advice is for spreadsheet files


def test_anchors_and_runs_say_they_are_not_utf8(tmp_path):
    bad = _write(tmp_path / "anchors.jsonl", '{"caf\u00e9": 1}\n', "cp1252")
    with pytest.raises(AnchorError, match="UTF-8"):
        load_anchors(bad)
    with pytest.raises(JudgmentsError, match="UTF-8"):
        read_run(bad)


# --version, and --debug with no command ------------------------------------------------------

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


def test_debug_with_no_command_runs_judgekeeper_the_same(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main([]) == 3  # nothing found here: the Next: line says what to do
    usual = capsys.readouterr().out
    assert main(["--debug"]) == 3
    out, err = capsys.readouterr()
    assert out == usual and err == ""


# An output location that cannot be written ----------------------------------------------------

def test_a_file_where_the_workspace_folder_should_be_is_said_plainly(tmp_path, capsys,
                                                                    monkeypatch):
    promptfoo_project(tmp_path, split(20, 20))
    blocker = _write(tmp_path / ".judgekeeper", "a file\n")
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    assert main(["start", "--no-browser", "--yes"]) == 2
    _plain_error(capsys, str(blocker), "is a file, but a folder is needed there")
    assert blocker.read_text(encoding="utf-8") == "a file\n"


def test_a_folder_where_a_file_should_be_is_said_plainly(tmp_path, capsys):
    sheet = _write(tmp_path / "sheet.csv", SHEET)
    folder = tmp_path / "a-folder"
    folder.mkdir()
    with pytest.raises(LabelError, match="is a folder, but a file is needed there"):
        make_server(LabelSession(sheet, folder), 0, page="")  # start's labels.csv


def test_debug_adds_the_traceback_to_the_plain_line(tmp_path, capsys, monkeypatch):
    promptfoo_project(tmp_path, split(20, 20))
    blocker = _write(tmp_path / ".judgekeeper", "a file\n")
    monkeypatch.chdir(tmp_path)
    assert main(["--debug", "start", "--no-browser", "--yes"]) == 2
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


# Windows --------------------------------------------------------------------------------------

def _terminal(encoding: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding)


def test_a_terminal_that_cannot_show_a_character_gets_a_question_mark(tmp_path, monkeypatch):
    err = _terminal("cp1252")
    monkeypatch.setattr(sys, "stderr", err)
    assert main(["start", str(tmp_path / "missing \u2192.csv")]) == 2
    err.flush()
    assert b"missing ?.csv" in err.buffer.getvalue()


def test_a_utf8_terminal_gets_the_characters_unchanged(tmp_path, monkeypatch):
    err = _terminal("utf-8")
    monkeypatch.setattr(sys, "stderr", err)
    assert main(["start", str(tmp_path / "missing \u2192.csv")]) == 2
    err.flush()
    assert "missing \u2192.csv".encode() in err.buffer.getvalue()


def test_start_prints_on_a_cp1252_terminal(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run(
        [sys.executable, "-m", "judgekeeper", "start", str(tmp_path / "caf\u00e9 \u2192.csv")],
        capture_output=True, env=env, check=False)
    assert proc.returncode == 2, proc.stderr
    assert b"Traceback" not in proc.stderr
    assert "caf\u00e9 ?.csv".encode("cp1252") in proc.stderr  # cp1252 has the first one


def test_printed_commands_quote_paths_for_the_shell_in_use(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")  # both shells' quoting, on every system
    assert textio.quote_arg("labels.csv") == "labels.csv"
    assert textio.quote_arg("my folder/labels.csv") == "'my folder/labels.csv'"
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.quote_arg("labels.csv") == "labels.csv"
    assert textio.quote_arg(r"C:\data\labels.csv") == r"C:\data\labels.csv"
    assert textio.quote_arg(r"C:\my data\labels.csv") == r'"C:\my data\labels.csv"'


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


# Wording of rare cases ------------------------------------------------------------------------

@pytest.mark.parametrize("separator", [";", "\t"])
def test_a_csv_with_another_separator_is_read(tmp_path, separator):
    """Excel in many European locales writes semicolons under the name CSV."""
    comma = _write(tmp_path / "comma.csv", TABLE)
    other = _write(tmp_path / "results.csv", TABLE.replace(",", separator))
    assert read_table(other) == read_table(comma)
    assert read_table(other)[0]["input"] == "caf\u00e9"


def test_a_comma_csv_with_semicolons_in_its_text_is_still_a_comma_csv(tmp_path):
    path = _write(tmp_path / "t.csv", 'id,note; more,verdict,label\na,"x; y",pass,pass\n')
    assert read_table(path) == [{"id": "a", "note; more": "x; y", "verdict": "pass",
                                 "label": "pass"}]


def test_numbers_and_words_get_both_hints_and_human_labels_only_the_map():
    mixed = str(unmapped_error(["0.9", "good", 0.2, "bad"], "judge verdict"))
    hint = '--label-map "good=pass" or --label-map "good=fail", whichever it means'
    assert '--pass-if "score>=0.5"' in mixed and hint in mixed
    words = str(unmapped_error(["good", "bad"], "judge verdict"))
    assert "--pass-if" not in words and hint in words
    human = str(unmapped_error(["4", "2"], "human label", pass_if=False))
    assert "--pass-if" not in human and '--label-map "4=pass" or --label-map "4=fail"' in human
    assert isinstance(unmapped_error([0.5]), NormaliseError)
    assert "'" not in str(unmapped_error([0.5]))  # no single quotes: cmd.exe does not strip them
