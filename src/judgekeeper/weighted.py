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
"""

from __future__ import annotations

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
