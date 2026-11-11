"""Answers whose output is a JSON object (such as {"reply", "booked", "date"}), with no grades:
every place that turns an answer into text uses the text the marking page shows for it, so a
Fail mark never stops the result, failed-answers.md or what changed since the last answers."""

from __future__ import annotations

import json

import pytest

from judgekeeper import no_grades, start_label
from tests.test_answers_without_grades import _live, _session
from tests.test_front import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(here, take: int = 1) -> None:
    rows = [{"input": f"Book a table on day {i}.",
             "output": {"reply": f"Booked day {i}, take {take}.", "booked": i % 2 == 0,
                        "date": f"2026-11-{i + 1:02d}"}} for i in range(30)]
    (here / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                        encoding="utf-8")


def _mark(here, fails: set[int]) -> start_label.StartSession:
    page = _session(here)
    for item in page.items:
        if not item["label"]:
            day = int(page.raw[item["id"]]["input"].split()[-1].rstrip("."))
            page.update({"id": item["id"], "label": "fail" if day in fails else "pass",
                         "seconds": 3})
    return page


def test_json_answers_with_fails_give_the_result_failed_answers_and_what_changed(
        here, capsys, pages):
    _write(here)
    run(capsys, "--no-browser")
    page = _mark(here, {0, 1, 2, 3, 4})  # 25 Pass, 5 Fail
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    assert "You passed 25 of 30 answers." in flat(out)
    html = _live(here, page)
    assert "reply: Booked day" in html
    ws = start_label.Workspace(here)
    failed = no_grades.failed_path(ws)
    assert no_grades.has_failed(ws)
    text = failed.read_text(encoding="utf-8")
    assert "reply: Booked day" in text and "{'reply'" not in text
    _write(here, take=2)
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    _mark(here, set())
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    said = flat(out)
    assert "kept aside: fixed" in said, said
