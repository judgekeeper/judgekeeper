"""`judgekeeper check` and `check_table`: a table of verdicts and labels in, a report out.

Fixture numbers, derived by hand. Ten items, q1-q6 human pass, q7-q10 human fail.
Runs 1 and 3: judge passes q1-q5 and q10, fails q6-q9. Run 2: same, but passes q6.

  run 1, 3: TP 5, FN 1, TN 3, FP 1 -> TPR 5/6, TNR 3/4,
            po 0.8, pe (6*6 + 4*4)/100 = 0.52, kappa 0.28/0.48 = 7/12
  run 2:    TP 6, FN 0, TN 3, FP 1 -> TPR 1, TNR 3/4,
            po 0.9, pe (6*7 + 4*3)/100 = 0.54, kappa 0.36/0.46 = 18/23
  means:    TPR 8/9, TNR 3/4, kappa (2*7/12 + 18/23)/3; one item (q6) of ten flipped.

scores.jsonl is run 1 alone as scores (pass iff score >= 0.5), no id and no run column.
"""

import hashlib
import json

import pytest

from judgekeeper import check_table
from judgekeeper.anchors import canonical_json
from judgekeeper.cli import main
from judgekeeper.gate import FLAKY, evaluate
from judgekeeper.normalise import NormaliseError
from judgekeeper.table import TableError, derive_id
from tests.conftest import FIXTURES

CSV = FIXTURES / "check" / "results.csv"
JSONL = FIXTURES / "check" / "scores.jsonl"
K1 = 7 / 12
K2 = 18 / 23


def test_check_csv_with_run_column(tmp_path):
    out = tmp_path / "rep"
    assert main(["check", str(CSV), "--judge", "verdict", "--human", "label", "--id", "id",
                 "--run", "run", "--out", str(out)]) == 0
    r = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert (out / "report.html").is_file()
    assert r["n_runs"] == 3
    h = r["headline"]
    assert h["tpr_mean"] == pytest.approx(8 / 9)
    assert h["tnr_mean"] == pytest.approx(0.75)
    assert h["kappa_mean"] == pytest.approx((2 * K1 + K2) / 3)
    assert [x["kappa"] for x in r["runs"]] == pytest.approx([K1, K2, K1])
    assert r["noise_floor"]["items_flipped_fraction"] == pytest.approx(0.1)
    assert r["noise_floor"]["status"] == "measured"
    assert r["source"]["kind"] == "table"
    assert r["source"]["file"] == "results.csv"
    assert r["source"]["metric"] == "verdict"
    assert r["source"]["ids_derived"] is False
    # the rule and the map are in the report, so it can be reproduced
    assert r["normaliser"]["label_map"]["yes"] == "pass"
    # rationale comes from the reason column
    q6 = next(d for d in r["disagreements"] if d["id"] == "q6")
    assert q6["rationale"] == "run 1 on q6"
    # the same files `validate` reads
    assert (out / "anchors.jsonl").is_file() and (out / "anchors.manifest.json").is_file()
    assert sorted(p.name for p in (out / "runs").iterdir()) == [
        "run-01.jsonl", "run-02.jsonl", "run-03.jsonl"]


def test_check_column_flags_default_to_their_names(tmp_path):
    assert main(["check", str(CSV), "--out", str(tmp_path / "a")]) == 0
    r = json.loads((tmp_path / "a" / "report.json").read_text(encoding="utf-8"))
    assert r["n_runs"] == 3 and r["source"]["ids_derived"] is False


def test_every_judgment_on_disk_has_a_fingerprint_and_source(tmp_path):
    check_table(CSV, out=tmp_path)
    lines = (tmp_path / "runs" / "run-01.jsonl").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["source"]["kind"] == "table"
    assert header["normaliser"]["pass_if"] is None
    assert "fingerprint" in header
    for line in lines[1:]:
        rec = json.loads(line)
        assert rec["fingerprint"]["created_at"]
        assert rec["fingerprint"]["model"] is None
        assert rec["fingerprint"]["endpoint"] == "unknown"


def test_check_jsonl_single_run_derived_ids(tmp_path):
    out = tmp_path / "rep"
    assert main(["check", str(JSONL), "--judge", "score", "--pass-if", "score>=0.5",
                 "--out", str(out)]) == 0
    r = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert r["n_runs"] == 1
    assert r["headline"]["tpr_mean"] == pytest.approx(5 / 6)
    assert r["headline"]["tnr_mean"] == pytest.approx(0.75)
    assert r["headline"]["kappa_mean"] == pytest.approx(K1)
    # noise floor is unknown, never zero
    nf = r["noise_floor"]
    assert nf["status"] == "unknown: one run supplied"
    assert nf["items_flipped_fraction"] is None and nf["mean_item_flip_rate"] is None
    assert "unknown: one run supplied" in (out / "report.html").read_text(encoding="utf-8")
    # ids derived from the input and output, and the report says so
    first = json.loads(JSONL.read_text(encoding="utf-8").splitlines()[0])
    expected = hashlib.sha256(canonical_json(
        {"input": first["input"], "output": first["output"]}).encode()).hexdigest()[:16]
    assert derive_id(first) == expected
    assert expected in {row["id"] for row in r["items"]}
    assert r["source"]["ids_derived"] is True
    assert any("derived" in n for n in r["notes"])
    assert r["normaliser"]["pass_if"] == "score>=0.5"
    # raw scores are kept
    run = (out / "runs" / "run-01.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(x)["raw_score"] for x in run[1:]} >= {0.95, 0.49}
    # gate on a one-run report is FLAKY, with that reason
    g = evaluate(r)
    assert g["status"] == FLAKY
    assert "one run supplied" in g["reason"].lower()
    assert main(["gate", str(out / "report.json")]) == 4


def test_duplicate_ids_are_a_usage_error(tmp_path, capsys):
    path = tmp_path / "dup.csv"
    path.write_text("id,verdict,label\na,pass,pass\nb,fail,fail\na,fail,pass\nb,pass,fail\n"
                    "c,pass,pass\n")
    assert main(["check", str(path), "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "duplicate" in err and "'a'" in err and "'b'" in err and "'c'" not in err
    with pytest.raises(TableError):
        check_table(path, out=tmp_path / "o2")


def test_derived_duplicate_ids_are_a_usage_error(tmp_path):
    rows = [{"input": "same", "output": "x", "verdict": "pass", "label": "pass"}] * 2
    with pytest.raises(TableError, match="duplicate"):
        check_table(rows, out=tmp_path)


def test_unmapped_values_are_a_usage_error_listing_them(tmp_path, capsys):
    path = tmp_path / "t.csv"
    path.write_text("id,verdict,label\na,good,pass\nb,bad,fail\nc,pass,pass\n")
    assert main(["check", str(path), "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "'good'" in err and "'bad'" in err and "--label-map" in err
    assert main(["check", str(path), "--label-map", "good=pass,bad=fail",
                 "--out", str(tmp_path / "o")]) == 0


def test_number_without_pass_if_is_usage_error(tmp_path):
    with pytest.raises(NormaliseError, match="--pass-if"):
        check_table(JSONL, judge="score", out=tmp_path)


def test_judge_errors_are_excluded_counted_and_flagged(tmp_path):
    rows = [{"id": f"p{i}", "verdict": "pass", "label": "pass"} for i in range(8)]
    rows += [{"id": f"f{i}", "verdict": "fail", "label": "fail"} for i in range(8)]
    rows += [{"id": "e1", "verdict": "", "label": "fail"},
             {"id": "e2", "verdict": None, "label": "pass"}]
    r = check_table(rows, out=tmp_path)
    assert r["headline"]["tpr_mean"] == 1.0 and r["headline"]["tnr_mean"] == 1.0
    assert r["runs"][0]["n"] == 16 and r["runs"][0]["n_error"] == 2
    assert r["errors"]["n"] == 2 and r["errors"]["items"] == ["e1", "e2"]
    assert "judge_errors" in {f["code"] for f in r["verdict"]["flags"]}
    assert not any(d["id"].startswith("e") for d in r["disagreements"])


def test_rows_with_no_human_label_are_dropped_and_counted(tmp_path):
    rows = [{"id": "a", "verdict": "pass", "label": "pass"},
            {"id": "b", "verdict": "fail", "label": "fail"},
            {"id": "c", "verdict": "fail", "label": ""}]
    r = check_table(rows, out=tmp_path)
    assert r["anchors"]["n_items"] == 2
    assert r["source"]["n_unlabeled"] == 1


def test_missing_column_is_a_usage_error(tmp_path, capsys):
    assert main(["check", str(CSV), "--judge", "nope", "--out", str(tmp_path)]) == 2
    assert "nope" in capsys.readouterr().err


def test_check_table_accepts_a_dataframe_like_object(tmp_path):
    class FakeFrame:
        def __init__(self, rows):
            self.rows = rows

        def to_dict(self, orient):
            assert orient == "records"
            return self.rows

    rows = [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines()]
    r = check_table(FakeFrame(rows), judge="score", pass_if="score>=0.5", out=tmp_path)
    assert r["headline"]["kappa_mean"] == pytest.approx(K1)


def test_check_table_without_out_uses_a_temp_dir():
    r = check_table(CSV)
    assert r["n_runs"] == 3


def test_check_table_fingerprint_fields_are_recorded(tmp_path):
    r = check_table(CSV, out=tmp_path, fingerprint={"model": "my-judge", "temperature": 0.0,
                                                    "prompt": "Grade it."})
    fp = r["fingerprint"]
    assert fp["model"] == "my-judge" and fp["temperature"] == 0.0
    assert fp["prompt_hash"] == hashlib.sha256(b"Grade it.").hexdigest()
    assert "model" not in r["fingerprint_unknown"]
    flag = next(f for f in r["verdict"]["flags"] if f["code"] == "identity_incomplete")
    assert flag["message"] == ("judge identity incomplete: provider, snapshot, endpoint, "
                               "rubric_version")


def test_three_column_csv_in_one_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.csv").write_text("id,verdict,label\n" + "".join(
        f"r{i},{'pass' if i % 3 else 'fail'},{'pass' if i % 2 else 'fail'}\n" for i in range(12)),
            encoding="utf-8")
    assert main(["check", "results.csv"]) == 0
    assert (tmp_path / "judgekeeper-report" / "report.html").is_file()
