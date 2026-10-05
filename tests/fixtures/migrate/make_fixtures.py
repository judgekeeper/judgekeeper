"""Write the migrate/attribute replay fixtures. Run from the repo root after editing a table:

    python tests/fixtures/migrate/make_fixtures.py

Ten pairwise items. Human labels: i01-i05 A, i06-i10 B. Slices: easy = i01 i02 i03 i06 i07 i08,
hard = i04 i05 i09 i10. Human labels are balanced 5/5, so for any judge on the full set chance
agreement is 0.5 and kappa = 2 * accuracy - 1. BA verdicts equal AB verdicts (no position bias).

Verdict patterns, one letter per item i01..i10:
    H  AAAAA BBBBB   matches every human label           kappa 1.0
    X  AAAAB BBBBA   wrong on i05 and i10               kappa 0.6
    N  AAABA BBBAB   wrong on i04 and i09 instead       kappa 0.6
"""

from __future__ import annotations

import json
from pathlib import Path

from judgekeeper.anchors import build_manifest

ROOT = Path(__file__).parent

HUMAN = "AAAAABBBBB"
EASY = {1, 2, 3, 6, 7, 8}
H = "AAAAABBBBB"
X = "AAAABBBBBA"
N = "AAABABBBAB"


def flip(pattern: str, item: int) -> str:
    """Flip item number `item` (1-based) between A and B."""
    k = item - 1
    return pattern[:k] + ("B" if pattern[k] == "A" else "A") + pattern[k + 1:]


# name: (model, snapshot, created_at, [pattern per run])
RUN_DIRS = {
    # migrate
    "old": ("judge-old", "judge-old", "2026-10-01T00:00:00Z", [X, X, X]),
    "old-perfect": ("judge-old", "judge-old", "2026-10-01T00:00:00Z", [H, H, H]),
    "new-equivalent": ("judge-new", "judge-new", "2026-10-08T00:00:00Z",
                       [flip(X, 5), flip(X, 5), flip(X, 3)]),
    "new-better": ("judge-new", "judge-new", "2026-10-08T00:00:00Z", [H, H, H]),
    "new-worse": ("judge-new", "judge-new", "2026-10-08T00:00:00Z", [X, X, X]),
    "new-different": ("judge-new", "judge-new", "2026-10-08T00:00:00Z", [N, N, N]),
    # attribute: the old judge re-run a week later
    "old-rerun": ("judge-old", "judge-old", "2026-10-08T00:00:00Z", [X, X, X]),
    "old-noisy": ("judge-old", "judge-old", "2026-10-08T00:00:00Z",
                  [flip(X, 5), flip(X, 5), X]),
    "old-drifted": ("judge-old", "judge-old", "2026-10-08T00:00:00Z", [N, N, N]),
    "old-new-snapshot": ("judge-old", "judge-old-2027", "2026-10-08T00:00:00Z", [H, H, H]),
}


def anchors() -> list[dict]:
    return [
        {"id": f"i{n:02d}", "input": f"instruction {n}", "output_a": f"a{n}",
         "output_b": f"b{n}", "human_label": HUMAN[n - 1],
         "slice": "easy" if n in EASY else "hard"}
        for n in range(1, 11)
    ]


def fingerprint(model: str, snapshot: str, created_at: str) -> dict:
    return {"provider": "anthropic", "model": model, "snapshot": snapshot,
            "prompt_hash": "0" * 63 + "1", "rubric_version": "pairwise-v1",
            "temperature": 0.0, "created_at": created_at, "endpoint": None}


def main() -> None:
    items = anchors()
    (ROOT / "anchors.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
    manifest = build_manifest(items)
    (ROOT / "anchors.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name, (model, snapshot, created_at, patterns) in RUN_DIRS.items():
        d = ROOT / name
        d.mkdir(exist_ok=True)
        for old in d.glob("*.jsonl"):
            old.unlink()
        fp = fingerprint(model, snapshot, created_at)
        for run, pattern in enumerate(patterns, 1):
            rows = [{"type": "header", "run": run, "anchors_sha256": manifest["sha256"],
                     "fingerprint": fp}]
            for item, verdict in zip(items, pattern, strict=True):
                rows.append({"type": "judgment", "id": item["id"], "verdict": verdict,
                             "raw_score": None, "rationale": f"{name} run{run} {item['id']} AB",
                             "verdict_ba": verdict, "raw_score_ba": None,
                             "rationale_ba": f"{name} run{run} {item['id']} BA",
                             "fingerprint": fp})
            (d / f"run-{run:02d}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


if __name__ == "__main__":
    main()
