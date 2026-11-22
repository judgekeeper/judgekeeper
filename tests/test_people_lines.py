"""The lines judgekeeper prints about how much people agree (people.lines)."""

from judgekeeper import people


def _label(k):
    return "pass" if k % 3 else "fail"


def _block(n_shared=12, people_n=2):
    ratings = [(f"i{k}", str(who), _label(k) if who == 2 or k % 4 else "pass")
               for k in range(n_shared) for who in range(2, 2 + people_n)]
    return people.analyse(ratings, {f"i{k}": _label(k) for k in range(n_shared)})


def test_two_people_line_and_the_limit_line():
    out = people.lines(_block())
    first = out[0]
    assert first.startswith("Your people agree with each other: kappa ")
    assert " (between " in first
    assert first.endswith("on 12 answers labelled by more than one person.")
    assert ("A check can't be expected to agree with your people more than they agree with "
            "each other.") in out


def test_three_people_say_what_alpha_is():
    out = people.lines(_block(people_n=3))
    assert out[0].startswith("Your people agree with each other: Krippendorff's alpha ")
    assert "on 12 answers labelled by more than one person." in out[0]


def test_fewer_than_ten_says_so_and_gives_no_number():
    out = people.lines(_block(n_shared=9))
    text = "\n".join(out)
    assert ("Fewer than 10 answers were labelled by more than one person, so judgekeeper "
            "can't say how much your people agree.") in out
    assert "Your people agree with each other" not in text
    assert "A check can't be expected" not in text


def test_answers_by_person_and_the_check_against_each_person():
    out = people.lines(_block())
    assert any(x.startswith("Answers labelled by each person: user 2 (12), user 3 (12)")
               for x in out)
    against = [x for x in out if x.startswith("Your check against user ")]
    assert len(against) == 2
    assert against[0].startswith("Your check against user 2: kappa 1.00; ")
    assert "it passes 100% of what they passed and fails 100% of what they failed" in against[0]
    assert against[0].endswith("(on 12 answers).")


def test_no_raw_agreement_and_no_trust_words():
    text = " ".join(people.lines(_block()) + people.lines(_block(n_shared=3))).lower()
    for word in ("accuracy", "trusted", "proven", "agreement rate"):
        assert word not in text


def test_everyone_the_same_label():
    ratings = [(f"i{k}", who, "pass") for k in range(12) for who in ("2", "3")]
    out = people.lines(people.analyse(ratings, None))
    assert ("Your people gave the same label to every answer, so how much they agree beyond "
            "coincidence can't be worked out.") in out


def test_no_block_no_lines():
    assert people.lines(None) == []


def test_many_people_are_cut_with_a_count():
    ratings = [(f"i{k}", str(who), "pass" if (k + who) % 3 else "fail")
               for k in range(12) for who in range(14)]
    line = next(x for x in people.lines(people.analyse(ratings, None))
                if x.startswith("Answers labelled by each person: "))
    assert line.endswith(" and 4 more.")
