"""Download RAGTruth's question-answering test rows and draw the sample for this report.

Source: the authors' GitHub repo, ParticleMedia/RAGTruth (MIT), pinned to the same commit as
../ragtruth/load.py. Files land in cache/raw/ (cache/ is ignored by git). The files are read as
JSON only; nothing in them is run. Run with: python3 -I load.py

Kept: split == "test" and task_type == "QA" (MS MARCO questions with three passages), one row
per model response. Label: Fail when the annotators marked at least one hallucination span in
the response (the paper's response-level label), else Pass. Answer texts that occur more than
once are left out of the pool, because the marks are matched to answers by their text.

Draws 100 Pass and 100 Fail with a fixed seed. If sample-ids.json exists, the new draw must
match it exactly; if it does not, the file is written. Writes cache/test.jsonl (row text:
never commit it) and prints the counts.
"""

import hashlib
import json
import random
import sys
import urllib.request
from collections import Counter
from pathlib import Path

TASK = "QA"
SEED = 20261030
PER_LABEL = 100

HERE = Path(__file__).resolve().parent
RAW = HERE / "cache" / "raw"
OUT = HERE / "cache" / "test.jsonl"
COMMIT = "c103204b9ce28d6bbad859304bf30de72b8ed8fe"  # main on 2026-10-17 (last change 2024-12-02)
URL = f"https://raw.githubusercontent.com/ParticleMedia/RAGTruth/{COMMIT}/dataset/{{name}}"
SHA256 = {  # the files as downloaded on 2026-10-17
    "response.jsonl": "e4c2e4ac24fff676d8984cc61c35d791612fadc58015335d97dd632375e18073",
    "source_info.jsonl": "0dffc26ea9f3c1c3d7c7e8336b56ef1646e3cec876edffcca3c9c624d12d578b",
}
NOTICE = """RAGTruth is MIT licensed, Copyright (c) 2023 Particle Media.
Cite: Niu et al., "RAGTruth: A Hallucination Corpus for Developing Trustworthy
Retrieval-Augmented Language Models", ACL 2024, arXiv 2401.00396.
The license text is in THIRD_PARTY_NOTICES.md at the repository's root."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(name: str) -> Path:
    path = RAW / name
    if not path.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} from GitHub ParticleMedia/RAGTruth@{COMMIT[:7]}")
        with urllib.request.urlopen(URL.format(name=name), timeout=120) as r:
            data = r.read()
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    got = sha256(path)
    if got != SHA256[name]:
        sys.exit(f"{name}: sha256 {got} is not the pinned {SHA256[name]}; stop and look.")
    return path


def context(info: dict) -> dict:
    """What the LLM-as-a-judge is shown next to the answer."""
    return {"question": info["question"], "passages": info["passages"]}


def main() -> None:
    gitignore = HERE / "cache" / ".gitignore"
    gitignore.parent.mkdir(exist_ok=True)
    if not gitignore.exists():
        gitignore.write_text("*\n")
    first = not all((RAW / name).exists() for name in SHA256)
    sources = {}
    with fetch("source_info.jsonl").open(encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            sources[s["source_id"]] = s
    rows = []
    with fetch("response.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            s = sources[r["source_id"]]
            if r["split"] != "test" or s["task_type"] != TASK:
                continue
            spans = r["labels"]
            rows.append({
                "id": r["id"], "source_id": r["source_id"], "source": s["source"],
                "model": r["model"], "label": "fail" if spans else "pass",
                "span_types": sorted({x["label_type"] for x in spans}),
                **context(s["source_info"]), "answer": r["response"],
            })
    if len({r["id"] for r in rows}) != len(rows):
        sys.exit("ids repeat; stop.")
    repeated = {t for t, n in Counter(r["answer"] for r in rows).items() if n > 1}
    pool = [r for r in rows if r["answer"] not in repeated]
    with OUT.open("w", encoding="utf-8") as f:
        for r in pool:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rng = random.Random(SEED)
    picked = []
    for label in ("pass", "fail"):
        group = sorted((r for r in pool if r["label"] == label), key=lambda r: int(r["id"]))
        picked += rng.sample(group, PER_LABEL)
    picked.sort(key=lambda r: int(r["id"]))
    sample = {
        "dataset": "RAGTruth (github.com/ParticleMedia/RAGTruth, dataset/)",
        "commit": COMMIT,
        "sha256": SHA256,
        "filter": f"split == test, task_type == {TASK}; Fail = at least one annotated span; "
                  "answer texts that occur more than once are left out of the pool",
        "seed": SEED,
        "method": "random.Random(seed).sample per label, Pass first, each group sorted by id",
        "counts": {
            "test_rows": len(rows),
            "left_out_repeated_text": len(rows) - len(pool),
            "pool": dict(Counter(r["label"] for r in pool)),
            "sample": dict(Counter(r["label"] for r in picked)),
            "sample_by_model": {m: dict(Counter(r["label"] for r in picked if r["model"] == m))
                                for m in sorted({r["model"] for r in picked})},
            "sample_sources": len({r["source_id"] for r in picked}),
        },
        "ids": {label: [r["id"] for r in picked if r["label"] == label]
                for label in ("pass", "fail")},
    }
    text = json.dumps(sample, indent=1) + "\n"
    path = HERE / "sample-ids.json"
    if path.exists():
        if path.read_text() != text:
            sys.exit("sample-ids.json is frozen and this draw is different; stop and look.")
        print("sample-ids.json matches the draw")
    else:
        path.write_text(text)
        print("wrote sample-ids.json")

    print(f"{TASK} test rows: {len(rows)} ({len(rows) - len(pool)} left out for repeated text); "
          f"pool Pass {sample['counts']['pool']['pass']}, Fail {sample['counts']['pool']['fail']}")
    print(f"{'model':24} {'Pass':>5} {'Fail':>5}   (the 200 sampled)")
    for model, c in sample["counts"]["sample_by_model"].items():
        print(f"{model:24} {c.get('pass', 0):>5} {c.get('fail', 0):>5}")
    if first:
        print(NOTICE)


if __name__ == "__main__":
    main()
