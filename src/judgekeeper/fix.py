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
from judgekeeper.redact import one_line, scrub
from judgekeeper.start_label import Workspace, next_marks, shown_folder
from judgekeeper.table import guard_cell
from judgekeeper.textio import (
    held_lines,
    jsonl_lines,
    loads,
    make_private,
    old_hook,
    plural,
    program,
    quote_arg,
    read_cached,
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
CLEAR_LINE = (f"Mark about {CLEAR} more answers for a clear answer (at least {FRESH}; with fewer "
              f"than about {CLEAR}, the result will often be \"can't tell yet\").")
RULE_SHOWN = 58  # characters of the rule shown, "…" included
STEP = "Step 4 of 5: Fix"
STEP_TEST = "Step 4 of 5: Fix (testing your new rule)"
RESULT = {
    "better": ("Result: your new rule is better. A difference this large is unlikely to be a "
               "coincidence."),
    "safe": ("Result: safe to try. Not clearly better yet, but unlikely to be more than 10 "
             "points worse."),
    "leans better": ("Result: can't tell yet. That leans toward better, but a split this small "
                     "could easily be a coincidence."),
    "same": "Result: can't tell yet. The two rules look about the same here.",
    "leans worse": "Result: can't tell yet. That leans toward worse.",
    "worse": "Result: it looks worse.",  # only past the sign test
}
CANT_TELL = ("Only {n} of your LLM-as-a-judge's mistakes {are} kept aside; 'better' needs about "
             "{better} fixed and none broken. Mark more answers to get a clearer test.")
NEW_RESULTS = "<new results file>"
MISSING = ("Result: can't tell. {k} of the {n} answers kept aside {have} no grade in your new "
           "results{why}. A rule is tested only on all of them: a rule that leaves the hard ones "
           "ungraded would look better than it is.")
MOSTLY_BLANK = ("Result: can't tell. {k} of the {n} answers kept aside {have} no decision from "
                "your new rule (such as an error): more than half, too many to test it on.")
COUNTED = ("{k} of the {n} answers kept aside got no grade from your new rule; judgekeeper "
           "counted {them}.")
REGRADE_SAME = ("grade every answer in {answers} again with your new rule, then run "
                f"`{{command}} {NEW_RESULTS}`.")
REWROTE = ("judgekeeper wrote {answers} again: it now holds every answer you marked, with the "
           "answers kept aside your new results lack.")
SAME_GRADES = ("These are the same grades as when you marked: give the results from after your "
               "change.")
EARLIER = ("{k} of the {n} answers kept aside {have} no grade from your LLM-as-a-judge as it "
           "is now, only from one before it, so judgekeeper leaves {them} out.")
TOOK = ("These are your LLM-as-a-judge's grades as it is now on {k} answers kept aside it had "
        "not graded yet: judgekeeper keeps them as its grades.")
NEXT_EARLIER = ("grade the answers in {answers} again with your LLM-as-a-judge as it is now, "
                "run `{command} <those results>` so judgekeeper has its grades, then test your "
                "new rule.")
UNCHANGED = ("Your new rule gives each of the {n} answers kept aside the grade the old one "
             "gave, so it changes nothing there to test.")
# How to grade the same answers again, per eval tool (an own file or record(): OWN)
REGRADE = {
    "promptfoo": (f"promptfoo: use {ANSWERS} as your tests (`tests: file://...`) with "
                  "`prompts: ['{{answer}}']`, the `echo` provider, your grader as "
                  "`defaultTest.options.provider` and the same `metric:` with your new rule; "
                  "the rule's variables are the file's columns, `{{question}}` and "
                  "`{{answer}}`. Save with `-o`. judgekeeper's docs/eval-tools.md shows the "
                  "whole config."),
    "inspect": ("Inspect AI: grade your log again with the new rule, no new answers needed. "
                "`--scorer` takes the scorer's name (`model_graded_qa` for Inspect's own); "
                "give the options you set before again with `-S`. `-S instructions=` takes a "
                "rule with no comma (Inspect cuts `-S` values at commas); else grade it with "
                "Inspect's score() in Python, as judgekeeper's docs/eval-tools.md shows. "
                "`--action overwrite` replaces the old grades in the new log, so your "
                "scorer's name holds the new ones, and `--output-file` writes a new log next "
                "to yours, so yours stays as it was and `judgekeeper check` finds the new "
                "one."),
    "mlflow": ("MLflow: `mlflow.genai.evaluate()` on the existing traces with the new scorer, "
               "under the same name."),
    "deepeval": (f"DeepEval: one test case per row of {ANSWERS} (`question` as input, "
                 "`answer` as actual_output, and any field your metric also reads, such as "
                 "expected_output, added back by its question); run your metric with its new "
                 "rule and the same name through `deepeval test run`, which saves a new "
                 "test_run_<date>.json in your results folder."),
}
OWN = f"Grade {ANSWERS} with your own code."
TABLE = ("Save the new grades with the columns of your first file: `question` as its input, "
         "`answer` as its output, and the grade.")

# The patterns: only when strong, from at least FEW mistakes
FEW = 3
NEAR = 0.1  # how close to the pass mark is close
LONG_SIDE = 4  # mistakes on one side the length pattern needs
LONG = 1.5  # how much longer is long
WORDS_SHOWN = 5
WORD_IN = 3  # mistakes a word must be in
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
    "would", "your", "yours", "yourself", "yourselves"))


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
NEXT_DAMAGED = ("put back the {name} judgekeeper wrote, or delete it and run `{command} --new`: "
                "every mark you have counts as seen, and the next {n} you make are kept aside.")


def _ints(t: dict, *keys: str) -> bool:
    return all(type(t.get(k)) is int and t[k] >= 0 for k in keys)


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
    its own. None kept aside, or one never marked: 0."""
    order = {i: n for n, i in enumerate(read_cached(ws.marks, marks.read).last)}
    if not hidden or any(i not in order for i in hidden):
        return 0
    first = min(order[i] for i in hidden)
    return sum(order.get(i, first) < first for i in seen)


def _split_problem(ws: Workspace, d) -> str | None:
    """What is wrong with split.json's data `d`, in a few words; None when it is as
    judgekeeper writes it: two lists of answers judgekeeper has, apart, about half kept aside
    (of the set's own marks, before it is retired: both from history.jsonl, the earlier
    sets' marks no more than marks.jsonl says), and tests whose
    counts fit them."""
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
        if t["kind"] == "rule" and (not _ints(t, "test") or t["test"] < 1 or t.get("verdict") !=
                                    targets.fix_verdict(t["fixed"], t["broke"], t["n"],
                                                        test=t["test"]).kind):
            return "a test in it has a result its counts don't give"
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
    write_replacing(path, json.dumps(split.to_json(), indent=2) + "\n")


def current_split(ws: Workspace, m: Marks, new: bool = False) -> Split:
    """The saved split with marks made since it split the same way; a new one when there is
    none. `new` retires the saved one: a mark once seen is never kept aside again, so only
    marks made after it make the next set."""
    split = read_split(ws)
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


def prepare_split(ws: Workspace) -> None:
    """Set the hidden marks aside when the first result appears (and take in marks made
    since), before any mistake is shown; nothing when there are too few marks."""
    try:
        m = Marks(ws)
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


def patterns(rows: list[dict], mark: float | None = None) -> list[list[str]]:
    """Plain patterns in the judge's mistakes on `rows` ("judge", "final", "output" text,
    "score"), only when strong: each pattern is its sentences. `mark` is the pass mark when
    the judge's grades follow its scores."""
    wrong = mistakes(rows)
    n = len(wrong)
    if n < FEW:
        return []
    out = []
    passes = sum(m["judge"] == "pass" for m in wrong)
    fails = n - passes
    made = f"Your LLM-as-a-judge made {n} mistakes."
    easy = "it said Pass where you said Fail"
    strict = "it said Fail where you said Pass"
    if passes > fails:
        out.append([f"{made} In {passes}, {easy}.", "Its rule may be too easy."])
    elif fails > passes:
        out.append([f"{made} In {fails}, {strict}.", "Its rule may be too strict."])
    else:
        out.append([f"{made} In {passes}, {easy}. In the other {fails}, {strict}."])
    if mark is not None:
        near = sum(m.get("score") is not None and abs(m["score"] - mark) <= NEAR + 1e-9
                   for m in wrong)
        if near * 2 > n:
            out.append([(f"{near} of your LLM-as-a-judge's {n} mistakes sit close to the pass "
                         "mark."), "Moving the pass mark may fix them."])
    for judge, final, name in (("fail", "pass", strict), ("pass", "fail", easy)):
        side = [len(m["output"].split()) for m in wrong if m["judge"] == judge]
        agreed = [len(m["output"].split()) for m in rows
                  if m["judge"] == m["final"] == final]
        if len(side) < LONG_SIDE or len(agreed) < FEW:
            continue
        long, usual = statistics.median(side), statistics.median(agreed)
        if usual > 0 and long >= LONG * usual:
            out.append([(f"Where {name}, the answers are long (about {_about(long)} words, "
                         f"against {_about(usual)}).")])
    agreed = [m for m in rows if m["judge"] == m["final"]]
    if len(agreed) >= FEW:
        in_wrong = Counter(w for m in wrong for w in _words(m["output"]))
        in_agreed = Counter(w for m in agreed for w in _words(m["output"]))
        k = len(agreed)
        strong = []
        for word, a in in_wrong.items():
            b = in_agreed[word]
            odds = (math.log((a + 0.5) / (n - a + 0.5))
                    - math.log((b + 0.5) / (k - b + 0.5)))
            if a >= WORD_IN and odds >= STRONG:
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


def report_section(ws: Workspace) -> dict | None:
    """The result page's disagreements: the mistakes on the marks the person can see, with the
    judge's reason, each text whole (the page folds each row), a many-field question's
    `fields` as the marking page shows them, and the person's reasons on it (`why`:
    reasons.of_line, rule parts only of the rule now); the rule's parts and the person's own
    buttons. Never a hidden mark. None when there is none. A split.json that can't be used
    can't say which marks are kept aside: no mistake and `split_unknown`."""
    try:
        m = Marks(ws)
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
            "own": list(m.own.values())}


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


def mistakes_md(rule: str | None, rows: list[dict], mark: float | None = None,
                worse_from: str | None = None) -> str:
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
        parts += [WORSE_JUDGE.format(file=worse_from, check=program("check")), ""]
    parts += [f"## {WHERE_WRONG.rstrip(':')}", "", *clues, ""]
    if rule:
        parts += ["## Your LLM-as-a-judge's rule now", "", fenced("RULE", rule, cut=False), ""]
    parts += ["## Mistakes", ""]
    wrong = mistakes(rows)
    own = reasons.own_numbers(wrong)  # named by number, as the clues name them
    grouped = reasons.groups(wrong, own) if reasons.has_any(wrong) else [(None, wrong)]
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
            said = reasons.said_line(r, own)
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
                                      else None))
    write_suggestions(ws, rows)
    return len(mistakes(rows))


def _saved_line(ws: Workspace, n: int) -> str:
    """Where the mistakes went and what the file is for; the line above already says how many
    mistakes the LLM-as-a-judge made."""
    made = (f"All {n} mistakes your LLM-as-a-judge made are" if n > 1
            else "The 1 mistake your LLM-as-a-judge made is")
    return (f"{made} saved in {_file(ws, MISTAKES)}. Use it to write a better "
            "rule, or hand it to a coding agent to help you write one.")


# The pass mark (free) ----------------------------------------------------------------------

VERDICT_WORDS = {"better": "better", "safe": "safe to try"}


def _follows(m: Marks, pm: dict | None) -> bool:
    return bool(pm and pm.get("follows")) and all(
        isinstance(m.scores.get(i), int | float) for i in m.person)


def test_pass_mark(m: Marks, split: Split) -> dict | None:
    """The pass mark that fits the seen marks best, tested on the hidden marks with the saved
    scores (no AI call), once per set of hidden marks: the test, also kept in split.json, or
    None for a judge with no pass mark or when the pass mark already fits best."""
    from judgekeeper.start import passes
    from judgekeeper.start_fix import cell, cell_weights, choose_mark

    pm = m.data.get("pass_mark")
    if not _follows(m, pm):
        return None
    if split.pass_mark is not None:
        return split.pass_mark or None
    rows = {i: {"judge": m.judge[i], "final": m.person[i]} for i in m.person}
    pool = m.data.get("pool") or {}
    if len(set(m.batch.values())) > 1:  # each answer weighs by its stratum
        for i, row in rows.items():
            row["batch"] = m.batch.get(i, 1)
        pool = Counter((m.batch[q], g) for q, g in
                       ((q["id"], q["group"]) for q in m.data.get("queue") or []))
    seen = [rows[i] for i in split.seen]
    weights = cell_weights(list(rows.values()), seen, pool)
    current, op = pm["mark"], pm["op"]
    new = choose_mark([(cell(rows[i]), m.person[i], m.scores[i]) for i in split.seen],
                      current, op, weights)
    if new == current:
        split.pass_mark = {}
        return None
    fixed = broke = 0
    for i in split.hidden:
        now = passes(m.scores[i], op, new)
        fixed += m.judge[i] != m.person[i] and now == m.person[i]
        broke += m.judge[i] == m.person[i] and now != m.person[i]
    v = targets.fix_verdict(fixed, broke, len(split.hidden), test=len(split.tests) + 1)
    test = {"kind": "pass mark", "time": utc_now(), "old": current, "new": new, "op": op,
            "n": len(split.hidden), "fixed": fixed, "broke": broke, "verdict": v.kind}
    split.tests.append(test)
    split.pass_mark = test
    return test


def pass_mark_line(ws: Workspace, pm: dict, test: dict) -> str | None:
    """Screen 5a's pass-mark line, when the verdict says the new mark is worth trying."""
    from judgekeeper.start_fix import locate, searched, where_lines

    words = VERDICT_WORDS.get(test["verdict"])
    if words is None:
        return None
    new, old = f"{test['new']:g}", f"{test['old']:g}"
    name = searched(pm)
    found = name and locate(ws.root, name, test["old"])
    if found:
        where = f"Change it in {found[0]}, line {found[1]}."
    else:
        where = re.sub(r'(--pass-if "[^"]*")', r"`\1`", where_lines(pm, test["new"])[0])
    return (f"A better pass mark: {new} instead of {old} (tested on the marks kept aside: fixed "
            f"{test['fixed']}, broke {test['broke']}, {words}). {where}")


def tried_line(test: dict) -> str:
    """The pass-mark test that found no better mark, said once, when it is made: it counts as
    a test on these marks kept aside, as a rule's does."""
    old = f"{test['old']:g}"
    return (f"judgekeeper also tried a pass mark of {test['new']:g} instead of {old} on the "
            f"marks kept aside (fixed {test['fixed']}, broke {test['broke']}): not clearly "
            f"better, so keep {old}. That used up one test on these marks.")


# Saying it ----------------------------------------------------------------------------------

class Talk:
    def __init__(self, path: str):
        self.path = path

    def say(self, text: str = "") -> None:
        print(said(text))
        for line in held_lines(text):  # a name left out of the command above, as data
            print(said(line))

    def para(self, text: str, indent: str = "") -> None:
        for line in wrap(text, indent=indent):
            self.say(line)

    def command(self, subcommand: str = "fix") -> str:
        return " ".join((program(subcommand), *([] if self.path == "." else
                                                [quote_arg(self.path)])))

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
        return f"{said} {link(ws.root / where[0], where[0])}, line {where[1]}"
    if read and read != task:
        file_link = start_fix_rule.file_link
        return (f"{said} {file_link(ws.root, read)}, which {file_link(ws.root, task)} reads "
                f"into {start_fix_rule.field(tool, data.get('rule_field'))}")
    if start_fix_rule.rule_config(ws.root, tool, data):
        return f"{said} {home}"
    if home == start_fix_rule.OWN_CODE:
        return "Your LLM-as-a-judge's rule, where your code keeps it"
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
    from judgekeeper.check import _state, path_problem

    problem = path_problem(path)
    results = Path(path) if Path(path).is_file() else None
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
        talk.next(f"give `{program('fix')}` the results of grading {ANSWERS} again with your "
                  "new rule, or run it in your project folder.")
        return EXIT_USAGE
    state = _state(talk.path)
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
        talk.para("You have not marked enough answers yet to fix your LLM-as-a-judge.")
        step = f"run `{program('mark')}` to mark more answers."
        talk.next(next_marks(ws, step) if ws is not None else step)
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
        talk.para(f"You asked for a new set of marks kept aside (`{program('fix')} --new`). The "
                  "marks you have made are all seen now, so the new set is made of new marks.")
    elif split.fresh.get("adopted"):
        talk.para("You took on a rule tested on these marks kept aside. Testing the next rule "
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
    talk.para(CLEAR_LINE)
    then = (": they become a new set of marks kept aside, and your new results are tested on "
            "them" if tested else ": they become a new set of marks kept aside")
    talk.next(next_marks(ws, f"mark more answers with `{program('mark')}` (at least {left} "
                             f"more), then run `{talk.command()}` again{then}."))
    return EXIT_NEEDS_YOU


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
    return len(rows)


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


def mlflow_store(ws: Workspace) -> str | None:
    """The MLflow store the marks were made on, as a path from where the command runs (the
    new grades are a new run in it), or None for another eval tool."""
    import os

    try:
        data = ws.cached_data()
    except (OSError, ValueError):
        return None
    store = data.get("mlflow_store") if data.get("tool") == "mlflow" else None
    if not isinstance(store, str) or not store:
        return None
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
    store = mlflow_store(ws)
    if store:
        return (f"run your new scorer on all the traces again, then run "
                f"`{talk.command()} {store}`: it reads the newest run.")
    try:
        tool = ws.cached_data().get("tool")
    except (OSError, ValueError, AttributeError):
        tool = None
    if tool == "inspect":  # the log itself is scored again
        log = quote_arg(new_log(ws))
        return (f"score your log again with your new rule: run `{INSPECT_SCORE}` with "
                f"`--output-file {log}`, then run `{talk.command()} {log}`.")
    return REGRADE_SAME.format(answers=_file(ws, ANSWERS), command=talk.command())


def regrade_line(tool: str | None) -> str:
    """How to grade the marked answers again with the person's own eval tool."""
    return f"{OWN} {TABLE}" if tool == "table" else REGRADE.get(tool or "", OWN)


NEW_LOG = "new.eval"
INSPECT_SCORE = "inspect score <log> --scorer <name> --action overwrite"


def new_log(ws: Workspace) -> str:
    """Where the regraded Inspect log goes: next to the marked log, so that `check` finds it
    with the others rather than in a second folder of logs."""
    import os

    try:
        files = ws.data().get("results_files") or []
    except (OSError, ValueError):
        files = []
    root = Path(ws.root)
    logs = Path(os.environ.get("INSPECT_LOG_DIR") or "logs")  # Inspect AI's log folder
    bases = [Path("."), *([logs] if not logs.is_absolute() and ".." not in logs.parts else [])]
    folder = "."
    if files and isinstance(files[0], str):  # named from the project, or from the log folder
        folder = next(((base / files[0]).parent.as_posix() for base in bases
                       if (root / base / files[0]).is_file()),
                      Path(files[0]).parent.as_posix())
    return NEW_LOG if folder == "." else f"{folder}/{NEW_LOG}"


def _next_regrade(talk: Talk, ws: Workspace, tool: str | None) -> None:
    """The per-tool line and the Next: line after marked-answers.csv is written."""
    talk.say()
    talk.para(regrade_line(tool))
    if tool == "inspect":  # the log itself is graded again
        log = quote_arg(new_log(ws))
        talk.next(f"change your scorer's rule, run `{INSPECT_SCORE}` with `--output-file {log}`, "
                  f"then run `{talk.command()} {log}`.")
        return
    store = mlflow_store(ws) if tool == "mlflow" else None
    if store:  # a new run in the same store
        talk.next(f"change your scorer's rule, run it with `mlflow.genai.evaluate()` on the "
                  f"same traces, then run `{talk.command()} {store}`: it reads the newest run.")
        return
    talk.next(f"change your LLM-as-a-judge's rule in your eval tool, grade the answers in "
              f"{_file(ws, ANSWERS)} again, save the results, then run "
              f"`{talk.command()} {NEW_RESULTS}`.")


def first_run(talk: Talk, ws: Workspace, m: Marks, split: Split) -> int:
    """Screen 5a: where the judge goes wrong on the seen marks, mistakes.md, the pass mark,
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
        _write_mistakes(ws, rule, seen_rows, mark, m.worse_from)  # both fit the set kept aside
        n = write_answers(ws, m)
        talk.say()
        talk.para(_answers_line(ws, split, n))
        if data.get("tool") == "inspect":  # the log itself is scored again
            log = quote_arg(new_log(ws))
            talk.next(f"nothing to fix. To test another rule anyway, score your log again "
                      f"with it: run `{INSPECT_SCORE}` with `--output-file {log}`, then run "
                      f"`{talk.command()} {log}`.")
            return EXIT_OK
        talk.next(f"nothing to fix. To test another rule anyway, grade the answers in "
                  f"{_file(ws, ANSWERS)} again with it, then run "
                  f"`{talk.command()} {NEW_RESULTS}`.")
        return EXIT_OK
    found = [[line] for line in reasons.clue_lines(wrong)] + patterns(seen_rows, mark)
    if found:
        talk.say(WHERE_WRONG)
        for p in found:
            for sentence in p:
                talk.para(sentence, indent="  ")
        talk.say()
    fresh = split.pass_mark is None  # no pass mark tested on these marks yet
    tested = test_pass_mark(m, split)
    save_split(ws, split)
    _write_mistakes(ws, rule, seen_rows, mark, m.worse_from)
    talk.para(_saved_line(ws, len(wrong)))
    talk.say()
    if write_suggestions(ws, seen_rows):
        talk.para(f"Suggestions from your reasons are in {_file(ws, SUGGESTIONS)}. Copy the ones "
                  "you agree with into your rule where your eval keeps it.")
        talk.say()
    line = tested and (pass_mark_line(ws, pm, tested) or (fresh and tried_line(tested)))
    if line:
        talk.para(line)
        talk.say()
    tool = data.get("tool")
    if rule:
        talk.para(f"{_rule_place(ws, rule, tool or '', data)}:")
        talk.say(f"  {_rule_quote(rule)}")
        talk.say()
    n = write_answers(ws, m)
    talk.para(_answers_line(ws, split, n))
    _next_regrade(talk, ws, tool)
    return EXIT_OK


def _write_mistakes(ws: Workspace, rule: str | None, rows: list[dict],
                    mark: float | None, worse_from: str | None = None) -> None:
    path = _folder(ws) / MISTAKES
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, mistakes_md(rule, rows, mark, worse_from))


def _answers_line(ws: Workspace, split: Split, n: int) -> str:
    """How many marks are kept aside, and that marked-answers.csv holds all `n`."""
    k = len(split.hidden)
    aside = f"{k} of your marks {'is' if k == 1 else 'are'} kept aside to test your new rule " \
        "fairly. " if k else ""
    return (f"{aside}{_file(ws, ANSWERS)} holds all {plural(n, 'marked answer')}, questions and "
            "answers only, so you can't tell which are kept aside.")


# The test of a new rule (Screen 5b) ------------------------------------------------------

def next_test(split: Split) -> int:
    """Which test on this set of hidden marks the next one is: every test counts, whatever
    its verdict, so each is stricter."""
    return len(split.tests) + 1


def _shown_path(path: Path) -> str:
    """A results file as the person gave it, a link they can click in a terminal."""
    return link(path, path.as_posix())


def _better_needs(n: int, k: int) -> int:
    """About how many fixed mistakes, none broken, a test `k` on `n` marks needs for
    "better" (targets.fix_verdict)."""
    return next((f for f in range(1, max(n, 1) + 1)
                 if targets.fix_verdict(f, 0, max(n, f), test=k).kind == "better"), n)


def _given(talk: Talk, state, m: Marks, path: Path):
    """The new results in `path`, read as step 1 reads results (check.read_given); None, said
    with what to give instead, when they can't be read or are from another tool."""
    from judgekeeper.check import read_given

    found, problem = read_given(state, path)
    if found is None:
        talk.para(problem)
        tool = m.data.get("tool")
        talk.next(_regrade_same(talk, state.ws) if tool == "inspect" else  # the log, scored again
                  f"give `{talk.command()}` the results of grading {_file(state.ws, ANSWERS)} "
                  f"again with your new rule, from {_tool_name(tool)}.")
    return found


def test_results(talk: Talk, state, m: Marks, split: Split, path: Path) -> int:
    """Screen 5b: the new results in `path`, read as step 1 reads results, on the hidden
    marks: how the old and the new grades agree with the person's marks, and the verdict from
    the math. A hidden answer not in the file is counted, said once and left out."""
    from judgekeeper import judge_setup
    from judgekeeper.check import (
        NEXT_UNKNOWN,
        lookup,
        mixed_line,
        no_decision,
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
        talk.next(NEXT_UNKNOWN.format(command=f"{talk.command()} {quote_arg(str(path))}"))
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
                  f"judgekeeper finds them by their exact text and question.")
        _rewrite_lacking(talk, ws, m, list(split.hidden))
        _next_regrade(talk, ws, m.data.get("tool"))
        return EXIT_NEEDS_YOU
    old = m.judge
    earlier = [i for i in ids if i in m.earlier]
    took = bool(earlier) and bool(setup.get("rule_hash")) and _same_rule(ws, setup, setup_hash)
    if took:
        from judgekeeper.check import take_grades  # the judge as it is now graded them

        take_grades(ws, {i: new[i] for i in earlier})
        old = {**old, **{i: new[i] for i in earlier}}
        talk.para(TOOK.format(k=len(earlier)))
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
            talk.next(NEXT_EARLIER.format(answers=_file(ws, ANSWERS), command=talk.command()))
            return EXIT_NEEDS_YOU
    # nothing changed: nothing to tell apart. An answer with no grade is a change: counted
    if not blank and ids and all(new[i] == old.get(i) for i in ids):
        if not took:  # else said: the grades of the judge as it is now
            talk.para(SAME_GRADES if _same_rule(ws, setup, setup_hash) else
                      UNCHANGED.format(n=len(ids)))
        _next_regrade(talk, ws, m.data.get("tool"))
        return EXIT_NEEDS_YOU
    if gone or 2 * len(blank) > len(ids) + len(blank):  # the rule may fail exactly on those;
        k = len(lack) if gone else len(blank)  # before a replay: this file can't test it
        talk.para(MISSING.format(k=k, n=len(split.hidden), have=_have(k),
                                 why=_missing_why(gone, len(lack) - gone)) if gone else
                  MOSTLY_BLANK.format(k=k, n=len(ids) + k, have=_have(k)))
        _rewrite_lacking(talk, ws, m, lack)
        talk.next(_regrade_same(talk, ws))
        return EXIT_NEEDS_YOU
    before = next((t for t in split.tests if t.get("kind") == "rule"
                   and (t.get("key") or t.get("setup_hash")) == key
                   and t.get("hidden") == len(split.hidden)
                   and t.get("n") == len(ids) + len(blank)), None)
    if before is not None:
        return tested_before(talk, ws, m, before, path, len(blank))
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
    fixed = sum(old[i] != m.person[i] and new[i] == m.person[i] for i in ids)
    broke = sum(old[i] == m.person[i] and new[i] != m.person[i] for i in ids)
    v = targets.fix_verdict(fixed, broke, len(ids), test=next_test(split))
    talk.say(f"Your LLM-as-a-judge, tested on the {len(ids)} marks kept aside:")
    for name, grades in (("Old", old), ("New", new)):
        agreed = sum(grades[i] == m.person[i] for i in ids)
        talk.say(f"  {name} rule: agreed with you on {agreed} of {len(ids)} answers.")
    talk.para(went_line(fixed, broke), indent="  ")
    talk.say()
    talk.para(RESULT[v.kind])
    k = next_test(split)
    _keep(ws, split, found, setup, setup_hash, key, v, Path(path).as_posix())
    wrong = sum(old[i] != m.person[i] for i in ids)
    if v.kind in ("leans better", "same") and wrong:  # never for a rule that leans worse
        talk.para(CANT_TELL.format(n=wrong, are="is" if wrong == 1 else "are",
                                   better=_better_needs(len(ids), k)))
    if len(split.rules()) >= MAX_RULES and v.kind not in ("better", "safe"):
        talk.say()
        talk.para(f"You have tested {plural(len(split.rules()), 'rule')} on these marks kept "
                  f"aside. Your next marks become a new set kept aside. {CLEAR_LINE}")
    talk.next(_after_step(talk, ws, m, v.kind, path))
    return EXIT_OK


def _have(k: int) -> str:
    return "has" if k == 1 else "have"


def _missing_why(gone: int, errors: int) -> str:
    """Why answers kept aside have no grade: not in the file, or there with no decision."""
    parts = ([f"{gone} {'is' if gone == 1 else 'are'} not in the file"] if gone else []) + (
        [f"{errors} {_have(errors)} no decision from your LLM-as-a-judge (such as an error)"]
        if errors else [])
    return f": {' and '.join(parts)}" if parts else ""


def _same_rule(ws: Workspace, setup: dict, setup_hash: str) -> bool:
    """Whether the new results come from the LLM-as-a-judge the marks were made with (or from
    results that hold no rule, which can't tell one rule from another)."""
    from judgekeeper import judge_setup

    saved = judge_setup.read(ws) or {}
    return not setup.get("rule_hash") or saved.get("setup_hash") == setup_hash


def _after_step(talk: Talk, ws: Workspace, m: Marks, kind: str, path: Path) -> str:
    """The next step after a test of the new results `path` (without "Next: "). They grade
    every marked answer, so `check` re-checks the new rule on them: running the eval again
    would make new answers, which judgekeeper can't compare."""
    if kind in ("better", "safe"):
        return (f"keep your new rule, then run `{talk.command('check')} "
                f"{quote_arg(path.as_posix())}` to re-check it on all your marks.")
    if kind == "worse":
        kept = f" ({_file(ws, MISTAKES)} keeps a copy)" if m.data.get("rule") else ""
        return (f"copy your old rule back into your eval tool{kept}, or try another rule and "
                f"run `{talk.command()} {_new_results(ws)}` again.")
    return next_marks(ws, f"mark more answers with `{program('mark')}`, then run "
                          f"`{talk.command()}` to write the marked answers to grade again.")


def tested_before(talk: Talk, ws: Workspace, m: Marks, test: dict, path: Path,
                  blank: int = 0) -> int:
    """This LLM-as-a-judge was tested on these marks kept aside: its saved result, never a
    new test, the file and day it came from, how many this file leaves ungraded (`blank`),
    and the next step that result gave."""
    from judgekeeper.check import _day

    day = _day(test.get("time"))
    talk.para(f"You tested this LLM-as-a-judge before{f' ({day})' if day else ''}, on the "
              f"{test.get('n')} marks kept aside. "
              f"{went_line(int(test.get('fixed') or 0), int(test.get('broke') or 0))}")
    talk.say()
    talk.para(RESULT.get(test.get("verdict"), ""))
    file = test.get("file") if isinstance(test.get("file"), str) else None
    source = (f"the result above is from {file or 'an earlier file'}"
              f"{f' on {day}' if day else ''}.")
    talk.para(f"This file leaves {blank} of the {test.get('n')} ungraded; {source}" if blank
              else source[0].upper() + source[1:])
    talk.next(_after_step(talk, ws, m, str(test.get("verdict")), path))
    return EXIT_OK


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
          v, file: str | None = None) -> None:
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
            "verdict": v.kind, "test": len(split.tests) + 1,
            **({"file": scrub(file)} if file else {})}  # split.json only: history has no paths
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
