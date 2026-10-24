"""Provider errors read as the judge's Fail, judge columns taken without asking, a range of no
width for a judge that gives every answer one grade, report.html after a check that ends Worse,
and the reading of damaged and far-away files. Every fixture here is made up, with the shape of
the files that showed each problem.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from judgekeeper.cli import main
from tests.start_projects import RUBRIC, promptfoo_data, question, split
from tests.test_front import assert_one_next_at_the_end, flat


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


def write_csv(path: Path, columns: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)
    return path


# promptfoo provider errors -----------------------------------------------------------------

def provider_error(row: dict) -> dict:
    """A row as promptfoo saves it when the model under test never answered: the judge never
    ran, so there is no gradingResult."""
    message = "API call error: Request failed after 0 retries: fetch failed"
    row.update({"response": {"error": message}, "error": message, "success": False,
                "score": 0, "failureReason": 2, "gradingResult": None})
    return row


def test_provider_errors_are_never_the_judges_fail(here, capsys):
    data = promptfoo_data(split(24, 16))
    for r in data["results"]["results"]:
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC}]
    for r in data["results"]["results"][:6]:
        provider_error(r)
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "Your judge passed 18 answers and failed 16." in out
    assert "failed 22" not in out
    assert ("6 answers have no answer: the call to the model you test failed, so your judge "
            "never ran. They are left out here.") in flat(out)
    assert "calls failed" not in out


def test_a_file_of_provider_errors_only_has_no_judge_decisions(here, capsys):
    data = promptfoo_data(split(2, 0))
    for r in data["results"]["results"]:
        r["testCase"]["assert"] = [{"type": "llm-rubric", "value": RUBRIC}]
        provider_error(r)
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = run(capsys)
    assert code != 0, out
    assert "failed 2" not in out
    assert "too strict" not in out
    assert "http://127.0.0.1" not in out
    assert ("The call to the model you test failed on every answer, so your judge never ran "
            "and there is nothing to mark.") in flat(out)
    assert "fix your judge" not in out
    line = assert_one_next_at_the_end(out)
    assert line.startswith("Next: re-run your eval once the model you test answers, then run "
                           "`judgekeeper")


# Two judge columns -------------------------------------------------------------------------

def test_a_judge_named_0_1_column_beside_a_score_column_asks_which(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", str(i % 2), ["0.1", "0.5", "0.9"][i % 3],
             str((i + 1) % 2)] for i in range(60)]
    write_csv(here / "results.csv", ["query", "completion", "llm_judge", "passed", "exact_match"],
              rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "http://127.0.0.1" not in out
    assert "llm_judge (60 answers)" in out
    assert "passed (60 answers)" in out
    assert out.index("llm_judge (60 answers)") < out.index("passed (60 answers)")
    assert "--metric NAME" in assert_one_next_at_the_end(out)


def test_a_judge_named_0_1_column_beside_a_verdict_column_asks_which(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", str(i % 2),
             "Fail" if i % 3 == 0 else "Pass"] for i in range(60)]
    write_csv(here / "results.csv", ["input", "output", "llm_judge", "verdict"], rows)
    code, out = run(capsys)
    assert code == 3, out
    assert "http://127.0.0.1" not in out
    assert out.index("llm_judge (60 answers)") < out.index("verdict (60 answers)")
    assert "--metric NAME" in assert_one_next_at_the_end(out)
    code, out = run(capsys, "--metric", "llm_judge")
    assert code == 0, out
    assert "Your judge passed 30 answers and failed 30." in flat(out)


# A judge that gives every answer the same grade ----------------------------------------------

def plain_jeffreys(k: int, n: int, level: float) -> tuple[float, float]:
    """The plain Jeffreys interval for k of n, from Beta(k + 0.5, n - k + 0.5): 0 at the low
    end when k is 0, 1 at the high end when k is n."""
    import random

    rng = random.Random(7)
    draws = sorted(rng.betavariate(k + 0.5, n - k + 0.5) for _ in range(40_000))
    lo, hi = draws[int((1 - level) / 2 * len(draws))], draws[int((1 + level) / 2 * len(draws))]
    return (0.0 if k == 0 else lo), (1.0 if k == n else hi)


@pytest.mark.parametrize("marks", [(23, 17), (12, 8), (30, 10)])
def test_a_judge_that_passes_every_answer_gets_ranges_of_some_width(marks):
    from judgekeeper import targets, weighted

    said_pass, said_fail = marks
    # the judge passed all 40 answers in the pool; the person marked some Pass, some Fail
    out = weighted.corrected(40, 0, said_pass + said_fail, said_pass, 0, 0)
    tpr, tnr = out["tpr_interval"], out["tnr_interval"]
    assert out["tpr"] == 1.0 and out["tnr"] == 0.0
    assert tpr[1] - tpr[0] > 0.01 and tnr[1] - tnr[0] > 0.01
    lo, _ = plain_jeffreys(said_pass, said_pass, weighted.LEVEL)
    _, hi = plain_jeffreys(0, said_fail, weighted.LEVEL)
    assert tpr[0] <= lo + 0.01 and tpr[1] == 1.0
    assert tnr[0] == 0.0 and tnr[1] >= hi - 0.01
    assert targets.level(tpr, tnr) == "not_gate"


@pytest.mark.parametrize("marks", [(17, 23), (8, 12), (10, 30)])
def test_a_judge_that_fails_every_answer_gets_ranges_of_some_width(marks):
    from judgekeeper import targets, weighted

    said_pass, said_fail = marks
    out = weighted.corrected(0, 40, 0, 0, said_pass + said_fail, said_pass)
    tpr, tnr = out["tpr_interval"], out["tnr_interval"]
    assert out["tpr"] == 0.0 and out["tnr"] == 1.0
    assert tpr[1] - tpr[0] > 0.01 and tnr[1] - tnr[0] > 0.01
    _, hi = plain_jeffreys(0, said_pass, weighted.LEVEL)
    lo, _ = plain_jeffreys(said_fail, said_fail, weighted.LEVEL)
    assert tpr[0] == 0.0 and tpr[1] >= hi - 0.01
    assert tnr[0] <= lo + 0.01 and tnr[1] == 1.0
    assert targets.level(tpr, tnr) == "not_gate"



# report.html after a check that ends Worse -------------------------------------------------

@pytest.mark.parametrize("paid", [False, True])
def test_report_after_worse_says_the_last_check_at_the_top(here, capsys, monkeypatch, paid):
    from judgekeeper import again, keys
    from judgekeeper.start_label import StartSession, store_result
    from tests.start_projects import project_promptfoo
    from tests.test_again_run import FakePromptfoo
    from tests.test_check import HAIKU, LENIENT, _marked, _new_outputs, _results
    from tests.test_check import run as check_run

    ws = _marked(here)
    store_result(ws, StartSession(ws))
    before = ws.report_html.read_text(encoding="utf-8")
    assert "Last check" not in before
    if paid:
        project_promptfoo(here)
        for name in keys.all_names():
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "x" * 30)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "y" * 30)
        monkeypatch.setattr(again, "which", lambda name: None)
        _results(here, LENIENT, model=HAIKU, outputs=_new_outputs())
        monkeypatch.setattr(again, "run_process", FakePromptfoo(ws, version="0.124.1"))
        code, out = check_run(capsys, "--yes")
    else:
        monkeypatch.setattr(again, "run_process", lambda *a, **k: pytest.fail("asked"))
        _results(here, LENIENT, model=HAIKU)
        code, out = check_run(capsys)
    assert code == 1, out
    html = ws.report_html.read_text(encoding="utf-8")
    top = html[html.index("Last check"):html.index('class="verdict')]
    assert "claude-haiku-4-5" in top
    assert "Worse" in top
    assert "9 answers went from right to wrong" in flat(top)
    assert "points lower (between" in top
    said = flat(re.sub("<[^>]+>", " ", top))
    for side in ("Pass", "Fail"):  # the new judge's two numbers, each with its range
        assert re.search(rf"When you say {side}, it also says {side}: about \d+% "
                         rf"\(between \d+% and \d+%\)", said), said
    assert "Go back to your old LLM-as-a-judge" in top
    assert html.count("Go back to your old LLM-as-a-judge") == 1
    assert "Answers you passed" in html or "agreed on all" in html  # the old judge stays


# Reading damaged and far-away files --------------------------------------------------------

def test_a_damaged_csv_row_is_named_by_its_line_never_quoted(here, capsys):
    lines = ["verdict,answer,question"] + [f"{i % 2},Answer text {i},Question {i}?"
                                           for i in range(40)]
    (here / "judged.csv").write_text("\n".join(lines) + '\n"unclosed,QZX99 my answer\n',
                                     encoding="utf-8")
    _, out = run(capsys)
    assert "QZX99" not in out
    assert "line 42" in out


def test_an_ndjson_file_is_read_as_jsonl(here, capsys):
    rows = [{"input": question(i), "output": f"A full answer number {i}.",
             "verdict": "fail" if i % 3 == 0 else "pass"} for i in range(30)]
    text = "".join(json.dumps(r) + "\n" for r in rows)
    (here / "out.ndjson").write_text(text, encoding="utf-8")
    code, out = run(capsys)
    assert code == 0, out
    assert "Your judge passed 20 answers and failed 10." in out
    from judgekeeper import find

    assert find.classify_file(here / "out.ndjson") == "table"  # named on the command line


TABLE = "question,generated_answer,llm_grade\n" + "".join(
    f"Question {k}?,This is answer number {k}.,{'PASS' if k % 3 else 'FAIL'}\n" for k in range(40))


@pytest.mark.parametrize("far", ["above", "deep"])
def test_a_far_results_file_never_hides_the_table_here(tmp_path, monkeypatch, capsys, far):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "eval.csv").write_text(TABLE, encoding="utf-8")
    if far == "above":
        (tmp_path / "results.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    else:
        deep = project / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "results.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    monkeypatch.chdir(project)
    _, out = run(capsys)
    assert "No eval results found" not in out, out
    assert "eval.csv" in out


@pytest.mark.parametrize("value", [{"a": 1}, [1, 2]])
def test_a_verdict_that_is_an_object_names_its_line(here, capsys, value):
    rows = [{"input": question(i), "output": f"A full answer number {i}.",
             "verdict": "pass" if i % 2 else "fail"} for i in range(30)]
    rows[4]["verdict"] = value
    (here / "judged.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                       encoding="utf-8")
    _, out = run(capsys, "judged.jsonl")
    assert "didn't expect" not in out, out
    assert "line 5 of judged.jsonl has a verdict judgekeeper can't read" in flat(out)


@pytest.mark.parametrize("body", [b"\x00" * 100, "verdict,é\n".encode("latin-1")],
                         ids=["nul", "latin-1"])
def test_a_file_that_is_not_utf8_says_save_it_as_utf8(here, capsys, body):
    (here / "results.json").write_bytes(body)
    _, out = run(capsys, "results.json")
    assert str(here) not in out
    assert ".." not in out.replace("...", "")
    assert "UTF-8" in assert_one_next_at_the_end(out)


def test_answers_in_an_older_file_too_are_never_run_1_times(here, capsys):
    import os

    from tests.start_projects import deepeval_project

    old = deepeval_project(here, split(10, 10), name="results/test_run_20261001_100000.json")
    new = deepeval_project(here, split(10, 10), name="results/test_run_20261002_100000.json",
                           start=5)
    os.utime(old, (new.stat().st_mtime - 60,) * 2)
    _, out = run(capsys)
    assert "1 times" not in out
    assert "Answers:     25 different answers" in out
    assert "has 40 results" in flat(out)


@pytest.mark.parametrize("column", ["verdict", "llm_grade", "judge_verdict"])
def test_a_table_with_no_question_says_so(here, capsys, column):
    rows = [{"output": f"A full answer number {i}.", column: "FAIL" if i % 3 == 0 else "PASS"}
            for i in range(40)]
    (here / "judge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                      encoding="utf-8")
    _, out = run(capsys)
    assert "No eval results found" not in out, out
    assert "judge.jsonl has your judge's verdicts and the answers but no question" in flat(out)
    assert "question column" in assert_one_next_at_the_end(out)


def test_a_minimal_mlflow_folder_is_damaged_and_gets_no_trash(here, capsys):
    pytest.importorskip("mlflow")
    (here / "mlruns" / "0").mkdir(parents=True)
    (here / "mlruns" / "0" / "meta.yaml").write_text("name: Default\nexperiment_id: '0'\n",
                                                     encoding="utf-8")
    _, out = run(capsys)
    assert "didn't expect" not in out, out
    assert "mlruns can't be read: it's damaged" in flat(out)
    assert not (here / "mlruns" / ".trash").exists()


# Wording -------------------------------------------------------------------------------------

def test_repeats_with_different_grades_never_say_each_is_counted_once(here, capsys):
    data = promptfoo_data(split(9, 9))
    rows = data["results"]["results"]
    extra = []
    for k, verdict in enumerate((True, False)):  # one answer graded twice more, differently
        row = json.loads(json.dumps(rows[0]))
        row["testIdx"] = 100 + k
        row["success"] = row["gradingResult"]["pass"] = verdict
        row["gradingResult"]["componentResults"][0]["pass"] = verdict
        extra.append(row)
    same = json.loads(json.dumps(rows[1]))  # and another twice, with the same grade
    same["testIdx"] = 102
    data["results"]["results"] = rows + extra + [same]
    (here / "results.json").write_text(json.dumps(data), encoding="utf-8")
    _, out = run(capsys)
    assert "so each is counted once)" not in flat(out), out
    assert "counted once unless its grades differ" in flat(out)


def test_every_judge_column_is_in_what_one_line_holds(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", "Pass" if i % 2 else "Fail",
             "Fail" if i % 3 == 0 else "Pass"] for i in range(60)]
    write_csv(here / "results.csv", ["question", "answer", "check_verdict", "llm_verdict"], rows)
    _, out = run(capsys)
    holds = out[out.index("holds:"):out.index("How judgekeeper reads it")]
    assert "check_verdict" in holds and "llm_verdict" in holds


def test_an_expected_output_column_is_not_a_second_answer(here, capsys):
    rows = [[question(i), f"A full answer number {i}.", f"The right answer {i}.",
             "FAIL" if i % 3 == 0 else "PASS"] for i in range(40)]
    write_csv(here / "eval_results.csv", ["question", "output", "expected_output", "llm_grade"],
              rows)
    _, out = run(capsys)
    assert "Count each as its own answer" not in out, out
    assert "output and expected_output" not in out


def test_a_records_file_with_one_damaged_line_names_it(here, capsys):
    from judgekeeper.records import Damaged, read_records

    path = here / "results.jsonl"
    path.write_text(json.dumps({"target_id": "a", "name": "j", "annotator_kind": "LLM",
                                "label": {"x": [1]}, "score": "not a number"}) + "\n",
                    encoding="utf-8")
    with pytest.raises(Damaged) as e:
        read_records(path, bad_lines_ok=True)
    assert "line 1 has a damaged field" in str(e.value)


def test_a_promptfoo_table_inside_results_is_named_as_the_table_output(here, capsys):
    body = [{"outputs": [{"text": f"Answer {k}", "pass": k % 2 == 0}], "vars": [f"Q {k}"]}
            for k in range(40)]
    table = {"head": {"prompts": [{"raw": "Answer {{q}}", "label": "p"}], "vars": ["q"]},
             "body": body}
    (here / "table.json").write_text(json.dumps({"results": {"table": table}}),
                                     encoding="utf-8")
    _, out = run(capsys, "table.json")
    assert "isn't a promptfoo results file" not in out, out
    assert "table output" in flat(out)
