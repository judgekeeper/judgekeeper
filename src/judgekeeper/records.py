"""ScoreRecords: one verdict per record, the format every framework reader produces.

Field names follow OpenInference annotations, so other tools' exports map onto it by renaming:
`target_id, name, annotator_kind ("LLM" | "HUMAN" | "CODE"), label, score, explanation, run,
input, output, evaluator {provider, model, prompt, temperature, version}, created_at`.
`evaluator` also accepts `prompt_hash`, `snapshot` and `endpoint`, which `export records` writes
because judgekeeper keeps only the hash of a prompt, never its text.

`records_to_report` pivots records into the files `check` writes: HUMAN records become anchor
labels, LLM records become judgments (one run per source file and run index), CODE records are
ignored. Then the report pipeline (normaliser, unknown-tolerant fingerprint, report) runs as
for `check`. Nothing here knows about any framework; see judgekeeper.readers.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from judgekeeper.anchors import PAIRWISE, SINGLE
from judgekeeper.fingerprint import ENDPOINT_UNKNOWN, IDENTITY_FIELDS
from judgekeeper.metrics import ERROR
from judgekeeper.normalise import Normaliser, UnmappedValue, parse_label_map, unmapped_error
from judgekeeper.table import (
    TableError,
    _blank,
    _listed,
    _run_key,
    derive_id,
    make_fingerprint,
    read_table,
    sheet_id,
    write_anchor_file,
    write_runs_and_report,
)

LLM, HUMAN, CODE = "LLM", "HUMAN", "CODE"
KINDS = (LLM, HUMAN, CODE)
_KIND_ALIASES = {"LLM_JUDGE": LLM, "JUDGE": LLM, "HUMAN_ANNOTATION": HUMAN, "HEURISTIC": CODE}
FIELDS = ("target_id", "name", "annotator_kind", "label", "score", "explanation", "run",
          "input", "output", "evaluator", "created_at")
EVALUATOR_KEYS = ("provider", "model", "prompt", "temperature", "version", "prompt_hash",
                  "snapshot", "endpoint")
DEFAULT_NAME = "judge"


class RecordsError(TableError):
    """The records cannot be turned into a report: a usage error."""


def derive_record_id(input, output) -> str:
    """table.derive_id over an item's input and output, with a missing value read as ""."""
    return derive_id({"input": "" if input is None else input,
                      "output": "" if output is None else output})


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

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in FIELDS}

    @classmethod
    def from_dict(cls, d: dict) -> ScoreRecord:
        unknown = sorted(set(d) - set(FIELDS))
        if unknown:
            raise RecordsError(f"unknown ScoreRecord field(s) {unknown}; fields are "
                               f"{', '.join(FIELDS)}")
        kind = "LLM" if _blank(d.get("annotator_kind")) else str(d["annotator_kind"]).strip()
        kind = _KIND_ALIASES.get(kind.upper(), kind.upper())
        if kind not in KINDS:
            raise RecordsError(f"annotator_kind {d.get('annotator_kind')!r} is not one of "
                               f"{', '.join(KINDS)}")
        return cls(
            target_id=None if _blank(d.get("target_id")) else str(d["target_id"]).strip(),
            name=DEFAULT_NAME if _blank(d.get("name")) else str(d["name"]),
            annotator_kind=kind,
            label=None if _blank(d.get("label")) else d["label"],
            score=_number(d.get("score")),
            explanation=None if _blank(d.get("explanation")) else str(d["explanation"]),
            run=_run(d.get("run")),
            input=_content(d.get("input")),
            output=_content(d.get("output")),
            evaluator=_evaluator(d.get("evaluator")),
            created_at=None if _blank(d.get("created_at")) else str(d["created_at"]),
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
    if _blank(v):
        return {}
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            raise RecordsError(f"evaluator {v[:60]!r} is not a JSON object") from None
    if not isinstance(v, dict):
        raise RecordsError("evaluator must be an object with provider, model, prompt, "
                           "temperature and version")
    bad = sorted(set(v) - set(EVALUATOR_KEYS))
    if bad:
        raise RecordsError(f"unknown evaluator field(s) {bad}; allowed: "
                           f"{', '.join(EVALUATOR_KEYS)}")
    return {k: val for k, val in v.items() if not (_blank(val) and k != "endpoint")}


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
        if (key not in FIELDS and sub not in EVALUATOR_KEYS) or not column:
            raise RecordsError(f"--map entries look like field=column with field one of "
                               f"{', '.join(FIELDS)} or evaluator.<{'|'.join(EVALUATOR_KEYS)}>; "
                               f"got {key}={column}")
        out[key] = column
    return out


def read_records(path: str | Path, column_map: str | dict | None = None) -> RecordList:
    """ScoreRecords from a JSONL, CSV or TSV file. `column_map` renames source columns."""
    rows = read_table(path)
    mapping = parse_map(column_map)
    columns = list(dict.fromkeys(k for r in rows for k in r))
    missing = [c for c in mapping.values() if c not in columns]
    if missing:
        raise RecordsError(f"--map names column(s) {missing} not in {Path(path).name}; "
                           f"columns are: {', '.join(columns)}")
    records = RecordList()
    for row in rows:
        d = {f: row.get(mapping.get(f, f)) for f in FIELDS if mapping.get(f, f) in row}
        ev = _evaluator(d.get("evaluator")) if "evaluator" in d else {}
        for k in EVALUATOR_KEYS:
            col = mapping.get(f"evaluator.{k}", f"evaluator.{k}")
            if col in row and not _blank(row[col]):
                ev[k] = row[col]
        d["evaluator"] = ev
        rec = ScoreRecord.from_dict(d)
        if rec.target_id is None:
            rec.target_id = derive_record_id(rec.input, rec.output)
            records.ids_derived = True
        records.append(rec)
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
        item_id = sheet_id(row["id"])  # a sheet from `template` or `label` guards its ids
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
            known = dict(r.evaluator)
            if "version" in known:
                known["rubric_version"] = known.pop("version")
            entries[r.target_id] = {"verdict": verdict, "rationale": r.explanation or "",
                                    "fingerprint": make_fingerprint(known, r.created_at)}
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
            item["slice"] = c["slice"]  # a slice column in --labels, as import-labels keeps it
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

    Input and output are the text the source returned, or "" when it returned none. Nothing
    else goes in: no rationales, no annotator ids. Returns the manifest.
    """
    items = []
    for i, label in label_of.items():
        c = content.get(i, {})
        item = {"id": i, "input": _or_blank(c.get("input")), "output": _or_blank(c.get("output")),
                "human_label": label}
        if c.get("slice"):
            item["slice"] = c["slice"]
        items.append(item)
    if not items:
        raise RecordsError("--anchors-out: no item has a human label")
    return write_anchor_file(Path(path), items)


def _or_blank(v):
    return "" if v is None else v


# judgekeeper's own runs back out as ScoreRecords ----------------------------------------

def _evaluator_from(fp: dict) -> dict:
    ev = {k: fp.get(k) for k in ("provider", "model", "snapshot", "prompt_hash", "temperature")
          if fp.get(k) is not None}
    if fp.get("rubric_version") is not None:
        ev["version"] = fp["rubric_version"]
    if fp.get("endpoint") != ENDPOINT_UNKNOWN:
        ev["endpoint"] = fp.get("endpoint")
    return ev


def _locate(source: Path, anchors: Path | None) -> tuple[Path, Path | None]:
    if source.is_file() and source.suffix == ".json":
        source = source.parent
    if not source.is_dir():
        raise RecordsError(f"{source} is not a report or runs directory")
    if (source / "runs").is_dir():
        if anchors is None and (source / "anchors.jsonl").is_file():
            anchors = source / "anchors.jsonl"
        source = source / "runs"
    if not list(source.glob("*.jsonl")):
        raise RecordsError(f"no run files (*.jsonl) in {source}")
    return source, anchors


def export_records(source: str | Path, out: str | Path, anchors: str | Path | None = None) -> int:
    """Write judgekeeper runs (and the anchor set's human labels) as ScoreRecords JSONL.

    `source` is a directory written by `check` or `import` (anchors.jsonl and runs/), its
    report.json, or a runs directory (pass `anchors` for the human labels and the item text).
    Returns the number of records written.
    """
    from judgekeeper.judgments import JudgmentsError, read_run
    from judgekeeper.report import ReportError, load_runs

    runs_dir, anchors = _locate(Path(source), Path(anchors) if anchors else None)
    if anchors is not None:
        try:
            items, manifest, runs = load_runs(anchors, runs_dir)
        except ReportError as e:
            raise RecordsError(str(e)) from None
        if manifest["kind"] == PAIRWISE:
            raise RecordsError("ScoreRecords hold single-output items; this anchor set is "
                               "pairwise")
        headers = [r["header"] for r in runs]
        run_records = [r["records"] for r in runs]
    else:
        items = []
        headers, run_records = [], []
        for path in sorted(runs_dir.glob("*.jsonl")):
            try:
                h, recs = read_run(path)
            except JudgmentsError as e:
                raise RecordsError(str(e)) from None
            headers.append(h)
            run_records.append(recs)
    by_id = {i["id"]: i for i in items}
    name = (headers[0].get("source") or {}).get("metric") or DEFAULT_NAME
    out_records = [ScoreRecord(target_id=i["id"], name=name, annotator_kind=HUMAN,
                               label=i["human_label"], input=i.get("input"),
                               output=i.get("output")) for i in items]
    for header, recs in zip(headers, run_records):
        ids = [i["id"] for i in items] if items else list(recs)
        for item_id in ids:
            rec = recs[item_id]
            fp = rec.get("fingerprint") or {}
            verdict = rec.get("verdict")
            item = by_id.get(item_id, {})
            out_records.append(ScoreRecord(
                target_id=item_id, name=name, annotator_kind=LLM,
                label=None if verdict == ERROR else verdict, score=rec.get("raw_score"),
                explanation=rec.get("rationale") or None, run=header.get("run"),
                input=item.get("input"), output=item.get("output"),
                evaluator=_evaluator_from(fp), created_at=fp.get("created_at")))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                           for r in out_records), encoding="utf-8")
    return len(out_records)
