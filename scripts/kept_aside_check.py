"""How often `judgekeeper fix` says better, safe to try, can't tell yet or worse: by simulation.

    python scripts/kept_aside_check.py     # writes docs/examples/kept-aside/

`fix` keeps half the marks aside and tests a new rule on them only. This script checks what
that test says, for a given number of marks, on made-up cases where the truth is known. How
many marks a clear answer needs depends on how much the new rule changes, so the new rules
range from small changes to large ones.

One made-up case: `marks` answers are marked, half of them passed by the LLM-as-a-judge and
half failed (as `judgekeeper` picks them). The person agrees with the LLM-as-a-judge on each
with chance `agree`. judgekeeper's own split (fix.make_split: half of each cell kept aside,
rounded up, at least 5 Pass and 5 Fail) picks the marks kept aside. On those, the new rule
fixes each of the LLM-as-a-judge's mistakes with chance `fixes` and breaks each answer it got
right with chance `breaks`. judgekeeper's own verdict (targets.fix_verdict, the first test on
these marks) says what `fix` would print.

The new rules (fixes, breaks): each of FIXES with each of BREAKS; two worse rules that fix
nothing and break WORSE; and one with no real change, which fixes 1 in 10 mistakes and breaks
as many right answers on average (a rule that changes no grade at all is not a test: `fix`
asks for the results from after the change).

REAL is one real run of `fix` on a corrected rule, per eval tool; its counts go through the
same verdict, and LIKE_REAL names the row closest to it.

CASES made-up cases per row, each row with its own fixed seed. No AI call. Standard library
only, one process; it takes a few minutes.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from judgekeeper import fix, targets

OUT = ROOT / "docs" / "examples" / "kept-aside"
SEED = 20261027
CASES = 20_000
MARKS = (30, 50, 80, 120)
AGREE = (0.70, 0.80, 0.90)
FIXES = (0.10, 0.25, 0.50, 0.90)
BREAKS = (0.0, 0.02, 0.05)
WORSE = (0.10, 0.25)
SAME = "no real change"
KINDS = ("better", "safe", "cant", "worse")
CLEAR = 0.5  # "most of the time": a clear answer (not "can't tell yet") in more than half
# One real end-to-end run at 80 marks, Claude Haiku as the LLM-as-a-judge: per eval tool, how
# often the old rule agreed with the marks, and on the marks kept aside its mistakes, and how
# many the corrected rule fixed and broke. The mistakes kept aside are estimates from the
# measured agreement (the run did not print them); fixed and broke were printed by `fix`.
REAL_MARKS = 80
REAL = [("promptfoo", 0.72, 11, 11, 0), ("DeepEval", 0.75, 10, 10, 0),
        ("MLflow", 0.65, 14, 13, 1), ("a CSV of its own", 0.66, 14, 13, 0)]
LIKE_REAL = (80, 0.70, "fixes 90%, breaks 2%")  # marks, agree, rule
BIG, QUARTER = "fixes 90%, breaks 2%", "fixes 25%, breaks 2%"  # the rules the README names
SLIPS = "fixes 0%, breaks 10%"  # a worse rule that is hard to catch


def rules() -> list[str]:
    return ([f"fixes {f:.0%}, breaks {b:.0%}" for f in FIXES for b in BREAKS]
            + [f"fixes 0%, breaks {b:.0%}" for b in WORSE] + [SAME])


def rates(rule: str, agree: float) -> tuple[float, float]:
    """(fixes, breaks) of a new rule on an LLM-as-a-judge that agrees with the person `agree`
    of the time."""
    if rule == SAME:
        return 0.10, 0.10 * (1 - agree) / agree
    fixes, breaks = (float(part.split()[1].rstrip("%")) / 100 for part in rule.split(", "))
    return fixes, breaks


def change(rule: str, agree: float) -> float:
    """The new rule's true change in agreement with the person, in points."""
    fixes, breaks = rates(rule, agree)
    return 100 * (fixes * (1 - agree) - breaks * agree)


def one_case(marks: int, agree: float, fixes: float, breaks: float,
             rng: random.Random) -> tuple[str, int]:
    """fix's verdict on one made-up case, and how many marks it kept aside."""
    judge = {f"a{i}": "pass" if i < marks // 2 else "fail" for i in range(marks)}
    other = {"pass": "fail", "fail": "pass"}
    person = {i: g if rng.random() < agree else other[g] for i, g in judge.items()}
    _, hidden = fix.make_split(SimpleNamespace(person=person, judge=judge, batch={}),
                               rng.getrandbits(32))
    fixed = broke = 0
    for i in hidden:
        if judge[i] != person[i]:
            fixed += rng.random() < fixes
        else:
            broke += rng.random() < breaks
    kind = targets.fix_verdict(fixed, broke, len(hidden)).kind
    return (kind if kind in KINDS else "cant"), len(hidden)


def row(marks: int, agree: float, rule: str, seed: int) -> dict:
    rng = random.Random(seed)
    fixes, breaks = rates(rule, agree)
    counts = dict.fromkeys(KINDS, 0)
    kept = 0
    for _ in range(CASES):
        kind, n = one_case(marks, agree, fixes, breaks, rng)
        counts[kind] += 1
        kept += n
    return {"marks": marks, "agree": agree, "rule": rule, "fixes": fixes,
            "breaks": round(breaks, 6), "change": round(change(rule, agree), 2),
            "kept_aside": round(kept / CASES, 1), "seed": seed, "counts": counts,
            "like_real": (marks, agree, rule) == LIKE_REAL,
            **{k: round(100 * v / CASES, 1) for k, v in counts.items()}}


def real() -> list[dict]:
    """The real run's counts through the same verdict (kept aside: half of the marks)."""
    kept = REAL_MARKS // 2
    return [{"tool": tool, "agree": agree, "mistakes_kept_aside": mistakes, "fixed": fixed,
             "broke": broke, "kept_aside": kept,
             "verdict": targets.fix_verdict(fixed, broke, kept).kind}
            for tool, agree, mistakes, fixed, broke in REAL]


def commit() -> str:
    """The commit this ran on, short, and whether src/ or scripts/ had changes on top."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts"],
                               cwd=ROOT, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + (" with changes" if dirty.strip() else "")


def run() -> dict:
    rows = []
    for a, agree in enumerate(AGREE):
        for m, marks in enumerate(MARKS):
            for r, rule in enumerate(rules()):
                rows.append(row(marks, agree, rule, SEED + 1000 * a + 100 * m + r))
    return {"seed": SEED, "cases": CASES, "commit": commit(),
            "hidden_tenths": fix.HIDDEN_TENTHS, "min_each": fix.MIN_EACH, "rows": rows,
            "needed": needed(rows), "real": real(), "summary": summary(rows)}


def _clear(r: dict) -> float:
    return 100 - r["cant"]


def needed(rows: list[dict]) -> dict:
    """Per rule: the fewest marks tried at which `fix` gives a clear answer most of the time
    at every agreement tried (None: not even at the most), and there how often it says each
    (low and high over the agreements)."""
    out = {}
    for rule in rules():
        at = next((m for m in MARKS if all(_clear(r) > 100 * CLEAR for r in rows
                                           if (r["rule"], r["marks"]) == (rule, m))), None)
        there = [r for r in rows if (r["rule"], r["marks"]) == (rule, at)]
        out[rule] = {"marks": at, **{k: [min(r[k] for r in there), max(r[k] for r in there)]
                                     if there else None for k in KINDS}}
    return out


def summary(rows: list[dict]) -> dict:
    """Never a false "better" or a false "worse", from the counts; and the row like the real
    run."""
    like = next(r for r in rows if r["like_real"])
    worse = [r for r in rows if (r["rule"], r["marks"]) == (SLIPS, MARKS[-1])]
    return {"worse_at_most": {k: [min(r[k] for r in worse), max(r[k] for r in worse)]
                              for k in KINDS},
            "quarter": {"rule": QUARTER, **needed(rows)[QUARTER]},"never_false_better": all(not r["counts"]["better"] for r in rows
                                      if r["change"] <= 0),
            "never_false_worse": all(not r["counts"]["worse"] for r in rows
                                     if r["change"] >= 0),
            "false_better": max(r["better"] for r in rows if r["change"] <= 0),
            "false_worse": max(r["worse"] for r in rows if r["change"] >= 0),
            "like_real": {k: like[k] for k in ("marks", "agree", "rule", *KINDS)}}


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _span(s: list[float]) -> str:
    return f"{s[0]:.1f}" if s[0] == s[1] else f"{s[0]:.1f} to {s[1]:.1f}"


def _marks(n: int | None) -> str:
    return f"more than {MARKS[-1]}" if n is None else str(n)


def sentences(result: dict) -> list[str]:
    """The plain sentences at the top of the report."""
    need, s = result["needed"], result["summary"]
    big, quarter = need[BIG], need[QUARTER]
    like = s["like_real"]
    out = [(f"A new rule that fixes almost all of the LLM-as-a-judge's mistakes (9 in 10) and "
            f"breaks 2 in 100 of its right answers gets a clear answer (not \"can't tell "
            f"yet\") most of the time from {_marks(big['marks'])} marks; one that fixes a "
            f"quarter needs {_marks(quarter['marks'])}; one that fixes 1 in 10 and breaks 5 in "
            f"100 needs {_marks(need['fixes 10%, breaks 5%']['marks'])}.")]
    if quarter["marks"] is not None:
        out.append(f"With {quarter['marks']} marks, the quarter rule reads \"safe to try\" in "
                   f"{_span(quarter['safe'])} cases in 100 and \"better\" in "
                   f"{_span(quarter['better'])}.")
    out.append(f"In the row like a real fix we saw ({like['marks']} marks, the old rule "
               f"agreeing {_pct(like['agree'])} of the time, {like['rule']}), `fix` says "
               f"\"better\" in {like['better']:.1f} cases in 100 and \"safe to try\" in "
               f"{like['safe']:.1f}.")
    if s["never_false_better"] and s["never_false_worse"]:
        out.append("A rule that is truly the same or worse is never called \"better\", and one "
                   "that is truly the same or better is never called \"worse\".")
    else:
        out.append(f"A rule that is truly the same or worse is called \"better\" in at most "
                   f"{s['false_better']:.1f} cases in 100, and one that is truly the same or "
                   f"better is called \"worse\" in at most {s['false_worse']:.1f}.")
    w = s["worse_at_most"]
    out.append(f"A worse rule can still slip through: one that fixes nothing and breaks 1 in 10 "
               f"right answers is caught (\"worse\") in only {_span(w['worse'])} cases in 100 "
               f"with {MARKS[-1]} marks, and reads \"safe to try\" (not more than 10 points "
               f"worse) in {_span(w['safe'])}.")
    return out


def markdown(result: dict) -> str:
    agrees = ", ".join(_pct(a) for a in AGREE[:-1]) + f" or {_pct(AGREE[-1])}"
    lines = ["# What `fix` says on made-up new rules", "",
             "Written by `scripts/kept_aside_check.py`; do not edit by hand.", "",
             (f"`judgekeeper fix` keeps half of each group of marks aside (rounded up, at least "
              f"{result['min_each']} Pass and {result['min_each']} Fail) and tests a new rule on "
              "those only. Here, made-up cases go through judgekeeper's own split and its own "
              "verdict, with new rules whose true effect is known. How many marks a clear "
              "answer needs depends on how much better or worse the new rule is: small "
              "improvements need many more marks. "
              f"{result['cases']:,} made-up cases per row, seed {result['seed']}, commit "
              f"`{result['commit']}`. No AI call."), "",
             "## The result", "", " ".join(sentences(result)), "",
             "## Marks for a clear answer", "",
             ("The fewest marks tried (" + ", ".join(map(str, MARKS)) + ") at which `fix` "
              "gives a clear answer most of the time, whether the LLM-as-a-judge agrees with "
              f"the person {agrees} of the time, and there how often it says each, in 100 "
              "cases (low to high over the agreements). New rule: of the answers kept aside, "
              "the share of the LLM-as-a-judge's mistakes it fixes and the share of its right "
              "answers it breaks."), "",
             "| New rule | Marks | Better | Safe to try | Can't tell yet | Worse |",
             "|---|---|---|---|---|---|"]
    for rule, n in result["needed"].items():
        if n["marks"] is None:
            lines.append(f"| {rule} | {_marks(None)} | | | | |")
        else:
            lines.append(f"| {rule} | {n['marks']} | "
                         + " | ".join(_span(n[k]) for k in KINDS) + " |")
    like = result["summary"]["like_real"]
    lines += ["", "## One real run", "",
              (f"One real end-to-end run, {REAL_MARKS} marks, Claude Haiku as the "
               "LLM-as-a-judge, an old rule that was clearly wrong, and a corrected rule. "
               "`fix` printed how many answers kept aside the new rule fixed and broke. The "
               "old rule's mistakes kept aside are estimates from how often it agreed with the "
               "marks (the run did not print them). Each line goes through the same verdict as "
               "the rows below."), "",
              ("| Eval tool | Old rule agrees | Its mistakes kept aside (about) | Fixed "
               "| Broke | Verdict |"),
              "|---|---|---|---|---|---|"]
    for r in result["real"]:
        lines.append(f"| {r['tool']} | {_pct(r['agree'])} | {r['mistakes_kept_aside']} | "
                     f"{r['fixed']} | {r['broke']} | {r['verdict']} |")
    lines += ["", (f"This is one real run, not a law: a large fix of a clearly wrong rule. The "
                   f"row marked \"like a real fix we saw\" below is the closest made-up case "
                   f"({like['marks']} marks, {_pct(like['agree'])}, {like['rule']})."), "",
              "## How often `fix` says each, in 100 cases", "",
              ("True change: the points of agreement with the person the new rule really gains "
               "or loses. Agrees: how often the LLM-as-a-judge agrees with the person. Kept "
               "aside: the marks kept aside, on average."), "",
              ("| Marks | Agrees | New rule | True change | Kept aside | Better | Safe to try "
               "| Can't tell yet | Worse |"),
              "|---|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        name = r["rule"] + (" (like a real fix we saw)" if r["like_real"] else "")
        lines.append(f"| {r['marks']} | {_pct(r['agree'])} | {name} | "
                     f"{r['change']:+.1f} | {r['kept_aside']:.0f} | "
                     + " | ".join(f"{r[k]:.1f}" for k in KINDS) + " |")
    lines += ["", ("Can't tell yet counts all three of its kinds (leans better, looks the same, "
                   "leans worse). Each row is one first test on a new set of marks kept aside; "
                   "later tests on the same marks are stricter.")]
    return "\n".join(lines) + "\n"


def main() -> None:
    result = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(markdown(result), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}/report.md")


if __name__ == "__main__":
    main()
