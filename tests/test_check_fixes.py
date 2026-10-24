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
No test calls an API: asking again goes through the fake promptfoo of test_again_run.
"""

from __future__ import annotations

import io
import json
import os
import sys

from judgekeeper import judge_setup
from judgekeeper.cli import main
from tests.start_projects import promptfoo_data
from tests.test_check import (  # noqa: F401
    HAIKU,
    LENIENT,
    MARKED,
    TAG,
    _flat,
    _history,
    _marked,
    _new_outputs,
    _next,
    _results,
    _write,
    here,
    judge,
    no_calls,
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

def test_nothing_changed_says_so_in_the_agreed_words(here, capsys, no_calls):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Step 5 of 5: Re-check", "",
        "Your LLM-as-a-judge has not changed since you marked your answers.",
        "Same model, same rule, same eval tool.", "",
        "Next: nothing to do. Run `judgekeeper check` again after you",
        "change your LLM-as-a-judge."]


def test_settings_changed_after_the_last_eval_run(here, capsys, no_calls):
    _marked(here)
    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    os.utime(config, (later, later))
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Step 5 of 5: Re-check", "",
        "Your LLM-as-a-judge's settings changed after your last eval run,",
        "so the grades judgekeeper has are out of date.", "",
        "Next: run your eval again, then run `judgekeeper check`."]
    assert "has not changed" not in out


def test_after_a_check_nothing_changed_names_that_check(here, capsys, no_calls):
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
    assert _next(out) == "Next: run `judgekeeper check` in your project folder."


def test_a_folder_inside_the_project_finds_the_marks(here, capsys, monkeypatch, no_calls):
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

def test_deleted_results_are_said_plainly(here, capsys, no_calls):
    _marked(here)
    (here / "results.json").unlink()
    code, out = run(capsys)
    assert code == 3
    assert f"judgekeeper finds no promptfoo results in this folder ({here.name})." in _flat(out)
    assert str(here) not in out
    assert "would have to ask" not in out
    assert _next(out) == "Next: run your eval once, then run `judgekeeper check` again."


# A lockfile-only version update ---------------------------------------------------------------

def test_a_lockfile_update_is_not_rechecked_on_older_results(here, capsys, no_calls):
    _lock(here, "0.121.0")
    ws = _marked(here, version=None)
    assert judge_setup.read(ws)["setup"]["tool_version"] == "0.121.0"
    before = (ws.dir / "judge.json").read_bytes()
    _lock(here, "0.130.0", later=60)  # promptfoo updated; the eval not run again
    code, out = run(capsys)
    assert code == 0
    flat = _flat(out)
    assert "Your eval tool changed: promptfoo 0.121.0 -> 0.130.0." in flat
    assert ("Your LLM-as-a-judge's settings changed after your last eval run, so the grades "
            "judgekeeper has are out of date.") in flat
    assert _next(out) == "Next: run your eval again, then run `judgekeeper check`."
    assert "Re-checked" not in out and "No drop" not in out
    assert (ws.dir / "judge.json").read_bytes() == before
    assert _history(ws) == []


def test_a_lockfile_update_is_rechecked_after_the_next_eval_run(here, capsys, no_calls):
    _lock(here, "0.121.0")
    ws = _marked(here, version=None)
    _lock(here, "0.130.0", later=60)
    stamp = (here / "package-lock.json").stat().st_mtime + 60  # the eval ran on the new one
    os.utime(here / "results.json", (stamp, stamp))
    code, out = run(capsys)
    assert code == 0
    assert "Re-checked with no AI call, from your new results." in out
    assert "Re-checked on all 50 of your marks:" in out
    assert judge_setup.read(ws)["setup"]["tool_version"] == "0.130.0"


# A worse judge stays worse --------------------------------------------------------------------

def test_a_worse_judge_stays_worse_until_it_goes_back(here, capsys, no_calls):
    ws = _marked(here)
    before = judge_setup.read(ws)["setup_hash"]
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys)[0] == 1
    assert judge_setup.read(ws)["setup_hash"] == before  # the old judge stays the reference
    code, out = run(capsys)
    assert code == 1
    assert "Worse: 9 answers went from right to wrong, and none from wrong to right." in _flat(out)
    assert "has not changed" not in out
    assert len(_history(ws)) == 1  # the same check is in the History once
    _results(here, MARKED)  # back to the old judge
    code, out = run(capsys)
    assert code == 0 and "has not changed" not in out
    assert "Your LLM-as-a-judge is back to the one you marked with" in _flat(out)  # v2-bugfix-2 LE3


def test_after_worse_judgekeeper_still_points_at_check(here, capsys, no_calls):
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

def test_no_marked_answer_in_the_new_results_says_why_and_what_to_do(here, capsys, judge):
    ws = _marked(here)
    data = promptfoo_data(LENIENT, model=HAIKU, tag=" OTHER")  # other questions
    data["metadata"]["promptfooVersion"] = "0.124.1"
    _write(here / "results.json", data)
    code, out = run(capsys, "--yes")
    assert code == 3
    flat = _flat(out)
    assert ("Your newest results don't contain the answers you marked, so your LLM-as-a-judge can't "
            "grade them again.") in flat
    assert "labeled" not in flat
    assert _next(out) == ("Next: run your eval on the questions you marked, then run "
                          "`judgekeeper check` again; or start over on your new answers with "
                          "`judgekeeper --new`.")
    assert _history(ws) == []


# A closed output pipe -------------------------------------------------------------------------

class _Closed(io.StringIO):
    """A pipe whose reader stopped reading (`| head`)."""

    def write(self, text):
        raise BrokenPipeError(32, "Broken pipe")

    def fileno(self):
        raise io.UnsupportedOperation


def test_a_closed_pipe_ends_quietly(here, capsys, monkeypatch, no_calls):
    _marked(here)
    monkeypatch.setattr(sys, "stdout", _Closed())
    assert main(["check"]) == 0
    assert capsys.readouterr().err == ""
