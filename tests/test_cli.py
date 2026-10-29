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

def _closed_stdout(cwd, *args, env=None) -> subprocess.CompletedProcess:
    """judgekeeper with stdout a pipe whose reader already stopped (`| head` that is done)."""
    read, write = os.pipe()
    os.close(read)
    try:
        return subprocess.run([sys.executable, "-P", "-m", "judgekeeper", *args], cwd=cwd,
                              stdin=subprocess.DEVNULL, stdout=write, stderr=subprocess.PIPE,
                              text=True, timeout=60, check=False, env=env)
    finally:
        os.close(write)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows says a closed pipe another way")
@pytest.mark.parametrize("args, code", [(["--help"], 0), (["--version"], 0),
                                        (["mark", "--help"], 0), (["nosuchcmd"], 2)])
@pytest.mark.parametrize("unbuffered", ["", "1"], ids=["buffered", "unbuffered"])
def test_a_closed_output_pipe_keeps_the_exit_code(tmp_path, args, code, unbuffered):
    """Unbuffered (PYTHONUNBUFFERED=1), the first line said already meets the closed pipe."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    done = _closed_stdout(tmp_path, *args, env={**env, "PYTHONUNBUFFERED": unbuffered}
                          if unbuffered else env)
    assert done.returncode == code, done.stderr
    assert "BrokenPipeError" not in done.stderr and "Exception ignored" not in done.stderr
    if code == 0:
        assert done.stderr == ""


# --- a closed or broken stdout or stderr ------------------------------------------------------

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="closes a file descriptor")


def _judgekeeper(cwd, *args, close=(), broken=(), script=None) -> subprocess.CompletedProcess:
    """judgekeeper with the streams in `close` closed and those in `broken` a pipe whose
    reader already stopped. `script` runs instead of `python -m judgekeeper`."""
    pipes = {}
    for fd in broken:
        read, write = os.pipe()
        os.close(read)
        pipes[fd] = write

    def child():
        for fd in close:
            os.close(fd)

    argv = [sys.executable, "-P", *(["-c", script] if script else ["-m", "judgekeeper"]), *args]
    try:
        return subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=pipes.get(1, subprocess.PIPE),
                              stderr=pipes.get(2, subprocess.PIPE), preexec_fn=child,
                              text=True, timeout=60, check=False)
    finally:
        for write in pipes.values():
            os.close(write)


@POSIX
def test_version_with_stdout_closed_exits_0(tmp_path):
    done = _judgekeeper(tmp_path, "--version", close=[1])
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr


@POSIX
@pytest.mark.parametrize("how", ["closed", "broken"])
def test_a_bad_port_with_stderr_gone_still_exits_2(tmp_path, how):
    stream = {"close": [2]} if how == "closed" else {"broken": [2]}
    done = _judgekeeper(tmp_path, "--port", "abc", **stream)
    assert done.returncode == 2


CTRL_C = """
import sys
from judgekeeper import __main__ as entry, cli

def stopped(argv):
    raise KeyboardInterrupt  # Ctrl-C while the flags are read

cli._main = stopped
sys.exit(entry.main(sys.argv[1:]))
"""


@POSIX
def test_ctrl_c_with_stdout_broken_still_exits_130(tmp_path):
    done = _judgekeeper(tmp_path, "--port", "1", broken=[1], script=CTRL_C)
    assert done.returncode == 130, done.stderr
    assert "Exception ignored" not in done.stderr and "Traceback" not in done.stderr


class _FullDisk:
    """A file on a full disk: every write fails with ENOSPC, until its descriptor is moved to
    the null device."""

    def __init__(self, path):
        import io

        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT)
        raw = type("Raw", (io.RawIOBase,), {
            "writable": lambda s: True, "fileno": lambda s: self.fd,
            "write": lambda s, b: self._write(b)})()
        self.stream = io.TextIOWrapper(io.BufferedWriter(raw), encoding="utf-8")

    def _write(self, data) -> int:
        null = os.stat(os.devnull)
        now = os.fstat(self.fd)
        if (now.st_dev, now.st_ino) != (null.st_dev, null.st_ino):
            import errno

            raise OSError(errno.ENOSPC, "No space left on device")
        return os.write(self.fd, bytes(data))


@pytest.mark.skipif(not hasattr(os, "dup2") or sys.platform == "win32",
                    reason="the null device is NUL on Windows")
@pytest.mark.parametrize("args, code", [(["--version"], 0), (["--port", "abc"], 2)])
def test_a_full_disk_on_stdout_gives_no_traceback(tmp_path, monkeypatch, args, code):
    full = _FullDisk(tmp_path / "out.txt")
    monkeypatch.setattr(sys, "stdout", full.stream)
    assert main(args) == code
    full.stream.flush()  # Python's own flush at exit: nothing left to fail


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="no /dev/full here")
def test_stdout_on_dev_full_exits_0_not_120(tmp_path):
    with open("/dev/full", "w", encoding="utf-8") as full:
        done = subprocess.run([sys.executable, "-P", "-m", "judgekeeper", "--version"],
                              cwd=tmp_path, stdout=full, stderr=subprocess.PIPE, text=True,
                              timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr


class _Refuses:
    """An unbuffered stream that refuses every write (`error`): each print meets it at once."""

    def __init__(self, error: OSError):
        self.error = error

    def write(self, text):
        raise self.error

    def flush(self):
        pass


def test_ctrl_c_in_a_command_with_stdout_broken_still_exits_130(monkeypatch):
    from judgekeeper import cli

    def stopped(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, None, stopped)
    monkeypatch.setattr(sys, "stdout", _Refuses(BrokenPipeError()))
    assert main([]) == 130


def test_an_error_with_stderr_broken_still_exits_2(monkeypatch):
    from judgekeeper import cli

    def failed(args):
        raise RuntimeError("went wrong")

    monkeypatch.setitem(cli.COMMANDS, None, failed)
    monkeypatch.setattr(sys, "stderr", _Refuses(BrokenPipeError()))
    assert main(["--debug"]) == 2


def test_version_on_a_full_unbuffered_stdout_gives_no_traceback(monkeypatch):
    import errno

    monkeypatch.setattr(sys, "stdout", _Refuses(OSError(errno.ENOSPC, "No space left")))
    assert main(["--version"]) == 0


# --- the help screens ----------------------------------------------------------------------

@pytest.mark.parametrize("columns", ["80", "60", "100"])
@pytest.mark.parametrize("command", [[], ["mark"]])  # the help screens that say it
def test_help_never_splits_llm_as_a_judge_across_lines(monkeypatch, capsys, command, columns):
    monkeypatch.setenv("COLUMNS", columns)
    assert main([*command, "--help"]) == 0
    out = capsys.readouterr().out
    assert "LLM-as-a-judge" in out
    words = out.split()
    assert not [w for w in words if w.startswith("LLM-") and "LLM-as-a-judge" not in w], out
