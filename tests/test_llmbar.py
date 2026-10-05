import json
import re

from judgekeeper.anchors import load_anchors
from judgekeeper.datasets import llmbar


def fake_fetch(url):
    subset = url.split("/LLMBar/")[1].rsplit("/", 1)[0]
    rows = [
        {"input": f"{subset} q1", "output_1": "one", "output_2": "two", "label": 1},
        {"input": f"{subset} q2", "output_1": "uno", "output_2": "dos", "label": 2},
    ]
    return json.dumps(rows).encode()


def test_convert_maps_labels_and_slices():
    raw = [{"input": "q", "output_1": "x", "output_2": "y", "label": 2}]
    items = llmbar.convert(raw, "Adversarial/GPTInst")
    assert items == [
        {
            "id": "llmbar-adversarial-gptinst-0000",
            "input": "q",
            "output_a": "x",
            "output_b": "y",
            "human_label": "B",
            "slice": "Adversarial/GPTInst",
        }
    ]


def test_load_covers_natural_and_adversarial(monkeypatch):
    monkeypatch.setattr(llmbar, "_fetch", fake_fetch)
    items = llmbar.load()
    slices = {i["slice"] for i in items}
    assert slices == set(llmbar.SUBSETS)
    assert "Natural" in slices and any(s.startswith("Adversarial/") for s in slices)
    assert len(items) == 2 * len(llmbar.SUBSETS)
    assert len({i["id"] for i in items}) == len(items)


def test_write_anchors_is_valid_anchor_file(monkeypatch, tmp_path):
    monkeypatch.setattr(llmbar, "_fetch", fake_fetch)
    out = tmp_path / "llmbar.jsonl"
    assert llmbar.main(["--out", str(out)]) == 0
    items = load_anchors(out)
    assert len(items) == 2 * len(llmbar.SUBSETS)
    assert {i["human_label"] for i in items} == {"A", "B"}


def test_bad_label_rejected():
    import pytest

    with pytest.raises(ValueError):
        llmbar.convert([{"input": "q", "output_1": "x", "output_2": "y", "label": 3}], "Natural")


def test_download_url_is_pinned_to_a_commit():
    """The upstream main branch can change under us; a commit hash cannot."""
    from judgekeeper.datasets import llmbar
    assert re.search(r"/LLMBar/[0-9a-f]{40}/", llmbar.BASE_URL), llmbar.BASE_URL
    assert "/main/" not in llmbar.BASE_URL
