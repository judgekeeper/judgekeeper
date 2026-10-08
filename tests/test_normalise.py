"""The verdict normaliser: one function for every import path."""

import pytest

from judgekeeper.normalise import (
    DEFAULT_LABEL_MAP,
    ERROR,
    NormaliseError,
    Normaliser,
    UnmappedValue,
    normalise_all,
    parse_label_map,
    parse_pass_if,
)


@pytest.fixture
def n():
    return Normaliser()


@pytest.mark.parametrize("raw,expected", [
    (True, "pass"), (False, "fail"),
    ("pass", "pass"), ("FAIL", "fail"), ("True", "pass"), ("false", "fail"),
    ("yes", "pass"), ("No", "fail"), ("correct", "pass"), ("Incorrect", "fail"),
    ("1", "pass"), ("0", "fail"), (1, "pass"), (0, "fail"),
    ("  pass  ", "pass"),
])
def test_default_label_map(n, raw, expected):
    assert n(raw).verdict == expected


def test_default_map_has_the_documented_pairs():
    assert DEFAULT_LABEL_MAP == {"pass": "pass", "fail": "fail", "true": "pass", "false": "fail",
                                 "yes": "pass", "no": "fail", "correct": "pass",
                                 "incorrect": "fail", "right": "pass", "wrong": "fail",
                                 "1": "pass", "0": "fail"}


@pytest.mark.parametrize("raw,expected", [
    ("PASS: the answer is right", "pass"),
    ("FAIL - it misses the date", "fail"),
    ("pass\nbecause it is fine", "pass"),
])
def test_leading_pass_fail_token(n, raw, expected):
    res = n(raw)
    assert res.verdict == expected
    assert res.rationale == raw


def test_leading_token_needs_a_word_boundary(n):
    with pytest.raises(UnmappedValue):
        n("passable answer")


def test_tuple(n):
    res = n((True, "matches the reference"))
    assert (res.verdict, res.rationale) == ("pass", "matches the reference")
    assert n(["fail", "wrong"]).verdict == "fail"


@pytest.mark.parametrize("key", ["verdict", "pass", "passed", "label", "score"])
def test_dict_verdict_keys(n, key):
    value = "pass" if key in ("verdict", "label") else True
    if key == "score":
        value = 1
    assert n({key: value}).verdict == "pass"


@pytest.mark.parametrize("key", ["reason", "rationale", "explanation", "comment"])
def test_dict_reason_keys(n, key):
    assert n({"verdict": "fail", key: "why"}).rationale == "why"


def test_number_needs_pass_if(n):
    with pytest.raises(UnmappedValue) as e:
        n(0.7)
    assert "--pass-if" in str(e.value)


@pytest.mark.parametrize("rule,raw,expected", [
    ("score>=0.5", 0.5, "pass"), ("score>=0.5", 0.49, "fail"),
    ("score > 3", 4, "pass"), ("score>3", 3, "fail"),
    ("x<=0.2", 0.1, "pass"), ("x<0.2", 0.2, "fail"), ("x==1", 1, "pass"),
    (">=0.5", "0.8", "pass"),  # numeric strings from a CSV
])
def test_pass_if(rule, raw, expected):
    res = Normaliser(pass_if=rule)(raw)
    assert res.verdict == expected
    assert res.raw_score == float(raw)


def test_pass_if_reads_named_dict_key():
    norm = Normaliser(pass_if="relevance>=3")
    res = norm({"relevance": 4, "fluency": 1, "reason": "on topic"})
    assert (res.verdict, res.raw_score, res.rationale) == ("pass", 4.0, "on topic")
    assert norm({"score": 2}).verdict == "fail"


def test_pass_if_wins_over_zero_one_map():
    assert Normaliser(pass_if="score>=0.5")("1").verdict == "pass"
    assert Normaliser(pass_if="score>=2")(1).verdict == "fail"


@pytest.mark.parametrize("rule", ["score", "score=>1", ">= abc", "score >= 1 and x"])
def test_bad_pass_if_is_usage_error(rule):
    with pytest.raises(NormaliseError):
        parse_pass_if(rule)


def test_label_map_extends_defaults():
    norm = Normaliser(label_map=parse_label_map("good=pass,Bad=fail"))
    assert norm("GOOD").verdict == "pass"
    assert norm("bad").verdict == "fail"
    assert norm("yes").verdict == "pass"


@pytest.mark.parametrize("text", ["good", "good=maybe", "=pass"])
def test_bad_label_map_is_usage_error(text):
    with pytest.raises(NormaliseError):
        parse_label_map(text)


def test_unmapped_value_lists_values_seen():
    with pytest.raises(NormaliseError) as e:
        normalise_all(Normaliser(), ["pass", "good", "bad", "good", "fail"])
    msg = str(e.value)
    assert "'good'" in msg and "'bad'" in msg and "--label-map" in msg
    assert "'pass'" not in msg


@pytest.mark.parametrize("raw", [None, "", "   ", float("nan"), [], [1, 2, 3], {"other": 1},
                                 {"verdict": None}, (None, "no verdict")])
def test_nothing_or_unparseable_is_error_not_fail(n, raw):
    res = n(raw)
    assert res.verdict == ERROR
    assert res.error


def test_pairwise_labels():
    norm = Normaliser(kind="pairwise", label_map=parse_label_map("first=A,second=B",
                                                                 kind="pairwise"))
    assert norm("a").verdict == "A"
    assert norm({"verdict": "B", "reason": "r"}).verdict == "B"
    assert norm("first").verdict == "A"
    with pytest.raises(UnmappedValue):
        norm(True)


def test_pass_if_rejected_for_pairwise():
    with pytest.raises(NormaliseError):
        Normaliser(kind="pairwise", pass_if="score>=0.5")


def test_describe_records_rule_and_map():
    d = Normaliser(pass_if="score>=0.5", label_map={"good": "pass"}).describe()
    assert d["pass_if"] == "score>=0.5"
    assert d["label_map"]["good"] == "pass"
    assert d["label_map"]["yes"] == "pass"


def test_the_label_map_advice_never_guesses_a_side():
    from judgekeeper.normalise import unmapped_error

    msg = str(unmapped_error(["Meh"]))
    assert '--label-map "Meh=pass" or --label-map "Meh=fail", whichever it means' in msg
    assert "Meh=pass," not in msg


def test_right_and_wrong_are_default_spellings():
    from judgekeeper.normalise import DEFAULT_LABEL_MAP

    assert DEFAULT_LABEL_MAP["right"] == "pass" and DEFAULT_LABEL_MAP["wrong"] == "fail"
