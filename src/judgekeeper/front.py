"""`judgekeeper` with no command does the next step. What is in the project decides it:

| What is there                                | What `judgekeeper` does                    | Exit |
|----------------------------------------------|--------------------------------------------|------|
| something must be asked (several tools,      | the question, and a Next: line naming the  | 3    |
| judges, a pass mark, an own format...)       | flag that answers it                       |      |
| nothing found, or too few answers            | says so                                    | 3    |
| found, no marking started                    | what was found, the free checks; prepares  | 0    |
|                                              | the pool and opens the page (output A)     |      |
| marking started, under 15 Pass + 15 Fail     | one line naming the judge and results;     | 0    |
|                                              | opens the page again (output A)            |      |
| every answer marked, under 15 of one kind    | says so, and to mark new results with      | 3    |
|                                              | --new; no page                             |      |
| at least 15 Pass + 15 Fail                   | the result (output B); says if the page    | 0    |
|                                              | is open                                    |      |
| marks for another judge (another metric or   | says why and asks "Start over...?" (the    | 3    |
| tool), or labels.csv from 0.2                | question list, then --yes)                 |      |

A new eval run does not start over: the answers being marked are in .judgekeeper/pool.jsonl,
so marking goes on with them and a result stays valid (marks are tests for the judge, not for
one results file); one line says the eval ran again. Only another judge or --new starts over.
When the judge's setup (judge_setup.py) changed since the marks, that line says what changed,
and once there are enough marks the result's Next: line is `judgekeeper check`, which re-tests
the new judge on them. A judge whose results hold no rule (a table) changes only in its grades:
grades that differ on marked answers (check.grades_changed) count as a change.
The project folder is start_again._project, for every command. A results file (or MLflow
store) given as the path is read where it is and named in start.json (`given`), so later runs
with no path read it again.
`judgekeeper mark` (mark.py) goes through the same table for marking more: it opens the page
in every row but "asked", "start over" and "every answer marked", prints the count, and leaves
the result to `judgekeeper`. --wait serves the page in this process, --stop closes it (page.py).

Finding: find the eval tool, its saved results, the judge and its rule; run the free checks
(judge_check); write .judgekeeper/judge.json (the judge's setup, judge_setup.py: before
marking starts it follows the newest results, then it keeps the judge of the marks until
`judgekeeper check` re-checks a new one); say what was found in plain lines, then exactly one
line starting `Next:`.

A person and a coding agent read the same output, and the agent follows the `Next:` line. So
the output holds counts, names, file paths and the judge's rule (the person's own config, on
one line), never an answer's or an input's text. A `Next:` line names only judgekeeper's own
commands or the person's eval tool; never a link to download, never a command built from what
a file says.

Finding is start.find_judge, with FrontTalk in place of start.Talk. At a terminal a question
is asked inline. Without one, a choice (which tool, judge, store, pass mark) is printed in
plain words with a `Next:` line naming the flag that answers it, and the exit code is 3. A
yes/no question is noted and the run goes on as if the answer is yes; at the end the noted
questions are printed as one list, nothing is written, and the exit code is 3. `--yes` means
yes to the questions printed in the last run, nothing else: they are the same questions,
because that run went on as if each answer was yes. judgekeeper.toml is written only for what
had to be asked (which tool, which judge, which MLflow store or experiment, how to read an own
format), after a yes.

No AI call and no key. Exit codes: 0 the next step is done (or `Next: nothing`), 3 the person
is needed (the `Next:` line says what to ask or do), 2 usage error, 130 Ctrl-C.
"""

from __future__ import annotations

import re
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
    own_format,
    page,
    report_page,
    settings,
    start,
    start_again,
    start_label,
    targets,
)
from judgekeeper.fingerprint import rule_hash
from judgekeeper.label import DEFAULT_PORT, is_open, page_folder
from judgekeeper.normalise import _numeric
from judgekeeper.records import RecordsError
from judgekeeper.start import EXIT_QUESTION, StartError, Stop
from judgekeeper.start_label import FOLDER, StartSession, Workspace, made_lines, shown_folder
from judgekeeper.textio import old_hook, plural, program, quote_arg, wrap

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NEEDS_YOU = 3
FIRST_SHOWN = 26  # characters of the first rule shown when they differ per test
RULE_SHOWN = 54  # characters of the judge's rule shown, "…" included, on one line
VALUE_WIDTH = 40  # characters of a judge's decision value shown
PASS_IF = '"score>=N"'  # the placeholder of --pass-if in a Next: line; quoted for every shell
LABEL_MAP = '"VALUE=pass,VALUE=fail,VALUE=error"'
SAVE = "Save your answers in judgekeeper.toml, so judgekeeper does not ask again?"
SAVE_MAP = ("Save how to read {file} in judgekeeper.toml? judgekeeper reads it from there "
            "from now on.")
QUESTIONS = "judgekeeper needs your answer to {which}:"
# Questions whose answer changes what is counted: the counts are printed after them
COUNT_QUESTIONS = ("Count each as its own answer?", "Leave them out?")
READS = ("judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV "
         "or JSONL file.")
# The options that find the judge, as start.find_judge takes them
FIND = ("tool", "metric", "experiment", "tracking_uri", "pass_if", "label_map", "judge_model")
ASKED = {"--tool": "tool", "--metric": "metric", "--experiment": "experiment"}
START_OVER = f"Start over with these results? Your old marks move to {FOLDER}/previous-<date>/."
OLD_MARKS = (f"{FOLDER}/labels.csv holds marks from an older judgekeeper. They have no time "
             "stamps, so this version does not use them.")
SCORE_READ = "Read the score column with your pass mark; the verdict column is not used."
RAN_AGAIN = "Your eval ran again. Your LLM-as-a-judge is the same, so your marks still test it."
RAN_AGAIN_CHECKED = ("Your eval ran again. Your LLM-as-a-judge is the one your last check "
                     "re-tested, so your marks still test it.")
JUDGE_CHANGED = "Your LLM-as-a-judge changed since your marks: {what}."
DEFAULT_GRADER = "promptfoo's default grader (no model written in your config)"
DEFAULT_GRADER_NOTE = "came from promptfoo's default grader"  # readers.promptfoo's warning
STEP = "Step {n} of 5: {name}"
INDENT = " " * 17  # under the value of "LLM-as-a-judge:  "
EVERY_ANSWER = "your LLM-as-a-judge gave every answer a clear Pass or Fail."
FREE_CHECK = "Checked: "  # every free-check line starts with it
SHOWS = ("It shows the answers one at a time. Mark each one Pass or Fail, the way you want your "
         "LLM-as-a-judge to decide. Your LLM-as-a-judge's grade stays hidden.")
BAR = "The bar at the top fills as you mark."
PRECISE = "Each new mark makes your numbers more precise."
NOT_ENOUGH = "That's not enough for a result yet."
NEXT_MARK = 'mark until "See your result" appears, then click it.'
NEXT_KEEP_MARKING = 'keep marking until "See your result" appears, then click it.'
NEXT_MORE = "mark more answers, then run `{command}` to see your updated result."
NEXT_CHECK = "run `{command}` to re-check your changed LLM-as-a-judge on your marks."
NEXT_RESULT = ("nothing to do. When you change your LLM-as-a-judge or update your eval tool, run "
               "`{command}`.")
NEXT_FIX = "to improve your LLM-as-a-judge's rule, run `{command}`."
NEXT_CONTINUE = "run `{command}` when you want to continue."
STILL_OPEN = ("The marking page is still open. Mark more answers to make these ranges "
              "narrower, so the numbers are more certain.")
AGREES = "How often your LLM-as-a-judge agrees with you (estimates):"
NEXT_MARK_MORE = "run `{command}` to mark more answers."
SAY_WHY_NEXT = "The Next step below also lets you say why on these."  # its command once
MARK_ANY_TIME = "To mark more answers at any time, run `{command}`."
SAY_WHY = "Say why on the answers you and your LLM-as-a-judge disagree on; `fix` uses your reasons."
RESULT_OPEN = "Your result page is open in your browser."
COULD_NOT = "run `{command}` in your own terminal (it keeps the page open there)."
PORT_TAKEN = "Port {port} is in use, so the marking page could not start."
PORT_PAGE = "Port {port} is in use by judgekeeper's marking page for {folder}."
NEXT_STOP_THERE = "run `{stop}` there, or `{command}`."
NEXT_ANY_PORT = "run `{command}` (it opens the page on any free port)."
# A tool found here with no saved results: what saves them
SAVES = {"deepeval": "DeepEval saves results only when you run deepeval test run or evaluate().",
         "inspect": "Inspect AI saves its logs in logs/ when you run inspect eval.",
         "mlflow": "MLflow keeps the LLM-as-a-judge's assessments once mlflow.genai.evaluate() "
                   "runs."}
OTHERS = 3  # other projects named when run from a folder that holds several
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
        self.refresh()

    def refresh(self) -> None:
        """The printed commands repeat the options as they are now, never --yes: it answers
        only the questions printed in the run just before (ask_noted)."""
        self.flags = start.repeated_flags(self.path, **self.options)
        if self.new:
            self.flags = (*self.flags, "--new")

    def set(self, name: str, value) -> None:
        self.options[name] = value
        self.refresh()

    def looking(self, root: Path) -> None:
        """Said only when nothing is found."""

    def remember(self, flag: str, chosen: str, line: str | None = None) -> None:
        if flag == "PATH":
            self.store = chosen
        self.answers[flag] = chosen

    def choose(self, title, options, flag_hint, ask="Which one?", flag=None, values=(),
               what=None) -> int:
        if start._interactive():
            return super().choose(title, options, flag_hint, ask)
        self.say(title)
        for option in options:
            self.say(f"  {option}")
        if flag is None:
            raise self.stop(EXIT_QUESTION, f"run `{self.command()}` in a terminal, to answer "
                                           "there.")
        names = ", ".join(f"'{v}'" if flag == "--metric" else quote_arg(str(v))  # names alike
                          for v in values)
        if flag == "PATH":
            commands = [f"`{self.command_at(v)}`" for v in values]
            then = start._or(commands)
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
        yes, again = f"`{self.command('--yes')}`", f"`{self.command()}`"
        raise self.stop(EXIT_QUESTION, f"run {again} in a terminal to answer, or {yes} to say "
                                       f"yes{'' if one else ' to all'}.")

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

    def para(self, text: str = "", indent: str = "") -> None:
        """Say `text` wrapped (textio.wrap)."""
        for line in wrap(text, indent=indent):
            self.say(line)

    def stop(self, code: int, next_step: str | None = None) -> Stop:
        """Say the Next: line; exit 3 when it asks for something, 0 when it is nothing."""
        if next_step:
            self.say()
            self.para(f"Next: {next_step}")
            return Stop(EXIT_OK if next_step.startswith("nothing") else EXIT_NEEDS_YOU)
        return Stop(EXIT_NEEDS_YOU if code == EXIT_QUESTION else code)


def run(path: str | Path = ".", tool: str | None = None, metric: str | None = None,
        experiment: str | None = None, tracking_uri: str | None = None,
        pass_if: str | None = None, label_map: str | None = None,
        judge_model: str | None = None, fields: str | None = None, yes: bool = False,
        port: int = DEFAULT_PORT, no_browser: bool = False, new: bool = False,
        wait: bool = False, stop: bool = False) -> int:
    """`judgekeeper`. Returns the exit code."""
    options = {"tool": tool, "metric": metric, "experiment": experiment,
               "tracking_uri": tracking_uri, "pass_if": pass_if, "label_map": label_map,
               "judge_model": judge_model, "fields": fields, "port": port,
               "no_browser": no_browser}
    talk = FrontTalk(yes=yes, path=path, options=options, new=new)
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
        if not marking and not _started(path):
            talk.say(STEP.format(n=1, name="Find"))
            talk.say()
        else:  # said only when Find has something to say (a file left out, an error)
            talk.step = STEP.format(n=1, name="Find")
        try:
            return _run(talk, path, wait, marking)
        except Exception:
            talk.say_step()  # the error cli.py prints comes under Step 1 too
            raise
    except Stop as e:
        return EXIT_NEEDS_YOU if e.code == EXIT_QUESTION else e.code


def _started(path: Path) -> bool:
    """Whether marking started in the project at `path` (or 0.2's marks are there)."""
    if not path.exists():
        return False
    ws = Workspace(start_again._project(path))
    return ws.start.is_file() or ws.labels.is_file()


# Finding -----------------------------------------------------------------------------------

def _run(talk: FrontTalk, path: Path, wait: bool, marking: bool) -> int:
    found, mapped = find_found(talk, path)  # anything it says comes under Step 1's label
    talk.step = None
    ws = Workspace(found.root)
    if not marking and not ws.start.is_file() and not ws.labels.is_file():
        return _say(talk, found, mapped, wait)
    return _go_on(talk, found, mapped, wait, marking)


def find_found(talk: FrontTalk, path: Path) -> tuple[start.Found, settings.StartSettings | None]:
    """(the judge found, the [start] table of an own-format file mapped now or None), asking
    what must be asked; `judgekeeper mark` finds the same way."""
    uri = talk.options["tracking_uri"]
    if uri is not None and str(uri).startswith(start.SERVERS):
        raise _tracking_server(talk, path, str(uri))
    if not path.exists():
        raise not_found(path)
    path = _remembered(talk, path)
    where, saved = _own_format(talk, path)
    found = _find(talk, where, saved)
    found = _marked_files(talk, where, saved, found)
    if path.is_file() or find.is_mlflow_folder(path):  # read there; kept in the project
        found = start.rebased(found, start_again._project(path))
    return found, saved


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
    ws = Workspace(start_again._project(path))
    try:
        if not ws.start.is_file() or start._saved(ws.root) is not None:
            return path
        return start.results_path(ws.root, ws.data()) if ws.data().get("given") else path
    except (OSError, ValueError):
        return path


def not_found(path: Path) -> StartError:
    """PATH is not there; a single word is taken for a command that does not exist."""
    word = str(path)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", word):
        return StartError(f"`{word}` is not a judgekeeper command, and there is no folder "
                          f"named {word} here.", f"run `{program()}`, or "
                                                 f"`{program()} --help` to see the commands.")
    return StartError(f"file or folder not found: {path}",
                      "check the path, then run `{command}`.")


def _own_format(talk: FrontTalk, path: Path) -> tuple[Path, settings.StartSettings | None]:
    """(where find_judge looks, the [start] table of an own-format file mapped now, or None).
    Nothing found at all: say where it looked, and stop."""
    from judgekeeper import own_map

    o = talk.options
    if path.is_file():
        if o["tool"] is not None or find.classify_file(path) is not None or \
                path.suffix.lower() not in own_format.SUFFIXES or find.is_promptfoo_table(path) \
                or find.title_row(path):
            return path, None  # find_judge reads it, or says why it can't
        root = start_again._project(path)
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
    if own is None and (search.skipped or find.results_above(root) is not None):
        return path, None  # results-like files too far up or down: find_judge names them
    if own is None and tables:  # promptfoo's table output, found past the walk's limits
        raise start.table_output(tables[0])
    for rel in tables:
        talk.para(f"{rel} {find.TABLE_OUTPUT}, so it was left out.")
    if own is None and search.judge_only:
        rel = search.judge_only[0]
        talk.para(f"{rel} has your LLM-as-a-judge's verdicts but no answer text, so there's "
                  "nothing to show you for marking.")
        raise talk.stop(EXIT_QUESTION, "add the answer column (the text that was judged) to "
                                       f"{rel}, then run `{talk.command()}`.")
    if own is None and search.no_question:
        rel = search.no_question[0]
        talk.para(f"{rel} has your LLM-as-a-judge's verdicts and the answers but no question, so "
                  "the answers can't be shown with what they answer.")
        raise talk.stop(EXIT_QUESTION, "add the question column (what each answer answers) to "
                                       f"{rel}, then run `{talk.command()}`.")
    if own is None:
        raise _nothing_found(talk, root, search.signs, find.nested_results(search), unlooked,
                             stopped=search.stopped)
    return root, own_map.map_file(talk, root, own.path, o["metric"], o["judge_model"],
                                  o["pass_if"], found=True)


def _find(talk: FrontTalk, path: Path, saved, only: list[str] | None = None) -> start.Found:
    """find_judge, again after each answer about decisions it cannot read as Pass or Fail.
    `only`: the results files the marks were made on (_marked_files)."""
    given = _given_model(path) if talk.options["judge_model"] is None and saved is None else None
    while True:
        options = {k: talk.options[k] for k in FIND}
        options.update({ASKED[f]: v for f, v in talk.answers.items() if f in ASKED})
        if saved is not None:  # a map made now holds the judge's model and its pass mark
            options.update(judge_model=None, pass_if=None)
            if str(options["metric"]).lower() in ("*", "all"):  # every judge: the map says so
                options["metric"] = None
        try:
            try:
                found = start.find_judge(path, talk=talk, saved=saved, store=talk.store,
                                         only=only, **{**options, "judge_model": given or
                                                       options["judge_model"]})
            except StartError:
                if given is None:
                    raise
                given = None  # the results name the model now
                continue
        except RecordsError as e:
            raise start.usage_error(e) from None
        if not found.pool.unmapped:
            _ignored(talk, found)
            return found
        _unread_values(talk, found)


def _given_model(path: Path) -> str | None:
    """The judge's model the person gave with --judge-model when marking started, kept in
    start.json: used while the results still don't name one."""
    ws = Workspace(start_again._project(path))
    try:
        fp = (ws.data().get("fingerprint") or {}) if ws.start.is_file() else {}
    except (OSError, ValueError, AttributeError):
        return None
    model = fp.get("model") if fp.get("model_source") == start.GIVEN_BY_YOU else None
    return model if isinstance(model, str) else None


IGNORED = {"experiment": ("mlflow", "--experiment is for MLflow results, so it was ignored."),
           "fields": ("deepeval", "--fields is for a DeepEval LLM-as-a-judge, so it was ignored.")}


def _ignored(talk: FrontTalk, found: start.Found) -> None:
    """A flag for another tool's results: said, and left out of the commands printed."""
    for option, (tool, said) in IGNORED.items():
        if talk.options.get(option) and found.tool != tool:
            talk.para(said)
            talk.say()
            talk.set(option, None)


def _shown(values) -> str:
    texts = [start.shown_value(v) for v in values]
    texts = [t[:VALUE_WIDTH - 1] + "…" if len(t) > VALUE_WIDTH else t for t in texts]
    return ", ".join(sorted(texts)[:10]) + (f" and {len(texts) - 10} more"
                                             if len(texts) > 10 else "")


def _add_label_map(talk: FrontTalk, extra: str) -> None:
    given = talk.options["label_map"]
    talk.set("label_map", f"{given},{extra}" if given else extra)


def _unread_values(talk: FrontTalk, found: start.Found) -> None:
    """The judge's decisions hold values that are not Pass or Fail: ask what they mean (never
    a guess: a wrong one turns fails into passes)."""
    values = list(dict.fromkeys(found.pool.unmapped))
    terminal = start._interactive()
    if found.tool == "inspect" and "P" in values:  # model_graded_qa(partial_credit=True)
        n = found.pool.n_unmapped.get(repr("P"), 0)
        for line in found_block(found):  # what was found; the count waits for the answer
            if not line.startswith("Answers:"):
                talk.say(line)
        talk.say()
        talk.say(f"Inspect gave partial credit (P) on {_n(n, 'answer')}.")
        if not terminal:
            raise talk.stop(EXIT_QUESTION, (
                "decide whether partial credit (P) counts as Pass or Fail, then run "
                f"`{talk.command('--label-map', 'P=pass')}` or "
                f"`{talk.command('--label-map', 'P=fail')}`."))
        i = talk.choose("Should partial credit count as Pass or Fail?", ["Pass", "Fail"], "")
        _add_label_map(talk, f"P={('pass', 'fail')[i]}")
        return
    if all(_numeric(v) for v in values):
        talk.say(f"Your LLM-as-a-judge's decisions are scores ({_shown(values)}), and the results "
                 "do not say which score passes.")
        if not terminal:
            raise talk.stop(EXIT_QUESTION, "decide which score counts as a pass, then run "
                                           f"`{talk.command('--pass-if', PASS_IF)}`.")
        while True:
            answer = talk.ask("Pass when the score is at least", "0.5")
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
            f"decision (error), then run `{talk.command('--label-map', LABEL_MAP)}`."))
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
        column = next((c for c in find.VERDICT_COLUMNS if c in columns), "verdict")
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
    return talk.stop(EXIT_QUESTION, f"{fix}, then run `{talk.command()}`.")


def _nested_line(nested: list[str]) -> str:
    """Results in projects of their own below this one (find.nested_results): whose they
    are, and where to check them."""
    named = start._and([f"{p}/" for p in nested])
    where = start._or([f"{p}/" for p in nested])
    return (f"These results belong to the {'project' if len(nested) == 1 else 'projects'} in "
            f"{named}. To check them, run `{program()}` in {where}.")


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
    if nested:
        talk.para(_nested_line(nested))
        where = start._or([f"{p}/" for p in nested])
        return talk.stop(EXIT_QUESTION, f"run `{program()}` in {where}.")
    saved = _saved_marks(root)
    if saved:  # the results file is gone, the marks are not
        talk.say(STEP.format(n=1, name="Find"))
        talk.say()
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
    again = f"`{talk.command()}`"
    other = "" if signs else (f" If your results are somewhere else, run "
                              f"`{talk.command_at('PATH')}` with their file or folder.")
    return talk.stop(EXIT_QUESTION, f"run your eval once from this folder, then run {again} "
                                    f"again.{other}")


def _saved_marks(root: Path) -> int:
    """How many marks the project's .judgekeeper/ holds."""
    ws = Workspace(start_again._project(root))
    try:
        return len(marks.read(ws.marks).counted()) if ws.marks.is_file() else 0
    except (OSError, ValueError):
        return 0


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


def _notes(found: start.Found) -> list[str]:
    pool, out = found.pool, [*found.stopped, *found.warnings]
    if judge_check.model_not_written(found):  # said once, with its fix, by the free checks
        out = [w for w in out if DEFAULT_GRADER_NOTE not in w]
    if not pool.answers:  # "none with a clear grade": where the grades came from is moot
        out = [w for w in out if "default grader" not in w]
    if pool.n_human:
        out.append(f"Your results also hold {_n(pool.n_human, 'human label')}. judgekeeper does "
                   "not use them: you mark the answers yourself.")
    n = len(pool.answers)
    for count, did, too in ((pool.n_fail, "failed", "passes too much"),
                            (pool.n_pass, "passed", "fails too much")):
        # under a fifth of the answers; a small pool is said below
        if 0 < count < FEW_SHARE * n and n >= start.MIN_POOL:
            out.append(f"Your LLM-as-a-judge {did} only {count} of {n} answers. That may mean it "
                       f"{too}: your marks will show it.")
    return out


def _other_files(found: start.Found) -> str | None:
    """Tables of results found next to the one read, never read with it: named (at most
    OTHERS), with the command that checks one."""
    if found.tool != "table" or found.given:
        return None
    others = [r.rel for r in found.results if r.rel not in found.used][:OTHERS]
    if not others:
        return None
    commands = start._or([f"`{program()} {quote_arg(r)}`" for r in others])
    return (f"Also found {start._and(others)}. To check "
            f"{'it' if len(others) == 1 else 'one'}, run {commands}.")


def _other_projects(found: start.Found) -> str | None:
    """Run from a folder that is no project but holds several: which project the results
    are from, and the others that hold results (at most OTHERS), each with its command."""
    root = Path(found.root)
    if found.given or start_again._is_project(root):
        return None

    def project_of(path: Path) -> str | None:
        for folder in path.parents:
            if folder == root or not folder.is_relative_to(root):
                return None
            if start_again._is_project(folder):
                return folder.relative_to(root).as_posix()
        return None

    read = project_of(found.results[0].path)
    search = find.search(root)
    others = sorted({p for t in find.TOOLS for r in search.readable(t)
                     if (p := project_of(r.path)) not in (None, read)})[:OTHERS]
    if read is None or not others:
        return None
    one = len(others) == 1
    named = start._and([f"{p}/" for p in others])
    commands = start._or([f"`{program()} {quote_arg(p)}`" for p in others])
    return (f"These results are from the project in {read}/. The "
            f"{'project' if one else 'projects'} in {named} {'has' if one else 'have'} "
            f"results too: to check them, run {commands}.")


def _nested_here(found: start.Found) -> str | None:
    """Results in a project of its own below this one, never read with these: named."""
    if found.given:
        return None
    nested = find.nested_results(find.search(found.root))
    return _nested_line(nested) if nested else None


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
            files = [(folder / f).resolve() for f in ([given] if isinstance(given, str) and given
                                                      else data.get("results_files") or [])]
            n = len(marks.read(ws.marks).counted())
        except (OSError, ValueError, AttributeError, TypeError):
            return None
        if n and any(f.is_relative_to(root) for f in files):
            return (f"The project above ({folder.name}) holds {_n(n, 'mark')} for these results "
                    f"in its {FOLDER}/. They stay there: this project keeps its own marks.")
        return None
    return None


def tool_version(found: start.Found) -> str | None:
    """The eval tool's version: from its results, else the project's lockfile."""
    return judge_setup.version_of(found)[0]


def _listed(found: start.Found) -> str:
    """Where _write puts the list of answers left out, as the person finds it."""
    from judgekeeper import start_label

    ws = start_label.Workspace(found.root)
    return f"{start_label.shown_folder(ws)}/{judge_check.CSV_FILE}"


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


TOOL_NAMES = {**find.NAMES, "records": "judgekeeper.record() in your code",
              "mapped": "your own format"}


def tool_name(tool: str | None, files: list[str] | None = None) -> str | None:
    """The eval tool as every screen and page names it; a table by its kind ("your own CSV
    file", from the first of `files`)."""
    if tool == "table" and files:
        return f"your own {Path(files[0]).suffix.lstrip('.').upper()} file"
    return TOOL_NAMES.get(tool, tool)


def _read_from(found: start.Found) -> str:
    """Where the answers were read, in the shape of found_line's brackets."""
    newest = found.results[0]
    if found.tool == "mlflow":
        return f"{found.store}, experiment {quote_arg(found.experiment or '')}"
    if found.tool == "records":
        return f"{start._folder_of(newest)}, {_n(len(found.used), 'file')}"
    if found.tool == "mapped":
        return newest.rel + (f", {_n(len(found.used), 'line')}" if len(found.used) > 1 else "")
    if len(found.used) > 1:
        return f"{newest.rel} and {_n(len(found.used) - 1, 'older file')}"
    return newest.rel


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
        return next((n for n in find.PROMPTFOO_CONFIGS if (Path(found.root) / n).is_file()),
                    None)
    return found.task_file if found.tool == "inspect" else None


def _rule_lines(found: start.Found) -> list[str]:
    if found.reference:
        return ["Rule:            compared with each test's reference answer"]
    if not found.rule:
        return ["Rule:            not in your results"]
    if not found.one_rule:
        first = " ".join(found.rule.split())
        if len(first) > FIRST_SHOWN:
            first = first[:FIRST_SHOWN - 1].rstrip() + "…"
        return [f'Rule:            differs per test ({found.n_rules} rules). First: "{first}"']
    text = " ".join(found.rule.split())
    if len(text) <= RULE_SHOWN:
        return [f'Rule:            "{text}"']
    where = _rule_file(found)
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
    which = ("1 answer got different grades, so its" if len(pool.split) == 1
             else f"{len(pool.split)} answers got different grades, so their")
    return f"{head}. Repeats with the same grade count once. {which} {split} repeats each count.)"


def passed_failed(n_pass: int, n_fail: int) -> str:
    return f"Your LLM-as-a-judge passed {_n(n_pass, 'answer')} and failed {n_fail}."


def found_block(found: start.Found, pass_if: str | None = None,
                mapped: settings.StartSettings | None = None) -> list[str]:
    """Screen 1's "Find" block: the eval tool, the file, the answers, the judge, its rule and
    what was read from the file."""
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
    else:
        lines.append(f"Answers:         {_n(answers, 'answer')}")
    if pool.answers and (pool.n_merged or pool.split):
        lines.append(INDENT + repeats_note(answers, pool))
    lines += [f"LLM-as-a-judge:  {_judge_value(found)}", *_rule_lines(found)]
    rows = read_rows(found, pass_if, mapped)
    if rows:
        width = max(len(k) for k, _ in rows) + 3
        lines.append("judgekeeper has read from your file:")
        lines += [f"  {k:<{width}}{v}" for k, v in rows]
    return lines


def read_rows(found: start.Found, pass_if: str | None = None,
              mapped: settings.StartSettings | None = None) -> list[tuple[str, str]]:
    """What was read from the file, as (what, where) rows: the question, the answer, the
    grade (with the pass mark when there is one), then the reason, model, version and your
    labels when the file has them."""
    pm = found.pass_mark
    mark = f": {start.pass_at(pm)}" if pm else ""
    if found.tool == "promptfoo":
        return [("question", "each test's vars"), ("answer", "each test's output"),
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
        return [("question", "each trace's request"), ("answer", "its response"),
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
        if m.get("model_key"):
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
    """Found, no marking started: Screen 1's "Find" block and the free checks, then the
    page."""
    if talk.counts_wait():  # the counts depend on the answers: they come after them
        _to_save(talk, found, mapped)  # noted with the others, so --yes answers it too
        talk.ask_noted()
    listed = _listed(found)
    talk.say()  # a blank line after what Find said first (a file left out), never two
    for line in found_block(found, talk.options["pass_if"], mapped):
        talk.say(line)
    if found.tool == "table" and _columns_line(found, talk.options["pass_if"]):
        talk.para(SCORE_READ)
    talk.say()
    pool = found.pool
    if pool.answers:
        talk.say(passed_failed(pool.n_pass, pool.n_fail))
    for note in _notes(found):
        talk.para(note)
    for others in (_other_files(found), _other_projects(found), _nested_here(found),
                   _outer_marks(found)):
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
    if n < start.MIN_POOL:
        talk.say()
        talk.para(f"You have {_n(n, 'answer')} with a clear grade. That is not enough answers "
                  "for a first result.")
        raise talk.stop(EXIT_QUESTION, (
            "run your eval to make more answers first (that makes model calls), then run "
            f"`{talk.command()}` again; or mark {'this one' if n == 1 else f'these {n}'} now "
            f"with `{_command_of(talk, saved, 'mark')}`."))
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
    unless judgekeeper.toml keeps them now."""
    path, options = answered(talk, saved)
    return " ".join((program(subcommand), *start.repeated_flags(path, **options)))


def _to_save(talk: FrontTalk, found: start.Found,
             mapped: settings.StartSettings | None) -> settings.StartSettings | None:
    """What judgekeeper.toml keeps after a yes, for what had to be asked: a map, or the
    answers at a terminal. None when there is nothing to keep or the person says no."""
    if mapped is None and not talk.answers:
        return None
    if mapped is not None:
        new, question = mapped, SAVE_MAP.format(file=mapped.file)
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
        talk.say("Nothing was saved.")
        raise talk.stop(EXIT_OK, f"nothing. judgekeeper reads {mapped.file} only once "
                                 f"judgekeeper.toml says how; run `{program()}` again to save "
                                 "it.")
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
    if over:
        for line in why:
            talk.para(line)
        over = talk.confirm(START_OVER, default=True, with_yes=True, hint="")
    talk.ask_noted()  # without a terminal, nothing is written or moved before the answers
    saved = to_save is not None and _save(talk, found, to_save, made=mapped is not None)
    if why is not None and not over:
        talk.say("Nothing was moved.")
        raise talk.stop(EXIT_OK, f"nothing. Your old marks stay in {FOLDER}/.")
    if over:
        if is_open(ws.dir):
            background.stop(ws.dir)
        start_again.move_to_previous(ws, talk.say)
    _write(found)  # judge.json and the free checks: the judge as it is now
    return _marking(talk, ws, found, wait, saved, marking)


def _why_start_over(talk: FrontTalk, ws: Workspace, found: start.Found) -> list[str] | None:
    """Why the marks saved in .judgekeeper/ can't be used for this judge, in lines; [] for
    --new on marks that could be; None when marking can go on. A new eval run is no reason:
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
    if (found.tool, found.metric) != (tool, metric):
        return [(f"Your marks are for other results: they are of the LLM-as-a-judge {judge} "
                 f"({tool}), and these results are of {found.judge}.")]
    return [] if talk.new else None


def _ran_again(ws: Workspace, found: start.Found) -> bool:
    """Whether the newest results differ from the ones being marked."""
    try:
        data = ws.data()
        marked = {q["id"]: q["group"] for q in data["queue"]}
        files = list(data.get("results_files") or [])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if data.get("results_seen") == batches.results_key(found):  # said, or added as a batch
        return False
    return files != list(found.used) or marked != {a.id: a.verdict for a in found.pool.answers}


def _marking(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool, saved: bool,
             marking: bool, first: bool = False) -> int:
    """The pool (prepared now unless it is there), then the page and the count (Screens 1, 2
    and 4), or for `judgekeeper` with enough marks the result."""
    from judgekeeper import check

    if not ws.start.is_file():
        with page.one_at_a_time(ws.dir, talk.say):  # two runs at once: one writes the pool
            if not ws.start.is_file():
                start_label.prepare(found, say=lambda line: None)
    start_label.repair(ws)  # a result whose saving was stopped half way
    head = [start_label.WORKED_OUT_AGAIN] if start_label.recompute_old(ws) else []
    back = None if first else check.back_to_marked(ws, found)  # the judge the marks were made on
    changed = [] if first or back else _changed(ws, found)
    grades = 0 if first or changed or back else check.grades_changed(ws, found)  # a table judge
    added = 0 if first or changed or back or grades else batches.add(ws, found)
    then = None  # new answers that came with changed grades: they wait, and the next step
    if back:
        head.append(back)
    elif changed or grades:
        head.append(JUDGE_CHANGED.format(what=", ".join(changed)) if changed
                    else check.GRADES.format(k=grades))
        then = _waiting(talk, ws, found, head, bool(changed))
    elif added:
        head.append(batches.added_line(added))
        if is_open(ws.dir):  # the page open shows the pool without the new batch
            background.stop(ws.dir)
    elif not first and _ran_again(ws, found):
        head.append(RAN_AGAIN_CHECKED if ws.data().get("checked_at") else RAN_AGAIN)
        batches.seen(ws, found)  # said once
    session = StartSession(ws)
    counts = session.counts()
    counted = list(batches.counted_labels(ws.data(), session.marked()).values())
    enough = min(counted.count("pass"), counted.count("fail")) >= targets.ROUGH
    every = bool(session.items) and all(i["label"] for i in session.items)
    if enough and not marking:
        return _result(talk, ws, found, wait, saved, head, check=bool(changed or grades))
    if every and not enough:  # nothing left to mark, and no result yet
        return _all_marked(talk, ws, counts, saved, head, then)
    return _page(talk, ws, counts, wait, saved, enough, head, marking, first, then)


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
    return (check.worse_step(was["before"], was["after"], _check_command(talk)) if was
            else NEXT_CHECK.format(command=_check_command(talk)))


def _all_marked(talk: FrontTalk, ws: Workspace, counts: dict, saved: bool,
                head: list[str], then: str | None = None) -> int:
    """Every answer is marked and a kind is still short: said, and no page (exit 3)."""
    talk.say(STEP.format(n=2, name="Mark"))
    talk.say()
    for line in head:
        talk.para(line)
    if head:
        talk.say()
    first, step = _all_marked_lines(talk, ws, counts, saved)
    talk.para(first)
    raise talk.stop(EXIT_QUESTION, then or step.removeprefix("Next: "))


def _all_marked_lines(talk: FrontTalk, ws: Workspace, counts: dict, saved: bool) -> list[str]:
    labels = {"correct": counts["correct"], "wrong": counts["wrong"]}
    return start_label.all_marked_lines(labels,
                                        start_label.mark_command(_command_of(talk, saved)))


def _open(talk: FrontTalk, ws: Workspace, wait: bool, saved: bool,
          result: bool = False) -> tuple[page.Page, str]:
    """A new page (the open one closed), shown: (the page, how it was shown). `result`:
    opened at its result page."""
    start_label.check_writable(ws)  # said here, never as "the page could not start"
    opened = None
    try:
        opened = page.open_new(ws, talk.options["port"], _command_of(talk, saved, "mark"),
                               _command_of(talk, saved), here=wait, say=talk.say)
        shown = opened and page.show(talk.say, opened, talk.options["no_browser"], wait,
                                     result)
    except KeyboardInterrupt:  # before its link was printed: no page is left running
        page.close(ws, opened)
        raise
    if not shown:
        if opened is not None and opened.server is None:
            background.stop(ws.dir)
        tried = page.choose_port(talk.options["port"], lambda line: None)
        if opened is None and not page.port_free(tried):  # --wait would need the same port
            path, options = answered(talk, saved)
            command = " ".join((program(), *start.repeated_flags(path, **{**options,
                                                                          "port": 0})))
            folder = page_folder(tried)
            if folder is not None:  # another project's page: it can be closed there
                talk.para(PORT_PAGE.format(port=tried, folder=folder))
                raise talk.stop(EXIT_QUESTION, NEXT_STOP_THERE.format(
                    stop=program("--stop"), command=command))
            talk.say(PORT_TAKEN.format(port=tried))
            raise talk.stop(EXIT_QUESTION, NEXT_ANY_PORT.format(command=command))
        talk.say(f"The marking page could not start in the background (what went wrong is in "
                 f"{shown_folder(ws)}/{background.LOG}).")
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
        talk.say(f"You have marked all {_n(n, 'answer')}. There are no more to mark.")
        talk.say()
        for line in head:
            talk.para(line)
        if head:
            talk.say()
        opened = None
        # disagreements the person can see: the result page, with its reason boxes
        if start_label.why_count(ws, start_label.compute(ws, session)):
            opened, shown = _open(talk, ws, wait, saved, result=True)
            talk.para(f"{RESULT_OPEN} {SAY_WHY}" if shown == page.BROWSER else SAY_WHY)
            if opened.server is not None:
                talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
            talk.say()
        talk.para("Next: " + then if then  # the new answers wait for a check
                  else _all_marked_lines(talk, ws, counts, saved)[1])  # they join later
        if opened is not None and opened.server is not None:
            page.serve(opened.server)
        return EXIT_OK
    talk.say(STEP.format(n=2, name="Mark (more answers)" if marking and enough else "Mark"))
    talk.say()
    for line in head:
        talk.para(line)
    if head:
        talk.say()
    if n:
        counted = list(batches.counted_labels(ws.data(), session.marked()).values())
        waiting = n - len(counted)
        if waiting:  # the counts before "not enough" are those that count, never the batch's
            talk.para(f"You marked {_n(n, 'answer')} so far: {counted.count('pass')} Pass, "
                      f"{counted.count('fail')} Fail count for a result, and {waiting} more "
                      f"{'is' if waiting == 1 else 'are'} in a newer batch that doesn't count "
                      "yet.")
        else:
            talk.say(f"You marked {_n(n, 'answer')} so far: {n_pass} Pass, {n_fail} Fail.")
        if not enough:
            talk.say(NOT_ENOUGH)
        talk.say()
    after = PRECISE if enough else BAR if n else SHOWS
    opened = None
    no_browser = talk.options["no_browser"]  # its link is printed again: a new page
    if not first and not marking and not wait and not no_browser and n and is_open(ws.dir):
        talk.para(f"The marking page is still open in your browser. {after}")
    else:
        opened, shown = _open(talk, ws, wait, saved)
        again = " again" if n and not marking else ""
        talk.para(f"The marking page is open in your browser{again}. {after}"
                  if shown == page.BROWSER else after)
        if opened.server is not None:
            talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    talk.say()
    next_step = (NEXT_MORE if enough else NEXT_KEEP_MARKING if n else NEXT_MARK)
    if opened is not None and opened.server is not None:
        page.serve(opened.server)  # Ctrl-C here: "Stopped." and its own Next line (cli)
    talk.para("Next: " + next_step.format(command=command))
    return EXIT_OK


def _pct(x: float) -> str:
    return f"{x:.0%}"


def agreement_lines(r: dict) -> list[str]:
    """Under the verdict, as on the result page: how many answers you and your judge
    disagreed on, then the two counts, indented."""
    from judgekeeper.report_page import counts

    c = counts(r)
    n, d = c["passed"] + c["failed"], c["strict"] + c["easy"]
    first = (f"You and your LLM-as-a-judge disagreed on {d} of {_n(n, 'answer')}." if d else
             f"You and your LLM-as-a-judge agreed on all {_n(n, 'answer')}.")
    return [first, "",
            (f"  You passed {_n(c['passed'], 'answer')}. Of those, your LLM-as-a-judge passed "
             f"{c['passed'] - c['strict']} and failed {c['strict']}."),
            (f"  You failed {_n(c['failed'], 'answer')}. Of those, your LLM-as-a-judge passed "
             f"{c['easy']} and failed {c['failed'] - c['easy']}.")]


def estimate_lines(r: dict) -> list[str]:
    """How often the judge agrees with you, estimated, as the result page's More details
    (report_page.estimate): "about 57% (between 37% and 74%)", or too early to tell."""
    from judgekeeper.report_page import estimate

    out = [AGREES]
    for said, key in (("Pass", "tpr"), ("Fail", "tnr")):
        shown, between = estimate(r.get(key), r.get(f"{key}_interval"))
        value = shown if between == "–" else f"{shown} (between {between})"
        out.append(f"  When you say {said}, it also says {said}: {value}")
    return out


def verdict_line(r: dict) -> str | None:
    """The one line on how good the judge is, "Result: ...", with the result page's
    headlines; None before a first result."""
    if r["verdict_level"] is None:
        return None
    verdict = r["verdict"]
    if start_label.all_labeled(r):  # nothing left to mark
        verdict = verdict.replace(f" {start_label.MARK_MORE}", "")
    return f"Result: {verdict[:1].lower()}{verdict[1:]}"


def _which_judge(ws: Workspace, found: start.Found) -> str | None:
    """When the judge's rule or model changed since marking started (or since the check that
    moved the marks to a new judge): which judge the result is about, as it was then."""
    data = ws.data()
    same_rule = rule_hash(data.get("rule")) == rule_hash(found.rule)
    if same_rule and not start_again.judge_change(data["fingerprint"], found.fingerprint):
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
    rule = f"rule hash {rule.removeprefix('sha256:')[:4]}" if rule else "rule not known"
    return f"This result is about your LLM-as-a-judge as it was{day}: {model}, {rule}."


def _check_command(talk: FrontTalk) -> str:
    """`judgekeeper check`, with the path when it is not this folder."""
    path = [] if talk.path == "." else [quote_arg(talk.path)]
    return " ".join((program("check"), *path))


def _result(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool, saved: bool,
            head: list[str], check: bool = False) -> int:
    """Step 3: the result from the marks, saved; whether the page is open. `check`: the
    judge changed since the marks, so the Next: line is `judgekeeper check`."""
    talk.say(STEP.format(n=3, name="Measure"))
    talk.say()
    for line in head:
        talk.para(line)
    if head:
        talk.say()
    from judgekeeper import check as checking
    from judgekeeper import fix

    fix.prepare_split(ws)  # before any mistake is shown or written: some marks are hidden
    session = StartSession(ws)
    was = checking.open_worse(ws, found) if check else None  # checking again says the same
    worse = was and checking.worse_step(was["before"], was["after"], _check_command(talk))
    r = start_label.store_result(ws, session, _command_of(talk, saved), worse=worse or None,
                                 redraw=True)
    made = marks.made(marks.read(ws.marks), ids=set(session.by_id))  # reasons added since
    for line in made_lines(made)[1:]:  # the notes on how they were made; the count is below
        talk.para(line)
        talk.say()
    talk.para(verdict_line(r))
    for line in agreement_lines(r):
        if line.startswith("  "):  # an indented count is said whole, never wrapped
            talk.say(line)
        else:
            talk.para(line)
    step = report_page.next_step(r)  # the report's next step
    # the Next: line runs `mark` (too early to tell, answers left): its command is named once
    mark_next = not worse and not check and step == "mark" and not start_label.all_labeled(r)
    why = not worse and start_label.why_count(ws, r)
    if why:  # the result page has a box on each
        talk.say()
        if mark_next:
            talk.para(SAY_WHY_NEXT)
        else:
            from judgekeeper.report_page import counts

            c = counts(r)
            talk.para(start_label.SAY_WHY_RUN.format(
                n=c["strict"] + c["easy"], command=_command_of(talk, saved, "mark")))
            if step != "mark":  # fix is never a step while it is too early to tell
                talk.para(start_label.SAY_WHY_FIX.format(fix=_command_of(talk, False, "fix")))
    if r["verdict_level"] in ("gate", "not_gate"):  # too early to tell: counts only
        talk.say()
        for line in estimate_lines(r):
            talk.say(line)
    which = _which_judge(ws, found)
    if which:
        talk.say()
        talk.para(which)
    left = batches.line(r.get("batches"))  # a batch with too few marks: never left out silently
    if left:
        talk.say()
        talk.para(left)
    talk.say()
    talk.say(f"Full report: {shown_folder(ws)}/{ws.report_html.name} (open it in your browser)")
    talk.say()
    opened = None
    if start_label.all_labeled(r):  # nothing left to mark: no page
        if step == "mark" and not check:
            labels = r["labels"]
            first, then = _all_marked_lines(talk, ws, {"correct": labels["correct"],
                                                       "wrong": labels["wrong"]}, saved)
            talk.para(first)
            talk.say()
            talk.para(then)
            return EXIT_NEEDS_YOU
    elif is_open(ws.dir):
        talk.para(STILL_OPEN)
    elif wait:
        opened, _ = _open(talk, ws, wait, saved)
        talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    elif not mark_next and not why:  # else the Next: line or "To say why" names it
        talk.para(MARK_ANY_TIME.format(command=_command_of(talk, saved, "mark")))
    if start_label.all_labeled(r) or is_open(ws.dir) or wait or not (mark_next or why):
        talk.say()
    if worse:
        next_step = worse
    elif check:
        next_step = NEXT_CHECK.format(command=_check_command(talk))
    elif step == "mark":  # too early to tell
        next_step = NEXT_MARK_MORE.format(command=_command_of(talk, saved, "mark"))
    elif step == "fix":
        next_step = NEXT_FIX.format(command=_check_command(talk).replace(
            program("check"), program("fix"), 1))
    else:
        next_step = NEXT_RESULT.format(command=_check_command(talk))
    talk.para("Next: " + next_step)
    if opened is not None:
        page.serve(opened.server)
    return EXIT_OK


def _stop(talk: FrontTalk, path: Path) -> int:
    """--stop: close the page open for this project."""
    if not path.exists():
        raise not_found(path)
    ws = Workspace(start_again._project(path))
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
    talk.para("Next: " + NEXT_CONTINUE.format(command=talk.command()))
    return EXIT_OK


__all__ = ["EXIT_NEEDS_YOU", "FrontTalk", "answered", "find_found", "found_block", "go", "run",
           "tool_version", "verdict_line"]
