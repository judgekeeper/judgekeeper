"""judgekeeper in a project's dev requirements (dev_requirements.py): the first form the
project has, once, never the main requirements, in the file's own line endings.

Windows text files end their lines with \\r\\n. The new line ends the same way, so adding it
never adds blank lines to a requirements file. These tests write \\r\\n files on macOS and
Linux too.
"""

from __future__ import annotations

import tomllib

import pytest

from judgekeeper.dev_requirements import NOT_LISTED, requirements_change

CRLF, LF = b"\r\n", b"\n"

PYPROJECT_GROUPS = '''[project]
name = "app"
dependencies = ["httpx"]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff"
]
'''


@pytest.mark.parametrize("files, where, check", [
    ({"pyproject.toml": PYPROJECT_GROUPS}, "the dev group in pyproject.toml",
     lambda d: d["dependency-groups"]["dev"] == ["pytest>=8", "ruff", "judgekeeper"]),
    ({"pyproject.toml": '[project]\nname = "app"\n\n[dependency-groups]\ndev = ["pytest"]\n'},
     "the dev group in pyproject.toml",
     lambda d: d["dependency-groups"]["dev"] == ["pytest", "judgekeeper"]),
    ({"pyproject.toml": '[project]\nname = "app"\n\n[project.optional-dependencies]\n'
                        'dev = [\n  "pytest",\n]\n'},
     "the dev extra in pyproject.toml",
     lambda d: d["project"]["optional-dependencies"]["dev"] == ["pytest", "judgekeeper"]),
    ({"requirements-dev.txt": "pytest\n"}, "requirements-dev.txt", None),
    ({"requirements-dev.in": "pytest"}, "requirements-dev.in", None),
])
def test_each_requirements_form_is_edited_once(tmp_path, files, where, check):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    change = requirements_change(tmp_path)
    assert change.text == f"add judgekeeper to {where}"
    change.apply()
    name = next(iter(files))
    text = (tmp_path / name).read_text(encoding="utf-8")
    if check:
        assert check(tomllib.loads(text))
    else:
        assert text.splitlines()[-1] == "judgekeeper"
    assert requirements_change(tmp_path) is None  # listed now


def test_the_first_requirements_form_that_exists_wins(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_GROUPS, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert "pyproject.toml" in requirements_change(tmp_path).text


def test_already_listed_anywhere_is_not_added(tmp_path):
    (tmp_path / "requirements.txt").write_text("judgekeeper==0.2.0\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
    assert requirements_change(tmp_path) is None


def test_a_dev_list_with_an_include_group_still_gets_the_line(tmp_path):
    text = ('[project]\nname = "app"\n\n[dependency-groups]\n'
            'dev = ["pytest", {include-group = "lint"}]\nlint = ["ruff"]\n')
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    requirements_change(tmp_path).apply()
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["dependency-groups"]["dev"] == ["pytest", {"include-group": "lint"},
                                                "judgekeeper"]


def test_an_unusual_pyproject_is_skipped_with_a_message(tmp_path):
    text = 'dependency-groups = { dev = ["pytest"] }\n\n[project]\nname = "app"\n'
    assert tomllib.loads(text)["dependency-groups"]["dev"] == ["pytest"]
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    change = requirements_change(tmp_path)
    assert change.apply is None
    assert "add it to the dev group in pyproject.toml yourself" in change.text
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == text


def test_no_dev_requirements_file_changes_nothing(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx\n", encoding="utf-8")
    change = requirements_change(tmp_path)
    assert change.apply is None and change.text == NOT_LISTED
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "httpx\n"


# Line endings ------------------------------------------------------------------------------

def endings(data: bytes) -> set[bytes]:
    """The line endings used in `data`: {b"\\r\\n"}, {b"\\n"}, or both."""
    found = set()
    if CRLF in data:
        found.add(CRLF)
    if LF in data.replace(CRLF, b""):
        found.add(LF)
    return found


@pytest.mark.parametrize("before, after", [
    (b"pytest\r\nruff\r\n", b"pytest\r\nruff\r\njudgekeeper\r\n"),
    (b"pytest\r\nruff", b"pytest\r\nruff\r\njudgekeeper\r\n"),
    (b"pytest\nruff\n", b"pytest\nruff\njudgekeeper\n"),
])
def test_a_requirements_file_keeps_its_line_endings(tmp_path, before, after):
    (tmp_path / "requirements-dev.txt").write_bytes(before)
    requirements_change(tmp_path).apply()
    assert (tmp_path / "requirements-dev.txt").read_bytes() == after


PYPROJECT = (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = [\r\n'
             b'    "pytest>=8",\r\n    "ruff",\r\n]\r\n')


@pytest.mark.parametrize("text, want", [
    (PYPROJECT, ["pytest>=8", "ruff", "judgekeeper"]),
    (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = ["pytest"]\r\n',
     ["pytest", "judgekeeper"]),
    (b'[project]\r\nname = "app"\r\n\r\n[dependency-groups]\r\ndev = [\r\n    "pytest"\r\n]\r\n',
     ["pytest", "judgekeeper"]),
])
def test_pyproject_keeps_its_line_endings(tmp_path, text, want):
    (tmp_path / "pyproject.toml").write_bytes(text)
    requirements_change(tmp_path).apply()
    data = (tmp_path / "pyproject.toml").read_bytes()
    assert tomllib.loads(data.decode("utf-8"))["dependency-groups"]["dev"] == want
    assert endings(data) == {CRLF} and b"\r\r" not in data
