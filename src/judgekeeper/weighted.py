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

Intervals (95%, no randomness): a Wilson interval for a and for b, each at 97.5% (Z), so both
hold together at 95% or more. TPR and TNR rise with a and fall with b, the real pass rate
rises with both, so the interval ends go into the formulas. A group with no labels has an
unknown rate (None), and so does every number that needs it; an undefined division is
unknown too, never an error. Kappa has no interval.

After asking the judge again (`general`, `steadiness`), the fresh verdicts may differ from the
saved ones, but the groups stay the saved verdicts: that is how the answers were picked. So
each labeled answer weighs N_group / n_group, TPR is the weighted share of the answers that
should pass that the judge passed, TNR likewise, and kappa is Cohen's kappa on the weighted
table. When the fresh verdicts equal the saved groups this is the form above. Its intervals
come from a stratified bootstrap with a fixed seed (each group resampled on its own, 2,000
times, percentile), so the same data always gives the same numbers. Steadiness, the share of
answers whose fresh verdicts are not all the same, is weighted like the real pass rate,
pi f_p + (1 - pi) f_f, with Wilson intervals at 97.5% for each group joined at the corners.
"""

from __future__ import annotations

import random

from judgekeeper.metrics import wilson_interval

Z = 2.2414  # two-sided 97.5%


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
              c_f: int) -> dict:
    """Every corrected number, with its interval, and the counts it came from.

    A group that the pool does not hold (N = 0) needs no labels: its rate does not count.
    """
    total = n_pool_pass + n_pool_fail
    pi = _div(n_pool_pass, total)
    rate = {"pass": None, "fail": None}
    bounds = {"pass": (None, None), "fail": (None, None)}
    for group, n, c in (("pass", n_p, c_p), ("fail", n_f, c_f)):
        rate[group] = _div(c, n)
        bounds[group] = wilson(c, n)
    a, b = rate["pass"], rate["fail"]
    (a_lo, a_hi), (b_lo, b_hi) = bounds["pass"], bounds["fail"]
    if pi is not None:  # an empty group of the pool: any value gives the same numbers
        if n_pool_fail == 0:
            b = b_lo = b_hi = 0.0
        if n_pool_pass == 0:
            a = a_lo = a_hi = 0.0
    p = 0.0 if pi is None else pi
    if pi is None:
        a = b = None
    return {
        "pi": pi,
        "judge_pass_rate": pi,
        "a": rate["pass"], "a_interval": list(bounds["pass"]),
        "b": rate["fail"], "b_interval": list(bounds["fail"]),
        "tpr": _tpr(p, a, b),
        "tpr_interval": _ends(_tpr, p, (a_lo, b_hi), (a_hi, b_lo)),
        "tnr": _tnr(p, a, b),
        "tnr_interval": _ends(_tnr, p, (a_lo, b_hi), (a_hi, b_lo)),
        "kappa": _kappa(p, a, b),
        "real_pass_rate": _pass_rate(p, a, b),
        "real_pass_rate_interval": _ends(_pass_rate, p, (a_lo, b_lo), (a_hi, b_hi)),
        "groups": {"pass": {"pool": n_pool_pass, "labeled": n_p, "correct": c_p},
                   "fail": {"pool": n_pool_fail, "labeled": n_f, "correct": c_f}},
        "z": Z,
    }


def _ends(f, pi: float, low: tuple, high: tuple) -> list:
    lo, hi = f(pi, *low), f(pi, *high)
    if lo is None or hi is None:
        return [None, None]
    return [lo, hi]


BOOT_SEED = 20261005
RESAMPLES = 2000


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


def general(items: list[tuple[str, str, str]], n_pool_pass: int, n_pool_fail: int,
            seed: int = BOOT_SEED, resamples: int = RESAMPLES) -> dict:
    """TPR, TNR and kappa of the person's labels against fresh verdicts, weighted by the saved
    groups. `items` are (saved group, label, fresh verdict), each "pass" or "fail"."""
    pool = {"pass": n_pool_pass, "fail": n_pool_fail}
    by_group = {g: [x for x in items if x[0] == g] for g in pool}
    weights = {g: _div(pool[g], len(xs)) or 0.0 for g, xs in by_group.items()}
    out = _table(items, weights)
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {k: [] for k in out}
    for _ in range(resamples):
        sample = [rng.choice(xs) for xs in by_group.values() for _ in xs]
        for key, value in _table(sample, weights).items():
            if value is not None:
                draws[key].append(value)
    for key in ("tpr", "tnr", "kappa"):
        values = draws[key]
        out[f"{key}_interval"] = ([_percentile(values, 0.025), _percentile(values, 0.975)]
                                  if values and out[key] is not None else [None, None])
    out.update(resamples=resamples, seed=seed,
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
