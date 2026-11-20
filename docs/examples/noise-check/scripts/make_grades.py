"""Turn the graded runs into grade files with no question or answer text.

    python3 -I make_grades.py <rounds-folder> <set-name>

Reads every <run>.csv in <rounds-folder> (columns input, output, verdict; multiple choice also
has id) and writes ../grades/<set-name>/<run>.json: {question_hash: "pass" | "fail"}.
The hash is the first 16 hex characters of the sha256 of the question text (UTF-8), the text
being the CSV's input column. Questions are written in the order of their text, sorted, so
every run's file lists them in the same order (dose_n.py uses that order).

The files go to $NOISE_WORK/grades/<set-name>/ (default noise-work/grades), so a new run never
overwrites the committed ones in ../grades. To count your own runs with dose_n.py or pairs.py,
set NOISE_GRADES to that folder.
"""

import csv
import hashlib
import json
import os
import sys
from pathlib import Path


def qhash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: make_grades.py <rounds-folder> <set-name>")
    src, name = Path(sys.argv[1]), sys.argv[2]
    out = Path(os.environ.get("NOISE_WORK", "noise-work")).resolve() / "grades" / name
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            rows = {r["input"]: r["verdict"] for r in csv.DictReader(f)}
        grades = {}
        for question in sorted(rows):
            if rows[question] not in ("pass", "fail"):
                sys.exit(f"{path.name}: verdict {rows[question]!r} is not pass or fail")
            h = qhash(question)
            if h in grades:
                sys.exit(f"{path.name}: two questions share the hash {h}")
            grades[h] = rows[question]
        (out / f"{path.stem}.json").write_text(json.dumps(grades) + "\n", encoding="utf-8")
        print(f"{name}/{path.stem}.json: {len(grades)} questions")


if __name__ == "__main__":
    main()
