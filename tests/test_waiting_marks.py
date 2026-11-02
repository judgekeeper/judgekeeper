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
