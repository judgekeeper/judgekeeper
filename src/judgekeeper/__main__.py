"""`python -m judgekeeper`, and the `judgekeeper` command: the entry point.

For a machine where the install worked but the `judgekeeper` command is not on the PATH, too.
It loads the commands (cli.py) inside `main`, so a Ctrl-C while they load (the first quarter of
a second) says "Stopped." with its Next: line and exits 130, never with a Python traceback.
"""

import sys

EXIT_STOPPED = 130  # Ctrl-C, as shells report it (cli.EXIT_STOPPED)


def main(argv: list[str] | None = None) -> int:
    try:
        from judgekeeper.cli import main as run
    except KeyboardInterrupt:
        code = _stopped()
    else:
        code = run(argv)
    if code == EXIT_STOPPED:
        # A Ctrl-C raised inside code run from a string (namedtuple and dataclass build their
        # classes so while modules load) leaves Python's "end by the signal" flag set, even
        # caught, and `python -m` obeys it. Running a string again clears the flag.
        exec("")  # noqa: S102 - an empty string, only to clear the flag
    return code


def _stopped() -> int:
    """Ctrl-C before the commands were loaded: said as cli.py says it, in its plainest form
    (the command as run would need them loaded)."""
    print("\nStopped.")
    print("Next: run `judgekeeper` to carry on.")
    return EXIT_STOPPED


if __name__ == "__main__":
    sys.exit(main())
