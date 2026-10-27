"""The free check in the browser (website/assets/freecheck.js) says what the tool says.

For every promptfoo, DeepEval and table fixture, the Python reader and free check (find_judge,
judge_check) and node running freecheck.js (tests/freecheck_cli.mjs) are compared: whether the
file can be read at all, the judges, and for each judge its answers, Pass and Fail counts,
model, rule and the free check's findings, word for word. The places where the page must differ
from the tool (it can't ask a question) are tested on their own below.

Needs node (CI sets up Node 22); skipped with the reason when it is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from judgekeeper import judge_check, start
from tests.conftest import FIXTURES
from tests.start_projects import table_project

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "tests" / "freecheck_cli.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")

FREECHECK = FIXTURES / "freecheck"
# Files the tool reads as they are (the others are below, each with what the page says)
COMPARED = sorted([
    *(FIXTURES / "promptfoo").glob("*.json"), FIXTURES / "promptfoo/real/results.json",
    *(FIXTURES / "deepeval/results").glob("*.json"),
    *(FIXTURES / "deepeval/real/results").glob("*.json"),
    *(p for p in FREECHECK.iterdir() if p.is_file() and not p.name.startswith("page-")),
])


def browser(path: Path) -> dict:
    out = subprocess.run([NODE, str(CLI), str(path)], capture_output=True, text=True,
                         check=True, encoding="utf-8")
    return json.loads(out.stdout)


def tool(path: Path) -> dict:
    """What the tool finds in `path`: {"ok": False} when it can't use it, else each judge."""
    try:
        found = start.find_judge(path)
        metrics = found.metrics or [found.metric]
    except start.Stop:  # several judges: one question, so each is named instead
        metrics = None
    except Exception:  # noqa: BLE001 - every way the tool stops on a file it can't use
        return {"ok": False}
    if metrics is None:
        from judgekeeper.find import classify_file

        kind = classify_file(path)
        recs = start._read(start.find.Result(kind, path, path.name)).records
        metrics = sorted(start._judges(recs, kind))
        if not metrics:  # it stopped because the file holds no judge
            return {"ok": False}
    judges = {}
    for metric in metrics:
        found = start.find_judge(path, metric=metric)
        block = found.check.block()
        judges[metric] = {
            "answers": block["answers"], "pass": found.pool.n_pass, "fail": found.pool.n_fail,
            "models": sorted(found.models),
            "rule": " ".join(found.rule.split()) if found.rule else None,
            "findings": judge_check.page_lines(block)}
    return {"ok": True, "judges": judges}


def _page(result: dict) -> dict:
    if not result["ok"]:
        return {"ok": False}
    return {"ok": True, "judges": {
        j["key"]: {"answers": j["answers"], "pass": j["pass"], "fail": j["fail"],
                   "models": sorted(j["models"]), "rule": j["rule"], "findings": j["findings"]}
        for j in result["judges"]}}


@pytest.mark.parametrize("fixture", COMPARED, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_the_page_says_what_the_tool_says(fixture, tmp_path):
    path = tmp_path / fixture.name
    shutil.copy2(fixture, path)  # the tool reads it in a folder of its own, as a person's file
    assert _page(browser(path)) == tool(path)


def test_every_kind_of_file_is_compared():
    names = {p.name for p in COMPARED}
    for name in ("errors-counted-as-passes.json", "empty-answers.json", "one-grade.json",
                 "two-judges.json", "score-and-pass-mark.json", "table.csv", "table.tsv",
                 "table.jsonl", "ab.csv", "not-results.json", "broken.json", "not-utf8.csv",
                 "rules-in-code.json", "empty.jsonl"):
        assert name in names, name


def test_an_error_grade_is_an_error_not_an_empty_decision(tmp_path):
    """A table whose grade is the word "error": no decision, said as such, not a blank one."""
    path = table_project(tmp_path, [True] * 10 + [False] * 10 + ["error", None])
    said = tool(path)
    assert _page(browser(path)) == said
    assert said["judges"]["verdict"]["findings"][0].startswith(
        "Your LLM-as-a-judge made no real decision on 2 of 22 answers: 1 error, 1 empty "
        "decision."), said
