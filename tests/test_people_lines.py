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
    assert first.startswith("The people marking agree with each other: kappa ")
    assert " (between " in first
    assert first.endswith("on 12 answers labelled by more than one person.")
    assert ("A check can't be expected to agree with the people marking more than they agree "
            "with each other.") in out


def test_three_people_say_what_alpha_is():
    out = people.lines(_block(people_n=3))
    assert out[0].startswith("The people marking agree with each other: Krippendorff's alpha ")
    assert "on 12 answers labelled by more than one person." in out[0]


def test_fewer_than_ten_says_so_and_gives_no_number():
    out = people.lines(_block(n_shared=9))
    text = "\n".join(out)
    assert ("Fewer than 10 answers were labelled by more than one person, so judgekeeper "
            "can't say how much the people marking agree.") in out
    assert "The people marking agree with each other" not in text
    assert "A check can't be expected" not in text


def test_answers_by_person_and_the_check_against_each_person():
    out = people.lines(_block())
    assert any(x.startswith("Answers labelled by each person: user 2 (12), user 3 (12)")
               for x in out)
    against = [x for x in out if x.startswith("Your check against user ")]
    assert len(against) == 2
    assert against[0] == (
        "Your check against user 2, on 12 answers: kappa 1.00. When user 2 says Pass, your "
        "check also says Pass 100% of the time; when user 2 says Fail, it also says Fail "
        "100% of the time.")


def test_no_raw_agreement_and_no_trust_words():
    text = " ".join(people.lines(_block()) + people.lines(_block(n_shared=3))).lower()
    for word in ("accuracy", "trusted", "proven", "agreement rate"):
        assert word not in text


def test_everyone_the_same_label():
    ratings = [(f"i{k}", who, "pass") for k in range(12) for who in ("2", "3")]
    out = people.lines(people.analyse(ratings, None))
    assert ("The people marking gave the same label to every answer, so how much they agree "
            "beyond coincidence can't be worked out.") in out


def test_no_block_no_lines():
    assert people.lines(None) == []


def test_many_people_are_cut_with_a_count():
    ratings = [(f"i{k}", str(who), "pass" if (k + who) % 3 else "fail")
               for k in range(12) for who in range(14)]
    line = next(x for x in people.lines(people.analyse(ratings, None))
                if x.startswith("Answers labelled by each person: "))
    assert line.endswith(" and 4 more.")


def _against(tpr, tnr, kappa=0.5, who="2", n=10):
    block = {"enough": True, "value": 0.5, "measure": "kappa", "interval": [0.1, 0.9],
             "shared": 10, "per_person": {who: n},
             "vs_check": {who: {"n": n, "kappa": kappa, "tpr": tpr, "tnr": tnr}}}
    return people.lines(block)[-1]


def test_a_person_who_passed_nothing_has_no_pass_rate_said():
    assert _against(None, 0.8) == (
        "Your check against user 2, on 10 answers: kappa 0.50. User 2 passed none of these "
        "answers; when user 2 says Fail, it also says Fail 80% of the time.")


def test_a_person_who_failed_nothing_has_no_fail_rate_said():
    assert _against(0.6, None) == (
        "Your check against user 2, on 10 answers: kappa 0.50. When user 2 says Pass, your "
        "check also says Pass 60% of the time; user 2 failed none of these answers.")


def test_kappa_undefined_stays_n_a_and_never_says_unknown_of_the_time():
    line = _against(None, None, kappa=None)
    assert "kappa n/a." in line and "unknown" not in line
    assert "passed none of these answers" in line and "failed none of these answers" in line


def _crowd(n_people: int, answers=lambda who: 12 - who % 3):
    """Many people on the answers: person `who` labelled the first `answers(who)` of 12."""
    ratings = [(f"i{k}", str(who), "pass" if (k + who) % 3 else "fail")
               for who in range(n_people) for k in range(answers(who))]
    check = {f"i{k}": ("pass" if k % 2 else "fail") for k in range(12)}
    return people.analyse(ratings, check)


def _about(out):
    return [x for x in out if x.startswith("Your check against user ")]


def test_the_check_against_each_person_is_cut_at_ten_people_with_the_most_answers():
    block = _crowd(13)
    assert len(block["vs_check"]) == 13  # all of them stay in the result
    out = people.lines(block)
    shown = {x.split(",")[0].removeprefix("Your check against user ") for x in _about(out)}
    counts = {w: v["n"] for w, v in block["vs_check"].items()}
    cut = set(counts) - shown
    assert len(shown) == 10 and len(cut) == 3
    assert min(counts[w] for w in shown) >= max(counts[w] for w in cut)
    assert out[-1] == "Your check against the other 3 people is in .judgekeeper/result.json."


def test_ten_people_or_fewer_get_every_line_and_no_cut_line():
    out = people.lines(_crowd(10))
    assert len(_about(out)) == 10
    assert not any("is in .judgekeeper/result.json" in x for x in out)


def test_one_person_cut_is_named_as_a_person_not_a_count_of_people():
    out = people.lines(_crowd(11, answers=lambda who: 12))
    assert out[-1] == "Your check against the other person is in .judgekeeper/result.json."


def test_the_people_shown_keep_the_order_of_their_numbers_when_they_tie():
    out = people.lines(_crowd(13, answers=lambda who: 12))
    assert [x.split(",")[0].split()[-1] for x in _about(out)] == [str(i) for i in range(10)]
