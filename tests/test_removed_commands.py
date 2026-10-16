"""The commands of the 0.1 CI gate, `setup` (part of `judgekeeper` now) and `start` (its steps
are `judgekeeper`, `mark`, `fix` and `check` now) are gone: each name prints one line, exits 2,
and is not in the help. (`check` is a command again.)"""

import re
from pathlib import Path

import pytest

from judgekeeper.cli import REMOVED, main

NAMES = ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "setup",
         "start")


def test_every_old_name_is_listed():
    assert set(REMOVED) == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("extra", [[], ["report.json", "--out", "x"], ["--help"]])
def test_a_removed_command_prints_one_line_and_exits_2(name, extra, capsys, tmp_path,
                                                       monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main([name, *extra]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == (f"judgekeeper {name} was removed. Run judgekeeper in your project.\n"
                   "Next: run `judgekeeper` in your project.\n")
    assert list(tmp_path.iterdir()) == []  # nothing written


def test_debug_before_the_name_still_finds_it(capsys):
    assert main(["--debug", "gate"]) == 2
    assert "judgekeeper gate was removed" in capsys.readouterr().err


def test_the_help_names_no_removed_command(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in NAMES:
        assert not re.search(rf"^  {name} ", out, re.MULTILINE) and f"{name}," not in out
    assert "CI" not in out


@pytest.mark.parametrize("flags", [["--review"], ["--fix", "--test-pass-mark"],
                                   ["--fix", "--rule-file", "rule.txt"], ["--ask-again"],
                                   ["--agent-prompt"]])
def test_start_with_its_old_flags_is_removed_too(flags, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["start", *flags]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("Next:") == 1 and "judgekeeper start was removed" in err
    assert list(tmp_path.iterdir()) == []


ROOT = Path(__file__).resolve().parent.parent
# The website keeps naming `start` until it is rewritten (tests/website_pages.STILL_NAMED), and
# the changelog says what each release had.
NAMED_OUTSIDE = [ROOT / "SECURITY.md", ROOT / "README.md", ROOT / ".github" / "CONTRIBUTING.md",
                 *(ROOT / "docs").rglob("*.md"), *(ROOT / "docs").rglob("*.json"),
                 *(ROOT / "src").rglob("*.py"), *(ROOT / "src").rglob("*.json"),
                 *(ROOT / "scripts").glob("*.py")]


@pytest.mark.parametrize("path", NAMED_OUTSIDE, ids=lambda p: str(p.relative_to(ROOT)))
def test_nothing_outside_the_website_names_start(path):
    assert not re.search(r"judgekeeper start\b", path.read_text(encoding="utf-8"))


def test_asking_again_names_no_flag_that_check_and_fix_lack():
    for path in (ROOT / "src" / "judgekeeper" / "again").glob("*.py"):
        assert "--python" not in path.read_text(encoding="utf-8"), path.name
