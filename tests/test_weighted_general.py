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
