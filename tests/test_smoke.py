"""The package imports, and the command line starts."""

from judgekeeper import __version__
from judgekeeper.cli import main


def test_version_is_set():
    assert __version__


def test_cli_help_exits_zero():
    assert main(["--help"]) == 0


def test_cli_unknown_command_exits_nonzero():
    assert main(["nope"]) == 2
