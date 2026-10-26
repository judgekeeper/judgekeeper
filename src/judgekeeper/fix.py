"""`judgekeeper fix`: where the LLM-as-a-judge goes wrong, and a fair test of a new rule.

It needs a result. With no new rule in rule.txt it shows the patterns, writes mistakes.md and
says where the rule lives; with a new rule it checks it, asks before the calls, and tests it on
the hidden marks.

The hidden marks: about 30% of each group of marks, at least 5 marked Pass and 5 Fail, picked
when the first result appears (prepare_split) and kept in fix/split.json. Everything shown
before the test uses only the other marks, so a new rule is never written from a hidden
answer, and nothing about a hidden mark is printed or written elsewhere. A set is retired once
a rule tested on it is adopted, after MAX_RULES rules, or with `fix --new`.

mistakes.md is ready to hand to a coding agent: each answer's text is fenced as data under a
warning never to follow instructions inside it. judgekeeper never edits the person's files.
"""

from __future__ import annotations

import json
import math
import random
import re
import secrets
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from judgekeeper import __version__, batches, marks, reasons, start_fix_rule, targets
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.links import link, said
from judgekeeper.redact import one_line, scrub
from judgekeeper.start_label import Workspace, every_marked, next_marks, shown_folder
from judgekeeper.textio import (
    jsonl_lines,
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
SPLIT, MISTAKES, RULE = "split.json", "mistakes.md", "rule.txt"
SUGGESTIONS = reasons.SUGGESTIONS
HIDDEN_TENTHS = 3  # of each group of marks hidden, rounded up
MIN_EACH = 5  # hidden marks marked Pass, and Fail, at least
MAX_RULES = 3  # rules tested on one set of hidden marks
FRESH = 10  # new marks that make a new set of hidden marks
SWAPPABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools whose rule fix can swap
RULE_SHOWN = 58  # characters of the rule shown, "…" included
STEP = "Step 4 of 5: Fix"
STEP_TEST = "Step 4 of 5: Fix (testing your new rule)"
ASK = ("To test it, judgekeeper asks your LLM-as-a-judge about the {n} answers kept aside, once "
       "with the old rule and once with the new one. That is {calls}, paid with your own key.")
RESULT = {
    "better": ("Result: your new rule is better. A difference this large is unlikely to be a "
               "coincidence."),
    "safe": ("Result: safe to try. Not clearly better yet, but unlikely to be more than 10 "
             "points worse."),
    "leans better": ("Result: can't tell yet. That leans toward better, but a split this small "
                     "could easily be a coincidence."),
    "same": ("Result: can't tell yet. The two rules look about the same here. More marks are "
             "unlikely to change that much."),
    "leans worse": "Result: can't tell yet. That leans toward worse; keep the old rule.",
    "worse": "Result: it looks worse. Keep the old rule.",  # only past the sign test
}
# A judge judgekeeper can't ask (can_test): the same words on every run and in report.html
CANT_ASK = "judgekeeper can't ask this LLM-as-a-judge itself."
# the result page's words
CANT_RERUN = "judgekeeper can't re-run this kind of LLM-as-a-judge itself"
NEXT_CANT_ASK = ("change its rule where your eval keeps it, run your eval, then run "
                 "`{command}`.")
# Inspect's model_graded_qa / _fact with no instructions= (rule None): Inspect's own text, which
# no public Inspect AI function gives, so it is not in the person's code to swap
INSPECT_DEFAULT = ("judgekeeper can't ask this LLM-as-a-judge itself: Inspect's default {scorer} "
                   "instructions aren't written in your code. To test a rule, set instructions= in "
                   "{scorer}(...) and run your eval again.")


def cant_ask_line(data: dict) -> str:
    """Why judgekeeper can't test a rule for this judge, in one line."""
    scorer = str(data.get("metric") or "").split("/")[-1]
    if data.get("tool") == "inspect" and not data.get("rule") and scorer in (
            "model_graded_qa", "model_graded_fact"):
        return INSPECT_DEFAULT.format(scorer=scorer)
    return CANT_ASK
# A rule test waits for its top-up: said first, then the clues as on a first run
TOP_UP_WAITING = ("Your last rule test is waiting for more marks: it couldn't tell yet. {step}, "
                  "and `{command}` tests that rule again on them.")
TOP_UP_EVAL = "Run your eval on more questions and mark the new answers"  # every answer marked

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
            row = json.loads(line)
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
        self.person = {i: m for i, m in self.person.items() if i in self.judge and i in counted}
        self.order = sorted(self.person, key=lambda i: str(read.last[i].get("at") or ""))
        said = read_cached(ws.pool_judge, _judge_said)
        self.reasons = dict(said["reasons"])  # judge_now changes these two
        self.scores = dict(said["scores"])
        self.rows = read_cached(ws.pool, _pool_rows)  # read only

    def enough(self) -> bool:
        values = list(self.person.values())
        return min(values.count("pass"), values.count("fail")) >= targets.ROUGH

    def can_test(self) -> bool:
        """Whether `fix` can test a new rule for this judge (can_test)."""
        return can_test(self.data.get("tool"), self.data.get("rule")
                        if self.data.get("one_rule", True) else None)

    def keeps_aside(self) -> bool:
        """Whether marks kept aside can test anything: a new rule, or a pass mark that
        follows the judge's scores (free). Else every mark is seen."""
        return self.can_test() or _follows(self, self.data.get("pass_mark"))

    def judge_now(self, found) -> None:
        """The grades and reasons of the judge in the newest results (`found`) on the marks,
        in place of the ones they were made on: after a check found that judge worse, its
        mistakes are the ones to fix."""
        from judgekeeper.check import _free

        answers = {a.id: a for a in found.pool.answers}
        for i, verdict in _free(found, self.person).items():
            self.judge[i] = verdict
            self.reasons[i] = scrub(answers[i].reason or "")
            self.scores[i] = answers[i].score

    def row(self, i: str) -> dict:
        """One mark as the patterns and mistakes.md read it."""
        from judgekeeper.fingerprint import rule_hash
        from judgekeeper.start_label import display

        raw = self.rows.get(i, {})
        why = self.why.get(i) or reasons.of_line(None)
        taps = list(why["reasons"]) + [c["id"] for c in self.own.values()
                                       if c.get("from") == i and why["note"]
                                       and c["id"] not in why["reasons"]]
        taps = [k for k in taps if k in reasons.REASONS or k in self.own]
        same = why["rule_hash"] == rule_hash(self.data.get("rule"))
        return {"id": i, "judge": self.judge[i], "final": self.person[i],
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
    """(seen, hidden) of the `new` marks of later batches: each cell (as _cells) of each batch,
    with the marks already split (`known`), gets HIDDEN_TENTHS hidden, rounded up, except a
    cell of one; the new marks make up what is missing. With none split yet, as _cells."""
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
    topup: dict | None = None  # {"want", "rule_hash", "done"}: after "can't tell yet", once
    fresh: dict | None = None  # {"want"}: after MAX_RULES rules, new marks make a new set
    pending: list[str] = field(default_factory=list)  # new marks waiting for a top-up or set
    retest: bool = False  # a top-up was just completed: test its rule again
    reset_at: str = ""  # `fix --new`: the picks are counted again from here (check.picks)

    def to_json(self) -> dict:
        return {"set": self.set, "seed": self.seed, "made_at": self.made_at,
                "visible": self.seen, "hidden": self.hidden, "tests": self.tests,
                "pass_mark": self.pass_mark, "topup": self.topup, "fresh": self.fresh,
                "reset_at": self.reset_at}

    def rules(self) -> list[str]:
        """The rules tested on this set, once each."""
        return list(dict.fromkeys(t["rule_hash"] for t in self.tests if t["kind"] == "rule"))


def _folder(ws: Workspace) -> Path:
    return ws.dir / FOLDER


def _file(ws: Workspace, name: str) -> str:
    """fix/<name> as the person finds it, a link they can click in a terminal."""
    return link(_folder(ws) / name, f"{shown_folder(ws)}/{FOLDER}/{name}")


def _rule_file(ws: Workspace) -> str:
    """_file(RULE), made empty first when there is none (never over one): the person is told
    to write in it. An empty rule.txt is no rule."""
    try:
        with (_folder(ws) / RULE).open("x", encoding="utf-8"):
            pass
    except OSError:  # there already (or can't be made: the line still names it)
        pass
    return _file(ws, RULE)


def read_split(ws: Workspace) -> Split | None:
    try:
        d = json.loads((_folder(ws) / SPLIT).read_text(encoding="utf-8"))
        return Split(seed=int(d["seed"]), seen=list(d["visible"]), hidden=list(d["hidden"]),
                     set=int(d.get("set") or 1), made_at=str(d.get("made_at") or ""),
                     tests=list(d.get("tests") or []), pass_mark=d.get("pass_mark"),
                     topup=d.get("topup"), fresh=d.get("fresh"),
                     reset_at=str(d.get("reset_at") or ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_split(ws: Workspace, split: Split) -> None:
    path = _folder(ws) / SPLIT
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, json.dumps(split.to_json(), indent=2) + "\n")


def current_split(ws: Workspace, m: Marks, new: bool = False) -> Split:
    """The saved split with marks made since it added as seen; a new one when there is none
    (or with `new`)."""
    split = None if new else read_split(ws)
    if not m.keeps_aside():  # nothing to test with marks kept aside: every mark is seen
        split = Split(seed=split.seed if split else secrets.randbelow(2 ** 31),
                      seen=sorted(m.person), hidden=[],
                      made_at=split.made_at if split else utc_now(),
                      reset_at=utc_now() if new else (split.reset_at if split else ""))
        save_split(ws, split)
        return split
    if split is None:
        seed = secrets.randbelow(2 ** 31)
        seen, hidden = make_split(m, seed)
        split = Split(seed=seed, seen=seen, hidden=hidden, made_at=utc_now(),
                      reset_at=utc_now() if new else "")
    if not split.fresh and (len(split.rules()) >= MAX_RULES or _adopted(ws, split)):
        retire(split)
    known = set(split.seen) | set(split.hidden)
    new_ids = [i for i in m.order if i not in known]
    if split.fresh:  # MAX_RULES rules tested: the next FRESH new marks are a new set
        if len(new_ids) >= split.fresh["want"]:
            split = Split(seed=split.seed, seen=sorted(known), hidden=new_ids,
                          set=split.set + 1, made_at=utc_now())
        else:
            split.pending = new_ids
    elif split.topup and not split.topup.get("done"):  # the top-up's marks are hidden
        want = split.topup["want"]
        if len(new_ids) >= want:
            split.hidden += new_ids[:want]
            split.seen += new_ids[want:]
            split.topup["done"] = split.retest = True
        else:
            split.pending = new_ids
    else:  # a later batch is kept aside at the same share, within each stratum, however
        # many sittings its marks came in; the first batch's new marks are seen
        first = min((m.batch.get(i, 1) for i in known), default=1)
        later = [i for i in new_ids if m.batch.get(i, 1) != first]
        split.seen += [i for i in new_ids if i not in later]
        if later and split.hidden:
            seen, hidden = _top_up(m, later, set(known) & set(m.person), split.hidden,
                                   random.Random(f"{split.seed}/{len(known)}"))
            split.seen += seen
            split.hidden += hidden
        else:
            split.seen += later
    split.seen = [i for i in split.seen if i in m.person]
    split.hidden = [i for i in split.hidden if i in m.person]
    save_split(ws, split)
    return split


def _adopted(ws: Workspace, split: Split) -> bool:
    """Whether a rule tested on this set is the judge's rule now (judge.json)."""
    from judgekeeper import judge_setup

    setup = (judge_setup.read(ws) or {}).get("setup") or {}
    return bool(split.tests) and setup.get("rule_hash") in split.rules()


def retire(split: Split) -> None:
    """The set's hidden marks are seen like the others from now on; the next FRESH new marks
    make a new set."""
    split.seen = sorted(set(split.seen) | set(split.hidden))
    split.hidden = []
    split.fresh = {"want": FRESH}


def prepare_split(ws: Workspace) -> None:
    """Set the hidden marks aside when the first result appears (and take in marks made
    since), before any mistake is shown; nothing when there are too few marks."""
    try:
        m = Marks(ws)
    except (OSError, ValueError, KeyError):
        return
    if m.enough():
        current_split(ws, m)


# The patterns -------------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w for w in re.findall(r"[^\W\d_]{4,}", text.lower())
                              if w not in STOPWORDS))


def _about(n: float) -> int:
    return int(round(n, -1)) if n >= 100 else round(n)


def mistakes(rows: list[dict]) -> list[dict]:
    """The marks the judge got wrong (the person's mark is not the judge's grade)."""
    return [r for r in rows if r["final"] != r["judge"] and r.get("choice") != "rule_unclear"]


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
    split = read_split(ws)
    ids = [i for i in split.seen if i in m.person] if split else list(m.person)
    rows = [m.row(i) for i in ids]
    pm = m.data.get("pass_mark")
    lines = pattern_lines(rows, pm["mark"] if _follows(m, pm) else None)
    return lines[:most], len(mistakes(rows))


VERDICT_NAMES = {"better": "Better", "safe": "Safe to try", "leans better": "Can't tell yet",
                 "same": "Can't tell yet", "leans worse": "Looks worse", "worse": "Worse"}


def report_section(ws: Workspace) -> dict | None:
    """The result page's disagreements: the mistakes on the marks the person can see, with the
    judge's reason, each text cut at a word to start_fix_rule.CUT characters, and the person's
    reasons on it (`why`: reasons.of_line, rule parts only of the rule now); the rule's parts
    and the person's own buttons. Never a hidden mark. None when there is none."""
    try:
        m = Marks(ws)
    except (OSError, ValueError, KeyError):
        return None
    split = read_split(ws)
    ids = [i for i in split.seen if i in m.person] if split else list(m.person)
    wrong = mistakes([m.row(i) for i in ids])
    if not wrong:
        return None
    cut = start_fix_rule.CUT

    def why(r: dict) -> dict:
        saved = m.why.get(r["id"]) or reasons.of_line(None)
        return {"reasons": saved["reasons"], "note": saved["note"],
                "rule_parts": [n for n, _ in r["parts"]], "spans": saved["spans"]}

    return {"mistakes": [{"id": r["id"], "judge": r["judge"], "final": r["final"],
                          "question": cut_words(_question(m, r), cut),
                          "answer": cut_words(reasons.canonical(r["output"]), cut),
                          "reason": cut_words(r["reason"], cut), "why": why(r)}
                         for r in wrong],
            "parts": m.parts, "own": list(m.own.values())}


def cut_words(text: str, width: int) -> str:
    """`text` cut to `width` characters, "…" included, at a word unless that leaves too
    little."""
    if len(text) <= width:
        return text
    cut = text[:width - 1]
    if " " in cut[width // 2:]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip() + "…"


def _question(m: Marks, row: dict) -> str:
    """A mistake's question as the marking page showed it: one named value as its value alone."""
    from judgekeeper.start_label import question_view

    shown = question_view(m.rows.get(row["id"], {}).get("input"))
    return "\n".join(f"{k}: {v}" for k, v in shown) if isinstance(shown, list) else shown


# mistakes.md --------------------------------------------------------------------------------

TASK = ("Write a new rule so your LLM-as-a-judge agrees with the marks below. Keep what the "
        "current rule gets right. You can hand this whole file to a coding agent.")
NO_PATTERN = "No pattern stands out yet."
WHERE_WRONG = "Where your LLM-as-a-judge goes wrong:"  # the clues' heading, here and in mistakes.md


def clue_lines(rows: list[dict], mark: float | None = None) -> list[str]:
    """Every clue, one sentence a line: the person's reasons first (reasons.clue_lines, on
    the mistakes), then the patterns."""
    return reasons.clue_lines(mistakes(rows)) + pattern_lines(rows, mark)


def mistakes_md(rule: str | None, rows: list[dict], mark: float | None = None) -> str:
    """The clue file, ready for a person or a coding agent: the task, the clues (the person's
    reasons and the pattern sentences the terminal prints; `mark` is the pass mark when the
    grades follow the scores), the judge's rule now, then each mistake on the seen marks,
    fenced as data; grouped by the person's reasons when they gave any. The warning comes
    before any of the person's or the app's words; the person's words outside a fence are on
    one line."""
    fenced = start_fix_rule.fenced
    clues = clue_lines(rows, mark) or [NO_PATTERN]
    parts = ["# Your LLM-as-a-judge's mistakes", "", TASK, "",
             f"{start_fix_rule.DATA_WARNING} {start_fix_rule.MARKS}", "",
             f"## {WHERE_WRONG.rstrip(':')}", "",
             *clues, ""]
    if rule:
        parts += ["## Your LLM-as-a-judge's rule now", "", fenced("RULE", rule, cut=False), ""]
    parts += ["## Mistakes", ""]
    wrong = mistakes(rows)
    grouped = reasons.groups(wrong) if reasons.has_any(wrong) else [(None, wrong)]
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


def write_suggestions(ws: Workspace, rows: list[dict], command: str, can: bool) -> bool:
    """fix/suggestions.md from the person's reasons on the mistakes they can see (`rows`: the
    seen marks), when they gave any; one written before is written again. Whether it holds
    any."""
    wrong = mistakes(rows)
    path = _folder(ws) / SUGGESTIONS
    if not reasons.has_any(wrong) and not path.is_file():
        return False
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, reasons.suggestions_md(wrong, f"{shown_folder(ws)}/{FOLDER}",
                                                 command, can))
    return reasons.has_any(wrong)


def refresh_mistakes(ws: Workspace, always: bool = False) -> int:
    """mistakes.md again from the marks the person can see, when there is one (`always`:
    also when there is none): after a check moved the marks to a new judge, its rule and its
    mistakes are that judge's. Returns how many mistakes it holds."""
    path = _folder(ws) / MISTAKES
    if not always and not path.is_file():
        return 0
    m = Marks(ws)
    split = read_split(ws)
    rows = [m.row(i) for i in (split.seen if split else m.person) if i in m.person]
    pm = m.data.get("pass_mark")
    rule = m.data.get("rule") if m.data.get("one_rule", True) else None
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, mistakes_md(rule, rows, pm["mark"] if pm and pm.get("follows")
                                      else None))
    write_suggestions(ws, rows, program("fix"), m.can_test())
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


# Saying it ----------------------------------------------------------------------------------

class Talk:
    def __init__(self, path: str):
        self.path = path

    def say(self, text: str = "") -> None:
        print(said(text))

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


def _rule_quote(rule: str) -> str:
    text = " ".join(rule.split())
    if len(text) > RULE_SHOWN:
        text = text[:RULE_SHOWN - 1].rstrip() + "…"
    return f'"{text}"'


# The run ------------------------------------------------------------------------------------

def read_rule(path: Path) -> str:
    """The rule in rule.txt, stripped. Only its first MAX_RULE bytes and one more are read: a
    longer file comes back longer than MAX_RULE, unstripped, and the checks refuse it."""
    with Path(path).open("rb") as f:
        raw = f.read(start_fix_rule.MAX_RULE + 1)
    if len(raw) > start_fix_rule.MAX_RULE:
        return raw.decode("utf-8", errors="replace")
    return raw.decode("utf-8").strip()


def _tested_rule(ws: Workspace, split: Split) -> tuple[str, dict] | None:
    """(the rule in fix/rule.txt, its last test) when it was tested on this set of marks
    kept aside."""
    from judgekeeper.fingerprint import rule_hash

    try:
        text = read_rule(_folder(ws) / RULE)
    except OSError:
        return None
    tests = [t for t in split.tests if t.get("kind") == "rule"
             and t.get("rule_hash") == rule_hash(text)] if text else []
    return (text, tests[-1]) if tests else None


def _new_rule(ws: Workspace, split: Split) -> str | None:
    """The rule in fix/rule.txt when it was not tested on this set of hidden marks yet."""
    from judgekeeper.fingerprint import rule_hash

    try:
        text = read_rule(_folder(ws) / RULE)
    except OSError:
        return None
    tested = {t.get("rule_hash") for t in split.tests if t.get("kind") == "rule"}
    return None if not text or rule_hash(text) in tested else text


def run(path: str = ".", yes: bool = False, new: bool = False) -> int:
    """`judgekeeper fix`. Returns the exit code."""
    from judgekeeper.check import _state

    talk = Talk(path)
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    hook = old_hook(path)
    if hook:
        talk.para(hook)
        talk.say()
    state = _state(path)
    ws = state.ws if state is not None else None
    m = Marks(ws) if ws is not None else None
    testable = m is not None and m.can_test()
    if m is not None and not testable and m.data.get("rule") is None:
        _after_worse(state, m)
    split = current_split(ws, m, new=new) if m is not None and m.enough() else None
    rule = _new_rule(ws, split) if split is not None and not new and testable else None
    if split is not None and split.retest:  # a top-up was just marked: the same rule again
        rule = (ws.dir / "rules" / f"{split.topup['rule_hash'].removeprefix('sha256:')}.txt"
                ).read_text(encoding="utf-8")
    waiting = split is not None and (split.fresh or (split.topup and not split.topup.get("done")))
    talk.say(STEP if rule is None or waiting else STEP_TEST)
    talk.say()
    if ws is None and not _has_results(Path(path)):
        talk.para(f"No eval results found in this folder ({Path(path).resolve().name}).")
        talk.next(f"run your eval once from this folder, then run `{program()}`.")
        return EXIT_NEEDS_YOU
    if split is None:
        talk.para("You have not marked enough answers yet to fix your LLM-as-a-judge.")
        step = f"run `{program('mark')}` to mark more answers."
        talk.next(next_marks(ws, step) if ws is not None else step)
        return EXIT_NEEDS_YOU
    if waiting:
        return _waiting(talk, ws, m, split, rule)
    if rule is not None:
        return test_rule(talk, ws, m, split, rule, yes)
    tested = _tested_rule(ws, split) if testable and not new else None
    if tested is not None:
        return tested_before(talk, ws, m, split, *tested)
    return first_run(talk, ws, m, split)


def _has_results(path: Path) -> bool:
    """Whether judgekeeper finds eval results it reads at `path` (nothing is read)."""
    from judgekeeper import find

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


def _waiting(talk: Talk, ws: Workspace, m: Marks, split: Split, rule: str | None = None) -> int:
    """New marks are needed first: for the top-up, or for a new set of hidden marks. A new
    rule in rule.txt (`rule`; an empty file is none) waits for them, and that is said. While a
    top-up waits, the clues show as on a first run: the step is never empty."""
    if split.fresh:
        want, then = split.fresh["want"], ": they become a new set of marks kept aside"
        talk.para(f"You have tested {plural(len(split.rules()), 'rule')} on these marks kept "
                  "aside. More tests on the same marks would make a coincidence look like a "
                  "better rule.")
        n = refresh_mistakes(ws, always=True)  # none is kept aside now: every mark is seen
        if n:
            talk.say()
            talk.para(_saved_line(ws, n))
    elif not m.can_test():  # the waiting test can't run again: what fix can do for this judge
        return first_run(talk, ws, m, split)
    else:
        want, then = split.topup["want"], ""
    left = want - len(split.pending)
    lines = []
    if split.pending:
        lines.append(f"You have marked {len(split.pending)} of the {want} more answers.")
    if rule:
        after = ("the rule before it is tested again; then it is tested" if not split.fresh
                 else "it is tested on them")
        lines.append(f"Your new rule is waiting: first mark {plural(left, 'more answer')}, then "
                     f"{after}.")
    step = next_marks(ws, f"mark {plural(left, 'more answer')} with `{program('mark')}`, "
                          f"then run `{talk.command()}` again{then}.")
    if split.fresh:
        for line in lines:
            talk.para(line)
        talk.next(step)
        return EXIT_NEEDS_YOU
    more = TOP_UP_EVAL if every_marked(ws) else f"Mark {plural(left, 'more answer')}"
    talk.para(TOP_UP_WAITING.format(step=more, command=talk.command()))
    talk.say()
    return first_run(talk, ws, m, split, then=(lines, step))


def first_run(talk: Talk, ws: Workspace, m: Marks, split: Split,
              then: tuple[list[str], str] | None = None) -> int:
    """Screen 5a: where the judge goes wrong on the seen marks, mistakes.md, the pass mark,
    where the rule lives, the hidden marks, and what to do next. While a rule test waits for
    more marks, `then` is (its lines, its next step), said in place of the usual next step."""
    data = m.data
    seen_rows = [m.row(i) for i in split.seen]
    wrong = mistakes(seen_rows)
    if not wrong:
        talk.para("Your LLM-as-a-judge agrees with every mark you can see, so there is nothing to "
                  "fix.")
        if then is not None:
            return _then(talk, then)
        talk.next("nothing to do. When you change your LLM-as-a-judge or update your eval tool, "
                  f"run `{talk.command('check')}`.")
        return EXIT_OK
    pm = data.get("pass_mark")
    mark = pm["mark"] if pm and pm.get("follows") else None
    found = [[line] for line in reasons.clue_lines(wrong)] + patterns(seen_rows, mark)
    if found:
        talk.say(WHERE_WRONG)
        for p in found:
            for sentence in p:
                talk.para(sentence, indent="  ")
        talk.say()
    rule = data.get("rule") if data.get("one_rule", True) else None
    tested = test_pass_mark(m, split)
    save_split(ws, split)
    path = _folder(ws) / MISTAKES
    marks._refuse_links(path)
    write_replacing(path, mistakes_md(rule, seen_rows, mark))
    talk.para(_saved_line(ws, len(wrong)))
    talk.say()
    tool = data.get("tool")
    if write_suggestions(ws, seen_rows, talk.command(), can_test(tool, rule)):
        where = (f"{_rule_file(ws)}, then run `{talk.command()}` to test the new rule on your "
                 "marks kept aside" if can_test(tool, rule)
                 else "your rule where your eval keeps it")
        talk.para(f"Suggestions from your reasons are in {_file(ws, SUGGESTIONS)}. Copy the ones "
                  f"you agree with into {where}.")
        talk.say()
    line = tested and pass_mark_line(ws, pm, tested)
    if line:
        talk.para(line)
        talk.say()
    if can_test(tool, rule):
        where = start_fix_rule.found_rule(ws.root, rule, tool)
        if where:
            talk.say(f"Your LLM-as-a-judge's rule is in {link(ws.root / where[0], where[0])}, "
                     f"line {where[1]}:")
        else:
            talk.para("judgekeeper can't tell which file holds your LLM-as-a-judge's rule. Your "
                      f"eval keeps it in {start_fix_rule.rule_home(ws.root, tool, data)}:")
        talk.say(f"  {_rule_quote(rule)}")
        talk.say()
    if split.hidden:
        talk.para(f"{len(split.hidden)} more of your marks "
                  f"{'is' if len(split.hidden) == 1 else 'are'} kept aside to test your new rule "
                  "fairly.")
    if not can_test(tool, rule):
        talk.say()
        talk.para(cant_ask_line(data))
        talk.next(NEXT_CANT_ASK.format(command=talk.command("check")))
        return EXIT_NEEDS_YOU
    if then is not None:
        return _then(talk, then)
    talk.next(f"write your new rule in {_rule_file(ws)}, then run `{talk.command()}` again to "
              "test it.")
    return EXIT_OK


def _then(talk: Talk, then: tuple[list[str], str]) -> int:
    """The end of a first run while a rule test waits: its lines, and its one next step."""
    lines, step = then
    for line in lines:
        talk.say()
        talk.para(line)
    talk.next(step)
    return EXIT_OK


def can_test(tool: str | None, rule: str | None) -> bool:
    """Whether judgekeeper can test a new rule for this judge: it swaps the rule into the
    judge's own eval tool. Not for a table, record() or an own format, nor without one rule
    for every answer."""
    return tool in SWAPPABLE and bool(rule)


# The test of a new rule (Screen 5b) ------------------------------------------------------

def _old_rule(m: Marks) -> str:
    """The judge's rule as the person edits it (a GEval's steps, numbered)."""
    return start_fix_rule.rule_text(m.data.get("rule") or "", m.data.get("tool") or "")


def _problems(m: Marks, split: Split, rule: str) -> list[dict]:
    """The rule checks: blocking (empty, judgekeeper's prompt pasted back, a dropped or added
    template part) and said (a big change, text copied from the seen answers)."""
    old = _old_rule(m)
    outputs = [m.row(i)["output"] for i in split.seen]
    found = start_fix_rule.checks(old, rule, m.data.get("tool") or "", outputs)
    if not any(c["blocking"] for c in found):
        found += start_fix_rule.agent_checks(old, rule)
    return found


def _ask_both(ws: Workspace, m: Marks, split: Split, rule: str, talk: Talk, yes: bool):
    """Ask the judge about the hidden answers with the old rule and with the new one, after
    the person's yes: ({id: old grade}, {id: new grade}, reasons not counted), or an exit
    code when nothing was asked."""
    from judgekeeper import again
    from judgekeeper.again.fresh import AUTH_ERROR, NOT_COUNTED, AgainError, no_answer
    from judgekeeper.check import CAN_WRITE, NOT_ASKED, _can_write, _go_ahead, _Quiet, downloads

    ids = set(split.hidden)
    plans = [again.make_plan(ws, again.AgainOptions(times=1, rule=r), dry=True, only=ids)
             for r in (None, rule)]
    cant = next((p for p in plans if p.status == again.CANT), None)
    no_key = next((p for p in plans if not p.key_ok), None) if cant is None else None
    if no_key is not None:  # which key, and where to set it: never its value
        for line in no_key.key_lines:
            talk.para(line)
        talk.para(NOT_ASKED)
        step = no_key.key_step or "set the key your LLM-as-a-judge needs"
        talk.next(f"{step}, then run `{talk.command()}` again.")
        return EXIT_NEEDS_YOU
    why = cant and (cant.plain or f"Your LLM-as-a-judge can't be asked again: {cant.why}.")
    if why:
        talk.para(why)
        if cant is not None and cant.install:
            talk.next(f"run `{cant.install}` in your project, then run `{talk.command()}` again.")
        else:
            talk.next(f"run `{talk.command()}` again once your LLM-as-a-judge can be asked here.")
        return EXIT_NEEDS_YOU
    marks.refuse_links_in(ws.dir)  # the run folders go in fix/runs/: never through a link
    calls = sum(p.calls for p in plans)
    talk.para(ASK.format(n=len(split.hidden), calls=plural(calls, "AI call"))
              + downloads(plans[0]))
    from judgekeeper import judge_setup

    if _can_write((judge_setup.read(ws) or {}).get("setup") or {}):
        talk.para(CAN_WRITE)
    answer = _go_ahead(yes)
    if answer is None:
        talk.next(f"run `{talk.command()}` in your terminal to answer, or "
                  f"`{talk.command()} --yes` to go ahead.")
        return EXIT_NEEDS_YOU
    if not answer:
        talk.para("Your LLM-as-a-judge was not asked.")
        talk.next(f"run `{talk.command()}` again when you are ready to test your rule.")
        return EXIT_NEEDS_YOU
    from judgekeeper.again.fresh import write_files
    from judgekeeper.fingerprint import rule_hash

    grades, left = [], {}
    for plan, text in zip(plans, (m.data.get("rule") or "", rule), strict=True):
        plan.folder = _run_folder(ws, rule_hash(text))
        try:
            fresh = again.run_tool(ws, plan, _Quiet())
        except AgainError as e:
            talk.say()
            talk.para(f"Asking your LLM-as-a-judge did not finish: {scrub(str(e))}")
            talk.next(f"run `{talk.command()}` again to test your rule.")
            return EXIT_NEEDS_YOU
        nothing = no_answer(fresh)
        if nothing:  # no result to give: the other rule is not asked
            talk.say()
            talk.para(nothing)
            step = ("check the key your LLM-as-a-judge uses, then run" if AUTH_ERROR in nothing
                    else "run")
            talk.next(f"{step} `{talk.command()}` again to test your rule.")
            return EXIT_NEEDS_YOU
        write_files(ws, plan, fresh, prefix="fix")  # its grades, each with the fingerprint
        grades.append({i: v[0] for i, v in fresh.verdicts.items()})
        for i, why in fresh.not_counted.items():
            left.setdefault(i, why)  # an answer not counted in both runs is one answer
    reasons = []
    for why, k in Counter(left.values()).items():
        one, many = NOT_COUNTED.get(why, (why, why))
        reasons.append(f"1 answer was not counted: {one}." if k == 1 else
                       f"{k} answers were not counted: {many}.")
    return grades[0], grades[1], reasons


def _run_folder(ws: Workspace, h: str) -> Path:
    """fix/runs/<time>-<the rule's hash>/ for one rule's run, new: the old and the new rule's
    runs, made in the same second, never share one."""
    base = ws.dir / FOLDER / "runs"
    name = f"{utc_now().replace(':', '-')}-{h.removeprefix('sha256:')[:12]}"
    folder, n = base / name, 2
    while folder.exists():
        folder, n = base / f"{name}-{n}", n + 1
    make_private(folder)
    return folder


def next_test(split: Split) -> int:
    """Which test on this set of hidden marks the next one is: every test counts, whatever
    its verdict (after "safe to try", a re-test after a top-up), so each is stricter."""
    return len(split.tests) + 1


def _copy_step(ws: Workspace, m: Marks, talk: Talk) -> str:
    """The next step after "better" or "safe to try": copy the new rule where the old one is."""
    old_rule = m.data.get("rule") or ""
    where = start_fix_rule.found_rule(ws.root, old_rule, m.data.get("tool") or "")
    place = (f"into {link(ws.root / where[0], where[0])}, line {where[1]}" if where else
             f"to where your eval keeps it ({start_fix_rule.field(m.data.get('tool') or '')})")
    return (f"if you like it, copy the new rule {place}. Then run your eval and "
            f"`{talk.command('check')}`.")


def _say_rule(talk: Talk, ws: Workspace, rule: str, problems: list[dict]) -> None:
    """The new rule's first words and where it is; only where it is when it copies text from
    the answers (it would print them)."""
    if any(c["text"] == start_fix_rule.COPIES for c in problems):
        talk.say(f"New rule:  from {_file(ws, RULE)}")
    else:
        talk.say(f"New rule:  {_rule_quote(rule)}")
        talk.say(f"           (from {_file(ws, RULE)})")
    talk.say()


def tested_before(talk: Talk, ws: Workspace, m: Marks, split: Split, rule: str,
                  test: dict) -> int:
    """The rule in rule.txt was tested on these marks kept aside: its saved result, never a
    new test, and the next step that result gave."""
    from judgekeeper.check import _day

    _say_rule(talk, ws, rule, _problems(m, split, rule))
    day = _day(test.get("time"))
    talk.para(f"You tested this rule before{f' ({day})' if day else ''}, on the "
              f"{test.get('n')} marks kept aside. "
              f"{went_line(int(test.get('fixed') or 0), int(test.get('broke') or 0))}")
    talk.say()
    talk.para(RESULT.get(test.get("verdict"), ""))
    if test.get("verdict") in ("better", "safe"):
        talk.next(_copy_step(ws, m, talk))
    else:
        talk.next(f"keep the old rule, or write another rule in {_file(ws, RULE)} and run "
                  f"`{talk.command()}` again.")
    return EXIT_OK


def few_mistakes(m: Marks, split: Split) -> str | None:
    """Said before the question when the hidden marks hold fewer than targets.FIX_FEW of the
    judge's mistakes: a test that can then only catch a worse rule. The counts it needs come
    from the verdict's own math, for this test."""
    wrong = sum(m.judge[i] != m.person[i] for i in split.hidden)
    if wrong >= targets.FIX_FEW:
        return None
    n, k = len(split.hidden), next_test(split)

    def fewest(kinds):
        return next((f for f in range(n + 1)
                     if targets.fix_verdict(f, 0, n, test=k).kind in kinds), n)

    return (f"The marks kept aside hold only {plural(wrong, 'answer')} your LLM-as-a-judge got "
            f"wrong. A new rule needs at least {fewest(('safe', 'better'))} of those fixed to be "
            f"called safe to try, and about {fewest(('better',))} to be called better, so this "
            "test can only catch a worse rule.")


def test_rule(talk: Talk, ws: Workspace, m: Marks, split: Split, rule: str, yes: bool) -> int:
    """Screen 5b: the new rule from rule.txt, checked, then tested on the hidden marks with
    the old rule asked the same way, in the same run; the verdict from the math."""
    from judgekeeper.fingerprint import rule_hash

    problems = _problems(m, split, rule)
    _say_rule(talk, ws, rule, problems)
    for c in problems:
        talk.para(c["text"])
    if any(c["blocking"] for c in problems):
        talk.next(f"change the rule in {_file(ws, RULE)}, then run `{talk.command()}` again.")
        return EXIT_NEEDS_YOU
    if problems:
        talk.say()
    few = few_mistakes(m, split)
    if few:
        talk.para(few)
        talk.say()
    asked = _ask_both(ws, m, split, rule, talk, yes)
    if isinstance(asked, int):
        return asked
    old, new, reasons = asked
    ids = [i for i in split.hidden if i in old and i in new]
    fixed = sum(old[i] != m.person[i] and new[i] == m.person[i] for i in ids)
    broke = sum(old[i] == m.person[i] and new[i] != m.person[i] for i in ids)
    v = targets.fix_verdict(fixed, broke, len(ids), test=next_test(split))
    talk.say()
    talk.say(f"Your LLM-as-a-judge, tested on the {len(ids)} marks kept aside:")
    for name, grades in (("Old", old), ("New", new)):
        agreed = sum(grades[i] == m.person[i] for i in ids)
        talk.say(f"  {name} rule: agreed with you on {agreed} of {len(ids)} answers.")
    talk.para(went_line(fixed, broke), indent="  ")
    for line in reasons:
        talk.para(line, indent="  ")
    talk.say()
    talk.para(RESULT[v.kind])
    h = rule_hash(rule)
    _keep(ws, split, rule, h, v)
    if v.kind in ("better", "safe"):
        talk.next(_copy_step(ws, m, talk))
        return EXIT_OK
    if v.kind == "leans better" and len(split.rules()) >= MAX_RULES:  # no top-up: a new set
        retire(split)
        save_split(ws, split)
        talk.para(f"You have tested {plural(len(split.rules()), 'rule')} on these marks kept "
                  f"aside. Mark {FRESH} more answers with `{program('mark')}`: they become a new "
                  f"set kept aside, and `{talk.command()}` tests this rule again on them.")
        talk.next(next_marks(ws, f"mark {FRESH} more answers with `{program('mark')}`, then "
                                 f"run `{talk.command()}` again."))
        return EXIT_OK
    if v.kind == "leans better" and split.topup is None:
        split.topup = {"want": targets.top_up(v.n), "rule_hash": h, "done": False}
        save_split(ws, split)
        talk.next(next_marks(ws, f"mark {split.topup['want']} more answers with "
                                 f"`{program('mark')}`, then run `{talk.command()}` again."))
        return EXIT_OK
    if v.kind == "leans better":  # one top-up per set: a new set is the way on
        split.fresh = {"want": FRESH}
        save_split(ws, split)
        more = next_marks(ws, f"mark {FRESH} more answers with `{program('mark')}`, then run "
                              f"`{talk.command()}` again: they become a new set of marks kept "
                              "aside.")
        talk.next(f"keep the old rule for now, or {more}")
        return EXIT_OK
    talk.next(f"keep the old rule, or write another rule in {_file(ws, RULE)} and run "
              f"`{talk.command()}` again.")
    return EXIT_OK


def _keep(ws: Workspace, split: Split, rule: str, h: str, v) -> None:
    """The tested rule in rules/<hash>.txt, the test in split.json and a history line: the
    rule's hash, the counts and the verdict, never answer text or ids."""
    path = ws.dir / "rules" / f"{h.removeprefix('sha256:')}.txt"
    marks._refuse_links(path)
    make_private(path.parent)
    write_replacing(path, rule)
    test = {"kind": "rule", "time": utc_now(), "rule_hash": h, "n": v.n, "fixed": v.fixed,
            "broke": v.broke, "verdict": v.kind, "test": len(split.tests) + 1}
    split.tests.append(test)
    save_split(ws, split)
    marks.append(ws.history_jsonl, {"time": test["time"], "kind": "fix", "rule_hash": h,
                                    "hidden": v.n, "fixed": v.fixed, "broke": v.broke,
                                    "verdict": v.kind, "test": test["test"],
                                    "set": split.set})
    from judgekeeper.start_label import write_report

    try:
        write_report(ws)
    except OSError:
        pass  # the test is saved; the report catches up with the next result


__all__ = ["TASK", "Marks", "Split", "make_split", "mistakes", "mistakes_md", "pattern_lines",
           "patterns", "read_split", "run"]
