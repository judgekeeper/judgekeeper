"""After `check` takes on a new rule that graded only some answers, a mark on an answer it has
not graded waits: it is kept, never counted as the new LLM-as-a-judge's grade, and counts once
`check` gets that judge's grade on it. Measure, the result page, report.html and the marking
page say how many wait and how to count them."""

from __future__ import annotations

import json

import pytest

import judgekeeper
from judgekeeper import check, recorder, start_label
from judgekeeper.start_label import StartSession, Workspace
from tests.test_earlier_grades import FIRST, LATER, WRONG, N, _mark, adopted, person
from tests.test_fix import closed
from tests.test_flow_across_runs import _jk, _rubric
from tests.test_front import flat

__all__ = ["adopted"]  # the fixture, used by name

WAIT = check.WAIT.format(k=len(LATER))


def _text(html: str) -> str:
    import html as html_mod
    import re

    return " ".join(html_mod.unescape(re.sub(r"<[^>]+>", "", html)).split())


def _result(ws: Workspace) -> dict:
    return start_label.compute(ws, StartSession(ws))


def test_the_old_rule_mistakes_on_later_marks_are_not_counted(adopted):
    """The first rule is wrong on 12 of the 20 marked later; the new one is right on every
    answer it graded. None of those 12 is the new rule's mistake."""
    ws, _ = adopted
    assert len(WRONG & set(LATER)) == 12
    r = _result(ws)
    assert r["waiting"] == len(LATER)
    assert r["disagreements"] == 0
    assert r["labels"]["correct"] + r["labels"]["wrong"] == len(FIRST)
    assert r["tpr"] == 1.0 and r["tnr"] == 1.0


def test_marks_made_after_the_change_wait_too(adopted):
    ws, _ = adopted
    lines = check.written_from_lines(ws)
    assert lines[0] == check.WRITTEN_FROM
    assert "On marks made after this change: none yet." in lines[1], lines
    assert not any("15 Pass" in x or "%" in x for x in lines), lines


def test_measure_says_how_many_wait_and_how_to_count_them(adopted):
    ws, capsys = adopted
    code, out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")  # the judge it took on
    closed(ws)
    said = flat(out)
    assert code == 0, out
    assert WAIT in said, out
    assert ("Next: grade all your answers with your new LLM-as-a-judge, then run "
            "`judgekeeper check <new results file>`.") in said, out
    assert "disagreed on 12" not in said and "On marks made after this change (" not in said
    assert WAIT in _text(ws.report_html.read_text(encoding="utf-8"))


def test_the_live_result_page_says_it(adopted):
    ws, _ = adopted
    text = _text(start_label.live_result(ws, StartSession(ws)))
    assert (f"{WAIT} To count them, grade all your answers with your new LLM-as-a-judge, then "
            "run judgekeeper check <new results file>.") in text, text


def test_the_live_page_names_the_program_as_it_runs_and_the_files_plainly(adopted,
                                                                          monkeypatch):
    from judgekeeper import textio

    ws, _ = adopted
    monkeypatch.setattr(textio, "_typed", "../tools/.venv/bin/judgekeeper")
    text = _text(start_label.live_result(ws, StartSession(ws)))
    assert "then run ../tools/.venv/bin/judgekeeper check <new results file>." in text, text
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["waiting_check"] == "judgekeeper check <new results file>"
    report = ws.report_html.read_text(encoding="utf-8")
    assert ".venv" not in report
    assert "then run judgekeeper check <new results file>." in _text(report)


def test_the_marking_page_says_it_once_in_its_status(adopted):
    ws, _ = adopted
    status = StartSession(ws).state()["status"]
    assert status["waiting"] == (f"{WAIT} To count them, grade all your answers with your new "
                                 "LLM-as-a-judge, then run `judgekeeper check <new results "
                                 "file>`.")


def test_the_marking_page_status_counts_as_the_result_does(adopted):
    """After `check` takes on a new rule, the page's ready box and headline come from the new
    LLM-as-a-judge's grades, as the result page's verdict does, never the old rule's."""
    ws, _ = adopted
    r = _result(ws)
    assert start_label.coloured(r), r["verdict"]
    status = StartSession(ws).state()["status"]
    assert (status["ready"], status["headline"]) == (True, r["verdict"]), status
    assert status["text"] == start_label.EVERY_MARKED and "done" not in status
    assert r["verdict"] in _text(start_label.live_result(ws, StartSession(ws)))


def test_with_no_mark_waiting_nothing_is_said(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(tmp_path, [i < 30 for i in range(N)], "V1 rule.")
    code, out = _jk(capsys, "--no-browser")
    assert code == 0, out
    ws = Workspace(tmp_path)
    closed(ws)
    _mark(ws, FIRST)
    assert "waiting" not in _result(ws)
    assert "waiting" not in StartSession(ws).state()["status"]
    assert check.WAIT.split("{k}")[1] not in flat(_jk(capsys, "--no-browser")[1])


def test_the_result_ready_box_never_fires_on_waiting_marks(adopted):
    """Counted alone, the marks give no result yet: the page says so, with no pop-up, even
    though all the marks together would."""
    ws, _ = adopted
    data = json.loads(ws.start.read_text(encoding="utf-8"))
    session = StartSession(ws)
    marked = [i["id"] for i in session.items if i["label"]]
    data["earlier_grades"] = marked[4:]  # only 4 marks have the judge's own grade
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    ws.ready_seen.unlink(missing_ok=True)
    session = StartSession(ws)
    state = session.state()
    assert state["status"]["ready"] is False and state["status"]["first"] is False
    assert state["counts"]["toward"] == {"correct": sum(
        session.marked()[i] == "pass" for i in marked[:4]), "wrong": sum(
        session.marked()[i] == "fail" for i in marked[:4])}
    assert not ws.ready_seen.is_file()


def test_grading_every_answer_then_check_counts_the_waiting_marks(adopted, tmp_path):
    ws, capsys = adopted
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="all.json")
    code, out = _jk(capsys, "check", "all.json")
    assert code == 0, out
    assert "earlier_grades" not in ws.data()
    r = _result(ws)
    assert "waiting" not in r
    assert r["labels"]["correct"] + r["labels"]["wrong"] == N
    assert r["disagreements"] == 0
    assert StartSession(ws).state()["status"].get("waiting") is None


@pytest.fixture
def records(tmp_path, monkeypatch, capsys):
    """judgekeeper.record() saves V1's grades on every answer; FIRST are marked, `fix` runs,
    the person grades only the marked answers with V2 (a new record run), `check` takes V2
    on, then LATER are marked."""
    monkeypatch.chdir(tmp_path)
    return adopt_records(tmp_path, monkeypatch, capsys), capsys


def adopt_records(tmp_path, monkeypatch, capsys) -> Workspace:
    """The `records` project, made in `tmp_path` (the folder this runs in)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "r"\nversion = "0"\n',
                                            encoding="utf-8")

    def run(rule, verdict, which, n):
        import os  # a new run of the program: a file of its own (record() names it by pid)

        monkeypatch.setattr(recorder, "_paths", {(os.getpid(), "Safe-wording"): tmp_path /
                                                 ".judgekeeper" / "records" / f"Safe-wording-{n}.jsonl"})
        for i in which:
            judgekeeper.record(input=f"Question {i}?", output=f"Answer {i}.",
                               verdict="pass" if verdict(i) else "fail", rule=rule,
                               judge="gpt-4o-mini", name="Safe wording")

    run("V1 rule.", lambda i: i < 30, range(N), 1)
    assert _jk(capsys, "--no-browser")[0] == 0
    ws = Workspace(tmp_path)
    closed(ws)
    _mark(ws, FIRST)
    assert _jk(capsys, "fix")[0] == 0
    run("V2 rule.", person, FIRST, 2)
    new = ".judgekeeper/records/Safe-wording-2.jsonl"
    _jk(capsys, "fix", new)  # as fix says to (the answers kept aside may hold no change)
    code, out = _jk(capsys, "check", new)
    assert code == 0, out
    closed(ws)
    _mark(ws, LATER)
    return ws


def test_records_marks_made_after_check_wait_too(records):
    ws, capsys = records
    assert sorted(ws.data()["earlier_grades"]) == sorted(_ids(ws, LATER))
    r = _result(ws)
    assert r["waiting"] == len(LATER) and r["disagreements"] == 0, r
    _, out = _jk(capsys, "--no-browser")
    assert WAIT in flat(out), out
    assert ("Next: grade all your answers with your new LLM-as-a-judge, then run "
            "`judgekeeper check .judgekeeper/records/<new file>`.") in flat(out), out
    assert "On marks made after this change (" not in out


def test_only_marks_with_the_judges_own_grade_are_graded(adopted):
    from judgekeeper import batches

    ws, _ = adopted
    session = StartSession(ws)
    graded = batches.graded(ws.data(), session.marked())
    assert sorted(graded) == sorted(_ids(ws, FIRST)) and len(session.marked()) == N


def _ids(ws: Workspace, which: list[int]) -> list[str]:
    import re

    session = StartSession(ws)
    return [item["id"] for item in session.items
            if int(re.search(r"Question (\d+)\?", json.dumps(session.raw[item["id"]]["input"]))[1])
            in which]


def test_a_plain_run_back_on_the_first_judge_counts_every_mark(adopted):
    """promptfoo's results.json still holds the first judge's grades on every answer: a plain
    run goes back to it, and its grades are the current judge's, so no mark waits."""
    ws, capsys = adopted
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    closed(ws)
    said = flat(out)
    assert code == 0, out
    assert "back to the one you marked with" in said, out
    assert check.WAIT.split("{k}")[1] not in said and "To count them" not in said, out
    r = _result(ws)
    assert "waiting" not in r and "earlier_grades" not in ws.data()
    assert r["labels"]["correct"] + r["labels"]["wrong"] == N
    assert r["disagreements"] == len(WRONG)  # the first judge's own mistakes, all counted


def test_the_wait_line_says_there_is_no_pass_or_fail_grade_yet():
    """An answer the new results hold with an error has a grade, but no Pass or Fail one."""
    assert check.WAIT.format(k=5) == ("5 of your marks wait: your new LLM-as-a-judge has no "
                                      "Pass or Fail grade on those answers yet.")


@pytest.fixture
def imported_wait(tmp_path, monkeypatch, capsys):
    """FIRST brought with --labels, V2 graded only those and `check` took it on, then 10 of
    LATER marked on the page: every answer left to mark is one V2 never graded."""
    monkeypatch.chdir(tmp_path)
    return _imported_wait(tmp_path, capsys), capsys


def _imported_wait(tmp_path, capsys, also: list[int] = (), page: int = 10,
                   said: list | None = None) -> Workspace:
    """`imported_wait`'s project; V2 grades the answers `also` too (none of them marked);
    `page`: how many of the others are marked on the page; `said` gets check's output."""
    from tests.start_projects import answer

    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    _rubric(tmp_path, [i < 30 for i in range(N)], "V1 rule.")
    (tmp_path / "labels.csv").write_text("output,label\n" + "".join(
        f"{answer(i)},{'pass' if person(i) else 'fail'}\n" for i in FIRST), encoding="utf-8")
    out = _jk(capsys, "--labels", "labels.csv", "--no-browser", "--port", "0")[1]
    assert f"Added {len(FIRST)} marks" in flat(out), out
    ws = Workspace(tmp_path)
    closed(ws)
    assert _jk(capsys, "fix")[0] == 0
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="v2.json",
            only=FIRST + list(also))
    _jk(capsys, "fix", "v2.json")
    code, out = _jk(capsys, "check", "v2.json")
    assert code == 0, out
    if said is not None:
        said.append(flat(out))
    _mark(ws, [i for i in LATER if i not in also][:page])
    return ws


def test_with_only_ungraded_answers_left_nothing_asks_for_more_marks(imported_wait):
    """No page mark can check the imported marks now: the result stays too early to tell (the
    check still holds), with no "mark more" line nor "keep marking"; the wait line and its
    Next are the step."""
    ws, capsys = imported_wait
    r = _result(ws)
    assert r["waiting"] == 10 and r["verdict_level"] == "too_early", r["verdict_level"]
    assert not r.get("import_gate") and r["only_wait"] is True
    code, out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")
    closed(ws)
    said = flat(out)
    assert code == 0 and "Result: too early to tell." in said, out
    assert "Mark at least" not in said and "mark more" not in said.lower(), out
    assert ("Next: grade all your answers with your new LLM-as-a-judge, then run "
            "`judgekeeper check <new results file>`.") in said, out
    for text in (_text(ws.report_html.read_text(encoding="utf-8")),
                 _text(start_label.live_result(ws, StartSession(ws), back="/"))):
        assert "Too early to tell" in text and check.WAIT.format(k=10) in text, text
        assert "Mark at least" not in text and "mark more" not in text.lower(), text
    status = StartSession(ws).state()["status"]
    assert status["only_wait"] is True and not status["ready"], status
    assert "keep marking" not in status["text"], status


NEXT_WAIT = ("Next: grade all your answers with your new LLM-as-a-judge, then run "
             "`judgekeeper check <new results file>`.")


def _no_mark_more(text: str) -> None:
    low = text.lower()
    for words in ("mark at least", "mark more answers", "keep marking", "marked every answer",
                  "run your eval on more questions", "result after every mark"):
        assert words not in low, (words, text)


def test_right_after_a_check_that_graded_only_the_marks_nothing_asks_for_marks(
        tmp_path, monkeypatch, capsys):
    """No mark waits yet, but every answer left to mark is one the new LLM-as-a-judge never
    graded: a mark there could only wait, so no line asks for one; the step is to grade every
    answer, then check."""
    monkeypatch.chdir(tmp_path)
    said = []
    ws = _imported_wait(tmp_path, capsys, page=0, said=said)
    _no_mark_more(said[0])
    assert "Next: grade all your answers with your new LLM-as-a-judge, then run" in said[0]
    r = _result(ws)
    assert "waiting" not in r and r["only_wait"] is True and not r.get("import_gate"), r
    code, out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")
    out += _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]  # the page open now
    closed(ws)
    text = flat(out)
    assert code == 0 and check.NO_GRADE_LEFT in text and NEXT_WAIT in text, out
    _no_mark_more(text)
    for page in (_text(ws.report_html.read_text(encoding="utf-8")),
                 _text(start_label.live_result(ws, StartSession(ws), back="/"))):
        assert check.NO_GRADE_LEFT in page, page
        _no_mark_more(page)
    status = StartSession(ws).state()["status"]
    assert status["only_wait"] is True and check.NO_GRADE_LEFT in status["waiting"], status
    _no_mark_more(status["text"])


def _mark_says(ws: Workspace, capsys) -> str:
    code, out = _jk(capsys, "mark", "v2.json", "--no-browser", "--port", "0")
    closed(ws)
    assert code == 0, out
    text = flat(out)
    _no_mark_more(text)
    assert "more precise" not in text and NEXT_WAIT in text, out
    return text


def test_mark_says_a_new_mark_can_only_wait(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ws = _imported_wait(tmp_path, capsys, page=0)
    assert check.NO_GRADE_LEFT in _mark_says(ws, capsys)


def test_mark_says_how_many_marks_wait(imported_wait):
    ws, capsys = imported_wait
    assert check.WAIT.format(k=10) in _mark_says(ws, capsys)


def test_mark_names_the_group_no_mark_can_move(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    ws = _imported_wait(tmp_path, capsys, also=[26, 27, 28, 29], page=0)
    assert check.NO_GRADE_IN.format(did="failed", name="labels.csv") in _mark_says(ws, capsys)


def test_while_only_marks_that_wait_are_left_the_open_page_asks_for_no_marks(imported_wait):
    """Measure never says "Mark more answers to make these ranges narrower" then."""
    ws, capsys = imported_wait
    out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]
    out += _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]
    closed(ws)
    assert "still open" not in flat(out) and NEXT_WAIT in flat(out), out
    _no_mark_more(flat(out))


def test_with_a_result_and_only_waiting_answers_left_nothing_asks_for_marks(
        tmp_path, monkeypatch, capsys):
    """Marked on the page, so the result is ready; 10 marks wait and every answer left is one
    the new LLM-as-a-judge never graded: no "still open… Mark more answers", no "Keep
    marking" nor "To mark more, run" in report.html."""
    from tests.test_earlier_grades import FIRST

    monkeypatch.chdir(tmp_path)
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n",
                                                  encoding="utf-8")
    _rubric(tmp_path, [i < 30 for i in range(N)], "V1 rule.")
    assert _jk(capsys, "--no-browser")[0] == 0
    ws = Workspace(tmp_path)
    closed(ws)
    _mark(ws, FIRST)
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="v2.json", only=FIRST)
    assert _jk(capsys, "check", "v2.json")[0] == 0
    _mark(ws, LATER[:10])
    out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]
    out += _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]  # the page open now
    closed(ws)
    r = _result(ws)
    assert r["verdict_level"] in ("gate", "not_gate") and r["only_wait"] is True, r
    text = flat(out)
    assert "still open" not in text and check.WAIT.format(k=10) in text, out
    _no_mark_more(text)
    report = _text(ws.report_html.read_text(encoding="utf-8"))
    assert "To mark more, run" not in report and "Keep marking" not in report, report


def test_every_answer_marked_and_some_waiting_say_only_the_wait(tmp_path, monkeypatch, capsys):
    """Every answer marked, then new results with an error on 5 marked answers: the marks are
    not too few and no eval run on more questions helps; the wait line and its Next are the
    step, in check, Measure and report.html."""
    from tests.start_projects import answer, question, table_project

    monkeypatch.chdir(tmp_path)
    verdicts = [i % 2 == 1 for i in range(80)]
    table_project(tmp_path, verdicts, model="bike-grader-v1")
    (tmp_path / "labels.csv").write_text("question,response,label\n" + "".join(
        f"{question(i)},{answer(i)},{'pass' if v == (i % 9 != 0) else 'fail'}\n"
        for i, v in enumerate(verdicts)), encoding="utf-8")
    assert _jk(capsys, "--labels", "labels.csv", "--no-browser", "--port", "0")[0] == 0
    ws = Workspace(tmp_path)
    closed(ws)
    table_project(tmp_path, ["error" if i < 5 else v for i, v in enumerate(verdicts)],
                  name="results-v2.csv", model="bike-grader-v2")
    code, out = _jk(capsys, "check", "results-v2.csv")
    assert code == 0, out
    _no_mark_more(flat(out))
    assert "Next: grade all your answers with your new LLM-as-a-judge, then run" in flat(out)
    code, out = _jk(capsys, "--no-browser", "--port", "0")
    closed(ws)
    text = flat(out)
    assert check.WAIT.format(k=5) in text and NEXT_WAIT.replace(
        "<new results file>", "results-v2.csv") in text or NEXT_WAIT in text, out
    _no_mark_more(text)
    _no_mark_more(_text(ws.report_html.read_text(encoding="utf-8")))
    code, out = _jk(capsys, "mark", "--no-browser", "--port", "0")  # every answer is marked
    closed(ws)
    text = flat(out)
    assert "You have marks on all 80 answers." in text and check.WAIT.format(k=5) in text, out
    assert NEXT_WAIT.replace("<new results file>", "results-v2.csv") in text or \
        NEXT_WAIT in text, out
    _no_mark_more(text)


def test_once_check_grades_the_waiting_answers_their_marks_count_toward_the_check(
        tmp_path, monkeypatch, capsys):
    """Every other answer marked on the page while it waits; then every answer graded by the
    new LLM-as-a-judge and `check`: those page marks count, the check is met and the verdict
    shows."""
    monkeypatch.chdir(tmp_path)
    ws = _imported_wait(tmp_path, capsys, page=len(LATER))
    assert _result(ws)["verdict_level"] == "too_early"
    _rubric(tmp_path, [person(i) for i in range(N)], "V2 rule.", name="all.json")
    code, out = _jk(capsys, "check", "all.json")
    assert code == 0, out
    r = _result(ws)
    assert "waiting" not in r and not r.get("import_gate"), r.get("import_gate")
    assert r["verdict_level"] in ("gate", "not_gate"), r["verdict_level"]


def test_a_group_whose_answers_left_all_wait_holds_the_check_and_is_named(
        tmp_path, monkeypatch, capsys):
    """V2 graded 3 answers no one marked, all in the group the first rule failed; every
    answer left in the group it passed waits. That group still needs page marks, so no page
    mark can finish the check of the imported marks: nothing asks for marks (no gate line),
    the line names the group, and the step is to grade every answer, then check."""
    monkeypatch.chdir(tmp_path)
    ws = _imported_wait(tmp_path, capsys, also=LATER[-3:])
    r = _result(ws)
    assert r["waiting"] == 10 and not r.get("import_gate"), r.get("import_gate")
    assert r["verdict_level"] == "too_early" and r["only_wait"] is True, r
    assert r["wait_group"] == "pass", r.get("wait_group")
    _says_the_group_waits(ws, capsys, "passed")


def test_a_group_left_with_only_waiting_answers_is_named_while_the_other_has_some(
        tmp_path, monkeypatch, capsys):
    """V2 graded 4 more answers the first rule passed; every answer left that it failed
    waits: marks on the 4 can't finish the check either."""
    monkeypatch.chdir(tmp_path)
    ws = _imported_wait(tmp_path, capsys, also=[26, 27, 28, 29], page=0)
    r = _result(ws)
    assert "waiting" not in r and not r.get("import_gate"), r.get("import_gate")
    assert r["only_wait"] is True and r["wait_group"] == "fail", r
    _says_the_group_waits(ws, capsys, "failed")


def _says_the_group_waits(ws: Workspace, capsys, did: str) -> None:
    line = check.NO_GRADE_IN.format(did=did, name="labels.csv")
    assert line == ("Your new LLM-as-a-judge has no Pass or Fail grade on the answers left that "
                    f"your old one {did}, so your marks from labels.csv can't be checked until "
                    "it grades them.")
    code, out = _jk(capsys, "v2.json", "--no-browser", "--port", "0")
    out += _jk(capsys, "v2.json", "--no-browser", "--port", "0")[1]  # the page open now
    closed(ws)
    text = flat(out)
    assert code == 0 and line in text and NEXT_WAIT in text, out
    assert check.NO_GRADE_LEFT not in text, out
    _no_mark_more(text)
    for page in (_text(ws.report_html.read_text(encoding="utf-8")),
                 _text(start_label.live_result(ws, StartSession(ws), back="/"))):
        assert line in page and check.NO_GRADE_LEFT not in page, page
        _no_mark_more(page)
    status = StartSession(ws).state()["status"]
    assert status["only_wait"] is True and line in status["waiting"], status
    _no_mark_more(status["text"])


def test_going_back_to_an_older_file_never_calls_it_the_newest(adopted):
    """After `check v2.json`, a plain run reads results.json again: older than v2.json, so it
    is not "the newest results here"."""
    ws, capsys = adopted
    said = flat(_jk(capsys, "--no-browser", "--port", "0")[1])
    closed(ws)
    assert "Reading results.json." in said and "the newest" not in said, said
