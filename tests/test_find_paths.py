"""Find names the folder it reads from where the command runs: never the whole path."""

from __future__ import annotations

import pytest

import judgekeeper
from judgekeeper import recorder
from judgekeeper.cli import main


@pytest.mark.parametrize("depth", [1, 3])
def test_records_at_the_project_root_are_named_from_here(tmp_path, monkeypatch, capsys, depth):
    root = tmp_path / "gp"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "gp"\nversion = "0"\n', encoding="utf-8")
    child = root.joinpath(*[f"c{n}" for n in range(depth)])
    child.mkdir(parents=True)
    monkeypatch.chdir(child)
    monkeypatch.setattr(recorder, "_paths", {})  # record() keeps its file per run
    judgekeeper.record(input="q", output="a", verdict="pass")
    assert list((root / ".judgekeeper" / "records").glob("*.jsonl"))
    capsys.readouterr()
    try:
        main(["--no-browser", "--port", "0"])
    finally:
        main(["--stop"])
    out = capsys.readouterr().out
    up = "/".join([".."] * depth)
    assert f"at the project root: reading them in {up}." in out, out
    assert str(tmp_path) not in out and str(tmp_path.resolve()) not in out
