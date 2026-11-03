"""A Ctrl-C at the very end of a run, after the command is done: while the result is flushed,
and in the entry point's last lines. It is only noted: the result is printed whole, with no
traceback, and Python's own Ctrl-C handler is back afterwards."""
from __future__ import annotations

import os
import signal

import pytest

from judgekeeper import __main__ as entry
from judgekeeper import cli
from tests.start_projects import promptfoo_project, split

ARGV = ["--no-browser", "--port", "0"]


@pytest.fixture
def here(tmp_path, monkeypatch):
    promptfoo_project(tmp_path, split(25, 25))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _press() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def _ran(main, argv=ARGV) -> int:
    """main(argv), failing (never ending the test session) when a Ctrl-C gets out of it."""
    try:
        return main(argv)
    except KeyboardInterrupt:
        pytest.fail("the Ctrl-C got out of the run")


def _whole(out: str) -> None:
    assert "Traceback" not in out and "KeyboardInterrupt" not in out, out
    assert "Step 2 of 5: Mark" in out and out.rstrip().splitlines()[-1].startswith("then"), out


@pytest.mark.parametrize("main", [cli.main, entry.main], ids=["cli", "entry"])
def test_a_ctrl_c_while_the_result_is_flushed_is_only_noted(main, here, capsys, monkeypatch):
    real, pressed = cli.flush_stdout, []

    def flush(*args, **kwargs):
        if not pressed:
            pressed.append(True)
            _press()
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "flush_stdout", flush)
    assert _ran(main) == 0
    assert pressed
    out = capsys.readouterr()
    _whole(out.out + out.err)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_a_ctrl_c_after_the_commands_return_is_only_noted(here, capsys, monkeypatch):
    """In the entry point, after cli.main has returned (its last lines)."""
    real = cli.main

    def run(*args, **kwargs):
        code = real(*args, **kwargs)
        _press()
        return code

    monkeypatch.setattr(cli, "main", run)
    assert _ran(entry.main) == 0
    out = capsys.readouterr()
    _whole(out.out + out.err)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_a_second_ctrl_c_while_stopped_is_said_is_only_noted(here, capsys, monkeypatch):
    """A Ctrl-C noted during the run says "Stopped."; another while that is said is noted."""
    from judgekeeper import textio

    real, pressed = cli._say, []

    def say(*args, **kwargs):
        if args and args[0] == "Stopped." and not pressed:
            pressed.append(True)
            _press()
        return real(*args, **kwargs)

    def swallowed(*args, **kwargs):
        textio.next_said = False  # as _main starts
        textio.ctrl_c.append(True)  # as a library that swallowed the KeyboardInterrupt
        return 0

    monkeypatch.setattr(cli, "_say", say)
    monkeypatch.setattr(cli, "_main", swallowed)
    assert _ran(cli.main) == cli.EXIT_STOPPED
    out = capsys.readouterr()
    assert pressed and "Traceback" not in out.out + out.err
    assert out.out.splitlines()[-2:][0] == "Stopped.", out.out
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
