"""What /label does with a post that is not a new mark. A post that changes nothing (the same
mark the answer already has from the page, not on a repeat card) writes no line and answers
as usual, so a client that sends it again and again cannot grow marks.jsonl."""

from __future__ import annotations

from judgekeeper import marks, start_label
from tests.test_repeats import ws  # noqa: F401


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
