"""Grade the DICES-350 conversations with a Claude model: is the chatbot's last reply safe?

    python3 -I load.py OUT_FOLDER
    ANTHROPIC_API_KEY=... python3 -I grade.py --export OUT_FOLDER/label-studio-export.json \
        --setup a --out OUT_FOLDER

Needs `pip install anthropic`. Setup a is claude-sonnet-5-5; it uses prompt.txt, word for word, and
the model's default effort. The conversations are adversarial, so the API may refuse some. Each
refusal is recorded as an error with its category and is not asked again. Writes into --out
(keep it outside the repository: the replies hold the dataset's text):
  raw-setup-<a|b>.jsonl      every reply, with its fingerprint, token counts and cost
  results-setup-<a|b>.jsonl  the grades in judgekeeper's records format, with input and output
  grades-setup-<a|b>.csv     ids, grades and fingerprints only: the file the repository keeps
  summary-setup-<a|b>.json   counts of graded items, errors and refusals, tokens and cost
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic
import claude_grader as grader

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "prompt.txt"
RUBRIC_VERSION = "dices-safe-reply-v1"
SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["Pass", "Fail"]},
                   "reason": {"type": "string"}},
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}
HEADER = [
    ("Source: DICES-350 (github.com/google-research-datasets/dices-dataset, CC BY 4.0, Copyright "
     "Google LLC), loaded by load.py"),
    ("Grades: Claude through the Anthropic API with prompt.txt, by grade.py (grade 'none' = no real "
     "decision, the kind is in the error column; Pass = safe, Fail = unsafe)"),
    ("Holds: ids, grades and fingerprints only; no conversation or reply, no rater. id is the "
     "dataset's item_id"),
]


def parse(text: str, item_id: int) -> tuple[str, str]:
    reply = grader.read_json_reply(text)
    verdict = str(reply.get("verdict", "")).strip().lower()
    if verdict not in ("pass", "fail"):
        raise ValueError(f"verdict is {reply.get('verdict')!r}, not Pass or Fail")
    return verdict, str(reply.get("reason", ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--export", type=Path, required=True, help="load.py's label-studio-export.json")
    grader.add_args(p)
    args = p.parse_args()
    if args.setup != "a":
        p.error("this example uses setup a only")
    tasks = json.loads(args.export.read_text(encoding="utf-8"))
    template = TEMPLATE.read_text(encoding="utf-8")
    by_id = {t["id"]: t["data"] for t in tasks}
    items = [(t["id"], grader.fill(template, conversation=t["data"]["input"],
                                   reply=t["data"]["output"])) for t in tasks]
    items = grader.spread(items, args.limit)
    client = anthropic.Anthropic()
    name, model, _ = grader.SETUPS[args.setup]
    if args.count_tokens:
        counts = grader.count_tokens(client, model, items, args.workers)
        print(json.dumps({"setup": name, "items": len(items),
                          "input_tokens": sum(n for n in counts.values() if n),
                          "too_long": [i for i, n in counts.items() if n is None]}))
        return
    records = grader.grade_items(client, args.setup, items, parse, TEMPLATE, RUBRIC_VERSION,
                                 args.out, args.workers, lambda v: v, HEADER, schema=SCHEMA)
    grader.write_records(args.out / f"results-{name}.jsonl", records, by_id,
                         "Last reply is safe")


if __name__ == "__main__":
    main()
