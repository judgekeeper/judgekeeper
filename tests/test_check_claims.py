# ruff: noqa: F811 - the fixtures come from test_check
"""`judgekeeper check` never claims more than it measured, and says where it looked.

- A version change seen only in a lockfile that is newer than the results is not
  re-checked on those older results: the grades are out of date until the next eval run.
- After "Worse", the old LLM-as-a-judge stays the reference: every check says it again until the
  judge goes back (or changes again), and the History gets the check once.
- When the newest results hold none of the marked answers: a reason and a way forward.
- A wrong PATH, or a folder under the project, says where it looked.
- No "since the last check" before any check; a missing results file is said plainly.
- Output piped into a program that stops reading ends quietly.
- The words for "nothing changed" and "changed after your last eval run".
No test calls an API: check only reads the results files.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

from judgekeeper import judge_setup
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer, promptfoo_data, table_project
from tests.test_check import (  # noqa: F401
    HAIKU,
    LENIENT,
    MARKED,
    TABLE_HEAD,
    TAG,
    _flat,
    _history,
    _marked,
    _next,
    _results,
    _write,
    here,
    run,
)


def _lock(root, version: str, later: float = 0) -> None:
    path = root / "package-lock.json"
    path.write_text(json.dumps({"packages": {"node_modules/promptfoo": {"version": version}}}),
                    encoding="utf-8")
    if later:
        stamp = (root / "results.json").stat().st_mtime + later
        os.utime(path, (stamp, stamp))


# The words for "nothing changed" and "changed after your last eval run" -----------------------

def test_nothing_changed_says_so_in_the_agreed_words(here, capsys):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Step 5 of 5: Re-check", "",
        "New results: results.json", "",
        "Your LLM-as-a-judge has not changed since you marked your answers.",
        "Same model, same rule, same eval tool.", "",
        "Next: nothing to do. Run `judgekeeper check` again after you",
        "change your LLM-as-a-judge."]


def test_a_rerun_with_new_text_says_how_many_marked_answers_it_holds(here, capsys):
    """An eval run again with new answers: same setup, but most marked answers are not in it."""
    _marked(here)
    outs = [answer(i, TAG) if i % 25 < 15 else f"A new answer {i}." for i in range(50)]
    _results(here, MARKED, outputs=outs, created="2026-10-20T09:00:00Z")
    for given in ((), ("results.json",)):
        code, out = run(capsys, *given)
        said = _flat(out)
        assert code == 0 and "nothing to do" not in said, out
        assert ("20 of your 50 marked answers had no grade in your new results, so judgekeeper "
                "left them out. It finds a marked answer by the same text, word for word, and the "
                "same question.") in said
        command = " ".join(("judgekeeper check", *given))
        assert _next(out) == ("Next: run `judgekeeper` to mark the new answers in your results: "
                              f"they join your marks as a new batch. Then run `{command}` again.")


def test_a_new_rule_run_on_only_some_marked_answers_never_says_they_are_new(here, capsys):
    """The eval run again with a new rule on the first 10 marked answers only: too few to
    tell, and they are the answers marked, not new ones."""
    _marked(here)
    _results(here, MARKED[:10], rubric="Pass only if the answer is short.",
             created="2026-10-20T09:00:00Z")
    code, out = run(capsys)
    said = _flat(out)
    assert code == 3, out
    assert "rule changed" in said and "40 of your 50 marked answers had no grade" in said, out
    assert "Compared with before: can't tell yet." in said
    assert "wrote new answers" not in said and "nothing to compare" not in said, out
    assert "Grade the answers you marked: 1. Change the grader in" in said, out


def test_a_table_with_no_rule_never_says_same_rule(tmp_path, monkeypatch, capsys):
    table_project(tmp_path, ["good"] * 30 + ["bad"] * 30, name="results.csv")
    monkeypatch.chdir(tmp_path)
    flags = ["--label-map", "good=pass,bad=fail", "--port", "0", "--no-browser", "--yes"]
    assert main(["results.csv", *flags]) == 0
    ws = Workspace(tmp_path)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 7})
    capsys.readouterr()
    code, out = run(capsys, "results.csv")
    said = _flat(out)
    assert code == 0 and "same rule" not in said, out
    assert "Same model, same grades on your marked answers, same eval tool." in said


def test_settings_changed_after_the_last_eval_run(here, capsys):
    _marked(here)
    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    os.utime(config, (later, later))
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Step 5 of 5: Re-check", "",
        "New results: results.json", "",
        "Your LLM-as-a-judge's settings changed after your last eval run,",
        "so the grades judgekeeper has are out of date.", "",
        "Next: run your eval again, then run `judgekeeper check`."]
    assert "has not changed" not in out


def test_after_a_check_nothing_changed_names_that_check(here, capsys):
    """"Since your last check" only once a check ran."""
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    assert run(capsys)[0] == 0
    code, out = run(capsys)
    assert code == 0
    assert "Your LLM-as-a-judge has not changed since your last check (" in out


# Where check looked ---------------------------------------------------------------------------

def test_a_path_that_does_not_exist(here, capsys):
    _marked(here)
    code, out = run(capsys, "nope.json")
    assert code == 2
    assert "There is no file named nope.json here." in out
    assert _next(out) == ("Next: give `judgekeeper check` your new results file, or run it in "
                          "your project folder.")


def test_a_folder_inside_the_project_finds_the_marks(here, capsys, monkeypatch):
    _marked(here)
    (here / "src").mkdir()
    monkeypatch.chdir(here / "src")
    code, out = run(capsys)
    assert code == 0, out
    assert "Your LLM-as-a-judge has not changed since you marked your answers." in out


def test_another_project_inside_says_where_the_marks_are(here, capsys, monkeypatch):
    _marked(here)
    (here / "app" / ".git").mkdir(parents=True)
    monkeypatch.chdir(here / "app")
    code, out = run(capsys)
    assert code == 3
    assert "No marks in this folder (app). Your marks are in the folder above it" in _flat(out)
    assert _next(out) == "Next: run `judgekeeper check ..`."


def test_no_marks_anywhere(tmp_path, capsys, monkeypatch):
    folder = tmp_path / "my-app"
    folder.mkdir()
    monkeypatch.chdir(folder)
    code, out = run(capsys)
    assert code == 3
    assert "No marks in this folder (my-app)." in out
    assert "15" not in out
    assert _next(out) == "Next: run `judgekeeper` to find your eval results and mark answers."


def test_too_few_marks_says_how_many_in_measures_words(here, capsys):
    """How many marks there are and how many a re-check needs, as Measure says them."""
    _marked(here, n_pass=10, n_fail=25)
    code, out = run(capsys)
    assert code == 3
    assert ("You have not marked enough answers yet for a re-check. You marked 35 answers so "
            "far: 10 Pass, 25 Fail. A re-check needs at least 15 answers you mark Pass and 15 "
            "you mark Fail.") in _flat(out)
    assert _next(out) == ("Next: run your eval on more questions, then run `judgekeeper mark`: "
                          "the new answers join the ones you marked.")  # every answer is marked


# A missing results file -----------------------------------------------------------------------

def test_deleted_results_are_said_plainly(here, capsys):
    _marked(here)
    (here / "results.json").unlink()
    code, out = run(capsys)
    assert code == 3
    assert f"judgekeeper finds no promptfoo results in this folder ({here.name})." in _flat(out)
    assert str(here) not in out
    assert "would have to ask" not in out
    assert _next(out) == "Next: run your eval once, then run `judgekeeper check` again."


# A lockfile-only version update ---------------------------------------------------------------

def test_a_lockfile_update_is_not_rechecked_on_older_results(here, capsys):
    _lock(here, "0.121.0")
    ws = _marked(here, version=None)
    assert judge_setup.read(ws)["setup"]["tool_version"] == "0.121.0"
    before = (ws.dir / "judge.json").read_bytes()
    _lock(here, "0.130.0", later=60)  # promptfoo updated; the eval not run again
    code, out = run(capsys)
    assert code == 3
    flat = _flat(out)
    assert "Your eval tool changed: promptfoo 0.121.0 -> 0.130.0." in flat
    assert ("Your eval tool was updated after your last eval run, so your newest results come "
            "from the old version. judgekeeper compared no grades.") in flat
    assert "settings changed" not in flat  # only the version did
    assert _next(out) == "Next: run your eval again, then run `judgekeeper check`."
    assert "Re-checked" not in out and "No drop" not in out
    assert (ws.dir / "judge.json").read_bytes() == before
    assert _history(ws) == []


def test_a_lockfile_update_is_rechecked_after_the_next_eval_run(here, capsys):
    _lock(here, "0.121.0")
    ws = _marked(here, version=None)
    _lock(here, "0.130.0", later=60)
    stamp = (here / "package-lock.json").stat().st_mtime + 60  # the eval ran on the new one
    os.utime(here / "results.json", (stamp, stamp))
    code, out = run(capsys)
    assert code == 0
    assert TABLE_HEAD in out
    assert judge_setup.read(ws)["setup"]["tool_version"] == "0.130.0"


# A worse judge stays worse --------------------------------------------------------------------

def test_a_worse_judge_stays_worse_until_it_goes_back(here, capsys):
    ws = _marked(here)
    before = judge_setup.read(ws)["setup_hash"]
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys)[0] == 1
    assert judge_setup.read(ws)["setup_hash"] == before  # the old judge stays the reference
    code, out = run(capsys)
    assert code == 1
    assert "When you said Fail 25 of 25 16 of 25 Worse" in _flat(out)
    assert "has not changed" not in out
    assert len(_history(ws)) == 1  # the same check is in the History once
    _results(here, MARKED)  # back to the old judge
    code, out = run(capsys)
    assert code == 0 and "has not changed" not in out
    assert "Your LLM-as-a-judge is back to the one you marked with" in _flat(out)


def test_after_worse_judgekeeper_still_points_at_check(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    code = main([])
    out = capsys.readouterr().out
    assert code == 0
    assert f"Your LLM-as-a-judge changed since your marks: model openai:gpt-4.1-mini -> {HAIKU}." in \
        _flat(out)
    assert "`judgekeeper check`" in _next(out)
    assert ws.report_html.is_file()


# No marked answer in the newest results -------------------------------------------------------

def test_no_marked_answer_in_the_new_results_says_why_and_what_to_do(here, capsys):
    ws = _marked(here)
    data = promptfoo_data(LENIENT, model=HAIKU, tag=" OTHER")  # other questions
    data["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "results.json", data)
    code, out = run(capsys)
    assert code == 3
    flat = _flat(out)
    assert ("None of your 50 marked answers is in your new results. judgekeeper finds a marked "
            "answer by the same text, word for word, and the same question.") in flat
    assert "labeled" not in flat
    assert ("Your eval wrote new answers, so there's nothing to compare. Grade the answers you "
            "marked instead:") in flat
    assert "2. Run: `npx promptfoo eval -c .judgekeeper/fix/regrade.yaml" in flat
    assert _next(out) == ("Next: follow the three steps above; or start over on your new "
                          "answers with `judgekeeper --new`.")
    assert _history(ws) == []


def test_doing_what_no_marked_answer_says_gives_a_check_that_compares(here, capsys):
    """Running the eval again makes new answers, which can't be compared: the Next: line says
    to grade the marked answers again, and doing so gives a re-check."""
    ws = _marked(here)
    other = promptfoo_data(LENIENT, model=HAIKU, tag=" OTHER")
    other["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "results.json", other)
    code, out = run(capsys)
    assert code == 3
    assert "3. Then: `judgekeeper check .judgekeeper/fix/new.json`" in _flat(out)
    commands = ["judgekeeper fix", "judgekeeper check <new results file>"]
    assert main(["fix"]) == 0
    capsys.readouterr()
    assert (ws.dir / "fix" / "marked-answers.csv").is_file()
    again = promptfoo_data(LENIENT, model=HAIKU, tag=TAG)  # the marked answers, graded again
    again["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "regraded.json", again)
    code, out = run(capsys, *commands[1].replace("<new results file>", "regraded.json").split()[2:])
    assert "None of your" not in _flat(out), out
    assert len(_history(ws)) == 1, out


# A closed output pipe -------------------------------------------------------------------------

class _Closed(io.StringIO):
    """A pipe whose reader stopped reading (`| head`)."""

    def write(self, text):
        raise BrokenPipeError(32, "Broken pipe")

    def fileno(self):
        raise io.UnsupportedOperation


def test_a_closed_pipe_ends_quietly(here, capsys, monkeypatch):
    _marked(here)
    monkeypatch.setattr(sys, "stdout", _Closed())
    assert main(["check"]) == 0
    assert capsys.readouterr().err == ""


# The same rule and model, graded again with other grades --------------------------------------

def _regraded(root, flips, name="regraded.json"):
    """A copy of the marked promptfoo results, same model and rule, with the grades of the
    answers `flips` turned over (the LLM-as-a-judge graded them again)."""
    from tests.start_projects import split
    from tests.test_check import MODEL

    verdicts = split(25, 25)
    for i in flips:
        verdicts[i] = not verdicts[i]
    data = promptfoo_data(verdicts, model=MODEL, tag=TAG, created="2026-10-13T09:00:00Z")
    data["metadata"]["promptfooVersion"] = "0.124.1"
    _write(root / name, data)


def test_the_same_rule_and_model_with_other_grades_is_compared(here, capsys):
    """Same model and rule, yet 11 of the marked answers got another grade: check compares
    them as usual and says why first. After "Worse" the grades it was marked on stay the
    reference, so checking again says the same, as for a table's new grades."""
    ws = _marked(here)
    _regraded(here, [*range(6), *range(25, 30)])
    for _ in range(2):
        code, out = run(capsys, "regraded.json")
        said = _flat(out)
        assert code == 1, out
        assert ("Same model and rule as before, yet 11 of your marked answers got a different "
                "grade: your LLM-as-a-judge doesn't always grade the same answer the same way."
                ) in said
        assert "has not changed" not in said and "nothing to do" not in said
        assert said.index("doesn't always grade") < said.index("Compared with before: worse.")
        assert "When you said Pass 25 of 25 19 of 25 Worse" in said
        assert "When you said Fail 25 of 25 20 of 25 Worse" in said
        assert _next(out) == (  # no old one to go back to: the same model and rule
            "Next: your model and rule are the same as before, so its grades change from run to "
            "run. Make your rule clearer, grade your marked answers again, then run "
            "`judgekeeper check <new results file>`.")
    assert [x["changed"] for x in _history(ws)] == [["grades changed on 11 marked answers"]]


def test_a_plain_check_after_a_same_rule_worse_says_worse_again(here, capsys):
    """The results graded again in place: a plain check says "Worse" (exit 1), and so does
    every plain check after it while nothing changes, never "nothing to do"."""
    ws = _marked(here)
    _regraded(here, [*range(8), *range(25, 33)], name="results.json")
    for _ in range(3):
        code, out = run(capsys)
        said = _flat(out)
        assert code == 1, out
        assert "Same model and rule as before, yet 16 of your marked answers" in said, out
        assert "Compared with before: worse." in said and "nothing to do" not in said, out
    assert [x["changed"] for x in _history(ws)] == [["grades changed on 16 marked answers"]]


def test_a_plain_run_after_a_same_rule_worse_names_it(here, capsys):
    """After that "Worse", a plain `judgekeeper` says why and that the last check found it
    worse, with the same next step: never "graded again ... the same ... nothing to do"."""
    _marked(here)
    _regraded(here, [*range(8), *range(25, 33)], name="results.json")
    assert run(capsys)[0] == 1
    main(["--no-browser", "--port", "0"])
    said = _flat(capsys.readouterr().out)
    main(["--stop"])
    capsys.readouterr()
    assert said.startswith("judgekeeper ") and "Step 3 of 5: Measure" in said
    assert ("Same model and rule as before, yet 16 of your marked answers got a different "
            "grade: your LLM-as-a-judge doesn't always grade the same answer the same way.") in said
    assert ("Your last check found your LLM-as-a-judge in results.json worse, so the numbers "
            "below still use the grades from before.") in said  # graded again in place
    assert said.endswith("Next: your model and rule are the same as before, so its grades "
                         "change from run to run. Make your rule clearer, grade your marked "
                         "answers again, then run `judgekeeper check`.")
    assert "graded again" not in said and "nothing to do" not in said


@pytest.mark.parametrize("command", [[], ["mark"]])
def test_a_regraded_copy_beside_says_whose_grades_the_numbers_use(here, capsys, command):
    """A copy graded again beside the marked results (same model and rule, 7 marked answers
    with another grade): a plain run and `mark` read it as the newest, but the numbers keep
    the grades the marks were checked with, so the words name both files and how to
    compare. result.json and report.html name the same file the numbers use."""
    import os
    import time

    ws = _marked(here)
    _regraded(here, [*range(4), *range(25, 28)], name="results-regraded.json")
    later = time.time() + 60
    os.utime(here / "results-regraded.json", (later, later))
    main([*command, "--no-browser", "--port", "0"])
    said = _flat(capsys.readouterr().out)
    main(["--stop"])
    capsys.readouterr()
    assert ("Your answers were graded again in results-regraded.json, and 7 of your marked "
            "answers got a different grade. The numbers below still use the grades in "
            "results.json. To compare, run `judgekeeper check`.") in said
    assert "the newest results here" not in said and "still test it" not in said, said
    if not command:  # the step after it is that check, never "nothing to do"
        assert ("Next: run `judgekeeper check` to compare the new grades with your marks."
                in said and "nothing to do" not in said), said
    if not command:  # the result: about the same file as the numbers
        result = json.loads(ws.result_json.read_text(encoding="utf-8"))
        assert result["judge"]["results_files"] == ["results.json"]
        # report.html names no results file, so never the other one
        assert "results-regraded.json" not in ws.report_html.read_text(encoding="utf-8")


def test_results_graded_again_in_place_say_the_numbers_use_the_grades_from_before(here, capsys):
    """The marked results file itself graded again: it no longer holds the grades the
    numbers use, so they are the grades from before, never that file again."""
    _marked(here)
    _regraded(here, [*range(4), *range(25, 28)], name="results.json")
    main(["--no-browser", "--port", "0"])
    said = _flat(capsys.readouterr().out)
    assert ("Your answers were graded again in results.json, and 7 of your marked answers got "
            "a different grade. The numbers below still use the grades from before. To "
            "compare, run `judgekeeper check`.") in said, said
    assert "still use the grades in" not in said, said
    assert "Next: run `judgekeeper check` to compare the new grades with your marks." in said


def _regraded_elsewhere(tmp_path, monkeypatch, capsys, home, project, here):
    """A copy graded again beside the marks of the project folder `project`, a plain run
    given that folder from `here` (home folder `home`): what it says."""
    import os
    import time

    monkeypatch.setenv("HOME", str(home))
    for folder in (home, project, here):
        folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(project)
    _marked(project)
    _regraded(project, [*range(4), *range(25, 28)], name="results-regraded.json")
    later = time.time() + 60
    os.utime(project / "results-regraded.json", (later, later))
    monkeypatch.chdir(here)
    given = os.path.relpath(project, here)
    main([given, "--no-browser", "--port", "0"])
    said = _flat(capsys.readouterr().out)
    main(["--stop", given])
    capsys.readouterr()
    return said


def _compare_commands(said: str) -> list[str]:
    import re

    return [*re.findall(r"To compare, run `([^`]+)`\.", said),
            *re.findall(r"Next: run `([^`]+)` to compare", said)]


def test_the_compare_command_runs_from_the_folder_the_project_was_given_from(
        tmp_path, monkeypatch, capsys):
    """`judgekeeper ../proj` from a folder beside it: the command names the project folder,
    as the other Next lines do, so it runs as printed from there and compares."""
    home = tmp_path / "home"
    said = _regraded_elsewhere(tmp_path, monkeypatch, capsys, home, home / "proj",
                               home / "other")
    assert _compare_commands(said) == ["judgekeeper check ../proj"] * 2, said
    code, out = run(capsys, "../proj")  # drops under 20 points: worse, exit 0
    assert code == 0 and "Compared with before: worse." in _flat(out), out
    assert ("Same model and rule as before, yet 7 of your marked answers got a different grade"
            in _flat(out)), out


def test_the_compare_command_for_a_project_no_line_can_name_is_the_other_lines_form(
        tmp_path, monkeypatch, capsys):
    """A project outside the home folder, given from inside it: no line names its path
    (never the whole path), so the command has the form every other line has there."""
    from judgekeeper import start

    home = tmp_path / "home"
    said = _regraded_elsewhere(tmp_path, monkeypatch, capsys, home, tmp_path / "proj",
                               home / "other")
    other_lines = f"judgekeeper check {start.path_word('../../proj')}"
    assert _compare_commands(said) == [other_lines] * 2, said
    assert "results-regraded.json`" not in said, said


def test_going_back_to_the_marked_grades_after_a_worse_says_so(here, capsys):
    """A same-rule "Worse", then results with the grades the marks were checked with: back
    to those grades, never "not changed since your last check" (that check said Worse)."""
    _marked(here)
    _regraded(here, [*range(6), *range(25, 30)])
    code, out = run(capsys, "regraded.json")
    assert code == 1, out
    _regraded(here, [])
    code, out = run(capsys, "regraded.json")
    said = _flat(out)
    assert code == 0, out
    assert "Your results are back to the grades your marks were checked with." in said, said
    assert "has not changed since your last check" not in said, said


def test_the_same_rule_and_model_graded_again_closer_is_taken_on(here, capsys):
    """One grade turned over on a marked answer: compared, no big drop, and taken on, so the
    next check has nothing new."""
    _marked(here)
    _regraded(here, [3])
    code, out = run(capsys, "regraded.json")
    said = _flat(out)
    assert code == 0, out
    assert ("Same model and rule as before, yet 1 of your marked answers got a different grade"
            in said)
    code, out = run(capsys, "regraded.json")
    assert code == 0 and "doesn't always grade" not in _flat(out), out
    assert "has not changed since your last check" in _flat(out), out


def test_the_same_rule_model_and_grades_has_not_changed(here, capsys):
    _marked(here)
    _regraded(here, [])
    code, out = run(capsys, "regraded.json")
    assert code == 0
    assert "Your LLM-as-a-judge has not changed since you marked your answers." in out
    assert "Same model, same rule, same eval tool." in out
    assert "doesn't always grade" not in _flat(out)
