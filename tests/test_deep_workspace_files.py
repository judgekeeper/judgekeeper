"""A file in .judgekeeper/ nested far too deep (a repo can ship that folder) is read as a
damaged file is, on every Python version: never as a problem judgekeeper didn't expect."""

from __future__ import annotations

import shutil

import pytest

from judgekeeper.cli import main
from tests.test_check import _marked

DEEP = '{"x": ' + "[" * 200_000 + "]" * 200_000 + "}"
DAMAGED = '{"x": [1, 2'

CASES = [("judge.json", []), ("start.json", []), ("marks.jsonl", []), ("marks.jsonl", ["mark"]),
         ("pool.jsonl", ["mark"]), ("fix/split.json", ["fix"]), ("history.jsonl", ["check"])]


@pytest.fixture(scope="module")
def marked(tmp_path_factory):
    root = tmp_path_factory.mktemp("marked") / "docs-qa"
    root.mkdir()
    _marked(root)
    return root


def _run(marked, tmp_path, monkeypatch, capsys, rel: str, text: str, argv: list) -> tuple:
    root = tmp_path / ("deep" if text is DEEP else "damaged")
    shutil.copytree(marked, root)
    target = root / ".judgekeeper" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    monkeypatch.chdir(root)
    code = main([*argv, "--no-browser"] if argv in ([], ["mark"]) else argv)
    return code, " ".join("".join(capsys.readouterr()).split())


@pytest.mark.parametrize(("rel", "argv"), CASES)
def test_a_deep_file_in_the_workspace_is_read_as_a_damaged_one(marked, tmp_path, monkeypatch,
                                                                capsys, rel, argv):
    code, out = _run(marked, tmp_path, monkeypatch, capsys, rel, DEEP, argv)
    assert "didn't expect" not in out, out
    damaged_code, damaged_out = _run(marked, tmp_path, monkeypatch, capsys, rel, DAMAGED, argv)
    assert "didn't expect" not in damaged_out, damaged_out
    assert code == damaged_code, (out, damaged_out)


def test_a_damaged_pool_is_left_behind_by_starting_over(marked, tmp_path, monkeypatch, capsys):
    code, out = _run(marked, tmp_path, monkeypatch, capsys, "pool.jsonl", DEEP, ["mark"])
    assert code == 2 and "Next: run `judgekeeper --new` to start over" in out, out
    code = main(["--new", "--yes", "--no-browser"])
    out = " ".join("".join(capsys.readouterr()).split())
    assert code == 0 and "Step 2 of 5: Mark" in out, out
    assert list((tmp_path / "deep" / ".judgekeeper").glob("previous-*/pool.jsonl")), out
