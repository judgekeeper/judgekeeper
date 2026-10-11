"""Anchor set format, canonical hashing and the manifest that seals it.

An anchor set is JSONL, one item per line. Every item has `id`, `input` and `human_label`.
Pairwise items add `output_a`, `output_b` and use labels A/B. Single-output items add `output`
and use labels pass/fail. `slice` and `notes` are optional.

The hash is sha256 over canonical JSON (sorted keys, no whitespace) of the items sorted by id,
so it is stable under key order, whitespace and line order, and changes on any content change.

An anchor set is sealed once: its manifest (`<name>.manifest.json`) records the hash. `judge`
and `validate` seal a set that has no manifest yet (`seal_new`); after that, a changed file
is a hash mismatch, never sealed again.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from judgekeeper.textio import jsonl_lines, read_utf8, write_replacing

PAIRWISE = "pairwise"
SINGLE = "single"

LABELS = {PAIRWISE: ("A", "B"), SINGLE: ("pass", "fail")}
# The label treated as "positive" for TPR/TNR.
POSITIVE = {PAIRWISE: "A", SINGLE: "pass"}
NEGATIVE = {PAIRWISE: "B", SINGLE: "fail"}


class AnchorError(Exception):
    """The anchor set or its manifest is malformed or missing."""


class AnchorHashMismatch(AnchorError):
    """The anchor set no longer matches its frozen manifest."""


def item_kind(item: dict) -> str:
    if "output_a" in item or "output_b" in item:
        return PAIRWISE
    return SINGLE


def _validate_item(item: object, where: str) -> str:
    if not isinstance(item, dict):
        raise AnchorError(f"{where}: item must be a JSON object")
    for key in ("id", "input", "human_label"):
        if key not in item:
            raise AnchorError(f"{where}: missing required field '{key}'")
    if not isinstance(item["id"], str) or not item["id"]:
        raise AnchorError(f"{where}: 'id' must be a non-empty string")
    kind = item_kind(item)
    required = ("output_a", "output_b") if kind == PAIRWISE else ("output",)
    for key in required:
        if key not in item:
            raise AnchorError(f"{where}: {kind} item missing '{key}'")
    if item["human_label"] not in LABELS[kind]:
        raise AnchorError(
            f"{where}: human_label {item['human_label']!r} not in {LABELS[kind]} for {kind} item"
        )
    if "slice" in item and not isinstance(item["slice"], str):
        raise AnchorError(f"{where}: 'slice' must be a string")
    return kind


def validate_items(items: list[dict]) -> str:
    """Check every item and return the anchor set kind (pairwise or single)."""
    if not items:
        raise AnchorError("anchor set is empty")
    kinds = set()
    seen = set()
    for n, item in enumerate(items, 1):
        kinds.add(_validate_item(item, f"item {n}"))
        if item["id"] in seen:
            raise AnchorError(f"duplicate id {item['id']!r}")
        seen.add(item["id"])
    if len(kinds) > 1:
        raise AnchorError("anchor set mixes pairwise and single-output items")
    return kinds.pop()


def load_anchors(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise AnchorError(f"anchor file not found: {path}")
    items = []
    for n, line in enumerate(jsonl_lines(read_utf8(path, AnchorError)), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise AnchorError(f"{path}: line {n}: invalid JSON ({e.msg})") from None
    validate_items(items)
    return items


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(items: list[dict]) -> str:
    ordered = sorted(items, key=lambda i: str(i.get("id")))
    blob = "\n".join(canonical_json(i) for i in ordered)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def manifest_path_for(path: str | Path) -> Path:
    return Path(path).with_suffix(".manifest.json")


def build_manifest(items: list[dict]) -> dict:
    kind = validate_items(items)
    labels = Counter(i["human_label"] for i in items)
    slices = Counter(i["slice"] for i in items if "slice" in i)
    return {
        "item_count": len(items),
        "kind": kind,
        "label_distribution": dict(sorted(labels.items())),
        "slice_counts": dict(sorted(slices.items())),
        "sha256": canonical_hash(items),
    }


def freeze(path: str | Path) -> dict:
    items = load_anchors(path)
    manifest = build_manifest(items)
    write_replacing(manifest_path_for(path), json.dumps(manifest, indent=2) + "\n", newline="\n")
    return manifest


def seal_new(path: str | Path) -> dict | None:
    """Seal an anchor set that has no manifest yet and return the manifest; None when it
    already has one (it is then checked, never rewritten)."""
    if manifest_path_for(path).is_file():
        return None
    return freeze(path)


def load_verified(path: str | Path) -> tuple[list[dict], dict]:
    """Load an anchor set and verify it against its manifest. Raises on mismatch."""
    mpath = manifest_path_for(path)
    items = load_anchors(path)
    if not mpath.is_file():
        raise AnchorError(f"no manifest at {mpath}: {path} is not sealed yet; `judgekeeper "
                          "judge` seals a new anchor set on first use")
    try:
        manifest = json.loads(read_utf8(mpath, AnchorError))
    except json.JSONDecodeError:
        raise AnchorError(f"manifest {mpath} is not valid JSON") from None
    actual = canonical_hash(items)
    if manifest.get("sha256") != actual:
        raise AnchorHashMismatch(
            f"anchor set {path} does not match {mpath}: "
            f"manifest sha256 {manifest.get('sha256')}, actual {actual}. "
            "The anchor set changed after it was frozen."
        )
    return items, manifest
