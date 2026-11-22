"""Agreement between people (people.py): Cohen's kappa for two, Krippendorff's alpha for three
or more, a fixed-seed range, counts per person and the check against each person."""

import pytest

from judgekeeper import people
from judgekeeper.metrics import cohen_kappa

# Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability": four observers, twelve
# units, nominal values 1 to 5, "*" missing. Its nominal alpha is 0.743.
KRIPPENDORFF = {
    "A": ["1", "2", "3", "3", "2", "1", "4", "1", "2", "*", "*", "*"],
    "B": ["1", "2", "3", "3", "2", "2", "4", "1", "2", "5", "*", "3"],
    "C": ["*", "3", "3", "3", "2", "3", "4", "2", "2", "5", "1", "*"],
    "D": ["1", "2", "3", "3", "2", "4", "4", "1", "2", "5", "1", "*"],
}


def _ratings(table: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    return [(f"u{i}", rater, v) for rater, row in table.items()
            for i, v in enumerate(row, 1) if v != "*"]


def _units(table: dict[str, list[str]]) -> list[list[str]]:
    return [[row[i] for row in table.values() if row[i] != "*"] for i in range(12)]


def test_alpha_matches_krippendorffs_worked_example():
    assert people.alpha_nominal(_units(KRIPPENDORFF)) == pytest.approx(0.743, abs=0.0005)


def test_alpha_two_raters_by_hand():
    # a: P P F F, b: P F F F. Coincidences: P-F 1 and F-P 1 (1 / (2 - 1) each); n = 8;
    # n_P = 3, n_F = 5. alpha = 1 - (8 - 1) * 2 / (2 * 3 * 5) = 1 - 14 / 30
    assert people.alpha_nominal([["P", "P"], ["P", "F"], ["F", "F"], ["F", "F"]]) == \
        pytest.approx(16 / 30)


def test_alpha_perfect_and_opposite():
    assert people.alpha_nominal([["P", "P"], ["F", "F"], ["P", "P"]]) == pytest.approx(1.0)
    # every unit split: below zero
    assert people.alpha_nominal([["P", "F"]] * 6) < 0


def test_alpha_unit_with_one_rating_is_ignored():
    units = [["P", "P"], ["F", "F"], ["P"], ["F", "P", "F"]]
    same = [["P", "P"], ["F", "F"], ["F", "P", "F"]]
    assert people.alpha_nominal(units) == pytest.approx(people.alpha_nominal(same))


def test_alpha_one_label_everywhere_is_undefined():
    assert people.alpha_nominal([["P", "P"], ["P", "P", "P"]]) is None
    assert people.alpha_nominal([["P"], ["F"]]) is None  # nothing was labelled twice


def test_kappa_for_two_people_is_cohens():
    # the textbook table: 20 yes-yes, 5 yes-no, 10 no-yes, 15 no-no: kappa 0.4
    a = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    ratings = [(f"i{k}", "2", x) for k, x in enumerate(a)] + \
              [(f"i{k}", "3", x) for k, x in enumerate(b)]
    r = people.between(ratings)
    assert r["measure"] == "kappa"
    assert r["value"] == pytest.approx(0.4) == pytest.approx(cohen_kappa(a, b))
    assert r["shared"] == 50 and r["people"] == 2
    lo, hi = r["interval"]
    assert lo < 0.4 < hi


def test_three_people_get_alpha_and_a_range():
    r = people.between(_ratings(KRIPPENDORFF))
    assert r["measure"] == "alpha" and r["people"] == 4
    assert r["value"] == pytest.approx(0.743, abs=0.0005)
    lo, hi = r["interval"]
    assert lo <= r["value"] <= hi
    assert r["shared"] == 11  # unit 12 has one rating only


def test_the_range_is_the_same_every_time():
    ratings = _ratings(KRIPPENDORFF)
    one, two = people.between(ratings), people.between(list(reversed(ratings)))
    assert one["interval"] == two["interval"]
    assert one["seed"] == people.SEED and one["draws"] == people.DRAWS


def test_fewer_than_ten_shared_answers_gives_no_number():
    ratings = [(f"i{k}", who, "P" if k % 2 else "F") for k in range(9) for who in ("2", "3")]
    r = people.between(ratings)
    assert r["enough"] is False
    assert r["value"] is None and r["interval"] == [None, None]
    assert r["shared"] == 9
    ten = ratings + [("i9", "2", "P"), ("i9", "3", "F")]
    assert people.between(ten)["enough"] is True


def test_answers_with_one_person_do_not_count_as_shared():
    ratings = [(f"i{k}", "2", "P" if k % 2 else "F") for k in range(30)]
    ratings += [(f"i{k}", "3", "P" if k % 2 else "F") for k in range(5)]
    r = people.between(ratings)
    assert r["shared"] == 5 and r["enough"] is False
    assert r["per_person"] == {"2": 30, "3": 5}


def test_one_person_has_no_agreement_block():
    assert people.between([("i1", "2", "P"), ("i2", "2", "F")]) is None
    assert people.between([]) is None


def test_a_person_who_labelled_an_answer_twice_counts_once_the_last_wins():
    ratings = [("i1", "2", "P"), ("i1", "2", "F"), ("i1", "3", "F")]
    r = people.between(ratings)
    assert r["per_person"] == {"2": 1, "3": 1}


def test_everyone_gave_the_same_label_has_no_number_but_is_counted():
    ratings = [(f"i{k}", who, "P") for k in range(12) for who in ("2", "3")]
    r = people.between(ratings)
    assert r["enough"] is True and r["value"] is None and r["interval"] == [None, None]


def test_check_against_each_person():
    check = {f"i{k}": ("pass" if k < 6 else "fail") for k in range(10)}
    ratings = [(f"i{k}", "2", check[f"i{k}"]) for k in range(10)]  # agrees with the check
    ratings += [(f"i{k}", "3", "pass") for k in range(10)]  # passes everything
    vs = people.against_check(ratings, check, "pass", "fail")
    assert vs["2"]["n"] == 10 and vs["2"]["kappa"] == pytest.approx(1.0)
    assert vs["2"]["tpr"] == 1.0 and vs["2"]["tnr"] == 1.0
    assert vs["3"]["n"] == 10
    # passes all ten: the check passed 6 of them; no Fail from this person to find
    assert vs["3"]["tpr"] == pytest.approx(0.6) and vs["3"]["tnr"] is None


def test_check_against_a_person_skips_answers_the_check_did_not_grade():
    check = {"i1": "pass", "i2": "error"}
    ratings = [("i1", "2", "pass"), ("i2", "2", "fail"), ("i3", "2", "pass")]
    vs = people.against_check(ratings, check, "pass", "fail")
    assert vs["2"]["n"] == 1


def test_analyse_holds_the_numbers_and_the_check_against_each_person():
    check = {f"i{k}": ("pass" if k % 3 else "fail") for k in range(12)}
    ratings = [(f"i{k}", who, check[f"i{k}"] if (who == "2" or k % 4) else "pass")
               for k in range(12) for who in ("2", "3")]
    r = people.analyse(ratings, check)
    assert r["people"] == 2 and r["measure"] == "kappa"
    assert set(r["vs_check"]) == {"2", "3"}
    assert r["vs_check"]["2"]["kappa"] == pytest.approx(1.0)


def test_analyse_without_a_check_has_no_vs_check():
    ratings = [(f"i{k}", who, "P" if k % 2 else "F") for k in range(12) for who in ("2", "3")]
    assert people.analyse(ratings, None)["vs_check"] == {}
    assert people.analyse([("i1", "2", "P")], None) is None
