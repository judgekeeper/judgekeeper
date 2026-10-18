"""Fixes from the security reviews (the stranger test and the scenario test on 1.0).

- A page opened by the program named in BROWSER stamps its marks, and the result says so
  once; the docs never say the marks are the person's.
No test calls an AI API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from judgekeeper import marks, start_label
from judgekeeper.start_label import Workspace
from tests.start_projects import promptfoo_project, split
from tests.test_check import HAIKU, no_calls  # noqa: F401
from tests.test_front import run
from tests.test_loop import _click, _flat, _post_marks

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# 1. A page opened by the program named in BROWSER --------------------------------------------

BROWSER_LINE = ("{n} of your marks came through a page opened by the program named in BROWSER, "
                "so a program could have made them. If you marked them yourself, nothing to do.")


def _lines(ws) -> list[dict]:
    return [json.loads(x) for x in ws.marks.read_text(encoding="utf-8").splitlines()[1:]]


def test_a_page_opened_through_browser_stamps_its_marks(here, capsys, no_browser, monkeypatch):
    monkeypatch.setenv("BROWSER", "/usr/local/bin/save-the-link %s")
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    ws = start_label.Workspace(here)
    assert _post_marks(no_browser[-1], ws, 36) == 36
    assert all(x["link"] == "browser-env" for x in _lines(ws))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert _flat(out).count(BROWSER_LINE.format(n=36)) == 1  # once per Measure
    report = ws.report_html.read_text(encoding="utf-8")
    assert report.count(BROWSER_LINE.format(n=36)) == 1


def test_without_browser_set_nothing_is_stamped(here, capsys, no_browser, monkeypatch):
    monkeypatch.delenv("BROWSER", raising=False)
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _post_marks(no_browser[-1], ws, 36)
    assert not any("link" in x for x in _lines(ws))
    _, out, _ = run(capsys)
    assert "named in BROWSER" not in out
    assert "named in BROWSER" not in ws.report_html.read_text(encoding="utf-8")


def test_marks_mostly_under_a_second_look_like_a_program():
    made = {"marks": 40, "pass": 20, "fail": 20, "sittings": 1, "seconds": 0,
            "under_second": 30, "not_counted": 0, "printed": 0, "browser_env": 0}
    said = start_label.made_lines(made)
    assert ("30 of your marks took under a second each. A result is only as good as the marks. "
            "This looks like a program, not a person.") in said
    made["under_second"] = 15  # more than a quarter, not more than half
    assert ("15 of your marks took under a second each. A result is only as good as the "
            "marks.") in start_label.made_lines(made)


def test_the_docs_never_say_the_marks_are_yours():
    said = ("The page accepts marks only from itself, so another website can't send marks. A "
            "program on your computer could, the same way it could edit your files.")
    for name in ("docs/reference.md", "CHANGELOG.md", "SECURITY.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "so the marks are yours" not in text, name
        assert said in text, name
    assert "so the marks are yours" not in (ROOT / "website" / "reference.html").read_text(
        encoding="utf-8")


def test_a_kept_page_is_stamped_too(here, capsys, no_browser, monkeypatch):
    """The page still open from the run before, opened again through BROWSER."""
    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = start_label.Workspace(here)
    _click(ws, n=2)
    monkeypatch.setenv("BROWSER", "save-the-link")
    run(capsys, "mark")
    _post_marks(no_browser[-1], ws, 4)
    assert [x.get("link") for x in _lines(ws)][-2:] == ["browser-env", "browser-env"]
    assert marks.made(marks.read(ws.marks))["browser_env"] >= 2


# 2. --debug prints where it went wrong, never the error's text -------------------------------

CANARY = "ZQOUT23 In Pebblequest"
REPORT = "report it at github.com/judgekeeper/judgekeeper/issues with the lines above."


def _store_fails(args):
    """An MLflow store with a bad byte in a stored answer (the P03b repro): the error quotes
    the answer, chained from the database's own error."""
    import sqlite3

    try:
        raise sqlite3.OperationalError(f"Could not decode to UTF-8 column 'preview' with text "
                                       f"'\"{CANARY}\xff, who goes first'")
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"(sqlite3.OperationalError) {e}") from e


def test_debug_prints_where_never_the_answer(here, capsys, monkeypatch):
    from judgekeeper import cli

    monkeypatch.setitem(cli.COMMANDS, None, _store_fails)
    assert cli.main(["--no-browser"]) == 2
    out, err = capsys.readouterr()
    assert CANARY not in out + err
    assert err.splitlines()[-1] == (f"Next: {REPORT} `--debug` shows where it went wrong, "
                                    "without your answers.")
    assert cli.main(["--no-browser", "--debug"]) == 2
    out, err = capsys.readouterr()
    assert CANARY not in out + err
    assert "Traceback" in err and "_store_fails" in err and "line " in err
    assert "sqlite3.OperationalError" in err and "RuntimeError" in err
    assert err.splitlines()[-1] == f"Next: {REPORT}"


# 3. A "Not sure" stays open, as a "Worse" does ------------------------------------------------

OLD = [i % 30 < 19 if i < 30 else i % 30 >= 19 for i in range(60)]  # the old judge's Pass


def _n03(root) -> Workspace:
    """N03: the person passes 30 answers and fails 30; the old judge agreed on 19 of each. The
    new judge (another model) flips every grade."""
    from judgekeeper import judge_setup, start
    from tests.test_check import _results
    from tests.test_flow_fixes import _mark

    old = OLD
    person = [i < 30 for i in range(60)]
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _results(root, old)
    found = start.find_judge(root)
    ws = Workspace(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    ws = start_label.prepare(found, say=lambda line="": None)
    _mark(ws, {i: "pass" if person[i] else "fail" for i in range(60)})
    _results(root, [not v for v in old], model=HAIKU)
    return ws


NOT_SURE = ("Not sure: 19 went from right to wrong, and 11 from wrong to right. It could be up "
            "to 52 points worse.")


@pytest.mark.usefixtures("no_calls")
def test_a_not_sure_check_says_it_again(here, capsys):
    from judgekeeper import judge_setup
    from tests.test_check import _flat, _history, _next, _results
    from tests.test_check import run as check

    ws = _n03(here)
    before = judge_setup.read(ws)["setup_hash"]
    code, out = check(capsys)
    assert code == 1 and NOT_SURE in _flat(out), out
    assert judge_setup.read(ws)["setup_hash"] == before  # the old judge stays the reference
    code, out = check(capsys)
    assert code == 1, out
    assert NOT_SURE in _flat(out)
    assert "has not changed" not in out
    assert "mark" not in _next(out).split("--new")[0].replace("marked", "")  # every one marked
    assert len(_history(ws)) == 1
    _results(here, OLD)  # back to the judge the marks were made on
    code, out = check(capsys)
    assert code == 0 and "Your judge is back to the one you marked with" in _flat(out)


# 4. No top-up on the 3rd rule: a new set at once -------------------------------------------------

@pytest.fixture
def fixing(tmp_path, monkeypatch):
    from tests.test_fix import judge as fake_judge

    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project, fake_judge.__wrapped__(project, monkeypatch)


def _fix(capsys, *argv):
    from tests.test_fix import run as fix_run

    code, out = fix_run(capsys, *argv)
    return code, " ".join(out.split())


def _leans_better(ws, holder) -> str:
    """A rule that fixes one hidden mark and breaks none: "can't tell yet, leans better"."""
    from judgekeeper import fix
    from tests.test_fix import _question, _split

    split, m = _split(ws), fix.Marks(ws)
    one = next(i for i in split["hidden"] if m.person[i] != m.judge[i])
    holder["fixes"] = {"Fix just one.": {_question(ws, one)}}
    return "Fix just one."


def test_a_third_rule_that_leans_better_gets_a_new_set_at_once(fixing, capsys):
    from tests.test_fix import _mark_more, _split, _write_rule, project

    root, holder = fixing
    holder["half"] = 40
    ws = project(root, n=80, marked=60)
    _fix(capsys)
    for k in range(2):
        _write_rule(ws, f"Rule number {k}.")
        assert _fix(capsys, "--yes")[0] == 0
    _write_rule(ws, _leans_better(ws, holder))
    code, flat = _fix(capsys, "--yes")
    assert code == 0 and "That leans toward better" in flat, flat
    assert ("You have tested 3 rules on these marks kept aside. Mark 10 more answers with "
            "`judgekeeper mark`: they become a new set kept aside, and `judgekeeper fix` tests "
            "this rule again on them.") in flat
    assert flat.endswith("Next: mark 10 more answers with `judgekeeper mark`, then run "
                         "`judgekeeper fix` again.")
    assert "mark 7 more" not in flat and "mark 9 more" not in flat
    new = _mark_more(ws, 10, 40)
    code, flat = _fix(capsys, "--yes")
    assert code == 0 and holder["evals"] == 8, flat
    assert "Tested on the 10 marks kept aside:" in flat  # the promised test, on the new set
    assert sorted(_split(ws)["hidden"]) == sorted(new)


def test_a_new_rule_while_a_top_up_waits_is_named(fixing, capsys):
    from judgekeeper import targets
    from tests.test_fix import _split, _write_rule, project

    root, holder = fixing
    holder["half"] = 40
    ws = project(root, n=80, marked=60)
    _fix(capsys)
    _write_rule(ws, _leans_better(ws, holder))
    _fix(capsys, "--yes")
    more = targets.top_up(len(_split(ws)["hidden"]))
    _write_rule(ws, "Another rule.")
    code, flat = _fix(capsys, "--yes")
    assert code == 3 and holder["evals"] == 2
    assert "testing your new rule" not in flat
    assert f"Your new rule is waiting: first mark {more} more answers" in flat
