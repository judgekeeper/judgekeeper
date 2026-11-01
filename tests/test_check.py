"""`judgekeeper check`: when the LLM-as-a-judge's setup changed since the last check, re-test the new
judge on the person's marks: the marked answers whose exact text is in the newest results; a
one-sided paired test per group; a history line; exit 0, 1 (a drop over 20 points) or 3.

No test calls an LLM: check only reads the results files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from judgekeeper import check, judge_setup, start, start_label
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import (
    MODEL,
    answer,
    deepeval_data,
    deepeval_project,
    inspect_data,
    promptfoo_data,
    split,
)

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
    a person who agrees with the LLM-as-a-judge on every answer."""
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


def run(capsys, *argv, stdin=None, monkeypatch=None):
    code = main(["check", *argv])
    out, err = capsys.readouterr()
    assert TAG.strip() not in out + err
    return code, out


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
    assert code == 0 and "Your LLM-as-a-judge has not changed" in out


def test_check_reads_again_when_the_results_change(here, capsys):
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

TABLE_HEAD = "Agreed with you:        Old LLM-as-a-judge   New LLM-as-a-judge"
SCENE_6 = [
    "Step 5 of 5: Re-check",
    "",
    "New results: results.json",
    "",
    "Your LLM-as-a-judge's model changed:",
    f"  {MODEL} -> {HAIKU}",
    "",
    "Result: worse. Your new LLM-as-a-judge agrees with you less.",
    "",
    TABLE_HEAD,
    "  When you said Pass    25 of 25             25 of 25             No big drop",
    "  When you said Fail    25 of 25             16 of 25             Worse",
    "",
    "On answers you pass, no drop, though these marks can't rule out",
    "one of up to 10 in every 100.",
    "On answers you fail, agreement drops by about 36 in every 100",
    "(somewhere between 22 and 53).",
    "",
    check.ONE_RUN,
    "",
]


def _expect(old_wrong: int, new_wrong: int, n: int = 40) -> list[str]:
    """What to expect when the old LLM-as-a-judge got `old_wrong` of each group's `n` marks
    wrong and the new one `new_wrong`."""
    marked = {f"p{i}": "pass" for i in range(n)} | {f"f{i}": "fail" for i in range(n)}
    flip = {"pass": "fail", "fail": "pass"}

    def judge(wrong: int) -> dict[str, str]:
        return {i: flip[m] if int(i[1:]) < wrong else m for i, m in marked.items()}
    return check.expect_lines(check.groups(marked, judge(old_wrong), judge(new_wrong)))


def test_a_clear_rise_in_both_groups_is_said():
    lines = _expect(20, 0)
    assert lines[-1] == "Agreement rose in both groups."
    assert not any("drop" in line and "none of the range" not in line for line in lines), lines


def test_worse_while_the_other_group_rose_says_which_group_decides():
    """Pass: 20 of 40 right before, 40 now; Fail: 40 of 40 right before, 20 now. The result is
    worse: one sentence says the Fail group dropped and a clear drop decides."""
    marked = {f"p{i}": "pass" for i in range(40)} | {f"f{i}": "fail" for i in range(40)}
    old = {i: ("fail" if i[0] == "p" and int(i[1:]) < 20 else m) for i, m in marked.items()}
    new = {i: ("pass" if i[0] == "f" and int(i[1:]) < 20 else m) for i, m in marked.items()}
    g = check.groups(marked, old, new)
    assert check.outcome(g) == "worse"
    assert check.expect_lines(g)[-1] == (
        "Agreement rose on answers you pass but dropped on answers you fail, and a clear drop "
        "in either group makes the result worse.")
    assert check.expect_lines(g).count(check.expect_lines(g)[-1]) == 1
    assert not any(x.startswith("Agreement rose on") for x in _expect(0, 20))  # both dropped


def test_a_group_with_no_drop_says_no_drop():
    lines = _expect(0, 0)
    assert all(line.split(", ", 1)[1].startswith("no drop, though") for line in lines), lines
    assert "Agreement rose in both groups." not in lines
    assert _expect(0, 3)[0].startswith("On answers you pass, agreement drops")  # a real drop


def test_worse_with_a_small_drop_exits_0_as_the_reference_says(here, capsys):
    """12 of 100 Fails now passed: the whole range is a drop ("Worse"), but its middle
    estimate is 12 points, so `check` exits 0; exit 1 needs a drop over 20 points."""
    _marked(here, 25, 100)
    _results(here, [True] * 37 + [False] * 88, model=HAIKU)
    code, out = run(capsys)
    assert code == 0 and "Worse" in out, out
    said = " ".join((Path(__file__).parents[1] / "docs" / "reference.md").read_text(
        encoding="utf-8").split())
    rule = ("the drop's middle estimate is over 20 points, whichever word it says (Worse or "
            "Not sure)")
    assert f"| 1 | {rule}:" in said
    assert ("It exits 1 only when the drop's middle estimate is over 20 points, whichever word "
            "it says.") in said


def test_a_marked_empty_answer_is_found_by_its_question(here, capsys):
    outputs = ["" if i == 3 else answer(i, TAG) for i in range(50)]
    _marked(here, outputs=outputs)
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys)
    assert code == 0 and "Re-checked on" not in out, out  # on all 50
    assert "had no grade" not in out, out


def test_a_rule_taken_on_with_a_marked_empty_answer_has_not_changed_after(here, capsys):
    """Its empty answer got no grade from the rule taken on, so every check after said "rule
    changed" against the old rule again."""
    outputs = ["" if i == 3 else answer(i, TAG) for i in range(50)]
    _marked(here, outputs=outputs)
    _results(here, MARKED, rubric="Is polite, correct and short.", outputs=outputs)
    code, out = run(capsys)
    assert code == 0 and "rule changed" in out, out  # taken on
    for _ in range(2):
        code, out = run(capsys)
        assert code == 0 and "has not changed since your last check" in out, out


def test_a_model_change_rechecked_free(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    code, out = run(capsys)
    assert code == 1
    lines = out.splitlines()
    start_at = lines.index(SCENE_6[0])
    assert lines[start_at:start_at + len(SCENE_6)] == SCENE_6
    for gone in ("can see a drop", "No drop seen", "%", "points", "right to wrong"):
        assert gone not in out, gone  # counts only on this screen; the detail is on the report
    assert _next(out) == ("Next: go back to your old LLM-as-a-judge, or try another change and "
                          "run `judgekeeper check` again.")
    saved = judge_setup.read(ws)["setup"]
    assert saved["models"] == [MODEL]  # after "Worse" the old judge stays the reference


def test_no_drop_exits_0_and_the_next_check_has_nothing_to_do(here, capsys):
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    code, out = run(capsys)
    assert code == 0
    assert "Result: no drop bigger than 20 in every 100 answers for your new LLM-as-a-judge." in out
    assert "  When you said Fail    25 of 25             25 of 25             No big drop" in out
    assert ("On answers you fail, no drop, though these marks can't rule out one of up to 10 "
            "in every 100.") in " ".join(out.split())
    assert "drops by no more than" not in out  # no answer went from right to wrong
    assert "turned" not in out
    assert _next(out) == ("Next: nothing to do. Run `judgekeeper check` again after you "
                          "change your LLM-as-a-judge.")
    code, out = run(capsys)
    assert code == 0
    day = datetime.now().astimezone()
    assert f"Your LLM-as-a-judge has not changed since your last check ({day.day} " in out


def test_the_same_judge_has_nothing_to_check(here, capsys):
    _marked(here)
    code, out = run(capsys)
    assert code == 0
    assert "Your LLM-as-a-judge has not changed since you marked your answers." in out
    assert _history(Workspace(here)) == []


def test_a_rule_change(here, capsys):
    _marked(here)
    _results(here, MARKED, rubric="Is polite, correct and short.")
    code, out = run(capsys)
    assert code == 0
    assert "Your LLM-as-a-judge changed: rule changed." in out


def test_a_pass_mark_change(here, capsys):
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
    assert "Your LLM-as-a-judge changed: pass mark 0.5 -> 0.7." in out


def _geval(criteria: str, steps) -> dict:
    """A DeepEval run whose GEval prompt for answer i has `criteria` and `steps(i)`."""
    data = deepeval_data(split(25, 25), tag=TAG)
    for i, case in enumerate(data["testCases"]):
        case["metricsData"][0]["verboseLogs"] = (
            f"Criteria:\n{criteria} \n \nEvaluation Steps:\n{json.dumps(steps(i), indent=4)}"
            " \n \nRubric:\nNone \n \nScore: 0.9")
    return data


RIGHT = "Is the answer right?"


@pytest.mark.parametrize("before, after, changed", [
    # GEval given only criteria= writes its steps with its model for each answer, every run
    ((RIGHT, lambda i: [f"Check fact {i}."]), (RIGHT, lambda i: [f"Look at fact {i}."]), False),
    ((RIGHT, lambda i: [f"Check fact {i}."]), ("Is it right and short?",
                                               lambda i: [f"Look at fact {i}."]), True),
    # steps the person gave are the same for every answer, and are the person's rule too
    ((RIGHT, lambda i: ["Check each fact."]), (RIGHT, lambda i: ["Check each fact."]), False),
    ((RIGHT, lambda i: ["Check each fact."]), (RIGHT, lambda i: ["Check each fact.",
                                                                 "Then the length."]), True),
], ids=["steps-written-again", "criteria-changed", "steps-given", "given-steps-changed"])
def test_a_geval_rule_is_what_the_person_wrote(here, capsys, before, after, changed):
    _write(here / ".deepeval" / ".latest_run_full.json", _geval(*before))
    (here / "requirements.txt").write_text("deepeval==4.2.8\n", encoding="utf-8")
    found = start.find_judge(here)
    judge_setup.save(Workspace(here), judge_setup.of(found))
    ws = start_label.prepare(found, say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    _write(here / ".deepeval" / ".latest_run_full.json", _geval(*after))
    code, out = run(capsys)
    assert code == 0, out
    assert ("Your LLM-as-a-judge changed: rule changed." in out) is changed, out
    assert ("Your LLM-as-a-judge changed" in out) is changed, out


def test_a_promptfoo_version_bump_only(here, capsys):
    _marked(here)
    _results(here, MARKED, version="0.125.0")
    code, out = run(capsys)
    assert code == 0
    assert ("Your eval tool changed: promptfoo 0.124.1 -> 0.125.0. Your LLM-as-a-judge's rule and model "
            "are the same.") in _flat(out)
    assert TABLE_HEAD in out


def test_an_inspect_version_bump_only(here, capsys):
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
    assert ("Your eval tool changed: Inspect AI 0.3.278 -> 0.3.280. Your LLM-as-a-judge's rule and "
            "model are the same.") in _flat(out)


# check: only the marked answers in the new results ----------------------------------------

def test_some_marked_answers_not_in_the_new_results_are_left_out(here, capsys):
    _marked(here)
    outputs = [answer(i, TAG) if i < 20 or 25 <= i < 45 else f"{answer(i, TAG)} (v2)"
               for i in range(50)]
    _results(here, MARKED, model=HAIKU, outputs=outputs)
    code, out = run(capsys)
    assert code == 0
    assert check.NOT_IN.format(k=10, n="50 marked answers", them="them") \
        in _flat(out)
    assert "Re-checked on 40 of your 50 marks:" in out


def test_a_verdicts_folder_that_is_a_link_is_not_written_through(here, capsys,
                                                                tmp_path_factory):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    outside = tmp_path_factory.mktemp("outside")
    shutil.rmtree(ws.dir / check.VERDICTS, ignore_errors=True)
    try:
        os.symlink(outside, ws.dir / check.VERDICTS, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make links")
    code = main(["check"])
    out, err = capsys.readouterr()
    assert code == 2
    assert list(outside.iterdir()) == []
    assert f"error: .judgekeeper/{check.VERDICTS} is a link to another folder." in err
    assert "didn't expect" not in out + err


def test_nothing_tested_keeps_the_check_pending(here, capsys):
    ws = _marked(here)
    before = (ws.dir / "judge.json").read_bytes()
    _results(here, MARKED, model=HAIKU, outputs=_new_outputs())
    code, out = run(capsys)
    assert code == 3
    assert check.NONE_IN.format(n="50 marked answers") in _flat(out)
    assert "Answers you passed" not in out and TABLE_HEAD not in out
    assert (ws.dir / "judge.json").read_bytes() == before
    assert _history(ws) == []
    assert run(capsys)[0] == 3  # said again, not "no change"


# The old verdicts: the last check's, else the results the marks were made on -------------

def test_the_next_check_compares_with_the_last_checks_verdicts(here, capsys):
    _marked(here)
    _results(here, MARKED, model=HAIKU)  # no drop: judge.json moves to this judge
    assert run(capsys)[0] == 0
    _results(here, LENIENT, model="anthropic:claude-sonnet-5")
    code, out = run(capsys)
    assert code == 1  # against the last check's verdicts (all agreed): 9 new mistakes
    assert "When you said Fail 25 of 25 16 of 25 Worse" in _flat(out)
    assert (f"Your LLM-as-a-judge's model changed: {HAIKU} -> anthropic:claude-sonnet-5"
            in _flat(out))


# History and saved verdicts -------------------------------------------------------------------

def test_a_history_line_per_check(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    (line,) = _history(ws)
    assert line["trigger"] == "by hand"
    assert line["before"]["models"] == [MODEL] and line["after"]["models"] == [HAIKU]
    assert line["changed"] == [f"model {MODEL} -> {HAIKU}"]
    assert (line["marks"], line["free"]) == (50, 50)
    assert not {"asked", "calls", "exact"} & set(line)
    failed = line["groups"]["failed"]
    assert (failed["now_wrong"], failed["now_right"], failed["verdict"]) == (9, 0, "worse")
    assert line["groups"]["passed"]["verdict"] == "no_drop"
    assert failed["high"] < 0 < line["groups"]["passed"]["high"]  # the range ends are kept
    assert failed["old_rate"] == 1.0 and failed["new_rate"] < 1.0
    assert len(line["flipped"]) == 9
    assert isinstance(line["smallest_drop"], int) and line["time"].endswith("Z")


def test_no_answer_text_in_history_verdicts_or_output(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)  # run() checks the output
    texts = [(ws.dir / "history.jsonl").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in (ws.dir / "verdicts").glob("*.jsonl")]
    assert len(texts) >= 2
    for text in texts:
        assert TAG.strip() not in text and "Question" not in text and "Answer" not in text


def test_verdicts_are_kept_by_setup(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    new = judge_setup.of(start.find_judge(here))  # the judge just checked
    setup_hash = judge_setup.hash_of(new)
    path = ws.dir / "verdicts" / f"{setup_hash.removeprefix('sha256:')}.jsonl"
    head, *lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert head["setup"] == new and head["setup_hash"] == setup_hash
    assert len(lines) == 50 and set(lines[0]) == {"id", "verdict"}


def test_history_and_verdicts_stay_on_new(here, capsys):
    ws = _marked(here)
    _results(here, LENIENT, model=HAIKU)
    run(capsys)
    from judgekeeper.project import move_to_previous

    moved = move_to_previous(ws, _quiet)
    assert (ws.dir / "history.jsonl").is_file() and (ws.dir / "verdicts").is_dir()
    assert not (moved / "history.jsonl").exists()


# The report after a check ----------------------------------------------------------------------

def test_a_check_writes_the_report_again_with_no_history_on_it(here, capsys):
    from judgekeeper.cli import main as cli

    ws = _marked(here)
    assert cli([]) == 0  # the result: report.html
    ws.report_html.unlink()
    _results(here, LENIENT, model=HAIKU)
    assert run(capsys)[0] == 1
    html = ws.report_html.read_text(encoding="utf-8")  # written again by the check
    assert 'id="verdict-h"' in html
    body = html.split("<body>")[1].split("</header>")[1]
    rest = body[:body.index("Last check")] + body[body.index('id="verdict-h"'):]
    assert "History" not in html and HAIKU not in rest  # named in the Last check block only
    assert any(json.loads(x).get("kind") == "check"  # history.jsonl is still written
               for x in ws.history_jsonl.read_text(encoding="utf-8").splitlines())


def test_no_internal_words_in_the_code():
    import judgekeeper

    for path in Path(judgekeeper.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bScene \d|walkthrough", text), path.name


def test_inside_texts_once_each_text_is_scrubbed_once(monkeypatch):
    """Matching many answers asks for the same texts many times: inside texts_once() each is
    scrubbed once; outside it nothing is kept."""
    calls = []
    real = check.scrub
    monkeypatch.setattr(check, "scrub", lambda text: calls.append(text) or real(text))
    with check.texts_once():
        assert check._text(" a ") == check._text(" a ") == "a"
        with check.texts_once():  # inside another: the same memo
            assert check._text(" a ") == "a"
        assert check._text({"q": 1}) == check._text({"q": 1})  # not text: never kept
    assert len(calls) == 3
    check._text(" a ")
    assert len(calls) == 4


def _side(verdict: str, low: float, change: float = 0.0, high: float = 0.1) -> dict:
    return {"n": 30, "verdict": verdict, "low": low, "high": high, "change": change,
            "now_wrong": 5, "now_right": 2, "old_right": 20, "new_right": 20}


@pytest.mark.parametrize("low,up_to", [(-0.201, 21), (-0.2, 20), (-0.07, 7), (-0.0009, 1)])
def test_the_worst_end_of_a_range_is_rounded_up(low, up_to):
    """A drop bound shown to the person rounds toward the bigger drop (−20.1 → 21), and a
    bound that is already whole stays whole (float noise in −0.07 * 100 is not a point)."""
    lines = check.paired_lines(_side("not_sure", low))
    assert lines[0].endswith(f"It could be up to {up_to} points worse."), lines
    lines = check.paired_lines(_side("no_drop", low))
    assert lines[1] == f"These marks can't rule out a drop of up to {up_to} points.", lines
    g = {"passed": _side("no_drop", 0.01), "failed": _side("no_drop", low)}
    assert (f"On answers you fail, no drop, though these marks can't rule out one of up to "
            f"{up_to} in every 100.") in check.expect_lines(g)
    g["failed"] = _side("no_drop", low, change=-0.0001)
    assert f"On answers you fail, agreement drops by no more than {up_to} in every 100." in (
        check.expect_lines(g))


def test_a_worse_range_rounds_only_its_far_end_up():
    g = {"passed": _side("no_drop", 0.01),
         "failed": _side("worse", -0.511, change=-0.364, high=-0.224)}
    assert ("On answers you fail, agreement drops by about 36 in every 100 (somewhere between "
            "22 and 52).") in check.expect_lines(g)
    assert check.paired_lines(g["failed"])[1] == (
        "That is about 36 points lower (between 22 and 52).")


def test_a_bound_that_rounds_to_no_drop_is_left_out():
    """A "can't rule out" bound that is 0 once rounded says nothing: only "no drop"."""
    g = {"passed": _side("no_drop", 0.01), "failed": _side("no_drop", -1e-12)}
    assert "On answers you fail, no drop." in check.expect_lines(g)
    assert not any("rule out" in line for line in check.expect_lines(g))
    assert check.paired_lines(g["failed"]) == [
        "No drop bigger than 20 points: 5 went from right to wrong, 2 from wrong to right."]


def test_new_results_given_in_full_are_named_from_here(here, capsys):
    _marked(here)
    _results(here, MARKED, model=HAIKU)
    _, out = run(capsys, str(here / "results.json"))
    assert "New results: results.json" in out.splitlines(), out
    assert str(here) not in out and str(here.resolve()) not in out


def test_a_path_on_another_drive_is_shown_by_its_name(here, monkeypatch):
    from judgekeeper import textio

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(textio.os.path, "relpath", other_drive)
    assert textio.shown_from_here("/elsewhere/runs/new.json") == "new.json"
    assert textio.shown_from_here("runs/new.json") == "runs/new.json"  # typed relative: as is
