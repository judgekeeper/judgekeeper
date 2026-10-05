"""Judgments files: one JSONL file per run.

Line 1 is a header: {"type": "header", "run", "anchors_sha256", "fingerprint", "source"} and,
for imported or custom judges, "normaliser" (the --pass-if rule and label map used).
`source` says where the verdicts came from: {"kind": "judgekeeper" | "table" | "callable" |
"exec" | "promptfoo" | "deepeval" | "inspect" | "records", "file", "metric"}; imports add
"version" (the tool's own format version), "notes" and "warnings". A file written by an early version has no `source` and reads as
judgekeeper.
Every following line is {"type": "judgment", "id", "verdict", "raw_score", "rationale",
"fingerprint", and for pairwise items "verdict_ba", "raw_score_ba", "rationale_ba"}. A verdict
of "error" means the judge raised, returned nothing or returned something unparseable; the
line then has an "error" field.
Every judgment line carries the full fingerprint, with `snapshot` as served for that call
and `created_at` as the time of that judgment. Free text (rationales, error text) and every
string in a fingerprint (the served model id comes from the provider) are scrubbed of
credentials on the way to disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.redact import scrub, scrub_fingerprint
from judgekeeper.runners.base import Judgment
from judgekeeper.textio import read_utf8

# Fields of a judgment line that hold text from the model or the provider.
FREE_TEXT_FIELDS = ("rationale", "rationale_ba", "error", "error_ba")


class JudgmentsError(Exception):
    pass


def default_source() -> dict:
    return {"kind": "judgekeeper", "file": None, "metric": None}


def judgment_to_record(item_id: str, j: Judgment, fp: JudgeFingerprint) -> dict:
    rec = {
        "type": "judgment",
        "id": item_id,
        "verdict": j.verdict,
        "raw_score": j.raw_score,
        "rationale": j.rationale,
    }
    if j.error:
        rec["error"] = j.error
    if j.swapped is not None:
        rec["verdict_ba"] = j.swapped.verdict
        rec["raw_score_ba"] = j.swapped.raw_score
        rec["rationale_ba"] = j.swapped.rationale
        if j.swapped.error:
            rec["error_ba"] = j.swapped.error
    rec["fingerprint"] = fp.to_dict()
    return rec


def record_to_judgment(rec: dict) -> Judgment:
    snapshot = (rec.get("fingerprint") or {}).get("snapshot")
    swapped = None
    if "verdict_ba" in rec:
        swapped = Judgment(
            verdict=rec["verdict_ba"],
            raw_score=rec.get("raw_score_ba"),
            rationale=rec.get("rationale_ba", ""),
            snapshot=snapshot,
            error=rec.get("error_ba"),
        )
    return Judgment(
        verdict=rec.get("verdict"),
        raw_score=rec.get("raw_score"),
        rationale=rec.get("rationale", ""),
        swapped=swapped,
        snapshot=snapshot,
        error=rec.get("error"),
    )


def _scrubbed(rec: dict, seen: dict) -> dict:
    out = {k: scrub(v) if k in FREE_TEXT_FIELDS and isinstance(v, str) else v
           for k, v in rec.items()}
    if "fingerprint" in out:
        out["fingerprint"] = scrub_fingerprint(out["fingerprint"], seen)
    return out


def _scrub_value(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, list):
        return [scrub(x) if isinstance(x, str) else x for x in v]
    return v


def write_run(path: Path, run: int, anchors_sha256: str, fp: JudgeFingerprint,
              records: list[dict], source: dict | None = None,
              normaliser: dict | None = None) -> None:
    """The one place judgment lines are written to disk."""
    seen: dict = {}  # fingerprint strings already scrubbed: most repeat on every line
    header = {
        "type": "header",
        "run": run,
        "anchors_sha256": anchors_sha256,
        "fingerprint": scrub_fingerprint(fp.to_dict(), seen),
        "source": {k: _scrub_value(v) for k, v in (source or default_source()).items()},
    }
    if normaliser is not None:
        header["normaliser"] = normaliser
    lines = [json.dumps(header, ensure_ascii=False)]
    lines += [json.dumps(_scrubbed(r, seen), ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_run(path: str | Path) -> tuple[dict, dict[str, dict]]:
    """Return (header, {item_id: record})."""
    path = Path(path)
    rows = []
    for n, line in enumerate(read_utf8(path, JudgmentsError).splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            raise JudgmentsError(f"{path}: line {n}: invalid JSON") from None
    if not rows or rows[0].get("type") != "header":
        raise JudgmentsError(f"{path}: first line must be a header")
    header = rows[0]
    if "fingerprint" not in header:
        raise JudgmentsError(f"{path}: header has no fingerprint")
    try:
        JudgeFingerprint.from_dict(header["fingerprint"])
    except ValueError as e:
        raise JudgmentsError(f"{path}: {e}") from None
    records: dict[str, dict] = {}
    for rec in rows[1:]:
        if rec.get("type") != "judgment" or "id" not in rec:
            raise JudgmentsError(f"{path}: malformed judgment line {rec!r:.80}")
        if "fingerprint" not in rec:
            raise JudgmentsError(f"{path}: judgment {rec['id']} has no fingerprint")
        records[rec["id"]] = rec
    return header, records
