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


# 2. Inspect logs, sample by sample ------------------------------------------------------------

def _fake_inspect(monkeypatch, data, stream=True):
    """inspect_ai.log with read_eval_log (and, with `stream`, read_eval_log_samples) over the
    JSON log `data`; returns what was called."""
    import sys
    from types import ModuleType, SimpleNamespace

    calls = []

    def dumped(value):
        def model_dump(mode="json", include=None, exclude=None):
            out = dict(value)
            if include is not None:
                out = {k: ({kk: vv for kk, vv in v.items() if kk in include[k]}
                            if isinstance(include[k], dict | set) and isinstance(v, dict)
                            else v) for k, v in out.items() if k in include}
            for k in exclude or ():
                out.pop(k, None)
            return out
        return SimpleNamespace(model_dump=model_dump)

    def read_eval_log(path, header_only=False, **kwargs):
        calls.append(("read_eval_log", header_only))
        head = {k: v for k, v in data.items() if k != "samples" or not header_only}
        return dumped(head)

    def read_eval_log_samples(path, all_samples_required=True, **kwargs):
        calls.append(("read_eval_log_samples", all_samples_required))
        for s in data["samples"]:
            yield dumped(s)

    pkg, log_mod = ModuleType("inspect_ai"), ModuleType("inspect_ai.log")
    log_mod.read_eval_log = read_eval_log
    if stream:
        log_mod.read_eval_log_samples = read_eval_log_samples
    pkg.log, pkg.__version__ = log_mod, "0.3.200"
    monkeypatch.setitem(sys.modules, "inspect_ai", pkg)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_mod)
    return calls


def _log_data(n=30):
    from tests.start_projects import inspect_data

    data = inspect_data([i % 3 != 0 for i in range(n)])
    for s in data["samples"]:
        s["events"] = [{"event": "model", "output": "x" * 2000}]  # big, never used
        s["metadata"] = {"blob": "y" * 2000}
    return data


def test_an_eval_log_is_read_one_sample_at_a_time(tmp_path, monkeypatch):
    from judgekeeper.readers import inspect_logs

    data = _log_data()
    calls = _fake_inspect(monkeypatch, data)
    path = tmp_path / "logs" / "2026-10-21_qa.eval"
    path.parent.mkdir()
    path.write_bytes(b"PK zip")
    loaded = inspect_logs._load(path)
    assert ("read_eval_log", False) not in calls  # never the whole log at once
    assert calls == [("read_eval_log", True), ("read_eval_log_samples", False)]
    kept = set().union(*(s.keys() for s in loaded["samples"]))
    assert kept <= set(inspect_logs.SAMPLE_FIELDS) and "events" not in kept
    assert len(loaded["samples"]) == 30 and loaded["eval"] == data["eval"]
    json_path = tmp_path / "log.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.delitem(__import__("sys").modules, "inspect_ai.log")
    monkeypatch.setitem(__import__("sys").modules, "inspect_ai", None)
    same = [(r.target_id, r.name, r.label, r.run) for r in inspect_logs.read_inspect(json_path)]
    _fake_inspect(monkeypatch, data)
    assert [(r.target_id, r.name, r.label, r.run)
            for r in inspect_logs.read_inspect(path)] == same


def test_without_sample_reading_a_log_too_big_stops_with_a_plain_line(tmp_path, monkeypatch):
    import pytest

    from judgekeeper.readers import inspect_logs
    from judgekeeper.records import RecordsError

    calls = _fake_inspect(monkeypatch, _log_data(), stream=False)
    monkeypatch.setattr(inspect_logs, "WHOLE_LIMIT", 1000)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(b"P" * 3072)
    with pytest.raises(RecordsError) as e:
        inspect_logs._load(path)
    said = str(e.value)
    assert "3 KB" in said and "reads Inspect logs up to" in said and "fewer samples" in said
    assert calls == []  # not read at all
    path.write_bytes(b"P" * 10)
    assert len(inspect_logs._load(path)["samples"]) == 30  # a small one is read whole


def _real_log(tmp_path, n=6):
    """A real Inspect AI log: model_graded_qa graded by mockllm (no network, no key)."""
    from inspect_ai import Task
    from inspect_ai import eval as run_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import model_graded_qa
    from inspect_ai.solver import generate

    task = Task(dataset=[Sample(input=f"Question {i}?", target=f"Answer {i}") for i in range(n)],
                solver=generate(), scorer=model_graded_qa())
    return run_eval(task, model="mockllm/model", model_roles={"grader": "mockllm/model"},
                    display="none", log_dir=str(tmp_path / "logs"))[0]


def test_a_real_eval_log_reads_the_same_as_its_json(tmp_path):
    import pytest

    pytest.importorskip("inspect_ai")
    from inspect_ai.log import write_eval_log

    from judgekeeper.readers import read_inspect

    log = _real_log(tmp_path)
    path, as_json = tmp_path / "2026-10-21_qa.eval", tmp_path / "2026-10-21_qa.json"
    write_eval_log(log, str(path))
    write_eval_log(log, str(as_json), format="json")

    def seen(records):
        return sorted((r.target_id, r.name, r.label, r.run, r.annotator_kind, r.output,
                       str(r.trajectory)) for r in records)

    assert len(seen(read_inspect(path))) == 6
    assert seen(read_inspect(path)) == seen(read_inspect(as_json))
