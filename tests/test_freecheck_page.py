"""The free check in the browser where it must differ from the tool, and what keeps the page
private. The tool asks a question about grades it can't read; the page can't ask, so it leaves
them out and says so. A whole number written as a decimal (1.0) is no Pass or Fail, as in the
tool. Files the page doesn't read say what to run instead.

The script must never reach the network or build HTML from text: those names are not in it.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from judgekeeper import start
from tests.conftest import FIXTURES

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "website" / "assets" / "freecheck.js"
CLI = ROOT / "tests" / "freecheck_cli.mjs"
NODE = shutil.which("node")
FREECHECK = FIXTURES / "freecheck"
needs_node = pytest.mark.skipif(NODE is None, reason="needs node to run the page's free check")


def browser(path: Path) -> dict:
    out = subprocess.run([NODE, str(CLI), str(path)], capture_output=True, text=True,
                         check=True, encoding="utf-8")
    return json.loads(out.stdout)


def _lines(result: dict) -> str:
    return "\n".join(line for j in result["judges"] for line in j["lines"])


# Nothing leaves the page ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["fetch", "XMLHttpRequest", "WebSocket", "sendBeacon",
                                  "EventSource", "Image(", "innerHTML", "outerHTML",
                                  "insertAdjacentHTML", "document.write", "eval(", "new Function",
                                  "localStorage", "import(", "http://", "https://"])
def test_the_script_never_reaches_out_or_builds_html(name):
    code = SCRIPT.read_text(encoding="utf-8")
    pattern = (rf"\b{re.escape(name)}\b" if name.isidentifier()
               else r"\beval\s*\(" if name == "eval(" else re.escape(name))
    assert not re.search(pattern, code), name


# Where the page differs from the tool ---------------------------------------------------------

@needs_node
def test_grades_the_tool_would_ask_about_are_left_out_and_said(tmp_path):
    path = tmp_path / "graded.csv"
    shutil.copy2(FREECHECK / "page-unknown-grades.csv", path)
    assert start.find_judge(path).pool.unmapped  # the tool asks what "maybe" means
    result = browser(path)
    (judge,) = result["judges"]
    assert (judge["pass"], judge["fail"], judge["unmapped"]) == (3, 3, 3)
    assert ('3 grades could not be read as Pass or Fail ("maybe"). They are left out here; '
            "judgekeeper in your project asks what they mean.") in judge["lines"]


@needs_node
def test_a_grade_written_1_0_is_never_a_pass(tmp_path):
    path = tmp_path / "graded.jsonl"
    shutil.copy2(FREECHECK / "page-one-point-zero.jsonl", path)
    assert start.find_judge(path).pool.unmapped == [0.0, 1.0]  # numbers needing a pass mark
    (judge,) = browser(path)["judges"]
    assert (judge["pass"], judge["fail"], judge["unmapped"]) == (0, 0, 6)
    assert '("0.0", "1.0")' in " ".join(judge["lines"])
    assert ("No answer has a clear Pass or Fail from your judge, so there is nothing to mark."
            in judge["lines"])


NOT_CHECKED = {
    "page-records.jsonl": ("This is a judgekeeper.record() file. This page does not read it: "
                           "run uvx judgekeeper in your project for this file."),
    "not-results.json": ("This doesn't look like results judgekeeper can read in the browser. "
                         "The tool also reads Inspect AI and MLflow: run uvx judgekeeper in "
                         "your project."),
    "table-output.json": ("This is promptfoo's table output, which doesn't keep the judge's "
                          "own decisions. Save the full results with promptfoo eval -o "
                          "results.json."),
    "rules-in-code.json": ("rules-in-code.json holds no decisions from an LLM judge. These "
                           "metrics are rules in code, not an LLM judge. judgekeeper checks "
                           "LLM judges."),
    "not-utf8.csv": "This file is not saved as UTF-8 text, so it cannot be read.",
    "ab.csv": ("These are A/B comparisons (output_a and output_b). judgekeeper handles answers "
               "with a Pass or Fail for now."),
}


@needs_node
@pytest.mark.parametrize("name, said", NOT_CHECKED.items())
def test_a_file_the_page_does_not_check_says_what_to_do(name, said):
    result = browser(FREECHECK / name)
    assert not result["ok"] and result["message"] == said


FULL_TOOL = ("Inspect AI and MLflow results are read by the full tool: run uvx judgekeeper in "
             "your project.")


@needs_node
def test_an_inspect_eval_file_says_the_full_tool_reads_it(tmp_path):
    """Inspect's .eval log is a zip: the page names the tool, not a broken file."""
    path = tmp_path / "2026-10-01_task.eval"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("header.json", '{"eval": {"task": "task"}}')
    result = browser(path)
    assert not result["ok"] and result["message"] == FULL_TOOL


@needs_node
def test_an_mlflow_store_says_the_full_tool_reads_it(tmp_path):
    path = tmp_path / "mlflow.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE experiments (experiment_id INTEGER)")
        db.execute("CREATE TABLE assessments (assessment_id TEXT)")
        db.commit()
    result = browser(path)
    assert not result["ok"] and result["message"] == FULL_TOOL


@needs_node
def test_an_empty_file_says_it_is_empty():
    result = browser(FREECHECK / "empty.jsonl")
    assert not result["ok"] and result["message"] == "This file is empty."


@needs_node
def test_judgekeeper_toml_says_to_run_the_tool(tmp_path):
    path = tmp_path / "judgekeeper.toml"
    path.write_text('[start]\nsource = "map"\nfile = "history/evals.jsonl"\n', encoding="utf-8")
    result = browser(path)
    assert result["message"] == ("This is judgekeeper's settings file (judgekeeper.toml). This "
                                 "page does not read it: run uvx judgekeeper in your project "
                                 "for this file.")


@needs_node
def test_a_local_provider_file_is_named_without_its_path():
    (judge,) = browser(FREECHECK / "own-provider.json")["judges"]
    assert judge["models"] == ["your own provider (claude_provider.js)"]
    assert "/home/" not in json.dumps(judge)


# The words it uses --------------------------------------------------------------------------

@needs_node
@pytest.mark.parametrize("name", ["table.csv", "two-judges.json", "errors-counted-as-passes.json",
                                  "score-and-pass-mark.json", "empty-answers.json"])
def test_the_report_keeps_the_tools_word_rules(name):
    result = browser(FREECHECK / name)
    text = "\n".join(line for j in result["judges"] for line in j["lines"]
                     if not line.startswith("Read the columns")).lower()  # its real names
    assert "checked: " in text and "free check" not in text and "your app" not in text
    for banned in ("verdict", "trusted", "proven", "luck", "chance", "works with"):
        assert banned not in text, (name, banned)


@needs_node
def test_the_report_names_the_file_tool_judge_and_grades():
    result = browser(FREECHECK / "table.csv")
    (judge,) = result["judges"]
    assert judge["lines"][:4] == [
        "Eval tool:   your own CSV file",
        "Answers:     12 answers, each graded by your judge",
        "             (read from table.csv)",
        "Judge:       claude-haiku-4-5"]
    assert "Your judge's grades: 8 Pass, 4 Fail." in judge["lines"]
    assert ("Checked: on 1 answer, your judge's reason says the opposite of its "
            "decision.") in judge["lines"]


def _first(judge: dict) -> list[str]:
    code = ("const fc = require(process.argv[1]); const j = JSON.parse(process.argv[2]);"
            "console.log(JSON.stringify(fc.firstAnswerLines(j).map(l => (l.k || '') + l.text)));")
    out = subprocess.run([NODE, "-e", code, str(SCRIPT), json.dumps(judge)], capture_output=True,
                         text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


@needs_node
def test_the_page_shows_the_first_answer_in_the_file():
    """After the check, the page shows the first answer it read: the question and the answer
    cut to 140 characters, and the judge's grade."""
    lines = _first({"first": {"input": "Q" * 200, "output": "An  answer.\n", "verdict": "pass"}})
    assert lines == ["", "First answer in your file:", "  Question:  " + "Q" * 139 + "…",
                     "  Answer:    An answer.", "  Judge:     Pass"]
    # promptfoo's vars: the question's var, else the longest text in them
    vars_ = {"context": "a much longer text than the question", "query": "Where is it?"}
    assert _first({"first": {"input": vars_, "output": None, "verdict": "fail"}})[2:] == [
        "  Question:  Where is it?", "  Answer:    (none)", "  Judge:     Fail"]
    assert _first({"first": {"input": {"a": "short", "b": "the longest one"}, "output": "x",
                             "verdict": "pass"}})[2] == "  Question:  the longest one"
    assert _first({"first": None}) == []
    (judge,) = browser(FREECHECK / "table.csv")["judges"]
    assert judge["first"]["verdict"] in ("pass", "fail") and judge["first"]["input"]


def test_the_check_words_are_the_tools():
    """The page prints the lines judgekeeper prints in Find (front.py)."""
    from judgekeeper import front

    code = SCRIPT.read_text(encoding="utf-8")
    assert f"var FREE_CHECK = '{front.FREE_CHECK}';" in code
    assert f"var EVERY_ANSWER = '{front.EVERY_ANSWER}';" in code
    assert "' answers, each graded by your judge'" not in code  # n() names the count
    assert "from your app" not in code and "Free check" not in code


def test_the_next_and_privacy_lines_are_the_pages_own():
    code = SCRIPT.read_text(encoding="utf-8")
    assert ("var NEXT = 'to see how often your judge agrees with you, run judgekeeper in your "
            "project folder and mark some answers.';") in code
    assert ("var NEXT_AFTER_ERROR = 'pick another file, or run uvx judgekeeper in your project: "
            "it finds your results by itself.';") in code
    assert ("Your file never leaves this page: it is read on your computer. Turn off Wi-Fi and "
            "it still works.") in code
    assert "var MAX_BYTES = 50 * 1024 * 1024;" in code


@needs_node
def test_an_excel_file_is_named_not_called_inspect(tmp_path):
    """An .xlsx is a zip too: the page looks at the first entry's name."""
    path = tmp_path / "judged.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
    result = browser(path)
    assert not result["ok"]
    assert result["message"] == "Excel files aren't read. Save it as CSV UTF-8."
