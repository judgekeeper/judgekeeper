"""The numbers `judgekeeper start` reports, corrected for picking half from the judge's passes
and half from its fails (weighted.py). Every expected value is worked out by hand below.

Words: the pool holds N_pass answers the judge passed and N_fail it failed, pi = N_pass / N.
In the pass group n_p answers are labeled, c_p of them Correct: a = c_p / n_p. In the fail
group n_f are labeled, c_f Correct: b = c_f / n_f.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from judgekeeper import weighted
from judgekeeper.metrics import cohen_kappa

COVERAGE = Path(__file__).resolve().parent.parent / "docs" / "examples" / "coverage"


def test_the_level_is_the_one_the_coverage_grid_chose():
    chosen = json.loads((COVERAGE / "coverage.json").read_text(encoding="utf-8"))
    assert weighted.LEVEL == chosen["corrected"]["chosen_level"]
    assert weighted.LEVEL in (0.95, 0.96, 0.97)
    assert weighted.DRAWS == chosen["draws"] and weighted.SEED == chosen["seed"]


def test_the_steadiness_and_corner_intervals_keep_z_for_two_intervals_at_97_5_percent():
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


def _middle(values, level):
    values = sorted(values)
    k = len(values)
    return values[int(k * (1 - level) / 2)], values[int(k * (1 + level) / 2) - 1]


def test_the_ranges_are_the_middle_of_jeffreys_draws():
    # Each group's share of Correct answers is Beta(correct + 0.5, labeled - correct + 0.5);
    # TPR, TNR and the real pass rate come from pairs of draws, and the range is their middle
    # LEVEL. Checked here with draws of our own (another seed, many more of them).
    r = weighted.corrected(900, 100, 25, 20, 25, 10)
    rng, pi, n = random.Random(1), 0.9, 200_000
    a = [rng.betavariate(20.5, 5.5) for _ in range(n)]
    b = [rng.betavariate(10.5, 15.5) for _ in range(n)]
    expected = {
        "a": a, "b": b,
        "tpr": [pi * x / (pi * x + (1 - pi) * y) for x, y in zip(a, b)],
        "tnr": [(1 - pi) * (1 - y) / ((1 - pi) * (1 - y) + pi * (1 - x)) for x, y in zip(a, b)],
        "real_pass_rate": [pi * x + (1 - pi) * y for x, y in zip(a, b)],
    }
    for key, values in expected.items():
        assert r[f"{key}_interval"] == pytest.approx(_middle(values, weighted.LEVEL), abs=0.01)


def test_the_same_labels_give_the_same_ranges_to_two_decimals_whatever_the_seed():
    one = weighted.corrected(171, 41, 16, 15, 15, 5)
    assert weighted.corrected(171, 41, 16, 15, 15, 5) == one  # a fixed seed
    for seed in (1, 2, 3):
        other = weighted.corrected(171, 41, 16, 15, 15, 5, seed=seed)
        for key in ("tpr_interval", "tnr_interval", "real_pass_rate_interval"):
            assert [round(x, 2) for x in other[key]] == pytest.approx(
                [round(x, 2) for x in one[key]], abs=0.011), key


def _corners(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f):
    """The TNR range the simple way: Wilson at 97.5% per group, joined at the corners."""
    pi = n_pool_pass / (n_pool_pass + n_pool_fail)
    (a_lo, a_hi), (b_lo, b_hi) = weighted.wilson(c_p, n_p), weighted.wilson(c_f, n_f)

    def tnr(a, b):
        return (1 - pi) * (1 - b) / ((1 - pi) * (1 - b) + pi * (1 - a))

    return tnr(a_lo, b_hi), tnr(a_hi, b_lo)


@pytest.mark.parametrize("counts", [(900, 100, 25, 20, 25, 10), (500, 500, 25, 22, 25, 4),
                                    (700, 300, 15, 12, 15, 3)])
def test_the_ranges_are_narrower_than_the_corners_were(counts):
    lo, hi = weighted.corrected(*counts)["tnr_interval"]
    old_lo, old_hi = _corners(*counts)
    assert hi - lo < 0.9 * (old_hi - old_lo)


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
    assert r["method"] == "jeffreys"
    assert (r["level"], r["draws"], r["seed"]) == (weighted.LEVEL, weighted.DRAWS, weighted.SEED)
