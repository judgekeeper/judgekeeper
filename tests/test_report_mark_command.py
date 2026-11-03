"""report.html names `mark` as the terminal does after the same run: with its --port too."""

from __future__ import annotations

import html
import re

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import Workspace
from tests.start_projects import table_project
from tests.test_check import _flat
from tests.test_flow_across_runs import _mark


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("flags", [["--port", "9784", "--no-browser"], ["--no-browser"]])
def test_the_reports_say_why_command_is_the_terminals(here, capsys, flags):
    truth = [i % 3 != 0 for i in range(60)]
    table_project(here, [(not t) if i % 4 == 1 else t for i, t in enumerate(truth)])
    main(["--no-browser", "--port", "0"])
    main(["--stop"])
    _mark(Workspace(here), {i: "pass" if t else "fail" for i, t in enumerate(truth)})
    capsys.readouterr()
    main(flags)
    said = _flat(capsys.readouterr().out)
    terminal = re.search(r"Tell judgekeeper why you disagree on these \d+: run `([^`]+)`", said)
    assert terminal, said
    page = html.unescape(re.sub(r"<[^>]+>", "", (here / ".judgekeeper" / "report.html")
                                .read_text(encoding="utf-8")))
    report = re.search(r"Tell judgekeeper why you disagree on these \d+: run ([^.]+?)\.",
                       " ".join(page.split()))
    assert report, page[-2000:]
    assert report[1] == terminal[1], (report[1], terminal[1])
