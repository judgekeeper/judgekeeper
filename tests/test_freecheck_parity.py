"""The free check in the browser (website/assets/freecheck.js) says what the tool says.

For every promptfoo, DeepEval and table fixture, the Python reader and free check (find_judge,
judge_check) and node running freecheck.js (tests/freecheck_cli.mjs) are compared: whether the
file can be read at all, the judges, and for each judge its answers, Pass and Fail counts,
model, rule and the free check's findings, word for word. The places where the page must differ
from the tool (it can't ask a question) are tested on their own below. Tables of answers with
no grade (start.read_results_table's answers) and agent runs (steps.read_runs) are compared too:
readable or not, the counts, the first answer or the first run's steps, and the refusal reason.

Needs node (CI sets up Node 22); skipped with the reason when it is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from judgekeeper import find, front, judge_check, start, steps
from tests import test_reader_grader_details as grader_details
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
                 "rules-in-code.json", "empty.jsonl", "scores-only.csv", "verdict-scores.csv"):
        assert name in names, name


def _tool_run(path: Path) -> str:
    """What `judgekeeper <file>` prints for a table it reads by its columns' names (its own map,
    saved in judgekeeper.toml): the tool asks no question for these names. Its input is an empty
    pipe: on Windows the empty device counts as a terminal, and the tool would ask."""
    run = [sys.executable, "-m", "judgekeeper"]
    out = subprocess.run([*run, path.name, "--no-browser", "--port", "0", "--yes"], check=False,
                         cwd=path.parent, capture_output=True, text=True, timeout=120,
                         input="", encoding="utf-8").stdout
    subprocess.run([*run, "--stop"], check=False, cwd=path.parent, capture_output=True,
                   input="", text=True, timeout=60)
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


@pytest.mark.parametrize("name", ["scores-only.csv", "verdict-scores.csv"])
def test_grades_that_are_scores_say_what_the_tool_says(name, tmp_path):
    """The tool stops and asks for a pass mark; the page says the same scores and that it asks."""
    path = tmp_path / name
    shutil.copy2(FREECHECK / name, path)
    said = _tool_run(path)
    (judge,) = browser(path)["judges"]
    (line,) = [x for x in judge["lines"] if "are scores" in x]
    first = line.split(". judgekeeper in your project")[0] + "."
    assert first in said, said
    assert "which score counts as a pass" in said and "which score counts as a pass" in line


def test_a_table_it_cant_place_names_the_columns_it_reads(tmp_path):
    path = tmp_path / "scores.csv"
    path.write_text("case,text,mark\n1,hello,7\n", encoding="utf-8")
    said = browser(path)
    assert said["ok"] is False and said["message"].startswith(
        "judgekeeper can't tell which columns hold the question, the answer and the grade (this "
        "file has case, text and mark). In the browser it reads a CSV, TSV or JSONL file with a "
        "question column (input or question), an answer column (output or answer) and a grade "
        "column (verdict or grade) holding Pass or Fail."), said


# Answers with no grades and agent runs ---------------------------------------------------

ANSWERS = sorted((FREECHECK / "answers").iterdir())
RUNS = sorted((FREECHECK / "runs").iterdir())
STEPS_SHOWN = 8  # the first run's steps the page shows


def tool_answers(path: Path) -> dict:
    """What the tool reads in a table of answers with no grade (find.answers_only, then
    start.read_results_table's answers): {"ok": False} when it is not one or can't be read."""
    if not find.answers_only(path):
        return {"ok": False}
    try:
        records = start.read_results_table(path, answers=True)
    except start.StartError:
        return {"ok": False}
    first = records.answers[0]
    return {"ok": True, "answers": len(records.answers),
            "first": {"input": first["input"], "output": first["output"]}}


def page_answers(result: dict) -> dict:
    if not result["ok"] or result.get("kind") != "answers":
        return {"ok": False}
    return {"ok": True, "answers": result["answers"], "first": result["first"]}


def tool_runs(path: Path) -> dict:
    """What `judgekeeper steps` reads in a runs file (steps.read_runs): the runs, the fewest
    and most steps in one, and the first run's steps; or the reason it refuses the file, with
    the file's name said as the page says it."""
    try:
        runs = steps.read_runs(path)
    except steps.StepsError as e:
        said = str(e).replace(path.name, "this file")
        return {"ok": False, "message": said[:1].upper() + said[1:]}
    counts = [len(run.steps) for run in runs]
    first = runs[0].steps
    return {"ok": True, "runs": len(runs), "steps": [min(counts), max(counts)],
            "first": {"n": len(first), "steps": [
                {"role": s["role"].split(". ", 1)[1], "text": s["content"]}
                for s in first[:STEPS_SHOWN]]}}


def page_runs(result: dict) -> dict:
    if not result["ok"]:
        return {"ok": False, "message": result["message"]}
    if result.get("kind") != "runs":
        return {"ok": "not read as runs"}
    return {"ok": True, "runs": result["runs"], "steps": [result["minSteps"], result["maxSteps"]],
            "first": result["first"]}


@pytest.mark.parametrize("fixture", ANSWERS, ids=lambda p: p.name)
def test_answers_with_no_grades_are_read_as_the_tool_reads_them(fixture, tmp_path):
    path = tmp_path / fixture.name
    shutil.copy2(fixture, path)
    said = browser(path)
    assert page_answers(said) == tool_answers(path)
    if said["ok"] and said.get("kind") == "answers":
        kind = {".csv": "CSV", ".tsv": "TSV", ".jsonl": "JSONL"}[path.suffix]
        assert said["toolName"] == f"your own {kind} file"


@pytest.mark.parametrize("fixture", RUNS, ids=lambda p: p.name)
def test_agent_runs_are_read_as_judgekeeper_steps_reads_them(fixture, tmp_path):
    path = tmp_path / fixture.name
    shutil.copy2(fixture, path)
    assert page_runs(browser(path)) == tool_runs(path)


def test_every_kind_of_answers_and_runs_file_is_compared():
    """Readable and refused files of both kinds, each one compared."""
    assert {p.name for p in ANSWERS} >= {"answers.csv", "answers.tsv", "answers.jsonl"}
    assert {p.name for p in RUNS} >= {
        "equal.jsonl", "unequal.jsonl", "one-run.jsonl", "two-hundred-steps.jsonl",
        "long-step.jsonl", "missing-id.jsonl", "duplicate-id.jsonl", "empty-steps.jsonl",
        "no-role.jsonl", "fake-key.jsonl", "script-tag.jsonl"}
    read = [p for p in RUNS if tool_runs(p)["ok"]]
    assert len(read) >= 7 and len(RUNS) - len(read) >= 5
    assert sum(tool_answers(p)["ok"] for p in ANSWERS) >= 3


def test_answers_with_no_grades_print_the_approved_lines(tmp_path):
    path = tmp_path / "shop-answers-no-grades.csv"
    rows = ["input,output", ('Can I return a lamp after 60 days?,"Of course! We accept returns '
                             'at any time, no questions asked."')]
    rows += [f"Question {i}?,Answer {i}." for i in range(39)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert browser(path)["lines"] == [
        "$ judgekeeper",
        "Step 1 of 4: Read",
        "",
        "Eval tool:       your own CSV file",
        "File:            shop-answers-no-grades.csv",
        "Answers:         40 answers",
        "LLM-as-a-judge:  none in your file",
        "",
        front.PATH_NO_GRADES.format(file="This file"),  # the tool's own words
        "",
        "First answer in your file:",
        "  Question:      Can I return a lamp after 60 days?",
        "  Answer:        Of course! We accept returns at any time, no questions asked.",
        "",
        "Next: to mark each answer Pass or Fail, run judgekeeper in your project folder."]


def _runs_file(path: Path, counts: list[int]) -> Path:
    first = [{"role": "user", "content": "I want to return order 4471."},
             {"role": "tool call", "content": "lookup_order(4471)"},
             {"role": "tool", "content": "Delivered 72 days ago."}]
    lines = []
    for i, n in enumerate(counts):
        made = first[:n] if i == 0 else []
        made = made + [{"role": "assistant", "content": f"Reply {k}."}
                       for k in range(n - len(made))]
        lines.append(json.dumps({"id": f"run-{i + 1}", "steps": made}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_agent_runs_print_the_approved_lines(tmp_path):
    path = _runs_file(tmp_path / "agent-runs.jsonl", [4, 3, 8, 5, 6, 7, 3, 4, 8, 5, 6, 4])
    assert browser(path)["lines"] == [
        "$ judgekeeper steps agent-runs.jsonl",
        "",
        "File:            agent-runs.jsonl",
        "Runs:            12 runs",
        "Steps:           3 to 8 in each run",
        "",
        ("This file has agent runs, so judgekeeper checks each run's steps: you click the first "
         "wrong step, or All steps are fine."),
        "",
        "First run in your file:",
        "  Step 1  user       I want to return order 4471.",
        "  Step 2  tool call  lookup_order(4471)",
        "  Step 3  tool       Delivered 72 days ago.",
        "  Step 4  assistant  Reply 0.",
        "",
        ("Next: to click the first wrong step of each run, run judgekeeper steps "
         "agent-runs.jsonl in your project folder.")]


@pytest.mark.parametrize("counts, runs, said", [
    ([4, 4, 4], "3 runs", "4 in each run"), ([3], "1 run", "3 in each run")])
def test_runs_of_one_length_say_it_once(tmp_path, counts, runs, said):
    lines = browser(_runs_file(tmp_path / "runs.jsonl", counts))["lines"]
    assert f"Runs:            {runs}" in lines and f"Steps:           {said}" in lines


def test_a_long_run_shows_its_first_eight_steps_and_how_many_more(tmp_path):
    path = tmp_path / "two-hundred-steps.jsonl"
    shutil.copy2(FREECHECK / "runs" / path.name, path)
    lines = browser(path)["lines"]
    shown = [line for line in lines if line.startswith("  Step ")]
    assert len(shown) == STEPS_SHOWN and shown[0].startswith("  Step 1  ")
    assert "  ... and 192 more steps" in lines


def test_a_long_step_is_cut_to_one_short_line(tmp_path):
    path = tmp_path / "long-step.jsonl"
    shutil.copy2(FREECHECK / "runs" / path.name, path)
    (step,) = [line for line in browser(path)["lines"] if line.startswith("  Step 1")]
    assert len(step) < 200 and step.endswith("…")


def test_step_text_is_shown_as_text_with_no_key_and_no_hidden_character(tmp_path):
    for name in ("fake-key.jsonl", "script-tag.jsonl"):
        shutil.copy2(FREECHECK / "runs" / name, tmp_path / name)
    keyed = "\n".join(browser(tmp_path / "fake-key.jsonl")["lines"])
    assert "sk-ant" not in keyed and "abcdefghij0123456789" not in keyed
    assert "[REDACTED]" in keyed
    tagged = browser(tmp_path / "script-tag.jsonl")["lines"]
    width = len("<b>assistant</b>") + 2
    assert ("  Step 1  " + "user".ljust(width) +
            "<script>alert('hi')</script> and <img src=x onerror=alert(1)>") in tagged
    assert ("  Step 2  " + "<b>assistant</b>".ljust(width) +
            "Text with a hidden character and a second line.") in tagged
    page = (ROOT / "website" / "assets" / "freecheck.js").read_text(encoding="utf-8")
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page


def test_a_runs_file_it_refuses_says_why_and_never_quotes_the_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"id": "r1", "steps": [{"role": "user", "content": "hi"}]}\n'
                    '{"id": "secret-run-name", "steps": []}\n', encoding="utf-8")
    said = browser(path)
    assert said["ok"] is False and said["message"] == (
        'Line 2 of this file has no steps (a list of {"role": ..., "content": ...}).')
    assert "secret-run-name" not in json.dumps(said)


@pytest.mark.parametrize("name, text, columns", [
    ("answers.csv", "question,answer\nWhat is 2+2?,4\n", "question and answer"),
    ("answers.jsonl", '{"prompt": "What is 2+2?", "response": "4"}\n', "prompt and response")])
def test_answers_under_other_names_say_what_to_rename_as_the_tool_does(tmp_path, name, text,
                                                                        columns):
    """The tool reads answers with no grade from an input and an output column; under other
    names it says what to rename (own_map.other_columns), and so does the page."""
    from judgekeeper import own_map

    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    assert tool_answers(path) == {"ok": False}
    said = browser(path)
    assert said["ok"] is False and said["message"] == (
        f"This file has the columns {columns}, and no LLM-as-a-judge grades. "
        f"{own_map.ANSWER_COLUMNS} Rename the question column to input and the answer column "
        "to output."), said


def test_the_page_names_agent_runs_among_what_it_reads(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("just some notes\n", encoding="utf-8")
    assert browser(path)["message"] == (
        "This isn't a results file this page can read. It reads promptfoo, DeepEval, CSV, TSV "
        "and JSONL files, and agent runs. For other results, run `uvx judgekeeper` in your "
        "project.")


@pytest.mark.parametrize("suffix, sep", [(".csv", ","), (".tsv", "\t")])
def test_a_score_column_with_no_verdict_column_is_read_as_a_verdict_column_of_scores(
        tmp_path, suffix, sep):
    """The tool reads it with --pass-if; the page can't ask for one, so it reads the scores
    as it reads them in a verdict column."""
    rows = [[f"Question {i}?", f"Answer {i}.", "0.9" if i % 3 else "0.2", f"Reason {i}."]
            for i in range(12)]
    said = {}
    for grade in ("score", "verdict"):
        path = tmp_path / grade / f"results{suffix}"
        path.parent.mkdir()
        path.write_text("\n".join(sep.join(r) for r in [["input", "output", grade, "reason"],
                                                       *rows]) + "\n", encoding="utf-8")
        page = browser(path)
        (judge,) = page["judges"]
        assert judge["key"] == grade and ["grade", f"the {grade} column"] in judge["readRows"]
        said[grade] = _page(page)["judges"][grade]
    assert said["score"] == said["verdict"]


def test_an_error_grade_is_an_error_not_an_empty_decision(tmp_path):
    """A table whose grade is the word "error": no decision, said as such, not a blank one."""
    path = table_project(tmp_path, [True] * 10 + [False] * 10 + ["error", None])
    said = tool(path)
    assert _page(browser(path)) == said
    assert said["judges"]["verdict"]["findings"][0].startswith(
        "Your LLM-as-a-judge made no real decision on 2 of 22 answers: 1 error, 1 empty "
        "decision."), said


@pytest.mark.parametrize("configured, made", [
    *grader_details.OTHER_PROVIDER, *grader_details.SAME_PROVIDER])
def test_a_made_grader_takes_the_config_id_as_the_tool_does(tmp_path, configured, made):
    data = json.loads(grader_details.RESULTS.read_text(encoding="utf-8"))
    data["config"]["defaultTest"]["options"]["provider"] = configured
    for row in data["results"]["results"]:
        row["testCase"].setdefault("options", {})["provider"] = made
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _page(browser(path)) == tool(path)


def test_human_labels_in_a_table_are_said_as_the_tool_says_them(tmp_path):
    """The Find line for labels already in the results: the page says the plain command."""
    from judgekeeper import front

    path = table_project(tmp_path, [True] * 8 + [False] * 4, name="table.csv",
                         extra={"human_label": ["pass"] * 6 + [""] * 6})
    (judge,) = browser(path)["judges"]
    said = [x for x in front._notes(start.find_judge(path), "judgekeeper --labels")
            if x.startswith("Found")]
    assert said == [("Found 6 labels in your results. To use them as your marks, run "
                     "`judgekeeper --labels`.")]
    assert said[0] in judge["lines"]


def test_table_labels_are_for_every_judge_in_the_table(tmp_path):
    """A table's label column is for the whole answer, whichever verdict column is chosen."""
    from judgekeeper import front

    path = tmp_path / "table.csv"
    rows = ["input,output,verdict,judge_verdict,human_label"]
    rows += [f"q{i},a{i},{'pass' if i < 8 else 'fail'},{'pass' if i % 2 else 'fail'},"
             f"{'pass' if i < 5 else ''}" for i in range(12)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    for judge in browser(path)["judges"]:
        said = [x for x in front._notes(start.find_judge(path, metric=judge["key"]),
                                        "judgekeeper --labels") if x.startswith("Found")]
        assert said == [("Found 5 labels in your results. To use them as your "
                         "marks, run `judgekeeper --labels`.")], judge["key"]
        assert said[0] in judge["lines"]
