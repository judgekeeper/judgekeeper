"""LLMBar (Zeng et al., ICLR 2024): pairwise instruction-following items with gold labels.

Downloads the Natural and Adversarial subsets from the public GitHub repository and converts
them to the judgekeeper anchor format, with `slice` set to the subset name. The data is not
committed to this repository.

    python -m judgekeeper.datasets.llmbar --out anchors/llmbar.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Pinned to a commit so the files cannot change under us (main as of 2024-07-08).
BASE_URL = ("https://raw.githubusercontent.com/princeton-nlp/LLMBar/"
            "900616bff90b6c6c8e1681f7d079250637c55992/Dataset/LLMBar")
SUBSETS = (
    "Natural",
    "Adversarial/Neighbor",
    "Adversarial/GPTInst",
    "Adversarial/GPTOut",
    "Adversarial/Manual",
)


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def convert(raw: list[dict], subset: str) -> list[dict]:
    """LLMBar rows {input, output_1, output_2, label in {1,2}} -> anchor items."""
    prefix = "llmbar-" + subset.lower().replace("/", "-")
    items = []
    for n, row in enumerate(raw):
        if row.get("label") not in (1, 2):
            raise ValueError(f"{subset} row {n}: label {row.get('label')!r} not in (1, 2)")
        items.append({
            "id": f"{prefix}-{n:04d}",
            "input": row["input"],
            "output_a": row["output_1"],
            "output_b": row["output_2"],
            "human_label": "A" if row["label"] == 1 else "B",
            "slice": subset,
        })
    return items


def load(subsets: tuple[str, ...] = SUBSETS) -> list[dict]:
    items = []
    for subset in subsets:
        raw = json.loads(_fetch(f"{BASE_URL}/{subset}/dataset.json"))
        items.extend(convert(raw, subset))
    return items


def write_anchors(path: str | Path, subsets: tuple[str, ...] = SUBSETS) -> int:
    items = load(subsets)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8"
    )
    return len(items)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download LLMBar and write a judgekeeper anchor set.")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    n = write_anchors(args.out)
    print(f"wrote {n} items to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
