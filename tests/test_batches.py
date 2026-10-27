"""New eval answers join the marking as batches.

- With one batch, every number is the one judgekeeper gave before batches, to the last digit
  (fixtures/batches/one-batch.json, saved from judgekeeper before batches).
- A second batch is added when the newest results hold new graded answers and the LLM-as-a-judge
  is the same; never when the LLM-as-a-judge changed.
- The marking page offers the newest batch first, half passed and half failed.
- The numbers are stratified by (batch, the LLM-as-a-judge's grade): a hand-worked example.
- A batch with too few marks is left out of the result and named, in the terminal, on
  report.html and in history.jsonl.
- The marks kept aside for `fix` are drawn within each stratum.
- With every answer marked, the Next: line points to `judgekeeper mark`.
No test calls an AI API.
"""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper import batches, fix, start, start_label, weighted
from judgekeeper.start_label import StartSession, Workspace
from tests.conftest import FIXTURES
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import flat, next_lines, run

BEFORE = json.loads((FIXTURES / "batches" / "one-batch.json").read_text(encoding="utf-8"))
HAIKU = "anthropic:claude-haiku-4-5"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _index(value) -> int:
    text = value.get("question") if isinstance(value, dict) else value
    return int(re.search(r"Question (\d+)\?", str(text))[1])


def _mark(ws: Workspace, person=None, only=None) -> None:
    """The person marks answers on the page: as the LLM-as-a-judge did, or `person[i]` for answer i;
    `only`: just those answers."""
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        i = _index(session.raw[item["id"]]["input"])
        if only is not None and i not in only:
            continue
        session.update({"id": item["id"], "label": (person or {}).get(i, groups[item["id"]]),
                        "seconds": 6})


def _jsonable(x):
    return json.loads(json.dumps(x, sort_keys=True, default=str))


# With one batch, today's numbers --------------------------------------------------------------

@pytest.mark.parametrize("key", [k for k in BEFORE["pure"] if k.startswith("corrected")])
def test_one_batch_gives_the_same_corrected_numbers(key):
    args = tuple(int(x) for x in re.findall(r"-?\d+", key))
    n_pass, n_fail, n_p, c_p, n_f, c_f = args
    one = weighted.stratified([(1, "pass", n_pass, n_p, c_p), (1, "fail", n_fail, n_f, c_f)])
    assert _jsonable(one) == BEFORE["pure"][key]
    assert _jsonable(weighted.corrected(*args)) == BEFORE["pure"][key]


ITEMS = ([("pass", "pass", "pass")] * 12 + [("pass", "fail", "pass")] * 3
         + [("pass", "pass", "fail")] * 2 + [("fail", "fail", "fail")] * 14
         + [("fail", "pass", "fail")] * 4 + [("fail", "fail", "pass")] * 1)


@pytest.mark.parametrize(("key", "items", "wobble"), [
    ("general", ITEMS, None), ("general_wobble", ITEMS, 0.1),
    ("general_steady", [x for x in ITEMS if x[0] == x[2]], None)])
def test_one_batch_gives_the_same_numbers_after_asking_again(key, items, wobble):
    by_stratum = [((1, g), label, v) for g, label, v in items]
    one = weighted.general_strata(by_stratum, {(1, "pass"): 70, (1, "fail"): 30}, wobble=wobble)
    want = BEFORE["pure"][key]
    for k in ("tpr", "tnr", "kappa", "tpr_interval", "tnr_interval", "kappa_interval",
              "interval_methods"):
        assert _jsonable(one[k]) == want[k], k
    assert _jsonable(weighted.general(items, 70, 30, wobble=wobble)) == want


def test_one_batch_gives_the_same_numbers_on_a_recheck():
    picked = {"pool": {"pass": 30, "fail": 20},
              "groups": {f"a{i}": ("pass" if i < 30 else "fail") for i in range(50)}}
    labels = {f"a{i}": ("pass" if (i < 26 or 30 <= i < 34) else "fail") for i in range(0, 50, 2)}
    verdicts = {f"a{i}": ("pass" if i < 33 else "fail") for i in range(50)}
    out = start_label.picked_numbers(picked, labels, verdicts, {"pass": 33, "fail": 17})
    assert _jsonable(out) == BEFORE["pure"]["picked"]


def test_one_batch_gives_the_same_result(here):
    promptfoo_project(here, split(30, 20))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    session = StartSession(ws)
    for item in session.items:
        i = _index(session.raw[item["id"]]["input"])
        if i % 5 == 4:
            continue  # some stay unmarked
        label = "fail" if i < 6 else "pass" if i < 34 else "fail"
        session.update({"id": item["id"], "label": label, "seconds": 3})
    r = start_label.compute(ws, StartSession(ws))
    want = BEFORE["result"]
    assert {k: _jsonable(r[k]) for k in want} == want
    assert "batches" not in r  # one batch: nothing to say about batches


# The weights: a hand-worked example with 2 batches and 4 strata -------------------------------
#
# batch 1: the judge passed 40 (10 marked, 8 of them Pass), failed 20 (10 marked, 3 Pass)
# batch 2: the judge passed 10 (5 marked, all Pass), failed 30 (6 marked, 1 Pass)
# Each mark weighs N/n: judge passed and person Pass 40*8/10 + 10*5/5 = 42, judge failed and
# person Pass 20*3/10 + 30*1/6 = 11, judge passed and person Fail 40*2/10 = 8, judge failed and
# person Fail 20*7/10 + 30*5/6 = 39. TPR 42/53, TNR 39/47, real pass rate 53/100; kappa: agree
# 0.81, by coincidence 0.5*0.53 + 0.5*0.47 = 0.5, so (0.81 - 0.5) / 0.5 = 0.62.

STRATA = [(1, "pass", 40, 10, 8), (1, "fail", 20, 10, 3), (2, "pass", 10, 5, 5),
          (2, "fail", 30, 6, 1)]


def test_the_weights_match_a_hand_worked_example():
    r = weighted.stratified(STRATA)
    assert r["tpr"] == pytest.approx(42 / 53)
    assert r["tnr"] == pytest.approx(39 / 47)
    assert r["real_pass_rate"] == pytest.approx(0.53)
    assert r["kappa"] == pytest.approx(0.62)
    assert r["judge_pass_rate"] == pytest.approx(0.5)
    assert r["groups"] == {"pass": {"pool": 50, "labeled": 15, "correct": 13},
                           "fail": {"pool": 50, "labeled": 16, "correct": 4}}
    for key in ("tpr", "tnr", "kappa", "real_pass_rate"):
        lo, hi = r[f"{key}_interval"]
        assert lo < r[key] < hi


def test_the_weights_after_asking_again_match_the_same_example():
    items = []
    for b, g, _, n, c in STRATA:  # asked again, the judge gives the same grades
        items += [((b, g), "pass", g)] * c + [((b, g), "fail", g)] * (n - c)
    r = weighted.general_strata(items, {(b, g): pool for b, g, pool, _, _ in STRATA})
    assert r["tpr"] == pytest.approx(42 / 53)
    assert r["tnr"] == pytest.approx(39 / 47)
    assert r["kappa"] == pytest.approx(0.62)
    same = weighted.stratified(STRATA)
    assert r["tpr_interval"] == pytest.approx(same["tpr_interval"], abs=0.02)


def test_the_draws_are_per_stratum():
    """Two batches with the same marks and pools give the numbers of one batch; their ranges
    are drawn per stratum, so they differ."""
    one = weighted.stratified([(1, "pass", 40, 10, 8), (1, "fail", 40, 10, 3)])
    two = weighted.stratified([(1, "pass", 20, 5, 4), (1, "fail", 20, 5, 1),
                               (2, "pass", 20, 5, 4), (2, "fail", 20, 5, 2)])
    assert one["tpr"] == pytest.approx(0.8 / (0.8 + 0.3))
    assert two["tpr"] == pytest.approx(0.8 / (0.8 + 0.3))
    assert one["tpr_interval"] != two["tpr_interval"]


# A second batch is added ----------------------------------------------------------------------

def _more_questions(root, model: str | None = None) -> None:
    """The eval ran on 10 more questions (36-45: 5 passed, then 5 failed), with the old 36."""
    kwargs = {"model": model} if model else {}
    promptfoo_project(root, split(20, 16) + split(5, 5), **kwargs)


def _all_marked(root) -> Workspace:
    promptfoo_project(root, split(20, 16))
    ws = start_label.prepare(start.find_judge(root), say=lambda line: None)
    _mark(ws)
    return ws


ADDED = "Your newest results have 10 answers you haven't seen. They're added for marking."


def test_new_graded_answers_join_as_a_second_batch(here, capsys, pages):
    ws = _all_marked(here)
    from judgekeeper import judge_setup

    found = start.find_judge(here)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    _more_questions(here)
    code, out, _ = run(capsys, "mark", "--no-browser")
    assert code == 0, out
    assert ADDED in flat(out)
    data = ws.data()
    new = [q for q in data["queue"] if q.get("batch") == 2]
    assert len(new) == 10 and len(data["queue"]) == 46
    assert {q["group"] for q in new} == {"pass", "fail"}
    assert all(q.get("batch", 1) == 1 for q in data["queue"] if q not in new)
    assert data["pool"] == {"answers": 46, "pass": 25, "fail": 21}
    pool = [json.loads(x) for x in ws.pool.read_text(encoding="utf-8").splitlines()]
    assert {_index(p["input"]) for p in pool if p.get("batch") == 2} == set(range(36, 46))
    # the old marks keep counting, and the next run adds nothing more
    assert len(StartSession(ws).items) == 46
    code, out, _ = run(capsys, "mark", "--no-browser")
    assert "haven't seen" not in out
    assert len(ws.data()["queue"]) == 46


def test_no_batch_is_added_when_the_judge_changed(here, capsys, pages):
    ws = _all_marked(here)
    from judgekeeper import judge_setup

    found = start.find_judge(here)
    judge_setup.save(ws, judge_setup.of(found), found.metric)
    _more_questions(here, model=HAIKU)
    run(capsys, "mark", "--no-browser")
    assert len(ws.data()["queue"]) == 36
    assert all("batch" not in q or q["batch"] == 1 for q in ws.data()["queue"])


def test_an_answer_whose_text_changed_is_a_new_answer(here):
    ws = _all_marked(here)
    outputs = [f"Answer {i}." for i in range(36)]
    outputs[3] = "A new answer to question 3."
    promptfoo_project(here, split(20, 16), outputs=outputs)
    added = batches.add(ws, start.find_judge(here))
    assert added == 1
    queue = ws.data()["queue"]
    assert len(queue) == 37  # the old answer 3 stays, with its mark
    assert [q.get("batch", 1) for q in queue].count(2) == 1


def test_answers_without_a_clear_grade_never_join(here):
    ws = _all_marked(here)
    promptfoo_project(here, split(20, 16) + [None, None])  # a judge error on both
    assert batches.add(ws, start.find_judge(here)) == 0
    assert len(ws.data()["queue"]) == 36


# The page offers the newest batch first -------------------------------------------------------

def test_the_page_offers_the_new_batch_first(here):
    ws = _all_marked(here)
    _more_questions(here)
    batches.add(ws, start.find_judge(here))
    state = StartSession(ws).state()
    first = [_index(x["input"]) for x in state["items"][:10]]
    assert set(first) == set(range(36, 46))
    assert state["items"][state["start"]]["label"] is None
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    head = [groups[x["id"]] for x in state["items"][:10]]
    assert head.count("pass") == head.count("fail") == 5  # half passed, half failed


def test_older_unmarked_answers_come_after_the_new_batch(here):
    promptfoo_project(here, split(20, 16))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark(ws, only=set(range(10)) | set(range(20, 30)))
    _more_questions(here)
    batches.add(ws, start.find_judge(here))
    items = StartSession(ws).items
    order = [_index(StartSession(ws).raw[i["id"]]["input"]) for i in items]
    assert set(order[:10]) == set(range(36, 46))
    assert set(order[10:]) == set(range(36))


# Which batches count --------------------------------------------------------------------------

def _two_batches(root) -> Workspace:
    ws = _all_marked(root)
    _more_questions(root)
    batches.add(ws, start.find_judge(root))
    return ws


def test_a_batch_below_the_minimum_is_left_out_and_named(here):
    ws = _two_batches(here)
    _mark(ws, only={36, 37, 41})  # 2 of 5 passed, 1 of 5 failed
    r = start_label.store_result(ws, StartSession(ws))
    assert r["batches"] == {"counted": [1], "of": 2, "answers": 36, "waiting": 10}
    assert r["labels"] == {"correct": 20, "wrong": 16}  # batch 2's 3 marks are left out
    assert batches.line(r["batches"]) == ("This result is on 1 of 2 batches (36 answers). 10 "
                                          "newer answers need a few marks first.")
    html = ws.report_html.read_text(encoding="utf-8")
    assert "This result is on 1 of 2 batches (36 answers)." in html
    line = json.loads(ws.history_jsonl.read_text(encoding="utf-8").splitlines()[-1])
    assert line["batches"] == {"counted": [1], "of": 2, "answers": 36, "waiting": 10}


def test_a_batch_counts_with_five_marks_in_each_stratum(here):
    ws = _two_batches(here)
    _mark(ws, only=set(range(36, 46)))  # every answer of batch 2
    r = start_label.store_result(ws, StartSession(ws))
    assert r["batches"] == {"counted": [1, 2], "of": 2, "answers": 46, "waiting": 0}
    assert batches.line(r["batches"]) is None
    assert r["labels"] == {"correct": 25, "wrong": 21}
    line = json.loads(ws.history_jsonl.read_text(encoding="utf-8").splitlines()[-1])
    assert line["batches"]["counted"] == [1, 2]


def test_a_fully_marked_small_stratum_counts():
    data = {"queue": [{"id": "a", "group": "pass"}, {"id": "b", "group": "fail"}]
            + [{"id": f"p{i}", "group": "pass", "batch": 2} for i in range(6)]
            + [{"id": f"f{i}", "group": "fail", "batch": 2} for i in range(2)]}
    labels = {"a": "pass", "b": "fail", **{f"p{i}": "pass" for i in range(5)},
              "f0": "fail", "f1": "pass"}
    assert batches.counting(data, labels) == [1, 2]  # 5 of 6, and 2 of 2
    del labels["f1"]
    assert batches.counting(data, labels) == [1]  # 1 of 2: under 5, not every one


def test_the_first_batch_always_counts():
    data = {"queue": [{"id": "a", "group": "pass"}, {"id": "b", "group": "fail"},
                      {"id": "c", "group": "fail"}]}
    assert batches.counting(data, {"a": "pass"}) == [1]


# The marks kept aside for `fix` ---------------------------------------------------------------

class _Marks:
    def __init__(self, person, judge, batch):
        self.person, self.judge, self.batch = person, judge, batch
        self.order = sorted(person)


def test_the_kept_aside_split_is_fair_in_each_stratum():
    person, judge, batch = {}, {}, {}
    for b, n in ((1, 40), (2, 20)):
        for k in range(n):
            i = f"{b}-{k}"
            judge[i] = "pass" if k % 2 else "fail"
            person[i] = judge[i] if k % 5 else ("fail" if judge[i] == "pass" else "pass")
            batch[i] = b
    seen, hidden = fix.make_split(_Marks(person, judge, batch), seed=7)
    assert sorted(seen + hidden) == sorted(person) and not set(seen) & set(hidden)
    for b in (1, 2):
        for g in ("pass", "fail"):
            for agrees in (True, False):
                cell = [i for i in person if batch[i] == b and judge[i] == g
                        and (person[i] == g) == agrees]
                k = sum(i in hidden for i in cell)
                assert k >= -(-len(cell) * fix.HIDDEN_TENTHS // 10) if len(cell) > 1 else k == 0


def test_an_existing_split_stays_and_new_batch_marks_are_split(here):
    ws = _two_batches(here)
    fix.prepare_split(ws)
    before = fix.read_split(ws)
    _mark(ws, only=set(range(36, 46)))
    fix.prepare_split(ws)
    after = fix.read_split(ws)
    assert set(before.hidden) <= set(after.hidden) and set(before.seen) <= set(after.seen)
    new = set(after.hidden) - set(before.hidden)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"] if q.get("batch") == 2}
    assert new and new <= set(groups)  # some of batch 2's marks are kept aside
    assert {groups[i] for i in new} == {"pass", "fail"}  # in each stratum


def test_marks_of_a_batch_that_does_not_count_are_not_shown(here):
    ws = _two_batches(here)
    _mark(ws, only={36, 41}, person={36: "fail"})  # a disagreement in a batch too small
    fix.prepare_split(ws)
    split_ = fix.read_split(ws)
    ids = {q["id"] for q in ws.data()["queue"] if q.get("batch") == 2}
    assert not ids & (set(split_.seen) | set(split_.hidden))


# Every answer marked: the Next: line points to `judgekeeper mark` ------------------------------

NEXT_ALL_MARKED = ("Next: run your eval on more questions, then run `judgekeeper mark`: the new "
                   "answers join the ones you marked.")


def test_every_answer_marked_points_to_mark(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    code, out, _ = run(capsys)
    assert code == 3, out
    assert next_lines(out)[-1] == NEXT_ALL_MARKED
    assert "--new" not in out


def test_the_end_card_points_to_mark(here, capsys):
    from judgekeeper import page

    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws)
    assert page.marking_status(StartSession(ws))["done"][1] == NEXT_ALL_MARKED


def test_then_mark_adds_the_new_answers(here, capsys, pages):
    promptfoo_project(here, split(28, 12))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    run(capsys)
    promptfoo_project(here, split(28, 12) + split(4, 6))
    code, out, _ = run(capsys, "mark", "--no-browser")
    assert code == 0, out
    assert ("Your newest results have 10 answers you haven't seen. They're added for "
            "marking.") in flat(out)
    assert "You marked 40 answers so far: 28 Pass, 12 Fail." in out


# `check` after a change: the marks of the batches that count, weighted the same way ----------

def _judged(ws: Workspace, root) -> None:
    from judgekeeper import judge_setup

    found = start.find_judge(root)
    judge_setup.save(ws, judge_setup.of(found), found.metric)


def test_check_leaves_out_the_marks_of_a_batch_that_does_not_count(here):
    from judgekeeper import check

    ws = _two_batches(here)
    _judged(ws, here)
    _mark(ws, only={36, 41})
    state = check._state(str(here))
    assert len(state.marks) == 36
    assert not set(state.marks) & {q["id"] for q in ws.data()["queue"] if q.get("batch") == 2}


def test_check_weighs_the_marks_by_stratum(here):
    from judgekeeper import check

    ws = _two_batches(here)
    _judged(ws, here)
    _mark(ws, only=set(range(36, 46)))
    state = check._state(str(here))
    assert len(state.marks) == 46
    picked, pool = check._picks(state)
    assert pool == {(1, "pass"): 20, (1, "fail"): 16, (2, "pass"): 5, (2, "fail"): 5}
    new = [q for q in ws.data()["queue"] if q.get("batch") == 2]
    assert {picked[q["id"]] for q in new} == {(2, "pass"), (2, "fail")}
    marked = state.marks
    verdicts = {i: ("pass" if m == "fail" else m) for i, m in marked.items()}  # passes all
    rates = check._rates(marked, verdicts, picked, pool)
    items = [(picked[i], marked[i], verdicts[i]) for i in marked]
    want = weighted.general_strata(items, pool, draws=200)
    assert rates == {"tpr": want["tpr"], "tnr": want["tnr"]}
    assert rates["tnr"] == 0.0


def test_a_recheck_keeps_each_batchs_picked_groups(here):
    """After a check moved the marks to a new LLM-as-a-judge, a later batch keeps the grades it was
    picked by when the marks move again."""
    from judgekeeper import check

    ws = _two_batches(here)
    _mark(ws, only=set(range(36, 46)))
    data = ws.data()
    data["picked"] = {"pool": {"pass": 20, "fail": 16},
                      "groups": {q["id"]: q["group"] for q in data["queue"]
                                 if q.get("batch", 1) == 1}}
    start_label._write_json(ws.start, data)
    found = start.find_judge(here)
    check._adopt(ws, found, {})
    groups = ws.data()["picked"]["groups"]
    assert len(groups) == 46


def test_the_pass_mark_fit_weighs_each_mark_by_its_stratum():
    from judgekeeper.start_fix import cell, cell_weights

    marks = ([{"judge": "pass", "final": "pass", "batch": 1}] * 4
             + [{"judge": "pass", "final": "pass", "batch": 2}] * 2
             + [{"judge": "fail", "final": "fail", "batch": 1}] * 2)
    pool = {(1, "pass"): 40, (2, "pass"): 10, (1, "fail"): 20}
    weights = cell_weights(marks, marks, pool)
    assert weights == {cell(marks[0]): 10.0, cell(marks[4]): 5.0, cell(marks[6]): 10.0}
    one = [{k: v for k, v in m.items() if k != "batch"} for m in marks]  # one batch: as before
    assert cell_weights(one, one, {"pass": 50, "fail": 20}) == {("pass", True): 50 / 6,
                                                                ("fail", True): 10.0}


# Later batches -----------------------------------------------------------------------------

def _next(out: str) -> str:
    return next_lines(out)[-1]


# a later batch marked in two sittings ----------------------------------------------------

class _Sittings:
    """Marks as fix.Marks gives them to current_split."""

    def __init__(self):
        self.person, self.judge, self.batch, self.order = {}, {}, {}, []

    def add(self, b: int, ids) -> None:
        for k in ids:
            i = f"{b}-{k}"
            self.judge[i] = "pass" if k % 2 else "fail"
            self.person[i] = self.judge[i] if k % 4 else ("fail" if k % 2 else "pass")
            self.batch[i] = b
            self.order.append(i)

    def keeps_aside(self) -> bool:
        return True


def _cells(m: _Sittings, b: int) -> list[list[str]]:
    return [[i for i in m.person if m.batch[i] == b and m.judge[i] == g
             and (m.person[i] == g) == agrees]
            for g in ("pass", "fail") for agrees in (True, False)]


def test_later_batch_in_two_sittings_same_share_kept_aside(here):
    ws = Workspace(here)
    ws.dir.mkdir()
    m = _Sittings()
    m.add(1, range(40))
    fix.current_split(ws, m)
    m.add(2, range(3))  # a first sitting of batch 2
    fix.current_split(ws, m)
    m.add(2, range(3, 40))  # and the rest of it
    split_ = fix.current_split(ws, m)
    hidden = set(split_.hidden)
    for cell in _cells(m, 2):
        want = -(-len(cell) * fix.HIDDEN_TENTHS // 10) if len(cell) > 1 else 0
        assert sum(i in hidden for i in cell) == want, cell
    first = sum(m.batch[i] == 1 for i in hidden)
    assert sum(m.batch[i] == 2 for i in hidden) >= first - 4  # about the first batch's share


# after "Worse", a waiting batch keeps one way out ----------------------------------------

NEXT_WORSE_TABLE = ("Next: go back to your old LLM-as-a-judge, or change its rule; then run "
                    "your eval and `judgekeeper check`.")


def _truth(i: int) -> bool:
    return i % 3 != 0


def test_after_worse_a_waiting_batch_does_not_bring_back_the_loop(here, capsys, pages):
    old = [(not _truth(i)) if i % 4 == 1 else _truth(i) for i in range(70)]
    table_project(here, old[:60])
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws, {i: "pass" if _truth(i) else "fail" for i in range(60)})
    run(capsys, "--no-browser")
    table_project(here, old)  # 10 more questions: a second batch
    run(capsys, "--no-browser")
    _mark(ws, {i: "pass" if _truth(i) else "fail" for i in range(70)}, only={60, 61, 62})
    new = [(not v) if i % 2 == 0 or i % 4 == 1 else v for i, v in enumerate(old)]
    table_project(here, new)
    code, out, _ = run(capsys, "check")
    assert code == 1 and "Worse" in out, out
    assert _next(out) == NEXT_WORSE_TABLE
    code, out, _ = run(capsys, "--no-browser")
    assert _next(out) == NEXT_WORSE_TABLE, out
    assert "re-check your changed LLM-as-a-judge" not in out


# new answers that came with changed grades wait ------------------------------------------

def test_new_answers_with_changed_grades_wait_and_the_screen_says_so(here, capsys, pages):
    table_project(here, split(20, 16))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    regraded = [(not v) if i % 6 == 0 else v for i, v in enumerate(split(20, 16))]
    table_project(here, regraded + split(10, 10))  # 20 new answers, and grades changed
    line = ("20 new answers came with changed grades, so they wait until your changed LLM-as-a-judge "
            "is checked.")
    for argv in (("mark", "--no-browser"), ("--no-browser",)):
        _, out, _ = run(capsys, *argv)
        assert line in flat(out), out
        assert "more questions" not in out
        assert "judgekeeper check" in _next(out), out
        assert len(ws.data()["queue"]) == 36  # they join no batch


# "Your eval ran again" once --------------------------------------------------------------

RAN_AGAIN = "Your eval ran again."


def test_ran_again_is_said_once_after_a_batch_from_a_new_file(here, capsys, pages):
    table_project(here, split(10, 30))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    table_project(here, split(5, 5), tag=" (new)")  # the file now holds only new answers
    _, out, _ = run(capsys, "--no-browser")
    assert "added for marking" in flat(out), out
    run(capsys, "--stop")
    _, out, _ = run(capsys, "--no-browser")
    assert RAN_AGAIN not in out, out


# a waiting batch's marks are named apart -------------------------------------------------

def test_a_waiting_batchs_marks_are_named_apart(here, capsys, pages):
    promptfoo_project(here, split(20, 14))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark(ws)
    promptfoo_project(here, split(20, 14) + split(5, 5))
    batches.add(ws, start.find_judge(here))
    _mark(ws, only={34, 39, 40})  # 1 Pass and 2 Fail in batch 2: it doesn't count yet
    _, out, _ = run(capsys, "--no-browser")
    text = flat(out)
    # the counts before "not enough" are the ones that count; the waiting batch's said apart
    assert ("You marked 37 answers so far: 20 Pass, 14 Fail count for a result, and 3 more "
            "are in a newer batch that doesn't count yet.") in text, out
    assert "21 Pass" not in text and "16 Fail" not in text
    assert "That's not enough for a result yet." in text
    assert text.index("count for a result") < text.index("not enough for a result yet")


def test_with_no_waiting_batch_the_count_line_is_as_before(here, capsys, pages):
    promptfoo_project(here, split(20, 14))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    _mark(ws, only=set(range(10)) | set(range(20, 25)))  # 10 Pass and 5 Fail
    _, out, _ = run(capsys, "--no-browser")
    assert "You marked 15 answers so far: 10 Pass, 5 Fail." in out, out
    assert "newer batch" not in out


# one newer answer ------------------------------------------------------------------------

def test_one_newer_answer_needs_a_mark():
    assert batches.line({"counted": [1], "of": 2, "answers": 40, "waiting": 1}) == (
        "This result is on 1 of 2 batches (40 answers). 1 newer answer needs a mark first.")
    assert batches.line({"counted": [1], "of": 2, "answers": 40, "waiting": 3}) == (
        "This result is on 1 of 2 batches (40 answers). 3 newer answers need a few marks "
        "first.")


# the mark command once on the result screen ----------------------------------------------

def test_the_result_screen_names_the_mark_command_once(here, capsys, pages):
    promptfoo_project(here, split(30, 30))
    ws = start_label.prepare(start.find_judge(here), say=lambda line: None)
    person = {i: ("fail" if i in (1, 2, 3) else "pass") if i < 30
              else ("pass" if i in (31, 32) else "fail") for i in range(60)}
    _mark(ws, person, only=set(range(20)) | set(range(30, 50)))
    promptfoo_project(here, split(30, 30) + split(5, 5))
    batches.add(ws, start.find_judge(here))
    _mark(ws, only={60, 65})  # a batch waiting
    code, out, _ = run(capsys, "--no-browser")
    assert code == 0, out
    assert "Too early to tell" in out or "too early to tell" in out, out
    run(capsys, "--stop")
    _, out, _ = run(capsys, "--no-browser")
    assert flat(out).count("judgekeeper mark") == 1, out
    assert "The Next step below also lets you say why on these." in flat(out)
    assert _next(out) == "Next: run `judgekeeper mark --no-browser` to mark more answers."


# A check of a partial eval --------------------------------------------------------------------

def test_a_check_of_a_partial_eval_says_to_run_it_on_all_questions(here, capsys, pages):
    table_project(here, split(20, 16))
    assert run(capsys, "--no-browser")[0] == 0
    ws = Workspace(here)
    _mark(ws)
    run(capsys, "--no-browser")
    partial = split(20, 16)[:10]
    partial[0] = not partial[0]
    table_project(here, partial)  # the eval ran on 10 questions, over the old file
    _, out, _ = run(capsys, "check")
    assert "more questions" not in out, out
    assert _next(out) == ("Next: run your eval on all your questions, then run "
                          "`judgekeeper check`."), out
