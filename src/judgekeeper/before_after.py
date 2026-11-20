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

Exit 1 only on "made it worse" (front.py): this is what a pipeline fails on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from judgekeeper import no_grades, start
from judgekeeper.records import RecordsError
from judgekeeper.start import StartError, Stop
from judgekeeper.textio import loads, make_private, plural, write_replacing

FILE = "last-graded.json"  # in .judgekeeper/: the results read last and the ones before
EXIT_WORSE = 1

COMPARED = "On the {questions} in both results: fixed {fixed}, broke {broke}, same {same}."
COUNTED = "Counted from the grades in your results, not from your marks."
LEFT_OUT = {1: "{n} question is in only one of the two results and is left out.",
            2: "{n} questions are in only one of the two results and are left out."}
NEXT_WORSE = "Next: fix what broke or undo your change, then run your eval again."
NO_MATCH = ("No question is in both results, so there is nothing to compare. Give each "
            "question an id that stays the same from run to run.")
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

    @property
    def same(self) -> int:
        return self.n - self.fixed - self.broke

    @property
    def worse(self) -> bool:
        return self.kind == "worse"


def grades_of(found: start.Found) -> dict[str, list[str]]:
    """The newest results' grades, {question key: [Pass or Fail of each of its answers]}: not
    the older results the pool may hold beside them."""
    newest = found.used[0] if found.used else None
    return _grades([a for a in found.pool.answers if a.source == newest])


def _grades(answers) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in answers:
        if a.verdict in ("pass", "fail"):
            out.setdefault(_key(a), []).append(a.verdict)
    return {k: sorted(v) for k, v in out.items()}


def _key(a) -> str:
    """A question: its test-case id when the file has its own (a table's id column), so a new
    prompt written into each question is still the same case; else its text. Hashed."""
    if a.case is None:
        return no_grades.question_key(a.input)
    from judgekeeper.table import ID_LENGTH, canonical_json

    data = canonical_json(["case", a.case]).encode("utf-8", errors="surrogatepass")
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


def compare(before: dict[str, list[str]], now: dict[str, list[str]]) -> Comparison:
    both = before.keys() & now.keys()
    fixed = sum(no_grades._fixed(before[k], now[k]) for k in both)
    broke = sum(no_grades._broke(before[k], now[k]) for k in both)
    return Comparison(n=len(both), fixed=fixed, broke=broke, only=len(before.keys() ^ now.keys()),
                      kind=no_grades.change_kind(fixed, broke, len(both), test=1))


def lines(c: Comparison) -> list[list[str]]:
    """What is said, in paragraphs: the counts and where they come from, then the result, then
    (when it is worse) the Next: line. With no question in both, only that, and no result."""
    if not c.n:
        return [[NO_MATCH]]
    left = [LEFT_OUT[min(c.only, 2)].format(n=c.only)] if c.only else []
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
    ["pass" or "fail", ...]}}."""
    if x is None:
        return None
    ok = isinstance(x, dict) and set(x) == {"questions"} and isinstance(x["questions"], dict) \
        and all(isinstance(k, str) and isinstance(v, list) and v
                and all(g in ("pass", "fail") for g in v) for k, v in x["questions"].items())
    return {"questions": {k: list(v) for k, v in x["questions"].items()}} if ok else False


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
    return {"before": before["questions"] if before else None, "now": now["questions"],
            "setup": d["setup"]}


def write(ws, before: dict | None, now: dict, setup: str) -> None:
    """The results read now and the ones read before them. Never written through a link."""
    path = _path(ws)
    if path.is_symlink() or ws.dir.is_symlink():
        return
    d = {"before": {"questions": before} if before is not None else None,
         "now": {"questions": now}, "setup": setup}
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


def look(talk, ws, found: start.Found, given: str | None = None,
         other_judge: bool = False) -> Look | None:
    """The comparison of the newest results with the last ones read here, or with the file
    `given` (--before). A file that can't be read is a usage error (StartError). None when
    the results hold no grade to compare. `other_judge`: the marks here are for another
    LLM-as-a-judge, whose grades say nothing of a change to the AI: the last ones read are
    not kept, whatever the person answers about starting over."""
    now = grades_of(found)
    if not now:
        return None
    setup = setup_of(found)
    state = None if other_judge else read(ws)
    if state is not None and state["setup"] != setup:  # another setup: its grades start again
        state = None
    # the same results read again keep the baseline they had; new ones have the last read
    last = (state["before"] if state["now"] == now else state["now"]) if state else None
    baseline = file_grades(talk, found, given) if given is not None else last
    return Look(compare(baseline, now) if baseline is not None else None, last, now, setup,
                state is not None)


def file_grades(talk, found: start.Found, name: str) -> dict[str, list[str]]:
    """The grades of the results file (or MLflow store) `name`, read as these results were: the
    same eval tool and judge, the same label map and pass mark."""
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
    return _grades([a for a in other.pool.answers if a.source == other.used[0]])
