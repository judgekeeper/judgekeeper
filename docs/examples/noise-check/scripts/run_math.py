"""Math (GSM8K): every test question, run with no change and with changes, graded by code.

    export ANTHROPIC_API_KEY=...        # your own key
    export NOISE_MODEL=...              # the AI to test
    export NOISE_OLDER_MODEL=...        # an older, cheaper AI, for the "older AI" run
    python3 run_math.py

Downloads the public test set (1,319 questions; MIT licence, Cobbe et al. 2021). The same AI
and prompt answers every question 5 times with no change (same-1 to same-5). Other runs: worse
(prompt set up to fail), small-a-1 (one added sentence), older-ai-1 (the older AI, same prompt).
A run's grade is pass when the last number in the answer equals the reference answer (code,
exact match; no LLM-as-a-judge, no person). Graded runs are written to
$NOISE_WORK/rounds/math/<run>.csv (columns input, output, verdict). A run already written is
skipped. Run make_grades.py on that folder to get the files that are safe to share.
"""

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from common import WORK, client, download, need, read_parquet, write_round

REVISION = "740312add88f781978c0658806c59bc2815b9866"
URL = ("https://huggingface.co/datasets/openai/gsm8k/resolve/"
       f"{REVISION}/main/test-00000-of-00001.parquet")
SHA256 = "ee7b8da9e381df27b9e3f7758a159ab2bdaa4dbaa910546cbbc47e0cb44e4f59"
ROWS, N, SEED = 1319, 1319, 20261119
MAX_TOKENS = 1024
V1 = "Answer with only the final number."
PROMPTS = {f"same-{k}": V1 for k in range(1, 6)}
PROMPTS["worse"] = V1 + " Do not work it out; give your quick first guess."
PROMPTS["small-a-1"] = V1 + " Answer quickly."
PROMPTS["older-ai-1"] = V1


def questions() -> list[dict]:
    data = WORK / "cache" / "gsm8k-test.parquet"
    download(URL, data, SHA256)
    rows = read_parquet(data)
    assert len(rows) == ROWS
    picked = random.Random(SEED).sample(range(ROWS), N)
    (WORK / "cache" / "math-sample.json").write_text(json.dumps({"seed": SEED, "rows": picked}) + "\n")
    return [{"question": rows[i]["question"],
             "reference": rows[i]["answer"].rsplit("####", 1)[1].strip().replace(",", "")}
            for i in picked]


def last_number(text: str) -> str | None:
    nums = re.findall(r"-?\d[\d,]*\.?\d*", text)
    if not nums:
        return None
    x = nums[-1].replace(",", "").rstrip(".")
    return x.removesuffix(".0")


def main() -> None:
    model = need("NOISE_MODEL", "the AI to test")
    older = need("NOISE_OLDER_MODEL", "an older, cheaper AI")
    qs = questions()
    api = client()

    for name, prompt in PROMPTS.items():
        if (WORK / "rounds" / "math" / f"{name}.csv").exists():
            print(f"math/{name}: done before")
            continue

        def ask(q: dict, name=name, prompt=prompt) -> dict:
            r = api.messages.create(model=older if name == "older-ai-1" else model,
                                    max_tokens=MAX_TOKENS, system=prompt,
                                    thinking={"type": "disabled"},
                                    messages=[{"role": "user", "content": q["question"]}])
            if r.stop_reason != "end_turn":
                raise RuntimeError(f"stop_reason {r.stop_reason}")
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            ok = last_number(text) == q["reference"]
            return {"input": q["question"], "output": text, "verdict": "pass" if ok else "fail"}

        with ThreadPoolExecutor(8) as pool:
            rows = list(pool.map(ask, qs))
        write_round("math", name, rows, ["input", "output", "verdict"])


if __name__ == "__main__":
    main()
