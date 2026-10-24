"""A file a person is told to open is a link they can click in a terminal (OSC 8), and the
same plain text as before everywhere else."""

from __future__ import annotations

import io
import os

import pytest

from judgekeeper import links
from judgekeeper.links import file_url, link

OPT_OUTS = ("NO_COLOR", "JUDGEKEEPER_NO_LINKS")


class Terminal(io.StringIO):
    def isatty(self):
        super().isatty()  # a closed stream raises ValueError, as a real one does
        return True


@pytest.fixture(autouse=True)
def plain_env(monkeypatch):
    for name in (*OPT_OUTS, "WT_SESSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setattr(links, "is_windows", lambda: False)


def _osc8(url, text):
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def test_terminal_wraps_the_shown_text_in_a_link(tmp_path):
    path = tmp_path / "report.html"
    shown = ".judgekeeper/report.html"
    assert link(path, shown, stream=Terminal()) == _osc8(file_url(path), shown)


def test_shown_text_defaults_to_the_path_as_given(tmp_path):
    path = tmp_path / "rule.txt"
    assert link(path, stream=Terminal()) == _osc8(file_url(path), str(path))


def test_a_relative_path_links_to_its_absolute_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    windows = os.name == "nt"
    url = file_url(os.path.join(".judgekeeper", "fix", "mistakes.md"), windows=windows)
    assert url == file_url(tmp_path / ".judgekeeper" / "fix" / "mistakes.md", windows=windows)
    assert url.startswith("file://") and url.endswith("/.judgekeeper/fix/mistakes.md")


@pytest.mark.parametrize("stream", [io.StringIO(), object()])
def test_not_a_terminal_is_plain_text(tmp_path, stream):
    assert link(tmp_path / "report.html", ".judgekeeper/report.html",
                stream=stream) == ".judgekeeper/report.html"


def test_a_closed_stream_is_plain_text(tmp_path):
    stream = Terminal()
    stream.close()
    assert link(tmp_path / "a.txt", "a.txt", stream=stream) == "a.txt"


def test_stdout_is_the_default_stream(tmp_path, capsys):
    assert link(tmp_path / "a.txt", "a.txt") == "a.txt"  # pytest's captured stdout is no terminal


@pytest.mark.parametrize("name", OPT_OUTS)
def test_each_opt_out_gives_plain_text(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "1")
    assert link(tmp_path / "a.txt", "a.txt", stream=Terminal()) == "a.txt"


@pytest.mark.parametrize("name", OPT_OUTS)
def test_an_empty_opt_out_is_not_set(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "")
    assert link(tmp_path / "a.txt", "a.txt", stream=Terminal()).startswith("\x1b]8;;")


def test_a_dumb_terminal_gets_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert link(tmp_path / "a.txt", "a.txt", stream=Terminal()) == "a.txt"


def test_the_old_windows_console_gets_plain_text(tmp_path, monkeypatch):
    """The old console host prints the escape codes instead of a link."""
    monkeypatch.setattr(links, "is_windows", lambda: True)
    monkeypatch.delenv("TERM_PROGRAM")
    monkeypatch.delenv("TERM", raising=False)
    assert link(tmp_path / "a.txt", "a.txt", stream=Terminal()) == "a.txt"


def test_windows_terminal_gets_a_link(tmp_path, monkeypatch):
    monkeypatch.setattr(links, "is_windows", lambda: True)
    monkeypatch.delenv("TERM_PROGRAM")
    monkeypatch.setenv("WT_SESSION", "1")
    assert link(tmp_path / "a.txt", "a.txt", stream=Terminal()).startswith("\x1b]8;;file:")


def test_line_is_added_to_the_text_not_the_url(tmp_path):
    path = tmp_path / "promptfooconfig.yaml"
    shown = link(path, "promptfooconfig.yaml", line=14, stream=Terminal())
    assert shown == _osc8(file_url(path), "promptfooconfig.yaml:14")


def test_line_in_plain_text(tmp_path):
    assert link(tmp_path / "c.yaml", "c.yaml", line=14) == "c.yaml:14"


def test_posix_url_encodes_spaces_and_non_ascii():
    assert (file_url("/home/ana/my evals/réponses #1.csv", windows=False)
            == "file:///home/ana/my%20evals/r%C3%A9ponses%20%231.csv")


def test_windows_drive_path():
    assert (file_url(r"C:\Users\Ana Lee\project\.judgekeeper\report.html", windows=True)
            == "file:///C:/Users/Ana%20Lee/project/.judgekeeper/report.html")


def test_windows_non_ascii_path():
    assert file_url(r"D:\données\règle.txt", windows=True) == (
        "file:///D:/donn%C3%A9es/r%C3%A8gle.txt")


def test_windows_network_share():
    assert (file_url(r"\\server\share\evals\mistakes.md", windows=True)
            == "file://server/share/evals/mistakes.md")


def test_the_url_never_holds_a_control_character():
    url = file_url("/tmp/a\x1b]8;;b\x07.txt", windows=False)
    assert all(" " < ch < "\x7f" for ch in url)
