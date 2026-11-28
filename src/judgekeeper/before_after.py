"""Did your change help? Two graded results, compared question by question.

Each question is its test-case id when the file has its own (start._names_cases), else its
text (no_grades.question_key); its grades are the Pass or Fail of every answer to it in the newest
results. A question is fixed when it failed before and passes now,
and broke when it passed before and fails now (no_grades._fixed and _broke, as they count marks
for answers with no grade). The verdict is no_grades.change_kind at one test: each run is
compared with one baseline, so nothing is corrected for several tests.

The baseline is the results judgekeeper read last in the project (`last-graded.json` in
.judgekeeper/: question hashes and grades, never a question or an answer), or `--before FILE`.
The same results read again are no new baseline, so a run says the same each time. Grades from
another setup of the LLM-as-a-judge (another model, rule or pass mark) say nothing about a
change to the AI: the file keeps a hash of the setup, and a new one starts it again.

Exit 1 on "made it worse" (front.py): this is what a pipeline fails on. Exit 3 when nothing
could be compared (no question in both, or `--before` graded by another setup): a gate never
passes on nothing. With `--before` or in CI the comparison alone sets the exit code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import no_grades, start
from judgekeeper.records import RecordsError
from judgekeeper.start import StartError, Stop
from judgekeeper.textio import loads, make_private, path_arg, plural, write_replacing

FILE = "last-graded.json"  # in .judgekeeper/: the results read last and the ones before
# its setup after `check` took on another LLM-as-a-judge's grades (restart): the next results
# start again, as for another setup, whatever their own setup's hash
RESTART = "restart"
EXIT_WORSE = 1

COMPARED = "On the {questions} in both results: fixed {fixed}, broke {broke}, same {same}."
COUNTED = "Counted from the grades in your results, not from your marks."
LEFT_OUT = {1: "{n} question is in only one of the two results and is left out.",
            2: "{n} questions are in only one of the two results and are left out."}
NO_GRADE = {1: "{n} question has no Pass or Fail grade in one of the results and is left out.",
            2: "{n} questions have no Pass or Fail grade in one of the results and are left out."}
NEXT_WORSE = "Next: fix what broke or undo your change, then run your eval again."
NO_MATCH = "No question is in both results, so there is nothing to compare."
NO_MATCH_NEXT = ("Next: give each question an id that stays the same from run to run (such as "
                 "an `id` column), then run your eval again.")
NO_MATCH_IDS_NEXT = ("Next: check that you compare results of the same eval: the two share no "
                     "question id.")
NO_IDS_ONE_SIDE = ("Only one of the two results names its questions by an id, so judgekeeper "
                   "can't tell which questions are the same, and compares nothing.")
NOTHING_GRADED = ("No question has a Pass or Fail grade in both results, so there is nothing to "
                  "compare.")
NOTHING_GRADED_NEXT = ("Next: check why your LLM-as-a-judge gave no Pass or Fail grade, then run "
                       "your eval again.")
RESTARTED = ("Your LLM-as-a-judge setup changed since the last results, so there is nothing to "
             "compare yet. This run is the new starting point.")
OTHER_SETUP = ("The two results were graded by different LLM-as-a-judge setups (the model, rule "
               "or pass mark changed), so judgekeeper does not compare them.")
OTHER_SETUP_NEXT = "Next: compare results graded by the same LLM-as-a-judge setup."
NUMBERED_IDS = ("The questions changed and their ids are plain numbers, so judgekeeper can't tell "
                "they are the same questions.")
NUMBERED_IDS_NEXT = ("run `{command} --before FILE`, with your earlier results as FILE, to "
                     "compare them, or put {file} in a folder of its own to mark it.")
UNREAD = ("judgekeeper can't tell which of the LLM-as-a-judge's decisions in {name} mean Pass "
          "and which mean Fail: {values}.")
LONG_TEXT = "some hold long text"
CANT_READ = ("{name} can't be read the way your results are, so there is nothing to compare "
             "with.")
CANT_READ_NEXT = "give the results file from before your change to --before, then run `{command}`."


@dataclass(frozen=True)
class Comparison:
    n: int  # questions graded in both
    fixed: int
    broke: int
    only: int  # questions in only one of the two, left out
    kind: str  # no_grades.CHANGE's key
    ungraded: int = 0  # in both, with no Pass or Fail grade in one of them: left out
    ids: bool = False  # both name each question by its own id
    one_side_ids: bool = False  # only one of the two does: their questions can't be matched

    @property
    def same(self) -> int:
        return self.n - self.fixed - self.broke

    @property
    def worse(self) -> bool:
        return self.kind == "worse"

    @property
    def exit_code(self) -> int | None:
        """1 when it made it worse, 3 when nothing was compared, else None (the run's own)."""
        return EXIT_WORSE if self.worse else None if self.n else start.EXIT_QUESTION


def grades_of(found: start.Found, numbers: bool = False) -> dict:
    """The newest results' grades as one side of last-graded.json: {"questions": {question
    key: [Pass or Fail of each of its answers]}, "ids": whether each is named by its own id}.
    Not the older results the pool may hold beside them. A question with no Pass or Fail
    grade is there with none. An id that is a plain number names a question only with
    `numbers` (--before: the person chose both files); else its text does. An answer with no
    question text has only its id, so its id is kept."""
    from judgekeeper.project import plain_number

    newest = found.used[0] if found.used else None
    answers = [(a.case, a.input, a.verdict) for a in found.pool.answers if a.source == newest]
    answers += [(case, found.pool.left[i][1].input, None)  # no Pass or Fail grade
                for i, (source, case) in found.pool.left_from.items() if source == newest]
    answers = [(c if c is not None and (numbers or not plain_number(c) or _blank(q)) else None,
                q, v) for c, q, v in answers]
    return {"questions": _grades(answers),
            "ids": bool(answers) and all(case is not None for case, _, _ in answers)}


def _blank(question) -> bool:
    """Whether a question has no text to name it by."""
    return question is None or (isinstance(question, str | list | dict) and not (
        question.strip() if isinstance(question, str) else question))


def _grades(answers) -> dict[str, list[str]]:
    """{question key: its grades} of (Answer.case, question, verdict) triples."""
    out: dict[str, list[str]] = {}
    for case, question, verdict in answers:
        grades = out.setdefault(_key(case, question), [])
        if verdict in ("pass", "fail"):
            grades.append(verdict)
    return {k: sorted(v) for k, v in out.items()}


def _key(case: str | None, question) -> str:
    """A question: its test-case id when the file has its own (a table's id column), so a new
    prompt written into each question is still the same case; else its text. Hashed."""
    if case is None:
        return no_grades.question_key(question)
    from judgekeeper.table import ID_LENGTH, canonical_json

    data = canonical_json(["case", case]).encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(data).hexdigest()[:ID_LENGTH]


def setup_of(found: start.Found) -> str:
    """A hash of what decides the grades: the LLM-as-a-judge's setup as judge.json keeps it
    (judge_setup.of: model, rule, prompt, temperature, pass mark...), the metric and the label
    map. Not the eval tool's version, which grades nothing. Never its text."""
    from judgekeeper import judge_setup
    from judgekeeper.redact import scrub
    from judgekeeper.table import canonical_json

    setup = {k: v for k, v in judge_setup.of(found).items()
             if k not in ("tool_version", "version_from")}
    data = canonical_json([setup, scrub(found.metric), found.pool.label_map])
    return hashlib.sha256(data.encode("utf-8", errors="surrogatepass")).hexdigest()


def compare(before: dict, now: dict) -> Comparison:
    """Two sides (grades_of): a question in both is compared when each has a grade for it."""
    b, n = before["questions"], now["questions"]
    both = b.keys() & n.keys()
    graded = {k for k in both if b[k] and n[k]}
    fixed = sum(no_grades._fixed(b[k], n[k]) for k in graded)
    broke = sum(no_grades._broke(b[k], n[k]) for k in graded)
    return Comparison(n=len(graded), fixed=fixed, broke=broke, only=len(b.keys() ^ n.keys()),
                      kind=no_grades.change_kind(fixed, broke, len(graded), test=1),
                      ungraded=len(both - graded), ids=before["ids"] and now["ids"],
                      one_side_ids=before["ids"] != now["ids"])


def lines(c: Comparison) -> list[list[str]]:
    """What is said, in paragraphs: the counts and where they come from, then the result, then
    (when it is worse) the Next: line. With nothing compared, why and its Next: line."""
    if not c.n:
        if c.ungraded:
            return [[NOTHING_GRADED], [NOTHING_GRADED_NEXT]]
        return [[NO_MATCH], [NO_MATCH_IDS_NEXT if c.ids else NO_MATCH_NEXT]]
    left = [LEFT_OUT[min(c.only, 2)].format(n=c.only)] if c.only else []
    left += [NO_GRADE[min(c.ungraded, 2)].format(n=c.ungraded)] if c.ungraded else []
    counted = [COMPARED.format(questions=plural(c.n, "question"), fixed=c.fixed, broke=c.broke,
                               same=c.same), COUNTED, *left]
    out = [counted, [no_grades.CHANGE[c.kind]]]
    if c.worse:
        out.append([NEXT_WORSE])
    return out


# The baseline: what the last two results read said ----------------------------------------------

def _path(ws) -> Path:
    return ws.dir / FILE


def _sum(d: dict) -> str:
    from judgekeeper.fix import _sum as checksum

    return checksum(d)


def _side(x) -> dict | None:
    """One side of the file as it is when it is as judgekeeper writes it: {"questions": {key:
    ["pass" or "fail", ...]}, "ids": bool} (a file with no "ids" names none)."""
    if x is None:
        return None
    ok = isinstance(x, dict) and set(x) in ({"questions"}, {"questions", "ids"}) \
        and isinstance(x.get("ids", False), bool) and isinstance(x["questions"], dict) \
        and all(isinstance(k, str) and isinstance(v, list)
                and all(g in ("pass", "fail") for g in v) for k, v in x["questions"].items())
    return {"questions": {k: list(v) for k, v in x["questions"].items()},
            "ids": x.get("ids", False)} if ok else False


def read(ws) -> dict | None:
    """last-graded.json as {"before": grades or None, "now": grades, "setup": setup_of's hash};
    None when there is none,
    it is a link, can't be read, is not as judgekeeper writes it or was changed by hand:
    nothing is compared, no error."""
    path = _path(ws)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        d = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or set(d) != {"before", "now", "setup", "sha256"} \
            or d["sha256"] != _sum(d) or not isinstance(d["setup"], str):
        return None
    before, now = _side(d["before"]), _side(d["now"])
    if before is False or not now:
        return None
    return {"before": before, "now": now, "setup": d["setup"]}


def restart(ws) -> None:
    """After `check` took on another LLM-as-a-judge's grades (check._adopt): the grades read
    next changed because the LLM-as-a-judge did, so they start again (RESTARTED). The grades
    read last stay, to tell --before's file of them (look)."""
    raw = read(ws)
    if raw is not None:
        write(ws, raw["before"], raw["now"], RESTART)


def write(ws, before: dict | None, now: dict, setup: str) -> None:
    """The results read now and the ones read before them. Never written through a link."""
    path = _path(ws)
    if path.is_symlink() or ws.dir.is_symlink():
        return
    d = {"before": before, "now": now, "setup": setup}
    make_private(path.parent)
    write_replacing(path, json.dumps({**d, "sha256": _sum(d)}, indent=2, sort_keys=True) + "\n")


@dataclass
class Look:
    """What a run learned before it said anything: the comparison (None when there is none),
    and what the file holds after it, written once the run is done."""

    comparison: Comparison | None
    before: dict | None  # the results before the newest, as last-graded.json will keep them
    now: dict
    setup: str  # setup_of's hash, kept with them
    had: bool  # last-graded.json was there and could be read
    restarted: bool = False  # it was, for another setup of the LLM-as-a-judge: RESTARTED
    other_setup: bool = False  # --before's file was graded by another setup: OTHER_SETUP

    def paragraphs(self, comparison: Comparison | None,
                   gate: bool = True) -> tuple[list[list[str]], int | None]:
        """What is said where the comparison goes, and the exit code it sets (None: the run's
        own). Outside a gate (`gate`: --before or CI), results that can't be matched because
        only one of them names its questions by id (marked-answers.csv graded again without
        it, say) are one line: the run's own Next: line and exit code stand."""
        if self.other_setup:
            return [[OTHER_SETUP], [OTHER_SETUP_NEXT]], start.EXIT_QUESTION
        c = comparison
        if c is not None and not gate and not c.n and not c.ungraded and c.one_side_ids:
            return [[NO_IDS_ONE_SIDE]], None
        if comparison is not None:
            return lines(comparison), comparison.exit_code
        return ([[RESTARTED]] if self.restarted else []), None


def look(talk, ws, found: start.Found, given: str | None = None,
         other_judge: bool = False) -> Look | None:
    """The comparison of the newest results with the last ones read here, or with the file
    `given` (--before). A file that can't be read is a usage error (StartError). None when
    the results hold no grade to compare. `other_judge`: the marks here are for another
    LLM-as-a-judge, whose grades say nothing of a change to the AI: the last ones read are
    not kept, whatever the person answers about starting over."""
    now = grades_of(found)
    if not any(now["questions"].values()):
        return None
    setup = setup_of(found)
    raw = read(ws)
    restarted = given is None and raw is not None and raw["setup"] != setup
    state = None if other_judge or restarted else raw  # another setup: its grades start again
    # the same results read again keep the baseline they had; new ones have the last read
    last = (state["before"] if state["now"] == now else state["now"]) if state else None
    baseline = last  # ids that are plain numbers say nothing here: the text does
    if given is not None:
        other = file_found(talk, found, given)
        if _judged(found) and _judged(other) and setup_of(other) != setup:
            return Look(None, last, now, setup, state is not None, other_setup=True)
        if raw is not None and raw["setup"] == RESTART and grades_of(other) == raw["now"]:
            # the grades a check replaced with another LLM-as-a-judge's: not compared
            return Look(None, None, now, setup, True, restarted=True)
        return Look(compare(grades_of(other, numbers=True), grades_of(found, numbers=True)),
                    last, now, setup, state is not None)
    return Look(compare(baseline, now) if baseline is not None else None, last, now, setup,
                state is not None, restarted=restarted)


def _judged(found: start.Found) -> bool:
    """Whether the results say who graded them: a model, a rule or a prompt."""
    from judgekeeper import judge_setup

    s = judge_setup.of(found)
    return bool(s["models"] or s["rule_hash"] or s["prompt_hash"])


def file_found(talk, found: start.Found, name: str) -> start.Found:
    """The results file (or MLflow store) `name`, read as these results were: the same eval
    tool and judge, the same label map and pass mark. Grades it can't tell as Pass or Fail
    stop the run, as they do in these results."""
    from judgekeeper.check import no_such

    path = Path(name)
    if not path.exists():
        raise StartError(no_such(name), "check the path, then run `{command}`.")
    o = talk.options
    try:
        other = start.find_judge(path, tool=o["tool"], metric=found.metric,
                                 pass_if=o["pass_if"], label_map=o["label_map"] or found.label_map)
    except RecordsError as e:
        raise start.usage_error(e) from None
    except Stop:
        raise StartError(CANT_READ.format(name=path.name), CANT_READ_NEXT) from None
    if other.pool.unmapped:
        raise _unread(talk, path, other)
    return other


def _unread(talk, path: Path, other: start.Found) -> Stop:
    """The --before file's decisions hold values that are not Pass or Fail: named as the
    main results' are (never long text: it may be an answer), with the --label-map to give."""
    from judgekeeper.front import LABEL_MAP, _shown

    values = list(dict.fromkeys(other.pool.unmapped))
    words = [str(v) for v in values]
    shown = _shown(words) if all(start.verdict_like(v) for v in values) else LONG_TEXT
    talk.para(UNREAD.format(name=path.name, values=shown))
    again = talk.command(*talk.labels_flags(), "--before", path_arg(str(path)), "--label-map",
                         LABEL_MAP)
    return talk.stop(start.EXIT_QUESTION, (
        "decide which of the values above mean Pass, which mean Fail and which mean no "
        f"decision (error), then run `{again}`."))
