"""Tables: CSV, TSV or JSONL rows (or a list of dicts, or a pandas DataFrame) as dicts, the
ids derived from them, a judge fingerprint from what is known, and the guard for cells a
spreadsheet would run as a formula.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from pathlib import Path

from judgekeeper.anchors import PAIRWISE, SINGLE, canonical_json, freeze
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, JudgeFingerprint, utc_now
from judgekeeper.redact import printable
from judgekeeper.textio import jsonl_lines, make_private, read_utf8, write_replacing

ID_LENGTH = 16
# A long answer or a RAG context fills one cell: Python's csv stops at 131,072 characters
csv.field_size_limit(2**31 - 1)  # the largest every platform takes (a C long on Windows)
_MAX_LISTED = 20
FINGERPRINT_KEYS = ("provider", "model", "snapshot", "endpoint", "prompt", "prompt_hash",
                    "rubric_version", "temperature")


# The column names judgekeeper looks for. In a file they match ignoring case and the spaces
# around them, as a spreadsheet's header is often typed ("Input", " Verdict").
KNOWN_COLUMNS = frozenset({
    "id", "run", "input", "output", "output_a", "output_b", "verdict", "judge_verdict",
    "judge", "label", "human_label", "reason", "notes", "score", "model", "judge_model",
    "app_version"})


def column_name(name):
    """`name` as judgekeeper knows it ("Input " is input); any other name as it is."""
    if isinstance(name, str):
        plain = name.strip().lower()
        if plain in KNOWN_COLUMNS:
            return plain
    return name


def _known_names(row: dict) -> dict:
    """The row with judgekeeper's own column names written as it knows them; when a file has
    both "input" and "Input", the one already named input is kept."""
    if all(column_name(k) == k for k in row):
        return row
    out = {}
    for k, v in row.items():
        name = column_name(k)
        if name in out and name != k:
            out.setdefault(k, v)
        elif name != k and name in row:
            out[k] = v
        else:
            out[name] = v
    return out


class TableError(Exception):
    """The table cannot be read as judgments: a usage error."""


def _delimiter(text: str, suffix: str) -> str:
    """The separator of a spreadsheet file, from its header line.

    A .csv is not always comma-separated: Excel writes semicolons in locales where the comma
    is the decimal mark, and some exports write tabs. A header with no comma at all, but with
    semicolons or tabs, is read with that separator. A header with a comma is a comma CSV,
    whatever else is in it.
    """
    if suffix == ".tsv":
        return "\t"
    header = text.split("\n", 1)[0]
    if "," not in header:
        for other in (";", "\t"):
            if other in header:
                return other
    return ","


_DECIMAL_COMMA = re.compile(r"\s*-?\d+,\d+\s*")


def csv_rows(text: str, suffix: str) -> list[dict]:
    return [row for _, row in csv_numbered(text, suffix)]


def csv_numbered(text: str, suffix: str) -> list[tuple[int, dict]]:
    """[(line number, row)] of a CSV or TSV text, each row a dict, without the rows where
    every cell is empty (a spreadsheet's trailing rows). In a `;` file (Excel where the comma
    is the decimal mark) a cell like 0,42 is the number 0.42, written 0.42."""
    delimiter = _delimiter(text, suffix)
    out = []
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    for row in reader:
        cells = [v for k, v in row.items() if k is not None and isinstance(v, str)]
        if not any(v.strip() for v in cells):
            continue
        if delimiter == ";":
            row = {k: v.replace(",", ".") if isinstance(v, str) and _DECIMAL_COMMA.fullmatch(v)
                   else v for k, v in row.items()}
        out.append((reader.line_num, row))
    return out


def read_table(path: str | Path) -> list[dict]:
    """Rows of a CSV, TSV or JSONL file as dicts. CSV values stay strings.

    The file must be UTF-8 (a byte order mark is fine); anything else is a TableError that
    says how to save it.
    """
    path = Path(path)
    if not path.is_file():
        raise TableError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        text = read_utf8(path, TableError)
        return [_known_names(r) for r in csv_rows(text, suffix)]
    if suffix in (".jsonl", ".ndjson", ".json"):
        rows = []
        for n, line in enumerate(jsonl_lines(read_utf8(path, TableError)), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise TableError(f"{path}: line {n}: invalid JSON ({e.msg})") from None
            if not isinstance(row, dict):
                raise TableError(f"{path}: line {n}: each line must be a JSON object")
            rows.append(_known_names(row))
        return rows
    raise TableError(f"{path}: expected a .csv, .tsv or .jsonl file")


def open_quote(path: str | Path, loose: bool = False) -> int | None:
    """The line where a quoted cell of a CSV or TSV file starts that swallows the rows after
    it (its quote never closes, or closes only rows later), or None. A cell swallowed rows
    when two lines or more inside it read as whole rows: one value per column, and a grade
    in the verdict column when the table has one (an answer over several lines, with commas,
    is not a row); with `loose`, when it holds a line break at all (a hint, not a finding)."""
    from judgekeeper.find import VERDICT_COLUMNS

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".tsv"):
        return None
    text = read_utf8(path, TableError)
    delimiter = _delimiter(text, suffix)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header, start, verdict = None, 1, None
    try:
        for row in reader:
            if header is None:
                header = row
                verdict = next((i for i, c in enumerate(header)
                                if column_name(c) in VERDICT_COLUMNS), None)
            elif any(loose or (len(header) >= 3 and _rows_inside(cell, delimiter,
                                                                 len(header), verdict) >= 2)
                     for cell in row if "\n" in cell):
                return start
            start = reader.line_num + 1
    except csv.Error as e:
        if loose or "unexpected end of data" in str(e):  # loose: any quote out of place
            return start
    return None


def _rows_inside(cell: str, delimiter: str, columns: int, verdict: int | None) -> int:
    """How many lines of a cell read as a whole row of `columns` values, with a grade at
    `verdict` (when the table has a verdict column)."""
    from judgekeeper.mapper import _verdict_value

    rows = (next(csv.reader([line], delimiter=delimiter), []) for line in cell.split("\n"))
    return sum(len(r) == columns and (verdict is None or _verdict_value(r[verdict]))
               for r in rows)


def kind_of(columns) -> str:
    return PAIRWISE if "output_a" in columns and "output_b" in columns else SINGLE


def derive_id(item: dict) -> str:
    """sha256 of the canonical input plus output(s), first 16 hex characters."""
    keys = ("input", "output_a", "output_b") if kind_of(item) == PAIRWISE else ("input", "output")
    content = {k: item.get(k, "") for k in keys}
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()[:ID_LENGTH]


def make_fingerprint(known: dict | None, created_at: str | None = None) -> JudgeFingerprint:
    """A fingerprint from whatever the user knows; every other field is unknown."""
    known = dict(known or {})
    bad = sorted(set(known) - set(FINGERPRINT_KEYS))
    if bad:
        raise TableError(f"unknown fingerprint field(s) {bad}; allowed: "
                         f"{', '.join(FINGERPRINT_KEYS)}")
    prompt = known.pop("prompt", None)
    if prompt is not None and "prompt_hash" not in known:
        known["prompt_hash"] = hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()
    known.setdefault("endpoint", ENDPOINT_UNKNOWN)
    if known.get("temperature") is not None:
        known["temperature"] = float(known["temperature"])
    return JudgeFingerprint(**known, created_at=created_at or utc_now())


def _blank(v) -> bool:
    if isinstance(v, float):
        return math.isnan(v)  # an empty cell in a pandas DataFrame
    return v is None or (isinstance(v, str) and not v.strip())


def _listed(values) -> str:
    values = list(values)
    more = f" and {len(values) - _MAX_LISTED} more" if len(values) > _MAX_LISTED else ""
    return ", ".join(repr(v) for v in values[:_MAX_LISTED]) + more


def write_anchor_file(path: Path, items: list[dict]) -> dict:
    make_private(path.parent)
    write_replacing(path, "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items),
                    newline="\n")  # the same bytes on every system
    return freeze(path)


TEMPLATE_COLUMNS = {SINGLE: ("id", "input", "output", "human_label", "notes"),
                    PAIRWISE: ("id", "input", "output_a", "output_b", "human_label", "notes")}


# A cell starting with one of these runs as a formula in Excel, Google Sheets and LibreOffice;
# some read the full-width forms, or spaces or characters no one sees before them, as the same.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\uff1d", "\uff0b", "\uff0d", "\uff20")


def _formula(text: str) -> bool:
    for i, ch in enumerate(text):
        if text.startswith(FORMULA_PREFIXES, i):
            return True
        if ch != " " and printable(ch):  # printable drops the unseen characters
            return False
    return False


def guard_cell(text: str) -> str:
    """Prefix a would-be formula with a quote, the way Excel marks a cell as text."""
    return "'" + text if _formula(text) else text


def unguard_cell(text: str) -> str:
    """Undo `guard_cell` when reading a sheet judgekeeper wrote."""
    return text[1:] if text.startswith("'") and _formula(text[1:]) else text


def _plain(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def sheet_id(value) -> str:
    """An id cell as the item's id: trimmed, and without the quote `guard_cell` put on it."""
    return unguard_cell(str(value).strip())


def _with_ids(rows: list[dict]) -> list[tuple[str, dict]]:
    out = []
    for row in rows:
        given = row.get("id")
        out.append((sheet_id(given) if not _blank(given) else derive_id(row), row))
    counts = Counter(i for i, _ in out)
    dups = [i for i, n in counts.items() if n > 1]
    if dups:
        raise TableError(f"duplicate ids: {_listed(dups)}; add a unique id column")
    return out
