"""`check` with too few marks when no answer is left to mark but skipped ones: the Next line
the plain run gives, never "mark more answers"."""

from __future__ import annotations

import re

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, split
from tests.test_check import _flat


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _said(capsys, *argv) -> tuple[int, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, _flat(out + err)


def _next(said: str) -> str:
    return re.search(r"Next: (.*)$", said)[1]


def _marked(here, capsys, verdicts, skip=()) -> None:
    promptfoo_project(here, verdicts)
    _said(capsys, "mark", "--no-browser", "--port", "0")  # under 30 answers: `mark` starts
    main(["--stop"])
    capsys.readouterr()
    session = StartSession(Workspace(here))
    for i, item in enumerate(session.items):
        change = {"id": item["id"], "seconds": 4}
        if i in skip:
            change["deferred"] = True
        else:
            change["label"] = session.groups[item["id"]]
        session.update(change)


def test_check_with_every_answer_marked_says_to_run_the_eval_on_more(here, capsys):
    _marked(here, capsys, split(15, 9))  # 24 of 24: too few Fail marks
    code, said = _said(capsys, "check")
    assert code == 3, said
    assert _next(said) == ("run your eval on more questions, then run `judgekeeper mark`: the "
                           "new answers join the ones you marked."), said
    _, plain = _said(capsys, "--no-browser", "--port", "0")
    assert _next(plain) == _next(said), plain


def test_check_with_only_a_skipped_answer_left_says_to_look_at_it_again(here, capsys):
    _marked(here, capsys, split(30, 0), skip={29})  # 29 Pass marks and 1 skipped
    code, said = _said(capsys, "check")
    assert code == 3, said
    assert _next(said) == ("mark the one you skipped with `judgekeeper mark`, or run "
                           "your eval on more questions and run it again: the new answers join "
                           "the ones you marked."), said
    assert "to mark more answers" not in said, said
