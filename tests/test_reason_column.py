"""The disagreement tables' "Its reason" column: shown when an answer you marked has the
LLM-as-a-judge's reason ("No reason given" on a row without one), left out when none has."""

from __future__ import annotations

import re

import pytest

from judgekeeper import fix, start, start_label
from judgekeeper.start_label import StartSession
from tests.start_projects import split, table_project
from tests.test_product_pages import NOT_GATE_TNR, _mistakes, _result


def _no_reason(n_easy: int, n_strict: int) -> list[dict]:
    return [{**m, "reason": None} for m in _mistakes(n_easy, n_strict)]


@pytest.mark.parametrize("page", ["result page", "report.html"])
def test_with_no_reason_anywhere_there_is_no_reason_column(page):
    fixing = {"mistakes": _no_reason(2, 1), "reasons_given": False}
    html = start_label.result_html(_result(*NOT_GATE_TNR), fixing=fixing,
                                   back="/" if page == "result page" else None)
    assert "Its reason" not in html and "No reason given" not in html
    assert '<col class="c3">' not in html
    assert html.count('<table class="tbl no-reason"') == 2
    assert all(x == "2" for x in re.findall(r'<td colspan="(\d)" class="why-cell">', html))


def test_with_a_reason_somewhere_a_row_without_one_says_so():
    mistakes = _no_reason(2, 0) + _mistakes(0, 1)
    html = start_label.result_html(_result(*NOT_GATE_TNR),
                                   fixing={"mistakes": mistakes, "reasons_given": True})
    assert html.count('<th scope="col">Its reason</th>') == 2
    assert '<td data-label="Its reason">No reason given</td>' in html
    assert 'class="tbl no-reason"' not in html


def _marked_disagreements(root, monkeypatch, reasons: bool):
    monkeypatch.chdir(root)
    verdicts = split(40, 40)
    extra = {"reason": [f"because {i}" for i in range(80)]} if reasons else None
    table_project(root, verdicts, extra=extra)
    ws = start_label.prepare(start.find_judge(root), say=lambda line: None)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for n, item in enumerate(session.items[:60]):
        mark = groups[item["id"]]
        if n % 4 == 0:  # a disagreement
            mark = "fail" if mark == "pass" else "pass"
        session.update({"id": item["id"], "label": mark, "seconds": 4})
    return ws


@pytest.mark.parametrize("reasons", [False, True])
def test_the_disagreements_say_whether_any_marked_answer_has_a_reason(tmp_path, monkeypatch,
                                                                     reasons):
    ws = _marked_disagreements(tmp_path, monkeypatch, reasons)
    section = fix.report_section(ws)
    assert section and section["mistakes"], section
    assert section["reasons_given"] is reasons
