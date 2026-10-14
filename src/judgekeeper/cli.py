"""Command-line entry point.

`judgekeeper` with no command (front.py) does the next step: finds the judge, checks it for
free, opens the page to mark answers on, and prints the result once there are enough marks; it
ends with one `Next:` line. `judgekeeper mark` (mark.py) opens the page to mark more.
`judgekeeper check` (check.py) re-tests a changed judge on the marks (exit 1: the new judge
got worse); it asks before any call to the judge.
`judgekeeper fix` (fix.py) shows where the judge goes wrong and tests a new rule on marks it
keeps hidden; it asks before any call to the judge.
`judgekeeper start` (not in the help) still has its review, fix and asking again. Exit codes: 0
success, 2 usage error, 3 the person is needed (the Next: line says what to do), 130 Ctrl-C;
`start` also 1 (asking again: the tool failed).

Every error ends with one `Next:` line, printed here. Everything printed as an error goes
through redact.scrub. A failure with no better message never prints its own text (it can hold
an answer's text): one line says judgekeeper hit a problem it didn't expect and where to report
it, exit 2; --debug adds the traceback, also scrubbed. A path that cannot be written or read
(no permission, a file where a folder should be) is a usage error: one line that names the
path and what to do.

`start` exits 0 when it is done (also when the person stops), 3 when it stopped at a question
it cannot ask (no terminal: the line before says the flag or command that answers it, and
nothing went wrong), 2 when the command is wrong or it finds nothing it can use.

Removed commands (`REMOVED`: the 0.1 CI gate, and `setup`, now part of `judgekeeper`) print
one line that says so and exit 2. They are not in the help. `check` is a command again, with
a new meaning.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
import traceback

from judgekeeper import __version__, textio
from judgekeeper.anchors import AnchorError
from judgekeeper.custom import CallableError
from judgekeeper.find import TOOLS
from judgekeeper.judgments import JudgmentsError
from judgekeeper.label import LabelError
from judgekeeper.mapper import MapError
from judgekeeper.normalise import NormaliseError
from judgekeeper.redact import one_line, printable, scrub
from judgekeeper.settings import SettingsError
from judgekeeper.start import StartError
from judgekeeper.table import TableError
from judgekeeper.textio import (
    describe_os_error,
    is_windows,
    lenient_streams,
    program,
    quote_arg,
    started_by_uvx,
    tick,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_STOPPED = 130  # Ctrl-C, as shells report it
ISSUES = "https://github.com/judgekeeper/judgekeeper/issues"
UNEXPECTED = ("judgekeeper hit a problem it didn't expect reading {what}. Please report it: "
              f"{ISSUES} (remove any answer text first).")
# The Next: line of an error; {command} is the command as it was run
NEXT_FIX = "fix what the line above says, then run `{command}`."
NEXT_UNEXPECTED = "report it; to see where it went wrong, run `{command} --debug`."
NEXT_WRITE = ("make this folder writable (judgekeeper keeps its files in .judgekeeper/ here), "
              "then run `{command}`.")
NEXT_PATH = "check the path, then run `{command}`."
NEXT_HELP = "run `{command}` to see the options."
NEXT_REMOVED = "run `{command}` in your project."
NEXT_STOPPED = "run `{command}` to carry on."

MESSAGE = "Check your LLM-as-a-judge in 5 steps."
STEPS = """\
  1. Find      judgekeeper          finds your eval results and your judge
  2. Mark      in your browser      you mark answers Pass or Fail
  3. Measure   judgekeeper          how often your judge agrees with you
  4. Fix       judgekeeper fix      write a better rule, tested on hidden marks
  5. Re-check  judgekeeper check    after you change your judge or update
                                    your eval tool"""
READS = """\
judgekeeper can read results from promptfoo, DeepEval, Inspect AI,
MLflow, or a CSV or JSONL file with these columns:
  input, output, verdict"""
COMMANDS_HELP = (
    ("mark", "mark more answers"),
    ("fix", "see where your judge goes wrong and test a better rule"),
    ("check", "re-check your judge on your marks after a change"),
)
HELP_WIDTH = 80
# Removed commands: the 0.1 CI gate, and setup (part of judgekeeper now). Each prints one line
# and exits 2.
REMOVED = ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "setup")


class _Parser(argparse.ArgumentParser):
    """argparse echoes bad argument values in its errors; scrub them too. An error of
    `judgekeeper check` ends in one Next: line (its flags for automatic checks, --on, --off,
    --hook, --fast, --ci, --baseline and --port, are gone)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        after = ""
        if self.prog.endswith(" check"):
            after = f"Next: run `{program('check')}` yourself after you change your judge.\n"
        self.exit(EXIT_USAGE, f"{self.prog}: error: {printable(scrub(message))}\n{after}")


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

    When the `judgekeeper` command is not on the PATH, the next step names the form that works.
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
        command = f"{'py' if is_windows() else 'python3'} -m judgekeeper"
    return [f"{tick(stream)} judgekeeper {__version__} is ready", f"Next: run {command}"]


class _Version(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print("\n".join(version_lines()))
        parser.exit()


def _say(text: str, file=None, end: str = "\n") -> None:
    """Print text that may quote an input file: control characters are dropped."""
    print(printable(text), file=file, end=end)


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


def _times(value: str) -> int:
    """`start --times`: 1 to 5."""
    try:
        n = int(value)
    except ValueError:
        n = 0
    if not 1 <= n <= 5:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number from 1 to 5")
    return n


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
                   help="the judge to look at when the results hold several")
    p.add_argument("--experiment", metavar="NAME_OR_ID",
                   help="MLflow: the experiment to read, when several have judge results")
    p.add_argument("--tracking-uri", metavar="URI",
                   help="MLflow: the local store to read (mlflow.db, sqlite:///..., an mlruns/ "
                        "folder or file:...)")
    _normaliser_args(p)
    p.add_argument("--judge-model", metavar="NAME",
                   help="the judge's model, when the results do not record it")
    p.add_argument("--fields", metavar="LIST",
                   help="a DeepEval GEval judge: the parts it reads, e.g. input,actual_output")
    p.add_argument("--yes", action="store_true",
                   help="without a terminal: yes to the questions judgekeeper printed")
    _page_args(p)
    p.add_argument("--version", action=_Version, nargs=0, help="show the version and exit")
    p.add_argument("--debug", action="store_true",
                   help="on an unexpected error, also print the traceback (credentials are "
                        "still scrubbed)")
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
                    help="the judge to look at when the results hold several")
    mk.add_argument("--experiment", metavar="NAME_OR_ID",
                    help="MLflow: the experiment to read, when several have judge results")
    mk.add_argument("--tracking-uri", metavar="URI",
                    help="MLflow: the local store to read (mlflow.db, sqlite:///..., an "
                         "mlruns/ folder or file:...)")
    _normaliser_args(mk)
    mk.add_argument("--judge-model", metavar="NAME",
                    help="the judge's model, when the results do not record it")
    mk.add_argument("--fields", metavar="LIST",
                    help="a DeepEval GEval judge: the parts it reads, e.g. input,actual_output")
    mk.add_argument("--yes", action="store_true",
                    help="without a terminal: yes to the questions judgekeeper printed")
    _page_args(mk)

    ck = sub.add_parser("check", parents=[common],
                        help="when your judge changed, re-check it on your marks")
    ck.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="your project folder (default: this folder)")
    ck.add_argument("--yes", action="store_true",
                    help="without a terminal: go ahead and ask your judge (it makes AI calls, "
                         "paid with your own key)")
    p.check = ck

    fx = sub.add_parser("fix", parents=[common],
                        help="see where your judge goes wrong and test a better rule")
    fx.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="your project folder (default: this folder)")
    fx.add_argument("--yes", action="store_true",
                    help="without a terminal: go ahead and test the new rule (it makes AI "
                         "calls, paid with your own key)")
    fx.add_argument("--new", action="store_true",
                    help="hide a new set of your marks to test rules on")

    st = sub.add_parser("start", parents=[common],
                        help="find your judge's saved results and check them against your own "
                             "labels")
    st.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="your project folder (default: this folder), one results file, or "
                         "an MLflow store (mlflow.db or an mlruns/ folder)")
    st.add_argument("--tool", choices=TOOLS,
                    help="which eval tool's results to use, when several are found")
    st.add_argument("--metric", metavar="NAME",
                    help="the judge metric or scorer to check, when the results hold several")
    st.add_argument("--experiment", metavar="NAME_OR_ID",
                    help="MLflow: the experiment to read, when several have judge results")
    st.add_argument("--tracking-uri", metavar="URI",
                    help="MLflow: the store to read, when the folder has several (mlflow.db, "
                         "sqlite:///..., an mlruns/ folder or file:...; default: "
                         "MLFLOW_TRACKING_URI when it names one)")
    _normaliser_args(st)
    st.add_argument("--judge-model", metavar="NAME",
                    help="the judge's model, when the results do not record it")
    st.add_argument("--port", type=_port, default=8765,
                    help="port on 127.0.0.1 for the page that opens (default 8765)")
    st.add_argument("--no-browser", action="store_true",
                    help="print the page's link instead of opening a browser")
    then = st.add_mutually_exclusive_group()
    then.add_argument("--new", action="store_true",
                      help="start a new check: move what is saved in .judgekeeper/ (except "
                           ".gitignore, baseline.json and records/) to .judgekeeper/previous-<date>/; "
                           "nothing is deleted")
    then.add_argument("--review", action="store_true",
                      help="after a result: review the answers where you and your judge "
                           "disagree (no AI call)")
    then.add_argument("--ask-again", action="store_true",
                      help="after a result: ask your judge again about your marked answers, "
                           "through your own eval tool; it shows the plan (calls, cost, key "
                           "name) and asks before any call")
    then.add_argument("--try-new-judge", action="store_true",
                      help="after a result: try the new version of your judge (found in your "
                           "newest results) on the answers you already marked; it asks before "
                           "any call")
    then.add_argument("--label-more", action="store_true",
                      help="after a result: open the page to mark more answers")
    then.add_argument("--fix", action="store_true",
                      help="after the review: what your judge gets wrong, and a fair test of "
                           "a change on answers kept aside (no AI call)")
    st.add_argument("--test-pass-mark", action="store_true",
                    help="with --fix: test the pass mark that fits your marks best, in the "
                         "terminal (free)")
    st.add_argument("--rule-file", metavar="PATH",
                    help="with --fix: check the new rule in this file (as your coding agent "
                         "writes it), save it and say where it goes; no page (free)")
    st.add_argument("--times", type=_times, default=None, metavar="N",
                    help="asking again: how many times to ask about each answer, 1 to 5 "
                         "(default 2; 1 with --try-new-judge)")
    st.add_argument("--allow-calls", type=int, metavar="N",
                    help="asking again: approve up to N judge calls without the question "
                         "(needed without a terminal, and above 1,000 calls)")
    st.add_argument("--python", metavar="PATH",
                    help="asking again: the Python you run your evals with (default: the "
                         "active virtual environment, else the project's .venv or venv)")
    st.add_argument("--fields", metavar="LIST",
                    help="asking a DeepEval GEval judge again: the parts it reads, e.g. "
                         "input,actual_output")
    st.add_argument("--judge-command", metavar="CMD",
                    help="asking again: your own judge as a command (one answer as JSON on "
                         "stdin, the verdict on stdout)")
    st.add_argument("--yes", action="store_true",
                    help="without a terminal, answer yes/no questions with the default (it "
                         "never picks a tool or a judge)")
    st.add_argument("--agent-prompt", action="store_true",
                    help="print a prompt for your coding agent that turns judge results saved "
                         "in your own format into judgekeeper's table, then exit")
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
                   help="when your judge's grades are scores: which pass, e.g. 'score>=0.5'")
    p.add_argument("--label-map", metavar="MAP",
                   help="more spellings of your judge's grades, e.g. 'good=pass,bad=fail' "
                        "(added to pass/fail, true/false, yes/no, correct/incorrect, "
                        "right/wrong, 1/0)")


def cmd_start(args) -> int:
    from judgekeeper.start import run

    if args.agent_prompt:
        from judgekeeper.own_format import agent_prompt

        print(agent_prompt())
        return 0
    for flag, given in (("--test-pass-mark", args.test_pass_mark),
                        ("--rule-file", args.rule_file is not None)):
        if given and not args.fix:
            print(f"judgekeeper start: error: {flag} works only with --fix", file=sys.stderr)
            _next(f"run `{program('start')} --fix {flag}`, or leave {flag} out.")
            return EXIT_USAGE
    return run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
               tracking_uri=args.tracking_uri, pass_if=args.pass_if, label_map=args.label_map, judge_model=args.judge_model,
               yes=args.yes, port=args.port, no_browser=args.no_browser, new=args.new,
               review=args.review, label_more=args.label_more, ask_again=args.ask_again,
               try_new_judge=args.try_new_judge, fix=args.fix,
               test_pass_mark=args.test_pass_mark, rule_file=args.rule_file,
               times=args.times, python=args.python, fields=args.fields,
               judge_command=args.judge_command, allow_calls=args.allow_calls)


def cmd_mark(args) -> int:
    from judgekeeper import mark

    return mark.run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
                    tracking_uri=args.tracking_uri, pass_if=args.pass_if,
                    label_map=args.label_map, judge_model=args.judge_model,
                    fields=args.fields, yes=args.yes, port=args.port,
                    no_browser=args.no_browser, new=args.new, wait=args.wait, stop=args.stop)


def cmd_check(args) -> int:
    from judgekeeper import check

    return check.run(args.path, yes=args.yes)


def cmd_fix(args) -> int:
    from judgekeeper import fix

    return fix.run(args.path, yes=args.yes, new=args.new)


def cmd_front(args) -> int:
    from judgekeeper import front

    return front.run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
                     tracking_uri=args.tracking_uri, pass_if=args.pass_if,
                     label_map=args.label_map, judge_model=args.judge_model,
                     fields=args.fields, yes=args.yes, port=args.port,
                     no_browser=args.no_browser, new=args.new, wait=args.wait, stop=args.stop)


COMMANDS = {"mark": cmd_mark, "check": cmd_check, "fix": cmd_fix, "start": cmd_start,
            None: cmd_front}


def _command(args_list: list[str]) -> str | None:
    """The command named on the command line: the first word after any --debug (the only
    option that may come before a command), when it is a command or a removed one."""
    name = next((a for a in args_list if a != "--debug"), None)
    return name if name in (*COMMANDS, *REMOVED) else None


def parse_args(args_list: list[str]) -> argparse.Namespace:
    """The arguments as `main` reads them: a command's own, or those of `judgekeeper` with no
    command (`command` None). A removed command, or arguments that do not parse, raise
    SystemExit with argparse's code (0 after --help or --version)."""
    command = _command(args_list)
    if command in REMOVED:
        print(f"judgekeeper {command} was removed. Run {program()} in your project.",
              file=sys.stderr)
        _next(NEXT_REMOVED.replace("{command}", program()))
        raise SystemExit(EXIT_USAGE)
    parser = _parser() if command else _front_parser()
    if command == "check":  # an unknown flag is said by `check` itself, with its Next: line
        args, extra = parser.parse_known_args(args_list)
        if extra:
            parser.check.error(f"unrecognized arguments: {' '.join(extra)}")
    else:
        args = parser.parse_args(args_list)
    if not command:
        args.command = None
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except BrokenPipeError:  # piped into a program that stopped reading (`| head`): no error
        _quiet_stdout()
        return EXIT_OK


def _quiet_stdout() -> None:
    """Point stdout at the null device, so Python's own flush at exit can't fail again."""
    import os

    try:
        with open(os.devnull, "w", encoding="utf-8") as null:
            os.dup2(null.fileno(), sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):  # io.UnsupportedOperation is an OSError
        pass


def _main(argv: list[str] | None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    lenient_streams()  # a terminal that cannot show a character prints "?", never a crash
    try:
        args = parse_args(args_list)
    except SystemExit as e:
        if e.code in (0, None):
            return EXIT_OK
        if _command(args_list) not in (*REMOVED, "check"):  # these said their Next: line
            _next(NEXT_HELP.replace("{command}", program(_command(args_list) or "") + " --help"))
        return EXIT_USAGE
    try:
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:  # Ctrl-C, often at a question: what was saved stays saved
        print("\nStopped.")
        _next(_step(NEXT_STOPPED, args_list), file=sys.stdout)
        return EXIT_STOPPED
    except BrokenPipeError:
        raise  # said by main: nothing went wrong
    except (AnchorError, JudgmentsError, NormaliseError, TableError, CallableError,
            LabelError, StartError, SettingsError, MapError) as e:
        _error(str(e))
        _next(_step(getattr(e, "next_step", None) or NEXT_FIX, args_list,
                    getattr(e, "drop", None)))
        return EXIT_USAGE
    except Exception as e:  # noqa: BLE001 - the last line of defence for what users see
        if args.debug:
            _say(scrub(traceback.format_exc()), file=sys.stderr, end="")
        file_problem = describe_os_error(e) if isinstance(e, OSError) else None
        if file_problem:
            _error(file_problem)
            _next(_step(NEXT_WRITE if file_problem.startswith("cannot write") else NEXT_PATH,
                        args_list))
            return EXIT_USAGE
        _error(UNEXPECTED.format(what=textio.last_read or "your results"))
        _next(_step(NEXT_UNEXPECTED, args_list))
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
