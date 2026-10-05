"""Agreement, noise-floor and position-bias metrics. Plain Python, no dependencies.

A verdict of None means the judge output could not be parsed. It is kept as its own category
("invalid") and is always counted as wrong against the human label.

A verdict of "error" (ERROR) means a custom or imported judge raised, returned nothing or
returned something unparseable. Errors are not verdicts: they are left out of every agreement
metric and counted separately.
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

INVALID = "invalid"
ERROR = "error"
Z95 = 1.96


def _norm(v: str | None) -> str:
    return INVALID if v is None else v


def _mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def wilson_interval(p: float | None, n: int, z: float = Z95) -> tuple[float | None,
                                                                    float | None]:
    """Wilson score interval for a proportion p observed over n trials (95% by default)."""
    if p is None or n <= 0:
        return None, None
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def wilson(k: int, n: int, z: float = Z95) -> dict:
    """Proportion k/n with its Wilson score interval (95% by default)."""
    if n == 0:
        return {"k": k, "n": n, "p": None, "lo": None, "hi": None}
    lo, hi = wilson_interval(k / n, n, z)
    return {"k": k, "n": n, "p": k / n, "lo": lo, "hi": hi}


def _scored(a: list, b: list) -> tuple[list, list, int]:
    """Drop pairs where either side is ERROR; return (a, b, n_dropped)."""
    keep = [(x, y) for x, y in zip(a, b, strict=True) if x != ERROR and y != ERROR]
    return [x for x, _ in keep], [y for _, y in keep], len(a) - len(keep)


def cohen_kappa(a: list, b: list) -> float | None:
    """Cohen's kappa between two raters. None when chance agreement is 1 (undefined)."""
    if len(a) != len(b):
        raise ValueError("raters must label the same number of items")
    if not a:
        raise ValueError("no items")
    a = [_norm(x) for x in a]
    b = [_norm(x) for x in b]
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / (n * n)
    if pe == 1:
        return None
    return (po - pe) / (1 - pe)


def confusion(human: list, judge: list, positive: str, negative: str) -> dict:
    c = {"tp": 0, "fn": 0, "fp": 0, "tn": 0, "invalid": 0}
    for h, j in zip(human, judge, strict=True):
        if j is None:
            c["invalid"] += 1
        if h == positive:
            c["tp" if j == positive else "fn"] += 1
        elif h == negative:
            c["tn" if j == negative else "fp"] += 1
        else:
            raise ValueError(f"human label {h!r} is neither {positive!r} nor {negative!r}")
    return c


def agreement(human: list, judge: list, positive: str, negative: str) -> dict:
    """Judge vs human: kappa, TPR, TNR, accuracy and the confusion matrix.

    Judge errors (ERROR) are excluded: `n` counts scored items, `n_error` the excluded ones.
    """
    human, judge, n_error = _scored(human, judge)
    c = confusion(human, judge, positive, negative)
    pos = c["tp"] + c["fn"]
    neg = c["tn"] + c["fp"]
    return {
        "n": len(human),
        "kappa": cohen_kappa(human, judge) if human else None,
        "tpr": c["tp"] / pos if pos else None,
        "tnr": c["tn"] / neg if neg else None,
        "accuracy": (c["tp"] + c["tn"]) / len(human) if human else None,
        "confusion": c,
        "n_invalid": c["invalid"],
        "n_error": n_error,
    }


def noise_floor(verdicts_by_item: dict[str, list]) -> dict:
    """Test-retest stats over repeated runs.

    `verdicts_by_item` maps item id -> list of verdicts, one per run, in run order.
    Per-item flip rate is the share of runs that disagree with the item's majority verdict.
    `items_flipped_fraction` is the share of items whose verdict was not identical in every run.
    Judge errors are left out: an item's flip rate is over its runs that returned a verdict,
    and an item with no verdict in any run has majority ERROR.
    """
    ids = list(verdicts_by_item)
    n_runs = len(next(iter(verdicts_by_item.values()))) if ids else 0
    per_item = []
    majority: dict[str, str | None] = {}
    n_ties = 0
    for item_id in ids:
        given = verdicts_by_item[item_id]
        if len(given) != n_runs:
            raise ValueError(f"item {item_id} has {len(given)} verdicts, expected {n_runs}")
        vs = [_norm(v) for v in given if v != ERROR]
        if vs:
            counts = Counter(vs).most_common()
            top, top_n = counts[0]
            tie = len(counts) > 1 and counts[1][1] == top_n
            maj = None if tie or top == INVALID else top
            flip = 1 - top_n / len(vs)
        else:
            tie, maj, flip = False, ERROR, 0.0
        n_ties += tie
        majority[item_id] = maj
        per_item.append(
            {
                "id": item_id,
                "verdicts": list(given),
                "majority": maj,
                "flip_rate": flip,
            }
        )

    pairwise = []
    for i, j in combinations(range(n_runs), 2):
        a, b, _ = _scored([verdicts_by_item[k][i] for k in ids],
                          [verdicts_by_item[k][j] for k in ids])
        po = sum(_norm(x) == _norm(y) for x, y in zip(a, b)) / len(a) if a else None
        pairwise.append({"runs": [i + 1, j + 1], "kappa": cohen_kappa(a, b) if a else None,
                         "agreement": po})

    return {
        "n_runs": n_runs,
        "n_items": len(ids),
        "items_flipped_fraction": (
            sum(row["flip_rate"] > 0 for row in per_item) / len(ids) if ids else 0.0
        ),
        "mean_item_flip_rate": _mean([row["flip_rate"] for row in per_item]) or 0.0,
        "pairwise_kappa": pairwise,
        "mean_pairwise_kappa": _mean([p["kappa"] for p in pairwise]),
        "test_retest_agreement": _mean([p["agreement"] for p in pairwise]),
        "majority": majority,
        "n_ties": n_ties,
        "per_item": per_item,
    }


def position_bias(ab: list, ba: list) -> dict:
    """AB/BA consistency for pairwise judging.

    Both lists hold verdicts in the item's original labels: `ab` from the prompt showing
    output_a first, `ba` from the prompt showing output_b first. In AB the first slot is A;
    in BA the first slot is B.
    """
    if len(ab) != len(ba):
        raise ValueError("ab and ba must have the same length")
    ab, ba, _ = _scored(ab, ba)
    n = len(ab)
    if n == 0:
        return {"n": 0, "inconsistency_rate": None, "p_first": None, "first_position_bias": None}
    inconsistent = sum(_norm(x) != _norm(y) for x, y in zip(ab, ba))
    first = sum(v == "A" for v in ab) + sum(v == "B" for v in ba)
    p_first = first / (2 * n)
    return {
        "n": n,
        "inconsistency_rate": inconsistent / n,
        "p_first": p_first,
        "first_position_bias": abs(p_first - 0.5),
    }
