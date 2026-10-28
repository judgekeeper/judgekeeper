"""Inspect AI .eval logs that pass each size limit but would still take minutes to read: a
header that names one sample many times, a part whose name zipfile and Inspect AI read
differently, one very long text, and many small samples packed very tightly. Each is refused
(or read once) before Inspect AI reads it. The logs are built here from the real old log."""

from __future__ import annotations

import json
import math
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


TOO_LONG = ("{path} is too big for judgekeeper to read: one text in it is longer than 32 MB, "
            "the most judgekeeper reads in one text of an Inspect AI log.")
SPECIAL = ("{path} is too big for judgekeeper to read: one text in it is over 8 MB and full of "
           "special characters such as \\n or \\\", and judgekeeper reads such a text of an "
           "Inspect AI log only up to 8 MB.")
LONG_TEXTS = ("{path} is too big for judgekeeper to read: its texts over 8 MB add up to more "
              "than 64 MB, the most judgekeeper reads of long texts in one Inspect AI log.")
ESCAPES = ("{path} is too big for judgekeeper to read: its texts over 1 MB hold more than "
           "11,000,000 special characters such as \\n or \\\" together, the most judgekeeper "
           "reads of them in one Inspect AI log.")


def _texts_log(tmp_path, *texts) -> object:
    """The old log with `texts` in its samples' metadata: a list of texts per sample."""
    parts = _old_parts()
    names = sorted(n for n in parts if n.startswith("samples/"))
    for name, held in zip(names, texts, strict=False):
        sample = json.loads(parts[name])
        sample["metadata"] = {f"pad{i}": text for i, text in enumerate(held)}
        parts[name] = json.dumps(sample).encode()
    return _log(tmp_path, parts)


def _png(mb: float) -> str:
    """A screenshot as a data URI of base64, `mb` MB long at most."""
    import base64
    import os

    head = "data:image/png;base64,"
    return head + base64.b64encode(os.urandom((int(mb * MB) - len(head)) // 4 * 3)).decode()


def _lines(mb: float, every: int) -> str:
    """Tool output `mb` MB long, a newline every `every` characters."""
    text = bytearray(_random(int(mb * MB), "0123456789abcdef").encode())
    text[every - 1::every] = b"\n" * len(range(every - 1, len(text), every))
    return text.decode()


def test_the_limits_for_one_long_text():
    from judgekeeper.readers import inspect_logs

    assert inspect_logs.MAX_STRING == 32 * MB
    assert inspect_logs.LONG_TEXT == 8 * MB and inspect_logs.LONG_TEXTS_LIMIT == 64 * MB
    assert inspect_logs.ESCAPE_SPACING == 32
    assert inspect_logs.COUNTED_TEXT == 1 * MB and inspect_logs.ESCAPES_LIMIT == 11_000_000
    assert inspect_logs.COUNTED_TEXT >= inspect_logs.STEP  # such a text spans steps


@pytest.mark.parametrize("field", ["metadata", "events", "attachments"])
def test_one_text_over_32_mb_is_refused_fast(tmp_path, monkeypatch, field):
    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _text_sample(field, _random(33 * MB, "0123456789abcdef"))
    path = _log(tmp_path, parts)
    said, took = _refused(path, monkeypatch)
    assert said == TOO_LONG.format(path=path), said
    assert took < 5


def test_a_screenshot_of_20_mb_is_read(tmp_path):
    pytest.importorskip("inspect_ai")
    from judgekeeper.readers import read_inspect

    path = _texts_log(tmp_path, [_png(20)])
    assert len(read_inspect(path)) == len(read_inspect(OLD_EVAL))


@pytest.mark.parametrize("kind", ["two screenshots", "a newline every 32"])
def test_long_texts_within_the_rules_pass_the_checks(tmp_path, kind):
    """Two long texts of 62 MB together, under the budget; tool output of 32 MB, a newline
    every 32 characters (inspect_ai reads it in about 6 s)."""
    from judgekeeper.readers import inspect_logs

    texts = [[_png(32)], [_png(30)]] if kind == "two screenshots" else [[_lines(32, 32)]]
    inspect_logs._check_unpacked(_texts_log(tmp_path, *texts))


def test_32_mb_with_a_newline_every_8_characters_is_refused(tmp_path, monkeypatch):
    path = _texts_log(tmp_path, [_lines(32, 8)])
    said, took = _refused(path, monkeypatch)
    assert said == SPECIAL.format(path=path), said
    assert took < 5


@pytest.mark.parametrize("mb", [9, 32])
def test_a_long_text_of_special_characters_is_refused_fast(tmp_path, monkeypatch, mb):
    """All escapes: inspect_ai takes about 9 s on 8 MB of them and minutes on 32 MB."""
    path = _texts_log(tmp_path, [_random(mb * MB, "\n\t")])
    said, took = _refused(path, monkeypatch)
    assert said == SPECIAL.format(path=path), said
    assert took < 3


def test_long_texts_over_64_mb_together_are_refused(tmp_path, monkeypatch):
    """Three screenshots of 30 MB in two samples: each passes, together 90 MB."""
    path = _texts_log(tmp_path, [_png(30), _png(30)], [_png(30)])
    said, took = _refused(path, monkeypatch)
    assert said == LONG_TEXTS.format(path=path), said
    assert took < 5


def _texts(mb: float, n: int, chars: str) -> list[str]:
    """`n` different texts of `mb` MB, each made of `chars` at random."""
    one = _random(int(mb * MB), chars)
    return [one[i:] + one[:i] for i in range(n)]


def test_long_texts_of_escapes_over_11_million_together_are_refused_fast(tmp_path,
                                                                         monkeypatch):
    """Escapes only: inspect_ai reads 8 MB of them in about 9 s, 2 MB in about 0.7 s. Seven of
    2 MB (14.7 million escapes) in one sample are refused; five (10.5 million) pass, and so does
    one of 8 MB (8.4 million)."""
    from judgekeeper.readers import inspect_logs

    path = _texts_log(tmp_path, _texts(2, 7, "\n\t"))
    said, took = _refused(path, monkeypatch)
    assert said == ESCAPES.format(path=path), said
    assert took < 3
    inspect_logs._check_unpacked(_texts_log(tmp_path, _texts(2, 5, "\n\t")))
    inspect_logs._check_unpacked(_texts_log(tmp_path, _texts(8, 1, "\n\t")))
    path = _texts_log(tmp_path, _texts(2, 4, "\n\t"), _texts(2, 3, "\n\t"))  # across samples
    assert _refused(path, monkeypatch)[0] == ESCAPES.format(path=path)


def _json_output(mb: float, seed: int) -> str:
    """An API response dumped as indented JSON, `mb` MB of it: kept in a log as a string, it
    holds an escape (\\" or \\n) every 6 or 7 characters."""
    import os
    import random

    rnd, items, text = random.Random(seed), [], ""
    while len(text) < mb * MB:
        items.extend({"id": rnd.randrange(10**9), "name": os.urandom(5).hex(),
                      "ok": rnd.random() < 0.5, "tags": [os.urandom(3).hex() for _ in range(3)],
                      "score": round(rnd.random(), 4), "note": os.urandom(12).hex()}
                     for _ in range(500))
        text = json.dumps({"data": items, "next": None}, indent=2)
    return text[:int(mb * MB)]


def test_twenty_json_outputs_of_1_5_mb_pass(tmp_path):
    """About 4.8 million escapes; inspect_ai reads them in about 1.6 s."""
    from judgekeeper.readers import inspect_logs

    outputs = [_json_output(1.5, i) for i in range(20)]
    inspect_logs._check_unpacked(_texts_log(tmp_path, outputs[:10], outputs[10:]))


def test_many_tool_outputs_with_a_newline_on_every_line_pass(tmp_path):
    """60 outputs of 1 MB, a newline every 80 characters; 100 of 100 KB that are all escapes:
    under 1 MB, they are never counted."""
    from judgekeeper.readers import inspect_logs

    outputs = [_lines(1, 80)[i:] for i in range(60)]
    inspect_logs._check_unpacked(_texts_log(tmp_path, outputs[:30], outputs[30:]))
    inspect_logs._check_unpacked(_texts_log(tmp_path, _texts(0.1, 100, "\n\t")))


def test_escapes_count_as_the_characters_they_stand_for(tmp_path, monkeypatch):
    """33 MB of plain text with escapes in it (\\n, \\t) is over the limit, as 33 MB of
    characters; 4 MB with \\u00e9 in it (about 14 MB in the file) is under it, and so is 8 MB
    of escapes, as before."""
    from judgekeeper.readers import inspect_logs

    parts = _old_parts()
    parts["samples/1_epoch_1.json"] = _text_sample("metadata", _lines(33, 64))
    said, _ = _refused(_log(tmp_path, parts), monkeypatch)
    assert "one text in it is longer than 32 MB" in said, said
    parts["samples/1_epoch_1.json"] = _text_sample("metadata", _random(4 * MB, "é\t"))
    assert len(parts["samples/1_epoch_1.json"]) > 12 * MB
    inspect_logs._check_unpacked(_log(tmp_path, parts))
    inspect_logs._check_unpacked(_texts_log(tmp_path, [_random(8 * MB, "\n\t")]))


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


@pytest.mark.parametrize("step", [1, 2, 3, 7, 19])
def test_long_texts_are_judged_alike_however_the_bytes_are_split(monkeypatch, step):
    """With small limits (a long text: over 20 characters, one escape per 4 at most, 45 in
    all): each step under LONG_TEXT, as STEP is under it."""
    from judgekeeper.readers import inspect_logs

    monkeypatch.setattr(inspect_logs, "LONG_TEXT", 20)
    monkeypatch.setattr(inspect_logs, "COUNTED_TEXT", 20)  # no escapes counted here
    monkeypatch.setattr(inspect_logs, "ESCAPE_SPACING", 4)

    def fed(strings, long_left=math.inf):
        depth = inspect_logs._Depth(long_left=long_left)
        text = json.dumps({"a": "short", "b": strings}).encode()
        for at in range(0, len(text), step):
            depth.feed(text[at:at + step])
        return depth.long

    assert fed(["x" * 24 + "\n" * 6]) == 30  # 6 escapes in 30: one per 5
    with pytest.raises(inspect_logs.TooSpecial):
        fed(["x" * 20 + "\n" * 10])  # 10 in 30
    with pytest.raises(inspect_logs.TooSpecial):
        fed(["\\" * 100])  # all escapes: refused before its end
    assert fed(["y" * 25, "z" * 19, "\n" * 19]) == 25  # short ones are never counted
    with pytest.raises(inspect_logs.TooManyLong):
        fed(["y" * 25, "z" * 25], long_left=45)


@pytest.mark.parametrize("step", [1, 2, 3, 7, 9])
def test_escapes_are_counted_alike_however_the_bytes_are_split(monkeypatch, step):
    """With a small limit (a text counted: over 10 characters): each step under COUNTED_TEXT,
    as STEP is not over it."""
    from judgekeeper.readers import inspect_logs

    monkeypatch.setattr(inspect_logs, "COUNTED_TEXT", 10)

    def fed(strings, escapes_left=math.inf):
        depth = inspect_logs._Depth(escapes_left=escapes_left)
        text = json.dumps({"a": "short", "b": strings}).encode()
        for at in range(0, len(text), step):
            depth.feed(text[at:at + step])
        return depth.counted

    assert fed(["x" * 12 + "\n" * 3, "\n" * 10]) == 3  # 10 long is not over it
    assert fed(["x" * 8 + '"' * 4, "\t" * 11]) == 15
    with pytest.raises(inspect_logs.TooManyEscapes):
        fed(["x" * 8 + '"' * 4, "\t" * 11], escapes_left=14)


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


# Ctrl-C while samples are read ------------------------------------------------------------------

def test_quiet_silences_inspect_and_asyncio():
    import logging

    from judgekeeper.readers.inspect_logs import quiet

    with quiet():
        for name in ("inspect_ai", "asyncio"):
            assert not logging.getLogger(name).isEnabledFor(logging.ERROR), name
    assert logging.getLogger("asyncio").level == logging.NOTSET


@pytest.mark.skipif(__import__("os").name == "nt", reason="Ctrl-C can't be sent this way")
def test_ctrl_c_while_samples_are_read_says_only_stopped(tmp_path):
    """300 samples that take Inspect AI seconds to read; Ctrl-C a second into the read."""
    import os
    import signal
    import subprocess
    import sys
    from pathlib import Path

    pytest.importorskip("inspect_ai")
    old = _old_parts()
    base = json.loads(old["samples/1_epoch_1.json"])
    header = json.loads(old["header.json"])
    header["eval"]["dataset"].update(samples=300, sample_ids=list(range(1, 301)))
    parts = {"_journal/start.json": old["_journal/start.json"]}
    for i in range(1, 301):
        sample = dict(base, id=i, metadata={"fill": os.urandom(10_000).hex(), "pad": [0] * 30_000})
        parts[f"samples/{i}_epoch_1.json"] = json.dumps(sample)
    parts.update({name: old[name] for name in ("summaries.json", "reductions.json")})
    parts["header.json"] = json.dumps(header)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-10-21_qa.eval").write_bytes(_zipped(parts))
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = dict(os.environ, PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.Popen([sys.executable, "-u", "-m", "judgekeeper", "--no-browser", "--yes"],
                         cwd=tmp_path, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:  # reading starts after the step's name
            if line.startswith("Step 1 of 5: Find"):
                break
        time.sleep(1)
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=120)
    finally:
        p.kill()
    assert p.returncode == 130, out + err
    assert "Stopped." in out
    assert "Task exception" not in err and "RuntimeError" not in err, err
