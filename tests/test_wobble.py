"""Ranges after asking the LLM-as-a-judge again, when it changes its own grade now and then.

A judge asked twice about the same answer does not always give the same grade (its wobble).
judgekeeper asks once, so it can't see the wobble: after `check`, the share of marks the new
LLM-as-a-judge got right again is drawn per group, one draw in three from Beta(k, m - k) and
the rest from Jeffreys, Beta(k + 0.5, m - k + 0.5), which stays open even when every mark
agreed. Then the ranges hold the true rates of a judge that turns some grades round, without
asking twice, and of one that doesn't. A group that holds no answer of a kind keeps the saved
grade.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import weighted


def _coverage(pi, n, flip, runs, systematic=0.0, seed=11):
    """How often the TPR and TNR ranges hold the asked judge's true rates. The pool: 10,000
    answers, a share `pi` passed by the LLM-as-a-judge; 90% of its passes should pass, 15% of
    its fails should. Asked again, each grade turns round with chance `flip`; `systematic`: a
    share of the answers it failed that should fail now passes."""
    a, b = 0.9, 0.15
    should_pass = pi * a + (1 - pi) * b
    tpr_old = pi * a / should_pass
    tnr_old = (1 - pi) * (1 - b) / (1 - should_pass)
    tnr_new = tnr_old * (1 - systematic)
    true = {"tpr": tpr_old * (1 - flip) + (1 - tpr_old) * flip,
            "tnr": tnr_new * (1 - flip) + (1 - tnr_new) * flip}
    rng = random.Random(seed)
    n_pass = round(pi * 10_000)
    hits = {"tpr": 0, "tnr": 0}
    for _ in range(runs):
        items = []
        for group, share in (("pass", a), ("fail", b)):
            for _ in range(n):
                should = rng.random() < share
                base = "pass" if group == "fail" and not should and rng.random() < systematic \
                    else group
                other = "fail" if base == "pass" else "pass"
                first = other if rng.random() < flip else base
                items.append((group, "pass" if should else "fail", first))
        r = weighted.general(items, n_pass, 10_000 - n_pass, draws=1000)
        for k in hits:
            lo, hi = r[f"{k}_interval"]
            hits[k] += lo is not None and lo - 1e-12 <= true[k] <= hi + 1e-12
    return {k: v / runs for k, v in hits.items()}


@pytest.mark.parametrize("flip", [0.05, 0.10])
def test_a_wobbling_judge_passing_most_answers_is_covered(flip):
    """The rows the statistics review found at 52 and 74 in 100, when every agreeing group of
    marks counted as exact: judge passes 90%, 15 marks per group."""
    got = _coverage(0.9, 15, flip, 300)
    assert got["tpr"] >= 0.93 and got["tnr"] >= 0.93, got


@pytest.mark.parametrize("pi,n,flip,systematic", [
    (0.9, 25, 0.10, 0.0), (0.5, 15, 0.10, 0.0), (0.9, 15, 0.0, 0.0),
    (0.9, 25, 0.05, 0.3),  # the judge also changed: it passes 30% of the fails it failed
])
def test_the_ranges_hold_the_true_rates(pi, n, flip, systematic):
    """300 runs move a share by about 1.3 points; the coverage grid checks 93 in 100 on 1,000."""
    got = _coverage(pi, n, flip, 300, systematic=systematic)
    assert got["tpr"] >= 0.91 and got["tnr"] >= 0.91, got


def test_every_mark_agreeing_still_gives_a_range():
    items = [("pass", "pass", "pass")] * 15 + [("fail", "fail", "fail")] * 15
    out = weighted.general(items, 900, 100)
    for k in ("tpr", "tnr"):
        lo, hi = out[f"{k}_interval"]
        assert out[k] == 1.0 and hi == 1.0 and lo < 0.97, k
    assert out["interval_methods"] == {"tpr": "jeffreys", "tnr": "jeffreys"}


def test_no_wobble_to_pass_in():
    import inspect

    assert "wobble" not in inspect.signature(weighted.general).parameters
    assert "wobble" not in inspect.signature(weighted.general_strata).parameters
