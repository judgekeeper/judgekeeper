"""`judgekeeper fix`: where the judge goes wrong, and a fair test of a new rule.

It needs a result (enough marks of each kind). Each run does the next step:

| What is there                                  | What `judgekeeper fix` does               | Exit |
|------------------------------------------------|-------------------------------------------|------|
| no rule.txt, or a rule already tested          | the patterns, mistakes.md, where the rule | 0    |
|                                                | lives, the hidden marks (Screen 5a)       |      |
| a new rule in rule.txt                         | checks it, asks before the calls, tests   | 0    |
|                                                | it on the hidden marks (Screen 5b)        |      |
| a judge whose rule judgekeeper can't swap      | says so: change it and run `check`        | 3    |

The hidden marks: about 30% of each group of marks (the judge's passes and fails, where the
person agrees and where not, rounded up; a group of one stays seen), at least 5 marked Pass
and 5 marked Fail, picked with a random seed when the first result appears (prepare_split),
before any mistake is shown, and kept in fix/split.json. The patterns, mistakes.md and every
number shown before the test use only the other marks, so the new rule is never written from a
hidden answer. Nothing about a hidden mark (its id or its text) is printed or written anywhere
but split.json while the set is in use. A set is retired when a rule tested on it is the
judge's rule now (adopted), after MAX_RULES rules, or with `fix --new`: then its marks are seen
like the others, and the next FRESH new marks make a new set.

mistakes.md, ready to hand to a coding agent: the task in one line, the clues (the pattern
sentences the terminal prints), the judge's rule now, then each mistake on the seen marks (the
person's mark, the judge's grade, the question, the answer, the person's note and the judge's
own reason), each text cut and fenced as data (start_fix_rule.fenced) under a warning never to
follow instructions inside it.

For a judge with a score and a pass mark, the pass mark that fits the seen marks best is tested
on the hidden marks with the saved scores: free, no AI call. It is shown only when the verdict
is better or safe to try.

judgekeeper never edits the person's files: it says where the rule (or the pass mark) lives.
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

from judgekeeper import __version__, marks, start_fix_rule, targets
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.redact import one_line, scrub
from judgekeeper.start_label import Workspace, shown_folder
from judgekeeper.textio import jsonl_lines, plural, program, quote_arg, wrap, write_replacing

EXIT_OK, EXIT_WORSE, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 1, 2, 3
FOLDER = "fix"
SPLIT, MISTAKES, RULE = "split.json", "mistakes.md", "rule.txt"
HIDDEN_TENTHS = 3  # of each group of marks hidden, rounded up
MIN_EACH = 5  # hidden marks marked Pass, and Fail, at least
MAX_RULES = 3  # rules tested on one set of hidden marks
FRESH = 10  # new marks that make a new set of hidden marks
SWAPPABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools whose rule fix can swap
RULE_SHOWN = 58  # characters of the rule shown, "…" included
STEP = "Step 4 of 5: Fix"
STEP_TEST = "Step 4 of 5: Fix (testing your new rule)"
ASK = ("To test it, judgekeeper asks your judge about the {n} answers kept aside, once with "
       "the old rule and once with the new one. That is {calls}, paid with your own key.")
RESULT = {
    "better": ("Result: your new rule is better. A difference this large is very unlikely to "
               "be a coincidence."),
    "safe": ("Result: safe to try. Not clearly better yet, but very unlikely to be more than "
             "10 points worse."),
    "leans better": ("Result: can't tell yet. That leans toward better, but a split this small "
                     "could easily be a coincidence."),
    "same": ("Result: can't tell yet. The two rules look about the same here. More marks are "
             "unlikely to change that much."),
    "leans worse": "Result: it looks worse. Keep the old rule.",
    "worse": "Result: worse. Keep the old rule.",
}
CANT_SWAP = {"table": "its grades come from a table",
             "records": "your own code gives its grades",
             "mapped": "its grades come from your own results file"}

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

class Marks:
    """The person's marks (person), the judge's grades on them (judge), and per answer its
    text (rows), the judge's reason and score, and the person's note."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.data = ws.data()
        read = marks.read(ws.marks)
        self.person = read.counted()
        self.notes = {i: str(x["note"]) for i, x in read.last.items()
                      if i in self.person and x.get("note")}
        groups = {q["id"]: q["group"] for q in self.data.get("queue") or []}
        self.judge = {i: groups[i] for i in self.person if i in groups}
        self.person = {i: m for i, m in self.person.items() if i in self.judge}
        self.order = sorted(self.person, key=lambda i: str(read.last[i].get("at") or ""))
        _, records = read_run(ws.pool_judge)
        self.reasons = {i: scrub(r.get("rationale") or "") for i, r in records.items()}
        self.scores = {i: r.get("raw_score") for i, r in records.items()}
        self.rows = {}
        for line in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
            if line.strip():
                row = json.loads(line)
                self.rows[row["id"]] = row

    def enough(self) -> bool:
        values = list(self.person.values())
        return min(values.count("pass"), values.count("fail")) >= targets.ROUGH

    def row(self, i: str) -> dict:
        """One mark as the patterns and mistakes.md read it."""
        from judgekeeper.start_label import display

        raw = self.rows.get(i, {})
        return {"id": i, "judge": self.judge[i], "final": self.person[i],
                "input": display(raw.get("input")), "output": display(raw.get("output")),
                "score": self.scores.get(i), "reason": self.reasons.get(i, ""),
                "why": self.notes.get(i, "")}


def make_split(m: Marks, seed: int) -> tuple[list[str], list[str]]:
    """(seen ids, hidden ids): HIDDEN_TENTHS of each of the four groups hidden, rounded up,
    except a group of one; then more hidden until MIN_EACH marked Pass and Fail are."""
    rng = random.Random(seed)
    seen, hidden = [], []
    for judge in ("pass", "fail"):
        for agrees in (True, False):
            ids = sorted(i for i in m.person
                         if m.judge[i] == judge and (m.person[i] == judge) == agrees)
            rng.shuffle(ids)
            n = -(-len(ids) * HIDDEN_TENTHS // 10) if len(ids) > 1 else 0
            hidden += ids[:n]
            seen += ids[n:]
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
    path.parent.mkdir(exist_ok=True)
    write_replacing(path, json.dumps(split.to_json(), indent=2) + "\n")


def current_split(ws: Workspace, m: Marks, new: bool = False) -> Split:
    """The saved split with marks made since it added as seen; a new one when there is none
    (or with `new`)."""
    split = None if new else read_split(ws)
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
    else:
        split.seen += new_ids
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
    if passes > fails:
        out.append([f"{passes} of its {n} mistakes are answers it passed but you failed.",
                    "Its rule may be too easy."])
    elif fails > passes:
        out.append([f"{fails} of its {n} mistakes are answers it failed but you passed.",
                    "Its rule may be too strict."])
    else:
        out.append([(f"Half of its {n} mistakes are answers it passed but you failed, and half "
                    "are answers it failed but you passed.")])
    if mark is not None:
        near = sum(m.get("score") is not None and abs(m["score"] - mark) <= NEAR + 1e-9
                   for m in wrong)
        if near * 2 > n:
            out.append([f"{near} of its {n} mistakes sit close to the pass mark.",
                        "Moving the pass mark may fix them."])
    for judge, final, name in (("fail", "pass", "wrong fails"), ("pass", "fail",
                                                                 "wrong passes")):
        side = [len(m["output"].split()) for m in wrong if m["judge"] == judge]
        agreed = [len(m["output"].split()) for m in rows
                  if m["judge"] == m["final"] == final]
        if len(side) < LONG_SIDE or len(agreed) < FEW:
            continue
        long, usual = statistics.median(side), statistics.median(agreed)
        if usual > 0 and long >= LONG * usual:
            out.append([(f"Its {name} are long answers (about {_about(long)} words, against "
                        f"{_about(usual)}).")])
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
            out.append(["Words found in many of its mistakes: " + ", ".join(
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
    judge's reason; never a hidden mark. None when there is none."""
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
    return {"mistakes": [{"judge": r["judge"], "final": r["final"],
                          "question": _question(m, r)[:cut], "answer": r["output"][:cut],
                          "reason": r["reason"][:cut]} for r in wrong]}


def _question(m: Marks, row: dict) -> str:
    """A mistake's question as the marking page showed it: one named value as its value alone."""
    from judgekeeper.start_label import question_view

    shown = question_view(m.rows.get(row["id"], {}).get("input"))
    return "\n".join(f"{k}: {v}" for k, v in shown) if isinstance(shown, list) else shown


# mistakes.md --------------------------------------------------------------------------------

TASK = ("Write a new rule so your judge agrees with the marks below. Keep what the current rule "
        "gets right. You can hand this whole file to a coding agent.")
NO_PATTERN = "No pattern stands out yet."


def mistakes_md(rule: str | None, rows: list[dict], mark: float | None = None) -> str:
    """The clue file, ready for a person or a coding agent: the task, the clues (the pattern
    sentences the terminal prints; `mark` is the pass mark when the grades follow the
    scores), the judge's rule now, then each mistake on the seen marks, fenced as data under
    the warning."""
    fenced = start_fix_rule.fenced
    clues = pattern_lines(rows, mark) or [NO_PATTERN]
    parts = ["# Your judge's mistakes", "", TASK, "", "## Clues", "", *clues, ""]
    if rule:
        parts += ["## Your judge's rule now", "", fenced("RULE", rule, cut=False), ""]
    parts += ["## Mistakes", "", f"{start_fix_rule.DATA_WARNING} {start_fix_rule.MARKS}", ""]
    for n, r in enumerate(mistakes(rows), 1):
        parts.append(f"## [M{n}] Your judge said {r['judge'].upper()}. You said "
                     f"{r['final'].upper()}.")
        parts += [fenced("QUESTION", r["input"]), fenced("ANSWER", r["output"])]
        if r.get("why"):
            parts.append(fenced("YOUR NOTE", r["why"]))
        if r.get("reason"):
            parts.append(fenced("JUDGE'S REASON", r["reason"]))
        parts.append("")
    return scrub("\n".join(parts).rstrip("\n") + "\n")


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
    seen = [rows[i] for i in split.seen]
    weights = cell_weights(list(rows.values()), seen, m.data.get("pool") or {})
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
        print(one_line(scrub(text)))

    def para(self, text: str, indent: str = "") -> None:
        for line in wrap(text, indent=indent):
            self.say(line)

    def command(self, subcommand: str = "fix") -> str:
        return " ".join((program(subcommand), *([] if self.path == "." else
                                                [quote_arg(self.path)])))

    def next(self, text: str) -> None:
        self.say()
        self.para(f"Next: {text}")


def _rule_quote(rule: str) -> str:
    text = " ".join(rule.split())
    if len(text) > RULE_SHOWN:
        text = text[:RULE_SHOWN - 1].rstrip() + "…"
    return f'"{text}"'


# The run ------------------------------------------------------------------------------------

def _new_rule(ws: Workspace, split: Split) -> str | None:
    """The rule in fix/rule.txt when it was not tested on this set of hidden marks yet."""
    from judgekeeper.fingerprint import rule_hash

    path = _folder(ws) / RULE
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    tested = {t.get("rule_hash") for t in split.tests if t.get("kind") == "rule"}
    return None if text and rule_hash(text) in tested else text


def run(path: str = ".", yes: bool = False, new: bool = False) -> int:
    """`judgekeeper fix`. Returns the exit code."""
    from judgekeeper.check import _state

    talk = Talk(path)
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    state = _state(path)
    ws = state.ws if state is not None else None
    m = Marks(ws) if ws is not None else None
    split = current_split(ws, m, new=new) if m is not None and m.enough() else None
    rule = _new_rule(ws, split) if split is not None and not new else None
    if split is not None and split.retest:  # a top-up was just marked: the same rule again
        rule = (ws.dir / "rules" / f"{split.topup['rule_hash'].removeprefix('sha256:')}.txt"
                ).read_text(encoding="utf-8")
    talk.say(STEP if rule is None else STEP_TEST)
    talk.say()
    if split is None:
        talk.para("You have not marked enough answers yet to fix your judge.")
        talk.next(f"run `{program('mark')}` to mark more answers.")
        return EXIT_NEEDS_YOU
    if split.fresh or (split.topup and not split.topup.get("done")):
        return _waiting(talk, ws, split)
    if rule is not None:
        return test_rule(talk, ws, m, split, rule, yes)
    return first_run(talk, ws, m, split)


def _waiting(talk: Talk, ws: Workspace, split: Split) -> int:
    """New marks are needed first: for the top-up, or for a new set of hidden marks."""
    if split.fresh:
        want, then = split.fresh["want"], ": they become a new set of marks kept aside"
        talk.para(f"You have tested {len(split.rules())} rules on these marks kept aside. More "
                  "tests on the same marks would make a coincidence look like a better rule.")
    else:
        want, then = split.topup["want"], ""
    if split.pending:
        talk.para(f"You have marked {len(split.pending)} of the {want} more answers.")
    talk.next(f"mark {want - len(split.pending)} more answers with `{program('mark')}`, then "
              f"run `{talk.command()}` again{then}.")
    return EXIT_NEEDS_YOU


def first_run(talk: Talk, ws: Workspace, m: Marks, split: Split) -> int:
    """Screen 5a: where the judge goes wrong on the seen marks, mistakes.md, the pass mark,
    where the rule lives, the hidden marks, and what to do next."""
    data = m.data
    seen_rows = [m.row(i) for i in split.seen]
    wrong = mistakes(seen_rows)
    if not wrong:
        talk.para("Your judge agrees with every mark you can see, so there is nothing to fix.")
        talk.next(f"nothing to do. When you change your judge or update your eval tool, run "
                  f"`{talk.command('check')}`.")
        return EXIT_OK
    pm = data.get("pass_mark")
    mark = pm["mark"] if pm and pm.get("follows") else None
    found = patterns(seen_rows, mark)
    if found:
        talk.say("Clues:")
        for p in found:
            for sentence in p:
                talk.para(sentence, indent="  ")
        talk.say()
    rule = data.get("rule") if data.get("one_rule", True) else None
    folder = f"{shown_folder(ws)}/{FOLDER}"
    tested = test_pass_mark(m, split)
    save_split(ws, split)
    path = _folder(ws) / MISTAKES
    marks._refuse_links(path)
    write_replacing(path, mistakes_md(rule, seen_rows, mark))
    every = f"all {len(wrong)} mistakes" if len(wrong) > 1 else "the 1 mistake"
    talk.para(f"The clues and {every} are saved in {folder}/{MISTAKES}. You can hand this "
              "file to a coding agent.")
    talk.say()
    line = tested and pass_mark_line(ws, pm, tested)
    if line:
        talk.para(line)
        talk.say()
    tool = data.get("tool")
    if tool in SWAPPABLE and rule:
        where = start_fix_rule.found_rule(ws.root, rule, tool)
        talk.say(f"Your judge's rule is in {where[0]}, line {where[1]}:" if where
                 else "Your judge's rule:")
        talk.say(f"  {_rule_quote(rule)}")
        talk.say()
    talk.para(f"{len(split.hidden)} more of your marks "
              f"{'is' if len(split.hidden) == 1 else 'are'} kept aside to test your new rule "
              "fairly.")
    if tool not in SWAPPABLE or not rule:
        why = CANT_SWAP.get(tool) or "its rule is not in your results"
        talk.say()
        talk.para(f"judgekeeper can't test a new rule for this judge by itself: {why}.")
        talk.next(f"change the rule where your eval keeps it, run your eval, then run "
                  f"`{talk.command('check')}`.")
        return EXIT_NEEDS_YOU
    talk.next(f"write your new rule in {folder}/{RULE}, then run `{talk.command()}` again to "
              "test it.")
    return EXIT_OK


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
    from judgekeeper.again.fresh import NOT_COUNTED, AgainError
    from judgekeeper.check import CAN_WRITE, DOWNLOAD, NO_KEY, _can_write, _go_ahead, _Quiet

    ids = set(split.hidden)
    plans = [again.make_plan(ws, again.AgainOptions(times=1, rule=r), dry=True, only=ids)
             for r in (None, rule)]
    why = next((p.plain or f"Your judge can't be asked again: {p.why}." for p in plans
                if p.status == again.CANT), None)
    why = why or (NO_KEY if not all(p.key_ok for p in plans) else None)
    why = why or next((DOWNLOAD.format(version=p.tool_version) for p in plans if p.download),
                      None)
    if why:
        talk.para(why)
        talk.next(f"run `{talk.command()}` again once your judge can be asked here.")
        return EXIT_NEEDS_YOU
    calls = sum(p.calls for p in plans)
    talk.para(ASK.format(n=len(split.hidden), calls=plural(calls, "AI call")))
    from judgekeeper import judge_setup

    if _can_write((judge_setup.read(ws) or {}).get("setup") or {}):
        talk.para(CAN_WRITE)
    answer = _go_ahead(yes)
    if answer is None:
        talk.next(f"run `{talk.command()}` in your terminal to answer, or "
                  f"`{talk.command()} --yes` to go ahead.")
        return EXIT_NEEDS_YOU
    if not answer:
        talk.para("Your judge was not asked.")
        talk.next(f"run `{talk.command()}` again when you are ready to test your rule.")
        return EXIT_NEEDS_YOU
    grades, left = [], Counter()
    for plan in plans:
        plan.folder = ws.dir / "fix" / "runs" / utc_now().replace(":", "-")
        try:
            fresh = again.run_tool(ws, plan, _Quiet())
        except AgainError as e:
            talk.say()
            talk.para(f"Asking your judge did not finish: {scrub(str(e))}")
            talk.next(f"run `{talk.command()}` again to test your rule.")
            return EXIT_NEEDS_YOU
        grades.append({i: v[0] for i, v in fresh.verdicts.items()})
        left.update(fresh.not_counted.values())
    reasons = []
    for why, k in left.items():
        one, many = NOT_COUNTED.get(why, (why, why))
        reasons.append(f"1 answer was not counted: {one}." if k == 1 else
                       f"{k} answers were not counted: {many}.")
    return grades[0], grades[1], reasons


def next_test(split: Split) -> int:
    """Which test on this set of hidden marks the next one is: every test counts, whatever
    its verdict (after "safe to try", a re-test after a top-up), so each is stricter."""
    return len(split.tests) + 1


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

    return (f"The marks kept aside hold only {plural(wrong, 'answer')} your judge got wrong. A new "
            f"rule needs at least {fewest(('safe', 'better'))} of those fixed to be called safe "
            f"to try, and about {fewest(('better',))} to be called better, so this test can "
            "only catch a worse rule.")


def test_rule(talk: Talk, ws: Workspace, m: Marks, split: Split, rule: str, yes: bool) -> int:
    """Screen 5b: the new rule from rule.txt, checked, then tested on the hidden marks with
    the old rule asked the same way, in the same run; the verdict from the math."""
    from judgekeeper.fingerprint import rule_hash

    folder = f"{shown_folder(ws)}/{FOLDER}"
    talk.say(f"New rule:  {_rule_quote(rule)}")
    talk.say(f"           (from {folder}/{RULE})")
    talk.say()
    problems = _problems(m, split, rule)
    for c in problems:
        talk.para(c["text"])
    if any(c["blocking"] for c in problems):
        talk.next(f"change the rule in {folder}/{RULE}, then run `{talk.command()}` again.")
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
    talk.say(f"Tested on the {len(ids)} marks kept aside:")
    talk.say(f"  Old rule agreed with you on {sum(old[i] == m.person[i] for i in ids)}. New "
             f"rule agreed with you on {sum(new[i] == m.person[i] for i in ids)}.")
    talk.say(f"  It fixed {fixed} and broke {broke}.")
    for line in reasons:
        talk.para(line, indent="  ")
    talk.say()
    talk.para(RESULT[v.kind])
    h = rule_hash(rule)
    _keep(ws, split, rule, h, v)
    if v.kind in ("better", "safe"):
        old_rule = m.data.get("rule") or ""
        where = start_fix_rule.found_rule(ws.root, old_rule, m.data.get("tool") or "")
        place = (f"into {where[0]}, line {where[1]}" if where else
                 f"to where your eval keeps it ({start_fix_rule.field(m.data.get('tool') or '')})")
        talk.next(f"if you like it, copy the new rule {place}. Then run your eval and "
                  f"`{talk.command('check')}`.")
        return EXIT_OK
    if v.kind == "leans better" and split.topup is None:
        split.topup = {"want": targets.top_up(v.n), "rule_hash": h, "done": False}
        save_split(ws, split)
        talk.next(f"mark {split.topup['want']} more answers with `{program('mark')}`, then run "
                  f"`{talk.command()}` again.")
        return EXIT_OK
    if v.kind == "leans better":  # one top-up per set: a new set is the way on
        split.fresh = {"want": FRESH}
        save_split(ws, split)
        talk.next(f"keep the old rule for now, or mark {FRESH} more answers with "
                  f"`{program('mark')}`, then run `{talk.command()}` again: they become a new "
                  "set of marks kept aside.")
        return EXIT_OK
    talk.next(f"keep the old rule, or write another rule in {folder}/{RULE} and run "
              f"`{talk.command()}` again.")
    return EXIT_OK


def _keep(ws: Workspace, split: Split, rule: str, h: str, v) -> None:
    """The tested rule in rules/<hash>.txt, the test in split.json and a history line: the
    rule's hash, the counts and the verdict, never answer text or ids."""
    path = ws.dir / "rules" / f"{h.removeprefix('sha256:')}.txt"
    marks._refuse_links(path)
    path.parent.mkdir(exist_ok=True)
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
