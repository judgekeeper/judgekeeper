"""Heavy use and failed calls: the marking page works the result out once per change, not per
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


def _no_inspect(monkeypatch):
    """judgekeeper's own process without inspect_ai, as CI runs it: the made-up logs are read
    as JSON (a worker runs in its own Python, with the stub)."""
    import sys

    for name in [n for n in sys.modules if n == "inspect_ai" or n.startswith("inspect_ai.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "inspect_ai", None)


def _counting(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counted)
    return calls


# The marking page -----------------------------------------------------------------------------

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


# Inspect logs, sample by sample ---------------------------------------------------------------

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


# One failed judge call, and its text ---------------------------------------------------------

CANARY = "CANARY-prompt-text-7f3a"


def _inspect_ws(tmp_path):
    from judgekeeper.start_label import StartSession as Session
    from tests.start_projects import save_result, split
    from tests.test_again_python_run import _inspect

    _inspect()(tmp_path, split(20, 16))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    session = Session(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _ask(ws):
    import sys

    from judgekeeper import again
    from judgekeeper.again import AgainOptions, make_plan
    from tests.test_again_run import _Said

    plan = make_plan(ws, AgainOptions(python=sys.executable), dry=True)
    said = _Said()
    return again.run_tool(ws, plan, said), "\n".join(said.lines)


def test_a_failed_judge_call_costs_only_its_own_answer(tmp_path, stubs, monkeypatch):
    from judgekeeper import again
    from judgekeeper.again.fresh import NOT_COUNTED

    _no_inspect(monkeypatch)
    ws = _inspect_ws(tmp_path)
    inputs = [a["input"] for a in again.labeled_answers(ws)]
    failing = inputs[1::2]  # every second answer's call fails, both times asked
    saved = {a["input"]: a["verdict"] == "pass" for a in again.labeled_answers(ws)}
    stubs.plan(verdicts=saved, errors=[[i, t] for i in failing for t in (0, 1)], error_text=CANARY)
    fresh, said = _ask(ws)
    assert len(fresh.verdicts) == len(inputs) - len(failing)
    assert set(fresh.not_counted.values()) == {"judge call failed"}
    assert len(fresh.not_counted) == len(failing)
    assert NOT_COUNTED["judge call failed"][1] == "the LLM-as-a-judge's calls for them failed"
    assert fresh.notes == [f"The LLM-as-a-judge's calls failed: RuntimeError on {len(failing)} answers."]
    assert CANARY not in said and "[Task]" not in said


def test_no_judge_error_text_reaches_a_file(tmp_path, stubs, monkeypatch):
    from judgekeeper import again

    _no_inspect(monkeypatch)
    ws = _inspect_ws(tmp_path)
    inputs = [a["input"] for a in again.labeled_answers(ws)]
    stubs.plan(errors=[[i, t] for i in inputs[::3] for t in (0, 1)], error_text=CANARY)
    _ask(ws)
    for path in ws.root.rglob("*"):
        if path.is_file():
            assert CANARY.encode() not in path.read_bytes(), path


def test_when_every_call_fails_it_says_the_type_and_count_only(tmp_path, stubs, monkeypatch):
    import pytest

    from judgekeeper import again
    from judgekeeper.again.fresh import AgainError

    _no_inspect(monkeypatch)
    ws = _inspect_ws(tmp_path)
    inputs = [a["input"] for a in again.labeled_answers(ws)]
    stubs.plan(errors=[[i, t] for i in inputs for t in (0, 1)], error_text=CANARY)
    with pytest.raises(AgainError) as e:
        _ask(ws)
    assert str(e.value) == (f"Inspect AI could not ask your LLM-as-a-judge: RuntimeError on "
                            f"{len(inputs)} answers")


def test_the_worker_keeps_the_scorers_name_for_real_inspect(tmp_path):
    """The guard is a scorer Inspect accepts: score_async names its scores as before, and a
    failure leaves only that sample unscored."""
    import asyncio
    import importlib.util

    import pytest

    pytest.importorskip("inspect_ai")
    from inspect_ai import score_async
    from inspect_ai.model import get_model
    from inspect_ai.scorer import model_graded_qa

    from judgekeeper.again import workers

    spec = importlib.util.spec_from_file_location(
        "inspect_worker", __import__("pathlib").Path(workers.__file__).parent / "inspect_worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    log = _real_log(tmp_path)
    inner, failed = model_graded_qa(), {}

    async def flaky(state, target):
        if int(str(state.sample_id)) % 2:
            raise RuntimeError(f"Error code: 400 {CANARY}")
        return await inner(state, target)

    from inspect_ai._util.registry import (
        registry_info,
        registry_params,
        set_registry_info,
        set_registry_params,
    )

    set_registry_info(flaky, registry_info(inner))  # as a scorer from Inspect's registry
    set_registry_params(flaky, registry_params(inner))
    new = asyncio.run(score_async(log, [worker.guarded(flaky, failed)], action="append",
                                  model=get_model("mockllm/model"),
                                  model_roles={"grader": get_model("mockllm/model")}))
    scored = {str(s.id): sorted(s.scores) for s in new.samples}
    assert scored["2"] == ["model_graded_qa", "model_graded_qa1"]
    assert scored["1"] == ["model_graded_qa"]
    assert failed == {(str(i), 1): "RuntimeError" for i in (1, 3, 5)}


# check, after some marks were not re-checked ---------------------------------------------------

def test_check_says_how_many_marks_were_not_re_checked(tmp_path, capsys, monkeypatch):
    from tests.test_again_run import FakePromptfoo
    from tests.test_check import HAIKU, MARKED, _marked, _new_outputs, _results
    from tests.test_check import judge as fake_judge
    from tests.test_check import run as check
    from tests.test_loop import _flat

    monkeypatch.chdir(tmp_path)
    holder = fake_judge.__wrapped__(monkeypatch, tmp_path)
    ws = _marked(tmp_path)
    _results(tmp_path, MARKED, model=HAIKU, outputs=_new_outputs())
    holder["fake"] = FakePromptfoo(ws, version="0.124.1")
    last = marks.read(ws.marks).last
    marked = {k: sorted(i for i, x in last.items() if x["mark"] == k) for k in ("pass", "fail")}
    holder["fake"].grader_errors = set(marked["pass"][:3] + marked["fail"][:3])
    code, out = check(capsys, "--yes")
    flat = _flat(out)
    assert code == 0 and "Re-checked on 44 of your 50 marks:" in flat, flat
    assert "Next: nothing to do" not in flat
    assert "Next: 6 marks were not re-checked. Run `" in flat
    assert "check` again to ask your LLM-as-a-judge about them." in flat


# fix, for model_graded_qa with Inspect's default instructions ---------------------------------

def test_fix_says_why_it_cant_test_inspects_default_instructions(tmp_path, capsys, monkeypatch):
    from judgekeeper.cli import main
    from tests.start_projects import inspect_data, save_result, split

    data = inspect_data(split(40, 40))
    for s in data["eval"]["scorers"]:
        s["options"] = {}  # model_graded_qa() as written: Inspect's own instructions
    path = tmp_path / "logs" / "2026-10-21_qa.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    _no_inspect(monkeypatch)
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    session = StartSession(ws)
    for n, q in enumerate(ws.data()["queue"]):
        session.update({"id": q["id"], "label": q["group"] if n % 4 else
                        ("fail" if q["group"] == "pass" else "pass")})
    save_result(ws, session, say=_quiet)
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    main(["fix"])
    out = " ".join(capsys.readouterr().out.split())
    assert ("judgekeeper can't ask this LLM-as-a-judge itself: Inspect's default model_graded_qa "
            "instructions aren't written in your code. To test a rule, set instructions= in "
            "model_graded_qa(...) and run your eval again.") in out, out


# A body far over the limit -------------------------------------------------------------------

def test_a_body_far_over_the_limit_gets_its_413_before_it_is_read(tmp_path, monkeypatch):
    """Over MAX_DRAIN, the page answers 413 at once and closes: the client reads the answer,
    never a reset."""
    import socket
    import threading

    from judgekeeper import label as label_mod
    from tests.test_label_server import PAGE, Session, _items

    monkeypatch.setattr(label_mod, "MAX_DRAIN", 2_000_000)
    server = label_mod.LabelServer(Session(_items(tmp_path), tmp_path / "labels.csv"), port=0,
                                   page=PAGE)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        port = server.port
        head = (f"POST /label?token={server.token} HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n"
                f"Origin: http://127.0.0.1:{port}\r\n"
                f"Content-Length: 100000000\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(head + b"x" * 300_000)  # a little of the 100 MB, then it waits
            answer = b""
            while chunk := s.recv(65536):  # a reset raises here
                answer += chunk
        assert answer.startswith(b"HTTP/1.0 413 "), answer[:80]
        assert b"too large" in answer.lower()
        assert not (tmp_path / "labels.csv").exists()
    finally:
        server.stop()
        thread.join(timeout=10)
