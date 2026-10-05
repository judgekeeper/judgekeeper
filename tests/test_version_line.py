"""`judgekeeper --version` is the install check, and `textio.tick()` the one tick every
`start` line uses.

In a terminal it says the install is ready and what to run next; piped, it prints exactly
`judgekeeper <version>`, so scripts that read it keep working.
"""

from __future__ import annotations

import io
import sys

import pytest

from judgekeeper import __version__, textio
from judgekeeper.cli import main


class Terminal(io.StringIO):
    """A stdout that says it is a terminal, with a chosen encoding."""

    def __init__(self, encoding: str = "utf-8"):
        super().__init__()
        self._encoding = encoding

    @property
    def encoding(self):
        return self._encoding

    def isatty(self):
        return True


@pytest.fixture
def plain_env(monkeypatch):
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")


def _version(monkeypatch, out, which="/usr/local/bin/judgekeeper") -> list[str]:
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr("shutil.which", lambda name: which)
    assert main(["--version"]) == 0
    return out.getvalue().splitlines()


def test_in_a_terminal_it_says_ready_and_what_to_run_next(monkeypatch, plain_env):
    lines = _version(monkeypatch, Terminal())
    assert lines == [f"✓ judgekeeper {__version__} is ready",
                     "Next: go to your project folder and run judgekeeper start"]


def test_piped_it_prints_only_the_version(monkeypatch, plain_env):
    assert _version(monkeypatch, io.StringIO()) == [f"judgekeeper {__version__}"]


def test_without_the_command_on_path_it_names_python_m(monkeypatch, plain_env):
    lines = _version(monkeypatch, Terminal(), which=None)
    assert lines[1] == "Next: go to your project folder and run python3 -m judgekeeper start"


def test_on_windows_without_the_command_on_path_it_names_py_m(monkeypatch, plain_env):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WT_SESSION", "1")
    lines = _version(monkeypatch, Terminal(), which=None)
    assert lines == [f"✓ judgekeeper {__version__} is ready",
                     "Next: go to your project folder and run py -m judgekeeper start"]


def test_the_tick_needs_an_encoding_that_has_it(plain_env):
    assert textio.tick(Terminal("utf-8")) == "✓"
    assert textio.tick(Terminal("ascii")) == "OK"
    assert textio.tick(Terminal("cp1252")) == "OK"


def test_on_windows_the_tick_needs_a_modern_terminal(monkeypatch, plain_env):
    monkeypatch.setattr(sys, "platform", "win32")
    assert textio.tick(Terminal("utf-8")) == "OK"  # the old console host
    monkeypatch.setenv("WT_SESSION", "{a-guid}")
    assert textio.tick(Terminal("utf-8")) == "✓"  # Windows Terminal
    monkeypatch.delenv("WT_SESSION")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    assert textio.tick(Terminal("utf-8")) == "✓"


def test_a_terminal_without_the_tick_says_ok(monkeypatch, plain_env):
    lines = _version(monkeypatch, Terminal("ascii"))
    assert lines[0] == f"OK judgekeeper {__version__} is ready"


def test_the_tick_is_never_an_emoji(plain_env):
    tick = textio.tick(Terminal("utf-8"))
    assert tick == "✓"  # CHECK MARK; not U+2705 or U+2714, no emoji variation selector
