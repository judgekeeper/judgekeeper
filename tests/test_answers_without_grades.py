"""A results file with a question and an answer and no grade: the person marks each answer
Pass or Fail, and from 10 marks sees how many they passed, the pass rate with its Wilson range
and the reasons they gave on the answers they failed. Nothing about an LLM-as-a-judge."""

from __future__ import annotations

import csv
import json
from collections import Counter

import pytest

from judgekeeper import find, no_grades, reasons, start, start_label
from judgekeeper.metrics import wilson
from tests.test_front import flat, run


def _rows(n: int) -> list[dict]:
    return [{"input": f"What is question {i}?", "output": f"This is answer number {i}."}
            for i in range(n)]


def write_answers(folder, n: int = 12, kind: str = "csv", name: str = "results",
                  grades: list[str] | None = None) -> str:
    rows = _rows(n)
    if grades is not None:
        rows = [{**r, "verdict": g} for r, g in zip(rows, grades, strict=True)]
    path = folder / f"{name}.{kind}"
    if kind == "jsonl":
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    else:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]),
                               delimiter="\t" if kind == "tsv" else ",")
            w.writeheader()
            w.writerows(rows)
    return path.name


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _session(here) -> start_label.StartSession:
    return start_label.StartSession(start_label.Workspace(here))


def mark(here, marks: list[str]) -> start_label.StartSession:
    """The first len(marks) answers in the page's order, marked so."""
    page = _session(here)
    for item, m in zip(page.items, marks, strict=False):
        page.update({"id": item["id"], "label": m, "seconds": 3})
    return page


# Finding and reading ----------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_a_file_with_input_and_output_only_is_read(here, kind):
    name = write_answers(here, 12, kind)
    assert find.classify_file(here / name) == "table"
    found = start.find_judge(here / name)
    assert found.graded is False
    assert len(found.pool.answers) == 12
    assert {a.verdict for a in found.pool.answers} == {None}
    assert found.pool.n_pass == found.pool.n_fail == 0


@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_a_folder_search_finds_it_when_it_is_all_there_is(here, kind):
    write_answers(here, 12, kind)
    found = start.find_judge(here)
    assert found.graded is False and len(found.pool.answers) == 12


def test_beside_results_with_grades_only_those_are_read(here):
    write_answers(here, 12, name="dataset")
    write_answers(here, 40, name="results", grades=["pass", "fail"] * 20)
    found = start.find_judge(here)
    assert found.graded is True
    assert [r.rel for r in found.results] == ["results.csv"]


def test_answers_tables_are_named_only_with_input_and_output():
    assert find.is_answers_table(["input", "output"])
    assert find.is_answers_table(["id", "input", "output", "reason"])
    assert not find.is_answers_table(["input", "output", "verdict"])  # a judge's results
    assert not find.is_answers_table(["input", "output", "score"])
    assert not find.is_answers_table(["question", "answer"])
    assert not find.is_answers_table(["input", "output_a", "output_b"])
    assert not find.is_answers_table(["input", "output", "label"])  # a labels file
    assert not find.is_answers_table(["input", "output", "human_label"])


def test_a_judge_column_by_another_name_is_not_answers_with_no_grade(here):
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "passed"])
        for i, r in enumerate(_rows(20)):
            w.writerow([r["input"], r["output"], "pass" if i % 2 else "fail"])
    assert not find.answers_only(here / "results.csv")
    assert find.classify_file(here / "results.csv") is None  # an own format, as before
    lines = [json.dumps({**r, "scores": {"helpful": {"verdict": "pass"}}}) for r in _rows(20)]
    (here / "evals.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not find.answers_only(here / "evals.jsonl")
    assert find.search(here).readable("table") == []


def test_a_file_with_grades_is_read_as_before(here, capsys, pages):
    write_answers(here, 40, grades=["pass", "fail"] * 20)
    found = start.find_judge(here / "results.csv")
    assert found.graded is True and found.pool.n_pass == 20
    _, out, _ = run(capsys, "--no-browser")
    assert "Your LLM-as-a-judge passed 20 answers and failed 20." in flat(out)
    data = start_label.Workspace(here).data()
    assert "graded" not in data and {q["group"] for q in data["queue"]} == {"pass", "fail"}


# The terminal -----------------------------------------------------------------------------

def test_the_first_run_finds_the_answers_and_opens_the_marking_page(here, capsys, pages):
    write_answers(here, 12)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    said = flat(out)
    assert "Step 1 of 5: Find" in said and "Step 2 of 5: Mark" in said
    assert "Answers: 12 answers" in said
    assert "question the input column" in said and "answer the output column" in said
    assert "LLM-as-a-judge" not in out
    assert "Mark each one Pass or Fail" in said
    data = start_label.Workspace(here).data()
    assert data["graded"] is False
    assert {q["group"] for q in data["queue"]} == {None}
    assert len(data["queue"]) == 12


@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_nine_marks_are_too_few(here, capsys, pages, kind):
    write_answers(here, 12, kind)
    run(capsys, "--no-browser")
    page = mark(here, ["pass"] * 6 + ["fail"] * 3)
    status = page.summary()["status"]
    assert status["first"] is False and status["ready"] is False
    assert status["text"] == "Mark a few more answers to see your result."
    _, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert "You marked 9 answers so far: 6 Pass, 3 Fail." in said
    assert "Mark a few more answers to see your result." in said
    assert "You passed" not in said and "LLM-as-a-judge" not in out


@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_ten_marks_give_a_result(here, capsys, pages, kind):
    write_answers(here, 12, kind)
    run(capsys, "--no-browser")
    page = mark(here, ["pass"] * 6 + ["fail"] * 4)
    status = page.summary()["status"]
    assert status["first"] and status["ready"]
    assert status["headline"] == "You passed 6 of 10 answers."
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    said = flat(out)
    assert "Step 3 of 5: Measure" in said
    assert "You passed 6 of 10 answers." in said
    assert "LLM-as-a-judge" not in out
    for word in ("TPR", "TNR", "Kappa", "kappa", "kept aside", "fix"):
        assert word not in out, word
    r = json.loads(start_label.Workspace(here).result_json.read_text(encoding="utf-8"))
    w = wilson(6, 10)
    assert r["graded"] is False
    assert r["pass_rate"] == pytest.approx(0.6)
    assert r["pass_rate_interval"] == pytest.approx([w["lo"], w["hi"]])
    assert no_grades.rate_words(r) == "about 60%, between 31% and 83%"


@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_thirty_of_thirty_still_has_a_range(here, capsys, pages, kind):
    write_answers(here, 30, kind)
    run(capsys, "--no-browser")
    page = mark(here, ["pass"] * 18 + ["fail"] * 12)
    r = no_grades.compute(start_label.Workspace(here), page)
    assert r["left"] == 0
    assert no_grades.rate_words(r) == "about 60%, between 42% and 75%"
    _, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert "You passed 18 of 30 answers." in said
    assert "every answer" not in said.split("You passed")[1]  # no "exact" note


def test_the_result_has_no_judge_numbers_and_lists_only_the_fails(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    page = mark(here, ["pass", "fail"] * 6)
    r = no_grades.compute(start_label.Workspace(here), page)
    for key in ("tpr", "tnr", "kappa", "tpr_interval", "tnr_interval", "verdict"):
        assert key not in r, key
    fails = {i["id"] for i in page.items if i["label"] == "fail"}
    assert set(r["fails"]) == fails and len(r["fails"]) == 6


def test_the_range_is_wilson_on_the_marked_answers():
    for k, n in ((6, 10), (18, 30), (30, 30), (0, 10)):
        r = no_grades.numbers(k, n)
        w = wilson(k, n)
        assert r["pass_rate_interval"] == pytest.approx([w["lo"], w["hi"]])
        assert r["check"] == "result"
    assert no_grades.numbers(6, 9)["check"] == "too_few"
    assert no_grades.numbers(6, 9)["pass_rate"] is None


# Reasons ----------------------------------------------------------------------------------

def test_only_the_reasons_about_the_answer_are_offered():
    assert no_grades.offered() == ["wrong_fact", "no_answer", "left_out", "unsafe",
                                   "format_tone", "unsure"]
    words = [reasons.REASONS[k][0] for k in no_grades.offered()]
    for hidden in ("worded_differently", "small_slips", "short_ok", "not_asked",
                   "rule_silent"):
        assert reasons.REASONS[hidden][0] not in words


def _with_result(here, capsys, marks):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, marks)
    run(capsys, "--no-browser")  # the result is saved
    return _session(here)


def test_reasons_are_taken_on_fail_marks_once_there_is_a_result(here, capsys, pages):
    page = _with_result(here, capsys, ["pass", "fail"] * 5)
    by = {i["label"]: i["id"] for i in page.items if i["label"]}
    page.update({"id": by["fail"], "reasons": ["wrong_fact"]})
    with pytest.raises(ValueError):  # a Pass mark has no reasons
        page.update({"id": by["pass"], "reasons": ["wrong_fact"]})
    with pytest.raises(ValueError):  # a reason about an LLM-as-a-judge
        page.update({"id": by["fail"], "reasons": ["worded_differently"]})
    with pytest.raises(ValueError):
        page.update({"id": by["fail"], "reasons": ["rule_silent"]})


def test_no_reasons_before_a_result(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    page = mark(here, ["fail"] * 5)
    with pytest.raises(ValueError):
        page.update({"id": page.items[0]["id"], "reasons": ["wrong_fact"]})


def test_the_fail_list_and_the_terminal_follow_the_reason_counts(here, capsys, pages):
    page = _with_result(here, capsys, ["fail"] * 8 + ["pass"] * 2)
    fails = [i["id"] for i in page.items if i["label"] == "fail"]
    given = {fails[0]: ["left_out"], fails[1]: ["wrong_fact"], fails[2]: ["wrong_fact"],
             fails[3]: ["left_out", "wrong_fact"], fails[4]: ["wrong_fact"],
             fails[5]: ["unsure"], fails[6]: ["left_out"]}  # fails[7]: none
    for i, why in given.items():
        page.update({"id": i, "reasons": why})
    r = no_grades.compute(start_label.Workspace(here), _session(here))
    rows = [{"reasons": why} for why in given.values()]
    tally = reasons.tally(rows)
    assert tally == Counter({"wrong_fact": 4, "left_out": 3})
    # the most common reason first, no reason (or only "not sure") last
    assert r["fails"][:4] == [fails[1], fails[2], fails[3], fails[4]]
    assert r["fails"][4:6] == [fails[0], fails[6]]
    assert set(r["fails"][6:]) == {fails[5], fails[7]}
    line = "Your reasons: It has a wrong fact (4), It leaves out something important (3)."
    assert no_grades.reasons_line(rows) == line
    _, out, _ = run(capsys, "--no-browser")
    assert line in flat(out)


def test_no_reasons_line_without_reasons(here, capsys, pages):
    _with_result(here, capsys, ["fail"] * 5 + ["pass"] * 5)
    _, out, _ = run(capsys, "--no-browser")
    assert "Your reasons" not in out
    assert no_grades.reasons_line([]) is None


# Grades added later ---------------------------------------------------------------------

def test_adding_a_grade_column_later_keeps_the_marks(here, capsys, pages):
    write_answers(here, 40)
    run(capsys, "--no-browser")
    page = mark(here, ["pass", "fail"] * 6)
    marked = page.marked()
    write_answers(here, 40, grades=["pass", "pass", "fail", "fail"] * 10)
    code, out, err = run(capsys, "--no-browser")
    assert code in (0, 3), out + err
    data = start_label.Workspace(here).data()
    assert "graded" not in data and data["metric"] == "verdict"
    assert _session(here).marked() == marked  # nothing to mark again
    assert "You marked 12 answers so far" in flat(out)
    assert "previous-" not in out  # nothing moved aside


def test_mark_with_every_answer_marked_says_so(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 8 + ["fail"] * 4)
    code, out, _ = run(capsys, "mark", "--no-browser")
    said = flat(out)
    assert code == 0
    assert "You have marked all 12 answers." in said
    assert "To change a mark, click it in the list." in said
    assert "makes your numbers more precise" not in said


@pytest.mark.parametrize("command", ["check", "fix"])
def test_check_and_fix_say_there_is_no_llm_as_a_judge(here, capsys, pages, command):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 8 + ["fail"] * 4)
    code, out, err = run(capsys, command)
    said = flat(out + err)
    assert code == 3, said
    assert "Your answers have no grades, so there is no LLM-as-a-judge to" in said
    assert "Traceback" not in said and "error:" not in said
    assert "Your marks are kept." in said


def test_labels_brought_with_labels_count_as_marks(here, capsys, pages):
    write_answers(here, 12)
    with (here / "mylabels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "label"])
        for i, r in enumerate(_rows(11)):
            w.writerow([r["input"], r["output"], "fail" if i % 3 == 0 else "pass"])
    code, out, err = run(capsys, "--labels", "mylabels.csv", "--no-browser")
    said = flat(out)
    assert code == 0, out + err
    assert "File: results.csv" in said  # never the labels file
    assert "Added 11 marks from mylabels.csv (7 Pass, 4 Fail)." in said
    assert "You passed 7 of 11 answers." in said


def test_every_answer_marked_under_ten_asks_for_more_answers(here, capsys, pages):
    write_answers(here, 9)
    run(capsys, "--no-browser")
    page = mark(here, ["pass"] * 6 + ["fail"] * 3)
    done = page.summary()["status"]["done"]
    line = ("Next: add more answers to results.csv (at least 10 in all), then run "
            "`judgekeeper` again.")
    assert done[1] == line
    code, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert code == 3
    assert ("You've marked every answer: 6 Pass, 3 Fail. Mark a few more answers to "
            "see your result.") in said
    assert line in said
    assert "your eval" not in said
