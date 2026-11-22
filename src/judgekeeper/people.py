"""How much the people who labelled the answers agree with each other. Plain Python.

The input is a list of (answer id, person, label): one line per label a person gave. A person
who labelled an answer twice counts once, by the last line. Two people: Cohen's kappa
(metrics.cohen_kappa). Three or more: Krippendorff's alpha for nominal labels, which allows
answers that not every person labelled. Both are over the answers that two or more people
labelled, and both come with a range: answers drawn again with replacement (a bootstrap),
DRAWS times with a fixed SEED, cut at the middle LEVEL, as weighted.py does. Raw agreement is
never shown alone. Under MIN_SHARED such answers no number is given.

The check against each person is metrics.agreement (kappa, TPR, TNR) on the answers that
person labelled.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from judgekeeper import metrics, weighted
from judgekeeper.textio import jsonl_lines, loads, plural, write_replacing

FILE = "people.jsonl"  # in .judgekeeper/: what each person said, for the agreement numbers
MIN_SHARED = 10  # answers labelled by two or more people, before any number is given
LEVEL = weighted.LEVEL
SEED = weighted.SEED
DRAWS = 2_000  # fewer than weighted.DRAWS: every draw works the number out again from scratch
SHOW_PEOPLE = 10  # people named in the line of counts

KAPPA_LINE = ("Your people agree with each other: kappa {k} (between {lo} and {hi}), on {n} "
              "answers labelled by more than one person.")
ALPHA_LINE = ("Your people agree with each other: Krippendorff's alpha {k} (between {lo} and "
              "{hi}), on {n} answers labelled by more than one person.")
LIMIT_LINE = ("A check can't be expected to agree with your people more than they agree with "
              "each other.")
TOO_FEW_LINE = ("Fewer than {min} answers were labelled by more than one person, so "
                "judgekeeper can't say how much your people agree.")
SAME_LINE = ("Your people gave the same label to every answer, so how much they agree beyond "
             "coincidence can't be worked out.")
COUNTS_LINE = "Answers labelled by each person: {people}."
AGAINST_LINE = "Your check against user {who}, on {answers}: kappa {kappa}. {pass_} {fail}."
PASS_CLAUSE = "When user {who} says Pass, your check also says Pass {tpr} of the time;"
FAIL_CLAUSE = "when user {who} says Fail, it also says Fail {tnr} of the time"
OTHERS_LINE = "Your check against the other {others} is in .judgekeeper/result.json."
NO_PASS_CLAUSE = "User {who} passed none of these answers;"  # no Pass to find: no rate
NO_FAIL_CLAUSE = "user {who} failed none of these answers"


# The numbers ------------------------------------------------------------------------------

def alpha_nominal(units: list[list]) -> float | None:
    """Krippendorff's alpha for nominal labels: `units` is one list of labels per answer, one
    label for each person who labelled it, in any number. An answer with fewer than two labels
    is left out. None when no pair of labels is left, or when every label is the same (chance
    agreement is then complete)."""
    return _alpha(_coincidences(units))


def _coincidences(units: list[list]) -> Counter:
    """The coincidence matrix as {(c, k): weight}: every ordered pair of labels given to the
    same answer by two different people adds 1 / (labels - 1)."""
    out: Counter = Counter()
    for unit in units:
        m = len(unit)
        if m < 2:
            continue
        counts = Counter(unit)
        for c, nc in counts.items():
            for k, nk in counts.items():
                pairs = nc * nk if c != k else nc * (nc - 1)
                if pairs:
                    out[(c, k)] += pairs / (m - 1)
    return out


def _alpha(o: Counter) -> float | None:
    totals: Counter = Counter()
    for (c, _), w in o.items():
        totals[c] += w
    n = sum(totals.values())
    expected = sum(totals[c] * totals[k] for c in totals for k in totals if c != k)
    if n <= 1 or expected == 0:
        return None
    observed = sum(w for (c, k), w in o.items() if c != k)
    return 1 - (n - 1) * observed / expected


def _last_labels(ratings) -> dict[str, dict[str, str]]:
    """{answer id: {person: label}}, the last line of a person winning. People are named as
    text (a Label Studio user id is a number)."""
    by_answer: dict[str, dict[str, str]] = defaultdict(dict)
    for item, who, label in ratings:
        by_answer[item][str(who)] = label
    return by_answer


def per_person(by_answer: dict[str, dict[str, str]]) -> dict[str, int]:
    counts: Counter = Counter()
    for given in by_answer.values():
        counts.update(given.keys())
    return dict(sorted(counts.items(), key=lambda kv: _order(kv[0])))


def _order(who: str):
    return (0, int(who), who) if who.isdigit() else (1, 0, who)


def _middle(draws: list[float], point: float | None, level: float) -> list:
    return weighted.middle(draws, level, point)


def _kappa_draws(pairs: list[tuple], draws: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        sample = rng.choices(pairs, k=len(pairs))
        k = metrics.cohen_kappa([a for a, _ in sample], [b for _, b in sample])
        if k is not None:
            out.append(k)
    return out


def _alpha_draws(units: list[Counter], draws: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        total: Counter = Counter()
        for unit in rng.choices(units, k=len(units)):
            total.update(unit)
        a = _alpha(total)
        if a is not None:
            out.append(a)
    return out


def between(ratings, level: float = LEVEL, draws: int = DRAWS, seed: int = SEED) -> dict | None:
    """How much the people agree: {"people", "answers", "shared", "per_person", "enough",
    "measure" ("kappa" for two people, "alpha" for more), "value", "interval", "level", "draws",
    "seed"}. None when fewer than two people labelled anything. With fewer than MIN_SHARED
    answers labelled by more than one person, `enough` is False and there is no number."""
    by_answer = _last_labels(ratings)
    counts = per_person(by_answer)
    if len(counts) < 2:
        return None
    shared = {i: g for i, g in by_answer.items() if len(g) >= 2}
    out = {"people": len(counts), "answers": len(by_answer), "shared": len(shared),
           "per_person": counts, "enough": len(shared) >= MIN_SHARED,
           "measure": "kappa" if len(counts) == 2 else "alpha", "value": None,
           "interval": [None, None], "level": level, "draws": draws, "seed": seed}
    if not out["enough"]:
        return out
    order = sorted(shared)  # the same draws whatever order the lines came in
    if out["measure"] == "kappa":
        a, b = list(counts)
        pairs = [(shared[i][a], shared[i][b]) for i in order if a in shared[i] and b in shared[i]]
        out["value"] = metrics.cohen_kappa([x for x, _ in pairs], [y for _, y in pairs])
        out["shared"] = len(pairs)
        drawn = _kappa_draws(pairs, draws, seed) if out["value"] is not None else []
    else:
        units = [list(shared[i].values()) for i in order]
        out["value"] = alpha_nominal(units)
        drawn = (_alpha_draws([_coincidences([u]) for u in units], draws, seed)
                 if out["value"] is not None else [])
    out["interval"] = _middle(drawn, out["value"], level)
    return out


def against_check(ratings, check: dict[str, str], positive: str = "pass",
                  negative: str = "fail") -> dict[str, dict]:
    """The check against each person, on the answers that person labelled and the check
    graded: {person: {"n", "kappa", "tpr", "tnr"}} (metrics.agreement). `check` is {answer id:
    the check's verdict}; an answer it gave no verdict for (metrics.ERROR) or has none for is
    left out."""
    by_answer = _last_labels(ratings)
    out = {}
    for who in per_person(by_answer):
        ids = [i for i, g in by_answer.items()
               if who in g and check.get(i) not in (None, metrics.ERROR)]
        if not ids:
            continue
        a = metrics.agreement([by_answer[i][who] for i in ids], [check[i] for i in ids],
                              positive, negative)
        out[who] = {"n": a["n"], "kappa": a["kappa"], "tpr": a["tpr"], "tnr": a["tnr"]}
    return out


def analyse(ratings, check: dict[str, str] | None, positive: str = "pass",
            negative: str = "fail") -> dict | None:
    """`between` and, with a check, `against_check` as "vs_check"; the block result.json keeps
    as "people". None when fewer than two people labelled anything."""
    ratings = list(ratings)
    out = between(ratings)
    if out is None:
        return None
    out["vs_check"] = against_check(ratings, check, positive, negative) if check else {}
    return out


# The file the ratings are kept in -----------------------------------------------------------

def save(path: str | Path, source: str, ratings) -> None:
    """Keep `ratings` ((answer id, person, mark): one line each, the person only a number)
    of the import `source` (a file's base name) in `path`, replacing what an earlier run of the
    same file kept and leaving other files' lines; no file when none is left."""
    path = Path(path)
    kept = [x for x in _lines(path) if x.get("from") != source]
    new = [{"id": i, "who": who, "mark": mark, "from": source} for i, who, mark in ratings]
    lines = [json.dumps(x, ensure_ascii=False) for x in kept + new]
    if lines:
        write_replacing(path, "\n".join(lines) + "\n")
    elif path.is_file() or path.is_symlink():
        path.unlink()


def _lines(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    out = []
    for raw in jsonl_lines(text):
        try:
            x = loads(raw) if raw.strip() else None
        except ValueError:
            continue
        if isinstance(x, dict) and all(isinstance(x.get(k), str) for k in ("id", "mark")) \
                and x.get("who") is not None:
            out.append(x)
    return out


def load(path: str | Path) -> list[tuple[str, str, str]]:
    """(answer id, person, mark) of every line `save` kept; [] when there is no file."""
    return [(x["id"], str(x["who"]), x["mark"]) for x in _lines(Path(path))]


# The lines ------------------------------------------------------------------------------------

def _two(x: float) -> str:
    text = f"{x:.2f}"
    return "0.00" if text == "-0.00" else text  # a plain minus sign: a legacy console has no real one


def _share(x: float | None) -> str:
    from judgekeeper.textio import percent

    return "unknown" if x is None else percent(x)


def lines(block: dict | None) -> list[str]:
    """The plain-words lines for `analyse`'s result: how much the people agree (or that there
    are too few answers for a number), how many answers each person labelled, and the check
    against each person. [] for None."""
    if not block:
        return []
    out = []
    if not block["enough"]:
        out.append(TOO_FEW_LINE.format(min=MIN_SHARED))
    elif block["value"] is None:
        out.append(SAME_LINE)
    else:
        lo, hi = block["interval"]
        line = KAPPA_LINE if block["measure"] == "kappa" else ALPHA_LINE
        out += [line.format(k=_two(block["value"]), lo=_two(lo), hi=_two(hi),
                            n=block["shared"]), LIMIT_LINE]
    named = [f"user {who} ({n})" for who, n in block["per_person"].items()]
    shown = ", ".join(named[:SHOW_PEOPLE])
    if len(named) > SHOW_PEOPLE:
        shown += f" and {len(named) - SHOW_PEOPLE} more"
    out.append(COUNTS_LINE.format(people=shown))
    against = block.get("vs_check") or {}
    # the SHOW_PEOPLE with the most answers (a tie: by their numbers); the rest only in result.json
    first = sorted(against, key=lambda who: (-against[who]["n"], _order(who)))[:SHOW_PEOPLE]
    for who in (w for w in against if w in first):
        a = against[who]
        pass_ = (NO_PASS_CLAUSE if a["tpr"] is None else PASS_CLAUSE).format(
            who=who, tpr=_share(a["tpr"]))
        fail = (NO_FAIL_CLAUSE if a["tnr"] is None else FAIL_CLAUSE).format(
            who=who, tnr=_share(a["tnr"]))
        out.append(AGAINST_LINE.format(
            who=who, kappa="n/a" if a["kappa"] is None else _two(a["kappa"]),
            answers=plural(a["n"], "answer"), pass_=pass_, fail=fail))
    if len(against) > SHOW_PEOPLE:
        k = len(against) - SHOW_PEOPLE
        out.append(OTHERS_LINE.format(others="person" if k == 1 else f"{k} people"))
    return out
