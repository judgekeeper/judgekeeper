"""`judgekeeper fix`: where the LLM-as-a-judge goes wrong, and a fair test of a new rule.

It needs a result. `judgekeeper fix` shows the patterns, writes mistakes.md and
marked-answers.csv (every marked answer, question and answer only, shuffled) and says where
the rule lives. The person changes the rule in their eval tool, grades marked-answers.csv
again and saves the results; `judgekeeper fix <new results file>` reads them with the reader
of step 1 and tests the new rule on the hidden marks. judgekeeper runs nothing itself.

The hidden marks: half of each group of marks, at least 5 marked Pass and 5 Fail, picked
when the first result appears (prepare_split) and kept in fix/split.json; marks made later are
split the same way. Everything shown before the test uses only the other marks, so a new rule
is never written from a hidden answer, and nothing about a hidden mark is printed or written
elsewhere (marked-answers.csv holds every marked answer, so it can't tell them apart). A set
is retired once a rule tested on it is adopted, after MAX_RULES rules, or with `fix --new`.

mistakes.md is ready to hand to a coding agent: each answer's text is fenced as data under a
warning never to follow instructions inside it. judgekeeper never edits the person's files.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import secrets
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import __version__, batches, find, marks, reasons, start_fix_rule, targets
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.links import link, said
from judgekeeper.records import RecordsError
from judgekeeper.redact import one_line, scrub
from judgekeeper.start_label import Workspace, every_marked, next_marks, shown_folder
from judgekeeper.table import guard_cell
from judgekeeper.textio import (
    ANYWHERE,
    held_lines,
    jsonl_lines,
    kept_at,
    kept_path,
    line_path,
    loads,
    make_private,
    old_hook,
    plainly,
    plural,
    program,
    program_in,
    quote_arg,
    read_cached,
    runnable,
    said_next,
    wrap,
    write_replacing,
)

EXIT_OK, EXIT_WORSE, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 1, 2, 3
FOLDER = "fix"
SPLIT, MISTAKES, ANSWERS = "split.json", "mistakes.md", "marked-answers.csv"
ANSWER_COLUMNS = ("question", "answer")
SUGGESTIONS = reasons.SUGGESTIONS
HIDDEN_TENTHS = 5  # of each group of marks hidden, rounded up
MIN_EACH = 5  # hidden marks marked Pass, and Fail, at least
MAX_RULES = 3  # rules tested on one set of hidden marks
FRESH = 10  # new marks that make a new set of hidden marks
CLEAR = 40  # new marks that most often give a new set a clear answer
CLEAR_LINE = (f"Mark about {CLEAR} more answers for a clear answer (at least {FRESH}). With fewer "
              f"than about {CLEAR}, the result will often be \"can't tell yet\".")
ONLY_LEFT = "Only {n} left to mark. Mark them, or add more answers to your results."
NONE_LEFT = "No answers are left to mark. Add more answers to your results."
RULE_SHOWN = 58  # characters of the rule shown, "…" included
STEP = "Step 4 of 5: Fix"
STEP_TEST = "Step 4 of 5: Fix (testing your new rule)"
RESULT = {
    "better": ("Result: your new rule is better. A difference this large is unlikely to be a "
               "coincidence."),
    "safe": ("Result: safe to try. Not clearly better yet, but unlikely to be more than 10 "
             "percentage points worse."),
    "leans better": ("Result: can't tell yet. That leans toward better, but a split this small "
                     "could easily be a coincidence."),
    "same": "Result: can't tell yet. The two rules look about the same here.",
    "leans worse": "Result: can't tell yet. That leans toward worse.",
    "worse": "Result: your new rule looks worse.",  # only past the sign test
}
LEANS = ("leans better", "same", "leans worse")


def shown_kind(kind: str, fixed: int, broke: int) -> str:
    """The result as the counts on screen show it: a lean, or none, from the plain counts
    `fixed` and `broke` the person sees. The weighted counts may lean the other way; they
    decide only better, safe to try and worse."""
    if kind not in LEANS:
        return kind
    return "leans better" if fixed > broke else "same" if fixed == broke else "leans worse"


CANT_TELL = ("Only {n} of your LLM-as-a-judge's mistakes {are} kept aside. 'Better' needs about "
             "{better} fixed and none broken. Mark more answers to get a clearer test.")
NEW_RESULTS = "<new results file>"
CANT_SETTLE = ("these marks can't settle it. Keep your old rule, or try another change and run "
               "`{command}` again.")  # can't tell yet, with every answer marked
MISSING = ("Result: can't tell. {k} of the {n} answers kept aside {have} no grade in your new "
           "results{why}. A rule is tested only on all of them: a rule that leaves the hard ones "
           "ungraded would look better than it is.")
MOSTLY_BLANK = ("Result: can't tell. {k} of the {n} answers kept aside {have} no decision from "
                "your new rule{why}: more than half, too many to test it on.")
# Every answer kept aside is there, none with a Pass or Fail: the grader did not grade
NO_GRADES = ("Your new results have no grades. None of the {n} answers kept aside got a Pass "
             "or Fail from your new rule.")
NO_GRADES_INSPECT = ("Inspect may have graded with your task's own model, not your grader model. "
                     "Check the `-S` options you gave `inspect score`. Give again each option "
                     "your scorer was set up with, its model too.")
NO_GRADES_OTHER = "Check that your LLM-as-a-judge ran with its model and your new rule."
COUNTED = ("{k} of the {n} answers kept aside got no grade from your new rule. judgekeeper "
           "counted {them}.")
REGRADE_SAME = "grade every answer in {answers} again with your new rule, then {run}."
REWROTE = ("judgekeeper wrote {answers} again. It now also holds the kept-aside answers "
           "missing from your new results.")
NOT_ENOUGH = "You have not marked enough answers yet to fix your LLM-as-a-judge."
# The same rule and model as a file tested before, with other grades: the way to test them
TEST_AS_NEW = "To test these grades as a new LLM-as-a-judge, change its rule and grade again."
SAME_GRADES = ("These grades are the same as when you marked. Use the results from after your "
               "change.")
EARLIER = ("{k} of the {n} answers kept aside {have} no grade from your LLM-as-a-judge as it "
           "is now, only from one before it, so judgekeeper leaves {them} out.")
TOOK = ("Your LLM-as-a-judge had not graded {k} kept-aside {answers} before. judgekeeper now "
        "uses {these} new {grades} for {them}.")


def took_line(k: int) -> str:
    """TOOK for `k` answers."""
    one = k == 1
    return TOOK.format(k=k, answers="answer" if one else "answers", them="it" if one else "them",
                       grades="grade" if one else "grades", these="this" if one else "these")


NEXT_EARLIER = ("grade the answers in {answers} again with your LLM-as-a-judge as it is now, "
                "{run} so judgekeeper has its grades, then test your "
                "new rule.")
UNCHANGED = ("Your new rule gives each of the {n} answers kept aside the grade the old one "
             "gave, so it changes nothing there to test.")
# The page on each eval tool: a pip install has no docs/ folder
EVAL_TOOLS = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/eval-tools.md"
# How to grade the same answers again, per eval tool (an own file or record(): OWN)
REGRADE = {
    "promptfoo": (f"promptfoo: grade {ANSWERS} again with your new rule, with the `echo` "
                  "provider and no new answers. " + EVAL_TOOLS + " shows the whole config."),
    "inspect": ("Inspect AI: grade your log again with the new rule, no new answers needed. "
                "`--scorer` takes the scorer's name (`model_graded_qa` for Inspect's own). "
                "Give the options you set before again with `-S`, the grader's model too. "
                "`-S instructions=` takes a "
                "rule with no comma and no colon followed by a space. Otherwise, grade it "
                "with Inspect's score() in Python, as " + EVAL_TOOLS + " shows. "
                "`--action overwrite` replaces the old grades in the new log, so your "
                "scorer's name holds the new ones, and `--output-file` writes a new log next "
                "to yours, so yours stays as it was and `judgekeeper check` finds the new "
                "one."),
    "mlflow": ("MLflow: `mlflow.genai.evaluate()` on the existing traces with the new scorer, "
               "under the same name."),
    "deepeval": (f"DeepEval: make one test case for each row of {ANSWERS} (`question` is the "
                 "input, and `answer` is the actual_output). Add any other field your metric reads, "
                 "such as expected_output. Run your metric with its new rule and the same name "
                 "through `deepeval test run`. It saves a new test_run_<date>.json in your "
                 "results folder."),
}
OWN = f"Grade {ANSWERS} with your own code."
# promptfoo: a ready config that grades the marked answers again (written as text: no YAML
# parser; every value is a JSON string, which is also a YAML string)
REGRADE_FILE, NEW_JSON = "regrade.yaml", "new.json"
TESTS_FILE = "marked-answers.yaml"  # regrade.yaml's tests: the answers exactly, no guard
REGRADE_STEPS = ("1. Change the {what} in {file} (line {line}).\n"
                 "2. Run: `npx promptfoo eval -c {config} -o {new}`{calls}\n"
                 "3. Then{where}: `{command} {after}`")
FOLLOW_STEPS = "follow the three steps above."
NOT_A_COLUMN = "Your rule uses {{{{{name}}}}}, but {answers} has only question and answer."
NEW_RECORDS = f"{find.RECORDS_DIR.as_posix()}/<new file>"
RECORD_AGAIN = (f"Grade {ANSWERS} with your own code, call `judgekeeper.record()` again on the "
                "new grades, then {run}.")
SAME_SHAPE = (f"Grade {ANSWERS} with your own code, and save the new grades in the same shape "
              "as {file}.")
TABLE = "Save the new grades in a file like your first one, with its column names ({names})."
TABLE_COLUMNS = ("input", "output", "verdict")
GRADE_COLUMNS = ("verdict", "judge_verdict", "judge", "score")  # the grade, first found

# The patterns: only when strong, from at least FEW mistakes
FEW = 3
NEAR = 0.1  # how close to the pass mark is close
LONG_SIDE = 4  # mistakes on one side the length pattern needs
LONG = 1.5  # how much longer is long
WORDS_SHOWN = 5
WORD_IN = 3  # mistakes a word must be in
WORD_SHARE = 10  # and at least 1 in this many of them
STRONG = 1.0  # smoothed log-odds a word needs, against the agreed answers
STOPWORDS = frozenset((
    "about", "above", "after", "again", "against", "also", "among", "another", "anything",
    "because", "been", "before", "being", "below", "between", "both", "cannot", "could",
    "does", "doing", "done", "down", "during", "each", "either", "else", "even", "ever",
    "every", "from", "further", "have", "having", "here", "hers", "herself", "himself",
    "however", "into", "itself", "just", "like", "made", "make", "many", "might", "more",
    "most", "much", "must", "myself", "need", "never", "once", "only", "other", "ours",
    "ourselves", "over", "same", "should", "since", "some", "something", "such", "than",
    "that", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "though", "through", "under", "until", "upon", "very", "want", "well", "were",
    "what", "when", "where", "whether", "which", "while", "will", "with", "within", "without",
    "would", "your", "yours", "yourself", "yourselves",
    # words about an eval's format, not its content ("The answer is 72.")
    "answer", "answers", "question", "questions", "response", "responses"))


# The marks ----------------------------------------------------------------------------------

def _judge_said(path: Path) -> dict:
    """The judge's reason and score on each answer in pool-judge.jsonl."""
    _, records = read_run(path)
    return {"reasons": {i: scrub(r.get("rationale") or "") for i, r in records.items()},
            "scores": {i: r.get("raw_score") for i, r in records.items()}}


def _pool_rows(path: Path) -> dict:
    """{id: row} from pool.jsonl."""
    rows = {}
    for line in jsonl_lines(path.read_text(encoding="utf-8")):
        if line.strip():
            row = loads(line)
            rows[row["id"]] = row
    return rows


class Marks:
    """The person's marks (person), the judge's grades on them (judge), and per answer its
    text (rows), the judge's reason and score, and the person's note and reasons (why)."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.data = ws.cached_data()  # read only
        read = marks.read(ws.marks)
        self.person = read.counted()
        self.notes = {i: str(x["note"]) for i, x in read.last.items()
                      if i in self.person and x.get("note")}
        self.why = {i: reasons.of_line(x) for i, x in read.last.items() if i in self.person}
        self.own = {c["id"]: c for c in reasons.own_chips(ws)}
        self.parts = reasons.rule_parts(self.data)  # the rule now's parts, for its buttons
        groups = {q["id"]: q["group"] for q in self.data.get("queue") or []}
        self.batch = batches.of(self.data)
        counted = batches.counted_labels(self.data, self.person)  # a batch too new is left out
        self.judge = {i: groups[i] for i in self.person if i in groups}
        self.earlier = set(self.data.get("earlier_grades") or [])  # an earlier judge's grade
        self.person = {i: m for i, m in self.person.items() if i in self.judge and i in counted}
        self.order = sorted(self.person, key=lambda i: str(read.last[i].get("at") or ""))
        said = read_cached(ws.pool_judge, _judge_said)
        self.reasons = dict(said["reasons"])  # judge_now changes these two
        self.scores = dict(said["scores"])
        self.rows = read_cached(ws.pool, _pool_rows)  # read only
        self.worse_from: str | None = None  # judge_now: the results the new judge's grades are in

    def enough(self) -> bool:
        values = list(self.person.values())
        return min(values.count("pass"), values.count("fail")) >= targets.ROUGH

    def judge_now(self, found) -> None:
        """The grades and reasons of the judge in the newest results (`found`) on the marks,
        in place of the ones they were made on: after a check found that judge worse, its
        mistakes are the ones to fix."""
        from judgekeeper.check import _matched

        for i, a in _matched(found, self.person, self.ws).items():
            self.judge[i] = a.verdict
            self.reasons[i] = scrub(a.reason or "")
            self.scores[i] = a.score
        self.worse_from = one_line(str(found.results[0].rel))

    def row(self, i: str) -> dict:
        """One mark as the patterns and mistakes.md read it."""
        from judgekeeper.fingerprint import rule_hash
        from judgekeeper.start_label import display

        raw = self.rows.get(i, {})
        why = self.why.get(i) or reasons.of_line(None)
        taps = list(why["reasons"]) + [c["id"] for c in self.own.values() if why["note"]
                                       and (c.get("from") == i
                                            or reasons.same_words(c["text"], why["note"]))
                                       and c["id"] not in why["reasons"]]
        taps = [k for k in taps if k in reasons.REASONS or k in self.own]
        same = why["rule_hash"] == rule_hash(self.data.get("rule"))
        return {"id": i, "judge": self.judge[i], "final": self.person[i],
                "earlier": i in self.earlier,
                "input": display(raw.get("input")), "output": display(raw.get("output")),
                "score": self.scores.get(i), "reason": self.reasons.get(i, ""),
                "why": self.notes.get(i, ""), "reasons": taps,
                "words": {k: self.own[k]["text"] for k in taps if k in self.own},
                "parts": [[n, self.parts[n - 1]] for n in why["rule_parts"]
                          if same and 1 <= n <= len(self.parts)],
                "spans": why["spans"]}


def _cells(m: Marks, ids: list[str], rng: random.Random) -> tuple[list[str], list[str]]:
    """(seen, hidden) of `ids`: HIDDEN_TENTHS of each stratum's cell (batch, the judge's
    grade, whether the person agrees) hidden, rounded up, except a cell of one."""
    batch = m.batch
    seen, hidden = [], []
    for b in sorted({batch.get(i, 1) for i in ids}):
        for judge in ("pass", "fail"):
            for agrees in (True, False):
                cell = sorted(i for i in ids if batch.get(i, 1) == b and m.judge[i] == judge
                              and (m.person[i] == judge) == agrees)
                rng.shuffle(cell)
                n = -(-len(cell) * HIDDEN_TENTHS // 10) if len(cell) > 1 else 0
                hidden += cell[:n]
                seen += cell[n:]
    return seen, hidden


def _top_up(m: Marks, new: list[str], known: set[str], hidden: list[str],
            rng: random.Random) -> tuple[list[str], list[str]]:
    """(seen, hidden) of the `new` marks: each cell (as _cells) of each batch, with the marks
    already split (`known`), gets HIDDEN_TENTHS hidden, rounded up, except a cell of one; the
    new marks make up what is missing. With none split yet, as _cells."""
    def where(i):
        return m.batch.get(i, 1), m.judge[i], m.person[i] == m.judge[i]

    kept = set(hidden)
    seen, out = [], []
    for b in sorted({m.batch.get(i, 1) for i in new}):
        for judge in ("pass", "fail"):
            for agrees in (True, False):
                cell = sorted(i for i in new if where(i) == (b, judge, agrees))
                old = [i for i in known if where(i) == (b, judge, agrees)]
                size = len(cell) + len(old)
                want = -(-size * HIDDEN_TENTHS // 10) if size > 1 else 0
                n = max(0, want - sum(i in kept for i in old))
                rng.shuffle(cell)
                out += cell[:n]
                seen += cell[n:]
    return seen, out


def make_split(m: Marks, seed: int) -> tuple[list[str], list[str]]:
    """(seen ids, hidden ids): HIDDEN_TENTHS of each cell of each stratum hidden (_cells);
    then more hidden until MIN_EACH marked Pass and Fail are."""
    rng = random.Random(seed)
    seen, hidden = _cells(m, list(m.person), rng)
    for mark in ("pass", "fail"):
        more = [i for i in seen if m.person[i] == mark]
        rng.shuffle(more)
        while sum(m.person[i] == mark for i in hidden) < MIN_EACH and more:
            i = more.pop()
            seen.remove(i)
            hidden.append(i)
    return sorted(seen), sorted(hidden)


@dataclass
class Split:
    """fix/split.json: the seen and hidden marks of this set, and every test on it."""
    seed: int
    seen: list[str]
    hidden: list[str]
    set: int = 1
    made_at: str = ""
    tests: list[dict] = field(default_factory=list)
    pass_mark: dict | None = None
    fresh: dict | None = None  # {"want"}: after MAX_RULES rules, `fix --new` ("asked") or a
    # rule taken on ("adopted"), new marks make a new set
    pending: list[str] = field(default_factory=list)  # new marks waiting for a new set
    earlier: int = 0  # marks the earlier sets hold, all seen: this set's own are the others
    # `fresh` and `earlier` come from history.jsonl (_set_history), never from split.json, and
    # `earlier` is 0 for set 1 and at most what marks.jsonl gives (_earlier_in_marks): an edit
    # there, or a line added to history.jsonl, can't skip the about-half check

    def to_json(self) -> dict:
        return {"set": self.set, "seed": self.seed, "made_at": self.made_at,
                "visible": self.seen, "hidden": self.hidden, "tests": self.tests,
                "pass_mark": self.pass_mark}

    def rules(self) -> list[str]:
        """The LLM-as-a-judge setups tested on this set (test_key), once each."""
        return list(dict.fromkeys(t.get("key") or t.get("setup_hash") or t.get("rule_hash")
                                  for t in self.tests if t["kind"] == "rule"))


def _folder(ws: Workspace) -> Path:
    return ws.dir / FOLDER


def _file(ws: Workspace, name: str) -> str:
    """fix/<name> as the person finds it, a link they can click in a terminal."""
    return link(_folder(ws) / name, f"{shown_folder(ws)}/{FOLDER}/{name}")


class SplitError(ValueError):
    """fix/split.json is there but can't be used: never replaced, never guessed around."""


DAMAGED = ("judgekeeper can't use {file}: {why}. It says which of your marks are kept aside, "
           "so judgekeeper doesn't replace it or guess.")
NEXT_DAMAGED = ("put back the {name} judgekeeper wrote, or run `{command} --new`. Then every "
                "mark you have counts as seen, and the next {n} you make are kept aside.")


def _ints(t: dict, *keys: str) -> bool:
    return all(type(t.get(k)) is int and t[k] >= 0 for k in keys)


def _fits(strata, t: dict) -> bool:
    """Whether a test's groups ([pool, fixed, broke, kept aside] each) add up to its counts."""
    if not isinstance(strata, list) or not all(
            isinstance(s, list) and len(s) == 4 and all(type(x) is int and x >= 0 for x in s)
            and s[1] + s[2] <= s[3] for s in strata):
        return False
    return [sum(s[k] for s in strata) for k in (1, 2, 3)] == [t["fixed"], t["broke"], t["n"]]


SET = "set"  # history.jsonl's kind for a set retired (its `fresh`) or begun (its `earlier`)


def _note_set(ws: Workspace, split: Split, **what) -> None:
    """A set retired (fresh=...) or begun (earlier=...), in history.jsonl: counts only, never
    answer text or ids. The split's seed tells this split from one made after a delete."""
    marks.append(ws.history_jsonl, {"time": utc_now(), "kind": SET, "seed": split.seed,
                                    "set": split.set, **what})


def _set_history(ws: Workspace, seed, number) -> tuple[int, dict | None]:
    """(how many marks the earlier sets hold, the set's `fresh` once it is retired) for set
    `number` of the split with `seed`, from history.jsonl: (0, None) when it says none. Set 1
    has no earlier sets: a line saying it has is not read."""
    try:
        text = ws.history_jsonl.read_text(encoding="utf-8")
    except OSError:
        return 0, None
    earlier, fresh = 0, None
    for raw in jsonl_lines(text):
        try:
            line = loads(raw)
        except ValueError:
            continue
        if not isinstance(line, dict) or line.get("kind") != SET or line.get("seed") != seed \
                or line.get("set") != number:
            continue
        if type(line.get("earlier")) is int and line["earlier"] >= 0 and number > 1:
            earlier = line["earlier"]
        if isinstance(line.get("fresh"), dict) and type(line["fresh"].get("want")) is int:
            fresh = line["fresh"]
    return earlier, fresh


def _earlier_in_marks(ws: Workspace, seen: list[str], hidden: list[str]) -> int:
    """How many of the `seen` marks were first made before any `hidden` one, by marks.jsonl:
    the most a later set's earlier sets can hold, since every mark made once a set begins is
    its own. A seen mark is its first Pass or Fail. A kept-aside one is its first Pass or Fail
    since it was last skipped or taken back: an answer skipped, or marked and taken back,
    before a set began and marked after is the set's. None kept aside, or one never marked: 0."""
    m = read_cached(ws.marks, marks.read)
    if not hidden or any(i not in m.fresh_mark for i in hidden):
        return 0
    first = min(m.fresh_mark[i] for i in hidden)
    return sum(m.first_mark.get(i, first) < first for i in seen)


def _sum(d: dict) -> str:
    """The sha256 of split.json's data `d` without its own: any edit by hand changes it."""
    body = json.dumps({k: v for k, v in d.items() if k != "sha256"}, sort_keys=True,
                      ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _split_problem(ws: Workspace, d) -> str | None:
    """What is wrong with split.json's data `d`, in a few words; None when it is as
    judgekeeper writes it: two lists of answers judgekeeper has, apart, about half kept aside
    (of the set's own marks, before it is retired: both from history.jsonl, the earlier
    sets' marks no more than marks.jsonl says), tests whose counts fit them, and its sha256
    (one written before there was one is read as it is)."""
    if not isinstance(d, dict) or type(d.get("seed")) is not int or not isinstance(
            d.get("set", 1), int) or isinstance(d.get("set", 1), bool) or d.get("set", 1) < 1:
        return "it is not as judgekeeper writes it"
    seen, hidden, tests = d.get("visible"), d.get("hidden"), d.get("tests") or []
    if not all(isinstance(x, list) and all(isinstance(i, str) for i in x)
               for x in (seen, hidden)) or not isinstance(tests, list):
        return "it is not as judgekeeper writes it"
    earlier, fresh = _set_history(ws, d["seed"], d.get("set", 1))
    earlier = min(earlier, _earlier_in_marks(ws, seen, hidden))
    if set(seen) & set(hidden):
        return "it names some marks as both kept aside and shown"
    if len(set(seen)) != len(seen) or len(set(hidden)) != len(hidden):
        return "it names a mark twice"
    try:
        known = read_cached(ws.pool, _pool_rows)
    except (OSError, ValueError, KeyError):
        known = None
    if known is not None and any(i not in known for i in (*seen, *hidden)):
        return "it names answers judgekeeper doesn't have"
    total = len(seen) + len(hidden)
    own = total - min(earlier, len(seen))  # a later set's: the marks made since the one before
    if not fresh and own >= 2 * MIN_EACH and \
            15 * len(hidden) < own * HIDDEN_TENTHS:  # under 2/3 of the share kept aside
        return "it keeps far fewer than half of your marks aside"
    for t in tests:
        if not isinstance(t, dict) or t.get("kind") not in ("rule", "pass mark") or \
                not _ints(t, "n", "fixed", "broke") or t["fixed"] + t["broke"] > t["n"] or \
                t["n"] > total:
            return "a test in it has counts that don't fit its marks"
        strata = t.get("strata")
        if strata is not None and not _fits(strata, t):
            return "a test in it has counts that don't fit its marks"
        if t["kind"] == "rule" and (not _ints(t, "test") or t["test"] < 1 or t.get("verdict") !=
                                    targets.fix_verdict(t["fixed"], t["broke"], t["n"],
                                                        test=t["test"], strata=strata).kind):
            return "a test in it has a result its counts don't give"
    if "sha256" in d and d["sha256"] != _sum(d):  # a swap, a new seed, a mark taken out
        return "it was changed by hand"
    return None


def read_split(ws: Workspace) -> Split | None:
    """fix/split.json; None when there is none. SplitError when it is there but damaged or
    changed by hand (_split_problem)."""
    path = _folder(ws) / SPLIT
    if not path.exists() and not path.is_symlink():
        return None
    try:
        d = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SplitError("it can't be read as JSON") from e
    why = _split_problem(ws, d)
    if why:
        raise SplitError(why)
    earlier, fresh = _set_history(ws, d["seed"], d.get("set", 1))
    earlier = min(earlier, _earlier_in_marks(ws, d["visible"], d["hidden"]))
    return Split(seed=d["seed"], seen=list(d["visible"]), hidden=list(d["hidden"]),
                 set=d.get("set", 1), earlier=min(earlier, len(d["visible"])),
                 made_at=str(d.get("made_at") or ""), tests=d["tests"]
                 if isinstance(d.get("tests"), list) else [], pass_mark=d.get("pass_mark"),
                 fresh=fresh)


def shown_split(ws: Workspace) -> tuple[bool, Split | None]:
    """(whether the marks can be shown, the split): a damaged split.json shows none, since it
    can't say which are kept aside."""
    try:
        return True, read_split(ws)
    except SplitError:
        return False, None


def save_split(ws: Workspace, split: Split) -> None:
    path = _folder(ws) / SPLIT
    marks._refuse_links(path)
    make_private(path.parent)
    d = split.to_json()
    write_replacing(path, json.dumps({**d, "sha256": _sum(d)}, indent=2) + "\n")


def can_run(ws: Workspace) -> bool:
    """Whether `fix` has the marks it needs (Marks.enough): until then it says NOT_ENOUGH. A
    file it can't read is said by `fix` itself."""
    try:
        return Marks(ws).enough()
    except (OSError, ValueError, KeyError):
        return True


def current_split(ws: Workspace, m: Marks, new: bool = False) -> Split:
    """The saved split with marks made since it split the same way; a new one when there is
    none. `new` retires the saved one: a mark once seen is never kept aside again, so only
    marks made after it make the next set."""
    try:
        split = read_split(ws)
    except SplitError:
        if not new:
            raise
        split = None  # `--new` asked: every mark counts as seen, so none can be guessed
    if split is None and new:  # none to retire: the marks may have been seen all the same
        split = Split(seed=secrets.randbelow(2 ** 31), seen=sorted(m.person), hidden=[],
                      made_at=utc_now(), fresh={"want": FRESH, "asked": True})
        _note_set(ws, split, fresh=split.fresh)
    elif split is None:
        seed = secrets.randbelow(2 ** 31)
        seen, hidden = make_split(m, seed)
        split = Split(seed=seed, seen=seen, hidden=hidden, made_at=utc_now())
    elif not split.fresh and len(split.rules()) >= MAX_RULES:
        retire(split)
        _note_set(ws, split, fresh=split.fresh)
    elif not split.fresh and _adopted(ws, split):
        retire(split, adopted=True)
        _note_set(ws, split, fresh=split.fresh)
    elif new and not split.fresh:
        retire(split, asked=True)
        _note_set(ws, split, fresh=split.fresh)
    known = set(split.seen) | set(split.hidden)
    new_ids = [i for i in m.order if i not in known]
    if split.fresh:  # MAX_RULES rules tested: the next FRESH new marks are a new set
        if len(new_ids) >= split.fresh["want"]:
            split = Split(seed=split.seed, seen=sorted(known), hidden=new_ids,
                          set=split.set + 1, earlier=len(known), made_at=utc_now())
            _note_set(ws, split, earlier=split.earlier)
        else:
            split.pending = new_ids
    elif new_ids and split.hidden:  # new marks are kept aside at the same share, within each
        # stratum, however many sittings they came in
        seen, hidden = _top_up(m, new_ids, set(known) & set(m.person), split.hidden,
                               random.Random(f"{split.seed}/{len(known)}"))
        split.seen += seen
        split.hidden += hidden
    else:
        split.seen += new_ids
    split.seen = [i for i in split.seen if i in m.person]
    split.hidden = [i for i in split.hidden if i in m.person]
    split.earlier = min(split.earlier, len(split.seen))  # an earlier set's mark may be undone
    save_split(ws, split)
    return split


def _adopted(ws: Workspace, split: Split) -> bool:
    """Whether an LLM-as-a-judge tested on this set is the one the marks test now
    (judge.json): its setup, or its rule, is a tested one that differs from the one the marks
    tested when it was tested. Results that hold no rule can't tell one rule from another, so
    for them only MAX_RULES retires the set."""
    from judgekeeper import judge_setup

    saved = judge_setup.read(ws) or {}
    now = {"setup_hash": saved.get("setup_hash"),
           "rule_hash": (saved.get("setup") or {}).get("rule_hash")}
    for t in split.tests:
        was = t.get("from") or {}
        if t["kind"] == "rule" and any(now[k] and t.get(k) == now[k] != was.get(k)
                                       for k in now):
            return True
    return False


def retire(split: Split, asked: bool = False, adopted: bool = False) -> None:
    """The set's hidden marks are seen like the others from now on; the next FRESH new marks
    make a new set. `asked`: by `fix --new`; `adopted`: a rule tested on the set was taken on
    (_adopted); neither: after MAX_RULES rules."""
    split.seen = sorted(set(split.seen) | set(split.hidden))
    split.hidden = []
    split.fresh = {"want": FRESH, **({"asked": True} if asked else {}),
                   **({"adopted": True} if adopted else {})}


def prepare_split(ws: Workspace, m: Marks | None = None) -> None:
    """Set the hidden marks aside when the first result appears (and take in marks made
    since), before any mistake is shown; nothing when there are too few marks. `m`: the
    marks, when the caller has them (Marks(ws))."""
    try:
        m = m if m is not None else Marks(ws)
    except (OSError, ValueError, KeyError):
        return
    if m.enough():
        try:
            current_split(ws, m)
        except SplitError:
            pass  # said by `fix`; nothing is shown from the marks meanwhile


# The patterns -------------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w for w in re.findall(r"[^\W\d_]{4,}", text.lower())
                              if w not in STOPWORDS))


def _about(n: float) -> int:
    return int(round(n, -1)) if n >= 100 else round(n)


def mistakes(rows: list[dict]) -> list[dict]:
    """The marks the judge got wrong (the person's mark is not the judge's grade); never on a
    grade an earlier judge gave (Marks.earlier)."""
    return [r for r in rows if r["final"] != r["judge"] and r.get("choice") != "rule_unclear"
            and not r.get("earlier")]


def patterns(rows: list[dict], mark: float | None = None,
             aside: int = 0) -> list[list[str]]:
    """Plain patterns in the judge's mistakes on `rows` ("judge", "final", "output" text,
    "score"), only when strong: each pattern is its sentences. `mark` is the pass mark when
    the judge's grades follow its scores. `aside`: the marks kept aside, said with the count
    of mistakes (Fix's screen: the mistakes are on the other marks only)."""
    wrong = mistakes(rows)
    n = len(wrong)
    if n < FEW:
        return []
    out = []
    passes = sum(m["judge"] == "pass" for m in wrong)
    fails = n - passes
    made = f"Your LLM-as-a-judge made {n} mistakes."
    if aside:
        made = (f"Your LLM-as-a-judge made {n} mistakes on the {len(rows)} marks used here. "
                f"The other {plural(aside, 'mark')} {'is' if aside == 1 else 'are'} kept aside to "
                "test a new "
                "rule.")
    easy = "it said Pass where you said Fail"
    strict = "it said Fail where you said Pass"
    other = {True: f", and in {fails}, {strict}" if fails else "",  # a kind with none: out
             False: f", and in {passes}, {easy}" if passes else ""}
    if passes > fails:
        out.append([f"{made} In {passes}, {easy}{other[True]}.", "Its rule may be too easy."])
    elif fails > passes:
        out.append([f"{made} In {fails}, {strict}{other[False]}.", "Its rule may be too strict."])
    else:
        out.append([f"{made} In {passes}, {easy}. In the other {fails}, {strict}."])
    if mark is not None:
        near = sum(m.get("score") is not None and abs(m["score"] - mark) <= NEAR + 1e-9
                   for m in wrong)
        if near * 2 > n:
            out.append([(f"{near} of your LLM-as-a-judge's {n} mistakes sit close to the pass "
                         "mark."), "Moving the pass mark may fix them."])
    for judge, final, name in (("fail", "pass", "it said Fail and you said Pass"),
                               ("pass", "fail", "it said Pass and you said Fail")):
        side = [len(m["output"].split()) for m in wrong if m["judge"] == judge]
        agreed = [len(m["output"].split()) for m in rows
                  if m["judge"] == m["final"] == final]
        if len(side) < LONG_SIDE or len(agreed) < FEW:
            continue
        long, usual = statistics.median(side), statistics.median(agreed)
        if usual > 0 and long >= LONG * usual:
            out.append([(f"When {name}, the answers are long (about {_about(long)} words, "
                         f"while the others average {_about(usual)}).")])
    agreed = [m for m in rows if m["judge"] == m["final"]]
    if len(agreed) >= FEW:
        in_wrong = Counter(w for m in wrong for w in _words(m["output"]))
        in_agreed = Counter(w for m in agreed for w in _words(m["output"]))
        in_all = Counter(w for m in rows for w in _words(m["output"]))
        k = len(agreed)
        strong = []
        for word, a in in_wrong.items():
            b = in_agreed[word]
            if in_all[word] * 2 > len(rows):  # in most answers: it says nothing about mistakes
                continue
            odds = (math.log((a + 0.5) / (n - a + 0.5))
                    - math.log((b + 0.5) / (k - b + 0.5)))
            if a >= WORD_IN and a * WORD_SHARE >= n and odds >= STRONG:
                strong.append((odds, a, word))
        strong.sort(key=lambda x: (-x[0], -x[1]))
        if strong:
            out.append(["Words found in many of your LLM-as-a-judge's mistakes: " + ", ".join(
                f"{word} ({a})" for _, a, word in strong[:WORDS_SHOWN]) + "."])
    return out


def pattern_lines(rows: list[dict], mark: float | None = None) -> list[str]:
    """`patterns`, one sentence a line."""
    return [line for p in patterns(rows, mark) for line in p]


def where_wrong(ws: Workspace, most: int = 3) -> tuple[list[str], int]:
    """For the result: at most `most` pattern lines and how many mistakes the judge made, on
    the marks the person can see (all of them until some are hidden)."""
    m = Marks(ws)
    ok, split = shown_split(ws)
    ids = ([i for i in split.seen if i in m.person] if split else list(m.person)) if ok else []
    rows = [m.row(i) for i in ids]
    pm = m.data.get("pass_mark")
    lines = pattern_lines(rows, pm["mark"] if _follows(m, pm) else None)
    return lines[:most], len(mistakes(rows))


# A result in a few words, fix's own (RESULT), as `check` names an earlier test
RESULT_WORDS = {"better": "better", "safe": "safe to try",
                "leans better": "can't tell yet, leans toward better",
                "same": "can't tell yet", "leans worse": "can't tell yet, leans toward worse",
                "worse": "looks worse"}


def without_why(mistakes: list[dict]) -> list[dict]:
    """The disagreements of report_section the person has given no reason on yet (no tap,
    note or marked words)."""
    def given(x: dict) -> bool:
        why = x.get("why") or {}
        return bool(why.get("reasons") or why.get("note") or why.get("spans"))

    return [x for x in mistakes if not given(x)]


def prepared_section(ws: Workspace) -> dict | None:
    """report_section after prepare_split, on one reading of the marks: with many marks,
    reading them takes time."""
    try:
        m = Marks(ws)
    except (OSError, ValueError, KeyError):
        return None
    prepare_split(ws, m)
    return report_section(ws, m)


def report_section(ws: Workspace, m: Marks | None = None) -> dict | None:
    """The result page's disagreements: the mistakes on the marks the person can see, with the
    judge's reason (`reasons_given`: whether any marked answer has one), each text whole (the
    page folds each row), a many-field question's
    `fields` as the marking page shows them, and the person's reasons on it (`why`:
    reasons.of_line, rule parts only of the rule now); the rule's parts and the person's own
    buttons. Never a hidden mark. None when there is none. A split.json that can't be used
    can't say which marks are kept aside: no mistake and `split_unknown`. `m`: the marks,
    when the caller has them (Marks(ws))."""
    try:
        m = m if m is not None else Marks(ws)
    except (OSError, ValueError, KeyError):
        return None
    ok, split = shown_split(ws)
    if not ok:
        return {"mistakes": [], "split_unknown": True}
    ids = [i for i in split.seen if i in m.person] if split else list(m.person)
    wrong = mistakes([m.row(i) for i in ids])
    if not wrong:
        return None

    def why(r: dict) -> dict:
        saved = m.why.get(r["id"]) or reasons.of_line(None)
        return {"reasons": saved["reasons"], "note": saved["note"],
                "rule_parts": [n for n, _ in r["parts"]], "spans": saved["spans"]}

    return {"mistakes": [{"id": r["id"], "judge": r["judge"], "final": r["final"],
                          "question": _question(m, r), "fields": _fields(m, r),
                          "answer": reasons.canonical(r["output"]),
                          "reason": r["reason"], "why": why(r)}
                         for r in wrong],
            "parts": m.parts, "left_out": reasons.parts_left_out(m.data),
            "own": list(m.own.values()),
            "reasons_given": any(m.reasons.get(i) for i in m.person)}  # else no reason column


def _fields(m: Marks, row: dict) -> list[list[str]] | None:
    """A mistake's question as named values, as the marking page shows them, when two or more
    are left (none is the answer itself); else None."""
    from judgekeeper.start_label import shown_question

    held = m.rows.get(row["id"], {})
    shown = shown_question(m.ws, held.get("input"), held.get("output"))
    if not isinstance(shown, list):
        return None
    shown = [[k, v] for k, v in shown if v.strip() != str(row["output"]).strip()]
    return shown if len(shown) > 1 else None


def _question(m: Marks, row: dict) -> str:
    """A mistake's question as the marking page showed it: of named values, those that are not
    the answer itself (it shows next to it); one left as its value alone."""
    from judgekeeper.start_label import shown_question

    held = m.rows.get(row["id"], {})
    shown = shown_question(m.ws, held.get("input"), held.get("output"))
    if not isinstance(shown, list):
        return shown
    shown = [(k, v) for k, v in shown if v.strip() != str(row["output"]).strip()]
    if len(shown) == 1:
        return shown[0][1]
    return "\n".join(f"{k}: {v}" for k, v in shown)


# mistakes.md --------------------------------------------------------------------------------

TASK = ("Write a new rule so your LLM-as-a-judge agrees with the marks below. Keep what the "
        "current rule gets right. You can hand this whole file to a coding agent.")
NO_PATTERN = "No pattern stands out yet."
WHERE_WRONG = "Where your LLM-as-a-judge goes wrong:"  # the clues' heading, here and in mistakes.md


def clue_lines(rows: list[dict], mark: float | None = None) -> list[str]:
    """Every clue, one sentence a line: the person's reasons first (reasons.clue_lines, on
    the mistakes), then the patterns."""
    return reasons.clue_lines(mistakes(rows), fence=start_fix_rule.fenced) + pattern_lines(
        rows, mark)


WORSE_JUDGE = ("These are the mistakes of your new LLM-as-a-judge, whose grades are in {file}: "
               "`{check}` found it worse than the one you marked against.")


MARKED_WITH = "The rule you marked with"
SAME_RULE = "The same as the rule now."


def marked_rule(data: dict) -> str | None:
    """The rule the marks were made with: start.json's marked_rule (kept when check took on
    a new rule), else its rule; None when the answers were graded by more than one rule."""
    if not data.get("one_rule", True):
        return None
    rule = data.get("marked_rule") or data.get("rule")
    return rule if isinstance(rule, str) else None


def mistakes_md(rule: str | None, rows: list[dict], mark: float | None = None,
                worse_from: str | None = None, marked: str | None = None) -> str:
    """The clue file, ready for a person or a coding agent: the task, the clues (the person's
    reasons and the pattern sentences the terminal prints; `mark` is the pass mark when the
    grades follow the scores), the judge's rule now, then each mistake on the seen marks,
    fenced as data; grouped by the person's reasons when they gave any. The warning comes
    before any of the person's or the app's words; the person's words outside a fence are on
    one line. `worse_from`: after a check found the new judge worse, the results its grades
    are in (Marks.judge_now): the mistakes are that judge's."""
    fenced = start_fix_rule.fenced
    clues = clue_lines(rows, mark) or [NO_PATTERN]
    parts = ["# Your LLM-as-a-judge's mistakes", "", TASK, "",
             f"{start_fix_rule.DATA_WARNING} {start_fix_rule.MARKS}", ""]
    if worse_from:
        with plainly():  # a file in .judgekeeper/: never a path that started it
            check = program("check")
        parts += [WORSE_JUDGE.format(file=worse_from, check=check), ""]
    parts += [f"## {WHERE_WRONG.rstrip(':')}", "", *clues, ""]
    if rule:
        parts += ["## Your LLM-as-a-judge's rule now", "", fenced("RULE", rule, cut=False), ""]
    if marked:  # a copy to go back to, after "Worse" too
        parts += [f"## {MARKED_WITH}", "", SAME_RULE if marked == rule
                  else fenced("MARKED RULE", marked, cut=False), ""]
    parts += ["## Mistakes", ""]
    wrong = mistakes(rows)
    grouped = reasons.groups(wrong, True) if reasons.has_any(wrong) else [(None, wrong)]
    n = 0
    for title, group in grouped:
        if title:
            parts += [f"## {title}", ""]
        for r in group:
            n += 1
            parts.append(f"## [M{n}] Your LLM-as-a-judge said {r['judge'].upper()}. You said "
                         f"{r['final'].upper()}.")
            answer = reasons.canonical(r["output"])
            parts += [fenced("QUESTION", r["input"]),
                      fenced("ANSWER", reasons.bold(answer, r.get("spans")))]
            said = reasons.said_line(r)
            if said:
                parts.append(said)
            if r.get("why"):
                parts.append(fenced("YOUR REASON", one_line(r["why"])))
            if r.get("reason"):
                parts.append(fenced("LLM-AS-A-JUDGE'S REASON", r["reason"]))
            parts.append("")
    return reasons.cleaned(scrub("\n".join(parts).rstrip("\n") + "\n"))


def write_suggestions(ws: Workspace, rows: list[dict]) -> bool:
    """fix/suggestions.md from the person's reasons on the mistakes they can see (`rows`: the
    seen marks), when they gave any; one written before is written again. Whether it holds
    any."""
    wrong = mistakes(rows)
    path = _folder(ws) / SUGGESTIONS
    if not reasons.has_any(wrong) and not path.is_file():
        return False
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, reasons.suggestions_md(wrong))
    return reasons.has_any(wrong)


def refresh_mistakes(ws: Workspace, always: bool = False) -> int:
    """mistakes.md again from the marks the person can see, when there is one (`always`:
    also when there is none): after a check moved the marks to a new judge, its rule and its
    mistakes are that judge's. Returns how many mistakes it holds."""
    path = _folder(ws) / MISTAKES
    if not always and not path.is_file():
        return 0
    m = Marks(ws)
    ok, split = shown_split(ws)
    if not ok:
        return 0
    rows = [m.row(i) for i in (split.seen if split else m.person) if i in m.person]
    pm = m.data.get("pass_mark")
    rule = m.data.get("rule") if m.data.get("one_rule", True) else None
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, mistakes_md(rule, rows, pm["mark"] if pm and pm.get("follows")
                                      else None, marked=marked_rule(m.data)))
    write_suggestions(ws, rows)
    return len(mistakes(rows))


def _saved_line(ws: Workspace, n: int) -> str:
    """Where the `n` mistakes went and what the file is for. With 3 or more, the clues above
    came from them ("All {n}"); with 1 or 2 there are no clues, so the words say how many."""
    made = (f"All {n} mistakes your LLM-as-a-judge made are" if n > 2
            else "Both mistakes your LLM-as-a-judge made are" if n == 2
            else "The one mistake your LLM-as-a-judge made is")
    return (f"{made} saved in {_file(ws, MISTAKES)}. Use it to write a better "
            "rule, or hand it to a coding agent to help you write one.")


# The pass mark (free) ----------------------------------------------------------------------

VERDICT_WORDS = {"better": "better", "safe": "safe to try"}


def _follows(m: Marks, pm: dict | None) -> bool:
    return bool(pm and pm.get("follows")) and all(
        isinstance(m.scores.get(i), int | float) for i in m.person)


def by_stratum(m: Marks, ids: list[str], old: dict, new: dict) -> list[list[int]]:
    """[pool, fixed, broke, kept aside] for each group the marks kept aside (`ids`) were
    picked from, (batch, the LLM-as-a-judge's grade then), in order: what targets.fix_verdict
    weighs them by. Fixed: `old` grade wrong, `new` right; broke: the other way."""
    where, sizes = batches.strata(m.data)
    out: dict = {}
    for i in ids:
        s = where.get(i, (m.batch.get(i, 1), m.judge[i]))
        row = out.setdefault(s, [int(sizes.get(s, 0)), 0, 0, 0])
        row[1] += old[i] != m.person[i] and new[i] == m.person[i]
        row[2] += old[i] == m.person[i] and new[i] != m.person[i]
        row[3] += 1
    return [out[s] for s in sorted(out)]


def _check_drop(m: Marks, op: str, mark: float) -> dict | None:
    """check's own rule (check.groups) on every mark it reads, for the pass mark `mark`
    against the one in use: the groups, when check would call it worse; else None. fix's
    test is overall, on the marks kept aside; check's is per side, on all of them."""
    from judgekeeper.check import groups
    from judgekeeper.start import passes

    ids = [i for i in m.person if i in m.judge and i not in m.earlier
           and isinstance(m.scores.get(i), int | float)]
    g = groups({i: m.person[i] for i in ids}, {i: m.judge[i] for i in ids},
               {i: passes(m.scores[i], op, mark) for i in ids})
    return g if any(g[k]["verdict"] == "worse" for k in ("passed", "failed")) else None


def _tried_worse(ws: Workspace, op: str) -> set[float]:
    """The pass marks a check (history.jsonl) found worse than the one before: never offered
    again."""
    from judgekeeper import check, judge_setup

    out = set()
    for x in check._history(ws):
        before, after = x.get("before"), x.get("after")
        if (x.get("kind") != "check" or not isinstance(before, dict)
                or not isinstance(after, dict) or not judge_setup.mark_only(before, after)):
            continue
        if not any(isinstance(g, dict) and g.get("verdict") == "worse"
                   for g in (x.get("groups") or {}).values()):
            continue
        pm = after.get("pass_mark") or {}
        mark = pm.get("mark")
        if pm.get("op") == op and isinstance(mark, int | float) and not isinstance(mark, bool):
            out.add(round(float(mark), 9))
    return out


def _held_back(m: Marks, op: str):
    """skip for choose_mark: a pass mark a check found worse, or one check would call worse."""
    tried = _tried_worse(m.ws, op)
    return lambda mark: round(mark, 9) in tried or _check_drop(m, op, mark) is not None


def _mark_items(m: Marks, split: Split) -> tuple[list, dict]:
    """(the seen marks as choose_mark takes them, their weights)."""
    from judgekeeper.start_fix import cell, cell_weights

    rows = {i: {"judge": m.judge[i], "final": m.person[i]} for i in m.person}
    pool = m.data.get("pool") or {}
    if len(set(m.batch.values())) > 1:  # each answer weighs by its stratum
        for i, row in rows.items():
            row["batch"] = m.batch.get(i, 1)
        pool = Counter((m.batch[q], g) for q, g in
                       ((q["id"], q["group"]) for q in m.data.get("queue") or []))
    seen = [rows[i] for i in split.seen]
    weights = cell_weights(list(rows.values()), seen, pool)
    return [(cell(rows[i]), m.person[i], m.scores[i]) for i in split.seen], weights


def held_line(m: Marks, split: Split) -> str | None:
    """The pass mark that fits the seen marks best, when it is held back (_held_back): why,
    in one line. None when it is not held back, or there is none better."""
    from judgekeeper.start_fix import choose_mark

    pm = m.data.get("pass_mark")
    if not _follows(m, pm):
        return None
    current, op = pm["mark"], pm["op"]
    items, weights = _mark_items(m, split)
    best = choose_mark(items, current, op, weights)
    if best == current:
        return None
    if round(best, 9) in _tried_worse(m.ws, op):
        return TRIED_WORSE.format(new=f"{best:g}")
    g = _check_drop(m, op, best)
    if g is None:
        return None
    less = " and ".join(f"on the answers you {key} ({g[key]['new_right']} of {g[key]['n']}, "
                        f"down from {g[key]['old_right']})"
                        for key in ("passed", "failed") if g[key]["verdict"] == "worse")
    fixed = sum(g[k]["now_right"] for k in ("passed", "failed"))
    broke = sum(g[k]["now_wrong"] for k in ("passed", "failed"))
    lead = "It fixes more answers overall, but agrees" if fixed > broke else "It agrees"
    return HELD.format(new=f"{best:g}", old=f"{current:g}", lead=lead, less=less)


# A pass mark held back (held_line): check would call it worse, or a check did
HELD = ("judgekeeper also tried a pass mark of {new} instead of {old}. {lead} with you less "
        "{less}, so `check` would call it worse.")
TRIED_WORSE = "You tried a pass mark of {new} with `check`, and it was worse."
KEEP = " Keep {old}."  # after it, when no other pass mark is offered


def test_pass_mark(m: Marks, split: Split) -> dict | None:
    """The pass mark that fits the seen marks best, tested on the hidden marks with the saved
    scores (no AI call), once per set of hidden marks and pass mark in use: the test, also
    kept in split.json, or None for a judge with no pass mark or when the pass mark already
    fits best (kept as {"old", "op"}: the mark it was run for)."""
    from judgekeeper.start import passes
    from judgekeeper.start_fix import choose_mark

    pm = m.data.get("pass_mark")
    if not _follows(m, pm):
        return None
    held = _held_back(m, pm["op"])
    saved = split.pass_mark
    ran_for = saved is not None and (saved.get("old"), saved.get("op")) == (pm["mark"], pm["op"])
    if ran_for and not ("new" in saved and held(saved["new"])):  # run for the mark in use:
        return saved if "new" in saved else None  # the test, or nothing better than it
    if saved and saved.get("new") == pm["mark"] and saved.get("op") == pm["op"]:
        return None  # the mark it found is the one in use now: nothing better was tested
    current, op = pm["mark"], pm["op"]
    items, weights = _mark_items(m, split)
    new = choose_mark(items, current, op, weights, skip=held)  # never one held back
    if new == current:
        split.pass_mark = {"old": current, "op": op}
        return None
    now = {i: passes(m.scores[i], op, new) for i in split.hidden}
    strata = by_stratum(m, split.hidden, m.judge, now)
    fixed, broke = sum(s[1] for s in strata), sum(s[2] for s in strata)
    v = targets.fix_verdict(fixed, broke, len(split.hidden), test=len(split.tests) + 1,
                            strata=strata)
    test = {"kind": "pass mark", "time": utc_now(), "old": current, "new": new, "op": op,
            "n": len(split.hidden), "fixed": fixed, "broke": broke, "verdict": v.kind,
            "strata": strata}
    split.tests.append(test)
    split.pass_mark = test
    return test


def pass_mark_command(ws: Workspace, pm: dict, test: dict) -> str | None:
    """The `check --pass-if` that switches to the better pass mark `test` found, when the
    pass mark is given with --pass-if (not kept in a file judgekeeper found); else None."""
    from judgekeeper.check import _here
    from judgekeeper.start_fix import locate, searched, where_lines

    if VERDICT_WORDS.get(test["verdict"]) is None:
        return None
    name = searched(pm)
    if name and locate(ws.root, name, test["old"]):
        return None
    given = re.search(r'--pass-if "([^"]*)"', where_lines(pm, test["new"])[0])
    return f"{_here(ws, 'check')} --pass-if {quote_arg(given[1])}" if given else None


def pass_mark_line(ws: Workspace, pm: dict, test: dict) -> str | None:
    """The pass-mark line of the fix output, when the verdict says the new mark is worth trying."""
    from judgekeeper.start_fix import locate, searched, where_lines

    words = VERDICT_WORDS.get(test["verdict"])
    if words is None:
        return None
    new, old = f"{test['new']:g}", f"{test['old']:g}"
    name = searched(pm)
    found = name and locate(ws.root, name, test["old"])
    command = pass_mark_command(ws, pm, test)
    if found:
        where = (f"Change it where your eval sets it. That may be in {found[0]}, "
                 f"line {found[1]}.")
    elif command:  # one form: the check that re-checks it with that pass mark
        where = f"To use a pass mark of {new}, run `{command}`."
    else:
        where = re.sub(r'(--pass-if "[^"]*")', r"`\1`", where_lines(pm, test["new"])[0])
    return (f"A better pass mark: {new} instead of {old} (tested on the marks kept aside: fixed "
            f"{test['fixed']}, broke {test['broke']}, so {words}). {where}")


def tried_line(test: dict) -> str:
    """The pass-mark test that found no better mark, said once, when it is made: it counts as
    a test on these marks kept aside, as a rule's does."""
    old = f"{test['old']:g}"
    return (f"judgekeeper also tried a pass mark of {test['new']:g} instead of {old} on the "
            f"marks kept aside (fixed {test['fixed']}, broke {test['broke']}): not clearly "
            f"better, so keep {old}. Each test on the same kept-aside marks makes them a little "
            "less reliable.")


# Saying it ----------------------------------------------------------------------------------

class Talk:
    def __init__(self, path: str):
        self.path = path

    def say(self, text: str = "") -> None:
        said_next(text)
        print(said(text))
        for line in held_lines(text):  # a name left out of the command above, as data
            print(said(line))

    def para(self, text: str, indent: str = "") -> None:
        for line in wrap(text, indent=indent):
            self.say(line)

    def command(self, subcommand: str = "fix") -> str:
        from judgekeeper.start import path_word

        return " ".join((program(subcommand), *([] if self.path == "." else
                                                [path_word(self.path)])))

    def away(self) -> bool:
        """Whether it was given a project folder other than the folder it runs in."""
        try:
            return self.path != "." and Path(self.path).resolve() != Path.cwd().resolve()
        except OSError:
            return True

    def run(self, file: str, subcommand: str = "fix") -> str:
        """"run `judgekeeper fix FILE`": it takes one path, so never the project folder too;
        "in your project folder, run ..." when it was given one from elsewhere (FILE is
        named from there)."""
        where = "in your project folder, " if self.away() else ""
        return f"{where}run `{self.program(subcommand)} {file}`"

    def program(self, subcommand: str = "fix") -> str:
        """program(), from the project folder when it was given one from elsewhere."""
        return program_in(self.path, subcommand) if self.away() else program(subcommand)

    def next(self, text: str) -> None:
        self.say()
        self.para(f"Next: {text}")


def went_line(fixed: int, broke: int) -> str:
    """What the new rule changed on the marks kept aside, in plain counts: how many answers
    went from wrong to right, and how many from right to wrong (said even at 0: a new rule
    can fix some answers and break others)."""
    went = (f"{fixed} answers went" if fixed > 1 else "1 answer went" if fixed == 1
            else "no answer went")
    back = str(broke) if broke else "none"
    return f"With the new rule, {went} from wrong to right, and {back} from right to wrong."


def _sessions_below(path: str) -> tuple[str, str] | None:
    """Where the sessions below this folder are, and the Next step (front.go_to_words)."""
    from judgekeeper import front

    sessions = front.sessions_here(path)
    return front.go_to_words(sessions, program("fix")) if sessions else None


MAY_BE_IN = "Your LLM-as-a-judge's rule may be in"


def _rule_place(ws: Workspace, rule: str, tool: str, data: dict) -> str:
    """Where the rule is, one answer per tool: the file and line that hold it; for Inspect,
    the file Find names too (start_fix_rule.opened_rule_file); else where the eval keeps it."""
    home = start_fix_rule.rule_home(ws.root, tool, data)
    task = data.get("task_file") if tool == "inspect" else None
    read = task and start_fix_rule.opened_rule_file(ws.root, task, rule, tool)
    first = read or start_fix_rule.rule_config(ws.root, tool, data)
    where = start_fix_rule.found_rule(ws.root, rule, tool, first=first)
    said = "Your LLM-as-a-judge's rule is in"
    if where and (not read or where[0] == read):
        # in the file the eval tool reads it from, else a search's guess in the person's code
        known = where[0] in (first, read)
        return (f"{said if known else MAY_BE_IN} {link(ws.root / where[0], where[0])}, "
                f"line {where[1]}")
    if read and read != task:
        file_link = start_fix_rule.file_link
        return (f"{said} {file_link(ws.root, read)}, which {file_link(ws.root, task)} reads "
                f"into {start_fix_rule.field(tool, data.get('rule_field'))}")
    if start_fix_rule.rule_config(ws.root, tool, data):
        return f"{said} {home}"
    if home == start_fix_rule.OWN_CODE:
        return "Your LLM-as-a-judge's rule, where your code keeps it"
    if tool == "promptfoo":  # no config here with the assert: never a file it can't point to
        return f"{said} {home} in your promptfoo config"
    return f"{said} {home} in your eval's code"


def _rule_quote(rule: str) -> str:
    text = " ".join(rule.split())
    if len(text) > RULE_SHOWN:
        text = text[:RULE_SHOWN - 1].rstrip() + "…"
    return f'"{text}"'


# The run ------------------------------------------------------------------------------------

def run(path: str = ".", new: bool = False) -> int:
    """`judgekeeper fix [PATH]`: PATH a file holds new results to test a rule with; a folder
    (or none) is the project. Returns the exit code."""
    from judgekeeper.check import _state, given_results, path_problem

    problem = path_problem(path)
    results = Path(path) if given_results(path) else None
    talk = Talk("." if results is not None else path)
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    hook = old_hook(talk.path)
    if hook:
        talk.para(hook)
        talk.say()
    if problem:  # never a plain `fix` in its place
        talk.say(STEP)
        talk.say()
        talk.para(problem)
        talk.next(f"give `{program_in(ANYWHERE, 'fix')}` the results of grading {ANSWERS} "
                  "again with your new rule, or run it in your project folder.")
        return EXIT_USAGE
    state = _state(talk.path)
    from judgekeeper import project

    if state is not None and results is not None and results.is_file() and (
            marked := project.other_eval(state.ws.root, results)) is not None:
        talk.say(STEP)  # as check and mark: never read as new results
        talk.say()
        talk.para(project.other_eval_line(results, marked))
        return EXIT_NEEDS_YOU
    ws = state.ws if state is not None else None
    m = Marks(ws) if ws is not None else None
    if m is not None and m.data.get("rule") is None:
        _after_worse(state, m)
    try:
        split = current_split(ws, m, new=new) if m is not None and m.enough() else None
    except SplitError as e:
        talk.say(STEP)
        talk.say()
        talk.para(DAMAGED.format(file=_file(ws, SPLIT), why=e))
        talk.next(NEXT_DAMAGED.format(name=SPLIT, command=program("fix"), n=FRESH))
        return EXIT_USAGE
    talk.say(STEP if results is None or split is None or split.fresh else STEP_TEST)
    talk.say()
    if ws is None and results is None and (below := _sessions_below(talk.path)):
        said, step = below
        talk.para(said)
        talk.next(step)
        return EXIT_NEEDS_YOU
    if ws is None and not _has_results(Path(talk.path)):
        talk.para(f"No eval results found in this folder ({Path(talk.path).resolve().name}).")
        talk.next(f"run your eval once from this folder, then run `{program()}`.")
        return EXIT_NEEDS_YOU
    if split is None:
        from judgekeeper.check import mark_more_step
        from judgekeeper.start_label import out_of_reach

        reach = out_of_reach(ws) if ws is not None else None  # as the plain run says
        talk.para(NOT_ENOUGH + (f" {reach}" if reach else ""))
        step = (mark_more_step(ws) if ws is not None  # from here
                else f"run `{program('mark')}` to mark more answers.")
        talk.next(next_marks(ws, step, need=math.inf if reach else 1) if ws is not None
                  else step)
        return EXIT_NEEDS_YOU
    if split.fresh:  # new results from another tool are refused first (exit 2)
        if results is not None and _given(talk, state, m, results) is None:
            return EXIT_USAGE
        return _waiting(talk, ws, m, split, tested=results is not None)
    if results is not None:
        return test_results(talk, state, m, split, results)
    return first_run(talk, ws, m, split)


def _has_results(path: Path) -> bool:
    """Whether judgekeeper finds eval results it reads at `path` (nothing is read)."""
    try:
        found = find.search(path)
    except OSError:
        return True  # said by the step that reads them
    return any(found.readable(t) for t in find.TOOLS)


def _after_worse(state, m: Marks) -> None:
    """For a judge whose results hold no rule (a table), after a check found its new grades
    worse (check.open_worse): the mistakes are the new judge's."""
    from judgekeeper.check import _history, _newest, open_worse

    if not _history(state.ws):
        return
    found, _ = _newest(state)
    if found is not None and open_worse(state.ws, found) is not None:
        m.judge_now(found)


def _waiting(talk: Talk, ws: Workspace, m: Marks, split: Split, tested: bool = False) -> int:
    """MAX_RULES rules were tested on the marks kept aside: FRESH new marks make a new set
    first. The clues show as on a first run (every mark is seen now). `tested`: new results
    were given, and wait for that set."""
    want = split.fresh["want"]
    if split.fresh.get("asked"):
        talk.para("Your next marks will form a new set kept aside.")
    elif split.fresh.get("adopted"):
        talk.para("You switched to a rule tested on these marks kept aside. Testing the next rule "
                  "on the same marks would make a coincidence look like a better rule.")
    else:
        talk.para(f"You have tested {plural(len(split.rules()), 'rule')} on these marks kept "
                  "aside. More tests on the same marks would make a coincidence look like a "
                  "better rule.")
    n = refresh_mistakes(ws, always=True)  # none is kept aside now: every mark is seen
    if n:
        talk.say()
        talk.para(_saved_line(ws, n))
    left = want - len(split.pending)
    talk.say()
    if split.pending:
        talk.para(f"You have marked {len(split.pending)} of the {want} more answers.")
    talk.para(more_marks_line(ws))
    then = (": they become a new set of marks kept aside, and your new results are tested on "
            "them" if tested else ": they become a new set of marks kept aside")
    from judgekeeper.check import mark_here

    talk.next(next_marks(ws, f"mark more answers with `{mark_here(ws)}` (at least {left} "
                             f"more), then run `{talk.command()}` again{then}.", need=left))
    return EXIT_NEEDS_YOU


def more_marks_line(ws: Workspace) -> str:
    """How many more marks a new set kept aside wants (CLEAR_LINE), never more than the
    answers left to mark: with fewer left, those."""
    from judgekeeper.start_label import _left_to_mark

    left = _left_to_mark(ws)
    if left >= CLEAR:
        return CLEAR_LINE
    if not left:
        return NONE_LEFT
    return ONLY_LEFT.format(n=f"{left} answer is" if left == 1 else f"{left} answers are")


def write_answers(ws: Workspace, m: Marks) -> int:
    """fix/marked-answers.csv: every marked answer, `question,answer` only, shuffled, each
    once; cells guarded as a spreadsheet would run them (table.guard_cell). No mark, grade or
    id: the answers kept aside can't be told from the others. How many rows it holds."""
    rows = list(dict.fromkeys((question_text((r := m.rows.get(i, {})).get("input"),
                                             r.get("output")),
                               answer_text(r.get("output")))
                              for i in m.person))
    random.SystemRandom().shuffle(rows)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(ANSWER_COLUMNS)
    for question, answer in rows:
        w.writerow([guard_cell(question), guard_cell(answer)])
    path = _folder(ws) / ANSWERS
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, buf.getvalue(), newline="")
    if m.data.get("tool") == "promptfoo":  # never opened in a spreadsheet: nothing guarded
        tests = _folder(ws) / TESTS_FILE
        marks._refuse_links(tests)
        write_replacing(tests, tests_yaml(rows), newline="")
    return len(rows)


def tests_yaml(rows: list[tuple[str, str]]) -> str:
    """The marked answers as promptfoo tests (fix/marked-answers.yaml, in the CSV's order):
    each question and answer exactly as marked."""
    return "".join("- vars: " + _yaml_string({"question": q, "answer": a}) + "\n"
                   for q, a in rows) or "[]\n"


def _rewrite_lacking(talk: Talk, ws: Workspace, m: Marks, ids: list[str]) -> None:
    """Answers kept aside (`ids`, not in the new results) that marked-answers.csv lacks, as
    after marks added since `fix` wrote it: it is written again, and said, so that grading it
    again holds them. Inspect AI and MLflow grade their own log or store, not the file."""
    if m.data.get("tool") in ("inspect", "mlflow"):
        return
    try:
        with (_folder(ws) / ANSWERS).open(encoding="utf-8", newline="") as f:
            held = {tuple(row[:2]) for row in csv.reader(f)}
    except (OSError, UnicodeDecodeError, csv.Error):
        held = set()
    rows = (m.rows.get(i, {}) for i in ids)
    if all((guard_cell(question_text(r.get("input"), r.get("output"))),
            guard_cell(answer_text(r.get("output"))))
           in held for r in rows):
        return
    write_answers(ws, m)
    talk.say()
    talk.para(REWROTE.format(answers=_file(ws, ANSWERS)))


def question_text(value, output=None) -> str:
    """A question as marked-answers.csv holds it: text as written; of a set of named values
    (such as promptfoo's vars), one value alone, or several as `name: value` lines. An answer
    graded again from that file (asked) keeps the question the file held, so each round
    writes the same text and is matched the same way."""
    from judgekeeper.start_label import display

    value = asked(value, output)
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    return scrub(display(value))


def asked(value, output):
    """The question an answer (`output`) was asked: `value`, or, as a grade of
    marked-answers.csv hands a row back (its two columns as the named values, the answer the
    one graded, as the `echo` provider gives), the question the file held. marked-answers.csv,
    the marking page, its list and the result page all take the question from here."""
    from judgekeeper.check import _text

    if (isinstance(value, dict) and set(value) == set(ANSWER_COLUMNS)
            and isinstance(value["question"], str) and output is not None
            and _text(output) != "" and _text(value["answer"]) == _text(output)):
        return value["question"]
    return value


def answer_text(value) -> str:
    from judgekeeper.start_label import display

    return scrub(display(value))


def mlflow_store(ws: Workspace, here: bool = True) -> str | None:
    """The MLflow store the marks were made on, as a path from where the command runs (not
    `here`: from the project folder; the new grades are a new run in it), or None for
    another eval tool."""
    import os

    try:
        data = ws.cached_data()
    except (OSError, ValueError):
        return None
    store = data.get("mlflow_store") if data.get("tool") == "mlflow" else None
    if not isinstance(store, str) or not store:
        return None
    if not here:
        return quote_arg(store)
    try:
        return quote_arg(Path(os.path.relpath(ws.root / store)).as_posix())
    except ValueError:  # another drive on Windows
        return quote_arg((ws.root / store).resolve().as_posix())


def _new_results(ws: Workspace) -> str:
    """What `fix` is given next: the MLflow store, else NEW_RESULTS."""
    return mlflow_store(ws) or NEW_RESULTS


def _regrade_same(talk: Talk, ws: Workspace) -> str:
    """The next step when answers kept aside are missing from the new results: Inspect AI
    scores its log again, MLflow makes a new run in its store, others grade
    marked-answers.csv."""
    store = mlflow_store(ws, here=not talk.away())
    if store:
        return (f"run your new scorer on all the traces again, then {talk.run(store)}. It "
                f"reads the newest run.")
    try:
        tool = ws.cached_data().get("tool")
    except (OSError, ValueError, AttributeError):
        tool = None
    if tool == "inspect":  # the log itself is scored again
        log = quote_arg(new_log(ws))
        return (f"score your log again with your new rule: run `{inspect_score(ws, log)}` "
                f"and then {talk.run(log)}.")
    return REGRADE_SAME.format(answers=_file(ws, ANSWERS), run=talk.run(NEW_RESULTS))


def _no_grades_next(talk: Talk, ws: Workspace) -> str:
    """The next step when the new results hold no grade at all: for Inspect AI, the command
    with the grader model when the log names it, else the options to give again."""
    try:
        tool = ws.cached_data().get("tool")
    except (OSError, ValueError, AttributeError):
        tool = None
    if tool != "inspect":
        return _regrade_same(talk, ws)
    log = quote_arg(new_log(ws))
    if scorer_model(ws):
        return (f"score your log again with your new rule and your grader model: run "
                f"`{inspect_score(ws, log)}` and then {talk.run(log)}.")
    return (f"give `inspect score` the `-S` options your scorer was set up with, its model "
            f"too, then {talk.run(log)}.")


def _yaml_string(text) -> str:
    """`text` as a double-quoted YAML string (any JSON value as YAML's flow form): JSON is
    YAML, with the line breaks and control characters YAML knows beyond JSON's escaped too."""
    return re.sub("[\x7f-\x9f\u2028\u2029\ufeff\ud800-\udfff]",
                  lambda m: f"\\u{ord(m.group()):04x}", json.dumps(text, ensure_ascii=False))


KEY_PARTS = ("key", "token", "secret", "password", "passwd", "credential", "auth", "bearer",
             "cookie", "session")
LEFT_OUT = ("# {name} left out: judgekeeper never writes keys to files. Set it the way your own "
            "config does.")
_GONE = object()  # a value left out


def _key_like(name: str) -> bool:
    """A name that may hold a key: it contains any of KEY_PARTS, in any case (apiKey, apikey,
    sessionToken, credentials, Authorization). Cautious on purpose."""
    return any(part in name.lower() for part in KEY_PARTS)


def _names_a_key(value) -> bool:
    """A {name: "x-api-key", value: ...} pair: its value is a key under a plain field name."""
    return isinstance(value, dict) and any(
        isinstance(value.get(f), str) and _key_like(value[f]) for f in ("name", "header"))


def _clean(value, path: str, left: list[str]):
    """`value` without anything that may hold a key (each one's path added to `left`), or
    _GONE: a field named like a key (unless its value is a number or true/false: a key never
    is), a dict or list holding a {name: <key-like>} pair, and any text judgekeeper hides as a
    key. A dict or list emptied by that goes too."""
    if isinstance(value, dict):
        kept, before = {}, len(left)
        for name, v in value.items():
            at = f"{path}.{name}" if path else str(name)
            if (_key_like(str(name)) and not isinstance(v, int | float)) or _names_a_key(v) or (
                    isinstance(v, list) and any(_names_a_key(x) for x in v)):
                left.append(at)
                continue
            v = _clean(v, at, left)
            if v is not _GONE:
                kept[name] = v
        return _GONE if not kept and len(left) > before and value else kept
    if isinstance(value, list):
        out, before = [], len(left)
        for i, v in enumerate(value):
            v = _clean(v, f"{path}[{i}]", left)
            if v is not _GONE:
                out.append(v)
        return _GONE if not out and len(left) > before else out
    if isinstance(value, str) and scrub(value) != value:
        left.append(path)
        return _GONE
    return value


def _without_keys(config: dict) -> tuple[dict, list[str]]:
    """(`config` without any field that may hold a key, the paths of those left out, as
    headers[0].value): _clean."""
    left: list[str] = []
    kept = _clean(config, "", left)
    return ({} if kept is _GONE else kept), left


def _promptfoo_assertion(ws: Workspace, data: dict) -> tuple[str, str | None] | None:
    """The type of the model-graded assertion the metric names, and the `metric:` it has (None
    when the metric is the type), read from the first results file; None when not found."""
    found = _promptfoo_grader(ws, data)
    return None if found is None else found[:2]


def _promptfoo_grader(ws: Workspace, data: dict) -> tuple[str, str | None, dict] | None:
    """_promptfoo_assertion, and the `config` of the grader that assertion used ({} when it
    has none or the file can't be read)."""
    from judgekeeper.readers import promptfoo as reader

    metric = data.get("metric")
    if not isinstance(metric, str) or not metric:
        return None
    files = data.get("results_files") or []
    try:
        if not (files and isinstance(files[0], str)):
            raise ValueError("no results file")
        loaded = reader._load(Path(ws.root) / files[0])
        config = loaded.get("config")
        default_test = (config if isinstance(config, dict) else {}).get("defaultTest") or {}
        default_test = default_test if isinstance(default_test, dict) else {}
        for row in loaded["results"]["results"]:
            if not isinstance(row, dict):
                continue
            one = reader._one_rubric(row)
            parts = reader._components(row.get("gradingResult")) or (
                [{"assertion": one}] if one else [])
            for part in parts:
                a = part.get("assertion") if isinstance(part, dict) else None
                a = a if isinstance(a, dict) else {}
                kind = a.get("type")
                if reader.judge_type(kind) and (a.get("metric") or kind) == metric:
                    grader = reader.grader_of(a, reader._options(row.get("testCase")),
                                              default_test)
                    own = grader.get("config") if isinstance(grader, dict) else None
                    return kind, a.get("metric") or None, own if isinstance(own, dict) else {}
    except (RecordsError, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return (metric, None, {}) if reader.judge_type(metric) == metric else None


# regrade.yaml's comments, on the lines they are about (so the line numbers said stay)
ECHO_NOTE = ("  # echo gives back each answer you marked as it is, so no new answers are made. "
             "The grader below still calls its model.")
TESTS_NOTE = "  # the answers you marked"
RULE_NOTE = ("  # your rule: change it here. {{question}} is the question, {{answer}} the "
             "answer")


def _regrade_yaml(ws: Workspace, data: dict) -> str | None:
    """The text of fix/regrade.yaml: the marked answers as tests, the `echo` provider, the
    grader the results name, the same assertion type (and metric name) with the rule as its
    value. The grader keeps its config, without any field that may hold a key: a comment
    names each one left out. None when the grader, the assertion or the one rule can't be
    read."""
    fp = data.get("fingerprint") if isinstance(data.get("fingerprint"), dict) else {}
    provider, grader, rule = fp.get("provider"), fp.get("model"), data.get("rule")
    if not (isinstance(provider, str) and isinstance(grader, str) and isinstance(rule, str)
            and rule.strip() and data.get("one_rule", True)
            and provider not in ("file", "exec") and grader.startswith(f"{provider}:")):
        return None
    found = _promptfoo_grader(ws, data)
    if found is None:
        return None
    kind, config = found[:2], found[2]
    kept, left = _without_keys(config)
    lines = ["prompts: [" + _yaml_string("{{answer}}") + "]",
             "providers: [" + _yaml_string("echo") + "]" + ECHO_NOTE,
             "tests: " + _yaml_string(f"file://{TESTS_FILE}") + TESTS_NOTE,
             "defaultTest:",
             "  options:",
             *("    " + LEFT_OUT.format(name=one_line(scrub(name))) for name in left),
             "    provider: " + _yaml_string({"id": grader, "config": kept} if kept else grader),
             "  assert:",
             "    - type: " + _yaml_string(kind[0]),
             *(["      metric: " + _yaml_string(kind[1])] if kind[1] else []),
             "      value: " + _yaml_string(rule) + RULE_NOTE]
    return "\n".join(lines) + "\n"


def _line_of(path: Path, key: str) -> int | None:
    """The line (from 1) of the first `key:` in the file, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return next((n for n, line in enumerate(text.splitlines(), 1)
                 if line.lstrip(" -").startswith(f"{key}:")), None)


def promptfoo_regrade(ws: Workspace) -> Path | None:
    """fix/regrade.yaml for promptfoo, written when there is none (a file the person changed
    stays as it is). The path, or None when it can't be had: another eval tool, no one rule,
    a grader or rule not read from the results, a file that can't be written. Writes only
    inside .judgekeeper/."""
    try:
        data = ws.cached_data()
    except (OSError, ValueError, AttributeError):
        return None
    if data.get("tool") != "promptfoo":
        return None
    path = _folder(ws) / REGRADE_FILE
    try:
        marks._refuse_links(path)
        if not path.is_file():
            text = _regrade_yaml(ws, data)
            if text is None:
                return None
            make_private(path.parent)
            write_replacing(path, text, newline="")
    except OSError:
        return None
    return path if _line_of(path, "value") else None


def regrade_steps(ws: Workspace, command: str, what: str = "rule",
                  away: bool = False) -> str | None:
    """The three steps that grade the marked answers again with promptfoo, `what` ("rule" or
    "grader") changed in regrade.yaml first, then `command` run on the new results (`away`:
    in the project folder, given from elsewhere). None when there is no regrade.yaml to
    point at (today's text stays)."""
    path = promptfoo_regrade(ws)
    line = path and _line_of(path, "value" if what == "rule" else "provider")
    if not line:
        return None
    shown = f"{shown_folder(ws)}/{FOLDER}"
    new = quote_arg(f"{shown}/{NEW_JSON}")
    n = _answer_rows(ws)
    calls = (f" It calls your LLM-as-a-judge's model {n} times, once for each marked answer, "
             "with your own API key." if n > 1 else " It calls your LLM-as-a-judge's model "
             "once, with your own API key." if n else "")
    return REGRADE_STEPS.format(what=what, file=_file(ws, REGRADE_FILE), line=line, calls=calls,
                                config=quote_arg(f"{shown}/{REGRADE_FILE}"), new=new,
                                where=", in your project folder" if away else "",
                                after=quote_arg(f"{ws.dir.name}/{FOLDER}/{NEW_JSON}") if away
                                else new, command=command)


def _answer_rows(ws: Workspace) -> int:
    """How many answers marked-answers.csv holds (0 when it can't be read): the model calls a
    regrade of it makes."""
    try:
        with (_folder(ws) / ANSWERS).open(encoding="utf-8", newline="") as f:
            return max(sum(1 for _ in csv.reader(f)) - 1, 0)
    except (OSError, UnicodeDecodeError, csv.Error):
        return 0


def not_a_column(ws: Workspace) -> list[str]:
    """One line per variable the rule uses that marked-answers.csv has no column for."""
    try:
        rule = ws.cached_data().get("rule")
    except (OSError, ValueError, AttributeError):
        return []
    names = dict.fromkeys(re.findall(r"\{\{\s*([A-Za-z_]\w*)", rule if isinstance(rule, str)
                                     else ""))
    return [NOT_A_COLUMN.format(name=n, answers=ANSWERS) for n in names
            if n not in ANSWER_COLUMNS]


def regrade_line(tool: str | None, run: str = f"run `judgekeeper fix {NEW_RECORDS}`",
                 file: str | None = None, columns=TABLE_COLUMNS) -> str:
    """How to grade the marked answers again with the person's own eval tool (`run`: the
    step that gives `fix` the new records, Talk.run); for a format of its own, `file` is the
    results file read at the start; for a table, `columns` are its question, answer and
    grade columns (table_columns)."""
    if tool == "records":
        return RECORD_AGAIN.format(run=run)
    if tool == "mapped" and file:
        return SAME_SHAPE.format(file=file)
    if tool == "table":
        return f"{OWN} {TABLE.format(names=', '.join(f'`{c}`' for c in columns))}"
    return REGRADE.get(tool or "", OWN)


def table_columns(ws: Workspace) -> tuple[str, ...]:
    """The first results file's question, answer and grade columns as written in it, or
    TABLE_COLUMNS when it can't be read."""
    from judgekeeper.table import column_name, columns

    file = _first_file(ws)
    names = columns(Path(ws.root) / file) if file else []
    known = {}
    for name in names:
        known.setdefault(column_name(name), name)
    grade = next((known[g] for g in GRADE_COLUMNS if g in known), None)
    if "input" in known and "output" in known and grade:
        return known["input"], known["output"], grade
    return TABLE_COLUMNS


def _first_file(ws: Workspace) -> str | None:
    """The results file step 1 read, as start.json keeps it, or None."""
    try:
        files = ws.data().get("results_files") or []
    except (OSError, ValueError, AttributeError):
        return None
    return files[0] if files and isinstance(files[0], str) else None


NEW_LOG = "new.eval"
# What is not known stays a placeholder (inspect_score)
INSPECT_SCORE = "inspect score {log} --scorer {scorer}{rule} --action overwrite"
_SCORER = re.compile(r"[A-Za-z_][\w/-]*")  # a name `--scorer` takes: a function, or pkg/name
INSPECT_OWN = ("model_graded_qa", "inspect_ai/model_graded_qa")
# The new rule, by the option the log set it in: model_graded_qa reads a template from a file
NEW_RULE = {"instructions": "<new rule>", "template": "<file with the new rule>"}
NOW_RULE = {"instructions": "<your rule>", "template": "<file with your rule>"}  # check
NOT_IN_S = ("Put your rule in place of `<your rule>`. A rule with a comma, or a colon followed "
            "by a space, can't go in `-S`. Grade the log with Inspect's score() in Python "
            "then, as " + EVAL_TOOLS + " shows.")
# A scorer of the person's own may take its template as text, not a file
OWN_TEMPLATE = ("<new rule, as your scorer takes it>", "<your rule, as your scorer takes it>")


def _marked_log(ws: Workspace) -> tuple[str | None, str]:
    """(the log the marks test now, from the project folder, or None when it is not there;
    the folder new_log puts the regraded one in). start.json keeps it from the project, or
    from Inspect's log folder."""
    import os

    try:
        files = ws.data().get("results_files") or []
    except (OSError, ValueError):
        files = []
    root = Path(ws.root)
    logs = Path(os.environ.get("INSPECT_LOG_DIR") or "logs")  # Inspect AI's log folder
    bases = [Path("."), *([logs] if not logs.is_absolute() and ".." not in logs.parts else [])]
    if not files or not isinstance(files[0], str):
        return None, "."
    there = next(((base / files[0]).as_posix() for base in bases
                  if (root / base / files[0]).is_file()), None)
    return there, Path(there).parent.as_posix() if there else Path(files[0]).parent.as_posix()


def new_log(ws: Workspace) -> str:
    """Where the regraded Inspect log goes: next to the marked log, so that `check` finds it
    with the others rather than in a second folder of logs."""
    folder = _marked_log(ws)[1]
    return NEW_LOG if folder == "." else f"{folder}/{NEW_LOG}"


def inspect_score(ws: Workspace, out: str | None = None, rule: bool = True,
                  now: dict | None = None) -> str:
    """INSPECT_SCORE with the marked log and its scorer, so it runs as it is copied: the
    scorer is the LLM-as-a-judge's metric (`scorer.key` for a dict score). A placeholder
    stays only for what is not known (a log gone, a name `--scorer` can't take, the new
    rule). `out`: the new log it writes (`--output-file`, quoted already), in the one
    command. `rule`: the new rule goes in with `-S`, in the option the log set it in, or
    `instructions` for Inspect's own scorer; without it, the scorer grades by its stock rule.
    `now` (check): the LLM-as-a-judge as it is now (now_options): its rule when `-S` can take
    it, its grader model, its grader role; else the marked log's grader model."""
    log = _marked_log(ws)[0]
    try:
        data = ws.data()
        metric, field = data.get("metric"), data.get("rule_field")
    except (OSError, ValueError, AttributeError):
        metric = field = None
    name = str(metric).split(".", 1)[0] if isinstance(metric, str) else ""
    scorer = name if _SCORER.fullmatch(name) else "<name>"
    if field not in NEW_RULE:
        field = "instructions" if scorer in INSPECT_OWN else None
    rules = NEW_RULE if now is None else NOW_RULE
    value = rules.get(field) if field != "template" or scorer in INSPECT_OWN else (
        OWN_TEMPLATE[now is not None])  # only Inspect's own scorers read a template file
    if now is not None and field == "instructions" and fits_s(now.get("rule")):
        value = now["rule"]
    option = f" -S {field}={quote_arg(value)}" if rule and field else ""
    model = (now or {}).get("model") or (
        _scorer_model(ws, log, scorer) if log and scorer != "<name>" else None)
    option += f" -S model={quote_arg(model)}" if model else ""
    role = (now or {}).get("role")
    option += f" --model-role grader={quote_arg(role)}" if role else ""
    command = INSPECT_SCORE.format(log=quote_arg(log) if log else "<log>", scorer=scorer,
                                   rule=option)
    return f"{command} --output-file {out}" if out else command


def fits_s(rule) -> bool:
    """Whether `-S` takes `rule` whole: Inspect reads -S values as YAML and splits text at
    commas, so no comma, no colon, no "#", on one line, not starting with a YAML sign."""
    return (isinstance(rule, str) and 0 < len(rule) <= 500 and rule.isprintable()
            and not re.search(r"[,:#]", rule) and not re.match(r"[\s\[\]{}&*!|>'\"%@`-]", rule))


def now_options(ws: Workspace, found) -> dict:
    """For `check`: the LLM-as-a-judge as the newest results hold it, for inspect_score: its
    rule, the model its scorer was given, and its grader role when the marked log's differs
    (`inspect score` keeps the marked log's roles)."""
    from judgekeeper.readers.inspect_logs import _model, eval_header

    out: dict = {"rule": getattr(found, "rule", None)}
    results = getattr(found, "results", None) or []
    if not results:
        return out
    try:
        metric = ws.data().get("metric")
    except (OSError, ValueError, AttributeError):
        metric = None
    name = str(metric).split(".", 1)[0] if isinstance(metric, str) else ""
    if _SCORER.fullmatch(name):
        out["model"] = _scorer_model(ws, str(results[0].path), name)
    role = _model((eval_header(results[0].path).get("model_roles") or {}).get("grader"))[0]
    marked = _marked_log(ws)[0]
    was = _model((eval_header(Path(ws.root) / marked).get("model_roles") or {}).get(
        "grader"))[0] if marked else None
    if isinstance(role, str) and role.isprintable() and "+" not in role and role != was:
        out["role"] = role
    return out


def scorer_model(ws: Workspace) -> str | None:
    """The grader model the marked log's scorer was given as its `model` option, or None."""
    log = _marked_log(ws)[0]
    try:
        metric = ws.data().get("metric")
    except (OSError, ValueError, AttributeError):
        metric = None
    name = str(metric).split(".", 1)[0] if isinstance(metric, str) else ""
    return _scorer_model(ws, log, name) if log and _SCORER.fullmatch(name) else None


def _scorer_model(ws: Workspace, log: str, scorer: str) -> str | None:
    """The model `scorer` was given as its `model` option in the log (model_graded_qa(model=
    ...)). `inspect score` does not keep it: without `-S model=`, the task's own model grades.
    A grader given as a model role needs nothing: `inspect score` keeps the log's roles."""
    from judgekeeper.readers.inspect_logs import _model, eval_header

    spec = eval_header(Path(ws.root) / log)
    for s in spec.get("scorers") or []:
        if isinstance(s, dict) and s.get("name") in (scorer, scorer.rsplit("/", 1)[-1]):
            model = _model((s.get("options") or {}).get("model"))[0]
            if isinstance(model, str) and model.strip() and model.isprintable() \
                    and "+" not in model:
                return model.strip()
    return None


def _next_regrade(talk: Talk, ws: Workspace, tool: str | None, first: str | None = None) -> None:
    """The per-tool line and the Next: line after marked-answers.csv is written. `first`: a
    step said before the new rule's (a better pass mark), which then comes after "Or"."""
    def nxt(text: str) -> None:
        talk.next(f"{first} Or {text}" if first else text)
    talk.say()
    steps = (regrade_steps(ws, talk.program("fix"), away=talk.away()) if tool == "promptfoo"
             else None)
    talk.para(steps or regrade_line(tool, talk.run(NEW_RECORDS), _first_file(ws),
                                    table_columns(ws) if tool == "table" else TABLE_COLUMNS))
    if steps:  # a ready config: the steps above are the whole way
        for line in not_a_column(ws):
            talk.para(line)
        nxt(FOLLOW_STEPS)
        return
    if tool == "inspect":  # the log itself is graded again
        log = quote_arg(new_log(ws))
        command = inspect_score(ws, log)
        spot = next((v for v in (*NEW_RULE.values(), OWN_TEMPLATE[0]) if v in command), None)
        what = "a file with your new rule" if spot == NEW_RULE["template"] else "your new rule"
        nxt(f"run `{command}` with {what} in place of `{spot}`, then {talk.run(log)}."
            if spot else f"change your scorer's rule, run `{command}` and then {talk.run(log)}.")
        return
    store = mlflow_store(ws, here=not talk.away()) if tool == "mlflow" else None
    if store:  # a new run in the same store
        nxt(f"change your scorer's rule, run it with `mlflow.genai.evaluate()` on the "
            f"same traces, then {talk.run(store)}. It reads the newest run.")
        return
    if tool in ("records", "mapped"):  # graded with their own code, as said above
        new = NEW_RECORDS if tool == "records" else NEW_RESULTS
        nxt(f"change your LLM-as-a-judge's rule, grade the answers in "
            f"{_file(ws, ANSWERS)} again as said above, then {talk.run(new)}.")
        return
    nxt(f"change your LLM-as-a-judge's rule in your eval tool, grade the answers in "
        f"{_file(ws, ANSWERS)} again, save the results, then {talk.run(NEW_RESULTS)}.")


def first_run(talk: Talk, ws: Workspace, m: Marks, split: Split) -> int:
    """Where the judge goes wrong on the seen marks, mistakes.md, the pass mark,
    where the rule lives, the hidden marks, marked-answers.csv, and what to do next."""
    data = m.data
    seen_rows = [m.row(i) for i in split.seen]
    wrong = mistakes(seen_rows)
    pm = data.get("pass_mark")
    mark = pm["mark"] if pm and pm.get("follows") else None
    rule = data.get("rule") if data.get("one_rule", True) else None
    if not wrong:
        talk.para("Your LLM-as-a-judge agrees with every mark you can see, so there is nothing to "
                  "fix.")
        if not split.hidden:
            talk.next("nothing to do. When you change your LLM-as-a-judge or update your eval "
                      f"tool, run `{talk.command('check')}`.")
            return EXIT_OK
        _write_mistakes(ws, rule, seen_rows, mark, m.worse_from, marked_rule(data))  # both fit the set kept aside
        n = write_answers(ws, m)
        talk.say()
        talk.para(_answers_line(ws, split, n))
        if data.get("tool") == "inspect":  # the log itself is scored again
            log = quote_arg(new_log(ws))
            talk.next(f"nothing to fix. To test another rule anyway, score your log again "
                      f"with it: run `{inspect_score(ws, log)}` and then "
                      f"{talk.run(log)}.")
            return EXIT_OK
        talk.next(f"nothing to fix. To test another rule anyway, grade the answers in "
                  f"{_file(ws, ANSWERS)} again with it, then {talk.run(NEW_RESULTS)}.")
        return EXIT_OK
    counted = patterns(seen_rows, mark, aside=len(split.hidden))  # its first names the half
    found = [[line] for line in reasons.clue_lines(wrong)] + counted
    if found:
        talk.say(WHERE_WRONG)
        for p in found:
            for sentence in p:
                talk.para(sentence, indent="  ")
        talk.say()
    made = len(split.tests)
    tested = test_pass_mark(m, split)
    fresh = len(split.tests) > made  # the test made now: its line is said once
    save_split(ws, split)
    _write_mistakes(ws, rule, seen_rows, mark, m.worse_from, marked_rule(data))
    talk.para(_saved_line(ws, len(wrong)))
    talk.say()
    if write_suggestions(ws, seen_rows):
        talk.para(f"Suggestions from your reasons are in {_file(ws, SUGGESTIONS)}. Copy the ones "
                  "you agree with into your rule where your eval keeps it.")
        talk.say()
    line = tested and (pass_mark_line(ws, pm, tested) or (fresh and tried_line(tested)))
    held = held_line(m, split)
    if held:  # the best fit, held back: why, and to keep the pass mark unless one follows
        talk.para(held + ("" if line else KEEP.format(old=f"{pm['mark']:g}")))
        talk.say()
    if line:
        talk.para(line)
        talk.say()
    tool = data.get("tool")
    if rule:
        talk.para(f"{_rule_place(ws, rule, tool or '', data)}:")
        talk.say(f"  {_rule_quote(rule)}")
        talk.say()
    n = write_answers(ws, m)
    talk.para(_answers_line(ws, split, n, said=bool(counted and split.hidden)))
    better = tested and pass_mark_command(ws, pm, tested)
    _next_regrade(talk, ws, tool, f"run `{better}` to switch to the better pass mark."
                  if better else None)
    return EXIT_OK


def _write_mistakes(ws: Workspace, rule: str | None, rows: list[dict],
                    mark: float | None, worse_from: str | None = None,
                    marked: str | None = None) -> None:
    path = _folder(ws) / MISTAKES
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, mistakes_md(rule, rows, mark, worse_from, marked))


def _answers_line(ws: Workspace, split: Split, n: int, said: bool = False) -> str:
    """How many marks are kept aside (unless `said` above), and that marked-answers.csv holds
    all `n`."""
    k = len(split.hidden)
    aside = f"{k} of your marks {'is' if k == 1 else 'are'} kept aside to test your new rule " \
        "fairly. " if k and not said else ""
    return (f"{aside}{_file(ws, ANSWERS)} holds all {plural(n, 'marked answer')}, questions and "
            "answers only, so you can't tell which are kept aside.")


# The test of a new rule ------------------------------------------------------------------

def next_test(split: Split) -> int:
    """Which test on this set of hidden marks the next one is: every test counts, whatever
    its verdict, so each is stricter."""
    return len(split.tests) + 1


def _shown_path(path: Path) -> str:
    """A results file from here (textio.line_path), a link they can click in a terminal."""
    return link(path, line_path(path))


def _better_needs(n: int, k: int) -> int:
    """About how many fixed mistakes, none broken, a test `k` on `n` marks needs for
    "better" (targets.fix_verdict)."""
    return next((f for f in range(1, max(n, 1) + 1)
                 if targets.fix_verdict(f, 0, max(n, f), test=k).kind == "better"), n)


def _given(talk: Talk, state, m: Marks, path: Path):
    """The new results in `path`, read as step 1 reads results (check.read_given); None, said
    with what to give instead, when they can't be read or are from another tool."""
    from judgekeeper.check import NAMED_AGAIN, OtherName, read_given

    found, problem = read_given(state, path)
    if found is None:
        talk.para(problem)
        tool = m.data.get("tool")
        store = mlflow_store(state.ws)
        if tool == "inspect":  # the log, scored again
            talk.next(_regrade_same(talk, state.ws))
        elif isinstance(problem, OtherName) and store:  # a new run in the store, as check says
            talk.next(NAMED_AGAIN.format(name=repr(scrub(m.data.get("metric") or "")),
                                         command=talk.command(), store=store))
        elif isinstance(problem, OtherName):
            talk.next(f"grade {_file(state.ws, ANSWERS)} again with your new rule under the "
                      f"name {scrub(m.data.get('metric') or '')!r}, the one your marks test, "
                      f"then run `{talk.command()} {runnable(str(path), labels=False)}`.")
        elif tool == "records":
            again = RECORD_AGAIN.format(run=talk.run(NEW_RECORDS))
            talk.next(again[0].lower() + again[1:])
        else:
            talk.next(f"give `{talk.command()}` the results of grading "
                      f"{_file(state.ws, ANSWERS)} again with your new rule, from "
                      f"{_tool_name(tool)}.")
    return found


def test_results(talk: Talk, state, m: Marks, split: Split, path: Path) -> int:
    """The test of a new rule: the new results in `path`, read as step 1 reads results, on the
    hidden marks: how the old and the new grades agree with the person's marks, and the
    verdict from the math. A hidden answer not in the file is counted, said once and left out."""
    from judgekeeper import judge_setup
    from judgekeeper.check import (
        NEXT_UNKNOWN,
        lookup,
        mixed_line,
        no_decision,
        no_decision_why,
        repeats_line,
        unknown_grades,
    )

    ws = state.ws
    found = _given(talk, state, m, path)
    if found is None:
        return EXIT_USAGE
    unknown = unknown_grades(found, path)
    if unknown:
        talk.para(unknown)
        talk.next(NEXT_UNKNOWN.format(command=f"{talk.command()} {runnable(str(path), labels=False)}"))
        return EXIT_NEEDS_YOU
    setup = judge_setup.of(found)
    setup_hash = judge_setup.hash_of(setup)
    matched, mixed = lookup(found, {i: m.person[i] for i in split.hidden}, ws)
    new = {i: a.verdict for i, a in matched.items()}
    ids = [i for i in split.hidden if i in new]
    lack = [i for i in split.hidden if i not in new]
    blank = no_decision(found, lack, ws) if lack else []  # there, with no decision
    gone = len(lack) - len(blank)
    key = test_key(setup, setup_hash, {**new, **dict.fromkeys(blank)}, ids + blank)
    talk.say(f"New results: {_shown_path(path)}")
    talk.say()
    if not ids and not blank:
        talk.para(f"None of the {len(split.hidden)} answers kept aside is in this file. "
                  "judgekeeper matches an answer only when the question and the answer text are "
                  "exactly the same.")
        _rewrite_lacking(talk, ws, m, list(split.hidden))
        _next_regrade(talk, ws, m.data.get("tool"))
        return EXIT_NEEDS_YOU
    old = m.judge
    earlier = [i for i in ids if i in m.earlier]
    took = bool(earlier) and bool(setup.get("rule_hash")) and _same_rule(ws, setup, setup_hash)
    if took:
        from judgekeeper.check import take_grades  # the judge as it is now graded them

        take_grades(ws, found, {i: matched[i] for i in earlier})
        old = {**old, **{i: new[i] for i in earlier}}
        talk.para(took_line(len(earlier)))
        talk.say()
    left = [i for i in blank if i in m.earlier] + ([] if took else earlier)
    if left:  # never compared with another judge's grade
        k = len(left)
        talk.para(EARLIER.format(k=k, n=len(split.hidden), have=_have(k),
                                 them="it" if k == 1 else "them"))
        talk.say()
        ids = [i for i in ids if i not in left]
        blank = [i for i in blank if i not in left]
        if not ids and not blank:
            talk.next(NEXT_EARLIER.format(answers=_file(ws, ANSWERS),
                                          run=talk.run("<those results>")))
            return EXIT_NEEDS_YOU
    # nothing changed: nothing to tell apart. An answer with no grade is a change: counted
    if not blank and ids and all(new[i] == old.get(i) for i in ids):
        if not took:  # else said: the grades of the judge as it is now
            talk.para(SAME_GRADES if _same_rule(ws, setup, setup_hash) else
                      UNCHANGED.format(n=len(ids)))
        _next_regrade(talk, ws, m.data.get("tool"))
        return EXIT_NEEDS_YOU
    if blank and not ids and not gone:  # not one grade: say so, never the same Next as before
        talk.para(NO_GRADES.format(n=len(blank)))
        talk.para(NO_GRADES_INSPECT if m.data.get("tool") == "inspect" else NO_GRADES_OTHER)
        talk.next(_no_grades_next(talk, ws))
        return EXIT_NEEDS_YOU
    if gone or 2 * len(blank) > len(ids) + len(blank):  # the rule may fail exactly on those;
        k = len(lack) if gone else len(blank)  # before a replay: this file can't test it
        error = no_decision_why(found, lack, ws)  # " (such as an error)" only for an error
        talk.para(MISSING.format(k=k, n=len(split.hidden), have=_have(k),
                                 why=_missing_why(gone, len(lack) - gone, error)) if gone else
                  MOSTLY_BLANK.format(k=k, n=len(ids) + k, have=_have(k), why=error))
        _rewrite_lacking(talk, ws, m, lack)
        talk.next(_regrade_same(talk, ws))
        return EXIT_NEEDS_YOU
    before = next((t for t in split.tests if t.get("kind") == "rule"
                   and (t.get("key") or t.get("setup_hash")) == key
                   and t.get("hidden") == len(split.hidden)
                   and t.get("n") == len(ids) + len(blank)), None)
    if before is not None:
        return tested_before(talk, ws, m, before, path, len(blank),
                             {**{i: new.get(i) for i in ids}, **dict.fromkeys(blank)})
    for line in filter(None, (mixed and mixed_line(len(mixed)), repeats_line(found))):
        talk.para(line)
        talk.say()
    if blank:  # no grade is never the person's mark: a mistake, wherever it falls
        new = {**new, **dict.fromkeys(blank)}
        ids += blank
        k = len(blank)
        talk.para(COUNTED.format(k=k, n=len(ids), them="it as its mistake" if k == 1 else
                                 "them as its mistakes"))
        talk.say()
    strata = by_stratum(m, ids, old, new)
    fixed, broke = sum(s[1] for s in strata), sum(s[2] for s in strata)
    v = targets.fix_verdict(fixed, broke, len(ids), test=next_test(split), strata=strata)
    talk.say(f"Your LLM-as-a-judge, tested on the {len(ids)} marks kept aside:")
    for name, grades in (("Old", old), ("New", new)):
        talk.say(f"  {name} rule:")
        for side, mark in (("Pass", "pass"), ("Fail", "fail")):
            of = [i for i in ids if m.person[i] == mark]
            agreed = sum(grades[i] == mark for i in of)
            talk.say(f"    When you say {side}: agrees on {agreed} of {len(of)}")
    talk.para(went_line(fixed, broke), indent="  ")
    talk.say()
    talk.para(RESULT[shown_kind(v.kind, fixed, broke)])
    k = next_test(split)
    _keep(ws, split, found, setup, setup_hash, key, v, kept_path(path, ws.root),
          {i: new.get(i) for i in ids})
    wrong = sum(old[i] != m.person[i] for i in ids)
    if v.kind in ("leans better", "same") and wrong:  # never for a rule that leans worse
        talk.para(CANT_TELL.format(n=wrong, are="is" if wrong == 1 else "are",
                                   better=_better_needs(len(ids), k)))
    if len(split.rules()) >= MAX_RULES and v.kind not in ("better", "safe"):
        talk.say()
        talk.para(f"You have tested {plural(len(split.rules()), 'rule')} on these marks kept "
                  f"aside. Your next marks become a new set kept aside. "
                  f"{more_marks_line(ws)}")
    talk.next(_after_step(talk, ws, m, v.kind, path))
    return EXIT_OK


def _have(k: int) -> str:
    return "has" if k == 1 else "have"


def _missing_why(gone: int, errors: int, error: str = "") -> str:
    """Why answers kept aside have no grade: not in the file, or there with no decision
    (`error`: " (such as an error)" when one of them was an error)."""
    parts = ([f"{gone} {'is' if gone == 1 else 'are'} not in the file"] if gone else []) + (
        [f"{errors} {_have(errors)} no decision from your LLM-as-a-judge{error}"]
        if errors else [])
    return f": {' and '.join(parts)}" if parts else ""


def _same_rule(ws: Workspace, setup: dict, setup_hash: str) -> bool:
    """Whether the new results come from the LLM-as-a-judge the marks were made with (or from
    results that hold no rule, which can't tell one rule from another)."""
    from judgekeeper import judge_setup

    saved = judge_setup.read(ws) or {}
    return not setup.get("rule_hash") or saved.get("setup_hash") == setup_hash


def _copy_rule(ws: Workspace, data: dict) -> str | None:
    """With promptfoo, while the config still holds the rule the marks were made with: "copy
    your new rule from regrade.yaml (line N) into <config> (line N)", each file and line
    named when known. Else None: the new rule is where the person changed it."""
    rule = data.get("rule")
    if data.get("tool") != "promptfoo" or not isinstance(rule, str) or not data.get(
            "one_rule", True):
        return None
    first = start_fix_rule.rule_config(ws.root, "promptfoo", data)
    where = start_fix_rule.found_rule(ws.root, rule, "promptfoo", first=first)
    if where is None:
        return None
    regrade = _folder(ws) / REGRADE_FILE
    line = _line_of(regrade, "value") if regrade.is_file() else None
    source = f" from {_file(ws, REGRADE_FILE)} (line {line})" if line else ""
    if where[0] != first:  # found by a search of the person's code: a guess, not named
        home = start_fix_rule.rule_home(ws.root, "promptfoo", data)
        return (f"copy your new rule{source} into {home}" +
                ("" if first else " in your promptfoo config"))
    return (f"copy your new rule{source} into {link(ws.root / where[0], where[0])} "
            f"(line {where[1]})")


def _after_step(talk: Talk, ws: Workspace, m: Marks, kind: str, path: Path) -> str:
    """The next step after a test of the new results `path` (without "Next: "). They grade
    every marked answer, so `check` re-checks the new rule on them: running the eval again
    would make new answers, which judgekeeper can't compare."""
    if kind in ("better", "safe"):
        check = (f"`{talk.command('check')} {runnable(str(path), labels=False)}` to re-check it "
                 "on all your marks.")
        copy = _copy_rule(ws, m.data)
        return f"{copy}, then run {check}" if copy else f"keep your new rule, then run {check}"
    if kind == "worse":
        kept = f" ({_file(ws, MISTAKES)} keeps a copy)" if m.data.get("rule") else ""
        return (f"copy your old rule back into your eval tool{kept}, or try another rule and "
                f"run `{talk.command()} {_new_results(ws)}` again.")
    if every_marked(ws):  # none left to mark: more marks would need more questions
        return CANT_SETTLE.format(command=f"{talk.command()} {_new_results(ws)}")
    from judgekeeper.check import mark_here

    return next_marks(ws, f"mark more answers with `{mark_here(ws)}`, then run "
                          f"`{talk.command()}` to write the marked answers to grade again.")


def tested_before(talk: Talk, ws: Workspace, m: Marks, test: dict, path: Path,
                  blank: int = 0, grades: dict | None = None) -> int:
    """This LLM-as-a-judge was tested on these marks kept aside: its saved result, never a
    new test, the file and day it came from, how many this file leaves ungraded (`blank`),
    and the next step that result gave. `grades`, this file's on the answers kept aside, are
    compared with the test's own (kept since 1.1.0) to say whether they differ."""
    from judgekeeper.check import _day

    day = _day(test.get("time"))
    talk.para(f"You tested this LLM-as-a-judge before{f' ({day})' if day else ''}, on the "
              f"{test.get('n')} marks kept aside. "
              f"{went_line(int(test.get('fixed') or 0), int(test.get('broke') or 0))}")
    talk.say()
    talk.para(RESULT.get(shown_kind(str(test.get("verdict")), int(test.get("fixed") or 0),
                                    int(test.get("broke") or 0)), ""))
    kept = test.get("file") if isinstance(test.get("file"), str) else None
    file = line_path(kept_at(kept, ws.root)) if kept else None
    source = (f"the result above is from {file or 'an earlier file'}"
              f"{f' on {day}' if day else ''}.")
    if blank:
        talk.para(f"This file leaves {blank} of the {test.get('n')} ungraded. "
                  f"{source[0].upper() + source[1:]}")
    elif kept and Path(kept_at(kept, ws.root)).resolve() != Path(path).resolve():
        # another file: say which one is given now
        when = f" ({day})" if day else ""
        if not test.get("rule_hash"):  # told apart by its grades: the same ones
            talk.para(f"{path.name} has the same grades as {file}{when}, so the result above is "
                      "the same.")
        else:
            talk.para(_same_rule_line(path.name, file, when, test, grades))
    else:
        talk.para(source[0].upper() + source[1:])
    talk.next(_after_step(talk, ws, m, str(test.get("verdict")), path))
    return EXIT_OK


def _same_rule_line(name: str, file: str, when: str, test: dict, grades: dict | None) -> str:
    """A file with the same rule and model as the one `test` came from: one LLM-as-a-judge to
    judgekeeper, so its saved result; "the same" only when the grades on the answers kept
    aside are too, else how many differ (unknown for a test before 1.1.0)."""
    head = (f"{name} has the same rule and model as {file}{when}, so judgekeeper treats them "
            "as one LLM-as-a-judge")
    kept = test.get("grades")
    if not isinstance(kept, dict) or grades is None:
        return f"{head}. The result above is from {file}."
    differ = sum(kept.get(i) != g for i, g in grades.items())
    if not differ:
        return f"{head}. The result above is the same."
    return (f"{head} and shows the result above, from {file}. Its grades differ on "
            f"{differ} of the {len(grades)} answers kept aside. {TEST_AS_NEW}")


def test_key(setup: dict, setup_hash: str, new: dict, ids: list[str]) -> str:
    """What tells one tested LLM-as-a-judge from another: its setup when the results hold its
    rule; else (a table, say) the setup and its grades on the marks kept aside."""
    if setup.get("rule_hash"):
        return setup_hash
    grades = json.dumps(sorted((i, new[i]) for i in ids)).encode("utf-8")
    return f"{setup_hash}/{hashlib.sha256(grades).hexdigest()[:16]}"


def _tool_name(tool: str | None) -> str:
    return find.NAMES.get(tool or "", tool or "your eval tool")


def _keep(ws: Workspace, split: Split, found, setup: dict, setup_hash: str, key: str,
          v, file: str | None = None, grades: dict | None = None) -> None:
    """The tested rule in rules/<hash>.txt (scrubbed) when the results hold one, the test in
    split.json (with the setup the marks tested then, for _adopted) and a history line: the
    setup's and rule's hashes, the counts and the verdict, never answer text or ids."""
    from judgekeeper import judge_setup

    saved = judge_setup.read(ws) or {}
    was = {"setup_hash": saved.get("setup_hash"),
           "rule_hash": (saved.get("setup") or {}).get("rule_hash")}
    h = setup.get("rule_hash")
    if h and found.rule:
        path = ws.dir / "rules" / f"{h.removeprefix('sha256:')}.txt"
        marks._refuse_links(path)
        make_private(path.parent)
        write_replacing(path, scrub(found.rule))
    test = {"kind": "rule", "time": utc_now(), "rule_hash": h, "setup_hash": setup_hash,
            "key": key, "from": was, "n": v.n, "hidden": len(split.hidden), "fixed": v.fixed, "broke": v.broke,
            "verdict": v.kind, "test": len(split.tests) + 1, "strata": [list(s) for s in v.strata],
            **({"file": scrub(file)} if file else {}),  # split.json only: history has no paths
            **({"grades": grades} if grades is not None else {})}  # nor grades
    split.tests.append(test)
    save_split(ws, split)
    marks.append(ws.history_jsonl, {"time": test["time"], "kind": "fix", "rule_hash": h,
                                    "setup_hash": setup_hash, "hidden": v.n, "fixed": v.fixed,
                                    "broke": v.broke, "verdict": v.kind, "test": test["test"],
                                    "set": split.set})
    from judgekeeper.start_label import write_report

    try:
        write_report(ws)
    except OSError:
        pass  # the test is saved; the report catches up with the next result


__all__ = ["TASK", "Marks", "Split", "make_split", "mistakes", "mistakes_md", "pattern_lines",
           "patterns", "read_split", "run"]
