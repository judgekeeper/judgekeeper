"""Heavy use and failed calls: the marking page works the result out once per change, not per
request; big Inspect logs are read sample by sample; one failed judge call costs only its own
answer and its text is never shown; `check` says what it could not re-check; a body far too
large gets its 413. Small made-up projects: each test asserts on how the work is done."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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

def _fake_inspect(monkeypatch, data, stream=True, sample=None):
    """inspect_ai.log with read_eval_log (and, with `stream`, read_eval_log_samples_by_id)
    over the JSON log `data`, or `sample(id, epoch)` for each sample asked for; returns what
    was called."""
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

    def read_eval_log_samples_by_id(path, samples, **kwargs):
        samples = list(samples)
        calls.append(("read_eval_log_samples_by_id", len(samples)))
        if sample is not None:
            return [dumped(sample(*key)) for key in samples]
        index = {(s["id"], s["epoch"]): s for s in data["samples"]}
        return [dumped(index[key]) for key in samples]

    pkg, log_mod = ModuleType("inspect_ai"), ModuleType("inspect_ai.log")
    log_mod.read_eval_log = read_eval_log
    if stream:
        log_mod.read_eval_log_samples = lambda *a, **k: calls.append("read_eval_log_samples")
        log_mod.read_eval_log_samples_by_id = read_eval_log_samples_by_id
    pkg.log, pkg.__version__ = log_mod, "0.3.200"
    monkeypatch.setitem(sys.modules, "inspect_ai", pkg)
    monkeypatch.setitem(sys.modules, "inspect_ai.log", log_mod)
    return calls


def _fake_eval(path, data, size=2):
    """A .eval log at `path` holding a part for each of the samples of `data` (its header
    then lists them), each part `size` bytes unpacked: for the made-up inspect_ai."""
    ids = list(dict.fromkeys(s["id"] for s in data["samples"]))
    data["eval"]["dataset"]["sample_ids"] = ids
    data["eval"]["config"]["epochs"] = max(s["epoch"] for s in data["samples"])
    parts = {"header.json": b"{}"}
    parts.update({f"samples/{s['id']}_epoch_{s['epoch']}.json": b"{}" + b" " * (size - 2)
                  for s in data["samples"]})
    path.write_bytes(_zipped(parts))


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
    _fake_eval(path, data)
    loaded = inspect_logs._load(path)
    samples = list(loaded["samples"])
    assert ("read_eval_log", False) not in calls  # never the whole log at once
    assert calls == [("read_eval_log", True), ("read_eval_log_samples_by_id", 30)]
    kept = set().union(*(s.keys() for s in samples))
    assert kept <= set(inspect_logs.SAMPLE_FIELDS) and "events" not in kept
    assert len(samples) == 30 and loaded["eval"] == data["eval"]
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
    path.write_bytes(_zipped({"header.json": b"{}"}))
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


def _declare(path, name, size):
    """Make the zip at `path` say its part `name` unpacks to `size` bytes, in both places a
    zip keeps it: the file stays as small as it was, as a zip bomb's does."""
    import struct
    import zipfile

    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as z:
        struct.pack_into("<I", data, z.getinfo(name).header_offset + 22, size)
    at = data.find(b"PK\x01\x02")
    while at != -1:
        length = struct.unpack_from("<H", data, at + 28)[0]
        if data[at + 46:at + 46 + length] == name.encode():
            struct.pack_into("<I", data, at + 24, size)
        at = data.find(b"PK\x01\x02", at + 4)
    path.write_bytes(bytes(data))
    with zipfile.ZipFile(path) as z:
        assert z.getinfo(name).file_size == size


def _bomb(tmp_path, monkeypatch, part, size):
    """A real .eval log whose `part` says it unpacks to `size` bytes, and the calls made to
    inspect_ai's readers while it is read."""
    import zipfile

    import pytest

    pytest.importorskip("inspect_ai")
    import inspect_ai.log
    from inspect_ai.log import write_eval_log

    from judgekeeper.readers import read_inspect

    path = tmp_path / "2026-10-21_qa.eval"
    write_eval_log(_real_log(tmp_path, n=2), str(path))
    assert len(read_inspect(path)) == 2  # read as it is
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n == part or n.startswith(part))
        sizes = {i.filename: i.file_size for i in z.infolist()}
    _declare(path, name, size)
    calls = []
    for reader in ("read_eval_log", "read_eval_log_samples"):
        real = getattr(inspect_ai.log, reader)
        monkeypatch.setattr(inspect_ai.log, reader,
                            lambda *a, _real=real, _name=reader, **k: (
                                calls.append(_name), _real(*a, **k))[1])
    return path, calls, sizes


def test_an_eval_log_whose_header_unpacks_too_big_is_refused_unread(tmp_path, monkeypatch):
    import tracemalloc

    import pytest

    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    path, calls, _ = _bomb(tmp_path, monkeypatch, "header.json", 3 * 2**30)
    assert path.stat().st_size < 100_000
    tracemalloc.start()
    try:
        with pytest.raises(RecordsError) as e:
            read_inspect(path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    said = str(e.value)
    assert "more than 50 MB for the header" in said, said
    assert calls == [] and peak < 20 * 2**20
    assert inspect_logs.eval_header(path) == {} and calls == []


def test_an_eval_log_with_one_sample_too_big_is_refused_unread(tmp_path, monkeypatch):
    import pytest

    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    path, calls, _ = _bomb(tmp_path, monkeypatch, "samples/", 2**30)
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    assert "more than 200 MB for one sample" in str(e.value) and calls == []


@pytest.mark.parametrize("part", ["header.json", "samples/"])
def test_an_eval_log_that_says_a_part_is_smaller_than_it_is_is_counted(tmp_path, monkeypatch,
                                                                       part):
    """A zip can declare any size: each part is counted as it really unpacks (here in
    inspect_ai's own compression), and the log refused once a part passes its limit."""
    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    path, calls, sizes = _bomb(tmp_path, monkeypatch, part, 100)
    if part == "header.json":  # the header's parts would pass as they say, not as they are
        limit = sizes["header.json"] - 1
        monkeypatch.setattr(inspect_logs, "HEADER_LIMIT", limit)
    else:
        limit = max(n for name, n in sizes.items() if name.startswith("samples/")) - 1
        monkeypatch.setattr(inspect_logs, "SAMPLE_LIMIT", limit, raising=False)
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    said = str(e.value)
    what = "the header" if part == "header.json" else "one sample"
    assert f"more than {inspect_logs._size(limit)} for {what}" in said, said
    assert calls == []


def _zip(path, parts, compression):
    import zipfile

    with zipfile.ZipFile(path, "w", compression) as z:
        for name, text in parts.items():
            z.writestr(name, text)


def test_a_deflated_part_that_says_it_is_smaller_is_counted(tmp_path, monkeypatch):
    import zipfile

    from judgekeeper.readers import inspect_logs
    from judgekeeper.records import RecordsError

    calls = _fake_inspect(monkeypatch, _log_data())
    monkeypatch.setattr(inspect_logs, "SAMPLE_LIMIT", 1000, raising=False)
    path = tmp_path / "2026-10-21_qa.eval"
    _zip(path, {"header.json": "{}", "samples/1_epoch_1.json": "{}" + " " * 5000},
         zipfile.ZIP_DEFLATED)
    _declare(path, "samples/1_epoch_1.json", 100)
    with pytest.raises(RecordsError) as e:
        inspect_logs._load(path)
    assert "more than 1000 bytes for one sample" in str(e.value) and calls == []


def test_a_part_in_a_compression_inspect_never_writes_is_refused(tmp_path, monkeypatch):
    import zipfile

    from judgekeeper.readers import inspect_logs
    from judgekeeper.records import RecordsError

    calls = _fake_inspect(monkeypatch, _log_data())
    path = tmp_path / "2026-10-21_qa.eval"
    _zip(path, {"header.json": "{}", "samples/1_epoch_1.json": "{}"}, zipfile.ZIP_BZIP2)
    with pytest.raises(RecordsError) as e:
        inspect_logs._load(path)
    assert "can't be read" in str(e.value) and calls == []


OLD_EVAL = Path(__file__).parent / "fixtures" / "inspect" / "real" / "old" / "inspect-0.3.204.eval"


def _with_sample(tmp_path, change) -> Path:
    """The real old .eval log, its first sample's JSON text changed by `change`."""
    import zipfile

    with zipfile.ZipFile(OLD_EVAL) as z:
        parts = {name: z.read(name).decode("utf-8") for name in z.namelist()}
    parts["samples/1_epoch_1.json"] = change(parts["samples/1_epoch_1.json"])
    path = tmp_path / "2026-10-21_qa.eval"
    _zip(path, parts, zipfile.ZIP_DEFLATED)
    return path


def test_an_eval_log_nested_too_deep_is_refused_unread(tmp_path, monkeypatch):
    """A few KB can hold a sample nested 100,000 deep, which inspect_ai would take many GB to
    read: the count of what a part unpacks to also counts how deep it goes."""
    import time
    import tracemalloc

    pytest.importorskip("inspect_ai")
    import inspect_ai.log

    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    deep = 100_000
    path = _with_sample(tmp_path, lambda _: '{"id": 1, "epoch": 1, "input": "x", "target": "y", '
                        '"metadata": ' + "[" * deep + "1" + "]" * deep + "}")
    assert path.stat().st_size < 20_000
    calls = []
    for reader in ("read_eval_log", "read_eval_log_samples"):
        monkeypatch.setattr(inspect_ai.log, reader, lambda *a, _name=reader, **k: calls.append(
            _name))
    tracemalloc.start()
    start = time.monotonic()
    try:
        with pytest.raises(RecordsError) as e:
            read_inspect(path)
        took, peak = time.monotonic() - start, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert str(e.value).startswith(f"{path.name} is nested more than 500 levels deep"), e.value
    assert calls == [] and took < 2 and peak < 20 * 2**20


def test_brackets_and_quotes_inside_text_are_not_nesting(tmp_path, monkeypatch):
    """Only lists and objects count: brackets in a string (with escaped quotes and
    backslashes around them) do not, also when a string runs across the steps counted."""
    import json

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import inspect_logs, read_inspect

    def bracketed(text):
        sample = json.loads(text)
        sample["metadata"] = {"note": '\\"' + "[{" * 2000 + '\\" \\'}
        return json.dumps(sample)

    path = _with_sample(tmp_path, bracketed)
    monkeypatch.setattr(inspect_logs, "STEP", 7)
    assert len(read_inspect(path)) == len(read_inspect(OLD_EVAL))


def test_without_sample_reading_a_log_that_unpacks_too_big_stops(tmp_path, monkeypatch):
    """An Inspect AI that reads a log whole: what the log unpacks to counts, not its size."""
    import zipfile

    import pytest

    from judgekeeper.readers import inspect_logs
    from judgekeeper.records import RecordsError

    calls = _fake_inspect(monkeypatch, _log_data(), stream=False)
    monkeypatch.setattr(inspect_logs, "WHOLE_LIMIT", 1000)
    path = tmp_path / "2026-10-21_qa.eval"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("header.json", "{}" + " " * 100)
        for n in range(4):
            z.writestr(f"samples/{n}_epoch_1.json", "{}" + " " * 800)
    assert path.stat().st_size < 1000
    with pytest.raises(RecordsError) as e:
        inspect_logs._load(path)
    assert "more than 1000 bytes unpacked" in str(e.value)
    assert "reads Inspect logs up to" in str(e.value)
    assert calls == []


# One zip, one table of contents ---------------------------------------------------------------

def _watched(monkeypatch):
    """inspect_ai's readers, each call to them noted; returns the calls."""
    pytest.importorskip("inspect_ai")
    import inspect_ai.log

    calls = []
    for reader in ("read_eval_log", "read_eval_log_samples"):
        real = getattr(inspect_ai.log, reader)
        monkeypatch.setattr(inspect_ai.log, reader,
                            lambda *a, _real=real, _name=reader, **k: (
                                calls.append(_name), _real(*a, **k))[1])
    return calls


def _old_parts() -> dict:
    import zipfile

    with zipfile.ZipFile(OLD_EVAL) as z:
        return {name: z.read(name) for name in z.namelist()}


def _zipped(parts: dict) -> bytes:
    import io
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return out.getvalue()


def _end(data: bytes) -> tuple[int, int, int]:
    """(parts, size, offset) of the table of contents, from the end record ending `data`."""
    import struct

    count, size, offset = struct.unpack_from("<HIIH", data, len(data) - 12)[:3]
    return count, size, offset


def _end_record(count: int, size: int, offset: int) -> bytes:
    import struct

    return struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, count, count, size, offset, 0)


def _moved(table: bytes, by: int) -> bytes:
    """A table of contents, each part's offset moved by `by`."""
    import struct

    out, at = bytearray(table), 0
    while at < len(out):
        struct.pack_into("<I", out, at + 42, struct.unpack_from("<I", out, at + 42)[0] + by)
        name, extra, comment = struct.unpack_from("<3H", out, at + 28)
        at += 46 + name + extra + comment
    return bytes(out)


def _refused_unread(path, calls):
    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    assert "can't be read: it may be cut short, or not an Inspect AI log" in str(e.value), e.value
    assert inspect_logs.eval_header(path) == {}
    assert calls == []


def test_a_log_whose_two_readers_see_different_parts_is_refused_unread(tmp_path, monkeypatch):
    """zipfile looks for the table of contents right before the end record, inspect_ai where
    the end record says. A log can hold two: the real old log's where zipfile looks, and one
    with a sample 1 MB bigger where inspect_ai does."""
    import zipfile

    calls = _watched(monkeypatch)
    shown = _zipped(_old_parts())
    parts = _old_parts()
    parts["samples/1_epoch_1.json"] += b" " * 2**20
    hidden = _zipped(parts)
    count, size, offset = _end(shown)
    assert _end(hidden)[:2] == (count, size)
    hidden_at = _end(hidden)[2]
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(hidden[:-22] + shown[:offset]
                     + _moved(shown[offset:offset + size], hidden_at - offset)
                     + _end_record(count, size, hidden_at))
    with zipfile.ZipFile(path) as z:
        assert z.getinfo("samples/1_epoch_1.json").file_size < 2**20
    _refused_unread(path, calls)


@pytest.mark.parametrize("moved", [True, False])
def test_a_log_with_bytes_before_its_first_part_is_refused_unread(tmp_path, monkeypatch, moved):
    """With the offsets moved to match (both readers find the parts) or not (zipfile alone
    does)."""
    calls = _watched(monkeypatch)
    data = OLD_EVAL.read_bytes()
    count, size, offset = _end(data)
    by = 100 if moved else 0
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(b"x" * 100 + data[:offset] + _moved(data[offset:offset + size], by)
                     + _end_record(count, size, offset + by))
    _refused_unread(path, calls)


def test_a_log_with_a_second_end_record_is_refused_unread(tmp_path, monkeypatch):
    """A zip64 end record that disagrees: zipfile reads the table of contents it names,
    inspect_ai (as the plain end record needs no zip64) the plain end record's own."""
    import struct
    import zipfile

    calls = _watched(monkeypatch)
    shown = _zipped(_old_parts())
    parts = _old_parts()
    parts["samples/1_epoch_1.json"] += b" " * 2**20
    hidden = _zipped(parts)
    count, size, offset = _end(shown)
    hidden_count, hidden_size, hidden_at = _end(hidden)
    body = hidden[:-22] + shown[:offset]
    table = _moved(shown[offset:offset + size], len(hidden) - 22)
    zip64_at = len(body) + size
    zip64 = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size,
                        len(hidden) - 22 + offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, zip64_at, 1)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(body + table + zip64 + locator
                     + _end_record(hidden_count, hidden_size, hidden_at))
    with zipfile.ZipFile(path) as z:
        assert z.getinfo("samples/1_epoch_1.json").file_size < 2**20
    _refused_unread(path, calls)


def test_end_record_bytes_inside_a_part_are_no_second_end_record(tmp_path):
    """Packed data can hold an end record's bytes by chance; only the record ending the file
    is the end record."""
    import zipfile

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(_old_parts()))
    with zipfile.ZipFile(path, "a", zipfile.ZIP_STORED) as z:
        z.writestr("notes.bin", b"PK\x05\x06 PK\x06\x06 PK\x06\x07" * 3)
    assert len(read_inspect(path)) == len(read_inspect(OLD_EVAL))


def test_a_log_zipfile_cannot_open_is_never_handed_to_inspect(tmp_path, monkeypatch):
    calls = _watched(monkeypatch)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(OLD_EVAL.read_bytes()[:-30])
    _refused_unread(path, calls)


# Wide parts: many values, little nesting

@pytest.mark.parametrize("part, said", [
    ("header.json", "more than 2,000,000 values for the header"),
    ("samples/1_epoch_1.json", "more than 2,000,000 values for one sample"),
    ("reductions.json", "more than 2,002,000 values for the header"),
    ("summaries.json", "more than 2,002,000 values for the header"),
])
def test_an_eval_log_with_a_wide_part_is_refused_unread(tmp_path, monkeypatch, part, said):
    """A few KB can hold `"zz": [0,0,...]` with millions of zeros, which inspect_ai would
    take GBs to read: values are counted as well as depth. A part that grows with the samples
    may hold 1,000 more values per sample (here 2)."""
    import time
    import tracemalloc

    pytest.importorskip("inspect_ai")
    import inspect_ai.log

    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    monkeypatch.setattr(inspect_logs, "PACKED_RATIO", 10**9)  # the values alone
    parts = _old_parts()
    text = parts[part].decode("utf-8")
    at = text.index("{") + 1
    parts[part] = (text[:at] + '"zz": [' + "0," * 3_000_000 + '0], ' + text[at:]).encode()
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    del parts, text
    assert path.stat().st_size < 50_000
    calls = []
    for reader in ("read_eval_log", "read_eval_log_samples"):
        monkeypatch.setattr(inspect_ai.log, reader, lambda *a, _name=reader, **k: calls.append(
            _name))
    tracemalloc.start()
    start = time.monotonic()
    try:
        with pytest.raises(RecordsError) as e:
            read_inspect(path)
        took, peak = time.monotonic() - start, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert said in str(e.value), e.value
    assert calls == [] and took < 2 and peak < 20 * 2**20


def test_a_log_of_30000_small_samples_still_reads(tmp_path):
    """The parts that grow with the samples (summaries, reductions) pass their caps."""
    import json

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import inspect_logs

    old = _old_parts()
    n = 30_000
    header = json.loads(old["header.json"])
    header["eval"]["dataset"].update(samples=n, sample_ids=list(range(1, n + 1)))
    summary = json.loads(old["summaries.json"])[0]
    reductions = json.loads(old["reductions.json"])
    reductions[0]["samples"] = reductions[0]["samples"][:1] * n
    parts = {"_journal/start.json": old["_journal/start.json"]}
    parts.update({f"samples/{i}_epoch_1.json": old["samples/1_epoch_1.json"]
                  for i in range(1, n + 1)})
    parts["summaries.json"] = json.dumps([dict(summary, id=i) for i in range(1, n + 1)])
    parts["reductions.json"] = json.dumps(reductions)
    parts["header.json"] = json.dumps(header)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    inspect_logs._check_unpacked(path)
    assert inspect_logs.eval_header(path)["dataset"]["samples"] == n


# The whole log: its parts together, and parts that share bytes

def _entries(data: bytes, name: str, more: list[str]) -> bytes:
    """The zip `data` with `more` entries in its table of contents, each pointing at the part
    `name`'s bytes: one stored part under many names."""
    import struct

    count, size, offset = _end(data)
    table, at = data[offset:offset + size], 0
    while at < len(table):
        length, extra, comment = struct.unpack_from("<3H", table, at + 28)
        end = at + 46 + length + extra + comment
        if table[at + 46:at + 46 + length] == name.encode():
            head, tail = table[at:at + 28], table[at + 30:at + 46]
            rest = table[at + 46 + length:end]
        at = end
    added = b"".join(head + struct.pack("<H", len(other.encode())) + tail + other.encode() + rest
                     for other in more)
    return (data[:offset] + table + added
            + _end_record(count + len(more), size + len(added), offset))


def _wide_sample(values: int) -> bytes:
    """The real old log's first sample, holding `values` zeros more: a few KB packed."""
    text = _old_parts()["samples/1_epoch_1.json"].decode("utf-8")
    at = text.index("{") + 1
    return (text[:at] + '"zz": [' + "0," * (values - 1) + '0], ' + text[at:]).encode()


def _stubbed(monkeypatch):
    """inspect_ai's readers replaced by ones that only note the call: a log handed to them
    is never really read."""
    pytest.importorskip("inspect_ai")
    import inspect_ai.log

    calls = []
    for reader in ("read_eval_log", "read_eval_log_samples"):
        monkeypatch.setattr(inspect_ai.log, reader, lambda *a, _name=reader, **k: calls.append(
            _name))
    return calls


@pytest.mark.parametrize("names", [100, 300])
def test_a_small_log_naming_one_wide_part_many_times_is_refused_fast(tmp_path, monkeypatch,
                                                                     names):
    """A few KB can name one stored part of about 2,000,000 values many times over: each
    name alone passes the limit for one sample, and Inspect AI would read every one."""
    import time
    import tracemalloc

    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _wide_sample(1_990_000)
    data = _entries(_zipped(parts), "samples/1_epoch_1.json",
                    [f"samples/{i}_epoch_1.json" for i in range(3, names + 2)])
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(data)
    assert path.stat().st_size < 50_000
    calls = _stubbed(monkeypatch)
    tracemalloc.start()
    start = time.monotonic()
    try:
        with pytest.raises(RecordsError) as e:
            read_inspect(path)
        took, peak = time.monotonic() - start, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert "can't be read: it may be cut short, or not an Inspect AI log" in str(e.value)
    assert calls == [] and took < 5 and peak < 300 * 2**20


def test_a_log_of_20_wide_samples_is_refused_fast(tmp_path, monkeypatch):
    """20 parts of about 2,000,000 values each, in 141 KB: each passes the limit of values
    for one sample, but unpacks to far more than 200 times its packed size."""
    import time

    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    parts = _old_parts()
    del parts["samples/2_epoch_1.json"]
    wide = _wide_sample(1_990_000)
    parts.update({f"samples/{i}_epoch_1.json": wide for i in range(1, 21)})
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    del parts, wide
    assert path.stat().st_size < 200_000
    calls = _stubbed(monkeypatch)
    start = time.monotonic()
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    said = str(e.value)
    assert said.startswith(f"{path} is too big for judgekeeper to read: one sample would "
                           "unpack to more than 200 times its packed size"), said
    assert "damaged" not in said and "\n" not in said
    assert calls == [] and time.monotonic() - start < 5


def test_a_log_whose_samples_unpack_too_big_together_is_refused(tmp_path, monkeypatch):
    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    calls = _watched(monkeypatch)
    with __import__("zipfile").ZipFile(OLD_EVAL) as z:
        sizes = [i.file_size for i in z.infolist() if i.filename.startswith("samples/")]
    limit = sum(sizes) - 1  # each sample alone passes it
    assert max(sizes) < limit
    monkeypatch.setattr(inspect_logs, "SAMPLES_LIMIT", limit, raising=False)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(OLD_EVAL.read_bytes())
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    said = str(e.value)
    assert said.startswith(f"{path} is too big for judgekeeper to read: it would unpack to more "
                           f"than {inspect_logs._size(limit)} of samples in all"), said
    assert "damaged" not in said and calls == []


def _longer(data: bytes, name: str, by: int) -> bytes:
    """The zip `data`, its part `name` saying it is `by` bytes longer packed, in both places a
    zip keeps it: it runs into the part after it."""
    import struct
    import zipfile

    out = bytearray(data)
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        info = z.getinfo(name)
    struct.pack_into("<I", out, info.header_offset + 18, info.compress_size + by)
    _, size, offset = _end(data)
    at = offset
    while at < offset + size:
        length, extra, comment = struct.unpack_from("<3H", out, at + 28)
        if out[at + 46:at + 46 + length] == name.encode():
            struct.pack_into("<I", out, at + 20, info.compress_size + by)
        at += 46 + length + extra + comment
    return bytes(out)


@pytest.mark.parametrize("how", ["two names, one part", "one name, one part twice",
                                 "runs into the next part"])
def test_a_log_whose_parts_share_bytes_or_names_is_refused_unread(tmp_path, monkeypatch, how):
    import zipfile

    calls = _watched(monkeypatch)
    data = _zipped(_old_parts())
    if how == "two names, one part":
        data = _entries(data, "samples/1_epoch_1.json", ["samples/3_epoch_1.json"])
    elif how == "one name, one part twice":
        data = _entries(data, "samples/1_epoch_1.json", ["samples/1_epoch_1.json"])
    else:
        data = _longer(data, "samples/1_epoch_1.json", 50)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(data)
    with zipfile.ZipFile(path) as z:  # zipfile opens it
        assert "samples/1_epoch_1.json" in z.namelist()
    _refused_unread(path, calls)


def test_a_sample_written_again_under_its_name_reads_as_inspect_reads_it(tmp_path):
    """Inspect AI writes a requeued or re-logged sample again under the same name, in its own
    bytes, and reads the last one: such a log is read, with the sample as written last."""
    import json
    import warnings
    import zipfile

    pytest.importorskip("inspect_ai")
    from inspect_ai.log import read_eval_log

    from judgekeeper.readers import read_inspect

    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(_old_parts()))
    sample = json.loads(_old_parts()["samples/1_epoch_1.json"])
    sample["scores"]["model_graded_qa"]["value"] = "C"  # it was I
    with warnings.catch_warnings(), zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as z:
        warnings.filterwarnings("ignore", message="Duplicate name:")
        z.writestr("samples/1_epoch_1.json", json.dumps(sample))
    with zipfile.ZipFile(path) as z:
        assert z.namelist().count("samples/1_epoch_1.json") == 2
    seen = {(r.target_id, r.label) for r in read_inspect(path)}
    assert seen == {(str(s.id), s.scores["model_graded_qa"].value)
                    for s in read_eval_log(str(path)).samples}
    assert ("1", "C") in seen


def test_the_limits_for_the_whole_log_are_far_above_honest_logs():
    from judgekeeper.readers import inspect_logs

    assert inspect_logs.SAMPLES_LIMIT == 4 * 2**30
    assert inspect_logs.ALL_VALUES_LIMIT == 200_000_000
    assert inspect_logs.PACKED_RATIO == 200


def test_a_log_holding_too_many_values_in_all_says_so(tmp_path, monkeypatch):
    from judgekeeper.readers import inspect_logs, read_inspect
    from judgekeeper.records import RecordsError

    calls = _watched(monkeypatch)
    monkeypatch.setattr(inspect_logs, "ALL_VALUES_LIMIT", 500)  # the log holds 950
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(OLD_EVAL.read_bytes())
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    said = str(e.value)
    assert said.startswith(f"{path} is too big for judgekeeper to read: it would unpack to more "
                           "than 500 values in all"), said
    assert calls == []


def test_a_sample_packed_over_200_times_tighter_is_too_big_to_read(tmp_path, monkeypatch):
    """600,000 values (1.2 MB) in about 1 KB: far under the limits for one sample, far over
    what an honest sample packs to."""
    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _wide_sample(600_000)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    calls = _stubbed(monkeypatch)
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    said = str(e.value)
    assert said.startswith(f"{path} is too big for judgekeeper to read: one sample would "
                           "unpack to more than 200 times its packed size"), said
    assert calls == []


def test_summaries_that_pack_tightly_still_read(tmp_path):
    """Inspect AI's summaries and reductions repeat a lot and can pack 100 to 200 times:
    only samples are held to the packing limit."""
    import json
    import zipfile

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    parts = _old_parts()
    summaries = json.loads(parts["summaries.json"])
    summaries[0]["input"] = "the same words " * 200_000
    parts["summaries.json"] = json.dumps(summaries)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("summaries.json")
    assert info.file_size > 200 * info.compress_size and info.file_size > 2**20
    assert len(read_inspect(path)) == len(read_inspect(OLD_EVAL))


def _sizes_in_zip64(first: int, second: int | None) -> bytes:
    """The real old log written again by hand, its first sample's packed size in the table
    of contents given in zip64 extras: `first`, then `second` when given. zipfile takes the
    last, inspect_ai the first."""
    import struct
    import zlib

    body, table = bytearray(), []
    for name, data in _old_parts().items():
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = packer.compress(data) + packer.flush()
        crc, raw, at = zlib.crc32(data), name.encode(), len(body)
        if name == "samples/1_epoch_1.json":
            body += struct.pack("<4s5H3L2H", b"PK\x03\x04", 45, 0, 8, 0, 0, crc, 0, 0,
                                len(raw), 0) + raw + packed
            extra = struct.pack("<HHQ", 1, 8, first)
            extra += b"" if second is None else struct.pack("<HHQ", 1, 8, second)
            size = 0xFFFFFFFF
        else:
            body += struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, 8, 0, 0, crc, len(packed),
                                len(data), len(raw), 0) + raw + packed
            extra, size = b"", len(packed)
        table.append(struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 45, 45, 0, 8, 0, 0, crc, size,
                                 len(data), len(raw), len(extra), 0, 0, 0, 0, at) + raw + extra)
    listed = b"".join(table)
    return bytes(body) + listed + _end_record(len(table), len(listed), len(body))


@pytest.mark.parametrize("how", ["two zip64 sizes", "a zip64 size of 0xFFFFFFFF",
                                 "packed data longer than it says"])
def test_a_part_whose_packed_size_reads_two_ways_is_refused_unread(tmp_path, monkeypatch, how):
    """zipfile and inspect_ai must take a part to end at the same byte: else what is checked
    is not what inspect_ai reads."""
    import zipfile

    calls = _watched(monkeypatch)
    if how == "two zip64 sizes":
        data = _sizes_in_zip64(0xFFFFFFFF, 64)
    elif how == "a zip64 size of 0xFFFFFFFF":
        data = _sizes_in_zip64(0xFFFFFFFF, None)
    else:
        data = _longer(_zipped(_old_parts()), "samples/1_epoch_1.json", -50)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(data)
    with zipfile.ZipFile(path) as z:
        assert "samples/1_epoch_1.json" in z.namelist()
    if how != "packed data longer than it says":
        _refused_unread(path, calls)
        return
    from judgekeeper.readers import read_inspect  # the header alone still reads
    from judgekeeper.records import RecordsError

    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    assert "can't be read: it may be cut short" in str(e.value) and calls == []


def test_a_log_whose_header_was_edited_in_place_still_reads(tmp_path):
    """Inspect AI edits a header (a score edited in its viewer) by writing a new one and
    leaving the old one's bytes unlisted: a gap between parts is allowed."""
    import struct
    import zipfile
    from itertools import pairwise

    pytest.importorskip("inspect_ai")
    from inspect_ai.log import read_eval_log, write_eval_log

    from judgekeeper.readers import read_inspect

    path = tmp_path / "2026-10-21_qa.eval"
    write_eval_log(read_eval_log(str(OLD_EVAL)), str(path))
    write_eval_log(read_eval_log(str(path), header_only=True), str(path), header_only=True)
    with zipfile.ZipFile(path) as z, path.open("rb") as f:
        spans = []
        for p in z.infolist():
            f.seek(p.header_offset + 26)
            name, extra = struct.unpack("<HH", f.read(4))
            spans.append((p.header_offset, p.header_offset + 30 + name + extra + p.compress_size))
        spans = sorted(spans) + [(z.start_dir, 0)]
    assert any(end < after for (_, end), (after, _) in pairwise(spans))
    assert len(read_inspect(path)) == len(read_inspect(OLD_EVAL))


def test_a_log_saying_a_billion_epochs_reads_in_seconds(tmp_path, monkeypatch):
    """Inspect AI's own loop asks for every sample id in every epoch the header names: only
    the samples the log holds are read."""
    import json
    import time

    pytest.importorskip("inspect_ai")
    import inspect_ai.log._file as inspect_file

    from judgekeeper.readers import read_inspect

    parts = _old_parts()
    for name in ("header.json", "_journal/start.json"):
        part = json.loads(parts[name])
        part["eval"]["config"]["epochs"] = 1_000_000_000
        parts[name] = json.dumps(part)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    assert path.stat().st_size < 10_000
    asked = []
    real = inspect_file.read_eval_log_sample

    def counted(*args, **kwargs):
        asked.append(1)
        if len(asked) > 1000:
            raise RuntimeError("still asking")
        return real(*args, **kwargs)

    monkeypatch.setattr(inspect_file, "read_eval_log_sample", counted)
    start = time.monotonic()
    records = read_inspect(path)
    assert time.monotonic() - start < 5 and len(asked) <= 2
    assert len(records) == len(read_inspect(OLD_EVAL))


def test_a_10_mb_log_of_4000_samples_reads_every_sample_in_flat_memory(tmp_path):
    """The real old log with 4,000 samples more of its first sample's shape, all listed in
    its header: the limits for the whole log pass and every sample is read, in seconds."""
    import json
    import time
    import tracemalloc

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    n = 4002
    parts = _old_parts()
    header = json.loads(parts["header.json"])
    header["eval"]["dataset"].update(samples=n, sample_ids=list(range(1, n + 1)))
    parts["header.json"] = json.dumps(header)
    sample = json.loads(parts["samples/1_epoch_1.json"])
    parts.update({f"samples/{i}_epoch_1.json": json.dumps(dict(sample, id=i, uuid=f"u{i}"))
                  for i in range(3, n + 1)})
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    del parts
    assert 8 * 2**20 < path.stat().st_size < 12 * 2**20
    tracemalloc.start()
    start = time.monotonic()
    try:
        records = read_inspect(path)
        took, peak = time.monotonic() - start, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len({r.target_id for r in records}) == n == len(records)
    assert took < 120 and peak < 60 * 2**20, (took, peak)  # one at a time: minutes
def test_samples_are_let_go_once_read(tmp_path, monkeypatch):
    """What a sample holds beyond what the reader keeps (here a 100 KB rendered prompt in its
    score's metadata) is let go once read: at most one batch of samples is held."""
    import copy
    import tracemalloc

    from judgekeeper.readers import inspect_logs

    data = _log_data(500)
    one = copy.deepcopy(data["samples"][0])

    def sample(i, epoch):
        s = copy.deepcopy(one)
        s.update(id=i, epoch=epoch, input=f"Question {i}?")
        s["scores"]["model_graded_qa"]["metadata"] = {"grading": "x" * 100_000}
        return s

    path = tmp_path / "2026-10-21_qa.eval"
    _fake_eval(path, data, size=100_000)
    data["samples"] = None
    calls = _fake_inspect(monkeypatch, data, sample=sample)
    tracemalloc.start()
    try:
        records = inspect_logs.read_inspect(path)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len(records) == 500 and len(calls) > 2
    assert peak < 20 * 2**20, peak  # all 500 at once: over 50 MB
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
