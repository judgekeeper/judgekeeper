"""What the stress test found: the marking page works the result out once per change, not per
request; big Inspect logs are read sample by sample; one failed judge call costs only its own
answer and its text is never shown; `check` says what it could not re-check; a body far too
large gets its 413. Small made-up projects: each test asserts on how the work is done."""

from __future__ import annotations

import json

from judgekeeper import marks, start, start_label, weighted
from judgekeeper.start_label import StartSession
from tests.start_projects import table_project


def _quiet(*args, **kwargs):
    pass


def _page(tmp_path, n=40):
    table_project(tmp_path, [i % 3 != 0 for i in range(n)], model="gpt-4.1")
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    return ws, StartSession(ws)


def _counting(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


# 1. The marking page --------------------------------------------------------------------------

def test_the_ranges_are_drawn_once_per_change_not_per_request(tmp_path, monkeypatch):
    ws, session = _page(tmp_path, n=60)
    queue = ws.data()["queue"]
    for n, q in enumerate(queue[:32]):  # past the count rule: the status draws ranges
        session.update({"id": q["id"], "label": ("pass", "fail")[n % 2]})
    draws = _counting(monkeypatch, weighted, "stratified")
    for _ in range(5):  # GET /state, GET / and the status a POST answers with
        session.state()
        session.summary()
    assert len(draws) == 1
    session.update({"id": queue[32]["id"], "label": "pass"})
    session.summary()
    session.state()
    assert len(draws) == 2


def test_no_range_is_drawn_before_there_are_enough_marks(tmp_path, monkeypatch):
    ws, session = _page(tmp_path)
    draws = _counting(monkeypatch, weighted, "stratified")
    for q in ws.data()["queue"][:4]:
        session.update({"id": q["id"], "label": "pass"})
        before = session.summary()["status"]
    assert draws == []
    assert before == {"text": start_label.VERDICTS[None], "ready": False}


def test_start_json_is_read_once_while_it_does_not_change(tmp_path, monkeypatch):
    ws, session = _page(tmp_path)
    queue = ws.data()["queue"]
    loads = _counting(monkeypatch, start_label, "_load_start")
    for q in queue[:6]:
        session.update({"id": q["id"], "label": q["group"]})
        session.summary()
        session.state()
    assert len(loads) <= 1
    data = ws.data()
    data["description"] = "changed on disk"
    ws.start.write_text(json.dumps(data), encoding="utf-8")
    session.summary()
    assert len(loads) == 2


def test_marks_another_process_wrote_are_seen(tmp_path):
    ws, session = _page(tmp_path)
    queue = ws.data()["queue"]
    session.update({"id": queue[0]["id"], "label": "pass"})
    other = StartSession(ws)  # a second page or run on the same folder
    other.update({"id": queue[1]["id"], "label": "fail"})
    session.update({"id": queue[2]["id"], "label": "pass"})
    assert session.marked() == {queue[0]["id"]: "pass", queue[1]["id"]: "fail",
                                queue[2]["id"]: "pass"}
    assert marks.read(ws.marks).counted() == session.marked()


def test_the_marks_file_is_parsed_again_only_when_it_changed(tmp_path, monkeypatch):
    ws, session = _page(tmp_path)
    queue = ws.data()["queue"]
    session.update({"id": queue[0]["id"], "label": "pass"})
    reads = _counting(monkeypatch, marks, "read")
    session.state()
    session.summary()
    session.update({"id": queue[1]["id"], "label": "pass"})  # its own line: no read needed
    assert reads == []
    with ws.marks.open("a", encoding="utf-8") as f:  # another program adds a line
        f.write(json.dumps(marks.stamp(queue[2]["id"], "fail", queue[2]["group"], None,
                                       marks.new_sitting())) + "\n")
    session.update({"id": queue[3]["id"], "label": "pass"})
    assert len(reads) == 1 and session.marked()[queue[2]["id"]] == "fail"


def test_the_result_page_reads_each_pool_file_once(tmp_path, monkeypatch):
    from judgekeeper import fix

    ws, session = _page(tmp_path, n=60)
    for q in ws.data()["queue"][:40]:
        session.update({"id": q["id"], "label": q["group"]})
    start_label.live_result(ws, session)
    runs = _counting(monkeypatch, fix, "read_run")
    start_label.live_result(ws, session)
    start_label.live_result(ws, session)
    assert runs == []  # the judge's grades are parsed again only when the file changes
