"""TPR, TNR and kappa corrected for how `judgekeeper start` picks answers. Plain Python.

`start` shows the person half answers the judge passed and half it failed, far more fails
than the pool usually holds, so plain rates over the labeled answers would be wrong. The
rates are worked out per group and weighted by group size (the Begg-Greenes correction).

Words: the pool holds N_pass answers the judge passed and N_fail it failed, and
pi = N_pass / (N_pass + N_fail). In the pass group n_p answers are labeled (skips not
counted), c_p of them Correct: a = c_p / n_p. In the fail group n_f, c_f Correct:
b = c_f / n_f. Then:

    TPR = pi a / (pi a + (1 - pi) b)                       of the answers that should pass,
                                                           the share the judge passed
    TNR = (1 - pi)(1 - b) / ((1 - pi)(1 - b) + pi (1 - a)) of the answers that should fail,
                                                           the share the judge failed
    real pass rate = pi a + (1 - pi) b                     the judge's own is pi

Kappa is Cohen's kappa on the weighted table: each labeled answer in the pass group counts
N_pass / n_p, in the fail group N_fail / n_f.

Ranges (Jeffreys draws): each group's share of Correct answers is given the Jeffreys
distribution Beta(c + 0.5, n - c + 0.5). DRAWS pairs (a, b) are drawn with a fixed SEED, TPR,
TNR and the real pass rate are worked out from each pair with the formulas above, and the
range is the middle LEVEL of those values. LEVEL is the first of 95%, 96% and 97% at which
scripts/coverage_check.py finds the ranges hold the true value at least 93 times in 100 in
every cell of its grid and 95 in 100 on average (docs/examples/coverage/coverage.md). A range
is widened, if needed, to hold the number itself (k of k Correct gives a share of 1, which no
draw reaches). A group with no labels has an unknown rate (None), and so does every number
that needs it; an undefined division is unknown too, never an error. Kappa has no range.

After asking the judge again (`general`, `steadiness`), the fresh verdicts may differ from the
saved ones, but the groups stay the saved verdicts: that is how the answers were picked. So
each labeled answer weighs N_group / n_group, TPR is the weighted share of the answers that
should pass that the judge passed, TNR likewise, and kappa is Cohen's kappa on the weighted
table. When the fresh verdicts equal the saved groups this is the form above. Its ranges are
Jeffreys draws too, per saved group: the share marked Correct (p) is Beta(k + 0.5, n - k + 0.5)
as in `corrected`; of those, the share the judge passed again (q), and of those marked Wrong the
share it failed again (r), are Beta(k, m - k): exactly 0 or 1 when none or every one agrees,
and the saved verdict when there is none to tell. So a steady judge (the same verdicts again)
gets `corrected`'s ranges. Each group weighs its pool, TPR and TNR come from each draw of
the weighted table, and the range is the middle LEVEL, widened to hold the number itself.
Kappa has no range here either.
A range never collapses to one point: when one would (the judge got every one right again, or
none), that range draws q and r from Beta(k + 0.5, m - k + 0.5) too ("jeffreys, verdicts too"
in `interval_methods`). A group of the pool with no labels leaves the ranges unknown. A
stratified bootstrap did this before; in scripts/coverage_check.py's grid its ranges held the
true value as rarely as 54 times in 100. Steadiness, the share of answers whose fresh verdicts
are not all the same, is weighted like the real pass rate,
pi f_p + (1 - pi) f_f, with Wilson intervals at 97.5% for each group joined at the corners.
"""

from __future__ import annotations

import random

from judgekeeper.metrics import wilson_interval

Z = 2.2414  # two-sided 97.5%: steadiness, and the corners of a range of zero width
# The middle share of the Jeffreys draws a range spans. Chosen by scripts/coverage_check.py,
# never assumed: the first of 0.95, 0.96 and 0.97 whose ranges hold the true TPR, TNR and real
# pass rate at least 93 times in 100 in every cell of the grid and 95 in 100 on average.
LEVEL = 0.96  # 0.95 held the true value only 91.6 times in 100 in its lowest cell
DRAWS = 20_000  # enough that another seed moves no range by more than about 0.01
SEED = 20261008


def wilson(k: int, n: int, z: float = Z) -> tuple[float | None, float | None]:
    """The Wilson interval for k of n at 97.5%; (None, None) when n is 0."""
    if n <= 0:
        return None, None
    return wilson_interval(k / n, n, z)


def _div(top: float, bottom: float) -> float | None:
    return None if bottom <= 0 else top / bottom


def _tpr(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return _div(pi * a, pi * a + (1 - pi) * b)


def _tnr(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return _div((1 - pi) * (1 - b), (1 - pi) * (1 - b) + pi * (1 - a))


def _pass_rate(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return pi * a + (1 - pi) * b


def _kappa(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    agree = pi * a + (1 - pi) * (1 - b)
    human_pass = pi * a + (1 - pi) * b
    chance = pi * human_pass + (1 - pi) * (1 - human_pass)
    return _div(agree - chance, 1 - chance)


def corrected(n_pool_pass: int, n_pool_fail: int, n_p: int, c_p: int, n_f: int,
              c_f: int, level: float = LEVEL, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Every corrected number, with its range, and the counts it came from.

    A group that the pool does not hold (N = 0) needs no labels: its rate does not count.
    """
    total = n_pool_pass + n_pool_fail
    pi = _div(n_pool_pass, total)
    a, b = _div(c_p, n_p), _div(c_f, n_f)
    samples = jeffreys_samples(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f, draws, seed)
    point = {"a": a, "b": b, "tpr": None, "tnr": None, "kappa": None, "real_pass_rate": None}
    if pi is not None:
        fa = 0.0 if n_pool_pass == 0 else a  # an empty group of the pool: any value gives
        fb = 0.0 if n_pool_fail == 0 else b  # the same numbers
        point.update(tpr=_tpr(pi, fa, fb), tnr=_tnr(pi, fa, fb), kappa=_kappa(pi, fa, fb),
                     real_pass_rate=_pass_rate(pi, fa, fb))
    out = {"pi": pi, "judge_pass_rate": pi, **point}
    for key in ("a", "b", "tpr", "tnr", "real_pass_rate"):
        out[f"{key}_interval"] = middle(samples.get(key), level, point[key])
    out.update(groups={"pass": {"pool": n_pool_pass, "labeled": n_p, "correct": c_p},
                       "fail": {"pool": n_pool_fail, "labeled": n_f, "correct": c_f}},
               method="jeffreys", level=level, draws=draws, seed=seed)
    return out


def jeffreys_samples(n_pool_pass: int, n_pool_fail: int, n_p: int, c_p: int, n_f: int,
                     c_f: int, draws: int = DRAWS, seed: int = SEED) -> dict[str, list[float]]:
    """Sorted draws of a, b, TPR, TNR and the real pass rate; a key is missing when unknown.

    a and b are drawn from Beta(c + 0.5, n - c + 0.5), a first, with one random generator
    seeded with `seed`. A group the pool does not hold has the rate 0 in every draw."""
    total = n_pool_pass + n_pool_fail
    if total <= 0:
        return {}
    pi = n_pool_pass / total
    rng = random.Random(seed)
    rates = {}
    for group, pool, n, c in (("a", n_pool_pass, n_p, c_p), ("b", n_pool_fail, n_f, c_f)):
        if pool == 0:
            rates[group] = [0.0] * draws
        elif n > 0:
            rates[group] = [rng.betavariate(c + 0.5, n - c + 0.5) for _ in range(draws)]
    out = {k: sorted(v) for k, v in rates.items() if (k == "a" and n_pool_pass) or
           (k == "b" and n_pool_fail)}
    if "a" in rates and "b" in rates:
        pairs = list(zip(rates["a"], rates["b"]))
        for key, f in (("tpr", _tpr), ("tnr", _tnr), ("real_pass_rate", _pass_rate)):
            values = [v for x, y in pairs if (v := f(pi, x, y)) is not None]
            if len(values) == len(pairs):
                out[key] = sorted(values)
    return out


def middle(values: list[float] | None, level: float, point: float | None) -> list:
    """The middle `level` of sorted draws, widened to hold `point`; [None, None] when either is
    unknown."""
    if not values or point is None:
        return [None, None]
    lo, hi = _percentile(values, (1 - level) / 2), _percentile(values, (1 + level) / 2)
    return [min(lo, point), max(hi, point)]


def _table(items, weights) -> dict | None:
    """TPR, TNR and kappa of (group, label, verdict) items, each weighing weights[group]."""
    tp = fn = fp = tn = 0.0
    for group, label, verdict in items:
        w = weights[group]
        if label == "pass":
            tp, fn = (tp + w, fn) if verdict == "pass" else (tp, fn + w)
        else:
            fp, tn = (fp + w, tn) if verdict == "pass" else (fp, tn + w)
    total = tp + fn + fp + tn
    if total <= 0:
        return {"tpr": None, "tnr": None, "kappa": None}
    judge, people = (tp + fp) / total, (tp + fn) / total
    chance = judge * people + (1 - judge) * (1 - people)
    return {"tpr": _div(tp, tp + fn), "tnr": _div(tn, tn + fp),
            "kappa": _div((tp + tn) / total - chance, 1 - chance)}


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * q
    low = int(k)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (k - low)


def _verdict_shares(rng: random.Random, k: int, m: int, saved: float, draws: int,
                    jeffreys: bool) -> list[float]:
    """Draws of the share of m answers the judge got right again, k of them. Beta(k, m - k),
    exactly 0 or 1 when none or all did, and the saved verdict (`saved`: 1 or 0) when there is
    none to tell; with `jeffreys`, Beta(k + 0.5, m - k + 0.5) instead."""
    if jeffreys:
        return [rng.betavariate(k + 0.5, m - k + 0.5) for _ in range(draws)]
    if m == 0:
        return [saved] * draws
    if k in (0, m):
        return [k / m] * draws
    return [rng.betavariate(k, m - k) for _ in range(draws)]


def _general_draws(by_group: dict, pool: dict, draws: int, seed: int,
                   jeffreys: bool) -> dict[str, list[float]]:
    """Sorted draws of TPR and TNR of the weighted table (see `general`)."""
    rng = random.Random(seed)
    shares = []  # per group: (pool, draws of p, of q, of r)
    for g, xs in by_group.items():
        if pool[g] <= 0:
            continue
        correct = [x for x in xs if x[1] == "pass"]
        wrong = [x for x in xs if x[1] != "pass"]
        passed = sum(x[2] == "pass" for x in correct)
        failed = sum(x[2] != "pass" for x in wrong)
        shares.append((pool[g],
                       [rng.betavariate(len(correct) + 0.5, len(wrong) + 0.5)
                        for _ in range(draws)],
                       _verdict_shares(rng, passed, len(correct), float(g == "pass"), draws,
                                       jeffreys),
                       _verdict_shares(rng, failed, len(wrong), float(g == "fail"), draws,
                                       jeffreys)))
    values: dict[str, list[float]] = {"tpr": [], "tnr": []}
    for i in range(draws):
        tp = fn = fp = tn = 0.0
        for w, p, q, r in shares:
            tp, fn = tp + w * p[i] * q[i], fn + w * p[i] * (1 - q[i])
            tn, fp = tn + w * (1 - p[i]) * r[i], fp + w * (1 - p[i]) * (1 - r[i])
        for key, value in (("tpr", _div(tp, tp + fn)), ("tnr", _div(tn, tn + fp))):
            if value is not None:
                values[key].append(value)
    return {k: sorted(v) for k, v in values.items()}


def general(items: list[tuple[str, str, str]], n_pool_pass: int, n_pool_fail: int,
            level: float = LEVEL, draws: int = DRAWS, seed: int = SEED) -> dict:
    """TPR, TNR and kappa of the person's labels against fresh verdicts, weighted by the saved
    groups; TPR and TNR with their ranges, kappa without one. `items` are (saved group, label, fresh verdict), each "pass"
    or "fail". A group of the pool with no labeled answer counts for nothing in the numbers,
    and leaves the ranges unknown, as in `corrected`."""
    pool = {"pass": n_pool_pass, "fail": n_pool_fail}
    by_group = {g: [x for x in items if x[0] == g] for g in pool}
    weights = {g: _div(pool[g], len(xs)) or 0.0 for g, xs in by_group.items()}
    out = _table(items, weights)
    keys = ("tpr", "tnr")
    methods = dict.fromkeys(keys, "jeffreys")
    if any(pool[g] > 0 and not xs for g, xs in by_group.items()):
        for key in keys:
            out[f"{key}_interval"] = [None, None]
    else:
        drawn = _general_draws(by_group, pool, draws, seed, jeffreys=False)
        again = None
        for key in keys:
            interval = middle(drawn[key], level, out[key])
            if interval[0] is not None and interval[1] - interval[0] <= 1e-12:  # one point
                again = again or _general_draws(by_group, pool, draws, seed, jeffreys=True)
                interval = middle(again[key], level, out[key])
                methods[key] = "jeffreys, verdicts too"
            out[f"{key}_interval"] = interval
    out.update(interval_methods=methods, level=level, draws=draws, seed=seed,
               groups={g: {"pool": pool[g], "labeled": len(by_group[g])} for g in pool})
    return out


def steadiness(groups: dict[str, tuple[int, int]], n_pool_pass: int,
               n_pool_fail: int) -> dict:
    """The share of answers whose fresh verdicts are not all the same, weighted by the pool's
    groups. `groups` maps "pass" and "fail" (the saved verdicts) to (answers asked, of them
    changed)."""
    total = n_pool_pass + n_pool_fail
    pi = _div(n_pool_pass, total)
    rates, ends = {}, {}
    for g, pool in (("pass", n_pool_pass), ("fail", n_pool_fail)):
        n, changed = groups.get(g, (0, 0))
        if pool == 0:
            rates[g], ends[g] = 0.0, (0.0, 0.0)
        else:
            rates[g], ends[g] = _div(changed, n), wilson(changed, n)
    out = {"changed": sum(c for _, c in groups.values()),
           "of": sum(n for n, _ in groups.values()),
           "groups": {g: {"asked": n, "changed": c} for g, (n, c) in groups.items()}}
    if pi is None or None in (rates["pass"], rates["fail"]):
        return {**out, "rate": None, "interval": [None, None]}

    def mix(a, b):
        return pi * a + (1 - pi) * b

    return {**out, "rate": mix(rates["pass"], rates["fail"]),
            "interval": [mix(ends["pass"][0], ends["fail"][0]),
                         mix(ends["pass"][1], ends["fail"][1])]}
