"""`judgekeeper` does the next step: what is in the project decides it. Every row of its state
table, without a terminal: the output, exactly one `Next:` line at the end, the exit code, and
no answer text. The page opens in the person's browser; its link is printed only when no
browser opens, and marks made through a link printed for a coding agent are stamped.

The page is served in a thread here (conftest.pages); test_page_token.py runs it as its own
process.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import __version__, background, label, marks, page, start_label
from tests.start_projects import promptfoo_project, records_project, split
from tests.test_front import assert_one_next_at_the_end, next_lines, run

TAG = " SECRET-7f3a"  # in every question and answer: a leak shows
OPEN = "The marking page is open in your browser."
NEXT_OPEN = ("Next: tell the person the marking page is open in their browser, and to mark "
             "answers until the page says it has enough. When they say they are done, run "
             "`judgekeeper` again.")
NEXT_LINK = ("Next: give the person the link above and ask them to mark answers until the "
             "page says it has enough. When they say they are done, run `judgekeeper` again.")
NEXT_RESULT = ("Next: nothing. Tell the person the result above. To mark more, run "
               "`judgekeeper mark`.")
RAN_AGAIN = "Your eval ran again. Your judge is the same, so your marks still test it."
NO_BROWSER = ("judgekeeper could not open a browser, so the link is printed here, where your "
              "coding agent can read it.")
PRINTED_LINE = "{n} of your marks were made through a link your coding agent could read."
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
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

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
        "Found your eval tool: promptfoo (results.json, 36 answers)",
        ('Your judge: openai:gpt-4.1-mini, rule "Is polite and correct. Second line of the '
         'rubric."'),
        "Your judge passed 20 and failed 16.",
        "",
        "Checked first (no AI call):",
        "  Your judge made a real decision on every answer.",
        "",
        OPEN,
        "It shows one answer at a time. Your judge's verdict is hidden.",
        "Marked so far: 0. A first result needs 15 Pass and 15 Fail.",
        "",
        NEXT_OPEN]
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
        "Next: ask the person which eval tool's results to check (records, promptfoo), then "
        "run `judgekeeper --tool NAME`.")
    assert pages[0] == [] and not (here / ".judgekeeper" / "start.json").exists()


def test_too_few_answers_is_asked_as_today(here, capsys, pages):
    promptfoo_project(here, split(6, 4))
    code, out, _ = run(capsys)
    assert code == 3
    assert _check(out).endswith("or to mark these 10 now: run `judgekeeper mark`.")
    assert pages[0] == []


def test_nothing_found_is_said_as_today(here, capsys, pages):
    code, out, _ = run(capsys)
    assert code == 3 and "No saved eval results found" in out
    assert pages[0] == []


# Marking started, under 15 + 15 -------------------------------------------------------------

def test_marking_started_opens_the_page_again_with_the_count(here, capsys, pages):
    promptfoo_project(here, split(20, 16), tag=TAG)
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, 10)  # the queue's first block of 10: 5 of the judge's passes, 5 of its fails
    code, out, err = run(capsys)
    assert code == 0, out
    assert _check(out, err) == NEXT_OPEN
    assert out.splitlines()[2:] == [
        "Marking answers for your judge: openai:gpt-4.1-mini (promptfoo, results.json).",
        "",
        OPEN,
        "It shows one answer at a time. Your judge's verdict is hidden.",
        "Marked so far: 10 (5 Pass, 5 Fail). A first result needs 15 Pass and 15 Fail.",
        "",
        NEXT_OPEN]
    assert "Found your eval tool" not in out and "Checked first" not in out
    assert len(pages[0]) == 2  # the open page was replaced by a new one


def test_with_several_judges_the_marking_line_names_the_metric(here, capsys, pages):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    run(capsys, "--metric", "safety")
    code, out, _ = run(capsys, "--metric", "safety")
    assert code == 0, out
    line = out.splitlines()[2]
    assert line.startswith("Marking answers for your judge: safety, claude-opus-5 "
                           "(judgekeeper.record(), "), line


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
    assert lines[2] == ("Your marks: 36 (20 Pass, 16 Fail), made on the page in 1 sitting, "
                        "about 7 seconds each.")
    assert "Of the answers you passed, your judge passed 100% (range" in out
    assert "Of the answers you failed, your judge failed 100% (range" in out
    assert "Kappa (agreement beyond chance): 1.00." in out
    assert "This set can see a drop of 40 points or more." in out
    assert "Report: .judgekeeper/report.html" in out
    assert "The marking page is still open, if they want to mark more." in out
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
    assert len(pages[0]) == 1


def test_a_judge_that_passes_too_many_is_said(here, capsys, pages):
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
    assert "Your marks: 36 (15 Pass, 21 Fail)" in out
    assert "\nYour judge passes too many answers you failed.\n" in out


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
                     r"openai:gpt-4\.1-mini, rule hash [0-9a-f]{4}\.", out), out
    assert head["judge"]["rule_hash"][7:11] in out
    assert "\nYour judge changed since your marks: rule changed.\n" in out
    assert _check(out) == "Next: run `judgekeeper check`."


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

def test_from_a_promptfoo_project_the_agent_runs_judgekeeper_twice(here, capsys, pages):
    """The agent pastes "Run `uvx judgekeeper` and follow what it says" and does what each
    Next: line says. From the first run to the result it runs exactly `judgekeeper` twice; the
    person's marking is the only other step."""
    promptfoo_project(here, split(20, 16), tag=TAG)
    ran, argv, person_marked = [], [], 0
    while len(ran) < 5:
        ran.append(["judgekeeper", *argv])
        code, out, err = run(capsys, *argv)
        assert code == 0, out + err
        said = _check(out, err)
        if said.startswith("Next: nothing."):
            break
        if "tell the person" in said:
            _click(start_label.Workspace(here))  # the person marks until the page has enough
            person_marked += 1
        (command,) = re.findall(r"run `(judgekeeper[^`]*)`", said)
        argv = command.split()[1:]
    assert ran == [["judgekeeper"], ["judgekeeper"]]
    assert person_marked == 1
    assert "Of the answers you passed, your judge passed" in out


# Marks for another judge, or from 0.2 -----------------------------------------------------

def test_another_judge_asks_to_start_over(here, capsys, pages):
    records_project(here, split(16, 16), name="helpfulness")
    records_project(here, split(16, 16), name="safety", pid=4102)
    assert run(capsys, "--metric", "helpfulness")[0] == 0
    code, out, err = run(capsys, "--metric", "safety")
    assert code == 3
    assert "Your marks are for other results" in out and "helpfulness" in out
    assert f"  1. {START_OVER}" in out
    assert _check(out, err) == (
        "Next: ask the person this question. If they say yes, run `judgekeeper --metric safety "
        "--yes`. If they say no, ask them to run `judgekeeper --metric safety` in a terminal.")
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
    assert ".judgekeeper/labels.csv holds marks from judgekeeper 0.2" in out
    assert START_OVER in out
    _check(out, err)
    assert pages[0] == []


def test_new_starts_over_after_a_yes(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, 4)
    code, out, _ = run(capsys, "--new")
    assert code == 3 and START_OVER in out
    assert "`judgekeeper --new --yes`" in next_lines(out)[0]
    code, out, _ = run(capsys, "--new", "--yes")
    assert code == 0, out
    assert len(list(ws.dir.glob("previous-*"))) == 1
    assert "Marked so far: 0." in out


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
    assert START_OVER not in out and "other results" not in out
    assert out.count(RAN_AGAIN) == 1
    assert "Marked so far: 6 (" in out
    assert _check(out, err) == NEXT_OPEN
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
    assert out.count(RAN_AGAIN) == 1
    assert "Your marks: 36 (20 Pass, 16 Fail)" in out
    assert _check(out) == NEXT_RESULT


def test_the_same_results_say_nothing_about_running_again(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    _click(start_label.Workspace(here), 4)
    code, out, _ = run(capsys)
    assert code == 0 and RAN_AGAIN not in out


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
    assert _check(out).startswith("Next: nothing.")
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
    assert "start" not in out.split("Commands:")[1]


def test_start_still_works(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    _click(start_label.Workspace(here))
    assert run(capsys)[0] == 0  # the result
    code, out, _ = run(capsys, "start", "--no-browser")
    assert code in (0, 8), out
    assert "Your last result" in out


# The printed link: the fallback -----------------------------------------------------------

def test_no_browser_without_a_terminal_prints_the_link_and_stamps_the_marks(here, capsys,
                                                                             pages):
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    lines = out.splitlines()
    assert NO_BROWSER in lines
    link = lines[lines.index(NO_BROWSER) + 1]
    assert link.startswith("Marking page: http://127.0.0.1:") and "token=" in link
    assert assert_one_next_at_the_end(out) == NEXT_LINK.replace(
        "`judgekeeper`", "`judgekeeper --no-browser`")
    url = link.removeprefix("Marking page: ")
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
    assert NO_BROWSER in out and "Marking page: http://127.0.0.1:" in out
    assert OPEN not in out
    assert assert_one_next_at_the_end(out) == NEXT_LINK


def test_the_result_counts_marks_made_through_a_printed_link(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    _, out, _ = run(capsys, "--no-browser")
    url = next(x for x in out.splitlines() if x.startswith("Marking page: "))
    ws = start_label.Workspace(here)
    _post_marks(url.removeprefix("Marking page: "), ws, 2)
    run(capsys)  # a new page, opened in the browser: its marks are not stamped
    _click(ws, first=2)
    code, out, _ = run(capsys)
    assert code == 0, out
    assert PRINTED_LINE.format(n=2) in out


def test_at_a_terminal_a_printed_link_is_not_stamped(here, capsys, pages, monkeypatch):
    monkeypatch.setattr(page, "terminal", lambda: True)
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    assert NO_BROWSER not in out
    link = next(x for x in out.splitlines() if x.startswith("Marking page: "))
    ws = start_label.Workspace(here)
    _post_marks(link.removeprefix("Marking page: "), ws, 3)
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
    assert _check(out, err) == ("Next: ask the person to run judgekeeper --wait in their own "
                                "terminal (it keeps the page open there).")


# The page says what to do when it has enough -----------------------------------------------

def test_the_page_says_to_tell_the_agent_when_it_has_enough(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    from judgekeeper import page

    session = page.marking_session(ws)
    assert "tell your coding agent" not in session.summary()["status"]["text"]
    _click(ws)
    status = page.marking_session(ws).summary()["status"]
    assert status["ready"]
    assert status["text"].endswith("When you're done, tell your coding agent, or run "
                                   "judgekeeper in your terminal.")


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
