"""The flow and the numbers, across runs, from the second bug hunt.

- promptfoo `check` grades with the new judge's grader, also on answers missing from the
  newest results; a re-ask that used another model than the new judge saves nothing.
- No Next: line sends the person to mark when every answer is marked.
- promptfoo through npx: the download goes in the same yes/no question as the calls.
- After a check, report.html describes the re-checked judge; after "Worse" for a table judge,
  no loop.
- Measure writes report.html, then the history line, then result.json; a run after one that
  stopped half way repairs them.
- Counts and words that agree with each other; `fix` reads the rule only from a real config
  and keeps nothing aside for a judge it can't ask; nested projects; marks kept while the
  results file is gone.
No test calls an AI API.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import again, keys
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import project_promptfoo, promptfoo_data, split
from tests.test_again_run import FakePromptfoo
from tests.test_check import HAIKU, MODEL, TAG, _history, _marked
from tests.test_front import flat, next_lines

NEW = HAIKU  # the new judge's grader in these tests: it passes every answer


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


# 1. promptfoo check grades with the new judge ------------------------------------------------

class GraderFake(FakePromptfoo):
    """The fake promptfoo, grading as the grader each test names: the new judge (NEW) passes
    every answer. `answers_as`: every row says it was graded by that grader instead."""

    answers_as: str | None = None

    def __call__(self, argv, cwd, env=None, timeout=None):
        done = super().__call__(argv, cwd, env, timeout)
        if "eval" not in argv:
            return done
        out = cwd / argv[argv.index("-o") + 1]
        data = json.loads(out.read_text(encoding="utf-8"))
        for row in data["results"]["results"]:
            grader = (row["testCase"].get("options") or {}).get("provider") or {}
            self.graders.append(grader.get("id"))
            if grader.get("id") == NEW:
                row["success"] = row["gradingResult"]["pass"] = True
                for c in row["gradingResult"]["componentResults"]:
                    c["pass"], c["score"] = True, 1
            if self.answers_as:
                row["testCase"]["options"] = {"provider": {"id": self.answers_as}}
        out.write_text(json.dumps(data), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def grader(monkeypatch, here):
    project_promptfoo(here)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    holder = {}

    def runner(argv, cwd, env=None, timeout=None):
        if "fake" not in holder:
            fake = GraderFake(Workspace(here), version="0.124.1")
            fake.graders = []
            fake.answers_as = holder.get("answers_as")
            holder["fake"] = fake
        return holder["fake"](argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


def _new_judge_on_a_few(root) -> None:
    """The grader changed to NEW, and the eval ran again on 5 of the 50 questions only, into a
    new results file: results.json (the old judge's) stays."""
    data = promptfoo_data(split(25, 25), model=NEW, tag=TAG)
    data["metadata"]["promptfooVersion"] = "0.124.1"
    data["metadata"]["evaluationCreatedAt"] = "2026-10-13T09:00:00Z"
    rows = data["results"]["results"]
    data["results"]["results"] = [r for i, r in enumerate(rows) if i in (1, 11, 21, 31, 41)]
    for r in data["results"]["results"]:
        r["success"] = r["gradingResult"]["pass"] = True  # the new judge passes everything
        r["gradingResult"]["componentResults"][0]["pass"] = True
    (root / "results-new.json").write_text(json.dumps(data), encoding="utf-8")


def test_promptfoo_check_asks_the_new_grader_about_the_answers_left_out(here, capsys, grader):
    ws = _marked(here)
    _new_judge_on_a_few(here)
    code, out = _check(capsys, "--yes")
    fake = grader["fake"]
    assert fake.graders and set(fake.graders) == {NEW}, fake.graders
    tests = fake.files_seen["tests"]
    assert {t["options"]["provider"]["id"] for t in tests} == {NEW}
    assert code == 1, out
    assert "Worse" in out
    assert judge_models(ws) == [MODEL]  # after "Worse" the old judge stays


def judge_models(ws):
    return json.loads((ws.dir / "judge.json").read_text(encoding="utf-8"))["setup"]["models"]


def test_a_reask_that_used_another_model_saves_nothing(here, capsys, grader):
    ws = _marked(here)
    _new_judge_on_a_few(here)
    grader["answers_as"] = MODEL  # every reply came from the old model
    before = (ws.dir / "judge.json").read_bytes()
    code, out = _check(capsys, "--yes")
    assert code == 2, out
    assert (f"judgekeeper asked the wrong model ({MODEL}, not {NEW}), so this check is not "
            "saved.") in flat(out)
    assert (ws.dir / "judge.json").read_bytes() == before
    assert _history(ws) == []
    assert not list((ws.dir / "checks").glob("*/check-*.jsonl"))
    assert not (ws.dir / "verdicts").exists()


# 2. No Next line points to marking when nothing is left to mark ------------------------------

def says_mark(line: str) -> bool:
    """A Next line that sends the person to mark more answers."""
    return bool(re.search(r"judgekeeper mark\b|mark (\d+ )?(more|new) answers", line))


def _mark(ws: Workspace, person=None) -> None:
    """The person marks every answer: as the judge did, or `person[i]` for answer i."""
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


def test_fix_check_fix_on_a_40_answer_project_never_says_mark(here, capsys, grader):
    """Every answer marked, then Fix, Re-check and Fix again: every Next line is possible."""
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(here, split(20, 20), RULE_A)
    assert _jk(capsys)[0] == 0
    person = {i: "fail" for i in range(8)} | {i: "pass" for i in range(20, 24)}
    _mark(Workspace(here), person)
    said = [_jk(capsys)[1]]
    said.append(_jk(capsys, "fix")[1])
    (here / ".judgekeeper" / "fix" / "rule.txt").write_text(RULE_B, encoding="utf-8")
    said.append(_jk(capsys, "fix", "--yes")[1])
    _rubric(here, split(20, 20), RULE_B)  # the rule copied into the config, the eval run
    said.append(_jk(capsys, "check")[1])
    said.append(_jk(capsys, "fix")[1])
    (here / ".judgekeeper" / "fix" / "rule.txt").write_text(RULE_C, encoding="utf-8")
    said.append(_jk(capsys, "fix")[1])
    _rubric(here, split(20, 20), RULE_B, only=range(10), model=NEW)  # 10 questions, new model
    said.append(_jk(capsys, "check")[1])
    for out in said:
        assert "Step" in out
        assert not says_mark(_next(out)), out
    assert "judgekeeper --new" in _next(said[4])  # fix after the rule was adopted
    assert "You have tested 1 rule on these marks kept aside." in flat(said[4])
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
    assert check.picks_lines(p, every=True) == [
        "These marks have helped pick 3 changes, so they may now flatter your judge."]
    assert check.picks_lines(p) == [
        ("These marks have helped pick 3 changes, so they may now flatter your judge. Mark 10 "
         "new answers for a fair check.")]


# 3. promptfoo through npx -------------------------------------------------------------------

NPX = "/opt/node/bin/npx"


@pytest.fixture
def npx(monkeypatch, here):
    """No promptfoo installed; npx is there (`holder["npx"]` False: not there either)."""
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
    holder = {"npx": True, "argv": []}
    monkeypatch.setattr(again, "which",
                        lambda name: NPX if name == "npx" and holder["npx"] else None)

    def runner(argv, cwd, env=None, timeout=None):
        holder["argv"].append(list(argv))
        if "fake" not in holder:
            holder["fake"] = FakePromptfoo(Workspace(here), version="0.124.1")
        return holder["fake"](argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


def _changed_model(root) -> None:
    from tests.test_check import LENIENT, _new_outputs, _results

    _results(root, LENIENT, model=NEW, outputs=_new_outputs())


def test_check_asks_about_the_npx_download_with_the_calls(here, capsys, npx):
    _marked(here)
    _changed_model(here)
    code, out = _check(capsys)
    assert code == 3, out
    assert ("That is 100 AI calls, paid with your own key. It also downloads promptfoo 0.124.1 "
            "with npx.") in flat(out)
    assert "doesn't download anything" not in out
    assert npx["argv"] == []
    code, out = _check(capsys, "--yes")
    assert code == 1, out
    evals = [a for a in npx["argv"] if "eval" in a]
    assert evals and evals[0][:3] == [NPX, "--yes", "promptfoo@0.124.1"]


def test_check_without_npx_names_the_install_command(here, capsys, npx):
    npx["npx"] = False
    _marked(here)
    _changed_model(here)
    code, out = _check(capsys, "--yes")
    assert code == 3, out
    assert _next(out) == ("Next: run `npm install promptfoo@0.124.1` in your project, then run "
                          "`judgekeeper check` again.")
    assert npx["argv"] == []


def _fix_ready(root, capsys):
    from tests.test_fix import NEW_RULE, project

    ws = project(root)
    _jk(capsys, "fix")
    (ws.dir / "fix" / "rule.txt").write_text(NEW_RULE, encoding="utf-8")
    return ws


def test_fix_asks_about_the_npx_download_with_the_calls(tmp_path, monkeypatch, capsys, npx):
    _fix_ready(tmp_path, capsys)
    code, out = _jk(capsys, "fix")
    assert code == 3, out
    assert "paid with your own key. It also downloads promptfoo 0.124.1 with npx." in flat(out)
    assert _next(out) == ("Next: run `judgekeeper fix` in your terminal to answer, or "
                          "`judgekeeper fix --yes` to go ahead.")
    code, out = _jk(capsys, "fix", "--yes")
    assert code == 0, out
    assert all(a[:3] == [NPX, "--yes", "promptfoo@0.124.1"] for a in npx["argv"] if "eval" in a)


def test_fix_without_npx_names_the_install_command(tmp_path, capsys, npx):
    npx["npx"] = False
    _fix_ready(tmp_path, capsys)
    code, out = _jk(capsys, "fix", "--yes")
    assert code == 3, out
    assert _next(out) == ("Next: run `npm install promptfoo@0.124.1` in your project, then run "
                          "`judgekeeper fix` again.")


# 4. report.html after check describes one judge ----------------------------------------------

def _report(root) -> str:
    return flat((root / ".judgekeeper" / "report.html").read_text(encoding="utf-8"))


def _said_in_report(report: str) -> list[str]:
    """The headline, the two counts and the kept-aside line, as report.html says them."""
    text = re.sub(r"<[^>]+>", "", report)
    return re.findall(r"Your judge [^.]*\.|Too early to tell\.|You (?:passed|failed) \d+ "
                      r"answers\. Of those, your judge passed \d+ and failed \d+\.|"
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
    assert ("You failed 38 answers. Of those, your judge passed 2 and failed 36."
            in _said_in_report(after_check)), _said_in_report(after_check)
    _jk(capsys)
    assert _said_in_report(_report(here)) == _said_in_report(after_check)


# 5. After "Worse" for a table judge, no loop ---------------------------------------------------

NEXT_WORSE_TABLE = ("Next: go back to your old judge, or change its rule; then run your eval "
                    "and `judgekeeper check`.")


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
    assert "re-check your changed judge" not in out
    assert _next(_check(capsys)[1]) == NEXT_WORSE_TABLE
    report = _report(here)
    assert ("Go back to your old judge, or change its rule; then run your eval and "
            "<code>judgekeeper check</code>.") in report
    assert "judgekeeper mark</code>" not in report and 'id="fix-h"' not in report
    _jk(capsys, "fix")
    mistakes = (here / ".judgekeeper" / "fix" / "mistakes.md").read_text(encoding="utf-8")
    wrong_now = [i for i in range(60) if new[i] != _truth(i)]
    assert mistakes.count("## [M") == len(wrong_now)
    assert "Question 9?" not in mistakes  # the old judge's mistake the new judge gets right
    assert "Question 2?" in mistakes  # and a new one


# 9. A judge fix can't ask: nothing kept aside ------------------------------------------------

def test_fix_for_a_table_judge_keeps_nothing_aside(here, capsys):
    from tests.start_projects import table_project

    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(60)]
    table_project(here, old)
    assert _jk(capsys)[0] == 0
    _mark(Workspace(here), {i: "pass" if _truth(i) else "fail" for i in range(60)})
    _jk(capsys)
    code, out = _jk(capsys, "fix")
    assert code == 3, out
    assert "kept aside" not in out
    wrong = sum(old[i] != _truth(i) for i in range(60))
    assert f"all {wrong} mistakes are saved" in flat(out)
    assert "kept aside" not in _report(here)


# 6. Ctrl-C during Measure ------------------------------------------------------------------------

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


# 7. Counts and words that agree --------------------------------------------------------------

def _all_marked_promptfoo(root, capsys, rule=RULE_A, n=40):
    (root / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(root, split(n // 2, n // 2), rule)
    assert _jk(capsys)[0] == 0
    _mark(Workspace(root), {i: "fail" for i in range(8)} | {i: "pass" for i in range(20, 24)})
    _jk(capsys)
    return Workspace(root)


def test_a_partial_eval_says_how_many_marked_answers_it_holds(here, capsys, no_calls):
    _all_marked_promptfoo(here, capsys)
    _rubric(here, split(20, 20), RULE_B, only=range(10))  # the eval on 10 questions only
    _, out = _check(capsys)
    assert "Your newest results hold 10 of your 40 marked answers." in flat(out), out
    assert "don't contain the answers you marked" not in out
    assert "Re-checked on 10 of your 40 marks:" in out
    _rubric(here, split(20, 20), RULE_B)  # then the whole eval
    _, out = _check(capsys)
    assert "You added" not in out, out  # no mark was made since
    assert "Re-checked on all 40 of your marks:" in out


def test_marks_really_added_since_a_check_are_counted(here, capsys, no_calls):
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
    assert "Re-checked on all 40 of your marks:" in _check(capsys)[1]
    time.sleep(1.1)  # marks are stamped to the second
    session = Session(ws)
    for item in session.items[40:]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 6})
    out = _check(capsys)[1]
    assert "You added 10 marks since your last check." in out, out


@pytest.fixture
def no_calls(monkeypatch):
    monkeypatch.setattr(again, "run_process", lambda *a, **k: pytest.fail("the judge was asked"))


def test_after_an_adopted_rule_the_judge_is_not_called_the_same(here, capsys, no_calls):
    ws = _all_marked_promptfoo(here, capsys)
    _jk(capsys, "fix")
    _rubric(here, split(20, 20), RULE_B)
    assert _check(capsys)[0] == 0
    mistakes = (ws.dir / "fix" / "mistakes.md").read_text(encoding="utf-8")
    assert RULE_B in mistakes and RULE_A not in mistakes
    _rubric(here, split(20, 20), RULE_B, name="results-2.json")  # the eval ran again
    out = _jk(capsys)[1]
    assert "Your judge is the same" not in out, out
    assert ("Your eval ran again. Your judge is the one your last check re-tested, so your marks "
            "still test it.") in flat(out)


def test_fix_with_a_rule_it_tested_shows_that_result(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    holder = _fake_fix_judge(tmp_path, monkeypatch)
    _fix_ready(tmp_path, capsys)
    code, first = _jk(capsys, "fix", "--yes")
    assert code == 0 and holder["evals"] == 2, first
    result = next(line for line in first.splitlines() if line.startswith("Result:"))
    code, out = _jk(capsys, "fix")
    assert code == 0, out
    assert holder["evals"] == 2  # never tested again
    assert "You tested this rule before" in out and "write your new rule" not in out
    assert result in out
    assert _next(first) == _next(out)


def _fake_fix_judge(root, monkeypatch):
    """The fake promptfoo of test_fix, counting its evals."""
    from tests.test_fix import NEW_RULE, N, _person

    project_promptfoo(root)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
    monkeypatch.setattr(again, "which", lambda name: None)
    holder = {"evals": 0}

    def runner(argv, cwd, env=None, timeout=None):
        if "fake" not in holder:
            holder["fake"] = FakePromptfoo(Workspace(root), version="0.124.1")
        fake = holder["fake"]
        if "eval" in argv:
            holder["evals"] += 1
            config = json.loads((Path(cwd) / argv[argv.index("-c") + 1]).read_text(encoding="utf-8"))
            tests = json.loads((Path(cwd) / config["tests"].removeprefix("file://"))
                               .read_text(encoding="utf-8"))
            fake.flips = {(t["description"], 0) for t in tests
                          if t["assert"][0]["value"] == NEW_RULE
                          and fake.saved[t["vars"]["question"]][0] != _person(
                              t["vars"]["question"], N // 2)}
        return fake(argv, cwd, env, timeout)

    monkeypatch.setattr(again, "run_process", runner)
    return holder


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
    from tests.test_reading_fixes import _errored_inspect, _inspect_log

    _inspect_log(here, "2026-10-17_qa.json", _errored_inspect(split(10, 10)))
    _, out = _jk(capsys, "--metric", "model_graded_qa")
    assert "Answers:     18 answers with a grade (2 failed before scoring)" in out, out
    assert "each graded by your judge" not in out


# 8. fix reads the rule only from a real config ---------------------------------------------

def test_fix_never_says_the_rule_is_in_a_saved_screen(tmp_path, capsys, monkeypatch):
    from tests.test_fix import RULE, project

    monkeypatch.chdir(tmp_path)
    project(tmp_path)
    screen = f'Eval tool:   promptfoo\nJudge rule:  "{RULE}"\n'
    (tmp_path / "find.txt").write_text(screen, encoding="utf-8")
    (tmp_path / "run.log").write_text(f"{RULE}\n", encoding="utf-8")
    (tmp_path / "copy.md").write_text(f"Step 1 of 5: Find\n\n{screen}", encoding="utf-8")
    _, out = _jk(capsys, "fix")
    assert "Your judge's rule is in promptfooconfig.yaml, line" in out, out
    assert "find.txt" not in out and "run.log" not in out and "copy.md" not in out


def test_fix_says_when_it_cant_tell_where_the_rule_is(tmp_path, capsys, monkeypatch):
    from tests.test_fix import RULE, project

    monkeypatch.chdir(tmp_path)
    project(tmp_path)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                   encoding="utf-8")
    (tmp_path / "notes.txt").write_text(f"{RULE}\n", encoding="utf-8")
    _, out = _jk(capsys, "fix")
    assert ("judgekeeper can't tell which file holds your judge's rule. Your eval keeps it in "
            "the `value:` of the llm-rubric assert in promptfooconfig.yaml:") in flat(out), out
    assert "notes.txt" not in out


# 10. Nested projects -------------------------------------------------------------------------

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
    assert "(read from inner/" not in out
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
    assert "(read from outer_results.csv)" in out
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


# 11. Saved marks while the results file is missing ----------------------------------------------

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
