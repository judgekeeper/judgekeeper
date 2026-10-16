"""Running `judgekeeper start` again: what is saved in `.judgekeeper/` decides what happens.

| saved                                   | start                                              |
|-----------------------------------------|----------------------------------------------------|
| nothing                                 | the full flow                                      |
| labeling not finished, no result        | "Continue?", then the page at the next answer      |
| a result, the same results              | the menu: review, label more, or nothing           |
| a result, newer results, same judge name| a re-check: the saved labels against new verdicts  |
| anything, with --new                    | moves it all to previous-<date>/ and starts fresh  |

No test opens a page: serving is replaced with a recorder.
"""

from __future__ import annotations

import pytest

from judgekeeper import start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import promptfoo_project, save_result, split


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16, labeled=None, result=True, **kwargs):
    """A project with promptfoo results and a check in `.judgekeeper/`: the first `labeled`
    answers (all when None) labeled the way the judge saw them, and a result unless not."""
    promptfoo_project(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    session = StartSession(ws)
    for item in session.items[:labeled]:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    if result:
        save_result(ws, session, say=_quiet)
    return ws


@pytest.fixture
def served(monkeypatch):
    """Serving the page is replaced: the workspaces it would have served are kept."""
    calls = []

    def serve(ws, port, open_browser, say, command="judgekeeper start"):
        calls.append(ws)
        say("(labeling page)")
        return 0

    return calls


def run(capsys, *argv):
    code = main([*map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


# Labeling not finished -------------------------------------------------------------------


# A result, and the same results ----------------------------------------------------------


# Re-check --------------------------------------------------------------------------------


# --new -----------------------------------------------------------------------------------


def test_new_twice_keeps_both_earlier_checks(tmp_path, capsys, served, monkeypatch):
    _checked(tmp_path, n_pass=20, n_fail=16)
    stamps = iter(["2026-10-05T10-00-00Z", "2026-10-06T10-00-00Z"])
    monkeypatch.setattr("judgekeeper.start_again._stamp", lambda: next(stamps))
    run(capsys, tmp_path, "--new", "--yes")
    run(capsys, tmp_path, "--new", "--yes")
    names = sorted(p.name for p in Workspace(tmp_path).dir.glob("previous-*"))
    assert names == ["previous-2026-10-05T10-00-00Z", "previous-2026-10-06T10-00-00Z"]


def test_an_unknown_new_prompt_is_not_called_a_change():
    from judgekeeper.start_again import judge_change

    assert judge_change({"prompt_hash": "abc"}, {"prompt_hash": None}) == \
        "the prompt was recorded, now not recorded"
    assert judge_change({"prompt_hash": "abc"}, {"prompt_hash": "def"}) == "the prompt changed"


