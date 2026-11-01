"""The numbers after asking a judge again (weighted.general, weighted.steadiness). Every
expected value is worked out by hand below.

The answers were picked half from the judge's saved passes and half from its saved fails, so
the groups stay the saved verdicts even when the fresh verdicts differ: each labeled answer
weighs N_group / n_group.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import weighted

# Pool: 20 saved passes, 16 saved fails. 4 labeled in each group.
#   pass group (weight 20/4 = 5): (label, fresh) = (pass, pass) (pass, pass) (pass, fail)
#                                                  (fail, fail)
#   fail group (weight 16/4 = 4): (fail, fail) (fail, fail) (fail, pass) (pass, pass)
ITEMS = ([("pass", "pass", "pass"), ("pass", "pass", "pass"), ("pass", "pass", "fail"),
          ("pass", "fail", "fail")]
         + [("fail", "fail", "fail"), ("fail", "fail", "fail"), ("fail", "fail", "pass"),
            ("fail", "pass", "pass")])  # (saved group, label, fresh verdict)


def test_the_general_form_by_hand():
    # Should pass: pass group 3 x 5 = 15, judge passed 2 x 5 = 10; fail group 1 x 4 = 4,
    # judge passed 4. TPR = (10 + 4) / (15 + 4) = 14/19.
    # Should fail: pass group 1 x 5 = 5, judge failed 5; fail group 3 x 4 = 12, judge failed
    # 2 x 4 = 8. TNR = (5 + 8) / (5 + 12) = 13/17.
    # Table (total 36): TP 14, FN 5, FP 4, TN 13. po = 27/36 = 0.75; the judge passes 18/36;
    # people pass 19/36; pe = 0.5 x 19/36 + 0.5 x 17/36 = 0.5; kappa = (0.75 - 0.5) / 0.5.
    r = weighted.general(ITEMS, 20, 16)
    assert r["tpr"] == pytest.approx(14 / 19)
    assert r["tnr"] == pytest.approx(13 / 17)
    assert r["kappa"] == pytest.approx(0.5)


@pytest.mark.parametrize("counts", [(20, 16, 4, 3, 4, 1), (900, 100, 25, 20, 25, 10),
                                    (50, 50, 10, 9, 12, 2)])
def test_with_fresh_verdicts_equal_to_the_groups_it_is_the_corrected_form(counts):
    n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f = counts
    items = ([("pass", "pass", "pass")] * c_p + [("pass", "fail", "pass")] * (n_p - c_p)
             + [("fail", "pass", "fail")] * c_f + [("fail", "fail", "fail")] * (n_f - c_f))
    general = weighted.general(items, n_pool_pass, n_pool_fail)
    corrected = weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f)
    for key in ("tpr", "tnr", "kappa"):
        assert general[key] == pytest.approx(corrected[key])


@pytest.mark.parametrize("fresh", ["pass", "fail"])
def test_fresh_verdicts_all_one_grade_have_no_kappa(fresh):
    r = weighted.general([(group, label, fresh) for group, label, _ in ITEMS], 20, 16)
    assert r["kappa"] is None and r["kappa_interval"] == [None, None]


def test_the_ranges_are_repeatable_with_their_seed():
    one = weighted.general(ITEMS, 20, 16)
    two = weighted.general(ITEMS, 20, 16)
    assert one["tpr_interval"] == two["tpr_interval"]
    assert one["tnr_interval"] == two["tnr_interval"]
    assert one["kappa_interval"] == two["kappa_interval"]
    other = weighted.general(ITEMS, 20, 16, seed=7)
    assert other["tpr_interval"] != one["tpr_interval"]
    assert (one["draws"], one["seed"], one["level"]) == (weighted.DRAWS, weighted.SEED,
                                                          weighted.LEVEL)
    assert one["interval_methods"] == {"tpr": "jeffreys", "tnr": "jeffreys"}


def _middle(values, level):
    values = sorted(values)
    k = len(values)
    return values[int(k * (1 - level) / 2)], values[int(k * (1 + level) / 2) - 1]


def test_the_ranges_are_the_middle_of_the_draws_per_group():
    # In each saved group, the share marked Correct (p) is drawn over the group's pool, as in
    # corrected(): the c Correct marks plus Binomial(N - n, Beta(c + 0.5, n - c + 0.5)) of the
    # unmarked ones. Of the answers marked Correct, the share the judge passed again (q), and
    # of those marked Wrong the share it failed again (r), are drawn one time in three from
    # Beta(k, m - k) (1 when all agree), else from Beta(k + 0.5, m - k + 0.5), which stays open
    # when all agree: asked again, a grade can turn round. Each group weighs its pool. Checked
    # with draws of our own (another seed, many more).
    #   pass group (pool 20): 3 of 4 Correct; 2 of 3 passed again; 1 of 1 failed again
    #   fail group (pool 16): 1 of 4 Correct; 1 of 1 passed again; 2 of 3 failed again
    r = weighted.general(ITEMS, 20, 16)
    rng, n = random.Random(1), 100_000
    tpr, tnr = [], []
    for _ in range(n):
        tp = fn = fp = tn = 0.0
        for pool, (labeled, correct), (passed, of_correct), (failed, of_wrong) in (
                (20, (4, 3), (2, 3), (1, 1)), (16, (4, 1), (1, 1), (2, 3))):
            share = rng.betavariate(correct + 0.5, labeled - correct + 0.5)
            p = (correct + sum(rng.random() < share for _ in range(pool - labeled))) / pool
            q, w = (_again(rng, passed, of_correct), _again(rng, failed, of_wrong))
            tp, fn = tp + pool * p * q, fn + pool * p * (1 - q)
            tn, fp = tn + pool * (1 - p) * w, fp + pool * (1 - p) * (1 - w)
        tpr.append(tp / (tp + fn))
        tnr.append(tn / (tn + fp))
    for key, values in (("tpr", tpr), ("tnr", tnr)):
        assert r[f"{key}_interval"] == pytest.approx(_middle(values, weighted.LEVEL), abs=0.01)


def _again(rng, k, m):
    """One draw of a share graded right again: Beta(k, m - k) one time in three, else
    Jeffreys."""
    if rng.random() < 1 / 3:
        return 1.0 if k == m else 0.0 if k == 0 else rng.betavariate(k, m - k)
    return rng.betavariate(k + 0.5, m - k + 0.5)


def test_intervals_are_inside_zero_to_one_and_hold_the_value():
    r = weighted.general(ITEMS, 20, 16)
    for key in ("tpr", "tnr"):
        lo, hi = r[f"{key}_interval"]
        assert 0 <= lo <= r[key] <= hi <= 1


def test_a_group_with_nobody_to_tell_is_unknown():
    r = weighted.general([("pass", "pass", "pass"), ("fail", "pass", "fail")], 10, 10)
    assert r["tnr"] is None and r["tnr_interval"] == [None, None]


# A range is one point only when every answer is marked --------------------------------------

def _all_agree(n_pass=15, n_fail=15):
    return ([("pass", "pass", "pass")] * n_pass) + ([("fail", "fail", "fail")] * n_fail)


def test_fifteen_of_fifteen_shows_a_real_range():
    out = weighted.general(_all_agree(), 100, 100)
    assert out["kappa"] == 1.0
    for key in ("tpr", "tnr"):
        lo, hi = out[f"{key}_interval"]
        assert out[key] == 1.0 and hi == 1.0
        assert lo < 0.95, key  # not 100% to 100%


def test_every_answer_marked_after_asking_again_is_exact():
    items = ([("pass", "pass", "pass")] * 12 + [("pass", "fail", "pass")] * 3
             + [("fail", "pass", "pass")] * 2 + [("fail", "fail", "fail")] * 8)
    out = weighted.general(items, 15, 10)
    for key in ("tpr", "tnr"):
        assert out[f"{key}_interval"] == pytest.approx([out[key], out[key]]), key


@pytest.mark.parametrize("counts", [(20, 16, 4, 3, 4, 1), (900, 100, 25, 20, 25, 10),
                                    (50, 50, 10, 9, 12, 2)])
def test_a_steady_judge_gets_wider_ranges_than_the_corrected_ones(counts):
    """Its grades asked again agree with the saved ones, but asked once more some could turn
    round: the ranges hold the same numbers and are wider."""
    n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f = counts
    items = ([("pass", "pass", "pass")] * c_p + [("pass", "fail", "pass")] * (n_p - c_p)
             + [("fail", "pass", "fail")] * c_f + [("fail", "fail", "fail")] * (n_f - c_f))
    general = weighted.general(items, n_pool_pass, n_pool_fail)
    corrected = weighted.corrected(n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f)
    for key in ("tpr", "tnr"):
        (lo, hi), (c_lo, c_hi) = general[f"{key}_interval"], corrected[f"{key}_interval"]
        assert lo <= general[key] <= hi and hi - lo > c_hi - c_lo, key


def test_zero_percent_shows_a_real_range():
    items = [("pass", "pass", "fail")] * 15 + [("fail", "fail", "pass")] * 15
    out = weighted.general(items, 100, 100)
    for key in ("tpr", "tnr"):
        lo, hi = out[f"{key}_interval"]
        assert out[key] == 0.0 and lo == 0.0 and hi > 0.0
        assert out["interval_methods"][key] == "jeffreys"


def test_no_range_is_ever_one_point():
    for items in (_all_agree(), _all_agree(3, 3), [("pass", "pass", "pass")] * 2):
        out = weighted.general(items, 100, 100)
        for key in ("tpr", "tnr"):
            lo, hi = out[f"{key}_interval"]
            assert lo is None or lo < hi, (key, lo, hi)
