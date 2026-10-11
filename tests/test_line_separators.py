"""Answers holding U+2028, U+2029 or U+0085, which text copied from web pages and PDFs often
has. JSON may hold them as they are, and `.judgekeeper/pool.jsonl` and `record()` files do;
every JSONL file is read by "\\n" only, so they stay inside their answer."""

from __future__ import annotations

import json

from judgekeeper import start, start_fix, start_label
from judgekeeper.again import AgainOptions, labeled_answers, make_plan
from judgekeeper.start_label import StartSession, save_result
from judgekeeper.start_review import ReviewSession
from judgekeeper.textio import jsonl_lines
from tests.start_projects import records_project, split
from tests.test_start_review import _reviewable, _second_look

SEPARATED = "Line one line two line three\u0085end."


def _quiet(line=""):
    pass


def test_jsonl_lines_split_at_newlines_only():
    text = json.dumps({"a": SEPARATED}, ensure_ascii=False) + "\r\n" + '{"b": 1}\n'
    assert jsonl_lines(text) == [json.dumps({"a": SEPARATED}, ensure_ascii=False), '{"b": 1}', ""]
    assert len(text.splitlines()) == 5  # what went wrong before


def test_an_answer_with_line_separators_goes_through_every_step(tmp_path):
    outputs = [f"Answer {i}. {SEPARATED}" for i in range(36)]
    ws, _ = _reviewable(tmp_path, outputs=outputs)  # start, marks and the result
    assert " " in ws.pool.read_text(encoding="utf-8")  # written as it is
    session = StartSession(ws)
    assert sorted(r["output"] for r in session.raw.values()) == sorted(outputs)

    review = ReviewSession(ws)
    _second_look(review)
    for item in review.items:
        if item["disagreement"]:
            review.update({"id": item["id"], "choice": "judge_wrong"})
    assert all(r["output"] in outputs for r in review.raw.values())
    mistakes = (ws.dir / "judge-mistakes.csv").read_text(encoding="utf-8")
    assert SEPARATED in mistakes

    fix = start_fix.Fix(ws)
    fix.write_patterns()
    assert fix.state()["lists"]
    assert SEPARATED in fix.prompt()

    assert sorted(a["output"] for a in labeled_answers(ws)) == sorted(outputs)
    assert make_plan(ws, AgainOptions(), dry=False).status != "cant"


def test_record_files_with_line_separators_are_read(tmp_path):
    path = records_project(tmp_path, split(20, 16), tag=" " + SEPARATED)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")  # as record() writes them
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    session = StartSession(ws)
    assert all(r["output"].endswith(SEPARATED) for r in session.raw.values())
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    assert json.loads(ws.result_json.read_text(encoding="utf-8"))
