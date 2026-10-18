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
import re
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
