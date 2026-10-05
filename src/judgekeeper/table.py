"""A table of judge verdicts and human labels in, a judgekeeper report out.

`check_table` turns CSV or JSONL rows (or a list of dicts, or a pandas DataFrame) into the
files the rest of judgekeeper reads: a frozen anchor set, one run file per run, then the usual
`validate` pipeline. One row per judgment; several rows for one id with different run values
are repeat runs.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from judgekeeper.anchors import PAIRWISE, SINGLE, canonical_json, freeze
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, JudgeFingerprint, utc_now
from judgekeeper.judgments import judgment_to_record, write_run
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, unmapped_error
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import read_utf8

ID_LENGTH = 16
_MAX_LISTED = 20
FINGERPRINT_KEYS = ("provider", "model", "snapshot", "endpoint", "prompt", "prompt_hash",
                    "rubric_version", "temperature")


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
        return list(csv.DictReader(io.StringIO(text, newline=""),
                                   delimiter=_delimiter(text, suffix)))
    if suffix in (".jsonl", ".ndjson", ".json"):
        rows = []
        for n, line in enumerate(read_utf8(path, TableError).splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise TableError(f"{path}: line {n}: invalid JSON ({e.msg})") from None
            if not isinstance(row, dict):
                raise TableError(f"{path}: line {n}: each line must be a JSON object")
            rows.append(row)
        return rows
    raise TableError(f"{path}: expected a .csv, .tsv or .jsonl file")


def as_rows(data) -> tuple[list[dict], str | None]:
    """(rows, file name) from a path, a list of dicts or a DataFrame-like object."""
    if isinstance(data, str | Path):
        return read_table(data), Path(data).name
    if hasattr(data, "to_dict"):  # pandas, without importing it
        return list(data.to_dict(orient="records")), None
    rows = list(data)
    if not all(isinstance(r, dict) for r in rows):
        raise TableError("rows must be dicts (or pass a file path or a DataFrame)")
    return rows, None


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


def _run_key(value) -> tuple:
    text = str(value).strip()
    try:
        return (0, float(text), text)
    except ValueError:
        return (1, 0.0, text)


def write_anchor_file(path: Path, items: list[dict]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items),
                    encoding="utf-8")
    return freeze(path)


def check_table(data, judge: str = "verdict", human: str = "label", id: str | None = None,
                run: str | None = None, input: str | None = None, output: str | None = None,
                reason: str | None = None, pass_if: str | None = None,
                label_map: dict | str | None = None, fingerprint: dict | None = None,
                out: str | Path | None = None) -> dict:
    """Build a report from a table of judge verdicts and human labels; return report.json.

    `id`, `run`, `input`, `output` and `reason` default to columns of those names when
    present. Without an id column, ids are derived from the input and output. Without a run
    column, there is one run and the noise floor is reported as unknown. `fingerprint` takes
    whatever is known about the judge (model, prompt text, temperature...); the rest is
    unknown. Files go under `out` (a temporary directory if None).
    """
    rows, file_name = as_rows(data)
    if not rows:
        raise TableError("the table has no rows")
    columns = list(dict.fromkeys(k for r in rows for k in r))

    def col(name: str | None, default: str, required: bool = False) -> str | None:
        name = name or (default if default in columns else None)
        if name is not None and name not in columns:
            raise TableError(f"no column {name!r}; columns are: {', '.join(columns)}")
        if required and name is None:
            raise TableError(f"no column {default!r}; columns are: {', '.join(columns)}")
        return name

    judge_col = col(judge, judge, required=True)
    human_col = col(human, human, required=True)
    id_col, run_col = col(id, "id"), col(run, "run")
    input_col, reason_col = col(input, "input"), col(reason, "reason")
    kind = kind_of(columns) if output is None else SINGLE
    output_cols = ("output_a", "output_b") if kind == PAIRWISE else (col(output, "output"),)
    if id_col is None and input_col is None:
        raise TableError("without an id column, ids are derived from the input: name the id "
                         "column with --id or the input column with --input")

    judge_norm = Normaliser(kind, pass_if=pass_if, label_map=label_map)
    human_norm = Normaliser(kind, label_map=label_map)

    # Pass 1: content, ids, labels. Every unmapped value is collected before failing.
    entries = []
    unmapped_judge, unmapped_human = [], []
    for row in rows:
        content = {"input": row.get(input_col, "") if input_col else ""}
        for c, key in zip(output_cols, ("output_a", "output_b") if kind == PAIRWISE
                          else ("output",)):
            content[key] = row.get(c, "") if c else ""
        item_id = str(row[id_col]).strip() if id_col and not _blank(row.get(id_col)) else None
        if id_col and item_id is None:
            raise TableError(f"a row has an empty {id_col!r}")
        item_id = item_id or derive_id(content)
        try:
            verdict = judge_norm(row.get(judge_col))
        except UnmappedValue as e:
            unmapped_judge.append(e.value)
            verdict = None
        try:
            label = human_norm(row.get(human_col)).verdict
        except UnmappedValue as e:
            unmapped_human.append(e.value)
            label = None
        run_value = "1" if run_col is None or _blank(row.get(run_col)) else str(row[run_col])
        rationale = "" if not reason_col or _blank(row.get(reason_col)) else str(row[reason_col])
        entries.append({"id": item_id, "run": run_value.strip(), "content": content,
                        "verdict": verdict, "label": label, "rationale": rationale})
    if unmapped_human:
        raise unmapped_error(unmapped_human, f"human label ({human_col!r})", pass_if=False)
    if unmapped_judge:
        raise unmapped_error(unmapped_judge, f"judge verdict ({judge_col!r})",
                             pass_if=kind != PAIRWISE)

    per_run = Counter((e["run"], e["id"]) for e in entries)
    dups = list(dict.fromkeys(i for (_, i), n in per_run.items() if n > 1))
    if dups:
        hint = "" if id_col else " (ids derived from identical input and output)"
        raise TableError(f"duplicate ids within a run{hint}: {_listed(dups)}. Use --run to mark "
                         "repeat runs, or --id to name a unique id column.")

    # Items: one per id with a human label; conflicting labels are an error.
    items: dict[str, dict] = {}
    labels: dict[str, set] = defaultdict(set)
    for e in entries:
        if e["label"] not in (None, ERROR):
            labels[e["id"]].add(e["label"])
        items.setdefault(e["id"], {"id": e["id"], **e["content"]})
    conflicts = [i for i, s in labels.items() if len(s) > 1]
    if conflicts:
        raise TableError(f"items with different human labels in different rows: "
                         f"{_listed(conflicts)}")
    unlabeled = [i for i in items if i not in labels]
    anchor_items = [{**items[i], "human_label": next(iter(labels[i]))}
                    for i in items if i in labels]
    if not anchor_items:
        raise TableError(f"no row has a human label in column {human_col!r}")

    out = Path(out) if out is not None else Path(tempfile.mkdtemp(prefix="judgekeeper-check-"))
    out.mkdir(parents=True, exist_ok=True)
    anchors_path = out / "anchors.jsonl"
    manifest = write_anchor_file(anchors_path, anchor_items)

    fp = make_fingerprint(fingerprint, utc_now())
    source = {"kind": "table", "file": file_name, "metric": judge_col,
              "ids_derived": id_col is None, "n_rows": len(rows), "n_unlabeled": len(unlabeled)}
    by_run: dict[str, dict] = defaultdict(dict)
    for e in entries:
        by_run[e["run"]][e["id"]] = e
    runs = [(r, source, by_run[r]) for r in sorted(by_run, key=_run_key)]
    return write_runs_and_report(out, anchors_path, manifest, anchor_items, runs, fp,
                                 judge_norm.describe())


def write_runs_and_report(out: Path, anchors_path: Path, manifest: dict,
                          anchor_items: list[dict], runs: list[tuple[str, dict, dict]],
                          fp: JudgeFingerprint, normaliser: dict) -> dict:
    """Write one run file per (run value, source, {id: entry}) in order, then the report.

    An entry has "verdict" (a Normalised), "rationale" and optionally "fingerprint", that
    judgment's own fingerprint (default `fp`, which goes in the run header). An anchor item
    with no entry in a run is an error judgment in that run.
    """
    from judgekeeper.report import build_report

    runs_dir = out / "runs"
    runs_dir.mkdir(exist_ok=True)
    for old in runs_dir.glob("run-*.jsonl"):
        old.unlink()
    for n, (run_value, source, entries) in enumerate(runs, 1):
        records = []
        for item in anchor_items:
            e = entries.get(item["id"])
            if e is None:
                j = Judgment(verdict=ERROR, raw_score=None, rationale="",
                             error=f"no row for this item in run {run_value!r}")
                item_fp = fp
            else:
                v = e["verdict"]
                j = Judgment(verdict=v.verdict, raw_score=v.raw_score,
                             rationale=e["rationale"] or v.rationale, error=v.error)
                item_fp = e.get("fingerprint") or fp
            records.append(judgment_to_record(item["id"], j, item_fp))
        write_run(runs_dir / f"run-{n:02d}.jsonl", n, manifest["sha256"], fp, records,
                  source=source, normaliser=normaliser)

    report = build_report(anchors_path, runs_dir)
    write_report(report, out)
    return report


def write_report(report: dict, out: Path) -> None:
    from judgekeeper.html_report import render_html

    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    (out / "report.html").write_text(render_html(report), encoding="utf-8")


TEMPLATE_COLUMNS = {SINGLE: ("id", "input", "output", "human_label", "notes"),
                    PAIRWISE: ("id", "input", "output_a", "output_b", "human_label", "notes")}


# A cell starting with one of these runs as a formula in Excel, Google Sheets and LibreOffice.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def guard_cell(text: str) -> str:
    """Prefix a would-be formula with a quote, the way Excel marks a cell as text."""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def unguard_cell(text: str) -> str:
    """Undo `guard_cell` when reading a sheet judgekeeper wrote."""
    return text[1:] if text.startswith("'") and text[1:].startswith(FORMULA_PREFIXES) else text


def _plain(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _cell(value) -> str:
    return guard_cell(_plain(value))


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


def write_template(items_path: str | Path, out_path: str | Path) -> int:
    """A labeling sheet for Excel or Google Sheets, with human_label empty. Returns rows."""
    rows = read_table(items_path)
    if not rows:
        raise TableError(f"{items_path} has no rows")
    columns = set().union(*rows)
    kind = kind_of(columns)
    needed = ("input", "output_a", "output_b") if kind == PAIRWISE else ("input", "output")
    missing = [c for c in needed if c not in columns]
    if missing:
        raise TableError(f"{items_path} has no {', '.join(missing)} column")
    header = TEMPLATE_COLUMNS[kind]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for item_id, row in _with_ids(rows):
            w.writerow([guard_cell(item_id)] + [_cell(row.get(c)) for c in header[1:-2]]
                       + ["", ""])
    return len(rows)


def import_labels(labels_path: str | Path, out_path: str | Path,
                  label_map: dict | str | None = None) -> dict:
    """Read a filled-in sheet, check every label, write and freeze the anchor set.

    Returns {"manifest", "n_labeled", "unlabeled": [ids], "quality"}.
    """
    from judgekeeper.normalise import normalise_all
    from judgekeeper.report import label_quality

    rows = read_table(labels_path)
    if not rows:
        raise TableError(f"{labels_path} has no rows")
    columns = set().union(*rows)
    if "human_label" not in columns:
        raise TableError(f"{labels_path} has no human_label column")
    kind = kind_of(columns)
    keyed = _with_ids(rows)
    labels = normalise_all(Normaliser(kind, label_map=label_map),
                           [row.get("human_label") for _, row in keyed], what="human_label",
                           pass_if=False)
    items, unlabeled = [], []
    outputs = ("output_a", "output_b") if kind == PAIRWISE else ("output",)
    for (item_id, row), label in zip(keyed, labels):
        if label.verdict == ERROR:
            unlabeled.append(item_id)
            continue
        item = {"id": item_id, "input": unguard_cell(row.get("input", "") or "")}
        item.update({c: unguard_cell(row.get(c, "") or "") for c in outputs})
        item["human_label"] = label.verdict
        for extra in ("slice", "notes"):
            if not _blank(row.get(extra)):
                item[extra] = unguard_cell(str(row[extra]))
        items.append(item)
    if not items:
        raise TableError(f"no row in {labels_path} has a human_label yet")
    manifest = write_anchor_file(Path(out_path), items)
    return {"manifest": manifest, "n_labeled": len(items), "unlabeled": unlabeled,
            "quality": label_quality(manifest)}
