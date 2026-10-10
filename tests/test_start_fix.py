"""Fix your judge, after the review: the split, the patterns and the pass mark.

Before any change is made, about 30% of the marked answers are set aside (in each of four
cells: the judge's group times whether it agrees with the person's final mark). A change is
tested only on those. The patterns page and the pass-mark choice use only the rest.

No test opens a browser: the server runs in a thread and a test client clicks for the person.
"""

from __future__ import annotations

import csv
import json
import os
import threading

import pytest

from judgekeeper import label as label_mod
from judgekeeper import start, start_fix, start_label, start_review, weighted
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace, save_result
from judgekeeper.start_review import ReviewSession
from tests.start_projects import (
    answer,
    deepeval_project,
    promptfoo_project,
    question,
    split,
)
from tests.test_label_server import Client
from tests.test_start_review import _reviewable, _second_look


def _quiet(line=""):
    pass


# Projects ---------------------------------------------------------------------------------

def scored_records(root, scores, pass_mark=0.5, labels=None, name="Helpful", outputs=None):
    """judgekeeper.record() lines with a score and a pass mark: the verdict is score >=
    pass_mark unless `labels` gives it."""
    folder = root / ".judgekeeper" / "records"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-2026-10-05-4101.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i, s in enumerate(scores):
            label = labels[i] if labels else ("pass" if s >= pass_mark else "fail")
            f.write(json.dumps({
                "schema_version": 2, "target_id": None, "name": name, "annotator_kind": "LLM",
                "label": label, "score": s, "explanation": f"reason {i}", "run": None,
                "input": question(i), "output": answer(i) if outputs is None else outputs[i],
                "evaluator": {"model": "claude-opus-5", "rule": "Be helpful."},
                "created_at": "2026-10-05T10:00:00Z",
                "metadata": {"pass_mark": pass_mark}}) + "\n")
    return path


def _scores(n=100):
    """0.005, 0.015, ... 0.995: the judge passes the 50 at 0.5 or more."""
    return [round(0.005 + 0.01 * i, 3) for i in range(n)]


def _mark_all(ws, mark, choice="judge_wrong", second=None):
    """Label every answer of the queue with mark(answer index, saved group), make the result,
    then finish the review: the second look keeps the first label (or `second`), and every
    disagreement gets `choice`."""
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        i = int(session.raw[q["id"]]["output"].split()[1].rstrip("."))
        session.update({"id": q["id"], "label": mark(i, q["group"])})
    save_result(ws, session, say=_quiet)
    review = ReviewSession(ws)
    _second_look(review, second)
    for item in review.items:
        if item["disagreement"]:
            review.update({"id": item["id"], "choice": choice})
    return review


@pytest.fixture
def seeded(monkeypatch):
    """The split's seed, fixed."""
    monkeypatch.setattr(start_fix.secrets, "randbelow", lambda n: 1234)


def too_easy_project(root, n=100):
    """The judge passes at 0.5; the person passes only at 0.7: the 20 answers from 0.505 to
    0.695 are passes that should have failed."""
    scored_records(root, _scores(n))
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    _mark_all(ws, lambda i, g: "pass" if _scores(n)[i] >= 0.7 else "fail")
    return ws


# Final marks ------------------------------------------------------------------------------

def test_the_final_mark_is_the_second_look_and_not_sure_is_left_out(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1, p2, p3 = flipped["pass"]
    review = ReviewSession(ws)
    _second_look(review, {p1: "pass", p2: "unsure"})
    marks = {m["id"]: m for m in start_fix.final_marks(ws)}
    assert len(marks) == 35  # 36 marked, 1 not sure
    assert p2 not in marks
    assert marks[p1]["final"] == "pass" and marks[p1]["first"] == "fail"
    assert marks[p3]["final"] == "fail"


def test_i_was_wrong_is_never_a_mistake(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1 = flipped["pass"][0]
    review = ReviewSession(ws)
    _second_look(review)
    review.update({"id": p1, "choice": "slipped"})
    marks = {m["id"]: m for m in start_fix.final_marks(ws)}
    assert marks[p1]["final"] == marks[p1]["judge"] == "pass"
    assert p1 not in {m["id"] for m in start_fix.mistakes(marks.values())}


def test_rule_unclear_answers_are_not_counted_as_mistakes(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    f1 = flipped["fail"][0]
    review = ReviewSession(ws)
    _second_look(review)
    review.update({"id": f1, "choice": "rule_unclear"})
    marks = start_fix.final_marks(ws)
    assert f1 not in {m["id"] for m in start_fix.mistakes(marks)}
    assert [m["id"] for m in start_fix.unclear(marks)] == [f1]


# The split --------------------------------------------------------------------------------

def _marks(cells):
    """Final marks from {(judge, final): n}."""
    out = []
    for (judge, final), n in cells.items():
        out += [{"id": f"{judge}-{final}-{i}", "judge": judge, "final": final}
                for i in range(n)]
    return out


def test_the_split_sets_aside_30_percent_rounded_up_in_each_of_four_cells():
    marks = _marks({("pass", "pass"): 10, ("pass", "fail"): 7, ("fail", "fail"): 21,
                    ("fail", "pass"): 2})
    used, aside = start_fix.split(marks, seed=7)
    cells = {}
    for i in aside:
        judge, final, _ = i.split("-")
        cells[(judge, final)] = cells.get((judge, final), 0) + 1
    assert cells == {("pass", "pass"): 3, ("pass", "fail"): 3, ("fail", "fail"): 7,
                     ("fail", "pass"): 1}
    assert sorted(used + aside) == sorted(m["id"] for m in marks)
    assert not set(used) & set(aside)


def test_a_cell_of_one_answer_stays_in_the_used_part():
    # One mistake flagged: it stays on the page instead of being set aside.
    marks = _marks({("pass", "pass"): 10, ("pass", "fail"): 1, ("fail", "fail"): 10})
    for seed in range(20):
        used, aside = start_fix.split(marks, seed=seed)
        assert "pass-fail-0" in used and "pass-fail-0" not in aside


def _tnr(items, weights):
    return weighted._table(items, weights)["tnr"]


def test_cell_weights_keep_the_set_aside_numbers_those_of_all_labels():
    # 900 passes and 100 fails in the pool. Labels: the judge's passes 24 agreed + 1 not,
    # its fails 20 agreed + 5 not. On all labels, weighted by group (900 / 25, 100 / 25):
    # TNR = 20 * 4 / (20 * 4 + 1 * 36) = 0.69.
    pool = {"pass": 900, "fail": 100}
    marks = _marks({("pass", "pass"): 24, ("pass", "fail"): 1, ("fail", "fail"): 20,
                    ("fail", "pass"): 5})
    every = _tnr([(m["judge"], m["final"], m["judge"]) for m in marks],
                 {"pass": 900 / 25, "fail": 100 / 25})
    assert every == pytest.approx(80 / 116)
    # The four-cell split with every cell rounded up (8, 1, 6 and 2 set aside) holds
    # proportionally more disagreements: weighted by group it reads 0.43.
    by_cell = {}
    for m in marks:
        by_cell.setdefault(start_fix.cell(m), []).append(m)
    aside = (by_cell[("pass", True)][:8] + by_cell[("pass", False)][:1]
             + by_cell[("fail", True)][:6] + by_cell[("fail", False)][:2])
    old = _tnr([(m["judge"], m["final"], m["judge"]) for m in aside],
               {"pass": 900 / 9, "fail": 100 / 8})
    assert old == pytest.approx(75 / 175)
    # Weighted by cell, the set-aside part reads the same as all labels.
    weights = start_fix.cell_weights(marks, aside, pool)
    assert _tnr([(start_fix.cell(m), m["final"], m["judge"]) for m in aside],
                weights) == pytest.approx(every)


def test_with_one_answer_cells_kept_the_used_part_keeps_the_numbers_of_all_labels():
    # The same labels through the real split: the single wrong pass stays in the used part,
    # where the pass mark is chosen, and the numbers there are those of all labels.
    pool = {"pass": 900, "fail": 100}
    marks = _marks({("pass", "pass"): 24, ("pass", "fail"): 1, ("fail", "fail"): 20,
                    ("fail", "pass"): 5})
    by_id = {m["id"]: m for m in marks}
    used_ids, _ = start_fix.split(marks, seed=3)
    assert "pass-fail-0" in used_ids
    used = [by_id[i] for i in used_ids]
    weights = start_fix.cell_weights(marks, used, pool)
    table = weighted._table([(start_fix.cell(m), m["final"], m["judge"]) for m in used],
                            weights)
    every = weighted._table([(m["judge"], m["final"], m["judge"]) for m in marks],
                            {"pass": 900 / 25, "fail": 100 / 25})
    assert table["tnr"] == pytest.approx(every["tnr"])
    assert table["tpr"] == pytest.approx(every["tpr"])
    # With two wrong passes, both parts hold every cell, and the set-aside part matches too.
    marks = _marks({("pass", "pass"): 23, ("pass", "fail"): 2, ("fail", "fail"): 20,
                    ("fail", "pass"): 5})
    by_id = {m["id"]: m for m in marks}
    every = weighted._table([(m["judge"], m["final"], m["judge"]) for m in marks],
                            {"pass": 900 / 25, "fail": 100 / 25})
    aside = [by_id[i] for i in start_fix.split(marks, seed=3)[1]]
    table = weighted._table([(start_fix.cell(m), m["final"], m["judge"]) for m in aside],
                            start_fix.cell_weights(marks, aside, pool))
    assert table["tnr"] == pytest.approx(every["tnr"])
    assert table["tpr"] == pytest.approx(every["tpr"])


def test_the_split_is_seeded():
    marks = _marks({("pass", "pass"): 20, ("pass", "fail"): 8, ("fail", "fail"): 20})
    assert start_fix.split(marks, seed=7) == start_fix.split(marks, seed=7)
    assert len({tuple(start_fix.split(marks, seed=s)[1]) for s in range(10)}) > 1


def test_the_split_is_made_once_and_saved(tmp_path):
    ws = too_easy_project(tmp_path)
    fix = start_fix.Fix(ws)
    assert fix.new
    saved = json.loads((ws.dir / "fix.json").read_text(encoding="utf-8"))
    assert saved["basis"] == start_review._basis(ws)
    assert isinstance(saved["seed"], int) and saved["tests"] == []
    assert len(saved["aside_ids"]) == 30 and len(saved["used_ids"]) == 70
    again = start_fix.Fix(ws)
    assert not again.new
    assert json.loads((ws.dir / "fix.json").read_text(encoding="utf-8")) == saved


def test_a_new_result_moves_the_old_fix_to_history(tmp_path):
    ws = too_easy_project(tmp_path)
    start_fix.Fix(ws).write_patterns()
    old = json.loads((ws.dir / "fix.json").read_text(encoding="utf-8"))
    session = StartSession(ws)
    session.update({"id": session.items[0]["id"], "label": None})
    save_result(ws, session, say=_quiet)
    fix = start_fix.Fix(ws)
    assert fix.new
    moved = list(ws.history.glob("fix-*"))
    assert len(moved) == 1
    assert json.loads((moved[0] / "fix.json").read_text(encoding="utf-8")) == old
    assert (moved[0] / "fix" / "patterns.json").is_file()


# What the page and patterns.json hold ----------------------------------------------------

def test_set_aside_answers_never_reach_the_page_or_patterns_json(tmp_path):
    ws = too_easy_project(tmp_path)
    fix = start_fix.Fix(ws)
    fix.write_patterns()
    raw = {json.loads(x)["id"]: json.loads(x) for x in ws.pool.read_text(encoding="utf-8").splitlines()}
    shown = json.dumps(fix.state()) + (ws.dir / "fix" / "patterns.json").read_text(encoding="utf-8")
    for i in fix.aside_ids:
        assert i not in shown
        assert raw[i]["output"] not in shown
    assert ("judgekeeper kept 30 of your answers aside. They test whether a change really "
            "helps, so they are not shown here.") in shown


def test_the_page_lists_the_two_kinds_of_mistakes_with_the_why_text(tmp_path):
    ws, flipped = _reviewable(tmp_path, flip_pass=6, flip_fail=6)
    review = ReviewSession(ws)
    _second_look(review)
    for item in review.items:
        if item["disagreement"]:
            review.update({"id": item["id"], "choice": "judge_wrong"})
            review.update({"id": item["id"], "why": f"why {item['id'][:6]}"})
    fix = start_fix.Fix(ws)
    state = fix.state()
    lists = state["lists"]
    assert lists[0]["title"] == f"Passed, but you said Fail ({len(lists[0]['items'])})"
    assert lists[1]["title"] == f"Failed, but you said Pass ({len(lists[1]['items'])})"
    assert len(lists[0]["items"]) + len(lists[1]["items"]) == 12 - len(
        [i for i in fix.aside_ids if i in flipped["pass"] + flipped["fail"]])
    first = lists[0]["items"][0]
    assert set(first) == {"input", "output", "reason", "why"}
    assert first["why"].startswith("why ") and first["reason"].startswith("reason ")
    assert state["rule"]


# The patterns ---------------------------------------------------------------------------

def _m(judge, final, output="An answer.", score=None, choice="judge_wrong"):
    return {"judge": judge, "final": final, "output": output, "score": score,
            "choice": choice if judge != final else None}


def test_too_easy_shows_from_three_mistakes():
    two = [_m("pass", "fail"), _m("pass", "fail")] + [_m("pass", "pass")] * 5
    assert start_fix.pattern_lines(two) == []
    three = two + [_m("fail", "pass")]
    assert start_fix.pattern_lines(three) == [
        "2 of its 3 mistakes are answers it passed but you failed. Its rule may be too easy."]
    strict = [_m("fail", "pass")] * 5 + [_m("pass", "fail")] * 2
    assert start_fix.pattern_lines(strict) == [
        "5 of its 7 mistakes are answers it failed but you passed. Its rule may be too strict."]


def test_near_the_pass_mark_needs_most_mistakes_within_a_tenth():
    near = [_m("pass", "fail", score=s) for s in (0.52, 0.55, 0.58, 0.9)]
    lines = start_fix.pattern_lines(near, mark=0.5)
    assert ("3 of its 4 mistakes sit close to the pass mark. Moving the pass mark may fix them."
            in lines)
    half = [_m("pass", "fail", score=s) for s in (0.52, 0.55, 0.9, 0.95)]
    assert not any("close to the pass mark" in x for x in start_fix.pattern_lines(half, 0.5))
    assert not any("close to the pass mark" in x for x in start_fix.pattern_lines(near))


def _words(n):
    return " ".join(["word"] * n)


def test_length_needs_four_mistakes_on_one_side_and_half_again_as_long():
    agreed = [_m("pass", "pass", _words(120))] * 5
    long_fails = [_m("fail", "pass", _words(410))] * 4
    assert ("Its wrong fails are long answers (about 410 words, against 120)."
            in start_fix.pattern_lines(long_fails + agreed))
    three = [_m("fail", "pass", _words(410))] * 3
    assert not any("long answers" in x for x in start_fix.pattern_lines(three + agreed))
    short = [_m("fail", "pass", _words(170))] * 4
    assert not any("long answers" in x for x in start_fix.pattern_lines(short + agreed))
    passes = [_m("pass", "fail", _words(80))] * 4 + [_m("fail", "fail", _words(40))] * 5
    assert ("Its wrong passes are long answers (about 80 words, against 40)."
            in start_fix.pattern_lines(passes))


def test_words_that_stand_out_in_three_or_more_mistakes():
    mistakes = ([_m("pass", "fail", "Our refund policy covers the warranty.")] * 3
                + [_m("pass", "fail", "A refund is possible.")])
    agreed = [_m("pass", "pass", "Thanks for asking about shipping.")] * 6
    lines = start_fix.pattern_lines(mistakes + agreed)
    assert ("Words that show up in many of its mistakes: refund (4), policy (3), covers (3), "
            "warranty (3).") in lines
    two = [_m("pass", "fail", "warranty")] * 2 + [_m("fail", "pass", "plain")]
    assert not any(x.startswith("Words") for x in start_fix.pattern_lines(two + agreed))


def test_at_most_five_words_and_none_that_agreed_answers_share():
    text = "alpha bravo charlie delta echoes foxtrot shipping"
    mistakes = [_m("pass", "fail", text)] * 3
    agreed = [_m("pass", "pass", "shipping shipping")] * 6
    line = next(x for x in start_fix.pattern_lines(mistakes + agreed) if x.startswith("Words"))
    assert line.count("(3)") == 5 and "shipping" not in line


# The pass mark: when it applies ----------------------------------------------------------

def test_a_record_score_with_its_pass_mark_is_kept(tmp_path):
    scored_records(tmp_path, _scores(40))
    found = start.find_judge(tmp_path)
    assert found.pass_mark == {"mark": 0.5, "op": ">=", "source": "records", "follows": True}
    ws = start_label.prepare(found, say=_quiet)
    assert ws.data()["pass_mark"]["mark"] == 0.5
    _, records = start_fix.read_run(ws.pool_judge)
    assert sorted(r["raw_score"] for r in records.values()) == _scores(40)


def test_deepeval_threshold_is_the_pass_mark(tmp_path):
    path = deepeval_project(tmp_path, split(20, 16))
    found = start.find_judge(tmp_path)
    assert found.pass_mark == {"mark": 0.5, "op": ">=", "source": "deepeval", "follows": True}
    data = json.loads(path.read_text(encoding="utf-8"))
    for case in data["testCases"]:
        case["metricsData"][0]["strictMode"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert start.find_judge(tmp_path).pass_mark is None


def test_answers_with_no_real_decision_do_not_count_for_the_pass_mark(tmp_path):
    # Two failed judge calls: no score, counted as fails by DeepEval. They are left out of
    # the pool, so the pass mark is still read from the answers the judge did decide.
    path = deepeval_project(tmp_path, split(20, 16))
    data = json.loads(path.read_text(encoding="utf-8"))
    for case in data["testCases"][:2]:
        case["metricsData"][0].update(success=False, score=None, error="rate limited")
    path.write_text(json.dumps(data), encoding="utf-8")
    found = start.find_judge(tmp_path)
    assert len(found.pool.left) == 2 and len(found.pool.answers) == 34
    assert found.pass_mark == {"mark": 0.5, "op": ">=", "source": "deepeval", "follows": True}


def test_deepeval_lower_is_better_is_read_from_the_saved_verdicts(tmp_path):
    path = deepeval_project(tmp_path, split(20, 16))
    data = json.loads(path.read_text(encoding="utf-8"))
    for case in data["testCases"]:
        md = case["metricsData"][0]
        md["score"] = 0.1 if md["success"] else 0.9
    path.write_text(json.dumps(data), encoding="utf-8")
    assert start.find_judge(tmp_path).pass_mark["op"] == "<="


def test_the_pass_mark_a_mapped_file_states(tmp_path, capsys):
    from tests.start_projects import coach_project

    path = coach_project(tmp_path)
    assert main(["setup", str(path), "--yes", "--metric", "all"]) == 0
    capsys.readouterr()
    found = start.find_judge(tmp_path, metric="helpful")
    assert found.pass_mark == {"mark": 0.7, "op": ">=", "source": "mapped", "follows": True,
                               "key": "judge.pass_mark"}


def test_pass_if_gives_the_pass_mark_and_its_direction(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    found = start.find_judge(tmp_path, pass_if="score<0.5")
    assert found.pass_mark == {"mark": 0.5, "op": "<", "source": "pass_if", "follows": True,
                               "rule": "score<0.5"}


def test_no_pass_mark_without_one(tmp_path):
    promptfoo_project(tmp_path, split(20, 16))
    assert start.find_judge(tmp_path).pass_mark is None


def test_decisions_that_do_not_follow_the_scores(tmp_path):
    scores = _scores(40)
    labels = ["pass" if s >= 0.5 else "fail" for s in scores]
    labels[3] = "pass"  # 0.035, passed anyway
    scored_records(tmp_path, scores, labels=labels)
    found = start.find_judge(tmp_path)
    assert found.pass_mark["follows"] is False
    ws = start_label.prepare(found, say=_quiet)
    _mark_all(ws, lambda i, g: "pass" if scores[i] >= 0.7 else "fail")
    section = start_fix.Fix(ws).state()["pass_mark"]
    assert section == {"kind": "no_follow", "text": (
        "Your judge's decisions don't follow its scores, so moving the pass mark can't be "
        "tested.")}


# The pass mark: choosing it ---------------------------------------------------------------

def test_the_mark_choice_on_a_hand_worked_example():
    # Used answers (group, final mark, score). Pass mark 0.5.
    # 0.2 F/F, 0.4 F/F, 0.55 P/F, 0.6 P/F, 0.8 P/P, 0.9 P/P, 0.45 F/P
    # Candidates between neighbours: ... the gap (0.6, 0.8) gives TPR 2/3 (0.45 still
    # fails) and TNR 4/4; the current mark gives TPR 2/3 and TNR 2/4.
    items = [("fail", "fail", 0.2), ("fail", "fail", 0.4), ("pass", "fail", 0.55),
             ("pass", "fail", 0.6), ("pass", "pass", 0.8), ("pass", "pass", 0.9),
             ("fail", "pass", 0.45)]
    weights = {"pass": 1.0, "fail": 1.0}
    assert start_fix.choose_mark(items, 0.5, ">=", weights) == 0.7
    # Ties go to the mark nearest the current one; the current mark wins a tie.
    fits = [("fail", "fail", 0.2), ("pass", "pass", 0.8)]
    assert start_fix.choose_mark(fits, 0.5, ">=", weights) == 0.5
    lower = [("pass", "pass", 0.2), ("pass", "fail", 0.6), ("fail", "fail", 0.9)]
    assert start_fix.choose_mark(lower, 0.7, "<=", weights) == 0.4


def test_the_mark_is_the_shortest_number_inside_its_gap():
    assert start_fix.nice_mark(0.6, 0.8) == 0.7
    assert start_fix.nice_mark(0.62, 0.71) == 0.7
    assert start_fix.nice_mark(0.695, 0.705) == 0.7
    assert start_fix.nice_mark(0.7, 0.71) == 0.705


def test_the_page_suggests_a_mark_from_the_used_answers(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    section = start_fix.Fix(ws).state()["pass_mark"]
    assert section["kind"] == "suggest"
    assert section["lines"] == ["Your judge passes an answer when its score is 0.5 or more.",
                                "On the answers judgekeeper used, 0.7 fits your marks best."]
    assert section["button"] == "Test 0.7 on the 30 answers kept aside"


def test_a_mark_that_already_fits_has_no_button(tmp_path):
    scored_records(tmp_path, _scores(100))
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    scores = _scores(100)
    # The person agrees with the pass mark, except 3 answers far from it.
    _mark_all(ws, lambda i, g: ("fail" if i in (90, 91, 92) else g))
    section = start_fix.Fix(ws).state()["pass_mark"]
    assert section["kind"] == "fits"
    assert section["lines"][-1] == "Your pass mark already fits your marks best."
    assert "button" not in section
    assert scores[90] > 0.9


def test_a_mark_that_already_fits_has_no_refusal(tmp_path):
    # 20 answers: too few set aside for a test, but nothing to test either.
    scores = [round(0.025 + 0.05 * i, 3) for i in range(20)]
    scored_records(tmp_path, scores)
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    _mark_all(ws, lambda i, g: "fail" if i in (18, 19) else g)
    fix = start_fix.Fix(ws)
    assert fix.refusal() is not None
    section = fix.state()["pass_mark"]
    assert section["kind"] == "fits"
    assert "refusal" not in section and "button" not in section


# The fair test ---------------------------------------------------------------------------

def test_the_sign_test_p_values():
    assert start_fix.sign_test(6, 0) == pytest.approx(0.03125)
    assert start_fix.sign_test(0, 6) == pytest.approx(0.03125)
    assert start_fix.sign_test(5, 0) == pytest.approx(0.0625)
    assert start_fix.sign_test(7, 1) == pytest.approx(0.0703125)
    assert start_fix.sign_test(0, 0) == 1.0
    assert start_fix.sign_test(3, 3) == 1.0


def test_the_test_sentences():
    assert start_fix.test_sentence(15, 6, 0) == (
        "On the 15 answers kept aside, the change did better: it fixed 6 and broke none.")
    assert start_fix.test_sentence(15, 0, 6) == (
        "On the 15 answers kept aside, the change did worse: it fixed 0 and broke 6. Keep what "
        "you have.")
    assert start_fix.test_sentence(15, 2, 0) == (
        "Can't tell yet: on the 15 answers kept aside, the change fixed 2 and broke 0. That is "
        "too few to be sure. Mark more answers to find out.")
    assert start_fix.test_sentence(15, 5, 0).startswith("Can't tell yet")


def test_the_pass_mark_test_on_the_set_aside_answers(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    fix = start_fix.Fix(ws)
    result = fix.test_pass_mark(0.7)
    assert result["kind"] == "better"
    assert result["fixed"] == 6 and result["broke"] == 0
    assert result["lines"][0] == ("On the 30 answers kept aside, the change did better: it "
                                  "fixed 6 and broke none.")
    assert result["lines"][1] == ("This test is small. The real check is on new answers, after "
                                  "your next eval run.")
    # The old -> new numbers, point values weighted by cell (no ranges): before the change
    # they are those of all final marks, weighted by group.
    marks = list(fix.marks.values())
    n = {g: sum(m["judge"] == g for m in marks) for g in ("pass", "fail")}
    every = weighted._table([(m["judge"], m["final"], m["judge"]) for m in marks],
                            {g: fix.pool[g] / n[g] for g in n})
    assert result["numbers"] == [
        "When you said Pass, your judge also said Pass: 100% → 100%",
        f"When you said Fail, your judge also said Fail: {every['tnr']:.0%} → 100%"]
    assert "ranges" not in result
    saved = json.loads((ws.dir / "fix.json").read_text(encoding="utf-8"))
    assert saved["tests"] == [{"kind": "pass_mark", "made_at": saved["tests"][0]["made_at"],
                               "change": "pass mark 0.5 to 0.7", "fixed": 6, "broke": 0,
                               "p": 0.03125, "result": "better",
                               "sentence": result["lines"][0]}]
    kept = json.loads((ws.dir / "fix" / "pass-mark.json").read_text(encoding="utf-8"))
    assert kept["old_mark"] == 0.5 and kept["new_mark"] == 0.7 and kept["test"]["fixed"] == 6


def test_testing_the_same_mark_again_shows_the_saved_test(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    fix = start_fix.Fix(ws)
    first = fix.test_pass_mark(0.7)
    assert start_fix.Fix(ws).test_pass_mark(0.7) == first
    assert len(json.loads((ws.dir / "fix.json").read_text(encoding="utf-8"))["tests"]) == 1


def test_only_the_suggested_mark_can_be_tested(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    with pytest.raises(ValueError):
        start_fix.Fix(ws).test_pass_mark(0.3)


def test_too_few_set_aside_refuses_the_test(tmp_path):
    # 40 answers, the judge passing the 20 from 0.5125. The person fails 7 of the judge's
    # fails and 3 of its passes: ceil(30%) of 7 and of 3 is 3 + 1 = 4 Fail set aside.
    scores = [round(0.0125 + 0.025 * i, 4) for i in range(40)]
    scored_records(tmp_path, scores)
    ws = start_label.prepare(start.find_judge(tmp_path), say=_quiet)
    _mark_all(ws, lambda i, g: "fail" if i < 7 or 20 <= i < 23 else "pass")
    fix = start_fix.Fix(ws)
    fails = sum(fix.marks[i]["final"] == "fail" for i in fix.aside_ids)
    assert fails == 4
    section = fix.state()["pass_mark"]
    assert section["refusal"] == (
        "Too few answers kept aside to test a change fairly: it needs 5 you marked Pass and 5 "
        "you marked Fail (you have 4 Fail). Mark more answers first.")
    with pytest.raises(ValueError):
        fix.test_pass_mark(section["mark"])
    assert fix.state()["lists"]  # the patterns page still works


def test_the_fourth_test_on_one_split_is_refused(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    path = ws.dir / "fix.json"
    start_fix.Fix(ws)
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["tests"] = [{"kind": "rule", "made_at": "x", "change": "a rule", "fixed": 1,
                       "broke": 0, "p": 1.0, "result": "unsure"}] * 3
    path.write_text(json.dumps(saved), encoding="utf-8")
    fix = start_fix.Fix(ws)
    assert fix.state()["pass_mark"]["refusal"] == (
        "You have tested 3 changes on the same 30 answers, so they no longer give a fair "
        "test. Mark new answers to test more.")
    with pytest.raises(ValueError):
        fix.test_pass_mark(0.7)


def test_the_hand_over_names_where_the_pass_mark_lives(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "check.py").write_text(
        "import judgekeeper\n\njudgekeeper.record(input=q, output=a, score=s,\n"
        "                   pass_mark=0.5)\n", encoding="utf-8")
    lines = start_fix.Fix(ws).test_pass_mark(0.7)["hand_over"]
    assert lines == [
        "Set pass_mark=0.7 in your judgekeeper.record() line.",
        "Probably in evals/check.py, line 4: pass_mark=0.5)",
        "Mark more answers from your next eval run: judgekeeper start --label-more",
    ]


def test_the_hand_over_per_source():
    assert start_fix.where_lines({"source": "deepeval", "op": ">="}, 0.65)[0] == (
        "Set threshold=0.65 in your metric, e.g. GEval(..., threshold=0.65).")
    assert start_fix.where_lines({"source": "mapped", "op": ">="}, 0.65)[0] == (
        "Set pass_mark = 0.65 in judgekeeper.toml [start].")
    # Double quotes, which work in Windows cmd as well.
    assert start_fix.where_lines({"source": "pass_if", "op": ">=", "rule": "score>=0.5"},
                                 0.65)[0] == 'Use --pass-if "score>=0.65".'
    # A pass mark kept with each verdict, read by another reader: record() or the toml.
    for source in ("table", "jsonl", "promptfoo"):
        assert start_fix.where_lines({"source": source, "op": ">="}, 0.65) == [
            ("Set pass_mark=0.65 in your judgekeeper.record() line, or pass_mark = 0.65 in "
             "judgekeeper.toml [start].")]


def test_the_hand_over_scrubs_the_line_it_found(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    key = "sk-ant-api03-" + "x" * 40
    (tmp_path / "check.py").write_text(f'judgekeeper.record(pass_mark=0.5, key="{key}")\n',
                                       encoding="utf-8")
    test = start_fix.Fix(ws).test_pass_mark(0.7)
    found = test["hand_over"][1]
    assert found.startswith("Probably in check.py, line 1: judgekeeper.record(pass_mark=0.5")
    assert key not in found
    assert key not in (ws.dir / "fix" / "pass-mark.json").read_text(encoding="utf-8")


def test_the_search_goes_on_past_a_file_it_cannot_look_at(tmp_path, monkeypatch):
    (tmp_path / "b.py").write_text("GEval(threshold=0.5)\n", encoding="utf-8")
    real = os.scandir

    class Gone:
        name, path = "a.py", str(tmp_path / "a.py")

        def is_symlink(self):
            return False

        def is_dir(self):
            return False

        def is_file(self):
            return True

        def stat(self):
            raise FileNotFoundError(self.path)

    monkeypatch.setattr(start_fix.os, "scandir",
                        lambda folder: [Gone(), *real(folder)])
    assert start_fix.locate(tmp_path, "threshold", 0.5) == ("b.py", 1, "GEval(threshold=0.5)")


def test_the_search_skips_virtual_environments_and_judgekeeper(tmp_path):
    for folder in (".venv", "venv", "node_modules", ".git", ".judgekeeper"):
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / "x.py").write_text("GEval(threshold=0.5)\n", encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.5) is None
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "t.py").write_text("x = 1\nm = GEval(threshold=.50)\n",
                                               encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.5) == ("a/b/t.py", 2,
                                                            "m = GEval(threshold=.50)")
    deep = tmp_path / "1" / "2" / "3" / "4" / "5"
    deep.mkdir(parents=True)
    (deep / "t.py").write_text("threshold=0.9\n", encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.9) is None


# The served page -------------------------------------------------------------------------

def _fix_server(ws):
    fix = start_fix.Fix(ws)
    server = label_mod.make_server(fix, port=0, page=start_fix.page_template(ws),
                                   result=start_review.result_maker(ws, say=_quiet))
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread, Client(server)


def test_the_pass_mark_button_tests_it_in_place(tmp_path, seeded):
    ws = too_easy_project(tmp_path)
    server, thread, client = _fix_server(ws)
    try:
        assert client.state()["pass_mark"]["kind"] == "suggest"
        resp, payload = client.request("POST", "/fix/pass-mark", {"mark": 0.7})
        assert resp.status == 200
        body = json.loads(payload)
        assert body["pass_mark"]["test"]["kind"] == "better"
        assert client.state()["pass_mark"]["test"]["fixed"] == 6
        resp, _ = client.request("POST", "/fix/pass-mark", {"mark": 0.7}, token=False)
        assert resp.status == 403
        resp, _ = client.request("POST", "/fix/pass-mark", {"mark": 0.3})
        assert resp.status == 400
    finally:
        server.stop()
        thread.join(5)


def test_the_labeling_server_switches_to_the_fix_page(tmp_path):
    ws = too_easy_project(tmp_path)
    server = label_mod.make_server(
        StartSession(ws), port=0, page=start_label.page_template(ws.data()),
        switches={"/fix": start_fix.switch(ws, _quiet)})
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    client = Client(server)
    try:
        resp, _ = client.request("GET", "/fix")
        assert resp.status == 303
        assert "lists" in client.state()
    finally:
        server.stop()
        thread.join(5)


def test_the_fix_page_holds_its_texts(tmp_path):
    ws = too_easy_project(tmp_path)
    page = start_fix.page_template(ws)
    for needed in ("What your judge gets wrong", "Move the pass mark", "/fix/pass-mark",
                   "Your own files are\n  never changed."):
        assert needed in page, needed


# The review: "I was wrong" and the Why? box -----------------------------------------------

def test_the_review_says_i_was_wrong(tmp_path):
    ws, _ = _reviewable(tmp_path)
    page = start_review.page_template(ws)
    assert "I was wrong" in page and "I slipped" not in page
    assert "Why? (optional, helps fix your judge)" in page
    assert 'maxlength="300"' in page


def test_the_why_box_is_saved_scrubbed_and_in_the_csvs(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1, p2, _ = flipped["pass"]
    f1 = flipped["fail"][0]
    review = ReviewSession(ws)
    _second_look(review)
    review.update({"id": p1, "choice": "judge_wrong"})
    key = "sk-ant-api03-" + "x" * 40
    review.update({"id": p1, "why": f"too vague, key {key}"})
    review.update({"id": f1, "choice": "rule_unclear"})
    review.update({"id": f1, "why": "the rule says nothing about tone"})
    saved = {i["id"]: i for i in json.loads(ws.review.read_text(encoding="utf-8"))["items"]}
    assert saved[p1]["why"].startswith("too vague, key ") and key not in saved[p1]["why"]
    with ws.judge_mistakes.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0])[-1] == "why"
    assert rows[0]["why"].startswith("too vague") and key not in rows[0]["why"]
    with ws.rule_unclear.open(newline="", encoding="utf-8") as f:
        assert next(csv.DictReader(f))["why"] == "the rule says nothing about tone"
    with pytest.raises(ValueError):
        review.update({"id": p2, "why": "no choice yet"})
    with pytest.raises(ValueError):
        review.update({"id": p1, "why": "x" * 301})


def test_changing_the_choice_keeps_the_why_and_undo_clears_it(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1 = flipped["pass"][0]
    review = ReviewSession(ws)
    _second_look(review)
    review.update({"id": p1, "choice": "judge_wrong"})
    review.update({"id": p1, "why": "too vague"})
    review.update({"id": p1, "choice": "rule_unclear"})
    assert review.by_id[p1]["why"] == "too vague"
    review.update({"id": p1, "choice": None})
    assert review.by_id[p1]["why"] is None


def _last_choice_server(tmp_path, monkeypatch):
    """A review server with every disagreement but the last one chosen, and a short wait
    before the server stops on its own."""
    monkeypatch.setattr(label_mod, "RESULT_WAIT", 0.3)
    ws, _ = _reviewable(tmp_path)
    review = ReviewSession(ws)
    _second_look(review)
    dis = [i["id"] for i in review.items if i["disagreement"]]
    for i in dis[:-1]:
        review.update({"id": i, "choice": "slipped"})
    server = label_mod.LabelServer(review, port=0, page=start_review.page_template(ws),
                                   result=start_review.result_maker(ws, say=_quiet))
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    return server, thread, Client(server), dis[-1]


def test_a_slow_why_on_the_last_disagreement_is_not_lost(tmp_path, monkeypatch):
    server, thread, client, last = _last_choice_server(tmp_path, monkeypatch)
    try:
        status, body = client.label(id=last, choice="judge_wrong")
        assert status == 200 and body["summary"]["done"]
        thread.join(timeout=1)  # the person is still typing why
        assert thread.is_alive()
        assert client.label(id=last, why="it ignored the refund rule")[0] == 200
        thread.join(timeout=1)
        assert thread.is_alive()
        saved = json.loads(server.session.workspace.review.read_text(encoding="utf-8"))
        assert {i["id"]: i for i in saved["items"]}[last]["why"] == "it ignored the refund rule"
        resp, _ = client.request("GET", "/result")  # Next: the result page stops the server
        assert resp.status == 200
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        server.stop()
        thread.join(5)


def test_i_was_wrong_on_the_last_disagreement_still_stops_on_its_own(tmp_path, monkeypatch):
    server, thread, client, last = _last_choice_server(tmp_path, monkeypatch)
    try:
        assert client.label(id=last, choice="slipped")[0] == 200
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        server.stop()
        thread.join(5)


def test_the_why_text_is_in_step_b_page_data(tmp_path):
    ws, flipped = _reviewable(tmp_path)
    p1 = flipped["pass"][0]
    review = ReviewSession(ws)
    _second_look(review)
    review.update({"id": p1, "choice": "judge_wrong"})
    review.update({"id": p1, "why": "too vague"})
    item = next(i for i in review.state()["items"] if i["id"] == p1)
    assert item["why"] == "too vague"


# The command ------------------------------------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    calls = []

    def serve(ws, port, open_browser, say, command="judgekeeper start"):
        calls.append(("fix", ws.dir))
        return 0

    monkeypatch.setattr(start_fix, "serve_fix", serve)
    return calls


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def test_fix_before_a_result_says_to_label_first(tmp_path, capsys, served):
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path, "--fix")
    assert code == 2 and served == []
    assert "There is no result yet to fix your judge with: it needs your marks." in out


def test_fix_before_the_review_is_done_says_to_review_first(tmp_path, capsys, served):
    _reviewable(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--fix")
    assert code == 2 and served == []
    assert (f"Look again at where you disagree first: judgekeeper start {tmp_path} --review"
            in out.replace("'", ""))


def test_fix_with_nothing_to_fix_says_so(tmp_path, capsys, served):
    ws, _ = _reviewable(tmp_path)
    review = ReviewSession(ws)
    _second_look(review)
    for item in review.items:
        if item["disagreement"]:
            review.update({"id": item["id"], "choice": "slipped"})
    code, out, _ = run(capsys, tmp_path, "--fix")
    assert code == 0 and served == []
    assert "Your judge agrees with every final mark you gave: nothing to fix." in out


def test_fix_sets_answers_aside_once_and_opens_the_page(tmp_path, capsys, served):
    ws = too_easy_project(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--fix")
    assert code == 0 and served == [("fix", ws.dir)]
    assert ("judgekeeper kept 30 of your 100 marked answers aside. They test whether a change "
            "really helps, so they are not shown, and they never go into a prompt.") in out
    code, out, _ = run(capsys, tmp_path, "--fix")
    assert "marked answers aside" not in out


def test_fix_without_a_browser_prints_the_patterns(tmp_path, capsys, served, seeded):
    too_easy_project(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--fix", "--no-browser")
    assert code == 0 and served == []
    assert "Passed, but you said Fail: 14" in out
    assert "Failed, but you said Pass: 0" in out
    assert ("14 of its 14 mistakes are answers it passed but you failed. Its rule may be too "
            "easy.") in out
    assert "On the answers judgekeeper used, 0.7 fits your marks best." in out
    assert "--no-browser --fix --test-pass-mark" in out
    assert "Saved in .judgekeeper/fix/" in out


def test_test_pass_mark_runs_the_free_test_in_the_terminal(tmp_path, capsys, served, seeded):
    too_easy_project(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--fix", "--no-browser", "--test-pass-mark")
    assert code == 0 and served == []
    assert ("On the 30 answers kept aside, the change did better: it fixed 6 and broke none."
            in out)
    assert "Set pass_mark=0.7 in your judgekeeper.record() line." in out


def test_test_pass_mark_needs_fix(tmp_path, capsys):
    too_easy_project(tmp_path)
    code, _, err = run(capsys, tmp_path, "--test-pass-mark")
    assert code == 2 and "--test-pass-mark works only with --fix" in err


def test_the_menu_offers_fix_your_judge_once_the_review_is_done(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(start, "_interactive", lambda: False)
    _reviewable(tmp_path)
    _, out, _ = run(capsys, tmp_path)
    assert "--fix" not in out
    too_easy_project(tmp_path / "b")
    _, out, _ = run(capsys, tmp_path / "b")
    assert f"judgekeeper start {tmp_path / 'b'} --fix" in out.replace("'", "")
    assert "Fix your judge (free)" in out


def test_the_result_page_offers_fix_your_judge(tmp_path):
    ws = too_easy_project(tmp_path)
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    steps = start_label.page_content(r)["next"]
    step = next(s for s in steps if s["title"] == "Fix your judge")
    assert step["command"] == "judgekeeper start --fix" and step["link"] == "/fix"
    ws2, _ = _reviewable(tmp_path / "b")
    r2 = json.loads(ws2.result_json.read_text(encoding="utf-8"))
    assert all(s["title"] != "Fix your judge" for s in start_label.page_content(r2)["next"])


def test_nothing_outside_judgekeeper_is_written(tmp_path, capsys, served, seeded):
    too_easy_project(tmp_path)

    def snapshot():
        return {p.relative_to(tmp_path): p.stat().st_mtime_ns for p in tmp_path.rglob("*")
                if ".judgekeeper" not in p.relative_to(tmp_path).parts}

    before = snapshot()
    run(capsys, tmp_path, "--fix", "--no-browser", "--test-pass-mark")
    ws = Workspace(tmp_path)
    server, thread, client = _fix_server(ws)
    try:
        client.state()
    finally:
        server.stop()
        thread.join(5)
    assert snapshot() == before
    assert sorted(p.name for p in (ws.dir / "fix").iterdir()) == ["pass-mark.json",
                                                                  "patterns.json"]
    assert os.path.isfile(ws.dir / "fix.json")


def test_after_a_new_pass_mark_label_more_marks_answers_from_the_next_run(tmp_path, capsys,
                                                                         monkeypatch):
    # The hand-over's last line: after the pass mark changes and the eval runs again (here:
    # the same 100 answers at the new pass mark, and 20 new ones), `start --label-more`
    # re-checks the marks against the new verdicts, then opens the labeling page on a pool
    # that holds the new answers.
    ws = too_easy_project(tmp_path)
    scored_records(tmp_path, _scores(120), pass_mark=0.7)
    opened = []

    def serve(ws, port, open_browser, say, command="judgekeeper start"):
        opened.append(ws.pool.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(start_label, "serve_workspace", serve)
    code, out, _ = run(capsys, tmp_path, "--label-more")
    assert code == 0
    assert "100 of your 100 marked answers are in your latest results" in out
    assert "before and" in out and "now." in out
    assert len(opened) == 1 and question(110) in opened[0]
    assert ws.data()["pass_mark"]["mark"] == 0.7
