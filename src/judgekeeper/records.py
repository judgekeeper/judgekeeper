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

`records_to_report` pivots records into the files `check` writes: HUMAN records become anchor
labels, LLM records become judgments (one run per source file and run index), CODE records are
ignored. Then the report pipeline (normaliser, unknown-tolerant fingerprint, report) runs as
for `check`. Nothing here knows about any framework; see judgekeeper.readers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from judgekeeper.anchors import PAIRWISE, SINGLE, canonical_json
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, IDENTITY_FIELDS
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, parse_label_map, unmapped_error
from judgekeeper.redact import scrub_value
from judgekeeper.table import (
    ID_LENGTH,
    TableError,
    _blank,
    _delimiter,
    _listed,
    _run_key,
    derive_id,
    make_fingerprint,
    read_table,
    sheet_id,
    write_anchor_file,
    write_runs_and_report,
)
from judgekeeper.textio import read_utf8

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
            return [f"evaluator {v[:60]!r} is not a JSON object"]
    if not isinstance(v, dict):
        return [("evaluator must be an object with provider, model, prompt, temperature and "
                 "version")]
    out = []
    for key in EVALUATOR_KEYS:
        value = v.get(key)
        if key == "temperature":
            if value is not None and not _is_number(value):
                out.append(f"evaluator.temperature {value!r} is not a number")
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
        out.append(f"schema_version {version!r} must be a whole number, 1 or more")
    target = d.get("target_id")
    if target is not None and not (isinstance(target, str) or _is_whole(target)):
        out.append("target_id must be text or a whole number")
    for key in ("name", "explanation", "created_at", "app_version"):
        if d.get(key) is not None and not _is_text(d[key]):
            out.append(f"{key} must be text")
    kind = d.get("annotator_kind")
    if kind is not None and (not isinstance(kind, str) or _kind(kind) is None):
        out.append(f"annotator_kind {kind!r} is not one of {', '.join(KINDS)}")
    score = d.get("score")
    if score is not None and not (_is_number(score) or isinstance(score, bool)):
        out.append(f"score {score!r} is not a number")
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
    """

    def __init__(self, records=(), *, version=None, ids_derived=False, warnings=None,
                 notes=None, label_map=None, per_metric=None):
        super().__init__(records)
        self.version = version
        self.ids_derived = ids_derived
        self.warnings = list(warnings or [])
        self.notes = list(notes or [])
        self.label_map = dict(label_map or {})
        self.per_metric = dict(per_metric or {})


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
        raise RecordsError(f"score {v!r} is not a number") from None


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
        for n, line in enumerate(read_utf8(path, RecordsError).splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                rows.append((n, f"not valid JSON ({e.msg})", 0))
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
                 cut_end_ok: bool = False) -> RecordList:
    """ScoreRecords from a JSONL, CSV or TSV file. `column_map` renames source columns.

    A record judgekeeper cannot read stops with its line number (`import records --check`
    lists every problem). A newer version of the format, or a record over 1 MB, adds one
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
    records = RecordList()
    n_big = 0
    for n, row, size in rows:
        if isinstance(row, str):
            raise RecordsError(f"{path}: line {n}: {row}")
        d, found = record_dict(row, mapping, cells)
        found += problems(d)
        if found:
            raise RecordsError(f"{path.name}: line {n}: {found[0]}")
        rec = ScoreRecord.from_dict(d)
        if rec.target_id is None:
            rec.target_id = derive_record_id(rec.input, rec.output, rec.trajectory)
            records.ids_derived = True
        n_big += size > BIG
        records.append(rec)
    records.warnings += file_warnings(path.name, records, n_big)
    if cut:
        records.notes.append(CUT_END)
    return records


# Records to a report --------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _verdict_value(rec: ScoreRecord, pass_if) -> Any:
    if pass_if is not None and rec.score is not None:
        return rec.score
    return rec.label if rec.label is not None else rec.score


def _read_labels(path, label_map) -> tuple[dict[str, str], dict[str, dict]]:
    rows = read_table(path)
    columns = list(dict.fromkeys(k for r in rows for k in r))
    if "id" not in columns:
        raise RecordsError(f"--labels {path}: needs an id column; columns are: "
                           f"{', '.join(columns)}")
    label_col = next((c for c in ("human_label", "label") if c in columns), None)
    if label_col is None:
        raise RecordsError(f"--labels {path}: needs a human_label (or label) column; columns "
                           f"are: {', '.join(columns)}")
    norm = Normaliser(SINGLE, label_map=label_map)
    labels, content, unmapped = {}, {}, []
    for row in rows:
        if _blank(row.get("id")):
            continue
        item_id = sheet_id(row["id"])  # a labels.csv judgekeeper wrote guards its ids
        try:
            v = norm(row.get(label_col)).verdict
        except UnmappedValue as e:
            unmapped.append(e.value)
            continue
        if v == ERROR:
            continue
        if item_id in labels and labels[item_id] != v:
            raise RecordsError(f"--labels {path}: different labels for id {item_id!r}")
        labels[item_id] = v
        content[item_id] = {k: str(row[k]) for k in ("input", "output", "slice")
                            if not _blank(row.get(k))}
    if unmapped:
        raise unmapped_error(unmapped, f"human label ({label_col!r} in --labels)",
                             pass_if=False)
    return labels, content


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


def _human_labels(records: list[ScoreRecord], metric: str, llm_names: list[str],
                  norm: Normaliser) -> dict[str, str]:
    """{id: label} from HUMAN records named `metric`, or named after no judge metric."""
    labels: dict[str, set] = defaultdict(set)
    unmapped = []
    for r in records:
        if r.annotator_kind != HUMAN or (r.name != metric and r.name in llm_names):
            continue
        try:
            v = norm(_verdict_value(r, None)).verdict
        except UnmappedValue as e:
            unmapped.append(e.value)
            continue
        if v != ERROR:
            labels[r.target_id].add(v)
    if unmapped:
        raise unmapped_error(unmapped, "human label", pass_if=False)
    conflicts = [i for i, s in labels.items() if len(s) > 1]
    if conflicts:
        raise RecordsError(f"items with different human labels: {_listed(conflicts)}")
    return {i: next(iter(s)) for i, s in labels.items()}


def _judgments(files: list[tuple[str, RecordList]], metric: str, norm: Normaliser,
               runs_by_order: bool) -> dict[tuple, dict[str, dict]]:
    """{(file index, run value): {id: entry}} from the LLM records named `metric`.

    With `runs_by_order`, each item's verdicts in a file are numbered 1, 2, 3 in order of
    appearance, in place of any run index the reader set.
    """
    by_run: dict[tuple, dict[str, dict]] = defaultdict(dict)
    order_seen: Counter = Counter()
    dups, unmapped = [], []
    for fi, (_, recs) in enumerate(files):
        for r in recs:
            if r.annotator_kind != LLM or r.name != metric:
                continue
            if runs_by_order:
                order_seen[(fi, r.target_id)] += 1
                run_value = str(order_seen[(fi, r.target_id)])
            elif r.run is not None:
                run_value = str(r.run)
            else:
                run_value = "1"
            entries = by_run[(fi, run_value)]
            if r.target_id in entries:
                dups.append(r.target_id)
                continue
            try:
                verdict = norm(_verdict_value(r, norm.pass_if))
            except UnmappedValue as e:
                unmapped.append(e.value)
                continue
            entries[r.target_id] = {"verdict": verdict, "rationale": r.explanation or "",
                                    "fingerprint": make_fingerprint(
                                        fingerprint_known(r.evaluator), r.created_at)}
    if unmapped:
        raise unmapped_error(unmapped, f"judge verdict ({metric!r})",
                             pass_if=norm.kind != PAIRWISE)
    if dups:
        raise RecordsError(f"several verdicts for one item in one run: "
                           f"{_listed(list(dict.fromkeys(dups)))}. Pass --runs-by-order to "
                           "number repeats in order of appearance.")
    return by_run


def records_to_report(files: list[tuple[str, RecordList]], kind: str, metric: str | None = None,
                      labels: str | Path | None = None, pass_if: str | None = None,
                      label_map: dict | str | None = None, runs_by_order: bool = False,
                      out: str | Path | None = None,
                      anchors_out: str | Path | None = None) -> dict:
    """Pivot the records of one or more source files into anchors and runs; return report.json.

    `files` is [(file name, records)] in run order. Each file's records form separate runs:
    one per run index, or a single run when records carry none. `anchors_out` also writes
    every item with a human label as a frozen anchor set (see `write_label_anchors`).
    """
    all_records = [r for _, recs in files for r in recs]
    if not all_records:
        raise RecordsError("no records found")
    llm_names = sorted({r.name for r in all_records if r.annotator_kind == LLM})
    if not llm_names:
        raise RecordsError("no LLM (judge) records found: nothing to validate")
    if metric is None:
        if len(llm_names) > 1:
            raise RecordsError(f"several metrics found: {_listed(llm_names)}. Choose one with "
                               "--metric NAME")
        metric = llm_names[0]
    elif metric not in llm_names:
        raise RecordsError(f"no LLM records named {metric!r}; names are: {_listed(llm_names)}")

    extra_map = {}
    for _, recs in files:
        extra_map.update(recs.label_map)
    extra_map.update(parse_label_map(label_map, SINGLE))
    judge_norm = Normaliser(SINGLE, pass_if=pass_if, label_map=extra_map)
    human_norm = Normaliser(SINGLE, label_map=extra_map)

    notes: list[str] = []
    warnings: list[str] = []
    per_metric: dict = {}
    for _, recs in files:
        extra = dict(recs.per_metric.get(metric, {}))
        notes += [n for n in recs.notes if n not in notes]
        warnings += [w for w in recs.warnings + extra.pop("warnings", []) if w not in warnings]
        per_metric.update(extra)
    n_code = sum(r.annotator_kind == CODE for r in all_records)
    if n_code:
        notes.append(f"{_plural(n_code, 'CODE record', 'CODE records')} ignored: code checks "
                     "are not a judge.")

    # Content and human labels, in order of first appearance.
    content: dict[str, dict] = {}
    for r in all_records:
        c = content.setdefault(r.target_id, {})
        if r.input is not None:
            c.setdefault("input", r.input)
        if r.output is not None:
            c.setdefault("output", r.output)
        for k, v in r.agent().items():
            if k not in c:
                c[k] = scrub_value(v)
    label_of = _human_labels(all_records, metric, llm_names, human_norm)
    if labels is not None:
        file_labels, file_content = _read_labels(labels, extra_map)
        both = [i for i in file_labels if i in label_of]
        if both:
            differ = sum(label_of[i] != file_labels[i] for i in both)
            notes.append(f"--labels overrides the human labels in the source for "
                         f"{_plural(len(both), 'item', 'items')} ({differ} differ).")
        label_of.update(file_labels)
        for i, c in file_content.items():
            for k, v in c.items():
                content.setdefault(i, {}).setdefault(k, v)

    if anchors_out is not None:
        write_label_anchors(anchors_out, label_of, content)

    # Judgments: one run per (file, run index).
    by_run = _judgments(files, metric, judge_norm, runs_by_order)

    judged_ids = {i for entries in by_run.values() for i in entries}
    unlabeled = [i for i in content if i in judged_ids and i not in label_of]
    unjudged = [i for i in label_of if i not in judged_ids]
    item_ids = [i for i in content if i in label_of and i in judged_ids]
    if not item_ids:
        hint = (" There are no human labels: pass --labels labels.csv (an id column and a "
                "human_label column)." if not label_of else "")
        raise RecordsError(f"no item has both a judge verdict and a human label.{hint}")
    if unlabeled:
        notes.append(f"{_plural(len(unlabeled), 'judged item has', 'judged items have')} no "
                     "human label: dropped.")
    if unjudged:
        notes.append(f"{_plural(len(unjudged), 'labeled item has', 'labeled items have')} no "
                     f"judge verdict for {metric!r}: dropped.")

    anchor_items = []
    for i in item_ids:
        c = content.get(i, {})
        item = {"id": i, "input": c.get("input", ""), "output": c.get("output", ""),
                "human_label": label_of[i]}
        if c.get("slice"):
            item["slice"] = c["slice"]  # a slice column in --labels is kept
        item.update({k: c[k] for k in AGENT_FIELDS if k in c})
        anchor_items.append(item)

    entries_fps = [e["fingerprint"] for entries in by_run.values() for e in entries.values()]
    known, fp_notes = _consensus(entries_fps)
    notes += fp_notes
    fp = make_fingerprint(known)

    out = Path(out) if out is not None else Path(tempfile.mkdtemp(prefix="judgekeeper-import-"))
    out.mkdir(parents=True, exist_ok=True)
    anchors_path = out / "anchors.jsonl"
    manifest = write_anchor_file(anchors_path, anchor_items)

    versions = [recs.version for _, recs in files if recs.version is not None]
    base_source = {
        "kind": kind, "version": versions[0] if versions else None, "metric": metric,
        "ids_derived": any(recs.ids_derived for _, recs in files),
        "n_records": len(all_records), "n_judged_unlabeled": len(unlabeled),
        "n_labeled_unjudged": len(unjudged), "notes": notes, "warnings": warnings,
    }
    base_source.update(per_metric)
    runs = [(run_value, {**base_source, "file": files[fi][0]}, by_run[(fi, run_value)])
            for fi, run_value in sorted(by_run, key=lambda k: (k[0], _run_key(k[1])))]
    return write_runs_and_report(out, anchors_path, manifest, anchor_items, runs, fp,
                                 judge_norm.describe())


def write_label_anchors(path: str | Path, label_of: dict[str, str],
                        content: dict[str, dict]) -> dict:
    """Write each labeled item (id, input, output, human_label) as an anchor set and freeze it.

    Input and output are the text the source returned, or "" when it returned none; the
    fields ready for agents (trajectory, outcome, app_version) go in when the records have
    them. Nothing else goes in: no rationales, no annotator ids. Returns the manifest.
    """
    items = []
    for i, label in label_of.items():
        c = content.get(i, {})
        item = {"id": i, "input": _or_blank(c.get("input")), "output": _or_blank(c.get("output")),
                "human_label": label}
        if c.get("slice"):
            item["slice"] = c["slice"]
        item.update({k: c[k] for k in AGENT_FIELDS if k in c})
        items.append(item)
    if not items:
        raise RecordsError("--anchors-out: no item has a human label")
    return write_anchor_file(Path(path), items)


def _or_blank(v):
    return "" if v is None else v
