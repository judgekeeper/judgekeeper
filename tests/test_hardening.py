"""Odd and broken input: every run keeps the four rules.

Whatever the input: (1) no Python traceback; (2) the exit code is 0, 2, 3 or 130; (3) exactly
one `Next:` line; (4) no answer, input or reason text from the results in anything printed.
Every answer holds ZQOUT, every input ZQIN and every reason ZQWHY, so a leak is easy to see.
`main()` runs without a terminal, as a coding agent runs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from judgekeeper.cli import main

SENTINELS = ("ZQIN", "ZQOUT", "ZQWHY")


def run(capsys, *args) -> tuple[int, str]:
    code = main([*args])
    printed = capsys.readouterr()
    return code, printed.out + printed.err


def assert_rules(code: int, text: str) -> None:
    assert "Traceback" not in text, text
    assert code in (0, 2, 3, 130), (code, text)
    nexts = [line for line in text.splitlines() if line.startswith("Next:")]
    assert len(nexts) == 1, text
    for sentinel in SENTINELS:
        assert sentinel not in text, (sentinel, text)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# Messages ---------------------------------------------------------------------------------

def test_no_message_prints_a_placeholder(project, capsys):
    _write(project / "requirements.txt", "inspect-ai\n")
    code, text = run(capsys)
    assert_rules(code, text)
    assert "{program}" not in text
    assert "then run judgekeeper again" in text


def test_a_link_in_judgekeepers_folder_names_the_main_command(project, capsys):
    from tests.start_projects import promptfoo_project, split
    from tests.test_links import _link

    promptfoo_project(project, split(20, 16))
    outside = project.parent / "outside"
    outside.mkdir()
    _link(project / ".judgekeeper", outside, folder=True)
    code, text = run(capsys, "--no-browser")
    assert code == 2
    assert "Remove it, then run judgekeeper again." in text


def test_the_free_check_says_what_it_saw_not_more(project, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(project, split(20, 16))
    code, text = run(capsys, "--no-browser")
    assert_rules(code, text)
    assert ("Your judge gave a Pass or Fail on every answer (no errors or empty "
            "replies).") in text
    assert "real decision" not in text
