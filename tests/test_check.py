"""`judgekeeper check`: when the judge's setup changed since the last check, re-test the new
judge on the person's marks. Free first (marked answers whose exact text is in the newest
results), then, only with automatic checks on, the person's own judge is asked about the
rest; a one-sided paired test per group; a history line; exit 0, 1 (worse) or 3.

No test calls a paid API or needs promptfoo: asking again goes through the fake promptfoo of
test_again_run.
"""

from __future__ import annotations

import json
import re
import socket
import time
from datetime import datetime
from pathlib import Path

import pytest

from judgekeeper import again, check, judge_setup, keys, start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import (
    MODEL,
    answer,
    deepeval_data,
    deepeval_project,
    inspect_data,
    project_promptfoo,
    promptfoo_data,
    split,
)
from tests.test_again_run import FakePromptfoo

TAG = " SECRET-c4e1"
HAIKU = "anthropic:claude-haiku-4-5"
# The marks: answers 0-24 passed and 25-49 failed by the judge, marked so by the person
MARKED = split(25, 25)
# A new judge that passes 9 of the answers the person failed
LENIENT = split(25, 25)
LENIENT[25:34] = [True] * 9


def _quiet(line=""):
    pass


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _results(root, verdicts, version="0.124.1", model=MODEL, outputs=None, rubric=None,
             created="2026-10-12T09:00:00Z", agent=False):
    kwargs = {"rubric": rubric} if rubric else {}
    data = promptfoo_data(verdicts, model=model, tag=TAG, created=created, outputs=outputs,
                          **kwargs)
    data["metadata"]["promptfooVersion"] = version
    if agent:
        for row in data["results"]["results"]:
            row["gradingResult"]["componentResults"][0]["assertion"]["type"] = "agent-rubric"
    _write(root / "results.json", data)


def _new_outputs(n=50):
    return [f"{answer(i, TAG)} (v2)" for i in range(n)]


def _marked(root, n_pass=25, n_fail=25, agent=False, **kwargs) -> Workspace:
    """A promptfoo project as judgekeeper leaves it after marking: judge.json, start.json, and
    a person who agrees with the judge on every answer."""
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _results(root, split(n_pass, n_fail), agent=agent, **kwargs)
    found = start.find_judge(root)
    ws = Workspace(root)
    judge_setup.save(ws, judge_setup.of(found))
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"], "seconds": 5})
    return ws


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def no_calls(monkeypatch):
    """Any process judgekeeper starts to ask the judge fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("the judge was asked")

    monkeypatch.setattr(again, "run_process", refuse)


@pytest.fixture
def judge(monkeypatch, here):
    """The project's own promptfoo (the fake, version 0.124.1) and a key in the shell."""
    project_promptfoo(here)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    holder = {}

    def runner(argv, cwd, env=None, timeout=None):
        if "fake" not in holder:  # the newest results are read when first called
            holder["fake"] = FakePromptfoo(Workspace(here), version="0.124.1")
        return holder["fake"](argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


def _on(ws, **extra):
    data = {"on": True, "since": "2026-10-12T08:00:00Z", "sitting": "s1",
            "allow_agent_judge": False, "added": [], **extra}
    _write(ws.dir / "checks.json", data)


def run(capsys, *argv, stdin=None, monkeypatch=None):
    code = main(["check", *argv])
    out, err = capsys.readouterr()
    assert TAG.strip() not in out + err
    return code, out


def _evals(holder) -> int:
    fake = holder.get("fake")
    return sum("eval" in c.argv for c in fake.calls) if fake else 0


def _history(ws):
    path = ws.dir / "history.jsonl"
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] \
        if path.is_file() else []
    return [x for x in lines if x.get("kind") == "check"]


def _next(out: str) -> str:
    return [x for x in out.splitlines() if x.startswith("Next:")][-1]


# --fast -------------------------------------------------------------------------------------

def test_fast_without_enough_marks_says_nothing(here, capsys):
    _marked(here, n_pass=10, n_fail=25)
    _results(here, MARKED, model=HAIKU)
    assert run(capsys, "--fast") == (0, "")


def test_fast_without_judgekeeper_says_nothing(here, capsys):
    _results(here, MARKED)
    assert run(capsys, "--fast") == (0, "")
    assert not (here / ".judgekeeper").exists()


def test_fast_with_the_same_judge_is_silent(here, capsys):
    _marked(here)
    _results(here, MARKED, created="2026-10-13T09:00:00Z")  # another run, the same judge
    assert run(capsys, "--fast") == (0, "")


def test_fast_says_one_line_in_a_terminal(here, capsys, monkeypatch):
    _marked(here)
    monkeypatch.setattr(check, "_terminal", lambda: True)
    assert run(capsys, "--fast") == (0, "judgekeeper: your judge matches your marks.\n")


def test_fast_names_the_change_and_exits_3(here, capsys, no_calls):
    _marked(here)
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys, "--fast")
    assert code == 3
    assert out == (f"Your judge changed: model {MODEL} -> {HAIKU}.\n"
                   "Next: run `judgekeeper check`.\n")


def test_fast_sees_a_version_bump_only(here, capsys):
    _marked(here)
    _results(here, MARKED, version="0.125.0")
    code, out = run(capsys, "--fast")
    assert code == 3
    assert out.splitlines()[0] == "Your eval tool changed: promptfoo 0.124.1 -> 0.125.0."


def test_fast_says_when_the_config_is_newer_than_the_results(here, capsys):
    _marked(here)
    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    config.write_text("description: support bot\n# a new rubric\n", encoding="utf-8")
    import os

    os.utime(config, (later, later))
    code, out = run(capsys, "--fast")
    assert code == 0
    assert out == ("Your judge's config changed after your last eval run; judgekeeper "
                   "re-checks it after the next one.\n")


def test_fast_is_fast_and_uses_no_network(here, capsys, monkeypatch):
    _marked(here, n_pass=250, n_fail=250)

    def no_network(*args, **kwargs):
        raise AssertionError("a network call")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    began = time.perf_counter()
    assert run(capsys, "--fast") == (0, "")
    assert time.perf_counter() - began < 1.0


# check: free first ---------------------------------------------------------------------------

SCENE_6 = [
    f"Your judge changed: model {MODEL} -> {HAIKU}.",
    "Re-checked on your 50 marks (50 free from your new results).",
    "",
    "  Answers you passed:  old judge 100%, new judge 100%.  No drop seen.",
    ("  Answers you failed:  old judge 100%, new judge 64%.  Worse: it now passes 9 answers "
     "you failed."),
    "",
]


def test_a_model_change_rechecked_free(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys)
    assert code == 1
    lines = out.splitlines()
    start_at = lines.index(SCENE_6[0])
    assert lines[start_at:start_at + len(SCENE_6)] == SCENE_6
    assert re.search(r"^This check can see a drop of \d+ points or more\.$", out, re.MULTILINE)
    assert _next(out) == ("Next: tell the person the new judge passes 9 answers they failed. "
                          "Ask whether to go back to the old judge.")
    saved = judge_setup.read(ws)["setup"]
    assert saved["models"] == [HAIKU]  # judge.json follows the judge just checked


def test_no_drop_exits_0_and_the_next_check_has_nothing_to_do(here, capsys, no_calls):
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    code, out = run(capsys)
    assert code == 0
    assert "  Answers you failed:  old judge 100%, new judge 100%.  No drop seen." in out
    assert _next(out).startswith("Next: nothing.")
    code, out = run(capsys)
    assert code == 0
    day = datetime.now().astimezone()
    assert f"No change in your judge since the last check ({day.day} " in out


def test_the_same_judge_has_nothing_to_check(here, capsys, no_calls):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert "No change in your judge since the last check" in out
    assert _history(Workspace(here)) == []


def test_a_rule_change(here, capsys, no_calls):
    _marked(here)
    _results(here, MARKED, rubric="Is polite, correct and short.")
    code, out = run(capsys)
    assert code == 0
    assert "Your judge changed: rule changed." in out


def test_a_pass_mark_change(here, capsys, no_calls):
    deepeval_project(here, split(25, 25), tag=TAG)
    (here / "requirements.txt").write_text("deepeval==4.2.8\n", encoding="utf-8")
    found = start.find_judge(here)
    judge_setup.save(Workspace(here), judge_setup.of(found))
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    data = deepeval_data(split(25, 25), tag=TAG)
    for case in data["testCases"]:
        case["metricsData"][0]["threshold"] = 0.7
    _write(here / ".deepeval" / ".latest_run_full.json", data)
    code, out = run(capsys)
    assert code == 0
    assert "Your judge changed: pass mark 0.5 -> 0.7." in out


def test_a_promptfoo_version_bump_only(here, capsys, no_calls):
    _marked(here)
    _results(here, MARKED, version="0.125.0")
    code, out = run(capsys)
    assert code == 0
    assert ("Your eval tool changed: promptfoo 0.124.1 -> 0.125.0. Your judge's rule and model "
            "are the same.") in out
    assert "Re-checked on your 50 marks (50 free from your new results)." in out


def test_an_inspect_version_bump_only(here, capsys, no_calls):
    log = inspect_data(split(25, 25), tag=TAG)
    log["eval"]["packages"] = {"inspect_ai": "0.3.278"}
    _write(here / "logs" / "a.json", log)
    found = start.find_judge(here)
    judge_setup.save(Workspace(here), judge_setup.of(found))
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    log["eval"]["packages"] = {"inspect_ai": "0.3.280"}
    _write(here / "logs" / "a.json", log)
    code, out = run(capsys)
    assert code == 0
    assert ("Your eval tool changed: Inspect AI 0.3.278 -> 0.3.280. Your judge's rule and "
            "model are the same.") in out


# check: asking the judge ----------------------------------------------------------------------

def test_with_checks_off_the_judge_is_never_asked(here, capsys, no_calls):
    _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 3
    assert ("Turning on automatic checks lets judgekeeper ask your judge about your 50 marked "
            "answers.") in out
    assert "Answers you passed" not in out
    assert _next(out).startswith("Next: tell the person")


def test_some_free_and_checks_off_tests_the_free_ones(here, capsys, no_calls):
    _marked(here)
    outputs = [answer(i, TAG) if i < 20 or 25 <= i < 45 else f"{answer(i, TAG)} (v2)"
               for i in range(50)]
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys)
    assert code == 0
    assert "Re-checked on 40 of your 50 marks (40 free from your new results)." in out
    assert ("Turning on automatic checks lets judgekeeper ask your judge about the other 10 "
            "marked answers.") in out
    assert re.search(r"^This check can see a drop of \d+ points or more", out, re.MULTILINE)


def test_with_checks_on_the_rest_is_asked_again(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 1
    assert "Re-checked on your 50 marks (50 asked again)." in out
    assert "it now passes 9 answers you failed" in out
    assert _evals(judge) == 1
    tests = judge["fake"].files_seen["tests"]
    assert len(tests) == 50
    assert all("(v2)" not in str(t["providerOutput"]) for t in tests)  # the marked answers
    assert "close copy" not in out  # the same promptfoo version: exactly the judge


def test_a_close_copy_is_said(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    _results(here, MARKED, model=HAIKU, version="0.125.0", outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 0
    assert re.search(r"^This was a close copy of your judge, not an exact one: .*0\.124\.1.*"
                     r"0\.125\.0", out, re.MULTILINE)


def test_free_first_then_asked(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    outputs = [answer(i, TAG) if i % 2 else f"{answer(i, TAG)} (v2)" for i in range(50)]
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys)
    assert code == 0
    assert "Re-checked on your 50 marks (25 free from your new results, 25 asked again)." in out
    assert len(judge["fake"].files_seen["tests"]) == 25


def test_an_agent_judge_that_can_write_is_not_run_by_itself(here, capsys, no_calls):
    ws = _marked(here, agent=True)
    _on(ws)
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs(), agent=True)
    code, out = run(capsys)
    assert code == 3
    assert "judgekeeper doesn't run a judge that can change files by itself." in out


def test_the_call_limit_stops_a_runaway(here, capsys, no_calls):
    ws = _marked(here)
    _on(ws)
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    found = start.find_judge(here)
    setup_hash = judge_setup.hash_of(judge_setup.of(found))
    _write(ws.dir / check.COUNTS, {"days": {}, "calls": {setup_hash: 90}})
    code, out = run(capsys)
    assert code == 3
    assert "judgekeeper reached its call limit for this judge" in out


def test_the_daily_cap(here, capsys, no_calls):
    ws = _marked(here)
    _on(ws)
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    _write(ws.dir / check.COUNTS, {"days": {today: check.PER_DAY}, "calls": {}})
    code, out = run(capsys)
    assert code == 3
    assert f"judgekeeper already ran {check.PER_DAY} checks that ask your judge today" in out


def test_a_check_with_calls_counts_them(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    run(capsys)
    counts = json.loads((ws.dir / check.COUNTS).read_text(encoding="utf-8"))
    assert sum(counts["days"].values()) == 1
    assert list(counts["calls"].values()) == [50]


def test_nothing_tested_keeps_the_check_pending(here, capsys, no_calls):
    ws = _marked(here)
    before = (ws.dir / "judge.json").read_bytes()
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    assert run(capsys)[0] == 3
    assert (ws.dir / "judge.json").read_bytes() == before
    assert run(capsys)[0] == 3  # said again, not "no change"


# The old verdicts: the last check's, else the results the marks were made on -------------

def test_the_next_check_compares_with_the_last_checks_verdicts(here, capsys, no_calls):
    _marked(here)
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys)[0] == 1
    _results(here, LENIENT, model="anthropic:claude-sonnet-5")
    code, out = run(capsys)
    assert code == 0  # the same 9 as the judge before: no new drop
    assert "  Answers you failed:  old judge 64%, new judge 64%.  No drop seen." in out
    assert f"Your judge changed: model {HAIKU} -> anthropic:claude-sonnet-5." in out


# History and saved verdicts -------------------------------------------------------------------

def test_a_history_line_per_check(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    (line,) = _history(ws)
    assert line["trigger"] == "by hand"
    assert line["before"]["models"] == [MODEL] and line["after"]["models"] == [HAIKU]
    assert line["changed"] == [f"model {MODEL} -> {HAIKU}"]
    assert (line["marks"], line["free"], line["asked"], line["calls"]) == (50, 50, 0, 0)
    assert line["exact"] == "exact"
    failed = line["groups"]["failed"]
    assert (failed["now_wrong"], failed["now_right"], failed["verdict"]) == (9, 0, "worse")
    assert line["groups"]["passed"]["verdict"] == "no drop seen"
    assert len(line["flipped"]) == 9
    assert isinstance(line["smallest_drop"], int) and line["time"].endswith("Z")


def test_no_answer_text_in_history_verdicts_or_output(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    run(capsys)  # run() checks the output
    texts = [(ws.dir / "history.jsonl").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in (ws.dir / "verdicts").glob("*.jsonl")]
    assert len(texts) >= 2
    for text in texts:
        assert TAG.strip() not in text and "Question" not in text and "Answer" not in text


def test_verdicts_are_kept_by_setup(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    setup = judge_setup.read(ws)
    path = ws.dir / "verdicts" / f"{setup['setup_hash'].removeprefix('sha256:')}.jsonl"
    head, *lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert head["setup"] == setup["setup"] and head["setup_hash"] == setup["setup_hash"]
    assert len(lines) == 50 and set(lines[0]) == {"id", "verdict"}


def test_history_and_verdicts_stay_on_new(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    from judgekeeper.start_again import move_to_previous

    moved = move_to_previous(ws, _quiet)
    assert (ws.dir / "history.jsonl").is_file() and (ws.dir / "verdicts").is_dir()
    assert not (moved / "history.jsonl").exists()


# --hook ----------------------------------------------------------------------------------------

HOOK = {"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "npx promptfoo eval"}, "cwd": "."}


def _hook(capsys, monkeypatch, data=HOOK):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
    return run(capsys, "--hook")


def test_the_hook_is_silent_when_nothing_changed(here, capsys, monkeypatch, no_calls):
    _marked(here)
    assert _hook(capsys, monkeypatch) == (0, "")


def test_the_hook_is_silent_without_marks(here, capsys, monkeypatch):
    _results(here, MARKED)
    assert _hook(capsys, monkeypatch) == (0, "")


def test_the_hook_tells_the_agent_and_the_person(here, capsys, monkeypatch, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    code, out = _hook(capsys, monkeypatch)
    assert code == 0  # never 2, and Claude Code reads the JSON only after 0
    data = json.loads(out)
    context = data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert SCENE_6[0] in context and "it now passes 9 answers you failed" in context
    assert "Next: tell the person the new judge passes 9 answers they failed." in context
    assert data["systemMessage"].startswith("judgekeeper: your judge changed")
    assert "\n" not in data["systemMessage"]
    assert _history(ws)[0]["trigger"] == "hook"


def test_the_hook_after_editing_the_config_says_when_it_rechecks(here, capsys, monkeypatch):
    _marked(here)
    import os

    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    os.utime(config, (later, later))
    edit = {**HOOK, "tool_name": "Edit", "tool_input": {"file_path": str(config)}}
    code, out = _hook(capsys, monkeypatch, edit)
    assert code == 0
    data = json.loads(out)
    assert data["hookSpecificOutput"]["additionalContext"] == (
        "Your judge's config changed after your last eval run; judgekeeper re-checks it after "
        "the next one.")
    assert "systemMessage" not in data


# Baseline (called by the page after Turn on) ---------------------------------------------------

def test_baseline_needs_checks_on(here, capsys, no_calls):
    _marked(here)
    code, out = run(capsys, "--baseline")
    assert code == 3
    assert "Automatic checks are off" in out


def test_baseline_asks_once_and_measures_steadiness(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    judge["fake"] = FakePromptfoo(ws, version="0.124.1")
    first, second = [q["id"] for q in ws.data()["queue"]][:2]
    judge["fake"].flips = {(first, 0), (second, 0)}
    code, out = run(capsys, "--baseline")
    assert code == 0
    assert "changed its mind on 2 of your 50 marked answers" in out
    (line,) = _history(ws)
    assert line["trigger"] == "baseline" and len(line["flipped"]) == 2
    setup = judge_setup.read(ws)
    assert (ws.dir / "verdicts" / f"{setup['setup_hash'].removeprefix('sha256:')}.jsonl").is_file()


def test_after_a_baseline_the_drop_uses_the_measured_steadiness(here, capsys, judge):
    ws = _marked(here)
    _on(ws)
    run(capsys, "--baseline")
    _results(here, MARKED, model=HAIKU)
    code, out = run(capsys)
    assert code == 0
    assert re.search(r"^This check can see a drop of \d+ points or more \(from your judge's "
                     r"measured steadiness\)\.$", out, re.MULTILINE)


def test_baseline_is_hidden_from_the_help(capsys):
    assert main(["check", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--fast" in out and "--baseline" not in out
