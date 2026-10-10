"""Command-line entry point.

Exit codes: 0 success, 1 runtime failure, 2 usage error (including unmapped verdicts or
labels, duplicate ids, and more than 1,000 --callable/--exec judge calls without --yes),
3 anchor hash mismatch, 8 stopped at a question (`start` and `setup`, below).
`gate` maps its status to an exit code: 0 PASS, 1 FAIL, 3 ANCHORS_CHANGED, 4 FLAKY,
5 JUDGE_CHANGED (see judgekeeper.gate.EXIT_CODES). `migrate` exits 0 when the analysis
completes, 1 when --fail-on matches.

Everything printed as an error goes through redact.scrub. A failure with no better message
(a provider error after the SDK's retries) prints one scrubbed line; --debug adds the
traceback, also scrubbed. A path that cannot be written or read (no permission, a file where
a folder should be) is a usage error: one line that names the path and what to do.

`start` exits 0 when it is done (also when the person stops), 8 when it stopped at a question
it cannot ask (no terminal: the line before says the flag or command that answers it, and
nothing went wrong), 2 when the command is wrong or it finds nothing it can use. `setup`
exits 8 the same way.

`judge` exits 1 when every judgment was an error (the judge program was not found, the judge
function raised each time): the run files are written, but there is nothing to validate.

Text that comes from an input file (a report, a run header, a table, an imported result) is
printed through `_say`, which drops control characters: a file cannot send escape sequences to
the terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
import traceback
from itertools import pairwise
from pathlib import Path

from judgekeeper import __version__
from judgekeeper.anchors import (
    AnchorError,
    AnchorHashMismatch,
    load_verified,
    manifest_path_for,
    seal_new,
)
from judgekeeper.custom import CallableError, CallLimitError
from judgekeeper.find import TOOLS
from judgekeeper.fingerprint import plaintext_warning
from judgekeeper.gate import DEFAULT_BASELINE, DEFAULT_CONFIG, GateError
from judgekeeper.judging import JudgeCallError
from judgekeeper.judgments import JudgmentsError
from judgekeeper.label import LabelError
from judgekeeper.mapper import MapError
from judgekeeper.migrate import MigrateError
from judgekeeper.normalise import NormaliseError
from judgekeeper.prompts import PromptError, unfilled_marker
from judgekeeper.readers.langfuse_api import LangfuseError
from judgekeeper.redact import printable, register_key_env, scrub
from judgekeeper.report import ReportError
from judgekeeper.settings import SettingsError
from judgekeeper.start import StartError
from judgekeeper.table import TableError
from judgekeeper.templates import DEFAULT_OUT, ExistsError, next_steps, write_starter
from judgekeeper.textio import describe_os_error, is_windows, lenient_streams, quote_arg, tick

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_HASH_MISMATCH = 3
EXIT_STOPPED = 130  # Ctrl-C, as shells report it
# The first error of a failed judge is quoted on one line, up to this many characters.
MAX_ERROR_SHOWN = 300

MESSAGE = "Check your LLM-as-a-judge."
# The top-level help shows the commands in three groups. Every command is in exactly one
# (tests/test_front_door.py compares these with the parser).
START_HERE = (
    ("start", "find your judge's saved results and check them against your own marks"),
    ("setup", "results saved your own way? set the project up in one step, asked once"),
)
IN_CI = ("init", "judge", "validate", "baseline", "gate", "migrate")
HELP_WIDTH = 100
OTHER_INPUTS = (
    ("check", "a table of judge verdicts and human labels in, a verdict out"),
    ("import", ("your eval tool's results into judge runs (promptfoo, DeepEval, Inspect AI, "
                "MLflow, Langfuse, records)")),
)

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """argparse echoes bad argument values in its errors; scrub them too."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {printable(scrub(message))}\n")


class _TopParser(_Parser):
    """The top-level help: the message, then the commands in three groups."""

    def format_help(self) -> str:
        width = max(len(name) for name, _ in START_HERE + OTHER_INPUTS) + 3

        def described(commands) -> list[str]:  # a long line goes on under its description
            return [line for name, text in commands for line in textwrap.wrap(
                text, HELP_WIDTH, initial_indent=f"  {name:<{width}}",
                subsequent_indent=" " * (2 + width))]

        lines = [self.description, "", "Start here:", *described(START_HERE)]
        lines += ["", "Check again in CI:", f"  {', '.join(IN_CI)}"]
        lines += ["", "Other inputs:", *described(OTHER_INPUTS)]
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
    lines = [f"{tick(stream)} judgekeeper {__version__} is ready",
             f"Next: run {command}"]
    if not in_an_environment():
        from judgekeeper.own_format import INSTALL_URL

        lines.append("judgekeeper is installed outside a project. Install it inside your "
                     f"project's environment instead (see {INSTALL_URL}).")
    return lines


def in_an_environment() -> bool:
    """Whether this Python runs inside a project's environment (a virtual or conda
    environment), not on the computer as a whole. Conda's own base environment is not one,
    and neither is an install made with pipx or `uv tool install`: their virtual environments
    are the tool's own, kept with the user's other tools (`tool_install`)."""
    if tool_install(sys.prefix):
        return False
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix) or os.environ.get("VIRTUAL_ENV"):
        return True
    return os.environ.get("CONDA_DEFAULT_ENV") not in (None, "", "base")


def _parts(path: str) -> tuple[str, ...]:
    """A path's parts, lower-cased for a Windows path (which ignores case)."""
    from pathlib import PurePosixPath, PureWindowsPath

    if "\\" in path or (len(path) > 1 and path[1] == ":"):
        return tuple(x.lower() for x in PureWindowsPath(path).parts)
    return PurePosixPath(path).parts


def tool_install(prefix: str) -> bool:
    """Whether `prefix` (sys.prefix) is a virtual environment made by pipx or `uv tool
    install`: under PIPX_HOME/venvs or UV_TOOL_DIR when they are set, else under pipx's
    `pipx/venvs/` or uv's `uv/.../tools/` folder, on Mac, Linux and Windows."""
    parts = _parts(str(prefix))
    for name, inside in (("PIPX_HOME", ("venvs",)), ("UV_TOOL_DIR", ())):
        home = os.environ.get(name)
        if home:
            base = _parts(home) + inside
            if parts[:len(base)] == base and len(parts) > len(base):
                return True
    folders = [x.lower() for x in parts[:-1]]
    if any(a in ("pipx", ".pipx") and b == "venvs" for a, b in pairwise(folders)):
        return True
    return bool(folders) and folders[-1] == "tools" and "uv" in folders[:-1]


class _Version(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print("\n".join(version_lines()))
        parser.exit()


def _say(text: str, file=None, end: str = "\n") -> None:
    """Print text that may quote an input file: control characters are dropped."""
    print(printable(text), file=file, end=end)


def _error(message: str) -> None:
    _say(f"error: {scrub(message)}", file=sys.stderr)


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

    i = sub.add_parser("init", parents=[common],
                       help="write a starter rule file for your own metric")
    i.add_argument("--out", default=DEFAULT_OUT,
                   help=f"rule file to write (default {DEFAULT_OUT}); parent folders are created")
    i.add_argument("--pairwise", action="store_true",
                   help="a rule that compares two outputs (A or B) instead of pass or fail")
    i.add_argument("--force", action="store_true", help="overwrite an existing file")

    j = sub.add_parser("judge", parents=[common], help="run a judge over a frozen anchor set")
    j.add_argument("anchors", help="anchor set JSONL (must be frozen)")
    j.add_argument("--runner", choices=["anthropic", "openai", "replay"],
                   help="a built-in judge; or bring your own with --callable or --exec")
    j.add_argument("--callable", metavar="MODULE:FUNCTION",
                   help="your Python judge, e.g. mypkg.judges:my_judge, called as "
                        "judge(item) -> bool | str | float | tuple | dict (sync or async)")
    j.add_argument("--exec", metavar="COMMAND",
                   help="any program, e.g. \"node judge.js\": one item as JSON on stdin per "
                        "call; stdout is a bare verdict or a JSON object; a non-zero exit is "
                        "an error judgment")
    j.add_argument("--timeout", type=float, default=300.0,
                   help="seconds per --exec call before it counts as an error (default 300)")
    j.add_argument("--yes", action="store_true",
                   help="run --callable/--exec judges even above 1,000 judge calls")
    _normaliser_args(j)
    j.add_argument("--model", help="model id (anthropic/openai); recorded in the fingerprint "
                                   "for --callable/--exec")
    j.add_argument("--prompt", help="judge prompt markdown with rubric_version frontmatter; "
                                    "for --callable/--exec, any prompt file, hashed into the "
                                    "fingerprint")
    j.add_argument("--fixture", help="recorded judgments JSONL (replay runner)")
    j.add_argument("--base-url", metavar="URL",
                   help="send requests to this endpoint instead of the provider default: any "
                        "OpenAI-compatible server for --runner openai (Azure OpenAI v1, "
                        "OpenRouter, Together, LiteLLM, Ollama, vLLM), a gateway for --runner "
                        "anthropic. Overrides OPENAI_BASE_URL / ANTHROPIC_BASE_URL. Must not "
                        "contain credentials")
    j.add_argument("--api-key-env", metavar="NAME",
                   help="name of the environment variable that holds the API key (default "
                        "ANTHROPIC_API_KEY or OPENAI_API_KEY). This takes a variable name, "
                        "never a key: there is no flag that takes a key value, and there never "
                        "will be")
    j.add_argument("--temperature", type=float,
                   help="sampling temperature (default 0 for anthropic/openai; unknown for "
                        "--callable/--exec unless given)")
    j.add_argument("--max-tokens", type=int, default=1024)
    j.add_argument("--runs", type=int, default=1)
    j.add_argument("--workers", type=int, default=4, help="concurrent judge calls")
    j.add_argument("--out", required=True, help="directory for run-NN.jsonl files")

    v = sub.add_parser("validate", parents=[common],
                       help="write a validation report from judged runs")
    v.add_argument("anchors", help="anchor set JSONL (must be frozen)")
    v.add_argument("runs", help="directory of judgments files from `judge`")
    v.add_argument("--out", required=True, help="directory for report.json and report.html")

    b = sub.add_parser("baseline", parents=[common],
                       help="set or show the committed baseline report")
    bsub = b.add_subparsers(dest="baseline_command", metavar="action")
    bs = bsub.add_parser("set", help="copy a report.json to the baseline path")
    bs.add_argument("report", help="report.json from `validate`")
    bs.add_argument("--path", default=str(DEFAULT_BASELINE),
                    help=f"baseline file (default {DEFAULT_BASELINE})")
    bw = bsub.add_parser("show", help="print the baseline's judge, anchors and metrics")
    bw.add_argument("--path", default=str(DEFAULT_BASELINE),
                    help=f"baseline file (default {DEFAULT_BASELINE})")

    g = sub.add_parser("gate", parents=[common],
                       help="decide PASS/FAIL/FLAKY/... for a report, for CI")
    g.add_argument("report", help="report.json from `validate`")
    g.add_argument("--baseline", help=f"baseline report (default {DEFAULT_BASELINE} if present)")
    g.add_argument("--config", help=f"gate thresholds TOML (default {DEFAULT_CONFIG} if present)")
    g.add_argument("--out", help="directory for gate.json and gate.md (default: next to report)")
    g.add_argument("--allow-judge-change", action="store_true",
                   help="warn instead of stopping when the judge differs from the baseline")
    g.add_argument("--require-fingerprint", action="store_true",
                   help="treat a judge field unknown on either side as JUDGE_CHANGED (\"cannot "
                        "prove same judge\") instead of a warning")
    g.add_argument("--flaky-as", choices=["pass", "fail"],
                   help="exit 0 (pass) or 1 (fail) on FLAKY instead of 4")

    m = sub.add_parser("migrate", parents=[common],
                       help="compare an old and a new judge on the same anchor set")
    m.add_argument("anchors", help="anchor set JSONL (must be frozen)")
    m.add_argument("old_runs", help="directory of runs from the old judge")
    m.add_argument("new_runs", help="directory of runs from the new judge")
    m.add_argument("--out", required=True, help="directory for migration.json and migration.html")
    m.add_argument("--rebase", action="store_true",
                   help="make the new judge's report the baseline and keep migration.json "
                        "under <baseline dir>/migrations/ as the audit trail")
    m.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                   help=f"baseline file written by --rebase (default {DEFAULT_BASELINE})")
    m.add_argument("--fail-on", choices=["worse", "different"],
                   help="exit 1 on WORSE (worse), or on WORSE or DIFFERENT (different)")
    m.add_argument("--config", help=f"thresholds TOML, [migrate] table (default {DEFAULT_CONFIG} "
                                    "if present)")

    c = sub.add_parser("check", parents=[common],
                       help="a CSV or JSONL of judge verdicts and human labels in, a report out")
    c.add_argument("table", help="CSV or JSONL, one row per judgment")
    c.add_argument("--judge", default="verdict", help="judge verdict column (default verdict)")
    c.add_argument("--human", default="label", help="human label column (default label)")
    c.add_argument("--id", help="id column (default id when present; otherwise ids are a hash "
                                "of the input and output)")
    c.add_argument("--run", help="run column for repeat runs (default run when present)")
    c.add_argument("--input", help="input column (default input when present)")
    c.add_argument("--output", help="output column (default output when present)")
    c.add_argument("--reason", help="judge rationale column (default reason when present)")
    _normaliser_args(c)
    c.add_argument("--out", default="judgekeeper-report",
                   help="directory for the anchor set, runs and report (default "
                        "judgekeeper-report)")

    im = sub.add_parser("import", parents=[common],
                        help="promptfoo, DeepEval, Inspect AI, MLflow or Langfuse results (or "
                             "ScoreRecords) in, a report out")
    im.add_argument("tool", choices=["promptfoo", "deepeval", "inspect", "records", "mlflow",
                                     "langfuse"],
                    help="which tool wrote the results; records is judgekeeper's ScoreRecord "
                         "JSONL or CSV; mlflow and langfuse read the platform, not files")
    im.add_argument("paths", nargs="*", metavar="path",
                    help="result files, directories or globs; several files are several runs "
                         "(not for mlflow or langfuse)")
    im.add_argument("--metric", metavar="NAME",
                    help="the judge metric, scorer or MLflow assessment to validate, when the "
                         "source holds several")
    im.add_argument("--labels", metavar="TABLE",
                    help="human labels: CSV or JSONL with id and human_label columns (wins "
                         "over human labels in the source); a slice column is kept")
    _normaliser_args(im)
    im.add_argument("--runs-by-order", action="store_true",
                    help="number each item's verdicts in a file 1, 2, 3 in order of "
                         "appearance, in place of any run index (any tool)")
    im.add_argument("--id-var", metavar="NAME",
                    help="promptfoo: the test var that holds the item id")
    im.add_argument("--map", metavar="MAP",
                    help="records: field=column pairs for renamed columns, e.g. "
                         "'target_id=trace_id,label=value,annotator_kind=source'")
    im.add_argument("--check", action="store_true",
                    help="records: check the file and say what judgekeeper reads in it (counts, "
                         "the pass/fail split per judge, the first 3 records, every problem "
                         "with its line); writes nothing. Exit 0 if usable, 2 if not")
    im.add_argument("--anchors-out", metavar="JSONL",
                    help="mlflow, langfuse: also write every item with a human label as a "
                         "frozen anchor set, to re-judge with `judgekeeper judge`")
    ml = im.add_argument_group("mlflow (needs pip install \"judgekeeper[mlflow]\")")
    ml.add_argument("--experiment", metavar="NAME_OR_ID", help="MLflow experiment to read")
    ml.add_argument("--run-id", action="append", metavar="ID",
                    help="only this MLflow run's judge assessments (repeatable; default all "
                         "runs, each one judgekeeper run, in start order)")
    ml.add_argument("--tracking-uri", metavar="URI",
                    help="MLflow tracking URI (default: MLFLOW_TRACKING_URI, as MLflow "
                         "resolves it)")
    ml.add_argument("--id-from", metavar="KEY",
                    help="a trace tag or request input key that holds a stable item id "
                         "(default: a hash of the request input)")
    ml.add_argument("--temperature", type=float,
                    help="the judge's temperature, recorded in the fingerprint (MLflow does "
                         "not store it)")
    lf = im.add_argument_group("langfuse (LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, "
                               "LANGFUSE_SECRET_KEY)")
    lf.add_argument("--judge-score", metavar="NAME", help="name of the judge's score")
    lf.add_argument("--human-score", metavar="NAME", help="name of the human score")
    lf.add_argument("--from", dest="from_", metavar="DATE",
                    help="read scores from this date or ISO time (inclusive)")
    lf.add_argument("--to", metavar="DATE", help="read scores before this date or ISO time")
    lf.add_argument("--max-items", type=int, metavar="N",
                    help="read at most N scores (a time window or this is required)")
    lf.add_argument("--rate", type=float, default=None, metavar="PER_MINUTE",
                    help="at most this many requests a minute (default 30, the Hobby limit)")
    im.add_argument("--out", default="judgekeeper-report",
                    help="directory for the anchor set, runs and report (default "
                         "judgekeeper-report)")

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
    st.add_argument("--port", type=int, default=8765,
                    help="port on 127.0.0.1 for the page that opens (default 8765)")
    st.add_argument("--no-browser", action="store_true",
                    help="print the page's link instead of opening a browser")
    then = st.add_mutually_exclusive_group()
    then.add_argument("--new", action="store_true",
                      help="start a new check: move what is saved in .judgekeeper/ (except "
                           "baseline.json and records/) to .judgekeeper/previous-<date>/; "
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
                           "a change on answers set aside (no AI call)")
    st.add_argument("--test-pass-mark", action="store_true",
                    help="with --fix: test the pass mark that fits your marks best, in the "
                         "terminal (free)")
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
                         "stdin, the verdict on stdout, as --exec)")
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


def _print_report(report: dict, out: Path) -> None:
    from judgekeeper.report import plain_summary

    print(plain_summary(report))
    _print_verdict(report)
    print(f"wrote {out / 'report.json'} and {out / 'report.html'}")


def _print_verdict(report: dict) -> None:
    """The summary line, then every flag it may point to ("Read the flags below")."""
    _say(report["verdict"]["summary"])
    for flag in report["verdict"]["flags"]:
        _say(f"  - {flag['message']}")


def _make_runner(args):
    from judgekeeper.runners import AnthropicRunner, OpenAIRunner, ReplayRunner

    if args.runner == "replay":
        if args.base_url or args.api_key_env:
            raise UsageError("--base-url and --api-key-env apply to the anthropic and openai "
                             "runners only")
        if not args.fixture:
            raise UsageError("--runner replay needs --fixture")
        if not Path(args.fixture).is_file():
            raise UsageError(f"fixture not found: {args.fixture}")
        return ReplayRunner(args.fixture)
    if not args.model or not args.prompt:
        raise UsageError(f"--runner {args.runner} needs --model and --prompt")
    if args.api_key_env is not None:
        if not _ENV_NAME.fullmatch(args.api_key_env):
            # Do not echo it: a value that is not a variable name may be a pasted key.
            raise UsageError("--api-key-env takes the name of an environment variable "
                             "(letters, digits and underscores), not a key")
        register_key_env(args.api_key_env)
    cls = AnthropicRunner if args.runner == "anthropic" else OpenAIRunner
    try:
        temperature = 0.0 if args.temperature is None else args.temperature
        runner = cls(model=args.model, prompt_path=args.prompt, temperature=temperature,
                     max_tokens=args.max_tokens, base_url=args.base_url,
                     api_key_env=args.api_key_env)
    except (RuntimeError, ValueError) as e:
        raise UsageError(str(e)) from None
    if runner.used_placeholder_key:
        print(f"note: {runner.api_key_env} is not set; sending a placeholder key to "
              f"{runner.endpoint} (local servers need no key)", file=sys.stderr)
    if plaintext := plaintext_warning(runner.base_url):
        print(f"warning: {plaintext}", file=sys.stderr)
    return runner


def cmd_init(args) -> int:
    try:
        out = write_starter(args.out, pairwise=args.pairwise, force=args.force)
    except ExistsError as e:
        raise UsageError(str(e)) from None
    print(next_steps(out))
    return EXIT_OK


def _refuse_unfilled_prompt(prompt: str | None) -> None:
    """A rule file from `init` that still has a [FILL IN: ...] marker is not a judge yet."""
    if not prompt or not Path(prompt).is_file():
        return  # a missing file is reported by the runner that needs it
    text = Path(prompt).read_bytes().decode("utf-8", errors="replace")
    found = unfilled_marker(text)
    if found:
        line, marker = found
        raise UsageError(f"{prompt} is not filled in: line {line} still has {marker}. Write "
                         "that part of the rule, then run judge again")


def cmd_judge(args) -> int:
    from judgekeeper.judging import run_judge

    if args.runs < 1:
        raise UsageError("--runs must be at least 1")
    sources = [x for x in (args.runner, args.callable, args.exec) if x]
    if len(sources) != 1:
        raise UsageError("judge needs exactly one of --runner, --callable or --exec")
    _refuse_unfilled_prompt(args.prompt)
    _seal_new(args.anchors)
    items, manifest = load_verified(args.anchors)
    if args.runner is None:
        return _judge_custom(args, items, manifest, run_judge)
    if args.pass_if or args.label_map or args.yes:
        raise UsageError("--pass-if, --label-map and --yes apply to --callable and --exec")
    runner = _make_runner(args)
    workers = 1 if args.runner == "replay" else max(1, args.workers)
    files = run_judge(items, runner, args.runs, args.out, manifest["sha256"], workers=workers,
                      progress=lambda msg: print(msg, file=sys.stderr))
    return _judge_outcome(files)


def _seal_new(anchors: str) -> None:
    """Seal an anchor set the first time `judge` or `validate` gets it, and say so."""
    manifest = seal_new(anchors)
    if manifest is not None:
        mpath = manifest_path_for(anchors)
        _say(f"Sealed {anchors}: {_count(manifest['item_count'], 'item')} "
             f"(sha256 {manifest['sha256'][:12]}...). Commit {mpath} with it.")


def _count(n: int, noun: str, fmt: str = "") -> str:
    """`3 runs`, `1 run`. `fmt` is the number's format: "," for thousands separators."""
    return f"{n:{fmt}} {noun}{'' if n == 1 else 's'}"


def _judge_outcome(files) -> int:
    """Say how many judgments were errors. A run of nothing but errors is a failure: the
    files are written, but a judge that never answered has not been run."""
    n, total = files.n_errors, files.n_judgments
    if not n:
        return EXIT_OK
    first = " ".join((scrub(files.first_error) or "").split())[:MAX_ERROR_SHOWN]
    counted = (f"{n} of {_count(total, 'judgment')} "
               f"{'was an error' if n == 1 else 'were errors'}")
    if n == total:
        _error(f"the judge failed on every item ({counted}). First error: {first}")
        return EXIT_FAILURE
    _say(f"warning: {counted}; they are left out of the metrics. First error: {first}",
         file=sys.stderr)
    return EXIT_OK


def _custom_fingerprint(args) -> dict:
    from judgekeeper.prompts import load_prompt, prompt_text

    known: dict = {}
    if args.model:
        known["model"] = args.model
    if args.temperature is not None:
        known["temperature"] = args.temperature
    if args.prompt:
        path = Path(args.prompt)
        if not path.is_file():
            raise UsageError(f"prompt file not found: {path}")
        text = prompt_text(path)  # a file that is not UTF-8 stops here, with how to fix it
        try:
            prompt = load_prompt(path)
            known["prompt_hash"], known["rubric_version"] = prompt.prompt_hash, \
                prompt.rubric_version
        except PromptError:  # no frontmatter: hash the file, rubric version unknown
            known["prompt"] = text
    if args.base_url or args.api_key_env:
        raise UsageError("--base-url and --api-key-env apply to the anthropic and openai "
                         "runners only")
    return known


def _judge_custom(args, items, manifest, run_judge) -> int:
    from judgekeeper.custom import (
        CustomRunner,
        check_call_limit,
        count_calls,
        exec_judge,
        load_callable,
        run_custom,
    )
    from judgekeeper.normalise import Normaliser
    from judgekeeper.table import make_fingerprint

    known = _custom_fingerprint(args)
    n_calls = count_calls(items, args.runs)
    orders = " x 2 orders (AB, BA)" if manifest["kind"] == "pairwise" else ""
    print(f"{_count(n_calls, 'judge call', ',')} ({_count(len(items), 'item')} x "
          f"{_count(args.runs, 'run')}{orders})", file=sys.stderr)
    check_call_limit(n_calls, args.yes)
    if args.callable:
        fn = load_callable(args.callable)
        source = {"kind": "callable", "file": None, "metric": args.callable}
        workers = 1  # a user function may not be thread-safe
    else:
        fn = exec_judge(args.exec, timeout=args.timeout)
        source = {"kind": "exec", "file": None, "metric": args.exec}
        workers = max(1, args.workers)
    runner = CustomRunner(fn, Normaliser(manifest["kind"], pass_if=args.pass_if,
                                         label_map=args.label_map),
                          make_fingerprint(known), source)
    files = run_custom(items, runner, args.runs, Path(args.out), manifest["sha256"], run_judge,
                       workers=workers, progress=lambda msg: print(msg, file=sys.stderr))
    return _judge_outcome(files)


def cmd_validate(args) -> int:
    from judgekeeper.html_report import render_html
    from judgekeeper.report import ReportError, build_report

    _seal_new(args.anchors)
    try:
        report = build_report(args.anchors, args.runs)
    except ReportError as e:
        raise UsageError(str(e)) from None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    (out / "report.html").write_text(render_html(report), encoding="utf-8")
    _print_report(report, out)
    return EXIT_OK


def cmd_check(args) -> int:
    from judgekeeper.table import check_table

    report = check_table(args.table, judge=args.judge, human=args.human, id=args.id,
                         run=args.run, input=args.input, output=args.output, reason=args.reason,
                         pass_if=args.pass_if, label_map=args.label_map, out=args.out)
    _print_report(report, Path(args.out))
    return EXIT_OK


_MLFLOW_FLAGS = {"experiment": "--experiment", "run_id": "--run-id",
                 "tracking_uri": "--tracking-uri", "id_from": "--id-from",
                 "temperature": "--temperature"}
_LANGFUSE_FLAGS = {"judge_score": "--judge-score", "human_score": "--human-score",
                   "from_": "--from", "to": "--to", "max_items": "--max-items", "rate": "--rate"}


def _platform_source(args) -> dict | None:
    """The platform reader's options from the flags; usage errors for flags of another tool."""
    for tool, flags in (("mlflow", _MLFLOW_FLAGS), ("langfuse", _LANGFUSE_FLAGS)):
        given = [flag for dest, flag in flags.items() if getattr(args, dest) is not None]
        if given and args.tool != tool:
            raise UsageError(f"{', '.join(given)} apply to `import {tool}` only")
    if args.tool == "mlflow":
        if not args.experiment:
            raise UsageError("import mlflow needs --experiment NAME_OR_ID")
        return {"experiment": args.experiment, "run_ids": args.run_id,
                "tracking_uri": args.tracking_uri, "id_from": args.id_from,
                "temperature": args.temperature}
    if args.tool == "langfuse":
        missing = [f for d, f in (("judge_score", "--judge-score"),
                                  ("human_score", "--human-score")) if not getattr(args, d)]
        if missing:
            raise UsageError(f"import langfuse needs {' and '.join(missing)}")
        source = {k: getattr(args, k) for k in _LANGFUSE_FLAGS}
        if source["rate"] is None:
            del source["rate"]
        return source
    return None


def cmd_import(args) -> int:
    from judgekeeper.readers import import_results

    if args.check:
        from judgekeeper import records_check

        if args.tool != "records":
            raise UsageError("--check applies to `import records` only")
        if not args.paths:
            raise UsageError("`import records --check` needs at least one path")
        return records_check.run(args.paths, column_map=args.map, pass_if=args.pass_if,
                                 label_map=args.label_map, say=lambda line: _say(scrub(line)))
    source = _platform_source(args)
    if source is not None and args.paths:
        raise UsageError(f"`import {args.tool}` reads the platform, not files: drop the "
                         f"path(s) {', '.join(args.paths)}")
    if source is None and not args.paths:
        raise UsageError(f"`import {args.tool}` needs at least one path")
    report = import_results(args.tool, args.paths, metric=args.metric, labels=args.labels,
                            pass_if=args.pass_if, label_map=args.label_map,
                            runs_by_order=args.runs_by_order, id_var=args.id_var,
                            column_map=args.map, out=args.out, anchors_out=args.anchors_out,
                            source=source)
    src = report["source"]
    for w in src.get("warnings") or []:
        _say(f"warning: {scrub(w)}", file=sys.stderr)
    for note in src.get("notes") or []:
        _say(f"note: {scrub(note)}")
    _print_report(report, Path(args.out))
    if args.anchors_out:
        print(f"wrote {args.anchors_out} (frozen): re-judge it with `judgekeeper judge "
              f"{quote_arg(args.anchors_out)} --runs 3 ...` for a noise floor")
    return EXIT_OK


def cmd_start(args) -> int:
    from judgekeeper.start import run

    if args.agent_prompt:
        from judgekeeper.own_format import AGENT_PROMPT

        print(AGENT_PROMPT)
        return 0
    if args.test_pass_mark and not args.fix:
        print("judgekeeper start: error: --test-pass-mark works only with --fix",
              file=sys.stderr)
        return EXIT_USAGE
    return run(args.path, tool=args.tool, metric=args.metric, experiment=args.experiment,
               tracking_uri=args.tracking_uri, pass_if=args.pass_if, label_map=args.label_map, judge_model=args.judge_model,
               yes=args.yes, port=args.port, no_browser=args.no_browser, new=args.new,
               review=args.review, label_more=args.label_more, ask_again=args.ask_again,
               try_new_judge=args.try_new_judge, fix=args.fix,
               test_pass_mark=args.test_pass_mark,
               times=args.times, python=args.python, fields=args.fields,
               judge_command=args.judge_command, allow_calls=args.allow_calls)


def cmd_setup(args) -> int:
    from judgekeeper import setup_project

    return setup_project.run(args.path, yes=args.yes, metric=args.metric,
                             judge_model=args.judge_model)


def cmd_baseline(args) -> int:
    from judgekeeper.gate import load_report

    if args.baseline_command is None:
        raise UsageError("baseline needs an action: set or show")
    path = Path(args.path)
    if args.baseline_command == "set":
        load_report(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.report, path)
        print(f"baseline set: {path} (commit it)")
        return EXIT_OK
    if not path.is_file():
        raise UsageError(f"no baseline at {path}; run `judgekeeper baseline set <report.json>`")
    report = load_report(path)
    fp, h = report["fingerprint"], report["headline"]
    pb = report.get("position_bias")

    def f(x):
        return "n/a" if x is None else f"{x:.2f}"

    print(f"baseline: {path}")
    _say(f"generated: {report.get('generated_at', 'n/a')}")
    print("judge:")
    for k in ("provider", "model", "snapshot", "endpoint", "prompt_hash", "rubric_version",
              "temperature", "created_at"):
        _say(f"  {k}: {fp.get(k)}")
    _say(f"anchors: {report['anchors'].get('file', '')} sha256 {report['anchors']['sha256']}")
    _say(f"runs: {report['n_runs']}")
    print(f"kappa: {f(h.get('kappa_mean'))} (runs {f(h.get('kappa_min'))} to "
          f"{f(h.get('kappa_max'))})")
    print(f"TPR: {f(h.get('tpr_mean'))}  TNR: {f(h.get('tnr_mean'))}")
    if pb:
        print(f"AB/BA disagreement: {f(pb.get('inconsistency_rate'))}")
    return EXIT_OK


def cmd_gate(args) -> int:
    from judgekeeper.gate import exit_code, render_markdown, run_gate

    result = run_gate(args.report, baseline=args.baseline, config=args.config,
                      allow_judge_change=args.allow_judge_change,
                      require_fingerprint=args.require_fingerprint)
    code = exit_code(result["status"], args.flaky_as)
    baseline_path = result["baseline_path"]
    result = {**result, "exit_code": code}

    out = Path(args.out) if args.out else Path(args.report).parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "gate.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    (out / "gate.md").write_text(render_markdown(result), encoding="utf-8")
    _say(f"{result['status']}: {result['reason']}")
    for w in result["warnings"]:
        _say(f"  warning: {w}")
    if baseline_path is None:
        print("  no baseline: absolute thresholds only")
    print(f"wrote {out / 'gate.json'} and {out / 'gate.md'} (exit {code})")
    return code


def _config(args, loader, default):
    if args.config:
        return loader(args.config)
    if DEFAULT_CONFIG.is_file():
        return loader(DEFAULT_CONFIG)
    return default


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_migrate(args) -> int:
    from judgekeeper.migrate import FAIL_ON, MigrateConfig, audit_path, compare, load_config
    from judgekeeper.migrate import render_html as render_migration

    config = _config(args, load_config, MigrateConfig())
    try:
        migration, _, new_report = compare(args.anchors, args.old_runs, args.new_runs, config)
    except ReportError as e:
        raise UsageError(str(e)) from None
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "migration.json", migration)
    (out / "migration.html").write_text(render_migration(migration), encoding="utf-8")
    _say(f"{migration['status']}: {scrub(migration['verdict'])}")
    print(f"wrote {out / 'migration.json'} and {out / 'migration.html'}")
    if args.rebase:
        baseline = Path(args.baseline)
        audit_dir = baseline.parent / "migrations"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit = audit_path(migration, audit_dir)
        _write_json(baseline, new_report)
        _write_json(audit, migration)
        print(f"baseline set to the new judge: {baseline}; audit trail: {audit} (commit both)")
    if args.fail_on and migration["status"] in FAIL_ON[args.fail_on]:
        return EXIT_FAILURE
    return EXIT_OK


COMMANDS = {"init": cmd_init, "judge": cmd_judge, "validate": cmd_validate,
            "baseline": cmd_baseline, "gate": cmd_gate, "migrate": cmd_migrate,
            "check": cmd_check, "import": cmd_import, "start": cmd_start, "setup": cmd_setup}


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    lenient_streams()  # a terminal that cannot show a character prints "?", never a crash
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
    except AnchorHashMismatch as e:
        _error(str(e))
        return EXIT_HASH_MISMATCH
    except (UsageError, AnchorError, PromptError, JudgmentsError, GateError, MigrateError,
            NormaliseError, TableError, CallableError, CallLimitError,
            LabelError, StartError, SettingsError, MapError) as e:
        _error(str(e))
        return EXIT_USAGE
    except LangfuseError as e:
        if args.debug:
            _say(scrub(traceback.format_exc()), file=sys.stderr, end="")
        _error(str(e))
        return EXIT_FAILURE
    except Exception as e:  # noqa: BLE001 - the last line of defence for what users see
        if args.debug:
            _say(scrub(traceback.format_exc()), file=sys.stderr, end="")
        file_problem = describe_os_error(e) if isinstance(e, OSError) else None
        if file_problem:
            _error(file_problem)
            return EXIT_USAGE
        _error(f"{e}" if isinstance(e, JudgeCallError) else f"{type(e).__name__}: {e}")
        if not args.debug:
            print("  run with --debug for the traceback", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
