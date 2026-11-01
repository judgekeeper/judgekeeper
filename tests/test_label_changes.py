"""What /label does with a post that is not a new mark. A post that changes nothing (the same
mark the answer already has from the page, not on a repeat card) writes no line and answers
as usual, so a client that sends it again and again cannot grow marks.jsonl. A post that
changes an answer's first mark (from the list, no `again`) is taken: the page's change wins.
A repeat card still due for that answer is then dropped, as its comparison with the first mark
no longer means anything; the answer says which (`dropped`), so the page takes it out."""

from __future__ import annotations

import pytest

from judgekeeper import marks, start_label
from tests.test_repeats import _until_offer, ws  # noqa: F401


def _count(path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_the_same_mark_again_writes_no_line(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    item = page.items[0]["id"]
    page.update({"id": item, "label": "pass", "seconds": 3})
    lines, counts = _count(ws.marks), page.counts()
    for _ in range(50):
        page.update({"id": item, "label": "pass", "seconds": 3})
    s = page.summary()
    assert _count(ws.marks) == lines and s["counts"] == counts
    assert s["before"] == s["version"]  # nobody else wrote: the page keeps its list
    assert marks.read(ws.marks).counted() == {item: "pass"}


def test_a_skip_or_an_unmark_again_writes_no_line(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    a, b = page.items[0]["id"], page.items[1]["id"]
    page.update({"id": a, "deferred": True})
    page.update({"id": b, "label": "fail"})
    page.update({"id": b, "label": None})
    lines = _count(ws.marks)
    for _ in range(5):
        page.update({"id": a, "deferred": True})
        page.update({"id": b, "label": None})
    assert _count(ws.marks) == lines


def test_a_different_mark_is_still_a_line(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    item = page.items[0]["id"]
    page.update({"id": item, "label": "pass"})
    lines = _count(ws.marks)
    page.update({"id": item, "label": "fail"})
    assert _count(ws.marks) == lines + 1
    assert marks.read(ws.marks).counted() == {item: "fail"}


def test_the_same_mark_on_an_imported_answer_is_a_page_mark(ws):  # noqa: F811
    """The person marked it on the page this time: that is a change (the import gate counts
    page marks), so it is a line."""
    page = start_label.StartSession(ws)
    item = page.items[0]
    marks.append(ws.marks, marks.imported_line(item["id"], "pass", item.get("group"),
                                               "file-0000beef", "labels.csv"))
    page = start_label.StartSession(ws)
    lines = _count(ws.marks)
    page.update({"id": item["id"], "label": "pass"})
    assert _count(ws.marks) == lines + 1
    assert item["id"] in page.page_marked


def test_a_repeat_card_marked_the_same_way_is_still_a_repeat_line(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    _, offer = _until_offer(page)
    first = page.by_id[offer["id"]]["label"]
    lines = _count(ws.marks)
    page.update({"id": offer["id"], "label": first, "again": offer["slot"]})
    assert _count(ws.marks) == lines + 1 and marks.read(ws.marks).slots == {offer["slot"]}


def test_changing_the_first_mark_drops_its_repeat_card(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    _, offer = _until_offer(page)
    first = page.by_id[offer["id"]]["label"]
    flip = "fail" if first == "pass" else "pass"
    before = page.counts()
    page.update({"id": offer["id"], "label": flip})  # from the list, no `again`
    s = page.summary()
    assert s["dropped"] == offer["slot"]  # the page takes the card out
    assert marks.read(ws.marks).counted()[offer["id"]] == flip  # the page's change wins
    assert s["counts"] != before
    state = page.state()
    assert all(i.get("again") is None or i["id"] != offer["id"] for i in state["items"])
    with pytest.raises(ValueError, match="repeat"):  # an old card for it is not taken
        page.update({"id": offer["id"], "label": first, "again": offer["slot"]})
    assert marks.read(ws.marks).repeats == {}


def test_a_new_page_does_not_show_that_answer_again_either(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    _, offer = _until_offer(page)
    flip = "fail" if page.by_id[offer["id"]]["label"] == "pass" else "pass"
    page.update({"id": offer["id"], "label": flip})
    state = start_label.StartSession(ws).state()  # `judgekeeper mark` again
    assert all(i.get("again") is None or i["id"] != offer["id"] for i in state["items"])


def test_dropped_is_only_in_the_answer_to_that_change(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    _, offer = _until_offer(page)
    flip = "fail" if page.by_id[offer["id"]]["label"] == "pass" else "pass"
    page.update({"id": offer["id"], "label": flip})
    page.update({"id": page.items[-1]["id"], "label": "pass"})
    assert "dropped" not in page.summary()


def test_changing_a_mark_with_no_card_due_drops_nothing(ws):  # noqa: F811
    page = start_label.StartSession(ws)
    item = page.items[0]["id"]
    page.update({"id": item, "label": "pass"})
    page.update({"id": item, "label": "fail"})
    assert "dropped" not in page.summary()


def test_the_page_takes_out_a_dropped_card():
    from tests.test_mark_page_script import _data, _run

    data = _data()
    got = _run("""
      var real = fetch, n = 0;
      fetch = function (url, opts) {
        return real(url, opts).then(function (r) {
          var body = JSON.parse(opts.body);
          n += 1;
          if (n === 1 || n === 2) {
            return r.json().then(function (b) {
              if (n === 1) {
                b.summary.again = {id: "a0", slot: 10, input: "Question 0?",
                                   output: "Answer 0"};
              } else { b.summary.dropped = 10; }
              return {ok: true, json: function () { return Promise.resolve(b); }};
            });
          }
          return r;
        });
      };
      key("ArrowRight"); await settle();
      var shown = ids["q-text"].textContent;
      var link = new El("a"); link.setAttribute("data-k", "0");  // a0 in the list
      later(400); ids["queue"].fire("click", {target: link}); await settle();
      later(400); key("ArrowLeft"); await settle();
      console.log(JSON.stringify({shown: shown, now: ids["q-text"].textContent,
        sent: sent.map(function (s) { return [s.body.id, s.body.label, s.body.again]; })}));""",
               data)
    assert got["shown"] == "Question 0?"  # the repeat card, next
    assert got["sent"] == [["a0", "pass", None], ["a0", "fail", None]]  # changed from the list
    assert got["now"] == "Question 1?"  # the card is gone: the next answer to mark
