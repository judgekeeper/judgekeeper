"""`judgekeeper setup`: set a project up in one step, with one yes for every file change.

1. Find what there is: an eval tool's results or judgekeeper.record() files (`start` reads
   them as they are), else a results file in the project's own format (own_format.search),
   or the file named on the command line.
2. Map an own-format file (mapper.py): list its nested paths, show the guess, and ask only
   what the file cannot tell: whether each of several answers per item (A and B) is its own
   answer, which judge to check when there are several, the pass mark when the scores are
   not between 0 and 1, whether to leave out answers with an error or a score made by a
   rule, and one confirm line when a guess goes by value types only. Then 3 answers as
   judgekeeper will read them.
3. One question lists every file change: judgekeeper.toml's [start] table, the .gitignore
   lines (in a Git repository, when missing), and judgekeeper in the dev requirements (the
   first of pyproject.toml's dev group or dev extra, requirements-dev.txt,
   requirements-dev.in; only when judgekeeper is not listed; never the main requirements).
   `--yes` answers it; without a terminal and without `--yes` it prints the list and exits 8
   (start.EXIT_QUESTION, as for every question it cannot ask).

Nothing is written before that yes, and the user's code is never edited. When a file cannot
be mapped, or the guess is wrong, it prints the prompt for a coding agent (own_format) and
the record() door. Exit 0 when a source is set up (or already was), 2 when none was found,
8 when it stopped at a question.
"""

from __future__ import annotations

import copy
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import find, mapper, own_format, settings
from judgekeeper.recorder import project_root
from judgekeeper.records import LLM
from judgekeeper.start import EXIT_OK, EXIT_USAGE, StartError, Stop, Talk, _or, find_judge
from judgekeeper.textio import line_ending, quote_arg, read_utf8, tick, write_keeping

MAX_PATHS = 24
EXAMPLES = 3
NOT_LISTED = ("judgekeeper is not listed in your project's requirements; add it so teammates "
              "get it")
GITIGNORE = ("# judgekeeper: your answers and labels stay off Git; a gate baseline is shared",
             ".judgekeeper/*", "!.judgekeeper/baseline.json", "!.judgekeeper/migrations/")
RECORD_DOOR = ("Or save your judge's verdicts from now on with one judgekeeper.record() line "
               "where it runs: judgekeeper record --agent-prompt prints a prompt that asks your "
               "coding agent to add it.")
NEXT = "Next: judgekeeper start"


@dataclass
class Change:
    text: str  # the line in the list
    apply: Callable[[], None] | None  # None: nothing to change, only something to know
    done: str = ""


# The .gitignore lines ---------------------------------------------------------------------

def gitignore_change(root: Path) -> Change | None:
    """Adding .judgekeeper/ to .gitignore, in a Git repository where it is missing."""
    if not (root / ".git").exists():
        return None
    path = root / ".gitignore"
    text = read_utf8(path, StartError) if path.is_file() else ""
    for line in text.splitlines():
        if line.strip().lstrip("/").rstrip("*").rstrip("/") == ".judgekeeper":
            return None

    def apply():  # in the file's own line endings
        eol = line_ending(text)
        before = text if not text or text.endswith("\n") else text + eol
        write_keeping(path, before + eol.join(GITIGNORE) + eol)

    return Change("add .judgekeeper/ to .gitignore (your answers stay off Git)", apply,
                  "Added .judgekeeper/ to .gitignore")


# The requirements line --------------------------------------------------------------------

_LISTED_TOML = re.compile(r"""["']judgekeeper\s*(?:["'\[<>=!~;@ ])""", re.IGNORECASE)
_LISTED_LINE = re.compile(r"^\s*judgekeeper\s*(?:[\[<>=!~;@#]|$)", re.IGNORECASE)
_HEADER = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")
_DEV = re.compile(r"^(\s*)dev\s*=\s*\[")
FORMS = (("the dev group in pyproject.toml", ("dependency-groups", "dev"), "dependency-groups"),
         ("the dev extra in pyproject.toml", ("project", "optional-dependencies", "dev"),
          "project.optional-dependencies"))


def _listed(root: Path) -> bool:
    files = [root / "pyproject.toml", *sorted(root.glob("requirements*.txt")),
             *sorted(root.glob("requirements*.in"))]
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".toml":
            if _LISTED_TOML.search(text):
                return True
        elif any(_LISTED_LINE.match(line) for line in text.splitlines()):
            return True
    return False


def _nested(data: dict, keys: tuple):
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _added(text: str, header: str) -> str | None:
    """pyproject.toml's text with "judgekeeper" added to the `dev = [...]` list of the table
    `header`, or None when the list is not where or how judgekeeper edits it."""
    eol = line_ending(text)  # new lines end as the file's lines do
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines)
                  if (m := _HEADER.match(line)) and m.group(1).replace(" ", "") == header),
                 None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
    at = next((i for i in range(start + 1, end) if _DEV.match(lines[i])), None)
    if at is None:
        return None
    line = lines[at]
    if "#" in line:
        return None
    if "]" in line:  # one line: dev = ["pytest"]
        close = line.rindex("]")
        inside = line[line.index("[") + 1:close].strip()
        item = '"judgekeeper"' if not inside else (
            ' "judgekeeper"' if inside.endswith(",") else ', "judgekeeper"')
        lines[at] = line[:close].rstrip() + item + line[close:] if inside else \
            line[:close] + item + line[close:]
        return "".join(lines)
    close = next((i for i in range(at + 1, end) if lines[i].strip().startswith("]")), None)
    if close is None:
        return None
    items = [i for i in range(at + 1, close) if lines[i].strip()]
    if any("#" in lines[i] for i in items):
        return None
    if not items:
        lines.insert(close, f'    "judgekeeper",{eol}')
        return "".join(lines)
    last = items[-1]
    indent = lines[last][:len(lines[last]) - len(lines[last].lstrip())]
    trailing = lines[last].rstrip().endswith(",")
    if not trailing:
        lines[last] = lines[last].rstrip("\r\n") + "," + eol
    lines.insert(last + 1, f'{indent}"judgekeeper"{"," if trailing else ""}{eol}')
    return "".join(lines)


def requirements_change(root: Path) -> Change | None:
    """Adding judgekeeper to the first dev requirements form the project has. None when it is
    listed already; a Change with nothing to apply when there is no form to add it to."""
    if _listed(root):
        return None
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = read_utf8(pyproject, StartError)
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            data = {}
        for where, keys, header in FORMS:
            old = _nested(data, keys)
            if not isinstance(old, list):
                continue
            new = _added(text, header)
            want = copy.deepcopy(data)
            _nested(want, keys[:-1])[keys[-1]] = [*old, "judgekeeper"]
            try:
                ok = new is not None and tomllib.loads(new) == want
            except tomllib.TOMLDecodeError:
                ok = False
            if not ok:
                return Change(f"judgekeeper is not listed in your project's requirements, and "
                              f"{where} has a shape judgekeeper does not edit: add it to "
                              f"{where} yourself", None)
            return Change(f"add judgekeeper to {where}",
                          lambda new=new: write_keeping(pyproject, new),
                          f"Added judgekeeper to {where}")
    for name in ("requirements-dev.txt", "requirements-dev.in"):
        path = root / name
        if path.is_file():
            text = read_utf8(path, StartError)

            def apply(path=path, text=text):  # in the file's own line endings
                eol = line_ending(text)
                before = text if not text or text.endswith("\n") else text + eol
                write_keeping(path, before + "judgekeeper" + eol)

            return Change(f"add judgekeeper to {name}", apply, f"Added judgekeeper to {name}")
    return Change(NOT_LISTED, None)


# judgekeeper.toml -------------------------------------------------------------------------

def settings_change(root: Path, saved: settings.StartSettings) -> Change:
    path = root / settings.FILE
    text = read_utf8(path, StartError) if path.is_file() else None
    why = "(where your judge's results are and how to read them)"
    try:
        new = settings.merged(text, saved)
    except settings.SettingsError as e:
        return Change(f"{e}: add this to it yourself:\n{settings.render(saved)}", None)
    if text is None:
        line = f"save {settings.FILE} {why}"
    elif re.search(r"^\s*\[\s*start\s*[\].]", text, re.MULTILINE):
        line = f"change the [start] table in {settings.FILE} {why}"
    else:
        line = f"add a [start] table to {settings.FILE} {why}"
    return Change(line, lambda: write_keeping(path, new), f"Saved {settings.FILE}")


# Mapping an own-format file ---------------------------------------------------------------

def _cannot(talk: Talk, why: str) -> None:
    """The file cannot be mapped: what to do instead."""
    talk.say(f"judgekeeper cannot read it by itself: {why}.")
    talk.say("Ask your coding agent to turn your results into judgekeeper's table. Paste this "
             "into Claude Code, Cursor or Codex:")
    talk.say()
    for line in own_format.AGENT_PROMPT.splitlines():
        talk.say(line)
    talk.say()
    talk.say(RECORD_DOOR)


def _how(g: mapper.Guess) -> list[str]:
    each = f"each item of {g.each}" if g.each else "each line or row"
    answer = mapper.shown(g.output) + (f" ({' and '.join(g.sides)})" if g.sides else "")
    score = mapper.shown(g.score) + (f" (judges: {', '.join(g.judges)})" if g.judges else "")
    label = "score:" if g.kind == "score" else "verdict:"
    lines = [f"  one answer:      {each}", f"  input:           {mapper.shown(g.input)}",
             f"  answer:          {answer}", f"  {label:<17}{score}"]
    if g.reason:
        lines.append(f"  reason:          {mapper.shown(g.reason)}")
    if g.id:
        lines.append(f"  id:              {g.id}")
    lines.append(f"  judge's model:   {g.model_key} ({g.model})" if g.model_key else
                 "  judge's model:   not in the file")
    if g.kind == "score":
        sure = " (the scores are between 0 and 1)" if g.pass_mark_sure else ""
        lines.append(f"  pass mark:       {g.pass_mark}{sure}")
    return lines


def _count(units: list, g: mapper.Guess, judge: str) -> int:
    n = 0
    for unit in units:
        for item, _ in mapper._safe_items(unit, g.each):
            for side in g.sides or [None]:
                try:
                    mapper.get(item, g.score, side, judge)
                    n += 1
                except mapper.Missing:
                    continue
    return n


def _choose_judge(talk: Talk, units, g: mapper.Guess, metric: str | None) -> str | None:
    if not g.judges:
        return None
    if metric is not None:
        if metric.lower() in ("*", "all"):
            return "*"
        if metric not in g.judges:
            raise StartError(f"no judge named {metric!r}; judges are: "
                             f"{', '.join(repr(j) for j in g.judges)}")
        return metric
    if len(g.judges) == 1:
        return g.judges[0]
    options = [f"{j} ({_count(units, g, j)} answers)" for j in g.judges]
    flags = _or([f"--metric {quote_arg(j)}" for j in g.judges] + ["--metric all"])
    i = talk.choose("Which judge do you want to check?", [*options, "All, one at a time"],
                    f"Several judges found; choose one with {flags}")
    return "*" if i == len(g.judges) else g.judges[i]


def _plain(value) -> str:
    """A value as one line of text, cut to mapper.EXAMPLE_WIDTH."""
    import json

    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    width = mapper.EXAMPLE_WIDTH
    return text[:width - 1] + "…" if len(text) > width else text


def _example_lines(records, m: dict) -> list[str]:
    out = []
    for n, r in enumerate(records[:EXAMPLES], 1):
        side = next((x for x in m.get("sides") or [] if str(r.target_id).endswith(f":{x}")),
                    None)
        label = f"Answer {side}" if side else "Answer"
        out += [f"  {n}. Input: {_plain(r.input)}", f"     {label}: {_plain(r.output)}"]
        if r.score is not None and m.get("pass_mark") is not None:
            verdict = (f"{r.name}: {r.score:g}, {r.label} (pass mark {m['pass_mark']:g})")
        else:
            verdict = f"{r.name}: {r.label if r.label is not None else 'no verdict'}"
        reason = f" Reason: {_plain(r.explanation)}" if r.explanation else ""
        out.append(f"     {verdict}.{reason}")
    return out


def map_file(talk: Talk, root: Path, path: Path, metric: str | None,
             judge_model: str | None, found: bool) -> settings.StartSettings | None:
    """The settings for an own-format results file, after the few questions; None when it
    cannot be mapped or the person says the guess is wrong."""
    from judgekeeper.readers.mapped import read_mapped

    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    try:
        numbered = mapper.load_numbered(path)
    except mapper.MapError as e:
        _cannot(talk, str(e))
        return None
    units = [u for _, u in numbered]
    lines = f"{len(units)} {'line' if len(units) == 1 else 'lines'}"
    talk.say(f"{rel} looks like your judge's results in a format of its own ({lines})."
             if found else f"{rel} ({lines}):")
    try:
        g = mapper.guess(units)
    except mapper.MapError as e:
        _cannot(talk, str(e))
        return None
    listed = mapper.listing(units[0], g.judges)
    talk.say("What one line holds:" if len(units) > 1 else "What it holds:")
    width = min(max(len(p) for p, _ in listed[:MAX_PATHS]), 44)
    for p, example in listed[:MAX_PATHS]:
        talk.say(f"  {p:<{width}}  {example}")
    if len(listed) > MAX_PATHS:
        talk.say(f"  and {len(listed) - MAX_PATHS} more")
    talk.say()
    talk.say("How judgekeeper reads it:")
    for line in _how(g):
        talk.say(line)
    talk.say()
    if g.unsure and not talk.confirm(
            "Is this right?", default=True, with_yes=True,
            hint="judgekeeper is not sure how to read this file. Run judgekeeper setup in a "
                 "terminal to check its guess."):
        _cannot(talk, "the guess was not right")
        return None

    sides = list(g.sides)
    if len(sides) > 1 and not talk.confirm(
            f"Each item has {len(sides)} answers ({' and '.join(sides)}). Count each as its "
            "own answer?", default=True, with_yes=True, hint="Count each as its own answer?"):
        sides = [sides[talk.choose("Which one do you want to check?", sides,
                                   "Run judgekeeper setup in a terminal to choose one.")]]
    judge = _choose_judge(talk, units, g, metric)
    mark = g.pass_mark
    if g.kind == "score" and not g.pass_mark_sure:
        answer = talk.ask("Pass when the score is at least", str(mark))
        if answer is not None:
            try:
                value = float(answer)
                mark = int(value) if value.is_integer() else value
            except ValueError:
                talk.say(f"  {answer!r} is not a number: the pass mark stays {mark}.")
    m = {**g.to_map(), "sides": sides}
    chosen = g.judges if judge == "*" else [judge] if judge else []
    left = mapper.left_out(units, mapper.Guess(**{**g.__dict__, "sides": sides}), chosen) \
        if chosen or not g.judges else 0
    if left and talk.confirm(
            f"{left} answers have an error or a score made by a rule (a reason starting "
            '"Rule"), not by your judge. Leave them out?', default=True, with_yes=True,
            hint="Leave them out?"):
        m["leave_out"] = True
    saved = settings.StartSettings(source="map", file=rel, judge=judge, pass_mark=mark
                                   if g.kind == "score" else None, model=judge_model, map=m)
    if not g.model_key and not judge_model:
        talk.say("Your results do not say which model judged. To record it: judgekeeper setup "
                 "--judge-model NAME")
    records = [r for _, recs in read_mapped(path, {**m, "judge": judge, "pass_mark":
                                                    saved.pass_mark, "model": judge_model})
               for r in recs if r.annotator_kind == LLM]
    if not records:
        _cannot(talk, "no answer could be read with this map")
        return None
    talk.say()
    talk.say("Three answers as judgekeeper will read them:")
    for line in _example_lines(records, {"pass_mark": saved.pass_mark, "sides": sides}):
        talk.say(line)
    talk.say()
    return saved


# The conversation -------------------------------------------------------------------------

def _doors(talk: Talk, root: Path) -> None:
    talk.say(f"No saved eval results found in {root}, and no file that looks like your "
             "judge's results.")
    talk.say("Three ways on:")
    talk.say("  1. Your judge saves its results in a file of its own: judgekeeper setup "
             "path/to/results.jsonl (no code change).")
    talk.say("  2. Save your judge's verdicts from now on with one judgekeeper.record() line "
             "where it runs: judgekeeper record --agent-prompt prints a prompt that asks your "
             "coding agent to add it (judgekeeper record --snippet python shows the line).")
    talk.say("  3. Ask your coding agent to turn your results into judgekeeper's table: "
             "judgekeeper start --agent-prompt prints the prompt.")


def _tool_source(talk: Talk, root: Path, metric: str | None, judge_model: str | None,
                 tool: str) -> settings.StartSettings:
    found = find_judge(root, tool=tool, metric=metric, judge_model=judge_model, talk=talk)
    talk.say(f"  judgekeeper start reads them as they are; {settings.FILE} keeps which tool "
             "and which judge.")
    talk.say()
    return settings.StartSettings(source=found.tool, judge=found.metric, model=judge_model)


def _source(talk: Talk, root: Path, file: Path | None, metric: str | None,
            judge_model: str | None) -> settings.StartSettings | None:
    if file is not None:
        kind = find.classify_file(file)
        if kind is not None:
            raise StartError(f"{file.name} is {find.NAMES[kind]} results: judgekeeper start "
                             "reads it as it is. Run judgekeeper setup in your project folder.")
        return map_file(talk, root, file, metric, judge_model, found=False)
    search = find.search(root)
    tools = [t for t in find.TOOLS if search.readable(t)]
    if tools:  # find_judge says where it looks
        return _tool_source(talk, root, metric, judge_model, tools[0] if len(tools) == 1
                            else None)
    talk.say(f"Looking in {root} ...")
    talk.say()
    own = own_format.search(root)
    if own is not None:
        return map_file(talk, root, own.path, metric, judge_model, found=True)
    _doors(talk, root)
    return None


def _root_and_file(path: Path) -> tuple[Path, Path | None]:
    path = path.resolve()
    if path.is_dir():
        return path, None
    if not path.is_file():
        raise StartError(f"file or folder not found: {path}")
    here = Path.cwd().resolve()
    return (here if path.is_relative_to(here) else project_root(path.parent)), path


def run(path: str | Path = ".", yes: bool = False, metric: str | None = None,
        judge_model: str | None = None) -> int:
    talk = Talk(yes=yes)
    try:
        return _run(talk, Path(path), metric, judge_model)
    except Stop as stop:
        return stop.code


def _run(talk: Talk, path: Path, metric, judge_model) -> int:
    root, file = _root_and_file(path)
    try:
        current = settings.load(root)
    except settings.SettingsError as e:
        raise StartError(str(e)) from None
    if current is not None:
        talk.say(f"{settings.FILE} already says where your judge's results are "
                 f"({current.describe()}).")
        if not talk.confirm("Set it up again?", default=False, with_yes=False,
                            hint="Set it up again? Run judgekeeper setup in a terminal to "
                                 "change it."):
            talk.say("Nothing was changed.")
            return EXIT_OK
        talk.say()
    saved = _source(talk, root, file, metric, judge_model)

    changes = [c for c in (settings_change(root, saved) if saved else None,
                           gitignore_change(root), requirements_change(root)) if c]
    todo = [c for c in changes if c.apply]
    if todo:
        talk.say("Set up judgekeeper in this project?")
        for c in changes:
            talk.say(f"  • {c.text}")
        if not talk.confirm("", default=True, with_yes=True,
                            hint="Run judgekeeper setup --yes to make these changes, or run it "
                                 "in a terminal to answer."):
            talk.say("Nothing was changed.")
            return EXIT_OK if saved else EXIT_USAGE
        for c in todo:
            c.apply()
            talk.say(f"{tick()} {c.done}")
    else:
        for c in changes:
            talk.say(f"  • {c.text}")
    if saved is None:
        return EXIT_USAGE
    talk.say()
    talk.say(NEXT)
    return EXIT_OK


__all__ = ["Change", "gitignore_change", "map_file", "requirements_change", "run"]
