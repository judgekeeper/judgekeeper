"""Anchor sets: the content hash, the manifest `freeze()` writes, and the checks on loading."""

import json

import pytest

from judgekeeper.anchors import (
    AnchorError,
    AnchorHashMismatch,
    canonical_hash,
    freeze,
    load_anchors,
    load_verified,
    manifest_path_for,
)

ITEMS = [
    {"id": "a1", "input": "q1", "output_a": "x", "output_b": "y", "human_label": "A", "slice": "s1"},
    {"id": "a2", "input": "q2", "output_a": "x", "output_b": "y", "human_label": "B", "slice": "s1"},
    {"id": "a3", "input": "q3", "output_a": "x", "output_b": "y", "human_label": "B", "slice": "s2"},
]


def write_jsonl(path, rows, **dump_kwargs):
    path.write_text("\n".join(json.dumps(r, **dump_kwargs) for r in rows) + "\n", encoding="utf-8")
    return path


def test_hash_stable_under_key_reordering_and_whitespace(tmp_path):
    base = canonical_hash(ITEMS)
    reordered = [dict(reversed(list(item.items()))) for item in ITEMS]
    assert canonical_hash(reordered) == base

    p = write_jsonl(tmp_path / "a.jsonl", reordered, indent=None, separators=(" , ", " :  "))
    p.write_text("\n\n" + p.read_text(encoding="utf-8").replace("\n", "\n   \n"), encoding="utf-8")
    assert canonical_hash(load_anchors(p)) == base


def test_hash_stable_under_line_order():
    assert canonical_hash(list(reversed(ITEMS))) == canonical_hash(ITEMS)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: items[0].update(input="q1 "),
        lambda items: items[1].update(human_label="A"),
        lambda items: items[2].update(slice="s3"),
        lambda items: items[0].update(notes="new field"),
        lambda items: items.pop(),
    ],
)
def test_hash_changes_on_any_content_change(mutate):
    items = [dict(i) for i in ITEMS]
    mutate(items)
    assert canonical_hash(items) != canonical_hash(ITEMS)


def test_freeze_writes_manifest(tmp_path):
    p = write_jsonl(tmp_path / "anchors.jsonl", ITEMS)
    manifest = freeze(p)
    assert manifest_path_for(p) == tmp_path / "anchors.manifest.json"
    on_disk = json.loads((tmp_path / "anchors.manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest["item_count"] == 3
    assert manifest["kind"] == "pairwise"
    assert manifest["label_distribution"] == {"A": 1, "B": 2}
    assert manifest["slice_counts"] == {"s1": 2, "s2": 1}
    assert manifest["sha256"] == canonical_hash(ITEMS)


def test_load_verified_refuses_on_mismatch(tmp_path):
    p = write_jsonl(tmp_path / "anchors.jsonl", ITEMS)
    freeze(p)
    assert len(load_verified(p)[0]) == 3
    changed = [dict(i) for i in ITEMS]
    changed[0]["human_label"] = "B"
    write_jsonl(p, changed)
    with pytest.raises(AnchorHashMismatch):
        load_verified(p)


def test_load_verified_requires_manifest(tmp_path):
    p = write_jsonl(tmp_path / "anchors.jsonl", ITEMS)
    with pytest.raises(AnchorError, match="not sealed yet"):
        load_verified(p)


@pytest.mark.parametrize(
    "bad",
    [
        [{"input": "q", "output": "o", "human_label": "pass"}],
        [{"id": "x", "output": "o", "human_label": "pass"}],
        [{"id": "x", "input": "q", "output": "o", "human_label": "A"}],
        [{"id": "x", "input": "q", "output_a": "o", "output_b": "p", "human_label": "pass"}],
        [{"id": "x", "input": "q", "human_label": "pass"}],
        [
            {"id": "x", "input": "q", "output": "o", "human_label": "pass"},
            {"id": "x", "input": "q", "output": "o", "human_label": "fail"},
        ],
        [
            {"id": "x", "input": "q", "output": "o", "human_label": "pass"},
            {"id": "y", "input": "q", "output_a": "o", "output_b": "p", "human_label": "A"},
        ],
    ],
)
def test_invalid_anchor_sets_rejected(tmp_path, bad):
    p = write_jsonl(tmp_path / "anchors.jsonl", bad)
    with pytest.raises(AnchorError):
        load_anchors(p)


def test_invalid_json_line_rejected(tmp_path):
    p = tmp_path / "anchors.jsonl"
    p.write_text('{"id": "x"\n', encoding="utf-8")
    with pytest.raises(AnchorError, match="line 1"):
        load_anchors(p)


def test_an_anchor_set_and_its_manifest_have_the_same_bytes_on_every_system(tmp_path):
    """\\n line endings, also on Windows, so a committed anchor set compares byte for byte."""
    from judgekeeper.table import write_anchor_file

    path = tmp_path / "anchors.jsonl"
    write_anchor_file(path, [{"id": "a", "input": "q", "output": "x", "human_label": "pass"},
                             {"id": "b", "input": "q", "output": "y", "human_label": "fail"}])
    for written in (path, tmp_path / "anchors.manifest.json"):
        assert b"\r" not in written.read_bytes()
