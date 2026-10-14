"""Every number on screen says only what the marks show.

The words for each number follow the width of its range; the verdict follows the ranges,
never the point numbers or kappa; kappa has a range; a re-check keeps the groups the marks
were picked by; `check` decides from a range on the paired change.

The cases: the judge passes a share of a pool of 1,000 answers; marks in its pass group and
its fail group, and how many of each the person marked Pass.
"""

from __future__ import annotations

import random

import pytest

from judgekeeper import start_label, targets, weighted


def result(judge_passes: float, pass_group: tuple[int, int], fail_group: tuple[int, int],
           pool: int = 1000) -> dict:
    """The result for marks in each of the judge's groups: (marked, of them marked Pass)."""
    n_pass = round(pool * judge_passes)
    return start_label.describe(weighted.corrected(n_pass, pool - n_pass, *pass_group,
                                                   *fail_group))


# Words for each number follow its width ------------------------------------------------------

@pytest.mark.parametrize("points,word", [(41, "too_wide"), (40, "rough"), (31, "rough"),
                                         (30, None), (21, None), (20, "sharp")])
def test_width_words_at_the_cut_offs(points, word):
    assert targets.width_word([0.5, 0.5 + points / 100]) == word


def test_a_range_of_no_width_is_exact():
    assert targets.width_word([1.0, 1.0]) == "exact"
    assert targets.width_word([None, None]) is None


# The verdict uses the ranges -----------------------------------------------------------------

def test_s4_is_not_green():
    """Judge passes 90%; the pass group 15 of 15 marked Pass, the fail group 0 of 15."""
    r = result(0.9, (15, 15), (15, 0))
    assert r["verdict_level"] == "too_early"
    assert targets.width_word(r["tpr_interval"]) == "sharp"
    assert targets.width_word(r["tnr_interval"]) == "too_wide"


def test_s5_does_not_flip_to_red_on_one_mark():
    r = result(0.9, (16, 15), (15, 0))
    assert r["verdict_level"] == "too_early"
    assert targets.width_word(r["tnr_interval"]) == "too_wide"


@pytest.mark.parametrize("case", [(0.5, (15, 13), (15, 2)), (0.5, (15, 14), (16, 1))],
                         ids=["S1", "S3"])
def test_s1_and_s3_can_not_tell_yet(case):
    assert result(*case)["verdict_level"] == "check"


@pytest.mark.parametrize("case", [(0.9, (20, 18), (20, 4)), (0.9, (25, 25), (25, 0))],
                         ids=["S2", "S6"])
def test_s2_and_s6_fail_side_is_too_early(case):
    r = result(*case)
    assert targets.width_word(r["tnr_interval"]) == "too_wide"
    assert r["verdict_level"] == "too_early"


def test_green_is_reachable():
    assert result(0.5, (50, 50), (50, 0))["verdict_level"] == "gate"


def test_red_when_a_side_is_clearly_below_the_bar():
    r = result(0.5, (40, 38), (40, 24))  # many answers it failed should pass
    assert r["tpr_interval"][1] < targets.RATE_GATE
    assert r["verdict"] == "Your judge fails too many answers you would pass."
    assert r["verdict_level"] == "not_gate"


def test_kappa_is_not_in_the_verdict():
    """Both rates clearly above 80% on a mix where nearly every answer passes: kappa is low,
    the judge is still good enough."""
    r = result(0.876, (4000, 3990), (400, 313), pool=100_000)
    assert r["kappa"] < 0.6
    assert r["tpr_interval"][0] >= 0.8 and r["tnr_interval"][0] >= 0.8
    assert r["verdict_level"] == "gate"


def _simulate_first_result(rng: random.Random, a: float, b: float, n_pass: int,
                           n_fail: int) -> str:
    """Mark in blocks of 5 from each group until 15 Pass and 15 Fail: the verdict then. `a`
    and `b`: the chance the person marks Pass an answer of the judge's pass and fail group."""
    groups = {"pass": [0, 0], "fail": [0, 0]}
    while True:
        for g, share in (("pass", a), ("fail", b)):
            for _ in range(5):
                groups[g][0] += 1
                groups[g][1] += rng.random() < share
        marked_pass = groups["pass"][1] + groups["fail"][1]
        marked_fail = groups["pass"][0] + groups["fail"][0] - marked_pass
        if min(marked_pass, marked_fail) >= targets.ROUGH:
            r = start_label.describe(weighted.corrected(n_pass, n_fail, *groups["pass"],
                                                        *groups["fail"], draws=4000))
            return r["verdict_level"]


def test_false_green_is_rare():
    """Judge passes 90%, true TPR 0.98, true TNR 0.75: green at most 5 runs in 100."""
    tpr, tnr, judge = 0.98, 0.75, 0.9
    real = (judge - (1 - tnr)) / (tpr - (1 - tnr))  # share that should pass
    a = real * tpr / judge
    b = real * (1 - tpr) / (1 - judge)
    rng = random.Random(4041)
    runs = [_simulate_first_result(rng, a, b, 900, 100) for _ in range(400)]
    assert runs.count("gate") / len(runs) <= 0.05


# The first result and "your result is ready" -------------------------------------------------

def test_the_first_result_is_a_count_rule():
    assert result(0.5, (14, 13), (15, 1))["check"] == "too_few"
    assert result(0.5, (15, 14), (15, 1))["check"] != "too_few"


def test_ready_follows_the_widths_only():
    assert result(0.5, (50, 50), (50, 0))["check"] == "reliable"
    assert result(0.9, (25, 25), (25, 0))["check"] == "rough"  # TNR still wide
    assert not hasattr(targets, "line")


# The result in the terminal (Step 3 of 5: Measure) -------------------------------------------

def _measured(project, capsys, marks, limit: int | None = None) -> str:
    """`judgekeeper` once to start marking, the marks (`marks(group, n)`: what the person
    says to the n-th answer of the judge's group; the first `limit` answers of the page
    only), then `judgekeeper` for the result."""
    from judgekeeper.cli import main

    main(["--no-browser"])
    ws = start_label.Workspace(project)
    session = start_label.StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    seen = {"pass": 0, "fail": 0}
    for item in session.items[:limit]:
        g = groups[item["id"]]
        seen[g] += 1
        session.update({"id": item["id"], "label": marks(g, seen[g]), "seconds": 5})
    capsys.readouterr()
    assert main(["--no-browser"]) == 0
    return capsys.readouterr().out


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_result_has_each_side_on_one_line_with_its_range(project, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(project, split(30, 30))
    out = _measured(project, capsys, lambda g, n: g if n > 4 else ("fail" if g == "pass"
                                                                    else "pass"))
    lines = out.splitlines()
    assert "Step 3 of 5: Measure" in lines
    assert "Your judge vs your marks, on 60 answers:" in lines
    sides = [x for x in lines if x.startswith("  You ")]
    assert len(sides) == 2
    for line, word in zip(sides, ("passed", "failed"), strict=True):
        assert line.startswith(f"  You {word}:  your judge also {word} about ")
        assert " (could be " in line and line.endswith("%)")
    assert "These are estimates from 60 marked answers." in lines
    assert "Mark more answers to make them more precise." in lines
    assert all(len(x) <= 80 for x in lines)
    for gone in ("Kappa", "kappa", "Your marks:", "sitting", "can see a drop", "likely",
                 "Probably"):
        assert gone not in out, gone


def test_a_side_too_wide_is_too_early_to_tell(project, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(project, split(180, 20))  # the judge passes 90%: few answers fail
    out = _measured(project, capsys, lambda g, n: g, limit=30)  # 15 + 15, all agreed
    assert "  You failed:  too early to tell" in out.splitlines()
    assert "Result:" not in out
    assert out.rstrip().endswith(
        "Next: run `judgekeeper mark --no-browser` to mark more answers.")


# Kappa: re-weighted, with a range, in the details -------------------------------------------

def _true_kappa(real: float, tpr: float, tnr: float) -> float:
    judge = real * tpr + (1 - real) * (1 - tnr)
    agree = real * tpr + (1 - real) * tnr
    chance = judge * real + (1 - judge) * (1 - real)
    return (agree - chance) / (1 - chance)


@pytest.mark.parametrize("real,expected", [(0.8, 0.65), (0.9, 0.53)])
def test_kappa_is_reweighted_to_the_real_mix(real, expected):
    """Half the marks from each of the judge's groups, re-weighted: the mean kappa is the
    kappa of all the answers."""
    tpr, tnr, n = 0.90, 0.80, 50
    assert _true_kappa(real, tpr, tnr) == pytest.approx(expected, abs=0.005)
    judge = real * tpr + (1 - real) * (1 - tnr)
    a, b = real * tpr / judge, real * (1 - tpr) / (1 - judge)
    pool_pass = round(100_000 * judge)
    rng = random.Random(7)
    kappas = []
    for _ in range(300):
        c_p = sum(rng.random() < a for _ in range(n))
        c_f = sum(rng.random() < b for _ in range(n))
        kappas.append(weighted.corrected(pool_pass, 100_000 - pool_pass, n, c_p, n, c_f,
                                         draws=50)["kappa"])
    assert sum(kappas) / len(kappas) == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize("case,kappa,low,high", [
    ((0.5, (15, 13), (15, 2)), 0.73, 0.40, 0.90),  # S1
    ((0.9, (15, 15), (15, 0)), 1.00, 0.49, 1.00),  # S4
])
def test_kappa_has_a_range(case, kappa, low, high):
    r = result(*case)
    assert r["kappa"] == pytest.approx(kappa, abs=0.01)
    assert r["kappa_interval"][0] == pytest.approx(low, abs=0.03)
    assert r["kappa_interval"][1] == pytest.approx(high, abs=0.03)


def test_kappa_after_asking_again_has_a_range():
    items = [("pass", "pass", "pass")] * 18 + [("pass", "fail", "pass")] * 2 + \
            [("fail", "fail", "fail")] * 17 + [("fail", "pass", "fail")] * 3
    out = weighted.general(items, 500, 500)
    lo, hi = out["kappa_interval"]
    assert lo < out["kappa"] < hi


def test_kappa_is_in_the_details_with_its_range_and_no_bar():
    from html import unescape

    r = result(0.5, (15, 13), (15, 2))
    html = " ".join(unescape(start_label.result_html(r)).split())
    lo, hi = r["kappa_interval"]
    assert "Kappa on your real mix (agreement beyond coincidence)" in html
    assert f"could be {lo:.2f} to {hi:.2f}" in html
    assert "or more is good" not in html and "beyond luck" not in html


# A re-check keeps the groups the marks were picked by ----------------------------------------

def test_a_recheck_weights_the_marks_by_the_groups_they_were_picked_from():
    """Pools of 2,000, 80% truly Pass. The old judge passes 97% of true Pass and 50% of true
    Fail; the new one 80% and 15%. 25 + 25 marks picked by the old judge's groups: the new
    judge's numbers come out right on average. Re-weighting by the new verdicts instead (as a
    re-check did) is far off."""
    rng = random.Random(2000)
    got, true, wrong = {"tpr": [], "tnr": []}, {"tpr": [], "tnr": []}, {"tpr": [], "tnr": []}
    for _ in range(300):
        truth = [rng.random() < 0.8 for _ in range(2000)]
        old = ["pass" if rng.random() < (0.97 if t else 0.50) else "fail" for t in truth]
        new = ["pass" if rng.random() < (0.80 if t else 0.15) else "fail" for t in truth]
        pool = {"pass": old.count("pass"), "fail": old.count("fail")}
        now = {"pass": new.count("pass"), "fail": new.count("fail")}
        picked, labels, verdicts = {}, {}, {}
        for g in ("pass", "fail"):
            for i in rng.sample([i for i, v in enumerate(old) if v == g], 25):
                picked[i] = g
                labels[i] = "pass" if truth[i] else "fail"
                verdicts[i] = new[i]
        r = start_label.picked_numbers({"pool": pool, "groups": picked}, labels, verdicts, now,
                                       draws=20)
        by_new = {g: [sum(verdicts[i] == g for i in labels),
                      sum(verdicts[i] == g and labels[i] == "pass" for i in labels)]
                  for g in ("pass", "fail")}
        old_way = weighted.corrected(now["pass"], now["fail"], *by_new["pass"], *by_new["fail"],
                                     draws=20)
        should = [i for i, t in enumerate(truth) if t]
        should_not = [i for i, t in enumerate(truth) if not t]
        for key, value in (("tpr", sum(new[i] == "pass" for i in should) / len(should)),
                           ("tnr", sum(new[i] == "fail" for i in should_not) / len(should_not))):
            got[key].append(r[key])
            true[key].append(value)
            wrong[key].append(old_way[key])
    for key in ("tpr", "tnr"):
        mean = sum(true[key]) / 300
        assert sum(got[key]) / 300 == pytest.approx(mean, abs=0.02), key
        assert abs(sum(wrong[key]) / 300 - mean) > 0.05, key


def test_the_new_judges_own_pass_share_comes_from_the_new_results():
    r = start_label.picked_numbers({"pool": {"pass": 20, "fail": 16},
                                    "groups": {i: "pass" for i in range(20)}},
                                   dict.fromkeys(range(20), "pass"),
                                   dict.fromkeys(range(20), "pass"),
                                   {"pass": 16, "fail": 20}, draws=20)
    assert r["judge_pass_rate"] == pytest.approx(16 / 36)
    assert r["groups"]["pass"]["pool"] == 20  # weighted by the pool the marks came from
