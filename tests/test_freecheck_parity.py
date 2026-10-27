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
import sys
from pathlib import Path

import pytest

from judgekeeper import judge_check, start
from tests.conftest import FIXTURES

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


def _tool_run(path: Path) -> str:
    """What `judgekeeper <file>` prints for a table it reads by its columns' names (its own map,
    saved in judgekeeper.toml): the tool asks no question for these names."""
    run = [sys.executable, "-m", "judgekeeper"]
    out = subprocess.run([*run, path.name, "--no-browser", "--port", "0", "--yes"], check=False,
                         cwd=path.parent, capture_output=True, text=True, timeout=120,
                         stdin=subprocess.DEVNULL, encoding="utf-8").stdout
    subprocess.run([*run, "--stop"], check=False, cwd=path.parent, capture_output=True,
                   stdin=subprocess.DEVNULL, timeout=60)
    return " ".join(out.split())


@pytest.mark.parametrize("columns", [("question", "answer", "grade"),
                                     ("Prompt", "Response", "Score"),
                                     ("question", "answer", "grade", "explanation")])
def test_a_table_with_other_common_names_reads_as_the_tool_reads_it(columns, tmp_path):
    path = tmp_path / "my-results.csv"
    rows = [",".join(columns)]
    for i in range(20):
        why = ["passes, it is fine" if i % 2 else "it fails"] if len(columns) == 4 else []
        rows.append(",".join([f"Question {i}?", f"Answer {i}.", "pass" if i % 3 else "fail",
                              *[f'"{w}"' for w in why]]))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    said = _tool_run(path)
    (judge,) = browser(path)["judges"]
    assert f"passed {judge['pass']} answers and failed {judge['fail']}." in said, said
    assert (judge["pass"], judge["fail"]) == (13, 7)
    for line in judge["findings"]:
        assert " ".join(line.split()).rstrip(".")[:60] in said, line
    assert judge["readRows"] == [["question", f"the {columns[0]} column"],
                                 ["answer", f"the {columns[1]} column"],
                                 ["grade", f"the {columns[2]} column"]]


def test_a_table_it_cant_place_names_the_columns_it_reads(tmp_path):
    path = tmp_path / "scores.csv"
    path.write_text("case,text,mark\n1,hello,7\n", encoding="utf-8")
    said = browser(path)
    assert said["ok"] is False and said["message"].startswith(
        "judgekeeper can't tell which columns hold the question, the answer and the grade (this "
        "file has case, text and mark). In the browser it reads a CSV or JSONL file with a "
        "question column (input or question), an answer column (output or answer) and a grade "
        "column (verdict or grade) holding Pass or Fail."), said
