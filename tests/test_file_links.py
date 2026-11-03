"""A file a person is told to open is printed as plain text, in a terminal too. A hidden link
target would hold the whole path, and with it the user name, which no printed line shows."""

from __future__ import annotations

import getpass
import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from judgekeeper.cli import main
from judgekeeper.links import link
from judgekeeper.textio import wrap
from tests.start_projects import promptfoo_project, split

ROOT = Path(__file__).resolve().parents[1]


class Terminal(io.StringIO):
    def isatty(self):
        return True


def _terminal(monkeypatch):
    """stdout is a terminal that names itself and could draw links."""
    for name in ("NO_COLOR", "JUDGEKEEPER_NO_LINKS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr(sys, "stdout", Terminal())


def test_a_file_is_its_shown_text_in_a_terminal(tmp_path, monkeypatch):
    _terminal(monkeypatch)
    assert link(tmp_path / "report.html", ".judgekeeper/report.html") == ".judgekeeper/report.html"


def test_shown_text_defaults_to_the_path_as_given(tmp_path, monkeypatch):
    _terminal(monkeypatch)
    assert link(tmp_path / "rule.txt") == str(tmp_path / "rule.txt")


def test_line_is_added_to_the_text(tmp_path, monkeypatch):
    _terminal(monkeypatch)
    assert link(tmp_path / "c.yaml", "c.yaml", line=14) == "c.yaml:14"


def test_an_escape_code_in_a_line_is_dropped():
    forged = "\x1b]8;;file:///etc/passwd\x1b\\results.json\x1b]8;;\x1b\\"
    assert wrap(f"File: {forged}") == ["File: ]8;;file:///etc/passwd\\results.json]8;;\\"]


def test_the_fix_screen_in_a_terminal_has_no_escape_codes(tmp_path, monkeypatch, capsys):
    from tests.test_fix import project

    folder = tmp_path / "support-bot"
    folder.mkdir()
    monkeypatch.chdir(folder)
    project(folder)
    capsys.readouterr()
    for name in ("NO_COLOR", "JUDGEKEEPER_NO_LINKS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    main(["fix"])
    out = capsys.readouterr().out
    assert ".judgekeeper/fix/mistakes.md" in out and "\x1b" not in out


# A real terminal ---------------------------------------------------------------------------------

def _in_a_terminal(folder: Path, *argv: str) -> bytes:
    """What `judgekeeper *argv` writes, run in `folder` in a pseudo-terminal."""
    import pty

    env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "JUDGEKEEPER_NO_LINKS")}
    env.update(TERM="xterm-256color", PYTHONPATH=str(ROOT / "src"), BROWSER="true")
    main_end, other_end = pty.openpty()
    try:
        proc = subprocess.Popen([sys.executable, "-m", "judgekeeper", *argv], cwd=folder,
                                env=env, stdin=subprocess.DEVNULL, stdout=other_end,
                                stderr=other_end)
    finally:
        os.close(other_end)
    out = b""
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            try:
                part = os.read(main_end, 65536)
            except OSError:  # the program closed its end
                break
            if not part:
                break
            out += part
        proc.wait(timeout=30)
    finally:
        os.close(main_end)
        if proc.poll() is None:
            proc.kill()
    return out


def _whole_paths(folder: Path) -> list[bytes]:
    paths = {str(folder), str(folder.resolve()), str(Path.home()), str(Path.home().resolve())}
    return [os.fsencode(p) for p in paths]


@pytest.mark.skipif(sys.platform == "win32", reason="a pseudo-terminal is POSIX only")
def test_a_terminal_shows_no_whole_path_and_no_user_name(tmp_path):
    from tests.test_fix import project

    folder = tmp_path / "support-bot"
    folder.mkdir()
    first = tmp_path / "first-look"
    first.mkdir()
    promptfoo_project(first, [*split(18, 16), None, None])
    here = os.getcwd()
    os.chdir(folder)
    try:
        project(folder)
    finally:
        os.chdir(here)
    try:
        out = b"".join([
            _in_a_terminal(first, "--no-browser", "--port", "0"),
            _in_a_terminal(first, "--stop"),
            _in_a_terminal(folder, "--no-browser", "--port", "0"),
            _in_a_terminal(folder, "--stop"),
            _in_a_terminal(folder, "fix"),
        ])
    finally:
        for done in (first, folder):
            _in_a_terminal(done, "--stop")
    text = out.decode("utf-8", "replace")
    assert "results.json" in text and "Full report: .judgekeeper/report.html" in text, text
    assert ".judgekeeper/fix/mistakes.md" in text, text
    assert b"\x1b]8;" not in out
    for path in _whole_paths(folder) + _whole_paths(first):
        assert path not in out, path
    user = getpass.getuser()
    if len(user) >= 3:
        assert not re.search(rf"(?<![A-Za-z0-9]){re.escape(user)}(?![A-Za-z0-9])", text), text
