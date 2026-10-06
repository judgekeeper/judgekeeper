"""`judgekeeper setup` keeps each file's own line endings, on every system.

Windows text files end their lines with \\r\\n. Setup reads the user's files as they are and
writes its new lines with the same ending, so running it (twice, too) never adds blank lines
to a requirements file and never leaves judgekeeper.toml with a stray \\r. These tests write
\\r\\n files on macOS and Linux too.
"""

from __future__ import annotations

import tomllib

import pytest

from judgekeeper.cli import main
from judgekeeper.config import load_section
from judgekeeper.gate import GateConfig
from tests.start_projects import flat_jsonl

CRLF, LF = b"\r\n", b"\n"


def setup_project(root, *argv):
    flat_jsonl(root / "evals" / "graded.jsonl")
    return main(["setup", str(root), "--yes", *argv])


def endings(data: bytes) -> set[bytes]:
    """The line endings used in `data`: {b"\\r\\n"}, {b"\\n"}, or both."""
    found = set()
    if CRLF in data:
        found.add(CRLF)
    if LF in data.replace(CRLF, b""):
        found.add(LF)
    return found


def assert_clean(data: bytes, eol: bytes) -> None:
    assert endings(data) == {eol}, data
    assert b"\r\r" not in data and b"\r" not in data.replace(CRLF, b""), data


@pytest.mark.parametrize("before, after", [
    (b"pytest\r\nruff\r\n", b"pytest\r\nruff\r\njudgekeeper\r\n"),
    (b"pytest\r\nruff", b"pytest\r\nruff\r\njudgekeeper\r\n"),
    (b"pytest\nruff\n", b"pytest\nruff\njudgekeeper\n"),
])
def test_a_requirements_file_keeps_its_line_endings(tmp_path, capsys, before, after):
    (tmp_path / "requirements-dev.txt").write_bytes(before)
    assert setup_project(tmp_path) == 0, capsys.readouterr().out
    assert (tmp_path / "requirements-dev.txt").read_bytes() == after


def test_gitignore_keeps_its_line_endings(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_bytes(b"node_modules\r\n*.pyc\r\n")
    assert setup_project(tmp_path) == 0, capsys.readouterr().out
    data = (tmp_path / ".gitignore").read_bytes()
    assert data.startswith(b"node_modules\r\n*.pyc\r\n# judgekeeper:")
    assert b".judgekeeper/*\r\n!.judgekeeper/baseline.json\r\n" in data
    assert_clean(data, CRLF)


PYPROJECT = (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = [\r\n'
             b'    "pytest>=8",\r\n    "ruff",\r\n]\r\n')


@pytest.mark.parametrize("text, want", [
    (PYPROJECT, ["pytest>=8", "ruff", "judgekeeper"]),
    (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = ["pytest"]\r\n',
     ["pytest", "judgekeeper"]),
    (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = [\r\n    "pytest"\r\n]\r\n',
     ["pytest", "judgekeeper"]),
])
def test_pyproject_keeps_its_line_endings(tmp_path, capsys, text, want):
    (tmp_path / "pyproject.toml").write_bytes(text)
    assert setup_project(tmp_path) == 0, capsys.readouterr().out
    data = (tmp_path / "pyproject.toml").read_bytes()
    assert tomllib.loads(data.decode("utf-8"))["dependency-groups"]["dev"] == want
    assert endings(data) == {CRLF} and b"\r\r" not in data


def test_judgekeeper_toml_keeps_its_line_endings_and_stays_valid(tmp_path, capsys):
    path = tmp_path / "judgekeeper.toml"
    path.write_bytes(b"# my thresholds\r\n[gate]\r\nkappa_min = 0.7\r\n")
    assert setup_project(tmp_path) == 0, capsys.readouterr().out
    data = path.read_bytes()
    assert endings(data) == {CRLF} and b"\r\r" not in data
    parsed = tomllib.loads(data.decode("utf-8"))
    assert parsed["gate"] == {"kappa_min": 0.7} and parsed["start"]["source"] == "map"
    assert load_section(path, "gate", GateConfig(), ValueError).kappa_min == 0.7


def test_a_new_judgekeeper_toml_uses_plain_newlines(tmp_path, capsys):
    assert setup_project(tmp_path) == 0, capsys.readouterr().out
    assert endings((tmp_path / "judgekeeper.toml").read_bytes()) == {LF}


def test_setup_twice_changes_nothing_the_second_time(tmp_path, capsys, monkeypatch):
    """The second run sets the same thing up again: every file's bytes stay as they were."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_bytes(b"node_modules\r\n")
    (tmp_path / "requirements-dev.txt").write_bytes(b"pytest\r\n")
    (tmp_path / "judgekeeper.toml").write_bytes(b"[gate]\r\nkappa_min = 0.7\r\n")
    assert setup_project(tmp_path) == 0
    first = {name: (tmp_path / name).read_bytes()
             for name in (".gitignore", "requirements-dev.txt", "judgekeeper.toml")}
    from judgekeeper import start

    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")  # set it up again: yes
    assert main(["setup", str(tmp_path)]) == 0
    capsys.readouterr()
    for name, data in first.items():
        assert (tmp_path / name).read_bytes() == data, name
    assert_clean(first["requirements-dev.txt"], CRLF)
    assert tomllib.loads(first["judgekeeper.toml"].decode("utf-8"))["gate"] == {
        "kappa_min": 0.7}
