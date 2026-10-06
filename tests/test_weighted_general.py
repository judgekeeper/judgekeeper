"""The numbers after asking a judge again (weighted.general, weighted.steadiness). Every
expected value is worked out by hand below.

The answers were picked half from the judge's saved passes and half from its saved fails, so
the groups stay the saved verdicts even when the fresh verdicts differ: each labeled answer
weighs N_group / n_group.
"""

from __future__ import annotations

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


def test_the_bootstrap_is_repeatable_with_its_seed():
    one = weighted.general(ITEMS, 20, 16)
    two = weighted.general(ITEMS, 20, 16)
    assert one["tpr_interval"] == two["tpr_interval"]
    assert one["kappa_interval"] == two["kappa_interval"]
    other = weighted.general(ITEMS, 20, 16, seed=7)
    assert other["tpr_interval"] != one["tpr_interval"]
    assert one["resamples"] == 2000


def test_intervals_are_inside_zero_to_one_and_hold_the_value():
    r = weighted.general(ITEMS, 20, 16)
    for key in ("tpr", "tnr"):
        lo, hi = r[f"{key}_interval"]
        assert 0 <= lo <= r[key] <= hi <= 1


def test_a_group_with_nobody_to_tell_is_unknown():
    r = weighted.general([("pass", "pass", "pass"), ("fail", "pass", "fail")], 10, 10)
    assert r["tnr"] is None and r["tnr_interval"] == [None, None]


def test_steadiness_by_hand():
    # pi = 20/36. Pass group: 1 of 4 changed (f_p = 0.25); fail group: 2 of 4 (f_f = 0.5).
    # Rate = 20/36 x 0.25 + 16/36 x 0.5 = 5/36 + 8/36 = 13/36.
    r = weighted.steadiness({"pass": (4, 1), "fail": (4, 2)}, 20, 16)
    assert r["rate"] == pytest.approx(13 / 36)
    lo, hi = r["interval"]
    p_lo, p_hi = weighted.wilson(1, 4)
    f_lo, f_hi = weighted.wilson(2, 4)
    assert lo == pytest.approx(20 / 36 * p_lo + 16 / 36 * f_lo)
    assert hi == pytest.approx(20 / 36 * p_hi + 16 / 36 * f_hi)
    assert r["changed"] == 3 and r["of"] == 8


def test_steadiness_when_nothing_changed():
    r = weighted.steadiness({"pass": (4, 0), "fail": (4, 0)}, 20, 16)
    assert r["rate"] == 0 and r["interval"][0] == 0 and 0 < r["interval"][1] < 1


# A range never collapses to one point from a finite sample ----------------------------------

def _all_agree(n_pass=15, n_fail=15):
    return ([("pass", "pass", "pass")] * n_pass) + ([("fail", "fail", "fail")] * n_fail)


def test_fifteen_of_fifteen_shows_a_real_range():
    out = weighted.general(_all_agree(), 15, 15)
    lo, hi = weighted.wilson(15, 15)
    for key in ("tpr", "tnr"):
        assert out[key] == 1.0
        assert out[f"{key}_interval"] == pytest.approx([lo, hi])
        assert out[f"{key}_interval"][0] < 1.0  # about 75%, not 100% to 100%
        assert out["interval_methods"][key] == "wilson corners"


def test_zero_percent_shows_a_real_range():
    items = [("pass", "pass", "fail")] * 15 + [("fail", "fail", "pass")] * 15
    out = weighted.general(items, 15, 15)
    lo, hi = weighted.wilson(0, 15)
    for key in ("tpr", "tnr"):
        assert out[key] == 0.0
        assert out[f"{key}_interval"] == pytest.approx([lo, hi]) and hi > 0.0


def test_the_corners_weigh_each_group_by_its_pool():
    # pass group: 20 in the pool, 10 labeled, all agree; fail group: 80 in the pool, 10
    # labeled, all agree. Every Correct is in the pass group: TPR's range is the pass group's.
    out = weighted.general(_all_agree(10, 10), 20, 80)
    assert out["tpr_interval"] == pytest.approx(list(weighted.wilson(10, 10)))
    corners = weighted.wilson_corners(_all_agree(10, 10), 20, 80)
    assert corners["tnr"] == pytest.approx(list(weighted.wilson(10, 10)))


def test_corners_mix_groups_by_weight():
    # Should-pass answers in both groups: 4 in the pass group (all passed), 2 in the fail
    # group (both failed by the judge); weights 100/4 and 50/2.
    items = [("pass", "pass", "pass")] * 4 + [("fail", "pass", "fail")] * 2
    corners = weighted.wilson_corners(items, 100, 50)
    w_pass, w_fail = 100 / 4 * 4, 50 / 2 * 2
    (a_lo, a_hi), (b_lo, b_hi) = weighted.wilson(4, 4), weighted.wilson(0, 2)
    assert corners["tpr"] == pytest.approx([(w_pass * a_lo + w_fail * b_lo) / (w_pass + w_fail),
                                            (w_pass * a_hi + w_fail * b_hi) / (w_pass + w_fail)])


def test_a_bootstrap_range_with_width_is_kept():
    items = ([("pass", "pass", "pass")] * 12 + [("pass", "pass", "fail")] * 3
             + [("fail", "fail", "fail")] * 10 + [("fail", "fail", "pass")] * 5)
    out = weighted.general(items, 15, 15)
    assert out["interval_methods"] == {"tpr": "bootstrap", "tnr": "bootstrap",
                                       "kappa": "bootstrap"}
    assert out["tpr_interval"][0] < out["tpr_interval"][1]


def test_a_kappa_range_of_one_point_is_dropped():
    out = weighted.general(_all_agree(), 15, 15)
    assert out["kappa"] == 1.0 and out["kappa_interval"] == [None, None]
    assert out["interval_methods"]["kappa"] == "none"


def test_no_range_is_ever_one_point():
    for items in (_all_agree(), _all_agree(3, 3), [("pass", "pass", "pass")] * 2):
        out = weighted.general(items, 10, 10)
        for key in ("tpr", "tnr", "kappa"):
            lo, hi = out[f"{key}_interval"]
            assert lo is None or lo < hi, (key, lo, hi)
