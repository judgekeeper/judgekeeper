"""Fix your judge, after the review of the disagreements. No AI call and no key.

The person's final mark for an answer is their second look (Pass or Fail) when they gave
one in the review, else their first mark; "I was wrong" makes it the judge's verdict, and an
answer they were not sure about on the second look is left out. A mistake is an answer whose
final mark differs from the judge's saved verdict (not counting those marked "The rule is
unclear", which have a box of their own). The main result keeps the first labels.

The first time, about 30% of the answers with a final mark are set aside: ceil(30%) of each
of four cells (the judge's pass or fail, times whether it agrees with the final mark), in a
seeded shuffle; a cell of one answer stays in the rest, so a single mistake is still shown. They
are used only to test a change, so the test is fair: nothing from them is shown or counted in a
pattern, and they never go into a prompt. The page shows, from the rest:

- what the judge gets wrong: the two kinds of mistakes, each a list that folds open, and plain
  patterns in them (too easy or too strict, close to the pass mark, long answers, words that
  stand out), only when they are strong;
- for a judge whose decisions are a score held against a pass mark: the pass mark that fits
  the person's marks best, and a free test of it on the answers set aside.

A test says how many of the set-aside answers the change fixed and broke, with an exact sign
test on the two, and the two agreement numbers before and after, with no range. Rounding up per
cell sets aside more of the few disagreements than of the many agreed answers, so the numbers on
either part weigh each answer by its cell (cell_weights), not only its group. After 3 tests on
one split, the answers set aside no longer give a fair test.

- for a judge with one rule: changing it, with a prompt for any AI assistant (start_fix_rule).
  A new judge is then tested on the answers set aside inside Try your new judge
  (new_judge_test).

`.judgekeeper/` gains fix.json (the result it is of, the seed, the two parts, the tests) and
fix/ (patterns.json: the counts and the pattern lines; pass-mark.json: the pass-mark test;
prompt.txt, rule.txt and rule.json: the prompt, the new rule, its checks and hand-over), and
result.json a `fix` block. A new result moves fix.json and fix/ to history/fix-<date>/.
judgekeeper never edits the person's own files: it only says where the pass mark or the rule
probably is.
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
from collections import Counter
from pathlib import Path

from judgekeeper import start_fix_rule, start_review, weighted
from judgekeeper.fingerprint import utc_now
from judgekeeper.judgments import read_run
from judgekeeper.redact import scrub
from judgekeeper.start_label import (
    FOLDER,
    Workspace,
    _write_json,
    display,
    question_view,
    say_opened,
)
from judgekeeper.textio import jsonl_lines, write_replacing

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
# Folders never searched: environments, judgekeeper's own, and where eval tools keep their
# results (DeepEval's runs, MLflow's folder store, Inspect's logs)
SEARCH_SKIP = {".venv", "venv", "node_modules", ".git", ".judgekeeper", "__pycache__",
               ".deepeval", "mlruns", "logs"}
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
    """(used ids, set-aside ids): ceil(30%) of each of the four cells set aside, except a cell
    of one answer, which stays in the used part."""
    rng = random.Random(seed)
    used, aside = [], []
    for judge in ("pass", "fail"):
        for agrees in (True, False):
            ids = sorted(m["id"] for m in marks
                         if m["judge"] == judge and (m["final"] == judge) == agrees)
            rng.shuffle(ids)
            n = -(-len(ids) * ASIDE_TENTHS // 10) if len(ids) > 1 else 0
            aside += ids[:n]
            used += ids[n:]
    return used, aside


def cell(m: dict) -> tuple[str, bool]:
    """The cell of a final mark: the judge's group, and whether the judge agrees with it."""
    return m["judge"], m["judge"] == m["final"]


def cell_weights(marks: list[dict], part: list[dict], pool: dict) -> dict:
    """The weight of an answer in each cell of `part` (the used or the set-aside answers of
    `marks`): the pool's group size times the cell's share of the group's marks, over the
    cell's answers in the part. The numbers on the part are then those of all the marks."""
    labeled = Counter(cell(m) for m in marks)
    groups = Counter(m["judge"] for m in marks)
    here = Counter(cell(m) for m in part)
    return {c: pool[c[0]] * labeled[c] / groups[c[0]] / k for c, k in here.items()}


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
        lines.append(f"{passes} of its {n} mistakes are answers it passed but you failed. Its "
                     "rule may be too easy.")
    elif fails > passes:
        lines.append(f"{fails} of its {n} mistakes are answers it failed but you passed. Its "
                     "rule may be too strict.")
    else:
        lines.append(f"Half of its {n} mistakes are answers it passed but you failed, and half "
                     "are answers it failed but you passed.")
    if mark is not None:
        near = sum(m.get("score") is not None and abs(m["score"] - mark) <= NEAR + 1e-9
                   for m in wrong)
        if near * 2 > n:
            lines.append(f"{near} of its {n} mistakes sit close to the pass mark. Moving the "
                         "pass mark may fix them.")
    for judge, final, name in (("fail", "pass", "wrong fails"), ("pass", "fail",
                                                                 "wrong passes")):
        side = [len(m["output"].split()) for m in wrong if m["judge"] == judge]
        agreed = [len(m["output"].split()) for m in rows
                  if m["judge"] == m["final"] == final]
        if len(side) < LONG_SIDE or len(agreed) < FEW:
            continue
        long, usual = statistics.median(side), statistics.median(agreed)
        if usual > 0 and long >= LONG * usual:
            lines.append(f"Its {name} are long answers (about {_about(long)} words, against "
                         f"{_about(usual)}).")
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
            lines.append("Words that show up in many of its mistakes: " + ", ".join(
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
    if source == "pass_if":  # double quotes work in Windows cmd too
        rule = re.sub(rf"{_NUMBER}\s*$", m, pm.get("rule") or f"score{pm['op']}0")
        return [f'Use --pass-if "{rule}".']
    # a pass mark kept with each verdict, read from another tool's files
    return [(f"Set pass_mark={m} in your judgekeeper.record() line, or pass_mark = {m} in "
             "judgekeeper.toml [start].")]


def searched(pm: dict) -> str | None:
    """The name the pass mark is set with in the project's files, or None when it is not
    set in them (--pass-if, or a key a mapped file states it in)."""
    if pm["source"] == "pass_if" or (pm["source"] == "mapped" and pm.get("key")):
        return None
    return "threshold" if pm["source"] == "deepeval" else "pass_mark"


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
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir():
                        if e.name not in SEARCH_SKIP:
                            folders.append(Path(e.path))
                        continue
                    small = e.is_file() and e.stat().st_size <= SEARCH_MAX_BYTES
                except OSError:  # gone, or not ours to look at
                    continue
                if small:
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
        return (f"On the {n} answers kept aside, the change did better: it fixed {fixed} and "
                f"broke {broke or 'none'}.")
    if kind == "worse":
        return (f"On the {n} answers kept aside, the change did worse: it fixed {fixed} and "
                f"broke {broke}. Keep what you have.")
    return (f"Can't tell yet: on the {n} answers kept aside, the change fixed {fixed} and broke "
            f"{broke}. That is too few to be sure. Mark more answers to find out.")


def _pct(value) -> str:
    return "unknown" if value is None else f"{value:.0%}"


# The session the page reads -------------------------------------------------------------

class Fix:
    """The fix of one result: the split (made once), the patterns, the pass mark and its
    test. The page gets only the used answers; the set-aside ones only as counts."""

    def __init__(self, ws: Workspace):
        self.workspace = ws
        self.out = ws.dir / "fix.json"
        self.folder = ws.dir / "fix"
        self.by_id: dict = {}  # nothing on this page is labeled
        self.posts = {"/fix/pass-mark": self._post_pass_mark, "/fix/prompt": self._post_prompt,
                      "/fix/rule": self._post_rule}
        # a body too big for the server to read, on a path: what to say
        self.too_long = {"/fix/rule": start_fix_rule.TOO_LONG}
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
        self.data = data
        self.tool = data.get("tool") or ""
        self.one_rule = data.get("one_rule", True)  # checks made before it was kept: one
        self.raw = {}
        for line in jsonl_lines(ws.pool.read_text(encoding="utf-8")):
            if line.strip():
                row = json.loads(line)
                self.raw[row["id"]] = row
        _, records = read_run(ws.pool_judge)
        self.reasons = {i: scrub(r.get("rationale") or "") for i, r in records.items()}
        self.scores = {i: r.get("raw_score") for i, r in records.items()}
        self.write_patterns()
        self._sync_result()

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
        n = len(self.aside_ids)
        return (f"judgekeeper kept {n} of your answers aside. "
                f"{'It tests' if n == 1 else 'They test'} whether a change really helps, so "
                f"{'it is' if n == 1 else 'they are'} not shown here.")

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

    def refusal(self, ids: list[str] | None = None) -> str | None:
        """Why no change can be tested on this split (on `ids` of it, by default all the
        answers set aside), or None."""
        n = len(self.aside_ids)
        tests = len(self.saved["tests"])
        if tests >= MAX_TESTS:
            return (f"You have tested {tests} changes on the same {n} answers, so they no "
                    "longer give a fair test. Mark new answers to test more.")
        finals = [self.marks[i]["final"] for i in (self.aside_ids if ids is None else ids)]
        short = [f"{finals.count(v)} {SAID[v]}" for v in ("pass", "fail")
                 if finals.count(v) < MIN_EACH]
        if short:
            return (f"Too few answers kept aside to test a change fairly: it needs {MIN_EACH} "
                    f"you marked Pass and {MIN_EACH} you marked Fail (you have "
                    f"{' and '.join(short)}). Mark more answers first.")
        return None

    def _weights(self, ids) -> dict:
        return cell_weights(list(self.marks.values()), [self.marks[i] for i in ids], self.pool)

    def suggested(self) -> float:
        items = [(cell(self.marks[i]), self.marks[i]["final"], self.scores[i])
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
        elif section["kind"] == "suggest":
            refusal = self.refusal()
            if refusal:
                section["refusal"] = refusal
            else:
                section["button"] = (f"Test {_mark(mark)} on the "
                                     f"{_plural(len(self.aside_ids), 'answer')} kept aside")
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
        if section["kind"] != "suggest" or mark != section["mark"]:
            raise ValueError("only the suggested pass mark can be tested")
        if section.get("refusal"):
            raise ValueError(section["refusal"])
        old_mark, op = self.pm["mark"], self.pm["op"]
        new = {i: passes(self.scores[i], op, mark) for i in self.aside_ids}
        test = self.fair_test(new)
        hand_over = where_lines(self.pm, mark)
        name = searched(self.pm)
        found = name and locate(self.workspace.root, name, old_mark)
        if found:  # a line of the person's own file: scrubbed before it is saved or shown
            hand_over.append(scrub(f"Probably in {found[0]}, line {found[1]}: {found[2]}"))
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

    def fair_test(self, new: dict[str, str], old: dict[str, str] | None = None,
                  ids: list[str] | None = None) -> dict:
        """Old decisions (the saved verdicts, or `old`) against `new` ones on the set-aside
        answers (or `ids` of them): fixed and broke, and the two agreement numbers before and
        after, weighted by cell (the saved verdict's), with no range."""
        ids = self.aside_ids if ids is None else ids
        aside = [self.marks[i] for i in ids]
        was = {m["id"]: (old or {}).get(m["id"], m["judge"]) for m in aside}
        fixed = sum(was[m["id"]] != m["final"] and new[m["id"]] == m["final"] for m in aside)
        broke = sum(was[m["id"]] == m["final"] and new[m["id"]] != m["final"] for m in aside)
        n = len(aside)
        weights = self._weights(ids)
        before = weighted._table([(cell(m), m["final"], was[m["id"]]) for m in aside], weights)
        after = weighted._table([(cell(m), m["final"], new[m["id"]]) for m in aside], weights)
        numbers = [f"When you said {said}, your judge also said {said}: {_pct(before[key])} → "
                   f"{_pct(after[key])}" for key, said in (("tpr", "Pass"), ("tnr", "Fail"))]
        return {"kind": test_kind(fixed, broke), "n": n, "fixed": fixed, "broke": broke,
                "p": sign_test(fixed, broke),
                "lines": [test_sentence(n, fixed, broke), SMALL], "numbers": numbers}

    def _record(self, change: str, kind: str, test: dict) -> None:
        self.saved["tests"].append({"kind": kind, "made_at": utc_now(), "change": change,
                                    "fixed": test["fixed"], "broke": test["broke"],
                                    "p": test["p"], "result": test["kind"],
                                    "sentence": test["lines"][0]})
        _write_json(self.out, self.saved)
        self._sync_result()

    def _sync_result(self) -> None:
        """Put the fix block (counts and tests) in result.json and redraw result.html. The
        main result does not change."""
        from judgekeeper.start_label import _scrubbed, result_html

        ws = self.workspace
        r = json.loads(ws.result_json.read_text(encoding="utf-8"))
        r["fix"] = {"counts": self.counts(), "used": len(self.used_ids),
                    "aside": len(self.aside_ids), "tests": self.saved["tests"]}
        _write_json(ws.result_json, r)
        write_replacing(ws.result_html, result_html(_scrubbed(r)))

    def _old_decisions(self) -> dict[str, str]:
        """The old judge's decisions asked again, when that was done for this result: from
        the first run file of result.json's `again` folder."""
        r = json.loads(self.workspace.result_json.read_text(encoding="utf-8"))
        folder = (r.get("again") or {}).get("folder")
        path = self.workspace.root / folder / "judge-again-1.jsonl" if folder else None
        if path is None or not path.is_file():
            return {}
        _, records = read_run(path)
        return {i: rec["verdict"] for i, rec in records.items()
                if rec.get("verdict") in ("pass", "fail")}

    def test_new_judge(self, new: dict[str, str], change: str) -> dict:
        """The fair test of a new judge (Try your new judge) on the set-aside answers it
        decided: counted in the tests unless refused. Old decisions are the old judge's
        asked again, when it was, else the saved verdicts."""
        ids = [i for i in self.aside_ids if new.get(i) in ("pass", "fail")]
        refusal = self.refusal(ids)
        if refusal:
            return {"kind": "refused", "lines": [refusal]}
        test = self.fair_test(new, self._old_decisions(), ids)
        if (self._saved_rule() or {}).get("how") == "written":
            test["lines"].append(start_fix_rule.HAND_WRITTEN)
        self._record(f"new judge: {change}", "rule", test)
        return {k: test[k] for k in ("kind", "n", "fixed", "broke", "p", "lines", "numbers")}

    # Change the rule ----------------------------------------------------------------------

    def _text(self, m: dict) -> dict:
        raw = self.raw.get(m["id"], {})
        return {**m, "input": display(raw.get("input")), "output": display(raw.get("output")),
                "reason": self.reasons.get(m["id"], "")}

    def _rule_problem(self) -> str | None:
        if not self.rule:
            return start_fix_rule.UNKNOWN
        if not self.one_rule:
            return start_fix_rule.PER_TEST
        return None

    def prompt(self) -> str:
        """The prompt for an AI assistant, from the used answers only; saved (scrubbed) in
        fix/prompt.txt."""
        problem = self._rule_problem()
        if problem:
            raise ValueError(problem)
        rows = [self._text(self.marks[i]) for i in self.used_ids]
        agreed = [m for m in rows if m["judge"] == m["final"]
                  and m.get("choice") != "rule_unclear"]
        text = scrub(start_fix_rule.build_prompt(self.rule, self.tool, mistakes(rows),
                                                 unclear(rows), agreed))
        self.folder.mkdir(exist_ok=True)
        write_replacing(self.folder / "prompt.txt", text)
        return text

    def _saved_rule(self) -> dict | None:
        path = self.folder / "rule.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def save_rule(self, text: str, how: str) -> dict:
        """Check the new rule (pasted from an AI assistant, or written by hand) and save it
        in fix/rule.txt and rule.json unless a check blocks it: {"saved", "checks"}."""
        if how not in ("pasted", "written"):
            raise ValueError("how must be pasted or written")
        if not isinstance(text, str):
            raise TypeError("the rule must be text")
        if len(text) > start_fix_rule.MAX_PASTE:
            raise ValueError(start_fix_rule.TOO_LONG)
        problem = self._rule_problem()
        if problem:
            raise ValueError(problem)
        old = start_fix_rule.rule_text(self.rule, self.tool)
        new = scrub(start_fix_rule.new_rule_of(text))
        if len(new) > start_fix_rule.MAX_RULE:
            raise ValueError(f"The new rule is too long: at most {start_fix_rule.MAX_RULE:,} "
                             "characters.")
        outputs = [display(self.raw.get(i, {}).get("output")) for i in self.used_ids]
        found = start_fix_rule.checks(old, new, self.tool, outputs)
        if any(c["blocking"] for c in found):
            return {"saved": False, "checks": found}
        self.folder.mkdir(exist_ok=True)
        write_replacing(self.folder / "rule.txt", new + "\n")
        hand = start_fix_rule.hand_over(self.workspace.root, self.data, self.rule, new,
                                        len(self.aside_ids))
        _write_json(self.folder / "rule.json", {
            "made_at": utc_now(), "how": how, "old": old, "new": new, "checks": found,
            "hand_over": hand})
        return {"saved": True, "checks": found}

    def rule_change(self) -> dict:
        """The page's "Change the rule" section."""
        problem = self._rule_problem()
        if problem:
            return {"kind": "unknown" if not self.rule else "per_test", "text": problem}
        old = start_fix_rule.rule_text(self.rule, self.tool)
        saved = self._saved_rule()
        if saved is not None:
            saved = {"rule": saved["new"], "how": saved["how"], "checks": saved["checks"],
                     "diff": start_fix_rule.word_diff(saved["old"], saved["new"]),
                     "hand_over": saved["hand_over"]}
        return {"kind": "ok", "rule": old, "steps": self.tool == "deepeval", "saved": saved,
                "max_paste": start_fix_rule.MAX_PASTE}

    def _post_prompt(self, body: dict) -> dict:
        return {"prompt": self.prompt()}

    def _post_rule(self, body: dict) -> dict:
        result = self.save_rule(body.get("text"), body.get("how"))
        return {"result": result, "rule_change": self.rule_change()}

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
                "aside": self.aside_note(), "pass_mark": self.pass_mark_section(),
                "rule_change": self.rule_change()}

    def summary(self) -> dict:
        return {"done": False}  # the page stays until Ctrl-C


# The terminal -----------------------------------------------------------------------------

def aside_line(fix: Fix) -> str:
    return (f"judgekeeper kept {len(fix.aside_ids)} of your {len(fix.marks)} marked answers "
            "aside. They test whether a change really helps, so they are not shown, and they "
            "never go into a prompt.")


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
            talk.say(f"To test it on the {_plural(len(fix.aside_ids), 'answer')} kept aside "
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


def new_judge_test(ws: Workspace, new: dict[str, str], change: str) -> dict | None:
    """For Try your new judge: the fair test on the answers set aside, when Fix your judge
    set some aside for this result; else None (no split is made here)."""
    path = ws.dir / "fix.json"
    if not path.is_file():
        return None
    if json.loads(path.read_text(encoding="utf-8")).get("basis") != start_review._basis(ws):
        return None
    return Fix(ws).test_new_judge(new, change)


def result_lines(block: dict) -> list[str]:
    """The fix block of result.json in words: the two counts and the latest test."""
    c = block["counts"]
    lines = [(f"On the {block['used']} answers judgekeeper used: Passed, but you said Fail: "
              f"{c['passed_but_fail']}. Failed, but you said Pass: {c['failed_but_pass']}.")]
    tests = block.get("tests") or []
    if tests and tests[-1].get("sentence"):
        lines.append(f"Latest test ({tests[-1]['change']}): {tests[-1]['sentence']}")
    return lines


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
    say_opened(server.url, open_browser, say, command, " --fix")
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
