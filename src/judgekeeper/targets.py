"""How many marks a check needs, and the verdicts on the numbers: one set for every command.

A first result needs ROUGH marks of each kind. The verdict follows the ranges, never a number
alone (level), and is given the wider verdict ranges (weighted.VERDICT_LEVEL), since the person
can look after every mark. No rule shows or hides a number by its range's width: a narrow
early range is often a lucky one.

`paired_verdict` compares the old and new LLM-as-a-judge on the same marks with Tango's score
range for a paired difference (90%), which works with zero cells too; the worst drop the marks
could hide is always said. `smallest_drop` is worked out exactly, with no random numbers.
`fix_verdict` tests a new rule on the hidden marks: the exact sign test, then Tango's test for
"safe to try", on counts weighted to the whole set of answers (`weighted_counts`); each extra
rule on the same marks divides the levels, so trying rule after rule does not turn a
coincidence into "better".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from statistics import NormalDist

ROUGH = 15
EPS = 1e-9

# The bar a judge is good enough at: the low end of both the TPR and the TNR range reach it.
RATE_GATE = 0.80

# A re-check: the paired range and the margin a drop must stay within (see the top)
PAIRED_LEVEL = 0.90
NO_DROP_MARGIN = 0.20

# The smallest drop: the model (see the top of this file)
RIGHT_NOW = 0.90  # how often the judge is right, when its rate is not known
TURNS_RIGHT = 0.03
POWER = 0.80
DROP_STEP = 5  # points


def _width(interval) -> float | None:
    if not interval or interval[0] is None or interval[1] is None:
        return None
    return interval[1] - interval[0]


def _points(width: float) -> float:
    """A width rounded to a hundredth of a point, so 0.4 worked out in floating point is 40."""
    return round(width * 100, 2)


def width_word(interval) -> str | None:
    """"exact" for a range of no width; else None (also when it is unknown)."""
    width = _width(interval)
    return "exact" if width is not None and _points(width) <= 0 else None


def side(interval) -> str | None:
    """"yes", "no" or "cant_tell" for one rate's range against RATE_GATE; None unknown."""
    if not interval or interval[0] is None or interval[1] is None:
        return None
    lo, hi = round(interval[0], 9), round(interval[1], 9)
    if lo >= RATE_GATE:
        return "yes"
    if hi < RATE_GATE:
        return "no"
    return "cant_tell"


def level(tpr_interval, tnr_interval) -> str:
    """The verdict from the two (verdict) ranges: "not_gate" (red) when a side is "no";
    "too_early" (no colour) when a side is unknown; "gate" (green) when both are "yes"; else
    "check" (can't tell yet). The width never decides."""
    sides = [side(tpr_interval), side(tnr_interval)]
    if "no" in sides:
        return "not_gate"
    if None in sides:
        return "too_early"
    return "gate" if sides == ["yes", "yes"] else "check"


def slip_rate(changed: float) -> float:
    """How often the person slips when marking, from the share of repeats (the same answer
    marked twice) marked differently: two marks differ when one of them slips, so
    changed = 2e(1 - e)."""
    return (1 - math.sqrt(max(1 - 2 * changed, 0.0))) / 2


def best_possible(real_pass: float, slip: float) -> dict:
    """The TPR and TNR even a perfect judge would show against marks that slip this often,
    when this share of the answers should pass. Never used to change a number."""
    p, e = real_pass, slip
    return {"tpr": p * (1 - e) / (p * (1 - e) + (1 - p) * e),
            "tnr": (1 - p) * (1 - e) / ((1 - p) * (1 - e) + p * e)}


def check(correct: int, wrong: int) -> dict:
    """{"check": "too_few" | "result"}: under ROUGH of each kind there is no result yet (a
    count rule, never a width)."""
    return {"check": "too_few" if min(correct, wrong) < ROUGH else "result"}


TINY = 1e-300  # a chance under this adds nothing the power can show


def _pmf(n: int, p: float, least: int = 0) -> tuple[int, list[float]]:
    """(first k, the Binomial(n, p) probabilities from k on) over the counts from `least` up
    whose chance is not far under TINY, walked out from the likeliest, in logs so a large n
    does not overflow. The counts left out add nothing a float can hold."""
    if p <= 0:
        return 0, [1.0]
    if p >= 1:
        return n, [1.0]
    lp, lq, ln = math.log(p), math.log1p(-p), math.lgamma(n + 1)
    floor = math.log(TINY) - 50

    def log_chance(k: int) -> float:
        return ln - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq

    top = max(min(n, int((n + 1) * p)), least)
    odds = lp - lq
    down, up = [], [log_chance(top)]
    while (k := top - len(down)) > least:  # k - 1 from k: times k / (n - k + 1) / odds
        v = (down[-1] if down else up[0]) + math.log(k / (n - k + 1)) - odds
        if v <= floor:
            break
        down.append(v)
    while (k := top + len(up) - 1) < n:  # k + 1 from k: times (n - k) / (k + 1) * odds
        v = up[-1] + math.log((n - k) / (k + 1)) + odds
        if v <= floor:
            break
        up.append(v)
    return top - len(down), [math.exp(v) for v in (*reversed(down), *up)]


def _score(right: int, wrong: int, n: int, change: float) -> float:
    """Tango's score for "the change is `change`": the observed change minus it, over its
    standard error with the cells' chances fitted under that change (their closed form)."""
    a = 2 * n
    b = -right - wrong + (2 * n - right + wrong) * change
    c = -wrong * change * (1 - change)
    p_wrong = (math.sqrt(max(b * b - 4 * a * c, 0.0)) - b) / (2 * a)
    variance = n * (2 * p_wrong + change - change * change)
    diff = right - wrong - n * change
    if variance <= 0:
        return math.copysign(math.inf, diff) if diff else 0.0
    return diff / math.sqrt(variance)


def _end(now_right: int, now_wrong: int, n: int, lo: float, hi: float, target: float) -> float:
    """One end of paired_range, found by halving."""
    for _ in range(60):
        mid = (lo + hi) / 2
        if _score(now_right, now_wrong, n, mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _z(level: float) -> float:
    return NormalDist().inv_cdf((1 + level) / 2)


def paired_range(now_right: int, now_wrong: int, n: int,
                 level: float = PAIRED_LEVEL) -> tuple[float, float]:
    """The range of the change (new right minus old right, as a share of the n marks): every
    change whose score is within the two-sided `level` (the score falls as the change grows,
    so each end is found by halving)."""
    z, seen = _z(level), (now_right - now_wrong) / n
    return (_end(now_right, now_wrong, n, -1.0, seen, z),
            _end(now_right, now_wrong, n, seen, 1.0, -z))


def _paired_high(now_right: int, now_wrong: int, n: int) -> float:
    """paired_range's top end alone."""
    return _end(now_right, now_wrong, n, (now_right - now_wrong) / n, 1.0, -_z(PAIRED_LEVEL))


def paired_verdict(now_right: int, now_wrong: int, n: int) -> dict:
    """The re-check of one group of n marks: {"change", "low", "high", "now_right",
    "now_wrong", "n", "verdict": "worse" | "no_drop" | "not_sure", "exit_worse"}."""
    change = (now_right - now_wrong) / n
    low, high = paired_range(now_right, now_wrong, n)
    if high < 0:
        verdict = "worse"
    elif low > -NO_DROP_MARGIN:
        verdict = "no_drop"
    else:
        verdict = "not_sure"
    exit_worse = verdict == "worse" or (verdict == "not_sure"
                                         and round(-change, 9) > NO_DROP_MARGIN)
    return {"change": change, "low": low, "high": high, "now_right": now_right,
            "now_wrong": now_wrong, "n": n, "verdict": verdict, "exit_worse": exit_worse}


@lru_cache(maxsize=1 << 16)
def _worse_from(n: int, right: int) -> int:
    """With `right` turned right, the fewest turned wrong that a re-check of n marks calls
    "Worse" (n + 1 when none does). More turned wrong only lowers the range."""
    lo, hi = right, n - right + 1  # the first count turned wrong with the range below 0
    while lo < hi:
        mid = (lo + hi) // 2
        if _paired_high(right, mid, n) < 0:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _power(n: int, drop: float, right: float, turns: float = TURNS_RIGHT) -> float:
    """How often a re-check of n marks calls a fall of `drop` (0 to 1) "Worse". Only the
    counts that can happen are worked out (_pmf): thousands of imported marks stay quick."""
    p_wrong = (drop + (1 - right) * turns)  # right * (the chance a right one turns wrong)
    p_right = (1 - right) * turns
    caught = 0.0
    first, chances = _pmf(n, p_right)
    for k_right, chance in enumerate(chances, start=first):
        if chance < TINY:
            continue
        need = _worse_from(n, k_right)
        if need > n - k_right:
            continue
        start, rest = _pmf(n - k_right, min(p_wrong / (1 - p_right), 1.0), need)
        caught += chance * sum(rest[max(need - start, 0):])
    return caught


def _smallest(n: int, right: float) -> int | None:
    for drop in range(DROP_STEP, 100, DROP_STEP):
        if drop / 100 + (1 - right) * TURNS_RIGHT > right:  # more than the judge gets right
            return None
        if _power(n, drop / 100, right) >= POWER:
            return drop
    return None


def smallest_drop(n_pass: int, n_fail: int, tpr: float | None = None,
                  tnr: float | None = None) -> int | None:
    """The smallest drop, in points, these marks can see (top of this file); None under
    ROUGH of each kind, or when a kind of mark can see none. `tpr` and `tnr`: how often this
    judge is right on the answers marked Pass and Fail (RIGHT_NOW when not known)."""
    if min(n_pass, n_fail) < ROUGH:
        return None
    drops = [_smallest(n, RIGHT_NOW if rate is None else max(rate, 0.01))
             for n, rate in ((n_pass, tpr), (n_fail, tnr))]
    return None if None in drops else max(drops)


# The verdict on a new rule ---------------------------------------------------------------------

SIGN_LEVEL = 0.05  # two-sided, better or worse
SAFE_LEVEL = 0.025  # one-sided, safe to try
SAFE_MARGIN = 0.10  # safe to try: not more than 10 points worse
FIX_FEW = 3  # fewer of the judge's mistakes hidden than this: a test can only catch worse


@dataclass(frozen=True)
class FixVerdict:
    kind: str  # "better", "safe", "leans better", "same", "leans worse" or "worse"
    fixed: int
    broke: int
    n: int
    strata: tuple = ()  # (pool, fixed, broke, kept aside) per group, when weighted


def sign_p(fixed: int, broke: int) -> float:
    """The exact two-sided sign test of fixed against broke (binomial, p = 0.5)."""
    d = fixed + broke
    if not d:
        return 1.0
    tail = sum(math.comb(d, i) for i in range(min(fixed, broke) + 1))
    return min(1.0, 2 * tail / 2 ** d)


def tango_z(fixed: int, broke: int, n: int, delta0: float) -> float:
    """Tango's (1998) score statistic for paired proportions, against a difference of
    `delta0` (new right minus old right, as a share of n)."""
    a = 2 * n
    b = -fixed - broke + (2 * n - fixed + broke) * delta0
    c = -broke * delta0 * (1 - delta0)
    q21 = (math.sqrt(max(b * b - 4 * a * c, 0.0)) - b) / (2 * a)
    var = n * (2 * q21 + delta0 * (1 - delta0))
    return 0.0 if var <= 0 else (fixed - broke - n * delta0) / math.sqrt(var)


def weighted_counts(strata) -> tuple[float, float, float]:
    """(fixed, broke, n) for the tests, weighted to the whole set of answers. `strata`: per
    group the marks were picked from, (its pool N_s, fixed, broke, marks kept aside h_s). Each
    kept-aside mark weighs N_s / h_s, as the numbers weigh it, scaled so the weights add up to
    the effective number of marks, (sum w)^2 / sum w^2 (Kish): unequal weights hold less than
    as many equal ones. Equal weights give the plain counts. A group with no mark kept aside
    weighs nothing."""
    live = [(N, f, b, h) for N, f, b, h in strata if N > 0 and h > 0]
    total = sum(N for N, *_ in live)
    if not total:
        return 0.0, 0.0, 0.0
    n_eff = total ** 2 / sum(N * N / h for N, _, _, h in live)
    fixed = sum(N * f / h for N, f, _, h in live) * n_eff / total
    broke = sum(N * b / h for N, _, b, h in live) * n_eff / total
    return fixed, broke, n_eff


def fix_verdict(fixed: int, broke: int, n: int, test: int = 1,
                strata=None) -> FixVerdict:
    """The verdict on a new rule from `n` hidden marks; `test` is how many tests these marks
    have now served, this one included. With `strata` (see weighted_counts) the tests run on
    the weighted counts, the sign test on them rounded; the verdict keeps the plain counts,
    which are what the person is shown."""
    k = max(1, test)
    f, b, size = weighted_counts(strata) if strata else (fixed, broke, n)
    if sign_p(round(f), round(b)) < SIGN_LEVEL / k:
        kind = "better" if f > b else "worse"
    elif size and tango_z(f, b, size, -SAFE_MARGIN) > NormalDist().inv_cdf(1 - SAFE_LEVEL / k):
        kind = "safe"
    elif f > b:
        kind = "leans better"
    elif f == b:
        kind = "same"
    else:
        kind = "leans worse"
    return FixVerdict(kind, fixed, broke, n, tuple(tuple(s) for s in strata or ()))
