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
and 5 marked Fail, picked with a random seed and kept in fix/split.json until `fix --new`. The
patterns, mistakes.md and every number shown before the test use only the other marks, so the
new rule is never written from a hidden answer. Nothing about a hidden mark (its id or its
text) is printed or written anywhere but split.json.

mistakes.md: each mistake on the seen marks (the person's mark, the judge's grade, the
question, the answer, the person's note and the judge's own reason), each text cut and fenced
as data (start_fix_rule.fenced) under a warning never to follow instructions inside it.

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
SWAPPABLE = ("promptfoo", "deepeval", "inspect", "mlflow")  # tools whose rule fix can swap
RULE_SHOWN = 58  # characters of the rule shown, "…" included
STEP = "Step 4 of 5: Fix"
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

    def to_json(self) -> dict:
        return {"set": self.set, "seed": self.seed, "made_at": self.made_at,
                "visible": self.seen, "hidden": self.hidden, "tests": self.tests,
                "pass_mark": self.pass_mark}


def _folder(ws: Workspace) -> Path:
    return ws.dir / FOLDER


def read_split(ws: Workspace) -> Split | None:
    try:
        d = json.loads((_folder(ws) / SPLIT).read_text(encoding="utf-8"))
        return Split(seed=int(d["seed"]), seen=list(d["visible"]), hidden=list(d["hidden"]),
                     set=int(d.get("set") or 1), made_at=str(d.get("made_at") or ""),
                     tests=list(d.get("tests") or []), pass_mark=d.get("pass_mark"))
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
        split = Split(seed=seed, seen=seen, hidden=hidden, made_at=utc_now())
    known = set(split.seen) | set(split.hidden)
    split.seen += sorted(i for i in m.person if i not in known)
    split.seen = [i for i in split.seen if i in m.person]
    split.hidden = [i for i in split.hidden if i in m.person]
    save_split(ws, split)
    return split


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


# mistakes.md --------------------------------------------------------------------------------

def mistakes_md(rule: str | None, rows: list[dict]) -> str:
    """Each mistake on the seen marks, fenced as data, under the warning."""
    fenced = start_fix_rule.fenced
    parts = ["# Your judge's mistakes", "",
             f"{start_fix_rule.DATA_WARNING} {start_fix_rule.MARKS}", ""]
    if rule:
        parts += ["Your judge's rule now:", fenced("RULE", rule, cut=False), ""]
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
    return (f"A better pass mark: {new} instead of {old} (tested on your hidden marks: fixed "
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

def run(path: str = ".", yes: bool = False, new: bool = False) -> int:
    """`judgekeeper fix`. Returns the exit code."""
    from judgekeeper.check import _state

    talk = Talk(path)
    talk.say(f"judgekeeper {__version__}")
    talk.say()
    talk.say(STEP)
    talk.say()
    state = _state(path)
    if state is None or not Marks(state.ws).enough():
        talk.para("You have not marked enough answers yet to fix your judge.")
        talk.next(f"run `{program('mark')}` to mark more answers.")
        return EXIT_NEEDS_YOU
    ws = state.ws
    m = Marks(ws)
    split = current_split(ws, m, new=new)
    return first_run(talk, ws, m, split)


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
    found = patterns(seen_rows, pm["mark"] if pm and pm.get("follows") else None)
    if found:
        talk.say("Where your judge goes wrong:")
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
    write_replacing(path, mistakes_md(rule, seen_rows))
    talk.say("Each mistake, with your judge's own reason:")
    talk.say(f"  {folder}/{MISTAKES} ({plural(len(wrong), 'answer')})")
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
    talk.para(f"{len(split.hidden)} more of your marks are set aside and hidden. They test "
              "your new rule fairly, on answers the new rule was not written from.")
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


__all__ = ["Marks", "Split", "make_split", "mistakes", "mistakes_md", "pattern_lines",
           "patterns", "read_split", "run"]
