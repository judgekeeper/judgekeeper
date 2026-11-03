"""Printed commands say plain `judgekeeper` only when the `judgekeeper` on the PATH is this same
program; another install first on the PATH (an older one, say) would run instead, so this one
is named as it was started."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from judgekeeper import textio
from judgekeeper.cli import main

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="a script here is a plain file; there it is an .exe")


def _script(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def ours(tmp_path, monkeypatch) -> Path:
    """This judgekeeper, started by its path from a project folder beside it, and another
    judgekeeper first on the PATH."""
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path / "project")
    tool = _script(tmp_path / "tools" / ".venv" / "bin" / "judgekeeper")
    other = _script(tmp_path / "old" / "bin" / "judgekeeper")
    monkeypatch.setenv("PATH", f"{other.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(sys, "argv", [os.path.relpath(tool)])
    monkeypatch.setattr(textio, "_typed", None)
    return tool


def test_another_judgekeeper_on_the_path_is_never_named(ours, capsys):
    assert textio.program() == "../tools/.venv/bin/judgekeeper"
    assert textio.program("fix") == "../tools/.venv/bin/judgekeeper fix"
    main(["--no-browser", "--port", "0"])
    out = " ".join(capsys.readouterr().out.split())
    assert "`../tools/.venv/bin/judgekeeper --port 0 --no-browser`" in out, out
    assert "`judgekeeper " not in out, out


def test_this_judgekeeper_on_the_path_is_named_plainly(ours, monkeypatch):
    monkeypatch.setenv("PATH", f"{ours.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "argv", [str(ours)])  # as the shell starts it from the PATH
    assert textio.program("fix") == "judgekeeper fix"


def test_a_link_on_the_path_to_this_judgekeeper_is_named_plainly(ours, tmp_path, monkeypatch):
    link = tmp_path / "local" / "bin" / "judgekeeper"
    link.parent.mkdir(parents=True)
    link.symlink_to(ours)
    monkeypatch.setenv("PATH", f"{link.parent}{os.pathsep}{os.environ['PATH']}")
    assert textio.program() == "judgekeeper"


def test_a_python_that_imports_another_judgekeeper_is_never_named(ours, monkeypatch, capsys):
    """Started by its whole path, with a `python3` first on the PATH whose judgekeeper is
    another install: commands name this program, not `python3 -m judgekeeper`."""
    python = ours.parent.parent.parent.parent / "old" / "bin" / "python3"
    python.write_text("#!/bin/sh\necho /opt/old/site-packages/judgekeeper/__init__.py\n",
                      encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setattr(sys, "argv", [str(ours)])
    monkeypatch.setattr(textio, "_imports", {})
    assert textio.program("fix") == "../tools/.venv/bin/judgekeeper fix"


STARTED_ELSE = ("These commands start with judgekeeper. If you start judgekeeper another way, "
                "start it that way.")


def _report(capsys, folder: Path) -> str:
    """report.html's text after a run of Measure on a promptfoo project with 40 marks."""
    import html
    import re

    from judgekeeper.start_label import Workspace
    from tests.test_earlier_grades import FIRST, N, _mark
    from tests.test_fix import closed
    from tests.test_flow_across_runs import _jk, _rubric

    (folder / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(folder, [i < 30 for i in range(N)], "V1 rule.")
    assert _jk(capsys, "--no-browser", "--port", "0")[0] == 0
    ws = Workspace(folder)
    closed(ws)
    _mark(ws, FIRST)
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    assert code == 0, out
    page = ws.report_html.read_text(encoding="utf-8")
    assert "tools" not in page and ".venv" not in page  # never a path in the file
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", page)).split())


def test_report_html_says_how_to_start_it_when_it_was_started_another_way(ours, capsys):
    text = _report(capsys, Path.cwd())
    assert "run judgekeeper mark" in text or "Run judgekeeper mark" in text, text
    assert STARTED_ELSE in text, text


def test_report_html_says_nothing_more_when_started_as_judgekeeper(ours, monkeypatch, capsys):
    monkeypatch.setenv("PATH", f"{ours.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(sys, "argv", [str(ours)])
    assert textio.program() == "judgekeeper"
    assert STARTED_ELSE not in _report(capsys, Path.cwd())


def test_report_html_says_nothing_more_when_started_by_uvx(ours, monkeypatch, capsys):
    monkeypatch.setattr(textio, "started_by_uvx", lambda: True)
    monkeypatch.setattr(textio, "extras_here", lambda: ())
    assert textio.program() == "uvx judgekeeper"
    assert STARTED_ELSE not in _report(capsys, Path.cwd())
