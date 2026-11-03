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


def _put_back(held) -> None:
    """Python's Ctrl-C handler (`held`) back, once the run is done: the very last step. Only
    in place of a handler of judgekeeper's that only notes a press (_record, cli._late)."""
    cli = sys.modules.get("judgekeeper.cli")
    if held is not None and signal.getsignal(signal.SIGINT) in (_record,
                                                               getattr(cli, "_late", _record)):
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
            if held is not None:  # "Stopped." is said whole: a press now is only recorded
                signal.signal(signal.SIGINT, _record)
            code = _stopped(sys.argv[1:] if argv is None else argv)
        else:
            code = run(argv, last=False)  # done, with a handler that only notes a press
        if code == EXIT_STOPPED:
            # A Ctrl-C raised inside code run from a string (namedtuple and dataclass build
            # their classes so while modules load) leaves Python's "end by the signal" flag
            # set, even caught, and `python -m` obeys it. Running a string again clears it.
            exec("")  # noqa: S102 - an empty string, only to clear the flag
            _end_now(code)
        return code
    finally:
        _put_back(held)


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


def _stopped(argv: list[str]) -> int:
    """Ctrl-C while the commands loaded: said as cli.py says it, the program as typed and the
    flags given. When the commands could not be loaded, the plain name and the flags."""
    try:
        from judgekeeper import cli, textio

        stop, first = cli._stopped, cli.command_first
        textio.next_said = False  # this run has said nothing yet (as cli._main starts)
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - not loaded: said plainly below
        stop = None
    if stop is not None:
        try:
            return stop(first(list(argv)))
        except OSError:  # stdout can't take it: still stopped
            return EXIT_STOPPED
    import shlex

    command = " ".join(["judgekeeper", *(shlex.quote(a) for a in argv if a != "--debug")])
    print("\nStopped.")
    print(f"Next: run `{command}` to carry on.")
    return EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main())
