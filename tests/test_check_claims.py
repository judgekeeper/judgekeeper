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
- Screen 6a: the agreed words for "nothing changed" and "changed after your last eval run".
No test calls an API: check only reads the results files.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys

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


# Screen 6a ------------------------------------------------------------------------------------

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
                "left them out. It finds a marked answer by its exact text and question.") in said
        command = " ".join(("judgekeeper check", *given))
        assert _next(out) == ("Next: run `judgekeeper` to mark the new answers in your results: "
                              f"they join your marks as a new batch. Then run `{command}` again.")


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
    assert "There is no file or folder named nope.json here." in out
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


def test_too_few_marks_says_so_without_a_number(here, capsys):
    _marked(here, n_pass=10, n_fail=25)
    code, out = run(capsys)
    assert code == 3
    assert "You have not marked enough answers yet for a re-check." in out
    assert "15" not in out
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
    assert "Your LLM-as-a-judge is back to the one you marked with" in _flat(out)  # v2-bugfix-2 LE3


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
            "answer by its exact text and question.") in flat
    assert "labeled" not in flat
    assert _next(out) == ("Next: run `judgekeeper fix` to write the answers you marked to "
                          ".judgekeeper/fix/marked-answers.csv, grade them again with your "
                          "LLM-as-a-judge, then run `judgekeeper check <new results file>`; or "
                          "start over on your new answers with `judgekeeper --new`.")
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
    commands = re.findall(r"`(judgekeeper [^`]*)`", _next(out))
    assert commands[:2] == ["judgekeeper fix", "judgekeeper check <new results file>"]
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
