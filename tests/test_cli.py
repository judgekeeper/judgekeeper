"""The command line: exit codes, and no terminal escape sequences in anything it prints."""

import os
import subprocess
import sys

import pytest

from judgekeeper.cli import main

# --- terminal escape sequences from input files ---------------------------------------------------

ESCAPES = "\x1b]0;PWNED-TITLE\x07\x1b[2J\x1b[H cleared\r\x9b31m\x7f"
CONTROL = [chr(c) for c in (*range(0x09), *range(0x0b, 0x20), *range(0x7f, 0xa0))]


def _no_control(*texts):
    for text in texts:
        assert not [c for c in CONTROL if c in text], repr(text)


def test_printable_strips_control_characters_but_keeps_newline_and_tab():
    from judgekeeper.redact import printable

    assert printable("a\x1b[31mb\tc\nd\re\x7f\x9b\x00f é") == "a[31mb\tc\ndef é"
    assert printable(ESCAPES) == "]0;PWNED-TITLE[2J[H cleared31m"


def test_error_messages_print_no_escape_sequence(tmp_path, capsys):
    missing = tmp_path / f"results{ESCAPES}.csv"
    assert main([str(missing)]) == 2
    printed = capsys.readouterr()
    assert "PWNED-TITLE" in printed.err
    _no_control(printed.out, printed.err)


def test_ctrl_c_stops_with_one_line_and_no_traceback(monkeypatch, capsys):
    from judgekeeper import cli

    def stopped(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, None, stopped)
    assert main([]) == 130
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert out.out == "\nStopped.\nNext: run `judgekeeper` to carry on.\n"


@pytest.mark.parametrize("port", ["99999", "-1", "65536", "eighty"])
def test_a_port_out_of_range_is_a_usage_error_before_anything_is_written(tmp_path, capsys,
                                                                          port):
    assert main([str(tmp_path), "--port", port]) == 2
    assert "is not a port: give a number from 1 to 65535" in capsys.readouterr().err
    assert not (tmp_path / ".judgekeeper").exists()


# --- a closed output pipe ---------------------------------------------------------------------

def _closed_stdout(cwd, *args) -> subprocess.CompletedProcess:
    """judgekeeper with stdout a pipe whose reader already stopped (`| head` that is done)."""
    read, write = os.pipe()
    os.close(read)
    try:
        return subprocess.run([sys.executable, "-P", "-m", "judgekeeper", *args], cwd=cwd,
                              stdin=subprocess.DEVNULL, stdout=write, stderr=subprocess.PIPE,
                              text=True, timeout=60, check=False)
    finally:
        os.close(write)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows says a closed pipe another way")
@pytest.mark.parametrize("args, code", [(["--help"], 0), (["--version"], 0),
                                        (["mark", "--help"], 0), (["nosuchcmd"], 2)])
def test_a_closed_output_pipe_keeps_the_exit_code(tmp_path, args, code):
    done = _closed_stdout(tmp_path, *args)
    assert done.returncode == code, done.stderr
    assert "BrokenPipeError" not in done.stderr and "Exception ignored" not in done.stderr
    if code == 0:
        assert done.stderr == ""
