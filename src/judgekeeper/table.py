"""Tables: CSV, TSV or JSONL rows (or a list of dicts, or a pandas DataFrame) as dicts, the
ids derived from them, a judge fingerprint from what is known, and the guard for cells a
spreadsheet would run as a formula.
"""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from judgekeeper.anchors import PAIRWISE, SINGLE, canonical_json, freeze
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, JudgeFingerprint, utc_now
from judgekeeper.redact import one_line, printable, scrub
from judgekeeper.textio import (
    lone_surrogate,
    make_private,
    read_utf8,
    shown_path,
    utf8_lines,
    write_replacing,
)

ID_LENGTH = 16
# Answers read from one table at most: a small file of tiny rows makes one answer per row,
# and each answer costs far more memory than its row
MAX_ROWS = 100_000
CAPPED = "Read the first {n:,} answers of {file}; the rest are left out."
_said_capped: set[str] = set()  # the tables CAPPED was said for, in this process
# Columns in one table at most: real tables have tens, and each cell of each row costs memory
# though an empty one is one byte on disk (100,000 rows of 200 take near 1 GB to read)
MAX_COLUMNS = 200
WIDE = "{file} has {n:,} columns; judgekeeper reads tables of up to {most:,}."
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


def csv_numbered(text: str, suffix: str, limit: int | None = None) -> list[tuple[int, dict]]:
    """[(line number, row)] of a CSV or TSV text, each row a dict, without the rows where
    every cell is empty (a spreadsheet's trailing rows); at most `limit` and one more. In a
    `;` file (Excel where the comma is the decimal mark) a cell like 0,42 is the number 0.42,
    written 0.42."""
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
        if limit is not None and len(out) > limit:
            break
    return out


def header(text: str, suffix: str) -> list[str]:
    """The first row of a CSV or TSV text: its column names."""
    try:
        return next(csv.reader(io.StringIO(text, newline=""),
                               delimiter=_delimiter(text, suffix)), [])
    except csv.Error:  # said when the rows are read
        return []


def _lines(text: str):
    """(line number, line) of JSONL text, split at "\n" only (textio.jsonl_lines), one at a
    time: a big file is never held as a list of lines."""
    start, n = 0, 0
    while start <= len(text):
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        n += 1
        yield n, text[start:end].removesuffix("\r")
        start = end + 1


def too_wide(columns, path: str | Path, error: type[Exception]) -> None:
    """Raise `error` (WIDE) when a table's header or row has more than MAX_COLUMNS columns."""
    if len(columns) > MAX_COLUMNS:
        raise error(WIDE.format(file=Path(path).name, n=len(columns), most=MAX_COLUMNS) +
                    " Save a copy without the columns you don't need.")


def capped(rows: list, path: str | Path, say: bool = True) -> list:
    """`rows` cut to MAX_ROWS; CAPPED is said once for `path` (on stderr, as the reading
    lines are) when that leaves rows out."""
    if len(rows) <= MAX_ROWS:
        return rows
    key = str(Path(path).resolve())
    if say and key not in _said_capped:
        _said_capped.add(key)
        line = CAPPED.format(n=MAX_ROWS, file=Path(path).name)
        print(one_line(scrub(line)), file=sys.stderr, flush=True)  # as every line said
    return rows[:MAX_ROWS]


def read_table(path: str | Path, say: bool = True, cap: bool = True) -> list[dict]:
    """Rows of a CSV, TSV or JSONL file as dicts, MAX_ROWS at most (`capped`: said once,
    unless `say` is False), or every row without `cap`. CSV values stay strings.

    The file must be UTF-8 (a byte order mark is fine); anything else is a TableError that
    says how to save it. A JSONL line holding a lone surrogate (\\ud800) is one too.
    """
    path = Path(path)
    if not path.is_file():
        raise TableError(f"file not found: {shown_path(path)}")
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        text = read_utf8(path, TableError)
        too_wide(header(text, suffix), path, TableError)
        rows = [r for _, r in csv_numbered(text, suffix, MAX_ROWS if cap else None)]
        return [_known_names(r) for r in (capped(rows, path, say) if cap else rows)]
    if suffix in (".jsonl", ".ndjson", ".json"):
        rows = []
        for n, line in _lines(read_utf8(path, TableError)):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise TableError(f"{path.name}: line {n}: invalid JSON") from None
            if not isinstance(row, dict):
                raise TableError(f"{path.name}: line {n}: each line must be a JSON object")
            if lone_surrogate(row):
                raise TableError(f"{path.name}: line {n} holds a character that isn't text (a "
                                 "lone surrogate such as \\ud800), so it can't be read.")
            too_wide(row, path, TableError)
            rows.append(_known_names(row))
            if cap and len(rows) > MAX_ROWS:
                break
        return capped(rows, path, say) if cap else rows
    raise TableError(f"{shown_path(path)}: expected a .csv, .tsv or .jsonl file")


def read_kept(path: str | Path, keep) -> list[dict]:
    """read_table(path, cap=False), one row at a time, each row holding only the columns
    `keep(name)` is true for (written as judgekeeper knows them): a big file's other cells
    are never held, nor the file's whole text."""
    from contextlib import closing

    path = Path(path)
    if not path.is_file():
        raise TableError(f"file not found: {shown_path(path)}")
    suffix = path.suffix.lower()
    rows = []
    if suffix in (".csv", ".tsv"):
        with closing(utf8_lines(path, TableError)) as lines:
            first = next(lines, "")
            delimiter = _delimiter(first, suffix)
            reader = csv.reader(itertools.chain([first], lines) if first else iter(()),
                                delimiter=delimiter)
            names = next(reader, [])
            too_wide(names, path, TableError)
            kept = [(i, name) for i, name in enumerate(names) if keep(name)]
            for cells in reader:  # as csv_numbered: a row with every cell empty is no row
                if not any(c.strip() for c in cells[:len(names)]):
                    continue
                row = {name: cells[i] if i < len(cells) else None for i, name in kept}
                if delimiter == ";":
                    row = {k: v.replace(",", ".") if isinstance(v, str)
                           and _DECIMAL_COMMA.fullmatch(v) else v for k, v in row.items()}
                rows.append(_known_names(row))
        return rows
    if suffix in (".jsonl", ".ndjson", ".json"):
        with closing(utf8_lines(path, TableError, newline="\n")) as lines:
            for n, line in enumerate(lines, 1):  # split at "\n" only, as _lines
                line = line.removesuffix("\n").removesuffix("\r")
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    raise TableError(f"{path.name}: line {n}: invalid JSON") from None
                if not isinstance(row, dict):
                    raise TableError(f"{path.name}: line {n}: each line must be a JSON object")
                if lone_surrogate(row):
                    raise TableError(f"{path.name}: line {n} holds a character that isn't text "
                                     "(a lone surrogate such as \\ud800), so it can't be read.")
                too_wide(row, path, TableError)
                rows.append(_known_names({k: v for k, v in row.items() if keep(k)}))
        return rows
    raise TableError(f"{shown_path(path)}: expected a .csv, .tsv or .jsonl file")


def problem(path: str | Path) -> str | None:
    """Why a table found in a folder can't be read as one, in a few words, or None. Read as
    `judgekeeper` reads it (read_table, open_quote), nothing said; of a CSV or TSV only the
    first row is made, as read_table makes them (the time goes in making every row)."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if open_quote(path) is not None:
            return "has a quote that never closes"
        if suffix in (".csv", ".tsv"):
            text = read_utf8(path, TableError)
            too_wide(header(text, suffix), path, TableError)
            if not csv_numbered(text, suffix, 0):
                return "has no rows"
        elif not read_table(path, say=False):
            return "has no rows"
    except TableError as e:
        return "is not saved as UTF-8" if "UTF-8" in str(e) else "can't be read"
    except (OSError, ValueError, RecursionError, csv.Error):
        return "can't be read"
    return None


def open_quote(path: str | Path, loose: bool = False) -> int | None:
    """The line where a quoted cell of a CSV or TSV file starts that swallows the rows after
    it (its quote never closes, or closes only rows later), or None. A cell swallowed rows
    when a quote closes on a later line that began as a row, with text after it, or two
    lines or more inside it read as whole rows: one value per column, and a grade in the verdict column (or, with
    none, the score column) when the table has one (an answer over several lines, with
    commas, is not a row); with `loose`, when it holds a line break at all (a hint, not a
    finding)."""
    from judgekeeper.find import VERDICT_COLUMNS

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".tsv"):
        return None
    from contextlib import closing

    with closing(utf8_lines(path, TableError)) as lines:  # never the whole text at once
        return _open_quote(path, lines, suffix, loose, VERDICT_COLUMNS)


def _open_quote(path: Path, lines, suffix: str, loose: bool, verdict_columns) -> int | None:
    first = next(lines, "")
    delimiter = _delimiter(first, suffix)
    reader = csv.reader(itertools.chain([first], lines) if first else iter(()),
                        delimiter=delimiter, strict=True)
    header, start, verdict = None, 1, None
    try:
        for row in itertools.islice(reader, MAX_ROWS + 1):  # the rows read_table reads
            if header is None:
                header = row
                verdict = next((i for i, c in enumerate(header)
                                if column_name(c) in verdict_columns), None)
                if verdict is None:  # find.grade_columns: with no verdict column, the score
                    verdict = next((i for i, c in enumerate(header)
                                    if column_name(c) == "score"), None)
            elif any(loose or (len(header) >= 3 and _rows_inside(cell, delimiter,
                                                                 len(header), verdict) >= 2)
                     for cell in row if "\n" in cell):
                return start
            start = reader.line_num + 1
    except csv.Error as e:
        # loose: any quote out of place; else one that closes on a later line, on a line
        # that began as a row (a delimiter before the quote), swallowed the rows between
        if loose or "unexpected end of data" in str(e) or (
                reader.line_num > start and delimiter in _line(path, reader.line_num).split('"')[0]):
            return start
    return None


def _line(path: Path, number: int) -> str:
    """Line `number` (from 1) of the file at `path`, split as csv.reader splits lines."""
    from contextlib import closing

    with closing(utf8_lines(path, TableError)) as lines:
        return next(itertools.islice(lines, number - 1, None), "")


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
    data = canonical_json(content).encode("utf-8", errors="surrogatepass")  # a lone \\ud800
    return hashlib.sha256(data).hexdigest()[:ID_LENGTH]


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
        try:
            known["temperature"] = float(known["temperature"])
        except (TypeError, ValueError):  # "hot", [0.1]: kept as the results say it
            known["temperature"] = str(known["temperature"])
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
        if not ch.isspace() and printable(ch):  # any space or line break before it, and
            return False  # the unseen characters printable drops
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
