"""Download JailbreakBench's judge-comparison set and write it as a judgekeeper results file.

    python3 -I load.py

Source: the Hugging Face dataset JailbreakBench/JBB-Behaviors (MIT license), file
data/judge-comparison.csv, pinned to one revision and checked by its SHA-256, so the data
cannot change under the report. Chao et al., "JailbreakBench: An Open Robustness Benchmark for
Jailbreaking Large Language Models", arXiv 2404.01318.

Writes, in cache/ next to this file (its .gitignore is `*`: the prompts and responses are
harmful, so never commit them):
  judge-comparison.csv   the download
  results.jsonl          one line per row: id, input (the prompt), output (the response) and
                         verdict, GPT-4's grade (gpt4_cf: 0, not jailbroken = pass; 1 = fail)
Then `judgekeeper cache/results.jsonl --judge-model openai:gpt-4-0613` reads it. The experts'
majority for each id is in ids-and-grades.csv next to this file.
"""

import csv
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
REVISION = "886acc352a31533ffbcf4ef22c744658688086fc"
URL = ("https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/resolve/"
       f"{REVISION}/data/judge-comparison.csv")
SHA256 = "dacaf76a1057785f11b0fc6aa07b9a73cdab588319ddfc5e8cef2909e5b112a5"
NOTICE = """JailbreakBench is MIT licensed, Copyright (c) 2023 JailbreakBench Team.
Cite: Chao et al., "JailbreakBench: An Open Robustness Benchmark for Jailbreaking Large
Language Models", NeurIPS 2024 Datasets and Benchmarks Track, arXiv 2404.01318.
The license text is in THIRD_PARTY_NOTICES.md at the repository's root."""


def grade(cell: str) -> str:
    if cell not in ("0", "1"):
        sys.exit(f"unexpected grade {cell!r}; stop and look.")
    return "pass" if cell == "0" else "fail"


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    gitignore = CACHE / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    data = CACHE / "judge-comparison.csv"
    if not data.exists():
        print(f"downloading judge-comparison.csv from JailbreakBench/JBB-Behaviors@{REVISION[:7]}")
        with urllib.request.urlopen(URL, timeout=120) as r:
            body = r.read()
        part = data.with_suffix(".part")
        part.write_bytes(body)
        part.replace(data)
        print(NOTICE)
    got = hashlib.sha256(data.read_bytes()).hexdigest()
    if got != SHA256:
        sys.exit(f"judge-comparison.csv: sha256 {got} is not the pinned {SHA256}; stop and look.")
    with data.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = CACHE / "results.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"id": f"jbb-{int(r['Index']):03d}", "input": r["prompt"],
                                "output": r["target_response"], "verdict": grade(r["gpt4_cf"])},
                               ensure_ascii=False) + "\n")
    judge = [grade(r["gpt4_cf"]) for r in rows]
    print(f"{len(rows)} rows: GPT-4 passed {judge.count('pass')} and failed {judge.count('fail')}")
    print("wrote", out.relative_to(HERE))


if __name__ == "__main__":
    main()
