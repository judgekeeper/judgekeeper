"""Reading judge results saved in a project's own format: the guess, the few questions the file
cannot answer, and the [start] table judgekeeper.toml keeps once the person says yes.
`judgekeeper` (front.py) runs it when it finds no eval tool's results but a file that looks
like a judge's (own_format.search), or when it is pointed at such a file.

1. List the file's nested paths (paths only: a value may be an answer's text) and show the
   guess (mapper.py): which part is the input, the answer, the score, and where the pass mark
   and the judge's model come from.
2. Ask whether it is right: at a terminal always, without one only when a part was guessed
   from value types only. After No, at a terminal, the person says which part is wrong and
   chooses it from the file's paths (or types the pass mark).
3. Then only what the file cannot tell: whether each of several answers per item (A and B)
   is its own answer, which judge to check when there are several, the pass mark when the
   scores are not between 0 and 1 and the file does not state one, and whether to leave out
   answers with an error or a score made by a rule.

Nothing is written here. When the file cannot be mapped, the Next: line asks the coding
agent to write a small converter to judgekeeper's table instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from judgekeeper import mapper, own_format, settings, start
from judgekeeper.normalise import NormaliseError, parse_pass_if
from judgekeeper.records import LLM, RecordsError
from judgekeeper.start import EXIT_QUESTION, EXIT_USAGE, StartError, Talk
from judgekeeper.textio import plural, quote_arg

MAX_PATHS = 24
RECORD_DOOR = ("Or save your LLM-as-a-judge's decisions from now on with one judgekeeper.record() "
               f"line where it runs: {own_format.RECORD_URL} shows the line.")
NOT_UTF8 = "is not saved as UTF-8 text"  # textio.not_utf8_message
QUOTE = re.compile(r"line (\d+) of .+ has a quote that never closes")
PASS_IF = '"score>=N"'  # the placeholder of --pass-if in a Next: line; quoted for every shell


def _para(talk: Talk, text: str) -> None:
    getattr(talk, "para", talk.say)(text)  # wrapped on `judgekeeper`'s screens


def cannot(talk: Talk, rel: str, why: str):
    """The file cannot be mapped: what to do instead. Returns the Stop to raise."""
    why = why.rstrip(".")
    quote = QUOTE.match(why)
    if quote:  # the file is read once the quote is closed
        _para(talk, f"{why[:1].upper()}{why[1:]}.")
        return talk.stop(EXIT_USAGE, f"close the quote on line {quote[1]} of "
                                     f"{Path(rel).name}, then run `{talk.command()}`.")
    if NOT_UTF8 in why:  # the file is read once it is saved as UTF-8
        _para(talk, f"{why}.")
        return talk.stop(EXIT_USAGE, f"save {Path(rel).name} as UTF-8, then run "
                                     f"`{talk.command()}`.")
    _para(talk, f"judgekeeper cannot read {rel} by itself: {why}.")
    _para(talk, f"Turn it into a CSV, as the Next: line says. {RECORD_DOOR}")
    return talk.stop(EXIT_USAGE, (
        f"turn {rel} into a CSV with the columns id, input, output, verdict (pass or fail) and "
        "reason, one CSV per LLM-as-a-judge, leaving out errors and scores made by a rule. Then "
        f"run `{csv_command(talk)}`, with PATH the path of your CSV."))


def csv_command(talk: Talk) -> str:
    """`judgekeeper PATH` with the person's flags, PATH standing for the CSV to read: the
    file they gave, when they gave one, is what PATH replaces."""
    given = talk.flags[:1] == (quote_arg(talk.path),) and talk.path != "."
    return " ".join((talk.program, "PATH", *(talk.flags[1:] if given else talk.flags)))


UNSURE_PARTS = {"output": "the answer", "input": "the input", "score": "the score"}


def unsure(talk: Talk, rel: str, g: mapper.Guess):
    """A reading judgekeeper is not sure of, without a terminal: --yes never accepts it.
    Returns the Stop to raise."""
    parts = [UNSURE_PARTS.get(p, p) for p in g.unsure]
    why = g.doubt or f"it guessed {' and '.join(parts)} from their values, not their names"
    _para(talk, f"judgekeeper isn't sure how to read {rel}: {why}.")
    return talk.stop(EXIT_QUESTION, (
        f"run `{talk.command()}` in a terminal to check how judgekeeper reads {rel}, or turn "
        "it into a CSV with the columns id, input, output, verdict (pass or fail) and "
        "reason."))


def how_lines(g: mapper.Guess, judge_model: str | None = None) -> list[str]:
    """How judgekeeper reads the file: the paths of each part, never a value."""
    each = f"each item of {g.each}" if g.each else "each line or row"
    side, judge = (g.sides or [None])[0], (g.judges or [None])[0]
    answer = (" and ".join(mapper.filled(g.output, s) for s in g.sides) if g.sides
              else mapper.filled(g.output))
    score = mapper.filled(g.score, side, judge)
    if g.judges:
        score += f" (LLM-as-a-judge names: {', '.join(g.judges)})"
    if len(g.sides) > 1 and mapper.SIDE in g.score:
        score += f" and the same under {' and '.join(g.sides[1:])}"
    label = "grade:"
    lines = [f"  one answer:      {each}", f"  question:        {mapper.filled(g.input)}",
             f"  answer:          {answer}", f"  {label:<17}{score}"]
    if g.reason:
        lines.append(f"  reason:          {mapper.filled(g.reason, side, judge)}")
    if g.id:
        lines.append(f"  id:              {g.id}")
    if g.model_key:
        lines.append(f"  model:           {mapper.filled(g.model_key, side, judge)} ({g.model})")
    elif judge_model:
        lines.append(f"  model:           {judge_model} (given with --judge-model)")
    else:
        lines.append("  model:           not in the file")
    if g.kind == "score":
        if g.pass_mark_given:
            where = " (given by you)"
        elif g.pass_mark_key:
            where = f" ({g.pass_mark_key} in the file)"
        else:
            where = " (the scores are between 0 and 1)" if g.pass_mark_sure else ""
        mark = g.pass_mark if g.pass_op == ">=" else f"{g.pass_op} {g.pass_mark}"
        lines.append(f"  pass mark:       {mark}{where}")
    return lines


# One part of the guess, corrected by the person: (part, its name, the question).
PARTS = (("each", "what one answer is", "Which list holds the answers, one item each?"),
         ("input", "the input", "Which path holds the input?"),
         ("output", "the answer", "Which path holds the answer?"),
         ("score", "the score", "Which path holds the score?"),
         ("reason", "the reason", "Which path holds the reason?"),
         ("id", "the id", "Which path holds the id?"),
         ("model_key", "the LLM-as-a-judge's model",
          "Which path holds the LLM-as-a-judge's model?"),
         ("pass_mark", "the pass mark", None))
OPTIONAL = ("reason", "id", "model_key")  # a file may have none
SHOWN_EXAMPLES = ("each", "model_key")  # a count of items, a model's name: never answer text


def _correct(talk: Talk, units: list, g: mapper.Guess) -> mapper.Guess | None:
    """After "Is this how judgekeeper should read FILE?" was answered No (at a terminal):
    which part is wrong, then that part, chosen from the file's paths (or typed in, for the
    pass mark). None: none of the parts fit."""
    import dataclasses

    names = [name for _, name, _ in PARTS]
    i = talk.choose("Which part is wrong?", [*names, "none of these fit"], "")
    if i == len(PARTS):
        return None
    role, _, question = PARTS[i]
    if role == "pass_mark":
        answer = talk.ask("Pass when the score is at least",
                          str(g.pass_mark if g.pass_mark is not None else 0.5))
        mark = mapper.number(answer)
        if mark is None:
            talk.say(f"  {answer!r} is not a number: the pass mark stays {g.pass_mark}.")
            return g
        return dataclasses.replace(g, kind="score", pass_mark=mark, pass_mark_sure=True,
                                   pass_mark_given=True, pass_mark_key=None)
    found = mapper.choices(units, g, role)
    side, judge = (g.sides or [None])[0], (g.judges or [None])[0]
    width = min(max((len(mapper.filled(p, side, judge)) for p, _ in found), default=0), 44)
    options = [f"{mapper.filled(p, side, judge) or '(the whole line)':<{width}}"
               + (f"  {example}" if role in SHOWN_EXAMPLES else "")
               for p, example in found] + (["none"] if role in OPTIONAL else [])
    if not options:
        talk.say("  Nothing else in the file fits there.")
        return g
    j = talk.choose(question, [o.rstrip() for o in options], "")
    try:
        return mapper.with_part(units, g, role, found[j][0] if j < len(found) else None)
    except mapper.MapError as e:
        talk.say(f"  That does not work: {e}. The guess stays as it was.")
        return g


def _count(units: list, g: mapper.Guess, judge: str) -> int:
    """How many answers `judge` graded: the values at its path that are not empty."""
    n = 0
    for unit in units:
        for item, _ in mapper._safe_items(unit, g.each):
            for side in g.sides or [None]:
                try:
                    n += not mapper.blank(mapper.get(item, g.score, side, judge))
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
            raise StartError(f"no LLM-as-a-judge named {metric!r}; the names are: "
                             f"{', '.join(repr(j) for j in g.judges)}")
        return metric
    if len(g.judges) == 1:
        return g.judges[0]
    options = [f"{j} ({plural(_count(units, g, j), 'answer')})" for j in g.judges]
    i = talk.choose("Which LLM-as-a-judge do you want to check?",
                    [*options, "All, one at a time"], "", flag="--metric",
                    values=[*g.judges, "all"], what="which LLM-as-a-judge to check")
    return "*" if i == len(g.judges) else g.judges[i]


def _given(g: mapper.Guess, pass_if: str | None) -> mapper.Guess:
    """The guess with --pass-if's pass mark and operator, so the box shows the pass mark that
    is used; the guess itself without one."""
    import dataclasses

    if pass_if is None or g.kind != "score":
        return g
    try:
        rule = parse_pass_if(pass_if)
    except NormaliseError as e:
        raise StartError(str(e)) from None
    mark = int(rule.threshold) if rule.threshold.is_integer() else rule.threshold
    return dataclasses.replace(g, pass_mark=mark, pass_mark_sure=True, pass_mark_given=True,
                               pass_mark_key=None, pass_op=rule.op)


def _pass_mark(talk: Talk, g: mapper.Guess, pass_if: str | None):
    """The pass mark of a score judge: --pass-if's (_given), the guess's when it is sure, else
    asked."""
    if pass_if is not None or g.pass_mark_sure:
        return g.pass_mark
    if start._interactive():
        answer = talk.ask("Pass when the score is at least", str(g.pass_mark))
        value = mapper.number(answer)
        if value is None:
            talk.say(f"  {answer!r} is not a number: the pass mark stays {g.pass_mark}.")
            return g.pass_mark
        return value
    talk.say("Your LLM-as-a-judge's scores are not between 0 and 1, and the file does not say "
             "which score passes.")
    raise talk.stop(EXIT_QUESTION, f"decide which score counts as a pass, then run "
                                   f"`{talk.command('--pass-if', PASS_IF)}`.")


def map_file(talk: Talk, root: Path, path: Path, metric: str | None,
             judge_model: str | None, pass_if: str | None,
             found: bool) -> settings.StartSettings:
    """The [start] table for an own-format results file, after the few questions. Raises the
    Stop of `cannot` when the file cannot be mapped or the person says none of it fits."""
    from judgekeeper.readers.mapped import read_mapped

    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    try:
        units = [u for _, u in mapper.load_numbered(path)]
        g = mapper.guess(units)
    except mapper.MapError as e:
        raise cannot(talk, rel, str(e)) from None
    lines = f"{len(units)} {'line' if len(units) == 1 else 'lines'}"
    talk.say(f"{rel} looks like your LLM-as-a-judge's results in a format of its own ({lines})."
             if found else f"{rel} ({lines}):")
    listed = [p for p, _ in mapper.listing(units[0], g.judges)]
    talk.say("What one line holds:" if len(units) > 1 else "What it holds:")
    for p in listed[:MAX_PATHS]:
        talk.say(f"  {p}")
    if len(listed) > MAX_PATHS:
        talk.say(f"  and {len(listed) - MAX_PATHS} more")
    talk.say()
    while True:
        g = _given(g, pass_if)
        talk.say("How judgekeeper reads it:")
        for line in how_lines(g, judge_model):
            talk.say(line)
        talk.say()
        if g.doubt:
            _para(talk, f"Check this: {g.doubt}.")
            talk.say()
        # At a terminal the person checks the guess; without one, an unsure guess stops and
        # --yes never accepts it.
        if (g.unsure or g.doubt) and not start._interactive():
            raise unsure(talk, rel, g)
        if not start._interactive() or talk.confirm(
                f'Is this how judgekeeper should read {rel} (the lines under "How judgekeeper '
                'reads it")?', default=True, with_yes=True, hint=""):
            break
        g = _correct(talk, units, g)
        if g is None:
            raise cannot(talk, rel, "none of the parts of the guess fit")
        talk.say()

    sides = list(g.sides)
    if len(sides) > 1 and not talk.confirm(
            f"Each item has {len(sides)} answers ({' and '.join(sides)}). Count each as its "
            "own answer?", default=True, with_yes=True, hint=""):
        sides = [sides[talk.choose("Which one do you want to check?", sides, "")]]
    judge = _choose_judge(talk, units, g, metric)
    mark = _pass_mark(talk, g, pass_if) if g.kind == "score" else None
    m = {**g.to_map(), "sides": sides}
    chosen = g.judges if judge == "*" else [judge] if judge else []
    left = mapper.left_out(units, mapper.Guess(**{**g.__dict__, "sides": sides}), chosen) \
        if chosen or not g.judges else 0
    if left and talk.confirm(
            f"{plural(left, 'answer has', 'answers have')} an error or a score made by a rule "
            "(a reason starting "
            '"Rule"), not by your LLM-as-a-judge. Leave them out?', default=True, with_yes=True,
            hint=""):
        m["leave_out"] = True
    op = g.pass_op if mark is not None and g.pass_op != ">=" else None
    saved = settings.StartSettings(source="map", file=rel, judge=judge, pass_mark=mark,
                                   pass_op=op, model=judge_model, map=m)
    try:
        records = [r for _, recs in read_mapped(path, {**m, "judge": judge, "pass_mark": mark,
                                                        "pass_op": op, "model": judge_model})
                   for r in recs if r.annotator_kind == LLM]
    except RecordsError:
        records = []
    if not records:
        raise cannot(talk, rel, "no answer could be read with this map")
    return saved


__all__ = ["cannot", "how_lines", "map_file", "unsure"]
