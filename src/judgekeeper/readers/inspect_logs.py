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
from itertools import accumulate
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
WHOLE_LIMIT = 500 * 2**20  # bytes: the biggest .eval log read whole (no read_eval_log_samples)
TOO_BIG = ("{path} is {size}. This Inspect AI version reads a log whole, so judgekeeper reads "
           "Inspect logs up to {limit} with it. Update Inspect AI (it then reads one sample at "
           "a time), or run your eval on fewer samples.")


# bytes: one sample of a .eval log unpacked, its events included. Far above real samples, so
# only a damaged or crafted log reaches it (inspect_ai unpacks a sample whole).
SAMPLE_LIMIT = 200 * 2**20
UNPACKS_TOO_BIG = ("{path} would unpack to more than {limit} for {part}, the most judgekeeper "
                   "reads for {part} of an Inspect AI log, so it did not read it. The log may be "
                   "damaged, or not an Inspect AI log.")
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


class _Depth:
    """How deep the lists and objects of JSON text go, fed a step at a time, with regex and
    bytes methods only: escapes are taken out, the text between quotes (the strings) left
    out, and the brackets left added up. Whether a string, or an escape, goes on into the
    next step is carried. TooDeep once past MAX_NESTING."""

    def __init__(self):
        self.depth, self.in_string, self.escaped = 0, False, False

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


def _unpacks_to(f, part, most: int) -> int:
    """How many bytes the zip `part` unpacks to, counted by unpacking it STEP bytes at a time
    and keeping none; the count stops once past `most`. What it unpacks to is also looked at
    for how deep it nests (_Depth): TooDeep past MAX_NESTING, as inspect_ai would take many GB
    to read a few KB nested 100,000 deep. Never through zipfile.open(): for zstd it unpacks a
    whole chunk at once, and it trusts the size the zip declares. ValueError for a part
    inspect_ai never writes: another compression, or encrypted."""
    import struct
    import zipfile
    import zlib

    f.seek(part.header_offset)
    head = f.read(30)
    if len(head) < 30 or head[:4] != b"PK\x03\x04" or part.flag_bits & 1:
        raise ValueError("not a part of an Inspect AI log")
    name, extra = struct.unpack_from("<HH", head, 26)
    f.seek(part.header_offset + 30 + name + extra)
    packed, n, depth = _Packed(f, part.compress_size), 0, _Depth()
    if part.compress_type == zipfile.ZIP_STORED:  # kept as it is: its size is what it holds
        while n <= most and (out := packed.read(STEP)):
            n += len(out)
            depth.feed(out)
        return n
    if part.compress_type == zipfile.ZIP_DEFLATED:
        unpack = zlib.decompressobj(-15)
        while n <= most and not unpack.eof:
            data = unpack.unconsumed_tail or packed.read(STEP)
            out = unpack.decompress(data, STEP)
            if not data and not out:
                break
            n += len(out)
            depth.feed(out)
        return n
    if part.compress_type == ZSTD:
        import zstandard

        reader = zstandard.ZstdDecompressor().stream_reader(
            packed, read_size=STEP, read_across_frames=True, closefd=False)
        while n <= most and (out := reader.read(STEP)):
            n += len(out)
            depth.feed(out)
        return n
    raise ValueError("not a compression inspect_ai writes")


def _too_big(path: Path, sizes, whole: bool) -> None:
    """RecordsError at the first of `sizes` (is it a sample, its bytes unpacked; per part)
    that passes a limit: the header parts together WHOLE_LIMIT, one sample SAMPLE_LIMIT, and
    with `whole` (a log read whole) all of it WHOLE_LIMIT."""
    header = total = 0
    for is_sample, n in sizes:
        total += n
        header += 0 if is_sample else n
        if whole and total > WHOLE_LIMIT:
            raise RecordsError(TOO_BIG.format(path=path, size=f"more than {_size(WHOLE_LIMIT)} "
                                              "unpacked", limit=_size(WHOLE_LIMIT)))
        for part, size, limit in (("the header", header, WHOLE_LIMIT),
                                  ("one sample", n if is_sample else 0, SAMPLE_LIMIT)):
            if size > limit:
                raise RecordsError(UNPACKS_TOO_BIG.format(path=path, part=part,
                                                          limit=_size(limit)))


def _check_unpacked(path: Path, whole: bool = False, samples: bool = True) -> None:
    """Refuse a .eval log (a zip) whose parts unpack too big (_too_big), before inspect_ai
    reads it: first by the sizes the zip declares, then by what each part really unpacks to
    (_unpacks_to), as a zip can declare any size. Nothing unpacked is kept, so memory stays
    low. `samples=False`: the header parts only. A file that isn't a zip is left to
    inspect_ai, which says so."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            parts = z.infolist()
    except (OSError, ValueError, zipfile.BadZipFile):
        return
    parts = [p for p in parts if samples or not p.filename.startswith("samples/")]
    _too_big(path, ((p.filename.startswith("samples/"), p.file_size) for p in parts), whole)
    try:
        with path.open("rb") as f:
            _too_big(path, ((p.filename.startswith("samples/"), _unpacks_to(
                f, p, SAMPLE_LIMIT if p.filename.startswith("samples/") else WHOLE_LIMIT))
                for p in parts), whole)
    except RecordsError:
        raise
    except TooDeep:
        raise damaged(path, "Inspect AI", NESTED) from None
    except Exception:  # noqa: BLE001 - a part that can't be unpacked: never read
        raise damaged(path, "Inspect AI", "can't be read: it may be cut short, or not an "
                                          "Inspect AI log") from None


def _by_sample(path: Path, read_eval_log, read_samples) -> dict:
    """A .eval log as its header and its samples, read one at a time, each kept to
    SAMPLE_FIELDS."""
    import inspect

    data = read_eval_log(str(path), header_only=True).model_dump(mode="json",
                                                                exclude={"samples"})
    options = {}
    try:
        if "exclude_fields" in inspect.signature(read_samples).parameters:
            options["exclude_fields"] = {"events", "attachments", "store"}
    except (TypeError, ValueError):
        pass
    data["samples"] = [s.model_dump(mode="json", include=SAMPLE_FIELDS)
                       for s in read_samples(str(path), all_samples_required=False, **options)]
    return data


def _load(path: Path) -> dict:
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        read_eval_log = None
    if read_eval_log is not None:
        try:
            from inspect_ai.log import read_eval_log_samples
        except ImportError:
            read_eval_log_samples = None
        is_eval = path.suffix.lower() == ".eval"
        if is_eval and read_eval_log_samples is None:
            size = path.stat().st_size
            if size > WHOLE_LIMIT:
                raise RecordsError(TOO_BIG.format(path=path, size=_size(size),
                                                  limit=_size(WHOLE_LIMIT)))
        if is_eval:
            _check_unpacked(path, whole=read_eval_log_samples is None)
        try:
            with quiet():
                if is_eval and read_eval_log_samples is not None:
                    return _by_sample(path, read_eval_log, read_eval_log_samples)
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
    status = data.get("status")
    if status not in ("error", "cancelled"):
        return None
    samples = [s for s in data.get("samples") or [] if isinstance(s, dict)]
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    total = (results.get("total_samples")
             or ((data.get("eval") or {}).get("dataset") or {}).get("samples"))
    errored = Counter(error_type((s["error"] or {}).get("message")
                                 if isinstance(s["error"], dict) else s["error"])
                      for s in samples if s.get("error"))
    done = results.get("completed_samples")
    if not isinstance(done, int) or isinstance(done, bool):
        done = len(samples) - sum(errored.values())
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
    (see the module docstring)."""
    path = Path(path)
    data = _load(path)
    spec = data.get("eval") if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        raise damaged(path, "Inspect AI", EVAL_DAMAGED if isinstance(data, dict) and "eval" in data
                      else "is not an Inspect AI log (no eval)")
    samples = data.get("samples")
    samples = samples if isinstance(samples, list) else None
    if not samples:
        raise RecordsError(f"{path}: the log has no samples (was it written with "
                           "--no-log-samples?)")
    created_at = spec.get("created")
    grader_model, temperature = _model((spec.get("model_roles") or {}).get("grader"))
    scorer_options = {s.get("name"): s.get("options") or {}
                      for s in spec.get("scorers") or [] if isinstance(s, dict)}
    _format_1(data, samples, scorer_options)

    records = RecordList(version=data.get("version"), label_map=DEFAULT_LABELS)
    keys: dict[str, list[str]] = {}  # each scorer's judges, as its scores name them
    for sample in samples:
        scores = sample.get("scores") if isinstance(sample, dict) else None
        for name, score in (scores if isinstance(scores, dict) else {}).items():
            if isinstance(score, dict):
                for key, _ in _verdicts(name, score.get("value")):
                    keys.setdefault(name, [])
                    if key not in keys[name]:
                        keys[name].append(key)
    stopped = stopped_early(data)
    if stopped:
        records.notes.append(stopped)

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
            judges = ([(key, None) for key in keys.get(name) or [name]]
                      if judged.get("reason") == SAMPLE_ERROR else _verdicts(name, judged.get("value")))
            for key, value in judges:
                label, number = _value(value)
                records.append(ScoreRecord(
                    target_id=item_id, name=key, annotator_kind=CODE if code else LLM,
                    label=label, score=number,
                    explanation=judged.get("explanation") or None, run=epoch, **content,
                    evaluator=dict(evaluator), created_at=created_at,
                    mark=_mark(judged, label)))
            if edit:
                provenance = edit[1]["provenance"]
                for key, value in _verdicts(name, score.get("value")):
                    human_label, human_score = _value(value)
                    records.append(ScoreRecord(
                        target_id=item_id, name=key, annotator_kind=HUMAN, label=human_label,
                        score=human_score, explanation=provenance.get("reason") or None,
                        **content, created_at=provenance.get("timestamp")))

    read_rows(records, enumerate(samples, 1), read_sample)
    all_damaged(path, "Inspect AI", records)
    return records


def _format_1(data: dict, samples: list, scorer_options: dict) -> None:
    """Logs of format 1 (2024) hold one `score` per sample and name the scorer in
    `results.scorer`: read as the current shape (`scores.<scorer>`), in place."""
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    scorer = results.get("scorer") if isinstance(results.get("scorer"), dict) else None
    name = scorer.get("name") if scorer else None
    if not isinstance(name, str) or not name:
        return
    scorer_options.setdefault(name, scorer.get("params") or {})
    for sample in samples:
        if isinstance(sample, dict) and "scores" not in sample and isinstance(
                sample.get("score"), dict):
            sample["scores"] = {name: sample["score"]}


def _verdicts(name: str, value) -> list[tuple[str, object]]:
    """[(judge name, value)]: one per key of a dict value, named scorer.key; else one."""
    if isinstance(value, dict) and value:
        return [(f"{name}.{key}", v) for key, v in value.items()]
    return [(name, value)]
