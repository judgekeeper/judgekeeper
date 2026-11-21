"""How many answers are only the number (math) or only the letter (multiple choice)?

    python3 -I answer_shape.py <rounds-folder> math|multiple-choice

The prompts say "Answer with only the final number" / "only the letter of the correct choice".
This counts, per run, the answers that did just that. Prints counts only, no answer text.
"""

import csv
import re
import sys
from pathlib import Path

BARE = {"math": re.compile(r"\W*-?[\d,]*\.?\d+\W*"), "multiple-choice": re.compile(r"\W*[ABCD]\W*")}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in BARE:
        sys.exit("usage: answer_shape.py <rounds-folder> math|multiple-choice")
    pattern = BARE[sys.argv[2]]
    for path in sorted(Path(sys.argv[1]).glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            answers = [r["output"].strip() for r in csv.DictReader(f)]
        bare = sum(bool(pattern.fullmatch(a)) for a in answers)
        print(f"{sys.argv[2]}/{path.stem}: {bare} of {len(answers)} answers are only the "
              f"{'number' if sys.argv[2] == 'math' else 'letter'}")


if __name__ == "__main__":
    main()
