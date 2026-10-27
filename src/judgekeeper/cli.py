"""Command-line entry point.

`judgekeeper` with no command (front.py) does the next step: finds the LLM-as-a-judge, checks
it, opens the marking page, and prints the result once there are enough marks. `mark`
(mark.py) opens the page to mark more; `check` (check.py) re-tests a changed judge on the marks
from its new results (exit 1: it got worse); `fix` (fix.py) tests a new rule on marks it keeps
hidden, from the results of grading them again. judgekeeper only reads files: it never runs an
eval tool or calls an AI. Exit codes: 0 success, 2 usage error, 3 the person is needed (a link
where judgekeeper writes, too), 130 Ctrl-C.

Every error is scrubbed (redact.scrub) and ends with one `Next:` line, printed here. A failure
with no better message never prints its own text, which can hold an answer's text: one line
says where to report it, and --debug adds each frame's file, line and function, never the
error's text. Removed commands (`REMOVED`) print one line that says so and exit 2; they are
not in the help.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
import traceback
from pathlib import Path

from judgekeeper import __version__, textio
from judgekeeper.anchors import AnchorError
from judgekeeper.find import TOOLS
from judgekeeper.judgments import JudgmentsError
from judgekeeper.label import LabelError, PageBusy
from judgekeeper.mapper import MapError
from judgekeeper.marks import MarksError
from judgekeeper.normalise import NormaliseError
from judgekeeper.redact import one_line, printable, scrub
from judgekeeper.settings import SettingsError
from judgekeeper.start import StartError
from judgekeeper.table import TableError
from judgekeeper.textio import (
    describe_os_error,
    flush_stdout,
    held_lines,
    is_windows,
    lenient_streams,
    program,
    quote_arg,
    started_by_uvx,
    tick,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NEEDS_YOU = 3
EXIT_STOPPED = 130  # Ctrl-C, as shells report it
ISSUES = "https://github.com/judgekeeper/judgekeeper/issues"
UNEXPECTED = ("judgekeeper hit a problem it didn't expect reading {what}. Please report it: "
              f"{ISSUES} (remove any answer text first).")
# The Next: line of an error; {command} is the command as it was run
NEXT_FIX = "fix what the line above says, then run `{command}`."
NEXT_REPORT = f"report it at {ISSUES.removeprefix('https://')} with the lines above."
NEXT_UNEXPECTED = NEXT_REPORT + " `--debug` shows where it went wrong, without your answers."
NEXT_WRITE = ("make this folder writable (judgekeeper keeps its files in .judgekeeper/ here), "
              "then run `{command}`.")
NEXT_PATH = "check the path, then run `{command}`."
NEXT_LINK = "remove that link, then run `{command}`."
NEXT_HELP = "run `{command}` to see the options."
NEXT_REMOVED = "run `{command}` in your project."
NEXT_STOPPED = "run `{command}` to carry on."
NEXT_BUSY = "run `{command}` again."

MESSAGE = "Check your LLM-as-a-judge in 5 steps."
STEPS = """\
  1. Find      judgekeeper          finds your eval results and the
                                    LLM-as-a-judge that graded them
  2. Mark      in your browser      you mark answers Pass or Fail
  3. Measure   judgekeeper          shows how often your LLM-as-a-judge agrees
                                    with you, and where it goes wrong
  4. Fix       judgekeeper fix      if your LLM-as-a-judge needs work, change
                                    its rule, grade your marked answers again,
                                    and test the new rule on the half of your
                                    marks kept aside
  5. Re-check  judgekeeper check    after you change your LLM-as-a-judge and
                                    run your eval, see if it still agrees
                                    with you"""
READS = """\
judgekeeper can read results from promptfoo, DeepEval, Inspect AI,
MLflow, or a CSV or JSONL file with these columns:
  input, output, verdict"""
FIX_HELP = ("see where your LLM-as-a-judge goes wrong; with the results of grading your marked "
            "answers again, test a better rule on the marks kept aside")
COMMANDS_HELP = (
    ("mark", "mark more answers"),
    ("fix", FIX_HELP),
    ("check", "re-check your LLM-as-a-judge on your marks after a change"),
)
HELP_WIDTH = 80
# Removed commands: the 0.1 CI gate, setup (part of judgekeeper now) and start (its steps are
# judgekeeper, mark, fix and check now). Each prints one line and exits 2.
REMOVED = ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "setup",
           "start")


class _Parser(argparse.ArgumentParser):
    """argparse echoes bad argument values in its errors; scrub them too. The Next: line that
    follows is said by `_main`."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {printable(scrub(message))}\n")


class _TopParser(_Parser):
    """The top-level help: the 5 steps, what judgekeeper reads, the usage, the commands, then
    the options of `judgekeeper` itself."""

    def format_help(self) -> str:
        width = max(len(name) for name, _ in COMMANDS_HELP) + 3
        commands = [line for name, text in COMMANDS_HELP for line in textwrap.wrap(
            text, HELP_WIDTH, initial_indent=f"  {name:<{width}}",
            subsequent_indent=" " * (2 + width))]
        usage, _, options = super().format_help().partition("\n\n")
        lines = [MESSAGE, "", STEPS, "", READS, "", usage.strip(), "", "Commands:", *commands,
                 "", options.rstrip()]
        return "\n".join(lines) + "\n"


def version_lines(stream=None) -> list[str]:
    """What `--version` prints. In a terminal it is the install check: the install is ready,
    and what to run next. Piped (a script, CI), exactly `judgekeeper <version>`.

    When the `judgekeeper` command is not on the PATH, the next step names the form that works,
    with -P so Python keeps this folder off the import path (a project's re.py never runs).
    """
    stream = sys.stdout if stream is None else stream
    try:
        terminal = stream.isatty()
    except (AttributeError, ValueError):  # no isatty, or a closed stream
        terminal = False
    if not terminal:
        return [f"judgekeeper {__version__}"]
    if started_by_uvx() or shutil.which("judgekeeper"):
        command = program()
    else:
        command = f"{'py' if is_windows() else 'python3'} -P -m judgekeeper"
    return [f"{tick(stream)} judgekeeper {__version__} is ready", f"Next: run {command}"]


class _Version(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print("\n".join(version_lines()))
        parser.exit()


def _say(text: str, file=None, end: str = "\n") -> None:
    """Print text that may quote an input file as one line: control characters are dropped,
    line breaks become spaces. A stream that can't take it (stderr closed by the program
    reading it) goes to the null device: the exit code stays the command's."""
    try:
        print(one_line(text), file=file, end=end)
        for line in held_lines(text):  # a name left out of the command above, as data
            print(one_line(line), file=file)
    except OSError:
        flush_stdout(err=file is sys.stderr)


def _error(message: str) -> None:
    _say(f"error: {one_line(scrub(message))}", file=sys.stderr)


def _next(step: str, file=None) -> None:
    """The one Next: line an error ends with."""
    _say(f"Next: {one_line(scrub(step))}", file=sys.stderr if file is None else file)


def again(args_list: list[str], drop: str | None = None) -> str:
    """The command as it was run (without --debug, and without the flag `drop` and its
    value), to repeat in a Next: line."""
    words, skip = [], False
    for arg in args_list:
        if skip or arg == "--debug":
            skip = False
            continue
        if drop is not None and arg == drop:
            skip = True
            continue
        if drop is not None and arg.startswith(f"{drop}="):
            continue
        words.append(quote_arg(arg))
    return " ".join((program(), *words))


def _step(step: str, args_list: list[str], drop: str | None = None) -> str:
    return step.replace("{command}", again(args_list, drop))


def _port(value: str) -> int:
    """--port: a port number from 1 to 65535, or 0 for any free one (the link says which),
    checked before anything is read or written."""
    try:
        port = int(value)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{value!r} is not a port: give a number from 1 to "
                                         "65535 (or 0 for any free port)")
    return port


def _front_parser() -> argparse.ArgumentParser:
    """`judgekeeper` with no command. Each option answers a question its Next: line asks."""
    p = _TopParser(prog="judgekeeper", usage="judgekeeper [PATH] [options]",
                   formatter_class=lambda prog: argparse.HelpFormatter(prog, width=HELP_WIDTH))
    p._positionals.title, p._optionals.title = "Arguments", "Options"
    p.add_argument("path", nargs="?", default=".", metavar="PATH",
                   help="your project folder (default: this folder), one results file, or an "
                        "MLflow store (mlflow.db or an mlruns/ folder)")
    p.add_argument("--tool", choices=TOOLS,
                   help="which eval tool's results to read when several are found")
    p.add_argument("--metric", metavar="NAME",
                   help="the LLM-as-a-judge to look at when the results hold several")
    p.add_argument("--experiment", metavar="NAME_OR_ID",
                   help="MLflow: the experiment to read, when several have LLM-as-a-judge results")
    p.add_argument("--tracking-uri", metavar="URI",
                   help="MLflow: the local store to read (mlflow.db, sqlite:///..., an mlruns/ "
                        "folder or file:...)")
    _normaliser_args(p)
    p.add_argument("--judge-model", metavar="NAME",
                   help="the LLM-as-a-judge's model, when the results do not record it")
    p.add_argument("--yes", action="store_true",
                   help="without a terminal: yes to the questions judgekeeper printed")
    _page_args(p)
    p.add_argument("--version", action=_Version, nargs=0, help="show the version and exit")
    p.add_argument("--debug", action="store_true",
                   help="on an unexpected error, also print where it went wrong (files, lines "
                        "and the error's type, never its text)")
    return p


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="judgekeeper", description=MESSAGE)
    p.add_argument("--debug", action="store_true")
    # Also accepted after the command name; SUPPRESS keeps it from resetting the flag above.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", metavar="command", parser_class=_Parser)

    mk = sub.add_parser("mark", parents=[common],
                        help="open a page to mark answers Pass or Fail; with enough marks, "
                             "the result")
    mk.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="your project folder (default: this folder), one results file, or "
                         "an MLflow store (mlflow.db or an mlruns/ folder)")
    mk.add_argument("--tool", choices=TOOLS,
                    help="which eval tool's results to read when several are found")
    mk.add_argument("--metric", metavar="NAME",
                    help="the LLM-as-a-judge to look at when the results hold several")
    mk.add_argument("--experiment", metavar="NAME_OR_ID",
                    help="MLflow: the experiment to read, when several have LLM-as-a-judge results")
    mk.add_argument("--tracking-uri", metavar="URI",
                    help="MLflow: the local store to read (mlflow.db, sqlite:///..., an "
                         "mlruns/ folder or file:...)")
    _normaliser_args(mk)
    mk.add_argument("--judge-model", metavar="NAME",
                    help="the LLM-as-a-judge's model, when the results do not record it")
    mk.add_argument("--yes", action="store_true",
                    help="without a terminal: yes to the questions judgekeeper printed")
    _page_args(mk)

    p.commands = {"mark": mk}  # each command's parser: an unknown flag shows its own usage
    ck = sub.add_parser("check", parents=[common],
                        help="when your LLM-as-a-judge changed, re-check it on your marks")
    ck.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="a new results file, or your project folder (default: this folder, "
                         "with its newest results)")
    p.commands["check"] = ck

    fx = sub.add_parser("fix", parents=[common],
                        help=FIX_HELP)
    fx.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="the results of grading your marked answers again with a new rule, "
                         "or your project folder (default: this folder)")
    fx.add_argument("--new", action="store_true",
                    help="start a new set of marks kept aside, made of the next marks you make")
    p.commands["fix"] = fx
    return p


def _page_args(p: argparse.ArgumentParser) -> None:
    """The marking page's options, the same for `judgekeeper` and `mark`."""
    p.add_argument("--port", type=_port, default=8765,
                   help="port on 127.0.0.1 for the page (default 8765)")
    p.add_argument("--no-browser", action="store_true",
                   help="print the page's link without opening a browser")
    what = p.add_mutually_exclusive_group()
    what.add_argument("--new", action="store_true",
                      help="start over: your marks move to .judgekeeper/previous-<date>/ "
                           "(asked first; nothing is deleted)")
    what.add_argument("--wait", action="store_true",
                      help="serve the page in this terminal until Ctrl-C, instead of in the "
                           "background")
    what.add_argument("--stop", action="store_true", help="close the open page")


def _normaliser_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pass-if", metavar="RULE",
                   help="when your LLM-as-a-judge's grades are scores: which pass, e.g. "
                        "'score>=0.5'")
    p.add_argument("--label-map", metavar="MAP",
                   help="more spellings of your LLM-as-a-judge's grades, e.g. 'good=pass,bad=fail' "
                        "(added to pass/fail, true/false, yes/no, correct/incorrect, right/wrong, "
                        "1/0); =error for a value that is no decision")


def cmd_mark(args) -> int:
    from judgekeeper import mark

    return mark.run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
                    tracking_uri=args.tracking_uri, pass_if=args.pass_if,
                    label_map=args.label_map, judge_model=args.judge_model,
                    yes=args.yes, port=args.port,
                    no_browser=args.no_browser, new=args.new, wait=args.wait, stop=args.stop)


def cmd_check(args) -> int:
    from judgekeeper import check

    return check.run(args.path)


def cmd_fix(args) -> int:
    from judgekeeper import fix

    return fix.run(args.path, new=args.new)


def cmd_front(args) -> int:
    from judgekeeper import front

    return front.run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
                     tracking_uri=args.tracking_uri, pass_if=args.pass_if,
                     label_map=args.label_map, judge_model=args.judge_model,
                     yes=args.yes, port=args.port,
                     no_browser=args.no_browser, new=args.new, wait=args.wait, stop=args.stop)


COMMANDS = {"mark": cmd_mark, "check": cmd_check, "fix": cmd_fix, None: cmd_front}


def refuse_linked_folder(path: str) -> None:
    """Stop (StartError) when the project's .judgekeeper/, or anything in it, is a link: once,
    before any command does its work, so none writes through it (`fix` writes in fix/)."""
    from judgekeeper import project, start_label

    given = Path(path)
    if given.exists():
        start_label.refuse_links(start_label.Workspace(project.project_of(given)))
# The options that take a value: the word after one is never the command
VALUED = ("--tool", "--metric", "--experiment", "--tracking-uri", "--pass-if", "--label-map",
          "--judge-model", "--port")


def command_first(args_list: list[str]) -> list[str]:
    """The arguments with the command first, so options may come before it:
    `judgekeeper --no-browser mark` is `judgekeeper mark --no-browser`. The command is the
    first word that is no option and no option's value."""
    after_option = False
    for i, arg in enumerate(args_list):
        if after_option:
            after_option = False
        elif arg == "--":
            break
        elif arg.startswith("-"):
            after_option = arg in VALUED
        elif arg in (*COMMANDS, *REMOVED):
            return [arg, *args_list[:i], *args_list[i + 1:]]
        else:
            break
    return list(args_list)


def _command(args_list: list[str]) -> str | None:
    """The command named on the command line (command_first), when it is a command or a
    removed one."""
    name = next(iter(command_first(args_list)), None)
    return name if name in (*COMMANDS, *REMOVED) else None


def parse_args(args_list: list[str]) -> argparse.Namespace:
    """The arguments as `main` reads them: a command's own, or those of `judgekeeper` with no
    command (`command` None). A removed command, or arguments that do not parse, raise
    SystemExit with argparse's code (0 after --help or --version)."""
    args_list = command_first(args_list)
    command = _command(args_list)
    if command in REMOVED:
        print(f"judgekeeper {command} was removed. Run {program()} in your project.",
              file=sys.stderr)
        _next(NEXT_REMOVED.replace("{command}", program()))
        raise SystemExit(EXIT_USAGE)
    parser = _parser() if command else _front_parser()
    if command:  # an unknown flag is said by the command itself, with its own usage
        args, extra = parser.parse_known_args(args_list)
        if extra:
            parser.commands[command].error(f"unrecognized arguments: {' '.join(extra)}")
    else:
        args = parser.parse_args(args_list)
    if not command:
        args.command = None
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        code = _main(argv)
    except BrokenPipeError:  # piped into a program that stopped reading (`| head`): no error
        code = EXIT_OK
    except KeyboardInterrupt:  # before a command started (reading the flags): as _main says it
        try:
            code = _stopped(command_first(sys.argv[1:] if argv is None else argv))
        except OSError:  # stdout can't take "Stopped.": still stopped
            code = EXIT_STOPPED
    # A closed or broken stream shows here, not in Python's own flush at exit (exit 120): the
    # code stays
    flush_stdout()
    flush_stdout(err=True)
    return code


def _stopped(args_list: list[str]) -> int:
    print("\nStopped.")
    _next(_step(NEXT_STOPPED, args_list), file=sys.stdout)
    return EXIT_STOPPED


def _main(argv: list[str] | None) -> int:
    textio._held.clear()  # a value an earlier command in this process held back is not said
    args_list = command_first(sys.argv[1:] if argv is None else argv)
    lenient_streams()  # a terminal that cannot show a character prints "?", never a crash
    try:
        args = parse_args(args_list)
    except SystemExit as e:
        if e.code in (0, None):
            return EXIT_OK
        if _command(args_list) not in REMOVED:  # a removed command said its Next: line
            _next(NEXT_HELP.replace("{command}", program(_command(args_list) or "") + " --help"))
        return EXIT_USAGE
    try:
        refuse_linked_folder(args.path)
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:  # Ctrl-C, often at a question: what was saved stays saved
        return _stopped(args_list)
    except BrokenPipeError:
        raise  # said by main: nothing went wrong
    except PageBusy as e:  # its page may be busy: never a second page for the project
        _say(str(e))
        _next(_step(NEXT_BUSY, args_list), file=sys.stdout)
        return EXIT_NEEDS_YOU
    except (AnchorError, JudgmentsError, NormaliseError, TableError,
            LabelError, StartError, SettingsError, MapError) as e:
        _error(str(e))
        _next(_step(getattr(e, "next_step", None) or NEXT_FIX, args_list,
                    getattr(e, "drop", None)))
        return EXIT_USAGE
    except MarksError as e:  # a link where judgekeeper writes: it says which (a place it
        _error(str(e))  # can't write, as a link start_label.refuse_links finds)
        _next(_step(NEXT_LINK, args_list))
        return EXIT_USAGE
    except Exception as e:  # noqa: BLE001 - the last line of defence for what users see
        if args.debug:
            print(printable(scrub(_frames(e))), file=sys.stderr, end="")
        workspace = textio.workspace_problem(e) if isinstance(e, OSError) else None
        if workspace:
            _error(workspace[0])
            _next(_step(workspace[1], args_list))
            return EXIT_USAGE
        file_problem = describe_os_error(e) if isinstance(e, OSError) else None
        if file_problem:
            _error(file_problem)
            _next(_step(NEXT_WRITE if file_problem.startswith("cannot write") else NEXT_PATH,
                        args_list))
            return EXIT_USAGE
        _error(UNEXPECTED.format(what=textio.last_read or "your results"))
        _next(NEXT_REPORT if args.debug else NEXT_UNEXPECTED)
        return EXIT_USAGE


def _frames(e: BaseException) -> str:
    """Where `e` went wrong, as a traceback without any text from the data: each frame's file,
    line and function, and each error's type, never its message or a line of source (an
    error's message can quote an answer). The errors it came from first."""
    chain, seen = [], set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        chain.append(e)
        e = e.__cause__ or (None if e.__suppress_context__ else e.__context__)
    out = []
    for n, err in enumerate(reversed(chain)):
        if n:
            out.append("\nThe error above led to this one:\n\n")
        out.append("Traceback (most recent call last):\n")
        for frame in traceback.extract_tb(err.__traceback__):
            out.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n')
        kind = type(err)
        module = "" if kind.__module__ == "builtins" else f"{kind.__module__}."
        out.append(f"{module}{kind.__qualname__}\n")
    return "".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
