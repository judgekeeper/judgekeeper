"""End to end: replay fixtures -> validate -> report.json / report.html.

The fixture has 8 pairwise items (human A,A,A,A,B,B,B,B; slices easy/hard) and three runs.
Expected values below are computed by hand in the comments.
"""

import json

import pytest

from judgekeeper.cli import main


@pytest.fixture
def report(pairwise_dir, tmp_path):
    out = tmp_path / "report"
    code = main(
        ["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"), "--out", str(out)]
    )
    assert code == 0
    assert (out / "report.html").exists()
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_fingerprint_echoed(report):
    fp = report["fingerprint"]
    assert fp["provider"] == "anthropic"
    assert fp["model"] == "claude-haiku-4-5-20251001"
    assert fp["rubric_version"] == "pairwise-v1"
    assert fp["temperature"] == 0.0
    assert set(fp) >= {"snapshot", "prompt_hash", "created_at"}
    assert report["anchors"]["n_items"] == 8
    assert report["anchors"]["kind"] == "pairwise"


def test_per_run_metrics(report):
    runs = report["runs"]
    assert [r["run"] for r in runs] == [1, 2, 3]
    # run1: TP3 FN1 TN3 FP1 -> kappa .5, TPR .75, TNR .75
    assert runs[0]["kappa"] == pytest.approx(0.5)
    assert runs[0]["tpr"] == pytest.approx(0.75)
    assert runs[0]["tnr"] == pytest.approx(0.75)
    assert runs[0]["confusion"] == {"tp": 3, "fn": 1, "fp": 1, "tn": 3, "invalid": 0}
    # run2: i3 flips to B. TP2 FN2 TN3 FP1. po=.625 pe=.5 -> .25
    assert runs[1]["kappa"] == pytest.approx(0.25)
    assert runs[1]["tpr"] == pytest.approx(0.5)
    assert runs[2]["kappa"] == pytest.approx(0.5)
    dis = {d["id"]: d for d in runs[0]["disagreements"]}
    assert set(dis) == {"i4", "i8"}
    assert dis["i4"]["rationale"] == "run1 i4 AB"
    assert dis["i4"]["human"] == "A" and dis["i4"]["verdict"] == "B"


def test_headline(report):
    h = report["headline"]
    assert h["kappa_mean"] == pytest.approx(1.25 / 3)
    assert h["kappa_min"] == pytest.approx(0.25)
    assert h["kappa_max"] == pytest.approx(0.5)
    assert h["tpr_mean"] == pytest.approx((0.75 + 0.5 + 0.75) / 3)
    assert h["tnr_mean"] == pytest.approx(0.75)
    assert "accuracy_mean" in h


def test_noise_floor(report):
    nf = report["noise_floor"]
    assert nf["n_runs"] == 3
    assert nf["items_flipped_fraction"] == pytest.approx(1 / 8)
    assert nf["mean_item_flip_rate"] == pytest.approx((1 / 3) / 8)
    assert nf["mean_pairwise_kappa"] == pytest.approx(2.5 / 3)
    assert nf["test_retest_agreement"] == pytest.approx((0.875 + 1 + 0.875) / 3)
    assert nf["majority_vs_human"]["kappa"] == pytest.approx(0.5)
    flipped = [row["id"] for row in nf["per_item"] if row["flip_rate"] > 0]
    assert flipped == ["i3"]


def test_position_bias(report):
    pb = report["position_bias"]
    # BA disagrees with AB on i1 in every run
    assert pb["inconsistency_rate"] == pytest.approx(0.125)
    # first-slot picks: (4+5)+(3+6)+(4+5) over 48
    assert pb["p_first"] == pytest.approx(27 / 48)
    assert pb["first_position_bias"] == pytest.approx(27 / 48 - 0.5)
    assert [r["inconsistency_rate"] for r in pb["per_run"]] == pytest.approx([0.125] * 3)


def test_slices(report):
    slices = {s["slice"]: s for s in report["slices"]}
    assert slices["easy"]["n"] == 4
    assert slices["easy"]["kappa_mean"] == pytest.approx(1.0)
    # hard: run1 kappa 0, run2 -0.5, run3 0
    assert slices["hard"]["kappa_mean"] == pytest.approx(-0.5 / 3)
    assert slices["hard"]["tpr_mean"] == pytest.approx(1 / 3)
    assert slices["hard"]["tnr_mean"] == pytest.approx(0.5)


def test_verdict_flags(report):
    codes = {f["code"] for f in report["verdict"]["flags"]}
    # The TPR/TNR rules and the label-quality warning (8 labeled items).
    assert codes == {"low_tpr", "low_tnr", "low_kappa", "position_inconsistent", "noisy",
                     "few_labels"}
    assert "not trustworthy as a gate" in report["verdict"]["summary"].lower()
    msgs = " ".join(f["message"] for f in report["verdict"]["flags"])
    assert "use majority of runs" in msgs


def test_disagreement_list(report):
    rows = {d["id"]: d for d in report["disagreements"]}
    assert set(rows) == {"i3", "i4", "i8"}
    assert rows["i3"]["verdicts"] == ["A", "B", "A"]
    assert rows["i3"]["rationale"] == "run2 i3 AB"


def test_html_is_self_contained(pairwise_dir, tmp_path):
    out = tmp_path / "r"
    main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"), "--out", str(out)])
    html = (out / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    for needle in ["claude-haiku-4-5-20251001", "not trustworthy as a gate", "Confusion matrix",
                   "Noise floor", "Position bias", "run1 i4 AB", "hard"]:
        assert needle in html
    assert "<script src" not in html and "<link" not in html and "http://" not in html


def test_html_escapes_rationales(pairwise_dir, tmp_path):
    run = pairwise_dir / "runs" / "run-01.jsonl"
    run.write_text(run.read_text(
        encoding="utf-8").replace("run1 i4 AB", "<script>alert(1)</script>"),
                   encoding="utf-8")
    out = tmp_path / "r"
    main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"), "--out", str(out)])
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_schema_version(report):
    assert report["schema_version"] == 2


def test_items_carry_per_run_and_majority_verdicts(report):
    items = {row["id"]: row for row in report["items"]}
    assert [row["id"] for row in report["items"]] == [f"i{n}" for n in range(1, 9)]
    # i1: AB says A in every run, BA says B in every run (position-dependent)
    assert items["i1"] == {"id": "i1", "slice": "easy", "human": "A",
                           "verdicts": ["A", "A", "A"], "majority": "A",
                           "verdicts_ba": ["B", "B", "B"], "majority_ba": "B"}
    # i3: run 2 flips to B in both orders; majority of three is still A
    assert items["i3"]["verdicts"] == ["A", "B", "A"]
    assert items["i3"]["majority"] == "A"
    assert items["i3"]["majority_ba"] == "A"
    assert items["i8"]["human"] == "B" and items["i8"]["majority"] == "A"
    assert all("rationale" not in row and "rationale_ba" not in row for row in items.values())
