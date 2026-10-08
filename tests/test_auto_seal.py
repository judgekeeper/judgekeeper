"""`judge` and `validate` seal an anchor set that has no manifest yet, once, and say so in one
line; a sealed set that changed still stops with exit code 3. `[attribute]` in
judgekeeper.toml is an unknown table like any other."""

import json

import pytest

from judgekeeper import check_judge
from judgekeeper.anchors import canonical_hash, load_anchors
from judgekeeper.cli import main
from tests.judges_for_tests import keyword_judge

JUDGE = ["--callable", "tests.judges_for_tests:keyword_judge"]


def _anchors(tmp_path, n=10):
    path = tmp_path / "anchors.jsonl"
    items = [{"id": f"s{i}", "input": f"q{i}", "output": ("good " if i % 2 == 0 else "bad ")
              + str(i), "human_label": "pass" if i % 2 == 0 else "fail"} for i in range(n)]
    path.write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    return path


def _sealed_line(anchors, n):
    sha = canonical_hash(load_anchors(anchors))
    return (f"Sealed {anchors}: {n} item{'' if n == 1 else 's'} (sha256 {sha[:12]}...). "
            f"Commit {anchors.with_suffix('.manifest.json')} with it.")


def _judge(anchors, out):
    return main(["judge", str(anchors), *JUDGE, "--runs", "3", "--out", str(out)])


def test_judge_seals_a_new_anchor_set_once_and_says_so(tmp_path, capsys):
    anchors = _anchors(tmp_path)
    manifest = tmp_path / "anchors.manifest.json"
    assert _judge(anchors, tmp_path / "runs") == 0
    assert capsys.readouterr().out.splitlines()[0] == _sealed_line(anchors, 10)
    sealed = json.loads(manifest.read_text(encoding="utf-8"))
    assert sealed["item_count"] == 10 and sealed["sha256"] == canonical_hash(
        load_anchors(anchors))
    assert _judge(anchors, tmp_path / "again") == 0
    assert "Sealed" not in capsys.readouterr().out
    assert json.loads(manifest.read_text(encoding="utf-8")) == sealed


def test_validate_seals_a_new_anchor_set_once_and_says_so(pairwise_dir, tmp_path, capsys):
    anchors, runs = pairwise_dir / "anchors.jsonl", pairwise_dir / "runs"
    manifest = pairwise_dir / "anchors.manifest.json"
    before = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.unlink()
    assert main(["validate", str(anchors), str(runs), "--out", str(tmp_path / "r")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == _sealed_line(anchors, 8)
    assert sum("Sealed" in line for line in out) == 1
    assert json.loads(manifest.read_text(encoding="utf-8"))["sha256"] == before["sha256"]
    assert main(["validate", str(anchors), str(runs), "--out", str(tmp_path / "r2")]) == 0
    assert "Sealed" not in capsys.readouterr().out


def test_one_item_is_said_in_the_singular(tmp_path, capsys):
    anchors = _anchors(tmp_path, n=1)
    assert _judge(anchors, tmp_path / "runs") == 0
    assert capsys.readouterr().out.splitlines()[0] == _sealed_line(anchors, 1)


@pytest.mark.parametrize("command", ["judge", "validate"])
def test_a_sealed_set_that_changed_still_exits_3(tmp_path, capsys, command):
    anchors = _anchors(tmp_path)
    assert _judge(anchors, tmp_path / "runs") == 0
    manifest = (tmp_path / "anchors.manifest.json").read_text(encoding="utf-8")
    anchors.write_text(anchors.read_text(encoding="utf-8").replace('"pass"', '"fail"', 1),
                       encoding="utf-8")
    capsys.readouterr()
    argv = {"judge": ["judge", str(anchors), *JUDGE, "--out", str(tmp_path / "r2")],
            "validate": ["validate", str(anchors), str(tmp_path / "runs"),
                         "--out", str(tmp_path / "rep")]}[command]
    assert main(argv) == 3
    captured = capsys.readouterr()
    assert "Sealed" not in captured.out
    assert "changed after it was frozen" in captured.err
    assert (tmp_path / "anchors.manifest.json").read_text(encoding="utf-8") == manifest


def test_a_file_that_is_not_an_anchor_set_is_not_sealed(tmp_path, capsys):
    anchors = tmp_path / "anchors.jsonl"
    anchors.write_text('{"id": "a", "input": "q"}\n', encoding="utf-8")
    assert _judge(anchors, tmp_path / "runs") == 2
    assert "human_label" in capsys.readouterr().err
    assert not (tmp_path / "anchors.manifest.json").exists()


def test_check_judge_seals_a_new_anchor_set_too(tmp_path):
    anchors = _anchors(tmp_path)
    report = check_judge(keyword_judge, anchors, runs=3, out=tmp_path / "out")
    assert (tmp_path / "anchors.manifest.json").is_file()
    assert report["anchors"]["sha256"] == canonical_hash(load_anchors(anchors))


def test_an_attribute_table_is_an_unknown_table(tmp_path, pairwise_dir, capsys):
    config = tmp_path / "judgekeeper.toml"
    config.write_text("[attribute]\nmin_band = 0.02\n", encoding="utf-8")
    report = tmp_path / "rep"
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(report)]) == 0
    capsys.readouterr()
    for argv in (["gate", str(report / "report.json"), "--config", str(config)],
                 ["migrate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                  str(pairwise_dir / "runs"), "--out", str(tmp_path / "m"), "--config",
                  str(config)]):
        assert main(argv) == 2
        err = capsys.readouterr().err
        assert "unknown table or key 'attribute'" in err
        assert "allowed: [gate], [migrate], [start]" in err
