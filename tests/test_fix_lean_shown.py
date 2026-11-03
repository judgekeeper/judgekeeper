"""fix's "leans toward" words follow the counts on screen: the plain fixed and broke. The
weighted counts decide only better, safe to try and worse."""

from judgekeeper import fix, targets

# 3 fixed and 3 broken; the broken ones are in a group 10 times as big, so weighted they lean
STRATA = [(100, 0, 3, 10), (10, 3, 0, 10)]


def test_equal_counts_on_screen_never_lean():
    v = targets.fix_verdict(3, 3, 20, strata=STRATA)
    assert v.kind == "leans worse"  # the weighted counts
    assert fix.shown_kind(v.kind, v.fixed, v.broke) == "same"
    assert fix.RESULT[fix.shown_kind(v.kind, 3, 3)] == ("Result: can't tell yet. The two rules "
                                                         "look about the same here.")


def test_a_lean_on_screen_is_the_plain_counts_lean():
    assert fix.shown_kind("leans worse", 4, 3) == "leans better"
    assert fix.shown_kind("leans better", 2, 3) == "leans worse"
    assert fix.shown_kind("same", 1, 0) == "leans better"


def test_better_safe_and_worse_stay_as_tested():
    for kind in ("better", "safe", "worse"):
        assert fix.shown_kind(kind, 3, 3) == kind
