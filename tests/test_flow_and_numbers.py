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
from types import SimpleNamespace

import pytest

from judgekeeper import again, keys
from judgekeeper.start_label import Workspace
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
