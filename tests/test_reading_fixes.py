"""Reading results files: what Find reads, counts and says about a results file.

- A CSV: multi-line answers with commas, blank or `NaN` scores, a verdict and a score column,
  `N/A` or `error` grades, Excel's `;` and decimal comma, two files in one folder, a title row
  above the header, an `.xlsx`, rows where every cell is empty, UTF-16 and CR-only files.
- What Find says: the "passes too much" warning, the pass mark in the box, every `--pass-if`
  operator, the Checked line next to a null score.
- Eval tools: promptfoo's default grader, a rubric per test, Inspect code scorers, a newer
  `.eval` log without the extra, samples that failed before scoring, DeepEval's newest run,
  empty or all-failed runs, and the pin advice.
No test calls an AI API.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import random
import re
import shutil
import time
import zipfile
from pathlib import Path

import pytest

from tests.start_projects import (
    INSPECT,
    PROMPTFOO,
    deepeval_data,
    inspect_data,
    promptfoo_data,
    split,
)
from tests.test_front import flat, next_lines, run

ROOT = Path(__file__).parent.parent
LINK = "Open this link in your browser to mark answers:"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_csv(path: Path, header, rows, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=kwargs.pop("encoding", "utf-8")) as f:
        w = csv.writer(f, **kwargs)
        w.writerow(header)
        w.writerows(rows)
    return path


def graded(n: int, seed: int = 1) -> list[tuple]:
    rnd = random.Random(seed)
    return [(f"Question {i}?", f"Answer {i}", rnd.choice(("pass", "fail"))) for i in range(n)]


def scored(n: int, seed: int = 1) -> list[tuple]:
    rnd = random.Random(seed)
    return [(f"Question {i}?", f"Answer {i}", f"{rnd.random():.2f}") for i in range(n)]


def grades(out: str):
    m = re.search(r"grades: (\d+) Pass, (\d+) Fail", flat(out))
    return (int(m[1]), int(m[2])) if m else None


def answers(out: str):
    m = re.search(r"Answers: (\d+) answers?", flat(out))
    return int(m[1]) if m else None


def find(capsys, *argv):
    """`judgekeeper` without a browser on any free port: (exit code, what it printed)."""
    code, out, err = run(capsys, *argv, "--no-browser", "--port", "0")
    return code, out + err


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# 15. A multi-line answer with commas --------------------------------------------------------

def test_multi_line_answers_with_commas_are_not_a_broken_quote(here, capsys):
    rows = [(f"Question {i}?", (f"Step one, check the input\nStep two, then, compare\n"
                               f"Step three, done, ok {i}"), "pass" if i % 3 else "fail")
            for i in range(40)]
    write_csv(here / "results.csv", ["input", "output", "verdict"], rows)
    code, out = find(capsys)
    assert "never closes" not in out
    assert code == 0 and answers(out) == 40 and LINK in out, out


# 16. A blank or NaN score -------------------------------------------------------------------

@pytest.mark.parametrize("blank", ["", "NaN"])
def test_a_blank_score_is_no_decision_and_the_pass_mark_is_used(here, capsys, blank):
    rows = scored(40, 3)
    rows[4] = (rows[4][0], rows[4][1], blank)
    write_csv(here / "results.csv", ["input", "output", "score"], rows)
    code, out = find(capsys, "--pass-if", "score>=0.5", "--yes")
    assert all(x.count("--pass-if") <= 1 for x in next_lines(out)), out
    assert code == 0 and LINK in out, out
    scores = [float(x[2]) for x in rows if x[2] not in ("", "NaN")]
    assert grades(out) == (sum(s >= 0.5 for s in scores), sum(s < 0.5 for s in scores))
    assert "no real decision on 1 of 40" in flat(out)


# 17. A verdict and a score column with --pass-if ---------------------------------------------

def test_pass_if_reads_the_score_column_and_says_so(here, capsys):
    rows = [(q, a, "pass" if i < 30 else "fail", s) for i, (q, a, s) in enumerate(scored(40, 5))]
    write_csv(here / "results.csv", ["input", "output", "verdict", "score"], rows)
    _, out = find(capsys, "--pass-if", "score>=0.7", "--yes")
    assert "Read the score column with your pass mark; the verdict column is not used." in \
        flat(out)
    assert grades(out) == (sum(float(x[3]) >= 0.7 for x in rows),
                           sum(float(x[3]) < 0.7 for x in rows)), out


# 18. N/A and error as grades ------------------------------------------------------------------

def test_na_and_error_grades_are_no_decision(here, capsys):
    rows = [list(x) for x in graded(40, 4)]
    for i, value in zip(range(3, 8), ("N/A", "error", "null", "none", "nan"), strict=True):
        rows[i][2] = value
    write_csv(here / "results.csv", ["input", "output", "verdict"], rows)
    code, out = find(capsys)
    assert code == 0 and LINK in out, out
    assert "no real decision on 5 of 40" in flat(out)


def test_a_label_map_may_say_error(here, capsys):
    rows = [list(x) for x in graded(40, 4)]
    rows[3][2] = "maybe"
    write_csv(here / "results.csv", ["input", "output", "verdict"], rows)
    code, out = find(capsys, "--label-map", "maybe=error")
    assert code == 0 and LINK in out, out
    assert "labels for single items" not in out
    assert "no real decision on 1 of 40" in flat(out)


def test_the_label_map_advice_names_error(here, capsys):
    rows = [list(x) for x in graded(40, 4)]
    rows[3][2] = "unclear"
    write_csv(here / "results.csv", ["input", "output", "verdict"], rows)
    code, out = find(capsys)
    assert code == 3
    assert "=error" in next_lines(out)[-1], out


# 19. A European Excel CSV ------------------------------------------------------------------------

def test_a_decimal_comma_in_a_semicolon_file_is_a_number(here, capsys):
    rnd = random.Random(7)
    values = [rnd.randint(0, 99) for _ in range(40)]
    with (here / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        f.write("input;output;score\r\n")
        for i, v in enumerate(values):
            f.write(f"Q{i};A{i};0,{v:02d}\r\n")
    _, out = find(capsys, "--pass-if", "score>=0.5", "--yes")
    assert grades(out) == (sum(v >= 50 for v in values), sum(v < 50 for v in values)), out


# 20. Two results files in one folder --------------------------------------------------------

def test_another_results_file_is_named_with_its_command(here, capsys):
    write_csv(here / "judge_b.csv", ["input", "output", "verdict"], graded(40, 2))
    write_csv(here / "judge_a.csv", ["input", "output", "verdict"], graded(40, 1))
    now = time.time()
    os.utime(here / "judge_b.csv", (now - 3600, now - 3600))
    code, out = find(capsys)
    assert code == 0, out
    assert "Also found judge_b.csv. To check it, run `judgekeeper judge_b.csv`." in flat(out)


def test_at_most_three_other_files_are_named(here, capsys):
    now = time.time()
    for k in range(5):
        write_csv(here / f"judge_{k}.csv", ["input", "output", "verdict"], graded(40, k))
        os.utime(here / f"judge_{k}.csv", (now - 3600 * (5 - k),) * 2)
    code, out = find(capsys)
    assert code == 0, out
    named = [k for k in range(4) if f"judge_{k}.csv" in out]
    assert len(named) == 3, out


# 21. "Passes too much" ----------------------------------------------------------------------

def test_too_much_is_said_only_under_a_fifth(here, capsys):
    rows = [(f"Q{i}?", f"A{i}", "pass" if i < 16 else "fail") for i in range(30)]
    write_csv(here / "results.csv", ["input", "output", "verdict"], rows)
    assert "too much" not in find(capsys)[1]
    rows = [(f"Q{i}?", f"A{i}", "pass" if i < 36 else "fail") for i in range(40)]
    write_csv(here / "b" / "results.csv", ["input", "output", "verdict"], rows)
    assert "passes too much" in flat(find(capsys, "b")[1])


# 22. One pass mark on screen ------------------------------------------------------------------

@pytest.mark.parametrize("values, rule, shown", [
    (None, "score>=0.7", "0.7"), ([1, 2, 3, 4, 5] * 8, "score>=4", "4")])
def test_the_box_shows_the_pass_mark_used(here, capsys, values, rule, shown):
    rows = scored(40, 3) if values is None else [(f"Q{i}", f"A{i}", v)
                                                 for i, v in enumerate(values)]
    write_csv(here / "results.csv", ["input", "output", "score"], rows)
    _, out = find(capsys, "--pass-if", rule, "--yes")
    box = re.search(r"^\s*pass mark:\s+(.*)$", out, re.MULTILINE)
    assert box is None or shown in box[1], out


# 23. Every --pass-if operator -----------------------------------------------------------------

@pytest.mark.parametrize("op, mark, passes", [
    (">", 4, lambda v: v > 4), (">=", 4, lambda v: v >= 4), ("<", 3, lambda v: v < 3),
    ("<=", 2, lambda v: v <= 2), ("==", 5, lambda v: v == 5)])
def test_every_pass_if_operator_reads_an_own_format_file(here, capsys, op, mark, passes):
    rnd = random.Random(9)
    values = [rnd.randint(1, 5) for _ in range(40)]
    write_csv(here / "results.csv", ["input", "output", "score"],
              [(f"Q{i}", f"A{i}", v) for i, v in enumerate(values)])
    _, out = find(capsys, "--pass-if", f"score{op}{mark}", "--yes")
    assert 'give the pass mark as --pass-if "score>=N"' not in out
    assert grades(out) == (sum(map(passes, values)), sum(not passes(v) for v in values)), out


# 24. A null score and the Checked line ------------------------------------------------------------

def test_a_null_score_is_counted_on_the_checked_line(here, capsys):
    with (here / "results.jsonl").open("w", encoding="utf-8") as f:
        for i in range(40):
            f.write(json.dumps({"input": f"Q{i}", "output": f"A{i}",
                                "score": None if i == 3 else (i % 10) / 10}) + "\n")
    _, out = find(capsys, "--yes")
    assert "every answer a clear Pass or Fail" not in out, out


# 25. A title row, an .xlsx, empty rows -----------------------------------------------------------

def _titled(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write("My eval results 2026-10-17,,\n")
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        w.writerows(graded(40, 11))


HEADER_ROW = "Row 2 looks like the header. Delete row 1 and run again."


def test_a_title_row_above_the_header_is_named(here, capsys):
    _titled(here / "results.csv")
    assert HEADER_ROW in flat(find(capsys)[1])
    assert HEADER_ROW in flat(find(capsys, "results.csv")[1])


def test_an_excel_file_says_how_to_save_it(here, capsys):
    with zipfile.ZipFile(here / "results.xlsx", "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    _, out = find(capsys, "results.xlsx")
    assert "Excel files aren't read. Save it as CSV UTF-8 and run again." in flat(out)


def test_rows_where_every_cell_is_empty_are_skipped(here, capsys):
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("input,output,verdict,,\r\n")
        for q, a, v in graded(40, 12):
            f.write(f"{q},{a},{v},,\r\n")
        f.write(",,,,\r\n" * 5)
    _, out = find(capsys)
    assert answers(out) == 40 and "empty decision" not in out, out


# 26. Files the search skipped --------------------------------------------------------------

def test_a_utf16_file_is_named_as_left_out(here, capsys):
    with (here / "results.tsv").open("w", encoding="utf-16", newline="") as f:
        f.write("input\toutput\tverdict\r\n")
        for q, a, v in graded(40):
            f.write(f"{q}\t{a}\t{v}\r\n")
    _, out = find(capsys)
    text = flat(out)
    assert "left out" in text and "results.tsv" in text and "UTF-8" in text, out


def test_a_cr_only_file_is_read_in_the_search(here, capsys):
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        f.write("input,output,verdict\r")
        for q, a, v in graded(40):
            f.write(f"{q},{a},{v}\r")
    code, out = find(capsys)
    assert code == 0 and answers(out) == 40 and LINK in out, out


# 27. The reference ---------------------------------------------------------------------------

def test_the_reference_does_not_promise_the_first_rows():
    assert "first 3 rows" not in (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")


# 28 and 32. promptfoo: the default grader, a rubric per test, factuality ---------------------

def test_answers_graded_by_promptfoos_default_grader_are_said(here, capsys):
    data = promptfoo_data(split(20, 20))
    for row in data["results"]["results"][20:]:
        row["testCase"]["options"] = {}
    _write(here / "results.json", data)
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _, out = find(capsys)
    assert "default grader" in flat(out), out


def test_a_rubric_per_test_is_said(here, capsys):
    data = promptfoo_data(split(20, 20))
    for i, row in enumerate(data["results"]["results"]):
        row["gradingResult"]["componentResults"][0]["assertion"]["value"] = f"Rubric {i}"
    _write(here / "results.json", data)
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _, out = find(capsys)
    assert re.search(r'Judge rule: differs per test \(40 rules\)\. First: "Rubric 0"',
                     flat(out)), out


def test_factuality_compares_with_each_tests_reference(here, capsys):
    _write(here / "results.json", json.loads(PROMPTFOO.read_text(encoding="utf-8")))
    (here / "promptfooconfig.yaml").write_text('prompts: ["{{question}}"]\n', encoding="utf-8")
    _, out = find(capsys, "--metric", "factuality")
    assert "compared with each test's reference answer" in flat(out), out
    assert '"reference 0"' not in out


# 29, 30 and 33. Inspect AI ------------------------------------------------------------------

def _inspect_log(root: Path, name: str, data: dict) -> Path:
    return _write(root / "logs" / name, data)


def test_inspect_code_scorers_are_not_judges(here, capsys):
    _inspect_log(here, "2026-09-30T10-00-00+00-00_qa_fixture.json",
                 json.loads(INSPECT.read_text(encoding="utf-8")))
    _, out = find(capsys)
    assert not re.search(r"^\s*match \(\d+ answers?\)", out, re.MULTILINE), out
    _, out = find(capsys, "--metric", "match")
    assert not re.search(r"Judge:\s+match\b", out), out


def test_a_newer_eval_log_without_the_extra_is_said(here, capsys, monkeypatch):
    from judgekeeper import start

    monkeypatch.setattr(start, "_has", lambda name: name != "inspect_ai")
    _inspect_log(here, "2026-10-17T17-47-27-00-00_qa_old.json", inspect_data(split(20, 20)))
    with zipfile.ZipFile(here / "logs" / "2026-10-17T17-49-42-00-00_qa_new.eval", "w") as z:
        z.writestr("header.json", "{}")
    later = time.time() + 60
    os.utime(here / "logs" / "2026-10-17T17-49-42-00-00_qa_new.eval", (later, later))
    _, out = find(capsys)
    assert ".eval" in out and "judgekeeper[inspect]" in out, out


def _errored_inspect(verdicts, errored=(3, 7)) -> dict:
    """Two epochs of one sample per verdict; samples `errored` failed before scoring (no
    scores, an error), and a second scorer, rubric, gives a dict per sample."""
    data = inspect_data(verdicts)
    spec = data["eval"]
    spec["scorers"] = [*spec["scorers"], {"name": "rubric", "options": {}}]
    samples = []
    for epoch in (1, 2):
        for s in data["samples"]:
            s = copy.deepcopy(s)
            s["epoch"] = epoch
            s["scores"]["rubric"] = {"value": {"accuracy": "C", "tone": "I"}}
            if s["id"] in errored:
                s["scores"] = {}
                s["error"] = {"message": "RuntimeError: the app crashed"}
            samples.append(s)
    return {**data, "samples": samples}


def test_samples_that_failed_before_scoring(here, capsys):
    _inspect_log(here, "2026-10-17_qa.json", _errored_inspect([*split(10, 6), *["P"] * 4]))
    _, out = find(capsys)
    assert not re.search(r"^\s*rubric \(\d+ answers?\)", out, re.MULTILINE), out
    _, first = find(capsys, "--metric", "model_graded_qa")
    _, out = find(capsys, "--metric", "model_graded_qa", "--label-map", "P=fail")
    assert "calls failed" not in out
    assert "2 answers have no score: the run failed before scoring." in flat(out), out
    assert answers(first) is not None and answers(first) == answers(out) == 20, (first, out)


# 31 and 34. DeepEval ---------------------------------------------------------------------------

def test_the_newest_deepeval_run_is_read_and_both_files_named(here, capsys):
    old = _write(here / "deepeval-results" / "test_run_20261001_100000.json",
                 deepeval_data(split(20, 20), model="gpt-4.1"))
    stamp = time.mktime((2026, 10, 1, 10, 0, 0, 0, 0, -1))
    os.utime(old, (stamp, stamp))
    _write(here / ".deepeval" / ".latest_run_full.json",
           deepeval_data(split(20, 20), model="gpt-5", start=100))
    _, out = find(capsys)
    text = flat(out)
    assert re.search(r"Judge:.*gpt-5\b", text), out
    assert ".latest_run_full.json" in text and "test_run_20261001_100000.json" in text
    assert "1 Oct" in text, out


def test_an_empty_deepeval_run_says_it_has_no_test_cases(here, capsys):
    _write(here / "deepeval-results" / "test_run_20261016_100000.json",
           {"testCases": [], "conversationalTestCases": []})
    (here / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    _, out = find(capsys)
    assert "The run has no test cases." in flat(out), out
    assert "add an LLM judge" not in out


def test_every_judge_call_failed_is_not_each_graded(here, capsys):
    data = promptfoo_data(split(15, 15))
    for row in data["results"]["results"]:
        c = row["gradingResult"]["componentResults"][0]
        c.update(**{"pass": False, "score": 0, "reason": "API error: 429 rate limited",
                    "metadata": {"graderError": True}})
    _write(here / "results.json", data)
    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _, out = find(capsys)
    assert "each graded by your judge" not in out, out


# 35. Pin advice ---------------------------------------------------------------------------------

def test_the_projects_own_pin_is_used(here, capsys):
    _write(here / ".deepeval" / ".latest_run_full.json", deepeval_data(split(20, 20)))
    (here / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\ndependencies = ["deepeval==4.0.5"]\n',
        encoding="utf-8")
    for argv in ((), (".deepeval/.latest_run_full.json",)):
        _, out = find(capsys, *argv)
        assert [v for v in re.findall(r"deepeval==([\d.]+)", out) if v != "4.0.5"] == [], out
        shutil.rmtree(here / ".judgekeeper", ignore_errors=True)


def test_without_a_pin_the_installed_version_is_named(monkeypatch):
    from judgekeeper import judge_check

    monkeypatch.setattr(judge_check, "installed", lambda package: "9.9.9")
    found = type("F", (), {"tool": "deepeval", "models": ["m"], "model_source": None})()
    assert judge_check.setup_lines(found, {"tool_version": None}) == [
        ("judgekeeper can't see your eval tool's version, so an update to it won't be noticed. "
        "Pin it in your project (e.g. `deepeval==9.9.9`).")]


# 44. The file's own ids ------------------------------------------------------------------------

def _own_rows(n: int) -> list[dict]:
    return [{"id": f"q{i}", "input": f"Question {i}?", "output": f"Answer {i}.",
             "verdict": ("pass", "fail")[i % 2], "reason": f"reason {i}"} for i in range(n)]


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _pool_ids(root: Path) -> set[str]:
    lines = (root / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8").splitlines()
    return {json.loads(x)["id"] for x in lines if x.strip()}


MADE_OWN = "The id column has blank or repeated ids, so judgekeeper made its own."


@pytest.mark.parametrize("name, score", [("results.jsonl", False), ("graded.jsonl", True)])
def test_the_files_id_column_is_the_answer_id(here, capsys, name, score):
    rows = _own_rows(40)
    if score:  # a file in its own format: a score, read with a map
        rows = [{"id": r["id"], "question": r["input"], "answer": r["output"],
                 "score": 0.9 if r["verdict"] == "pass" else 0.1} for r in rows]
    _jsonl(here / name, rows)
    code, out = find(capsys, "--yes")
    assert code == 0 and LINK in out, out
    assert _pool_ids(here) == {r["id"] for r in rows}
    assert MADE_OWN not in out


@pytest.mark.parametrize("name, score", [("results.jsonl", False), ("graded.jsonl", True)])
def test_blank_or_repeated_ids_are_made_by_judgekeeper_and_said_once(here, capsys, name, score):
    rows = _own_rows(40)
    if score:
        rows = [{"id": r["id"], "question": r["input"], "answer": r["output"],
                 "score": 0.9 if r["verdict"] == "pass" else 0.1} for r in rows]
    rows[3]["id"] = ""
    rows[7]["id"] = rows[8]["id"]
    _jsonl(here / name, rows)
    code, out = find(capsys, "--yes")
    assert code == 0 and LINK in out, out
    assert flat(out).count(MADE_OWN) == 1, out
    assert not _pool_ids(here) & {r["id"] for r in rows}
