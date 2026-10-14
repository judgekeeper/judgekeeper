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

The smallest drop a set of marks can see (`smallest_drop`): the smallest fall in how often the
judge is right, in steps of 5 points, that checking these marks again would catch at least 80
times in 100. Worked out exactly, with no random numbers: the judge is right on 90% of answers
now; with the changed judge a right answer turns wrong with the chance that makes the net fall
that size, and a wrong one turns right 3% of the time; a one-sided sign test at 5% on the
answers that changed. It uses the fewer kind of mark (Pass or Fail). Once judgekeeper has
asked the judge again about the marked answers (the baseline), it uses the judge's measured
steadiness instead: how often its verdict changed (at least 1%) and how often it was right.

Why 0.30: about what 25 + 25 gives when the judge agrees with the person about 85% of the
time and passes half the answers; when the judge passes most answers, its TNR range stays wide
for longer, and the result is not called ready until it is really that narrow
(docs/examples/coverage/coverage.md). The width cut-offs are a judgement, kept as names so they
can change after real use.
"""

from __future__ import annotations

import math

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

# The smallest drop: the model and the test (see the top of this file)
RIGHT_NOW = 0.90
TURNS_RIGHT = 0.03
ALPHA = 0.05
POWER = 0.80
DROP_STEP = 5  # points
MIN_FLIP = 0.01  # a measured flip rate counts as at least this
MIN_RIGHT = 0.5  # a judge measured as right less often than this counts as this
DROP_MODEL = ("The smallest drop assumes your judge is right on 9 in 10 answers now, and is the "
              "smallest fall a re-check of these marks catches 80 times in 100 (a one-sided "
              "sign test at 5%).")


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


def _critical(m: int) -> int:
    """The fewest of m changed answers that must have turned wrong for the sign test to say
    the judge got worse: P(Binomial(m, 1/2) >= k) <= ALPHA, worked out in whole numbers."""
    tail, total = 0, 2 ** m
    for k in range(m, -1, -1):
        tail += math.comb(m, k)
        if tail * 20 > total:  # ALPHA is 1/20
            return k + 1
    return 0


def got_worse(now_wrong: int, now_right: int) -> bool:
    """Whether a re-check shows the judge got worse: the one-sided sign test at 5% on the
    answers whose verdict changed (`now_wrong` turned wrong, `now_right` turned right)."""
    m = now_wrong + now_right
    return m > 0 and now_wrong >= _critical(m)


def _power(n: int, drop: float, right: float = RIGHT_NOW, turns: float = TURNS_RIGHT) -> float:
    """How often a re-check of n marks catches a fall of `drop` (0 to 1)."""
    worse = (drop + (1 - right) * turns) / right  # a right answer turns wrong
    p_worse, p_better = right * worse, (1 - right) * turns
    changed = _pmf(n, p_worse + p_better)
    share = p_worse / (p_worse + p_better)
    caught = 0.0
    for m in range(1, n + 1):
        if changed[m] < 1e-300:
            continue
        k = _critical(m)
        if k <= m:
            caught += changed[m] * sum(_pmf(m, share)[k:])
    return caught


def smallest_drop(n_pass: int, n_fail: int, flip: float | None = None,
                  right: float | None = None) -> int | None:
    """The smallest drop, in points, these marks can see (top of this file); None under
    ROUGH of each kind. `flip` and `right` are the judge's measured steadiness (how often its
    verdict changed when asked again, at least MIN_FLIP; how often it was right), used in
    place of TURNS_RIGHT and RIGHT_NOW."""
    n = min(n_pass, n_fail)
    if n < ROUGH:
        return None
    turns = TURNS_RIGHT if flip is None else max(flip, MIN_FLIP)
    now = RIGHT_NOW if right is None else min(max(right, MIN_RIGHT), 1.0)
    for drop in range(DROP_STEP, 100, DROP_STEP):
        if (drop / 100 + (1 - now) * turns) / now > 1:
            return None
        if _power(n, drop / 100, now, turns) >= POWER:
            return drop
    return None


def drop_line(drop: int | None) -> str | None:
    if drop is None:
        return None
    return f"This set can see a drop of {drop} points or more. Smaller changes need more marks."
