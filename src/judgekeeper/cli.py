"""Command-line entry point.

Exit codes: 0 success, 1 runtime failure, 2 usage error, 8 stopped at a question (`start`
and `setup`, below), 130 Ctrl-C.

Everything printed as an error goes through redact.scrub. A failure with no better message
prints one scrubbed line; --debug adds the traceback, also scrubbed. A path that cannot be
written or read (no permission, a file where a folder should be) is a usage error: one line
that names the path and what to do.

`start` exits 0 when it is done (also when the person stops), 8 when it stopped at a question
it cannot ask (no terminal: the line before says the flag or command that answers it, and
nothing went wrong), 2 when the command is wrong or it finds nothing it can use. `setup`
exits 8 the same way.

The commands of the 0.1 CI gate (`REMOVED`) print one line that says so and exit 2. They are
not in the help.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import textwrap
import traceback

from judgekeeper import __version__
from judgekeeper.anchors import AnchorError
from judgekeeper.custom import CallableError
from judgekeeper.find import TOOLS
from judgekeeper.judgments import JudgmentsError
from judgekeeper.label import LabelError
from judgekeeper.mapper import MapError
from judgekeeper.normalise import NormaliseError
from judgekeeper.redact import printable, scrub
from judgekeeper.settings import SettingsError
from judgekeeper.start import StartError
from judgekeeper.table import TableError
from judgekeeper.textio import describe_os_error, is_windows, lenient_streams, tick

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_STOPPED = 130  # Ctrl-C, as shells report it

MESSAGE = "Check your LLM-as-a-judge."
START_HERE = (
    ("start", "find your judge's saved results and check them against your own marks"),
    ("setup", "results saved your own way? set the project up in one step, asked once"),
)
HELP_WIDTH = 100
# The commands of the 0.1 CI gate. Each prints one line and exits 2.
REMOVED = ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "check")


class _Parser(argparse.ArgumentParser):
    """argparse echoes bad argument values in its errors; scrub them too."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {printable(scrub(message))}\n")


class _TopParser(_Parser):
    """The top-level help: the message, then the commands."""

    def format_help(self) -> str:
        width = max(len(name) for name, _ in START_HERE) + 3

        def described(commands) -> list[str]:  # a long line goes on under its description
            return [line for name, text in commands for line in textwrap.wrap(
                text, HELP_WIDTH, initial_indent=f"  {name:<{width}}",
                subsequent_indent=" " * (2 + width))]

        lines = [self.description, "", "Start here:", *described(START_HERE)]
        lines += ["", "Options:",
                  "  -h, --help   show this help and exit",
                  "  --version    show the version and exit",
                  "  --debug      on an unexpected error, also print the traceback",
                  "               (credentials are still scrubbed)",
                  "", "Run `judgekeeper <command> --help` for a command's options."]
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
    if shutil.which("judgekeeper"):
        command = "judgekeeper start"
    else:
        command = f"{'py' if is_windows() else 'python3'} -m judgekeeper start"
    return [f"{tick(stream)} judgekeeper {__version__} is ready", f"Next: run {command}"]


class _Version(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print("\n".join(version_lines()))
        parser.exit()


def _say(text: str, file=None, end: str = "\n") -> None:
    """Print text that may quote an input file: control characters are dropped."""
    print(printable(text), file=file, end=end)


def _error(message: str) -> None:
    _say(f"error: {scrub(message)}", file=sys.stderr)


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


def _parser() -> argparse.ArgumentParser:
    p = _TopParser(prog="judgekeeper", description=MESSAGE)
    p.add_argument("--version", action=_Version, nargs=0)
    p.add_argument("--debug", action="store_true",
                   help="on an unexpected error, also print the traceback (credentials are "
                        "still scrubbed)")
    # Also accepted after the command name; SUPPRESS keeps it from resetting the flag above.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", metavar="command", parser_class=_Parser)

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

    su = sub.add_parser("setup", parents=[common],
                        help="set a project up in one step: where your judge's results are and "
                             "how to read them, .gitignore and the dev requirements; one "
                             "question before any file changes")
    su.add_argument("path", nargs="?", default=".", metavar="PATH",
                    help="your project folder (default: this folder), or your judge's "
                         "results file")
    su.add_argument("--metric", metavar="NAME",
                    help="the judge to check when the results hold several (all: every "
                         "judge, one at a time)")
    su.add_argument("--judge-model", metavar="NAME",
                    help="the judge's model, when the results do not say it")
    su.add_argument("--yes", action="store_true",
                    help="without a terminal, answer the yes/no questions with their "
                         "default, including the one before the file changes")

    return p


def _normaliser_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pass-if", metavar="RULE",
                   help="rule for numeric verdicts, e.g. 'score>=0.5' (required for numbers)")
    p.add_argument("--label-map", metavar="MAP",
                   help="extra verdict spellings, e.g. 'good=pass,bad=fail' (added to the "
                        "defaults pass/fail, true/false, yes/no, correct/incorrect, right/wrong, 1/0)")


def cmd_start(args) -> int:
    from judgekeeper.start import run

    if args.agent_prompt:
        from judgekeeper.own_format import AGENT_PROMPT

        print(AGENT_PROMPT)
        return 0
    for flag, given in (("--test-pass-mark", args.test_pass_mark),
                        ("--rule-file", args.rule_file is not None)):
        if given and not args.fix:
            print(f"judgekeeper start: error: {flag} works only with --fix", file=sys.stderr)
            return EXIT_USAGE
    return run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
               tracking_uri=args.tracking_uri, pass_if=args.pass_if, label_map=args.label_map, judge_model=args.judge_model,
               yes=args.yes, port=args.port, no_browser=args.no_browser, new=args.new,
               review=args.review, label_more=args.label_more, ask_again=args.ask_again,
               try_new_judge=args.try_new_judge, fix=args.fix,
               test_pass_mark=args.test_pass_mark, rule_file=args.rule_file,
               times=args.times, python=args.python, fields=args.fields,
               judge_command=args.judge_command, allow_calls=args.allow_calls)


def cmd_setup(args) -> int:
    from judgekeeper import setup_project

    return setup_project.run(args.path, yes=args.yes, metric=args.metric,
                             judge_model=args.judge_model)


COMMANDS = {"start": cmd_start, "setup": cmd_setup}


def _removed(args_list: list[str]) -> str | None:
    """The removed command named on the command line, if any: the first word that is not an
    option (the only option before a command is --debug, which takes no value)."""
    name = next((a for a in args_list if not a.startswith("-")), None)
    return name if name in REMOVED else None


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    lenient_streams()  # a terminal that cannot show a character prints "?", never a crash
    removed = _removed(args_list)
    if removed:
        print(f"judgekeeper {removed} was removed. Run judgekeeper start in your project.",
              file=sys.stderr)
        return EXIT_USAGE
    parser = _parser()
    if not args_list:
        parser.print_help()
        return EXIT_OK
    try:
        args = parser.parse_args(args_list)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if args.command is None:  # only --debug was given
        parser.print_help()
        return EXIT_OK
    try:
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:  # Ctrl-C, often at a question: what was saved stays saved
        print("\nStopped.")
        return EXIT_STOPPED
    except (AnchorError, JudgmentsError, NormaliseError, TableError, CallableError,
            LabelError, StartError, SettingsError, MapError) as e:
        _error(str(e))
        return EXIT_USAGE
    except Exception as e:  # noqa: BLE001 - the last line of defence for what users see
        if args.debug:
            _say(scrub(traceback.format_exc()), file=sys.stderr, end="")
        file_problem = describe_os_error(e) if isinstance(e, OSError) else None
        if file_problem:
            _error(file_problem)
            return EXIT_USAGE
        _error(f"{type(e).__name__}: {e}")
        if not args.debug:
            print("  run with --debug for the traceback", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
