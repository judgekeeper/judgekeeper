"""The commands of the 0.1 CI gate, and `setup` (part of `judgekeeper` now), are gone: each
name prints one line, exits 2, and is not in the help. (`check` is a command again.)"""

import pytest

from judgekeeper.cli import REMOVED, main

NAMES = ("init", "judge", "validate", "baseline", "gate", "migrate", "import", "setup")


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
    assert err == f"judgekeeper {name} was removed. Run judgekeeper in your project.\n"
    assert list(tmp_path.iterdir()) == []  # nothing written


def test_debug_before_the_name_still_finds_it(capsys):
    assert main(["--debug", "gate"]) == 2
    assert "judgekeeper gate was removed" in capsys.readouterr().err


def test_the_help_names_only_start(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "  start " in out
    for name in NAMES:
        assert f"  {name} " not in out and f"{name}," not in out
    assert "CI" not in out


def test_start_still_parses(capsys):
    assert main(["start", "--help"]) == 0
    assert "--review" in capsys.readouterr().out
