"""One project folder for every command, and no dead ends in the flow across runs.

- A results file given by path keeps `.judgekeeper/` in the project the command runs from;
  `judgekeeper`, `mark`, `--stop`, `check` and `fix` find the same marks and page from the
  project and from a folder inside it. A folder that holds two projects says which one it
  read and names the other.
- Every answer marked with too few of one kind: said plainly, the same words in the
  terminal, `mark`, the Measure screen and on the marking page's end card.
- A table judge whose grades changed in the newest results is re-checked on them (no AI
  call); marks added after a check are re-checked; after a check the result and `fix`
  describe the judge in the newest results.
- `fix` for a judge it can't ask never asks for a rule.txt; report.html says the same.
- Read-only `.judgekeeper/`, `--no-browser` again, two runs at once, the same next step in
  the terminal and the report, the grammar of "finds no results", exit codes, a wrong flag
  or a flag before the command, and a `--judge-model` remembered.
No test calls an AI API.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import pytest

from judgekeeper import check, fix, judge_setup, page, start, start_label, textio
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_data, promptfoo_project, split, table_project
from tests.test_front import flat, next_lines, run

LINK = page.LINK
ALL_MARKED = ("You've marked every answer: 28 Pass, 12 Fail. A result needs at least 15 of "
              "each.")
NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper --new` to mark "
                   "the new results. Your marks so far are kept in "
                   ".judgekeeper/previous-<date>/.")
RULE_A = "Is polite and correct."
RULE_B = "Is polite, correct and short."


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def no_calls(monkeypatch):
    monkeypatch.setattr("judgekeeper.again.run_process",
                        lambda *a, **k: pytest.fail("the judge was asked"))


def _index(value) -> int:
    text = value.get("question") if isinstance(value, dict) else value
    return int(re.search(r"Question (\d+)\?", str(text))[1])


def _mark(ws: Workspace, person=None, only=None) -> None:
    """The person marks the answers on the page: as the judge did, or `person[i]` for answer
    i; `only`: just those answers."""
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        i = _index(session.raw[item["id"]]["input"])
        if only is not None and i not in only:
            continue
        mark = (person or {}).get(i, groups[item["id"]])
        session.update({"id": item["id"], "label": mark, "seconds": 6})


def _next(out: str) -> str:
    return next_lines(out)[-1]


# 1. One project folder ----------------------------------------------------------------------

def test_a_results_file_given_by_path_keeps_the_marks_in_the_project(here, capsys,
                                                                      monkeypatch):
    (here / ".git").mkdir()
    deep = "data/a/b/c/d/deep.csv"  # deeper than the search looks
    table_project(here, split(20, 16), name=deep)
    code, out, err = run(capsys, deep)
    assert code == 0, out + err
    assert (here / ".judgekeeper" / "start.json").is_file()
    assert not (here / "data" / "a" / "b" / "c" / "d" / ".judgekeeper").exists()
    assert "(read from data/a/b/c/d/deep.csv)" in out
    _mark(Workspace(here), only=range(6))
    (here / "src").mkdir()
    for folder in (here, here / "src"):
        monkeypatch.chdir(folder)
        code, out, err = run(capsys)
        assert code == 0, out + err
        assert "You marked 6 answers so far: 6 Pass, 0 Fail." in out
        code, out, err = run(capsys, "mark")
        assert code == 0, out + err
        assert "You marked 6 answers so far: 6 Pass, 0 Fail." in out
        code, out, err = run(capsys, "--stop")
        assert code == 0
        assert "Closed the marking page. Your marks are saved." in out
    _mark(Workspace(here))
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    assert "Your judge has not changed since you marked your answers." in out
    assert "You have not marked enough" not in run(capsys, "fix")[1]
    assert not (here / "src" / ".judgekeeper").exists()


def test_a_results_file_outside_the_project_keeps_the_marks_here(tmp_path, capsys,
                                                                  monkeypatch):
    project, other = tmp_path / "proj", tmp_path / "other"
    (project / ".git").mkdir(parents=True)
    table_project(other, split(20, 16), name="r.csv")
    monkeypatch.chdir(project)
    code, out, err = run(capsys, "../other/r.csv")
    assert code == 0, out + err
    assert (project / ".judgekeeper" / "start.json").is_file()
    assert not (other / ".judgekeeper").exists()
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert "No eval results found" not in out


def test_stop_and_check_from_a_folder_inside_the_project(here, capsys, monkeypatch):
    (here / ".git").mkdir()
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    (here / "src" / "app").mkdir(parents=True)
    monkeypatch.chdir(here / "src" / "app")
    assert "Closed the marking page." in run(capsys, "--stop")[1]
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    assert "Your judge has not changed since you marked your answers." in out
    code, out, _ = run(capsys, "fix")
    assert "You have not marked enough answers yet" not in out


def test_a_folder_with_two_projects_says_which_it_read(here, capsys):
    for name in ("a", "b"):
        (here / name / ".git").mkdir(parents=True)
        table_project(here / name, split(20, 16))
    later = time.time() + 60
    os.utime(here / "b" / "results.csv", (later, later))
    code, out, err = run(capsys)
    assert code == 0, out + err
    assert ("These results are from the project in b/. The project in a/ has results too: to "
            "check them, run `judgekeeper a`.") in flat(out)


# 2. Every answer marked, too few of one kind ------------------------------------------------

def test_every_answer_marked_with_too_few_fails_says_so(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    started = len(pages[0])
    code, out, _ = run(capsys)
    assert code == 3, out
    assert ALL_MARKED in flat(out)
    assert _next(out) == NEXT_ALL_MARKED
    assert "keep marking" not in out and "is open" not in out
    assert len(pages[0]) == started  # no page: nothing is left to mark on it


def test_the_new_command_never_repeats_the_pages_flags(here, capsys):
    promptfoo_project(here, split(28, 12))
    assert run(capsys, "--no-browser", "--port", "0")[0] == 0
    _mark(Workspace(here))
    code, out, _ = run(capsys, "--no-browser", "--port", "0")
    assert code == 3
    assert _next(out) == NEXT_ALL_MARKED


def test_mark_says_the_same_when_every_answer_is_marked(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    code, out, _ = run(capsys, "mark")
    assert code == 3, out
    assert ALL_MARKED in flat(out)
    assert _next(out) == NEXT_ALL_MARKED


def test_the_page_says_it_on_its_end_card(here, capsys):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws)
    status = page.marking_status(StartSession(ws))
    assert status["ready"] is False
    assert status["done"] == [ALL_MARKED, NEXT_ALL_MARKED]


def test_measure_with_every_answer_marked_does_not_offer_the_page(here, capsys):
    """Every answer marked, enough of each kind, too early to tell: the same words, never
    "the page is still open" or "mark more"."""
    promptfoo_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    person = {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (20, 21, 22)}
    _mark(Workspace(here), person)
    code, out, _ = run(capsys)
    assert "Step 3 of 5: Measure" in out
    assert "Result: too early to tell." in out
    assert "still open" not in out and "To mark more answers" not in out
    assert "estimates" not in out  # too early to tell: counts only
    assert "You've marked every answer: 20 Pass, 20 Fail. That's still too few to tell." in \
        flat(out)
    assert _next(out) == NEXT_ALL_MARKED
    assert code == 3


# 3 to 5. Re-checks -------------------------------------------------------------------------

def test_a_table_judge_whose_grades_changed_is_re_checked(here, capsys, no_calls):
    verdicts = split(20, 20)
    table_project(here, verdicts)
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    flipped = list(verdicts)
    for i in (0, 4, 8, 12, 24, 28, 32):
        flipped[i] = not flipped[i]
    table_project(here, flipped)
    out = run(capsys)[1]
    assert "Your judge is the same" not in out
    assert "Your judge's grades changed on 7 of your marked answers." in flat(out)
    assert _next(out) == ("Next: run `judgekeeper check` to re-check your changed judge on "
                          "your marks.")
    _, out, _ = run(capsys, "check")
    assert "Your judge's grades changed on 7 of your marked answers." in flat(out)
    assert "Re-checked on all 40 of your marks:" in out
    assert "has not changed" not in out


def test_a_table_judge_made_worse_stays_worse(here, capsys, no_calls):
    """A "Worse" keeps the old grades as the reference: every later run says it again."""
    table_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    table_project(here, split(20, 20)[::-1])  # every grade the other way
    assert run(capsys, "check")[0] == 1
    code, out, _ = run(capsys, "check")
    assert code == 1 and "Worse" in out
    out = run(capsys)[1]
    assert "Your judge's grades changed on 40 of your marked answers." in flat(out)
    assert "Your judge is the same" not in out


def _rule_project(root, verdicts, rule):
    data = promptfoo_data(verdicts, rubric=rule)
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def test_marks_added_after_a_check_are_re_checked(here, capsys, no_calls):
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rule_project(here, split(25, 25), RULE_A)
    assert run(capsys)[0] == 0
    _mark(Workspace(here), only=range(5, 45))
    _rule_project(here, split(25, 25), RULE_B)
    out = run(capsys, "check")[1]
    assert "Re-checked on all 40 of your marks:" in out
    _mark(Workspace(here), only=[*range(5), *range(45, 50)])
    _, out, _ = run(capsys, "check")
    assert "has not changed" not in out, out
    assert "You added 10 marks since your last check." in out
    assert "Re-checked on all 50 of your marks:" in out


def test_after_a_check_the_result_and_fix_are_about_the_new_judge(here, capsys, no_calls,
                                                                  monkeypatch):
    monkeypatch.setattr(fix, "make_split", lambda m, seed: (sorted(m.person), []))
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rule_project(here, split(25, 25), RULE_A)
    assert run(capsys)[0] == 0
    person = {i: "pass" for i in range(25, 31)}  # the old judge is too strict on 6
    _mark(Workspace(here), person)
    assert "You and your judge disagreed on 6 of 50 answers." in flat(run(capsys)[1])
    new = split(25, 25)
    new[25:31] = [True] * 6  # the new rule fixes those 6
    new[0] = False  # and breaks 1
    _rule_project(here, new, RULE_B)
    code, out, _ = run(capsys, "check")
    assert code == 0, out
    code, out, _ = run(capsys)
    assert "You and your judge disagreed on 1 of 50 answers." in flat(out)
    assert "This result is about your judge as it was" not in out
    assert "Your judge is the same" in out or "Your judge changed" not in out
    run(capsys, "fix")
    mistakes = (here / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert RULE_B in mistakes and RULE_A not in mistakes
    assert mistakes.count("## [M") == 1


# 6. fix for a judge it can't ask -------------------------------------------------------------

CANT_ASK = "judgekeeper can't ask this judge itself."
NEXT_CANT_ASK = ("Next: change its rule where your eval keeps it, run your eval, then run "
                 "`judgekeeper check`.")


def _table_needs_work(root, capsys):
    """A table judge that needs work: it passes 12 of the answers the person fails."""
    table_project(root, split(30, 30))
    assert run(capsys)[0] == 0
    _mark(Workspace(root), {i: "fail" for i in range(12)} | {i: "pass" for i in range(30, 34)})
    _, out, _ = run(capsys)
    assert "Result: your judge needs work." in out, out


def test_fix_for_a_table_judge_never_asks_for_a_rule(here, capsys):
    _table_needs_work(here, capsys)
    code, first, _ = run(capsys, "fix")
    assert CANT_ASK in flat(first) and _next(first) == NEXT_CANT_ASK
    assert code == 3
    (here / ".judgekeeper" / "fix" / "rule.txt").write_text("Be fair.", encoding="utf-8")
    code, second, _ = run(capsys, "fix")
    assert code == 3
    assert CANT_ASK in flat(second) and _next(second) == NEXT_CANT_ASK
    assert "rule.txt" not in first + second and "can't be asked again" not in second


def test_the_report_says_the_same_for_a_judge_it_cant_ask(here, capsys):
    _table_needs_work(here, capsys)
    report = flat((here / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))
    assert "again to test it" not in report
    assert ("judgekeeper can&#x27;t ask this judge itself. Change its rule where your eval "
            "keeps it, run your eval, then run <code>judgekeeper check</code>.") in report


# 7 to 9. The folder and the page -------------------------------------------------------------

def test_a_read_only_folder_never_says_to_remove_it():
    assert "remove" not in textio.WORKSPACE_DENIED_NEXT
    assert textio.WORKSPACE_DENIED_NEXT == ("give your user permission to write in "
                                            ".judgekeeper/, then run `{command}`.")


def test_no_browser_again_prints_the_link(here, capsys):
    promptfoo_project(here, split(20, 16))
    assert LINK in run(capsys, "--no-browser")[1]
    _mark(Workspace(here), only=range(3))
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0
    assert LINK in out and "http://127.0.0.1:" in out
    assert "still open in your browser" not in out


def test_a_second_run_waits_for_the_first_to_open_the_page(here, capsys):
    promptfoo_project(here, split(20, 16))
    ws = Workspace(here)
    start_label.make_folder(ws)
    opening = ws.dir / page.OPENING
    opening.write_text(str(os.getpid()), encoding="utf-8")
    threading.Timer(0.5, opening.unlink).start()
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "judgekeeper is already opening the marking page for this folder." in out
    assert LINK in out and "in use" not in out


# 10. The same next step in the terminal and the report ----------------------------------------

def test_too_early_with_mistakes_says_mark_more_as_the_report_does(here, capsys):
    promptfoo_project(here, split(25, 25))
    assert run(capsys)[0] == 0
    person = {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (25, 26, 27)}
    _mark(Workspace(here), person, only=[*range(20), *range(25, 45)])
    _, out, _ = run(capsys)
    assert "Result: too early to tell." in out
    assert _next(out) == "Next: run `judgekeeper mark` to mark more answers."
    report = (here / ".judgekeeper" / "report.html").read_text(encoding="utf-8")
    assert "<code>judgekeeper mark</code> to mark more answers." in report
    assert "judgekeeper fix" not in report


# 11 and 12. Words and exit codes ---------------------------------------------------------------

def test_check_with_its_table_gone_says_so_in_a_sentence(here, capsys):
    table_project(here, split(20, 20))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    (here / "results.csv").unlink()
    code, out, _ = run(capsys, "check")
    assert f"judgekeeper finds no results in this folder ({here.name})." in flat(out)
    assert "no a plain table" not in out
    assert code == 3


def test_no_results_exits_3_as_the_reference_says(here, capsys):
    from pathlib import Path

    code, out, _ = run(capsys)
    assert code == 3
    assert "No eval results found" in out
    reference = (Path(__file__).parent.parent / "docs" / "reference.md").read_text(
        encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in reference.splitlines()
            if re.match(r"\| [0-9]+ \|", line)}
    assert "nothing it can use found" not in rows["2"]
    assert "no eval results found" in rows["3"]


# 13. A wrong flag, or a flag before the command --------------------------------------------------

@pytest.mark.parametrize("command", ["mark", "fix", "check"])
def test_a_wrong_flag_prints_the_commands_own_usage(here, capsys, command):
    code = main([command, "--bogus"])
    _out, err = capsys.readouterr()
    assert code == 2
    assert f"usage: judgekeeper {command} " in err
    assert "usage: judgekeeper [-h] [--debug] command" not in err
    assert err.rstrip().splitlines()[-1] == (f"Next: run `judgekeeper {command} --help` to see "
                                             "the options.")


def test_a_flag_before_the_command_works(here, capsys, pages):
    promptfoo_project(here, split(20, 16))
    code, out, err = run(capsys, "--no-browser", "mark")
    assert code == 0, out + err
    assert "is not a judgekeeper command" not in out + err
    assert LINK in out


# 14. --judge-model remembered ----------------------------------------------------------------------

def test_a_judge_model_given_once_is_remembered(here, capsys):
    table_project(here, split(20, 16))
    code, out, _ = run(capsys, "--judge-model", "openai:gpt-4")
    assert code == 0, out
    assert "openai:gpt-4 (as you said)" in out
    _mark(Workspace(here), only=range(4))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "changed" not in out
    assert _next(out) == 'Next: keep marking until "See your result" appears, then click it.'


def test_check_then_judgekeeper_keeps_the_given_model(here, capsys):
    table_project(here, split(20, 20))
    assert run(capsys, "--judge-model", "openai:gpt-4")[0] == 0
    _mark(Workspace(here))
    assert "changed" not in run(capsys)[1]
    assert judge_setup.read(Workspace(here))["setup"]["models"] == ["openai:gpt-4"]
    assert check.full(".", check.Said()) == 0
    assert start.GIVEN_BY_YOU in json.dumps(Workspace(here).data())
