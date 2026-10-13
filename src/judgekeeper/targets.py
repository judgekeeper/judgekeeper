"""How many labels a check needs: one set of targets for every command.

`start` uses these: its result and the line under the labeling page's meters. The two kinds
of label are the answers marked Pass and Fail.

- A rough check: at least ROUGH of each kind.
- A reliable result: at least RELIABLE of each kind, and both the TPR range and the TNR range
  no wider than MAX_WIDTH (from the low end to the high end). The TPR range is about the
  answers marked Pass, the TNR range about those marked Fail.

The smallest drop a set of marks can see (`smallest_drop`): the smallest fall in how often the
judge is right, in steps of 5 points, that checking these marks again would catch at least 80
times in 100. Worked out exactly, with no random numbers: the judge is right on 90% of answers
now; with the changed judge a right answer turns wrong with the chance that makes the net fall
that size, and a wrong one turns right 3% of the time; a one-sided sign test at 5% on the
answers that changed. It uses the fewer kind of mark (Pass or Fail). Once judgekeeper has
asked the judge again about the marked answers (the baseline), it uses the judge's measured
steadiness instead: how often its verdict changed (at least 1%) and how often it was right.

`got_worse` is that same test on a re-check: of the answers whose verdict changed, the ones
the new judge now gets wrong against the ones it now gets right.

Why 0.30: about what 25 + 25 gives when the judge agrees with the person about 85% of the
time and passes half the answers, so such checks are reliable at 25 of each; when the judge
passes most answers, its TNR range stays wide for longer, and the result is not called
reliable until it is really that narrow (docs/examples/coverage/coverage.md).
"""

from __future__ import annotations

import math

ROUGH = 15
RELIABLE = 25
MAX_WIDTH = 0.30
EPS = 1e-9
START_NAMES = ("answers you marked Correct", "answers you marked Wrong")

# What the result calls good. Kappa at or above KAPPA_GATE is good. TPR and TNR are the
# numbers to act on: below RATE_GATE the judge is not fit to be a gate, below RATE_CARE it is
# usable with care.
KAPPA_GATE = 0.6
RATE_GATE = 0.80
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


def check(correct: int, wrong: int, tpr_interval, tnr_interval) -> dict:
    """{"check": "too_few" | "rough" | "reliable", "wide": {"tpr" | "tnr": width or None}}.

    `wide` names a range that keeps a check with RELIABLE of each from being reliable: wider
    than MAX_WIDTH, or unknown (None). It is empty below RELIABLE of each."""
    least = min(correct, wrong)
    if least < ROUGH:
        return {"check": "too_few", "wide": {}}
    if least < RELIABLE:
        return {"check": "rough", "wide": {}}
    wide = {}
    exact = False  # a range of no width: exact, but no sign that the marks are enough
    for key, interval in (("tpr", tpr_interval), ("tnr", tnr_interval)):
        width = _width(interval)
        if width is None or width > MAX_WIDTH + EPS:
            wide[key] = width
        elif width <= EPS:
            exact = True
    return {"check": "rough" if wide or exact else "reliable", "wide": wide}


def line(result: dict, names: tuple[str, str] = START_NAMES) -> str:
    """How far along a check is and what to do, in one or two sentences."""
    if result["check"] == "too_few":
        return f"A rough check needs {ROUGH} of each."
    if result["check"] == "reliable":
        return "Reliable result ready."
    wide = result["wide"]
    if not wide:
        return f"Rough check ready. A reliable result needs {RELIABLE} of each."
    sides = [names[0] if key == "tpr" else names[1] for key in wide]
    if None in wide.values():
        unknown = [names[0] if key == "tpr" else names[1] for key, w in wide.items() if w is None]
        return (f"Not reliable yet: the range for {' and '.join(unknown)} is not known yet. "
                "Label more answers.")
    widths = " and ".join(f"{w:.2f}" for w in wide.values())
    if len(sides) == 1:
        return (f"Not reliable yet: the range for {sides[0]} is still {widths} wide. Label "
                "more answers to narrow it.")
    return (f"Not reliable yet: the ranges for {sides[0]} and {sides[1]} are still {widths} "
            "wide. Label more answers to narrow them.")


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
