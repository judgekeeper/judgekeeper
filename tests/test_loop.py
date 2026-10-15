"""`judgekeeper` does the next step: what is in the project decides it. Every row of its state
table, without a terminal: the output, exactly one `Next:` paragraph at the end, the exit code,
and no answer text. The page opens in the person's browser; its link is printed only when no
browser opens (or with --no-browser), and marks made through a link printed without a terminal
are stamped.

The page is served in a thread here (conftest.pages); test_page_token.py runs it as its own
process.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import __version__, background, label, marks, page, start_label
from tests.page_http import retried
from tests.start_projects import promptfoo_project, records_project, split
from tests.test_front import assert_one_next_at_the_end, next_lines, run

TAG = " SECRET-7f3a"  # in every question and answer: a leak shows
OPEN = "The marking page is open in your browser."
NEXT_OPEN = "Next: mark until the page says you have enough, then run `judgekeeper` again."
NEXT_LINK = NEXT_OPEN
NEXT_KEEP = ("Next: keep marking until the page says you have enough, then run `judgekeeper` "
             "again.")
NEXT_RESULT = ("Next: nothing to do. When you change your judge or update your eval tool, run "
               "`judgekeeper check`.")
RAN_AGAIN = "Your eval ran again. Your judge is the same, so your marks still test it."
LINK = "Open this link in your browser to mark answers:"
PRINTED_LINE = ("{n} of your marks were made through a link printed where another program "
                "could read it.")
START_OVER = ("Start over with these results? Your old marks move to "
              ".judgekeeper/previous-<date>/.")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def browser_fails(monkeypatch):
    """No browser can be opened (webbrowser.open returns False)."""
    tried = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: tried.append(url) and False)
    return tried


def _flat(out: str) -> str:
    return " ".join(out.split())


def _link(out: str) -> str:
    """The page's link: the line after LINK."""
    lines = out.splitlines()
    return lines[lines.index(LINK) + 1]


def _check(out: str, err: str = "") -> str:
    assert TAG.strip() not in out + err
    assert "token=" not in out + err
    assert out.startswith(f"judgekeeper {__version__}\n\n"), out
    return assert_one_next_at_the_end(out)


def _click(ws, n=None, seconds=7, first=0):
    """The person marks answers first to n on the page, as the judge did."""
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[first:n]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": seconds})


def _post_marks(url: str, ws, n: int, seconds=5) -> int:
    """The person marks the first n answers through the page's link, as the judge did."""
    import urllib.request

    base, token = url.split("/?token=")

    def call(path, body=None):
        req = urllib.request.Request(f"{base}{path}?token={token}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Origin": base})  # as the page sends it

        def send():
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        return retried(send)

    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    items = call("/state")["items"][:n]
    for item in items:
        call("/label", {"id": item["id"], "label": groups[item["id"]], "seconds": seconds})
    return len(items)


# Found, no marking started: output A --------------------------------------------------------

def test_the_first_run_finds_checks_and_opens_the_page(here, capsys, pages, no_browser):
    promptfoo_project(here, split(20, 16), tag=TAG)
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert _check(out, err) == NEXT_OPEN
    assert out.splitlines() == [
        f"judgekeeper {__version__}",
        "",
        "Step 1 of 5: Find",
        "",
        "Eval tool:   promptfoo",
        "Answers:     36 answers from your app, each graded by your judge",
        "             (read from results.json)",
        "Judge:       openai:gpt-4.1-mini",
        'Judge rule:  "Is polite and correct. Second line of the rubric."',
        "",
        "Your judge's grades: 20 Pass, 16 Fail.",
        "Free check (no AI call): every answer got a clear Pass or Fail.",
        "",
        "Step 2 of 5: Mark",
        "",
        "The marking page is open in your browser. It shows the same",
        "answers one at a time. Mark each one Pass or Fail, the way you",
        "want your judge to decide. Your judge's grade stays hidden, so",
        "you decide on your own.",
        "",
        "Next: mark until the page says you have enough, then run",
        "`judgekeeper` again."]
    assert len(pages[0]) == 1 and len(no_browser) == 1
    assert label.is_open(here / ".judgekeeper")
    ws = start_label.Workspace(here)
    assert marks.read(ws.marks).header["pool"] == {"pass": 20, "fail": 16}
    assert ws.start.is_file() and ws.pool.is_file()
    assert (ws.dir / "judge.json").is_file() and (ws.dir / "judge-check.json").is_file()


def test_a_question_is_asked_as_today(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    records_project(here, split(16, 16))
    code, out, err = run(capsys)
    assert code == 3
    assert _check(out, err) == (
        "Next: choose which eval tool's results to check (records, promptfoo), then run "
        "`judgekeeper --tool NAME`.")
    assert pages[0] == [] and not (here / ".judgekeeper" / "start.json").exists()


def test_too_few_answers_is_asked_as_today(here, capsys, pages):
    promptfoo_project(here, split(6, 4))
    code, out, _ = run(capsys)
    assert code == 3
    assert _check(out).endswith("or mark these 10 now with `judgekeeper mark`.")
    assert pages[0] == []


def test_nothing_found_is_said_as_today(here, capsys, pages):
    code, out, _ = run(capsys)
    assert code == 3 and "No eval results found in this folder" in out
    assert pages[0] == []


# Marking started, under 15 + 15 -------------------------------------------------------------

def test_marking_started_keeps_the_open_page_and_says_the_count(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, 10)  # the queue's first block of 10: 5 of the judge's passes, 5 of its fails
    code, out, err = run(capsys)
    assert code == 0, out
    assert _check(out, err) == NEXT_KEEP
    assert out.splitlines()[2:] == [
        "Step 2 of 5: Mark",
        "",
        "You have marked 10 answers so far (5 Pass, 5 Fail).",
        "That is not enough for a first result yet.",
        "",
        "The marking page is still open in your browser. The bar at the",
        "top shows how close you are.",
        "",
        "Next: keep marking until the page says you have enough, then run",
        "`judgekeeper` again."]
    assert "Step 1 of 5" not in out and "Free check" not in out
    assert len(pages[0]) == 1  # the open page stays: its tab still works


# At least 15 Pass + 15 Fail: output B -----------------------------------------------------

def test_enough_marks_print_the_result(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws)
    code, out, err = run(capsys)
    assert code == 0, out
    assert _check(out, err) == NEXT_RESULT
    lines = out.splitlines()
    assert lines[2:4] == ["Step 3 of 5: Measure", ""]
    assert "Your judge vs your marks, on 36 answers:" in lines
    assert "  You passed:  your judge also passed about 100% (could be " in out
    assert "  You failed:  your judge also failed about 100% (could be " in out
    assert "These are estimates from 36 marked answers." in lines
    for gone in ("Your marks:", "Kappa", "can see a drop"):
        assert gone not in out, gone
    assert ("Full report: .judgekeeper/report.html (open it in your browser)") in out
    assert "The marking page is still open if you want to mark more answers." in out
    assert len(pages[0]) == 1  # no page started for the result
    assert (ws.dir / "report.html").is_file()


def test_the_result_without_an_open_page_says_nothing_about_it(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws)
    assert background.stop(ws.dir)
    code, out, _ = run(capsys)
    assert code == 0
    assert "still open" not in out and "http://" not in out
    assert "To mark more answers at any time, run `judgekeeper mark`." in out
    assert len(pages[0]) == 1


def test_a_judge_that_fails_few_of_the_answers_you_failed_is_measured(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    failed = 0
    for item in session.items:  # the person fails 5 of the judge's passes
        said = groups[item["id"]]
        if said == "pass" and failed < 5:
            said, failed = "fail", failed + 1
        session.update({"id": item["id"], "label": said, "seconds": 5})
    code, out, _ = run(capsys)
    assert code == 0
    assert "Your judge vs your marks, on 36 answers:" in out
    assert "  You failed:  your judge also failed about 76% (could be 62% to 89%)" in out


def test_a_changed_rule_carries_on_and_says_which_judge(here, capsys, pages):
    promptfoo_project(here, split(20, 16), rubric="Is polite.")
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws)
    promptfoo_project(here, split(20, 16), rubric="Is polite and short.")
    code, out, _ = run(capsys)
    assert code == 0, out
    head = marks.read(ws.marks).header
    assert re.search(r"This result is about your judge as it was on \d{1,2} [A-Z][a-z]{2}: "
                     r"openai:gpt-4\.1-mini, rule hash [0-9a-f]{4}\.", _flat(out)), out
    assert head["judge"]["rule_hash"][7:11] in out
    assert "\nYour judge changed since your marks: rule changed.\n" in out
    assert _check(out) == ("Next: run `judgekeeper check` to re-check your changed judge on "
                           "your marks.")


def test_the_result_keeps_the_start_command_for_starts_next_steps(here, capsys, pages):
    """`judgekeeper start` builds --review and --fix from the command a result keeps."""
    promptfoo_project(here, split(20, 16))
    run(capsys, "--port", "0")
    ws = start_label.Workspace(here)
    _click(ws)
    run(capsys, "--port", "0")
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["command"] == "judgekeeper start --port 0"


# The exit test: one prompt to a result ----------------------------------------------------

def test_from_a_promptfoo_project_the_person_runs_judgekeeper_twice(here, capsys, pages):
    """The person runs `judgekeeper` and does what each Next: line says. From the first run to
    the result it runs exactly `judgekeeper` twice; marking is the only other step."""
    promptfoo_project(here, split(20, 16), tag=TAG)
    ran, argv, person_marked = [], [], 0
    while len(ran) < 5:
        ran.append(["judgekeeper", *argv])
        code, out, err = run(capsys, *argv)
        assert code == 0, out + err
        said = _check(out, err)
        if said.startswith("Next: nothing"):
            break
        if said.startswith("Next: mark until the page says you have enough"):
            _click(start_label.Workspace(here))  # the person marks until the page has enough
            person_marked += 1
        (command,) = re.findall(r"run `(judgekeeper[^`]*)`", said)
        argv = command.split()[1:]
    assert ran == [["judgekeeper"], ["judgekeeper"]]
    assert person_marked == 1
    assert "  You passed:  your judge also passed about " in out


# Marks for another judge, or from 0.2 -----------------------------------------------------

def test_another_judge_asks_to_start_over(here, capsys, pages):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    assert run(capsys, "--metric", "helpfulness")[0] == 0
    code, out, err = run(capsys, "--metric", "safety")
    assert code == 3
    assert "Your marks are for other results" in _flat(out) and "helpfulness" in out
    assert f"1. {START_OVER}" in _flat(out)
    assert _check(out, err) == (
        "Next: run `judgekeeper --metric safety` in a terminal to answer, or "
        "`judgekeeper --metric safety --yes` to say yes.")
    code, out, _ = run(capsys, "--metric", "safety", "--yes")
    assert code == 0, out
    assert len(list((here / ".judgekeeper").glob("previous-*"))) == 1


def test_marks_from_0_2_ask_to_start_over(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    folder = here / ".judgekeeper"
    folder.mkdir()
    (folder / "labels.csv").write_text("id,input,output,human_label,notes\n", encoding="utf-8")
    code, out, err = run(capsys)
    assert code == 3
    assert ".judgekeeper/labels.csv holds marks from an older judgekeeper" in _flat(out)
    assert START_OVER in _flat(out)
    _check(out, err)
    assert pages[0] == []


def test_new_starts_over_after_a_yes(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, 4)
    code, out, _ = run(capsys, "--new")
    assert code == 3 and START_OVER in _flat(out)
    assert "`judgekeeper --new --yes`" in next_lines(out)[0]
    code, out, _ = run(capsys, "--new", "--yes")
    assert code == 0, out
    assert len(list(ws.dir.glob("previous-*"))) == 1
    assert "You have marked" not in out and "It shows the same answers" in _flat(out)


# A new eval run no longer asks to start over ----------------------------------------------

def test_a_new_eval_run_keeps_the_marks_and_marking_goes_on(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, 6)
    pool = ws.pool.read_text(encoding="utf-8")
    promptfoo_project(here, split(18, 18), tag=" new" + TAG)
    code, out, err = run(capsys)
    assert code == 0, out
    assert START_OVER not in _flat(out) and "other results" not in out
    assert _flat(out).count(RAN_AGAIN) == 1
    assert "You have marked 6 answers so far (" in out
    assert _check(out, err) == NEXT_KEEP
    assert ws.pool.read_text(encoding="utf-8") == pool  # the answers being marked are kept
    assert not list(ws.dir.glob("previous-*"))


def test_after_a_new_eval_run_the_result_goes_on(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws)
    promptfoo_project(here, split(18, 18), tag=" new")
    code, out, _ = run(capsys)
    assert code == 0, out
    assert _flat(out).count(RAN_AGAIN) == 1
    assert "Your judge vs your marks, on 36 answers:" in out
    assert _check(out) == NEXT_RESULT


def test_the_same_results_say_nothing_about_running_again(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    _click(start_label.Workspace(here), 4)
    code, out, _ = run(capsys)
    assert code == 0 and RAN_AGAIN not in _flat(out)


# --stop and --wait ------------------------------------------------------------------------

def test_stop_closes_the_page(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    folder = here / ".judgekeeper"
    assert label.is_open(folder)
    code, out, _ = run(capsys, "--stop")
    assert code == 0
    assert "Closed the marking page." in out
    assert "marks are saved" not in out  # none were made
    assert _check(out) == "Next: run `judgekeeper` when you want to continue."
    assert not label.is_open(folder)
    code, out, _ = run(capsys, "--stop")
    assert code == 0 and "No marking page is open." in out


def test_stop_says_the_marks_are_saved_when_there_are_some(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    _click(start_label.Workspace(here), 4)
    code, out, _ = run(capsys, "--stop")
    assert "Closed the marking page. Your marks are saved." in out
    assert code == 0


def test_the_help_has_the_page_flags_and_hides_start(capsys):
    code, out, _ = run(capsys, "--help")
    assert code == 0
    for flag in ("--port", "--no-browser", "--new", "--wait", "--stop"):
        assert flag in out
    assert "mark" in out
    assert "start" not in out.split("Commands:")[1].split("Options:")[0]


def test_start_still_works(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    _click(start_label.Workspace(here))
    assert run(capsys)[0] == 0  # the result
    code, out, _ = run(capsys, "start", "--no-browser")
    assert code in (0, 3), out
    assert "Your last result" in out


# The printed link: the fallback -----------------------------------------------------------

def test_no_browser_without_a_terminal_prints_the_link_and_stamps_the_marks(here, capsys,
                                                                             pages):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    url = _link(out)
    assert url.startswith("http://127.0.0.1:") and "token=" in url
    assert assert_one_next_at_the_end(out) == NEXT_LINK.replace(
        "`judgekeeper`", "`judgekeeper --no-browser`")
    ws = start_label.Workspace(here)
    assert _post_marks(url, ws, 4) == 4
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    assert len(lines) == 4 and all(x["link"] == "printed" for x in lines)
    assert marks.made(marks.read(ws.marks))["printed"] == 4


def test_a_browser_that_does_not_open_prints_the_link(here, capsys, pages, browser_fails):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0
    assert len(browser_fails) == 1
    assert _link(out).startswith("http://127.0.0.1:")
    assert OPEN not in out
    assert assert_one_next_at_the_end(out) == NEXT_LINK


def test_the_result_counts_marks_made_through_a_printed_link(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    _, out, _ = run(capsys, "--no-browser")
    ws = start_label.Workspace(here)
    _post_marks(_link(out), ws, 2)
    run(capsys, "--stop")
    run(capsys)  # a new page, opened in the browser: its marks are not stamped
    _click(ws, first=2)
    code, out, _ = run(capsys)
    assert code == 0, out
    assert PRINTED_LINE.format(n=2) in _flat(out)


def test_at_a_terminal_a_printed_link_is_not_stamped(here, capsys, pages, monkeypatch):
    monkeypatch.setattr(page, "terminal", lambda: True)
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    ws = start_label.Workspace(here)
    _post_marks(_link(out), ws, 3)
    lines = [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]
    assert len(lines) == 3 and not any("link" in x for x in lines)
    assert marks.made(marks.read(ws.marks))["printed"] == 0


def test_a_page_that_cannot_start_is_said_in_one_line(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    pages[1]["fail"] = True
    code, out, err = run(capsys)
    assert code == 3
    assert ("The marking page could not start in the background (what went wrong is in "
            ".judgekeeper/page.log).") in out
    assert _check(out, err) == ("Next: run `judgekeeper --wait` in your own terminal (it keeps "
                                "the page open there).")


# The page says what to do when it has enough -----------------------------------------------

def test_the_page_says_what_to_run_when_it_has_enough(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    from judgekeeper import page

    session = page.marking_session(ws)
    assert "When you're done" not in session.summary()["status"]["text"]
    _click(ws)
    status = page.marking_session(ws).summary()["status"]
    assert status["ready"]
    assert status["text"].endswith("When you're done, run judgekeeper in your terminal.")


class _Stream:
    def __init__(self, tty: bool):
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize("stdin,stdout,expected", [(True, True, True), (True, False, False),
                                                   (False, True, False)])
def test_a_terminal_needs_both_input_and_output(monkeypatch, stdin, stdout, expected):
    """On Windows the NUL device says it is a terminal: a command run with its input from NUL
    and its output read by an agent is not at a terminal."""
    monkeypatch.setattr("sys.stdin", _Stream(stdin))
    monkeypatch.setattr("sys.stdout", _Stream(stdout))
    assert page.terminal() is expected
