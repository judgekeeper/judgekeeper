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
    found = start.find_judge(here / name, answers=True)
    assert found.graded is False
    assert len(found.pool.answers) == 12
    assert {a.verdict for a in found.pool.answers} == {None}
    assert found.pool.n_pass == found.pool.n_fail == 0


@pytest.mark.parametrize("kind", ["csv", "tsv", "jsonl"])
def test_a_folder_search_finds_it_when_it_is_all_there_is(here, kind):
    write_answers(here, 12, kind)
    found = start.find_judge(here, answers=True)
    assert found.graded is False and len(found.pool.answers) == 12


def test_beside_results_with_grades_only_those_are_read(here):
    write_answers(here, 12, name="dataset")
    write_answers(here, 40, name="results", grades=["pass", "fail"] * 20)
    found = start.find_judge(here, answers=True)
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
    found = start.find_judge(here / "results.csv", answers=True)
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


@pytest.mark.parametrize("argv", [[], ["mark"]])
def test_every_answer_marked_with_a_result_asks_for_more_for_a_surer_number(here, capsys,
                                                                            pages, argv):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 8 + ["fail"] * 4)
    _, out, _ = run(capsys, *argv, "--no-browser")
    said = flat(out)
    assert ("Next: add more answers to results.csv for a surer number, then run "
            "`judgekeeper` again.") in said
    assert "your eval" not in said


def test_answers_left_after_a_result_say_mark_more(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 6 + ["fail"] * 4)
    _, out, _ = run(capsys, "--no-browser")
    assert "Next: run `judgekeeper mark --no-browser` to mark more answers." in flat(out)


# The result page --------------------------------------------------------------------------

BACK = "/?token=t"


def _live(here, page=None) -> str:
    ws = start_label.Workspace(here)
    return start_label.live_result(ws, page or _session(here), back=BACK)


def _report(here) -> str:
    return start_label.Workspace(here).report_html.read_text(encoding="utf-8")


def _row_ids(html: str) -> list[str]:
    import re

    return re.findall(r'<div class="why" data-id="([^"]+)"', html)


def _chips(html: str, item_id: str) -> list[str]:
    import re

    box = html.split(f'data-id="{item_id}"', 1)[1].split('<div class="why" ', 1)[0]
    return re.findall(r'data-reason="([^"]+)"', box)


def _seen(html: str) -> str:
    """The page as a person reads it: no style or script, no tags."""
    import re

    html = re.sub(r"<(style|script)\b.*?</\1>", "", html, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", " ", html)


JUDGE_WORDS = ("LLM-as-a-judge", "Kappa", "kappa", "When you say", "kept aside",
               "judgekeeper fix", "Its reason", "rule part")


def test_the_result_page_says_the_counts_and_the_range(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 6 + ["fail"] * 4)
    _, out, _ = run(capsys, "--no-browser")
    assert "Full report: .judgekeeper/report.html (open it in your browser)" in flat(out)
    for html in (_report(here), _live(here)):
        assert ('<h1 id="verdict-h" class="plain">You passed <b>6</b> of <b>10</b> answers.'
                "</h1>") in html
        assert "about </span>60%" in html and "between 31% and 83%" in html
        assert "Answers you failed" in html
        for word in JUDGE_WORDS:
            assert word not in _seen(html), word


def test_thirty_of_thirty_shows_the_range_on_the_page(here, capsys, pages):
    write_answers(here, 30)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 18 + ["fail"] * 12)
    run(capsys, "--no-browser")
    html = _report(here)
    assert "between 42% and 75%" in html
    assert "every answer, so" not in html  # no "exact" note


def test_the_page_lists_only_the_fails_in_reason_order(here, capsys, pages):
    page = _with_result(here, capsys, ["fail", "pass"] * 5)
    fails = [i["id"] for i in page.items if i["label"] == "fail"]
    page.update({"id": fails[3], "reasons": ["wrong_fact"]})
    page.update({"id": fails[1], "reasons": ["wrong_fact"]})
    page.update({"id": fails[4], "reasons": ["left_out"]})
    html = _live(here, page)
    assert _row_ids(html) == [fails[1], fails[3], fails[4], fails[0], fails[2]]
    assert html.count('class="add-reason sbtn"') == 5
    r = json.loads(start_label.Workspace(here).result_json.read_text(encoding="utf-8"))
    assert r["fails"] == _row_ids(html)


def test_the_page_offers_only_the_reasons_about_the_answer(here, capsys, pages):
    page = _with_result(here, capsys, ["fail", "pass"] * 5)
    fail = next(i["id"] for i in page.items if i["label"] == "fail")
    page.update({"id": fail, "note": "too long"})  # makes the person's own button
    html = _live(here, page)
    other = next(i for i in _row_ids(html) if i != fail)
    chips = _chips(html, other)
    assert chips[:6] == no_grades.offered()
    assert len(chips) == 7 and chips[6] not in reasons.REASONS  # the person's own
    assert "Other…" in html
    for hidden in ("worded_differently", "small_slips", "short_ok", "not_asked",
                   "rule_silent"):
        assert f'data-reason="{hidden}"' not in html


def test_marked_words_are_kept_on_a_fail(here, capsys, pages):
    page = _with_result(here, capsys, ["fail", "pass"] * 5)
    fail = next(i["id"] for i in page.items if i["label"] == "fail")
    page.update({"id": fail, "spans": [[0, 4]]})
    with pytest.raises(ValueError):
        page.update({"id": fail, "rule_parts": [1]})
    assert '<b class="hl">This</b>' in _live(here, _session(here))


def test_what_next_with_answers_left_links_back_to_marking(here, capsys, pages):
    _with_result(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    html = _live(here)
    assert f'<a href="{BACK}">Mark more answers for a surer number.</a>' in html
    assert "saved in this project's <code>.judgekeeper</code> folder" in html
    report = _report(here)
    assert "Mark more answers for a surer number." in report and BACK not in report
    assert "Run judgekeeper mark" in " ".join(_seen(report).split())


def test_what_next_with_every_answer_marked(here, capsys, pages):
    _with_result(here, capsys, ["pass"] * 8 + ["fail"] * 4)
    html = _live(here)
    assert "Mark more answers for a surer number." not in html
    assert ("Add more answers to results.csv for a surer number, then run judgekeeper "
            "again.") in " ".join(_seen(html).split())
    assert f'<a href="{BACK}">Change a mark</a>' in html


def test_under_ten_the_page_asks_for_more_marks(here, capsys, pages):
    write_answers(here, 12)
    run(capsys, "--no-browser")
    page = mark(here, ["pass"] * 5 + ["fail"] * 4)
    html = _live(here, page)
    assert start_label.VERDICTS[None] in html
    assert "You passed <b>" not in html and "Answers you failed" not in html
    assert not start_label.Workspace(here).result_json.exists()
    for word in JUDGE_WORDS:
        assert word not in _seen(html), word


def test_a_reason_makes_no_copy_in_history(here, capsys, pages):
    page = _with_result(here, capsys, ["fail", "pass"] * 5)
    fail = next(i["id"] for i in page.items if i["label"] == "fail")
    page.update({"id": fail, "reasons": ["wrong_fact"]})
    ws = start_label.Workspace(here)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["reasons"] == [["It has a wrong fact", 1]]
    assert not ws.history.exists() or not list(ws.history.glob("result-*.json"))
    page.update({"id": fail, "label": "pass", "seconds": 3})  # a mark changed: kept
    start_label.live_result(ws, _session(here), back=BACK)
    assert len(list(ws.history.glob("result-*.json"))) == 1


def test_a_note_over_several_lines_is_one_reason_on_one_line(here, capsys, pages):
    """A note sent with \n on one answer and \r\n on another: saved on one line each, one
    button, counted once with both answers, one line in the terminal."""
    page = _with_result(here, capsys, ["fail", "pass"] * 5)
    fails = [i["id"] for i in page.items if i["label"] == "fail"]
    page.update({"id": fails[0], "note": "Line one\nLine two\nLine three"})
    page.update({"id": fails[1], "note": "Line one\r\nLine two\r\nLine three"})
    ws = start_label.Workspace(here)
    m = __import__("judgekeeper.marks", fromlist=["read"]).read(ws.marks)
    assert {m.last[i]["note"] for i in fails[:2]} == {"Line one Line two Line three"}
    assert [c["text"] for c in reasons.own_chips(ws)] == ["Line one Line two Line three"]
    html = _live(here, _session(here))
    assert "Line one\n" not in html and "\r" not in html
    assert 'value="Line one Line two Line three"' in html
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["reasons"] == [["“Line one Line two Line three”", 2]]
    _, out, _ = run(capsys, "--no-browser")
    line = next(x for x in out.splitlines() if x.startswith("Your reasons:"))
    assert "Your reasons: “Line one Line two Line three” (2)." in flat(out)
    assert "Line one" in line  # the reason starts on the line it belongs to


def test_the_page_with_grades_keeps_its_style(here, capsys, pages):
    """The one-cell rule is this page's only: a result with grades is drawn as before."""
    from judgekeeper import report_page

    assert ".nums.one" not in report_page.STYLE
    _with_result(here, capsys, ["pass"] * 6 + ["fail"] * 4)
    assert ".nums.one" in _report(here)


# A file with no grades never takes the place of LLM-as-a-judge results ----------------------

def _own_format(folder):
    lines = [json.dumps({"id": f"r{i}", "input": f"Q{i}?", "output": f"A{i}",
                         "scores": {"helpful": {"verdict": "pass" if i % 3 else "fail"}}})
             for i in range(40)]
    (folder / "evals.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_own_format_results_beside_answers_with_no_grade_are_read(here, capsys, pages):
    _own_format(here)
    _, alone, _ = run(capsys, "--no-browser")
    write_answers(here, 12, name="dataset")
    assert find.search(here).readable("table") == []
    _, out, _ = run(capsys, "--no-browser")
    assert out == alone  # as with no answers file beside it
    assert "format of its own" in flat(out) and "dataset.csv" not in out


def test_a_deepeval_project_with_no_run_gives_the_deepeval_steps(here, capsys, pages):
    (here / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    write_answers(here, 12, name="dataset")
    assert find.search(here).readable("table") == []
    _, out, _ = run(capsys, "--no-browser")
    assert "DeepEval saves results only when" in flat(out)
    assert "Mark each one Pass or Fail" not in out


def test_results_in_a_project_below_are_named_not_the_answers_here(here, capsys, pages):
    below = here / "support-bot"
    below.mkdir()
    (below / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    write_answers(below, 40, grades=["pass", "fail"] * 20)
    write_answers(here, 12, name="dataset")
    assert [r.rel for r in find.search(here).readable("table")] == ["support-bot/results.csv"]
    _, out, _ = run(capsys, "--no-browser")
    assert "support-bot" in out and "dataset.csv" not in out


def test_results_in_the_project_above_are_read_not_the_answers_here(here, monkeypatch):
    (here / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    write_answers(here, 40, grades=["pass", "fail"] * 20)
    src = here / "src"
    src.mkdir()
    write_answers(src, 12, name="sample")
    assert find.search(src).readable("table") == []
    assert find.results_above(src) == here
    monkeypatch.chdir(src)
    found = start.find_judge(src, answers=True)
    assert found.graded is True


def test_answers_alone_never_make_a_folder_hold_results(here):
    for name in ("a", "b"):
        (here / name).mkdir()
        (here / name / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        write_answers(here / name, 12)
    assert find.nested_results(find.search(here)) == []
    src = here / "a" / "src"
    src.mkdir()
    assert find.results_above(src) is None


def test_new_answers_after_every_answer_was_marked_make_a_new_result(here, capsys, pages):
    """All 12 marked, then 10 answers added to the file: the result counts the answers left,
    so the terminal and the pages say to mark more, not to add answers or change a mark."""
    write_answers(here, 12)
    run(capsys, "--no-browser")
    mark(here, ["pass"] * 8 + ["fail"] * 4)
    run(capsys, "--no-browser")
    ws = start_label.Workspace(here)
    assert json.loads(ws.result_json.read_text(encoding="utf-8"))["left"] == 0
    write_answers(here, 22)  # the same 12 and 10 more
    _, out, _ = run(capsys, "--no-browser")
    said = flat(out)
    assert "You passed 8 of 12 answers." in said
    assert "Next: run `judgekeeper mark --no-browser` to mark more answers." in said
    assert "for a surer number, then run" not in said
    assert json.loads(ws.result_json.read_text(encoding="utf-8"))["left"] == 10
    report = _report(here)
    assert "Mark more answers for a surer number." in report and "Change a mark" not in report
    assert f'<a href="{BACK}">Mark more answers for a surer number.</a>' in _live(here)


GRADES_GONE = "results.csv needs input, output and a verdict or score column"


def test_check_and_fix_stop_when_the_results_lost_their_grades(here, capsys, pages):
    """Marks made on graded results, then the file has no grade column: `check` and `fix`
    stop with what the file needs, never read it as an LLM-as-a-judge with no grades."""
    write_answers(here, 40, grades=["pass", "fail"] * 20)
    run(capsys, "--no-browser")
    mark(here, ["pass", "fail"] * 15)
    write_answers(here, 40)  # the verdict column is gone
    code, out, err = run(capsys, "check")
    assert code != 0 and GRADES_GONE in flat(out + err), out + err
    assert "worse" not in out.lower()
    code, out, err = run(capsys, "check", "results.csv")
    assert code != 0 and GRADES_GONE in flat(out + err), out + err
    code, out, err = run(capsys, "fix")
    assert "didn't expect" not in out + err, out + err
    assert "Traceback" not in out + err


def test_check_and_fix_with_only_answers_with_no_grade_and_no_marks(here, capsys, pages):
    write_answers(here, 12)
    for command in ("check", "fix"):
        code, out, err = run(capsys, command)
        assert code != 0, out + err
        assert "didn't expect" not in out + err and "Traceback" not in out + err


@pytest.mark.parametrize("column", ["label", "human_label"])
def test_labels_in_the_answers_file_stop_with_a_question_as_before(here, capsys, pages,
                                                                     column):
    """A table of input, output and the person's labels, with --labels on it: not answers to
    mark (a labels column is never answers with no grade); as before, judgekeeper asks how
    to read it and stops, with no traceback."""
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", column])
        for i, r in enumerate(_rows(12)):
            w.writerow([r["input"], r["output"], "fail" if i % 3 == 0 else "pass"])
    assert not find.answers_only(here / "results.csv")
    code, out, err = run(capsys, "--labels", "results.csv", "--no-browser")
    assert code == 3, out + err
    assert "format of its own" in flat(out) and "Mark each one Pass or Fail" not in out
    assert "didn't expect" not in out + err
    assert not no_grades.here(start_label.Workspace(here))
