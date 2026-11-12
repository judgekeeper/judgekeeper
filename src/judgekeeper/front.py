"""`judgekeeper` with no command does the next step; what is in the project decides which.
What it does in each case is the table in docs/reference.md ("judgekeeper: find, mark,
measure"). `judgekeeper mark` (mark.py) goes through the same steps for marking more.

A new eval run does not start over: the answers being marked stay in .judgekeeper/pool.jsonl,
and marks are tests for the LLM-as-a-judge, not for one results file. Only another
LLM-as-a-judge or --new starts over.

A person and a coding agent read the same output, and the agent follows the one `Next:` line.
So the output holds counts, names, paths and the rule, never an answer's or an input's text,
and `Next:` names only judgekeeper's commands or the person's eval tool. Without a terminal, a
choice prints the flag that answers it and exits 3; a yes/no question is noted, the run goes
on as if yes but writes nothing, and `--yes` then answers exactly those questions.
No AI call and no key. Exit codes: 0 done, 3 the person is needed, 2 usage error, 130 Ctrl-C.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import (
    __version__,
    background,
    batches,
    find,
    judge_check,
    judge_setup,
    marks,
    no_grades,
    own_format,
    page,
    project,
    report_page,
    settings,
    start,
    start_fix_rule,
    start_label,
    targets,
    textio,
)
from judgekeeper import labels as labels_mod
from judgekeeper.fingerprint import rule_hash
from judgekeeper.label import DEFAULT_PORT, is_open, is_page, read_lock
from judgekeeper.links import link
from judgekeeper.mark_page import SEE_FIRST, SEE_READY
from judgekeeper.normalise import NormaliseError, _numeric, parse_pass_if
from judgekeeper.records import RecordsError
from judgekeeper.redact import scrub, scrub_fingerprint
from judgekeeper.start import EXIT_QUESTION, StartError, Stop
from judgekeeper.start_label import FOLDER, StartSession, Workspace, made_lines, shown_folder
from judgekeeper.textio import (
    kept_at,
    kept_path,
    old_hook,
    percent,
    plural,
    program,
    quote_arg,
    wrap,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NEEDS_YOU = 3
FIRST_SHOWN = 26  # characters of the first rule shown when they differ per test
RULE_SHOWN = 58  # characters of the judge's rule shown, "…" included, on one line
VALUE_WIDTH = 40  # characters of a judge's decision value shown
PASS_IF = '"score>=N"'  # the placeholder of --pass-if in a Next: line; quoted for every shell
# With no terminal to ask in, a pass mark measured before (the Next line gives the command)
PASS_MARK_AGAIN = ("Your pass mark is {rule}. Without a terminal, judgekeeper can't ask for it, "
                   "so give it with --pass-if.")
LABEL_MAP = '"VALUE=pass,VALUE=fail,VALUE=error"'
SAVE = "Save your answers in judgekeeper.toml, so judgekeeper does not ask again?"
GO_TO_PROJECT = ("judgekeeper reads eval results in your project folder. Go to it (`cd <your "
                 "project folder>`), then run `{command}` there.")
SAVE_MAP = ("Save how to read {file} in judgekeeper.toml? judgekeeper reads it from there "
            "from now on.")
QUESTIONS = "judgekeeper needs your answer to {which}:"
# Questions whose answer changes what is counted: the counts are printed after them
COUNT_QUESTIONS = ("Count each as its own answer?", "Leave them out?")
READS = ("judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV, "
         "TSV or JSONL file with input and output columns, and a verdict column if an "
         "LLM-as-a-judge graded them.")
# No results and no eval tool: a prompt for the person's coding agent to make answers to check.
# Each of its lines starts a line of its own, wrapped as every other line.
QUESTIONS_NEXT = "paste the prompt above into your coding agent, then run `{command}` again."
FOLDER_ABOVE = "Results in the folder above? Run `{command}`."  # after the prompt
THIS_FOLDER = "This folder already holds your judgekeeper session ({marks})."  # run from below
SAVED_SETUP = "judgekeeper saved your LLM-as-a-judge's setup in {folder}/judge.json."
FOLDERS_ABOVE = "Results in a folder above? Run `{command}`."  # more than one level up
QUESTIONS_INTRO = ("No answers yet? Paste this into your coding agent (Claude Code, Cursor or "
                   "Codex):")
QUESTIONS_PROMPT = (
    "Read this project and list what its AI is meant to do (its prompt and the tasks it "
    "handles).\n"
    "Write about 40 test questions the way its real users would ask them: cover every task, "
    "and make about half of them hard (missing details, out of scope, against the AI's own "
    "rules, a wrong premise, or more than one step). No near-duplicates.\n"
    "Show me the questions as a numbered table (question, the task it tests, normal or hard) "
    "and wait for my yes. I may edit or drop any.\n"
    "Then run the AI on each question and save the questions and answers in results.csv, with "
    "two columns: input (the question) and output (the answer). Do not grade the answers. "
    "Then run {program}.")
QUESTIONS_KEY = "Running your AI may use your API key."
# The options that find the judge, as start.find_judge takes them
FIND = ("tool", "metric", "experiment", "tracking_uri", "pass_if", "label_map", "judge_model")
ASKED = {"--tool": "tool", "--metric": "metric", "--experiment": "experiment"}
START_OVER = f"Start over with these results? Your old marks move to {FOLDER}/previous-<date>/."
OLD_MARKS = (f"{FOLDER}/labels.csv holds marks from an older judgekeeper. They have no time "
             "stamps, so this version does not use them.")
SCORE_READ = "Read the score column with your pass mark; the verdict column is not used."
# New results with no new answers: the same answers graded again (a regrade, or an eval run
# that gave the same answers)
RAN_AGAIN = ("Your answers were graded again. Your LLM-as-a-judge is the same, so your marks "
             "still test it.")
RAN_AGAIN_CHECKED = ("Your answers were graded again. Your LLM-as-a-judge is the one your last "
                     "check re-tested, so your marks still test it.")
RAN_AGAIN_KEPT = ("Your answers were graded again. Your LLM-as-a-judge is the one you had before "
                  "your last check, so your marks still test it.")  # that check found it worse
JUDGE_CHANGED = "Your LLM-as-a-judge changed since your marks: {what}."
NEWEST = "Reading {file}, the newest results here."
# Newer results whose grades only `check` takes on: the numbers keep the ones the marks were
# checked with. Graded again (the same model and rule, or a table): which, and the check
REGRADED = ("Your answers were graded again in {file}, and {k} of your marked answers got a "
            "different grade. {numbers}. To compare, run `{command}`.")
# ...after a check found them worse (a "Worse" kept the marks on the grades before), any judge
HELD_WORSE = "Your last check found your LLM-as-a-judge in {file} worse, so {numbers}."
NUMBERS_IN = "the numbers below still use the grades in {old}"
NUMBERS_BEFORE = "the numbers below still use the grades from before"  # that file graded again
NO_GRADES_HERE = "It has no Pass or Fail grades, so {numbers}."  # the newest results file
READING = "Reading {file}."  # back to a file older than the last one read
# A check took on the LLM-as-a-judge of a file elsewhere; the results here are older
CHECKED_FILE = "This result is about your LLM-as-a-judge in {file}, the file your last check read."
MODEL_WRITTEN = "Your LLM-as-a-judge's model is written down now: {model}."
WORSE_LAST = "Your last check found your LLM-as-a-judge in your newest results worse than this one."
DEFAULT_GRADER = "promptfoo's default grader (no model written in your config)"
DEFAULT_GRADER_NOTE = "came from promptfoo's default grader"  # readers.promptfoo's warning
STEP = "Step {n} of 5: {name}"
# Which path judgekeeper takes and why, and how to switch: once a run (path_lines)
PATH_NO_GRADES = ("{file} has no LLM-as-a-judge grades, so judgekeeper checks your AI's "
                  "answers: you mark each one Pass or Fail.")
PATH_TO_GRADES = ("Have an LLM-as-a-judge? Save its Pass or Fail in a verdict column, or run it "
                  "with promptfoo, DeepEval, Inspect AI or MLflow.")
PATH_GRADES = ("{file} has LLM-as-a-judge grades, so judgekeeper checks your LLM-as-a-judge "
               "against your marks.")
PATH_TABLE_TO_ANSWERS = ("To check your AI's answers instead, use a copy of the file without "
                         "the verdict column.")
PATH_TOOL_TO_ANSWERS = ("To check your AI's answers instead, save them in a CSV file with input "
                        "and output columns and no verdict column.")
INDENT = " " * 17  # under the value of "LLM-as-a-judge:  "
EVERY_ANSWER = "your LLM-as-a-judge gave every answer a clear Pass or Fail."
FREE_CHECK = "Checked: "  # every free-check line starts with it
# Said where marking starts, before the page opens (and in the README and the reference)
NEEDS_EACH_KIND = ("A result needs at least {n} Pass and {n} Fail marks from you. It also needs "
                   "{g} marks on answers your LLM-as-a-judge passed and {g} on answers it "
                   "failed (or all of them, if there are fewer).")
# ...and when the LLM-as-a-judge failed under FEW_FAILS of the answers: how many marks that takes
# depends on how many of its fails the person fails too, so no number is said
FEW_FAILS = 0.10
# ...and when it gave every answer the same grade: one mark the other way is the result
ONE_GRADE = ("Your LLM-as-a-judge said {said} on every answer. Your result comes as soon as you "
             "mark one answer {other}.")
FINDING = "finding {n} answers you mark Fail can take many marks."
FINDING_FAILS = "Your LLM-as-a-judge failed only {f} of {answers} answers, so " + FINDING
# ...unless too few answers are left to mark to reach them
FAILS_OUT_OF_REACH = ("Only {left} left to mark, not enough to reach {n} {side} marks, so run "
                      "your eval on more questions.")
FAILED_ONLY = "Your LLM-as-a-judge failed only "  # how Find's note on few fails starts (_notes)
SHOWS = ("It shows the answers one at a time. Mark each one Pass or Fail, the way you want your "
         "LLM-as-a-judge to decide. Your LLM-as-a-judge's grade stays hidden.")
BAR = "The bar at the top fills as you mark."
PRECISE = "Each new mark makes your numbers more precise."
NOT_ENOUGH = "That's not enough for a result yet."
GROUP_MARKS = "You marked {marked}. A result needs {need}."
GROUP_ALL = "Your LLM-as-a-judge {word} only {n} answers, so a result needs your marks on all {n}."
GROUP_ONE = "Your LLM-as-a-judge {word} only 1 answer, so a result needs your mark on it."
NEXT_MARK = (f'mark answers on the page until a "{SEE_FIRST}" link appears, then click '
             "it.")  # a terminal has no link at the top: the page's link by its own words
NEXT_MORE = "mark more answers, then run `{command}` to see your updated result."
# answers with no grade (no_grades.py): the page's link once there is a result, no LLM-as-a-judge
NEXT_ANSWERS = f'mark answers on the page until a "{SEE_READY}" link appears, then click it.'
SHOWS_ANSWERS = "It shows the answers one at a time. Mark each one Pass or Fail."
# ...fewer answers than a first result needs (start.MIN_POOL): as Find says it
NEXT_FEW_ANSWERS = ("mark your {n} answers on the page. Your marks are kept for when more "
                    "answers come. A first result needs at least {min} answers, so then run your "
                    "eval to make more answers (that makes model calls), and run `{command}` "
                    "again.")
NEXT_CHECK = "run `{command}` to re-check your changed LLM-as-a-judge on your marks."
NEXT_COMPARE = "run `{command}` to compare the new grades with your marks."  # after REGRADED
NEXT_RESULT = ("nothing to do. When you change your LLM-as-a-judge or update your eval tool, run "
               "`{command}`.")
NEXT_FIX = "to improve your LLM-as-a-judge's rule, run `{command}`."
NEXT_CONTINUE = "run `{command}` when you want to continue."
PORT_KEPT = "The marking page is already open on port {port}, so --port {asked} was not used."
STILL_OPEN = ("The marking page is still open. Mark more answers to make these ranges "
              "narrower, so the numbers are more certain.")
AGREES = "How often your LLM-as-a-judge agrees with you (estimates):"
KAPPA_LINE = "Kappa (agreement beyond coincidence): {value}. It never decides the result."
NEXT_MARK_MORE = "run `{command}` to mark more answers."
FAILED_REMOVED = "No answer you marked Fail is listed now, so judgekeeper removed {path}."
PAGE_CLOSED = ("The marking page that was open is closed now: it showed your answers from "
               "before. To open it again, run `{command}`.")  # a result after new answers
MARK_ANY_TIME = "To mark more answers at any time, run `{command}`."
SAY_WHY = "Where you and your LLM-as-a-judge disagree, say why. `fix` uses your reasons."
RESULT_OPEN = "Your result page is open in your browser."
CHANGE_MARK = "To change a mark, click it in the list."  # every answer marked (mark_page too)
CHANGE_ON_RESULT = 'To change a mark, open the page and click "Change a mark".'  # its link
IN_BROWSER = "The marking page is already running."  # no new tab for it; a first run with
# --no-browser opened none, so "in your browser" could be false
CLOSED_IT = "Need its link? Run `{command}` to print it."  # no terminal: no link
COULD_NOT = "run `{command}` in your own terminal (it keeps the page open there)."
PORT_TAKEN = "Port {port} is in use, so the marking page could not start."
PORT_PAGE = "Port {port} is in use by judgekeeper's marking page for another project."
NEXT_STOP_THERE = "run `{stop}` there, or `{command}`."
NEXT_ANY_PORT = "run `{command}` (it opens the page on any free port)."
# A tool found here with no saved results: what saves them
SAVES = {"deepeval": "DeepEval saves results only when you run deepeval test run or evaluate().",
         "inspect": "Inspect AI saves its logs in logs/ when you run inspect eval.",
         "mlflow": "MLflow keeps the LLM-as-a-judge's assessments once mlflow.genai.evaluate() "
                   "runs."}
OTHERS = 3  # other projects named when run from a folder that holds several
FILE_TOOLS = ("table", "promptfoo", "deepeval", "inspect")  # each results file is one run
FEW_SHARE = 0.2  # a side under this share of the answers: the judge may pass (fail) too much
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class FrontTalk(start.Talk):
    """start.Talk for `judgekeeper`: printed commands start `judgekeeper`. Without a
    terminal a choice ends in a `Next:` line (stop), and a yes/no question is noted."""

    subcommand = ""
    asks_everything = True
    screens = True  # start.py says some things in this command's own words

    def __init__(self, yes: bool, path: str | Path, options: dict, new: bool = False):
        self.options = dict(options)  # the flags given, and answers given as flags
        self.new = new  # repeated while starting over is asked about
        super().__init__(yes=yes, path=path)
        self.answers: dict[str, str] = {}  # what the person chose at a terminal: flag -> value
        self.store: str | None = None  # the MLflow store chosen at a terminal
        self.noted: list[str] = []  # yes/no questions taken as yes without a terminal
        self.step: str | None = None  # said before the first line, when there is one (go)
        self.find_said = False  # "Step 1 of 5: Find" was said in this run
        self.path_said = False  # path_lines were said in this run
        self.switched: str | None = None  # _switched_line, said once
        self.found: start.Found | None = None  # the results read, for path_lines
        self.path_head: list[str] = []  # path_lines in a step's head lines (_path_first)
        # --labels (never repeated in a command): a file's name or labels.IN_RESULTS; then the
        # labels read, and where from (marks.jsonl's "from")
        self.labels: str | None = None
        self.labels_read: list | None = None
        self.labels_from: str | None = None
        self.few_fails = False  # Find said how few answers the LLM-as-a-judge failed
        self.held: list[str] | None = None  # Find's Excel notes, said once a labels file is read
        self.left_below: list[str] = []  # projects below whose files were left out (_tool_below)
        self.refresh()

    def refresh(self) -> None:
        """The printed commands repeat the options as they are now, never --yes: it answers
        only the questions printed in the run just before (ask_noted)."""
        self.flags = start.repeated_flags(self.path, **self.options)
        if self.path == "." and self.given:  # typed: this folder is the project, never above
            self.flags = (".", *self.flags)
        if self.new:
            self.flags = (*self.flags, "--new")

    def set(self, name: str, value) -> None:
        self.options[name] = value
        self.refresh()

    def command(self, *extra: str) -> str:
        """start.Talk.command; a --label-map in `extra` adds to the person's own map."""
        return super().command(*_with_given_map(self.options.get("label_map"), extra))

    def command_at(self, where: str | Path, *extra: str) -> str:
        return super().command_at(where, *_with_given_map(self.options.get("label_map"), extra))

    def command_in(self, folder: str, *extra: str) -> str:
        return super().command_in(folder, *_with_given_map(self.options.get("label_map"), extra))

    def looking(self, root: Path) -> None:
        """Said only when nothing is found."""

    def remember(self, flag: str, chosen: str, line: str | None = None) -> None:
        if flag == "PATH":
            self.store = chosen
        self.answers[flag] = chosen

    def choose(self, title, options, flag_hint, ask="Which one?", flag=None, values=(),
               what=None, keep=0) -> int:
        if start._interactive():
            return super().choose(title, options, flag_hint, ask, flag=flag, values=values,
                                  keep=keep)
        self.say(title)
        left = len(options) - keep - start.LIST_LIMIT
        for option in options[:start.LIST_LIMIT] if left > 0 else options:
            self.say(f"  {option}")
        if left > 0:
            self.say(f"  {start.more(left)}")
            for option in options[len(options) - keep:]:
                self.say(f"  {option}")
        if flag is None:
            raise self.stop(EXIT_QUESTION, f"run `{self.command()}` in a terminal, to answer "
                                           "there.")
        names = ", ".join(start.shown_name(str(v), quoted=True) if flag == "--metric"
                          else f"table for {find.NAMES['table']}"
                          if flag == "--tool" and v == "table"  # a CSV file: never a "table"
                          else quote_arg(str(v)) for v in values)
        if len(values) - keep > start.LIST_LIMIT:  # the list above holds the first ones; the
            # kept last options ("All, one at a time") are choices, not names
            names = f"{start.LIST_LIMIT} of the {len(values) - keep:,} are listed above"
        if flag == "PATH":
            commands = [f"`{self.command_at(v)}`" for v in values]
            then = start.some(commands)
        elif any(str(v).startswith("-") for v in values):  # argparse reads `--metric --yes`
            then = f"`{self.command(f'{flag}=NAME')}`"  # as two flags
        else:
            then = f"`{self.command(flag, 'NAME')}`"
        raise self.stop(EXIT_QUESTION, f"choose {what} ({names}), then run {then}.")

    def confirm(self, question, default, hint, with_yes) -> bool:
        if start._interactive():
            return super().confirm(question, default, hint, with_yes)
        if not self.yes:  # with --yes, the person said yes to it: it was printed last run
            self.noted.append(question)
        return True

    def counts_wait(self) -> bool:
        """Whether a noted question changes the counts (how many answers, which are left
        out): then the counts are printed only once it is answered."""
        return any(q.endswith(COUNT_QUESTIONS) for q in self.noted)

    def ask_noted(self) -> None:
        """The yes/no questions noted on the way, as one list, before anything is written."""
        if not self.noted:
            return
        self.say()
        one = len(self.noted) == 1
        self.say(QUESTIONS.format(which="this question" if one
                                  else f"these {len(self.noted)} questions"))
        for n, question in enumerate(self.noted, 1):
            for i, line in enumerate(wrap(question, indent="     ")):
                self.say(f"  {n}. {line.lstrip()}" if i == 0 else line)
        keep = self.labels_flags()  # the answer reads the same labels
        yes, again = f"`{self.command(*keep, '--yes')}`", f"`{self.command(*keep)}`"
        raise self.stop(EXIT_QUESTION, f"run {again} in a terminal to answer, or {yes} to say "
                                       f"yes{'' if one else ' to all'}.")

    def labels_flags(self) -> tuple[str, ...]:
        """--labels as it was given, for a command that answers a question about this run."""
        if self.labels is None:
            return ()
        if self.labels == labels_mod.IN_RESULTS:
            return ("--labels",)
        return ("--labels", start.path_word(self.labels))

    def say(self, text: str = "") -> None:
        if text:  # Find says something: under its step label
            self.say_step()
        super().say(text)

    def say_step(self) -> None:
        """The step label waiting to be said (`step`), once, before Find's first line."""
        if self.step is not None:
            step, self.step = self.step, None
            super().say(step)
            super().say()
            self.find_said = self.find_said or step == STEP.format(n=1, name="Find")

    def para(self, text: str = "", indent: str = "") -> None:
        """Say `text` wrapped (textio.wrap)."""
        for line in wrap(text, indent=indent):
            self.say(line)

    def stop(self, code: int, next_step: str | None = None, as_given: bool = False) -> Stop:
        """Say the Next: line; exit 3 when it asks for something, 0 when it is nothing, or
        `code` itself (`as_given`: a file it can't read is a usage error, 2)."""
        if next_step:
            self.say()
            self.para(f"Next: {next_step}")
            if as_given:
                return Stop(code)
            return Stop(EXIT_OK if next_step.startswith("nothing") else EXIT_NEEDS_YOU)
        return Stop(EXIT_NEEDS_YOU if code == EXIT_QUESTION else code)


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, tracking_uri: str | None = None,
        pass_if: str | None = None, label_map: str | None = None,
        judge_model: str | None = None, yes: bool = False,
        port: int = DEFAULT_PORT, no_browser: bool = False, new: bool = False,
        wait: bool = False, stop: bool = False, labels: str | None = None,
        given: bool = False) -> int:
    """`judgekeeper`. Returns the exit code. `labels`: --labels, a file's name or
    labels.IN_RESULTS. `given`: the PATH was given on the command line (Talk.given)."""
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model, "port": port,
               "no_browser": no_browser}
    talk = FrontTalk(yes=yes, path=path, options=options, new=new)
    talk.labels, talk.given = labels, given
    talk.refresh()
    return go(talk, Path(path), wait=wait, stop=stop, marking=False)


def go(talk: FrontTalk, path: Path, wait: bool, stop: bool, marking: bool) -> int:
    """`judgekeeper`, or (`marking`) `judgekeeper mark`. Returns the exit code."""
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    hook = old_hook(path)
    if hook:
        talk.para(hook)
        talk.say()
    try:
        if stop:
            return _stop(talk, path)
        uri = str(talk.options.get("tracking_uri") or "")
        if not path.exists() and not uri.startswith(start.SERVERS):
            raise not_found(path, talk.path)  # no step ran: the error alone
        if talk.labels is not None or not marking and not _started(path):  # an import
            talk.say(STEP.format(n=1, name="Find"))  # always says something: Find, now
            talk.say()
            talk.find_said = True
        else:  # said only when Find has something to say (a file left out, an error)
            talk.step = STEP.format(n=1, name="Find")
        from judgekeeper.check import texts_once

        try:
            with texts_once():  # a run matches and scrubs the same texts many times
                return _run(talk, path, wait, marking)
        except Exception:
            talk.say_step()  # the error cli.py prints comes under Step 1 too
            raise
    except Stop as e:
        return EXIT_NEEDS_YOU if e.code == EXIT_QUESTION else e.code


def _started(path: Path) -> bool:
    """Whether marking started in the project at `path` (a labels.csv file counts too)."""
    if not path.exists():
        return False
    ws = Workspace(project.project_of(path))
    return ws.start.is_file() or ws.labels.is_file()


# Finding -----------------------------------------------------------------------------------

def _run(talk: FrontTalk, path: Path, wait: bool, marking: bool) -> int:
    given = _labels_file(talk)  # a folder, an Excel file, no file: said before any search
    if path.is_dir() and textio.above_projects(path):  # a search would walk home folders
        talk.para(GO_TO_PROJECT.format(command=program()))
        return EXIT_NEEDS_YOU
    talk.held = [] if given is not None else None  # never above a stop about the labels
    found, mapped = find_found(talk, path)  # anything it says comes under Step 1's label
    _read_labels(talk, found, given)  # nothing is written before the labels are read
    for note in talk.held or ():
        talk.para(note)
    talk.held = None
    talk.step = None
    ws = Workspace(found.root)
    if not found.graded:  # answers with no grade: the person marks each, no LLM-as-a-judge
        return _no_grades(talk, ws, found, wait, marking)
    if no_grades.here(ws):  # a grade column added since: the marks are used as they are
        with page.one_at_a_time(ws.dir, talk.say):
            no_grades.to_graded(ws, found)
    if not marking and not ws.start.is_file() and not ws.labels.is_file():
        return _say(talk, found, mapped, wait)
    if not marking and _find_anew(talk, ws, found):
        return _say(talk, found, mapped, wait)
    return _go_on(talk, found, mapped, wait, marking)


def _find_anew(talk: FrontTalk, ws: Workspace, found: start.Found) -> bool:
    """Nothing is marked yet and the judge is set up otherwise (another --pass-if, say):
    the saved answers move aside, asking nothing, and Find starts again with these flags.
    Returns whether it did."""
    if talk.new or _has_marks(ws) or _why_start_over(talk, ws, found) is None:
        return False
    if is_open(ws.dir):
        background.stop(ws.dir)
    _move_aside(talk, ws)
    if not talk.find_said:  # Find's label once per run
        talk.say(STEP.format(n=1, name="Find"))
        talk.say()
    return True


def _move_aside(talk: FrontTalk, ws: Workspace) -> None:
    """The saved answers move to previous-<date>/; a line, then a blank one, when marks
    moved."""
    said: list[str] = []
    project.move_to_previous(ws, said.append)
    for line in said:
        talk.say(line)
    if said:
        talk.say()  # a blank line before the step header, as everywhere


def _labels_stop(talk: FrontTalk, e: labels_mod.LabelsStop) -> Stop:
    """Why the labels can't be used (exit 3): nothing was written."""
    _say_lines(talk, e.lines)
    if e.next_step:
        talk.say()
    return talk.stop(EXIT_QUESTION, e.next_step)


def _say_lines(talk: FrontTalk, lines: list[str]) -> None:
    """Lines of labels.py, those that start with two spaces indented."""
    for line in lines:
        if line.startswith("  "):
            talk.para(line[2:], indent="  ")
        else:
            talk.para(line)


def _labels_file(talk: FrontTalk) -> Path | None:
    """The labels file --labels names, checked before the results are looked for."""
    if talk.labels is None or talk.labels == labels_mod.IN_RESULTS:
        return None
    try:
        return labels_mod.check_file(talk.labels, talk.command, talk.command_in)
    except labels_mod.LabelsStop as e:
        raise _labels_stop(talk, e) from None


def _read_labels(talk: FrontTalk, found: start.Found, path: Path | None) -> None:
    """The labels --labels asks for, read (with the project's label map) before anything is
    written: a word that isn't Pass or Fail stops here."""
    if talk.labels is None:
        return
    mine = talk.options["label_map"] or _kept_label_map(found.root)  # the person's own map
    command = talk.command
    if talk.options["label_map"] is None and isinstance(mine, str):  # saved by an earlier run:
        def command(*extra: str) -> str:  # a --label-map in a Next line adds to it, as typed
            return talk.command(*_with_given_map(mine, extra))
    try:
        if path is None:
            talk.labels_read = labels_mod.in_results(found.pool, found.metric, command, mine)
            talk.labels_from = marks.FROM_RESULTS
        else:
            start._read_anyway(talk, path, ("--labels", textio.quote_arg(talk.labels)))
            talk.labels_read = labels_mod.read_file(path, found.pool.label_map, mine,
                                                    command, talk.labels)
            talk.labels_from = path.name
    except labels_mod.LabelsStop as e:
        raise _labels_stop(talk, e) from None


def _unmarked_newest(ws: Workspace, session: StartSession) -> int:
    """How many answers of the newest batch have no mark: those --labels did not mark."""
    batch = batches.of(ws.data())
    newest = max(batch.values(), default=1)
    marked = session.marked()
    return sum(b == newest and i not in marked for i, b in batch.items())


def _import_labels(talk: FrontTalk, ws: Workspace, found: start.Found, first: bool) -> None:
    """The labels read (_read_labels) as marks, once the pool is ready: said under Find."""
    if talk.labels_read is None:
        return
    rows = start_label.StartSession(ws).raw
    data = ws.data()
    plan = labels_mod.match(talk.labels_read, rows, data["queue"], found.pool.left,
                            data.get("left"))
    if (stop := labels_mod.nothing_added(plan, talk.labels_from)) is not None:
        raise _labels_stop(talk, stop)
    added = labels_mod.add(ws, plan, talk.labels_from)
    _say_lines(talk, labels_mod.said(added, plan, talk.labels_from))
    talk.say()
    talk.labels_read = None  # once


def find_found(talk: FrontTalk, path: Path) -> tuple[start.Found, settings.StartSettings | None]:
    """(the judge found, the [start] table of an own-format file mapped now or None), asking
    what must be asked; `judgekeeper mark` finds the same way."""
    uri = talk.options["tracking_uri"]
    if uri is not None and str(uri).startswith(start.SERVERS):
        raise _tracking_server(talk, path, str(uri))
    if not path.exists():
        raise not_found(path, talk.path)
    asked, path = path, _remembered(talk, path)  # a folder given stays the project
    if _sent_below(path):  # never a second session above one, nor one above's for them:
        # results in a folder with its own session belong to it
        sessions = _sessions_below(path, judged=True)
        raise _go_to(talk, [(_from_here(path, [n])[0], k) for n, k in sessions])
    held = _saved_marks(path) or _session_in(project.project_of(path))  # never sent below
    if path.is_dir() and not project.is_project(path) and not held and (
            folders := _projects_below(path)):  # nor one session for several projects
        raise _checked_there(talk, _from_here(path, folders))
    if path.is_dir() and not held and (folders := _beside_a_session(path)):
        raise _go_to_one(talk, _from_here(path, folders))  # a session below never joins
        # other results here
    only, talk.left_below = None, []  # the files in no project below, never a project's
    if path.is_dir() and not project.is_project(path) and not held and (
            tool := _tool_read(talk, path)):  # a session here keeps to its files
        owners, rest = _tool_below(path, tool)
        if owners and not rest:
            raise _checked_there(talk, _from_here(path, owners))
        if owners and rest:
            only, talk.left_below = rest, _from_here(path, owners)
    if path.is_file() and (owner := _session_owning(path)) is not None:
        # its own project's answers, never a batch here
        talk.para(_nested_line([owner], Path.cwd()))
        raise talk.stop(EXIT_QUESTION, run_there([owner], Path.cwd()))
    store = project.project_of(asked)
    if path.is_file() and (marked := project.other_eval(store, path)) is not None:
        line, step = project.other_eval_stop(path, marked)  # never read, marked or set apart
        talk.para(line)
        raise talk.stop(EXIT_QUESTION, step)
    if not asked.is_file():  # the marked file is read still: why not the other
        for other, marked in project.others_beside(store):
            talk.para(project.other_eval_line(other, marked))
            talk.say()
    if (read := _project_reads(path, store)) != path:  # the project above's, as before
        path, only, talk.left_below = read, None, []
    where, saved = _own_format(talk, path)
    found = _find(talk, where, saved, only)
    found = _marked_files(talk, where, saved, found)
    root = project.project_of(asked)  # its remembered file is read from there
    if path.is_file() or find.is_mlflow_folder(path):  # read there; kept in the project
        found = start.rebased(found, root)
        _folder_chosen(talk, found, path.resolve().parent)
    elif root != path.resolve() and _log_folder_of(root, found):  # in the marked project
        found = start.rebased(found, root, path)
        _folder_chosen(talk, found, path.resolve())
    return found, saved


def _project_reads(path: Path, store: Path) -> Path:
    """Where a run from `path` reads: the project folder `store` when `path` is a folder below
    it with the results its marks are on, as if run there, so no second session starts. A
    folder of logs is the project's choice of folder (_log_folder_of), and a folder with no
    results reads the project above and says so (start._locate)."""
    if not path.is_dir() or find.is_mlflow_folder(path) or store == path.resolve():
        return path
    if (tool := project.session_tool(store)) is None:
        return path
    search = find.search(path)
    if tool in ("deepeval", "inspect") or not any(search.readable(t) for t in find.TOOLS):
        return path
    return store


def _log_folder_of(root: Path, found: start.Found) -> bool:
    """Whether `found` is read from a folder of logs (DeepEval, Inspect AI) of the eval tool the
    project in `root` marks: the project's choice of folder, not a project of its own."""
    from judgekeeper import start_label

    if found.tool not in ("deepeval", "inspect"):
        return False
    try:
        data = json.loads(start_label.Workspace(root).start.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return False
    return isinstance(data, dict) and data.get("tool") == found.tool


def _folder_chosen(talk: FrontTalk, found: start.Found, folder: Path) -> None:
    """A PATH in the project that picks one of the folders its DeepEval results (or Inspect
    logs) are in: kept in judgekeeper.toml after a yes, as when it is chosen at a terminal,
    so plain commands stop asking (`judgekeeper mark` never saves it)."""
    if found.tool not in ("deepeval", "inspect") or talk.store is not None or talk.subcommand:
        return
    rel = folder.relative_to(found.root).as_posix() if folder.is_relative_to(found.root) else None
    try:
        kept = settings.load(found.root)
    except settings.SettingsError:
        return  # said when it is read
    if kept is not None and (kept.source, kept.file) == (found.tool, rel):
        return
    search = find.search(found.root)
    folders = {start._eval_folder(r) for r in search.readable(found.tool)} - {None}
    if len(folders) > 1 and rel in folders:
        talk.remember("PATH", rel)


def install_switch(files: list[str], used: list[str], can_read_eval: bool) -> str | None:
    """Why the files read differ from the ones the marks were made on (`files`), when only
    the install changed: "keep" when the extra arrived and .eval logs now stand in for the
    .json logs marked (read the same logs instead); "cant" when the marks are on .eval logs
    this install can't read; None otherwise (the same files, or a new run)."""
    if not files or set(files) == set(used):
        return None
    evals = [f for f in files if f.lower().endswith(".eval")]
    if evals and not can_read_eval:
        return "cant"
    if not evals and any(f.lower().endswith(".eval") for f in used) and all(
            f.lower().endswith(".json") for f in files):
        return "keep"
    return None


def _marked_files(talk: FrontTalk, path: Path, saved, found: start.Found) -> start.Found:
    """The results files the marks were made on win over the install's choice: an install
    that gained the Inspect extra reads the same .json logs, never the .eval logs beside
    them (a different file choice is no judge change); one that lost it says so."""
    ws = Workspace(found.root)
    if not ws.start.is_file() or found.tool != "inspect":
        return found
    try:
        data = ws.data()
        files = [f for f in data.get("results_files") or [] if isinstance(f, str)]
        if data.get("given") or data.get("tool") != found.tool:
            return found
    except (OSError, ValueError, TypeError, AttributeError):
        return found
    if not all((found.root / f).is_file() for f in files):
        return found  # replaced by a new run: what changed is real
    switch = install_switch(files, list(found.used), start._has("inspect_ai"))
    if switch == "keep":
        return _find(talk, path, saved, only=files)
    if switch == "cant":
        evals = [f for f in files if f.lower().endswith(".eval")]
        talk.para(f"Your marks were made on {start._and(evals)}, which this install reads "
                  "only with its Inspect extra. To keep checking the same answers, "
                  f"{start._get_extra(talk, 'inspect')}.")
        raise talk.stop(EXIT_QUESTION, f"{start._get_extra(talk, 'inspect')}.")
    return found


def _remembered(talk: FrontTalk, path: Path) -> Path:
    """The results file (or MLflow store) given by path when marking started, for a run
    with no path; else `path`."""
    o = talk.options
    if path.is_file() or find.is_mlflow_folder(path) or o["tool"] or o["tracking_uri"]:
        return path
    ws = Workspace(project.project_of(path))
    try:
        if not ws.start.is_file() or start._saved(ws.root) is not None:
            return path
        return start.results_path(ws.root, ws.data()) if ws.data().get("given") else path
    except (OSError, ValueError):
        return path


def not_found(path: Path, given: str | None = None) -> StartError:
    """PATH is not there, in the words `check` says it with (check.no_such); a single word is
    taken for a command that does not exist. `given`: the path as typed, before Path made
    "https://" one slash, so a URL's password is still known to be one and hidden."""
    from judgekeeper.check import no_such

    word = given if given and Path(given) == path else str(path)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", word):
        return StartError(f"`{word}` is not a judgekeeper command, and there is no folder "
                          f"named {word} here.", f"run `{program()}`, or "
                                                 f"`{program()} --help` to see the commands.")
    return StartError(no_such(word), "check the path, then run `{command}`.")


def _own_format(talk: FrontTalk, path: Path) -> tuple[Path, settings.StartSettings | None]:
    """(where find_judge looks, the [start] table of an own-format file mapped now, or None).
    Nothing found at all: say where it looked, and stop."""
    from judgekeeper import own_map

    o = talk.options
    if path.is_file() and start.is_empty_file(path):  # as a file Find found empty
        root = project.project_of(path)
        raise start.empty_file(textio.shown_in(path, Path.cwd()), any(
            (root / name).is_file() for name in find.PROMPTFOO_CONFIGS))
    if path.is_file():
        if o["tool"] is not None or find.classify_file(path) is not None or \
                path.suffix.lower() not in own_format.SUFFIXES or find.is_promptfoo_table(path) \
                or find.title_row(path):
            return path, None  # find_judge reads it, or says why it can't
        root = project.project_of(path)
        return root, own_map.map_file(talk, root, path.resolve(), o["metric"], o["judge_model"],
                                      o["pass_if"], found=False)
    root = path.resolve()
    if (o["tool"] is not None or o["tracking_uri"] is not None or find.is_mlflow_folder(path)
            or start._saved(root)):
        return path, None
    search = find.search(root)
    if (any(search.readable(t) for t in find.TOOLS) or search.too_big() or search.unreadable
            or find.records_above(root) is not None or "promptfoo" in search.signs):
        return path, None  # find_judge reads them, or says how
    unlooked: list = []
    tables: list[str] = []
    own = own_format.search(root, unlooked, tables)
    if own is None and search.skipped and (nested := find.nested_results(search, answers=True)):
        raise _nothing_found(talk, root, search.signs, nested)  # a link left out here
        # never hides the projects below that hold results
    if own is None and (search.skipped or not talk.given
                        and find.results_above(root) is not None):
        return path, None  # results-like files too far up or down: find_judge names them
    if own is None and tables:  # promptfoo's table output, found past the walk's limits
        raise start.table_output(tables[0])
    for rel in tables:
        talk.para(f"{rel} {find.TABLE_OUTPUT}, so it was left out.")
    if own is None and search.judge_only:
        rel = search.judge_only[0]
        talk.para(f"{rel} has your LLM-as-a-judge's verdicts but no answer text, so there's "
                  "nothing to show you for marking.")
        raise talk.stop(EXIT_QUESTION, "add the answer column (the text that was graded) to "
                                       f"{rel}, then run `{talk.command()}`.")
    if own is None and search.no_question:
        rel = search.no_question[0]
        talk.para(f"{rel} has your LLM-as-a-judge's verdicts and the answers but no question, so "
                  "the answers can't be shown with what they answer.")
        raise talk.stop(EXIT_QUESTION, "add the question column (what each answer answers) to "
                                       f"{rel}, then run `{talk.command()}`.")
    if own is None:
        raise _nothing_found(talk, root, search.signs, find.nested_results(search, answers=True),
                             unlooked, stopped=search.stopped)
    return root, own_map.map_file(talk, root, own.path, o["metric"], o["judge_model"],
                                  o["pass_if"], found=True)


def _find(talk: FrontTalk, path: Path, saved, only: list[str] | None = None) -> start.Found:
    """find_judge, again after each answer about decisions it cannot read as Pass or Fail.
    `only`: the results files the marks were made on (_marked_files)."""
    given = _given_model(path) if talk.options["judge_model"] is None and saved is None else None
    kept = _kept_experiment(path) if talk.options["experiment"] is None else None
    kept_map = _kept_label_map(path) if talk.options["label_map"] is None and saved is None \
        else None
    kept_tool = _kept_tool(path) if saved is None else None
    while True:
        options = {k: talk.options[k] for k in FIND}
        options.update({ASKED[f]: v for f, v in talk.answers.items() if f in ASKED})
        if saved is not None:  # a map made now holds the judge's model and its pass mark
            # (unless the file names the model: then --judge-model wins for this run)
            options.update(pass_if=None, judge_model=options["judge_model"]
                           if saved.map.get("model_key") else None)
            if str(options["metric"]).lower() in ("*", "all"):  # every judge: the map says so
                options["metric"] = None
        if options["experiment"] is None:
            options["experiment"] = kept
        if options["label_map"] is None:
            options["label_map"] = kept_map
        if options["tool"] is None and options["tracking_uri"] is None:
            options["tool"] = kept_tool
        try:
            try:
                found = start.find_judge(path, talk=talk, saved=saved, store=talk.store,
                                         only=only, answers=True,
                                         **{**options, "judge_model": given or
                                                       options["judge_model"]})
            except StartError:
                if given is None and kept is None and kept_tool is None:
                    raise
                if given is not None:
                    given = None  # the results name the model now
                elif kept is not None:
                    kept = None  # the experiment is gone: asked again
                else:
                    kept_tool = None  # its results are gone: found again
                continue
        except RecordsError as e:
            raise start.usage_error(e) from None
        if not found.pool.unmapped:
            _ignored(talk, found)
            return found
        _unread_values(talk, found)


def _kept_tool(path: Path) -> str | None:
    """The eval tool the marks were made on, kept in start.json, for a run on the project
    folder with no judgekeeper.toml: read again with no --tool, as `check` reads it."""
    if not path.is_dir():
        return None
    ws = Workspace(project.project_of(path))
    try:
        if not ws.start.is_file() or start._saved(ws.root) is not None:
            return None
        tool = ws.data().get("tool")
    except (OSError, ValueError, AttributeError):
        return None
    return tool if tool in find.TOOLS else None


def _kept_experiment(path: Path) -> str | None:
    """The MLflow experiment the marks were made on, kept in start.json: read again with no
    --experiment, as the store is."""
    ws = Workspace(project.project_of(path))
    try:
        data = ws.data() if ws.start.is_file() else {}
    except (OSError, ValueError):
        return None
    name = data.get("experiment") if isinstance(data, dict) and data.get("tool") == "mlflow" \
        else None
    return name if isinstance(name, str) else None


def _kept_label_map(path: Path) -> str | dict | None:
    """The --label-map the marks were read with, kept in start.json: read again with no
    --label-map, so the plain command the page names doesn't ask the same question again."""
    ws = Workspace(project.project_of(path))
    try:
        data = ws.data() if ws.start.is_file() else {}
    except (OSError, ValueError):
        return None
    value = data.get("label_map") if isinstance(data, dict) else None
    return value if isinstance(value, (str, dict)) and value else None


def _given_model(path: Path) -> str | None:
    """The judge's model the person gave with --judge-model when marking started, kept in
    start.json: used while the results still don't name one."""
    ws = Workspace(project.project_of(path))
    try:
        fp = (ws.data().get("fingerprint") or {}) if ws.start.is_file() else {}
    except (OSError, ValueError, AttributeError):
        return None
    model = start.given_model(fp, ws.root)
    return model if isinstance(model, str) else None


IGNORED = {"experiment": ("mlflow", "--experiment is for MLflow results, so it was ignored.")}


def _ignored(talk: FrontTalk, found: start.Found) -> None:
    """A flag for another tool's results: said, and left out of the commands printed."""
    for option, (tool, said) in IGNORED.items():
        if talk.options.get(option) and found.tool != tool:
            talk.para(said)
            talk.say()
            talk.set(option, None)


def _shown(values) -> str:
    texts = [scrub(start.shown_value(v)) for v in values]  # keys hidden before the cut
    texts = [t[:VALUE_WIDTH - 1] + "…" if len(t) > VALUE_WIDTH else t for t in texts]
    return ", ".join(sorted(texts)[:10]) + (f" and {len(texts) - 10} more"
                                             if len(texts) > 10 else "")


def _with_given_map(given: str | None, extra: tuple[str, ...]) -> tuple[str, ...]:
    """`extra` with the person's `given` map before the entries of its --label-map, which
    replaces theirs in the command (start.Talk.command): so no entry of theirs is lost."""
    at = next((n for n, w in enumerate(extra)
               if w == "--label-map" or w.startswith("--label-map=")), None)
    if not given or at is None:
        return extra
    one_word = extra[at] != "--label-map"  # `--label-map=entries`
    entries = extra[at].split("=", 1)[1] if one_word else extra[at + 1]
    merged = f"{given},{entries.strip(chr(34))}"
    textio._held.pop(given, None)  # on Windows, only the merged map is said beside the command
    value = quote_arg(merged)
    if entries.startswith('"') and value == merged:  # a placeholder stays in its quotes
        value = f'"{merged}"'
    flag = (f"--label-map={value}",) if merged.startswith("-") else ("--label-map", value)
    return (*extra[:at], *flag, *extra[at + (1 if one_word else 2):])


def _add_label_map(talk: FrontTalk, extra: str) -> None:
    given = talk.options["label_map"]
    talk.set("label_map", f"{given},{extra}" if given else extra)


def _saved_pass_mark(found: start.Found) -> dict:
    """The pass mark the marks read the scores with now, as start.json keeps it; else {}."""
    try:
        return Workspace(found.root).data().get("pass_mark") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _rule_in_use(found: start.Found) -> str:
    """--pass-if's value in the command said without a terminal: the rule the marks read the
    scores with now (given with --pass-if, or taken on by a check), quoted; else PASS_IF."""
    pm = _saved_pass_mark(found)
    rule = pm.get("rule")
    if pm.get("source") != "pass_if" or not isinstance(rule, str) or not rule.isprintable():
        return PASS_IF
    try:
        parse_pass_if(rule)
    except NormaliseError:
        return PASS_IF
    return quote_arg(rule)


def _mark_in_use(found: start.Found) -> str:
    """The default for the pass mark asked: the one the marks read the scores with now (given
    with --pass-if, or taken on by a check), when it is "at least"; else 0.5."""
    pm = _saved_pass_mark(found)
    mark = pm.get("mark")
    if pm.get("source") == "pass_if" and pm.get("op") == ">=" and isinstance(mark, (int, float)) \
            and not isinstance(mark, bool):
        return f"{mark:g}"
    return "0.5"


def _unread_values(talk: FrontTalk, found: start.Found) -> None:
    """The judge's decisions hold values that are not Pass or Fail: ask what they mean (never
    a guess: a wrong one turns fails into passes)."""
    values = list(dict.fromkeys(found.pool.unmapped))
    terminal = start._interactive()
    keep = talk.labels_flags()  # a run with --labels: its Next lines keep it
    if found.tool == "inspect" and "P" in values:  # model_graded_qa(partial_credit=True)
        n = found.pool.n_unmapped.get(repr("P"), 0)
        for line in found_block(found):  # what was found; the count waits for the answer
            if not line.startswith("Answers:"):
                _say_found(talk, line)
        talk.say()
        talk.say(f"Inspect gave partial credit (P) on {_n(n, 'answer')}.")
        if not terminal:
            raise talk.stop(EXIT_QUESTION, (
                "decide whether partial credit (P) counts as Pass or Fail, then run "
                f"`{talk.command(*keep, '--label-map', 'P=pass')}` or "
                f"`{talk.command(*keep, '--label-map', 'P=fail')}`."))
        i = talk.choose("Should partial credit count as Pass or Fail?", ["Pass", "Fail"], "")
        _add_label_map(talk, f"P={('pass', 'fail')[i]}")
        return
    if all(_numeric(v) for v in values):
        if not terminal and (rule := _rule_in_use(found)) != PASS_IF:  # measured: it is saved
            again = talk.command(*keep, "--pass-if", rule)
            talk.step = None  # a saved pass mark: past Find, so no "Step 1 of 5: Find" above it
            talk.para(PASS_MARK_AGAIN.format(rule=_saved_pass_mark(found)["rule"]))
            raise talk.stop(EXIT_QUESTION, f"run `{again}`.")
        talk.say(f"Your LLM-as-a-judge's decisions are scores ({_shown(values)}), and the results "
                 "do not say which score passes.")
        if not terminal:
            raise talk.stop(EXIT_QUESTION, "decide which score counts as a pass, then run "
                                           f"`{talk.command(*keep, '--pass-if', _rule_in_use(found))}`.")
        while True:
            answer = talk.ask("Pass when the score is at least", _mark_in_use(found))
            if _numeric(answer):
                talk.set("pass_if", f"score>={answer}")
                return
    words = [str(v) for v in values if not _numeric(v)]
    long = [v for v in values if not _numeric(v) and not start.verdict_like(v)]
    if long:  # never shown: it may be the judge's reason or an answer's text
        raise _long_text(talk, found, long)
    talk.para("judgekeeper can't tell which of your LLM-as-a-judge's decisions mean Pass and which "
              f"mean Fail: {_shown(words)}.")
    if not terminal:
        raise talk.stop(EXIT_QUESTION, (
            "decide which of the values above mean Pass, which mean Fail and which mean no "
            f"decision (error), then run `{talk.command(*keep, '--label-map', LABEL_MAP)}`."))
    picked = []
    for w in words:
        i = talk.choose(f"Does {w!r} mean Pass or Fail?", ["Pass", "Fail"], "")
        picked.append(f"{w}={('pass', 'fail')[i]}")
    _add_label_map(talk, ",".join(picked))


def _long_text(talk: FrontTalk, found: start.Found, long: list) -> Stop:
    """The judge's decisions hold long text, not grade words: counted, never shown. In a
    table, a quote that never closes may have put it there."""
    from judgekeeper.table import open_quote

    n = sum(found.pool.n_unmapped.get(repr(v), 0) for v in long)
    newest = found.results[0].path
    if found.tool == "table":
        columns = find.table_columns(newest)
        column = next(iter(find.grade_columns(columns)), "verdict")
        line = open_quote(newest, loose=True)
        hint = (f" (line {line} of {newest.name} may have a quote that never closes)"
                if line else "")
        where = f"the {column} column holds long text in {_n(n, 'row')}{hint}"
        fix = f"make each grade in the {column} column of {newest.name} one word, like pass"
    else:
        where = f"they hold long text in {_n(n, 'answer')}"
        fix = "check where your LLM-as-a-judge's decisions are saved"
    talk.para("judgekeeper can't tell which of your LLM-as-a-judge's decisions mean Pass and which "
              f"mean Fail: {where}.")
    return talk.stop(EXIT_QUESTION, f"{fix}, then run `{talk.command(*talk.labels_flags())}`.")


OTHERS_HOME = "in another person's home folder, which judgekeeper doesn't name in full"


def _nested_line(nested: list[str], base: Path) -> str:
    """Results in projects of their own below this one (find.nested_results, named from the
    folder `base`): whose they are, and where to check them. A folder in another person's
    home folder (cut short) is said to be there."""
    named = start._and([f"{p}/" for p in nested])
    cut = any(textio.cut_short(p) for p in nested)
    return (f"These results belong to the {'project' if len(nested) == 1 else 'projects'} in "
            f"{named}{f', {OTHERS_HOME}' if cut else ''}. To check them, "
            f"{run_there(nested, base)}")


def run_there(folders: list[str], base: Path) -> str:
    """"run `<program>` in <folder>." for `folders` (named from `base`): "in that folder" when
    one is cut short, which no one can go to by its name."""
    if any(textio.cut_short(p) for p in folders):
        where = "that folder" if len(folders) == 1 else "one of those folders"
    else:
        where = start._or([f"{p}/" for p in folders])
    return f"run `{_program_there(folders, base)}` in {where}."


def _from_here(base: Path, names: list[str]) -> list[str]:
    """Folders `names` right below `base`, as lines name them (textio.folder_from_here), so
    `cd` and "in ..." work from here, never with a user name."""
    return [textio.folder_from_here(Path(base) / name) for name in names]


def _program_there(folders: list[str], base: Path) -> str:
    """program() as it is typed in each of `folders` (from `base`), for a line that says to
    run it there: the same in all of them, else the form that runs in any folder."""
    shown = {textio.program_in(textio.folder_of(f, base)) for f in folders}
    return shown.pop() if len(shown) == 1 else textio.program_in(textio.ANYWHERE)


def _nothing_found(talk: FrontTalk, root: Path, signs: dict,
                   nested: list[str] | None = None, unlooked: list | None = None,
                   stopped: str | None = None) -> Stop:
    """No results: the tools found here (with what saves their results), else what
    judgekeeper can read. The folder by its name only. Results in a project of its own below
    (`nested`) are named, never read; results-like files too big to look into (`unlooked`,
    own_format.search) are named. `stopped` (find.Search.stopped): the walk gave up before
    the end, so the person gives the path."""
    if stopped:
        talk.para(f"judgekeeper {stopped[0].lower()}{stopped[1:]}")
        return talk.stop(EXIT_QUESTION, (f"give the path of your results: run "
                                         f"`{talk.command_at('PATH')}` with their file or "
                                         "folder."))
    if nested and len(sessions := _sessions_below(root, nested)) == len(nested):
        return _go_to(talk, [(_from_here(root, [n])[0], k) for n, k in sessions])
    if nested:
        nested = _from_here(root, nested)
        talk.para(_nested_line(nested, Path.cwd()))
        return talk.stop(EXIT_QUESTION, run_there(nested, Path.cwd()))
    saved = _marks_in(Workspace(root)) if talk.given else _saved_marks(root)  # a folder named
    # is the project: never the marks of a project around it
    if saved:  # the results file is gone, the marks are not
        talk.say_step()
        talk.para(f"No eval results found in this folder. Your {_n(saved, 'mark')} "
                  f"{'is' if saved == 1 else 'are'} saved in {FOLDER}/; they come back when "
                  "your results file is back.")
    elif signs:
        for tool, where in signs.items():
            name = find.NAMES[tool]
            talk.para(f"Found {name} in this folder ({where[0]}), but no saved results yet. "
                      + SAVES.get(tool, ""))
    else:
        down = find.looked(root).replace(f" from {root.name}", "")
        talk.para(f"No eval results found in this folder ({root.name}). judgekeeper looked "
                  f"{down}.")
        talk.para(READS)
    for own in (unlooked or [])[:OTHERS]:
        size = own.path.stat().st_size
        shown = (f"{size / 1_000_000:,.0f} MB" if size >= 1_000_000
                 else f"{size / 1000:,.0f} KB")
        talk.para(f"It left out {own.rel} ({shown}): too big to look into. If it holds your "
                  f"LLM-as-a-judge's results, run `{talk.command_at(own.rel)}`.")
    if not (saved or signs or unlooked):  # no eval tool set up here: maybe no answers yet
        _questions_prompt(talk)
        _way_above(talk, root)
        return talk.stop(EXIT_QUESTION, QUESTIONS_NEXT.format(command=talk.command()))
    again = f"`{talk.command()}`"
    other = "" if signs else (f" If your results are somewhere else, run "
                              f"`{talk.command_at('PATH')}` with their file or folder.")
    return talk.stop(EXIT_QUESTION, f"run your eval once from this folder, then run {again} "
                                    f"again.{other}")


def _way_above(talk: FrontTalk, root: Path) -> None:
    """above_line, for a run with no PATH that found nothing to read."""
    if talk.given:
        return
    line = above_line(talk, root)
    if line is not None:
        talk.say()
        talk.para(line)


def above_line(talk: FrontTalk, root: Path) -> str | None:
    """FOLDER_ABOVE (FOLDERS_ABOVE when it is more than one level up) when the project folder
    above `root` holds results: the command that reads them, from the folder run in."""
    up = reads_above(root)
    if up is None:
        return None
    path = Path(os.path.relpath(up, Path.cwd())).as_posix()
    said = FOLDERS_ABOVE if len(Path(path).parts) > 1 else FOLDER_ABOVE
    return said.format(command=talk.command_in(path))


def _questions_prompt(talk: FrontTalk) -> None:
    """The prompt that has the person's coding agent write test questions and save the AI's
    answers, for a project with none yet."""
    talk.say()
    talk.para(QUESTIONS_INTRO)
    talk.say()
    for line in QUESTIONS_PROMPT.format(program=textio.program()).splitlines():
        talk.para(line)
    talk.say()
    talk.say(QUESTIONS_KEY)


def _saved_marks(root: Path) -> int:
    """How many marks the project's .judgekeeper/ holds."""
    return _marks_in(Workspace(project.project_of(root)))


def _marks_in(ws: Workspace) -> int:
    try:
        return len(marks.read(ws.marks).counted()) if ws.marks.is_file() else 0
    except (OSError, ValueError):
        return 0


def _session_in(folder: Path) -> bool:
    """Whether the .judgekeeper/ in `folder` holds a session: start.json or labels."""
    ws = Workspace(folder)
    try:
        return ws.start.is_file() or ws.labels.is_file()
    except OSError:  # a folder that can't be read (/lost+found): no session
        return False


def _sessions_below(folder: Path, names: list[str] | None = None,
                    judged: bool = False) -> list[tuple[str, int]]:
    """(name, its marks) of each folder right below `folder` (or of `names`, paths from it)
    whose .judgekeeper/ holds a session (_session_in); `judged`: or only the judge.json of a
    first run that stopped before marking."""
    if names is None:
        try:
            names = sorted(e.name for e in os.scandir(folder)
                           if e.is_dir(follow_symlinks=False) and e.name != FOLDER)
        except OSError:
            return []
    out = []
    for name in names:
        ws = Workspace(folder / name)
        try:
            held = _session_in(folder / name) or judged and (ws.dir / judge_setup.FILE).is_file()
        except OSError:  # a folder that can't be read (/lost+found): no session to name
            continue
        if held:
            out.append((name, _marks_in(ws)))
    return out


def _own_results(folder: Path, besides: Path | None = None) -> bool:
    """Whether a run in `folder` has results of its own to read: a results file, or answers
    with no grade, that is not inside a project below it (find.is_project: a project file
    or its own .judgekeeper/), nor in `besides` (the folder a run below it reads)."""
    found = find.search(folder)
    files = [r.path for rs in found.results.values() for r in rs]
    files += [path for path, _ in found.answers_only]
    left = Path(besides).resolve() if besides is not None else None
    return any(not _in_project_below(folder, Path(path))
               and not (left is not None and Path(path).resolve().is_relative_to(left))
               for path in files)


def reads_above(root: Path) -> Path | None:
    """The nearest folder above `root`, up to its project folder (find.project_folder), that
    holds a session (_session_in) or where a run reads results of its own (_own_results, not
    those in `root`); None when there is none."""
    root = Path(root).resolve()
    top = find.project_folder(root)
    if top is None:
        return None
    for folder in root.parents:
        if _session_in(folder) or _own_results(folder, besides=root):
            return folder
        if folder == top:
            return None
    return None


def _in_project_below(folder: Path, path: Path) -> bool:
    """Whether `path` is inside a project of its own below `folder`."""
    folder = folder.resolve()
    for above in Path(path).resolve().parents:
        if above == folder or not above.is_relative_to(folder):
            return False
        if find.is_project(above) and not find._left_empty(above):
            return True
    return False


def _sent_below(path: Path) -> bool:
    """Whether a run in `path` (a folder) goes to the sessions below it: it is no project,
    holds no session of its own, has no results of its own, and a folder right below holds
    a session."""
    return (path.is_dir() and not project.is_project(path) and not _session_in(path)
            and bool(_sessions_below(path)) and not _own_results(path))


def go_to_words(sessions: list[tuple[str, int]], command: str) -> tuple[str, str]:
    """(where the sessions in folders below are, the Next step: go there and run `command`).
    The folder run in is "this folder", and then the step is to run `command` in it."""
    if len(sessions) == 1:
        (name, n), = sessions
        said = (THIS_FOLDER.format(marks=_n(n, 'mark')) if name == "." else
                f"{name}/ already holds your judgekeeper session ({_n(n, 'mark')}): "
                "judgekeeper keeps a project's marks in its own folder.")
    else:
        named = start._and([f"{'this folder' if name == '.' else name + '/'} "
                            f"({_n(n, 'mark')})" for name, n in sessions])
        said = (f"{named} already hold your judgekeeper sessions: judgekeeper keeps a "
                "project's marks in its own folder.")
    if any(name == "." for name, _ in sessions):
        return said, f"run `{command}`."
    return said, _go_step([name for name, _ in sessions], command)


def _go_step(names: list[str], command: str) -> str:
    """Go to the first folder of `names` and run `command` (it starts with program()) there:
    the program as it is typed in that folder (textio.run_from)."""
    folder = "that folder" if len(names) == 1 else "one of those folders"
    here = program()
    if command.startswith(here):
        with textio.run_from(textio.folder_of(names[0], Path.cwd())):
            command = program() + command[len(here):]
    if textio.cut_short(names[0]):  # no `cd` can go there by its name
        return f"go to {folder} ({OTHERS_HOME}), then run `{command}` there."
    if textio.is_windows() and (inside := _in_home_windows(names[0])) is not None:
        # cmd reads %USERPROFILE%, PowerShell only ~: no `cd` runs in both, so in words
        where = ("your home folder" if not inside and len(names) == 1 else
                 f"{folder} ({inside} in your home folder)" if len(names) == 1 else
                 f"{folder} (in your home folder)")
        return f"go to {where}, then run `{command}` there."
    return f"go to {folder} (`cd {textio.cd_word(names[0])}`), then run `{command}` there."


def _in_home_windows(shown: str) -> str | None:
    """The rest of a folder_from_here name in the home folder on Windows (`%USERPROFILE%`
    and what follows it): "" for the home folder itself; None for any other name."""
    form = textio.HOME_FORMS[1]
    if shown == form.rstrip("\\"):
        return ""
    return shown[len(form):] if shown.startswith(form) else None


def _go_to(talk: FrontTalk, sessions: list[tuple[str, int]]) -> Stop:
    """Sessions in folders below this one: where they are, never a second one here."""
    said, step = go_to_words(sessions, program())
    talk.para(said)
    return talk.stop(EXIT_QUESTION, step)


# A tool's own folder for its results, in the project it runs in: Inspect AI's, DeepEval's,
# MLflow's and judgekeeper.record()'s
TOOL_FOLDERS = ("logs", find.HIDDEN_KEPT, "mlruns", FOLDER)
ASKED = ("deepeval", "inspect")  # results in several folders: asked which (start._choose_folder)


def _projects_below(folder: Path) -> list[str]:
    """The folders right below `folder` that hold results, when there are 2 or more (or one
    that is a project of its own, project.is_project) and nothing says `folder` is one
    project: no results or tool's config in it, and none in a tool's own folder
    (TOOL_FOLDERS). DeepEval and Inspect AI results are asked about as before (ASKED). Each
    is a project of its own, never run."""
    found = find.search(folder)
    if found.answers_read or any("/" not in sign for signs in found.signs.values()
                                 for sign in signs):  # answers with no grade: one project
        return []
    tops = set()
    for result in (r for rs in found.results.values() for r in rs):
        parts = Path(result.rel).parts
        if (len(parts) < 2 or result.tool in ASKED
                or any(part in TOOL_FOLDERS for part in parts[:-1])):
            return []
        tops.add(parts[0])
    if len(tops) == 1 and not project.is_project(folder / next(iter(tops))):
        return []  # one plain folder (evals/) holds this folder's results
    return sorted(tops)


def _tool_below(folder: Path, tool: str) -> tuple[list[str], list[str]]:
    """(the projects of their own below `folder` (find.is_project) that hold `tool`'s results,
    by their path from it, the paths of its results in none): run from a folder that is no
    project, a project's files below are never read with the others."""
    owners, rest = set(), []
    for result in find.search(folder).results.get(tool, []):
        parts = Path(result.rel).parts
        owner = next((Path(*parts[:n]) for n in range(1, len(parts))
                      if find.is_project(folder / Path(*parts[:n]))
                      and not find._left_empty(folder / Path(*parts[:n]))), None)
        if owner is None:
            rest.append(result.rel)
        else:
            owners.add(owner.as_posix())
    return sorted(owners), rest


def _tool_read(talk: FrontTalk, path: Path) -> str | None:
    """The eval tool a run on the folder `path` reads: --tool, else the only tool whose results
    are found there (several are asked about as before). None for a store, a map, or a folder
    with a tool's config of its own: one project, as _projects_below takes it."""
    o = talk.options
    if o["tracking_uri"] is not None or find.is_mlflow_folder(path) or (
            o["tool"] is None and start._saved(path.resolve()) is not None):
        return None
    search = find.search(path)
    if any("/" not in sign for signs in search.signs.values() for sign in signs):
        return None
    if o["tool"] is not None:
        return o["tool"]
    tools = [tool for tool in find.TOOLS if search.results.get(tool)]
    return tools[0] if len(tools) == 1 else None


def _checked_there(talk: FrontTalk, folders: list[str]) -> Stop:
    """Results in projects of their own below (from here), never run here: where to check
    them."""
    if len(folders) == 1:
        talk.para(_nested_line(folders, Path.cwd()))
        return talk.stop(EXIT_QUESTION, run_there(folders, Path.cwd()))
    return _go_to_one(talk, folders)


def _beside_a_session(folder: Path) -> list[str]:
    """The folders below `folder` that hold results, when one is a project with a session of
    its own (find.nested_results) and the others hold the rest, none in `folder` itself or a
    tool's own folder there: projects of their own, never one session for them."""
    if not _sessions_below(folder):  # the walk below only when a session is right below
        return []
    found = find.search(folder)
    nested = find.nested_results(found)
    if not nested or len(_sessions_below(folder, nested)) < len(nested) or any(
            "/" not in sign for signs in found.signs.values() for sign in signs):
        return []
    tops = set()
    for result in (r for rs in found.results.values() for r in rs):
        parts = Path(result.rel).parts
        if len(parts) < 2 or parts[0] in TOOL_FOLDERS:
            return []
        tops.add(parts[0])
    return sorted({*nested, *tops}) if tops else []


def _session_owning(path: Path) -> str | None:
    """A results file in a folder below this project whose own .judgekeeper/ holds a
    session: that folder, from the folder the command runs in. From a folder that is no
    project, a project below (project.is_project) owns its files too, used or not."""
    root = project.project_of(path)
    folder = path.resolve().parent
    if not folder.is_relative_to(root):
        return None
    no_project = not project.is_project(root)
    while folder != root:
        ws = Workspace(folder)
        held = (ws.start.is_file() or ws.labels.is_file()) and (
            project.marks_above(folder, path.resolve()) is None)
        if held or no_project and project.is_project(folder):
            return textio.folder_from_here(folder)
        folder = folder.parent
    return None


def _go_to_one(talk: FrontTalk, folders: list[str]) -> Stop:
    """Results in projects below, never run: which, and to go to one."""
    talk.para(f"{start._and([f'{name}/' for name in folders])} hold eval results: judgekeeper "
              "keeps a project's marks in its own folder, so it checks one at a time.")
    return talk.stop(EXIT_QUESTION, _go_step(folders, program()))


def sessions_here(path: str | Path) -> list[tuple[str, int]]:
    """For `fix` and `check` with no marks to use: the sessions in the folders right below
    `path`, a folder whose project holds no session of its own."""
    path = Path(path)
    if not path.is_dir() or Workspace(project.project_of(path)).start.is_file():
        return []
    return _sessions_below(path)


def _tracking_server(talk: FrontTalk, path: Path, uri: str) -> Stop:
    """--tracking-uri names a server: say what works instead, a local store."""
    talk.say(start.TRACKING_SERVER.format(uri=uri))
    talk.set("tracking_uri", None)
    root = path.resolve() if path.is_dir() else path.resolve().parent
    stores = find.search(root).readable("mlflow") if root.is_dir() else []
    if stores:
        return talk.stop(EXIT_QUESTION, f"run `{talk.command_at(stores[0].rel)}`.")
    return talk.stop(EXIT_QUESTION, (
        "find your local MLflow store (an mlflow.db file or an mlruns/ folder), then run "
        f"`{talk.command('--tracking-uri', 'PATH')}`."))


# Saying it ---------------------------------------------------------------------------------

_n = plural  # textio.plural


def _columns_line(found: start.Found, pass_if: str | None = None) -> str | None:
    """SCORE_READ when --pass-if reads a table's score column next to its verdict column;
    else None (the Read-from-your-file rows name the columns)."""
    columns = find.table_columns(found.results[0].path)
    verdict = next((c for c in find.VERDICT_COLUMNS if c in columns), None)
    return SCORE_READ if pass_if and verdict and "score" in columns else None


def _notes(found: start.Found, labels_command: str | None = None) -> list[str]:
    """The notes under the counts; `labels_command`: the command that uses the human labels
    in the results (None when --labels was given)."""
    pool, out = found.pool, [*found.stopped, *found.warnings]
    if judge_check.model_not_written(found):  # said once, with its fix, by the free checks
        out = [w for w in out if DEFAULT_GRADER_NOTE not in w]
    if not pool.answers:  # "none with a clear grade": where the grades came from is moot
        out = [w for w in out if "default grader" not in w]
    if pool.humans and labels_command:
        out.append(labels_mod.found_line(len(pool.humans), labels_command))
    n = len(pool.answers)
    for count, did, too in ((pool.n_fail, "failed", "passes too much"),
                            (pool.n_pass, "passed", "fails too much")):
        # under a fifth of the answers; a small pool is said below
        if 0 < count < FEW_SHARE * n and n >= start.MIN_POOL:
            out.append(f"Your LLM-as-a-judge {did} only {count} of {n} answers. That may mean it "
                       f"{too}: your marks will show it.")
    return out


def _other_files(found: start.Found, talk: FrontTalk) -> str | None:
    """Results files found next to the one read, never read with it: named (at most
    OTHERS), with the command that checks one, the person's flags kept. Another eval beside
    it can't be checked here once marking starts (project.other_eval): a folder of its own."""
    if found.tool not in FILE_TOOLS or found.given:
        return None
    others = [r for r in found.results if r.rel not in found.used][:OTHERS]
    apart = [r.rel for r in others if _another_eval(r, found)]
    here = [r.rel for r in others if r.rel not in apart]
    said = []
    if here:
        commands = start._or([f"`{talk.command_at(r)}`" for r in here])
        said.append(f"Also found {start._and(here)}. To check "
                    f"{'it' if len(here) == 1 else 'one'}, run {commands}.")
    if apart:
        said.append(f"Also found {start._and(apart)}, with other questions. To check "
                    f"{'it' if len(apart) == 1 else 'one'}, put it in a folder of its own and "
                    f"run `{project.program_anywhere()}` there.")
    return " ".join(said) or None


def _another_eval(result: find.Result, found: start.Found) -> bool:
    """Whether `result`, not read, sits beside a file read and is another eval than `found`."""
    read = {r.path.resolve().parent for r in found.results if r.rel in found.used}
    if result.path.resolve().parent not in read or not found.pool.answers:
        return False
    held = [{"input": a.input, "output": a.output, "id": a.id} for a in found.pool.answers]
    return not project.same_questions(result.path.resolve(), found.tool, held)


def _other_projects(found: start.Found) -> str | None:
    """Run from a folder that is no project but holds several: which project the results
    are from, and the others that hold results (at most OTHERS), each with its command."""
    root = Path(found.root)
    if found.given or project.is_project(root):
        return None

    def project_of(path: Path) -> str | None:
        for folder in path.parents:
            if folder == root or not folder.is_relative_to(root):
                return None
            if project.is_project(folder):
                return folder.relative_to(root).as_posix()
        return None

    read = project_of(found.results[0].path)
    search = find.search(root)
    others = sorted({p for t in find.TOOLS for r in search.readable(t)
                     if (p := project_of(r.path)) not in (None, read)})[:OTHERS]
    if read is None or not others:
        return None
    return f"These results are from the project in {read}/. {_results_too(others)}"


def _results_too(others: list[str]) -> str:
    """The projects in `others` (paths from here) have results too, each with its command."""
    one = len(others) == 1
    named = start._and([f"{p}/" for p in others])
    commands = start._or([f"`{program()} {quote_arg(p)}`" for p in others])
    return (f"The {'project' if one else 'projects'} in {named} {'has' if one else 'have'} "
            f"results too: to check them, run {commands}.")


def _nested_here(found: start.Found) -> str | None:
    """Results in a project of its own below this one, never read with these: named."""
    if found.given:
        return None
    nested = find.nested_results(find.search(found.root), answers=True)
    return _results_too(_from_here(found.root, nested)) if nested else None


def _outer_marks(found: start.Found) -> str | None:
    """A project above this one whose .judgekeeper/ holds marks for these results (made from
    there before a project kept its own): said once, when marking starts here."""
    root = Path(found.root).resolve()
    try:
        home = Path.home().resolve()
    except (RuntimeError, OSError):
        home = None
    for folder in root.parents:
        if folder == home:
            return None
        ws = Workspace(folder)
        if not ws.start.is_file():
            continue
        try:
            data = ws.data()
            given = data.get("given")  # a file given by path: read from where it is
            files = [Path(kept_at(f, folder)).resolve()
                     for f in ([given] if isinstance(given, str) and given
                               else data.get("results_files") or [])]
            n = len(marks.read(ws.marks).counted())
        except (OSError, ValueError, AttributeError, TypeError):
            return None
        if n and any(f.is_relative_to(root) for f in files):
            return (f"The project above ({folder.name}) holds {_n(n, 'mark')} for these results "
                    f"in its {FOLDER}/. They stay there: this project keeps its own marks.")
        return None
    return None


def _kept_apart(found: start.Found) -> str | None:
    """A session above whose marks are for other results than these: these get their own
    .judgekeeper/ here, said once, when marking starts here."""
    root = Path(found.root)
    apart = project.kept_apart(root, Path(kept_at(found.given, root)) if found.given else None)
    if apart is None:
        return None
    above, files = apart
    rel = textio.folder_from_here(above)  # never a user name
    return ("These results get their own marks here. "
            + (f"The marks in {rel}/ are for {', '.join(files)}." if files else "")).strip()


def tool_version(found: start.Found) -> str | None:
    """The eval tool's version: from its results, else the project's lockfile."""
    return judge_setup.version_of(found)[0]


def _listed(found: start.Found) -> str:
    """Where _write puts the list of answers left out, as the person finds it."""
    from judgekeeper import start_label

    ws = start_label.Workspace(found.root)
    return link(ws.dir / judge_check.CSV_FILE,
                f"{start_label.shown_folder(ws)}/{judge_check.CSV_FILE}")


def _write(found: start.Found) -> None:
    """judge-check.json and .csv, and judge.json, in the project's .judgekeeper/ (never
    through a link). judge.json follows the newest results only until marking starts: then it
    is the judge of the marks, which `judgekeeper check` moves on."""
    from judgekeeper import start_label

    ws = start_label.Workspace(found.root)
    start_label.save_judge_check(ws, found)  # only when it lists something
    if not ws.start.is_file() or judge_setup.read(ws) is None:
        judge_setup.save(ws, judge_setup.of(found), found.metric)


def _changed(ws: Workspace, found: start.Found) -> list[str]:
    """What changed in the judge's setup since the one judge.json keeps, in words."""
    saved = judge_setup.read(ws)
    return judge_setup.changes(saved["setup"], judge_setup.of(found)) if saved else []


def _model_given(talk: FrontTalk, ws: Workspace, found: start.Found) -> bool:
    """Whether `--judge-model` names the model of a judge whose results name none, after
    marking started, and nothing else changed: it is written down then (write_model)."""
    saved = judge_setup.read(ws)
    new = judge_setup.of(found)
    if (saved is None or found.model_source != start.GIVEN_BY_YOU or saved["setup"]["models"]
            or judge_setup.changes({**saved["setup"], "models": new["models"]}, new)):
        return False
    data = ws.data()
    if {q["id"]: q["group"] for q in data.get("queue") or []} != {
            a.id: a.verdict for a in found.pool.answers}:  # the marks test other grades now
        return False
    with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one writes
        start_label.write_model(ws, found)
        judge_setup.save(ws, new, found.metric)
    return True


TOOL_NAMES = {**find.NAMES, "records": "judgekeeper.record() in your code",
              "mapped": "your own format"}


def tool_name(tool: str | None, files: list[str] | None = None) -> str | None:
    """The eval tool as every screen and page names it; a table by its kind ("your own CSV
    file", from the first of `files`)."""
    kind = Path(files[0]).suffix.lstrip(".").upper() if files else ""
    if tool == "table" and files or tool == "mapped" and kind in ("CSV", "TSV", "JSONL"):
        return f"your own {kind} file"  # a table by its kind, read by its columns or mapped
    return TOOL_NAMES.get(tool, tool)


def path_lines(found: start.Found, about: str | None = None) -> list[str]:
    """Which path judgekeeper takes with these results and why, then how to switch. `about`:
    the graded file the result is about, named from here, when it is not the one read."""
    if about is not None and found.graded:
        table = Path(about).suffix.lower() in (".csv", ".tsv", ".jsonl")
        return [PATH_GRADES.format(file=about),
                PATH_TABLE_TO_ANSWERS if table else PATH_TOOL_TO_ANSWERS]
    if found.tool == "mlflow":
        file = found.store
    elif found.tool == "records":
        file = _read_from(found).split(", ")[0]
    else:
        file = _newest(found)
    if not found.graded:
        return [PATH_NO_GRADES.format(file=file), PATH_TO_GRADES]
    table = tool_name(found.tool, [str(found.results[0].rel)]).startswith("your own ")
    return [PATH_GRADES.format(file=file),
            PATH_TABLE_TO_ANSWERS if table else PATH_TOOL_TO_ANSWERS]


def _path_head(talk: FrontTalk, found: start.Found, about: str | None = None) -> list[str]:
    """path_lines the first time this run asks, else none: said once a run."""
    if talk.path_said:
        return []
    talk.path_said = True
    lines = path_lines(found, about)
    root = Path(found.root)
    if not found.graded and not talk.given and not find.has_marker(root) \
            and getattr(talk, "find_shown", True):  # answers here, with code or not, not the
        # results above (find): said with Find, never on the runs after it
        line = above_line(talk, root)
        if line is not None:
            lines.append(line)
    return lines


def _path_first(talk: FrontTalk, head: list[str]) -> list[str]:
    """Say the path_lines in `head` now, under the step's header; the other head lines."""
    path = [line for line in talk.path_head if line in head]
    for line in path:
        talk.para(line)
    if path:
        talk.say()
    return [line for line in head if line not in path]


def _say_path(talk: FrontTalk, found: start.Found) -> None:
    """path_lines as a paragraph each and a blank line, once a run."""
    lines = _path_head(talk, found)
    for line in lines:
        talk.para(line)
    if lines:
        talk.say()


def _newest(found: start.Found) -> str:
    """The newest results file read, named from here (linked): `~/...` in the home folder,
    never through a top folder (textio.shown_in)."""
    newest = found.results[0]
    return link(newest.path, textio.shown_in(newest.path, found.root))


def _newest_line(ws: Workspace, found: start.Found) -> str | None:
    """NEWEST when this run found other results files than the last one read (a newer one
    saved in the folder), or the same ones with 2 or more results files here, not given by
    path; READING when the one read is older than the last one read (a run back on an
    earlier file)."""
    if found.given or found.tool in ("mlflow", "records") or not found.results:
        return None
    try:
        data = ws.data()
        files = [f for f in data.get("results_files") or [] if isinstance(f, str)]
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if not files or data.get("given"):
        return None
    if _same_files(ws, data, files, found) and len(found.results) < 2:
        return None
    return (READING if _older(ws, data, files, found) else NEWEST).format(file=_newest(found))


def _older(ws: Workspace, data: dict, files: list[str], found: start.Found) -> bool:
    """Whether the newest file `found` read is older than one of `files`, the files read last
    (start.json's, from the folder its results were read in), or than `results_read`, the
    newest one a check read, wherever it was (in .judgekeeper/fix/, or outside the project)."""
    base = start.results_path(ws.root, data)
    base = base if base.is_dir() else base.parent
    try:
        now = found.results[0].path.stat().st_mtime
    except OSError:
        return False
    read = data.get("results_read")
    if isinstance(read, str) and read:
        try:
            if Path(textio.kept_at(read, ws.root)).stat().st_mtime > now:
                return True
        except OSError:
            pass
    for f in files:
        try:
            if (base / f).stat().st_mtime > now:
                return True
        except OSError:
            continue
    return False


def _read_from(found: start.Found) -> str:
    """Where the answers were read, in the shape of found_line's brackets."""
    newest = found.results[0]
    if found.tool == "mlflow":
        return f"{found.store}, experiment {quote_arg(found.experiment or '')}"
    if found.tool == "records":  # from here, as every other path line (textio.shown_in)
        shown = textio.shown_in(newest.path, found.root)
        folder = Path(shown).parent.as_posix()
        return f"{shown if folder == '.' else folder + '/'}, {_n(len(found.used), 'file')}"
    shown = _newest(found)
    if found.tool == "mapped":
        return shown + (f", {_n(len(found.used), 'line')}" if len(found.used) > 1 else "")
    if len(found.used) > 1:
        older = [textio.shown_in(r.path, found.root) for label in found.used[1:]
                 for r in found.results[1:] if r.rel == label]
        names = f" ({start._and(older)})" if len(older) == len(found.used) - 1 else ""
        return f"{shown} and {_n(len(found.used) - 1, 'older file')}{names}"
    return shown


def _judge_value(found: start.Found) -> str:
    """The judge after "Judge:": its name when the results hold several, and its model."""
    parts = [found.metric] if len(found.metrics) > 1 or found.tool == "deepeval" else []
    if found.models:
        model = ", ".join(found.models)
        if found.model_source == start.GIVEN_BY_YOU:
            model += " (as you said)"
        elif found.model_source:
            model += f" ({found.model_source})"
    elif found.tool == "promptfoo":  # explained once, with its fix (judge_check.setup_lines)
        model = DEFAULT_GRADER
    else:
        model = "model not found in your results (add --judge-model NAME)"
    return ", ".join([*parts, model])


def _rule_file(found: start.Found) -> str | None:
    """The file the judge's rule comes from, when judgekeeper knows it."""
    if found.tool == "promptfoo":
        return start_fix_rule.rule_config(Path(found.root), found.tool, {})
    if found.tool == "inspect" and found.task_file and found.rule:
        return start_fix_rule.opened_rule_file(Path(found.root), found.task_file, found.rule,
                                               found.tool)
    return None


def _rule_lines(found: start.Found) -> list[str]:
    if found.reference:
        return ["Rule:            compared with each test's reference answer"]
    if not found.rule:
        return ["Rule:            not in your results"]
    rule = scrub(found.rule)  # keys hidden before the cut: a key cut short is not known
    if not found.one_rule:
        first = " ".join(rule.split())
        if len(first) > FIRST_SHOWN:
            first = first[:FIRST_SHOWN - 1].rstrip() + "…"
        return [f'Rule:            differs per test ({found.n_rules} rules). First: "{first}"']
    text = " ".join(rule.split())
    if len(text) <= RULE_SHOWN:
        return [f'Rule:            "{text}"']
    where = _rule_file(found)
    where = where and start_fix_rule.file_link(Path(found.root), where)
    return [f'Rule:            "{text[:RULE_SHOWN - 1].rstrip()}…"',
            f"{INDENT}(shortened{f'; full rule in {where}' if where else ''})"]


def repeats_note(answers: int, pool: start.Pool) -> str:
    """The note under Answers when answers are in the file more than once: repeats with the
    same grade count once, repeats with different grades each count (freecheck.js says the
    same)."""
    times = next(iter(pool.repeat_sizes)) if len(pool.repeat_sizes) == 1 else None
    times = times if times and times > 1 else None  # merged with a newer file's: no runs
    split = sum(n for n, _, _ in pool.split.values())
    head = (f"{_n(answers - split + len(pool.split), 'answer')}, each run {times} times"
            if times else "some answers are in it more than once")
    head = f"(your file has {answers + pool.n_merged} results: {head}"
    if not pool.split:
        return f"{head}, so each counts once.)"
    which = ("1 answer got different grades, so each of its" if len(pool.split) == 1
             else f"{len(pool.split)} answers got different grades, so each of their")
    return f"{head}. Repeats with the same grade count once. {which} {split} repeats counts.)"


def needs_each_kind(fails: int, answers: int, said: bool = False, left: int | None = None,
                    fail_marks: int = 0, pass_marks: int | None = None) -> str:
    """What a result needs, said where marking starts; when the LLM-as-a-judge failed under
    FEW_FAILS of the `answers` (`fails` of them), that finding the Fail marks can take many
    (`said`: Find said how few it failed in this run, so only that). With `left` answers to
    mark (None: all of them) and `fail_marks` and `pass_marks` made (None: not counted), fewer
    left than the marks of one kind still needed says so instead."""
    if answers and fails in (0, answers):  # one grade for every answer: exact numbers
        said, other = ("Pass", "Fail") if not fails else ("Fail", "Pass")
        return ONE_GRADE.format(said=said, other=other)
    out = NEEDS_EACH_KIND.format(n=targets.ROUGH, g=targets.FIRST_GROUP)
    if side := side_out_of_reach(fails, answers, left, fail_marks, pass_marks):
        return out + " " + FAILS_OUT_OF_REACH.format(
            left=f"{_n(left, 'answer')} {'is' if left == 1 else 'are'}", n=targets.ROUGH,
            side=side)
    if 0 < fails < FEW_FAILS * answers:  # none failed: another stop says so
        rest = FINDING.format(n=targets.ROUGH)
        out += " " + (rest[:1].upper() + rest[1:] if said else
                      FINDING_FAILS.format(f=fails, answers=answers, n=targets.ROUGH))
    return out


def side_out_of_reach(fails: int, answers: int, left: int | None = None,
                      fail_marks: int = 0, pass_marks: int | None = None) -> str | None:
    """"Fail" or "Pass" when marking the `left` answers can't reach targets.ROUGH marks of
    that kind (`fail_marks` and `pass_marks` made; None: Pass marks not counted), when the
    LLM-as-a-judge failed `fails` of the `answers` and passed the others (`left` None: every
    answer is left); else None."""
    if answers and fails in (0, answers) or left is None:  # one grade: exact numbers
        return None
    return ("Fail" if left < targets.ROUGH - fail_marks else
            "Pass" if pass_marks is not None and left < targets.ROUGH - pass_marks else None)


def _each_kind(session: StartSession) -> dict:
    """needs_each_kind's numbers for `session`, but `said`."""
    groups = list(session.groups.values())  # every answer to mark, each batch's too
    return {"fails": groups.count("fail"), "answers": len(groups),
            "left": sum(not i["label"] for i in session.items),
            "fail_marks": sum(i["label"] == "fail" for i in session.items),
            "pass_marks": sum(i["label"] == "pass" for i in session.items)}


def _only_skipped(session: StartSession) -> int:
    """How many answers are left to mark when each of them was skipped, else 0. Said also
    when marking them all can't bring a result (side_out_of_reach), as the page says it."""
    left = [i for i in session.items if not i["label"]]
    if not left or not all(i["deferred"] for i in left):
        return 0
    return len(left)


def _needs_each_kind(talk, session: StartSession) -> None:
    talk.para(needs_each_kind(said=talk.few_fails, **_each_kind(session)))


def _group_marks(session: StartSession) -> str:
    """GROUP_MARKS: the marks on answers the LLM-as-a-judge passed and on those it failed."""
    marked = [i for i in session.items if i["label"] in ("pass", "fail")]
    passed = sum(session.groups.get(i["id"]) == "pass" for i in marked)
    sizes = Counter(session.groups.get(i["id"]) for i in session.items)
    short = [(word, have, min(targets.FIRST_GROUP, sizes.get(side, 0)))
             for side, word, have in (("pass", "passed", passed),
                                      ("fail", "failed", len(marked) - passed))
             if have < min(targets.FIRST_GROUP, sizes.get(side, 0))]
    if not short:  # every group has its marks: what holds the result back is said elsewhere
        short = [("passed", passed, targets.FIRST_GROUP),
                 ("failed", len(marked) - passed, targets.FIRST_GROUP)]

    def need(n: int) -> str:
        return str(n) if n == targets.FIRST_GROUP else f"all {n}"
    if len(short) == 1:
        word, have, n = short[0]
        said = GROUP_MARKS.format(marked=f"{_n(have, 'answer')} your LLM-as-a-judge {word}",
                                  need=need(n))
        if n < targets.FIRST_GROUP:  # why "all": fewer such answers than a result's usual marks
            said = said.split(". A result needs")[0] + ". " + (
                GROUP_ONE if n == 1 else GROUP_ALL).format(word=word, n=n)
        return said
    (_, p, np), (_, f, nf) = short
    return GROUP_MARKS.format(
        marked=f"{_n(p, 'answer')} your LLM-as-a-judge passed and {f} it failed",
        need=f"{need(np)} of each" if np == nf else f"{need(np)} and {need(nf)}")


def _import_gate(ws: Workspace, session: StartSession) -> str | None:
    """The line that says how many page marks a coloured verdict still needs to check the
    marks brought with --labels (labels.gate_line); None when none are needed."""
    if not ws.marks.is_file():
        return None
    data = ws.data()
    ids = set(batches.counted_labels(data, batches.graded(data, session.marked())))
    imported, needed, _ = start_label.import_check(marks.read(ws.marks), data, ids,
                                                   markable=True)
    return labels_mod.gate_line(needed, imported)


def passed_failed(n_pass: int, n_fail: int) -> str:
    return f"Your LLM-as-a-judge passed {_n(n_pass, 'answer')} and failed {n_fail}."


def _say_found(talk: FrontTalk, line: str) -> None:
    """A line of the Find block; a note under a value is wrapped under it."""
    if line.startswith(f"{INDENT}("):
        talk.para(line[len(INDENT):], indent=INDENT)
    else:
        talk.say(line)


def found_block(found: start.Found, pass_if: str | None = None,
                mapped: settings.StartSettings | None = None,
                said: list[str] | None = None) -> list[str]:
    """The "Find" block: the eval tool, the file, the answers, the judge, its rule and
    what was read from the file, but for what `said` (own_map.how_lines, printed this run)
    already said in the same words."""
    answers = found.check.answers if found.check else len(found.pool.answers)
    tool = tool_name(found.tool, [str(found.results[0].rel)])
    unscored = found.check.counts().get(judge_check.NOT_SCORED, 0) if found.check else 0
    pool = found.pool
    where = _read_from(found)
    label = ("Store:" if found.tool == "mlflow" else "Files:"
             if found.tool == "records" or "older file" in where else "File:")
    lines = [f"Eval tool:       {tool}", f"{label:<17}{where}"]
    if unscored and pool.answers:  # only answers with a grade are said to have one
        lines.append(f"Answers:         {_n(answers - unscored, 'answer')} with a grade "
                     f"({unscored} failed before scoring)")
    elif not pool.answers and not pool.unread:
        lines.append(f"Answers:         {_n(answers, 'answer')}, none with a clear grade")
    elif pool.split:  # repeats graded both ways each count: more to mark than answers
        lines.append(f"Answers:         {answers} to mark")
    else:
        lines.append(f"Answers:         {_n(answers, 'answer')}")
    if pool.answers and (pool.n_merged or pool.split):
        lines.append(INDENT + repeats_note(answers, pool))
    lines.append(f"LLM-as-a-judge:  {_judge_value(found)}")
    if found.model_refused and not found.models:  # so the column is not shown as read
        lines.append(f"{INDENT}The {found.model_refused} column holds no model's name.")
    lines += _rule_lines(found)
    rows = _not_said(read_rows(found, pass_if, mapped), said or [])
    if rows:
        width = max(len(k) for k, _ in rows) + 3
        lines.append("judgekeeper has read from your file:")
        lines += [f"  {k:<{width}}{v}" for k, v in rows]
    return lines


def _not_said(rows: list[tuple[str, str]], said: list[str]) -> list[tuple[str, str]]:
    """`rows` but those "How judgekeeper reads it" (`said`: "  what:   where" lines) already
    said: the same part, in words that start with the row's."""
    how = {}
    for line in said:
        what, _, where = line.strip().partition(":")
        how[what] = where.strip()
    return [(what, where) for what, where in rows if not how.get(what, "").startswith(where)]


def read_rows(found: start.Found, pass_if: str | None = None,
              mapped: settings.StartSettings | None = None) -> list[tuple[str, str]]:
    """What was read from the file, as (what, where) rows: the question, the answer, the
    grade (with the pass mark when there is one), then the reason, model, version and your
    labels when the file has them."""
    pm = found.pass_mark
    mark = f": {start.pass_at(pm)}" if pm else ""
    if found.tool == "promptfoo":  # with no vars, the prompt it was asked (in `prompts:`)
        prompt = {isinstance(a.input, str) for a in found.pool.answers}
        asked = {frozenset({True}): "each test's prompt",
                 frozenset({True, False}): "each test's vars, or its prompt"}.get(
                     frozenset(prompt), "each test's vars")
        return [("question", asked), ("answer", "each test's output"),
                ("grade", "your LLM-as-a-judge's Pass or Fail" + mark)]
    if found.tool == "deepeval":
        return [("question", "each test case's input"),
                ("answer", "each test case's actual_output"),
                ("grade", f"the {found.metric} score{mark}"),
                ("reason", "your LLM-as-a-judge's reason")]
    if found.tool == "inspect":
        grade = f"the scorer's score{mark}" if pm else "the scorer's grade (C or I)"
        return [("question", "each sample's input"), ("answer", "each sample's output"),
                ("grade", grade)]
    if found.tool == "mlflow":
        return [("question", "each trace's request"), ("answer", "each trace's response"),
                ("grade", "your LLM-as-a-judge's assessment" + mark)]
    if found.tool == "records":
        return [("question", "each line's input"), ("answer", "each line's output"),
                ("grade", "each line's label" + mark)]
    if found.tool == "table":
        columns = find.table_columns(found.results[0].path)
        verdict = found.metric if found.metric in columns else next(
            (c for c in find.VERDICT_COLUMNS if c in columns), "verdict")
        grade = (f"the score column{mark}" if pass_if and "score" in columns
                 else f"the {verdict} column{mark}")
        rows = [("question", "the input column"), ("answer", "the output column"),
                ("grade", grade)]
        model = next((c for c in ("judge_model", "model") if c in columns), None)
        if not found.models or found.model_source:  # the column was not what was read
            model = None
        labels = next((c for c in start.HUMAN_COLUMNS if c in columns), None)
        for what, column in (("reason", "reason" if "reason" in columns else None),
                             ("model", model),
                             ("version", "app_version" if "app_version" in columns else None),
                             ("your labels", labels)):
            if column:
                rows.append((what, f"the {column} column"))
        return rows
    if found.tool == "mapped":  # the map made in this run, else judgekeeper.toml's
        saved = mapped if mapped is not None and mapped.map else start._saved(found.root)
        m = saved.map if saved is not None and saved.map else None
        if not m:
            return []
        from judgekeeper import mapper

        sides = list(m.get("sides") or [])
        judge = saved.judge if saved.judge not in (None, "*") else (m.get("judges") or [None])[0]
        side = sides[0] if sides else None
        answer = (" and ".join(mapper.filled(m["output"], s) for s in sides) if sides
                  else mapper.filled(m["output"]))
        rows = [("question", mapper.filled(m["input"])), ("answer", answer),
                ("grade", mapper.filled(m["score"], side, judge) + mark)]
        if found.fingerprint.get("model_source") == start.GIVEN_BY_YOU and m.get("model_key"):
            rows.append(("model", f"{found.fingerprint['model']} (given with --judge-model)"))
        elif m.get("model_key"):
            rows.append(("model", mapper.filled(m["model_key"], side, judge)))
        return rows
    return []


def _free_check(talk: FrontTalk, found: start.Found, listed: str) -> None:
    """The free checks, each a paragraph starting "Checked:": what was found, where its list
    is, then what can change the judge without judgekeeper seeing it."""
    block = found.check.block() if found.check else None
    findings = [" ".join(f) for f in judge_check.lines(block)]
    if not findings:
        talk.para(FREE_CHECK + EVERY_ANSWER)
    for finding in findings:
        talk.para(FREE_CHECK + finding[:1].lower() + finding[1:])
    if findings and judge_check.has_rows(block):
        talk.para(f"The list is in {listed}.")
    for line in judge_check.setup_lines(found, judge_setup.of(found)):
        talk.para(line)


def _say(talk: FrontTalk, found: start.Found, mapped: settings.StartSettings | None,
         wait: bool) -> int:
    """Found, no marking started: the "Find" block and the free checks, then the page."""
    if talk.counts_wait():  # the counts depend on the answers: they come after them
        _to_save(talk, found, mapped)  # noted with the others, so --yes answers it too
        talk.ask_noted()
    listed = _listed(found)
    talk.say()  # a blank line after what Find said first (a file left out), never two
    for line in found_block(found, talk.options["pass_if"], mapped,
                            getattr(talk, "how_said", None) if mapped is not None else None):
        _say_found(talk, line)
    if found.tool == "table" and _columns_line(found, talk.options["pass_if"]):
        talk.para(SCORE_READ)
    talk.say()
    _say_path(talk, found)
    pool = found.pool
    if pool.answers:
        talk.say(passed_failed(pool.n_pass, pool.n_fail))
    for note in _notes(found, None if talk.labels is not None else talk.command("--labels")):
        talk.few_fails = talk.few_fails or note.startswith(FAILED_ONLY)
        talk.para(note)
    left = _results_too(talk.left_below) if talk.left_below else None
    for others in (_other_files(found, talk), _other_projects(found), _nested_here(found),
                   left, _outer_marks(found), _kept_apart(found)):
        if others:
            talk.para(others)
    _free_check(talk, found, listed)
    if not pool.answers:
        talk.ask_noted()
        _write(found)
        talk.say()
        raise _nothing_to_mark(talk, found, None)  # the free check said where the list is
    new = _to_save(talk, found, mapped)
    talk.ask_noted()  # without a terminal, nothing is written before they are answered
    _write(found)
    saved = new is not None and _save(talk, found, new, made=mapped is not None)
    n = len(pool.answers)
    if targets.few_answers(pool.n_pass, pool.n_fail):
        talk.say()
        talk.para(f"You have {_n(n, 'answer')} with a clear grade. That is not enough answers "
                  "for a first result.")
        ws = Workspace(found.root)
        if (ws.dir / judge_setup.FILE).is_file():  # nothing else is written before marking
            talk.para(SAVED_SETUP.format(folder=shown_folder(ws)))
        raise talk.stop(EXIT_QUESTION, (
            f"mark these {n} now with "
            f"`{_command_of(talk, saved, 'mark')}`. Your marks are kept. Then run your eval to "
            f"make more answers (that makes model calls), and run `{talk.command()}` again."))
    talk.say()
    return _marking(talk, Workspace(found.root), found, wait, saved, marking=False, first=True)


def _nothing_to_mark(talk: FrontTalk, found: start.Found, listed: str | None) -> Stop:
    """No answer has a clear Pass or Fail: the person fixes the judge and runs the eval
    again (exit 3)."""
    kinds = {kind for kind, _ in found.pool.left.values()}
    if kinds == {judge_check.MODEL_FAILED}:  # the model under test failed, not the judge
        talk.para(judge_check.ALL_MODEL_FAILED)
        if listed:
            talk.para(f"The list is in {listed}.")
        return talk.stop(EXIT_QUESTION, judge_check.MODEL_FAILED_NEXT.format(
            command=talk.command()))
    failed = kinds == {judge_check.ERROR}
    talk.para("Your LLM-as-a-judge's calls failed on every answer, so there is nothing to mark."
              if failed else "No answer has a clear Pass or Fail from your LLM-as-a-judge, so "
                             "there is nothing to mark.")
    if listed:
        talk.para(f"The list is in {listed}.")
    fix = "fix your LLM-as-a-judge's calls" if failed else "fix your LLM-as-a-judge"
    return talk.stop(EXIT_QUESTION, f"{fix}, run your eval again, then run "
                                    f"`{talk.command()}`.")


def answered(talk: FrontTalk, saved: bool) -> tuple[str, dict]:
    """(the path, the options): the flags given, and the answers given at a terminal unless
    judgekeeper.toml keeps them now."""
    options = dict(talk.options)
    path = talk.path
    if not saved:
        options.update({ASKED[f]: v for f, v in talk.answers.items() if f in ASKED})
        if talk.store is not None:
            path = str(Path(path) / talk.store) if path != "." else talk.store
    return path, options


def _command_of(talk: FrontTalk, saved: bool, subcommand: str = "") -> str:
    """judgekeeper's `subcommand` with the flags given, and the answers given at a terminal
    unless judgekeeper.toml keeps them now. The page and result.json keep them as data
    instead (_flags_of)."""
    path, options = answered(talk, saved)
    return " ".join((program(subcommand), *start.repeated_flags(path, **options)))


def _flags_of(talk: FrontTalk, saved: bool, ws: Workspace) -> dict:
    """What result.json and the page keep of the command (start.run_flags): the flags
    `_command_of` writes, as data, each path in them from the project folder (kept_path):
    the commands they make run there, and a file names no folder outside it."""
    path, options = answered(talk, saved)
    if path != ".":
        path = kept_path(path, ws.root)
    if options.get("tracking_uri"):
        options["tracking_uri"] = _kept_uri(str(options["tracking_uri"]), ws.root)
    return start.run_flags(path, **options)


def _back(talk: FrontTalk, saved: bool) -> dict | None:
    """How to come back to the page as typed here (start.saved_back), for its footer: the
    path given, from here (never a whole path), and the program as typed here. None when the
    path can't be said from here (another drive)."""
    path = answered(talk, saved)[0]
    if path != "." and (os.path.isabs(path) or textio.through_top(path)):
        try:
            path = os.path.relpath(os.path.abspath(path))
        except ValueError:
            return None
    return {"path": path, "program": program()}


def _kept_uri(uri: str, root: Path) -> str:
    """An MLflow store as result.json keeps it: a whole path in it (as it is, or after
    sqlite:///) from the project folder; any other store as given."""
    sqlite = "sqlite:///"
    rest = uri.removeprefix(sqlite)
    if "://" in rest or not os.path.isabs(rest):
        return uri
    return (sqlite if uri.startswith(sqlite) else "") + kept_path(rest, root)


def _to_save(talk: FrontTalk, found: start.Found,
             mapped: settings.StartSettings | None) -> settings.StartSettings | None:
    """What judgekeeper.toml keeps after a yes, for what had to be asked: a map, or the
    answers at a terminal. None when there is nothing to keep or the person says no."""
    if mapped is None and not talk.answers:
        return None
    if mapped is not None:
        new, question = mapped, SAVE_MAP.format(  # named as File: names it
            file=textio.shown_in(Path(found.root) / mapped.file, found.root))
    else:
        try:
            new = settings.load(found.root) or settings.StartSettings(source=found.tool)
        except settings.SettingsError as e:
            raise StartError(str(e)) from None
        new.source = found.tool
        if "--metric" in talk.answers:
            new.judge = found.metric
        if found.tool == "mlflow":
            new.file = talk.store or new.file
        if found.tool in ("deepeval", "inspect") and talk.store is not None:  # which folder
            new.file = talk.store
            new.experiment = talk.answers.get("--experiment", new.experiment)
        question = SAVE
    talk.say()
    if not talk.confirm(question, default=True, with_yes=True, hint=""):
        if mapped is None:
            return None
        _write(found)
        talk.para(f"Nothing was saved: judgekeeper reads "
                  f"{textio.shown_in(Path(found.root) / mapped.file, found.root)} only once "
                  "judgekeeper.toml says how.")
        raise talk.stop(EXIT_OK, f"run `{program()}` again and answer yes.", as_given=True)
    return new


def _save(talk: FrontTalk, found: start.Found, new: settings.StartSettings,
          made: bool) -> bool:
    """Write judgekeeper.toml (`made`: with a map made now). Returns True: it keeps the
    answers now."""
    try:
        settings.save(found.root, new)
    except settings.SettingsError as e:
        talk.say(f"{e}. Add this to {settings.FILE} yourself:")
        for line in settings.render(new).splitlines():
            talk.say(f"  {line}")
        raise talk.stop(EXIT_QUESTION, f"add the lines above to {settings.FILE}, then run "
                                       f"`{program()}` again.") from None
    talk.say(f"Saved {settings.FILE} (where your LLM-as-a-judge's results are and how to read "
             "them).")
    if made:  # judgekeeper.toml keeps the judge, its model and pass mark now
        for name in ("metric", "pass_if", "judge_model"):
            talk.set(name, None)
    return True


# Marking: the page, the count, the result -------------------------------------------------

def _go_on(talk: FrontTalk, found: start.Found, mapped: settings.StartSettings | None,
           wait: bool, marking: bool) -> int:
    """Marking started (or `judgekeeper mark`): start over when the marks are for another
    judge, else go on with the marks."""
    to_save = _to_save(talk, found, mapped) if mapped is not None or not marking else None
    ws = Workspace(found.root)
    start_label.refuse_links(ws)
    why = _why_start_over(talk, ws, found)
    if not found.pool.answers and (why is not None or not ws.start.is_file()):
        talk.ask_noted()
        raise _nothing_to_mark(talk, found, None)
    over = why is not None
    if over and _has_marks(ws):  # else nothing to lose: start over without asking
        for line in why:
            talk.para(line)
        over = talk.confirm(START_OVER, default=True, with_yes=True, hint="")
    talk.ask_noted()  # without a terminal, nothing is written or moved before the answers
    saved = to_save is not None and _save(talk, found, to_save, made=mapped is not None)
    if why is not None and not over:
        talk.say("Nothing was moved.")
        raise talk.stop(EXIT_OK, f"nothing. Your old marks stay in {FOLDER}/.")
    if why == [] and talk.new and not _has_marks(ws) and not _changed(ws, found):
        talk.para("You haven't marked any answers yet, so `--new` has nothing to move.")
        talk.new = False  # done: the command to go on is without it
        talk.refresh()
        raise talk.stop(EXIT_OK, f"run `{talk.command()}` to start marking.", as_given=True)
    if over:
        if is_open(ws.dir):
            background.stop(ws.dir)
        _move_aside(talk, ws)
    _write(found)  # judge.json and the free checks: the judge as it is now
    return _marking(talk, ws, found, wait, saved, marking)


def _has_marks(ws: Workspace) -> bool:
    """Whether .judgekeeper/ holds marks that count (a labels.csv file counts too)."""
    if ws.labels.is_file():
        return True
    try:
        return ws.marks.is_file() and bool(marks.read(ws.marks).counted())
    except (OSError, ValueError):
        return True  # unreadable: ask, so nothing moves without a yes


def _why_start_over(talk: FrontTalk, ws: Workspace, found: start.Found) -> list[str] | None:
    """Why the marks saved in .judgekeeper/ can't be used for this judge, in lines; [] for
    --new on marks that could be, or for a judge set up otherwise (another --pass-if, say)
    before anything is marked; None when marking can go on. A new eval run is no reason:
    the answers being marked are kept in pool.jsonl."""
    if ws.labels.is_file():
        return [OLD_MARKS]
    if not ws.start.is_file():
        return None
    try:
        data = ws.data()
        tool, metric, judge = data["tool"], data["metric"], data["judge"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"judgekeeper can't read {FOLDER}/start.json, so the marks there can't be used."]
    if (found.tool, scrub(found.metric)) != (tool, scrub(metric)):  # start.json's, keys hidden
        return [(f"Your marks are for another LLM-as-a-judge: {judge} ({tool}). These "
                 f"results are from {found.judge}.")]
    if not _has_marks(ws) and _changed(ws, found):  # nothing marked yet: read them anew
        return []
    return [] if talk.new else None


def _checked_file(ws: Workspace, found: start.Found) -> str | None:
    """The file the last check read (check.last_read_file), named from here; else None."""
    from judgekeeper import check as checking

    path = checking.last_read_file(ws, [r.path for r in found.results])
    return None if path is None else textio.line_path(path)


def _regraded_line(talk: FrontTalk, ws: Workspace, found: start.Found, k: int) -> str:
    """REGRADED: the newest file read, `k`, whose grades the numbers use, and the check that
    compares them, as the Next line gives it."""
    return REGRADED.format(file=_newest(found), k=k, numbers=_sentence(_graded_in(ws, found)),
                           command=_compare_command(talk, ws))


def _sentence(words: str) -> str:
    return words[:1].upper() + words[1:]


def _graded_in(ws: Workspace, found: start.Found) -> str:
    """Whose grades the numbers use: the results file(s) the marks were checked with
    (start.json's, as result.json names them), named from here; "from before" when the
    newest file read is one of them, graded again in place: it holds them no more."""
    data = ws.data()
    base = start.results_path(ws.root, data)
    base = base if base.is_dir() else base.parent
    files = [base / f for f in data.get("results_files") or [] if isinstance(f, str)]

    def same(file: Path) -> bool:
        try:
            return os.path.samefile(file, found.results[0].path)
        except OSError:
            return False

    if not files or any(same(f) for f in files):
        return NUMBERS_BEFORE
    return NUMBERS_IN.format(old=" and ".join(textio.shown_in(f, found.root) for f in files))


def _graded_files(ws: Workspace, found: start.Found) -> str | None:
    """The results file(s) the marks were checked with, named from here (_graded_in), when
    the newest file read is not one of them; else None."""
    said = _graded_in(ws, found)
    return said.removeprefix(NUMBERS_IN.format(old="")) if said != NUMBERS_BEFORE else None


def _ran_again(ws: Workspace, found: start.Found) -> bool:
    """Whether the newest results differ from the ones being marked, with marks made: other
    files (by where they are, not how they were named) or other grades. No marks yet: nothing
    to say."""
    try:
        data = ws.data()
        marked = {q["id"]: q["group"] for q in data["queue"]}
        files = [f for f in data.get("results_files") or [] if isinstance(f, str)]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if data.get("results_seen") == batches.results_key(found):  # said, or added as a batch
        return False
    if not _has_marks(ws):
        return False
    return (not _same_files(ws, data, files, found)
            or marked != {a.id: a.verdict for a in found.pool.answers})


def _same_files(ws: Workspace, data: dict, files: list[str], found: start.Found) -> bool:
    """Whether `files` (start.json's, from the folder its results were read in) are the files
    `found` read, however each run named them: the same label, or the same file on disk."""
    if files == list(found.used):
        return True
    base = start.results_path(ws.root, data)
    base = base if base.is_dir() else base.parent

    def path_of(label: str) -> Path | None:  # a label is a file's path from where it was read
        paths = [r.path for r in found.results if r.rel == label or r.rel.endswith("/" + label)]
        return paths[0] if len(paths) == 1 else None

    try:
        return len(files) == len(found.used) and all(
            f == u or ((path := path_of(u)) is not None
                       and os.path.realpath(base / f) == os.path.realpath(path))
            for f, u in zip(files, found.used, strict=True))
    except (OSError, ValueError, TypeError):
        return False


def _marking(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool, saved: bool,
             marking: bool, first: bool = False) -> int:
    """The pool (prepared now unless it is there), then the page and the count, or for
    `judgekeeper` with enough marks the result."""
    from judgekeeper import check

    if not ws.start.is_file():
        with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one writes the pool
            if not ws.start.is_file():
                start_label.prepare(found, say=lambda line: None)
    # first: repair would make it again too, with the old run's flags and without a word
    again = start_label.recompute_old(ws, flags=_flags_of(talk, saved, ws))  # this run's
    start_label.repair(ws)  # a result whose saving was stopped half way
    head = [start_label.WORKED_OUT_AGAIN] if again else []
    newest = None if first else _newest_line(ws, found)
    if newest:
        head.append(newest)
    if not first and _model_given(talk, ws, found):  # the same judge: no change
        head.append(MODEL_WRITTEN.format(model=found.fingerprint["model"]))
    # A newer file the last check read, which the search never finds: its result stays,
    # unless the file is typed (then it is the one to read, and may go back to the marked judge)
    typed = Path(talk.path).is_file() or find.is_mlflow_folder(Path(talk.path))
    elsewhere = None if first or typed else _checked_file(ws, found)  # older results here
    closed: list[str] = []  # the marking page it closes: said by a plain run, not by `mark`
    back = None if first or elsewhere else check.back_to_marked(ws, found, talk.say,
                                                                closed=closed)
    elsewhere = elsewhere or (None if first or back else _checked_file(ws, found))
    changed = [] if first or back or elsewhere else _changed(ws, found)
    held = not (first or changed or back or elsewhere) and found.rule is not None and \
        check.open_worse(ws, found, held=True) is not None  # a same-rule "Worse" stays
    grades = (0 if first or changed or back or elsewhere
              else check.grades_changed(ws, found, ruled=held))  # a table judge, or held
    regraded = (check.grades_changed(ws, found, ruled=True)
                if not (first or changed or back or elsewhere or grades)
                and found.rule is not None and found.results else 0)
    if regraded:  # the grades the numbers use are not the ones read: which, and the check
        head[:] = [x for x in head if x != newest]  # that compares them, as Next gives it
        head.append(_regraded_line(talk, ws, found, regraded))
    added, took, added_at = 0, None, None
    about = elsewhere  # the file the numbers are about, when not the one read (path_lines)
    if not (first or changed or back or grades or elsewhere):
        with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one adds the batch
            added = batches.add(ws, found)
        took = check.take_new_grades(ws, found)  # grades on answers left that waited
    then = None  # new answers that came with changed grades: they wait, and the next step
    if back:
        head.append(back)  # the judge marked on
        if not marking and closed:
            head.extend(["", *closed])  # a paragraph of its own
    elif elsewhere:  # the result is about that file, not the one read here
        head[:] = [x for x in head if x != newest]
        head.append(CHECKED_FILE.format(file=elsewhere))
        if typed:  # an older file typed: every command given names the file the result is about
            talk.path = elsewhere
    elif changed or grades:  # grades only `check` takes on: whose grades the numbers use
        kept_worse = held or check.open_worse(ws, found, held=True) is not None  # any judge
        if kept_worse or not changed:  # the file read is named in the line itself
            head[:] = [x for x in head if x != newest]
        if kept_worse:  # that check, not one to run
            head.append(JUDGE_CHANGED.format(what=", ".join(changed)) if changed
                        else (check.SAME_RULE_GRADES if held else check.GRADES).format(k=grades))
            head.append(HELD_WORSE.format(file=_newest(found), numbers=_graded_in(ws, found)))
        elif changed:
            head.append(JUDGE_CHANGED.format(what=", ".join(changed)))
            head.append(_sentence(_graded_in(ws, found)) + ".")
        else:  # a table graded again
            head.append(_regraded_line(talk, ws, found, grades))
        then = _waiting(talk, ws, found, head, bool(changed))
    elif added:
        added_at = len(head)
        head.append(batches.added_line(added))
        if talk.labels is None and (n := _new_labels(ws, found)):  # later runs say no Find
            head.append(labels_mod.found_line(n, talk.command("--labels")))
        if is_open(ws.dir):  # the page open shows the pool without the new batch
            background.stop(ws.dir)
    elif not first and not regraded and _ran_again(ws, found):
        if not (found.pool.n_pass or found.pool.n_fail):  # nothing was graded again
            head.append(NO_GRADES_HERE.format(numbers=_graded_in(ws, found)))
            about = _graded_files(ws, found)
            newest = head[-1]  # "It" is the file read: the path line comes after it
        else:
            head.append(RAN_AGAIN if not ws.data().get("checked_at")
                        else RAN_AGAIN_KEPT if check.last_check(ws) else RAN_AGAIN_CHECKED)
        batches.seen(ws, found)  # said once
    # which path and why: said first, after NEWEST or READING, of the file the result is about
    at = head.index(newest) + 1 if newest and newest in head else int(bool(again))
    talk.path_head = _path_head(talk, found, about)
    head[at:at] = talk.path_head
    if added_at is not None and added_at >= at:  # the added line moved down with them
        added_at += len(talk.path_head)
    if took:
        head.append(took)
    with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one writes the marks
        _import_labels(talk, ws, found, first)
    session = StartSession(ws)
    if added_at is not None:  # --labels may have marked some of them just now
        unseen = _unmarked_newest(ws, session)
        if not unseen:
            del head[added_at]
        elif unseen != added:
            head[added_at] = batches.added_line(unseen)
    if unreadable := marks.unreadable_line(marks.read(ws.marks)):
        head.append(unreadable)
    if lost := start_label.lost_marks_line(ws):
        head.append(lost)
    counts = session.counts()
    enough = start_label.has_result(batches.counted_strata(
        ws.data(), batches.graded(ws.data(), session.marked())))
    every = bool(session.items) and all(i["label"] for i in session.items)
    if enough and not marking:
        return _result(talk, ws, found, wait, saved, head, check=bool(changed or grades),
                       elsewhere=bool(elsewhere), compare=bool(regraded),
                       worse_said=any(x.startswith(HELD_WORSE[:20]) for x in head))
    if not enough and ws.result_json.is_file():  # a mark taken back since: no result now
        start_label.store_result(ws, session, _flags_of(talk, saved, ws))
    if every and not enough:  # nothing left to mark, and no result yet
        return _all_marked(talk, ws, counts, saved, head, then)
    return _page(talk, ws, counts, wait, saved, enough, head, marking, first, then)


def _new_labels(ws: Workspace, found: start.Found) -> int:
    """How many human labels in the results (Pool.humans) are for the newest batch's answers."""
    of = batches.of(ws.data())
    last = max(of.values(), default=1)
    new = {labels_mod._base(i) for i, batch in of.items() if batch == last}
    return sum(key in new for key, _, _ in found.pool.humans)


def _waiting(talk: FrontTalk, ws: Workspace, found: start.Found, head: list[str],
             changed: bool) -> str | None:
    """New answers in the newest results that came with changed grades join no batch: the
    line that says they wait goes in `head`; the next step once every answer is marked
    (`judgekeeper check`, or after a "Worse" check.worse_step). None when there are none."""
    from judgekeeper import check

    n = len(batches.new_answers(ws, found))
    if not n:
        return None
    was = check.open_worse(ws, found)
    head.append(batches.waiting_line(n, changed, worse=was is not None))
    return (check.worse_step(was["before"], was["after"], _check_command(talk), ws) if was
            else _recheck_step(talk, ws))


def _all_marked(talk: FrontTalk, ws: Workspace, counts: dict, saved: bool,
                head: list[str], then: str | None = None) -> int:
    """Every answer is marked and a kind is still short: said, and no page (exit 3)."""
    talk.say(STEP.format(n=2, name="Mark"))
    talk.say()
    _say_head(talk, head)
    first, step = _all_marked_lines(talk, ws, counts, saved)
    talk.para(first)
    if (waits := _waits(ws, StartSession(ws))) is not None:  # no eval run on more helps
        _say_waits(talk, waits)
        step = _wait_step(ws)
    raise talk.stop(EXIT_QUESTION, then or step.removeprefix("Next: "))


def _waits(ws: Workspace, session: StartSession) -> dict | None:
    """The result (start_label.compute) when marks wait or a new mark could only wait
    (only_wait): what Measure says then, `mark` says too. None otherwise."""
    data = ws.data()
    if not (data.get("earlier_grades") or batches.waiting(data, session.marked())):
        return None  # a mark waits only on an answer the judge now never graded
    try:
        r = start_label.compute(ws, session)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return r if r.get("waiting") or r.get("only_wait") else None


def counted_line(so_far: str, counted: list[str], waiting: int) -> str:
    """The marks so far, when some wait: those that count (with their Pass and Fail) and those
    that wait, each said in the singular for one."""
    one = len(counted) == 1
    return (f"{so_far} so far. {len(counted)} {'counts' if one else 'count'} for a result "
            f"({counted.count('pass')} Pass, {counted.count('fail')} Fail). "
            f"{waiting} more {'waits' if waiting == 1 else 'wait'} and "
            f"{'doesn' if waiting == 1 else 'don'}'t count yet.")


def _say_waits(talk: FrontTalk, r: dict) -> None:
    """The wait lines, as Measure says them."""
    from judgekeeper import check as checking

    if r.get("waiting"):
        talk.para(checking.WAIT.format(k=r["waiting"]))
    if r.get("wait_group") or r.get("only_wait") and not r.get("waiting"):
        talk.para(checking.no_grade_left(r))


def _wait_step(ws: Workspace) -> str:
    from judgekeeper import check as checking

    return "Next: " + checking.WAIT_NEXT.format(run=checking.wait_run(ws))


def _say_head(talk: FrontTalk, head: list[str]) -> None:
    """The lines under a step's header, each a paragraph ("" a blank line), then a blank
    line."""
    for line in head:
        if line:
            talk.para(line)
        else:
            talk.say()
    if head:
        talk.say()


def _all_marked_lines(talk: FrontTalk, ws: Workspace, counts: dict, saved: bool) -> list[str]:
    labels = {"correct": counts["correct"], "wrong": counts["wrong"]}
    return start_label.all_marked_lines(labels,
                                        start_label.mark_command(_command_of(talk, saved)),
                                        ws.data().get("pool"))


def _kept(talk: FrontTalk, opened: page.Page, shown: str, after: str) -> bool | None:
    """Said for a page that was open already, which gets no new tab: that it is open, and with
    no terminal (no link printed) how to print its link. None for any other page."""
    if not opened.kept or talk.options["no_browser"]:
        return None
    talk.para(f"{IN_BROWSER} {after}".rstrip())
    if shown == page.KEPT:
        talk.para(CLOSED_IT.format(command=talk.command("--no-browser")))
    return True


def _open(talk: FrontTalk, ws: Workspace, wait: bool, saved: bool,
          result: bool = False) -> tuple[page.Page, str]:
    """A new page (the open one closed), shown: (the page, how it was shown). `result`:
    opened at its result page."""
    start_label.check_writable(ws)  # said here, never as "the page could not start"
    opened = None
    try:
        opened = page.open_new(ws, talk.options["port"], _flags_of(talk, saved, ws), here=wait,
                               say=talk.para, back=_back(talk, saved))
        shown = opened and page.show(talk.say, opened, talk.options["no_browser"], wait,
                                     result)
    except KeyboardInterrupt:  # before its link was printed: no page is left running
        page.close(ws, opened)
        raise
    asked = talk.options.get("port")
    if opened is not None and opened.kept and asked not in (None, 0, DEFAULT_PORT) and (
            asked != opened.port):
        talk.para(PORT_KEPT.format(port=opened.port, asked=asked))
    if not shown:
        if opened is not None and opened.server is None:
            background.stop(ws.dir)
        tried = page.choose_port(talk.options["port"], lambda line: None)
        if opened is None and not page.port_free(tried):  # --wait would need the same port
            path, options = answered(talk, saved)
            command = " ".join((program(), *start.repeated_flags(path, **{**options,
                                                                          "port": 0})))
            if is_page(tried):  # another project's page (its name needs its token): close it
                talk.para(PORT_PAGE.format(port=tried))
                with textio.run_from(textio.ANYWHERE):  # its folder can't be named
                    stop = program("--stop")
                raise talk.stop(EXIT_QUESTION, NEXT_STOP_THERE.format(stop=stop,
                                                                      command=command))
            talk.say(PORT_TAKEN.format(port=tried))
            raise talk.stop(EXIT_QUESTION, NEXT_ANY_PORT.format(command=command))
        talk.say(f"The marking page could not start in the background (what went wrong is in "
                 f"{link(ws.dir / background.LOG, f'{shown_folder(ws)}/{background.LOG}')}).")
        raise talk.stop(EXIT_QUESTION, COULD_NOT.format(command=talk.command("--wait")))
    return opened, shown


def _page(talk: FrontTalk, ws: Workspace, counts: dict, wait: bool, saved: bool,
          enough: bool, head: list[str], marking: bool, first: bool,
          then: str | None = None) -> int:
    """Step 2: the count so far and the page, opened in the browser (its link printed with
    --no-browser). `judgekeeper` again before a first result keeps a page that is still open
    (its tab still works); `mark`, and --no-browser, show it again with the same link
    (page.open_new)."""
    n_pass, n_fail = counts["correct"], counts["wrong"]
    n = n_pass + n_fail
    session = StartSession(ws)
    items = session.items
    command = _command_of(talk, saved)
    if marking and n and n == len(items):
        talk.say(STEP.format(n=2, name="Mark"))
        talk.say()
        head = _path_first(talk, head)  # its other head lines come after the count
        some_imported = marks.imported(marks.read(ws.marks), ids=set(session.by_id))
        talk.say(marked_all(n, "marks on" if some_imported else "marked"))  # imported: not marked
        waits = _waits(ws, session)
        if waits is not None:  # the step is grading them again, not more questions
            _say_waits(talk, waits)
        talk.say()
        _say_head(talk, head)
        # disagreements the person can see: the result page, with its reason boxes (and its
        # link to change a mark); else the marking page, where a mark can always be changed
        if start_label.why_count(ws, start_label.compute(ws, session)):
            opened, shown = _open(talk, ws, wait, saved, result=True)
            why = f"{SAY_WHY} {CHANGE_ON_RESULT}"
            if _kept(talk, opened, shown, why) is None:
                talk.para(f"{RESULT_OPEN} {why}" if shown == page.BROWSER else why)
        else:
            opened, shown = _open(talk, ws, wait, saved)
            if _kept(talk, opened, shown, CHANGE_MARK) is None:
                talk.para(f"The marking page is open in your browser. {CHANGE_MARK}"
                          if shown == page.BROWSER else CHANGE_MARK)
        if opened.server is not None:
            talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
        talk.say()
        talk.para("Next: " + then if then  # the new answers wait for a check
                  else _wait_step(ws) if waits is not None
                  else _all_marked_lines(talk, ws, counts, saved)[1])  # they join later
        if opened is not None and opened.server is not None:
            page.serve(opened.server)
        return EXIT_OK
    talk.say(STEP.format(n=2, name="Mark (more answers)" if marking and enough else "Mark"))
    talk.say()
    _say_head(talk, head)
    waits = _waits(ws, session) if n else None  # no line asks for a mark that can only wait
    if n:
        counted = list(batches.counted_labels(ws.data(), session.marked()).values())
        waiting = n - len(counted)
        so_far = (_n(n, 'mark')  # some came with --labels: not marked here
                  if marks.imported(marks.read(ws.marks), ids=set(session.by_id))
                  else f"You marked {_n(n, 'answer')}")
        if waiting:  # the counts before "not enough" are those that count, never the waiting
            talk.para(counted_line(so_far, counted, waiting))
        else:
            talk.say(f"{so_far} so far: {n_pass} Pass, {n_fail} Fail.")
        if not enough:  # and why: what a result needs (also after an import came first)
            talk.say(NOT_ENOUGH)
            _needs_each_kind(talk, session)
            if min(n_pass, n_fail) >= targets.ROUGH:  # what is missing: the groups' marks
                talk.para(_group_marks(session))
            if skipped := _only_skipped(session) if waits is None else 0:
                talk.para(start_label.only_skipped(skipped))
        elif waits is None and (gate := _import_gate(ws, session)):  # as the result says it
            talk.para(gate)
        if waits is not None:
            _say_waits(talk, waits)
        talk.say()
    after = "" if waits is not None else PRECISE if enough else BAR if n else SHOWS
    if not n:  # marking starts: what a result needs, before the page opens
        _needs_each_kind(talk, session)
        talk.say()
    opened = None
    no_browser = talk.options["no_browser"]  # its link is printed again: a new page
    if not first and not marking and not wait and not no_browser and n and is_open(ws.dir):
        talk.para(f"The marking page is still open in your browser. {after}".rstrip())
    else:
        opened, shown = _open(talk, ws, wait, saved)
        again = " again" if n and not marking else ""
        if _kept(talk, opened, shown, after) is None and (shown == page.BROWSER or after):
            talk.para(f"The marking page is open in your browser{again}. {after}".rstrip()
                      if shown == page.BROWSER else after)
        if opened.server is not None:
            talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    talk.say()
    next_step = NEXT_MORE if enough else NEXT_MARK
    out_of_reach = not enough and side_out_of_reach(**_each_kind(session))
    too_few = not enough and start_label.few_answers(session)
    few = out_of_reach or too_few  # exit 3
    if not enough and n and waits is None and (skipped := _only_skipped(session)):
        next_step = start_label.next_only_skipped(  # the page that marks it: `mark`
            skipped, _command_of(talk, saved, "mark"), on_page=marking
        ).replace("{", "{{").replace("}", "}}")
    elif out_of_reach:  # as FAILS_OUT_OF_REACH says
        next_step = start_label.NEXT_ALL_MARKED
    elif too_few:  # no link can appear
        next_step = NEXT_FEW_ANSWERS.format(n=len(session.items), min=start.MIN_POOL,
                                            command=_command_of(talk, saved, "mark")
                                            ).replace("{", "{{").replace("}", "}}")
    if opened is not None and opened.server is not None:
        page.serve(opened.server)  # Ctrl-C here: "Stopped." and its own Next line (cli)
        if getattr(opened.server, "stopped", False):  # --stop closed it: no link is open
            next_step, waits = NEXT_CONTINUE, None
    talk.para(_wait_step(ws) if waits is not None
              else "Next: " + next_step.format(command=command))
    return EXIT_QUESTION if few else EXIT_OK  # too few answers: as fix and check exit


def _pct(x: float) -> str:
    return percent(x)


def marked_all(n: int, did: str) -> str:
    """The person's marks cover all `n` answers (`did`: "marked", or "marks on")."""
    return f"You have {did} the one answer." if n == 1 else f"You have {did} all {n} answers."


def agreed_all(n: int) -> str:
    what = "the one answer" if n == 1 else f"all {n} answers"
    return f"You and your LLM-as-a-judge agreed on {what}."


def agreement_lines(r: dict) -> list[str]:
    """Under the verdict, as on the result page: how many answers you and your judge
    disagreed on, then the two counts, indented; before a result, your two counts only."""
    from judgekeeper.report_page import counts

    c = counts(r)
    if r["check"] == "too_few":  # before a result, the person's own counts only (as the page)
        return [f"  You passed {_n(c['passed'], 'answer')}.",
                f"  You failed {_n(c['failed'], 'answer')}."]
    n, d = c["passed"] + c["failed"], c["strict"] + c["easy"]
    first = (f"You and your LLM-as-a-judge disagreed on {d} of {_n(n, 'answer')}." if d else
             agreed_all(n))
    return [first, "",
            (f"  You passed {_n(c['passed'], 'answer')}. Of those, your LLM-as-a-judge passed "
             f"{c['passed'] - c['strict']} and failed {c['strict']}."),
            (f"  You failed {_n(c['failed'], 'answer')}. Of those, your LLM-as-a-judge passed "
             f"{c['easy']} and failed {c['failed'] - c['easy']}.")]


def estimate_lines(r: dict, every: bool | None = None, pool: dict | None = None) -> list[str]:
    """How often the judge agrees with you, estimated, as the result page's score
    (report_page.estimate): "about 57% (between 37% and 74%)", also while it is too early to
    tell; "78% (you marked every answer)" with no width; too early to tell only with no number
    yet. `every` (every answer is marked) and `pool` (how many the judge passed and failed):
    as `r` says, by default."""
    from judgekeeper.report_page import estimate, why_for, why_no_range

    out, ranged = [], False
    for said, key in (("Pass", "tpr"), ("Fail", "tnr")):
        why = why_for(r, key) if every is None else why_no_range(key, every, pool)
        shown, between = estimate(r.get(key), r.get(f"{key}_interval"), why)
        ranged = ranged or between != "–" or shown.startswith("about ")  # almost exact too
        value = shown if between == "–" else f"{shown} (between {between})"
        out.append(f"  When you say {said}, it also says {said}: {value}")
    # with no range (every answer marked) the numbers are no estimates
    return [AGREES if ranged else AGREES.replace(" (estimates)", ""), *out]


def kappa_line(r: dict) -> str:
    """Kappa as the result page's score has it, with a plain minus sign: a legacy code
    page has no real one, and would print "?0.09" (textio.lenient_streams)."""
    from judgekeeper.report_page import kappa_shown

    shown, lo, hi = kappa_shown(r)
    value = shown if lo is None else f"about {shown} (between {lo} and {hi})"
    return KAPPA_LINE.format(value=value.replace("−", "-"))


def verdict_line(r: dict) -> str | None:
    """The one line on how good the judge is, "Result: ...", with the result page's
    headlines; None before a first result."""
    if r["verdict_level"] is None:
        return None
    verdict = r["verdict"]
    if start_label.all_labeled(r) or r.get("only_wait"):  # nothing left to mark that counts
        verdict = start_label.without_mark_more(verdict)
    return f"Result: {verdict[:1].lower()}{verdict[1:]}"


def _which_judge(ws: Workspace, found: start.Found) -> str | None:
    """When the judge's rule or model changed since marking started (or since the check that
    moved the marks to a new judge), or a check was held: which judge the result is about,
    as it was then."""
    from judgekeeper import check as checking

    data = ws.data()
    same_rule = rule_hash(data.get("rule")) == rule_hash(scrub(found.rule))  # as start.json
    now = scrub_fingerprint(found.fingerprint)  # as start.json keeps it
    if (same_rule and not judge_setup.judge_change(data["fingerprint"], now)
            and checking.open_worse(ws, found, held=True) is None):  # a held check: as it was
        return None
    head = marks.read(ws.marks).header or {}
    checked = data.get("checked_at")  # the judge a check moved the marks to (check._adopt)
    judge = (start_label.judge_of(data) if checked else None) or head.get("judge") or \
        start_label.judge_of(data)
    try:
        made = datetime.strptime(checked or head.get("created_at") or data.get("started_at") or "",
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
        day = f" on {made.day} {MONTHS[made.month - 1]}"
    except ValueError:
        day = ""
    model = judge.get("model") or "model not named"
    rule = judge.get("rule_hash")
    rule = f"rule ID {rule.removeprefix('sha256:')[:4]}" if rule else "rule not known"
    return f"This result is about your LLM-as-a-judge as it was{day}: {model}, {rule}."


def _check_command(talk: FrontTalk) -> str:
    """`judgekeeper check`, with the path when it is not this folder: a typed one with `/`
    between folders, as the line beside it names the files in it (textio.line_path)."""
    typed = talk.path if os.path.isabs(str(talk.path)) else Path(talk.path).as_posix()
    path = [] if talk.path == "." else [start.path_word(typed)]
    return " ".join((program("check"), *path))


def _recheck_step(talk: FrontTalk, ws: Workspace) -> str:
    """The step that re-checks this run's LLM-as-a-judge (_compare_command). A pass mark the
    eval or judgekeeper.toml sets is changed there: `check --pass-if` would refuse it."""
    rule = talk.options.get("pass_if")
    pm = ws.data().get("pass_mark") or {}
    if rule and pm and pm.get("source") != "pass_if":
        from judgekeeper import check

        return check.NEXT_MARK_ELSEWHERE.format(
            where=check.mark_set_in(pm, _check_command(talk)))
    return NEXT_CHECK.format(command=_compare_command(talk, ws))


def _compare_command(talk: FrontTalk, ws: Workspace) -> str:
    """`check` on this run's results: with the pass mark this run was given (--pass-if),
    which `check` reads the scores with too, unless the eval or judgekeeper.toml sets it."""
    rule = talk.options.get("pass_if")
    pm = ws.data().get("pass_mark") or {}
    if not rule or pm and pm.get("source") != "pass_if":
        return _check_command(talk)
    return f"{_check_command(talk)} --pass-if {quote_arg(rule)}"


def _fix_command(talk: FrontTalk) -> str:
    """`judgekeeper fix`, with the path when it is not this folder: `fix` takes no other flag."""
    return _check_command(talk).replace(program("check"), program("fix"), 1)


def _result(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool, saved: bool,
            head: list[str], check: bool = False, elsewhere: bool = False,
            compare: bool = False, worse_said: bool = False) -> int:
    """Step 3: the result from the marks, saved; whether the page is open. `check`: the
    judge changed since the marks, so the Next: line is `judgekeeper check`. `elsewhere`: the
    marks test a file a check read elsewhere (_checked_file): a plain `check` would read the
    older results here, so the next one is given the new results file. `compare`: graded
    again with the same model and rule (REGRADED): the check that compares is the Next.
    `worse_said`: the head named the check that found the newer grades worse (HELD_WORSE)."""
    talk.say(STEP.format(n=3, name="Measure"))
    talk.say()
    _say_head(talk, head)
    from judgekeeper import check as checking
    from judgekeeper import fix

    fix.prepare_split(ws)  # before any mistake is shown or written: some marks are hidden
    session = StartSession(ws)
    was = checking.open_worse(ws, found) if check else None  # checking again says the same
    worse = was and checking.worse_step(was["before"], was["after"],
                                        start.kept_check(talk.path, ws.root), ws, kept=True)
    # the terminal's: run where it is printed, as `check` says it
    worse_here = was and checking.worse_step(was["before"], was["after"],
                                             _check_command(talk), ws)
    r = start_label.store_result(ws, session, _flags_of(talk, saved, ws), worse=worse or None,
                                 redraw=True)
    m = marks.read(ws.marks)
    made = marks.made(m, ids=set(session.by_id))  # reasons added since
    for line in made_lines(made, marks.imported(m, ids=set(session.by_id)),
                           r.get("real_pass_rate"), (r.get("tpr"), r.get("tnr")),
                           links=start_label.link_news(ws, made))[1:]:
        # the notes on how they were made; the count is below. A link note: once per count
        talk.para(line)
        talk.say()
    talk.para(verdict_line(r))
    for line in r.get("written_from") or []:  # as check says it, and the page under its headline
        if line.startswith("  "):
            talk.para(line[2:], indent="  ")
        else:
            talk.para(line)
    if r.get("waiting"):  # marks on answers the judge now never graded (batches.graded)
        talk.para(checking.WAIT.format(k=r["waiting"]))
    if r.get("wait_group") or r.get("only_wait") and not r.get("waiting"):
        talk.para(checking.no_grade_left(r))  # none yet, but a new mark could only wait
    no_grade = report_page.no_grade_line(r)  # as report.html says it, under the counts
    if no_grade:
        talk.para(no_grade)
    gate = labels_mod.gate_line(r.get("import_gate"), r.get("imported"))
    if gate:  # imported marks not yet checked against page marks
        talk.para(gate)
    for line in agreement_lines(r):
        if line.startswith("  "):  # an indented count, wrapped under itself
            talk.para(line[2:], indent="  ")
        else:
            talk.para(line)
    step = report_page.next_step(r)  # the report's next step
    # the Next: line runs `mark` (too early to tell, answers left): its command is named once
    only = bool(r.get("only_wait"))  # a new mark would only wait: no line asks for one
    mark_next = (not worse and not check and step == "mark" and not start_label.all_labeled(r)
                 and not only)
    why, have = start_label.why_counts(ws, r) if not worse else (0, 0)
    if why:  # the result page has a box on each; those it lists, never those kept aside
        talk.say()
        talk.para(start_label.say_why_run(why, _command_of(talk, saved, "mark"), have))
        if step != "mark":  # fix is never a step while it is too early to tell
            talk.para(start_label.SAY_WHY_FIX.format(fix=_fix_command(talk)))
        if kept := start_label.kept_count(ws, r):  # said on the result page too
            talk.para(report_page.kept_line(kept))
    if r["verdict_level"] is not None:  # a result, too early to tell too: both estimates
        talk.say()
        for line in estimate_lines(r):
            talk.say(line)
        if report_page.shows_range(r):  # with no range shown, nothing is wider
            talk.para(start_label.wider(r))
        talk.say()  # apart from the lines above: it plays no part in the result
        talk.para(kappa_line(r))
    assumes = labels_mod.assumes_line(r.get("imported"))  # marks brought with --labels
    if assumes:
        talk.say()
        talk.para(assumes)
        off = labels_mod.looks_off_line(r.get("imports_off"), r.get("imported"))
        if off:  # a warning, never a stop
            talk.para(off)
    which = _which_judge(ws, found)
    if which:
        talk.say()
        talk.para(which)
    left = batches.line(r.get("batches"))  # a batch with too few marks: never left out silently
    if left:
        talk.say()
        talk.para(left)
    talk.say()
    report = link(ws.report_html, f"{shown_folder(ws)}/{ws.report_html.name}")
    talk.say(f"Full report: {report} (open it in your browser)")
    talk.say()
    opened = None
    ranges = report_page.shows_range(r)
    if start_label.all_labeled(r):  # nothing left to mark: no page
        if step == "mark" and not check and not only:
            labels = r["labels"]
            first, then = _all_marked_lines(talk, ws, {"correct": labels["correct"],
                                                       "wrong": labels["wrong"]}, saved)
            talk.para(first)
            talk.say()
            talk.para(then)
            return EXIT_NEEDS_YOU
    elif is_open(ws.dir):
        if ranges and not only:  # with no range shown, there is none to narrow
            talk.para(STILL_OPEN)
    elif wait:
        opened, _ = _open(talk, ws, wait, saved)
        talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    elif not mark_next and not why and ranges and not only:  # else Next or "To say why" names it
        # with exact numbers (one grade) more marks would not make them more certain: no line
        talk.para(MARK_ANY_TIME.format(command=_command_of(talk, saved, "mark")))
    # wait before is_open: --wait's own page answers only once it is served (page.serve)
    if (start_label.all_labeled(r) or wait or (is_open(ws.dir) and ranges and not only)
            or (ranges and not (is_open(ws.dir) or mark_next or why or only))):
        talk.say()
    if worse:  # why "go back" next to this result, unless the head said it
        if not worse_said:
            talk.para(WORSE_LAST)
            talk.say()
        next_step = worse_here
    elif check and (few := checking.too_few_here(ws, found)):  # check would say can't tell
        talk.para(few[0])
        talk.say()
        for line in few[1]:  # check's own steps (promptfoo's regrade.yaml)
            talk.say(line)
        next_step = few[2]
    elif check:
        next_step = _recheck_step(talk, ws)
    elif compare:
        next_step = NEXT_COMPARE.format(command=_compare_command(talk, ws))
    elif r.get("waiting") or only:  # only the judge's grades on them can count them
        next_step = checking.WAIT_NEXT.format(run=checking.wait_run(ws))  # from here
    elif step == "mark" and r.get("only_skipped"):  # only a skipped one is left to mark
        next_step = start_label.next_only_skipped(r["only_skipped"],
                                                  _command_of(talk, saved, "mark"))
    elif step == "mark":  # too early to tell
        next_step = NEXT_MARK_MORE.format(command=_command_of(talk, saved, "mark"))
    elif step == "fix" and not fix.can_run(ws):  # fix would say the same: mark more first
        talk.para(fix.NOT_ENOUGH)
        talk.say()
        # with exact numbers (one grade), marking more would not make them more certain; with
        # every answer marked, fix's step: more questions first (next_marks)
        next_step = start_label.next_marks(ws, (NEXT_MARK_MORE if ranges else NEXT_CONTINUE).format(
            command=_command_of(talk, saved, "mark")))
    elif step == "fix":
        next_step = NEXT_FIX.format(command=_fix_command(talk))
    elif elsewhere:
        next_step = checking.NEXT_SAME_FILE.removeprefix("Next: ").format(
            command=f"{program('check')} {checking.NEW_RESULTS}")
    else:
        next_step = NEXT_RESULT.format(command=_check_command(talk))
    talk.para("Next: " + next_step)
    if opened is not None:
        page.serve(opened.server)
    return EXIT_OK


# Answers with no grade ----------------------------------------------------------------------

def _no_grades(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool,
               marking: bool) -> int:
    """Answers with no grade (no_grades.py): Find's block the first time, the marking page until
    no_grades.MIN_MARKS marks and while answers new results brought wait to be marked, then
    the result (`judgekeeper mark` always opens the page).
    Marks made for an LLM-as-a-judge, or any with --new, move aside first, after a yes when
    there are any."""
    start_label.refuse_links(ws)
    first = not ws.start.is_file()
    if not first and (talk.new or not no_grades.here(ws)):  # for a judge, or --new
        if _has_marks(ws):
            talk.say()
            if not talk.confirm(START_OVER, default=True, with_yes=True, hint=""):
                talk.say("Nothing was moved.")
                raise talk.stop(EXIT_OK, f"nothing. Your old marks stay in {FOLDER}/.")
        talk.ask_noted()
        if is_open(ws.dir):
            background.stop(ws.dir)
        _move_aside(talk, ws)
        first = True
        talk.new = False  # done: the commands to go on are without it
        talk.refresh()
    if first and not marking:
        talk.say()  # a blank line after what Find said first (a file left out), never two
        for line in _no_grades_block(found):
            _say_found(talk, line)
        talk.say()
        _say_path(talk, found)
    talk.found = found
    talk.ask_noted()
    talk.find_shown = first and not marking  # the folder above is named with Find alone
    before = [q["id"] for q in ws.data().get("queue") or []] if not first else None
    was = no_grades.round_of(ws) if not first else None
    talk.switched = None if first else _switched_line(ws, found)  # said with the new answers
    with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one writes the pool
        start_label.prepare(found, say=lambda line: None, ws=ws)
        _import_labels(talk, ws, found, first)  # --labels: the marks it brings
    new = no_grades.found_new(ws, was) if not first else 0  # said once, on this run
    closed = False
    if before is not None and before != [q["id"] for q in ws.data()["queue"]] and \
            is_open(ws.dir):
        background.stop(ws.dir)  # the page open shows the answers without the new ones
        closed = True
    session = StartSession(ws)
    counts = session.counts()
    n = counts["correct"] + counts["wrong"]
    if n >= no_grades.MIN_MARKS and not marking and not no_grades.waiting(ws, session):
        return _no_grades_result(talk, ws, session, wait, new, closed)  # new answers first
    return _no_grades_page(talk, ws, session, wait, marking, first, new)


NO_GRADES = "none. You mark each answer."  # Find's Grades line: no LLM-as-a-judge checked


def _switched_line(ws: Workspace, found: start.Found) -> str | None:
    """NEWEST (READING for an older one) when the file read now is not the one read last."""
    if found.given or not found.results:
        return None
    try:
        data = ws.data()
        files = [f for f in data.get("results_files") or [] if isinstance(f, str)]
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if not files or data.get("given") or _same_files(ws, data, files, found):
        return None
    return (READING if _older(ws, data, files, found) else NEWEST).format(file=_newest(found))


def _say_switched(talk: FrontTalk, new: int) -> None:
    """_switched_line, in one paragraph with the new answers it brought (found_line)."""
    line = getattr(talk, "switched", None)
    if line:
        talk.para(line)
        if not new:
            talk.say()
        talk.switched = None


def _no_grades_block(found: start.Found) -> list[str]:
    """Find's block for answers with no grade: the file, the answers, what was read."""
    answers = len(found.pool.answers)
    lines = [f"Eval tool:       {tool_name(found.tool, [str(found.results[0].rel)])}",
             f"File:            {_read_from(found)}", f"Answers:         {_n(answers, 'answer')}"]
    if found.pool.n_merged:
        lines.append(INDENT + repeats_note(answers, found.pool))
    lines.append(f"Grades:          {NO_GRADES}")
    rows = [("question", "the input column"), ("answer", "the output column")]
    if found.app_version:
        rows.append(("version", "the app_version column"))
    lines.append("judgekeeper has read from your file:")
    lines += [f"  {k:<11}{v}" for k, v in rows]
    return lines


def _no_grades_page(talk: FrontTalk, ws: Workspace, session: StartSession, wait: bool,
                    marking: bool, first: bool, new: int = 0) -> int:
    """Step 2 with no grade: the marks so far and the marking page; with every answer marked
    and too few for a result, what comes next (exit 3). `new`: answers new since the last
    results, said first."""
    counts = session.counts()
    n_pass, n_fail = counts["correct"], counts["wrong"]
    n = n_pass + n_fail
    enough = n >= no_grades.MIN_MARKS
    every = bool(session.items) and all(i["label"] for i in session.items)
    talk.say(STEP.format(n=2, name="Mark (more answers)" if marking and enough else "Mark"))
    talk.say()
    if talk.found is not None:
        _say_path(talk, talk.found)
    _say_switched(talk, new)
    if new:
        talk.para(no_grades.found_line(ws, new))
        talk.say()
    if every and not enough:  # nothing left to mark, and no result yet
        done = no_grades.status(session, _command_of(talk, False))["done"]
        talk.para(done[0])
        raise talk.stop(EXIT_QUESTION, done[1].removeprefix("Next: "))
    if every:  # `mark` with a result: a mark can be changed, none is left to make
        talk.say(marked_all(n, "marked"))
        talk.say()
        opened, shown = _open(talk, ws, wait, False)
        if _kept(talk, opened, shown, CHANGE_MARK) is None:
            talk.para(f"The marking page is open in your browser. {CHANGE_MARK}"
                      if shown == page.BROWSER else CHANGE_MARK)
        if opened.server is not None:
            talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
        talk.say()
        talk.para("Next: " + no_grades.more_answers(ws, _command_of(talk, False), surer=True))
        if opened.server is not None:
            page.serve(opened.server)
        return EXIT_OK
    if n:
        waiting = (no_grades.waiting_line(ws, session)
                   if (marking or no_grades.waiting(ws, session)) and not new else None)
        talk.say(f"You marked {_n(n, 'answer')} so far: {n_pass} Pass, {n_fail} Fail."
                 + (f" {waiting}" if waiting else ""))
        if not enough:
            talk.say(start_label.VERDICTS[None])
        talk.say()
    after = PRECISE if enough else BAR if n else SHOWS_ANSWERS
    opened = None
    no_browser = talk.options["no_browser"]  # its link is printed again: a new page
    if not first and not marking and not wait and not no_browser and n and is_open(ws.dir):
        talk.para(f"The marking page is still open in your browser. {after}".rstrip())
    else:
        opened, shown = _open(talk, ws, wait, False)
        again = " again" if n and not marking else ""
        if _kept(talk, opened, shown, after) is None and (shown == page.BROWSER or after):
            talk.para(f"The marking page is open in your browser{again}. {after}".rstrip()
                      if shown == page.BROWSER else after)
        if opened.server is not None:
            talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    talk.say()
    next_step = NEXT_MORE if enough else NEXT_ANSWERS
    if opened is not None and opened.server is not None:
        page.serve(opened.server)  # Ctrl-C here: "Stopped." and its own Next line (cli)
        if getattr(opened.server, "stopped", False):  # --stop closed it: no link is open
            next_step = NEXT_CONTINUE
    talk.para("Next: " + next_step.format(command=_command_of(talk, False)))
    return EXIT_OK


def _no_grades_result(talk: FrontTalk, ws: Workspace, session: StartSession,
                      wait: bool, new: int = 0, closed: bool = False) -> int:
    """Step 3 with no grade: how many answers the person passed and the reasons they gave,
    saved in result.json; nothing about an LLM-as-a-judge. `new`: answers new since the last
    results, said first. `closed`: this run closed the marking page open (PAGE_CLOSED)."""
    talk.say(STEP.format(n=3, name="Measure"))
    talk.say()
    if talk.found is not None:
        _say_path(talk, talk.found)
    _say_switched(talk, new)
    if new:
        talk.para(no_grades.found_line(ws, new))
        talk.say()
    failed = no_grades.failed_path(ws)
    had = no_grades.listed_failed(ws)  # the last result listed some (no before.json to say)
    r = start_label.store_result(ws, session, _flags_of(talk, False, ws))
    labels = r["labels"]
    rate = no_grades.rate_line(r)  # as the result page says it
    talk.para(no_grades.counts_line(labels["correct"], labels["correct"] + labels["wrong"])
              + (f" {rate}" if rate else ""))
    for said in no_grades.since_lines(r.get("since")):  # what changed since the last answers
        talk.para(said)
    line = no_grades.reasons_line(no_grades.reason_rows(ws, session))
    if line:
        talk.para(line)
    agent = no_grades.agent_lines(ws)  # the answers failed, for a coding agent
    if agent:
        talk.say()
        for said in agent:
            talk.say(said)
    if not failed.is_file() and (had or no_grades.removed_unsaid(ws)):  # removed by this run,
        # a mark on the page or the page's result: said once, here
        talk.say()
        talk.para(FAILED_REMOVED.format(path=f"{shown_folder(ws)}/fix/{failed.name}"))
        no_grades.set_removed_unsaid(ws, False)
    talk.say()
    report = link(ws.report_html, f"{shown_folder(ws)}/{ws.report_html.name}")
    talk.say(f"Full report: {report} (open it in your browser)")
    talk.say()
    opened = None
    if wait and r["left"] and not is_open(ws.dir):
        opened, _ = _open(talk, ws, wait, False)
        talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
        talk.say()
    elif closed:
        talk.para(PAGE_CLOSED.format(command=_command_of(talk, False, "mark")))
    talk.para("Next: " + (NEXT_MARK_MORE.format(command=_command_of(talk, False, "mark"))
                          if r["left"] else
                          no_grades.more_answers(ws, _command_of(talk, False), surer=True)))
    if opened is not None:
        page.serve(opened.server)
    return EXIT_OK


def _stop(talk: FrontTalk, path: Path) -> int:
    """--stop: close the page open for this project, or, when marking never started here,
    the one opened from a folder right below it (Find looks one level down); with several
    there, where they are. A project with marks of its own never closes another's page."""
    if not path.exists():
        raise not_found(path, talk.path)
    ws = Workspace(project.project_of(path))
    if path.is_dir() and not (ws.start.is_file() or ws.labels.is_file()):
        ws = Workspace(start.reads_in(path, talk.given))  # the folder a run from here reads
    if path.is_dir() and not is_open(ws.dir) and is_open(Workspace(path).dir):
        ws = Workspace(path)  # a page open on a session every command now passes over
    own = ws.start.is_file() or ws.labels.is_file()  # marking started in this project
    below = [] if own or is_open(ws.dir) or not path.is_dir() else [
        name for name, _ in _sessions_below(path) if is_open(Workspace(path / name).dir)]
    if len(below) == 1:  # opened from the folder right below
        ws = Workspace(path / below[0])
    elif below:
        below = _from_here(path, below)
        talk.para(f"Marking pages are open in {start._and([f'{n}/' for n in below])}.")
        raise talk.stop(EXIT_QUESTION, _go_step(below, f"{program()} --stop"))
    lock = read_lock(ws.dir) if is_open(ws.dir) else None
    closed = None if lock is None else {  # how the page was opened: carried on
        "port": lock["port"] if lock["asked"] is None else lock["asked"],
        "no_browser": bool(lock["no_browser"])}
    if not is_open(ws.dir):
        talk.say("No marking page is open.")
    elif not background.stop(ws.dir):
        talk.say("The marking page did not close.")
        raise talk.stop(EXIT_QUESTION, "close it with Ctrl-C in the terminal it runs in; else "
                                       "it closes by itself after 30 minutes without a click.")
    else:
        saved = " Your marks are saved." if marks.read(ws.marks).counted() else ""
        talk.say(f"Closed the marking page.{saved}")
    talk.say()
    talk.para("Next: " + NEXT_CONTINUE.format(command=_continue_command(talk, ws, closed)))
    return EXIT_OK


def _continue_command(talk: FrontTalk, ws: Workspace, page: dict | None = None) -> str:
    """The run that carries on the project after --stop: in its own folder, as the result
    was made (result.json's flags: the pass mark in use, the flags that read the results,
    how the page opens), so a scores project still reads its scores; else as typed. Either
    way with how the `page` it closed was opened ({"port", "no_browser"}): its port, but the
    default or any free one (0), and --no-browser when it was given it."""
    port = page and page["port"] not in (None, 0, DEFAULT_PORT) and page["port"]
    try:
        flags = json.loads(ws.result_json.read_text(encoding="utf-8")).get("flags")
    except (OSError, ValueError, AttributeError):
        flags = None
    if not isinstance(flags, dict) or Path.cwd().resolve() != ws.root.resolve():
        typed = talk.options.get("port", DEFAULT_PORT) != DEFAULT_PORT
        extra = ("--port", str(port)) if port and not typed else ()
        if page and page["no_browser"] and not talk.options.get("no_browser"):
            extra = (*extra, "--no-browser")
        return talk.command(*extra)  # the paths it keeps are from the project folder
    if page:
        flags = {**flags, "port": port or DEFAULT_PORT, "no_browser": page["no_browser"]}
    return start.command_from(flags)


__all__ = ["EXIT_NEEDS_YOU", "FrontTalk", "answered", "find_found", "found_block", "go", "run",
           "tool_version", "verdict_line"]
