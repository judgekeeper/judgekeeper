"""Fix your judge, after the review of the disagreements. No AI call and no key.

The person's final mark for an answer is their second look (Correct or Wrong) when they gave
one in the review, else their first label; "I was wrong" makes it the judge's verdict, and an
answer they were not sure about on the second look is left out. A mistake is an answer whose
final mark differs from the judge's saved verdict (not counting those marked "The rule is
unclear", which have a box of their own). The main result keeps the first labels.

The first time, about 30% of the answers with a final mark are set aside: ceil(30%) of each
of four cells (the judge's pass or fail, times whether it agrees with the final mark), in a
seeded shuffle. They are used only to test a change, so the test is fair: nothing from them is
shown or counted in a pattern, and they never go into a prompt. The page shows, from the rest:

- what the judge gets wrong: the two kinds of mistakes, each a list that folds open, and plain
  patterns in them (too easy or too strict, close to the pass mark, long answers, words that
  stand out), only when they are strong;
- for a judge whose decisions are a score held against a pass mark: the pass mark that fits
  the person's marks best, and a free test of it on the answers set aside.

A test says how many of the set-aside answers the change fixed and broke, with an exact sign
test on the two, and the two agreement numbers before and after (weighted by the saved groups,
as `new_judge` does). After 3 tests on one split, the answers set aside no longer give a fair
test.

`.judgekeeper/` gains fix.json (the result it is of, the seed, the two parts, the tests) and
fix/ (patterns.json: the counts and the pattern lines; pass-mark.json: the pass-mark test). A
new result moves both to history/fix-<date>/. judgekeeper never edits the person's own files:
it only says where the pass mark probably is.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import random
import re
import secrets
import statistics
import sys
import webbrowser
from collections import Counter
from pathlib import Path

from judgekeeper import start_review, weighted
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.redact import scrub
from judgekeeper.start_label import FOLDER, Workspace, _write_json, display, question_view

ASIDE_TENTHS = 3  # of each cell set aside, rounded up
MIN_EACH = 5  # set-aside answers marked Pass, and Fail, a test needs
MAX_TESTS = 3  # tests on one split
P_SURE = 0.05
FEW = 3  # mistakes a pattern needs
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
SEARCH_SKIP = {".venv", "venv", "node_modules", ".git", ".judgekeeper", "__pycache__"}
SEARCH_DEPTH = 4
SEARCH_MAX_BYTES = 1_000_000
SEARCH_MAX_FILES = 5000
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)"

SMALL = "This test is small. The real check is on new answers, after your next eval run."
NEXT_RUN = "Mark more answers from your next eval run: judgekeeper start --label-more"
NO_FOLLOW = ("Your judge's decisions don't follow its scores, so moving the pass mark can't be "
             "tested.")
FITS = "Your pass mark already fits your marks best."
NOTHING = "Your judge agrees with every final mark you gave: nothing to fix."
SIDES = (("pass", "fail", "Passed, but you said Fail"),
         ("fail", "pass", "Failed, but you said Pass"))
SAID = {"pass": "Pass", "fail": "Fail"}


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def _mark(x: float) -> str:
    return f"{x:g}"


# Final marks ------------------------------------------------------------------------------

def final_rows(rows: list[dict], items: list[dict]) -> list[dict]:
    """The final mark of each labeled answer: [{"id", "judge", "first", "final", "choice",
    "why"}], from `rows` (start_review.labeled) and the review's `items`."""
    by_id = {i["id"]: i for i in items}
    out = []
    for r in rows:
        item = by_id.get(r["id"], {})
        second, choice = item.get("second"), item.get("choice")
        if second == "unsure":
            continue
        final = second if second in ("pass", "fail") else r["first"]
        if choice == "slipped":  # "I was wrong": the person takes the judge's side
            final = r["judge"]
        out.append({"id": r["id"], "judge": r["judge"], "first": r["first"], "final": final,
                    "choice": choice, "why": item.get("why")})
    return out


def mistakes(marks) -> list[dict]:
    """The answers the judge got wrong by the final marks, without "The rule is unclear"."""
    return [m for m in marks if m["final"] != m["judge"] and m.get("choice") != "rule_unclear"]


def unclear(marks) -> list[dict]:
    return [m for m in marks if m.get("choice") == "rule_unclear"]


def to_fix(rows: list[dict], items: list[dict]) -> int:
    """How many answers there are to fix the judge with: mistakes and unclear rules."""
    marks = final_rows(rows, items)
    return len(mistakes(marks)) + len(unclear(marks))


def _review_items(ws: Workspace) -> list[dict]:
    """The items of the review of this result, or [] when there is none."""
    if not ws.review.is_file():
        return []
    saved = json.loads(ws.review.read_text(encoding="utf-8"))
    return saved["items"] if saved.get("basis") == start_review._basis(ws) else []


def final_marks(ws: Workspace) -> list[dict]:
    return final_rows(start_review.labeled(ws), _review_items(ws))


def review_done(ws: Workspace) -> bool:
    items = _review_items(ws)
    return bool(items) and all(i["second"] for i in items) and all(
        i["choice"] for i in items if i["disagreement"])


def ready(ws: Workspace) -> bool:
    """Whether Fix your judge has something to work with: the review is done and found at
    least one mistake or unclear rule."""
    return (ws.result_json.is_file() and review_done(ws)
            and to_fix(start_review.labeled(ws), _review_items(ws)) > 0)


# The split --------------------------------------------------------------------------------

def split(marks: list[dict], seed: int) -> tuple[list[str], list[str]]:
    """(used ids, set-aside ids): ceil(30%) of each of the four cells set aside."""
    rng = random.Random(seed)
    used, aside = [], []
    for judge in ("pass", "fail"):
        for agrees in (True, False):
            ids = sorted(m["id"] for m in marks
                         if m["judge"] == judge and (m["final"] == judge) == agrees)
            rng.shuffle(ids)
            n = -(-len(ids) * ASIDE_TENTHS // 10)
            aside += ids[:n]
            used += ids[n:]
    return used, aside


def _keep_old(ws: Workspace) -> None:
    """Move an earlier fix.json and fix/ to history/fix-<date>/. Nothing is deleted."""
    stamp = utc_now().replace(":", "-")
    target = ws.history / f"fix-{stamp}"
    n = 2
    while target.exists():
        target = ws.history / f"fix-{stamp}-{n}"
        n += 1
    target.mkdir(parents=True)
    for p in (ws.dir / "fix.json", ws.dir / "fix"):
        if p.exists():
            p.replace(target / p.name)


# The patterns -----------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return list(dict.fromkeys(w for w in re.findall(r"[^\W\d_]{4,}", text.lower())
                              if w not in STOPWORDS))


def _about(n: float) -> int:
    return int(round(n, -1)) if n >= 100 else round(n)


def pattern_lines(rows: list[dict], mark: float | None = None) -> list[str]:
    """Plain patterns in the judge's mistakes, only when strong. `rows` are the used answers:
    "judge", "final", "choice", "output" (text) and "score"; `mark` is the pass mark when the
    judge's decisions follow its scores."""
    wrong = mistakes(rows)
    n = len(wrong)
    if n < FEW:
        return []
    lines = []
    passes = sum(m["judge"] == "pass" for m in wrong)
    fails = n - passes
    if passes > fails:
        lines.append(f"{passes} of your judge's {n} mistakes are passes that should have "
                     "failed: its rule may be too easy.")
    elif fails > passes:
        lines.append(f"{fails} of your judge's {n} mistakes are fails that should have "
                     "passed: its rule may be too strict.")
    else:
        lines.append(f"Half of your judge's {n} mistakes are passes that should have failed, "
                     "and half are fails that should have passed.")
    if mark is not None:
        near = sum(m.get("score") is not None and abs(m["score"] - mark) <= NEAR + 1e-9
                   for m in wrong)
        if near * 2 > n:
            lines.append(f"{near} of {n} mistakes sit close to the pass mark. Moving the pass "
                         "mark may fix them.")
    for judge, final, name in (("fail", "pass", "wrong fails"), ("pass", "fail",
                                                                 "wrong passes")):
        side = [len(m["output"].split()) for m in wrong if m["judge"] == judge]
        agreed = [len(m["output"].split()) for m in rows
                  if m["judge"] == m["final"] == final]
        if len(side) < LONG_SIDE or len(agreed) < FEW:
            continue
        long, usual = statistics.median(side), statistics.median(agreed)
        if usual > 0 and long >= LONG * usual:
            lines.append(f"Your judge's {name} are long answers (about {_about(long)} words, "
                         f"against {_about(usual)}).")
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
            lines.append("Words in many mistakes: " + ", ".join(
                f"{word} ({a})" for _, a, word in strong[:WORDS_SHOWN]) + ".")
    return lines


# The pass mark ----------------------------------------------------------------------------

def nice_mark(low: float, high: float) -> float:
    """The shortest number strictly between two neighbouring scores, near their middle."""
    middle = (low + high) / 2
    for digits in range(1, 7):
        mark = round(middle, digits)
        if low < mark < high:
            return mark
    return middle


def choose_mark(items: list[tuple[str, str, float]], current: float, op: str,
                weights: dict) -> float:
    """The pass mark that fits (group, final mark, score) items best: the best weighted
    (TPR + TNR) / 2 among a point between each two neighbouring scores; on a tie, the one
    nearest the current mark, which wins its own ties."""
    from judgekeeper.start import passes

    def fit(mark):
        t = weighted._table([(g, label, passes(s, op, mark)) for g, label, s in items], weights)
        return None if t["tpr"] is None or t["tnr"] is None else (t["tpr"] + t["tnr"]) / 2

    scores = sorted({s for _, _, s in items})
    best, best_fit = current, fit(current)
    for low, high in itertools.pairwise(scores):
        mark = nice_mark(low, high)
        f = fit(mark)
        if f is None:
            continue
        if best_fit is None or f > best_fit + 1e-12 or (
                abs(f - best_fit) <= 1e-12 and abs(mark - current) < abs(best - current)):
            best, best_fit = mark, f
    return best


def rule_words(op: str, mark: float) -> str:
    m = _mark(mark)
    return {">=": f"{m} or more", ">": f"more than {m}", "<=": f"{m} or less",
            "<": f"less than {m}"}[op]


def where_lines(pm: dict, mark: float) -> list[str]:
    """Where the pass mark lives, by where it came from. judgekeeper changes none of it."""
    m = _mark(mark)
    source = pm["source"]
    if source == "deepeval":
        return [f"Set threshold={m} in your metric, e.g. GEval(..., threshold={m})."]
    if source == "records":
        return [f"Set pass_mark={m} in your judgekeeper.record() line."]
    if source == "mapped" and pm.get("key"):
        return [(f"Your eval writes its pass mark in {pm['key']}: set it to {m} where your "
                 "eval sets it.")]
    if source == "mapped":
        return [f"Set pass_mark = {m} in judgekeeper.toml [start]."]
    rule = re.sub(rf"{_NUMBER}\s*$", m, pm.get("rule") or f"score{pm['op']}0")
    return [f"Use --pass-if '{rule}'."]


SEARCHED = {"deepeval": "threshold", "records": "pass_mark", "mapped": "pass_mark"}


def _files(root: Path):
    """The project's files to search, shallow folders first: at most SEARCH_DEPTH folders
    deep, skipping SEARCH_SKIP and links, each under SEARCH_MAX_BYTES."""
    level, seen = [root], 0
    for _ in range(SEARCH_DEPTH + 1):
        folders = []
        for folder in level:
            try:
                entries = sorted(os.scandir(folder), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    if e.name not in SEARCH_SKIP:
                        folders.append(Path(e.path))
                elif e.is_file() and e.stat().st_size <= SEARCH_MAX_BYTES:
                    seen += 1
                    if seen > SEARCH_MAX_FILES:
                        return
                    yield Path(e.path)
        level = folders


def locate(root: Path, name: str, value: float) -> tuple[str, int, str] | None:
    """(file, line number, line) of the first `name = value` in the project's text files, or
    None. It only reads: nothing is imported or run."""
    pattern = re.compile(rf"\b{re.escape(name)}\s*=\s*({_NUMBER})")
    for path in _files(Path(root)):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            for m in pattern.finditer(line):
                try:
                    if abs(float(m[1]) - value) < 1e-9:
                        return path.relative_to(root).as_posix(), n, line.strip()
                except ValueError:
                    continue
    return None


# The fair test ----------------------------------------------------------------------------

def sign_test(fixed: int, broke: int) -> float:
    """The exact two-sided sign test of fixed against broke (binomial, p = 0.5)."""
    n = fixed + broke
    if not n:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(fixed, broke) + 1))
    return min(1.0, 2 * tail / 2 ** n)


def test_kind(fixed: int, broke: int) -> str:
    p = sign_test(fixed, broke)
    if p < P_SURE and fixed > broke:
        return "better"
    if p < P_SURE and broke > fixed:
        return "worse"
    return "unsure"


def test_sentence(n: int, fixed: int, broke: int) -> str:
    kind = test_kind(fixed, broke)
    if kind == "better":
        return (f"On the {n} answers set aside, it did better: it fixed {fixed} and broke "
                f"{broke or 'none'}.")
    if kind == "worse":
        return (f"On the {n} answers set aside, it did worse: it fixed {fixed} and broke "
                f"{broke}. Keep what you have.")
    return (f"Can't tell yet: on the {n} answers set aside it fixed {fixed} and broke {broke}. "
            "That is too few to be sure. Mark more answers to find out.")



def _pct(value) -> str:
    return "unknown" if value is None else f"{value:.0%}"


def _ranged(value, interval) -> str:
    lo, hi = interval or (None, None)
    return _pct(value) if value is None or lo is None or hi is None else (
        f"{_pct(value)} ({_pct(lo)} to {_pct(hi)})")


# The session the page reads -------------------------------------------------------------

class Fix:
    """The fix of one result: the split (made once), the patterns, the pass mark and its
    test. The page gets only the used answers; the set-aside ones only as counts."""

    def __init__(self, ws: Workspace):
        self.workspace = ws
        self.out = ws.dir / "fix.json"
        self.folder = ws.dir / "fix"
        self.by_id: dict = {}  # nothing on this page is labeled
        self.posts = {"/fix/pass-mark": self._post_pass_mark}
        basis = start_review._basis(ws)
        saved = json.loads(self.out.read_text(encoding="utf-8")) if self.out.is_file() \
            else None
        if saved is not None and saved.get("basis") != basis:
            _keep_old(ws)
            saved = None
        marks = final_marks(ws)
        self.marks = {m["id"]: m for m in marks}
        self.new = saved is None
        if saved is None:
            seed = secrets.randbelow(2**31)
            used, aside = split(marks, seed)
            saved = {"basis": basis, "seed": seed, "made_at": utc_now(), "used_ids": used,
                     "aside_ids": aside, "tests": []}
            _write_json(self.out, saved)
        self.saved = saved
        self.used_ids = [i for i in saved["used_ids"] if i in self.marks]
        self.aside_ids = [i for i in saved["aside_ids"] if i in self.marks]
        data = ws.data()
        self.pool, self.rule, self.pm = data["pool"], data.get("rule"), data.get("pass_mark")
        self.raw = {}
        for line in ws.pool.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                self.raw[row["id"]] = row
        _, records = read_run(ws.pool_judge)
        self.reasons = {i: scrub(r.get("rationale") or "") for i, r in records.items()}
        self.scores = {i: r.get("raw_score") for i, r in records.items()}
        self.write_patterns()

    # The used part ------------------------------------------------------------------------

    def _rows(self) -> list[dict]:
        return [{**self.marks[i], "output": display(self.raw.get(i, {}).get("output")),
                 "score": self.scores.get(i)} for i in self.used_ids]

    def _follows(self) -> bool:
        return bool(self.pm and self.pm.get("follows")) and all(
            isinstance(self.scores.get(i), int | float) for i in self.marks)

    def lines(self) -> list[str]:
        return pattern_lines(self._rows(), self.pm["mark"] if self._follows() else None)

    def counts(self) -> dict:
        rows = self._rows()
        wrong = mistakes(rows)
        return {"passed_but_fail": sum(m["judge"] == "pass" for m in wrong),
                "failed_but_pass": sum(m["judge"] == "fail" for m in wrong),
                "unclear": len(unclear(rows))}

    def aside_note(self) -> str:
        return (f"{_plural(len(self.aside_ids), 'answer')} "
                f"{'is' if len(self.aside_ids) == 1 else 'are'} set aside for the test and "
                "not shown here.")

    def _item(self, m: dict) -> dict:
        raw = self.raw.get(m["id"], {})
        return {"input": question_view(raw.get("input")), "output": display(raw.get("output")),
                "reason": self.reasons.get(m["id"], ""), "why": m.get("why") or ""}

    def write_patterns(self) -> None:
        self.folder.mkdir(exist_ok=True)
        _write_json(self.folder / "patterns.json", {
            "made_at": utc_now(), "used": len(self.used_ids), "aside": len(self.aside_ids),
            "counts": self.counts(), "lines": self.lines(),
            "pass_mark": {k: v for k, v in (self.pass_mark_section() or {}).items()
                          if k != "test"}})

    # The pass mark ------------------------------------------------------------------------

    def refusal(self) -> str | None:
        """Why no change can be tested on this split, or None."""
        n = len(self.aside_ids)
        tests = len(self.saved["tests"])
        if tests >= MAX_TESTS:
            return (f"You have tested {tests} changes on the same {n} answers, so they no "
                    "longer give a fair test. Mark new answers to test more.")
        finals = [self.marks[i]["final"] for i in self.aside_ids]
        short = [f"{finals.count(v)} {SAID[v]}" for v in ("pass", "fail")
                 if finals.count(v) < MIN_EACH]
        if short:
            return (f"Too few answers set aside to test a change fairly: it needs {MIN_EACH} "
                    f"you marked Pass and {MIN_EACH} you marked Fail (you have "
                    f"{' and '.join(short)}). Mark more answers first.")
        return None

    def _weights(self, ids) -> dict:
        n = Counter(self.marks[i]["judge"] for i in ids)
        return {g: self.pool[g] / n[g] if n[g] else 0.0 for g in ("pass", "fail")}

    def suggested(self) -> float:
        items = [(self.marks[i]["judge"], self.marks[i]["final"], self.scores[i])
                 for i in self.used_ids]
        return choose_mark(items, self.pm["mark"], self.pm["op"], self._weights(self.used_ids))

    def _saved_test(self) -> dict | None:
        path = self.folder / "pass-mark.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def pass_mark_section(self) -> dict | None:
        """The page's pass-mark section, or None for a judge with no score and pass mark."""
        if not self.pm:
            return None
        if not self._follows():
            return {"kind": "no_follow", "text": NO_FOLLOW}
        mark, current = self.suggested(), self.pm["mark"]
        lines = [(f"Your judge passes an answer when its score is "
                  f"{rule_words(self.pm['op'], current)}.")]
        if mark == current:
            section = {"kind": "fits", "mark": mark, "lines": lines + [FITS]}
        else:
            section = {"kind": "suggest", "mark": mark, "lines": lines + [
                f"On the answers judgekeeper used, {_mark(mark)} fits your marks best."]}
        saved = self._saved_test()
        if saved is not None and saved["new_mark"] == mark:
            section["test"] = saved["test"]
        elif self.refusal():
            section["refusal"] = self.refusal()
        elif section["kind"] == "suggest":
            section["button"] = (f"Test {_mark(mark)} on the "
                                 f"{_plural(len(self.aside_ids), 'answer')} set aside")
        return section

    def test_pass_mark(self, mark: float) -> dict:
        """Test the suggested pass mark on the set-aside answers, save it and return it. The
        same mark again returns the saved test, and is not counted again."""
        from judgekeeper.start import passes

        section = self.pass_mark_section()
        if not section or section["kind"] == "no_follow":
            raise ValueError("this judge has no pass mark that can be moved")
        if section.get("test") and section["mark"] == mark:
            return section["test"]
        if section.get("refusal"):
            raise ValueError(section["refusal"])
        if section["kind"] != "suggest" or mark != section["mark"]:
            raise ValueError("only the suggested pass mark can be tested")
        old_mark, op = self.pm["mark"], self.pm["op"]
        new = {i: passes(self.scores[i], op, mark) for i in self.aside_ids}
        test = self.fair_test(new)
        hand_over = where_lines(self.pm, mark)
        name = SEARCHED.get(self.pm["source"])
        if name and not (self.pm["source"] == "mapped" and self.pm.get("key")):
            found = locate(self.workspace.root, name, old_mark)
            if found:
                hand_over.append(f"Probably in {found[0]}, line {found[1]}: {found[2]}")
        test.update(hand_over=hand_over + [NEXT_RUN], old_mark=old_mark, new_mark=mark)
        self._record(f"pass mark {_mark(old_mark)} to {_mark(mark)}", "pass_mark", test)
        _write_json(self.folder / "pass-mark.json", {
            "made_at": utc_now(), "old_mark": old_mark, "new_mark": mark, "op": op,
            "test": test})
        return self._saved_test()["test"]

    def _post_pass_mark(self, body: dict) -> dict:
        mark = body.get("mark")
        if isinstance(mark, bool) or not isinstance(mark, int | float):
            raise TypeError("mark must be a number")
        self.test_pass_mark(float(mark))
        return {"pass_mark": self.pass_mark_section()}

    # The fair test ------------------------------------------------------------------------

    def fair_test(self, new: dict[str, str]) -> dict:
        """Old decisions (the saved verdicts) against `new` ones on the set-aside answers."""
        aside = [self.marks[i] for i in self.aside_ids]
        fixed = sum(m["judge"] != m["final"] and new[m["id"]] == m["final"] for m in aside)
        broke = sum(m["judge"] == m["final"] and new[m["id"]] != m["final"] for m in aside)
        n = len(aside)
        before = weighted.general([(m["judge"], m["final"], m["judge"]) for m in aside],
                                  self.pool["pass"], self.pool["fail"])
        after = weighted.general([(m["judge"], m["final"], new[m["id"]]) for m in aside],
                                 self.pool["pass"], self.pool["fail"])
        numbers, ranges = [], []
        for key, said in (("tpr", "Pass"), ("tnr", "Fail")):
            line = f"When you said {said}, your judge also said {said}"
            numbers.append(f"{line}: {_pct(before[key])} → {_pct(after[key])}")
            ranges.append(f"{line}: before {_ranged(before[key], before[f'{key}_interval'])}, "
                          f"after {_ranged(after[key], after[f'{key}_interval'])}.")
        return {"kind": test_kind(fixed, broke), "n": n, "fixed": fixed, "broke": broke,
                "p": sign_test(fixed, broke),
                "lines": [test_sentence(n, fixed, broke), SMALL],
                "numbers": numbers, "ranges": ranges}

    def _record(self, change: str, kind: str, test: dict) -> None:
        self.saved["tests"].append({"kind": kind, "made_at": utc_now(), "change": change,
                                    "fixed": test["fixed"], "broke": test["broke"],
                                    "p": test["p"], "result": test["kind"]})
        _write_json(self.out, self.saved)

    # What the server asks for -------------------------------------------------------------

    def state(self) -> dict:
        rows = [self.marks[i] for i in self.used_ids]
        wrong = mistakes(rows)
        lists = []
        for judge, final, title in SIDES:
            items = [self._item(m) for m in wrong if m["judge"] == judge]
            lists.append({"title": f"{title} ({len(items)})", "judge": SAID[judge],
                          "you": SAID[final], "items": items})
        hazy = [self._item(m) for m in unclear(rows)]
        return {"rule": self.rule, "used": len(self.used_ids), "lines": self.lines(),
                "lists": lists,
                "unclear": {"title": f"Your rule does not decide these ({len(hazy)})",
                            "items": hazy},
                "aside": self.aside_note(), "pass_mark": self.pass_mark_section()}

    def summary(self) -> dict:
        return {"done": False}  # the page stays until Ctrl-C


# The terminal -----------------------------------------------------------------------------

def aside_line(fix: Fix) -> str:
    return (f"Setting aside {len(fix.aside_ids)} of your {len(fix.marks)} marked answers. "
            "They are used only to test a change, so the test is fair. They never go into a "
            "prompt.")


def count_lines(fix: Fix) -> list[str]:
    c = fix.counts()
    lines = [(f"What your judge gets wrong, on the {len(fix.used_ids)} answers judgekeeper "
              "used:"), f"  Passed, but you said Fail: {c['passed_but_fail']}",
             f"  Failed, but you said Pass: {c['failed_but_pass']}"]
    if c["unclear"]:
        lines.append(f"  Your rule does not decide these: {c['unclear']}")
    return lines + [f"  {line}" for line in fix.lines()] + [f"  {fix.aside_note()}"]


def test_lines(test: dict) -> list[str]:
    title = "Where to change it:" if test["kind"] == "better" else \
        "If you still want to use it:"
    return [*test["lines"], *(f"  {x}" for x in test["numbers"]), "", title,
            *(f"  {x}" for x in test["hand_over"])]



def _terminal(fix: Fix, talk, test: bool) -> int:
    talk.say()
    for line in count_lines(fix):
        talk.say(line)
    section = fix.pass_mark_section()
    if section is not None:
        talk.say()
        for line in [section["text"]] if section["kind"] == "no_follow" else section["lines"]:
            talk.say(line)
        if section.get("refusal"):
            talk.say(section["refusal"])
        elif section.get("test") and not test:
            talk.say()
            for line in test_lines(section["test"]):
                talk.say(line)
        elif section.get("button") and not test:
            talk.say(f"To test it on the {_plural(len(fix.aside_ids), 'answer')} set aside "
                     f"(free): {talk.command('--fix', '--test-pass-mark')}")
    if test:
        talk.say()
        if section is None:
            talk.say("Your judge gives no score with a pass mark, so there is no pass mark to "
                     "test.")
        elif section.get("button") or section.get("test"):
            for line in test_lines(fix.test_pass_mark(section["mark"])):
                talk.say(line)
    talk.say()
    talk.say(f"Saved in {FOLDER}/fix/.")
    return 0


def page_template(ws: Workspace) -> str:
    from judgekeeper.start_page import fix_page

    return fix_page(ws.data().get("description"))


def switch(ws: Workspace, say):
    """For the labeling and review servers: the fix's session, page and result function, or
    None while there is nothing to fix."""

    def go():
        if not ready(ws):
            return None
        fix = Fix(ws)
        if fix.new:
            say(aside_line(fix))
        return fix, page_template(ws), start_review.result_maker(ws, say)

    return go


def finish(fix: Fix, say) -> None:
    c = fix.counts()
    say("")
    say(f"Passed, but you said Fail: {c['passed_but_fail']}. Failed, but you said Pass: "
        f"{c['failed_but_pass']}.")
    section = fix.pass_mark_section() or {}
    if section.get("test"):
        say(section["test"]["lines"][0])
    say(f"Saved in {FOLDER}/fix/.")


def serve_fix(ws: Workspace, port: int, open_browser: bool, say,
              command: str = "judgekeeper start") -> int:
    """Serve the fix page until Ctrl-C or 2 hours idle."""
    from judgekeeper.label import make_server

    fix = Fix(ws)
    server = make_server(fix, port, result=start_review.result_maker(ws, say),
                         page=page_template(ws), switches={"/fix": switch(ws, say)})
    print(f"Fix page: {server.url}")  # not scrubbed: the token must stay whole
    say(f"Press Ctrl-C here to stop; run {command} --fix to come back.")
    sys.stdout.flush()
    if open_browser:
        webbrowser.open(server.url)
        say("Opened in your browser.")
    try:
        server.serve()
    except KeyboardInterrupt:
        pass
    finish(Fix(ws), say)
    return 0


def run(ws: Workspace, talk, port: int, open_browser: bool, test: bool = False) -> int:
    """`judgekeeper start --fix`, or the menu's choice."""
    from judgekeeper import start

    if not start_review.count(ws):
        talk.say(NOTHING)
        return 0
    if not review_done(ws):
        talk.say(f"Look again at where you disagree first: {talk.command('--review')}")
        return start.EXIT_USAGE
    if not ready(ws):
        talk.say(NOTHING)
        return 0
    fix = Fix(ws)
    if fix.new:
        talk.say()
        talk.say(aside_line(fix))
    if test or not open_browser:
        return _terminal(fix, talk, test)
    return serve_fix(ws, port, open_browser, talk.say, talk.command())


__all__ = ["Fix", "final_marks", "pattern_lines", "ready", "run", "serve_fix", "sign_test",
           "split", "switch", "test_sentence"]
