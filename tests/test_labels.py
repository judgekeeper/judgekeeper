"""Labels: the label-quality warnings in every report, and a labels sheet whose ids
judgekeeper guarded against spreadsheet formulas (as `start` writes labels.csv)."""

import csv

import pytest

from judgekeeper.anchors import load_verified
from judgekeeper.cli import main


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _report(tmp_path, n_pass, n_fail, wrong_fails=0):
    """A table whose judge gets every label right except `wrong_fails` of the fails."""
    from judgekeeper import check_table

    rows = [{"id": f"p{i}", "verdict": "pass", "label": "pass"} for i in range(n_pass)]
    rows += [{"id": f"f{i}", "verdict": "pass" if i < wrong_fails else "fail", "label": "fail"}
             for i in range(n_fail)]
    return check_table(rows, out=tmp_path)


def _flags(r) -> dict:
    return {f["code"]: f["message"] for f in r["verdict"]["flags"]}


def test_too_few_of_one_kind_is_too_few_for_a_rough_check(tmp_path):
    r = _report(tmp_path, 70, 10)  # plenty passed, too few failed
    assert _flags(r)["too_few_labels"] == ("Too few labels for a rough check (70 labeled pass, "
                                           "10 labeled fail): it needs 15 of each.")
    assert r["label_quality"] == {"n_labeled": 80, "per_class": {"pass": 70, "fail": 10},
                                  "check": "too_few", "wide": {}}


def test_a_rough_check_says_what_a_reliable_result_needs(tmp_path):
    r = _report(tmp_path, 30, 20)
    assert _flags(r)["rough_check"] == ("Rough check (30 labeled pass, 20 labeled fail): a "
                                        "reliable result needs 25 of each.")
    assert r["label_quality"]["check"] == "rough"


def test_twenty_five_of_each_with_a_wide_range_is_not_reliable_yet(tmp_path):
    r = _report(tmp_path, 25, 25, wrong_fails=8)  # TNR 17/25: its 95% range is wide
    lo, hi = r["headline"]["tnr_ci"]["lo"], r["headline"]["tnr_ci"]["hi"]
    assert hi - lo > 0.30
    assert _flags(r)["not_reliable_yet"] == (
        f"Not reliable yet: the range for answers people failed is still {hi - lo:.2f} wide. "
        "Label more answers to narrow it.")
    assert r["label_quality"]["check"] == "rough"
    assert r["label_quality"]["wide"] == {"tnr": pytest.approx(hi - lo)}


def test_a_reliable_result_has_no_label_flag(tmp_path):
    r = _report(tmp_path, 40, 40, wrong_fails=1)
    assert r["label_quality"]["check"] == "reliable"
    assert not {"too_few_labels", "rough_check", "not_reliable_yet"} & set(_flags(r))


def test_the_old_label_flags_are_gone(tmp_path):
    r = _report(tmp_path, 70, 10)
    assert not {"few_labels", "lopsided_labels"} & set(_flags(r))
    assert "largest_class" not in r["label_quality"]


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
