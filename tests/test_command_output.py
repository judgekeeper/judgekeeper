"""What the commands say around the marking page and the result, and how they stop.

- A page opened by the program named in BROWSER stamps its marks, and the result says so
  once; the docs never say the marks are the person's.
- --debug shows where it went wrong, never the error's text; a "Not sure" check stays open;
  fix's top-up after a 3rd rule, its not-counted answers and the missing key; Inspect logs in
  several folders are asked about.
- The order and the words of what is said, the ports, the page that stays open after the result
  until it is idle, Ctrl-C from the first line, damaged files named, an old pre-commit line.
No test calls an AI API.
"""

from __future__ import annotations

import json
import re
import sys
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


# A page opened by the program named in BROWSER -----------------------------------------------

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
    in_security = ("Every change must also come from the page itself: `Origin: "
                   "http://127.0.0.1:<port>`, and `Sec-Fetch-Site: same-origin` when the browser "
                   "sends it. So another website can't send marks. A program on your computer "
                   "could, the same way it could edit your files.")
    for name in ("docs/reference.md", "CHANGELOG.md", "SECURITY.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "so the marks are yours" not in text, name
        assert (in_security if name == "SECURITY.md" else said) in text, name
    for page in (ROOT / "website").rglob("*.html"):  # the full reference is docs/reference.md
        assert "so the marks are yours" not in page.read_text(encoding="utf-8"), page.name


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


# --debug prints where it went wrong, never the error's text ----------------------------------

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


# A "Not sure" stays open, as a "Worse" does ---------------------------------------------------

OLD = [i % 30 < 19 if i < 30 else i % 30 >= 19 for i in range(60)]  # the old judge's Pass


def _n03(root) -> Workspace:
    """N03: the person passes 30 answers and fails 30; the old LLM-as-a-judge agreed on 19 of each. The
    new LLM-as-a-judge (another model) flips every grade."""
    from judgekeeper import judge_setup, start
    from tests.test_check import _results
    from tests.test_project_folder import _mark

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


NOT_SURE = ("Result: not sure. These marks can't tell whether your new LLM-as-a-judge agrees "
            "with you less. Agreed with you: Old LLM-as-a-judge New LLM-as-a-judge When you said "
            "Pass 19 of 30 11 of 30 Not sure When you said Fail 19 of 30 11 of 30 Not sure")


@pytest.mark.usefixtures("no_calls")
def test_a_not_sure_check_says_it_again(here, capsys):
    from judgekeeper import judge_setup
    from tests.test_check import _flat, _history, _next, _results
    from tests.test_check import run as check
    from tests.test_project_folder import NEXT_ALL_MARKED

    ws = _n03(here)
    before = judge_setup.read(ws)["setup_hash"]
    code, out = check(capsys)
    assert code == 1 and NOT_SURE in _flat(out), out
    assert judge_setup.read(ws)["setup_hash"] == before  # the old judge stays the reference
    code, out = check(capsys)
    assert code == 1, out
    assert NOT_SURE in _flat(out)
    assert "has not changed" not in out
    assert _next(out) == NEXT_ALL_MARKED  # every one marked: no "mark N more" from a Not sure
    assert len(_history(ws)) == 1
    _results(here, OLD)  # back to the judge the marks were made on
    code, out = check(capsys)
    assert code == 0 and "Your LLM-as-a-judge is back to the one you marked with" in _flat(out)


# No top-up on the 3rd rule: a new set at once ----------------------------------------------------

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
    assert "Your LLM-as-a-judge, tested on the 10 marks kept aside:" in flat  # the promised test, on the new set
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
    assert code == 0 and holder["evals"] == 2  # the clues show while the test waits
    assert "testing your new rule" not in flat
    assert (f"Your last rule test is waiting for more marks: it couldn't tell yet. Mark {more} "
            "more answers, and `judgekeeper fix` tests that rule again on them.") in flat
    assert f"Your new rule is waiting: first mark {more} more answers" in flat


# Answers the judge errors on in both runs are counted once -----------------------------------

def test_answers_not_counted_in_both_runs_are_counted_once(fixing, capsys):
    from tests.test_again_run import FakePromptfoo
    from tests.test_fix import NEW_RULE, _split, _write_rule, project

    root, holder = fixing
    ws = project(root)
    _fix(capsys)
    hidden = _split(ws)["hidden"]
    k = len(hidden) // 2
    holder["fake"] = FakePromptfoo(Workspace(root), version="0.124.1")
    holder["fake"].errors = set(hidden[:k])  # in the old rule's run and in the new one's
    _write_rule(ws, NEW_RULE)
    code, flat = _fix(capsys, "--yes")
    assert code == 0, flat
    assert f"Your LLM-as-a-judge, tested on the {len(hidden) - k} marks kept aside:" in flat
    assert f"{k} answers were not counted: the LLM-as-a-judge gave no clear decision." in flat
    assert flat.count("were not counted") == 1


# promptfoo grader errors are not grades --------------------------------------------------------

GRADER_ERRORS = "{n} answers were not counted: the LLM-as-a-judge's tool gave an error for them."


def test_fix_does_not_count_promptfoo_grader_errors_as_grades(fixing, capsys):
    from tests.test_again_run import FakePromptfoo
    from tests.test_fix import NEW_RULE, _split, _write_rule, project

    root, holder = fixing
    ws = project(root)
    _fix(capsys)
    hidden = _split(ws)["hidden"]
    holder["fake"] = FakePromptfoo(Workspace(root), version="0.124.1")
    holder["fake"].grader_errors = set(hidden[:6])  # promptfoo saved them as pass: false
    _write_rule(ws, NEW_RULE)
    code, flat = _fix(capsys, "--yes")
    assert code == 0, flat
    assert f"Your LLM-as-a-judge, tested on the {len(hidden) - 6} marks kept aside:" in flat
    assert GRADER_ERRORS.format(n=6) in flat
    assert "New rule: agreed with you on 10 of 10 answers." in flat  # errors are no fails
    assert "none from right to wrong." in flat


@pytest.mark.usefixtures("no_calls")
def test_check_does_not_count_promptfoo_grader_errors_as_grades(here, capsys, monkeypatch):
    from tests.test_again_run import FakePromptfoo
    from tests.test_check import LENIENT, _marked, _new_outputs, _results
    from tests.test_check import judge as fake_judge
    from tests.test_check import run as check

    holder = fake_judge.__wrapped__(monkeypatch, here)
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    holder["fake"] = FakePromptfoo(ws, version="0.124.1")
    last = marks.read(ws.marks).last
    marked = {k: sorted(i for i, x in last.items() if x["mark"] == k) for k in ("pass", "fail")}
    holder["fake"].grader_errors = set(marked["pass"][:3] + marked["fail"][:3])
    code, out = check(capsys, "--yes")
    flat = _flat(out)
    assert code == 1, out
    assert GRADER_ERRORS.format(n=6) in flat
    assert "Re-checked on 44 of your 50 marks:" in flat, flat
    assert "When you said Pass 22 of 22 22 of 22" in flat, flat  # the 3 errors are no fails
    assert re.search(r"When you said Fail \d+ of 22 \d+ of 22", flat), flat


# No key: which key, and where to set it -------------------------------------------------------

NEEDS = "Your LLM-as-a-judge needs ANTHROPIC_API_KEY. It is not set in your shell or in .env."


def _no_keys(monkeypatch):
    from judgekeeper import keys

    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)


def test_fix_names_the_key_a_claude_geval_needs(tmp_path, stubs, monkeypatch, capsys):
    from tests.test_again_tools import _deepeval_model

    monkeypatch.chdir(tmp_path)
    ws = _deepeval_model(tmp_path, "claude-haiku-5-5 (Anthropic)", monkeypatch)
    _no_keys(monkeypatch)
    _fix(capsys)
    (ws.dir / "fix" / "rule.txt").write_text("1. Is it kind?\n2. Is it short?\n",
                                              encoding="utf-8")
    code, flat = _fix(capsys, "--yes")
    assert code == 3, flat
    assert NEEDS in flat
    assert "isn't set where judgekeeper runs" not in flat
    assert flat.endswith("Next: set ANTHROPIC_API_KEY in your shell or in .env, then run "
                         "`judgekeeper fix` again.")


def test_check_names_the_key_its_new_judge_needs(here, capsys, monkeypatch):
    from tests.test_check import _marked
    from tests.test_check import run as check
    from tests.test_flow_across_runs import _new_judge_on_a_few, grader

    grader.__wrapped__(monkeypatch, here)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    _marked(here)
    _new_judge_on_a_few(here)
    code, out = check(capsys, "--yes")
    flat = " ".join(out.split())
    assert code == 1, out  # 5 answers re-checked with no AI call: "Not sure", a big drop
    assert NEEDS in flat
    assert flat.endswith("Next: set ANTHROPIC_API_KEY in your shell or in .env, then run "
                         "`judgekeeper check` again.")


# Inspect logs in more than one folder: which ----------------------------------------------------

def test_inspect_logs_in_two_folders_are_asked_about(here, capsys):
    import os

    from judgekeeper.textio import quote_arg
    from tests.start_projects import inspect_project
    from tests.test_front import assert_one_next_at_the_end

    old = inspect_project(here, split(20, 16), name="evals/quiz/logs/2026-10-01_quiz.json")
    new = inspect_project(here, split(20, 16), name="evals/chat/logs/2026-10-02_chat.json",
                          tag=" chat")
    os.utime(old, (new.stat().st_mtime - 60,) * 2)
    code, out, _ = run(capsys)
    assert code == 3, out
    assert "Inspect logs in more than one folder:" in out
    chat, quiz = (quote_arg(f"evals/{a}/logs") for a in ("chat", "quiz"))
    assert assert_one_next_at_the_end(out) == (
        "Next: choose which Inspect logs to check (evals/chat/logs, evals/quiz/logs), then run "
        f"`judgekeeper {chat}` or `judgekeeper {quiz}`.")
    assert not (here / ".judgekeeper" / "pool.jsonl").exists()
    code, out, _ = run(capsys, "evals/quiz/logs")
    assert "Inspect logs in more than one folder" not in out
    assert "36 answers" in out


def test_at_a_terminal_the_logs_folder_is_asked_and_kept(here, capsys, monkeypatch):
    import os
    import tomllib

    from tests.start_projects import inspect_project
    from tests.test_front import terminal

    answers, _ = terminal.__wrapped__(monkeypatch)
    old = inspect_project(here, split(20, 16), name="evals/quiz/logs/2026-10-01_quiz.json")
    new = inspect_project(here, split(9, 9), name="evals/chat/logs/2026-10-02_chat.json",
                          tag=" chat")
    os.utime(old, (new.stat().st_mtime - 60,) * 2)
    answers += ["2", ""]  # evals/quiz/logs; save? yes
    run(capsys)
    saved = tomllib.loads((here / "judgekeeper.toml").read_text(encoding="utf-8"))["start"]
    assert saved["source"] == "inspect" and saved["file"] == "evals/quiz/logs"
    _, out, _ = run(capsys)  # asked once
    assert "more than one folder" not in out
    started = (here / ".judgekeeper" / "start.json").read_text(encoding="utf-8")
    assert "evals/quiz/logs/2026-10-01_quiz.json" in started and "chat" not in started


# "Left out" lines come after Step 1, with a blank line before the found block ------------------

def _inspect_log(root, name, created, judged=True, n=(18, 18)):
    from tests.test_inspect_newest_judge import _log

    _log(root, name, created, judged=judged, n=n)


def _before(out: str, first: str, then: str) -> bool:
    return first in out and then in out and out.index(first) < out.index(then)


def test_a_left_out_log_after_marking_comes_after_step_1(here, capsys):
    _inspect_log(here, "2026-10-01_support.json", "2026-10-01T10:00:00+00:00")
    run(capsys)
    _click(Workspace(here))
    run(capsys, "--stop")
    _inspect_log(here, "2026-10-02_exact.json", "2026-10-02T10:00:00+00:00", judged=False)
    code, out, _ = run(capsys)
    assert code == 0, out
    left = "logs/2026-10-02_exact.json is left out: no LLM-as-a-judge in it."
    assert "Step 1 of 5: Find\n\n" + left + "\n\nStep 3 of 5: Measure" in out


def test_a_subfolder_with_no_judge_still_says_step_1(here, capsys):
    _inspect_log(here, "2026-10-01_support.json", "2026-10-01T10:00:00+00:00")
    run(capsys)
    _inspect_log(here / "sub", "2026-10-03_exact.json", "2026-10-03T10:00:00+00:00",
                 judged=False)
    code, out, _ = run(capsys, "sub")
    assert code == 3
    assert out.startswith("judgekeeper ") and out.splitlines()[2] == "Step 1 of 5: Find", out


def test_a_file_left_out_is_followed_by_a_blank_line(here, capsys):
    import os

    from tests.start_projects import promptfoo_data

    (here / "results.json").write_text(json.dumps(promptfoo_data(split(5, 5))),
                                       encoding="utf-8")
    old = json.dumps(promptfoo_data(split(20, 16)))
    (here / "results-old.json").write_text(old[:len(old) // 2], encoding="utf-8")
    older = (here / "results.json").stat().st_mtime - 3600
    os.utime(here / "results-old.json", (older, older))
    _, out, _ = run(capsys, "--no-browser")
    lines = out.splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith("Eval tool:"))
    assert lines[at - 1] == "", out
    assert all(len(x) <= 80 for x in lines), out
    assert _before(out, "Step 1 of 5: Find", "left out") and _before(out, "left out", "Eval tool")


# Said once: promptfoo's default grader, and the MLflow command -----------------------------------

def test_promptfoos_default_grader_is_explained_once(here, capsys):
    from tests.start_projects import promptfoo_data

    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    (here / "results.json").write_text(json.dumps(promptfoo_data(split(20, 16), model=None)),
                                       encoding="utf-8")
    _, out, _ = run(capsys, "--no-browser")
    flat = " ".join(out.split())
    assert "LLM-as-a-judge: promptfoo's default grader (no model written in your config)" in flat, out
    assert "model not found" not in flat and "--judge-model" not in flat
    assert flat.count("default grader") == 1  # the LLM-as-a-judge: line
    assert flat.count("defaultTest.options.provider") == 1
    assert "came from promptfoo's default grader" not in flat


# The llm-rubric line names the config file; defaultTest's rubric is said -----------------------

def _two_rubrics(default: bool = False) -> dict:
    from tests.test_promptfoo_two_rubrics import _two_rubrics as two

    data = two()
    if default:  # defaultTest adds one to every test, and each test has its own
        data["config"]["defaultTest"] = {"assert": [{"type": "llm-rubric", "value": "Polite."}]}
        for row in data["results"]["results"]:
            comps = row["gradingResult"]["componentResults"]
            if len(comps) == 1:
                comps.append(json.loads(json.dumps(comps[0])))
    return data


def test_two_configs_name_the_one_beside_the_results(here, capsys):
    from tests.test_promptfoo_two_rubrics import CONFIG

    for folder in ("02", "03"):  # neither says which results are its own
        (here / folder).mkdir()
        (here / folder / "promptfooconfig.yaml").write_text(
            CONFIG.replace("description: support bot\n", ""), encoding="utf-8")
    data = _two_rubrics()
    data["config"].pop("description")
    (here / "03" / "results.json").write_text(json.dumps(data), encoding="utf-8")
    _, out, err = run(capsys)
    assert "your promptfoo config" not in out + err, out + err
    assert "03/results.json: test 3 in 03/promptfooconfig.yaml has more than one" in err, out


def test_a_rubric_in_default_test_is_said(here, capsys):
    from tests.test_promptfoo_two_rubrics import _config

    _config(here)
    (here / "results.json").write_text(json.dumps(_two_rubrics(default=True)), encoding="utf-8")
    code, out, err = run(capsys)
    flat = " ".join((out + err).split())
    assert code == 2
    assert ("results.json: defaultTest adds an llm-rubric to every test in "
            "promptfooconfig.yaml, and each test has its own, so each has two. Give each one a "
            "name with metric: in its assertion") in flat
    assert "test 1 in" not in flat


# Small words --------------------------------------------------------------------------------------

def test_judge_names_in_a_list_are_quoted_alike(here, capsys):
    import copy

    from tests.start_projects import deepeval_data

    data = deepeval_data(split(5, 5))
    for case in data["testCases"]:
        case["metricsData"][0]["name"] = "Answer Relevancy"
        other = copy.deepcopy(case["metricsData"][0])
        other["name"] = "Faithfulness"
        case["metricsData"].append(other)
    (here / ".deepeval").mkdir()
    (here / ".deepeval" / ".latest_run_full.json").write_text(json.dumps(data),
                                                              encoding="utf-8")
    _, out, _ = run(capsys)
    alike = ('("Answer Relevancy", "Faithfulness")' if sys.platform == "win32"
             else "('Answer Relevancy', 'Faithfulness')")  # each shell's own quotes
    assert alike in " ".join(out.split()), out


def test_one_answer_is_not_each(here, capsys):
    promptfoo_project(here, [True])
    _, out, _ = run(capsys, "--no-browser")
    assert "Answers:         1 answer\n" in out and "each" not in out.split("Answers:")[1][:20], out


PIN_LINE = ("judgekeeper can't see your eval tool's version. Write its version in your project's "
            "requirements{example}, so `check` notices when it changes.")


@pytest.mark.parametrize("venv, example", [
    (True, " (e.g. `deepeval==3.4.1`)"),  # the project's, never the one uvx runs judgekeeper with
    (False, ""),
])
def test_pin_it_says_what_and_why_with_the_projects_version(here, capsys, monkeypatch, venv,
                                                             example):
    from judgekeeper import judge_check, textio
    from tests.start_projects import deepeval_project

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(judge_check, "installed", lambda package: "9.9.9")
    monkeypatch.setattr(textio, "started_by_uvx", lambda: True)
    if venv:
        site = here / ".venv" / "lib" / "python3.12" / "site-packages"
        (site / "deepeval-3.4.1.dist-info").mkdir(parents=True)
    deepeval_project(here, split(20, 16))
    _, out, _ = run(capsys, "--no-browser")
    flat = " ".join(out.split())
    assert PIN_LINE.format(example=example) in flat, out
    assert "9.9.9" not in flat and "Pin it" not in flat


def test_one_range_form_everywhere():
    assert start_label.side_sentence("tpr", 0.61, (0.42, 0.78)) == (
        "You passed: your LLM-as-a-judge also passed about 61% (between 42% and 78%).")
    for name in ("README.md", "docs/reference.md", "website/index.html"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"could be \d+%", text), name
    assert '"about 89% (between 84% and 93%)"' in (ROOT / "README.md").read_text(encoding="utf-8")


def test_a_split_the_sign_test_does_not_pass_is_cant_tell_yet():
    from judgekeeper import fix, targets

    assert targets.fix_verdict(2, 8, 26).kind == "leans worse"  # p = 0.11
    assert fix.RESULT["leans worse"] == ("Result: can't tell yet. That leans toward worse; keep "
                                         "the old rule.")
    assert targets.fix_verdict(0, 12, 26).kind == "worse"
    assert fix.RESULT["worse"] == "Result: it looks worse. Keep the old rule."


def test_a_bad_pass_if_is_not_repeated_in_the_next_line(here, capsys):
    from judgekeeper.textio import quote_arg
    from tests.start_projects import table_project

    table_project(here, split(20, 16))
    code, _, err = run(capsys, "--pass-if", "0.5", "--no-browser")
    assert code == 2
    assert err.splitlines()[-1] == ("Next: run `judgekeeper --no-browser --pass-if "
                                    f"{quote_arg('score>=0.5')}`."), err  # as the shell writes it
    code, _, err = run(capsys, "--label-map", "good", "--no-browser")
    assert code == 2
    assert "--label-map good" not in err.splitlines()[-1], err


def test_no_placeholder_in_angle_brackets_in_backticks():
    pattern = re.compile(r"`[^`\n]*<[a-z][^`>\n]*>[^`\n]*`")
    for path in (ROOT / "src" / "judgekeeper").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = [m for m in pattern.findall(text) if "previous-<date>" not in m
                 and "<criterion>" not in m and "<scorer>" not in m]
        assert not [m for m in found if "<the" in m or "<your" in m], (path.name, found)


# More small words ------------------------------------------------------------------------------

@pytest.mark.usefixtures("no_calls")
def test_a_damaged_results_file_in_check_ends_with_one_stop(here, capsys):
    from tests.test_check import _marked
    from tests.test_check import run as check

    _marked(here)
    text = (here / "results.json").read_text(encoding="utf-8")
    (here / "results.json").write_text(text[:len(text) // 2], encoding="utf-8")
    code, out = check(capsys)
    flat = " ".join(out.split())
    assert code == 3 and "Save it again from promptfoo." in flat, out
    assert ".." not in flat


def test_fix_waits_for_one_more_answer_in_the_singular(fixing, capsys):
    from tests.test_fix import _mark_more, _write_rule, project

    root, holder = fixing
    holder["half"] = 40
    ws = project(root, n=80, marked=60)
    _fix(capsys)
    for k in range(3):
        _write_rule(ws, f"Rule number {k}.")
        _fix(capsys, "--yes")
    _mark_more(ws, 9, 40)
    _write_rule(ws, "Rule number 3.")
    _, flat = _fix(capsys)
    assert "Next: mark 1 more answer with `judgekeeper mark`" in flat, flat


def test_the_table_depth_is_said_alike_in_the_terminal_and_the_reference():
    from judgekeeper import find

    said = find.looked(ROOT)
    assert "(tables: 2 folders deep)" in said and "1 folder down" not in said
    ref = " ".join((ROOT / "docs" / "reference.md").read_text(encoding="utf-8").split())
    assert "A CSV, TSV or JSONL file at most two folders deep" in ref


def test_one_damaged_row_is_its_only_row():
    from judgekeeper.records import Damaged, RecordList, all_damaged, left_out_note

    records = RecordList(unit="row")
    records.left_out = [1]
    with pytest.raises(Damaged) as e:
        all_damaged("results.json", "promptfoo", records)
    assert "results.json is damaged: its only row has a damaged field." in str(e.value)
    assert "each of its 1" not in str(e.value)
    lines = RecordList(unit="line")
    lines.left_out = [4]
    assert left_out_note(lines, "x.jsonl").endswith("line 4 has a damaged field.")


def test_or_save_comes_after_its_first_choice(capsys):
    from judgekeeper import own_map, start

    talk = start.Talk()
    with pytest.raises(start.Stop):
        raise own_map.cannot(talk, "history/evals.jsonl", "no LLM-as-a-judge verdicts were found in it")
    out = " ".join(capsys.readouterr().out.split())
    first = "Turn it into a CSV, as the Next: line says."
    assert first in out and out.index(first) < out.index("Or save your LLM-as-a-judge's decisions")


def test_fix_with_no_results_says_so_first(here, capsys):
    code, flat = _fix(capsys)
    assert code == 3
    assert f"No eval results found in this folder ({here.name})." in flat, flat
    assert "marked enough" not in flat and "`judgekeeper mark`" not in flat
    assert flat.endswith("Next: run your eval once from this folder, then run `judgekeeper`.")


@pytest.mark.usefixtures("no_calls")
def test_a_pass_mark_change_made_without_fix_is_no_pick(here, capsys):
    from judgekeeper import judge_setup, start
    from judgekeeper.start_label import StartSession
    from tests.start_projects import deepeval_data, deepeval_project
    from tests.test_check import TAG, _write
    from tests.test_check import run as check

    deepeval_project(here, split(25, 25), tag=TAG)
    (here / "requirements.txt").write_text("deepeval==4.2.8\n", encoding="utf-8")
    found = start.find_judge(here)
    judge_setup.save(Workspace(here), judge_setup.of(found))
    ws = start_label.prepare(found, say=lambda line="": None)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    data = deepeval_data(split(25, 25), tag=TAG)
    for case in data["testCases"]:
        case["metricsData"][0]["threshold"] = 0.7
    _write(here / ".deepeval" / ".latest_run_full.json", data)
    _, out = check(capsys)
    flat = " ".join(out.split())
    assert "Your LLM-as-a-judge changed: pass mark 0.5 -> 0.7." in flat, out
    assert "helped pick" not in flat
    assert "you looked at to write this rule" not in flat


@pytest.mark.usefixtures("no_calls")
def test_a_rule_change_made_without_fix_is_no_pick(here, capsys):
    from tests.test_check import MARKED, _marked, _results
    from tests.test_check import run as check

    _marked(here)
    _results(here, MARKED, rubric="Is polite, correct and short.")
    _, out = check(capsys)
    flat = " ".join(out.split())
    assert "Your LLM-as-a-judge changed: rule changed." in flat, out
    assert "helped pick" not in flat
    assert "you looked at to write this rule" not in flat


def test_a_browser_that_hangs_still_gets_the_link_printed(here, capsys, monkeypatch):
    from judgekeeper import page
    from tests.test_loop import LINK, OPEN

    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(page, "_clock", lambda: next(ticks, 31.0))
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert LINK in out and "http://127.0.0.1:" in out
    assert OPEN not in out


# A port held by judgekeeper's page for another folder ----------------------------------------

def test_a_port_held_by_another_projects_page_names_it(tmp_path, monkeypatch, capsys, pages):
    from judgekeeper import label
    from tests.test_front import assert_one_next_at_the_end

    quiz, support = tmp_path / "quiz-bot", tmp_path / "support-bot"
    for root in (quiz, support):
        root.mkdir()
        promptfoo_project(root, split(20, 16))
    monkeypatch.chdir(quiz)
    run(capsys)
    port = label.read_lock(quiz / ".judgekeeper")["port"]
    monkeypatch.chdir(support)
    pages[1]["fail"] = True  # the page can't start: its port is held
    code, out, _ = run(capsys, "--port", str(port))
    assert code == 3, out
    flat = " ".join(out.split())
    assert f"Port {port} is in use by judgekeeper's marking page for quiz-bot." in flat
    assert assert_one_next_at_the_end(out) == (
        "Next: run `judgekeeper --stop` there, or `judgekeeper --port 0`.")


def test_without_the_token_only_the_folder_name_is_told(here, capsys):
    from judgekeeper import label

    promptfoo_project(here, split(20, 16))
    run(capsys)
    port = label.read_lock(here / ".judgekeeper")["port"]
    assert label.page_folder(port) == here.name
    status, body = label._answer(port, "GET", "/state", {})
    assert status == 403 and b"Question" not in body


# Every answer marked and the result opened: the page stays until it is idle --------------------

def test_the_page_stays_open_after_the_result_with_every_answer_marked(here, capsys,
                                                                       no_browser):
    """The result page may still ask the page (reasons), so it stays; 30 minutes without a
    request close it (label.IDLE_TIMEOUT), and the next run says nothing about it."""
    import urllib.request

    from judgekeeper import label

    promptfoo_project(here, split(20, 16))
    run(capsys)
    ws = Workspace(here)
    _post_marks(no_browser[-1], ws, 36)
    base, token = no_browser[-1].split("/?token=")
    with urllib.request.urlopen(f"{base}/result?token={token}", timeout=10) as r:
        assert r.status == 200
    assert label.is_open(ws.dir)
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "marking page" not in out, out  # nothing left to mark: not a word about the page
    assert label.is_open(ws.dir)
    _, out, _ = run(capsys, "--stop")
    assert "Closed the marking page." in out
    _, out, _ = run(capsys, "--stop")
    assert "No marking page is open." in out


# A rule that copies answer text is never printed ----------------------------------------------

def test_a_rule_copied_from_answers_is_not_printed(fixing, capsys):
    from judgekeeper import fix
    from tests.test_fix import _split, _write_rule, project

    root, _ = fixing
    ws = project(root)
    _fix(capsys)
    m = fix.Marks(ws)
    copied = next(m.row(i)["output"] for i in _split(ws)["visible"]
                  if "refund" in m.row(i)["output"])
    _write_rule(ws, f"{copied} Grade it as the person would.")
    _, flat = _fix(capsys)
    assert "New rule: from .judgekeeper/fix/rule.txt" in flat, flat
    assert "It copies text from your answers" in flat
    assert copied[:20] not in flat


# Ctrl-C from the first line ------------------------------------------------------------------

def test_ctrl_c_while_the_commands_load_says_stopped(monkeypatch, capsys):
    import builtins
    import sys

    from judgekeeper import __main__ as entry

    real = builtins.__import__

    def interrupted(name, *args, **kwargs):
        if name == "judgekeeper.cli":
            raise KeyboardInterrupt
        return real(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "judgekeeper.cli", raising=False)
    monkeypatch.setattr(builtins, "__import__", interrupted)
    assert entry.main(["--no-browser"]) == 130
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert out.out.splitlines()[-2:] == ["Stopped.", "Next: run `judgekeeper` to carry on."]


def test_ctrl_c_while_the_arguments_are_read_says_stopped(monkeypatch, capsys):
    from judgekeeper import cli

    def interrupted(args_list):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "parse_args", interrupted)
    assert cli.main(["--no-browser"]) == 130
    out = capsys.readouterr()
    assert out.out == "\nStopped.\nNext: run `judgekeeper --no-browser` to carry on.\n"


def test_the_command_starts_from_the_light_entry():
    import tomllib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"]
    assert scripts == {"judgekeeper": "judgekeeper.__main__:main"}
    text = (ROOT / "src" / "judgekeeper" / "__main__.py").read_text(encoding="utf-8")
    assert "\nfrom judgekeeper.cli import" not in text  # loaded inside main, under its try


# Damage named ----------------------------------------------------------------------------------

def _promptfoo_shaped(root, change) -> None:
    from tests.start_projects import promptfoo_data

    data = promptfoo_data(split(20, 16))
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    (root / "results.json").write_text(json.dumps(change(data)), encoding="utf-8")


@pytest.mark.parametrize("change, why", [
    (lambda d: {**d, "results": d["results"]["results"]}, 'its "results" is a list'),
    (lambda d: "a string", "it holds a string, not a JSON object"),
    (lambda d: {**d, "config": [1, 2]}, 'its "config" is a list'),
])
def test_a_promptfoo_results_file_of_the_wrong_shape_is_named(here, capsys, change, why):
    _promptfoo_shaped(here, change)
    code, out, err = run(capsys, "--no-browser")
    flat = " ".join((out + err).split())
    assert code == 2, flat
    assert f"results.json isn't a promptfoo results file ({why})." in flat
    assert "didn't expect" not in flat and "own database" not in flat


class MlflowException(Exception):
    """MLflow's own error, as it wraps the database's."""


def _store_error(*args, **kwargs):
    import sqlite3

    try:
        raise sqlite3.DatabaseError("file is not a database")
    except sqlite3.DatabaseError as e:
        raise MlflowException(f"(sqlite3.DatabaseError) {e}") from e


def test_a_damaged_mlflow_db_is_named(here, capsys, monkeypatch):
    from judgekeeper import start
    from judgekeeper.readers import mlflow_store

    (here / "mlflow.db").write_bytes(b"not a database at all " * 40)
    monkeypatch.setattr(start, "_has", lambda module: True)
    monkeypatch.setattr(mlflow_store, "store_uri", lambda path, say=None: f"sqlite:///{path}")
    monkeypatch.setattr(start, "_mlflow_experiment", _store_error)
    code, out, err = run(capsys, "--no-browser")
    flat = " ".join((out + err).split())
    assert code == 2, flat
    assert "mlflow.db can't be read: it's damaged. Save it again from MLflow." in flat
    assert "didn't expect" not in flat


def test_a_one_line_file_too_big_to_look_into_is_named(here, capsys):
    row = {"run_id": "run-0", "judge": "claude-opus-5",
           "cases": [{"case_id": f"case-{i}", "prompt": f"Question {i}?",
                      "responses": {"A": "x" * 200},
                      "scores": {"A": {"safe": {"score": 0.9, "reason": "r"}}}}
                     for i in range(600)]}
    (here / "data").mkdir()
    (here / "data" / "prompt_evals.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    code, out, _ = run(capsys)
    flat = " ".join(out.split())
    assert code == 3
    assert "data/prompt_evals.jsonl" in flat, out
    assert "too big to look into" in flat


# An old pre-commit hook line ------------------------------------------------------------------

OLD_HOOK = ("Your git pre-commit hook still runs `judgekeeper check --fast`, which was removed. "
            "Delete that line from .git/hooks/pre-commit.")


@pytest.mark.parametrize("argv", [(), ("check",), ("fix",), ("mark", "--no-browser")])
def test_an_old_pre_commit_line_is_said_once(here, capsys, argv):
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    text = "#!/bin/sh\nuvx judgekeeper@1.0.0b2 check --fast || exit $?\n"
    hook.write_text(text, encoding="utf-8")
    promptfoo_project(here, split(20, 16))
    _, out, _ = run(capsys, *argv)
    assert " ".join(out.split()).count(OLD_HOOK) == 1, out
    assert hook.read_text(encoding="utf-8") == text  # never edited


def test_a_hook_without_the_old_line_says_nothing(here, capsys):
    hook = here / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nruff check\n", encoding="utf-8")
    promptfoo_project(here, split(20, 16))
    _, out, _ = run(capsys)
    assert "pre-commit" not in out


# A port judgekeeper picked and lost before the page bound it ----------------------------------

def test_a_picked_port_lost_to_another_run_gets_the_next_free_one(here, capsys, monkeypatch,
                                                                   pages):
    from judgekeeper import background, page

    started, _ = pages
    fake = background.start
    lost = set()

    def start(folder, settings, token, timeout=background.WAIT):
        if not lost:  # another run took the port between the check and the bind
            lost.add(settings["port"])
            started.append(dict(settings))
            return None
        return fake(folder, settings, token, timeout)

    monkeypatch.setattr(background, "start", start)
    real_free = page.port_free
    monkeypatch.setattr(page, "port_free", lambda port: port not in lost and real_free(port))
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys)
    assert code == 0, out
    assert "could not start" not in out
    assert len(started) == 2 and started[1]["port"] != started[0]["port"]


def test_a_port_the_person_named_is_not_changed(here, capsys, pages):
    _, state = pages
    state["fail"] = True
    promptfoo_project(here, split(20, 16))
    code, _, _ = run(capsys, "--port", "9871")
    assert code == 3 and len(pages[0]) == 1


# The Python uvx runs judgekeeper with is never named by its cache path ------------------------

def test_uvx_python_is_named_in_words(tmp_path, monkeypatch):
    import sys

    from judgekeeper import again
    from judgekeeper.again import AgainOptions, make_plan
    from tests.start_projects import deepeval_project
    from tests.test_again_tools import _checked

    cache = "/home/me/.cache/uv/archive-v0/abc123/bin/python"
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(sys, "executable", cache)
    monkeypatch.setattr(again, "run_worker", lambda *a, **k: {"ok": False, "missing": True})
    ws = _checked(tmp_path, lambda r, v: deepeval_project(r, v))
    plan = make_plan(ws, AgainOptions(fields="input,actual_output"), dry=True)
    said = " ".join([plan.why or "", plan.plain or "", *plan.side_effects])
    assert "archive-v0" not in said and ".cache/uv" not in said, said
    assert "the Python uvx runs judgekeeper with" in said


def test_a_rubric_from_default_test_in_the_config_file_is_said(here, capsys):
    from tests.test_promptfoo_two_rubrics import CONFIG

    (here / "promptfooconfig.yaml").write_text(
        CONFIG + "defaultTest:\n  assert:\n    - type: llm-rubric\n      value: Polite.\n",
        encoding="utf-8")
    (here / "results.json").write_text(json.dumps(_two_rubrics()), encoding="utf-8")
    _, out, err = run(capsys)
    assert ("defaultTest adds an llm-rubric to every test in promptfooconfig.yaml" in
            " ".join((out + err).split()))


def test_a_big_one_line_file_named_otherwise_is_named_by_its_keys(here, capsys):
    rows = [{"id": f"c{i}", "question": f"Fact {i}?", "answer": {"text": "x" * 80,
             "scores": {"quality": {"score": 0.5}}}} for i in range(40000)]
    (here / "cases.json").write_text(json.dumps({"cases": rows}), encoding="utf-8")
    _, out, _ = run(capsys)
    assert "cases.json" in out and "too big to look into" in " ".join(out.split())


# A damaged file after marking is said under Step 1, like every other line ----------------------

def test_a_damaged_file_after_marking_is_said_under_step_1(here, capsys, no_browser):
    from tests.start_projects import deepeval_data, deepeval_project

    path = deepeval_project(here, split(20, 16))
    run(capsys)
    data = deepeval_data([True])
    del data["testCases"][0]["metricsData"][0]["name"]
    path.write_text(json.dumps(data), encoding="utf-8")
    for command in ((), ("mark",)):
        code, out, err = run(capsys, *command)
        assert code == 2, out + err
        assert ".latest_run_full.json is damaged: its only row has a damaged field." in err
        assert out.splitlines()[2:4] == ["Step 1 of 5: Find", ""], out

# The result page says what fix does for a judge judgekeeper can't ask -----------------------

S11_FIX = ("In your project folder, run `judgekeeper fix`. It lists the answers your LLM-as-a-judge got "
           "wrong and saves them in .judgekeeper/fix/. judgekeeper can't re-run this kind of LLM-as-a-judge "
           "itself, so change its rule where your eval keeps it, run your eval, then run "
           "`judgekeeper check`.")


def _page_text(html: str) -> str:
    """What a reader sees, a command in backticks as the terminal writes it."""
    from html import unescape

    html = re.sub(r"<code>(.*?)</code>", r"`\1`", html)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_the_live_result_page_says_what_fix_does_for_an_own_file(here, capsys, no_browser):
    """A file in a format of its own: fix can't swap a rule in. The live result page and
    report.html say so, in the words of the terminal."""
    import urllib.request

    from tests.start_projects import flat_jsonl

    flat_jsonl(here / "graded.jsonl", 36)
    code, out, _ = run(capsys, "--yes")
    assert code == 0, out
    ws = Workspace(here)
    base, token = no_browser[-1].split("/?token=")

    def call(path, body=None):
        req = urllib.request.Request(f"{base}{path}?token={token}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Origin": base})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    flipped = 0
    for item in call("/state")["items"]:  # 16 Pass, 20 Fail; the judge passed 8 of the fails
        label = groups[item["id"]]
        if label == "pass" and flipped < 8:
            label, flipped = "fail", flipped + 1
        call("/label", {"id": item["id"], "label": label, "seconds": 5})
    with urllib.request.urlopen(f"{base}/result?token={token}", timeout=10) as r:
        live = r.read().decode("utf-8")
    assert 'id="fix-h"' in live, live
    assert S11_FIX in _page_text(live), live
    assert "tells you where to write a better rule" not in live
    run(capsys, "--yes")
    report = ws.report_html.read_text(encoding="utf-8")
    assert S11_FIX in _page_text(report), report
    assert "tells you where to write a better rule" not in report


# Two runs at once: one prepares the pool at a time, as one opens the page ----------------------

def test_the_pool_is_prepared_while_the_opening_mark_is_held(here, capsys, no_browser,
                                                             monkeypatch):
    """A second run waits on .judgekeeper/opening while the first writes the pool, so neither
    reads a file the other is replacing (Windows refuses that) and both get one pool."""
    from judgekeeper import page

    real, held = start_label.prepare, []

    def prepare(found, say, ws=None):
        held.append((Workspace(found.root).dir / page.OPENING).is_file())
        return real(found, say, ws)

    monkeypatch.setattr(start_label, "prepare", prepare)
    promptfoo_project(here, split(20, 16))
    code, out, _ = run(capsys, "mark")
    assert code == 0, out
    assert held == [True]
