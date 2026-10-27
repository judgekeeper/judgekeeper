"""The result made from marks.jsonl: how the marks were made, the smallest drop the set can
see (both kept in result.json), report.html, and one history.jsonl line per new set of marks."""

from __future__ import annotations

import json

import pytest

from judgekeeper import marks, start, start_label
from tests.start_projects import promptfoo_project, save_result, split


@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(20, 20), tag=" SECRET-TEXT")
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


def _mark(ws, n=None, seconds=9):
    """Mark the first n answers (default: all) as the judge did."""
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:n]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": seconds})
    return start_label.StartSession(ws)


def _history(ws):
    path = ws.dir / "history.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] \
        if path.is_file() else []


# How the marks were made ----------------------------------------------------------------

def test_the_marks_line():
    made = {"marks": 32, "pass": 16, "fail": 16, "sittings": 1, "seconds": 9,
            "under_second": 0, "not_counted": 0}
    assert start_label.made_lines(made) == [
        ("Your marks: 32 (16 Pass, 16 Fail), made on the page in 1 sitting, about 9 seconds "
         "each.")]
    made.update(sittings=2, seconds=1)
    assert start_label.made_lines(made)[0].endswith("in 2 sittings, about 1 second each.")
    made.update(seconds=None)
    assert start_label.made_lines(made)[0].endswith("made on the page in 2 sittings.")


def test_quick_marks_are_said_when_more_than_a_quarter():
    made = {"marks": 32, "pass": 16, "fail": 16, "sittings": 1, "seconds": 2,
            "under_second": 8, "not_counted": 0}
    assert len(start_label.made_lines(made)) == 1  # a quarter: not said
    made["under_second"] = 9
    assert start_label.made_lines(made)[1] == ("9 of your marks took under a second each. A result is "
                                        "only as good as the marks.")


def test_lines_not_made_on_the_page_are_said():
    made = {"marks": 30, "pass": 15, "fail": 15, "sittings": 1, "seconds": 4,
            "under_second": 0, "not_counted": 2}
    assert start_label.made_lines(made)[-1] == ("2 lines in marks.jsonl were not made on the page and "
                                         "are not counted.")


def test_marks_made_through_a_printed_link_are_said(ws):
    session = start_label.StartSession(ws)
    session.link = "printed"
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items[:3]:
        session.update({"id": item["id"], "label": groups[item["id"]], "seconds": 4})
    made = marks.made(marks.read(ws.marks))
    assert made["printed"] == 3
    assert start_label.made_lines(made)[-1] == (
        "3 of your marks came through a link printed in a terminal, so another program on this "
        "computer could have made them. If you marked them yourself, nothing to do.")
    made["printed"] = 1
    assert start_label.made_lines(made)[-1] == (
        "1 of your marks came through a link printed in a terminal, so another program on this "
        "computer could have made it. If you marked it yourself, nothing to do.")


def test_the_result_keeps_how_the_marks_were_made_and_the_smallest_drop(ws):
    r = save_result(ws, _mark(ws, seconds=0.5), say=lambda line: None)
    assert r["made"] == {"marks": 40, "pass": 20, "fail": 20, "sittings": 1, "seconds": 0,
                         "under_second": 40, "not_counted": 0, "printed": 0, "browser_env": 0, "unsure": 0,
                         "after_result": 0}
    assert r["smallest_drop"] == 25


def test_no_smallest_drop_under_fifteen_of_each(ws):
    r = save_result(ws, _mark(ws, n=20), say=lambda line: None)
    assert r["smallest_drop"] is None


def test_the_report_page_shows_neither_line_and_the_result_keeps_both(ws):
    r = save_result(ws, _mark(ws), say=lambda line: None)
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert start_label.made_lines(saved["made"])[0] == (
        "Your marks: 40 (20 Pass, 20 Fail), made on the page in 1 sitting, about 9 seconds "
        "each.")
    assert saved["smallest_drop"] == r["smallest_drop"] == 25
    page = (ws.dir / "report.html").read_text(encoding="utf-8")
    for gone in ("Your marks:", "can see a drop", "result.html"):  # not on the page
        assert gone not in page, gone


def test_report_html_replaces_result_html(ws):
    (ws.dir / "result.html").write_text("<p>old</p>", encoding="utf-8")
    save_result(ws, _mark(ws), say=lambda line: None)
    assert (ws.dir / "report.html").is_file()
    assert not (ws.dir / "result.html").exists()


# history.jsonl ----------------------------------------------------------------------------

def test_one_history_line_per_new_set_of_marks(ws):
    session = _mark(ws, n=34)
    save_result(ws, session, say=lambda line: None)
    save_result(ws, start_label.StartSession(ws), say=lambda line: None)
    assert len(_history(ws)) == 1
    save_result(ws, _mark(ws), say=lambda line: None)
    first, second = _history(ws)
    assert (first["marks"], second["marks"]) == (34, 40)
    assert second["kind"] == "result"
    assert second["judge"] == marks.read(ws.marks).header["judge"]
    assert (second["pass"], second["fail"]) == (20, 20)
    assert set(second["tpr"]) == {"value", "low", "high"}
    assert set(second["tnr"]) == {"value", "low", "high"}
    assert second["smallest_drop"] == 25 and second["marks_hash"] != first["marks_hash"]
    assert isinstance(second["kappa"], float) and second["time"].endswith("Z")


def test_no_answer_text_or_ids_in_the_history(ws):
    save_result(ws, _mark(ws), say=lambda line: None)
    text = (ws.dir / "history.jsonl").read_text(encoding="utf-8")
    assert "SECRET-TEXT" not in text and "Question" not in text
    for q in ws.data()["queue"]:
        assert q["id"] not in text


# Before a result: nothing on the page tells the LLM-as-a-judge's grade ------------------------

def test_a_mark_taken_back_below_a_result_takes_the_saved_result_back(ws, monkeypatch, capsys):
    """15 Pass and 15 Fail that read "needs work" on /result, then one mark taken back: the
    next run has no result to measure, and report.html and result.json say so."""
    from judgekeeper.cli import main
    from tests.test_fix import closed

    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for want in ("pass", "fail"):  # the person and the LLM-as-a-judge disagree on 8 of each 15
        for k, item in enumerate([i for i in session.items if groups[i["id"]] == want][:15]):
            other = "fail" if want == "pass" else "pass"
            session.update({"id": item["id"], "label": other if k < 8 else want, "seconds": 5})
    start_label.live_result(ws, session)
    assert json.loads(ws.result_json.read_text(encoding="utf-8"))["verdict_level"] == "not_gate"
    session.update({"id": next(iter(session.marked())), "label": None, "seconds": 1})
    monkeypatch.chdir(ws.root)
    assert main(["--no-browser"]) == 0
    closed(ws)
    capsys.readouterr()
    saved = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert saved["check"] == "too_few" and saved["labels"]["correct"] + saved["labels"]["wrong"] == 29
    page = ws.report_html.read_text(encoding="utf-8")
    assert "needs work" not in page and start_label.VERDICTS[None] in page


def test_grades_are_seen_only_when_the_page_lists_a_disagreement(ws):
    """/result before a result (10 Pass and 10 Fail, 3 of each the other way): the page lists
    no disagreement, so no change later is said to follow the grades, and none is kept aside."""
    from judgekeeper import reasons
    from tests.test_product_pages import _text

    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for want in ("pass", "fail"):
        for k, item in enumerate([i for i in session.items if groups[i["id"]] == want][:10]):
            other = "fail" if want == "pass" else "pass"
            session.update({"id": item["id"], "label": other if k < 3 else want, "seconds": 5})
    page = _text(start_label.live_result(ws, session))
    assert "your LLM-as-a-judge said" not in page  # no disagreement listed
    assert not reasons.grades_shown(ws) and not (ws.dir / "fix" / "split.json").exists()


def test_marking_an_answer_and_taking_it_back_shows_nothing_of_its_grade(ws):
    """Mark the next answer Pass, read /result, take the mark back: the page reads the same
    for an answer the LLM-as-a-judge passed as for one it failed."""
    from tests.test_product_pages import _text

    session = _mark(ws, 8)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    seen = {}
    for item in [i for i in session.items if not i["label"]][:10]:
        session.update({"id": item["id"], "label": "pass", "seconds": 3})
        seen.setdefault(groups[item["id"]], set()).add(
            _text(start_label.live_result(ws, session)))
        session.update({"id": item["id"], "label": None, "seconds": 1})
    assert set(seen) == {"pass", "fail"}  # both kinds were peeked at
    assert seen["pass"] == seen["fail"] and len(seen["pass"]) == 1
    (text,) = seen["pass"]
    assert "Of those" not in text and "disagreed" not in text
    said = [i["label"] for i in session.items if i["label"]]  # the 8, as the page's order gave
    assert (f"You passed {said.count('pass') + 1} answers. You failed {said.count('fail')} "
            "answers.") in text
