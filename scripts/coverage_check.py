"""How often judgekeeper's ranges hold the true value: the coverage grid.

    python scripts/coverage_check.py     # the full grid; writes docs/examples/coverage/

A "95%" range should hold the true value about 95 times in 100. This script checks that by
simulation, for the ranges `judgekeeper start` shows (weighted.corrected) and the ranges after
asking the judge again (weighted.general).

One simulated check: the pool holds POOL answers, a share `pi` of them passed by the judge. An
answer the judge passed is Correct with chance `a`; an answer it failed is Wrong with chance
`w` (Correct with chance b = 1 - w). `n` answers are labeled in each group, each Correct with
that chance. The true TPR, TNR and real pass rate follow from pi, a and b with weighted.py's
formulas. For general(), the judge asked again gives the same verdicts as the saved ones (a
steady judge). Kappa has no range, so it is not measured.

The grid: pi in SHARES, a in CORRECT_IF_PASS, w in WRONG_IF_FAIL, n in LABELS; CHECKS checks
per cell, each cell with its own fixed seed. For each cell and each range, how often it holds
the true value (checks where the number is unknown, such as TNR when every labeled answer is
Correct, are left out and counted), and its average width.

Ranges measured:
- start, now: Jeffreys draws (weighted.corrected) at each level in LEVELS, from the same draws.
- start, before: Wilson at 97.5% per group, joined at the corners (the earlier method),
  rebuilt here.
- general(), before: a stratified percentile bootstrap, 2,000 resamples, with the Wilson
  corners when a range has zero width (the earlier method), rebuilt here.
- general(), now: weighted.general as it is.

The level for start is the first of 0.95, 0.96 and 0.97 whose ranges hold the true TPR, TNR
and real pass rate at least FLOOR_CELL of the time in every cell and FLOOR_MEAN on average.

Two more checks: how far another seed moves a range (STABILITY), and how often a check that
reached targets.RELIABLE Correct and Wrong labels has both ranges no wider than each
candidate width (RELIABLE_RUNS simulated labelings per case, picking 5 from each group per
block as `start` does).

Standard library only. Uses every processor core; the full grid takes a few minutes.
"""

from __future__ import annotations

import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from judgekeeper import targets, weighted

OUT = ROOT / "docs" / "examples" / "coverage"
SEED = 20261008
POOL = 1000
SHARES = (0.5, 0.7, 0.9)
CORRECT_IF_PASS = (0.60, 0.80, 0.95)
WRONG_IF_FAIL = (0.60, 0.80, 0.95)
LABELS = (10, 15, 25, 40)
CHECKS = 4000
LEVELS = (0.95, 0.96, 0.97, 0.98)
CANDIDATES = (0.95, 0.96, 0.97)
FLOOR_CELL = 0.93
FLOOR_MEAN = 0.95
START_METRICS = ("tpr", "tnr", "real_pass_rate")
GENERAL_METRICS = ("tpr", "tnr")
STABILITY = [(500, 500, 25, 21, 25, 4), (700, 300, 15, 13, 15, 2), (900, 100, 25, 24, 25, 6),
             (900, 100, 40, 38, 40, 9), (171, 41, 16, 15, 15, 5), (600, 400, 10, 7, 10, 3)]
STABILITY_SEEDS = (1, 2, 3, 4, 5)
RELIABLE_CASES = [(0.5, 0.85, 0.85), (0.7, 0.85, 0.85), (0.9, 0.85, 0.85), (0.5, 0.95, 0.95),
                  (0.7, 0.95, 0.60), (0.9, 0.95, 0.60)]
RELIABLE_RUNS = 1000
WIDTHS = (0.25, 0.30, 0.35, 0.40)
BOOT_SEED = 20261005
RESAMPLES = 2000


def truth(pi: float, a: float, b: float) -> dict:
    return {"tpr": weighted._tpr(pi, a, b), "tnr": weighted._tnr(pi, a, b),
            "real_pass_rate": weighted._pass_rate(pi, a, b)}


def pool_counts(pi: float) -> tuple[int, int]:
    n_pass = round(pi * POOL)
    return n_pass, POOL - n_pass


# The earlier ranges, rebuilt -----------------------------------------------------------

def corners(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f) -> dict:
    """Wilson at 97.5% per group, the ends put into the formulas (the earlier weighted.corrected)."""
    pi = n_pool_pass / (n_pool_pass + n_pool_fail)
    (a_lo, a_hi), (b_lo, b_hi) = weighted.wilson(c_p, n_p), weighted.wilson(c_f, n_f)
    a, b = c_p / n_p, c_f / n_f
    out = {}
    for key, f, low, high in (("tpr", weighted._tpr, (a_lo, b_hi), (a_hi, b_lo)),
                              ("tnr", weighted._tnr, (a_lo, b_hi), (a_hi, b_lo)),
                              ("real_pass_rate", weighted._pass_rate, (a_lo, b_lo), (a_hi, b_hi))):
        lo, hi = f(pi, *low), f(pi, *high)
        out[key] = None if f(pi, a, b) is None or lo is None or hi is None else [lo, hi]
    return out


def _items(n_p, c_p, n_f, c_f) -> list[tuple[str, str, str]]:
    """A steady judge asked again: the fresh verdicts are the saved groups."""
    return ([("pass", "pass", "pass")] * c_p + [("pass", "fail", "pass")] * (n_p - c_p)
            + [("fail", "pass", "fail")] * c_f + [("fail", "fail", "fail")] * (n_f - c_f))


def wilson_corners(items, n_pool_pass, n_pool_fail) -> dict:
    """The Wilson-corners range general() fell back on when a bootstrap range had zero width:
    per saved group, the share the judge got right among the answers that should pass (or
    fail), with its Wilson interval at 97.5%, mixed by the groups' weights."""
    pool = {"pass": n_pool_pass, "fail": n_pool_fail}
    by_group = {g: [x for x in items if x[0] == g] for g in pool}
    out = {}
    for key, label in (("tpr", "pass"), ("tnr", "fail")):
        total = low = high = 0.0
        for g, xs in by_group.items():
            marked = [x for x in xs if x[1] == label]
            if not marked or pool[g] <= 0:
                continue
            weight = pool[g] / len(xs) * len(marked)
            lo, hi = weighted.wilson(sum(x[2] == label for x in marked), len(marked))
            total, low, high = total + weight, low + weight * lo, high + weight * hi
        out[key] = [low / total, high / total] if total > 0 else None
    return out


def bootstrap(items, n_pool_pass, n_pool_fail) -> dict:
    """The stratified percentile bootstrap the earlier weighted.general used, with its corners."""
    pool = {"pass": n_pool_pass, "fail": n_pool_fail}
    by_group = {g: [x for x in items if x[0] == g] for g in pool}
    weights = {g: weighted._div(pool[g], len(xs)) or 0.0 for g, xs in by_group.items()}
    point = weighted._table(items, weights)
    rng = random.Random(BOOT_SEED)
    draws = {k: [] for k in point}
    for _ in range(RESAMPLES):
        sample = [rng.choice(xs) for xs in by_group.values() for _ in xs]
        for key, value in weighted._table(sample, weights).items():
            if value is not None:
                draws[key].append(value)
    out = {}
    for key in GENERAL_METRICS:
        values = draws[key]
        if not values or point[key] is None:
            out[key] = None
            continue
        interval = [weighted._percentile(values, 0.025), weighted._percentile(values, 0.975)]
        if interval[1] - interval[0] <= 1e-12:
            interval = wilson_corners(items, n_pool_pass, n_pool_fail)[key]
        out[key] = interval
    return out


# One labeled outcome, every range ---------------------------------------------------------

def _general_now(items, n_pool_pass, n_pool_fail) -> dict:
    general = weighted.general(items, n_pool_pass, n_pool_fail)
    return {k: (general[f"{k}_interval"] if general[k] is not None
                and general[f"{k}_interval"][0] is not None else None) for k in GENERAL_METRICS}


def quick_ranges(args: tuple) -> tuple:
    """Only the ranges judgekeeper shows now, at weighted.LEVEL (for the test suite)."""
    n_pool_pass, n_pool_fail, n, c_p, c_f = args
    now = weighted.corrected(n_pool_pass, n_pool_fail, n, c_p, n, c_f)
    return args, {
        "start_now": {weighted.LEVEL: {k: (None if now[f"{k}_interval"][0] is None
                                           else now[f"{k}_interval"]) for k in START_METRICS}},
        "general_now": _general_now(_items(n, c_p, n, c_f), n_pool_pass, n_pool_fail),
    }


def ranges(args: tuple) -> tuple:
    """Every range for one outcome: n labeled per group, c_p and c_f of them Correct."""
    n_pool_pass, n_pool_fail, n, c_p, c_f = args
    counts = (n_pool_pass, n_pool_fail, n, c_p, n, c_f)
    samples = weighted.jeffreys_samples(*counts)
    now = weighted.corrected(*counts)
    jeffreys = {}
    for level in LEVELS:
        jeffreys[level] = {k: (None if now[k] is None
                               else weighted.middle(samples.get(k), level, now[k]))
                           for k in START_METRICS}
        jeffreys[level] = {k: (None if v is None or v[0] is None else v)
                           for k, v in jeffreys[level].items()}
    items = _items(n, c_p, n, c_f)
    return args, {
        "start_before": corners(*counts),
        "start_now": jeffreys,
        "general_before": bootstrap(items, n_pool_pass, n_pool_fail),
        "general_now": _general_now(items, n_pool_pass, n_pool_fail),
    }


def _binomial(rng: random.Random, n: int, p: float) -> int:
    return sum(rng.random() < p for _ in range(n))


def cells(shares=SHARES, correct=CORRECT_IF_PASS, wrong=WRONG_IF_FAIL, labels=LABELS):
    return [(pi, a, w, n) for pi in shares for a in correct for w in wrong for n in labels]


def outcomes(grid: list[tuple], checks: int, seed: int = SEED) -> dict:
    """The simulated (c_p, c_f) of every check, per cell, with a fixed seed per cell."""
    out = {}
    for index, (pi, a, w, n) in enumerate(grid):
        rng = random.Random(seed + index)
        out[(pi, a, w, n)] = [(_binomial(rng, n, a), _binomial(rng, n, 1 - w))
                              for _ in range(checks)]
    return out


def _tally(hits: dict, key: str, interval, true: float) -> None:
    row = hits.setdefault(key, {"held": 0, "checked": 0, "unknown": 0, "width": 0.0})
    if interval is None:
        row["unknown"] += 1
        return
    lo, hi = interval
    row["checked"] += 1
    row["held"] += lo - 1e-12 <= true <= hi + 1e-12
    row["width"] += hi - lo


def _summary(row: dict) -> dict:
    checked = row["checked"]
    return {"coverage": row["held"] / checked if checked else None,
            "width": row["width"] / checked if checked else None,
            "checked": checked, "unknown": row["unknown"]}


def run_grid(grid: list[tuple], checks: int, workers: int | None = None,
             quick: bool = False) -> list[dict]:
    """Coverage and average width per cell, for every range (quick: only those shown now)."""
    sims = outcomes(grid, checks)
    needed = sorted({(*pool_counts(pi), n, c_p, c_f)
                     for (pi, _, _, n), pairs in sims.items() for c_p, c_f in pairs})
    work = quick_ranges if quick else ranges
    if workers == 1:
        computed = dict(map(work, needed))
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            computed = dict(ex.map(work, needed, chunksize=8))
    rows = []
    for (pi, a, w, n), pairs in sims.items():
        n_pass, n_fail = pool_counts(pi)
        true = truth(n_pass / POOL, a, 1 - w)
        hits: dict[str, dict] = {}
        for c_p, c_f in pairs:
            r = computed[(n_pass, n_fail, n, c_p, c_f)]
            for k in START_METRICS:
                if "start_before" in r:
                    _tally(hits, f"start_before/{k}", r["start_before"][k], true[k])
                for level, now in r["start_now"].items():
                    _tally(hits, f"start_now/{level}/{k}", now[k], true[k])
            for k in GENERAL_METRICS:
                if "general_before" in r:
                    _tally(hits, f"general_before/{k}", r["general_before"][k], true[k])
                _tally(hits, f"general_now/{k}", r["general_now"][k], true[k])
        rows.append({"pi": pi, "a": a, "w": w, "n": n, "truth": true,
                     "ranges": {key: _summary(row) for key, row in sorted(hits.items())}})
    return rows


def _pmf(n: int, p: float) -> list[float]:
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]


def exact_grid(grid: list[tuple], smallest: float = 1e-5) -> list[dict]:
    """Coverage with no simulation noise, for the ranges shown now: every outcome (c_p, c_f)
    weighed by its binomial chance. Outcomes less likely than `smallest` are left out and
    counted as misses, so each coverage is a lower bound. For the test suite."""
    rows = []
    for pi, a, w, n in grid:
        n_pass, n_fail = pool_counts(pi)
        true = truth(n_pass / POOL, a, 1 - w)
        held: dict[str, float] = {}
        for c_p, p_p in enumerate(_pmf(n, a)):
            for c_f, p_f in enumerate(_pmf(n, 1 - w)):
                if p_p * p_f < smallest:
                    continue
                _, r = quick_ranges((n_pass, n_fail, n, c_p, c_f))
                found = {f"start_now/{k}": r["start_now"][weighted.LEVEL][k]
                         for k in START_METRICS}
                found.update({f"general_now/{k}": r["general_now"][k] for k in GENERAL_METRICS})
                for key, interval in found.items():
                    metric = key.split("/")[1]
                    inside = (interval is None or  # unknown: no range shown, nothing claimed
                              interval[0] - 1e-12 <= true[metric] <= interval[1] + 1e-12)
                    held[key] = held.get(key, 0.0) + p_p * p_f * inside
        rows.append({"pi": pi, "a": a, "w": w, "n": n, "coverage": held})
    return rows


def judge_levels(rows: list[dict], prefix: str, metrics: tuple) -> dict:
    """The lowest cell and the average coverage of the ranges under `prefix`."""
    values = [row["ranges"][f"{prefix}/{k}"]["coverage"] for row in rows for k in metrics]
    values = [v for v in values if v is not None]
    per_metric = {k: min(v for row in rows if (v := row["ranges"][f"{prefix}/{k}"]["coverage"])
                         is not None) for k in metrics}
    return {"min_cell": min(values), "mean": sum(values) / len(values), "per_metric": per_metric,
            "passes": min(values) >= FLOOR_CELL and sum(values) / len(values) >= FLOOR_MEAN}


def narrower(rows: list[dict], level: float) -> dict:
    """How much narrower start's ranges are at `level` than the corners were, per cell and
    number: the smallest, the largest and the average share."""
    shares = [1 - row["ranges"][f"start_now/{level}/{k}"]["width"]
              / row["ranges"][f"start_before/{k}"]["width"]
              for row in rows for k in START_METRICS
              if row["ranges"][f"start_now/{level}/{k}"]["width"]
              and row["ranges"][f"start_before/{k}"]["width"]]
    return {"min": min(shares), "max": max(shares), "mean": sum(shares) / len(shares)}


def choose_level(rows: list[dict]) -> tuple[float | None, dict]:
    levels = {str(level): judge_levels(rows, f"start_now/{level}", START_METRICS)
              for level in LEVELS}
    chosen = next((level for level in CANDIDATES if levels[str(level)]["passes"]), None)
    return chosen, levels


# How far another seed moves a range ---------------------------------------------------------

def stability() -> dict:
    largest = 0.0
    for counts in STABILITY:
        base = weighted.corrected(*counts)
        for seed in STABILITY_SEEDS:
            other = weighted.corrected(*counts, seed=seed)
            for k in START_METRICS:
                if base[k] is None:
                    continue
                largest = max(largest, *(abs(x - y) for x, y in
                                         zip(base[f"{k}_interval"], other[f"{k}_interval"])))
    return {"draws": weighted.DRAWS, "seeds": len(STABILITY_SEEDS),
            "counts": [list(c) for c in STABILITY], "largest_change": largest}


# How often a check with 25 Correct and 25 Wrong is reliable --------------------------------

def _labeling(args: tuple) -> list[float | None]:
    """One labeling as `start` does it: blocks of 5 from each group, until RELIABLE Correct
    and RELIABLE Wrong; then the TPR and TNR range widths."""
    pi, a, w, run = args
    rng = random.Random(SEED + run)
    n_pass, n_fail = pool_counts(pi)
    n = {"pass": 0, "fail": 0}
    c = {"pass": 0, "fail": 0}
    while True:
        correct, wrong = c["pass"] + c["fail"], n["pass"] + n["fail"] - c["pass"] - c["fail"]
        if min(correct, wrong) >= targets.RELIABLE:
            break
        for group, chance in (("pass", a), ("fail", 1 - w)):
            for _ in range(5):
                n[group] += 1
                c[group] += rng.random() < chance
    r = weighted.corrected(n_pass, n_fail, n["pass"], c["pass"], n["fail"], c["fail"])
    return [None if r[f"{k}_interval"][0] is None
            else r[f"{k}_interval"][1] - r[f"{k}_interval"][0] for k in ("tpr", "tnr")]


def reliable_widths(runs: int = RELIABLE_RUNS, workers: int | None = None) -> list[dict]:
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for pi, a, w in RELIABLE_CASES:
            widths = list(ex.map(_labeling, [(pi, a, w, run) for run in range(runs)],
                                 chunksize=16))
            share = {str(m): sum(1 for t, u in widths if t is not None and u is not None
                                 and max(t, u) <= m + 1e-12) / runs for m in WIDTHS}
            mean = {k: sum(x[i] for x in widths if x[i] is not None) /
                    max(1, sum(1 for x in widths if x[i] is not None))
                    for i, k in enumerate(("tpr", "tnr"))}
            out.append({"pi": pi, "a": a, "w": w, "runs": runs, "reliable_share": share,
                        "mean_width": mean})
    return out


# Writing it down ----------------------------------------------------------------------------

def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}"


def _w(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def markdown(result: dict) -> str:
    level = result["corrected"]["chosen_level"]
    lines = ["# Coverage of judgekeeper's ranges", "",
             ("Written by `scripts/coverage_check.py`; do not edit by hand. How often a range "
             "holds the true value, in percent, and its average width (high end minus low end). "
             "A 95% range should hold it about 95 times in 100."), "",
             (f"Grid: the judge's pass share (pi) {', '.join(f'{x:.0%}' for x in SHARES)}; the "
             f"chance an answer the judge passed is Correct (a) {', '.join(map(str, CORRECT_IF_PASS))}; "
             f"the chance an answer it failed is Wrong (w) {', '.join(map(str, WRONG_IF_FAIL))}; "
             f"{', '.join(map(str, LABELS))} answers labeled in each group. {CHECKS:,} simulated "
             f"checks per cell, fixed seed {SEED}. Jeffreys ranges: {result['draws']:,} draws, "
             f"seed {result['seed']}. Checks where a number is unknown (TNR when every labeled "
             "answer is Correct, say) are left out of that number's coverage and counted."), "",
             "## `judgekeeper start`: the level", "",
             (f"Rule: the first of {', '.join(f'{x:.0%}' for x in CANDIDATES)} whose ranges hold "
             f"the true TPR, TNR and real pass rate at least {FLOOR_CELL:.0%} of the time in "
             f"every cell and {FLOOR_MEAN:.0%} on average."), "",
             "| Level | Lowest cell | Average | Passes |", "|---|---|---|---|"]
    for key, v in result["corrected"]["levels"].items():
        lines.append(f"| {float(key):.0%} | {_pct(v['min_cell'])} | {_pct(v['mean'])} | "
                     f"{'yes' if v['passes'] else 'no'} |")
    before = result["corrected"]["before"]
    n = result["corrected"]["narrower"]
    lines += ["", (f"Chosen level: **{'none' if level is None else f'{level:.0%}'}**. Before this "
              f"change (Wilson corners): lowest cell {_pct(before['min_cell'])}, average "
              f"{_pct(before['mean'])}. The ranges now are {_pct(n['mean'])}% narrower on "
              f"average ({_pct(n['min'])}% to {_pct(n['max'])}% by cell and number)."), "",
              (f"## `judgekeeper start`: per cell, before (Wilson corners) and now (Jeffreys "
              f"{'n/a' if level is None else f'{level:.0%}'})"), "",
              "Coverage % / average width, before → now.", "",
              "| pi | a | w | n | TPR | TNR | Real pass rate |", "|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        cells_ = []
        for k in START_METRICS:
            old = row["ranges"][f"start_before/{k}"]
            new = row["ranges"][f"start_now/{level or 0.95}/{k}"]
            cells_.append(f"{_pct(old['coverage'])} / {_w(old['width'])} → "
                          f"{_pct(new['coverage'])} / {_w(new['width'])}")
        lines.append(f"| {row['pi']:.0%} | {row['a']} | {row['w']} | {row['n']} | "
                     + " | ".join(cells_) + " |")
    g = result["general"]
    lines += ["", "## After asking the judge again (`weighted.general`)", "",
              "A steady judge: asked again, it gives the same verdicts. TPR and TNR.", "",
              (f"Before (stratified bootstrap): lowest cell {_pct(g['before']['min_cell'])}, "
              f"average {_pct(g['before']['mean'])}. Now ({g['now_method']}): lowest cell "
              f"{_pct(g['now']['min_cell'])}, average {_pct(g['now']['mean'])}."), "",
              ("Lowest cell per number, before → now: " + "; ".join(
                  f"{k.upper()} {_pct(g['before']['per_metric'][k])}"
                  f" → {_pct(g['now']['per_metric'][k])}" for k in GENERAL_METRICS)
               + ". Kappa is given without a range, as in `start`'s result."), "",
              "| pi | a | w | n | TPR | TNR |", "|---|---|---|---|---|---|"]
    for row in result["rows"]:
        cells_ = []
        for k in GENERAL_METRICS:
            old, new = row["ranges"][f"general_before/{k}"], row["ranges"][f"general_now/{k}"]
            cells_.append(f"{_pct(old['coverage'])} / {_w(old['width'])} → "
                          f"{_pct(new['coverage'])} / {_w(new['width'])}")
        lines.append(f"| {row['pi']:.0%} | {row['a']} | {row['w']} | {row['n']} | "
                     + " | ".join(cells_) + " |")
    s = result["stability"]
    lines += ["", "## Another seed", "",
              (f"With {s['draws']:,} draws, {s['seeds']} other seeds moved a range end by at "
              f"most {s['largest_change']:.4f} on the counts tried."), "",
              "## When is a check reliable?", "",
              (f"{RELIABLE_RUNS:,} simulated labelings per case, 5 from each group per block as "
              f"`start` picks, until {targets.RELIABLE} Correct and {targets.RELIABLE} Wrong. "
              "The share whose TPR and TNR ranges are both no wider than each width, and the "
              f"average widths. The width judgekeeper uses: {targets.MAX_WIDTH:.2f}."), "",
              "| pi | a | w | " + " | ".join(f"≤ {m:.2f}" for m in WIDTHS)
              + " | TPR width | TNR width |",
              "|---|---|---|" + "---|" * (len(WIDTHS) + 2)]
    for case in result["reliable"]:
        lines.append(f"| {case['pi']:.0%} | {case['a']} | {case['w']} | "
                     + " | ".join(f"{case['reliable_share'][str(m)]:.0%}" for m in WIDTHS)
                     + f" | {_w(case['mean_width']['tpr'])} | {_w(case['mean_width']['tnr'])} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = run_grid(cells(), CHECKS)
    chosen, levels = choose_level(rows)
    result = {
        "seed": weighted.SEED, "draws": weighted.DRAWS, "checks_per_cell": CHECKS,
        "grid_seed": SEED, "floor_cell": FLOOR_CELL, "floor_mean": FLOOR_MEAN,
        "corrected": {"chosen_level": chosen, "levels": levels,
                      "before": judge_levels(rows, "start_before", START_METRICS),
                      "narrower": narrower(rows, chosen or LEVELS[-1])},
        "general": {"before": judge_levels(rows, "general_before", GENERAL_METRICS),
                    "now": judge_levels(rows, "general_now", GENERAL_METRICS),
                    "now_method": general_method()},
        "stability": stability(),
        "reliable": reliable_widths(),
        "rows": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "coverage.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (OUT / "coverage.md").write_text(markdown(result), encoding="utf-8")
    print(f"chosen level: {chosen}; wrote {OUT / 'coverage.md'} and coverage.json")


def general_method() -> str:
    items = _items(10, 8, 10, 3)
    return weighted.general(items, 600, 400)["interval_methods"]["tpr"]


if __name__ == "__main__":
    main()
