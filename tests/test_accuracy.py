"""Every number on screen says only what the marks show.

The words for each number follow the width of its range; the verdict follows the ranges,
never the point numbers or kappa; kappa has a range; a re-check keeps the groups the marks
were picked by; `check` decides from a range on the paired change.

The cases: the LLM-as-a-judge passes a share of a pool of 1,000 answers; marks in its pass group and
its fail group, and how many of each the person marked Pass.
"""

from __future__ import annotations

import random
import re

import pytest

from judgekeeper import report_page, start_label, targets, weighted


def result(judge_passes: float, pass_group: tuple[int, int], fail_group: tuple[int, int],
           pool: int = 1000) -> dict:
    """The result for marks in each of the LLM-as-a-judge's groups: (marked, of them marked Pass)."""
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

def test_a_judge_that_passes_most_answers_is_not_green_at_15_each():
    """Judge passes 90%; the pass group 15 of 15 marked Pass, the fail group 0 of 15."""
    r = result(0.9, (15, 15), (15, 0))
    assert r["verdict_level"] == "too_early"
    assert targets.width_word(r["tpr_interval"]) == "sharp"
    assert targets.width_word(r["tnr_interval"]) == "too_wide"


def test_one_mark_does_not_flip_it_to_red():
    r = result(0.9, (16, 15), (15, 0))
    assert r["verdict_level"] == "too_early"
    assert targets.width_word(r["tnr_interval"]) == "too_wide"


@pytest.mark.parametrize("case", [(0.5, (15, 13), (15, 2)), (0.5, (15, 14), (16, 1))],
                         ids=["87-each-side", "94-each-side"])
def test_good_numbers_on_few_marks_can_not_tell_yet(case):
    assert result(*case)["verdict_level"] == "check"


@pytest.mark.parametrize("case", [(0.9, (20, 18), (20, 4)), (0.9, (25, 25), (25, 0))],
                         ids=["some-disagree", "25-each"])
def test_the_fail_side_is_too_early_when_most_answers_pass(case):
    r = result(*case)
    assert targets.width_word(r["tnr_interval"]) == "too_wide"
    assert r["verdict_level"] == "too_early"


def test_green_is_reachable():
    assert result(0.5, (50, 50), (50, 0))["verdict_level"] == "gate"


def test_red_when_a_side_is_clearly_below_the_bar():
    r = result(0.5, (40, 38), (40, 24))  # many answers it failed should pass
    assert r["tpr_interval"][1] < targets.RATE_GATE
    assert r["verdict"] == "Your LLM-as-a-judge needs work."
    assert r["verdict_level"] == "not_gate"


def test_kappa_is_not_in_the_verdict():
    """Both rates clearly above 80% on a mix where nearly every answer passes: kappa is low,
    the LLM-as-a-judge is still good enough."""
    r = result(0.876, (4000, 3990), (400, 313), pool=100_000)
    assert r["kappa"] < 0.6
    assert r["tpr_interval"][0] >= 0.8 and r["tnr_interval"][0] >= 0.8
    assert r["verdict_level"] == "gate"


def _simulate_first_result(rng: random.Random, a: float, b: float, n_pass: int,
                           n_fail: int) -> str:
    """Mark in blocks of 5 from each group until 15 Pass and 15 Fail: the verdict then. `a`
    and `b`: the chance the person marks Pass an answer of the LLM-as-a-judge's pass and fail group."""
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
    says to the n-th answer of the LLM-as-a-judge's group; the first `limit` answers of the page
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
    assert main(["--no-browser"]) in (0, 3)  # 3: every answer marked, more are needed
    return capsys.readouterr().out


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_result_has_each_side_on_one_line_with_its_range(project, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(project, split(30, 30))
    out = _measured(project, capsys, lambda g, n: g if n > 2 else ("fail" if g == "pass"
                                                                    else "pass"))
    lines = out.splitlines()
    assert "Step 3 of 5: Measure" in lines
    at = lines.index("How often your LLM-as-a-judge agrees with you (estimates):")
    for line, word in zip(lines[at + 1:at + 3], ("Pass", "Fail"), strict=True):
        assert line.startswith(f"  When you say {word}, it also says {word}: about ")
        assert " (between " in line and line.endswith("%)")
    counts = [x for x in lines if x.startswith("  You ")]
    assert [x.split(" answers.")[0] for x in counts] == ["  You passed 30", "  You failed 30"]
    assert all(len(x) <= 80 for x in lines)
    for gone in ("Kappa", "kappa", "Your marks:", "sitting", "can see a drop", "likely",
                 "Probably", "These are estimates", "could be"):
        assert gone not in out, gone


def test_a_side_too_wide_is_too_early_to_tell(project, capsys):
    from tests.start_projects import promptfoo_project, split

    promptfoo_project(project, split(180, 20))  # the judge passes 90%: few answers fail
    out = _measured(project, capsys, lambda g, n: g, limit=30)  # 15 + 15, all agreed
    assert "Result: too early to tell. Mark more answers to get a result." in out.splitlines()
    assert "How often" not in out and "When you say" not in out  # no estimates block yet
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
    """Half the marks from each of the LLM-as-a-judge's groups, re-weighted: the mean kappa is the
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
    ((0.5, (15, 13), (15, 2)), 0.73, 0.40, 0.90),  # half pass, 87% each side
    ((0.9, (15, 15), (15, 0)), 1.00, 0.49, 1.00),  # 90% pass, every mark agrees
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


def test_kappa_is_in_more_details_with_its_range_and_no_bar():
    from html import unescape

    r = result(0.5, (15, 13), (15, 2))
    html = " ".join(unescape(re.sub(r"<[^>]+>", " ", start_label.result_html(r))).split())
    lo, hi = r["kappa_interval"]
    kappa = f"{r['kappa']:.2f} {lo:.2f} and {hi:.2f}".replace("-", "\u2212")
    assert f"Kappa ⓘ {report_page.KAPPA_MEANS} {kappa}" in html
    assert "or more is good" not in html and "beyond luck" not in html


# A re-check keeps the groups the marks were picked by ----------------------------------------

def test_a_recheck_weights_the_marks_by_the_groups_they_were_picked_from():
    """Pools of 2,000, 80% truly Pass. The old LLM-as-a-judge passes 97% of true Pass and 50% of true
    Fail; the new one 80% and 15%. 25 + 25 marks picked by the old LLM-as-a-judge's groups: the new
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


# check: a range on the paired change ---------------------------------------------------------

@pytest.mark.parametrize("right,wrong,n,low,high,verdict", [
    (11, 19, 30, -52, 3, "not_sure"),
    (0, 12, 30, -55, -27, "worse"),
    (0, 0, 30, -8, 8, "no_drop"),
    (1, 1, 30, -11, 11, "no_drop"),
    (0, 2, 30, -18, 2, "no_drop"),
    (3, 6, 30, -27, 7, "not_sure"),
    (0, 0, 15, -15, 15, "no_drop"),
    (0, 0, 60, -4, 4, "no_drop"),
    (2, 4, 60, -11, 4, "no_drop"),
])
def test_the_paired_range(right, wrong, n, low, high, verdict):
    """now_right (old wrong, new right) and now_wrong (old right, new wrong) of n marks."""
    lo, hi = targets.paired_range(right, wrong, n)
    assert lo * 100 == pytest.approx(low, abs=1)
    assert hi * 100 == pytest.approx(high, abs=1)
    assert targets.paired_verdict(right, wrong, n)["verdict"] == verdict


@pytest.mark.parametrize("right,wrong,n,worse", [
    (11, 19, 30, True),   # not sure, and down 27 points: more than 20
    (0, 12, 30, True),    # worse
    (3, 6, 30, False),    # not sure, down 10 points
    (0, 2, 30, False),    # no drop bigger than 20
])
def test_which_paired_verdicts_exit_1(right, wrong, n, worse):
    assert targets.paired_verdict(right, wrong, n)["exit_worse"] is worse


@pytest.mark.parametrize("right,wrong,n,words", [
    (11, 19, 30, [("Not sure: 19 went from right to wrong, and 11 from wrong to right. It "
                  "could be up to 52 points worse.")]),
    (0, 12, 30, ["Worse: 12 answers went from right to wrong, and none from wrong to right.",
                 "That is about 40 points lower (between 27 and 55)."]),
    (0, 2, 30, [("No drop bigger than 20 points: 2 went from right to wrong, none from wrong "
                 "to right."),
                "These marks can't rule out a drop of up to 18 points."]),
    (1, 1, 30, [("No drop bigger than 20 points: 1 went from right to wrong, 1 from wrong "
                 "to right."),
                "These marks can't rule out a drop of up to 11 points."]),
])
def test_the_paired_words(right, wrong, n, words):
    from judgekeeper import check

    assert check.paired_lines(targets.paired_verdict(right, wrong, n)) == words


def test_one_answer_worse_is_said_in_the_singular():
    from judgekeeper import check

    g = {"verdict": "worse", "now_wrong": 1, "now_right": 2, "change": -0.1, "low": -0.25,
         "high": -0.02}
    assert check.paired_lines(g)[0] == ("Worse: 1 answer went from right to wrong, and 2 from "
                                        "wrong to right.")


def test_check_rates_are_the_reports():
    """The LLM-as-a-judge passes 90%; of 20 marks in its pass group 18 Pass, of 20 in its fail group 4
    Pass. The old LLM-as-a-judge's TNR in check is the report's (47%), not the raw 89%."""
    from judgekeeper import check

    marked, old, groups = {}, {}, {}
    for g, (n, c) in (("pass", (20, 18)), ("fail", (20, 4))):
        for k in range(n):
            i = f"{g}-{k}"
            groups[i] = old[i] = g
            marked[i] = "pass" if k < c else "fail"
    out = check.groups(marked, old, dict(old), groups, {"pass": 900, "fail": 100})
    report = result(0.9, (20, 18), (20, 4))
    assert out["failed"]["old_rate"] == pytest.approx(report["tnr"], abs=1e-9)
    assert round(out["failed"]["old_rate"], 2) == 0.47
    assert out["passed"]["old_rate"] == pytest.approx(report["tpr"], abs=1e-9)


def test_the_smallest_drop_follows_the_judges_own_rates():
    assert targets.smallest_drop(30, 30, 0.32, 0.32) != targets.smallest_drop(30, 30, 0.9, 0.9)
    assert targets.smallest_drop(14, 30, 0.9, 0.9) is None  # no first result yet


# Small items ---------------------------------------------------------------------------------

def test_repeats_with_different_grades_are_split_not_tied(tmp_path):
    """An answer graded twice with the other grade is two answers, said as such: no grade is
    picked for it by a coin."""
    from judgekeeper import start
    from tests.start_projects import promptfoo_data, split

    data = promptfoo_data(split(20, 16))
    rows = data["results"]["results"]
    twice = [dict(r) for r in rows[:2]]  # the same answers again, with the other grade
    for r in twice:
        r["gradingResult"] = {**r["gradingResult"], "componentResults": [
            {**c, "pass": not c["pass"]} for c in r["gradingResult"]["componentResults"]]}
    data["results"]["results"] = rows + twice
    (tmp_path / "results.json").write_text(__import__("json").dumps(data), encoding="utf-8")
    found = start.find_judge(tmp_path)
    assert len(found.pool.split) == 2 and len(found.pool.answers) == 38
    assert all(n == (2, 1, 1) for n in found.pool.split.values())


WORDS_NEVER_SHOWN = ("Probably", "probably", "No drop seen", "trusted", "proven", "guaranteed",
                     "significant", "p-value", "confidence", "likely")


def test_no_shown_string_overclaims():
    """No string in the code that reaches the screen, the page or report.html."""
    import re
    from pathlib import Path

    src = Path(start_label.__file__).parent
    shown = ("start_label.py", "front.py", "check.py", "targets.py", "mark_page.py",
             "report_page.py")
    for name in shown:
        text = (src / name).read_text(encoding="utf-8")
        strings = re.findall(r'"(?:[^"\\\n]|\\.)*"', text)
        for s in strings:
            for word in WORDS_NEVER_SHOWN:
                assert word not in s, (name, word, s)


def test_the_readme_names_kappas_range():
    from pathlib import Path

    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    means = readme[readme.index("## What the numbers mean"):readme.index("## Checked on")]
    assert "**Kappa:**" in means and "Each number comes with a range" in means


def test_check_shows_counts_only(tmp_path, monkeypatch, capsys):
    """No line of check's output or the report names a flipped answer's id."""
    import json

    from judgekeeper.cli import main
    from tests.test_check import HAIKU, LENIENT, _marked, _results

    monkeypatch.chdir(tmp_path)
    ws = _marked(tmp_path)
    start_label.store_result(ws, start_label.StartSession(ws))  # report.html
    _results(tmp_path, LENIENT, model=HAIKU)
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    line = [json.loads(x) for x in ws.history_jsonl.read_text(encoding="utf-8").splitlines()
            if '"check"' in x][-1]
    report = ws.report_html.read_text(encoding="utf-8")
    assert len(line["flipped"]) == 9  # kept in history.jsonl only
    for answer_id in line["flipped"]:
        assert answer_id not in out and answer_id not in report
