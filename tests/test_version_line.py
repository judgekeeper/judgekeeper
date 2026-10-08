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
    monkeypatch.setenv("VIRTUAL_ENV", "/projects/app/.venv")  # inside a project's environment


@pytest.fixture
def outside(monkeypatch):
    """Python as installed on the computer: no virtual environment, no conda environment."""
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    for name in ("VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "CONDA_PREFIX"):
        monkeypatch.delenv(name, raising=False)


OUTSIDE = ("judgekeeper is installed outside a project. Install it inside your project's "
           "environment instead (see www.judgekeeper.com/start.html#install).")


def _version(monkeypatch, out, which="/usr/local/bin/judgekeeper") -> list[str]:
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr("shutil.which", lambda name: which)
    assert main(["--version"]) == 0
    return out.getvalue().splitlines()


def test_in_a_terminal_it_says_ready_and_what_to_run_next(monkeypatch, plain_env):
    lines = _version(monkeypatch, Terminal())
    assert lines == [f"✓ judgekeeper {__version__} is ready",
                     "Next: run judgekeeper start"]


def test_piped_it_prints_only_the_version(monkeypatch, plain_env):
    assert _version(monkeypatch, io.StringIO()) == [f"judgekeeper {__version__}"]


def test_without_the_command_on_path_it_names_python_m(monkeypatch, plain_env):
    lines = _version(monkeypatch, Terminal(), which=None)
    assert lines[1] == "Next: run python3 -m judgekeeper start"


def test_on_windows_without_the_command_on_path_it_names_py_m(monkeypatch, plain_env):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WT_SESSION", "1")
    lines = _version(monkeypatch, Terminal(), which=None)
    assert lines == [f"✓ judgekeeper {__version__} is ready",
                     "Next: run py -m judgekeeper start"]


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


def test_outside_a_project_it_says_to_install_inside_one(monkeypatch, plain_env, outside):
    lines = _version(monkeypatch, Terminal())
    assert lines == [f"✓ judgekeeper {__version__} is ready",
                     "Next: run judgekeeper start", OUTSIDE]


def test_piped_outside_a_project_it_still_prints_only_the_version(monkeypatch, plain_env,
                                                                  outside):
    assert _version(monkeypatch, io.StringIO()) == [f"judgekeeper {__version__}"]


def test_a_virtual_environment_counts_as_inside(monkeypatch, plain_env, outside):
    monkeypatch.setattr(sys, "prefix", "/projects/app/.venv")  # sys.base_prefix differs
    assert OUTSIDE not in _version(monkeypatch, Terminal())


def test_virtual_env_set_counts_as_inside(monkeypatch, plain_env, outside):
    monkeypatch.setenv("VIRTUAL_ENV", "/projects/app/.venv")
    assert OUTSIDE not in _version(monkeypatch, Terminal())


@pytest.mark.parametrize("env, inside", [("app", True), ("base", False)])
def test_a_conda_environment_counts_but_not_its_base(monkeypatch, plain_env, outside, env,
                                                     inside):
    monkeypatch.setenv("CONDA_DEFAULT_ENV", env)
    assert (OUTSIDE not in _version(monkeypatch, Terminal())) is inside


# pipx and `uv tool install` are installs on the computer, not inside a project ----------------

@pytest.mark.parametrize("prefix", [
    "/Users/me/.local/pipx/venvs/judgekeeper",  # pipx on a Mac (and older Linux)
    "/home/me/.local/share/pipx/venvs/judgekeeper",  # pipx on Linux
    "/Users/me/Library/Application Support/pipx/venvs/judgekeeper",
    "C:\\Users\\me\\pipx\\venvs\\judgekeeper",  # pipx on Windows
    "C:\\Users\\me\\AppData\\Local\\pipx\\pipx\\venvs\\judgekeeper",
    "/Users/me/.local/share/uv/tools/judgekeeper",  # uv tool on a Mac and Linux
    "C:\\Users\\me\\AppData\\Roaming\\uv\\data\\tools\\judgekeeper",  # uv tool on Windows
])
def test_pipx_and_uv_tool_installs_are_outside_a_project(monkeypatch, plain_env, outside,
                                                         prefix):
    monkeypatch.setattr(sys, "prefix", prefix)  # a virtual environment, but a tool's own
    for name in ("PIPX_HOME", "UV_TOOL_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert _version(monkeypatch, Terminal())[-1] == OUTSIDE


@pytest.mark.parametrize("env, home, prefix", [
    ("PIPX_HOME", "/opt/tools/px", "/opt/tools/px/venvs/judgekeeper"),
    ("UV_TOOL_DIR", "/opt/tools/uvt", "/opt/tools/uvt/judgekeeper"),
    ("PIPX_HOME", "D:\\px", "D:\\px\\venvs\\judgekeeper"),
    ("UV_TOOL_DIR", "D:\\uvt", "D:\\UVT\\judgekeeper"),  # Windows paths ignore case
])
def test_pipx_home_and_uv_tool_dir_are_read(monkeypatch, plain_env, outside, env, home,
                                            prefix):
    monkeypatch.setattr(sys, "prefix", prefix)
    monkeypatch.setenv(env, home)
    assert _version(monkeypatch, Terminal())[-1] == OUTSIDE


@pytest.mark.parametrize("prefix", [
    "/projects/app/.venv",
    "/work/tools/app/.venv",  # a folder named tools, but not uv's
    "/work/pipx-demo/.venv",
    "/work/uv/app/.venv",
    "C:\\work\\app\\.venv",
])
def test_a_project_environment_is_still_inside(monkeypatch, plain_env, outside, prefix):
    monkeypatch.setattr(sys, "prefix", prefix)
    for name in ("PIPX_HOME", "UV_TOOL_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert OUTSIDE not in _version(monkeypatch, Terminal())


def test_a_tool_install_is_outside_even_with_a_project_environment_switched_on(
        monkeypatch, plain_env, outside):
    monkeypatch.setattr(sys, "prefix", "/home/me/.local/share/pipx/venvs/judgekeeper")
    monkeypatch.setenv("VIRTUAL_ENV", "/projects/app/.venv")  # this judgekeeper is not that one
    assert _version(monkeypatch, Terminal())[-1] == OUTSIDE
