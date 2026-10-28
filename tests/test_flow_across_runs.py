"""The flow and the numbers, across runs.

- promptfoo `check` on results that hold only a few marked answers tests the new LLM-as-a-judge
  on those and leaves the rest out.
- No Next: line sends the person to mark when every answer is marked.
- After a check, report.html describes the re-checked judge; after "Worse" for a table judge,
  no loop.
- Measure writes report.html, then the history line, then result.json; a run after one that
  stopped half way repairs them.
- Counts and words that agree with each other; `fix` reads the rule only from a real config;
  a rule `fix` tested is not tested again; nested projects; marks kept while the results file
  is gone.
No test calls an AI API.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import deepeval_data, promptfoo_data, split
from tests.test_check import HAIKU, MODEL, TAG, _marked
from tests.test_front import flat, next_lines

NEW = HAIKU  # the new LLM-as-a-judge's model in these tests


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _next(out: str) -> str:
    return next_lines(out)[-1]


def _check(capsys, *argv):
    from judgekeeper.cli import main

    code = main(["check", *argv])
    out, err = capsys.readouterr()
    return code, out + err


# promptfoo check grades with the new judge ---------------------------------------------------

def _new_judge_on_a_few(root) -> None:
    """The grader changed to NEW, and the eval ran again on 5 of the 50 questions only, into a
    new results file: results.json (the old LLM-as-a-judge's) stays."""
    data = promptfoo_data(split(25, 25), model=NEW, tag=TAG)
    data["metadata"]["promptfooVersion"] = "0.124.1"
    data["metadata"]["evaluationCreatedAt"] = "2026-10-13T09:00:00Z"
    rows = data["results"]["results"]
    data["results"]["results"] = [r for i, r in enumerate(rows) if i in (1, 11, 21, 31, 41)]
    for r in data["results"]["results"]:
        r["success"] = r["gradingResult"]["pass"] = True  # the new judge passes everything
        r["gradingResult"]["componentResults"][0]["pass"] = True
    (root / "results-new.json").write_text(json.dumps(data), encoding="utf-8")


def test_promptfoo_check_on_a_few_answers_cant_tell_yet(here, capsys):
    ws = _marked(here)
    _new_judge_on_a_few(here)
    code, out = _check(capsys)
    assert code == 3, out  # 2 of the 5 were marked Fail: too few to call it a drop
    assert ("45 of your 50 marked answers had no grade in your new results, so judgekeeper "
            "left them out.") in flat(out)
    assert "Result: can't tell yet." in out and "Re-checked on" not in out
    assert judge_models(ws) == [MODEL]  # the old judge stays


def judge_models(ws):
    return json.loads((ws.dir / "judge.json").read_text(encoding="utf-8"))["setup"]["models"]


# No Next line points to marking when nothing is left to mark ---------------------------------

def says_mark(line: str) -> bool:
    """A Next line that sends the person to mark more answers now (not after running the eval
    on more questions: then new answers join the marks)."""
    if "run your eval on more questions, then run `judgekeeper mark`" in line:
        return False
    return bool(re.search(r"judgekeeper mark\b|mark (\d+ )?(more|new) answers", line))


def _mark(ws: Workspace, person=None) -> None:
    """The person marks every answer: as the LLM-as-a-judge did, or `person[i]` for answer i."""
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        text = session.raw[item["id"]]["input"]
        i = int(re.search(r"Question (\d+)\?", json.dumps(text))[1])
        session.update({"id": item["id"], "label": (person or {}).get(i, groups[item["id"]]),
                        "seconds": 6})


def _jk(capsys, *argv):
    from judgekeeper.cli import main

    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out + err


def _rubric(root, verdicts, rule, name="results.json", only=None, model=MODEL):
    data = promptfoo_data(verdicts, rubric=rule, model=model)
    data["metadata"]["promptfooVersion"] = "0.124.1"
    if only is not None:
        data["results"]["results"] = [r for i, r in enumerate(data["results"]["results"])
                                      if i in only]
    (root / name).write_text(json.dumps(data), encoding="utf-8")


RULE_A = "Is polite and correct."
RULE_B = "Is polite, correct and short."
RULE_C = "Is correct, polite and kind."
AS_MARKED = [8 <= i < 24 for i in range(40)]  # graded as the person marks them (_all_marked...)


def test_fix_check_fix_on_a_40_answer_project_never_says_mark(here, capsys):
    """Every answer marked, then Fix, Re-check and Fix again: every Next line is possible."""
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(here, split(20, 20), RULE_A)
    assert _jk(capsys)[0] == 0
    person = {i: "fail" for i in range(8)} | {i: "pass" for i in range(20, 24)}
    _mark(Workspace(here), person)
    said = [_jk(capsys)[1]]
    said.append(_jk(capsys, "fix")[1])
    _rubric(here, AS_MARKED, RULE_B, name="regraded.json")  # the marked answers, graded again
    said.append(_jk(capsys, "fix", "regraded.json")[1])
    (here / "regraded.json").unlink()  # not the eval's newest results from here on
    _rubric(here, split(20, 20), RULE_B)  # the rule copied into the config, the eval run
    said.append(_jk(capsys, "check")[1])
    said.append(_jk(capsys, "fix")[1])
    _rubric(here, split(20, 20), RULE_C, name="regraded-2.json")
    said.append(_jk(capsys, "fix", "regraded-2.json")[1])
    (here / "regraded-2.json").unlink()
    (here / "other.json").write_text(json.dumps(deepeval_data(split(20, 20))), encoding="utf-8")
    code, other = _jk(capsys, "fix", "other.json")  # another tool's file, while waiting
    assert code == 2 and "again with your new rule, from promptfoo." in flat(other), other
    (here / "other.json").unlink()
    _rubric(here, split(20, 20), RULE_B, only=range(10), model=NEW)  # 10 questions, new model
    said.append(_jk(capsys, "check")[1])
    for out in said:
        assert "Step" in out
        assert not says_mark(_next(out)), out
    assert "run your eval on more questions" in _next(said[4])  # fix after the rule was adopted
    assert "You took on a rule tested on these marks kept aside." in flat(said[4])
    assert "You have tested" not in flat(said[4]) + flat(said[5])  # taking one on is no test
    mistakes = (here / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert RULE_B in mistakes and RULE_A not in mistakes  # the judge the marks test now


def test_measure_with_every_answer_marked_never_says_mark_more(here, capsys):
    from tests.start_projects import promptfoo_project

    promptfoo_project(here, split(20, 20))
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here), {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (20, 21, 22)})
    _, out = _jk(capsys)
    assert "Result: too early to tell." in out
    assert "Mark more answers" not in out
    assert not says_mark(_next(out))


def test_the_page_line_never_says_mark_more_once_every_answer_is_marked(here, capsys):
    from judgekeeper import page
    from tests.start_projects import promptfoo_project

    promptfoo_project(here, split(20, 20))
    assert _jk(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws, {i: "fail" for i in (0, 1, 2)} | {i: "pass" for i in (20, 21, 22)})
    status = page.marking_status(StartSession(ws))
    assert status["ready"] is True
    assert status["text"] == ("You marked every answer. When you're done, run judgekeeper in "
                              "your terminal.")


def test_the_picks_line_says_it_once_and_never_asks_with_nothing_left():
    from judgekeeper import check

    p = {"n": 3, "new_marks": 0, "ask": True}
    warn = ("You've used these marks to choose 3 changes, so they may now make your "
            "LLM-as-a-judge look better than it is.")
    assert check.picks_lines(p, every=True) == [warn]
    assert check.picks_lines(p) == [f"{warn} Mark some new answers."]
    assert check.picks_lines({"n": 3, "new_marks": 0, "ask": False}) == []


# report.html after check describes one judge -------------------------------------------------

def _report(root) -> str:
    return flat((root / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))


def _said_in_report(report: str) -> list[str]:
    """The headline, the two counts and the kept-aside line, as report.html says them."""
    text = re.sub(r"<[^>]+>", "", report)
    return re.findall(r"Your LLM-as-a-judge [^.]*\.|Too early to tell\.|You (?:passed|failed) \d+ "
                      r"answers\. Of those, your LLM-as-a-judge passed \d+ and failed \d+\.|"
                      r"\* \d+ more (?:is|are) kept aside", text)


def test_report_after_a_check_is_the_new_judges(here, capsys):
    from tests.start_projects import table_project

    table_project(here, split(30, 30))
    assert _jk(capsys)[0] == 0
    # the person fails 12 answers the judge passed and passes 4 it failed
    _mark(Workspace(here), {i: "fail" for i in range(12)} | {i: "pass" for i in range(30, 34)})
    assert "disagreed on <b>16</b> of <b>60</b>" in (_jk(capsys), _report(here))[1]
    new = split(30, 30)
    new[2:12] = [False] * 10  # the new judge fails 10 of the 12
    table_project(here, new)
    code, out = _check(capsys)
    assert code == 0, out
    after_check = _report(here)
    assert ("You failed 38 answers. Of those, your LLM-as-a-judge passed 2 and failed 36."
            in _said_in_report(after_check)), _said_in_report(after_check)
    _jk(capsys)
    assert _said_in_report(_report(here)) == _said_in_report(after_check)



def _own_jsonl(path, rule: str) -> None:
    """60 answers graded by a JSONL judge: answer k is right when k % 3 != 0; the LLM-as-a-judge is
    wrong on (k * 7) % 10 < 3 (rule v1) or on (k * 7) % 10 == 0 (v2)."""
    rows = []
    for k in range(60):
        wrong = (k * 7) % 10 == 0 if rule == "v2" else (k * 7) % 10 < 3
        verdict = (k % 3 != 0) != wrong
        rows.append({"input": f"Question {k}?", "output": f"Answer {k}.",
                     "verdict": "pass" if verdict else "fail", "model": "gpt-4.1-mini"})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_report_after_a_too_early_check_says_how_many_you_disagreed_on(here, capsys):
    _own_jsonl(here / "judge.jsonl", "v1")
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here), {k: "pass" if k % 3 else "fail" for k in range(60)})  # 40 and 20
    assert "disagreed on 18 of 60" in flat(_jk(capsys)[1])
    _own_jsonl(here / "judge.jsonl", "v2")  # the same model, 12 grades changed
    code, out = _check(capsys)
    assert code == 0 and "grades changed on 12" in flat(out), out
    report = re.sub(r"<[^>]+>", "", _report(here))
    assert "Too early to tell." in report
    assert "You and your LLM-as-a-judge disagreed on 6 of 60 answers." in report
    terminal = flat(_jk(capsys)[1])
    assert "You and your LLM-as-a-judge disagreed on 6 of 60 answers." in terminal

# After "Worse" for a table judge, no loop ------------------------------------------------------

NEXT_WORSE_TABLE = ("Next: go back to your old LLM-as-a-judge or change its rule, run "
                    "`judgekeeper fix` to write the answers you marked to "
                    ".judgekeeper/fix/marked-answers.csv, grade them again with it, then run "
                    "`judgekeeper check <new results file>`.")


def _truth(i: int) -> bool:
    return i % 3 != 0


def test_after_worse_a_table_judge_gets_one_way_out(here, capsys):
    from tests.start_projects import table_project

    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(60)]
    table_project(here, old)
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here), {i: "pass" if _truth(i) else "fail" for i in range(60)})
    _jk(capsys)
    new = [(not v) if i % 2 == 0 or i % 4 == 1 else v for i, v in enumerate(old)]
    table_project(here, new)
    code, out = _check(capsys)
    assert code == 1 and "Worse" in out, out
    assert _next(out) == NEXT_WORSE_TABLE
    code, out = _jk(capsys)
    assert _next(out) == NEXT_WORSE_TABLE, out
    assert "re-check your changed LLM-as-a-judge" not in out
    assert _next(_check(capsys)[1]) == NEXT_WORSE_TABLE
    report = _report(here)
    assert ("Go back to your old LLM-as-a-judge or change its rule, run <code>judgekeeper fix"
            "</code> to write the answers you marked to .judgekeeper/fix/marked-answers.csv, "
            "grade them again with it, then run <code>judgekeeper check &lt;new results file&gt;"
            "</code>.") in report
    assert "judgekeeper mark</code>" not in report and 'id="fix-h"' not in report
    _jk(capsys, "fix")
    mistakes = (here / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    shown = [int(x) for x in re.findall(r"<<<QUESTION\nQuestion (\d+)\?", mistakes)]
    assert len(shown) == mistakes.count("## [M") > 0
    assert all(new[i] != _truth(i) for i in shown)  # the new judge's mistakes, never the old's


# A table judge: marks kept aside, as for every judge ---------------------------------------------

def test_fix_for_a_table_judge_keeps_marks_aside(here, capsys):
    from judgekeeper import fix
    from tests.start_projects import table_project

    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(60)]
    table_project(here, old)
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here), {i: "pass" if _truth(i) else "fail" for i in range(60)})
    _jk(capsys)
    code, out = _jk(capsys, "fix")
    assert code == 0, out
    kept = len(fix.read_split(Workspace(here)).hidden)
    assert f"{kept} of your marks are kept aside to test your new rule fairly." in flat(out)
    assert _next(out).endswith("then run `judgekeeper fix <new results file>`.")


# Ctrl-C during Measure ---------------------------------------------------------------------------

def _measured(root, capsys, only=None):
    """A table project with a result made from the first marks (`only`: those answers)."""
    from tests.start_projects import table_project

    table_project(root, split(30, 30))
    assert _jk(capsys)[0] == 0
    ws = Workspace(root)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:only]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 6})
    assert "Step 3 of 5: Measure" in _jk(capsys)[1]
    return ws


def _counts_in_report(root) -> tuple[int, int]:
    """(marked Pass, marked Fail) as report.html counts them."""
    text = re.sub(r"<[^>]+>", "", _report(root))
    return tuple(int(re.search(rf"You {did} (\d+) answers", text)[1])
                 for did in ("passed", "failed"))


def _result_lines(ws) -> list[dict]:
    lines = [json.loads(x) for x in ws.history_jsonl.read_text(encoding="utf-8").splitlines()]
    return [x for x in lines if x.get("kind") == "result"]


def test_measure_writes_the_report_then_the_history_then_the_result(here, capsys,
                                                                     monkeypatch):
    from judgekeeper import start_label

    ws = _measured(here, capsys, only=40)
    _mark(ws)
    order = []
    real = start_label.write_replacing

    def record(path, *a, **k):
        order.append(Path(path).name)
        return real(path, *a, **k)

    monkeypatch.setattr(start_label, "write_replacing", record)
    _jk(capsys)
    names = [n for n in order if n in ("report.html", "history.jsonl", "result.json")]
    assert names == ["report.html", "history.jsonl", "result.json"], order


def test_a_measure_stopped_before_its_result_is_made_again_once(here, capsys, monkeypatch):
    from judgekeeper import start_label

    ws = _measured(here, capsys, only=40)
    _mark(ws)
    real = start_label._write_json

    def stop(path, data):
        if Path(path).name == "result.json":
            raise KeyboardInterrupt
        return real(path, data)

    monkeypatch.setattr(start_label, "_write_json", stop)
    assert _jk(capsys)[0] == 130
    monkeypatch.setattr(start_label, "_write_json", real)
    code, out = _jk(capsys)
    assert code == 0, out
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["labels"]["correct"] + saved["labels"]["wrong"] == 60
    assert [x["marks"] for x in _result_lines(ws)] == [40, 60]
    assert _counts_in_report(here) == (30, 30)


def test_a_result_saved_before_its_report_and_history_is_repaired(here, capsys):
    """judgekeeper before 1.0 wrote result.json first: a Ctrl-C left the report and the
    history on the old result."""
    import os

    ws = _measured(here, capsys, only=40)
    old_report = ws.report_html.read_text(encoding="utf-8")
    _mark(ws)
    _jk(capsys)
    lines = ws.history_jsonl.read_text(encoding="utf-8").splitlines()
    ws.history_jsonl.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    ws.report_html.write_text(old_report, encoding="utf-8")
    t = ws.result_json.stat().st_mtime - 60
    os.utime(ws.report_html, (t, t))
    code, out = _jk(capsys)
    assert code == 0, out
    assert [x["marks"] for x in _result_lines(ws)] == [40, 60]
    assert ws.report_html.read_text(encoding="utf-8") != old_report
    assert _counts_in_report(here) == (30, 30)


# Counts and words that agree -----------------------------------------------------------------

def _all_marked_promptfoo(root, capsys, rule=RULE_A, n=40):
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(root, split(n // 2, n // 2), rule)
    assert _jk(capsys)[0] == 0
    _mark(Workspace(root), {i: "fail" for i in range(8)} | {i: "pass" for i in range(20, 24)})
    _jk(capsys)
    return Workspace(root)


def test_a_partial_eval_says_how_many_marked_answers_it_holds(here, capsys):
    _all_marked_promptfoo(here, capsys)
    _rubric(here, split(20, 20), RULE_B, only=range(10))  # the eval on 10 questions only
    _, out = _check(capsys)
    assert ("30 of your 40 marked answers had no grade in your new results, so judgekeeper "
            "left them out.") in flat(out), out
    assert "Result: can't tell yet." in out
    _rubric(here, split(20, 20), RULE_B)  # then the whole eval
    _, out = _check(capsys)
    assert "You added" not in out, out  # no mark was made since
    assert "Agreed with you:" in out


def test_marks_really_added_since_a_check_are_counted(here, capsys):
    from judgekeeper.start_label import StartSession as Session

    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(here, split(25, 25), RULE_A)
    assert _jk(capsys)[0] == 0
    ws = Workspace(here)
    session = Session(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:40]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 6})
    _rubric(here, split(25, 25), RULE_B)
    assert "Agreed with you:" in _check(capsys)[1]
    time.sleep(1.1)  # marks are stamped to the second
    session = Session(ws)
    for item in session.items[40:]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 6})
    out = _check(capsys)[1]
    assert "You added 10 marks since your last check." in out, out


def test_after_an_adopted_rule_the_judge_is_not_called_the_same(here, capsys):
    ws = _all_marked_promptfoo(here, capsys)
    _jk(capsys, "fix")
    _rubric(here, split(20, 20), RULE_B)
    assert _check(capsys)[0] == 0
    mistakes = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert RULE_B in mistakes and RULE_A not in mistakes
    _rubric(here, split(20, 20), RULE_B, name="results-2.json")  # the eval ran again
    out = _jk(capsys)[1]
    assert "Your LLM-as-a-judge is the same" not in out, out
    assert ("Your answers were graded again. Your LLM-as-a-judge is the one your last check "
            "re-tested, so your marks still test it.") in flat(out)


def test_fix_with_a_rule_it_tested_shows_that_result(here, capsys):
    from judgekeeper import fix

    ws = _all_marked_promptfoo(here, capsys)
    _jk(capsys, "fix")
    _rubric(here, AS_MARKED, RULE_B, name="regraded.json")
    code, first = _jk(capsys, "fix", "regraded.json")
    assert code == 0, first
    result = next(line for line in first.splitlines() if line.startswith("Result:"))
    tests = fix.read_split(ws).tests
    code, out = _jk(capsys, "fix", "regraded.json")
    assert code == 0, out
    assert fix.read_split(ws).tests == tests  # never tested again
    assert "You tested this LLM-as-a-judge before" in out
    assert result in out
    assert _next(first) == _next(out)


def test_new_without_a_result_moves_the_marks_not_a_check(here, capsys):
    from tests.start_projects import promptfoo_project

    promptfoo_project(here, split(28, 12))
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here))
    assert _jk(capsys)[0] == 3  # every answer marked, too few fails: no result
    _, out = _jk(capsys, "--new", "--yes")
    assert "Moved your marks to .judgekeeper/previous-" in out, out
    assert "last check" not in out


def test_the_answers_line_counts_only_answers_with_a_grade(here, capsys):
    from tests.test_reading_results import _errored_inspect, _inspect_log

    _inspect_log(here, "2026-10-17_qa.json", _errored_inspect(split(10, 10)))
    _, out = _jk(capsys, "--metric", "model_graded_qa")
    assert "Answers:         18 answers with a grade (2 failed before scoring)" in out, out
    assert "each graded by your LLM-as-a-judge" not in out


# fix reads the rule only from a real config ------------------------------------------------

def test_fix_never_says_the_rule_is_in_a_saved_screen(tmp_path, capsys, monkeypatch):
    from tests.test_fix import RULE, project

    monkeypatch.chdir(tmp_path)
    project(tmp_path)
    screen = f'Eval tool:       promptfoo\nRule:            "{RULE}"\n'
    (tmp_path / "find.txt").write_text(screen, encoding="utf-8")
    (tmp_path / "run.log").write_text(f"{RULE}\n", encoding="utf-8")
    (tmp_path / "copy.md").write_text(f"Step 1 of 5: Find\n\n{screen}", encoding="utf-8")
    _, out = _jk(capsys, "fix")
    assert "Your LLM-as-a-judge's rule is in promptfooconfig.yaml, line" in out, out
    assert "find.txt" not in out and "run.log" not in out and "copy.md" not in out


def test_fix_names_the_file_that_holds_the_rule_when_it_cant_find_the_line(tmp_path, capsys,
                                                                           monkeypatch):
    from tests.test_fix import RULE, project

    monkeypatch.chdir(tmp_path)
    project(tmp_path)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                   encoding="utf-8")
    (tmp_path / "notes.txt").write_text(f"{RULE}\n", encoding="utf-8")
    _, out = _jk(capsys, "fix")
    assert ("Your LLM-as-a-judge's rule is in the `value:` of the llm-rubric assert in "
            "promptfooconfig.yaml:") in flat(out), out
    assert "can't tell which file" not in flat(out) and "notes.txt" not in out


def test_fix_says_when_it_cant_tell_which_file_holds_the_rule(tmp_path, capsys, monkeypatch):
    from tests.test_fix import project

    monkeypatch.chdir(tmp_path)
    ws = project(tmp_path)
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    data["tool"] = "deepeval"
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "promptfooconfig.yaml").unlink()  # nothing in the project holds the rule
    _, out = _jk(capsys, "fix")
    assert ("judgekeeper can't tell which file holds your LLM-as-a-judge's rule. Your eval keeps "
            "it in") in flat(out), out


# Nested projects -----------------------------------------------------------------------------

def test_an_outer_project_never_reads_a_nested_projects_results(tmp_path, capsys, monkeypatch):
    from tests.start_projects import table_project

    outer = tmp_path / "nest3"
    (outer / "inner").mkdir(parents=True)
    (outer / "pyproject.toml").write_text("[project]\nname = 'outer'\n", encoding="utf-8")
    (outer / "inner" / "pyproject.toml").write_text("[project]\nname = 'inner'\n",
                                                    encoding="utf-8")
    table_project(outer / "inner", split(30, 30), name="inner_results.csv")
    monkeypatch.chdir(outer)
    code, out = _jk(capsys, "--no-browser")
    assert code == 3, out
    assert ("These results belong to the project in inner/. To check them, run `judgekeeper` "
            "in inner/.") in flat(out)
    assert _next(out) == "Next: run `judgekeeper` in inner/."
    assert "File:            inner/" not in out
    assert not (outer / ".judgekeeper" / "start.json").exists()


def test_outer_results_are_read_and_the_nested_ones_named(tmp_path, capsys, monkeypatch):
    from tests.start_projects import table_project

    outer = tmp_path / "nest3"
    (outer / "inner").mkdir(parents=True)
    (outer / "pyproject.toml").write_text("[project]\nname = 'outer'\n", encoding="utf-8")
    (outer / "inner" / ".judgekeeper").mkdir()
    table_project(outer / "inner", split(30, 30), name="inner_results.csv")
    table_project(outer, split(20, 20), name="outer_results.csv")
    later = time.time() + 60
    os.utime(outer / "inner" / "inner_results.csv", (later, later))
    monkeypatch.chdir(outer)
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    assert code == 0, out
    assert "File:            outer_results.csv" in out
    assert "These results belong to the project in inner/." in flat(out)
    _jk(capsys, "--stop")


def test_the_inner_project_says_once_that_the_outer_one_holds_its_marks(tmp_path, capsys,
                                                                         monkeypatch):
    from tests.start_projects import table_project

    outer = tmp_path / "nest3"
    (outer / "inner").mkdir(parents=True)
    table_project(outer / "inner", split(30, 30), name="inner_results.csv")
    monkeypatch.chdir(outer)  # no project file yet: the outer folder read them and kept marks
    assert _jk(capsys, "--no-browser", "--port", "0")[0] == 0
    _jk(capsys, "--stop")
    session = StartSession(Workspace(outer))
    for item in session.items[:3]:
        session.update({"id": item["id"], "label": "pass", "seconds": 6})
    (outer / "inner" / "pyproject.toml").write_text("[project]\nname = 'inner'\n",
                                                    encoding="utf-8")
    monkeypatch.chdir(outer / "inner")
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    assert code == 0, out
    assert ("The project above (nest3) holds 3 marks for these results in its .judgekeeper/."
            in flat(out)), out
    _jk(capsys, "--stop")
    _, again_out = _jk(capsys, "--no-browser", "--port", "0")
    assert "holds 3 marks" not in again_out
    _jk(capsys, "--stop")


# Saved marks while the results file is missing --------------------------------------------------

def test_marks_saved_while_the_results_file_is_gone_are_said(here, capsys):
    from tests.start_projects import table_project

    table_project(here, split(50, 50))
    assert _jk(capsys, "--no-browser", "--port", "0")[0] == 0
    _jk(capsys, "--stop")
    session = StartSession(Workspace(here))
    for item in session.items[:50]:
        session.update({"id": item["id"], "label": "pass", "seconds": 6})
    (here / "results.csv").unlink()
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    assert code == 3, out
    assert ("No eval results found in this folder. Your 50 marks are saved in .judgekeeper/; "
            "they come back when your results file is back.") in flat(out)


# Back to the marked judge ---------------------------------------------------------------------

def test_back_to_the_marked_judge_after_a_worse_check(here, capsys):
    """LE3: a check on another model said "Worse"; the eval runs with the old LLM-as-a-judge again."""
    from tests.test_check import LENIENT, MARKED, _results

    ws = _marked(here)
    _results(here, LENIENT, model=NEW)
    assert _check(capsys)[0] == 1  # Worse
    _results(here, MARKED)  # back to the judge the marks were made on
    out = _jk(capsys)[1]
    assert "Your LLM-as-a-judge is back to the one you marked with (gpt-4.1-mini)." in flat(out), out
    assert "go back to" not in out and "go back to" not in _report(here).lower()
    code, out = _check(capsys)
    assert code == 0, out
    assert ("Your LLM-as-a-judge is back to the one you marked with (gpt-4.1-mini). Your marks' result "
            "still holds.") in flat(out)
    assert "has not changed since your last check" not in out
    assert judge_models(ws) == [MODEL]


def test_back_to_the_marked_judge_after_an_adopted_check(here, capsys):
    """LE3: a check moved the marks to another model; the eval runs with the old LLM-as-a-judge again:
    the result is the marks' own again."""
    from tests.test_check import MARKED, _results

    ws = _marked(here)
    before = _jk(capsys)[1]
    other = list(MARKED)
    other[0] = not other[0]  # the other model differs on one answer: not worse
    _results(here, other, model=NEW)
    assert _check(capsys)[0] == 0
    assert judge_models(ws) == [NEW]
    _results(here, MARKED)
    out = _jk(capsys)[1]
    assert ("Your LLM-as-a-judge is back to the one you marked with (gpt-4.1-mini). Your marks' result "
            "still holds.") in flat(out), out
    assert judge_models(ws) == [MODEL]
    assert "picked" not in ws.data()
    agreed = [line for line in before.splitlines() if "You and your LLM-as-a-judge" in line]
    assert agreed and agreed[0] in out
    code, out = _check(capsys)  # the check that sees it says it too, and keeps it in history
    assert code == 0 and "back to the one you marked with" in flat(out), out
    assert "has not changed since your last check" in _check(capsys)[1]
