"""Shared helpers for the run scripts. Nothing here prints or stores a key."""

import csv
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

# Everything the scripts download or write (datasets, raw answers, graded runs with question
# and answer text) goes here, never into the repository. Set NOISE_WORK to change it.
WORK = Path(os.environ.get("NOISE_WORK", "noise-work")).resolve()


def need(name: str, what: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Set {name} to {what} first, then run this again.")
    return value


def client():
    """An API client. The key is read from ANTHROPIC_API_KEY and nothing else."""
    need("ANTHROPIC_API_KEY", "your API key")
    try:
        import anthropic
    except ImportError:
        sys.exit("Install the API library first: pip install anthropic")
    return anthropic.Anthropic(max_retries=8)


def download(url: str, dest: Path, sha256: str | None = None) -> str:
    """Download a public dataset file once. Returns its sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=120) as r:
            dest.write_bytes(r.read())
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if sha256 and digest != sha256:
        sys.exit(f"{dest.name} does not match the pinned sha256; stop and look.")
    return digest


def read_parquet(path: Path) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        sys.exit("Install the table reader first: pip install pyarrow")
    return pq.read_table(path).to_pylist()


def write_round(folder: str, name: str, rows: list[dict], fields: list[str]) -> None:
    """Write one graded run as WORK/rounds/<folder>/<name>.csv and print its pass rate."""
    out = WORK / "rounds" / folder
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.csv"
    part = path.with_suffix(".part")
    with part.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    part.replace(path)
    passed = sum(r["verdict"] == "pass" for r in rows)
    print(f"{folder}/{name}: {passed} of {len(rows)} pass ({100 * passed / len(rows):.1f}%)",
          flush=True)
