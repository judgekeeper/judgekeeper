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
| at least 15 Pass + 15 Fail                   | the result (output B); says if the page    | 0    |
|                                              | is open                                    |      |
| marks for another judge (another metric or   | says why and asks "Start over...?" (the    | 3    |
| tool), or labels.csv from 0.2                | question list, then --yes)                 |      |

A new eval run does not start over: the answers being marked are in .judgekeeper/pool.jsonl,
so marking goes on with them and a result stays valid (marks are tests for the judge, not for
one results file); one line says the eval ran again. Only another judge or --new starts over.
When the judge's setup (judge_setup.py) changed since the marks, that line says what changed,
and once there are enough marks the result's Next: line is `judgekeeper check`, which re-tests
the new judge on them.
`judgekeeper mark` (mark.py) goes through the same table for marking more: it opens the page
in every row but "asked" and "start over", prints the count, and leaves the result to
`judgekeeper`. --wait serves the page in this process, --stop closes it (page.py).

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

from datetime import UTC, datetime
from pathlib import Path

from judgekeeper import (
    __version__,
    background,
    find,
    judge_check,
    judge_setup,
    marks,
    own_format,
    page,
    settings,
    start,
    start_again,
    start_label,
    targets,
)
from judgekeeper.fingerprint import rule_hash
from judgekeeper.label import DEFAULT_PORT, is_open
from judgekeeper.normalise import _numeric
from judgekeeper.records import RecordsError
from judgekeeper.start import EXIT_QUESTION, StartError, Stop
from judgekeeper.start_label import FOLDER, StartSession, Workspace, made_lines, shown_folder
from judgekeeper.textio import plural, program, quote_arg, wrap

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NEEDS_YOU = 3
RULE_SHOWN = 58  # characters of the judge's rule shown, "…" included, on one line
VALUE_WIDTH = 40  # characters of a judge's decision value shown
PASS_IF = '"score>=N"'  # the placeholder of --pass-if in a Next: line; quoted for every shell
LABEL_MAP = '"VALUE=pass,VALUE=fail"'
SAVE = "Save your answers in judgekeeper.toml, so judgekeeper does not ask again?"
SAVE_MAP = ("Save how to read {file} in judgekeeper.toml? judgekeeper reads it from there "
            "from now on.")
QUESTIONS = "judgekeeper needs your answer to {which}:"
READS = ("judgekeeper can read results from promptfoo, DeepEval, Inspect AI, MLflow, or a CSV "
         "or JSONL file.")
# The options that find the judge, as start.find_judge takes them
FIND = ("tool", "metric", "experiment", "tracking_uri", "pass_if", "label_map", "judge_model")
ASKED = {"--tool": "tool", "--metric": "metric", "--experiment": "experiment"}
START_OVER = f"Start over with these results? Your old marks move to {FOLDER}/previous-<date>/."
OLD_MARKS = (f"{FOLDER}/labels.csv holds marks from judgekeeper 0.2. They have no time stamps, "
             "so this version does not use them.")
RAN_AGAIN = "Your eval ran again. Your judge is the same, so your marks still test it."
JUDGE_CHANGED = "Your judge changed since your marks: {what}."
STEP = "Step {n} of 5: {name}"
INDENT = " " * 13  # under the value of "Eval tool:   "
EVERY_ANSWER = "every answer got a clear Pass or Fail."
FREE_CHECK = "Free check (no AI call): "
SHOWS = ("It shows the same answers one at a time. Mark each one Pass or Fail, the way you "
         "want your judge to decide. Your judge's grade stays hidden, so you decide on your "
         "own.")
BAR = "The bar at the top shows how close you are."
PRECISE = "Each new mark makes your numbers more precise."
NOT_ENOUGH = "That is not enough for a first result yet."
NEXT_MARK = "mark until the page says you have enough, then run `{command}` again."
NEXT_KEEP_MARKING = ("keep marking until the page says you have enough, then run `{command}` "
                     "again.")
NEXT_MORE = "mark more answers, then run `{command}` to see your updated result."
NEXT_ALL_MARKED = "run your eval again to get new answers, then run `{command}`."
NEXT_CHECK = "run `{command}` to re-check your changed judge on your marks."
NEXT_RESULT = ("nothing to do. When you change your judge or update your eval tool, run "
               "`{command}`.")
NEXT_CONTINUE = "run `{command}` when you want to continue."
STILL_OPEN = "The marking page is still open if you want to mark more answers."
MARK_ANY_TIME = "To mark more answers at any time, run `{command}`."
COULD_NOT = "run `{command}` in your own terminal (it keeps the page open there)."
PORT_TAKEN = "Port {port} is in use, so the marking page could not start."
NEXT_ANY_PORT = "run `{command}` (it opens the page on any free port)."
NO_DECISION = ("nothing to do now. Your judge made no real decision on any answer{listed}; run "
               "`{command}` again after your next eval run.")
# A tool found here with no saved results: what saves them
SAVES = {"deepeval": "DeepEval saves results only when you run deepeval test run or evaluate().",
         "inspect": "Inspect AI saves its logs in logs/ when you run inspect eval.",
         "mlflow": "MLflow keeps the judge's assessments once mlflow.genai.evaluate() runs."}
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
        names = ", ".join(quote_arg(str(v)) for v in values)
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
    try:
        if stop:
            return _stop(talk, path)
        if not marking and not _started(path):
            talk.say(STEP.format(n=1, name="Find"))
            talk.say()
        return _run(talk, path, wait, marking)
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
    found, mapped = find_found(talk, path)
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
        raise StartError(f"file or folder not found: {path}")
    where, saved = _own_format(talk, path)
    return _find(talk, where, saved), saved


def _own_format(talk: FrontTalk, path: Path) -> tuple[Path, settings.StartSettings | None]:
    """(where find_judge looks, the [start] table of an own-format file mapped now, or None).
    Nothing found at all: say where it looked, and stop."""
    from judgekeeper import own_map
    from judgekeeper.recorder import project_root

    o = talk.options
    if path.is_file():
        if o["tool"] is not None or find.classify_file(path) is not None or \
                path.suffix.lower() not in own_format.SUFFIXES:
            return path, None
        file, here = path.resolve(), Path.cwd().resolve()
        root = here if file.is_relative_to(here) else project_root(file.parent)
        return root, own_map.map_file(talk, root, file, o["metric"], o["judge_model"],
                                      o["pass_if"], found=False)
    root = path.resolve()
    if (o["tool"] is not None or o["tracking_uri"] is not None or find.is_mlflow_folder(path)
            or start._saved(root)):
        return path, None
    search = find.search(root)
    if (any(search.readable(t) for t in find.TOOLS) or search.too_big()
            or find.records_above(root) is not None or "promptfoo" in search.signs):
        return path, None  # find_judge reads them, or says how
    own = own_format.search(root)
    if own is None:
        raise _nothing_found(talk, root, search.signs)
    return root, own_map.map_file(talk, root, own.path, o["metric"], o["judge_model"],
                                  o["pass_if"], found=True)


def _find(talk: FrontTalk, path: Path, saved) -> start.Found:
    """find_judge, again after each answer about decisions it cannot read as Pass or Fail."""
    while True:
        options = {k: talk.options[k] for k in FIND}
        options.update({ASKED[f]: v for f, v in talk.answers.items() if f in ASKED})
        if saved is not None:  # a map made now holds the judge's model and its pass mark
            options.update(judge_model=None, pass_if=None)
            if str(options["metric"]).lower() in ("*", "all"):  # every judge: the map says so
                options["metric"] = None
        try:
            found = start.find_judge(path, talk=talk, saved=saved, store=talk.store, **options)
        except RecordsError as e:
            raise StartError(str(e)) from None
        if not found.pool.unmapped:
            return found
        _unread_values(talk, found)


def _shown(values) -> str:
    texts = [" ".join(str(v).split()) for v in values]
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
        for line in found_block(found):  # what was found, before the question
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
        talk.say(f"Your judge's decisions are scores ({_shown(values)}), and the results do "
                 "not say which score passes.")
        if not terminal:
            raise talk.stop(EXIT_QUESTION, "decide which score counts as a pass, then run "
                                           f"`{talk.command('--pass-if', PASS_IF)}`.")
        while True:
            answer = talk.ask("Pass when the score is at least", "0.5")
            if _numeric(answer):
                talk.set("pass_if", f"score>={answer}")
                return
    words = [str(v) for v in values if not _numeric(v)]
    talk.say(f"judgekeeper can't tell which of your judge's decisions mean Pass and which mean "
             f"Fail: {_shown(words)}.")
    if not terminal:
        raise talk.stop(EXIT_QUESTION, (
            f"decide which of these mean Pass and which mean Fail ({_shown(words)}), then run "
            f"`{talk.command('--label-map', LABEL_MAP)}`."))
    picked = []
    for w in words:
        i = talk.choose(f"Does {w!r} mean Pass or Fail?", ["Pass", "Fail"], "")
        picked.append(f"{w}={('pass', 'fail')[i]}")
    _add_label_map(talk, ",".join(picked))


def _nothing_found(talk: FrontTalk, root: Path, signs: dict) -> Stop:
    """No results: the tools found here (with what saves their results), else what
    judgekeeper can read. The folder by its name only."""
    if signs:
        for tool, where in signs.items():
            name = find.NAMES[tool]
            talk.para(f"Found {name} in this folder ({where[0]}), but no saved results yet. "
                      + SAVES.get(tool, ""))
    else:
        talk.say(f"No eval results found in this folder ({root.name}).")
        talk.para(READS)
    again = f"`{talk.command()}`"
    other = "" if signs else f" If your results are in another folder, run {again} from there."
    return talk.stop(EXIT_QUESTION, f"run your eval once from this folder, then run {again} "
                                    f"again.{other}")


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


def _columns_line(found: start.Found) -> str | None:
    """Which columns of a table were read (never the rows)."""
    columns = find.table_columns(found.results[0].path)
    verdict = next((c for c in find.VERDICT_COLUMNS if c in columns), None)
    read = ("input", "output", verdict, "reason", "model", "judge_model", "app_version",
            *start.HUMAN_COLUMNS)
    used = [c for c in columns if c in read]
    return f"Read the columns {start._and(used)}." if used else None


def _map_line(saved: settings.StartSettings) -> str:
    """How an own-format file is read, as judgekeeper.toml says: paths only."""
    from judgekeeper import mapper

    m = saved.map
    score = "score" if m.get("kind", "score") == "score" else "decision"
    return (f"Read as {settings.FILE} says: input {mapper.shown(m['input'])}, answer "
            f"{mapper.shown(m['output'])}, {score} {mapper.shown(m['score'])}.")


def _notes(found: start.Found) -> list[str]:
    pool, out = found.pool, list(found.stopped)
    if pool.n_merged:
        out.append(f"{_n(pool.n_merged, 'repeat')} of the same answer "
                   f"{'was' if pool.n_merged == 1 else 'were'} merged.")
    if pool.n_human:
        out.append(f"Your results also hold {_n(pool.n_human, 'human label')}. judgekeeper does "
                   "not use them: you mark the answers yourself.")
    n = len(pool.answers)
    for count, did, too in ((pool.n_fail, "failed", "passes too much"),
                            (pool.n_pass, "passed", "fails too much")):
        if 0 < count < start.ROUGH and n >= start.MIN_POOL:  # a small pool is said below
            out.append(f"Your judge {did} only {count} of {n} answers. That may mean it {too}: "
                       "your marks will show it.")
    return out


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
    start_label.save_judge_check(ws, found)  # also when it lists nothing: no list stays stale
    if not ws.start.is_file() or judge_setup.read(ws) is None:
        judge_setup.save(ws, judge_setup.of(found), found.metric)


def _changed(ws: Workspace, found: start.Found) -> list[str]:
    """What changed in the judge's setup since the one judge.json keeps, in words."""
    saved = judge_setup.read(ws)
    return judge_setup.changes(saved["setup"], judge_setup.of(found)) if saved else []


TOOL_NAMES = {**find.NAMES, "records": "judgekeeper.record() in your code",
              "mapped": "your own format"}


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
    else:
        model = "model not named in your results (add --judge-model NAME)"
    return ", ".join([*parts, model])


def _rule_file(found: start.Found) -> str | None:
    """The file the judge's rule comes from, when judgekeeper knows it."""
    if found.tool == "promptfoo":
        return next((n for n in find.PROMPTFOO_CONFIGS if (Path(found.root) / n).is_file()),
                    None)
    return found.task_file if found.tool == "inspect" else None


def _rule_lines(found: start.Found) -> list[str]:
    if not found.rule:
        return ["Judge rule:  not in your results"]
    text = " ".join(found.rule.split())
    if len(text) <= RULE_SHOWN:
        return [f'Judge rule:  "{text}"']
    where = _rule_file(found)
    return [f'Judge rule:  "{text[:RULE_SHOWN - 1].rstrip()}…"',
            f"{INDENT}(shortened{f'; full rule in {where}' if where else ''})"]


def found_block(found: start.Found) -> list[str]:
    """Screen 1's "Find" block: the eval tool, the answers, the judge and its rule."""
    answers = found.check.answers if found.check else len(found.pool.answers)
    tool = TOOL_NAMES.get(found.tool, found.tool)
    if found.tool == "table":  # named by its kind: "your own CSV file"
        tool = f"your own {Path(found.results[0].rel).suffix.lstrip('.').upper()} file"
    lines = [f"Eval tool:   {tool}",
             f"Answers:     {_n(answers, 'answer')} from your app, each graded by your judge",
             f"{INDENT}(read from {_read_from(found)})",
             f"Judge:       {_judge_value(found)}", *_rule_lines(found)]
    if found.pass_mark:
        lines.append(f"Pass mark:   {start._pass_mark_words(found.pass_mark)}")
    return lines


def _free_check(talk: FrontTalk, found: start.Found, listed: str) -> None:
    """The free checks, each a paragraph: what was found, where its list is, then what can
    change the judge without judgekeeper seeing it."""
    block = found.check.block() if found.check else None
    findings = [" ".join(f) for f in judge_check.lines(block)]
    if not findings:
        talk.para(FREE_CHECK + EVERY_ANSWER)
    for i, finding in enumerate(findings):
        talk.para(FREE_CHECK + finding[:1].lower() + finding[1:] if i == 0 else finding)
    if findings and judge_check.has_rows(block):
        talk.para(f"The list is in {listed}.")
    for line in judge_check.setup_lines(found, judge_setup.of(found)):
        talk.para(line)


def _say(talk: FrontTalk, found: start.Found, mapped: settings.StartSettings | None,
         wait: bool) -> int:
    """Found, no marking started: Screen 1's "Find" block and the free checks, then the
    page."""
    listed = _listed(found)
    for line in found_block(found):
        talk.say(line)
    if found.tool == "table":
        talk.para(_columns_line(found) or "")
    if found.tool == "mapped" and mapped is None:
        saved = start._saved(found.root)
        if saved is not None and saved.map:
            talk.para(_map_line(saved))
    talk.say()
    pool = found.pool
    if pool.answers:
        talk.say(f"Your judge's grades: {pool.n_pass} Pass, {pool.n_fail} Fail.")
    for note in _notes(found):
        talk.para(note)
    _free_check(talk, found, listed)
    if not pool.answers:
        talk.ask_noted()
        _write(found)
        talk.say()
        talk.para("No answer has a clear Pass or Fail from your judge, so there is nothing to "
                  "mark.")
        raise talk.stop(EXIT_OK, NO_DECISION.format(listed=f" (the list is in {listed})",
                                                    command=talk.command()))
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
        if found.tool == "deepeval" and talk.store is not None:  # which folder
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
    talk.say(f"Saved {settings.FILE} (where your judge's results are and how to read them).")
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
        talk.para("No answer has a clear Pass or Fail from your judge, so there is nothing to "
                  "mark.")
        raise talk.stop(EXIT_OK, NO_DECISION.format(listed="", command=program()))
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
        return [(f"Your marks are for other results: they are of the judge {judge} ({tool}), "
                 f"and these results are of {found.judge}.")]
    return [] if talk.new else None


def _ran_again(ws: Workspace, found: start.Found) -> bool:
    """Whether the newest results differ from the ones being marked."""
    try:
        data = ws.data()
        marked = {q["id"]: q["group"] for q in data["queue"]}
        files = list(data.get("results_files") or [])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return files != list(found.used) or marked != {a.id: a.verdict for a in found.pool.answers}


def _marking(talk: FrontTalk, ws: Workspace, found: start.Found, wait: bool, saved: bool,
             marking: bool, first: bool = False) -> int:
    """The pool (prepared now unless it is there), then the page and the count (Screens 1, 2
    and 4), or for `judgekeeper` with enough marks the result."""
    if not ws.start.is_file():
        start_label.prepare(found, say=lambda line: None)
    counts = StartSession(ws).counts()
    enough = min(counts["correct"], counts["wrong"]) >= targets.ROUGH
    head = []
    changed = [] if first else _changed(ws, found)
    if changed:
        head.append(JUDGE_CHANGED.format(what=", ".join(changed)))
    elif not first and _ran_again(ws, found):
        head.append(RAN_AGAIN)
    if enough and not marking:
        return _result(talk, ws, found, wait, saved, head, check=bool(changed))
    return _page(talk, ws, counts, wait, saved, enough, head, marking, first)


def _open(talk: FrontTalk, ws: Workspace, wait: bool, saved: bool) -> tuple[page.Page, str]:
    """A new page (the open one closed), shown: (the page, how it was shown)."""
    opened = page.open_new(ws, talk.options["port"], _command_of(talk, saved),
                           _command_of(talk, saved, "start"), here=wait, say=talk.say)
    shown = opened and page.show(talk.say, opened, talk.options["no_browser"], wait)
    if not shown:
        if opened is not None and opened.server is None:
            background.stop(ws.dir)
        tried = page.choose_port(talk.options["port"], lambda line: None)
        if opened is None and not page.port_free(tried):  # --wait would need the same port
            talk.say(PORT_TAKEN.format(port=tried))
            path, options = answered(talk, saved)
            command = " ".join((program(), *start.repeated_flags(path, **{**options,
                                                                          "port": 0})))
            raise talk.stop(EXIT_QUESTION, NEXT_ANY_PORT.format(command=command))
        talk.say(f"The marking page could not start in the background (what went wrong is in "
                 f"{shown_folder(ws)}/{background.LOG}).")
        raise talk.stop(EXIT_QUESTION, COULD_NOT.format(command=talk.command("--wait")))
    return opened, shown


def _page(talk: FrontTalk, ws: Workspace, counts: dict, wait: bool, saved: bool,
          enough: bool, head: list[str], marking: bool, first: bool) -> int:
    """Step 2: the count so far and the page, opened in the browser (its link printed with
    --no-browser). `judgekeeper` again before a first result keeps a page that is still open
    (its tab still works); `mark` always opens a new one."""
    n_pass, n_fail = counts["correct"], counts["wrong"]
    n = n_pass + n_fail
    items = StartSession(ws).items
    command = _command_of(talk, saved)
    if marking and n and n == len(items):
        talk.say(f"You have marked all {_n(n, 'answer')}. There are no more to mark.")
        talk.say()
        talk.para("Next: " + NEXT_ALL_MARKED.format(command=_command_of(talk, saved, "mark")))
        return EXIT_OK
    talk.say(STEP.format(n=2, name="Mark (more answers)" if marking and enough else "Mark"))
    talk.say()
    for line in head:
        talk.para(line)
    if head:
        talk.say()
    if n:
        talk.say(f"You have marked {_n(n, 'answer')} so far ({n_pass} Pass, {n_fail} Fail).")
        if not enough:
            talk.say(NOT_ENOUGH)
        talk.say()
    after = PRECISE if enough else BAR if n else SHOWS
    opened = None
    if not first and not marking and not wait and n and is_open(ws.dir):
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
    talk.para("Next: " + next_step.format(command=command))
    if opened is not None and opened.server is not None:
        page.serve(opened.server)
    return EXIT_OK


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _rate(said: str, did: str, value, interval) -> str:
    start_words = f"Of the answers you {said}, your judge {did}"
    if value is None:
        return f"{start_words}: not known yet."
    lo, hi = interval or (None, None)
    if lo is None or hi is None:
        return f"{start_words} {_pct(value)}."
    if hi - lo <= 1e-12:
        return f"{start_words} {_pct(value)} (exactly)."
    return f"{start_words} {_pct(value)} (range {_pct(lo)} to {_pct(hi)})."


def verdict_line(r: dict) -> str:
    """The one line on how good the judge is: which way it goes wrong, when it is not good
    enough and leans one way."""
    tpr, tnr = r["tpr"], r["tnr"]
    if r["verdict_level"] == "not_gate" and None not in (tpr, tnr) and tpr != tnr:
        return ("Your judge passes too many answers you failed." if tnr < tpr
                else "Your judge fails too many answers you passed.")
    return r["verdict"]


def _which_judge(ws: Workspace, found: start.Found) -> str | None:
    """When the judge's rule or model changed since marking started: which judge the result
    is about, as it was then."""
    data = ws.data()
    same_rule = rule_hash(data.get("rule")) == rule_hash(found.rule)
    if same_rule and not start_again.judge_change(data["fingerprint"], found.fingerprint):
        return None
    head = marks.read(ws.marks).header or {}
    judge = head.get("judge") or start_label.judge_of(data)
    try:
        made = datetime.strptime(head.get("created_at") or data.get("started_at") or "",
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
        day = f" on {made.day} {MONTHS[made.month - 1]}"
    except ValueError:
        day = ""
    model = judge.get("model") or "model not named"
    rule = judge.get("rule_hash")
    rule = f"rule hash {rule.removeprefix('sha256:')[:4]}" if rule else "rule not known"
    return f"This result is about your judge as it was{day}: {model}, {rule}."


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
    session = StartSession(ws)
    r = start_label.store_result(ws, session, _command_of(talk, saved, "start"))
    made = r.get("made") or marks.made(marks.read(ws.marks), ids=set(session.by_id))
    for line in made_lines(made):
        talk.para(line)
    talk.say()
    talk.para(_rate("passed", "passed", r["tpr"], r.get("tpr_interval")))
    talk.para(_rate("failed", "failed", r["tnr"], r.get("tnr_interval")))
    kappa = "unknown" if r["kappa"] is None else f"{r['kappa']:.2f}"
    talk.say(f"Kappa (agreement beyond chance): {kappa}.")
    talk.para(verdict_line(r))
    which = _which_judge(ws, found)
    if which:
        talk.para(which)
    talk.say()
    drop = targets.drop_line(r.get("smallest_drop", targets.smallest_drop(
        r["labels"]["correct"], r["labels"]["wrong"])))
    if drop:
        talk.para(drop)
    talk.say(f"Report: {shown_folder(ws)}/{ws.report_html.name}")
    talk.say()
    opened = None
    if is_open(ws.dir):
        talk.say(STILL_OPEN)
    elif wait:
        opened, _ = _open(talk, ws, wait, saved)
        talk.say("The page stays open while this runs. To stop it: Ctrl-C.")
    else:
        talk.para(MARK_ANY_TIME.format(command=_command_of(talk, saved, "mark")))
    talk.say()
    next_step = NEXT_CHECK if check else NEXT_RESULT
    talk.para("Next: " + next_step.format(command=_check_command(talk)))
    if opened is not None:
        page.serve(opened.server)
    return EXIT_OK


def _stop(talk: FrontTalk, path: Path) -> int:
    """--stop: close the page open for this project."""
    if not path.exists():
        raise StartError(f"file or folder not found: {path}")
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
