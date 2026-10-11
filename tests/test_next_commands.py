"""Every command judgekeeper prints for the person to run next works when copied: it keeps the
results path and the person's own flags (start.Talk.command), in the terminal, on the result
page and at the end of the review.

The labeling page is replaced by a stand-in that marks every answer and saves the result, as
the page's server does; no page is served.
"""

from __future__ import annotations

import re
import shlex

import pytest

from judgekeeper import start_label, start_review
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace, save_result
from tests.start_projects import split, table_project

FLAGS = ["--label-map", "good=pass,bad=fail", "--port", "8805", "--no-browser"]
BASE = "judgekeeper start evals/results.csv --label-map good=pass,bad=fail --port 8805 --no-browser"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Results with their own labels in a subfolder, run from the project folder."""
    verdicts = ["good" if v else "bad" for v in split(20, 16)]
    table_project(tmp_path, verdicts, name="evals/results.csv")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def marked(monkeypatch):
    """The labeling page: every answer marked as the judge said, except four, then saved."""
    flip = {"pass": "fail", "fail": "pass"}

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        ws = start_label.prepare(found, say)
        session = StartSession(ws)
        for n, q in enumerate(ws.data()["queue"]):
            session.update({"id": q["id"], "label": flip[q["group"]] if n < 4 else q["group"]})
        save_result(ws, session, say, command)
        return 0

    monkeypatch.setattr(start_label, "run_labeling", run_labeling)


@pytest.fixture
def served(monkeypatch):
    """The review page: the workspace it would serve, kept."""
    calls = []

    def serve_review(ws, port, open_browser, say, command="judgekeeper start"):
        calls.append({"ws": ws, "port": port, "command": command})
        return 0

    monkeypatch.setattr(start_review, "serve_review", serve_review)
    return calls


def _printed(text: str) -> list[str]:
    return re.findall(r"judgekeeper start[^\n]*", text)


def test_the_next_commands_keep_the_path_and_flags(project, marked, served, capsys):
    code = main(["start", "evals/results.csv", *FLAGS, "--yes"])
    out = capsys.readouterr().out
    assert code == 0, out
    nexts = out.split("\nNext:\n", 1)[1]
    commands = _printed(nexts)
    assert f"{BASE} --review" in commands and BASE in commands, nexts
    assert all(c.startswith(BASE) for c in commands), commands

    page = Workspace(project / "evals").result_html.read_text(encoding="utf-8")
    assert f"{BASE} --review".replace("_", "&#95;") in page.replace("_", "&#95;")
    assert "<code>judgekeeper start --review</code>" not in page

    review = next(c for c in commands if c.endswith("--review"))
    code = main(shlex.split(review)[1:])  # run as printed
    out = capsys.readouterr().out
    assert code == 0 and "no result to review yet" not in out, out
    assert served and served[0]["command"] == BASE


def test_the_review_page_and_its_end_name_the_same_command(project, marked, capsys):
    main(["start", "evals/results.csv", *FLAGS, "--yes"])
    ws = Workspace(project / "evals")
    assert f"<code>{BASE} --review</code>".replace("_", "&#95;") in (
        start_review.page_template(ws))
    session = start_review.ReviewSession(ws)
    for item in session.items:
        session.update({"id": item["id"], "second": item["first"]})
    for item in session.items:
        if item["disagreement"]:
            session.update({"id": item["id"], "choice": "judge_wrong"})
    said = []
    start_review.finish(ws, said.append, BASE)
    assert f"Next: {BASE} --fix" in said


def test_every_marked_line_names_the_runs_command():
    r = {"check": "too_few", "left": 0, "labels": {"correct": 20, "wrong": 4}, "command": BASE}
    assert start_label.sentences(r)[0].endswith(f"then {BASE} --label-more.")
