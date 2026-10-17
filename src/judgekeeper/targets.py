"""How many labels a check needs: one set of targets for every command.

`start` uses these: its result and the line under the labeling page's meters. The two kinds
of label are the answers marked Pass and Fail.

- A first result: at least ROUGH of each kind (a count rule).
- A result that is ready: both the TPR range and the TNR range no wider than MAX_WIDTH (from
  the low end to the high end), whatever the counts. The TPR range is about the answers marked
  Pass, the TNR range about those marked Fail.

The words for a number follow the width of its range (width_word): wider than TOO_WIDE, too
early to give a number; down to ROUGH_WIDTH, rough; SHARP_WIDTH or less, sharp. The verdict
follows the ranges, never a number alone (level): each side is "yes" when the low end of its
range reaches RATE_GATE, "no" when the high end stays below it, else "can't tell".

A re-check (`paired_verdict`) compares the old and the new judge on the same marks, one group
at a time (the answers the person passed, and failed): of n marks, now_wrong turned wrong (the
old judge was right, the new one is not) and now_right turned right. The change is
(now_right - now_wrong) / n, and its range is Tango's score range for a paired difference
(Tango 1998), 90% (5% each side), which works with zero cells too. "Worse" when the whole
range is below 0; "no drop bigger than NO_DROP_MARGIN" when its low end is above minus that
margin; else "not sure", which counts as worse (exit 1) only when the drop seen is bigger than
the margin. The low end is always said: the worst drop the marks could hide.

The smallest drop a set of marks can see (`smallest_drop`): the smallest fall in how often the
judge is right, in steps of 5 points, that a re-check of these marks calls "Worse" at least 80
times in 100. Worked out exactly, with no random numbers, for each kind of mark with how often
this judge is right on it (TPR on the answers marked Pass, TNR on those marked Fail): with the
changed judge a right answer turns wrong with the chance that makes the net fall that size,
and a wrong one turns right 3% of the time. The larger of the two is said: a drop both kinds of
mark can see.

`fix_verdict` is the verdict on a new rule tested on the hidden marks (`judgekeeper fix`):
fixed (the old rule was wrong, the new one right) against broke (the other way round), out of
n hidden marks. Better or worse: the exact two-sided sign test at 5%. Else safe to try: Tango's
score test for paired proportions, one-sided 2.5%, rules out the new rule being more than 10
points worse. Else can't tell yet, leaning better, the same or leaning worse. Each extra test
on the same hidden marks (`test` k) uses the levels divided by k, so trying rule after rule
does not turn a coincidence into "better". `top_up` is how many more marks most often settle a
"can't tell yet" (7 with about 10 hidden, 9 with about 15).

Why 0.30: about what 25 + 25 gives when the judge agrees with the person about 85% of the
time and passes half the answers; when the judge passes most answers, its TNR range stays wide
for longer, and the result is not called ready until it is really that narrow
(docs/examples/coverage/coverage.md). The width cut-offs are a judgement, kept as names so they
can change after real use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from statistics import NormalDist

ROUGH = 15
MAX_WIDTH = 0.30
EPS = 1e-9

# The words for a number, by the width of its range (in points / 100)
TOO_WIDE = 0.40  # wider: too early to give a number
ROUGH_WIDTH = 0.30  # wider (up to TOO_WIDE): rough
SHARP_WIDTH = 0.20  # this wide or less: sharp

# The bar a judge is good enough at: the low end of both the TPR and the TNR range reach it.
RATE_GATE = 0.80
# The thresholds of the committed LLMBar example report and the learn page that quotes it;
# the verdict here uses neither (kappa moves with how many answers pass).
KAPPA_GATE = 0.6
RATE_CARE = 0.90

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
    """"too_wide", "rough", None (plain), "sharp" or "exact" for a range; None when it is
    unknown. A width on a cut-off takes the narrower side: 40 points is rough, 30 plain, 20
    sharp."""
    width = _width(interval)
    if width is None:
        return None
    points = _points(width)
    if points <= 0:
        return "exact"
    if points > TOO_WIDE * 100:
        return "too_wide"
    if points > ROUGH_WIDTH * 100:
        return "rough"
    return "sharp" if points <= SHARP_WIDTH * 100 else None


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
    """The verdict from the two ranges: "not_gate" (red) when a side is "no", whatever its
    width; "too_early" (no colour) when a side is wider than TOO_WIDE or unknown; "gate"
    (green) when both are "yes"; else "check" (can't tell yet)."""
    sides = [side(tpr_interval), side(tnr_interval)]
    if "no" in sides:
        return "not_gate"
    if None in sides or "too_wide" in (width_word(tpr_interval), width_word(tnr_interval)):
        return "too_early"
    return "gate" if sides == ["yes", "yes"] else "check"


# A range for a share that stays honest however often it is looked at while marks come in: a
# message shown while the person is still marking that compares a number with the bar must use
# it. Robbins' mixture: the chance of k of n under a uniform mix of shares, against the chance
# under the share p; p is in the range while that ratio stays under 1/ANYTIME_ALPHA.
ANYTIME_ALPHA = 0.05


def _log_mixture(p: float, k: int, n: int) -> float:
    """log of B(k + 1, n - k + 1) / (p^k (1 - p)^(n - k))."""
    if p <= 0 or p >= 1:
        return math.inf if (k if p <= 0 else n - k) else -math.inf
    log_beta = math.lgamma(k + 1) + math.lgamma(n - k + 1) - math.lgamma(n + 2)
    return log_beta - k * math.log(p) - (n - k) * math.log1p(-p)


def anytime_holds(p: float, k: int, n: int, alpha: float = ANYTIME_ALPHA) -> bool:
    """Whether the share p is in the anytime range for k of n."""
    return _log_mixture(p, k, n) < math.log(1 / alpha)


def anytime_range(k: int, n: int, alpha: float = ANYTIME_ALPHA) -> tuple[float, float]:
    """The anytime range for k of n: each end found by halving, from the share k / n (always
    in it) outwards."""
    seen = k / n

    def end(inside: float, outside: float) -> float:
        for _ in range(60):
            mid = (inside + outside) / 2
            if anytime_holds(mid, k, n, alpha):
                inside = mid
            else:
                outside = mid
        return inside

    return end(seen, 0.0), end(seen, 1.0)


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


def check(correct: int, wrong: int, tpr_interval, tnr_interval) -> dict:
    """{"check": "too_few" | "rough" | "reliable", "wide": {"tpr" | "tnr": width or None}}.

    Under ROUGH of each kind there is no result yet (a count rule). After that the result is
    reliable when both ranges are MAX_WIDTH wide or less; `wide` names each one that is wider,
    or unknown (None)."""
    if min(correct, wrong) < ROUGH:
        return {"check": "too_few", "wide": {}}
    wide = {}
    exact = False  # a range of no width: exact, but no sign that the marks are enough
    for key, interval in (("tpr", tpr_interval), ("tnr", tnr_interval)):
        width = _width(interval)
        if width is None or width > MAX_WIDTH + EPS:
            wide[key] = width
        elif width <= EPS:
            exact = True
    return {"check": "rough" if wide or exact else "reliable", "wide": wide}


def _pmf(n: int, p: float) -> list[float]:
    """Binomial(n, p) probabilities of 0..n, in logs so a large n does not overflow."""
    if p <= 0:
        return [1.0] + [0.0] * n
    if p >= 1:
        return [0.0] * n + [1.0]
    lp, lq = math.log(p), math.log1p(-p)
    return [math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                     + k * lp + (n - k) * lq) for k in range(n + 1)]


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


def paired_range(now_right: int, now_wrong: int, n: int,
                 level: float = PAIRED_LEVEL) -> tuple[float, float]:
    """The range of the change (new right minus old right, as a share of the n marks): every
    change whose score is within the two-sided `level` (the score falls as the change grows,
    so each end is found by halving)."""
    z = NormalDist().inv_cdf((1 + level) / 2)
    seen = (now_right - now_wrong) / n

    def end(lo: float, hi: float, target: float) -> float:
        for _ in range(60):
            mid = (lo + hi) / 2
            if _score(now_right, now_wrong, n, mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    return end(-1.0, seen, z), end(seen, 1.0, -z)


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


@lru_cache(maxsize=512)
def _worse_from(n: int) -> tuple[int, ...]:
    """For each count turned right (0..n), the fewest turned wrong that a re-check of n marks
    calls "Worse" (n + 1 when none does). More turned wrong only lowers the range."""
    out = []
    for right in range(n + 1):
        lo, hi = right, n - right + 1  # the first count turned wrong with the range below 0
        while lo < hi:
            mid = (lo + hi) // 2
            if paired_range(right, mid, n)[1] < 0:
                hi = mid
            else:
                lo = mid + 1
        out.append(lo)
    return tuple(out)


def _power(n: int, drop: float, right: float, turns: float = TURNS_RIGHT) -> float:
    """How often a re-check of n marks calls a fall of `drop` (0 to 1) "Worse"."""
    p_wrong = (drop + (1 - right) * turns)  # right * (the chance a right one turns wrong)
    p_right = (1 - right) * turns
    need = _worse_from(n)
    caught = 0.0
    for k_right, chance in enumerate(_pmf(n, p_right)):
        if chance < 1e-300 or need[k_right] > n - k_right:
            continue
        rest = _pmf(n - k_right, min(p_wrong / (1 - p_right), 1.0))
        caught += chance * sum(rest[need[k_right]:])
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


def fix_verdict(fixed: int, broke: int, n: int, test: int = 1) -> FixVerdict:
    """The verdict on a new rule from `n` hidden marks; `test` is how many tests these marks
    have now served, this one included."""
    k = max(1, test)
    if sign_p(fixed, broke) < SIGN_LEVEL / k:
        kind = "better" if fixed > broke else "worse"
    elif n and tango_z(fixed, broke, n, -SAFE_MARGIN) > NormalDist().inv_cdf(1 - SAFE_LEVEL / k):
        kind = "safe"
    elif fixed > broke:
        kind = "leans better"
    elif fixed == broke:
        kind = "same"
    else:
        kind = "leans worse"
    return FixVerdict(kind, fixed, broke, n)


def top_up(n: int) -> int:
    """How many more marks most often settle a "can't tell yet" on `n` hidden marks."""
    return 7 if n <= 12 else 9
