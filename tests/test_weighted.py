"""The numbers `judgekeeper start` reports, corrected for picking half from the judge's passes
and half from its fails (weighted.py). Every expected value is worked out by hand below.

Words: the pool holds N_pass answers the judge passed and N_fail it failed, pi = N_pass / N.
In the pass group n_p answers are labeled, c_p of them Correct: a = c_p / n_p. In the fail
group n_f are labeled, c_f Correct: b = c_f / n_f.
"""

from __future__ import annotations

import math

import pytest

from judgekeeper import weighted
from judgekeeper.metrics import cohen_kappa


def test_the_interval_z_is_for_two_intervals_at_97_5_percent():
    assert weighted.Z == 2.2414


def test_the_worked_example():
    # Pool 900 passes, 100 fails; 25 labeled in each; 20 and 10 Correct.
    # pi = 0.9, a = 0.8, b = 0.4
    # TPR = 0.9*0.8 / (0.9*0.8 + 0.1*0.4) = 0.72 / 0.76 = 0.947...
    # TNR = 0.1*0.6 / (0.1*0.6 + 0.9*0.2) = 0.06 / 0.24 = 0.25
    # real pass rate = 0.72 + 0.04 = 0.76; the judge passes 0.9
    r = weighted.corrected(900, 100, 25, 20, 25, 10)
    assert r["pi"] == pytest.approx(0.9)
    assert r["a"] == pytest.approx(0.8) and r["b"] == pytest.approx(0.4)
    assert r["tpr"] == pytest.approx(0.72 / 0.76)
    assert r["tpr"] == pytest.approx(0.95, abs=0.005)
    assert r["tnr"] == pytest.approx(0.25)
    assert r["real_pass_rate"] == pytest.approx(0.76)
    assert r["judge_pass_rate"] == pytest.approx(0.9)


def test_kappa_on_the_weighted_table():
    # Weights: pass group 900/25 = 36, fail group 100/25 = 4. The table:
    #   judge pass, Correct 20*36 = 720    judge pass, Wrong 5*36 = 180
    #   judge fail, Correct 10*4  = 40     judge fail, Wrong 15*4 = 60
    # po = (720 + 60) / 1000 = 0.78; human pass share 0.76, judge pass share 0.9
    # pe = 0.9*0.76 + 0.1*0.24 = 0.708; kappa = (0.78 - 0.708) / 0.292 = 0.2466
    r = weighted.corrected(900, 100, 25, 20, 25, 10)
    assert r["kappa"] == pytest.approx(0.072 / 0.292)
    judge = ["pass"] * 900 + ["fail"] * 100
    human = ["pass"] * 720 + ["fail"] * 180 + ["pass"] * 40 + ["fail"] * 60
    assert r["kappa"] == pytest.approx(cohen_kappa(human, judge))


def test_groups_labeled_in_the_pool_shares_give_the_plain_rates():
    # 60 passes and 40 fails in the pool, labeled 30 and 20: no correction needed.
    # Correct: 24 + 5 = 29, of which the judge passed 24 -> TPR 24/29
    # Wrong: 6 + 15 = 21, of which the judge failed 15 -> TNR 15/21
    r = weighted.corrected(60, 40, 30, 24, 20, 5)
    assert r["tpr"] == pytest.approx(24 / 29)
    assert r["tnr"] == pytest.approx(15 / 21)
    human = ["pass"] * 24 + ["fail"] * 6 + ["pass"] * 5 + ["fail"] * 15
    judge = ["pass"] * 30 + ["fail"] * 20
    assert r["kappa"] == pytest.approx(cohen_kappa(human, judge))


def test_a_group_with_no_labels_is_unknown_never_an_error():
    r = weighted.corrected(900, 100, 10, 8, 0, 0)
    assert r["b"] is None and r["b_interval"] == [None, None]
    for key in ("tpr", "tnr", "kappa", "real_pass_rate"):
        assert r[key] is None, key
    for key in ("tpr_interval", "tnr_interval", "real_pass_rate_interval"):
        assert r[key] == [None, None], key
    assert r["a"] == pytest.approx(0.8)


def test_nothing_labeled_is_unknown():
    r = weighted.corrected(30, 20, 0, 0, 0, 0)
    assert r["tpr"] is None and r["tnr"] is None and r["kappa"] is None
    assert r["judge_pass_rate"] == pytest.approx(0.6)


def test_undefined_divisions_are_unknown():
    # Every labeled answer Correct: no answer should fail, so TNR has nothing to count.
    # po = 0.5, pe = 0.5*1 + 0.5*0 = 0.5, so kappa = 0.
    r = weighted.corrected(50, 50, 10, 10, 10, 10)
    assert r["tpr"] == pytest.approx(0.5)
    assert r["tnr"] is None
    assert r["kappa"] == pytest.approx(0.0)
    # Judge and labels all one way: chance agreement is the whole agreement.
    r = weighted.corrected(50, 0, 10, 10, 0, 0)
    assert r["tpr"] == pytest.approx(1.0) and r["tnr"] is None and r["kappa"] is None


@pytest.mark.parametrize("counts", [
    (900, 100, 25, 20, 25, 10), (60, 40, 30, 24, 20, 5), (171, 41, 16, 15, 15, 5),
    (100, 100, 3, 0, 3, 3), (500, 20, 25, 25, 20, 0), (40, 400, 1, 1, 1, 0),
])
def test_intervals_hold_the_point_and_stay_between_0_and_1(counts):
    r = weighted.corrected(*counts)
    for key in ("a", "b", "tpr", "tnr", "real_pass_rate"):
        if r[key] is None:
            continue
        lo, hi = r[f"{key}_interval"]
        assert 0 <= lo <= r[key] + 1e-12 and r[key] - 1e-12 <= hi <= 1, key


def test_the_interval_ends_go_into_the_formulas():
    # TPR low = f(a_low, b_high), high = f(a_high, b_low); TNR the same; the real pass rate
    # rises with both a and b.
    r = weighted.corrected(900, 100, 25, 20, 25, 10)
    a_lo, a_hi = r["a_interval"]
    b_lo, b_hi = r["b_interval"]
    pi = 0.9

    def tpr(a, b):
        return pi * a / (pi * a + (1 - pi) * b)

    def tnr(a, b):
        return (1 - pi) * (1 - b) / ((1 - pi) * (1 - b) + pi * (1 - a))

    assert r["tpr_interval"] == pytest.approx([tpr(a_lo, b_hi), tpr(a_hi, b_lo)])
    assert r["tnr_interval"] == pytest.approx([tnr(a_lo, b_hi), tnr(a_hi, b_lo)])
    assert r["real_pass_rate_interval"] == pytest.approx(
        [pi * a_lo + (1 - pi) * b_lo, pi * a_hi + (1 - pi) * b_hi])


def test_the_wilson_interval_at_97_5_percent():
    # k = 20, n = 25, z = 2.2414: centre (0.8 + z^2/50) / (1 + z^2/25),
    # half z*sqrt(0.8*0.2/25 + z^2/2500) / (1 + z^2/25)
    z = 2.2414
    denom = 1 + z * z / 25
    centre = (0.8 + z * z / 50) / denom
    half = z * math.sqrt(0.16 / 25 + z * z / 2500) / denom
    assert weighted.wilson(20, 25) == pytest.approx((centre - half, centre + half))
    assert weighted.wilson(0, 0) == (None, None)


def test_the_counts_are_kept_with_the_numbers():
    r = weighted.corrected(900, 100, 25, 20, 25, 10)
    assert r["groups"] == {"pass": {"pool": 900, "labeled": 25, "correct": 20},
                           "fail": {"pool": 100, "labeled": 25, "correct": 10}}
    assert r["z"] == weighted.Z
