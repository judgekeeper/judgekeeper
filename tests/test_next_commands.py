"""Every command judgekeeper prints for the person to run next works when copied: it keeps the
results path and the person's own flags (start.Talk.command), in the terminal and on the result
page (`mark` with every flag, `check`, `fix` and `--new` with the path). No page names `judgekeeper
start` or one of its flags: that command is gone."""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import report_page, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import split, table_project

FLAGS = ["--label-map", "good=pass,bad=fail", "--port", "0", "--no-browser"]
BASE = "judgekeeper evals/results.csv --label-map good=pass,bad=fail --port 0 --no-browser"
GONE = ("judgekeeper start", "--review", "--ask-again", "--try-new-judge", "--label-more",
        "--fix", "--rule-file", "--test-pass-mark")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Results with their own labels in a subfolder, run from the project folder."""
    verdicts = ["good" if v else "bad" for v in split(20, 16)]
    table_project(tmp_path, verdicts, name="evals/results.csv")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _mark_all(ws: Workspace) -> None:
    """Every answer marked as the judge said: 20 Pass and 16 Fail, enough for a result."""
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 7})


def test_the_result_names_only_the_command_that_was_run(project, capsys):
    assert main(["evals/results.csv", *FLAGS, "--yes"]) == 0
    ws = Workspace(project)  # in the project, never next to the file
    _mark_all(ws)
    capsys.readouterr()
    code = main(["evals/results.csv", *FLAGS, "--yes"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert ws.report_html.is_file(), (out, sorted(p.name for p in ws.dir.iterdir()))
    page = ws.report_html.read_text(encoding="utf-8")
    on_page = set(re.findall(r"<code[^>]*>(judgekeeper[^<]*)</code>", page))
    # as the terminal prints them: mark keeps every flag, check and fix the path
    named = report_page.commands(json.loads(ws.result_json.read_text(encoding="utf-8")))
    assert {k: named[k] for k in ("mark", "check", "fix")} == {
        "mark": BASE.replace("judgekeeper", "judgekeeper mark", 1),
        "check": "judgekeeper check evals/results.csv",
        "fix": "judgekeeper fix evals/results.csv"}
    assert on_page <= {named["mark"], named["fix"]}, on_page
    for gone in GONE:
        assert gone not in page and gone not in out, gone


def test_every_marked_line_names_the_runs_command():
    r = {"check": "too_few", "left": 0, "labels": {"correct": 20, "wrong": 4}, "command": BASE}
    # as the terminal says it: the path only, never the run's flags
    assert "`judgekeeper evals/results.csv --new`" in start_label.sentences(r)[1]
