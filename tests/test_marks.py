"""marks.jsonl (marks.py): a header, then one stamped line per click on the page. The last
line for an answer wins, null clears it, and a line without its stamps is not counted."""

from __future__ import annotations

import json
import os

import pytest

from judgekeeper import __version__, marks, start, start_label
from tests.start_projects import answer, promptfoo_project, question, split

JUDGE = {"tool": "promptfoo", "model": "gpt-4o-mini", "rule_hash": "sha256:ab12",
         "pass_mark": None, "fingerprint": {"model": "gpt-4o-mini"}}


def _new(tmp_path):
    path = tmp_path / "marks.jsonl"
    marks.begin(path, marks.header(judge=JUDGE, pool={"pass": 20, "fail": 12},
                                   results=["results.json"]))
    return path


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_the_header_says_the_judge_the_pool_and_the_results(tmp_path):
    head = _lines(_new(tmp_path))[0]
    assert head["marks"] == 1
    assert head["judgekeeper_version"] == __version__
    assert head["judge"] == JUDGE
    assert head["pool"] == {"pass": 20, "fail": 12}
    assert head["results"] == ["results.json"]
    assert head["created_at"].endswith("Z")


def test_a_mark_is_a_stamped_line(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.stamp("a1", "pass", "fail", 8.5, "s1"))
    line = _lines(path)[1]
    assert line == {"id": "a1", "mark": "pass", "group": "fail", "at": line["at"],
                    "seconds": 8.5, "sitting": "s1", "by": "page"}
    assert line["at"].endswith("Z")
    assert marks.stamp("a1", "skip", "pass", None, "s1", note="unclear")["note"] == "unclear"


@pytest.mark.parametrize("given,kept", [(-3, 0), (99999, 3600), (12.345, 12.35), (None, None),
                                        (float("inf"), 3600)])
def test_seconds_are_kept_between_0_and_3600(given, kept):
    assert marks.stamp("a", "pass", "pass", given, "s")["seconds"] == kept


@pytest.mark.parametrize("bad", ["9", True, float("nan"), [1]])
def test_seconds_that_are_not_a_number_are_refused(bad):
    with pytest.raises(ValueError):
        marks.stamp("a", "pass", "pass", bad, "s")


def test_a_mark_is_pass_fail_skip_or_null():
    with pytest.raises(ValueError):
        marks.stamp("a", "maybe", "pass", 1, "s")


def test_the_last_line_wins_and_null_clears(tmp_path):
    path = _new(tmp_path)
    for item, mark in (("a", "pass"), ("b", "fail"), ("a", "fail"), ("c", "pass"), ("c", None),
                       ("d", "skip")):
        marks.append(path, marks.stamp(item, mark, "pass", 3, "s1"))
    m = marks.read(path)
    assert m.header["pool"] == {"pass": 20, "fail": 12}
    assert m.counted() == {"a": "fail", "b": "fail"}
    assert m.last["c"]["mark"] is None and m.last["d"]["mark"] == "skip"
    assert m.not_counted == 0


def test_unstamped_and_broken_lines_are_not_counted(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.stamp("a", "pass", "pass", 3, "s1"))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "b", "mark": "pass", "group": "pass"}) + "\n")  # no stamps
        f.write("{not json\n")
        f.write(json.dumps({"id": "c", "mark": "pass", "group": "pass", "at": "x",
                            "sitting": "s", "by": "agent"}) + "\n")
        f.write("\n")
    m = marks.read(path)
    assert m.counted() == {"a": "pass"}
    assert m.not_counted == 3
    assert marks.not_counted_line(m.not_counted) == (
        "3 lines in marks.jsonl were not made on the page and are not counted.")
    assert marks.not_counted_line(1) == (
        "1 line in marks.jsonl was not made on the page and is not counted.")
    assert marks.not_counted_line(0) is None


def test_a_missing_file_has_no_marks(tmp_path):
    m = marks.read(tmp_path / "marks.jsonl")
    assert m.header is None and m.counted() == {} and m.not_counted == 0


def test_how_the_marks_were_made(tmp_path):
    path = _new(tmp_path)
    for n, (sitting, seconds) in enumerate([("s1", 9), ("s1", 0.4), ("s2", 12), ("s2", 0.2),
                                            ("s2", 7)]):
        marks.append(path, marks.stamp(f"a{n}", "pass" if n % 2 else "fail", "pass", seconds,
                                       sitting))
    marks.append(path, marks.stamp("skipped", "skip", "pass", 0.1, "s3"))
    made = marks.made(marks.read(path))
    assert made == {"marks": 5, "pass": 2, "fail": 3, "sittings": 2, "seconds": 7,
                    "under_second": 2, "not_counted": 0, "printed": 0}
    assert marks.made(marks.read(path), ids={"a0", "a1"})["marks"] == 2


def test_a_line_separator_in_a_note_stays_on_one_line(tmp_path):
    path = _new(tmp_path)
    marks.append(path, marks.stamp("a", "pass", "pass", 1, "s", note="one two "))
    assert len(path.read_bytes().split(b"\n")) == 3
    assert marks.read(path).last["a"]["note"] == "one two "


def test_a_link_in_the_folder_stops_the_write(tmp_path):
    folder = tmp_path / ".judgekeeper"
    folder.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    path = folder / "marks.jsonl"
    try:
        os.symlink(outside, path)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make links")
    with pytest.raises(marks.MarksError, match="link"):
        marks.append(path, marks.stamp("a", "pass", "pass", 1, "s"))
    assert outside.read_text(encoding="utf-8") == ""


# Written by the page's session ------------------------------------------------------------

@pytest.fixture
def ws(tmp_path):
    promptfoo_project(tmp_path, split(20, 12), tag=" SECRET-TEXT")
    return start_label.prepare(start.find_judge(tmp_path), say=lambda line: None)


def test_marking_starts_with_the_header(ws):
    head = marks.read(ws.marks).header
    data = ws.data()
    assert head["pool"] == {"pass": 20, "fail": 12}
    assert head["results"] == data["results_files"]
    assert head["judge"]["tool"] == "promptfoo"
    assert head["judge"]["fingerprint"] == data["fingerprint"]
    assert head["judge"]["model"] == data["fingerprint"]["model"]
    assert head["judge"]["rule_hash"].startswith("sha256:")


def test_each_click_is_one_stamped_line_with_the_judges_group(ws):
    session = start_label.StartSession(ws)
    first, second = session.items[0]["id"], session.items[1]["id"]
    session.update({"id": first, "label": "pass", "seconds": 4})
    session.update({"id": second, "deferred": True})
    session.update({"id": first, "label": None})
    lines = _lines(ws.marks)[1:]
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    assert [(x["id"], x["mark"]) for x in lines] == [(first, "pass"), (second, "skip"),
                                                     (first, None)]
    assert all(x["group"] == groups[x["id"]] and x["by"] == "page" for x in lines)
    assert lines[0]["seconds"] == 4 and lines[1]["seconds"] is None
    assert len({x["sitting"] for x in lines}) == 1


def test_no_answer_text_in_the_marks_file(ws):
    session = start_label.StartSession(ws)
    for item in session.items[:6]:
        session.update({"id": item["id"], "label": "pass"})
    text = ws.marks.read_text(encoding="utf-8")
    assert "SECRET-TEXT" not in text and question(0) not in text and answer(0) not in text
    assert "SECRET-TEXT" in ws.pool.read_text(encoding="utf-8")


def test_a_new_page_carries_on_from_the_marks(ws):
    session = start_label.StartSession(ws)
    ids = [i["id"] for i in session.items]
    session.update({"id": ids[0], "label": "fail"})
    session.update({"id": ids[1], "deferred": True})
    again = start_label.StartSession(ws)
    assert again.by_id[ids[0]]["label"] == "fail"
    assert again.by_id[ids[1]]["deferred"] and again.by_id[ids[1]]["label"] is None
    assert again.sitting != session.sitting


def test_a_link_in_the_workspace_stops_a_click(ws, tmp_path):
    session = start_label.StartSession(ws)
    outside = tmp_path / "elsewhere.jsonl"
    outside.write_text("", encoding="utf-8")
    ws.marks.unlink()
    try:
        os.symlink(outside, ws.marks)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make links")
    with pytest.raises(marks.MarksError):
        session.update({"id": session.items[0]["id"], "label": "pass"})
    assert outside.read_text(encoding="utf-8") == ""
    assert session.items[0]["label"] is None
