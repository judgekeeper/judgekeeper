# ruff: noqa: F811 - the fixtures come from test_check
"""`judgekeeper check` never claims more than it measured, and says where it looked.

- N04: a version change seen only in a lockfile that is newer than the results is not
  re-checked on those older results: the grades are out of date until the next eval run.
- N05: after "Worse", the old judge stays the reference: every check says it again until the
  judge goes back (or changes again), and the History gets the check once.
- N06: when the newest results hold none of the marked answers: a reason and a way forward.
- N20: a wrong PATH, or a folder under the project, says where it looked.
- N21: no "since the last check" before any check; a missing results file is said plainly.
- N24: output piped into a program that stops reading ends quietly.
- Screen 6a: the agreed words for "nothing changed" and "changed after your last eval run".
No test calls an API: asking again goes through the fake promptfoo of test_again_run.
"""

from __future__ import annotations

import json
import os

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
        "Your judge has not changed since you marked your answers.",
        "Same model, same rule, same eval tool.", "",
        "Next: nothing to do. Run `judgekeeper check` again after you",
        "change your judge."]


def test_settings_changed_after_the_last_eval_run(here, capsys, no_calls):
    _marked(here)
    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    os.utime(config, (later, later))
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines()[2:] == [
        "Step 5 of 5: Re-check", "",
        "Your judge's settings changed after your last eval run, so the",
        "grades judgekeeper has are out of date.", "",
        "Next: run your eval again, then run `judgekeeper check`."]
    assert "has not changed" not in out


def test_after_a_check_nothing_changed_names_that_check(here, capsys, no_calls):
    """N21: "since the last check" only once a check ran."""
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    assert run(capsys)[0] == 0
    code, out = run(capsys)
    assert code == 0
    assert "Your judge has not changed since your last check (" in out


# N20 ------------------------------------------------------------------------------------------

def test_a_path_that_does_not_exist(here, capsys):
    _marked(here)
    code, out = run(capsys, "nope.json")
    assert code == 2
    assert "There is no file or folder named nope.json here." in out
    assert _next(out) == "Next: run `judgekeeper check` in your project folder."


def test_a_folder_under_the_project_says_where_the_marks_are(here, capsys, monkeypatch):
    _marked(here)
    (here / "src").mkdir()
    monkeypatch.chdir(here / "src")
    code, out = run(capsys)
    assert code == 3
    assert "No marks in this folder (src). Your marks are in the folder above it" in _flat(out)
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
    assert _next(out) == "Next: run `judgekeeper mark` to mark more answers."
