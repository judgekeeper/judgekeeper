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


def test_every_judge_call_failed_needs_the_person(project, capsys):
    from tests.test_judge_check import promptfoo_with_problems

    data = promptfoo_with_problems([True, False], errors=[0, 1])
    _write(project / "results.json", __import__("json").dumps(data))
    code, text = run(capsys, "--no-browser")
    assert_rules(code, text)
    assert code == 3
    assert text.splitlines()[-4:] == [
        "Your judge's calls failed on every answer, so there is nothing to mark.",
        "The list is in .judgekeeper/judge-check.csv.", "",
        ("Next: fix your judge's calls, run your eval again, then run "
         "`judgekeeper --no-browser`.")]


# Every error ends with a Next: line ---------------------------------------------------------

def _promptfoo(root: Path) -> Path:
    from tests.start_projects import promptfoo_project, split

    return promptfoo_project(root, split(20, 16), tag=" ZQIN ZQOUT")


@pytest.mark.parametrize("args", [
    ["--tool", "nope"], ["--port", "99999"], ["--no-such-flag"], ["mark", "--tool", "nope"],
    ["check", "--no-such-flag"], ["start", "--rule-file", "rule.txt"], ["setup"], ["init"],
    ["no/such/folder"], ["mark", "no/such/folder"], ["--stop", "no/such/folder"]])
def test_a_usage_error_ends_with_a_next_line(project, capsys, args):
    code, text = run(capsys, *args)
    assert_rules(code, text)
    assert code == 2


def test_a_bare_word_is_not_taken_for_a_folder(project, capsys):
    code, text = run(capsys, "status")
    assert_rules(code, text)
    assert code == 2
    assert "`status` is not a judgekeeper command" in text
    assert "file or folder not found" not in text
    assert "Next: run `judgekeeper`, or `judgekeeper --help` to see the commands." in text


def test_a_judge_name_that_is_not_there_names_one_that_is(project, capsys):
    _promptfoo(project)
    code, text = run(capsys, "--metric", "nope", "--no-browser")
    assert_rules(code, text)
    assert code == 2
    assert "Next: run `judgekeeper --no-browser --metric llm-rubric`." in text


def test_an_unexpected_error_never_prints_its_text(project, capsys, monkeypatch):
    from judgekeeper import front

    _promptfoo(project)

    def broken(*args, **kwargs):
        raise ValueError("ZQOUT the answer text")

    monkeypatch.setattr(front, "find_found", broken)
    code, text = run(capsys, "--no-browser")
    assert_rules(code, text)
    assert code == 2
    assert "judgekeeper hit a problem it didn't expect" in text
    assert "https://github.com/judgekeeper/judgekeeper/issues" in text
    assert "ValueError" not in text


def test_ctrl_c_says_how_to_carry_on(project, capsys, monkeypatch):
    from judgekeeper import front

    def stopped(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(front, "find_found", stopped)
    code, text = run(capsys, "--no-browser")
    assert_rules(code, text)
    assert code == 130
    assert "Next: run `judgekeeper --no-browser` to carry on." in text


@pytest.mark.skipif(__import__("os").name == "nt", reason="chmod does not stop writes there")
def test_a_folder_judgekeeper_cannot_write_in(project, capsys):
    import os

    _promptfoo(project)
    project.chmod(0o555)
    try:
        if os.access(project, os.W_OK):
            pytest.skip("running as a user that can write anywhere")
        code, text = run(capsys, "--no-browser")
    finally:
        project.chmod(0o755)
    assert_rules(code, text)
    assert code == 2
    assert "Next: make this folder writable" in text


def test_start_stopped_at_a_question_exits_3(project, capsys):
    _promptfoo(project)
    code, _ = run(capsys, "start")
    assert code == 3


def test_errors_are_printed_in_one_place():
    """Each `error:` line is printed by cli.main, which adds the Next: line; `judgekeeper`
    and `mark` never end with exit 2 on their own."""
    import re

    src = Path(__file__).parent.parent / "src" / "judgekeeper"
    printed = re.compile(r"""(["']|: )error: """)  # a line printed as an error
    for path in src.rglob("*.py"):
        if path.name != "cli.py":
            assert not printed.search(path.read_text(encoding="utf-8")), path
    for name in ("front.py", "mark.py"):
        lines = (src / name).read_text(encoding="utf-8").splitlines()
        assert not [x for x in lines if "EXIT_USAGE" in x and not x.startswith("EXIT_")], name
    cli = (src / "cli.py").read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(cli):
        if line.strip().startswith("return EXIT_USAGE"):
            assert any("_next(" in x for x in cli[n - 3:n]), (n + 1, line)
