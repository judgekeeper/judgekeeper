"""`python -m judgekeeper`, and the `judgekeeper` command: the entry point.

For a machine where the install worked but the `judgekeeper` command is not on the PATH, too.
It loads the commands (cli.py) inside `main`, so a Ctrl-C while they load (the first quarter of
a second) says "Stopped." with its Next: line and exits 130, never with a Python traceback.
"""

import signal
import sys

EXIT_STOPPED = 130  # Ctrl-C, as shells report it (cli.EXIT_STOPPED)
_pressed = False  # Ctrl-C pressed while the commands loaded


def _record(signum, frame) -> None:
    """Only note the press: a KeyboardInterrupt raised inside Python's import machinery can be
    swallowed ("Exception ignored ... KeyboardInterrupt"), and the run would carry on."""
    global _pressed
    _pressed = True


def _hold():
    """Take Ctrl-C until the commands are loaded; the handler it replaced (None: not the main
    thread, where Python leaves it alone)."""
    global _pressed
    _pressed = False
    try:
        return signal.signal(signal.SIGINT, _record)
    except (ValueError, OSError):
        return None


def _release(held) -> None:
    if held is not None:
        signal.signal(signal.SIGINT, held)


def main(argv: list[str] | None = None) -> int:
    held = _hold()  # the first statement: a press while the imports run is only recorded
    try:
        try:
            from judgekeeper.cli import main as run
            _release(held)
            if _pressed:  # loaded: now it stops the usual way
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            _release(held)
            code = _stopped()
        else:
            code = run(argv)
    finally:
        _release(held)
    if code == EXIT_STOPPED:
        # A Ctrl-C raised inside code run from a string (namedtuple and dataclass build their
        # classes so while modules load) leaves Python's "end by the signal" flag set, even
        # caught, and `python -m` obeys it. Running a string again clears the flag.
        exec("")  # noqa: S102 - an empty string, only to clear the flag
        _end_now(code)
    return code


def _end_now(code: int) -> None:
    """After "Stopped.", end at once: a thread a library left running (a reader that a Ctrl-C
    stopped half way) would hold Python open while it waits for it. What judgekeeper tidies at
    exit (atexit) is done first. Only as the program itself, never inside another one."""
    import threading

    from judgekeeper import textio

    if not textio._started_as_judgekeeper() or not any(
            t.is_alive() and not t.daemon for t in threading.enumerate()
            if t is not threading.main_thread()):
        return
    import atexit
    import os

    atexit._run_exitfuncs()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


def _stopped() -> int:
    """Ctrl-C before the commands were loaded: said as cli.py says it, in its plainest form
    (the command as run would need them loaded)."""
    print("\nStopped.")
    print("Next: run `judgekeeper` to carry on.")
    return EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main())
