import pytest

from judgekeeper.metrics import (
    agreement,
    cohen_kappa,
    confusion,
    noise_floor,
    position_bias,
)


def test_kappa_hand_computed():
    # po = 0.75, pe = 0.5*0.5 + 0.5*0.5 = 0.5 -> kappa = 0.5
    human = ["A", "A", "A", "A", "B", "B", "B", "B"]
    judge = ["A", "A", "A", "B", "B", "B", "B", "A"]
    assert cohen_kappa(human, judge) == pytest.approx(0.5)


def test_kappa_unbalanced_hand_computed():
    # human: 3 pass 1 fail; judge: 2 pass 2 fail; agree on 3/4
    # po = .75; pe = .75*.5 + .25*.5 = .5 -> kappa = .5
    human = ["pass", "pass", "pass", "fail"]
    judge = ["pass", "pass", "fail", "fail"]
    assert cohen_kappa(human, judge) == pytest.approx(0.5)


def test_kappa_perfect_and_inverse():
    assert cohen_kappa(["A", "B", "A"], ["A", "B", "A"]) == pytest.approx(1.0)
    assert cohen_kappa(["A", "B"], ["B", "A"]) == pytest.approx(-1.0)


def test_kappa_undefined_when_chance_agreement_is_one():
    assert cohen_kappa(["pass", "pass"], ["pass", "pass"]) is None


def test_kappa_rejects_length_mismatch_and_empty():
    with pytest.raises(ValueError):
        cohen_kappa(["A"], ["A", "B"])
    with pytest.raises(ValueError):
        cohen_kappa([], [])


def test_judge_passes_everything_high_accuracy_zero_kappa():
    human = ["pass"] * 9 + ["fail"]
    judge = ["pass"] * 10
    res = agreement(human, judge, positive="pass", negative="fail")
    assert res["accuracy"] == pytest.approx(0.9)
    assert res["kappa"] == pytest.approx(0.0)
    assert res["tpr"] == pytest.approx(1.0)
    assert res["tnr"] == pytest.approx(0.0)
    assert res["confusion"] == {"tp": 9, "fn": 0, "fp": 1, "tn": 0, "invalid": 0}


def test_confusion_counts_invalid_as_wrong():
    human = ["A", "B", "A", "B"]
    judge = ["A", None, None, "A"]
    c = confusion(human, judge, positive="A", negative="B")
    assert c == {"tp": 1, "fn": 1, "fp": 2, "tn": 0, "invalid": 2}
    res = agreement(human, judge, positive="A", negative="B")
    assert res["tpr"] == pytest.approx(0.5)
    assert res["tnr"] == pytest.approx(0.0)
    assert res["n_invalid"] == 2


def test_tpr_tnr_undefined_without_class():
    res = agreement(["A", "A"], ["A", "B"], positive="A", negative="B")
    assert res["tnr"] is None
    assert res["tpr"] == pytest.approx(0.5)


def test_noise_floor_hand_computed():
    runs = {
        "i1": ["A", "A", "A"],
        "i2": ["A", "B", "A"],
        "i3": ["B", "B", "B"],
        "i4": ["B", "B", "A"],
    }
    nf = noise_floor(runs)
    assert nf["n_runs"] == 3
    assert nf["items_flipped_fraction"] == pytest.approx(0.5)
    assert nf["mean_item_flip_rate"] == pytest.approx((1 / 3 + 1 / 3) / 4)
    per_item = {row["id"]: row for row in nf["per_item"]}
    assert per_item["i2"]["majority"] == "A"
    assert per_item["i2"]["flip_rate"] == pytest.approx(1 / 3)
    assert per_item["i4"]["majority"] == "B"
    assert nf["majority"] == {"i1": "A", "i2": "A", "i3": "B", "i4": "B"}
    # run1 vs run2: A,A,B,B vs A,B,B,B. po=.75, pe=.5*.25+.5*.75=.5 -> .5
    # run1 vs run3: A,A,B,B vs A,A,B,A. po=.75, pe=.5*.75+.5*.25=.5 -> .5
    # run2 vs run3: A,B,B,B vs A,A,B,A. po=.5, pe=.25*.75+.75*.25=.375 -> .2
    pk = {tuple(row["runs"]): row["kappa"] for row in nf["pairwise_kappa"]}
    assert pk[(1, 2)] == pytest.approx(0.5)
    assert pk[(1, 3)] == pytest.approx(0.5)
    assert pk[(2, 3)] == pytest.approx(0.2)
    assert nf["mean_pairwise_kappa"] == pytest.approx(1.2 / 3)
    assert nf["test_retest_agreement"] == pytest.approx((0.75 + 0.75 + 0.5) / 3)


def test_noise_floor_tie_has_no_majority():
    nf = noise_floor({"i1": ["A", "B"], "i2": ["A", "A"]})
    assert nf["majority"]["i1"] is None
    assert nf["n_ties"] == 1


def test_noise_floor_single_run():
    nf = noise_floor({"i1": ["A"], "i2": ["B"]})
    assert nf["n_runs"] == 1
    assert nf["items_flipped_fraction"] == 0.0
    assert nf["pairwise_kappa"] == []
    assert nf["mean_pairwise_kappa"] is None
    assert nf["test_retest_agreement"] is None


def test_position_bias_hand_computed():
    # verdicts in original labels; ab picks first when "A", ba picks first when "B"
    ab = ["A", "A", "B", "B"]
    ba = ["A", "B", "B", "B"]
    pb = position_bias(ab, ba)
    assert pb["inconsistency_rate"] == pytest.approx(0.25)
    # first picks: ab -> 2, ba -> 3; 5/8
    assert pb["p_first"] == pytest.approx(5 / 8)
    assert pb["first_position_bias"] == pytest.approx(1 / 8)


def test_position_bias_always_first_slot():
    pb = position_bias(["A", "A"], ["B", "B"])
    assert pb["inconsistency_rate"] == pytest.approx(1.0)
    assert pb["p_first"] == pytest.approx(1.0)
    assert pb["first_position_bias"] == pytest.approx(0.5)
