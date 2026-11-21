"""How many questions does a small drop need?

    python3 -I dose_n.py                                    # math (the default)
    python3 -I dose_n.py truthfulness worse-2 100,200,400,817

Reads the grade files in ../grades/<set>/ (or in $NOISE_GRADES/<set>/ if you set it). Needs
judgekeeper installed: it uses judgekeeper.no_grades.change_kind, the function behind
"made it worse".

Pick n questions at random, hurt k% of them (the answer comes from the set-up-to-fail run),
take the rest from a no-change run, and compare with a different no-change run. 20 (before,
filler) pairs x 25 random picks = 500 tries per cell. Prints the mean real drop in points,
how often judgekeeper says "made it worse", and how often it says "leans worse". k = 0 is the
false-alarm rate.

The questions are drawn from the order they are listed in the grade files (sorted by question
text), so the same seed gives the same draws.
"""

import itertools
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

from judgekeeper.no_grades import change_kind

GRADES = Path(os.environ.get("NOISE_GRADES") or Path(__file__).resolve().parent.parent / "grades")
FOLDER, BAD = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("math", "worse")
NS = (tuple(int(x) for x in sys.argv[3].split(",")) if len(sys.argv) > 3
      else (100, 200, 500, 1000, 1319))
KS = (0, 5, 10, 15, 20, 30)
TRIES = 25


def load(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    d = GRADES / FOLDER
    same = {p.stem: load(p) for p in sorted(d.glob("same-[0-9].json"))}
    bad = load(d / f"{BAD}.json")
    allq = list(next(iter(same.values())))
    assert len(same) == 5 and all(set(r) == set(allq) for r in [*same.values(), bad])

    def rate(r: dict[str, str]) -> float:
        return 100 * sum(v == "pass" for v in r.values()) / len(r)

    print("pass rates:", {k: f"{rate(v):.1f}%" for k, v in same.items()}, f"worse {rate(bad):.1f}%")
    print("cells: mean drop in points / share of tries that say 'made it worse' / 'leans worse'")
    print("hurt%  " + "  ".join(f"{'n=' + str(n):>22}" for n in NS))
    for k in KS:
        cells = []
        for n in NS:
            rng = random.Random(f"{n}-{k}")
            kinds, drops = Counter(), []
            for base, fill in itertools.permutations(same, 2):
                for _ in range(TRIES):
                    qs = rng.sample(allq, n)
                    hit = set(rng.sample(qs, round(n * k / 100)))
                    b = same[base]
                    mix = {q: (bad[q] if q in hit else same[fill][q]) for q in qs}
                    fixed = sum(b[q] == "fail" and mix[q] == "pass" for q in qs)
                    broke = sum(b[q] == "pass" and mix[q] == "fail" for q in qs)
                    kinds[change_kind(fixed, broke, n, test=1)] += 1
                    drops.append(100 * (sum(b[q] == "pass" for q in qs) -
                                        sum(mix[q] == "pass" for q in qs)) / n)
            t = sum(kinds.values())
            cells.append(f"{sum(drops) / t:5.1f} / {100 * kinds['worse'] / t:5.1f}% /"
                         f" {100 * kinds['leans worse'] / t:4.0f}%")
        print(f"{k:4d}   " + "  ".join(f"{c:>22}" for c in cells))


if __name__ == "__main__":
    main()
