"""Download JailbreakBench's judge-comparison set and write the rows for the Claude run.

    python3 -I load.py

Uses the same source, revision and SHA-256 as ../jailbreakbench/load.py (read from that file,
so the two cannot drift): the Hugging Face dataset JailbreakBench/JBB-Behaviors (MIT license),
file data/judge-comparison.csv. Chao et al., "JailbreakBench: An Open Robustness Benchmark for
Jailbreaking Large Language Models", arXiv 2404.01318.

Writes, in cache/ next to this file (its .gitignore is `*`: the requests and responses are
harmful, so never commit them):
  judge-comparison.csv   the download
  rows.jsonl             one line per row: id (jbb-NNN, as in ../jailbreakbench), goal (the
                         harmful behaviour, the paper's REQUEST), response, the experts'
                         majority label (human_majority: 0, not jailbroken = pass; 1 = fail)
                         and GPT-4's grade (gpt4_cf), for the comparison line in the report.
All 300 rows are used; there is no sample.
"""

import csv
import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True  # the loader below is read, not installed
HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
_spec = importlib.util.spec_from_file_location("jbb_load", HERE.parent / "jailbreakbench" / "load.py")
jbb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jbb)


def grade(cell: str) -> str:
    return jbb.grade(cell)


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    gitignore = CACHE / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    data = CACHE / "judge-comparison.csv"
    if not data.exists():
        print(f"downloading judge-comparison.csv from JailbreakBench/JBB-Behaviors@{jbb.REVISION[:7]}")
        with urllib.request.urlopen(jbb.URL, timeout=120) as r:
            body = r.read()
        part = data.with_suffix(".part")
        part.write_bytes(body)
        part.replace(data)
        print(jbb.NOTICE)
    got = hashlib.sha256(data.read_bytes()).hexdigest()
    if got != jbb.SHA256:
        sys.exit(f"judge-comparison.csv: sha256 {got} is not the pinned {jbb.SHA256}; stop and look.")
    with data.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 300:
        sys.exit(f"{len(rows)} rows, not 300; stop and look.")
    out = CACHE / "rows.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"id": f"jbb-{int(r['Index']):03d}", "goal": r["goal"],
                                "response": r["target_response"],
                                "expert": grade(r["human_majority"]), "gpt4": grade(r["gpt4_cf"])},
                               ensure_ascii=False) + "\n")
    experts = [grade(r["human_majority"]) for r in rows]
    print(f"{len(rows)} rows: the experts passed {experts.count('pass')} and failed "
          f"{experts.count('fail')}")
    print("wrote", out.relative_to(HERE))


if __name__ == "__main__":
    main()
