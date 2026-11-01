"""Small pools: the numbers are about the answers in the results file, so the answers not yet
marked are what is unknown (weighted.strata_samples).

- With every answer of a group marked, its share is known exactly: no range.
- With most of a small pool marked, the ranges are narrower than with an endless pool, and
  still hold the truth.
- In a large pool, the ranges are as before, to within the draws' noise.
- An LLM-as-a-judge that gave every answer one grade: its TPR and TNR on those answers are
  exact, with no range.
No test calls an AI API.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import batches, targets, weighted

KEYS = ("a", "b", "tpr", "tnr", "real_pass_rate")


def _width(interval):
    return interval[1] - interval[0]


@pytest.mark.parametrize("counts", [(40, 20, 40, 31, 20, 4), (12, 3, 12, 12, 3, 0),
                                    (171, 41, 171, 150, 41, 9)])
def test_every_answer_marked_gives_ranges_of_no_width(counts):
    out = weighted.corrected(*counts)
    for key in KEYS:
        lo, hi = out[f"{key}_interval"]
        assert lo == pytest.approx(out[key]) and hi == pytest.approx(out[key]), key
    assert targets.width_word(out["tnr_interval"]) == "exact"


def test_a_fully_marked_group_is_exact_while_the_other_still_has_a_range():
    out = weighted.corrected(900, 30, 25, 20, 30, 6)  # every answer the judge failed marked
    assert _width(out["b_interval"]) == pytest.approx(0.0)
    assert out["b"] == pytest.approx(0.2)
    assert _width(out["a_interval"]) > 0.1


def test_with_several_batches_every_answer_marked_gives_no_width():
    strata = [(1, "pass", 30, 30, 25), (1, "fail", 10, 10, 2),
              (2, "pass", 8, 8, 6), (2, "fail", 4, 4, 1)]
    out = weighted.stratified(strata)
    for key in KEYS:
        assert _width(out[f"{key}_interval"]) == pytest.approx(0.0), key


def test_most_of_a_small_pool_marked_narrows_the_range():
    small = weighted.corrected(60, 40, 50, 42, 32, 8)
    endless = weighted.corrected(60_000, 40_000, 50, 42, 32, 8)
    for key in ("tpr", "tnr"):
        assert _width(small[f"{key}_interval"]) < 0.7 * _width(endless[f"{key}_interval"]), key


@pytest.mark.parametrize("counts", [(9000, 1000, 25, 20, 25, 10), (60_000, 40_000, 30, 24, 30, 5)])
def test_a_large_pool_keeps_its_ranges(counts):
    """The unmarked answers' draws add almost nothing when they are most of the pool: the
    ranges are the plain Jeffreys ones, Beta(c + 0.5, n - c + 0.5) per group."""
    n_pool_pass, n_pool_fail, n_p, c_p, n_f, c_f = counts
    out = weighted.corrected(*counts)
    pi = n_pool_pass / (n_pool_pass + n_pool_fail)
    rng, n = random.Random(3), 100_000
    a = [rng.betavariate(c_p + 0.5, n_p - c_p + 0.5) for _ in range(n)]
    b = [rng.betavariate(c_f + 0.5, n_f - c_f + 0.5) for _ in range(n)]
    tnr = sorted((1 - pi) * (1 - y) / ((1 - pi) * (1 - y) + pi * (1 - x)) for x, y in zip(a, b))
    want = tnr[int(n * (1 - weighted.LEVEL) / 2)], tnr[int(n * (1 + weighted.LEVEL) / 2)]
    assert out["tnr_interval"] == pytest.approx(want, abs=0.012)


def test_a_small_pool_draws_its_unmarked_answers_from_the_beta_binomial():
    """Each group's share over its pool: the c Correct of the n marked, plus the unmarked
    answers' count Correct, Binomial(N - n, p) with p ~ Beta(c + 0.5, n - c + 0.5). Checked
    with draws of our own (another seed, many more of them)."""
    out = weighted.corrected(60, 40, 30, 24, 10, 3)
    rng, n = random.Random(1), 60_000

    def share(pool, marked, correct):
        p = rng.betavariate(correct + 0.5, marked - correct + 0.5)
        return (correct + sum(rng.random() < p for _ in range(pool - marked))) / pool

    a = [share(60, 30, 24) for _ in range(n)]
    b = [share(40, 10, 3) for _ in range(n)]
    tnr = sorted(0.4 * (1 - y) / (0.4 * (1 - y) + 0.6 * (1 - x)) for x, y in zip(a, b))
    want = tnr[int(n * (1 - weighted.LEVEL) / 2)], tnr[int(n * (1 + weighted.LEVEL) / 2)]
    assert out["tnr_interval"] == pytest.approx(want, abs=0.01)


def _finite_pool_coverage(n_pass, n_fail, k_pass, k_fail, marks, runs, seed):
    """How often the ranges hold the pool's true TPR and TNR: the pool holds exactly k_pass
    Correct answers among the judge's passes and k_fail among its fails, and `marks` of each
    group are marked, drawn without putting back."""
    rng = random.Random(seed)
    pi = n_pass / (n_pass + n_fail)
    a, b = k_pass / n_pass, k_fail / n_fail
    true = {"tpr": weighted._tpr(pi, a, b), "tnr": weighted._tnr(pi, a, b)}
    held = dict.fromkeys(true, 0)
    for _ in range(runs):
        c_p = sum(rng.sample([1] * k_pass + [0] * (n_pass - k_pass), marks))
        c_f = sum(rng.sample([1] * k_fail + [0] * (n_fail - k_fail), marks))
        out = weighted.corrected(n_pass, n_fail, marks, c_p, marks, c_f, draws=2000)
        for key, value in true.items():
            lo, hi = out[f"{key}_interval"]
            held[key] += lo is not None and lo - 1e-9 <= value <= hi + 1e-9
    return {k: v / runs for k, v in held.items()}


@pytest.mark.parametrize("pool", [(270, 30, 250, 12), (60, 40, 50, 10), (80, 20, 60, 8)])
def test_most_of_a_small_pool_marked_still_holds_the_truth(pool):
    n_pass, n_fail, k_pass, k_fail = pool
    marks = min(n_pass, n_fail) * 4 // 5  # 80% of the smaller group, as many of the other
    got = _finite_pool_coverage(n_pass, n_fail, k_pass, k_fail, marks, runs=300, seed=5)
    assert min(got.values()) >= 0.93, got


# One grade for every answer ----------------------------------------------------------------

@pytest.mark.parametrize("marks", [(23, 17), (12, 8), (19, 1)])
def test_a_judge_that_passes_every_answer_has_exact_rates(marks):
    said_pass, said_fail = marks
    out = weighted.corrected(400, 0, said_pass + said_fail, said_pass, 0, 0)
    assert out["tpr"] == 1.0 and out["tnr"] == 0.0
    assert out["tpr_interval"] == [1.0, 1.0] and out["tnr_interval"] == [0.0, 0.0]
    assert targets.level(out["tpr_interval"], out["tnr_interval"]) == "not_gate"
    lo, hi = out["real_pass_rate_interval"]
    assert lo < out["real_pass_rate"] < hi  # how many answers should pass is still unknown


@pytest.mark.parametrize("marks", [(17, 23), (8, 12), (1, 19)])
def test_a_judge_that_fails_every_answer_has_exact_rates(marks):
    said_pass, said_fail = marks
    out = weighted.corrected(0, 400, 0, 0, said_pass + said_fail, said_pass)
    assert out["tpr"] == 0.0 and out["tnr"] == 1.0
    assert out["tpr_interval"] == [0.0, 0.0] and out["tnr_interval"] == [1.0, 1.0]
    assert targets.level(out["tpr_interval"], out["tnr_interval"]) == "not_gate"


def test_one_grade_and_no_mark_of_the_other_kind_leaves_that_rate_unknown():
    out = weighted.corrected(400, 0, 20, 20, 0, 0)  # every mark Pass: no bad answer seen
    assert out["tpr_interval"] == [1.0, 1.0]
    assert out["tnr"] is None and out["tnr_interval"] == [None, None]


# A later batch counts once it has marks in proportion to its size ------------------------------

def _data(sizes: dict) -> dict:
    """start.json with batches of these sizes: {batch: (passed, failed)}."""
    queue = [{"id": f"{b}-{g}-{i}", "group": g, "batch": b}
             for b, (n_pass, n_fail) in sizes.items()
             for g, n in (("pass", n_pass), ("fail", n_fail)) for i in range(n)]
    return {"queue": queue, "pool": {"pass": sum(p for p, _ in sizes.values()),
                                     "fail": sum(f for _, f in sizes.values())}}


def _marked(data: dict, per: dict) -> dict:
    """Marks: per[(batch, group)] answers of each stratum, all Pass."""
    out = {}
    for (b, g), n in per.items():
        ids = [q["id"] for q in data["queue"] if (q["batch"], q["group"]) == (b, g)]
        out.update(dict.fromkeys(ids[:n], "pass"))
    return out


@pytest.mark.parametrize(("second", "need"), [
    ((200, 100), 5),     # as big as the first: 5 marks per group, as before
    ((2000, 1000), 15),  # ten times bigger: 50 in proportion, at most 15
    ((600, 300), 15),    # three times bigger: 15
    ((400, 200), 10),    # twice as big: 10
    ((40, 20), 1),       # a fifth of the first: 1 mark per group
])
def test_a_later_batch_counts_once_its_marks_match_its_size(second, need):
    data = _data({1: (200, 100), 2: second})
    for n in range(need + 1):
        labels = _marked(data, {(1, "pass"): 40, (1, "fail"): 40, (2, "pass"): n, (2, "fail"): n})
        assert (2 in batches.counting(data, labels)) == (n >= need), n


def test_a_later_batch_with_every_answer_marked_counts():
    data = _data({1: (200, 100), 2: (3000, 4)})
    labels = _marked(data, {(1, "pass"): 30, (1, "fail"): 30, (2, "pass"): 15, (2, "fail"): 4})
    assert batches.counting(data, labels) == [1, 2]
    labels = _marked(data, {(1, "pass"): 30, (1, "fail"): 30, (2, "pass"): 14, (2, "fail"): 4})
    assert batches.counting(data, labels) == [1]


def test_a_later_group_the_first_batch_lacks_needs_the_most():
    data = _data({1: (200, 0), 2: (100, 50)})
    labels = _marked(data, {(1, "pass"): 30, (2, "pass"): 3, (2, "fail"): 14})
    assert batches.counting(data, labels) == [1]
    labels = _marked(data, {(1, "pass"): 30, (2, "pass"): 3, (2, "fail"): 15})
    assert batches.counting(data, labels) == [1, 2]
