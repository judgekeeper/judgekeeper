"""Repeats: after the first marks, about 1 in 20 answers comes back a second time on the
marking page, never said. Only the first mark counts; the result says how often the second
mark differed, and, from enough repeats, what even a perfect LLM-as-a-judge would show at that
rate."""

from __future__ import annotations

import json

import pytest

from judgekeeper import marks, start, start_label, targets
from tests.start_projects import promptfoo_project, save_result, split

JUDGE = {"tool": "promptfoo", "model": "gpt-4o-mini", "rule_hash": "sha256:ab12",
         "pass_mark": None, "fingerprint": {"model": "gpt-4o-mini"}}


def _new(tmp_path):
    path = tmp_path / "marks.jsonl"
    marks.begin(path, marks.header(judge=JUDGE, pool={"pass": 20, "fail": 12},
                                   results=["results.json"]))
    return path


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


# marks.jsonl ---------------------------------------------------------------------------------

def test_a_repeat_line_never_counts_as_a_mark(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.stamp("a", "pass", "pass", 4, "s"))
    marks.append(path, marks.repeat_line("a", "fail", "pass", 3, "s", slot=10))
    m = marks.read(path)
    assert m.counted() == {"a": "pass"}  # the first mark counts
    assert m.repeats["a"]["mark"] == "fail" and m.slots == {10}
    assert m.not_counted == 0
    line = _lines(path)[-1]
    assert line["repeat"] is True and line["slot"] == 10 and line["by"] == "page"


def test_a_repeat_for_an_answer_never_marked_counts_for_nothing(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.repeat_line("a", "pass", "pass", 3, "s", slot=10))
    m = marks.read(path)
    assert m.counted() == {} and "repeats" not in marks.made(m)


def test_made_counts_the_repeats_and_how_many_differ(tmp_path):
    path = _new(tmp_path)
    for i, mark in enumerate(["pass", "fail", "pass", "pass"]):
        marks.append(path, marks.stamp(f"a{i}", mark, "pass", 4, "s"))
    marks.append(path, marks.repeat_line("a0", "pass", "pass", 3, "s", slot=10))
    marks.append(path, marks.repeat_line("a1", "pass", "pass", 3, "s", slot=11))
    marks.append(path, marks.repeat_line("a2", "skip", "pass", 3, "s", slot=12))  # skipped
    marks.append(path, marks.repeat_line("a3", "fail", "pass", 3, "s", slot=13))
    marks.append(path, marks.repeat_line("a3", None, "pass", 3, "s", slot=13))  # undone
    made = marks.made(marks.read(path))
    assert made["repeats"] == {"seen": 2, "changed": 1}
    assert made["marks"] == 4 and made["pass"] == 3 and made["fail"] == 1


def test_a_repeat_changes_no_timing_count(tmp_path):
    path = _new(tmp_path)
    for i in range(4):
        marks.append(path, marks.stamp(f"a{i}", "pass", "pass", 4, "s"))
    marks.append(path, marks.repeat_line("a0", "pass", "pass", 0, "s", slot=10))
    made = marks.made(marks.read(path))
    assert made["seconds"] == 4 and made["under_second"] == 0 and made["sittings"] == 1


def test_a_repeat_of_an_imported_mark_is_left_out(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.imported_line("a", "pass", "pass", "file-1234abcd", "labels.csv"))
    marks.append(path, marks.repeat_line("a", "fail", "pass", 3, "s", slot=10))
    assert "repeats" not in marks.made(marks.read(path))


def test_no_repeats_leave_made_as_it_was(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.stamp("a", "pass", "pass", 4, "s"))
    assert "repeats" not in marks.made(marks.read(path))


# The words ---------------------------------------------------------------------------------

def _made(seen, changed):
    return {"repeats": {"seen": seen, "changed": changed}}


@pytest.mark.parametrize(("seen", "changed", "said"), [
    (1, 0, "You saw 1 answer twice and marked it the same way both times."),
    (3, 0, "You saw 3 answers twice and marked each the same way both times."),
    (1, 1, ("You saw 1 answer twice and marked it differently the second time. Only your "
           "first mark counts.")),
    (3, 1, ("You saw 3 answers twice and marked 1 differently the second time. Only your "
           "first mark counts.")),
    (4, 2, ("You saw 4 answers twice and marked 2 differently the second time. Only your "
           "first mark counts.")),
])
def test_the_repeat_line(seen, changed, said):
    assert start_label.second_thoughts(_made(seen, changed), real_pass=0.8) == [said]


def test_from_10_repeats_with_a_change_it_says_what_a_perfect_judge_would_show():
    best = targets.best_possible(0.8, targets.slip_rate(2 / 10))
    lines = start_label.second_thoughts(_made(10, 2), real_pass=0.8)
    assert lines == [
        ("You saw 10 answers twice and marked 2 differently the second time. Only your first "
        "mark counts."),
        (f"At this rate, even a perfect LLM-as-a-judge would agree with you only about "
        f"{round(best['tpr'] * 100)}% when you say Pass and {round(best['tnr'] * 100)}% when "
        "you say Fail.")]


@pytest.mark.parametrize(("seen", "changed", "real_pass"), [
    (9, 2, 0.8),    # too few repeats
    (10, 0, 0.8),   # no change: nothing to say
    (10, 2, None),  # no real pass rate yet
])
def test_otherwise_no_perfect_judge_line(seen, changed, real_pass):
    assert len(start_label.second_thoughts(_made(seen, changed), real_pass=real_pass)) == 1


def test_the_terminal_says_the_repeat_line_with_the_marks(tmp_path):
    made = {"marks": 30, "pass": 15, "fail": 15, "sittings": 1, "seconds": 4,
            "under_second": 0, "not_counted": 0, "printed": 0, "browser_env": 0, "unsure": 0,
            "after_result": 0, "repeats": {"seen": 2, "changed": 0}}
    assert start_label.made_lines(made)[-1] == ("You saw 2 answers twice and marked each the "
                                                "same way both times.")


# The page's session --------------------------------------------------------------------------

@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(150, 150))
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


def _mark_all(session, n, mark=lambda k: "pass" if k % 2 else "fail", answer_repeats=True):
    """Mark the first `n` answers in queue order, as the page does: each repeat the server
    offers is marked right after (the same mark unless `mark` says otherwise). The offers."""
    offers = []
    for k, item in enumerate(session.items[:n]):
        session.update({"id": item["id"], "label": mark(k), "seconds": 3})
        offer = session.offer
        if offer:
            offers.append((k, offer))
            if answer_repeats:
                session.update({"id": offer["id"], "label": session.by_id[offer["id"]]["label"],
                                "again": offer["slot"], "seconds": 3})
    return offers


def test_no_repeat_before_10_marks_then_about_1_in_20(ws):
    session = start_label.StartSession(ws)
    offers = _mark_all(session, 200)
    assert offers and min(k for k, _ in offers) >= start_label.REPEAT_FROM - 1
    assert 8 <= len(offers) <= 11  # one in each 20 marks after the first 10 (or so)
    assert len({o["id"] for _, o in offers}) == len(offers)  # never the same answer twice


def test_an_offer_is_one_answer_marked_on_the_page_well_before(ws):
    session = start_label.StartSession(ws)
    order = [i["id"] for i in session.items]
    for k, offer in _mark_all(session, 200):
        at = order.index(offer["id"])
        assert at <= k - start_label.REPEAT_GAP  # not one of the last few marked
        assert offer["output"] == session.state()["items"][at]["output"]  # its own text
        assert "label" not in offer or offer["label"] is None  # looks unmarked


def test_the_offer_is_only_in_the_answer_to_that_mark(ws):
    session = start_label.StartSession(ws)
    offers = _mark_all(session, 200, answer_repeats=False)
    k = offers[0][0]
    assert session.offer is None or offers[-1][0] == 199
    session.update({"id": session.items[k]["id"], "label": None})  # undo: no offer
    assert session.offer is None


def test_an_answered_slot_is_never_offered_again(ws):
    session = start_label.StartSession(ws)
    offers = _mark_all(session, 200)
    k, _offer = offers[0]
    item = session.items[k]["id"]
    session.update({"id": item, "label": None})
    again = start_label.StartSession(ws)  # a new page, the same marks
    again.update({"id": item, "label": "pass"})
    assert again.offer is None


def test_marking_a_repeat_the_other_way_changes_no_mark(ws):
    session = start_label.StartSession(ws)
    _mark_all(session, 200, answer_repeats=False)
    counted = marks.read(ws.marks).counted()
    session = start_label.StartSession(ws)  # a new page
    for item in session.items[200:260]:
        session.update({"id": item["id"], "label": "pass", "seconds": 3})
        offer = session.offer
        if offer:
            first = session.by_id[offer["id"]]["label"]
            flip = "fail" if first == "pass" else "pass"
            session.update({"id": offer["id"], "label": flip, "again": offer["slot"]})
            assert session.by_id[offer["id"]]["label"] == first
    m = marks.read(ws.marks)
    now = m.counted()
    assert m.repeats and all(m.repeats[i]["mark"] != now[i] for i in m.repeats)
    assert {i: x for i, x in now.items() if i in counted} == counted
    r = save_result(ws, start_label.StartSession(ws))
    assert r["made"]["repeats"] == {"seen": len(m.repeats), "changed": len(m.repeats)}


def test_the_numbers_are_the_same_with_and_without_repeat_lines(ws, tmp_path):
    session = start_label.StartSession(ws)
    _mark_all(session, 200, answer_repeats=False)
    without = start_label.compute(ws, start_label.StartSession(ws))
    m = marks.read(ws.marks)
    for n, (i, mark) in enumerate(list(m.counted().items())[:20]):
        marks.append(ws.marks, marks.repeat_line(i, "fail" if mark == "pass" else "pass",
                                                 None, 3, "s", slot=500 + n))
    with_them = start_label.compute(ws, start_label.StartSession(ws))
    for key in ("tpr", "tnr", "tpr_interval", "tnr_interval", "real_pass_rate", "labels",
                "verdict"):
        assert with_them[key] == without[key], key
    assert with_them["made"]["repeats"] == {"seen": 20, "changed": 20}


def test_a_repeat_the_page_was_not_offered_is_refused(ws):
    session = start_label.StartSession(ws)
    first = session.items[0]["id"]
    session.update({"id": first, "label": "pass"})
    with pytest.raises(ValueError, match="repeat"):
        session.update({"id": first, "label": "fail", "again": 10})
    assert marks.read(ws.marks).repeats == {}


def test_undo_and_skip_on_a_repeat_write_repeat_lines(ws):
    session = start_label.StartSession(ws)
    offers = _mark_all(session, 200, answer_repeats=False)
    _, offer = offers[0]
    mark = session.by_id[offer["id"]]["label"]
    session.update({"id": offer["id"], "label": mark, "again": offer["slot"]})
    session.update({"id": offer["id"], "label": None, "deferred": False, "again": offer["slot"]})
    session.update({"id": offer["id"], "deferred": True, "again": offer["slot"]})
    lines = [x for x in _lines(ws.marks)[1:] if x.get("repeat")]
    assert [x["mark"] for x in lines] == [mark, None, "skip"]
    assert session.by_id[offer["id"]]["label"] == mark  # the first mark stays
    assert "repeats" not in marks.made(marks.read(ws.marks))  # a skip counts for nothing


def test_a_repeat_is_never_an_imported_mark(ws):
    session = start_label.StartSession(ws)
    lines = [marks.imported_line(i["id"], "pass", i.get("group"), "file-0000beef", "labels.csv")
             for i in session.items[:100]]
    marks.append_all(ws.marks, lines)
    session = start_label.StartSession(ws)
    imported = {i["id"] for i in session.items[:100]}
    offers = []
    for item in session.items[100:200]:
        session.update({"id": item["id"], "label": "pass"})
        offer = session.offer
        if offer:
            offers.append(offer["id"])
    assert offers and not set(offers) & imported


# The marking page's script ---------------------------------------------------------------------

def test_the_page_shows_an_offered_repeat_next_and_sends_its_slot():
    from tests.test_mark_page_script import _data, _run

    data = _data()
    got = _run("""
      var real = fetch;
      fetch = function (url, opts) {
        return real(url, opts).then(function (r) {
          var body = JSON.parse(opts.body);
          if (body.id === "a0" && body.again === undefined) {
            return r.json().then(function (b) {
              b.summary.again = {id: "a0", slot: 10, input: "Question 0?", output: "Answer 0"};
              return {ok: true, json: function () { return Promise.resolve(b); }};
            });
          }
          return r;
        });
      };
      key("ArrowRight"); await settle();
      var shown = ids["q-text"].textContent, listed = ids["queue"].children.length;
      later(400); key("ArrowLeft"); await settle();
      var after = ids["q-text"].textContent;
      later(400); key("z"); await settle();
      console.log(JSON.stringify({shown: shown, after: after, listed: listed,
        back: ids["q-text"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label, s.body.again]; })}));""",
               data)
    assert got["shown"] == "Question 0?"  # the repeat comes next, looking like any answer
    assert got["after"] == "Question 1?"
    assert got["listed"] == len(data["items"])  # never twice in the list
    assert got["sent"][:2] == [["a0", "pass", None], ["a0", "fail", 10]]
    assert got["back"] == "Question 0?" and got["sent"][2] == ["a0", None, 10]  # undo: the repeat


def _until_offer(session):
    """Mark answers in queue order until the server offers a repeat; (marks made, offer)."""
    for k, item in enumerate(session.items):
        session.update({"id": item["id"], "label": "pass" if k % 2 else "fail", "seconds": 3})
        if session.offer:
            return k + 1, session.offer
    raise AssertionError("no repeat offered")


def test_a_repeat_showing_when_the_page_closed_comes_first_on_the_next_page(ws):
    _, offer = _until_offer(start_label.StartSession(ws))
    state = start_label.StartSession(ws).state()  # the tab closed; `judgekeeper mark` again
    first = state["items"][state["start"]]
    assert first["id"] == offer["id"] and first["again"] == offer["slot"]
    assert first["label"] is None and first["output"] == offer["output"]
    assert [i["id"] for i in state["items"]].count(offer["id"]) == 2  # its own place too
    assert state["total"] == len(start_label.StartSession(ws).items) + 1


def test_that_repeat_can_be_marked_from_the_new_page_and_is_then_gone(ws):
    _, offer = _until_offer(start_label.StartSession(ws))
    page = start_label.StartSession(ws)
    page.state()
    page.update({"id": offer["id"], "label": "pass", "again": offer["slot"]})
    assert marks.read(ws.marks).slots == {offer["slot"]}
    state = start_label.StartSession(ws).state()
    assert all("again" not in i for i in state["items"])


def test_the_same_repeat_whichever_page_asks(ws):
    session = start_label.StartSession(ws)
    _, offer = _until_offer(session)
    again = start_label.StartSession(ws)
    again.state()
    assert again.offered == {offer["slot"]: offer["id"]}


@pytest.mark.parametrize("seed", [None, 402])  # 402: the next mark is a new repeat's slot
def test_once_the_next_answer_is_marked_a_missed_repeat_is_not_shown(tmp_path, monkeypatch,
                                                                    seed):
    if seed is not None:
        monkeypatch.setattr(start_label.secrets, "randbelow", lambda n: seed)
    promptfoo_project(tmp_path, split(150, 150))
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)
    n, missed = _until_offer(start_label.StartSession(ws))
    page = start_label.StartSession(ws)
    page.update({"id": page.items[n]["id"], "label": "pass"})  # past it without the repeat
    again = [i for i in start_label.StartSession(ws).state()["items"] if "again" in i]
    # the missed slot is gone; its answer, never marked a second time, may come back in a later
    # slot as any answer may
    assert all(i["again"] != missed["slot"] for i in again)
    if seed is not None:  # a repeat whose own slot came due is shown, the missed one is not
        assert [i["again"] for i in again] == [missed["slot"] + 1]


def test_the_last_first_mark_offers_no_repeat_and_drops_one_still_waiting(ws, monkeypatch):
    """Every answer has a mark: the result is there at once, never behind a repeat card. A
    repeat still waiting on the page is dropped (the page takes it out), and no new one comes,
    also on a new page."""
    monkeypatch.setattr(start_label, "REPEAT_EVERY", 1)  # a repeat due at every mark
    session = start_label.StartSession(ws)
    items = list(session.items)
    for k, item in enumerate(items[:-1]):
        session.update({"id": item["id"], "label": "pass" if k % 2 else "fail", "seconds": 3})
    waiting = session.offer  # offered after the mark before the last, not marked
    assert waiting is not None
    session.update({"id": items[-1]["id"], "label": "pass", "seconds": 3})
    said = session.summary()
    assert "again" not in said and said["dropped"] == waiting["slot"]
    assert not any("again" in x for x in session.state()["items"])
    assert not any("again" in x for x in start_label.StartSession(ws).state()["items"])
