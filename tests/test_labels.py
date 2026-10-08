"""Labels: the label-quality warnings in every report, and a labels sheet whose ids
judgekeeper guarded against spreadsheet formulas (as `start` writes labels.csv)."""

import csv

from judgekeeper.anchors import load_verified
from judgekeeper.cli import main


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_label_quality_warnings_appear_in_every_report(tmp_path):
    from judgekeeper import check_table

    rows = [{"id": f"p{i}", "verdict": "pass", "label": "pass"} for i in range(70)]
    rows += [{"id": f"f{i}", "verdict": "fail", "label": "fail"} for i in range(10)]
    r = check_table(rows, out=tmp_path)
    codes = {f["code"] for f in r["verdict"]["flags"]}
    assert "lopsided_labels" in codes and "few_labels" not in codes
    assert r["label_quality"]["largest_class_share"] == 70 / 80


def test_guarded_ids_in_a_sheet_match_their_items(tmp_path):
    """`import --labels` reads a sheet judgekeeper wrote: the quote on an id must not hide its
    label (security review, finding 1)."""
    ids = ("=x", "@y")
    sheet = tmp_path / "labels.csv"
    _write(sheet, [{"id": "'" + i, "input": "q", "output": f"a{n}", "human_label": label,
                    "notes": ""} for n, (i, label) in enumerate(zip(ids, ("pass", "fail")))])
    records = tmp_path / "records.csv"
    _write(records, [{"id": i, "metric": "q", "value": v, "kind": "llm"}
                     for i, v in zip(ids, ("pass", "fail"))])
    out = tmp_path / "out"
    assert main(["import", "records", str(records), "--map",
                 "target_id=id,name=metric,label=value,annotator_kind=kind",
                 "--labels", str(sheet), "--out", str(out)]) == 0
    items, _ = load_verified(out / "anchors.jsonl")
    assert {i["id"]: i["human_label"] for i in items} == {"=x": "pass", "@y": "fail"}
