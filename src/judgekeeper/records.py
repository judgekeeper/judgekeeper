"""ScoreRecords: one verdict per record, the format every framework reader produces.

Field names follow OpenInference annotations, so other tools' exports map onto it by renaming:
`target_id, name, annotator_kind ("LLM" | "HUMAN" | "CODE"), label, score, explanation, run,
input, output, evaluator {provider, model, prompt, temperature, version, rule}, created_at`.
`evaluator` also accepts `prompt_hash`, `snapshot` and `endpoint`.

Version 2 of the format (`schema_version`; a record without one is version 1) adds:
- `metadata`, an open object for anything else (a criterion name, a run id, an A/B version);
- `rule` inside `evaluator`: the judge's rule text, hashed into the prompt hash when the
  record gives neither a prompt nor a hash;
- three fields ready for agents, stored and passed through to the anchor set but not shown on
  any page yet: `trajectory` (the agent's steps as OpenAI-style messages: role, content,
  tool_calls [id, name, arguments], tool_call_id), `outcome` (an automatic check of the
  result: passed, score, source, detail) and `app_version` (the app or agent that answered).
Fields judgekeeper does not know are kept, at the top level and inside `evaluator`
(`ScoreRecord.to_dict` gives them back). A file of a newer version is read as far as this
version understands it, with one warning. `problems` holds the rules;
schemas/records.schema.json says the same for other tools, and a test keeps the two in step.
A record's id, when it has to be derived, covers its trajectory too, so two agent runs that
end in the same answer stay two answers.

Nothing here knows about any framework; see judgekeeper.readers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from judgekeeper.anchors import canonical_json
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, IDENTITY_FIELDS
from judgekeeper.table import (
    ID_LENGTH,
    TableError,
    _blank,
    _delimiter,
    derive_id,
)
from judgekeeper.textio import MAX_NESTING, jsonl_lines, plural, read_utf8, reading, too_deep

SCHEMA_VERSION = 2
LLM, HUMAN, CODE = "LLM", "HUMAN", "CODE"
KINDS = (LLM, HUMAN, CODE)
_KIND_ALIASES = {"LLM_JUDGE": LLM, "JUDGE": LLM, "HUMAN_ANNOTATION": HUMAN, "HEURISTIC": CODE}
FIELDS = ("target_id", "name", "annotator_kind", "label", "score", "explanation", "run",
          "input", "output", "evaluator", "created_at")
AGENT_FIELDS = ("trajectory", "outcome", "app_version")
OPTIONAL_FIELDS = ("metadata", *AGENT_FIELDS)
ALL_FIELDS = ("schema_version", *FIELDS, *OPTIONAL_FIELDS)
EVALUATOR_KEYS = ("provider", "model", "prompt", "temperature", "version", "prompt_hash",
                  "snapshot", "endpoint", "rule")
JSON_CELLS = ("metadata", "trajectory", "outcome")  # JSON text in a CSV cell
DEFAULT_NAME = "judge"
BIG = 1_000_000  # bytes: a record larger than this is kept, with a warning
_NUMBER = re.compile(r"\A\s*([-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?)?\s*\Z")


class RecordsError(TableError):
    """The records cannot be turned into a report: a usage error."""


class Damaged(RecordsError):
    """A results file that can't be read as a whole (empty, cut off, not the tool's). Its
    message names the file, never its content or the JSON parser's words; `next_step` is the
    Next: line's (cli.main)."""

    def __init__(self, message: str, next_step: str):
        super().__init__(message)
        self.next_step = next_step


def damaged(path: str | Path, tool: str, how: str) -> Damaged:
    """`how` the file at `path` is damaged, and to save it again from `tool`."""
    name = Path(path).name
    return Damaged(f"{name} {how}. Save it again from {tool}.",
                   f"save {name} again from {tool}, then run `{{command}}`.")


NESTED = f"is nested more than {MAX_NESTING} levels deep"  # the same on every Python


def load_json(path: str | Path, tool: str):
    """The JSON in `tool`'s results file. Damaged, in plain words, when it is empty, cut off,
    not JSON or nested too deep."""
    text = read_utf8(path, RecordsError)
    if not text.strip():
        raise damaged(path, tool, "is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        cut = e.pos >= len(text.rstrip()) or e.msg.startswith("Unterminated string")
        raise damaged(path, tool, "is cut off or damaged (it ends in the middle)" if cut
                      else "is damaged (it isn't valid JSON)") from None
    except RecursionError:  # Python before 3.14 stops here; 3.14 reads it: too_deep below
        raise damaged(path, tool, NESTED) from None
    except ValueError:  # a number too long to read
        raise damaged(path, tool, "is damaged (judgekeeper can't read it as JSON)") from None
    if too_deep(data):
        raise damaged(path, tool, NESTED)
    return data


def derive_record_id(input, output, trajectory=None) -> str:
    """table.derive_id over an item's input and output, with a missing value read as "".

    With a trajectory (a non-empty list of steps), the id covers it too: two agent runs that
    end in the same answer are two answers."""
    item = {"input": "" if input is None else input, "output": "" if output is None else output}
    if not trajectory:
        return derive_id(item)
    content = canonical_json({**item, "trajectory": trajectory})
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:ID_LENGTH]


# The rules -------------------------------------------------------------------------------

def _is_text(v) -> bool:
    """Text, or a number written as text (an id, a version, a date)."""
    return isinstance(v, str) or (isinstance(v, int | float) and not isinstance(v, bool))


def _is_whole(v) -> bool:
    return (isinstance(v, int) and not isinstance(v, bool)) or (
        isinstance(v, float) and v.is_integer())


def _is_number(v, text: bool = True) -> bool:
    """A number; with `text`, also a number written as text (or a blank cell)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int | float):
        return True
    return text and isinstance(v, str) and bool(_NUMBER.match(v))


def _kind(v) -> str | None:
    if _blank(v):
        return LLM
    text = str(v).strip().upper()
    text = _KIND_ALIASES.get(text, text)
    return text if text in KINDS else None


def _evaluator_problems(v) -> list[str]:
    if _blank(v):
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            return ["evaluator is not a JSON object"]
    if not isinstance(v, dict):
        return [("evaluator must be an object with provider, model, prompt, temperature and "
                 "version")]
    out = []
    for key in EVALUATOR_KEYS:
        value = v.get(key)
        if key == "temperature":
            if value is not None and not _is_number(value):
                out.append("evaluator.temperature is not a number")
        elif value is not None and not _is_text(value):
            out.append(f"evaluator.{key} must be text")
    return out


def _message_problems(n: int, m) -> list[str]:
    where = f"trajectory step {n}"
    if not isinstance(m, dict):
        return [f"{where} must be an object with a role"]
    out = []
    if not isinstance(m.get("role"), str) or not m["role"]:
        out.append(f"{where} needs a role (user, assistant, tool or system)")
    content = m.get("content")
    if content is not None and not isinstance(content, str | list):
        out.append(f"{where}: content must be text, a list of parts or null")
    calls = m.get("tool_calls")
    if calls is not None and not isinstance(calls, list):
        out.append(f"{where}: tool_calls must be a list")
    for c, call in enumerate(calls if isinstance(calls, list) else [], 1):
        if not isinstance(call, dict):
            out.append(f"{where}, tool call {c} must be an object with a name")
            continue
        if not isinstance(call.get("name"), str) or not call["name"]:
            out.append(f"{where}, tool call {c} needs a name")
        if call.get("id") is not None and not isinstance(call["id"], str):
            out.append(f"{where}, tool call {c}: id must be text")
    if m.get("tool_call_id") is not None and not isinstance(m["tool_call_id"], str):
        out.append(f"{where}: tool_call_id must be text")
    return out


def _outcome_problems(v) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, dict):
        return ["outcome must be an object with passed (true or false) or score (a number)"]
    out = []
    if "passed" not in v and "score" not in v:
        out.append("outcome needs passed or score")
    if "passed" in v and not isinstance(v["passed"], bool):
        out.append("outcome.passed must be true or false")
    if "score" in v and not _is_number(v["score"], text=False):
        out.append("outcome.score must be a number")
    for key in ("source", "detail"):
        if v.get(key) is not None and not _is_text(v[key]):
            out.append(f"outcome.{key} must be text")
    return out


def problems(d: dict) -> list[str]:
    """What is wrong with one record, in words; [] when judgekeeper can read it.

    These are the rules of schemas/records.schema.json. Fields judgekeeper does not know are
    never a problem. Values from a CSV are text: read_records turns them into JSON values
    first (a version number, and the JSON in metadata, trajectory and outcome cells)."""
    out = []
    version = d.get("schema_version")
    if version is not None and not (_is_whole(version) and version >= 1):
        out.append("schema_version is not a whole number, 1 or more")
    target = d.get("target_id")
    if target is not None and not (isinstance(target, str) or _is_whole(target)):
        out.append("target_id must be text or a whole number")
    for key in ("name", "explanation", "created_at", "app_version"):
        if d.get(key) is not None and not _is_text(d[key]):
            out.append(f"{key} must be text")
    kind = d.get("annotator_kind")
    if kind is not None and (not isinstance(kind, str) or _kind(kind) is None):
        out.append(f"annotator_kind is not one of {', '.join(KINDS)}")
    score = d.get("score")
    if score is not None and not (_is_number(score) or isinstance(score, bool)):
        out.append("score is not a number")
    run = d.get("run")
    if run is not None and not (isinstance(run, str) or _is_whole(run)):
        out.append("run must be a whole number or text")
    out += _evaluator_problems(d.get("evaluator"))
    meta = d.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        out.append("metadata must be an object")
    steps = d.get("trajectory")
    if steps is not None and not isinstance(steps, list):
        out.append("trajectory must be a list of messages (role, content, tool_calls, "
                   "tool_call_id)")
    for n, m in enumerate(steps if isinstance(steps, list) else [], 1):
        out += _message_problems(n, m)
    out += _outcome_problems(d.get("outcome"))
    return out


@dataclass(frozen=True)
class Mark:
    """What a reader learned about one verdict that its file keeps no field for: held in memory
    only, for `start`'s judge check (judgekeeper.judge_check). Never written to any file and
    never compared, so the records read exactly as before.

    `problem`: the judge made no real decision: "error" (its call failed), "unreadable" (its
    reply could not be read) or "nothing_checked" (it checked nothing and the tool gave full
    marks). `tool_counted_as`: what the eval tool counted such a verdict as ("pass", "fail" or
    "left out"); None when it does not say. `output_elsewhere`: the answer is not in `output`
    (a DeepEval conversation's turns).
    """

    problem: str | None = None
    tool_counted_as: str | None = None
    output_elsewhere: bool = False


NO_MARK = Mark()


@dataclass
class ScoreRecord:
    target_id: str
    name: str
    annotator_kind: str
    label: Any = None
    score: float | None = None
    explanation: str | None = None
    run: int | str | None = None
    input: Any = None
    output: Any = None
    evaluator: dict = field(default_factory=dict)
    created_at: str | None = None
    metadata: dict = field(default_factory=dict)
    trajectory: list | None = None
    outcome: dict | None = None
    app_version: str | None = None
    schema_version: int = SCHEMA_VERSION
    extra: dict = field(default_factory=dict)  # fields judgekeeper does not know, kept
    mark: Mark = field(default=NO_MARK, compare=False, repr=False)  # in memory only

    def to_dict(self) -> dict:
        """The record as written: version 2 (or the newer version it was read as), the
        classic fields, the optional ones that are set, then the fields kept unread."""
        d = {"schema_version": max(self.schema_version, SCHEMA_VERSION)}
        d.update({k: getattr(self, k) for k in FIELDS})
        for k in OPTIONAL_FIELDS:
            if getattr(self, k) not in (None, {}, []):
                d[k] = getattr(self, k)
        for k, v in self.extra.items():
            d.setdefault(k, v)
        return d

    def agent(self) -> dict:
        """The fields ready for agents that this record has."""
        return {k: getattr(self, k) for k in AGENT_FIELDS if getattr(self, k) is not None}

    @classmethod
    def from_dict(cls, d: dict) -> ScoreRecord:
        found = problems(d)
        if found:
            raise RecordsError(found[0])
        version = d.get("schema_version")
        return cls(
            target_id=None if _blank(d.get("target_id")) else str(d["target_id"]).strip(),
            name=DEFAULT_NAME if _blank(d.get("name")) else str(d["name"]),
            annotator_kind=_kind(d.get("annotator_kind")),
            label=None if _blank(d.get("label")) else d["label"],
            score=_number(d.get("score")),
            explanation=None if _blank(d.get("explanation")) else str(d["explanation"]),
            run=_run(d.get("run")),
            input=_content(d.get("input")),
            output=_content(d.get("output")),
            evaluator=_evaluator(d.get("evaluator")),
            created_at=None if _blank(d.get("created_at")) else str(d["created_at"]),
            metadata=dict(d.get("metadata") or {}),
            trajectory=d.get("trajectory") or None,
            outcome=d.get("outcome"),
            app_version=None if _blank(d.get("app_version")) else str(d["app_version"]),
            schema_version=1 if version is None else int(version),
            extra={k: v for k, v in d.items() if k not in ALL_FIELDS},
        )


class RecordList(list):
    """A list of ScoreRecords plus what the reader learned about the file as a whole.

    `version`: the tool's own format version, when the file states one. `ids_derived`: ids are
    a hash of input and output. `warnings` become report flags; `notes` become report notes.
    `label_map`: the reader's default verdict spellings (Inspect's C/I), under --label-map.
    `per_metric`: extra source fields for one metric name, e.g. DeepEval's threshold; its
    "warnings" are added to `warnings` when that metric is the one validated.
    `left_out`: the numbers (from 1) of the rows left out for a damaged field (read_rows);
    `unit` says what a row is in this file ("row", or "line" in a JSONL file). `source`: the
    file's name as the person knows it, when it is not the file read (an MLflow store).
    """

    def __init__(self, records=(), *, version=None, ids_derived=False, warnings=None,
                 notes=None, label_map=None, per_metric=None, unit="row"):
        super().__init__(records)
        self.version = version
        self.ids_derived = ids_derived
        self.warnings = list(warnings or [])
        self.notes = list(notes or [])
        self.label_map = dict(label_map or {})
        self.per_metric = dict(per_metric or {})
        self.left_out: list = []
        self.unit = unit
        self.source: str | None = None


# One damaged row ------------------------------------------------------------------------
# A reader reads each row of a file on its own. A row whose reading raises one of these (a
# string where an object should be, a list for a name...), or whose records hold a value
# judgekeeper can't use further on (check_record), is left out and counted; the rest is read.

ROW_DAMAGE = (AttributeError, TypeError, ValueError, KeyError, IndexError, RecursionError,
              OverflowError)
ROW_NESTING = 100  # lists and objects inside each other in one answer; real ones use a few
SHOWN_ROWS = 5  # row numbers named in the note; the rest are counted


def _nested(value) -> int:
    """How deep lists and objects are nested in `value`, walked without recursion."""
    deepest, stack = 0, [(value, 0)]
    while stack:
        v, depth = stack.pop()
        if isinstance(v, dict | list):
            depth += 1
            deepest = max(deepest, depth)
            if depth > ROW_NESTING:
                break
            stack.extend((x, depth) for x in (v.values() if isinstance(v, dict) else v))
    return deepest


def _finite(v) -> bool:
    return not isinstance(v, int | float) or isinstance(v, bool) or math.isfinite(float(v))


def check_record(r: ScoreRecord) -> None:
    """TypeError or ValueError (OverflowError for a number too big) when `r` holds a value
    judgekeeper can't use further on: an id or a name that is not text, a decision or score
    that is not a plain value or not a finite number, a reason that is not text, an answer
    nested too deep or holding NaN, a judge's model that is not text."""
    if not isinstance(r.target_id, str) or not isinstance(r.name, str):
        raise TypeError("id or name")
    for v in (r.label, r.score):
        if not (v is None or isinstance(v, str | bool | int | float)) or not _finite(v):
            raise TypeError("decision or score")
    if r.explanation is not None and not isinstance(r.explanation, str):
        raise TypeError("reason")
    for v in (r.input, r.output, r.trajectory):
        if _nested(v) > ROW_NESTING:
            raise ValueError("nested too deep")
        json.dumps(v, allow_nan=False)
    model = r.evaluator.get("model") if isinstance(r.evaluator, dict) else None
    if not isinstance(r.evaluator, dict) or not (model is None or isinstance(model, str)):
        raise TypeError("judge")


def read_rows(records: RecordList, rows, read_one) -> None:
    """`read_one(row)` for each (number, row) of `rows`; it adds the row's records to
    `records`. A damaged row (ROW_DAMAGE, check_record) adds nothing: its number goes to
    `records.left_out`. A RecordsError still stops the file."""
    for n, row in rows:
        reading(n)
        before = len(records)
        try:
            read_one(row)
            for r in records[before:]:
                check_record(r)
        except ROW_DAMAGE:
            del records[before:]
            records.left_out.append(n)


def left_out_note(records: RecordList, file: str) -> str | None:
    """The note on the rows of `file` left out for a damaged field, or None."""
    rows = records.left_out
    if not rows:
        return None
    named = [f"{records.unit} {n}" for n in rows[:SHOWN_ROWS]]
    if len(rows) > SHOWN_ROWS:
        named.append(f"{len(rows) - SHOWN_ROWS} more")
    listed = " and ".join([", ".join(named[:-1]), named[-1]] if len(named) > 1 else named)
    one = len(rows) == 1
    name = records.source or Path(file).name
    return (f"{plural(len(rows), 'answer')} in {name} {'was' if one else 'were'} "
            f"left out: {listed} {'has' if one else 'have'} a damaged field.")


def all_damaged(path: str | Path, tool: str, records: RecordList) -> None:
    """Damaged when every row of the file was left out (there were rows; none was read)."""
    if records.left_out and not records:
        raise damaged(path, tool, f"is damaged: {_each(records.left_out, records.unit)} has a "
                                  "damaged field")


def _each(left_out: list, unit: str) -> str:
    """"each of its 3 rows", or "its only row"."""
    return (f"its only {unit}" if len(left_out) == 1
            else f"each of its {plural(len(left_out), unit)}")


def _content(v):
    """Input or output as given; None (or NaN from a DataFrame) is missing, "" is not."""
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def _number(v) -> float | None:
    if _blank(v):
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int | float):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        raise RecordsError("score is not a number") from None


def _run(v):
    if _blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return v


def _evaluator(v) -> dict:
    """The evaluator object; keys judgekeeper does not know are kept."""
    if _blank(v):
        return {}
    if isinstance(v, str):
        v = json.loads(v)  # problems() has checked it is a JSON object
    return {k: val for k, val in v.items() if not (_blank(val) and k != "endpoint")}


def fingerprint_known(evaluator: dict) -> dict:
    """The judge identity in a record's evaluator, as make_fingerprint takes it.

    `version` is the rubric version. The rule stands in for the prompt when the evaluator has
    neither a prompt nor a prompt hash, so it is hashed into the prompt hash. Keys judgekeeper
    does not know are left out."""
    known = {k: v for k, v in evaluator.items()
             if k in EVALUATOR_KEYS and k not in ("version", "rule")}
    if evaluator.get("version") is not None:
        known["rubric_version"] = evaluator["version"]
    rule = evaluator.get("rule")
    if rule is not None and "prompt" not in known and "prompt_hash" not in known:
        known["prompt"] = rule
    return known


# Reading ScoreRecords from JSONL or CSV, with an optional column map ----------------------

def parse_map(text: str | dict | None) -> dict[str, str]:
    """`"target_id=trace_id,label=value"` (or a dict) to {ScoreRecord field: column}."""
    if not text:
        return {}
    pairs = text.items() if isinstance(text, dict) else (
        part.split("=", 1) if "=" in part else (part, "")
        for part in (p.strip() for p in text.split(",")) if part)
    out = {}
    for key, column in pairs:
        key, column = str(key).strip(), str(column).strip()
        sub = key.split(".", 1)[1] if key.startswith("evaluator.") else None
        if (key not in ALL_FIELDS and sub not in EVALUATOR_KEYS) or not column:
            raise RecordsError(f"--map entries look like field=column with field one of "
                               f"{', '.join(ALL_FIELDS)} or "
                               f"evaluator.<{'|'.join(EVALUATOR_KEYS)}>; got {key}={column}")
        out[key] = column
    return out


def source_rows(path: str | Path) -> tuple[list[tuple[int, dict | str, int]], bool]:
    """([(line number, the row or what is wrong with the line, size in bytes)], whether the
    file is a CSV or TSV, whose values are all text). Blank lines are skipped."""
    path = Path(path)
    if not path.is_file():
        raise RecordsError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        text = read_utf8(path, RecordsError)
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=_delimiter(text, suffix))
        rows = []
        for row in reader:
            row = {k: v for k, v in row.items() if k is not None}
            rows.append((reader.line_num, row, len(json.dumps(row).encode("utf-8"))))
        return rows, True
    if suffix in (".jsonl", ".ndjson", ".json"):
        rows = []
        for n, line in enumerate(jsonl_lines(read_utf8(path, RecordsError)), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):  # never the parser's words: they quote it
                rows.append((n, "not valid JSON", 0))
                continue
            if not isinstance(row, dict):
                rows.append((n, "each line must be a JSON object", 0))
                continue
            rows.append((n, row, len(line.encode("utf-8"))))
        return rows, False
    raise RecordsError(f"{path}: expected a .csv, .tsv or .jsonl file")


def check_map(mapping: dict, rows: list, path: Path) -> None:
    """A usage error when `mapping` names a column the file does not have."""
    columns = list(dict.fromkeys(k for _, r, _ in rows if isinstance(r, dict) for k in r))
    missing = [c for c in mapping.values() if c not in columns]
    if missing:
        raise RecordsError(f"--map names column(s) {missing} not in {path.name}; "
                           f"columns are: {', '.join(columns)}")


def record_dict(row: dict, mapping: dict, cells: bool) -> tuple[dict, list[str]]:
    """One source row as a record (columns renamed by `mapping`; `evaluator.<key>` columns
    folded into `evaluator`; other columns kept as they are), and what is wrong with the row
    before the rules run. `cells`: the row is from a CSV, so a version number is text and
    metadata, trajectory and outcome hold JSON text."""
    used = set()
    d = {}
    for f in ALL_FIELDS:
        col = mapping.get(f, f)
        if col in row:
            d[f] = row[col]
            used.add(col)
    columns = {}
    for k in EVALUATOR_KEYS:
        col = mapping.get(f"evaluator.{k}", f"evaluator.{k}")
        if col in row:
            used.add(col)
            columns[k] = row[col]
    for k, v in row.items():
        if k in used or k in ALL_FIELDS:
            continue
        if k.startswith("evaluator."):
            columns[k.split(".", 1)[1]] = v
        else:
            d[k] = v
    found = []
    if cells:
        for f in JSON_CELLS:
            if f in d and _blank(d[f]):
                del d[f]
            elif f in d:
                try:
                    d[f] = json.loads(d[f])
                except json.JSONDecodeError:
                    found.append(f"{f} is not JSON: a CSV cell for {f} must hold JSON text")
                    del d[f]
        version = d.get("schema_version")
        if isinstance(version, str) and _blank(version):
            del d["schema_version"]
        elif isinstance(version, str) and version.strip().isdigit():
            d["schema_version"] = int(version.strip())
    columns = {k: v for k, v in columns.items() if not _blank(v)}
    if columns:
        ev = d.get("evaluator")
        if _blank(ev):
            ev = {}
        elif isinstance(ev, str):
            try:
                ev = json.loads(ev)
            except json.JSONDecodeError:
                pass  # problems() names it
        if isinstance(ev, dict):
            d["evaluator"] = {**ev, **columns}
    return d, found


def file_warnings(name: str, records: list[ScoreRecord], n_big: int) -> list[str]:
    """One warning for a newer version of the format, one for records over 1 MB."""
    out = []
    newest = max((r.schema_version for r in records), default=1)
    if newest > SCHEMA_VERSION:
        out.append(f"{name} uses records format version {newest}; this judgekeeper knows up "
                   f"to version {SCHEMA_VERSION}. It read what it could: update judgekeeper "
                   "to read the rest.")
    if n_big:
        out.append(f"{n_big} {'record' if n_big == 1 else 'records'} in {name} "
                   f"{'is' if n_big == 1 else 'are'} over 1 MB: kept, but such files are slow "
                   "to read.")
    return out


CUT_END = "the last line was cut short and was left out"


def read_records(path: str | Path, column_map: str | dict | None = None,
                 cut_end_ok: bool = False, bad_lines_ok: bool = False) -> RecordList:
    """ScoreRecords from a JSONL, CSV or TSV file. `column_map` renames source columns.

    A record judgekeeper cannot read stops with its line number; with `bad_lines_ok` it is
    left out instead, its line number in `left_out`, and the other lines are read (Damaged
    when no line is left). A newer version of the format, or a record over 1 MB, adds one
    warning. With `cut_end_ok`, a last line that is not whole JSON (the writing program
    stopped in the middle of it) is left out, with CUT_END in the notes."""
    path = Path(path)
    rows, cells = source_rows(path)
    cut = cut_end_ok and bool(rows) and isinstance(rows[-1][1], str) and \
        rows[-1][1].startswith("not valid JSON")
    if cut:
        rows = rows[:-1]
    mapping = parse_map(column_map)
    check_map(mapping, rows, path)
    records = RecordList(unit="line")
    n_big = 0
    for n, row, size in rows:
        try:
            if isinstance(row, str):
                raise RecordsError(f"{path.name}: line {n}: {row}")
            d, found = record_dict(row, mapping, cells)
            found += problems(d)
            if found:
                raise RecordsError(f"{path.name}: line {n}: {found[0]}")
            rec = ScoreRecord.from_dict(d)
            if rec.target_id is None:
                rec.target_id = derive_record_id(rec.input, rec.output, rec.trajectory)
                records.ids_derived = True
            if bad_lines_ok:
                check_record(rec)
        except (RecordsError, *ROW_DAMAGE):
            if not bad_lines_ok:
                raise
            records.left_out.append(n)
            continue
        n_big += size > BIG
        records.append(rec)
    if records.left_out and not records:
        raise Damaged(f"{path.name} is damaged: {_each(records.left_out, 'line')} has a damaged "
                      "field.",
                      "run your eval again (it writes new records), then run `{command}`.")
    records.warnings += file_warnings(path.name, records, n_big)
    if cut:
        records.notes.append(CUT_END)
    return records


# Records to a report --------------------------------------------------------------------

_plural = plural  # textio.plural


def _verdict_value(rec: ScoreRecord, pass_if) -> Any:
    if pass_if is not None and rec.score is not None:
        return rec.score
    return rec.label if rec.label is not None else rec.score


def _consensus(fps: list) -> tuple[dict, list[str]]:
    """Fingerprint fields every judgment agrees on; the rest unknown, with a note."""
    known, differ = {}, []
    for f in (*IDENTITY_FIELDS, "snapshot"):
        values = list(dict.fromkeys(getattr(fp, f) for fp in fps))
        if len(values) == 1:
            if values[0] is not None:
                known[f] = values[0]
            continue
        shown = ", ".join("unknown" if v is None else str(v) for v in values[:5])
        if f == "prompt_hash":
            shown = f"{len(values)} different prompts"
        differ.append(f"{f} ({shown})")
        if f == "endpoint":
            known[f] = ENDPOINT_UNKNOWN
    if not differ:
        return known, []
    note = (f"Judgments disagree on the judge's {', '.join(differ)}: the run header records "
            "these as unknown and each judgment keeps its own.")
    return known, [note]
