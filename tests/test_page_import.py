"""A marking page left open while `--labels` imports marks. Every answer to the page carries
the version of marks.jsonl (its size and time): /state and the page's own data the version
now, /label the version before its own line and after it. When the version before is not the
one the page holds, someone else wrote marks (an import, another page), and the page takes a
new list and counts from /state before it shows the next answer. No test calls an LLM."""

from __future__ import annotations

from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer
from tests.test_labels_import import here, run, table, write_labels  # noqa: F401


def _ids(page: StartSession) -> dict[str, str]:
    """{answer text: id} for the answers the page holds."""
    return {page.raw[i["id"]]["output"]: i["id"] for i in page.items}


def test_the_page_and_state_carry_the_marks_version(here, capsys, pages):  # noqa: F811
    table(here, 60, 60)
    run(capsys)
    page = StartSession(Workspace(here))
    held = page.state()["version"]
    assert held and held == page.version()
    item = page.items[0]
    page.update({"id": item["id"], "label": "pass"})
    s = page.summary()
    assert s["before"] == held  # nobody else wrote: the page's list is still right
    assert s["version"] != held and s["version"] == page.state()["version"]


def test_an_import_while_the_page_is_open_shows_in_the_version(here, capsys, pages):  # noqa: F811
    table(here, 60, 60)
    run(capsys)
    ws = Workspace(here)
    page = StartSession(ws)
    held = page.state()
    shown = held["items"][held["start"]]
    rows = _ids(page)
    imported = [i for i in range(60) if rows[answer(i)] != shown["id"]][:4]
    write_labels(here / "mine.csv", [{"answer": answer(i), "label": "pass"} for i in imported])
    run(capsys, "--labels", "mine.csv")  # the page is still open
    page.update({"id": shown["id"], "label": "fail", "seconds": 4})
    s = page.summary()
    assert s["before"] != held["version"]  # the page learns its list is old
    fresh = page.state()  # what it takes before it shows the next answer
    assert fresh["version"] == s["version"]
    marked = {i["id"]: i["label"] for i in fresh["items"]}
    assert all(marked.get(rows[answer(i)]) == "pass" for i in imported)
    assert fresh["items"][fresh["start"]]["label"] is None  # the next answer is one to mark
    assert fresh["counts"]["correct"] + fresh["counts"]["wrong"] == len(imported) + 1


def test_a_repeat_mark_also_says_the_version_before(here, capsys, pages):  # noqa: F811
    table(here, 60, 60)
    run(capsys)
    page = StartSession(Workspace(here))
    held = page.state()["version"]
    item = page.items[0]
    page.update({"id": item["id"], "label": "pass"})
    page.offered[10] = item["id"]
    after = page.summary()["version"]
    page.update({"id": item["id"], "label": "fail", "again": 10})
    s = page.summary()
    assert s["before"] == after != held
