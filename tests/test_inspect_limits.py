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


# A part whose name zipfile and Inspect AI read differently --------------------------------------

UPATH = 0x7075  # zip's Unicode Path extra field: zipfile names the part from it


def _upath(alias: str, raw: str) -> bytes:
    data = alias.encode()
    return struct.pack("<HHBL", UPATH, 5 + len(data), 1, zlib.crc32(raw.encode())) + data


def _with_decoy(where: str) -> bytes:
    """The real old log with a decoy part whose raw name is sample 1's (what Inspect AI reads:
    the last part of a name) and whose Unicode Path extra, in the table of contents or the
    part's own header, names it zz/other.json (what zipfile reads)."""
    import io
    import warnings

    parts = _old_parts()
    decoy = json.loads(parts["samples/1_epoch_1.json"])
    decoy["output"]["completion"] = "DECOY answer"
    raw = "samples/1_epoch_1.json"
    info = zipfile.ZipInfo(raw)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.extra = field = _upath("zz/other.json", raw)
    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        warnings.filterwarnings("ignore", message="Duplicate name:")
        for name, data in parts.items():
            if name != "header.json":
                z.writestr(name, data)
        z.writestr(info, json.dumps(decoy))
        z.writestr("header.json", parts["header.json"])
    data = bytearray(out.getvalue())
    assert data.count(field) == 2  # in the part's own header, then in the table of contents
    local, central = data.find(field), data.rfind(field)
    if where == "central":  # the part's own header names it as Inspect AI does
        data[local:local + 2] = struct.pack("<H", 0xCAFE)
    elif where == "local":
        data[central:central + 2] = struct.pack("<H", 0xCAFE)
    return bytes(data)


@pytest.mark.parametrize("where", ["central", "local", "both"])
def test_a_part_named_two_ways_is_refused_unread(tmp_path, monkeypatch, where):
    calls = _watched(monkeypatch)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_with_decoy(where))
    _refused_unread(path, calls)


def test_a_name_zipfile_reads_otherwise_is_refused_unread(tmp_path, monkeypatch):
    """A raw name that isn't UTF-8 (zipfile reads it as cp437, Inspect AI as UTF-8)."""
    calls = _watched(monkeypatch)
    data = bytearray(_zipped(_old_parts()))
    at = data.rfind(b"samples/2_epoch_1.json")  # in the table of contents
    data[at + 8] = 0xE9  # samples/\xe9...
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(bytes(data))
    _refused_unread(path, calls)


def test_a_normal_log_still_reads(tmp_path):
    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    assert len(read_inspect(_log(tmp_path, _old_parts()))) == len(read_inspect(OLD_EVAL)) > 0


def _repeated(first: bytes, last: bytes) -> bytes:
    """The real old log with sample 1 written twice under its name: `first`, then `last`."""
    import io
    import warnings

    parts = _old_parts()
    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        warnings.filterwarnings("ignore", message="Duplicate name:")
        z.writestr("samples/1_epoch_1.json", first)
        for name, data in parts.items():
            z.writestr(name, last if name == "samples/1_epoch_1.json" else data)
    return out.getvalue()


def test_a_repeated_name_whose_first_copy_is_too_big_is_refused(tmp_path, monkeypatch):
    """Each copy of a repeated name is checked, not only the one zipfile and Inspect AI read."""
    from judgekeeper.readers import inspect_logs

    sample = _old_parts()["samples/1_epoch_1.json"]
    monkeypatch.setattr(inspect_logs, "SAMPLE_LIMIT", len(sample) + 100)
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_repeated(sample + b" " * 5000, sample))
    said, _ = _refused(path, monkeypatch)
    assert "for one sample" in said, said


def test_zipfile_and_inspect_read_the_last_copy_of_a_repeated_name(tmp_path):
    pytest.importorskip("inspect_ai")
    from inspect_ai.log import read_eval_log

    sample = json.loads(_old_parts()["samples/1_epoch_1.json"])
    last = dict(sample, output=dict(sample["output"], completion="the last copy"))
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(_repeated(json.dumps(sample).encode(), json.dumps(last).encode()))
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read("samples/1_epoch_1.json"))["output"]["completion"] == (
            "the last copy")
    read = {s.id: s.output.completion for s in read_eval_log(str(path)).samples}
    assert read[1] == "the last copy"


# One very long text ---------------------------------------------------------------------------

def _text_sample(field: str, text: str) -> bytes:
    sample = json.loads(_old_parts()["samples/1_epoch_1.json"])
    if field == "metadata":
        sample["metadata"] = {"pad": text}
    elif field == "events":  # left out of the read, but still parsed
        sample["events"] = [{"event": "info", "data": text}]
    else:
        sample["attachments"] = {"a" * 32: text}
    return json.dumps(sample).encode()


def _random(n: int, chars: str) -> str:
    """`n` characters, each one of `chars` at random (so the text doesn't pack tightly)."""
    import os

    return os.urandom(n // 2 + 1).hex().translate(str.maketrans(
        "0123456789abcdef", (chars * 16)[:16]))[:n]


@pytest.mark.parametrize("field", ["metadata", "events", "attachments"])
def test_one_text_over_8_mb_is_refused_fast(tmp_path, monkeypatch, field):
    from judgekeeper.readers import inspect_logs

    assert inspect_logs.MAX_STRING == 8 * MB
    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _text_sample(field, _random(9 * MB, "0123456789abcdef"))
    path = _log(tmp_path, parts)
    said, took = _refused(path, monkeypatch)
    assert said == (f"{path} is too big for judgekeeper to read: one text in it is longer than "
                    "8 MB, the most judgekeeper reads in one text of an Inspect AI log."), said
    assert took < 5


def test_escapes_count_as_the_characters_they_stand_for(tmp_path, monkeypatch):
    """9 MB written as escapes (\\n, \\t: 18 MB in the file) is over the limit; 4 MB with
    \\u00e9 in it (about 14 MB in the file) is under it."""
    from judgekeeper.readers import inspect_logs

    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _text_sample("metadata", _random(9 * MB, "\n\t"))
    said, _ = _refused(_log(tmp_path, parts), monkeypatch)
    assert "one text in it is longer than 8 MB" in said, said
    parts["samples/1_epoch_1.json"] = _text_sample("metadata", _random(4 * MB, "é\t"))
    assert len(parts["samples/1_epoch_1.json"]) > 12 * MB
    inspect_logs._check_unpacked(_log(tmp_path, parts))


@pytest.mark.parametrize("step", [1, 2, 3, 7, 64])
def test_the_longest_text_is_found_however_the_bytes_are_split(step):
    from judgekeeper.readers import inspect_logs

    text = json.dumps({"a": "x" * 40, "b": ['q\\"' + "y" * 55, "z" * 7], "c": "\\" * 9,
                       "d": ""}).encode()
    longest = max(len(s) for s in json.loads(text)["b"])  # the first, its escapes read
    depth = inspect_logs._Depth(longest=longest)
    for at in range(0, len(text), step):
        depth.feed(text[at:at + step])
    with pytest.raises(inspect_logs.TooLong):
        too_short = inspect_logs._Depth(longest=longest - 1)
        for at in range(0, len(text), step):
            too_short.feed(text[at:at + step])


def test_a_long_agent_sample_with_attachments_still_reads(tmp_path):
    """A real-shaped agent sample of about 50 MB: many messages of about 120 KB, and a few
    screenshots of 1 MB as base64 in its attachments."""
    import base64
    import os

    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    sample = json.loads(_old_parts()["samples/1_epoch_1.json"])
    words = [os.urandom(4).hex() for _ in range(5000)]
    messages = list(sample["messages"])
    for i in range(400):
        text = " ".join(words[(i * 7 + k) % 5000] for k in range(13_000))
        messages.append({"role": "assistant" if i % 2 else "user", "content": text,
                         "source": "generate" if i % 2 else "input"})
    sample["messages"] = messages
    sample["attachments"] = {f"{i:032x}": base64.b64encode(os.urandom(750_000)).decode()
                             for i in range(3)}
    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = json.dumps(sample).encode()
    path = _log(tmp_path, parts)
    assert 45 * MB < len(parts["samples/1_epoch_1.json"]) < 60 * MB
    del parts, sample, messages
    records = read_inspect(path)
    assert len(records) == len(read_inspect(OLD_EVAL))


# Many small samples, packed tightly -------------------------------------------------------------

def test_400_tightly_packed_small_samples_are_refused_fast(tmp_path, monkeypatch):
    """400 samples of 499,000 values each, about 2.4 KB packed: each under the ratio's floor
    and under the limit of values for one sample, all together about 190 values per byte."""
    import io

    from judgekeeper.readers import inspect_logs

    old = _old_parts()
    base = json.loads(old["samples/1_epoch_1.json"])
    base["metadata"] = {"pad": "PAD"}
    wide = json.dumps(base).encode().replace(b'"PAD"', b"[" + b"0," * 498_999 + b"0]")
    header = json.loads(old["header.json"])
    header["eval"]["dataset"].update(samples=400, sample_ids=list(range(1, 401)))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("_journal/start.json", old["_journal/start.json"])
        for i in range(1, 401):
            z.writestr(f"samples/{i}_epoch_1.json", wide)
        for name in ("summaries.json", "reductions.json"):
            z.writestr(name, old[name])
        z.writestr("header.json", json.dumps(header))
    path = tmp_path / "2026-10-21_qa.eval"
    path.write_bytes(out.getvalue())
    assert path.stat().st_size < 2 * MB
    said, took = _refused(path, monkeypatch)
    assert said == (f"{path} is too big for judgekeeper to read: its samples would unpack to "
                    f"more than {inspect_logs.VALUES_PER_BYTE} values for each byte they pack "
                    "to, the most judgekeeper reads of an Inspect AI log."), said
    assert took < 5


def test_honest_logs_hold_far_fewer_values_per_byte():
    from judgekeeper.readers import inspect_logs

    assert inspect_logs.VALUES_PER_BYTE == 10
    with zipfile.ZipFile(OLD_EVAL) as z, OLD_EVAL.open("rb") as f:
        samples = [p for p in z.infolist() if p.filename.startswith("samples/")]
        values = sum(inspect_logs._unpacks_to(f, p, 10**9)[1] for p in samples)
        packed = sum(p.compress_size for p in samples)
    assert values / packed < inspect_logs.VALUES_PER_BYTE / 20
