"""Ask a Claude reviewer for the first wrong step of each AgentProcessBench gaia_dev run.

    python3 -I load.py OUT_FOLDER
    ANTHROPIC_API_KEY=... python3 -I grade.py --runs OUT_FOLDER/runs.jsonl --setup a \
        --out OUT_FOLDER
    python3 -I load.py OUT_FOLDER --guesses OUT_FOLDER/guesses-setup-a.jsonl

Needs `pip install anthropic`. Setup a is claude-sonnet-5-5; it uses prompt.txt, word for word,
and the model's default effort. The reviewer reads the task and every step, with no reference
answer, and says the number of the first wrong step (0 = all fine). A run that does not fit the
model's context window is recorded as an error (too_long) and is not cut down. Writes into --out
(keep it outside the repository: the replies hold the dataset's text):
  raw-setup-<a|b>.jsonl      every reply, with its fingerprint, token counts and cost
  guesses-setup-<a|b>.jsonl  {id, first_wrong_step, model} per run the reviewer answered
  grades-setup-<a|b>.csv     ids, guesses and fingerprints only: the file the repository keeps
  summary-setup-<a|b>.json   counts of graded runs and errors, tokens and cost
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
RUBRIC_VERSION = "first-wrong-step-v1"
SCHEMA = {
    "type": "object",
    "properties": {"first_wrong_step": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["first_wrong_step", "reason"],
    "additionalProperties": False,
}
HEADER = [
    ("Source: AgentProcessBench gaia_dev (huggingface.co/datasets/LulaCola/AgentProcessBench, MIT "
     "per the dataset card), loaded by load.py"),
    ("Grades: a Claude reviewer through the Anthropic API with prompt.txt, by grade.py: the number of "
     "the first wrong step, 0 = all fine (grade 'none' = no real decision, the kind is in the error "
     "column)"),
    "Holds: ids, guesses and fingerprints only; no task or step. id is the dataset's total_index",
]
STEP_COUNTS: dict[int, int] = {}


def parse(text: str, item_id: int) -> tuple[int, str]:
    reply = grader.read_json_reply(text)
    value = reply.get("first_wrong_step")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"first_wrong_step is {value!r}, not a whole number")
    if not 0 <= value <= STEP_COUNTS[item_id]:
        raise ValueError(f"first_wrong_step {value} is outside 0 to {STEP_COUNTS[item_id]}")
    return value, str(reply.get("reason", ""))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=Path, required=True, help="load.py's runs.jsonl")
    grader.add_args(p)
    args = p.parse_args()
    if args.setup != "a":
        p.error("this example uses setup a only")
    template = TEMPLATE.read_text(encoding="utf-8")
    items = []
    for line in args.runs.read_text(encoding="utf-8").splitlines():
        run = json.loads(line)
        STEP_COUNTS[run["id"]] = len(run["steps"])
        steps = "\n\n".join(f"[Step {n}]\n{s['content']}" for n, s in enumerate(run["steps"], 1))
        items.append((run["id"], grader.fill(template, task=run["task"], steps=steps)))
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
                                 args.out, args.workers, str, HEADER, schema=SCHEMA)
    with (args.out / f"guesses-{name}.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            if r["ok"]:
                f.write(json.dumps({"id": r["id"], "first_wrong_step": r["value"],
                                    "model": model}) + "\n")


if __name__ == "__main__":
    main()
