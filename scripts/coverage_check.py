"""How often judgekeeper's ranges hold the true value: the coverage grid.

    python scripts/coverage_check.py     # the full grid; writes docs/examples/coverage/

A "95%" range should hold the true value about 95 times in 100. This script checks that by
simulation, for the ranges `judgekeeper` shows (weighted.corrected) and the ranges after
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
reached RELIABLE Correct and Wrong labels has both ranges no wider than each candidate width
(RELIABLE_RUNS simulated labelings per case, picking 5 from each group per block as
`judgekeeper` does).

The numbers on screen (`accuracy`): kappa's range; the ranges at the real stopping rule
(marking 5 + 5 per block until 15 Pass and 15 Fail, and until 25 + 25); how often each width
word is said at the first result; how often the verdict is green when the lower of the true
TPR and TNR is 75% and 80%; weighted.general when the judge asked again (twice, as a paid
re-check does) changes its mind, with and without the wobble it showed; and how often `check` says "Worse" (and exits 1) when nothing changed, with and without the judge's
own wobble when asked again.

The batch grid (`batches`): new answers join as batches (batches.py), and the numbers are
stratified by (batch, the judge's grade). Two and three batches of different sizes, judges whose
accuracy differs between batches, and BATCH_MARKS marks per stratum; the ranges judgekeeper
shows (weighted.stratified, at weighted.LEVEL with weighted.DRAWS draws) and after asking a
steady judge again (weighted.general_strata). The bar is the level's: FLOOR_CELL in every cell
and FLOOR_MEAN on average.

    python scripts/coverage_check.py --batches   # only the batch grid, added to the files
    python scripts/coverage_check.py --one-grade # only the one-grade grid, added likewise

The one-grade grid (`one_grade`): a judge that passed (or failed) every answer of the pool,
with ONE_GRADE_MARKS marks, each the judge's own grade with chance ONE_GRADE_AGREE.

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
RELIABLE = 25  # Correct and Wrong labels a labeling goes on to (an earlier "reliable" target)
FIRST = 15  # Correct and Wrong labels the first result needs (targets.ROUGH)
ACCURACY_RUNS = 1000
KAPPA_CELLS = [(pi, a, w, n) for pi in SHARES for a, w in ((0.8, 0.8), (0.95, 0.95), (0.95, 0.6))
               for n in (15, 25, 40)]
KAPPA_CHECKS = 500
STOP_CASES = RELIABLE_CASES
# (judge's pass share, true TPR, true TNR): the lower of TPR and TNR at 75% and at 80%
GREEN_CASES = [(0.9, 0.98, 0.75), (0.9, 0.98, 0.80), (0.5, 0.75, 0.95), (0.5, 0.80, 0.95)]
CHANGES_MIND = (0.05, 0.10)  # the share of grades a judge asked again turns round
# the judge also changed: the share of the answers it failed, that should fail, it now passes
ALSO_CHANGED = (0.0, 0.3)
WOBBLES = (0.0, 0.05, 0.10)  # the same judge asked again: the share of answers whose grade
# comes out different, half of them turning wrong and half turning right (nothing changed)
WIDTHS = (0.25, 0.30, 0.35, 0.40)
# The batch grid: answers per batch (the shapes 40 + 20 and 60 + 30 + 30, ten times over so a
# stratum holds the marks; and a small new batch of 15); per batch (pi, a, w), judges whose
# accuracy differs between batches (the first two or three batches of each); marks per stratum
# in each batch (the last repeats), never more than the stratum holds
BATCH_SHAPES = ((400, 200), (600, 300, 300), (60, 15))
BATCH_JUDGES = (((0.7, 0.90, 0.80), (0.5, 0.70, 0.60), (0.9, 0.95, 0.60)),
                ((0.5, 0.80, 0.95), (0.9, 0.95, 0.60), (0.7, 0.60, 0.80)),
                ((0.9, 0.95, 0.95), (0.7, 0.60, 0.60), (0.5, 0.80, 0.80)),
                ((0.7, 0.80, 0.80), (0.7, 0.60, 0.95), (0.7, 0.95, 0.60)))
BATCH_MARKS = ((10,), (15,), (25,), (40,), (40, 10))
BATCH_CHECKS = 1500
ONE_GRADE_AGREE = (0.6, 0.8, 0.95)  # the chance a mark is the judge's own grade
ONE_GRADE_MARKS = (20, 25, 30, 40)
ONE_GRADE_CHECKS = 2000
GENERAL_DRAWS = 4000  # after asking again, as the other re-check rows
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
        if min(correct, wrong) >= RELIABLE:
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


# The numbers on screen -----------------------------------------------------------------------

def _kappa_cell(args: tuple) -> dict:
    """Kappa's range in one cell: how often it holds the true kappa, and its width."""
    pi, a, w, n = args
    rng = random.Random(SEED + int(pi * 1000) + int(a * 100) + int(w * 10) + n)
    n_pass, n_fail = pool_counts(pi)
    true = weighted._kappa(pi, a, 1 - w)
    hits = tried = 0
    width = 0.0
    for _ in range(KAPPA_CHECKS):
        c_p, c_f = _binomial(rng, n, a), _binomial(rng, n, 1 - w)
        r = weighted.corrected(n_pass, n_fail, n, c_p, n, c_f)
        lo, hi = r["kappa_interval"]
        if lo is None:
            continue
        tried += 1
        hits += lo - 1e-12 <= true <= hi + 1e-12
        width += hi - lo
    return {"pi": pi, "a": a, "w": w, "n": n, "true": true,
            "coverage": hits / tried if tried else None,
            "width": width / tried if tried else None}


def _marked_until(rng: random.Random, a: float, b: float, each: int) -> dict:
    """Marks in blocks of 5 from each of the judge's groups until `each` Pass and Fail: per
    group [marked, marked Pass]."""
    g = {"pass": [0, 0], "fail": [0, 0]}
    while True:
        passed = g["pass"][1] + g["fail"][1]
        if min(passed, g["pass"][0] + g["fail"][0] - passed) >= each:
            return g
        for group, share in (("pass", a), ("fail", b)):
            for _ in range(5):
                g[group][0] += 1
                g[group][1] += rng.random() < share


def _stopping(args: tuple) -> dict:
    """One case under the real stopping rule: coverage of TPR and TNR at the stop, and at
    the first result the share of each width word."""
    pi, a, w, each = args
    rng = random.Random(SEED + int(pi * 100) + int(a * 1000) + int(w * 10000) + each)
    n_pass, n_fail = pool_counts(pi)
    true = truth(pi, a, 1 - w)
    hits = {"tpr": 0, "tnr": 0}
    words = {"tpr": {}, "tnr": {}}
    for _ in range(ACCURACY_RUNS):
        g = _marked_until(rng, a, 1 - w, each)
        r = weighted.corrected(n_pass, n_fail, *g["pass"], *g["fail"], draws=4000)
        for k in ("tpr", "tnr"):
            lo, hi = r[f"{k}_interval"]
            hits[k] += lo is not None and lo - 1e-12 <= true[k] <= hi + 1e-12
            word = str(targets.width_word(r[f"{k}_interval"]) or "plain")
            words[k][word] = words[k].get(word, 0) + 1
    return {"pi": pi, "a": a, "w": w, "each": each,
            "coverage": {k: v / ACCURACY_RUNS for k, v in hits.items()},
            "words": {k: {x: c / ACCURACY_RUNS for x, c in v.items()} for k, v in words.items()}}


def _green(args: tuple) -> dict:
    """How often the verdict is green at the stop, for a judge with these true rates."""
    from judgekeeper import start_label

    judge, tpr, tnr, each = args
    real = (judge - (1 - tnr)) / (tpr - (1 - tnr))
    a, b = real * tpr / judge, real * (1 - tpr) / (1 - judge)
    rng = random.Random(SEED + int(tpr * 1000) + int(tnr * 100) + each)
    n_pass = round(judge * POOL)
    green = 0
    for _ in range(ACCURACY_RUNS):
        g = _marked_until(rng, a, b, each)
        r = start_label.describe(weighted.corrected(n_pass, POOL - n_pass, *g["pass"],
                                                    *g["fail"], draws=4000))
        green += r["verdict_level"] == "gate"
    return {"judge_passes": judge, "tpr": tpr, "tnr": tnr, "each": each,
            "green": green / ACCURACY_RUNS}


def _changes_mind(args: tuple) -> dict:
    """weighted.general when the judge, asked again twice, turns round a share `flip` of its
    grades at random each time (and, `changed`, now passes that share of the answers it failed
    that should fail): how often its TPR and TNR ranges hold the asked judge's true rates, with
    the wobble the two asks showed (`coverage`) and without it (`without`)."""
    pi, a, w, n, flip, changed = args
    rng = random.Random(SEED + int(flip * 1000) + n + int(pi * 10) + int(changed * 100))
    n_pass, n_fail = pool_counts(pi)
    old = truth(pi, a, 1 - w)
    tnr = old["tnr"] * (1 - changed)
    true = {"tpr": old["tpr"] * (1 - flip) + (1 - old["tpr"]) * flip,
            "tnr": tnr * (1 - flip) + (1 - tnr) * flip}
    hits = {f"{how}/{k}": 0 for how in ("with", "without") for k in ("tpr", "tnr")}
    tried = dict.fromkeys(hits, 0)
    wobble_seen = 0.0
    for _ in range(ACCURACY_RUNS):
        items, differ = [], 0
        for group, share in (("pass", a), ("fail", 1 - w)):
            for _ in range(n):
                label = "pass" if rng.random() < share else "fail"
                base = "pass" if group == "fail" and label == "fail" and \
                    rng.random() < changed else group
                other = "fail" if base == "pass" else "pass"
                first = other if rng.random() < flip else base
                second = other if rng.random() < flip else base
                differ += first != second
                items.append((group, label, first))  # the first grade counts, as in check
        wobble = differ / len(items)
        wobble_seen += wobble
        for how, r in (("with", weighted.general(items, n_pass, n_fail, draws=4000,
                                                 wobble=wobble)),
                       ("without", weighted.general(items, n_pass, n_fail, draws=4000))):
            for k in ("tpr", "tnr"):
                lo, hi = r[f"{k}_interval"]
                if lo is None:
                    continue
                tried[f"{how}/{k}"] += 1
                hits[f"{how}/{k}"] += lo - 1e-12 <= true[k] <= hi + 1e-12
    share = {key: hits[key] / tried[key] if tried[key] else None for key in hits}
    return {"pi": pi, "a": a, "w": w, "n": n, "flip": flip, "changed": changed,
            "wobble": wobble_seen / ACCURACY_RUNS,
            "coverage": {k: share[f"with/{k}"] for k in ("tpr", "tnr")},
            "without": {k: share[f"without/{k}"] for k in ("tpr", "tnr")}}


def false_worse(n: int, right: float, wobble: float) -> dict:
    """How often `check` says "Worse" (and how often it exits 1) on one group of n marks when
    the judge did not change, worked out exactly: asked again, a share `wobble` of the answers
    get another grade, half of them turning wrong and half turning right. (How often the judge
    is right does not enter: unchanged, it is as often right as before.)"""
    turn_wrong = turn_right = wobble / 2
    worse = exits = 0.0
    for k_wrong, p_wrong in enumerate(targets._pmf(n, turn_wrong)):
        if p_wrong < 1e-15:
            continue
        rest = n - k_wrong
        share = turn_right / (1 - turn_wrong) if turn_wrong < 1 else 0.0
        for k_right, p_right in enumerate(targets._pmf(rest, share)):
            if p_right < 1e-15:
                continue
            v = targets.paired_verdict(k_right, k_wrong, n)
            worse += p_wrong * p_right * (v["verdict"] == "worse")
            exits += p_wrong * p_right * v["exit_worse"]
    return {"n": n, "wobble": wobble, "worse": worse, "exit_1": exits}


def accuracy(workers: int | None = None) -> dict:
    with ProcessPoolExecutor(max_workers=workers) as ex:
        kappa = list(ex.map(_kappa_cell, KAPPA_CELLS))
        stopping = list(ex.map(_stopping, [(pi, a, w, each) for pi, a, w in STOP_CASES
                                           for each in (FIRST, RELIABLE)]))
        green = list(ex.map(_green, [(*c, each) for c in GREEN_CASES
                                     for each in (FIRST, RELIABLE)]))
        mind = list(ex.map(_changes_mind, [(pi, 0.9, 0.85, n, flip, changed)
                                           for changed in ALSO_CHANGED for pi in SHARES
                                           for n in (15, 25) for flip in CHANGES_MIND]))
    worse = [false_worse(n, 0.9, wobble) for n in (15, 25, 40) for wobble in WOBBLES]
    return {"kappa": kappa, "stopping": stopping, "green": green, "changes_mind": mind,
            "false_worse": worse}


def accuracy_markdown(acc: dict) -> list[str]:
    lines = ["", "## The numbers on screen", "",
             "### Kappa's range", "",
             (f"{KAPPA_CHECKS} simulated checks per cell, the same labels per group as the grid. "
              "How often kappa's range holds the true kappa of the pool's real mix, and its "
              "average width."), "",
             "| pi | a | w | n | true kappa | coverage | width |", "|---|---|---|---|---|---|---|"]
    for row in acc["kappa"]:
        lines.append(f"| {row['pi']:.0%} | {row['a']} | {row['w']} | {row['n']} | "
                     f"{row['true']:.2f} | {_pct(row['coverage'])} | {_w(row['width'])} |")
    lines += ["", "### The real stopping rule", "",
              (f"{ACCURACY_RUNS:,} simulated markings per case: 5 from each of the judge's "
               f"groups per block, until {FIRST} Pass and {FIRST} Fail (the first result), and "
               f"until {RELIABLE} of each. How often the TPR and TNR ranges hold the true value "
               "at the stop, and at the first result how often each width word is said "
               "(Not enough marks yet: over 40 points; Rough: over 30; plain: over 20; Sharp: "
               "20 or less)."), "",
              "| pi | a | w | stop | TPR | TNR | TPR words | TNR words |",
              "|---|---|---|---|---|---|---|---|"]
    names = {"too_wide": "not enough", "rough": "rough", "plain": "plain", "sharp": "sharp",
             "exact": "exact"}
    for row in acc["stopping"]:
        said = {k: ", ".join(f"{names[x]} {v:.0%}" for x, v in sorted(row["words"][k].items()))
                for k in ("tpr", "tnr")}
        lines.append(f"| {row['pi']:.0%} | {row['a']} | {row['w']} | {row['each']} + "
                     f"{row['each']} | {_pct(row['coverage']['tpr'])} | "
                     f"{_pct(row['coverage']['tnr'])} | {said['tpr']} | {said['tnr']} |")
    lines += ["", "### How often the verdict is green", "",
              (f"{ACCURACY_RUNS:,} simulated markings per case, stopped at {FIRST} + {FIRST} and "
               f"at {RELIABLE} + {RELIABLE}. Green needs the low end of both ranges at 80% or "
               "more, so a judge whose weaker side is 80% or less should rarely be green. In "
               "percent."), "",
              "| judge passes | TPR | TNR | stop | green |", "|---|---|---|---|---|"]
    for row in acc["green"]:
        lines.append(f"| {row['judge_passes']:.0%} | {row['tpr']:.0%} | {row['tnr']:.0%} | "
                     f"{row['each']} + {row['each']} | {_pct(row['green'])} |")
    mind = acc["changes_mind"]
    low = min(row["coverage"][k] for row in mind for k in ("tpr", "tnr")
              if row["coverage"][k] is not None)
    lines += ["", "### After asking again, a judge that changes its mind", "",
              (f"{ACCURACY_RUNS:,} simulated re-checks per row. weighted.general when the judge, "
               "asked again twice as a paid re-check does, turns round a share of its grades at "
               "random each time (a = 0.9, w = 0.85); in the lower half it also changed, and "
               "now passes 30% of the answers it failed that should fail. The first grade "
               "counts. How often the ranges hold the asked judge's true TPR and TNR, with the "
               "wobble the two asks showed (the share of answers whose two grades differ, "
               "averaged) and, before, without it. In percent; lowest with the wobble: "
               f"{_pct(low)}."), "",
              ("| pi | n | turned | also changed | wobble seen | TPR | TNR | TPR before | "
               "TNR before |"), "|---|---|---|---|---|---|---|---|---|"]
    for row in mind:
        lines.append(f"| {row['pi']:.0%} | {row['n']} | {row['flip']:.0%} | "
                     f"{row['changed']:.0%} | {row['wobble']:.0%} | "
                     f"{_pct(row['coverage']['tpr'])} | {_pct(row['coverage']['tnr'])} | "
                     f"{_pct(row['without']['tpr'])} | {_pct(row['without']['tnr'])} |")
    lines += ["", "### `check` when nothing changed", "",
              ("Worked out exactly for one group of marks: the same judge asked again, a share "
               "of the answers getting another grade (the wobble), half turning wrong and half "
               "turning right. How often `check` says Worse, and how often it exits 1 (Worse, "
               "or Not sure with a drop of more than 20 points), in percent."),
              "", "| marks | wobble | Worse | exit 1 |", "|---|---|---|---|"]
    for row in acc["false_worse"]:
        lines.append(f"| {row['n']} | {row['wobble']:.0%} | {100 * row['worse']:.1f} | "
                     f"{100 * row['exit_1']:.1f} |")
    return lines


# Batches ------------------------------------------------------------------------------------

def batch_cells() -> list[tuple]:
    return [(shape, judge[:len(shape)], marks) for shape in BATCH_SHAPES
            for judge in BATCH_JUDGES for marks in BATCH_MARKS]


def _batch_strata(shape: tuple, judge: tuple) -> list[tuple[int, str, int, float]]:
    """(batch, grade, answers, chance an answer is Correct) per stratum."""
    out = []
    for b, (size, (pi, a, w)) in enumerate(zip(shape, judge), 1):
        n_pass = round(pi * size)
        out += [(b, "pass", n_pass, a), (b, "fail", size - n_pass, 1 - w)]
    return out


def batch_truth(strata: list[tuple]) -> dict:
    """The true TPR, TNR and real pass rate of the whole pool: each stratum's answers, the
    share of them Correct."""
    tp = sum(n * p for _, g, n, p in strata if g == "pass")
    fn = sum(n * p for _, g, n, p in strata if g == "fail")
    fp = sum(n * (1 - p) for _, g, n, p in strata if g == "pass")
    tn = sum(n * (1 - p) for _, g, n, p in strata if g == "fail")
    return {"tpr": tp / (tp + fn), "tnr": tn / (tn + fp),
            "real_pass_rate": (tp + fn) / (tp + fn + fp + tn)}


def _batch_cell(args: tuple) -> dict:
    """One cell of the batch grid: BATCH_CHECKS simulated checks, each stratum marked
    min(marks, its answers) times, each mark Correct with the stratum's chance."""
    index, (shape, judge, marks) = args
    rng = random.Random(SEED + 7919 * (index + 1))
    strata = _batch_strata(shape, judge)
    true = batch_truth(strata)
    pool = {(b, g): n for b, g, n, _ in strata}
    hits: dict[str, dict] = {}
    for _ in range(BATCH_CHECKS):
        rows, items = [], []
        for b, g, n_pool, p in strata:
            n = min(marks[min(b, len(marks)) - 1], n_pool)
            c = _binomial(rng, n, p)
            rows.append((b, g, n_pool, n, c))
            items += [((b, g), "pass", g)] * c + [((b, g), "fail", g)] * (n - c)
        start = weighted.stratified(rows)
        again = weighted.general_strata(items, pool, draws=GENERAL_DRAWS)
        for k in START_METRICS:
            _tally(hits, f"start/{k}", None if start[k] is None else start[f"{k}_interval"],
                   true[k])
        for k in GENERAL_METRICS:
            _tally(hits, f"general/{k}", None if again[k] is None else again[f"{k}_interval"],
                   true[k])
    return {"shape": list(shape), "judge": [list(x) for x in judge], "marks": list(marks),
            "truth": true, "ranges": {key: _summary(row) for key, row in sorted(hits.items())}}


def batch_grid(workers: int | None = None) -> dict:
    """The batch grid's cells, and for each kind of range its lowest cell, average and whether
    it passes the bar."""
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_batch_cell, enumerate(batch_cells())))
    return {"checks_per_cell": BATCH_CHECKS, "level": weighted.LEVEL, "draws": weighted.DRAWS,
            "general_draws": GENERAL_DRAWS, "grid_seed": SEED,
            "start": judge_levels(rows, "start", START_METRICS),
            "general": judge_levels(rows, "general", GENERAL_METRICS), "rows": rows}


def batches_markdown(g: dict) -> list[str]:
    start, again = g["start"], g["general"]

    def shape(row):
        return " + ".join(map(str, row["shape"]))

    def judge(row):
        return "; ".join(f"{pi:.0%}, {a}, {w}" for pi, a, w in row["judge"])

    def marks(row):
        m = row["marks"]
        return str(m[0]) if len(m) == 1 else f"{m[0]}, then {m[1]}"

    lines = ["", "## Batches", "",
             ("New answers join as batches, and the numbers are stratified by (batch, the "
              "judge's grade). Two and three batches of different sizes (answers per batch), "
              "judges whose accuracy differs between batches (per batch: pi, a, w), and marks "
              "per stratum (in the first batch, then in each later one; never more than the "
              f"stratum holds). {g['checks_per_cell']:,} simulated checks per cell, fixed seed "
              f"{g['grid_seed']}. The ranges `judgekeeper` shows: level {g['level']:.0%}, "
              f"{g['draws']:,} draws. After asking a steady judge again: "
              f"{g['general_draws']:,} draws. The bar: at least {FLOOR_CELL:.0%} in every "
              f"cell and {FLOOR_MEAN:.0%} on average."), "",
             "| Ranges | Lowest cell | Average | Passes |", "|---|---|---|---|",
             (f"| `judgekeeper` (TPR, TNR, real pass rate) | {_pct(start['min_cell'])} | "
              f"{_pct(start['mean'])} | {'yes' if start['passes'] else 'no'} |"),
             (f"| After asking again (TPR, TNR) | {_pct(again['min_cell'])} | "
              f"{_pct(again['mean'])} | {'yes' if again['passes'] else 'no'} |"), "",
             "Coverage % / average width.", "",
             ("| Answers | Judge per batch (pi, a, w) | Marks | TPR | TNR | Real pass rate | "
              "TPR again | TNR again |"), "|---|---|---|---|---|---|---|---|"]
    for row in g["rows"]:
        r = row["ranges"]
        cells_ = [f"{_pct(r[key]['coverage'])} / {_w(r[key]['width'])}"
                  for key in ("start/tpr", "start/tnr", "start/real_pass_rate", "general/tpr",
                              "general/tnr")]
        lines.append(f"| {shape(row)} | {judge(row)} | {marks(row)} | " + " | ".join(cells_)
                     + " |")
    return lines


# A judge that gives every answer one grade --------------------------------------------------

def one_grade_cells() -> list[tuple]:
    return [(grade, p, n) for grade in ("pass", "fail") for p in ONE_GRADE_AGREE
            for n in ONE_GRADE_MARKS]


def _one_grade_ranges(args: tuple) -> tuple:
    """The ranges `judgekeeper` shows when the judge gave all POOL answers `grade`: n marked,
    c of them the judge's own grade."""
    grade, n, c = args  # c: marked Pass (Correct), as in weighted.stratified
    other = "fail" if grade == "pass" else "pass"
    start = weighted.stratified([(1, grade, POOL, n, c), (1, other, 0, 0, 0)])
    return args, {k: (start[f"{k}_interval"] if start[k] is not None
                      and start[f"{k}_interval"][0] is not None else None)
                  for k in START_METRICS}


def one_grade_grid(workers: int | None = None) -> dict:
    """The one-grade cells (the judge gave all POOL answers one grade; n of them marked, each
    the same way as the judge with chance p; ONE_GRADE_CHECKS checks per cell), and the
    lowest cell, average and bar of their ranges."""
    sims = {}
    for index, (grade, p, n) in enumerate(one_grade_cells()):
        rng = random.Random(SEED + 104729 * (index + 1))
        agree = [_binomial(rng, n, p) for _ in range(ONE_GRADE_CHECKS)]
        sims[(grade, p, n)] = agree if grade == "pass" else [n - k for k in agree]
    needed = sorted({(grade, n, c) for (grade, _, n), cs in sims.items() for c in cs})
    with ProcessPoolExecutor(max_workers=workers) as ex:
        computed = dict(ex.map(_one_grade_ranges, needed, chunksize=4))
    rows = []
    for (grade, p, n), cs in sims.items():
        pi = 1.0 if grade == "pass" else 0.0
        true = truth(pi, *((p, 0.0) if grade == "pass" else (0.0, 1 - p)))
        true["real_pass_rate"] = p if grade == "pass" else 1 - p
        hits: dict[str, dict] = {}
        for c in cs:
            for k, interval in computed[(grade, n, c)].items():
                _tally(hits, f"start/{k}", interval, true[k])
        rows.append({"grade": grade, "agree": p, "marks": n, "truth": true,
                     "ranges": {key: _summary(row) for key, row in sorted(hits.items())}})
    return {"checks_per_cell": ONE_GRADE_CHECKS, "level": weighted.LEVEL,
            "draws": weighted.DRAWS, "grid_seed": SEED,
            "start": judge_levels(rows, "start", START_METRICS), "rows": rows}


def one_grade_markdown(g: dict) -> list[str]:
    s = g["start"]
    lines = ["", "## A judge that gives every answer one grade", "",
             ("The judge passed (or failed) every answer of a pool of "
              f"{POOL:,}; that many marks, each one the same way as the judge with the chance "
              "given (agree). Its TPR and TNR are then 100% and 0% (or 0% and 100%), and "
              "their ranges are the plain Jeffreys ranges of the marks. "
              f"{g['checks_per_cell']:,} simulated checks per cell, fixed seed "
              f"{g['grid_seed']}, level {g['level']:.0%}, {g['draws']:,} draws. Checks where "
              "a number is unknown (TNR when every mark agrees, say) are left out and counted."),
             "",
             (f"Lowest cell {_pct(s['min_cell'])}, average {_pct(s['mean'])}: "
              f"{'passes' if s['passes'] else 'does not pass'} the bar "
              f"({FLOOR_CELL:.0%} in every cell, {FLOOR_MEAN:.0%} on average)."), "",
             "Coverage % / average width.", "",
             "| Judge | Agree | Marks | TPR | TNR | Real pass rate |", "|---|---|---|---|---|---|"]
    for row in g["rows"]:
        r = row["ranges"]
        cells_ = [f"{_pct(r[f'start/{k}']['coverage'])} / {_w(r[f'start/{k}']['width'])}"
                  for k in START_METRICS]
        judge = "passes every answer" if row["grade"] == "pass" else "fails every answer"
        lines.append(f"| {judge} | {row['agree']} | {row['marks']} | " + " | ".join(cells_)
                     + " |")
    return lines


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
             "## `judgekeeper`: the level", "",
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
              (f"## `judgekeeper`: per cell, before (Wilson corners) and now (Jeffreys "
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
               + ". Kappa is given without a range, as in judgekeeper's result."), "",
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
              f"`judgekeeper` picks, until {RELIABLE} Correct and {RELIABLE} Wrong. "
              "The share whose TPR and TNR ranges are both no wider than each width, and the "
              f"average widths. The width judgekeeper uses: {targets.MAX_WIDTH:.2f}."), "",
              "| pi | a | w | " + " | ".join(f"≤ {m:.2f}" for m in WIDTHS)
              + " | TPR width | TNR width |",
              "|---|---|---|" + "---|" * (len(WIDTHS) + 2)]
    for case in result["reliable"]:
        lines.append(f"| {case['pi']:.0%} | {case['a']} | {case['w']} | "
                     + " | ".join(f"{case['reliable_share'][str(m)]:.0%}" for m in WIDTHS)
                     + f" | {_w(case['mean_width']['tpr'])} | {_w(case['mean_width']['tnr'])} |")
    if result.get("accuracy"):
        lines += accuracy_markdown(result["accuracy"])
    if result.get("batches"):
        lines += batches_markdown(result["batches"])
    if result.get("one_grade"):
        lines += one_grade_markdown(result["one_grade"])
    return "\n".join(lines) + "\n"


def _write(result: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "coverage.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (OUT / "coverage.md").write_text(markdown(result), encoding="utf-8")


def main() -> None:
    if "--one-grade" in sys.argv[1:]:  # only the one-grade grid, added to the committed grid
        result = json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))
        result["one_grade"] = one_grade_grid()
        _write(result)
        g = result["one_grade"]["start"]
        print(f"one grade: lowest cell {g['min_cell']:.4f}, average {g['mean']:.4f}, "
              f"passes {g['passes']}")
        return
    if "--batches" in sys.argv[1:]:  # only the batch grid, added to the committed grid
        result = json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))
        result["batches"] = batch_grid()
        _write(result)
        b = result["batches"]
        print(f"batches: lowest cell {b['start']['min_cell']:.4f}, average "
              f"{b['start']['mean']:.4f}, passes {b['start']['passes']}; after asking again "
              f"{b['general']['min_cell']:.4f}, {b['general']['mean']:.4f}, "
              f"passes {b['general']['passes']}")
        return
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
        "accuracy": accuracy(),
        "rows": rows,
        "batches": batch_grid(),
        "one_grade": one_grade_grid(),
    }
    _write(result)
    print(f"chosen level: {chosen}; wrote {OUT / 'coverage.md'} and coverage.json")


def general_method() -> str:
    items = _items(10, 8, 10, 3)
    return weighted.general(items, 600, 400)["interval_methods"]["tpr"]


if __name__ == "__main__":
    main()
