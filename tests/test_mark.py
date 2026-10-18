"""`judgekeeper mark`: for marking more. It opens the page in every state except "something
must be asked" and "start over", and prints the count so far; the result is `judgekeeper`'s
(test_loop.py). Every row, without a terminal: the output, exactly one `Next:` paragraph at
the end, the exit code, and no answer text.

The page itself starts in the background (test_mark_background.py runs it as a real
process); here it is served in a thread (conftest.pages).
"""

from __future__ import annotations

import json
import threading

import pytest

from judgekeeper import __version__, background, label, marks, page, start, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, records_project, save_result, split
from tests.test_front import assert_one_next_at_the_end, next_lines, run

TAG = " SECRET-7f3a"  # in every question and answer: a leak shows
OPEN = "The marking page is open in your browser."
NEXT_OPEN = 'Next: mark until "See your result" appears, then click it.'
NEXT_LINK = NEXT_OPEN
NEXT_KEEP = 'Next: keep marking until "See your result" appears, then click it.'
NEXT_MORE = "Next: mark more answers, then run `judgekeeper` to see your updated result."
LINK = "Open this link in your browser to mark answers:"
COULD_NOT = ("Next: run `judgekeeper mark --wait` in your own terminal (it keeps the page open "
             "there).")
START_OVER = ("Start over with these results? Your old marks move to "
              ".judgekeeper/previous-<date>/.")
ADDED = "Your newest results have {n} answers you haven't seen. They're added for marking."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _flat(out: str) -> str:
    return " ".join(out.split())


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
        "Next: choose which eval tool's results to check (records, promptfoo), then run "
        "`judgekeeper mark --tool NAME`.")
    assert not (here / ".judgekeeper" / "marks.jsonl").exists()
    assert pages[0] == []


# No marking started -----------------------------------------------------------------------

def test_no_marking_started_opens_the_page(here, capsys, pages, no_browser):
    promptfoo_project(here, split(20, 16), tag=TAG)
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert _check(out, err) == NEXT_OPEN
    assert out.splitlines()[2:] == [
        "Step 2 of 5: Mark",
        "",
        "The marking page is open in your browser. It shows the answers",
        "one at a time. Mark each one Pass or Fail, the way you want your",
        "judge to decide. Your judge's grade stays hidden.",
        "",
        'Next: mark until "See your result" appears, then click it.']
    assert len(no_browser) == 1 and label.is_open(here / ".judgekeeper")
    ws = start_label.Workspace(here)
    assert marks.read(ws.marks).header["pool"] == {"pass": 20, "fail": 16}
    assert (ws.dir / "judge.json").is_file() and (ws.dir / "judge-check.json").is_file()


def test_the_page_starts_with_the_commands_of_the_flags_given(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    records_project(here, split(16, 16))
    code, out, _ = run(capsys, "mark", "--tool", "promptfoo", "--port", "0", "--no-browser")
    assert code == 0, out
    settings = pages[0][0]
    assert settings["root"] == str(here.resolve())
    assert settings["port"] == 0
    # the page says how to come back to it: `judgekeeper mark`, with the flags given
    assert settings["command"] == "judgekeeper mark --tool promptfoo --port 0 --no-browser"
    assert settings["start_command"] == "judgekeeper --tool promptfoo --port 0 --no-browser"
    assert _check(out) == NEXT_LINK.replace(
        "`judgekeeper`", "`judgekeeper --tool promptfoo --port 0 --no-browser`")


def test_too_few_answers_are_marked_anyway(here, capsys, pages):
    promptfoo_project(here, split(6, 4))
    code, out, _ = run(capsys, "mark")
    assert code == 0, out
    assert "Step 2 of 5: Mark" in out and "You marked" not in out


def test_no_clear_verdict_means_nothing_to_mark(here, capsys, pages):
    promptfoo_project(here, [None] * 6)
    code, out, _ = run(capsys, "mark")
    assert code == 3
    assert "nothing to mark" in _flat(out)
    assert _check(out) == ("Next: fix your judge, run your eval again, then run "
                           "`judgekeeper mark`.")
    assert pages[0] == []


# Marking started --------------------------------------------------------------------------

def test_marking_started_shows_the_open_page_with_the_count(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    started, _ = pages
    ws = start_label.Workspace(here)
    _click(ws, 10)  # the queue's first block of 10: 5 of the judge's passes, 5 of its fails
    code, out, err = run(capsys, "mark")
    assert code == 0
    assert len(started) == 1  # the open page is kept: its tab and link still work
    assert "You marked 10 answers so far: 5 Pass, 5 Fail." in out
    assert "That's not enough for a result yet." in out
    assert "The marking page is open in your browser. The bar at the top" in out
    assert _check(out, err) == NEXT_KEEP


def test_a_closed_page_is_started_again(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    started, _ = pages
    ws = start_label.Workspace(here)
    _click(ws, 10)
    assert background.stop(ws.dir)
    code, out, _ = run(capsys, "mark")
    assert code == 0 and len(started) == 2
    assert "You marked 10 answers so far: 5 Pass, 5 Fail." in out


def test_enough_marks_open_the_page_and_leave_the_result_to_judgekeeper(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws, 34)  # enough, with 2 answers left to mark
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert "Step 2 of 5: Mark (more answers)" in out
    assert "You marked 34 answers so far: " in out and "not enough" not in out
    assert "Each new mark makes your numbers more precise." in _flat(out)
    assert "Your marks:" not in out and "Kappa" not in out
    assert _check(out, err) == NEXT_MORE
    assert len(pages[0]) == 1  # the open page, kept


def test_every_answer_marked_after_a_result_points_to_mark(here, capsys, pages):
    """With a result already made and every answer marked, `mark` points to running the eval
    on more questions, then `judgekeeper mark`: the new answers join as a batch."""
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    _click(start_label.Workspace(here))
    code, out, err = run(capsys)
    assert code == 0 and "Step 3 of 5: Measure" in out, out
    assert (here / ".judgekeeper" / "result.json").is_file()
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert "You have marked all 36 answers. There are no more to mark." in out
    assert _check(out, err) == (
        "Next: run your eval on more questions, then run `judgekeeper mark`: the new answers "
        "join the ones you marked.")
    assert "again to get new answers" not in out
    assert len(pages[0]) == 1  # no page opened for it


def test_every_answer_marked_opens_no_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    _click(start_label.Workspace(here))
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert "You have marked all 36 answers. There are no more to mark." in out
    assert _check(out, err) == (  # new answers join as a batch once the eval ran again
        "Next: run your eval on more questions, then run `judgekeeper mark`: the new answers "
        "join the ones you marked.")
    assert "run your eval again to get new answers" not in out
    assert len(pages[0]) == 1


# Marks for another judge, or from 0.2: start over -----------------------------------------

def test_a_new_eval_run_goes_on_with_the_marks(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws, 6)
    promptfoo_project(here, split(18, 18), tag=" new" + TAG)
    code, out, err = run(capsys, "mark")
    assert code == 0, out
    assert START_OVER not in _flat(out)
    assert ADDED.format(n=36) in _flat(out)  # the new answers join as a second batch
    assert "You marked 6 answers so far: " in out
    assert marks.read(ws.marks).header["pool"] == {"pass": 20, "fail": 16}
    assert len(ws.data()["queue"]) == 72
    assert _check(out, err) == NEXT_KEEP


def test_another_judge_asks_to_start_over(here, capsys, pages):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    assert run(capsys, "mark", "--metric", "helpfulness")[0] == 0
    code, out, err = run(capsys, "mark", "--metric", "safety")
    assert code == 3
    assert "Your marks are for other results" in _flat(out) and "helpfulness" in out
    assert f"1. {START_OVER}" in _flat(out)
    assert _check(out, err) == (
        "Next: run `judgekeeper mark --metric safety` in a terminal to answer, or "
        "`judgekeeper mark --metric safety --yes` to say yes.")
    code, out, _ = run(capsys, "mark", "--metric", "safety", "--yes")
    assert code == 0, out
    ws = start_label.Workspace(here)
    previous = [p for p in ws.dir.iterdir() if p.name.startswith("previous-")]
    assert len(previous) == 1 and (previous[0] / "marks.jsonl").is_file()
    assert "You marked" not in out and "It shows the answers one at a time." in _flat(out)


def test_marks_from_0_2_are_never_used(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    folder = here / ".judgekeeper"
    folder.mkdir()
    (folder / "labels.csv").write_text("id,input,output,human_label,notes\n", encoding="utf-8")
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert ".judgekeeper/labels.csv holds marks from an older judgekeeper" in _flat(out)
    assert START_OVER in _flat(out)
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
    assert code == 3 and START_OVER in _flat(out)
    assert "`judgekeeper mark --new --yes`" in next_lines(out)[0]
    assert not list(ws.dir.glob("previous-*"))
    code, out, _ = run(capsys, "mark", "--new", "--yes")
    assert code == 0, out
    assert len(list(ws.dir.glob("previous-*"))) == 1
    assert "You marked" not in out
    assert label.is_open(ws.dir)  # the old page was closed, a new one opened


# The page could not start -----------------------------------------------------------------

def test_a_page_that_cannot_start_is_said_in_one_line(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    pages[1]["fail"] = True
    code, out, err = run(capsys, "mark")
    assert code == 3
    assert _check(out, err) == COULD_NOT
    said = out[:out.index("Next:")].splitlines()[2:]
    assert [line for line in said if line] == [
        "Step 2 of 5: Mark",
        ("The marking page could not start in the background (what went wrong is in "
         ".judgekeeper/page.log).")]


# --stop and --wait ------------------------------------------------------------------------

def test_stop_closes_the_open_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    folder = here / ".judgekeeper"
    assert label.is_open(folder)
    code, out, _ = run(capsys, "mark", "--stop")
    assert code == 0
    assert "Closed the marking page." in out and "marks are saved" not in out
    assert _check(out) == "Next: run `judgekeeper mark` when you want to continue."
    assert not label.is_open(folder)
    code, out, _ = run(capsys, "mark", "--stop")
    assert code == 0 and "No marking page is open." in out
    _check(out)


def _wait_in_a_thread(here, *argv):
    """`mark --wait` in a thread, once its own page is open (a page open before is replaced)."""
    done = {}
    folder = here / ".judgekeeper"
    before = label.read_lock(folder)
    thread = threading.Thread(target=lambda: done.update(code=main(["mark", "--wait",
                                                                    "--port", "0", *argv])),
                              daemon=True)
    thread.start()
    for _ in range(100):
        lock = label.read_lock(folder)
        if lock is not None and lock != before and label.is_open(folder):
            break
        thread.join(0.1)
    return thread, done


def test_wait_serves_the_page_in_this_process(here, capsys, pages, no_browser):
    promptfoo_project(here, split(20, 16))
    thread, done = _wait_in_a_thread(here)
    folder = here / ".judgekeeper"
    assert label.is_open(folder) and pages[0] == []  # served here, not in the background
    assert background.stop(folder)
    thread.join(timeout=10)
    assert done == {"code": 0}
    out = capsys.readouterr().out
    assert OPEN in out and len(no_browser) == 1
    assert "token=" not in out
    assert "The page stays open while this runs. To stop it: Ctrl-C." in out
    assert len(next_lines(out)) == 1


def test_wait_at_a_terminal_prints_the_link(here, capsys, pages, no_browser, monkeypatch):
    monkeypatch.setattr(page, "terminal", lambda: True)
    promptfoo_project(here, split(20, 16))
    thread, _ = _wait_in_a_thread(here)
    assert background.stop(here / ".judgekeeper")
    thread.join(timeout=10)
    out = capsys.readouterr().out
    assert f"{LINK}\n{no_browser[0]}\n" in out


def test_wait_replaces_an_open_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    first = pages[0][0]
    thread, done = _wait_in_a_thread(here)
    folder = here / ".judgekeeper"
    assert label.is_open(folder) and pages[0] == [first]
    assert background.stop(folder)
    thread.join(timeout=10)
    assert done == {"code": 0}


def test_mark_is_in_the_help(capsys):
    assert main(["--help"]) == 0
    assert "  mark " in capsys.readouterr().out


def test_the_marks_file_holds_no_text(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys, "mark")
    _click(start_label.Workspace(here))
    text = (here / ".judgekeeper" / "marks.jsonl").read_text(encoding="utf-8")
    assert TAG.strip() not in text
    assert all(json.loads(x) for x in text.splitlines())


def test_start_marks_on_the_same_file(here, capsys, pages):
    """A result made from marks.jsonl, as `judgekeeper` makes it."""
    promptfoo_project(here, split(20, 16))
    run(capsys, "mark")
    ws = start_label.Workspace(here)
    _click(ws)
    session = start_label.StartSession(ws)
    r = save_result(ws, session, say=lambda line: None)
    assert r["labels"] == {"correct": 20, "wrong": 16}
    assert start.ROUGH == 15
