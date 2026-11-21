"""Multiple choice (MMLU): 1,000 test questions, run with no change and with changes, graded by code.

    export ANTHROPIC_API_KEY=...        # your own key
    export NOISE_MODEL=...              # the AI to test
    export NOISE_OLDER_MODEL=...        # an older, cheaper AI, for the "older AI" run
    python3 run_multiple_choice.py

Downloads the public test set (all subjects; MIT licence, Hendrycks et al. 2021) and picks 1,000
questions with a fixed seed. The same AI and prompt answers them 5 times with no change (same-1
to same-5), once with a prompt set up to fail (worse) and once with the older AI (older-ai-1).
Graded by code: pass when the answer's letter (a bare letter at the start, else the letter after
"answer is", else the last standalone A-D) is the right one. Graded runs are written to
$NOISE_WORK/rounds/multiple-choice/<run>.csv (columns id, input, output, verdict). A run already
written is skipped. Run make_grades.py on that folder to get the files that are safe to share.
"""

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from common import WORK, client, download, need, read_parquet, write_round

REVISION = "c30699e8356da336a370243923dbaf21066bb9fe"
URL = ("https://huggingface.co/datasets/cais/mmlu/resolve/"
       f"{REVISION}/all/test-00000-of-00001.parquet")
N, SEED = 1000, 20261119
MAX_TOKENS = 1024
V1 = "Answer with only the letter of the correct choice."
PROMPTS = {f"same-{k}": V1 for k in range(1, 6)}
PROMPTS["worse"] = V1 + " Pick the first choice that looks right without reading the others."
PROMPTS["older-ai-1"] = V1
LETTERS = "ABCD"


def questions() -> list[dict]:
    data = WORK / "cache" / "mmlu-test.parquet"
    sha = download(URL, data)
    rows = read_parquet(data)
    picked = random.Random(SEED).sample(range(len(rows)), N)
    (WORK / "cache" / "multiple-choice-sample.json").write_text(json.dumps(
        {"revision": REVISION, "sha256": sha, "rows": len(rows), "seed": SEED,
         "picked": picked}) + "\n")
    out = []
    for i in picked:
        r = rows[i]
        text = r["question"].strip() + "\n\n" + "\n".join(
            f"{LETTERS[j]}. {c}" for j, c in enumerate(r["choices"]))
        out.append({"id": f"mmlu-test-{i:05d}", "question": text, "answer": LETTERS[r["answer"]]})
    return out


def letter(text: str) -> str | None:
    """The answer's letter: a bare letter at the start ("B", "B.", "**B**"), else after
    "answer is", else the last standalone A-D (an article "A" early in a sentence is not it)."""
    t = text.strip()
    m = re.match(r"^\W*([ABCD])(?:[.):*\]]|\s*$|\s*\n)", t)
    if m:
        return m.group(1)
    m = re.search(r"answer(?: is)?\W*\(?([ABCD])\b", t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    found = re.findall(r"\b([ABCD])\b", t)
    return found[-1] if found else None


def main() -> None:
    model = need("NOISE_MODEL", "the AI to test")
    older = need("NOISE_OLDER_MODEL", "an older, cheaper AI")
    qs = questions()
    api = client()

    for name, prompt in PROMPTS.items():
        if (WORK / "rounds" / "multiple-choice" / f"{name}.csv").exists():
            print(f"multiple-choice/{name}: done before")
            continue

        def ask(q: dict, name=name, prompt=prompt) -> dict:
            r = api.messages.create(model=older if name == "older-ai-1" else model,
                                    max_tokens=MAX_TOKENS, system=prompt,
                                    thinking={"type": "disabled"},
                                    messages=[{"role": "user", "content": q["question"]}])
            if r.stop_reason != "end_turn":
                raise RuntimeError(f"{q['id']}: stop_reason {r.stop_reason}")
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            ok = letter(text) == q["answer"]
            return {"id": q["id"], "input": q["question"], "output": text,
                    "verdict": "pass" if ok else "fail"}

        with ThreadPoolExecutor(8) as pool:
            rows = list(pool.map(ask, qs))
        write_round("multiple-choice", name, rows, ["id", "input", "output", "verdict"])


if __name__ == "__main__":
    main()
