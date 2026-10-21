"""Download RAGTruth's news-summary test rows for the RAGTruth example report.

Source: the authors' GitHub repo, ParticleMedia/RAGTruth (MIT), pinned to one commit so the
data cannot change under us. Files land in cache/raw/ (cache/ is ignored by git). The files are
read as JSON only; nothing in them is run. Run with: python3 -I load.py

Kept: split == "test" and task_type == "Summary" (CNN/DM and "Recent News"), one row per
model response. Label: Fail when the annotators marked at least one hallucination span in the
response (the paper's response-level label), else Pass.

Writes cache/summary-test.jsonl (row text: never commit it) and prints the counts.
"""

import hashlib
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "cache" / "raw"
OUT = HERE / "cache" / "summary-test.jsonl"
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
            if r["split"] != "test" or s["task_type"] != "Summary":
                continue
            spans = r["labels"]
            rows.append({
                "id": r["id"], "source_id": r["source_id"], "source": s["source"],
                "model": r["model"], "label": "fail" if spans else "pass",
                "span_types": sorted({x["label_type"] for x in spans}),
                "only_implicit_true": bool(spans) and all(x.get("implicit_true") for x in spans),
                "article": s["source_info"], "summary": r["response"],
            })
    if len({r["id"] for r in rows}) != len(rows) or len({r["summary"] for r in rows}) != len(rows):
        sys.exit("ids or summary texts repeat; the marks are matched by summary text, so stop.")
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    labels = Counter(r["label"] for r in rows)
    print(f"news-summary test rows: {len(rows)} (Pass {labels['pass']}, Fail {labels['fail']}), "
          f"from {len({r['source_id'] for r in rows})} articles")
    print(f"{'model':24} {'Pass':>5} {'Fail':>5}")
    for model in sorted({r["model"] for r in rows}):
        c = Counter(r["label"] for r in rows if r["model"] == model)
        print(f"{model:24} {c['pass']:>5} {c['fail']:>5}")
    by_source = Counter((r["source"], r["label"]) for r in rows)
    print("by source:", ", ".join(f"{s} {lab} {n}" for (s, lab), n in sorted(by_source.items())))
    print("Fail rows whose every span is 'implicit_true' (true, but not in the article):",
          sum(r["only_implicit_true"] for r in rows))
    print("wrote", OUT.relative_to(HERE))
    if first:
        print(NOTICE)


if __name__ == "__main__":
    main()
