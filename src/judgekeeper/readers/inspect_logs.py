"""Inspect AI: `.eval` or `.json` logs.

With the `inspect` extra any log is read with inspect_ai, a `.eval` log one sample at a time,
so a log of a million samples fits in memory. Without it `.json` logs are read directly; a
`.eval` log is a zip and needs the extra.

- Item id is `samples[].id`; run is `samples[].epoch`. The conversation is kept as the
  record's `trajectory`, in a form that is the same with or without inspect_ai.
- A score whose value is a dict is one LLM-as-a-judge per key, named `<scorer>.<key>`.
- The prompt hash covers the scorer's `template` and `instructions`, or Inspect's defaults.
- `C`/`I` read as pass/fail; anything else needs --label-map. Code scorers (CODE_SCORERS) are
  not judges.
- A grader reply with no grade, or a sample that errored before scoring, is marked for the
  judge check. In a score's `history`, the first value is the judge's and an edit the human's.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from itertools import accumulate, pairwise
from pathlib import Path

from judgekeeper.anchors import canonical_json
from judgekeeper.records import (
    CODE,
    HUMAN,
    LLM,
    NESTED,
    Mark,
    RecordList,
    RecordsError,
    ScoreRecord,
    all_damaged,
    damaged,
    derive_record_id,
    load_json,
    read_rows,
)
from judgekeeper.textio import MAX_NESTING, error_type, get_extra, read_json

DEFAULT_LABELS = {"C": "pass", "I": "fail"}
# Inspect's scorers that check text in code, never with a model: not judges, left out
CODE_SCORERS = frozenset({"match", "includes", "exact", "pattern", "f1", "answer"})
# Stands in for a template or instructions the scorer leaves at Inspect's default.
DEFAULT_PROMPT = "inspect_ai default for {name}"
EVAL_NEEDS_EXTRA = ("{path}: reading .eval logs needs inspect_ai. To read it, {get}; or run "
                    "`inspect log dump {path} > log.json` first and read the .json.")


GRADER_FAILED = "grader_failed"
NO_GRADE = "Grade not found in model output"
SAMPLE_ERROR = "sample_error"  # judgekeeper's own reason: the sample errored, no score


def _sample_error(error) -> dict:
    """A stand-in score for a sample that errored before it was scored."""
    message = error.get("message") if isinstance(error, dict) else error
    return {"value": None, "reason": SAMPLE_ERROR, "explanation": error_type(message)}


def _mark(score: dict, label) -> Mark:
    """What the judge check needs to know about one score (see the module docstring)."""
    unscored = score.get("reason") == SAMPLE_ERROR or GRADER_FAILED in (
        score.get("reason"), (score.get("metadata") or {}).get("unscored_reason"))
    explanation = score.get("explanation")
    no_grade = isinstance(explanation, str) and explanation.startswith(NO_GRADE)
    problem = ("not_scored" if score.get("reason") == SAMPLE_ERROR else "unreadable" if no_grade
               else "error" if unscored else None)
    counted = "left out" if unscored else DEFAULT_LABELS.get(label)  # C or I
    return Mark(problem=problem, tool_counted_as=counted if problem else None)


@contextmanager
def quiet() -> Iterator[None]:
    """Around inspect_ai's reading: its loggers show only CRITICAL (a log it cannot read is
    said here, in plain words, never with its text). Put back afterwards."""
    logger = logging.getLogger("inspect_ai")
    level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(level)


# What judgekeeper reads of a sample (and of its output, the completion only).
SAMPLE_FIELDS = {"id": True, "epoch": True, "input": True, "target": True,
                 "output": {"completion"}, "messages": True, "scores": True, "error": True}
WHOLE_LIMIT = 500 * 2**20  # bytes: the biggest .eval log read whole (no sample reader)
TOO_BIG = ("{path} is {size}. This Inspect AI version reads a log whole, so judgekeeper reads "
           "Inspect logs up to {limit} with it. Update Inspect AI (it then reads one sample at "
           "a time), or run your eval on fewer samples.")


# bytes: one sample of a .eval log unpacked, its events included. Far above real samples, so
# only a damaged or crafted log reaches it (inspect_ai unpacks a sample whole).
SAMPLE_LIMIT = 200 * 2**20
# The parts of a .eval log that stay small however many samples it holds; the others (samples
# aside) grow with them: summaries.json, reductions.json, _journal/summaries/...
HEADER_PARTS = frozenset({"header.json", "_journal/start.json"})
HEADER_LIMIT = 50 * 2**20  # bytes: one of HEADER_PARTS unpacked
# values (a comma or an opening bracket) in one part: inspect_ai takes GBs to read a few KB
# that unpack to `[0,0,...]` with millions of zeros. A part that grows with the samples may
# hold VALUES_PER_SAMPLE more per sample in the log.
VALUE_LIMIT = 2_000_000
VALUES_PER_SAMPLE = 1_000
UNPACKS_TOO_BIG = ("{path} is too big for judgekeeper to read: it would unpack to more than "
                   "{limit} for {part}, the most judgekeeper reads for {part} of an Inspect AI "
                   "log.")
# The whole log: all its samples unpacked together (bytes), and the values in all its parts.
# Each part on its own passing its limit, a few KB could still name millions of values.
SAMPLES_LIMIT = 4 * 2**30
ALL_VALUES_LIMIT = 200_000_000
ALL_TOO_BIG = ("{path} is too big for judgekeeper to read: it would unpack to more than "
               "{limit} in all, the most judgekeeper reads of one Inspect AI log.")
# A sample unpacks to at most PACKED_RATIO times its packed size (honest ones: under 30), once
# past RATIO_FLOOR bytes: so what is read grows with the file, never 1,000 times over. Not the
# summaries and reductions: their repeats pack 100 to 200 times, and they have their limits.
PACKED_RATIO = 200
RATIO_FLOOR = 2**20
PACKED_TOO_TIGHT = ("{path} is too big for judgekeeper to read: one sample would unpack to "
                    "more than {ratio} times its packed size, the most judgekeeper reads for "
                    "one sample of an Inspect AI log.")
STEP = 2**20  # bytes unpacked at a time while a part of a .eval log is counted
ZSTD = 93  # zstd's number as a zip compression method: inspect_ai's own


def _size(n: int) -> str:
    for unit, step in (("GB", 2**30), ("MB", 2**20), ("KB", 2**10)):
        if n >= step:
            return f"{n / step:.1f}".removesuffix(".0") + f" {unit}"
    return f"{n} bytes"


class _Packed:
    """The packed bytes of one zip part, read a step at a time."""

    def __init__(self, f, left: int):
        self.f, self.left = f, left

    def read(self, n: int = -1) -> bytes:
        data = self.f.read(self.left if n is None or n < 0 else min(n, self.left))
        self.left -= len(data)
        return data


# In a part's JSON: an escape in a string (its backslash and the byte after it); the bytes that
# are no list or object bracket; how each bracket changes the depth
_ESCAPE = re.compile(rb"\\.", re.DOTALL)
_NOT_BRACKETS = bytes(b for b in range(256) if b not in b"[]{}")
_DEPTH_STEP = tuple(1 if b in b"[{" else -1 if b in b"]}" else 0 for b in range(256))


class TooDeep(ValueError):
    """A part of a .eval log nests lists and objects deeper than MAX_NESTING."""


class TooWide(ValueError):
    """A part of a .eval log holds more values than it may."""


class _Depth:
    """How deep the lists and objects of JSON text go, and how many values it holds, fed a step
    at a time, with regex and bytes methods only: escapes are taken out, the text between
    quotes (the strings) left out, and the brackets left added up; commas and opening brackets
    count as values. Whether a string, or an escape, goes on into the next step is carried.
    TooDeep once past MAX_NESTING, TooWide once past `values` values."""

    def __init__(self, values: float = math.inf):
        self.depth, self.in_string, self.escaped = 0, False, False
        self.values, self.most_values = 0, values

    def feed(self, text: bytes) -> None:
        if self.escaped:  # the step before ended on a backslash: this byte is escaped
            text, self.escaped = text[1:], False
        if b"\\" in text:
            text = _ESCAPE.sub(b"", text)
            if text.endswith(b"\\"):  # its byte is in the next step
                text, self.escaped = text[:-1], True
        pieces = text.split(b'"')  # inside and outside strings in turn
        outside = b"".join(pieces[1 if self.in_string else 0::2])
        self.in_string ^= len(pieces) % 2 == 0
        brackets = outside.translate(None, _NOT_BRACKETS)
        opens = brackets.count(b"[") + brackets.count(b"{")
        if self.depth + opens > MAX_NESTING and max(accumulate(
                map(_DEPTH_STEP.__getitem__, brackets), initial=self.depth)) > MAX_NESTING:
            raise TooDeep("nested too deep")
        self.depth += 2 * opens - len(brackets)
        self.values += opens + outside.count(b",")
        if self.values > self.most_values:
            raise TooWide("too many values")


def _unpacks_to(f, part, most: int, values: float = math.inf) -> tuple[int, int]:
    """How many bytes the zip `part` unpacks to and how many values it holds, counted by
    unpacking it STEP bytes at a time and keeping none; the count stops once past `most`.
    What it unpacks to is also looked at for how deep it nests (_Depth): TooDeep past
    MAX_NESTING, as inspect_ai would take many GB to read a few KB nested 100,000 deep, and
    TooWide past `values`. Never through zipfile.open(): for zstd it unpacks a whole chunk at once, and it
    trusts the size the zip declares. ValueError for a part inspect_ai never writes: another
    compression, or encrypted."""
    import struct
    import zipfile
    import zlib

    f.seek(part.header_offset)
    head = f.read(30)
    if len(head) < 30 or head[:4] != b"PK\x03\x04" or part.flag_bits & 1:
        raise ValueError("not a part of an Inspect AI log")
    name, extra = struct.unpack_from("<HH", head, 26)
    f.seek(part.header_offset + 30 + name + extra)
    packed, n, depth = _Packed(f, part.compress_size), 0, _Depth(values)
    if part.compress_type == zipfile.ZIP_STORED:  # kept as it is: its size is what it holds
        while n <= most and (out := packed.read(STEP)):
            n += len(out)
            depth.feed(out)
        return n, depth.values
    if part.compress_type == zipfile.ZIP_DEFLATED:
        unpack = zlib.decompressobj(-15)
        while n <= most and not unpack.eof:
            data = unpack.unconsumed_tail or packed.read(STEP)
            out = unpack.decompress(data, STEP)
            if not data and not out:
                break
            n += len(out)
            depth.feed(out)
        if n <= most and not unpack.eof:  # the packed data goes on past where the part ends
            raise ValueError("packed data cut short")
        return n, depth.values
    if part.compress_type == ZSTD:
        import zstandard

        reader = zstandard.ZstdDecompressor().stream_reader(
            packed, read_size=STEP, read_across_frames=True, closefd=False)
        while n <= most and (out := reader.read(STEP)):
            n += len(out)
            depth.feed(out)
        return n, depth.values
    raise ValueError("not a compression inspect_ai writes")


def _what(name: str) -> str:
    return "one sample" if name.startswith("samples/") else "the header"


def _too_big(path: Path, sizes, whole: bool) -> None:
    """RecordsError at the first of `sizes` (part name, its bytes unpacked) that passes a
    limit: one of HEADER_PARTS HEADER_LIMIT, the other header parts (they grow with the
    samples) together WHOLE_LIMIT, one sample SAMPLE_LIMIT, all samples together
    SAMPLES_LIMIT, and with `whole` (a log read whole) all of it WHOLE_LIMIT."""
    growing = total = samples = 0
    for name, n in sizes:
        total += n
        if whole and total > WHOLE_LIMIT:
            raise RecordsError(TOO_BIG.format(path=path, size=f"more than {_size(WHOLE_LIMIT)} "
                                              "unpacked", limit=_size(WHOLE_LIMIT)))
        if name.startswith("samples/"):
            samples += n
            size, limit = n, SAMPLE_LIMIT
        elif name in HEADER_PARTS:
            size, limit = n, HEADER_LIMIT
        else:
            growing += n
            size, limit = growing, WHOLE_LIMIT
        if size > limit:
            raise RecordsError(UNPACKS_TOO_BIG.format(path=path, part=_what(name),
                                                      limit=_size(limit)))
        if samples > SAMPLES_LIMIT:
            raise RecordsError(ALL_TOO_BIG.format(
                path=path, limit=f"{_size(SAMPLES_LIMIT)} of samples"))


EOCD, EOCD64, LOCATOR = b"PK\x05\x06", b"PK\x06\x06", b"PK\x06\x07"  # zip end records


def _one_table(f, parts) -> bool:
    """Whether every zip reader finds the same table of contents (central directory) in the
    zip `f`, and so the same `parts`. zipfile looks for it right before the end record and
    moves every offset by how far that is from where the end record says; inspect_ai takes
    the end record as written. So: the end record ends the file, with no comment; a zip64 end
    record sits right before it, saying the same; the table ends right where these start, at
    the place they name; and the first part starts the file."""
    import struct

    size = f.seek(0, 2)
    if size < 22:
        return False
    f.seek(size - 22)
    sig, disk, start, here, count, length, offset, comment = struct.unpack("<4s4H2LH", f.read(22))
    if sig != EOCD or disk or start or comment or here != count:
        return False
    end, zip64 = size - 22, False
    if end >= 76:
        f.seek(end - 20)
        sig, disk, at, disks = struct.unpack("<4sLQL", f.read(20))
        zip64 = sig == LOCATOR
    if zip64:
        if disk or disks != 1 or at != end - 76:
            return False
        f.seek(at)
        sig, record, _, _, disk, start, here, *big = struct.unpack("<4sQ2H2L4Q", f.read(56))
        if sig != EOCD64 or record != 44 or disk or start or here != big[0] or any(
                small not in (wide, full) for small, wide, full in zip(
                    (count, length, offset), big, (0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF), strict=True)):
            return False
        (count, length, offset), end = big, at
    elif count == 0xFFFF or 0xFFFFFFFF in (length, offset):
        return False
    return offset + length == end and count == len(parts) and min(
        (p.header_offset for p in parts), default=offset) == 0


ZIP64 = 0x0001  # the extra field that holds a part's sizes when they don't fit in 4 bytes


def _one_zip64(extra: bytes) -> bool:
    """Whether a part's extra fields give its sizes one way: at most one zip64 field, and no
    size in it of 0xFFFFFFFF (the mark that says look in the zip64 field). zipfile takes the
    last zip64 field, inspect_ai the first: with two, each would read the part to a different
    end."""
    import struct

    seen, at = 0, 0
    while at + 4 <= len(extra):
        kind, size = struct.unpack_from("<HH", extra, at)
        if kind == ZIP64:
            seen += 1
            body = extra[at + 4:at + 4 + size]
            if seen > 1 or 0xFFFFFFFF in struct.unpack_from(f"<{len(body) // 8}Q", body):
                return False
        at += 4 + size
    return True


def _apart(f, parts, table: int) -> bool:
    """Whether each of `parts` has its own bytes: from its local header to the end of its
    packed data, no part runs into the next one, nor into the table of contents at `table`.
    Else one stored part could be read under many names. A name may repeat with bytes of its
    own: inspect_ai writes a requeued sample again under its name and reads the last. Bytes
    no part lists may sit between parts: inspect_ai leaves an edited header's old bytes. Each
    part says its sizes one way only (_one_zip64)."""
    import struct

    spans = []
    for p in parts:
        f.seek(p.header_offset)
        head = f.read(30)
        if len(head) < 30 or head[:4] != b"PK\x03\x04":
            return False
        name, extra = struct.unpack_from("<HH", head, 26)
        f.seek(p.header_offset + 30 + name)
        if not (_one_zip64(p.extra) and _one_zip64(f.read(extra))):
            return False
        spans.append((p.header_offset, p.header_offset + 30 + name + extra + p.compress_size))
    return all(end <= after for (_, end), (after, _) in pairwise(sorted(spans) + [(table, 0)]))


def _check_unpacked(path: Path, whole: bool = False, samples: bool = True) -> dict[str, int]:
    """Refuse a .eval log (a zip) that zipfile can't open, or where it and inspect_ai could
    find different parts (_one_table), or whose parts share bytes (_apart), or whose
    parts unpack too big (_too_big) or hold too many values, each or all together, before
    inspect_ai reads it: first by the sizes the zip declares, then by what each part really
    unpacks to (_unpacks_to), as a zip can declare any size. A sample may also unpack to at
    most PACKED_RATIO times its packed size. Nothing unpacked is kept, so memory stays low.
    `samples=False`: the header parts only. Returns what each part really unpacks to, by name
    (a repeated name: its last part, the one inspect_ai reads)."""
    import zipfile

    unreadable = damaged(path, "Inspect AI", "can't be read: it may be cut short, or not an "
                                             "Inspect AI log")
    try:
        with zipfile.ZipFile(path) as z, path.open("rb") as f:
            parts = z.infolist()
            if not _one_table(f, parts) or not _apart(f, parts, z.start_dir):
                raise unreadable
    except (OSError, ValueError, zipfile.BadZipFile):
        raise unreadable from None
    n_samples = sum(p.filename.startswith("samples/") for p in parts)
    parts = [p for p in parts if samples or not p.filename.startswith("samples/")]
    _too_big(path, ((p.filename, p.file_size) for p in parts), whole)

    sizes: dict[str, int] = {}

    def unpacked(f):
        all_values = sample_bytes = 0
        for p in parts:
            sample = p.filename.startswith("samples/")
            most, values = (
                (min(SAMPLE_LIMIT, SAMPLES_LIMIT - sample_bytes), VALUE_LIMIT) if sample
                else (HEADER_LIMIT, VALUE_LIMIT) if p.filename in HEADER_PARTS
                else (WHOLE_LIMIT, VALUE_LIMIT + VALUES_PER_SAMPLE * n_samples))
            tight = max(PACKED_RATIO * p.compress_size, RATIO_FLOOR) if sample else math.inf
            left = ALL_VALUES_LIMIT - all_values
            try:
                n, counted = _unpacks_to(f, p, min(most, tight), min(values, left))
            except TooWide:
                if left < values:
                    raise RecordsError(ALL_TOO_BIG.format(
                        path=path, limit=f"{ALL_VALUES_LIMIT:,} values")) from None
                raise RecordsError(UNPACKS_TOO_BIG.format(path=path, part=_what(p.filename),
                                                          limit=f"{values:,} values")) from None
            if n > tight and tight < most:
                raise RecordsError(PACKED_TOO_TIGHT.format(path=path, ratio=PACKED_RATIO))
            all_values += counted
            sample_bytes += n if sample else 0
            sizes[p.filename] = n
            yield p.filename, n

    try:
        with path.open("rb") as f:
            _too_big(path, unpacked(f), whole)
    except RecordsError:
        raise
    except TooDeep:
        raise damaged(path, "Inspect AI", NESTED) from None
    except Exception:  # noqa: BLE001 - a part that can't be unpacked: never read
        raise unreadable from None
    return sizes


# A sample's part in a .eval log: samples/{id}_epoch_{epoch}.json, as inspect_ai names it
_SAMPLE_PART = re.compile(r"samples/(.+)_epoch_([1-9][0-9]{0,9})\.json", re.DOTALL)
# Samples asked of inspect_ai at once: so many, or so many bytes unpacked together
BATCH, BATCH_BYTES = 100, 64 * 2**20


def _held(spec: dict, sizes: dict[str, int]) -> list[tuple[str | int, int]]:
    """(id, epoch) of each sample the log holds a part for, in the order inspect_ai reads
    them: by the ids the header lists, then by epoch up to the header's epochs. Only parts
    that are there: inspect_ai would ask for every id in every epoch the header names, a
    billion epochs in a 7 KB log."""
    dataset, config = spec.get("dataset") or {}, spec.get("config") or {}
    ids, most = dataset.get("sample_ids"), config.get("epochs") or 1
    if not isinstance(ids, list):
        raise TypeError("no sample ids")
    epochs: dict[str, list[int]] = {}
    for name in sizes:
        if m := _SAMPLE_PART.fullmatch(name):
            epochs.setdefault(m[1], []).append(int(m[2]))
    return [(i, epoch) for i in ids for epoch in sorted(epochs.get(str(i), ())) if epoch <= most]


def _batches(wanted, sizes: dict[str, int]):
    """`wanted` in lists of up to BATCH samples, BATCH_BYTES unpacked together (one more when
    a single sample is bigger)."""
    batch, held = [], 0
    for i, epoch in wanted:
        n = sizes.get(f"samples/{i}_epoch_{epoch}.json", 0)
        if batch and (len(batch) == BATCH or held + n > BATCH_BYTES):
            yield batch
            batch, held = [], 0
        batch.append((i, epoch))
        held += n
    if batch:
        yield batch


def _by_sample(path: Path, read_eval_log, read_by_id, read_one, sizes: dict[str, int]) -> dict:
    """A .eval log as its header and its samples: only the samples it holds parts for
    (_held), read in small batches with `read_by_id` (or one at a time with `read_one`) as
    they are gone through, once, each kept to SAMPLE_FIELDS and let go once used."""
    import inspect

    data = read_eval_log(str(path), header_only=True).model_dump(mode="json",
                                                                exclude={"samples"})
    wanted = _held(data.get("eval") or {}, sizes)
    reader = read_by_id or read_one
    options = {}
    try:
        if "exclude_fields" in inspect.signature(reader).parameters:
            options["exclude_fields"] = {"events", "attachments", "store"}
    except (TypeError, ValueError):
        pass

    def read(batch):
        if read_by_id is not None:
            return read_by_id(str(path), batch, **options)
        return [read_one(str(path), id=i, epoch=epoch, **options) for i, epoch in batch]

    def samples() -> Iterator[dict]:
        try:
            with quiet():
                for batch in _batches(wanted, sizes):
                    got = read(batch)
                    got.reverse()
                    while got:
                        yield got.pop().model_dump(mode="json", include=SAMPLE_FIELDS)
        except Exception:  # noqa: BLE001 - a sample cut short or not Inspect's
            raise damaged(path, "Inspect AI", "can't be read: it may be cut short, or not "
                                              "an Inspect AI log") from None

    data["samples"] = samples()
    return data


def _load(path: Path) -> dict:
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        read_eval_log = None
    if read_eval_log is not None:
        from inspect_ai import log as inspect_log

        read_by_id = getattr(inspect_log, "read_eval_log_samples_by_id", None)
        read_one = getattr(inspect_log, "read_eval_log_sample", None)
        by_sample = read_by_id is not None or read_one is not None
        is_eval = path.suffix.lower() == ".eval"
        if is_eval and not by_sample:
            size = path.stat().st_size
            if size > WHOLE_LIMIT:
                raise RecordsError(TOO_BIG.format(path=path, size=_size(size),
                                                  limit=_size(WHOLE_LIMIT)))
        if is_eval:
            sizes = _check_unpacked(path, whole=not by_sample)
        try:
            with quiet():
                if is_eval and by_sample:
                    return _by_sample(path, read_eval_log, read_by_id, read_one, sizes)
                return read_eval_log(str(path)).model_dump(mode="json")
        except Exception:  # noqa: BLE001 - a log cut short, empty or not Inspect's
            if is_eval:
                raise damaged(path, "Inspect AI", "can't be read: it may be cut short, or not "
                                                  "an Inspect AI log") from None
            # a .json log inspect_ai refuses is read as without it: the same checks and words
    elif path.suffix.lower() == ".eval":
        raise RecordsError(EVAL_NEEDS_EXTRA.format(path=path, get=get_extra("inspect")))
    return load_json(path, "Inspect AI")


EVAL_DAMAGED = "can't be read: its eval part is damaged"


def eval_header(path: str | Path) -> dict:
    """The log's `eval` part (task_file, model, model_roles, ...), or {} when it cannot be
    read. With inspect_ai, only the header is read; without it, or when it refuses a .json log,
    a .json log as JSON."""
    path = Path(path)
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        read_eval_log = None
    spec = None
    if read_eval_log is not None:
        try:
            if path.suffix.lower() == ".eval":
                _check_unpacked(path, samples=False)
            with quiet():
                spec = read_eval_log(str(path), header_only=True).eval.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - Inspect's own errors: the header only shapes advice
            if path.suffix.lower() == ".eval":
                return {}
    elif path.suffix.lower() == ".eval":
        return {}
    if spec is None:
        try:
            spec = read_json(path, RecordsError).get("eval")
        except (OSError, ValueError, AttributeError, RecordsError):
            return {}
    return spec if isinstance(spec, dict) else {}


def _model(config) -> tuple[str | None, float | None]:
    if isinstance(config, list):
        models = [c.get("model") for c in config if isinstance(c, dict)]
        temps = {(c.get("config") or {}).get("temperature") for c in config
                 if isinstance(c, dict)}
        return "+".join(sorted(m for m in models if m)) or None, (
            temps.pop() if len(temps) == 1 else None)
    if isinstance(config, dict):
        return config.get("model"), (config.get("config") or {}).get("temperature")
    if isinstance(config, str):
        return config, None
    return None, None


def _text(content):
    """A message's content as text: text parts joined; None when there is no text."""
    if isinstance(content, str) or content is None:
        return content
    if isinstance(content, list):
        texts = [p["text"] for p in content if isinstance(p, dict)
                 and p.get("type") == "text" and isinstance(p.get("text"), str)]
        return "\n".join(texts) if texts else None
    return None


def _step(message: dict) -> dict:
    step = {"role": str(message.get("role") or "unknown"), "content": _text(message.get("content"))}
    calls = [{"id": c.get("id"), "name": str(c.get("function") or c.get("name") or "unknown"),
              "arguments": c.get("arguments")}
             for c in message.get("tool_calls") or [] if isinstance(c, dict)]
    if calls:
        step["tool_calls"] = calls
    if isinstance(message.get("tool_call_id"), str):
        step["tool_call_id"] = message["tool_call_id"]
    return step


def trajectory(sample: dict) -> list[dict] | None:
    """A sample's messages as OpenAI-style steps, or None when it has none."""
    messages = [m for m in sample.get("messages") or [] if isinstance(m, dict)]
    return [_step(m) for m in messages] or None


_NAMED_MODEL = re.compile(r"\s\(([A-Za-z][\w.:@-]*(?:/[\w.:@-]+)*)\)\Z")
_MODEL_KEYS = ("grader_model", "judge_model", "model", "grader")


def _model_said(name: str, score: dict) -> str | None:
    """The grader's model when the log has no grader role: in the score's metadata, or after
    the scorer's name as R's vitals package writes it (`model_graded_qa() (claude-sonnet-4-5)`).
    A word in brackets is a model only when it looks like one (a digit and a - . or /)."""
    metadata = score.get("metadata")
    for key in _MODEL_KEYS:
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    m = _NAMED_MODEL.search(name or "")
    if m and re.search(r"\d", m[1]) and re.search(r"[-./]", m[1]):
        return m[1]
    return None


def sample_key(sample: dict) -> str:
    """The id `start` gives this sample's answer: its input, output and steps."""
    return derive_record_id(sample.get("input"), (sample.get("output") or {}).get("completion"),
                            trajectory(sample))


def _value(v) -> tuple[object, float | None]:
    """(label, score) from a score value."""
    if isinstance(v, bool):
        return ("pass" if v else "fail"), None
    if isinstance(v, int | float):
        return None, None if math.isnan(v) else float(v)
    if isinstance(v, str):
        return v, None
    return None, None  # dict or list values: no single verdict


def scorer_prompt(name: str, options: dict) -> str:
    """The grading prompt's identity: the scorer's template and instructions from
    `eval.scorers[].options`, each standing in as Inspect's default for that scorer when unset.

    Never the rendered prompt in `score.metadata.grading`: it holds each sample's text, so its
    hash would differ per sample. With default instructions, `partial_credit` changes them.
    """
    default = DEFAULT_PROMPT.format(name=name)
    parts = {"template": options.get("template") or default,
             "instructions": options.get("instructions") or default}
    if not options.get("instructions") and options.get("partial_credit"):
        parts["partial_credit"] = True
    return canonical_json(parts)


def _human_edit(score: dict) -> tuple[dict, dict] | None:
    """(original, last human edit) when the score was edited by a named author."""
    history = [h for h in score.get("history") or [] if isinstance(h, dict)]
    edits = [h for h in history if (h.get("provenance") or {}).get("author")]
    if not history or not edits or history[0].get("provenance"):
        return None
    return history[0], edits[-1]


STOPPED = "Your Inspect run stopped early"  # how its note starts


def stopped_early(data: dict) -> str | None:
    """A note when the log's run did not finish (status error or cancelled): how far it got,
    and the type and count of the errors, never their text (an error Inspect saves can hold
    the eval's prompt and request); else None."""
    samples = [s for s in data.get("samples") or [] if isinstance(s, dict)]
    return _stopped(data, len(samples), Counter(filter(None, map(_error_kind, samples))))


def _error_kind(sample: dict) -> str | None:
    """The type of the error a sample stopped on, or None."""
    error = sample.get("error")
    if not error:
        return None
    return error_type(error.get("message") if isinstance(error, dict) else error)


def _stopped(data: dict, samples: int, errored: Counter) -> str | None:
    """stopped_early, from the log's header, how many samples it holds and their errors."""
    status = data.get("status")
    if status not in ("error", "cancelled"):
        return None
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    total = (results.get("total_samples")
             or ((data.get("eval") or {}).get("dataset") or {}).get("samples"))
    done = results.get("completed_samples")
    if not isinstance(done, int) or isinstance(done, bool):
        done = samples - sum(errored.values())
    far = f"{done} of {total} samples" if isinstance(total, int) and total else f"{done} samples"
    if status == "cancelled":
        return f"{STOPPED} ({far}): it was cancelled."
    if errored:
        kinds = ", ".join(f"{kind} on {n} sample{'' if n == 1 else 's'}"
                          for kind, n in errored.most_common())
        return f"{STOPPED} ({far}): {kinds}."
    return f"{STOPPED} ({far}): {error_type((data.get('error') or {}).get('message'))}."


def read_inspect(path: str | Path, with_errors: bool = False) -> RecordList:
    """ScoreRecords from one Inspect AI log: one LLM record per scorer per sample and epoch.
    `with_errors`: also one record per scorer for a sample that errored before it was scored
    (see the module docstring). The samples are gone through once, in order, and each let go
    once its records are made."""
    path = Path(path)
    data = _load(path)
    samples = data.get("samples") if isinstance(data, dict) else None
    try:
        return _read(path, data, samples, with_errors)
    finally:
        if isinstance(samples, Iterator):
            samples.close()


def _read(path: Path, data, samples, with_errors: bool) -> RecordList:
    spec = data.get("eval") if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        raise damaged(path, "Inspect AI", EVAL_DAMAGED if isinstance(data, dict) and "eval" in data
                      else "is not an Inspect AI log (no eval)")
    no_samples = RecordsError(f"{path}: the log has no samples (was it written with "
                              "--no-log-samples?)")
    if not isinstance(samples, list | Iterator) or samples == []:
        raise no_samples
    created_at = spec.get("created")
    grader_model, temperature = _model((spec.get("model_roles") or {}).get("grader"))
    scorer_options = {s.get("name"): s.get("options") or {}
                      for s in spec.get("scorers") or [] if isinstance(s, dict)}
    format_1 = _format_1(data, scorer_options)

    records = RecordList(version=data.get("version"), label_map=DEFAULT_LABELS)
    keys: dict[str, list[str]] = {}  # each scorer's judges, as its scores name them
    seen, errored = 0, Counter()  # samples, and the types of the errors they stopped on
    # The records of samples that errored before they were scored, one per scorer: each
    # stands for every judge of its scorer, known only once all samples are seen
    waiting: list[tuple[int, ScoreRecord]] = []

    def rows() -> Iterator[tuple[int, object]]:
        nonlocal seen
        for n, sample in enumerate(samples, 1):
            if isinstance(sample, dict):
                seen += 1
                errored.update(filter(None, [_error_kind(sample)]))
                if format_1 and "scores" not in sample and isinstance(sample.get("score"), dict):
                    sample["scores"] = {format_1: sample["score"]}
                scores = sample.get("scores")
                for name, score in (scores if isinstance(scores, dict) else {}).items():
                    if isinstance(score, dict):
                        for key, _ in _verdicts(name, score.get("value")):
                            keys.setdefault(name, [])
                            if key not in keys[name]:
                                keys[name].append(key)
            yield n, sample

    def read_sample(sample: dict) -> None:
        if not (sample.get("id") is None or isinstance(sample["id"], str | int)) or \
                isinstance(sample.get("id"), bool):
            raise TypeError("a sample's id")
        if not isinstance(sample.get("messages"), list | None):
            raise TypeError("a sample's messages")
        item_id = str(sample.get("id"))
        epoch = sample.get("epoch")
        output = (sample.get("output") or {}).get("completion")
        content = {"input": sample.get("input"), "output": output,
                   "trajectory": trajectory(sample)}
        scores = sample.get("scores") or {}
        if with_errors and not scores and sample.get("error"):
            scores = {name: _sample_error(sample["error"]) for name in scorer_options}
        for name, score in scores.items():
            if not isinstance(score, dict):
                raise TypeError("a score")
            options = scorer_options.get(name) or {}
            model, temp = grader_model, temperature
            if model is None and options.get("model"):
                model, temp = _model(options["model"])[0], None
            if model is None:
                model, temp = _model_said(name, score), None
            evaluator = {}
            if model:
                evaluator["model"] = model
                if "/" in model and "+" not in model:
                    evaluator["provider"] = model.split("/", 1)[0]
            if temp is not None:
                evaluator["temperature"] = temp
            evaluator["prompt"] = scorer_prompt(name, options)
            edit = _human_edit(score)
            judged = edit[0] if edit else score
            code = name in CODE_SCORERS and not options.get("model")
            stand_in = judged.get("reason") == SAMPLE_ERROR
            judges = [(name, None)] if stand_in else _verdicts(name, judged.get("value"))
            for key, value in judges:
                label, number = _value(value)
                records.append(ScoreRecord(
                    target_id=item_id, name=key, annotator_kind=CODE if code else LLM,
                    label=label, score=number,
                    explanation=judged.get("explanation") or None, run=epoch, **content,
                    evaluator=dict(evaluator), created_at=created_at,
                    mark=_mark(judged, label)))
                if stand_in:
                    waiting.append((len(records) - 1, records[-1]))
            if edit:
                provenance = edit[1]["provenance"]
                for key, value in _verdicts(name, score.get("value")):
                    human_label, human_score = _value(value)
                    records.append(ScoreRecord(
                        target_id=item_id, name=key, annotator_kind=HUMAN, label=human_label,
                        score=human_score, explanation=provenance.get("reason") or None,
                        **content, created_at=provenance.get("timestamp")))

    read_rows(records, rows(), read_sample)
    if not seen and not records.left_out:
        raise no_samples
    for at, record in reversed(waiting):  # a row left out took its records with it
        if at < len(records) and records[at] is record:
            records[at:at + 1] = [replace(record, name=key, evaluator=dict(record.evaluator))
                                  for key in keys.get(record.name) or [record.name]]
    stopped = _stopped(data, seen, errored)
    if stopped:
        records.notes.append(stopped)
    all_damaged(path, "Inspect AI", records)
    return records


def _format_1(data: dict, scorer_options: dict) -> str | None:
    """Logs of format 1 (2024) hold one `score` per sample and name the scorer in
    `results.scorer`: its name, each sample's `score` then read as the current shape
    (`scores.<scorer>`); else None."""
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    scorer = results.get("scorer") if isinstance(results.get("scorer"), dict) else None
    name = scorer.get("name") if scorer else None
    if not isinstance(name, str) or not name:
        return None
    scorer_options.setdefault(name, scorer.get("params") or {})
    return name


def _verdicts(name: str, value) -> list[tuple[str, object]]:
    """[(judge name, value)]: one per key of a dict value, named scorer.key; else one."""
    if isinstance(value, dict) and value:
        return [(f"{name}.{key}", v) for key, v in value.items()]
    return [(name, value)]
