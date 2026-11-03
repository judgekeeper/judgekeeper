"""Once a Ctrl-C is noted, the run ends with "Stopped." and exit 130, even when a library
swallowed the KeyboardInterrupt (raised inside its import, Python prints "Exception ignored"
and goes on), and it exits at once: a thread a library left running never holds it open."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from judgekeeper import front, textio
from judgekeeper.readers import inspect_logs
from tests.test_hardening import flat, project, run  # noqa: F401 - project is a fixture

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _swallowed(handler) -> None:
    """A Ctrl-C that lands inside a library which swallows it."""
    try:
        handler(signal.SIGINT, None)
    except KeyboardInterrupt:
        pass


@pytest.mark.parametrize("reading", [False, True])
def test_a_ctrl_c_a_library_swallowed_still_stops_the_run(project, capsys, monkeypatch,  # noqa: F811
                                                          reading):
    """Swallowed where the run's own handler notes it, or while Inspect AI reads (its own)."""
    real = front.find_found

    def found(*args, **kwargs):
        if reading:
            with inspect_logs.quiet():
                _swallowed(signal.getsignal(signal.SIGINT))
        else:
            _swallowed(signal.getsignal(signal.SIGINT))
        return real(*args, **kwargs)

    monkeypatch.setattr(front, "find_found", found)
    code, text = run(capsys, "--no-browser")
    assert code == 130, text
    assert "Stopped." in text
    assert flat(text).endswith("Next: run `judgekeeper --no-browser` when you want to continue.")
    assert text.count("Next:") == 1
    assert "No eval results found" not in text  # stopped before its next line
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler  # put back
    assert not textio.ctrl_c and not inspect_logs._stopping


def test_the_next_run_in_the_same_process_is_not_stopped(project, capsys, monkeypatch):  # noqa: F811
    code, text = run(capsys, "--no-browser")
    assert code != 130 and "Stopped." not in text, text


def test_a_ctrl_c_noted_while_inspect_reads_is_cleared_when_the_read_ends(tmp_path):
    """inspect_ai turned the Ctrl-C into an error of its own: it ends the read as a Ctrl-C, and
    the note is cleared, so a later read is never taken for a stopped one."""
    with pytest.raises(KeyboardInterrupt), inspect_logs.quiet():
        _swallowed(inspect_logs._noted)
        raise RuntimeError("a task inspect_ai cancelled")
    assert not inspect_logs._stopping
    with inspect_logs.quiet():
        assert not isinstance(inspect_logs._unreadable(tmp_path / "qa.eval"), KeyboardInterrupt)
    with inspect_logs.quiet():  # swallowed: the read ends as it is, the run is told
        _swallowed(inspect_logs._noted)
    assert not inspect_logs._stopping and textio.ctrl_c


def test_samples_read_after_the_header_still_see_a_ctrl_c():
    """The samples are read by a generator after _load's quiet() ended: its own quiet() notes
    a Ctrl-C there, and inspect_ai's error for it is the Ctrl-C."""
    def samples():
        with inspect_logs.quiet():
            yield 1
            _swallowed(inspect_logs._noted)
            raise RuntimeError("a task inspect_ai cancelled")

    got = []
    with pytest.raises(KeyboardInterrupt):
        got.extend(samples())
    assert got == [1]
    assert not inspect_logs._stopping


@pytest.mark.skipif(os.name == "nt", reason="the same exit on Windows, not faked here")
def test_stopped_exits_at_once_with_a_thread_left_running(tmp_path):
    """A thread a library left running (blocked for good) would hold Python open after
    "Stopped.": the run exits with 130 at once."""
    script = textwrap.dedent("""
        import sys, threading
        import judgekeeper.__main__ as entry
        import judgekeeper.cli as cli

        threading.Thread(target=threading.Event().wait).start()  # never ends, not a daemon

        def stopped(argv=None, last=True):
            print("Stopped.")
            return 130

        cli.main = stopped
        sys.argv = ["judgekeeper"]
        sys.exit(entry.main())
    """)
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, check=False,
                       capture_output=True, text=True, timeout=20)
    assert p.returncode == 130, p.stdout + p.stderr
    assert p.stdout == "Stopped.\n"


@pytest.mark.parametrize("left", ["run", "reading"])
def test_a_handler_or_note_left_from_before_never_reaches_the_next_run(project, capsys,  # noqa: F811
                                                                         left):
    """A Ctrl-C handler of judgekeeper's own left in place (a samples generator closed late)
    and its notes: the run still notes a Ctrl-C a library swallows, and puts Python's own
    handler back, with no note left, whatever it found."""
    stale = textio.note_ctrl_c if left == "run" else inspect_logs._noted
    signal.signal(signal.SIGINT, stale)
    inspect_logs._stopping.append(True)
    textio.ctrl_c.append(True)
    try:
        code, text = run(capsys, "--no-browser")
        assert code != 130 and "Stopped." not in text, text  # no note from before
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        assert not textio.ctrl_c and not inspect_logs._stopping
    finally:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        inspect_logs._stopping.clear()


def test_samples_closed_after_the_run_put_back_no_old_handler():
    """The samples generator's quiet() ends when the generator is closed, maybe after the run
    put its handler back: it never puts back a handler from before."""
    def samples():
        with inspect_logs.quiet():
            yield 1
            yield 2

    signal.signal(signal.SIGINT, textio.note_ctrl_c)  # as cli.main has it while it runs
    try:
        reading = samples()
        assert next(reading) == 1
        assert signal.getsignal(signal.SIGINT) is inspect_logs._noted
        signal.signal(signal.SIGINT, signal.default_int_handler)  # the run ended
        reading.close()
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        assert not inspect_logs._stopping
    finally:
        signal.signal(signal.SIGINT, signal.default_int_handler)


def test_a_noted_ctrl_c_stops_before_any_line_and_any_long_read(monkeypatch):
    """Not only a Next: line: any line, and the next "Reading ..." check of a long read."""
    monkeypatch.setattr(textio, "next_said", False)  # a run under way (cli._main)
    textio.ctrl_c.append(True)
    with pytest.raises(KeyboardInterrupt):
        textio.said_next("Step 2 of 5: Mark")
    assert not textio.ctrl_c
    monkeypatch.setattr(textio, "_clock", lambda: 0.0)
    textio.ctrl_c.append(True)
    with pytest.raises(KeyboardInterrupt):
        textio.reading(500)
    assert not textio.ctrl_c


def test_a_ctrl_c_a_library_swallowed_prints_no_traceback(tmp_path):
    """Swallowed inside a weakref callback (as in Python's import machinery), Python would
    print "Exception ignored ... KeyboardInterrupt" with a traceback: not once it is noted."""
    script = textwrap.dedent("""
        import gc, signal, weakref
        from judgekeeper import textio

        class Held:
            pass

        held = Held()
        ref = weakref.ref(held, lambda _: textio.note_ctrl_c(signal.SIGINT, None))
        del held
        gc.collect()
        print("noted" if textio.ctrl_c else "not noted")
    """)
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, check=False,
                       capture_output=True, text=True, timeout=20)
    assert p.stdout == "noted\n", p.stdout + p.stderr
    assert p.stderr == "", p.stderr
