"""Ranges after asking the LLM-as-a-judge again, when it changes its own grade now and then.

A judge asked twice about the same answer does not always give the same grade. The share of
answers whose two grades differ (its wobble) is measured when a paid re-check asks twice. Each
re-asked grade can then have turned round by itself, so "every answer agreed" is no longer
exact: the range for the new LLM-as-a-judge's numbers is widened for it, most where a group of the marks
holds few answers. A judge that gave the same grade both times keeps its ranges as they were.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import weighted


def _coverage(pi, n, flip, runs, use_wobble, systematic=0.0, seed=11):
    """How often the TPR and TNR ranges hold the asked judge's true rates. The pool: 1,000
    answers, a share `pi` passed by the LLM-as-a-judge; 90% of its passes should pass, 15% of its fails
    should. Asked again, each grade turns round with chance `flip`, asked twice to measure it;
    `systematic`: a share of the answers it failed that should fail now passes."""
    a, b = 0.9, 0.15
    should_pass = pi * a + (1 - pi) * b
    tpr_old = pi * a / should_pass
    tnr_old = (1 - pi) * (1 - b) / (1 - should_pass)
    tnr_new = tnr_old * (1 - systematic)
    true = {"tpr": tpr_old * (1 - flip) + (1 - tpr_old) * flip,
            "tnr": tnr_new * (1 - flip) + (1 - tnr_new) * flip}
    rng = random.Random(seed)
    n_pass = round(pi * 1000)
    hits = {"tpr": 0, "tnr": 0}
    for _ in range(runs):
        items, differ = [], 0
        for group, share in (("pass", a), ("fail", b)):
            for _ in range(n):
                should = rng.random() < share
                base = "pass" if group == "fail" and not should and rng.random() < systematic \
                    else group
                other = "fail" if base == "pass" else "pass"
                first = other if rng.random() < flip else base
                second = other if rng.random() < flip else base
                differ += first != second
                items.append((group, "pass" if should else "fail", first))
        wobble = differ / len(items) if use_wobble else None
        r = weighted.general(items, n_pass, 1000 - n_pass, draws=1000, wobble=wobble)
        for k in hits:
            lo, hi = r[f"{k}_interval"]
            hits[k] += lo is not None and lo - 1e-12 <= true[k] <= hi + 1e-12
    return {k: v / runs for k, v in hits.items()}


def test_a_judge_that_passes_most_answers_and_wobbles_was_covered_too_rarely():
    """The case the coverage grid found: ranges that treat every agreeing answer as exact."""
    assert _coverage(0.9, 15, 0.05, 300, use_wobble=False)["tpr"] < 0.8


@pytest.mark.parametrize("pi,n,flip,systematic", [
    (0.9, 15, 0.05, 0.0), (0.9, 25, 0.10, 0.0), (0.5, 15, 0.10, 0.0),
    (0.9, 25, 0.05, 0.3),  # the judge also changed: it passes 30% of the fails it failed
])
def test_with_its_wobble_the_ranges_hold_the_true_rates(pi, n, flip, systematic):
    """300 runs move a share by about 1.3 points; the coverage grid checks 93 in 100 on 1,000."""
    got = _coverage(pi, n, flip, 300, use_wobble=True, systematic=systematic)
    assert got["tpr"] >= 0.91 and got["tnr"] >= 0.91, got


def test_a_judge_with_no_wobble_keeps_its_ranges():
    items = ([("pass", "pass", "pass")] * 12 + [("pass", "fail", "pass")] * 3
             + [("fail", "pass", "fail")] * 2 + [("fail", "fail", "fail")] * 13)
    before = weighted.general(items, 900, 100)
    for wobble in (None, 0.0):
        after = weighted.general(items, 900, 100, wobble=wobble)
        assert after["tpr_interval"] == before["tpr_interval"]
        assert after["tnr_interval"] == before["tnr_interval"]


def test_a_wobbling_judge_gets_wider_ranges_and_the_same_numbers():
    items = ([("pass", "pass", "pass")] * 12 + [("pass", "fail", "pass")] * 3
             + [("fail", "pass", "fail")] * 2 + [("fail", "fail", "fail")] * 13)
    steady = weighted.general(items, 900, 100)
    wobbly = weighted.general(items, 900, 100, wobble=0.1)
    assert (wobbly["tpr"], wobbly["tnr"]) == (steady["tpr"], steady["tnr"])
    for k in ("tpr", "tnr"):
        width = wobbly[f"{k}_interval"][1] - wobbly[f"{k}_interval"][0]
        assert width > steady[f"{k}_interval"][1] - steady[f"{k}_interval"][0]
    assert wobbly["interval_methods"]["tpr"] == "jeffreys, with the judge's wobble"


def test_check_widens_the_numbers_after_a_change_for_the_wobble():
    from judgekeeper import check

    n = check.AFTER_NUMBERS
    marks = {f"p{i}": "pass" for i in range(n)} | {f"f{i}": "fail" for i in range(n)}
    tested = {i: m if i not in ("p0", "f0") else ("fail" if m == "pass" else "pass")
              for i, m in marks.items()}
    picked = {i: m for i, m in marks.items()}
    pool = {"pass": 800, "fail": 200}
    steady = check._after_lines(marks, tested, picked, pool)
    wobbly = check._after_lines(marks, tested, picked, pool, wobble=0.1)
    assert steady[0] == wobbly[0] and steady[1] != wobbly[1]
    assert "about 90% (between" in wobbly[1] and len(wobbly[1]) <= 80
