"""Marks brought with --labels, checked against the marks made on the page.

- The gate: with imported marks, no coloured verdict (good enough / needs work) until there
  are 15 page marks in each of the LLM-as-a-judge's groups (passed, failed), or no answer left
  to mark in that group. The numbers still show.
- The check: once there are 15 page marks in each group, Fisher's exact test (two-sided) per
  group on the share marked Pass, imported against page marks. p < 0.025 in either group: a
  warning, never a stop.
No test calls an AI API.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import labels, start_label
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer
from tests.test_labels_import import flat, here, run, table, write_labels  # noqa: F401

GATE = ("Mark at least {n} more answers on the page to check the marks from {name}. Until "
        "then, it's too early to tell.")
OFF = ("Your marks from {name} don't look like your marks on the page. Of the answers your "
       "LLM-as-a-judge {did}, you passed {x}% of those from {name} and {y}% of those you "
       "marked on the page. The numbers may be off.")


# Fisher's exact test -------------------------------------------------------------------------

def test_fishers_exact_test_matches_the_textbook():
    # Fisher's tea tasting table and a lopsided one; two-sided p as R's fisher.test gives it
    assert labels.fisher_p(3, 1, 1, 3) == pytest.approx(0.4857143, abs=1e-6)
    assert labels.fisher_p(1, 9, 11, 3) == pytest.approx(0.002759456, abs=1e-8)
    assert labels.fisher_p(0, 0, 5, 5) == 1.0
    assert labels.fisher_p(10, 0, 0, 10) == pytest.approx(1.082509e-05, rel=1e-5)


def _counts(file_pass, page_pass, file_fail=None, page_fail=None):
    """{group: {"file": [Pass, Fail], "page": [Pass, Fail]}} with the same counts in both
    groups unless given."""
    file_fail = file_fail or file_pass
    page_fail = page_fail or page_pass
    return {"pass": {"file": list(file_pass), "page": list(page_pass)},
            "fail": {"file": list(file_fail), "page": list(page_fail)}}


def test_alike_marks_are_not_flagged():
    assert labels.looks_off(_counts((30, 10), (12, 4))) is None


def test_marks_unlike_the_page_are_flagged_with_their_shares():
    off = labels.looks_off(_counts((38, 2), (5, 10), (10, 30), (4, 12)))
    assert off == {"group": "pass", "file": 95, "page": 33}


def test_no_check_until_15_page_marks_in_each_group():
    assert labels.looks_off(_counts((38, 2), (5, 9), (10, 30), (4, 12))) is None  # 14
    assert labels.looks_off(_counts((38, 2), (5, 10), (10, 30), (4, 10))) is None


# The gate ------------------------------------------------------------------------------------

@pytest.mark.parametrize(("page", "left", "n"), [
    ({"pass": 15, "fail": 15}, {"pass": 40, "fail": 40}, 0),
    ({"pass": 10, "fail": 15}, {"pass": 40, "fail": 40}, 5),
    ({"pass": 0, "fail": 0}, {"pass": 40, "fail": 40}, 30),
    ({"pass": 10, "fail": 2}, {"pass": 3, "fail": 40}, 16),  # only 3 left to mark
    ({"pass": 10, "fail": 2}, {"pass": 0, "fail": 0}, 0),  # every answer marked: no dead end
])
def test_the_gate_counts_the_page_marks_still_needed(page, left, n):
    assert labels.still_needed(page, left) == n


# Through judgekeeper ---------------------------------------------------------------------------

def _ids(ws: Workspace) -> dict[str, str]:
    return {json.loads(x)["output"]: json.loads(x)["id"]
            for x in ws.pool.read_text(encoding="utf-8").splitlines() if x}


def _page(ws: Workspace, marks: dict[int, str]) -> None:
    rows, session = _ids(ws), StartSession(ws)
    for i, m in marks.items():
        session.update({"id": rows[answer(i)], "label": m, "seconds": 5})


def _result(ws: Workspace) -> dict:
    return json.loads(ws.result_json.read_text(encoding="utf-8"))


def _text(html: str) -> str:
    return flat(re.sub(r"<[^>]+>", " ", html)).replace("&#x27;", "'").replace(" .", ".")


def test_imported_marks_alone_show_numbers_and_say_too_early(here, capsys):  # noqa: F811
    table(here, 60, 60)  # the first 60 answers the LLM-as-a-judge passed
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    r = _result(ws)
    assert r["tpr"] is not None and r["tnr"] is not None  # numbers still show
    assert r["verdict_level"] == "too_early" and r["import_gate"] == 30
    line = GATE.format(n=30, name="mine.csv")
    assert line in flat(out)
    assert line in _text(ws.report_html.read_text(encoding="utf-8"))
    status = start_label.start_status(StartSession(ws))
    assert status["first"] and not status["ready"]  # the marking page: no "ready" either


def test_after_15_page_marks_in_each_group_the_verdict_is_as_usual(here, capsys):  # noqa: F811
    table(here, 60, 60)
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    _page(ws, {i: "pass" for i in range(20, 34)} | {i: "fail" for i in range(80, 95)})
    _, out = run(capsys)
    assert _result(ws)["import_gate"] == 1  # 14 in the pass group: one more
    assert GATE.format(n=1, name="mine.csv") in flat(out)
    _page(ws, {34: "pass"})
    _, out = run(capsys)
    r = _result(ws)
    assert "import_gate" not in r and r["verdict_level"] != "too_early"
    assert "on the page to check the marks" not in flat(out)


def test_an_imported_answer_marked_again_on_the_page_counts_as_a_page_mark(here, capsys):  # noqa: F811
    table(here, 60, 60)
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    _page(ws, {i: "pass" for i in range(5)})  # imported ones, marked on the page
    run(capsys)
    assert _result(ws)["import_gate"] == 25


def test_marks_unlike_the_page_marks_get_the_warning(here, capsys):  # noqa: F811
    table(here, 60, 60)
    rows = [{"answer": answer(i), "label": "pass"} for i in range(30)]  # every one Pass
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    page = {i: ("pass" if i < 35 else "fail") for i in range(30, 45)}  # 5 of 15 Pass
    page |= {i: "fail" for i in range(80, 95)}
    _page(ws, page)
    _, out = run(capsys)
    line = OFF.format(name="mine.csv", did="passed", x=100, y=33)
    assert line in flat(out)
    assert line in _text(ws.report_html.read_text(encoding="utf-8"))
    assert _result(ws)["imports_off"] == {"group": "pass", "file": 100, "page": 33}


def test_alike_marks_get_no_warning(here, capsys):  # noqa: F811
    table(here, 60, 60)
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    run(capsys, "--labels", "mine.csv")
    ws = Workspace(here)
    _page(ws, {i: "pass" for i in range(20, 35)} | {i: "fail" for i in range(80, 95)})
    _, out = run(capsys)
    assert "don't look like your marks" not in flat(out)
    assert "imports_off" not in _result(ws)


def test_mark_says_how_many_page_marks_the_imported_marks_still_need(here, capsys, pages):  # noqa: F811
    table(here, 60, 60)
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / "mine.csv", rows)
    run(capsys, "--labels", "mine.csv")
    _, out = run(capsys, "mark")
    assert "You have 40 marks so far: 20 Pass, 20 Fail." in out
    assert GATE.format(n=30, name="mine.csv") in flat(out)
    _page(Workspace(here), {i: "pass" for i in range(20, 35)} | {i: "fail" for i in range(80, 95)})
    _, out = run(capsys, "mark")
    assert "on the page to check the marks" not in flat(out)


def test_an_import_first_with_too_few_says_what_a_result_needs(here, capsys):  # noqa: F811
    table(here, 60, 60)  # nothing marked yet: the import comes first
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 78)]  # 18 it failed
    write_labels(here / "mine.csv", rows)
    _, out = run(capsys, "--labels", "mine.csv")
    said = flat(out)
    assert ("You have 38 marks so far: 20 Pass, 18 Fail. That's not enough for a result yet. "
            "A result needs at least 15 answers you mark Pass and 15 you mark Fail, and 20 marks "
            "on answers your LLM-as-a-judge passed and 20 on answers it failed (or all of them, "
            "when there are fewer).") in said


def test_mark_with_every_answer_marked_and_some_imported_says_marks_on_all(here, capsys, pages):  # noqa: F811
    table(here, 20, 16)
    write_labels(here / "mine.csv", [{"answer": answer(i), "label": "pass"} for i in range(10)])
    run(capsys, "--labels", "mine.csv")
    _page(Workspace(here), {i: ("pass" if i < 20 else "fail") for i in range(10, 36)})
    _, out = run(capsys, "mark")
    assert "You have marks on all 36 answers. There are no more to mark." in out
    assert "You have marked all" not in out


def test_a_long_file_name_can_wrap_on_the_result_page_and_report(here, capsys):  # noqa: F811
    table(here, 60, 60)
    name = "L" * 120 + "ラベル" * 14 + ".csv"  # 250 bytes, nowhere to break
    rows = [{"answer": answer(i), "label": "pass"} for i in range(20)]
    rows += [{"answer": answer(i), "label": "fail"} for i in range(60, 80)]
    write_labels(here / name, rows)
    run(capsys, "--labels", name)
    ws = Workspace(here)
    html = ws.report_html.read_text(encoding="utf-8")
    page = start_label.result_html(_result(ws), back="/?token=t")  # served by the marking page
    for doc in (html, page):
        assert re.search(r"\.file\s*\{[^}]*overflow-wrap:\s*anywhere", doc)
        assert doc.count(f'<span class="file">{name}</span>') >= 2  # the gate and where from
        assert name not in re.sub(r'<span class="file">[^<]*</span>', "", doc)
