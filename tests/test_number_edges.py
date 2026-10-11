"""The numbers' edge cases: a rate of exactly 0.90 in floating point, a judge that passes (or
fails) every answer, a range narrower than one point, and a group of the judge with nothing
counted when it is asked again."""

from __future__ import annotations

from judgekeeper import start_label, targets, weighted
from judgekeeper.report import _rate_flags


def test_a_rate_of_exactly_090_is_not_below_090():
    tpr = 0.5 * 1 / (0.5 * 1 + 0.5 * 2 / 18)  # 9/10, worked out as 0.8999999999999999
    assert tpr < 0.9 and round(tpr, 9) == 0.9
    r = {"check": "rough", "tpr": tpr, "tnr": 1.0, "kappa": 0.89}
    assert start_label._level(r) == "gate"  # green, not amber
    assert _rate_flags("TPR", tpr) == []
    assert start_label._level({**r, "tpr": 0.8999}) == "check"


def test_a_judge_that_passes_every_answer_has_exact_numbers():
    assert start_label.range_words([1.0, 1.0]) == (
        "100%, exactly: marking more answers won't change it.")
    assert start_label.range_words([0.0, 0.0]).startswith("0%, exactly")
    check = targets.check(25, 25, [1.0, 1.0], [0.0, 0.0])
    assert check == {"check": "rough", "wide": {}}  # never "reliable" from no width at all
    r = {"check": "rough", "wide": {}, "tpr_interval": [1.0, 1.0], "tnr_interval": [0.0, 0.0]}
    assert start_label.status_line(r) == "You can see your result now."
    assert start_label.still_needed(r) is None


def test_a_range_never_shows_as_one_point():
    assert start_label.range_words([0.997, 1.0]) == (
        "Probably between 99.7% and 100.0%. Marking more answers narrows this.")
    assert start_label.range_words([0.66, 0.93]) == (
        "Probably between 66% and 93%. Marking more answers narrows this.")


def test_a_group_with_nothing_counted_gives_unknown_numbers():
    # only the judge's pass group came back: 17 marked Pass, 3 Fail
    items = [("pass", "pass", "pass")] * 17 + [("pass", "fail", "pass")] * 3
    out = weighted.general(items, 100, 100)
    assert out["tpr"] is None and out["tnr"] is None and out["kappa"] is None
    assert out["tpr_interval"] == [None, None]
    from judgekeeper.again.fresh import _share
    assert _share(out["tpr"]) == "an unknown share"
