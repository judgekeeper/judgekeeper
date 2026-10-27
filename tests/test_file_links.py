"""A file a person is told to open is a link they can click in a terminal (OSC 8), and the
same plain text as before everywhere else."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest

from judgekeeper import links
from judgekeeper.cli import main
from judgekeeper.links import file_url, keep, link
from judgekeeper.redact import printable
from judgekeeper.textio import wrap
from tests.start_projects import promptfoo_project, split

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


# Said on a screen ----------------------------------------------------------------------------

LINK = re.compile(r"\x1b\]8;;([^\x1b]*)\x1b\\(.*?)\x1b\]8;;\x1b\\")


def plain(out: str) -> str:
    """`out` with each link back to the text it shows."""
    return LINK.sub(r"\2", out)


def linked(out: str) -> dict[str, str]:
    """{the text shown: its URL} for each link in `out`."""
    return {text: url for url, text in LINK.findall(out)}


def test_a_link_made_here_passes_the_terminal_clean_up(tmp_path):
    made = link(tmp_path / "report.html", ".judgekeeper/report.html", stream=Terminal())
    text = f"Full report: {made} (open it\x07 in your browser)"
    assert keep(text, printable) == f"Full report: {made} (open it in your browser)"


def test_an_escape_code_from_anywhere_else_is_dropped(tmp_path):
    forged = "\x1b]8;;file:///etc/passwd\x1b\\results.json\x1b]8;;\x1b\\"
    assert keep(f"File: {forged}", printable) == (
        "File: ]8;;file:///etc/passwd\\results.json]8;;\\")


def test_the_text_a_link_shows_is_cleaned_too(tmp_path):
    made = link(tmp_path / "a.txt", "a\x07.txt", stream=Terminal())
    assert keep(made, printable) == _osc8(file_url(tmp_path / "a.txt"), "a.txt")


@pytest.mark.parametrize("width", [20, 30, 40, 64])
def test_a_link_wraps_where_its_text_would(tmp_path, width):
    text = ("All 10 mistakes your LLM-as-a-judge made are saved in {}. Use it to write a "
            "better rule.")
    shown = ".judgekeeper/fix/mistakes.md"
    made = link(tmp_path / "mistakes.md", shown, stream=Terminal())
    lines = wrap(text.format(made), width=width)
    assert [plain(line) for line in lines] == wrap(text.format(shown), width=width)
    assert sum(made in line for line in lines) == 1


@pytest.fixture
def links_on(monkeypatch):
    """A terminal that draws links, for what is printed to stdout only."""
    monkeypatch.setattr(links, "_links_show", lambda stream: True)


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _front(capsys, *argv) -> str:
    main([*argv, "--no-browser"])
    main(["--stop"])
    return capsys.readouterr().out


def _url_of(path) -> str:
    return file_url(Path(path).resolve())


def _first_screen(folder: Path, monkeypatch, capsys) -> str:
    """The first screen, its marking page's address (a new port and token each time) left out."""
    folder.mkdir(parents=True)
    monkeypatch.chdir(folder)
    promptfoo_project(folder, [*split(18, 16), None, None, None])
    return re.sub(r"http://127\.0\.0\.1:\S+", "PAGE", _front(capsys))


def test_the_find_screen_links_the_results_file_and_the_list(tmp_path, capsys, monkeypatch):
    out = _first_screen(tmp_path / "a" / "bot", monkeypatch, capsys)
    monkeypatch.setattr(links, "_links_show", lambda stream: True)
    here = tmp_path / "b" / "bot"
    again = _first_screen(here, monkeypatch, capsys)
    assert plain(again) == out
    shown = linked(again)
    assert shown["results.json"] == _url_of(here / "results.json")
    assert shown[".judgekeeper/judge-check.csv"] == _url_of(here / ".judgekeeper" /
                                                            "judge-check.csv")


def test_the_shortened_rule_links_its_config(here, capsys, links_on):
    promptfoo_project(here, split(20, 16), rubric="Grade it well. " * 20)
    out = _front(capsys)
    assert "(shortened; full rule in promptfooconfig.yaml)" in plain(out)
    assert linked(out)["promptfooconfig.yaml"] == _url_of(here / "promptfooconfig.yaml")


def test_the_result_links_the_full_report(here, capsys, links_on):
    from tests.test_fix import project

    project(here)
    out = _front(capsys)
    assert "Full report: .judgekeeper/report.html (open it in your browser)" in plain(out)
    assert linked(out)[".judgekeeper/report.html"] == _url_of(here / ".judgekeeper" /
                                                              "report.html")


def test_fix_links_every_file_it_asks_you_to_open(here, capsys, monkeypatch):
    from tests.test_fix import project

    project(here)
    capsys.readouterr()
    main(["fix"])
    out = capsys.readouterr().out
    monkeypatch.setattr(links, "_links_show", lambda stream: True)
    main(["fix"])
    again = capsys.readouterr().out
    assert plain(again) == out
    shown = linked(again)
    fix_folder = here / ".judgekeeper" / "fix"
    assert shown[".judgekeeper/fix/mistakes.md"] == _url_of(fix_folder / "mistakes.md")
    assert shown[".judgekeeper/fix/marked-answers.csv"] == _url_of(
        fix_folder / "marked-answers.csv")
    assert shown["promptfooconfig.yaml"] == _url_of(here / "promptfooconfig.yaml")
    assert "\x1b" not in LINK.sub("", again)


def test_a_piped_screen_has_no_escape_codes(here, capsys):
    from tests.test_fix import project

    project(here)
    main(["fix"])
    assert "\x1b" not in capsys.readouterr().out
