"""Count every pair again from the grade files.

    python3 -I pairs.py

For each set, prints the pass rate of every run, then for every pair judgekeeper was run on:
questions compared, fixed, broke, the move in points, and what change_kind says (the function
behind judgekeeper's "made it worse" / "leans worse" lines). Also, for the no-change runs, how
many answers differ between two runs. Needs judgekeeper installed.
"""

import itertools
import json
import os
from pathlib import Path

from judgekeeper.no_grades import change_kind

GRADES = Path(os.environ.get("NOISE_GRADES") or Path(__file__).resolve().parent.parent / "grades")
CHANGES = {"math": ("worse", "small-a-1", "older-ai-1"),
           "truthfulness": ("worse-2", "small-a-1", "older-ai-1"),
           "multiple-choice": ("worse", "older-ai-1")}


def load(set_name: str, run: str) -> dict[str, str]:
    return json.loads((GRADES / set_name / f"{run}.json").read_text(encoding="utf-8"))


def rate(r: dict[str, str]) -> float:
    return 100 * sum(v == "pass" for v in r.values()) / len(r)


def pair(a: dict[str, str], b: dict[str, str]) -> tuple[int, int, int, float, str]:
    qs = [q for q in a if q in b]
    fixed = sum(a[q] == "fail" and b[q] == "pass" for q in qs)
    broke = sum(a[q] == "pass" and b[q] == "fail" for q in qs)
    return len(qs), fixed, broke, rate(b) - rate(a), change_kind(fixed, broke, len(qs), test=1)


def main() -> None:
    for set_name, changes in CHANGES.items():
        runs = [p.stem for p in sorted((GRADES / set_name).glob("*.json"))]
        data = {r: load(set_name, r) for r in runs}
        print(f"== {set_name}")
        for r in runs:
            print(f"{r}: {rate(data[r]):.1f}% pass of {len(data[r])}")
        flips = []
        for a, b in itertools.combinations([f"same-{i}" for i in range(1, 6)], 2):
            n, f, br, pts, kind = pair(data[a], data[b])
            flips.append(f + br)
            print(f"{a} -> {b}: n={n} fixed={f} broke={br} flips={f + br} points={pts:+.1f} {kind}")
        print(f"no-change flips: {min(flips)} to {max(flips)} of {n}")
        base = sum(rate(data[f"same-{i}"]) for i in range(1, 6)) / 5
        print(f"average of the 5 no-change runs: {base:.2f}%")
        for c in changes:
            print(f"{c} against that average: {rate(data[c]) - base:+.2f} points")
        for c in (*changes, *(["same-1-regrade"] if set_name == "truthfulness" else [])):
            for i in range(1, 6):
                if c == "same-1-regrade" and i > 1:
                    continue
                n, f, br, pts, kind = pair(data[f"same-{i}"], data[c])
                print(f"same-{i} -> {c}: n={n} fixed={f} broke={br} points={pts:+.1f} {kind}")


if __name__ == "__main__":
    main()
