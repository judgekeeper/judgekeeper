"""Started by uvx, judgekeeper names itself the way it was started. uv and pip skip betas
unless asked, and a person who ran `uvx judgekeeper` has no `judgekeeper` command: so every
`Next:` line and every printed command says `uvx judgekeeper` (`@<this version>` for a beta),
with the same subcommand and flags. Otherwise, `judgekeeper` as before.

uvx runs judgekeeper from a folder named `archive-v<N>/<id>` in uv's cache, and sets `UV`.
"""

from __future__ import annotations

import io
import re
import sys

import pytest

from judgekeeper import __version__, page, start_label, textio
from judgekeeper.cli import version_lines
from tests.start_projects import promptfoo_project, records_project, split
from tests.test_front import next_lines, run

UVX = f"uvx judgekeeper@{__version__}" if textio.is_prerelease() else "uvx judgekeeper"
CACHES = ["/Users/me/.cache/uv/archive-v0/r-lOTHILJ6Qzv6Y1",
          "/home/me/.cache/uv/archive-v0/abc123",
          "C:\\Users\\me\\AppData\\Local\\uv\\cache\\archive-v0\\abc123",
          "/custom/cache/archive-v1/abc123"]  # UV_CACHE_DIR set to a folder of the person's


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def by_uvx(monkeypatch):
    monkeypatch.setenv("UV", "/Users/me/.local/bin/uv")
    monkeypatch.setattr(sys, "prefix", CACHES[0])
    monkeypatch.setattr(textio, "extras_here", lambda: ())  # started without an extra


def _bare_commands(text: str) -> list[str]:
    """Commands that name `judgekeeper` without uvx: `judgekeeper ...` in backticks, or after
    "run"."""
    return re.findall(r"`judgekeeper[ `]|\b[Rr]un judgekeeper\b(?![.\w])", text)


# Telling how it was started ---------------------------------------------------------------

@pytest.mark.parametrize("prefix", CACHES)
def test_uv_s_cache_folder_and_uv_set_mean_uvx(monkeypatch, prefix):
    monkeypatch.setenv("UV", "uv")
    monkeypatch.setattr(textio, "extras_here", lambda: ())
    monkeypatch.setattr(sys, "prefix", prefix)
    assert textio.program() == UVX
    assert textio.program("mark") == f"{UVX} mark"


@pytest.mark.parametrize("version, pin", [("1.0.0", ""), ("1.1.0", ""), ("1.1.0b2", "@1.1.0b2")])
def test_only_a_beta_is_pinned(monkeypatch, by_uvx, version, pin):
    monkeypatch.setattr("judgekeeper.__version__", version)
    assert textio.program("check") == f"uvx judgekeeper{pin} check"


@pytest.mark.parametrize("prefix", [
    "/projects/app/.venv",  # `uv run judgekeeper` in a project
    "/Users/me/.local/share/uv/tools/judgekeeper",  # `uv tool install judgekeeper`
    "C:\\Users\\me\\AppData\\Roaming\\uv\\data\\tools\\judgekeeper",
])
def test_uv_without_its_cache_folder_is_the_judgekeeper_command(monkeypatch, prefix):
    monkeypatch.setenv("UV", "uv")
    monkeypatch.setattr(sys, "prefix", prefix)
    assert textio.program() == "judgekeeper"
    assert textio.program("mark") == "judgekeeper mark"


def test_the_cache_folder_without_uv_is_the_judgekeeper_command(monkeypatch):
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(sys, "prefix", CACHES[0])
    assert textio.program() == "judgekeeper"


# What it prints -----------------------------------------------------------------------------

class Terminal(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


def test_the_version_line_names_uvx(by_uvx, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)  # uvx puts nothing on the PATH
    assert version_lines(Terminal())[1] == f"Next: run {UVX}"


def test_the_first_run_names_no_bare_command(here, capsys, by_uvx, no_browser):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert next_lines(out) == ['Next: mark until "See your result" appears, then click it.']
    assert not _bare_commands(out), out


def test_a_printed_link_names_no_bare_command(here, capsys, by_uvx):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    assert next_lines(out) == ['Next: mark until "See your result" appears, then click it.']
    assert not _bare_commands(out), out


def test_marking_started_and_the_result_name_uvx(here, capsys, by_uvx):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:10]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 5})
    _, out, _ = run(capsys)
    assert next_lines(out) == ['Next: keep marking until "See your result" appears, then click it.'] and not _bare_commands(out), out
    for item in session.items[10:]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 5})
    code, out, _ = run(capsys)
    assert code == 0, out
    assert next_lines(out)[-1].endswith(f"run `{UVX} check`.")
    assert not _bare_commands(out), out


def test_a_question_names_uvx_with_the_flag(here, capsys, by_uvx):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    code, out, _ = run(capsys)
    assert code == 3
    assert f"`{UVX} --metric NAME`" in out and not _bare_commands(out), out


def test_mark_names_no_bare_command(here, capsys, by_uvx):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "mark", "--no-browser")
    assert code == 0, out
    assert next_lines(out) == ['Next: mark until "See your result" appears, then click it.']
    assert not _bare_commands(out), out


def test_stop_and_start_over_name_uvx(here, capsys, by_uvx):
    records_project(here, split(16, 16), name="helpfulness")
    run(capsys, "--metric", "helpfulness")
    code, out, _ = run(capsys, "--metric", "helpfulness", "--new")
    assert code == 3
    assert f"`{UVX} --metric helpfulness --new --yes`" in out
    assert not _bare_commands(out), out


def test_the_page_says_to_run_uvx_in_the_terminal(here, capsys, by_uvx):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 5})
    text = page.marking_session(ws).summary()["status"]["text"]
    assert text.endswith(f"When you're done, run {UVX} in your terminal."), text


def test_without_uvx_nothing_changes(here, capsys, no_browser, monkeypatch):
    monkeypatch.delenv("UV", raising=False)
    promptfoo_project(here, split(20, 16))
    _, out, _ = run(capsys)
    assert "uvx" not in out
    assert next_lines(out) == ['Next: mark until "See your result" appears, then click it.']
