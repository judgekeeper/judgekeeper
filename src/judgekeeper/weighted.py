"""TPR, TNR and kappa corrected for how judgekeeper picks answers. Plain Python.

judgekeeper shows the person half answers the LLM-as-a-judge passed and half it failed, far
more fails than the pool usually holds, so plain rates over the marks would be wrong. The rates
are worked out per group and weighted by group size (the Begg-Greenes correction); kappa is
Cohen's kappa on that weighted table. With batches the groups are strata, (batch, grade); after
asking again they stay the saved grades, since that is how the answers were picked.

Ranges are Jeffreys draws per group (DRAWS, a fixed SEED), cut at the middle LEVEL. LEVEL was
picked by scripts/coverage_check.py, not assumed. A range is widened to hold the number itself,
and an unknown rate is None, never an error. The formulas, in plain words, are in
docs/reference.md under "How the numbers are worked out".
"""

from __future__ import annotations

import random

from judgekeeper.metrics import wilson_interval

Z = 2.2414  # two-sided 97.5%: steadiness, and the corners of a range of zero width
# The middle share of the Jeffreys draws a range spans. Chosen by scripts/coverage_check.py,
# never assumed: the first of 0.95, 0.96 and 0.97 whose ranges hold the true TPR, TNR and real
# pass rate at least 93 times in 100 in every cell of the grid and 95 in 100 on average.
LEVEL = 0.96  # 0.95 held the true value only 91.6 times in 100 in its lowest cell
DRAWS = 20_000  # enough that another seed moves no range by more than about 0.01
SEED = 20261008
# How many marks a share of turned grades weighs the judge's wobble as, less the marks counted.
# Chosen by scripts/coverage_check.py: the first of 0, 5, 10 and 20 whose ranges after asking
# again hold the true TPR and TNR at least 93 times in 100 in every cell and 95 on average.
WOBBLE_MARKS = 5  # 0 held the true TNR only 90.3 times in 100 in its lowest cell


def wilson(k: int, n: int, z: float = Z) -> tuple[float | None, float | None]:
    """The Wilson interval for k of n at 97.5%; (None, None) when n is 0."""
    if n <= 0:
        return None, None
    return wilson_interval(k / n, n, z)


def _div(top: float, bottom: float) -> float | None:
    return None if bottom <= 0 else top / bottom


def _tpr(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return _div(pi * a, pi * a + (1 - pi) * b)


def _tnr(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return _div((1 - pi) * (1 - b), (1 - pi) * (1 - b) + pi * (1 - a))


def _pass_rate(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return pi * a + (1 - pi) * b


def _kappa(pi: float, a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    agree = pi * a + (1 - pi) * (1 - b)
    human_pass = pi * a + (1 - pi) * b
    chance = pi * human_pass + (1 - pi) * (1 - human_pass)
    return _div(agree - chance, 1 - chance)


def corrected(n_pool_pass: int, n_pool_fail: int, n_p: int, c_p: int, n_f: int,
              c_f: int, level: float = LEVEL, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Every corrected number, with its range, and the counts it came from: `stratified` with
    one batch.

    A group that the pool does not hold (N = 0) needs no labels: its rate does not count.
    """
    return stratified([(1, "pass", n_pool_pass, n_p, c_p), (1, "fail", n_pool_fail, n_f, c_f)],
                      level, draws, seed)


def _pooled(strata: list[tuple], grade: str, rates: dict) -> float | None:
    """The share marked Correct among the answers the judge gave `grade`: each stratum's
    share (`rates`, by its place in `strata`) weighed by its pool. One stratum: its own share,
    exactly (1.0 times it)."""
    total = sum(s[2] for s in strata if s[1] == grade)
    out = 0.0
    for k, (_, g, pool, _, _) in enumerate(strata):
        if g != grade or pool <= 0:
            continue
        if rates[k] is None:
            return None
        out += pool / total * rates[k]
    return out


def stratified(strata: list[tuple[int, str, int, int, int]], level: float = LEVEL,
               draws: int = DRAWS, seed: int = SEED) -> dict:
    """Every corrected number, with its range, from strata (batch, the judge's grade, pool
    size, labeled, labeled Correct): a and b are the pools' shares Correct, each stratum's
    weighed by its pool, so each labeled answer weighs N_stratum / n_stratum. With one batch
    this is the module's form above, to the last digit.

    A grade that the pool does not hold (N = 0) needs no labels: its rate does not count. A
    stratum of the pool with no labels leaves its grade's rate unknown."""
    n_pool_pass = sum(s[2] for s in strata if s[1] == "pass")
    n_pool_fail = sum(s[2] for s in strata if s[1] == "fail")
    total = n_pool_pass + n_pool_fail
    pi = _div(n_pool_pass, total)
    shares = [_div(c, n) for _, _, _, n, c in strata]
    a, b = _pooled(strata, "pass", shares), _pooled(strata, "fail", shares)
    if not n_pool_pass:  # nothing to weigh: the share of the marks, as it is shown
        a = _div(*_sums(strata, "pass"))
    if not n_pool_fail:
        b = _div(*_sums(strata, "fail"))
    samples = strata_samples(strata, draws, seed)
    point = {"a": a, "b": b, "tpr": None, "tnr": None, "kappa": None, "real_pass_rate": None}
    if pi is not None:
        fa = 0.0 if n_pool_pass == 0 else a  # an empty group of the pool: any value gives
        fb = 0.0 if n_pool_fail == 0 else b  # the same numbers
        point.update(tpr=_tpr(pi, fa, fb), tnr=_tnr(pi, fa, fb), kappa=_kappa(pi, fa, fb),
                     real_pass_rate=_pass_rate(pi, fa, fb))
    out = {"pi": pi, "judge_pass_rate": pi, **point}
    for key in ("a", "b", "tpr", "tnr", "real_pass_rate", "kappa"):
        out[f"{key}_interval"] = middle(samples.get(key), level, point[key])
    groups = {}
    for g in ("pass", "fail"):
        labeled, correct = (sum(s[i] for s in strata if s[1] == g) for i in (3, 4))
        groups[g] = {"pool": sum(s[2] for s in strata if s[1] == g), "labeled": labeled,
                     "correct": correct}
    out.update(groups=groups, method="jeffreys", level=level, draws=draws, seed=seed)
    return out


def _sums(strata: list[tuple], grade: str) -> tuple[int, int]:
    """(labeled Correct, labeled) over the strata of `grade`."""
    return (sum(s[4] for s in strata if s[1] == grade),
            sum(s[3] for s in strata if s[1] == grade))


def jeffreys_samples(n_pool_pass: int, n_pool_fail: int, n_p: int, c_p: int, n_f: int,
                     c_f: int, draws: int = DRAWS, seed: int = SEED) -> dict[str, list[float]]:
    """Sorted draws of a, b, TPR, TNR, the real pass rate and kappa; a key is missing when
    unknown: `strata_samples` with one batch."""
    return strata_samples([(1, "pass", n_pool_pass, n_p, c_p), (1, "fail", n_pool_fail, n_f, c_f)],
                          draws, seed)


def strata_samples(strata: list[tuple[int, str, int, int, int]], draws: int = DRAWS,
                   seed: int = SEED) -> dict[str, list[float]]:
    """Sorted draws of a, b, TPR, TNR, the real pass rate and kappa from strata (see
    `stratified`); a key is missing when unknown.

    Each stratum's share Correct is drawn from Beta(c + 0.5, n - c + 0.5), stratum by stratum
    in the order given, with one random generator seeded with `seed`; a and b are those draws
    weighed by the strata's pools. A grade the pool does not hold has the rate 0 in every
    draw."""
    n_pool_pass = sum(s[2] for s in strata if s[1] == "pass")
    n_pool_fail = sum(s[2] for s in strata if s[1] == "fail")
    total = n_pool_pass + n_pool_fail
    if total <= 0:
        return {}
    pi = n_pool_pass / total
    rng = random.Random(seed)
    drawn = {}
    for k, (_, _, pool, n, c) in enumerate(strata):
        if pool > 0 and n > 0:
            drawn[k] = [rng.betavariate(c + 0.5, n - c + 0.5) for _ in range(draws)]
    rates = {}
    for key, grade, pool in (("a", "pass", n_pool_pass), ("b", "fail", n_pool_fail)):
        if pool == 0:
            rates[key] = [0.0] * draws
            continue
        parts = [k for k, s in enumerate(strata) if s[1] == grade and s[2] > 0]
        if all(k in drawn for k in parts):
            weights = [strata[k][2] / pool for k in parts]
            rates[key] = [sum((w * drawn[k][i] for w, k in zip(weights, parts)), 0.0)
                          for i in range(draws)]
    out = {k: sorted(v) for k, v in rates.items() if (k == "a" and n_pool_pass) or
           (k == "b" and n_pool_fail)}
    if "a" in rates and "b" in rates:
        pairs = list(zip(rates["a"], rates["b"]))
        for key, f in (("tpr", _tpr), ("tnr", _tnr), ("real_pass_rate", _pass_rate),
                       ("kappa", _kappa)):
            values = [v for x, y in pairs if (v := f(pi, x, y)) is not None]
            if len(values) == len(pairs):
                out[key] = sorted(values)
    if (n_pool_pass == 0) != (n_pool_fail == 0):
        out.update(_one_grade(strata, "pass" if n_pool_pass else "fail", rng, draws))
    return out


def _one_grade(strata: list[tuple], grade: str, rng: random.Random,
               draws: int) -> dict[str, list[float]]:
    """TPR and TNR drawn from the marks themselves when the judge gave every answer of the
    pool one grade. The weighted draws are then one point (TPR exactly 1 and TNR 0 for a
    judge that passes all), which a few marks can't show: so each rate is drawn as the plain
    Jeffreys share of the marks the judge got right, Beta(k + 0.5, m - k + 0.5)."""
    marked_pass, labeled = _sums(strata, grade)  # Correct: marked Pass
    marked_fail = labeled - marked_pass
    agreed = ({"tpr": (marked_pass, marked_pass), "tnr": (0, marked_fail)} if grade == "pass"
              else {"tpr": (0, marked_pass), "tnr": (marked_fail, marked_fail)})
    return {key: sorted(rng.betavariate(k + 0.5, m - k + 0.5) for _ in range(draws))
            for key, (k, m) in agreed.items() if m > 0}


def middle(values: list[float] | None, level: float, point: float | None) -> list:
    """The middle `level` of sorted draws, widened to hold `point`; [None, None] when either is
    unknown."""
    if not values or point is None:
        return [None, None]
    lo, hi = _percentile(values, (1 - level) / 2), _percentile(values, (1 + level) / 2)
    return [min(lo, point), max(hi, point)]


def _table_kappa(tp: float, fn: float, fp: float, tn: float) -> float | None:
    """Cohen's kappa of a weighted table."""
    total = tp + fn + fp + tn
    if total <= 0:
        return None
    judge, people = (tp + fp) / total, (tp + fn) / total
    chance = judge * people + (1 - judge) * (1 - people)
    return _div((tp + tn) / total - chance, 1 - chance)


def _table(items, weights) -> dict | None:
    """TPR, TNR and kappa of (group, label, verdict) items, each weighing weights[group]."""
    tp = fn = fp = tn = 0.0
    for group, label, verdict in items:
        w = weights[group]
        if label == "pass":
            tp, fn = (tp + w, fn) if verdict == "pass" else (tp, fn + w)
        else:
            fp, tn = (fp + w, tn) if verdict == "pass" else (fp, tn + w)
    return {"tpr": _div(tp, tp + fn), "tnr": _div(tn, tn + fp),
            "kappa": _table_kappa(tp, fn, fp, tn)}


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * q
    low = int(k)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (k - low)


def _verdict_shares(rng: random.Random, k: int, m: int, saved: float, draws: int,
                    jeffreys: bool) -> list[float]:
    """Draws of the share of m answers the judge got right again, k of them. Beta(k, m - k),
    exactly 0 or 1 when none or all did, and the saved verdict (`saved`: 1 or 0) when there is
    none to tell; with `jeffreys`, Beta(k + 0.5, m - k + 0.5) instead."""
    if jeffreys:
        return [rng.betavariate(k + 0.5, m - k + 0.5) for _ in range(draws)]
    if m == 0:
        return [saved] * draws
    if k in (0, m):
        return [k / m] * draws
    return [rng.betavariate(k, m - k) for _ in range(draws)]


def _turned_shares(rng: random.Random, turned: int, m: int, slip: float,
                   draws: int) -> list[float]:
    """Draws of the share of m answers whose fresh grade turned from the saved one, `turned`
    of them, when the judge's grades turn round by themselves `slip` of the time."""
    s = max(0, WOBBLE_MARKS - m)
    return [rng.betavariate(turned + 0.5 + s * slip, m - turned + 0.5 + s * (1 - slip))
            for _ in range(draws)]


def _general_draws(by_group: dict, pool: dict, draws: int, seed: int,
                   jeffreys: bool, slip: float = 0.0) -> dict[str, list[float]]:
    """Sorted draws of TPR, TNR and kappa of the weighted table (see `general`)."""
    rng = random.Random(seed)
    shares = []  # per group: (pool, draws of p, of q, of r)
    for key, xs in by_group.items():
        if pool[key] <= 0:
            continue
        g = _grade(key)
        correct = [x for x in xs if x[1] == "pass"]
        wrong = [x for x in xs if x[1] != "pass"]
        passed = sum(x[2] == "pass" for x in correct)
        failed = sum(x[2] != "pass" for x in wrong)
        p = [rng.betavariate(len(correct) + 0.5, len(wrong) + 0.5) for _ in range(draws)]
        if slip > 0:
            turned_c = _turned_shares(rng, sum(x[2] != g for x in correct), len(correct), slip,
                                      draws)
            turned_w = _turned_shares(rng, sum(x[2] != g for x in wrong), len(wrong), slip,
                                      draws)
            q = [1 - t if g == "pass" else t for t in turned_c]  # passed again
            r = [t if g == "pass" else 1 - t for t in turned_w]  # failed again
        else:
            q = _verdict_shares(rng, passed, len(correct), float(g == "pass"), draws, jeffreys)
            r = _verdict_shares(rng, failed, len(wrong), float(g == "fail"), draws, jeffreys)
        shares.append((pool[key], p, q, r))
    values: dict[str, list[float]] = {"tpr": [], "tnr": [], "kappa": []}
    for i in range(draws):
        tp = fn = fp = tn = 0.0
        for w, p, q, r in shares:
            tp, fn = tp + w * p[i] * q[i], fn + w * p[i] * (1 - q[i])
            tn, fp = tn + w * (1 - p[i]) * r[i], fp + w * (1 - p[i]) * (1 - r[i])
        for key, value in (("tpr", _div(tp, tp + fn)), ("tnr", _div(tn, tn + fp)),
                           ("kappa", _table_kappa(tp, fn, fp, tn))):
            if value is not None:
                values[key].append(value)
    return {k: sorted(v) for k, v in values.items()}


def _grade(key) -> str:
    """The judge's grade of a group: the group itself, or a stratum's (batch, grade)."""
    return key if isinstance(key, str) else key[1]


def general(items: list[tuple[str, str, str]], n_pool_pass: int, n_pool_fail: int,
            level: float = LEVEL, draws: int = DRAWS, seed: int = SEED,
            wobble: float | None = None) -> dict:
    """TPR, TNR and kappa of the person's labels against fresh verdicts, weighted by the saved
    groups, each with its range: `general_strata` with one batch. `items` are (saved group,
    label, fresh verdict), each "pass" or "fail"."""
    out = general_strata(items, {"pass": n_pool_pass, "fail": n_pool_fail}, level, draws, seed,
                         wobble)
    out["groups"] = out.pop("strata")
    return out


def general_strata(items: list[tuple], pool: dict, level: float = LEVEL, draws: int = DRAWS,
                   seed: int = SEED, wobble: float | None = None) -> dict:
    """TPR, TNR and kappa of the person's labels against fresh verdicts, weighted by the
    strata the answers were picked from, each with its range. `items` are (stratum, label,
    fresh verdict); a stratum is (batch, the judge's saved grade), or a saved grade alone, and
    `pool` its size. Each labeled answer weighs N_stratum / n_stratum and the draws are per
    stratum. A stratum of the pool with no labeled answer counts for nothing in the numbers,
    and leaves the ranges unknown, as in `stratified`. `wobble`: the share of answers whose
    grades differed when the judge was asked twice, which widens the ranges (see the
    module)."""
    by_group = {g: [x for x in items if x[0] == g] for g in pool}
    weights = {g: _div(pool[g], len(xs)) or 0.0 for g, xs in by_group.items()}
    out = _table(items, weights)
    keys = ("tpr", "tnr")
    methods = dict.fromkeys(keys, "jeffreys")
    if any(pool[g] > 0 and not xs for g, xs in by_group.items()):
        for key in keys:  # a group of the judge with nothing counted: unknown, as in corrected
            out[key], out[f"{key}_interval"] = None, [None, None]
        out["kappa"], out["kappa_interval"] = None, [None, None]
    elif wobble:
        slip = (1 - max(1 - 2 * wobble, 0.0) ** 0.5) / 2  # as targets.slip_rate
        drawn = _general_draws(by_group, pool, draws, seed, jeffreys=False, slip=slip)
        for key in keys:
            out[f"{key}_interval"] = middle(drawn[key], level, out[key])
            methods[key] = "jeffreys, with the judge's wobble"
        out["kappa_interval"] = middle(drawn["kappa"], level, out["kappa"])
    else:
        drawn = _general_draws(by_group, pool, draws, seed, jeffreys=False)
        again = None
        for key in keys:
            interval = middle(drawn[key], level, out[key])
            if interval[0] is not None and interval[1] - interval[0] <= 1e-12:  # one point
                again = again or _general_draws(by_group, pool, draws, seed, jeffreys=True)
                interval = middle(again[key], level, out[key])
                methods[key] = "jeffreys, verdicts too"
            out[f"{key}_interval"] = interval
        out["kappa_interval"] = middle(drawn["kappa"], level, out["kappa"])
    out.update(interval_methods=methods, level=level, draws=draws, seed=seed, wobble=wobble,
               strata={_name(g): {"pool": pool[g], "labeled": len(by_group[g])} for g in pool})
    return out


def _name(key) -> str:
    """A stratum as a JSON key: the grade alone, or "<batch>/<grade>"."""
    return key if isinstance(key, str) else f"{key[0]}/{key[1]}"
