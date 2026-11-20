"""In a CI job judgekeeper opens no marking page and no result page, and no browser.

- CI is one of CI_VARIABLES set to something other than "", "false" or "0" (page.in_ci).
- Having no terminal is not CI: a coding agent runs judgekeeper with none and gets the page.
- Step 2 says one line instead of the opening lines and its Next line; the comparison that
  follows is as it was, and the exit code is the comparison's.
No test calls an AI API.
"""

from __future__ import annotations

import pytest

from judgekeeper import page
from judgekeeper.start_label import StartSession, Workspace
from tests.conftest import CI_VARIABLES
from tests.test_before_after import NEXT_WORSE, WORSE, counts, qs, rows_csv, said
from tests.test_front import flat, next_lines

LINE = ("judgekeeper opens no marking page in CI. To mark answers, run `{command}` on your "
        "own computer.")
OPENING = "Opening the marking page in your browser"
MADE_WORSE = [False] * 12 + [True] * 28


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _files(here, now) -> None:
    rows_csv(here / "main-results.csv", qs(0, 40, True))
    rows_csv(here / "results.csv", qs(0, 40, now))


def _nothing_started(here, pages, no_browser) -> None:
    started, _ = pages
    assert started == []  # no server process
    assert no_browser == []  # no browser call
    ws = Workspace(here)
    assert not (ws.dir / "server.json").exists()
    assert not (ws.dir / "page.json").exists()


# CI is one function -----------------------------------------------------------------------

@pytest.mark.parametrize("name", CI_VARIABLES)
@pytest.mark.parametrize("value", ["true", "1", "yes", "True", "github"])
def test_each_variable_set_is_ci(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    assert page.in_ci() is True


@pytest.mark.parametrize("name", CI_VARIABLES)
@pytest.mark.parametrize("value", ["", "false", "False", "FALSE", "0", " "])
def test_a_variable_empty_false_or_zero_is_not_ci(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    assert page.in_ci() is False


def test_no_variable_is_not_ci():
    assert page.in_ci() is False


def test_no_terminal_is_not_ci(monkeypatch):
    """Agents run with no terminal and must still get the page."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert page.in_ci() is False


# The CI form: graded results against the file from main -----------------------------------

def test_ci_step_2_says_one_line_and_starts_nothing(here, capsys, monkeypatch, pages,
                                                    no_browser):
    monkeypatch.setenv("CI", "true")
    _files(here, MADE_WORSE)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 1, out
    assert LINE.format(command="judgekeeper results.csv") in flat(out)
    assert OPENING not in out
    assert "marking page is open" not in flat(out)
    assert "Step 2 of 5: Mark" in out
    assert "You marked" not in out and "A result needs at least" in out  # the counts stay
    assert counts(0, 12, 28) in flat(out)
    assert WORSE in flat(out)
    assert next_lines(out) == [NEXT_WORSE]  # none for Step 2


def test_ci_no_change_exits_0_and_has_no_next_line(here, capsys, monkeypatch, pages,
                                                   no_browser):
    monkeypatch.setenv("CI", "true")
    _files(here, True)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper results.csv") in flat(out)
    assert next_lines(out) == []


@pytest.mark.parametrize("name", CI_VARIABLES)
def test_every_variable_keeps_the_page_closed(name, here, capsys, monkeypatch, pages,
                                              no_browser):
    monkeypatch.setenv(name, "1")
    _files(here, True)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert "opens no marking page in CI" in flat(out)


def test_the_line_leaves_out_before_port_and_no_browser(here, capsys, monkeypatch, pages,
                                                        no_browser):
    monkeypatch.setenv("CI", "true")
    _files(here, True)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv", "--port", "9000",
                     "--no-browser", "--judge-model", "gpt-x")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper results.csv --judge-model gpt-x") in flat(out)


def test_ci_with_no_before_says_the_line_too(here, capsys, monkeypatch, pages, no_browser):
    monkeypatch.setenv("CI", "true")
    rows_csv(here / "results.csv", qs(0, 40, True))
    code, out = said(capsys, "results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper results.csv") in flat(out)
    assert next_lines(out) == []


def test_ci_with_too_few_answers_exits_as_it_did(tmp_path, capsys, monkeypatch, pages,
                                                 no_browser):
    """What the data decides (too few answers for a result) is not changed by CI."""
    codes = {}
    for name in ("plain", "ci"):
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.chdir(folder)
        rows_csv(folder / "results.csv", qs(0, 8, True))
        if name == "ci":
            monkeypatch.setenv("CI", "true")
        codes[name], out = said(capsys, "results.csv", "--no-browser")
    assert codes["ci"] == codes["plain"]
    assert "opens no marking page in CI" in flat(out)
    assert not (tmp_path / "ci" / ".judgekeeper" / "server.json").exists()


# No terminal and no CI variable: the agent path is as it was ---------------------------------

@pytest.mark.parametrize("value", [None, "", "false", "0"])
def test_no_terminal_and_no_ci_still_starts_the_page(value, here, capsys, monkeypatch, pages):
    if value is not None:
        monkeypatch.setenv("CI", value)
    _files(here, MADE_WORSE)
    code, out = said(capsys, "results.csv", "--before", "main-results.csv")
    started, _ = pages
    assert len(started) == 1
    assert code == 1, out
    assert OPENING in out
    assert "opens no marking page in CI" not in out
    assert next_lines(out)[-1] == NEXT_WORSE and len(next_lines(out)) == 2


# Other commands that would open a page --------------------------------------------------------

def test_mark_in_ci_says_the_line_and_starts_nothing(here, capsys, monkeypatch, pages,
                                                     no_browser):
    monkeypatch.setenv("CI", "true")
    rows_csv(here / "results.csv", qs(0, 40, True))
    code, out = said(capsys, "mark", "results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper mark results.csv") in flat(out)
    assert OPENING not in out


def test_mark_wait_in_ci_does_not_wait(here, capsys, monkeypatch, pages, no_browser):
    monkeypatch.setenv("CI", "true")
    rows_csv(here / "results.csv", qs(0, 40, True))
    code, out = said(capsys, "mark", "results.csv", "--wait")  # returns: nothing is served
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper mark results.csv") in flat(out)


def test_mark_with_every_answer_marked_in_ci_opens_nothing(here, capsys, monkeypatch, pages,
                                                           no_browser):
    rows_csv(here / "results.csv", qs(0, 40, [True] * 20 + [False] * 20))
    said(capsys, "results.csv", "--no-browser")
    session = StartSession(Workspace(here))
    for i, item in enumerate(session.items):
        session.update({"id": item["id"], "label": "pass" if i % 2 else "fail", "seconds": 3})
    started, _ = pages
    before = len(started)
    monkeypatch.setenv("CI", "true")
    code, out = said(capsys, "mark", "results.csv")
    assert len(started) == before  # none started by this run
    assert no_browser == []
    assert code == 0, out
    assert LINE.format(command="judgekeeper mark results.csv") in flat(out)
    assert OPENING not in out


def test_answers_with_no_grades_in_ci_open_nothing(here, capsys, monkeypatch, pages, no_browser):
    monkeypatch.setenv("CI", "true")
    (here / "results.csv").write_text(
        "input,output\n" + "".join(f"Question {i}?,Answer {i}.\n" for i in range(20)),
        encoding="utf-8")
    code, out = said(capsys, "results.csv")
    _nothing_started(here, pages, no_browser)
    assert code == 0, out
    assert LINE.format(command="judgekeeper results.csv") in flat(out)
    assert next_lines(out) == []


def test_answers_with_no_grades_and_no_ci_still_open_the_page(here, capsys, pages):
    (here / "results.csv").write_text(
        "input,output\n" + "".join(f"Question {i}?,Answer {i}.\n" for i in range(20)),
        encoding="utf-8")
    code, out = said(capsys, "results.csv")
    started, _ = pages
    assert code == 0 and len(started) == 1, out
    assert OPENING in out
