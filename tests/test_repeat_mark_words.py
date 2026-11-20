"""A mark on a card shown again that differs from the first: the page says the first mark still
counts, on the status line and for a screen reader. The same mark: the usual words."""

from __future__ import annotations

import pytest

from judgekeeper import mark_page, start, start_label
from tests.start_projects import promptfoo_project, split
from tests.test_mark_page_script import _data, _run
from tests.test_repeats import _until_offer


@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(150, 150))
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


def test_a_repeat_carries_the_mark_that_counts_on_the_offer_and_the_next_page(ws):
    session = start_label.StartSession(ws)
    _, offer = _until_offer(session)
    counted = session.by_id[offer["id"]]["label"]
    assert counted in ("pass", "fail") and offer["first"] == counted
    state = start_label.StartSession(ws).state()  # the tab closed; `judgekeeper mark` again
    assert state["items"][state["start"]]["first"] == counted
    assert state["items"][state["start"]]["label"] is None  # the card shows no mark


def _repeat_data(first: str) -> dict:
    data = _data(3, start=1)
    data["items"][0]["label"] = first
    data["items"].insert(1, {"id": "a0", "input": "Question 0?", "output": "Answer 0.",
                             "label": None, "skipped": False, "again": 4, "first": first})
    data["total"] = 4
    return data


SAID = """
  await new Promise(function (r) { setTimeout(r, 200); });  // what is heard, a moment later
  console.log(JSON.stringify({status: ids["status"].textContent, heard: ids["done"].textContent,
    at: ids["q-text"].textContent, card: ids["a-again"].textContent,
    sent: sent.map(function (s) { return [s.body.id, s.body.label, s.body.again]; })}));"""


@pytest.mark.parametrize(("first", "press", "said"), [
    ("pass", 'key("ArrowLeft")', "Noted. Your first mark (Pass) still counts."),
    ("fail", 'ids["pass"].fire("click")', "Noted. Your first mark (Fail) still counts."),
])
def test_a_different_mark_on_a_repeat_says_the_first_mark_still_counts(first, press, said):
    got = _run(press + "; await settle();" + SAID, data=_repeat_data(first))
    assert got["status"] == said and got["heard"] == said
    assert got["at"] == "Question 1?"  # the next answer is on screen
    other = "fail" if first == "pass" else "pass"
    assert got["sent"] == [["a0", other, 4]]  # still sent as a repeat


def test_the_same_mark_on_a_repeat_gets_the_usual_words():
    got = _run('key("ArrowRight"); await settle();' + SAID, data=_repeat_data("pass"))
    assert got["status"] == "" and got["heard"] == "Marked Pass."


def test_the_next_mark_clears_the_line():
    got = _run('key("ArrowLeft"); await settle(); later(400); key("ArrowRight"); await settle();'
               + SAID, data=_repeat_data("pass"))
    assert got["status"] == "" and got["heard"] == "Marked Pass."


def test_a_repeat_offered_after_a_mark_keeps_its_first_mark():
    got = _run("""
      var real = fetch;
      fetch = function (url, opts) {
        return real(url, opts).then(function (r) {
          var body = JSON.parse(opts.body);
          if (body.id === "a0" && body.again === undefined) {
            return r.json().then(function (b) {
              b.summary.again = {id: "a0", slot: 10, input: "Question 0?", output: "Answer 0",
                                 first: "pass"};
              return {ok: true, json: function () { return Promise.resolve(b); }};
            });
          }
          return r;
        });
      };
      key("ArrowRight"); await settle(); later(400); key("ArrowLeft"); await settle();""" + SAID,
        data=_data(3))
    assert got["status"] == "Noted. Your first mark (Pass) still counts."


def test_the_card_keeps_its_words():
    assert mark_page.AGAIN == "You saw this answer before. Mark it as you see it now."
