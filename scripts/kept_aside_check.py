"""How often `judgekeeper fix` says better, safe to try, can't tell yet or worse: by simulation.

    python scripts/kept_aside_check.py     # writes docs/examples/kept-aside/

`fix` keeps half the marks aside and tests a new rule on them only. This script checks what
that test says, for a given number of marks, on made-up cases where the truth is known. How
many marks a clear answer needs depends on how much the new rule changes, so the new rules
range from small changes to large ones.

One made-up case: the LLM-as-a-judge passed a share `pi` of POOL answers. `marks` of them are
marked as the marking page offers them (start_label.build_queue): 15 it passed and 15 it
failed first, then in the pool's own mix. The person agrees with the LLM-as-a-judge on each
with chance `agree`. judgekeeper's own split (fix.make_split: half of each cell kept aside,
rounded up, at least 5 Pass and 5 Fail) picks the marks kept aside. On those, the new rule
fixes each of the LLM-as-a-judge's mistakes with chance `fixes` and breaks each answer it got
right with chance `breaks`. judgekeeper's own verdict (targets.fix_verdict, the first test on
these marks, each weighted to the pool by its group) says what `fix` would print.

The new rules (fixes, breaks): each of FIXES with each of BREAKS; two worse rules that fix
nothing and break WORSE; one with no real change, which fixes 1 in 10 mistakes and breaks as
many right answers on average (a rule that changes no grade at all is not a test: `fix` asks
for the results from after the change); and LOPSIDED, a rule that fixes 9 in 10 of the
mistakes among the answers the LLM-as-a-judge failed but breaks 1 in 4 right answers among
the ones it passed: far better on the marks, which hold many of its fails, than on the pool.

LARGE names one row the README quotes: a large fix of a clearly wrong rule.

CASES made-up cases per row, each row with its own fixed seed. No AI call. Standard library
only, one process; it takes a few minutes.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from judgekeeper import fix, targets

OUT = ROOT / "docs" / "examples" / "kept-aside"
SEED = 20261027
CASES = 20_000
MARKS = (30, 50, 80, 120, 160, 200)
AGREE = (0.70, 0.80, 0.90)
PIS = (0.5, 0.8)  # the share of the pool the LLM-as-a-judge passed
POOL = 10_000
FIRST = 15  # marks of each grade the page offers first (targets.ROUGH)
FIXES = (0.10, 0.25, 0.50, 0.90)
BREAKS = (0.0, 0.02, 0.05)
WORSE = (0.10, 0.25)
SAME = "no real change"
KINDS = ("better", "safe", "cant", "worse")
CLEAR = 0.5  # "most of the time": a clear answer (not "can't tell yet") in more than half
LARGE = (80, 0.70, 0.5, "fixes 90%, breaks 2%")  # marks, agree, pi, rule
BIG, QUARTER = "fixes 90%, breaks 2%", "fixes 25%, breaks 2%"  # the rules the README names
SLIPS = "fixes 0%, breaks 10%"  # a worse rule that is hard to catch
LOPSIDED = "fixes 90% of its fails' mistakes, breaks 25% of its passes' right answers"


def rules() -> list[str]:
    return ([f"fixes {f:.0%}, breaks {b:.0%}" for f in FIXES for b in BREAKS]
            + [f"fixes 0%, breaks {b:.0%}" for b in WORSE] + [SAME, LOPSIDED])


def rates(rule: str, agree: float) -> dict:
    """{the LLM-as-a-judge's grade: (fixes, breaks)} of a new rule on an LLM-as-a-judge that
    agrees with the person `agree` of the time."""
    if rule == SAME:
        same = (0.10, 0.10 * (1 - agree) / agree)
        return {"pass": same, "fail": same}
    if rule == LOPSIDED:
        return {"pass": (0.0, 0.25), "fail": (0.90, 0.0)}
    fixes, breaks = (float(part.split()[1].rstrip("%")) / 100 for part in rule.split(", "))
    return {"pass": (fixes, breaks), "fail": (fixes, breaks)}


def change(rule: str, agree: float, pi: float) -> float:
    """The new rule's true change in agreement with the person on the pool, in points."""
    r = rates(rule, agree)
    return 100 * sum(share * (r[g][0] * (1 - agree) - r[g][1] * agree)
                     for g, share in (("pass", pi), ("fail", 1 - pi)))


def verdict(fixed: int, broke: int, n: int, strata: list) -> str:
    """What `fix` says: targets.fix_verdict, the first test on these marks."""
    return targets.fix_verdict(fixed, broke, n, strata=strata).kind


def one_case(marks: int, agree: float, pi: float, rule: dict,
             rng: random.Random) -> tuple[str, int]:
    """fix's verdict on one made-up case, and how many marks it kept aside."""
    n_pass = round(pi * POOL)
    passed = min(marks, FIRST + round(pi * (marks - 2 * FIRST))) if marks > 2 * FIRST \
        else marks // 2
    judge = {f"a{i}": "pass" if i < passed else "fail" for i in range(marks)}
    other = {"pass": "fail", "fail": "pass"}
    person = {i: g if rng.random() < agree else other[g] for i, g in judge.items()}
    _, hidden = fix.make_split(SimpleNamespace(person=person, judge=judge, batch={}),
                               rng.getrandbits(32))
    strata = {"pass": [n_pass, 0, 0, 0], "fail": [POOL - n_pass, 0, 0, 0]}
    for i in hidden:
        s = strata[judge[i]]
        fixes, breaks = rule[judge[i]]
        s[3] += 1
        if judge[i] != person[i]:
            s[1] += rng.random() < fixes
        else:
            s[2] += rng.random() < breaks
    rows = [s for s in strata.values() if s[3]]
    kind = verdict(sum(s[1] for s in rows), sum(s[2] for s in rows), len(hidden), rows)
    return (kind if kind in KINDS else "cant"), len(hidden)


def row(args: tuple) -> dict:
    marks, agree, pi, rule, seed = args
    rng = random.Random(seed)
    counts = dict.fromkeys(KINDS, 0)
    kept = 0
    r = rates(rule, agree)
    for _ in range(CASES):
        kind, n = one_case(marks, agree, pi, r, rng)
        counts[kind] += 1
        kept += n
    return {"marks": marks, "agree": agree, "pi": pi, "rule": rule, "fixes": r["fail"][0],
            "breaks": round(r["pass"][1], 6), "change": round(change(rule, agree, pi), 2),
            "kept_aside": round(kept / CASES, 1), "seed": seed, "counts": counts,
            **{k: round(100 * v / CASES, 1) for k, v in counts.items()}}


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
    work = [(marks, agree, pi, rule, SEED + 10_000 * p + 1000 * a + 100 * m + r)
            for p, pi in enumerate(PIS) for a, agree in enumerate(AGREE)
            for m, marks in enumerate(MARKS) for r, rule in enumerate(rules())]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(row, work, chunksize=4))
    return {"seed": SEED, "cases": CASES, "commit": commit(), "pool": POOL, "pis": list(PIS),
            "hidden_tenths": fix.HIDDEN_TENTHS, "min_each": fix.MIN_EACH, "rows": rows,
            "needed": needed(rows), "summary": summary(rows)}


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
    """How often a false "better" or a false "worse" (from the counts), and how far from no
    change the rules it happens to are; a worse rule that slips through; the LARGE row."""
    large = next(r for r in rows if (r["marks"], r["agree"], r["pi"], r["rule"]) == LARGE)
    false = [r for r in rows if (r["change"] <= 0 and r["counts"]["better"])
             or (r["change"] >= 0 and r["counts"]["worse"])]
    worse = [r for r in rows if (r["rule"], r["marks"]) == (SLIPS, MARKS[-1])]
    lop = [r for r in rows if r["rule"] == LOPSIDED and r["change"] < -100 * targets.SAFE_MARGIN]
    return {"worse_at_most": {k: [min(r[k] for r in worse), max(r[k] for r in worse)]
                              for k in KINDS},
            "quarter": {"rule": QUARTER, **needed(rows)[QUARTER]},"never_false_better": all(not r["counts"]["better"] for r in rows
                                      if r["change"] <= 0),
            "never_false_worse": all(not r["counts"]["worse"] for r in rows
                                     if r["change"] >= 0),
            "false_better": max(r["better"] for r in rows if r["change"] <= 0),
            "false_worse": max(r["worse"] for r in rows if r["change"] >= 0),
            "false_within": max((abs(r["change"]) for r in false), default=0.0),
            "large": {k: large[k] for k in ("marks", "agree", "pi", "rule", *KINDS)},
            "lopsided": {"change": [min(r["change"] for r in lop), max(r["change"] for r in lop)],
                         **{k: [min(r[k] for r in lop), max(r[k] for r in lop)] for k in KINDS},
                         "wrong": max(r["safe"] + r["better"] for r in lop)}}


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
    large = s["large"]
    out = [(f"A new rule that fixes almost all of the LLM-as-a-judge's mistakes (9 in 10) and "
            f"breaks 2 in 100 of its right answers gets a clear answer (not \"can't tell "
            f"yet\") most of the time from {_marks(big['marks'])} marks; one that fixes a "
            f"quarter needs {_marks(quarter['marks'])}; one that fixes 1 in 10 and breaks 5 in "
            f"100 needs {_marks(need['fixes 10%, breaks 5%']['marks'])}.")]
    if quarter["marks"] is not None:
        out.append(f"With {quarter['marks']} marks, the quarter rule reads \"safe to try\" in "
                   f"{_span(quarter['safe'])} cases in 100 and \"better\" in "
                   f"{_span(quarter['better'])}.")
    out.append(f"A large fix of a clearly wrong rule (one that fixes about 9 in 10 of the "
               f"mistakes of an LLM-as-a-judge agreeing {_pct(large['agree'])} of the time and "
               f"passing {_pct(large['pi'])} of the answers, and "
               f"breaks about 2 in 100 right answers) reads \"better\" in "
               f"{large['better']:.1f} cases in 100 with {large['marks']} marks, and \"safe to "
               f"try\" in {large['safe']:.1f}.")
    if s["never_false_better"] and s["never_false_worse"]:
        out.append("A rule that is truly the same or worse is never called \"better\", and one "
                   "that is truly the same or better is never called \"worse\".")
    else:
        out.append(f"A rule that is truly the same or worse is called \"better\" in at most "
                   f"{s['false_better']:.1f} cases in 100, and one that is truly the same or "
                   f"better is called \"worse\" in at most {s['false_worse']:.1f}: rare but "
                   f"not zero, and only for rules within {s['false_within']:.1f} points of no "
                   "change.")
    lop = s["lopsided"]
    out.append(f"A rule that fixes 9 in 10 of the mistakes among the answers the "
               f"LLM-as-a-judge failed, but breaks 1 in 4 right answers among those it passed, "
               f"is {-lop['change'][1]:.1f} to {-lop['change'][0]:.1f} points worse on the "
               "whole set of answers where the LLM-as-a-judge passes most of them; there it "
               f"reads \"safe to try\" or \"better\" in at most {lop['wrong']:.1f} cases in "
               "100 at any marks tried. The marks hold many of its fails, so each one is "
               "weighted to the whole set.")
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
              "Marks come as the marking page offers them: 15 the LLM-as-a-judge passed and 15 "
              "it failed first, then in the pool's own mix; the LLM-as-a-judge passes "
              + " or ".join(_pct(x) for x in result["pis"]) + f" of {result['pool']:,} answers. "
              f"{result['cases']:,} made-up cases per row, seed {result['seed']}, commit "
              f"`{result['commit']}`. No AI call."), "",
             "## The result", "", " ".join(sentences(result)), "",
             "## Marks for a clear answer", "",
             ("The fewest marks tried (" + ", ".join(map(str, MARKS)) + ") at which `fix` "
              "gives a clear answer most of the time, whether the LLM-as-a-judge agrees with "
              f"the person {agrees} of the time and whatever share it passes, and there how "
              "often it says each, in 100 cases (low to high over those). New rule: of the "
              "answers kept aside, "
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
    lines += ["",
              "## How often `fix` says each, in 100 cases", "",
              ("True change: the points of agreement with the person the new rule really gains "
               "or loses on the whole pool. Agrees: how often the LLM-as-a-judge agrees with the "
               "person. Passes: the share of the pool it passed. Kept aside: the marks kept "
               "aside, on average."), "",
              ("| Marks | Agrees | Passes | New rule | True change | Kept aside | Better | Safe "
               "to try | Can't tell yet | Worse |"),
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['marks']} | {_pct(r['agree'])} | {_pct(r['pi'])} | {r['rule']} | "
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
