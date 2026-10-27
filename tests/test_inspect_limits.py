"""Inspect AI .eval logs that pass each size limit but would still take minutes to read: a
header that names one sample many times, a part whose name zipfile and Inspect AI read
differently, one very long text, and many small samples packed very tightly. Each is refused
(or read once) before Inspect AI reads it. The logs are built here from the real old log."""

from __future__ import annotations

import json
import struct
import time
import zipfile
import zlib

import pytest

from tests.test_load_and_failures import (
    OLD_EVAL,
    _old_parts,
    _refused_unread,
    _stubbed,
    _watched,
    _zipped,
)

MB = 2**20


def _log(tmp_path, parts) -> object:
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_zipped(parts))
    return path


def _refused(path, monkeypatch) -> tuple[str, float]:
    """What judgekeeper says refusing the log at `path`, and how long it took; Inspect AI's
    readers are stubbed, so a log handed to them is never really read."""
    from judgekeeper.readers import read_inspect
    from judgekeeper.records import RecordsError

    calls = _stubbed(monkeypatch)
    start = time.monotonic()
    with pytest.raises(RecordsError) as e:
        read_inspect(path)
    took = time.monotonic() - start
    assert calls == []
    return str(e.value), took


# A header that names one sample many times -----------------------------------------------------

def test_a_header_naming_one_sample_10000_times_reads_it_once(tmp_path, monkeypatch):
    pytest.importorskip("inspect_ai")
    import inspect_ai.log

    from judgekeeper.readers import read_inspect

    parts = _old_parts()
    for name in ("header.json", "_journal/start.json"):
        header = json.loads(parts[name])
        header["eval"]["dataset"].update(samples=10_000, sample_ids=[1] * 10_000)
        parts[name] = json.dumps(header)
    del parts["samples/2_epoch_1.json"]
    path = _log(tmp_path, parts)
    asked = []
    real = inspect_ai.log.read_eval_log_samples_by_id
    monkeypatch.setattr(inspect_ai.log, "read_eval_log_samples_by_id",
                        lambda p, ids, **k: (asked.extend(ids), real(p, ids, **k))[1])
    start = time.monotonic()
    records = read_inspect(path)
    assert time.monotonic() - start < 2
    assert asked == [(1, 1)]
    assert [r.target_id for r in records] == ["1"]


def test_held_never_names_more_samples_than_the_log_holds():
    from judgekeeper.readers import inspect_logs

    sizes = {"samples/1_epoch_1.json": 10, "samples/2_epoch_1.json": 10, "header.json": 5}
    spec = {"dataset": {"sample_ids": [1, "1", 2, 1, 2, 3] * 1000}, "config": {"epochs": 1}}
    assert inspect_logs._held(spec, sizes) == [(1, 1), (2, 1)]
