"""Every command judgekeeper prints for the person to run next works when copied: it keeps the
results path and the person's own flags (start.Talk.command), in the terminal and on the result
page (`mark` with every flag, `check` and `fix` with the path; with every answer marked, `mark`
with the path and the flags that change how the results are read). No page names `judgekeeper
start` or one of its flags: that command is gone."""

from __future__ import annotations

import json
import re
import shlex

import pytest

from judgekeeper import page, report_page, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import split, table_project

FLAGS = ["--label-map", "good=pass,bad=fail", "--port", "0", "--no-browser"]
BASE = "judgekeeper evals/results.csv --label-map good=pass,bad=fail --port 0 --no-browser"
MARK = "judgekeeper mark evals/results.csv --label-map good=pass,bad=fail"  # no page flags
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
    assert f"`{MARK}`" in start_label.sentences(r)[1]  # the reading flags, not the page's


# How the results were read, as start.json keeps it: the same reading gives the same pool
READ = ("given", "label_map", "metric", "pool", "pool_sha256", "left_out")


def test_marked_line_is_the_same_everywhere(
        tmp_path, monkeypatch, capsys):
    """Every answer marked, Fail still short: the terminal, the marking page's end card, the
    result page and report.html name the same `mark` command, and that command, run as
    printed, reads the results as the first run did."""
    verdicts = ["good"] * 50 + ["bad"] * 10
    table_project(tmp_path, verdicts, name="evals/results.csv")
    monkeypatch.chdir(tmp_path)
    assert main(["evals/results.csv", *FLAGS, "--yes"]) == 0
    ws = Workspace(tmp_path)
    first = {k: ws.data()[k] for k in READ}
    assert first["pool"] == {"answers": 60, "pass": 50, "fail": 10}
    _mark_all(ws)
    assert main(["evals/results.csv", *FLAGS, "--yes"]) == 3
    terminal = " ".join(capsys.readouterr().out.split())
    assert f"then run `{MARK}`: the new answers join the ones you marked." in terminal
    assert main(["--stop"]) == 0  # the page that run opened: this test opens its own
    capsys.readouterr()
    server = page.page_server(ws, 0, BASE.replace("judgekeeper", "judgekeeper mark", 1), BASE)
    try:
        card = server.session.state()["status"]["done"][1]
        html = server.result(server.session, "/?token=t")
    finally:  # never served: its socket and the project's lock, closed here
        server.httpd.server_close()
        server.release()
    assert f"then run `{MARK}`: the new answers join the ones you marked." in card
    for name, text in (("result page", html),
                       ("report.html", ws.report_html.read_text(encoding="utf-8"))):
        assert f"then run <code>{MARK}</code>: the new answers join the ones you marked." in \
            text, name
    capsys.readouterr()
    assert main(shlex.split(MARK)[1:]) == 3  # nothing new yet: it says the same
    out = " ".join(capsys.readouterr().out.split())
    assert f"then run `{MARK}`: the new answers join the ones you marked." in out, out
    assert {k: ws.data()[k] for k in READ} == first  # read the same way: nothing new to add
    assert StartSession(ws).counts()["correct"] == 50  # the marks are kept
