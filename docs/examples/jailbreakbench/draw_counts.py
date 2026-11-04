"""Count, for each of hundred_marks.py's 100 draws, the answers the marking page showed and
how the LLM-as-a-judge's grade and the experts' majority met on them.

    python3 -I draw_counts.py [--cache DIR] [--out DIR]

It reads each draw's project folder that hundred_marks.py left in --cache (default cache/
next to this file): the seed in .judgekeeper/start.json, and result.json's `groups`, which
judgekeeper wrote from the marks. For the answers the LLM-as-a-judge passed ("pass") and
failed ("fail"): `labeled`, how many the page showed and the experts' majority marked, and
`correct`, how many of those the experts passed.

Each draw's seed and disagreements must match --out's draws.csv (hundred_marks.py's), so the
folders are those draws. It writes --out's draw-counts.csv: numbers only, no prompt or
response.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEADER = ["draw", "seed", "shown_judge_pass", "shown_judge_fail", "judge_pass_experts_pass",
          "judge_pass_experts_fail", "judge_fail_experts_pass", "judge_fail_experts_fail"]


def _rows(path: Path) -> list[dict]:
    """A CSV's rows, after its # lines."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(line for line in f if not line.startswith("#")))


def _notes(path: Path) -> list[str]:
    """A CSV's # lines: its source and licence."""
    with path.open(encoding="utf-8") as f:
        return [line for line in f if line.startswith("#")]


def counts(folder: Path) -> dict:
    """One draw's row, from its project folder."""
    r = json.loads((folder / ".judgekeeper" / "result.json").read_text(encoding="utf-8"))
    start = json.loads((folder / ".judgekeeper" / "start.json").read_text(encoding="utf-8"))
    p, f = r["groups"]["pass"], r["groups"]["fail"]
    row = {"draw": folder.name, "seed": int(start["seed"]),
           "shown_judge_pass": int(p["labeled"]), "shown_judge_fail": int(f["labeled"]),
           "judge_pass_experts_pass": int(p["correct"]),
           "judge_pass_experts_fail": int(p["labeled"]) - int(p["correct"]),
           "judge_fail_experts_pass": int(f["correct"]),
           "judge_fail_experts_fail": int(f["labeled"]) - int(f["correct"])}
    if min(v for k, v in row.items() if k != "draw") < 0:
        raise SystemExit(f"{folder.name}: a count below 0")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=HERE / "cache")
    ap.add_argument("--out", type=Path, default=HERE / "hundred-marks")
    args = ap.parse_args(argv)
    draws = {r["draw"]: r for r in _rows(args.out / "draws.csv")}
    folders = sorted(p for p in (args.cache / "hundred-marks").glob("d[0-9]*") if p.is_dir())
    if sorted(p.name for p in folders) != sorted(draws):
        raise SystemExit("the draw folders in --cache are not the draws in draws.csv")
    rows = [counts(p) for p in folders]
    for row in rows:
        want = draws[row["draw"]]
        dis = row["judge_pass_experts_fail"] + row["judge_fail_experts_pass"]
        shown = row["shown_judge_pass"] + row["shown_judge_fail"]
        if (row["seed"], dis, shown) != (int(want["seed"]), int(want["disagreements"]),
                                         int(want["marks_counted"])):
            raise SystemExit(f"{row['draw']}: its folder does not match draws.csv")
    out = args.out / "draw-counts.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        f.writelines(_notes(args.out / "draws.csv"))
        w = csv.DictWriter(f, HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out.name}: {len(rows)} draws")
    return 0


if __name__ == "__main__":
    sys.exit(main())
