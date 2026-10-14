"""The verdict on a new rule, from the hidden marks: fixed (old wrong, new right) against broke
(old right, new wrong), out of n hidden marks.

- better / worse: the exact two-sided sign test at 5%;
- safe to try: else, a non-inferiority test (Tango's score test for paired proportions,
  one-sided 2.5%) rules out "more than 10 points worse";
- else can't tell yet: leaning better, the same, or leaning worse.
Each extra test on the same hidden marks is stricter: test k uses the level divided by k.
The cases are a lookup table of the first test worked out by hand; the error check is exact.
"""

from __future__ import annotations

import math

import pytest

from judgekeeper import targets

V = targets.fix_verdict


@pytest.mark.parametrize("fixed, broke, n, kind", [
    (6, 0, 10, "better"), (7, 0, 10, "better"), (8, 1, 10, "better"), (9, 1, 15, "better"),
    (10, 2, 15, "better"),
    (4, 0, 10, "safe"), (3, 0, 10, "safe"), (5, 1, 10, "safe"), (7, 2, 10, "safe"),
    (2, 0, 15, "safe"), (9, 2, 15, "safe"), (10, 3, 15, "safe"),
    (2, 0, 10, "leans better"), (4, 2, 10, "leans better"), (3, 1, 10, "leans better"),
    (1, 0, 10, "leans better"), (6, 3, 15, "leans better"),
    (2, 2, 10, "same"), (0, 0, 10, "same"),
    (1, 3, 10, "leans worse"), (1, 2, 15, "leans worse"),
    (1, 8, 10, "worse"), (0, 6, 10, "worse"), (1, 9, 15, "worse"),
])
def test_the_first_test_matches_the_lookup_table(fixed, broke, n, kind):
    assert V(fixed, broke, n).kind == kind


def test_the_sign_test_is_exact():
    assert targets.sign_p(6, 0) == pytest.approx(0.03125)
    assert targets.sign_p(4, 2) == pytest.approx(0.6875)
    assert targets.sign_p(0, 0) == 1.0


def test_each_extra_test_on_the_same_marks_is_stricter():
    assert V(6, 0, 10, test=1).kind == "better"
    assert V(6, 0, 10, test=2).kind != "better"  # p 0.031 is over 5% / 2
    assert V(7, 0, 10, test=2).kind == "better"  # p 0.016
    assert V(7, 0, 10, test=3).kind == "better"  # 0.016 is under 5% / 3
    assert V(7, 0, 10, test=4).kind != "better"  # but over 5% / 4
    for fixed, broke in ((4, 0), (5, 1), (3, 0)):
        if V(fixed, broke, 10, test=1).kind == "safe":
            assert V(fixed, broke, 10, test=3).kind in ("safe", "leans better")
    assert V(3, 0, 10, test=3).kind == "leans better"


# The exact error, in percent, rounded to one decimal: hidden marks -> P(fixed) -> error
ERROR = {10: {0.0: 0.0, 0.02: 0.0, 0.05: 0.4, 0.10: 1.3, 0.20: 2.7, 0.30: 3.0},
         15: {0.0: 0.0, 0.02: 0.7, 0.05: 1.9, 0.10: 2.3, 0.20: 2.0, 0.30: 2.1}}


@pytest.mark.parametrize("n, pf", [(n, pf) for n in ERROR for pf in ERROR[n]])
def test_safe_to_try_rarely_clears_a_rule_10_points_worse(n, pf):
    """Exact: over every possible result when the new rule is truly 10 points worse, the
    chance of "better" or "safe to try" is about 3% at most."""
    pb, same = pf + 0.10, 1 - 2 * pf - 0.10
    error = sum(math.comb(n, f) * math.comb(n - f, b) * pf ** f * pb ** b * same ** (n - f - b)
                for f in range(n + 1) for b in range(n + 1 - f)
                if V(f, b, n).kind in ("better", "safe"))
    assert round(100 * error, 1) == ERROR[n][pf]


def test_the_top_up_size():
    assert targets.top_up(10) == 7
    assert targets.top_up(15) == 9
    assert targets.top_up(8) == 7 and targets.top_up(20) == 9
