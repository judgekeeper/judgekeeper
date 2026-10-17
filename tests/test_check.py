"""`judgekeeper check`: when the judge's setup changed since the last check, re-test the new
judge on the person's marks. Free first (marked answers whose exact text is in the newest
results), then, only after the person's yes, the person's own judge is asked about the rest;
a one-sided paired test per group; a history line; exit 0, 1 (worse) or 3.

No test calls a paid API or needs promptfoo: asking again goes through the fake promptfoo of
test_again_run.
"""

from __future__ import annotations

import json
import re
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
    judge_setup.save(ws, judge_setup.of(found), found.metric)
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
    from tests.test_front import next_lines

    return next_lines(out)[-1]


def _flat(out: str) -> str:
    """The output with its wrapping undone."""
    return " ".join(out.split())


# check remembers the setup of the results it read ------------------------------------------

def _no_reading(monkeypatch):
    """Reading the results (and with them inspect_ai or mlflow) fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("the results were read")

    monkeypatch.setattr(start, "find_judge", refuse)


def test_check_remembers_the_setup_and_reads_nothing_next_time(here, capsys, monkeypatch):
    _marked(here)
    assert run(capsys)[0] == 0
    assert (here / ".judgekeeper" / check.SEEN).is_file()
    _no_reading(monkeypatch)
    code, out = run(capsys)
    assert code == 0 and "Your judge has not changed" in out


def test_check_reads_again_when_the_results_change(here, capsys, no_calls):
    _marked(here)
    run(capsys)
    _results(here, MARKED, version="0.125.0")  # the same size, maybe the same modified time
    code, out = run(capsys)
    assert code == 0
    assert "Your eval tool changed: promptfoo 0.124.1 -> 0.125.0." in out


def test_check_says_when_the_config_is_newer_than_the_results(here, capsys):
    _marked(here)
    import os

    config = here / "promptfooconfig.yaml"
    later = (here / "results.json").stat().st_mtime + 60
    config.write_text("description: support bot\n# a new rubric\n", encoding="utf-8")
    os.utime(config, (later, later))
    code, out = run(capsys)
    assert code == 0
    assert check.CONFIG_NEWER in " ".join(out.split())


def test_a_remembered_setup_from_another_version_is_not_used(here, capsys, monkeypatch):
    _marked(here)
    run(capsys)
    seen = here / ".judgekeeper" / check.SEEN
    data = json.loads(seen.read_text(encoding="utf-8"))
    data["judgekeeper_version"] = "0.0.1"
    seen.write_text(json.dumps(data), encoding="utf-8")
    reads = []
    real = start.find_judge
    monkeypatch.setattr(start, "find_judge", lambda *a, **k: reads.append(1) or real(*a, **k))
    assert run(capsys)[0] == 0
    assert reads == [1]


def test_a_store_folder_is_seen_to_change_deep_inside(tmp_path):
    store = tmp_path / "mlruns"
    (store / "1" / "traces" / "t1").mkdir(parents=True)
    (store / "1" / "traces" / "t1" / "meta.yaml").write_text("a: 1\n", encoding="utf-8")
    before = check.files_signature([store])
    assert check.files_signature([store]) == before
    (store / "1" / "traces" / "t1" / "assessments").mkdir()
    (store / "1" / "traces" / "t1" / "assessments" / "x.json").write_text("{}", encoding="utf-8")
    assert check.files_signature([store]) != before


# check: free first ---------------------------------------------------------------------------

SCENE_6 = [
    "Step 5 of 5: Re-check",
    "",
    f"Your judge changed: model {MODEL} -> {HAIKU}.",
    "Re-checked for free from your new results.",
    "",
    "Re-checked on all 50 of your marks:",
    "",
    "  You passed 25 answers. Your old judge agreed with you on 25,",
    "  your new judge on 25.",
    "    No drop bigger than 20 points: none went from right to",
    "    wrong, none from wrong to right.",
    "    These marks can't rule out a drop of up to 10 points.",
    "",
    "  You failed 25 answers. Your old judge agreed with you on 25,",
    "  your new judge on 16.",
    "    Worse: 9 answers went from right to wrong, and none from wrong to right.",
    "    That is about 36 points lower, and could be as much as 52.",
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
    for gone in ("can see a drop", "No drop seen", "%"):  # counts only on this screen
        assert gone not in out, gone
    assert _next(out) == ("Next: go back to the old judge, or change your judge and run "
                          "`judgekeeper check` again.")
    saved = judge_setup.read(ws)["setup"]
    assert saved["models"] == [MODEL]  # after "Worse" the old judge stays the reference


def test_no_drop_exits_0_and_the_next_check_has_nothing_to_do(here, capsys, no_calls):
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    code, out = run(capsys)
    assert code == 0
    assert ("You failed 25 answers. Your old judge agreed with you on 25, your new judge on "
            "25.") in _flat(out)
    assert ("No drop bigger than 20 points: none went from right to wrong, none from wrong to "
            "right.") in _flat(out)
    assert "turned" not in out
    assert _next(out) == ("Next: nothing to do. Run `judgekeeper check` again after you "
                          "change your judge.")
    code, out = run(capsys)
    assert code == 0
    day = datetime.now().astimezone()
    assert f"Your judge has not changed since your last check ({day.day} " in out


def test_the_same_judge_has_nothing_to_check(here, capsys, no_calls):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert "Your judge has not changed since you marked your answers." in out
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
            "are the same.") in _flat(out)
    assert "Re-checked for free from your new results." in out
    assert "Re-checked on all 50 of your marks:" in out


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
            "model are the same.") in _flat(out)


# check: asking the judge, only after a yes -----------------------------------------------------

ASK = ("To re-check, judgekeeper asks your new judge about your 50 marked answers, twice each. "
       "That is 100 AI calls, paid with your own key. Asking twice shows how much the judge "
       "varies by itself.")


@pytest.fixture
def terminal(monkeypatch):
    """A person at a terminal, answering the question with each of `answers` in turn."""
    answers, prompts = [], []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        prompts.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return answers, prompts


def test_without_a_terminal_or_yes_the_judge_is_never_asked(here, capsys, judge):
    ws = _marked(here)
    before = (ws.dir / "judge.json").read_bytes()
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 3
    assert ASK in " ".join(out.split())
    assert "Answers you passed" not in out
    assert _next(out) == ("Next: run `judgekeeper check` in your terminal to answer, or "
                          "`judgekeeper check --yes` to go ahead.")
    assert (ws.dir / "judge.json").read_bytes() == before
    assert _history(ws) == []
    assert _evals(judge) == 0


def test_with_yes_the_rest_is_asked_again(here, capsys, judge):
    _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys, "--yes")
    assert code == 1
    assert "Re-checked on all 50 of your marks:" in out
    assert "Re-checked for free" not in out
    assert "Worse: 9 answers went from right to wrong, and none from wrong to right." in _flat(out)
    assert _evals(judge) == 1
    tests = judge["fake"].files_seen["tests"]
    assert len(tests) == 50
    assert all("(v2)" not in str(t["providerOutput"]) for t in tests)  # the marked answers
    assert "close copy" not in out  # the same promptfoo version: exactly the judge


def test_at_a_terminal_yes_asks_the_judge(here, capsys, judge, terminal):
    answers, prompts = terminal
    answers.append("y")
    _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 1
    assert prompts == ["Go ahead? [y/N] "]
    assert ASK in " ".join(out.split())
    assert _evals(judge) == 1


@pytest.mark.parametrize("said", ["", "n", "no"])
def test_at_a_terminal_no_is_the_default(here, capsys, judge, terminal, said):
    terminal[0].append(said)
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 3
    assert "Your judge was not asked." in out
    assert _history(ws) == []
    assert _evals(judge) == 0


def test_a_free_recheck_asks_nothing(here, capsys, no_calls, terminal):
    _marked(here)
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys)
    assert code == 1
    assert terminal[1] == [] and "Go ahead?" not in out


def test_some_free_and_a_no_tests_the_free_ones(here, capsys, judge, terminal):
    terminal[0].append("n")
    _marked(here)
    outputs = [answer(i, TAG) if i < 20 or 25 <= i < 45 else f"{answer(i, TAG)} (v2)"
               for i in range(50)]
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys)
    assert code == 0
    assert ("judgekeeper asks your new judge about the other 10 marked answers, twice each. That "
            "is 20 AI calls") in _flat(out)
    assert "Re-checked on 40 of your 50 marks:" in out


def test_a_close_copy_is_said(here, capsys, judge):
    _marked(here)
    _results(here, MARKED, model=HAIKU, version="0.125.0", outputs=_new_outputs())
    code, out = run(capsys, "--yes")
    assert code == 0
    assert re.search(r"This was a close copy of your judge, not an exact one: .*0\.124\.1.*"
                     r"0\.125\.0", _flat(out))


def test_free_first_then_asked(here, capsys, judge):
    _marked(here)
    outputs = [answer(i, TAG) if i % 2 else f"{answer(i, TAG)} (v2)" for i in range(50)]
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys, "--yes")
    assert code == 0
    assert "Re-checked on all 50 of your marks:" in out
    assert len(judge["fake"].files_seen["tests"]) == 25


def test_the_question_says_when_the_judge_can_change_files(here, capsys, judge):
    _marked(here, agent=True)
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs(), agent=True)
    code, out = run(capsys)
    assert code == 3
    assert "Your judge is an agent that can change files when it runs." in out
    assert _evals(judge) == 0


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
    _results(here, MARKED, model=HAIKU)  # no drop: judge.json moves to this judge
    assert run(capsys)[0] == 0
    _results(here, LENIENT, model="anthropic:claude-sonnet-5")
    code, out = run(capsys)
    assert code == 1  # against the last check's verdicts (all agreed): 9 new mistakes
    assert "Your old judge agreed with you on 25, your new judge on 16." in _flat(out)
    assert f"Your judge changed: model {HAIKU} -> anthropic:claude-sonnet-5." in _flat(out)


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
    assert line["groups"]["passed"]["verdict"] == "no_drop"
    assert failed["high"] < 0 < line["groups"]["passed"]["high"]  # the range ends are kept
    assert failed["old_rate"] == 1.0 and failed["new_rate"] < 1.0
    assert len(line["flipped"]) == 9
    assert isinstance(line["smallest_drop"], int) and line["time"].endswith("Z")


def test_no_answer_text_in_history_verdicts_or_output(here, capsys, judge):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
    run(capsys, "--yes")  # run() checks the output
    texts = [(ws.dir / "history.jsonl").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in (ws.dir / "verdicts").glob("*.jsonl")]
    assert len(texts) >= 2
    for text in texts:
        assert TAG.strip() not in text and "Question" not in text and "Answer" not in text


def test_verdicts_are_kept_by_setup(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    new = judge_setup.of(start.find_judge(here))  # the judge just checked
    setup_hash = judge_setup.hash_of(new)
    path = ws.dir / "verdicts" / f"{setup_hash.removeprefix('sha256:')}.jsonl"
    head, *lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert head["setup"] == new and head["setup_hash"] == setup_hash
    assert len(lines) == 50 and set(lines[0]) == {"id", "verdict"}


def test_history_and_verdicts_stay_on_new(here, capsys, no_calls):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    from judgekeeper.start_again import move_to_previous

    moved = move_to_previous(ws, _quiet)
    assert (ws.dir / "history.jsonl").is_file() and (ws.dir / "verdicts").is_dir()
    assert not (moved / "history.jsonl").exists()


# The report after a check ----------------------------------------------------------------------

def test_a_check_writes_the_report_again_with_no_history_on_it(here, capsys, no_calls):
    from judgekeeper.cli import main as cli

    ws = _marked(here)
    assert cli([]) == 0  # the result: report.html
    ws.report_html.unlink()
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys)[0] == 1
    html = ws.report_html.read_text(encoding="utf-8")  # written again by the check
    assert 'id="verdict-h"' in html
    assert "History" not in html and HAIKU not in html.split("<body>")[1].split("</header>")[1]
    assert any(json.loads(x).get("kind") == "check"  # history.jsonl is still written
               for x in ws.history_jsonl.read_text(encoding="utf-8").splitlines())


def test_no_internal_words_in_the_code():
    import judgekeeper

    for path in Path(judgekeeper.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bScene \d|walkthrough", text), path.name
