"""`judgekeeper mark`: where marking stands, and the one thing that fits. Every row of its
state table, without a terminal: the output, exactly one `Next:` line at the end, the exit
code, and no answer text.

The page itself starts in the background (test_mark_background.py runs it as a real
process); here `background.start` serves the same page in a thread.
"""

from __future__ import annotations

import json
import re
import threading

import pytest

from judgekeeper import __version__, background, label, mark, marks, start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, records_project, split
from tests.test_front import assert_one_next_at_the_end, next_lines, run

TAG = " SECRET-7f3a"  # in every question and answer: a leak shows
NEXT_A = ("Next: give the person the link above and ask them to mark answers until the page "
          "says it has enough. When they say they are done, run `judgekeeper mark` again.")
NEXT_B = ("Next: nothing. Tell the person the result above. Marking more on the page narrows "
          "the ranges.")
COULD_NOT = ("Next: ask the person to run judgekeeper mark --wait in their own terminal (it "
             "keeps the page open there).")
START_OVER = ("Start over with these results? Your old marks move to "
              ".judgekeeper/previous-<date>/.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def pages(monkeypatch):
    """background.start, with the page served in a thread of this process. `started` keeps
    the arguments of each start; `fail` makes the next start fail."""
    started, servers = [], []
    state = {"fail": False}

    def fake_start(folder, args, timeout=background.WAIT):
        started.append(list(args))
        if state["fail"]:
            return None
        ws = start_label.Workspace(folder.parent)
        server = mark.page_server(ws, 0, "judgekeeper mark")
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        servers.append((server, thread))
        return label.open_page(folder)

    monkeypatch.setattr(background, "start", fake_start)
    yield started, state
    for server, thread in servers:
        server.stop()
        thread.join(timeout=5)


def _check(out: str, err: str = "") -> str:
    assert TAG.strip() not in out + err
    assert out.startswith(f"judgekeeper {__version__}\n\n"), out
    return assert_one_next_at_the_end(out)


def _click(ws, n=None, seconds=7):
    """The person marks the first n answers on the page, as the judge did."""
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:n]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": seconds})


# Something must be asked ------------------------------------------------------------------

def test_a_question_is_the_same_as_judgekeepers(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    records_project(here, split(16, 16))
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert "Saved results from more than one eval tool:" in out
    assert _check(out, err) == (
        "Next: ask the person which eval tool's results to check (records, promptfoo), then "
        "run `judgekeeper mark --tool NAME`.")
    assert not (here / ".judgekeeper" / "marks.jsonl").exists()
    assert pages[0] == []


# No marking started -----------------------------------------------------------------------

def test_no_marking_started_opens_the_page_and_prints_its_link(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert _check(out, err) == NEXT_A
    url = label.open_page(here / ".judgekeeper")
    assert out.splitlines()[2:6] == [
        f"Marking page: {url}",
        "It shows one answer at a time. Your judge's verdict is hidden.",
        "Marked so far: 0 (0 Pass, 0 Fail). A first result needs 15 Pass and 15 Fail.",
        ""]
    ws = start_label.Workspace(here)
    assert marks.read(ws.marks).header["pool"] == {"pass": 20, "fail": 16}
    assert (ws.dir / "judge.json").is_file() and (ws.dir / "judge-check.json").is_file()


def test_the_page_starts_with_the_flags_given(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    records_project(here, split(16, 16))
    code, out, _ = run(capsys, "mark", "--tool", "promptfoo", "--port", "0", "--no-browser")
    assert code == 0, out
    args = pages[0][0]
    assert args[:3] == [".", "--tool", "promptfoo"]
    assert {"--port", "0", "--no-browser", "--yes"} <= set(args)
    assert "--new" not in args and "--stop" not in args
    assert _check(out) == NEXT_A.replace("`judgekeeper mark`",
                                         "`judgekeeper mark --tool promptfoo --port 0 "
                                         "--no-browser`")


def test_too_few_answers_are_marked_anyway(here, capsys, pages):
    promptfoo_project(here, split(6, 4))
    code, out, _ = run(capsys, "mark")
    assert code == 0, out
    assert "Marked so far: 0 (0 Pass, 0 Fail)." in out


def test_no_clear_verdict_means_nothing_to_mark(here, capsys, pages):
    promptfoo_project(here, [None] * 6)
    code, out, _ = run(capsys, "mark")
    assert code == 0
    assert "nothing to mark" in out
    assert _check(out).startswith("Next: nothing.")
    assert pages[0] == []


# Marking started, fewer than 15 + 15 ------------------------------------------------------

def test_marking_started_reopens_the_page_with_the_count(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    started, _ = pages
    ws = start_label.Workspace(here)
    _click(ws, 10)  # the queue's first block of 10: 5 of the judge's passes, 5 of its fails
    code, out, err = run(capsys, "mark")
    assert code == 0
    assert len(started) == 1  # the open page is reused
    assert "Marked so far: 10 (5 Pass, 5 Fail). A first result needs 15 Pass and 15 Fail." in out
    assert f"Marking page: {label.open_page(ws.dir)}" in out
    assert _check(out, err) == NEXT_A


def test_a_closed_page_is_started_again(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    started, _ = pages
    ws = start_label.Workspace(here)
    _click(ws, 10)
    assert background.stop(ws.dir)
    code, out, _ = run(capsys, "mark")
    assert code == 0 and len(started) == 2
    assert "Marked so far: 10 (5 Pass, 5 Fail)." in out


# At least 15 Pass + 15 Fail ---------------------------------------------------------------

def test_enough_marks_print_the_result(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws)
    url = label.open_page(ws.dir)
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert _check(out, err) == NEXT_B
    lines = out.splitlines()
    assert lines[2] == ("Your marks: 36 (20 Pass, 16 Fail), made on the page in 1 sitting, "
                        "about 7 seconds each.")
    assert "Of the answers you passed, your judge passed 100% (range" in out
    assert "Of the answers you failed, your judge failed 100% (range" in out
    assert "Kappa (agreement beyond chance): 1.00." in out
    assert "This set can see a drop of 40 points or more. Smaller changes need more marks." \
        in out
    assert "Report: .judgekeeper/report.html" in out
    assert f"The page is still open if they want to mark more: {url}" in out
    assert len(pages[0]) == 1  # no page started for the result
    assert (ws.dir / "report.html").is_file()


def test_the_result_without_an_open_page_has_no_link(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws)
    background.stop(ws.dir)
    code, out, _ = run(capsys, "mark")
    assert code == 0 and "still open" not in out and "http://" not in out
    assert len(pages[0]) == 1


def test_a_judge_that_passes_too_many_is_said(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    failed = 0
    for item in session.items:  # the person fails 5 of the judge's passes
        said = groups[item["id"]]
        if said == "pass" and failed < 5:
            said, failed = "fail", failed + 1
        session.update({"id": item["id"], "label": said, "seconds": 5})
    code, out, _ = run(capsys, "mark")
    assert code == 0
    assert "Your marks: 36 (15 Pass, 21 Fail)" in out
    assert "\nYour judge passes too many answers you failed.\n" in out


# Marking started on other results ---------------------------------------------------------

def test_a_new_eval_run_asks_to_start_over(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws, 6)
    background.stop(ws.dir)
    promptfoo_project(here, split(18, 18), tag=" new" + TAG)
    before = sorted(p.name for p in ws.dir.iterdir())
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert "Your marks are for other results" in out
    assert f"  1. {START_OVER}" in out
    assert _check(out, err) == (
        "Next: ask the person this question. If they say yes, run `judgekeeper mark --yes`. If "
        "they say no, ask them to run `judgekeeper mark` in a terminal.")
    assert sorted(p.name for p in ws.dir.iterdir()) == before  # nothing moved
    code, out, _ = run(capsys, "mark", "--yes")
    assert code == 0, out
    previous = [p for p in ws.dir.iterdir() if p.name.startswith("previous-")]
    assert len(previous) == 1 and (previous[0] / "marks.jsonl").is_file()
    assert marks.read(ws.marks).header["pool"] == {"pass": 18, "fail": 18}
    assert "Marked so far: 0 (0 Pass, 0 Fail)." in out


def test_another_judge_asks_to_start_over(here, capsys, pages):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    assert run(capsys, "mark", "--metric", "helpfulness")[0] == 0
    code, out, _ = run(capsys, "mark", "--metric", "safety")
    assert code == 3
    assert "Your marks are for other results" in out and "helpfulness" in out
    assert START_OVER in out


def test_marks_from_0_2_are_never_used(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    folder = here / ".judgekeeper"
    folder.mkdir()
    (folder / "labels.csv").write_text("id,input,output,human_label,notes\n", encoding="utf-8")
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert ".judgekeeper/labels.csv holds marks from judgekeeper 0.2" in out
    assert START_OVER in out
    _check(out, err)
    assert (folder / "labels.csv").is_file() and not (folder / "marks.jsonl").exists()
    code, out, _ = run(capsys, "mark", "--yes")
    assert code == 0
    assert not (folder / "labels.csv").exists()
    assert any((p / "labels.csv").is_file() for p in folder.glob("previous-*"))


def test_start_over_now_is_asked_first(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws, 4)
    code, out, _ = run(capsys, "mark", "--new")
    assert code == 3 and START_OVER in out
    assert "`judgekeeper mark --new --yes`" in next_lines(out)[0]
    assert not list(ws.dir.glob("previous-*"))
    code, out, _ = run(capsys, "mark", "--new", "--yes")
    assert code == 0, out
    assert len(list(ws.dir.glob("previous-*"))) == 1
    assert "Marked so far: 0 (0 Pass, 0 Fail)." in out
    assert label.open_page(ws.dir)  # the old page was closed, a new one opened


# The judge changed since marking started --------------------------------------------------

def test_a_changed_rule_carries_on_and_says_which_judge(here, capsys, pages):
    promptfoo_project(here, split(20, 16), rubric="Is polite.")
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws)
    promptfoo_project(here, split(20, 16), rubric="Is polite and short.")
    code, out, _ = run(capsys, "mark")
    assert code == 0, out
    head = marks.read(ws.marks).header
    assert re.search(r"This result is about your judge as it was on \d{1,2} [A-Z][a-z]{2}: "
                     r"openai:gpt-4\.1-mini, rule hash [0-9a-f]{4}\.", out), out
    assert head["judge"]["rule_hash"][7:11] in out
    assert _check(out) == NEXT_B


# The page could not start -----------------------------------------------------------------

def test_a_page_that_cannot_start_is_said_in_one_line(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    pages[1]["fail"] = True
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert _check(out, err) == COULD_NOT
    said = [line for line in out.splitlines()[2:] if line and not line.startswith("Next:")]
    assert said == [("The marking page could not start in the background (what went wrong is "
                     "in .judgekeeper/page.log).")]


# --stop and --wait ------------------------------------------------------------------------

def test_stop_closes_the_open_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    folder = here / ".judgekeeper"
    assert label.open_page(folder)
    code, out, _ = run(capsys, "mark", "--stop")
    assert code == 0
    assert "Closed the marking page. Your marks are saved." in out
    assert _check(out).startswith("Next: nothing.")
    assert label.open_page(folder) is None
    code, out, _ = run(capsys, "mark", "--stop")
    assert code == 0 and "No marking page is open." in out
    _check(out)


def test_wait_serves_the_page_in_this_terminal(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    done = {}
    thread = threading.Thread(target=lambda: done.update(code=main(["mark", "--wait",
                                                                    "--port", "0"])))
    thread.start()
    folder = here / ".judgekeeper"
    for _ in range(100):
        if label.open_page(folder):
            break
        thread.join(0.1)
    url = label.open_page(folder)
    assert url and pages[0] == []  # served here, not in the background
    assert background.stop(folder)
    thread.join(timeout=10)
    assert done == {"code": 0}
    out = capsys.readouterr().out
    assert f"Marking page: {url}" in out
    assert "To stop it: Ctrl-C." in out
    assert len(next_lines(out)) == 1


def test_wait_reuses_an_open_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    url = label.open_page(here / ".judgekeeper")
    code, out, _ = run(capsys, "mark", "--wait")
    assert code == 0 and f"Marking page: {url}" in out
    _check(out)


def test_mark_is_in_the_help(capsys):
    assert main(["--help"]) == 0
    assert re.search(r"^\s+mark\s", capsys.readouterr().out, re.MULTILINE)


def test_the_marks_file_holds_no_text(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    _click(start_label.Workspace(here))
    text = (here / ".judgekeeper" / "marks.jsonl").read_text(encoding="utf-8")
    assert TAG.strip() not in text
    assert all(json.loads(x) for x in text.splitlines())


def test_start_marks_on_the_same_file(here, capsys, pages):
    """`judgekeeper start` keeps working on marks.jsonl until later steps replace it."""
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws)
    session = start_label.StartSession(ws)
    r = start_label.save_result(ws, session, say=lambda line: None)
    assert r["labels"] == {"correct": 20, "wrong": 16}
    assert start.ROUGH == 15


def test_the_result_keeps_the_start_command_for_starts_next_steps(here, capsys, pages):
    """`judgekeeper start` builds --review and --fix from the command a result keeps."""
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark", "--port", "0")
    ws = start_label.Workspace(here)
    _click(ws)
    run(capsys, "mark", "--port", "0")
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["command"] == "judgekeeper start --port 0"
    page = ws.report_html.read_text(encoding="utf-8")
    assert "judgekeeper mark --review" not in page
