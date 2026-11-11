"""Answers with no grades: a card shown again (a repeat) and marked the other way never
counts as a second mark. The counts, the pass rate and its range, the questions kept aside,
fixed / broke / same and failed-answers.md all count each answer once, by its first mark."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper import marks, no_grades, start_label
from tests.test_answers_without_grades import _session
from tests.test_front import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(here, word: str, n: int = 40) -> None:
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["input", "output"])
        w.writerows([f"What is question {i}?", f"{word} answer {i}."] for i in range(n))


def _ok(capsys) -> str:
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    return flat(out)


def _q(page, i: str) -> int:
    return int(page.raw[i]["input"].split()[-1].rstrip("?"))


def _mark(here, how, upto: int | None = None) -> tuple[dict, int]:
    """Each answer not marked yet (up to `upto` marks) marked how(question); each repeat card
    marked the other way. ({question: mark}, repeats marked)."""
    page, given, repeats = _session(here), {}, 0
    for item in [i for i in page.items if not i["label"]][:upto]:
        m = how(_q(page, item["id"]))
        page.update({"id": item["id"], "label": m, "seconds": 3})
        given[_q(page, item["id"])] = m
        offer = page.offer
        if offer:
            first = page.by_id[offer["id"]]["label"]
            page.update({"id": offer["id"], "label": "pass" if first == "fail" else "fail",
                         "again": offer["slot"], "seconds": 3})
            repeats += 1
    return given, repeats


def test_repeat_cards_marked_the_other_way_never_count(here, capsys, pages):
    _write(here, "First")
    _ok(capsys)
    given, repeats = _mark(here, lambda q: "fail" if q % 3 == 0 else "pass", upto=30)
    said = _ok(capsys)
    p = sum(m == "pass" for m in given.values())
    assert f"You passed {p} of 30 answers." in said, said
    _, out, err = run(capsys, "mark", "--no-browser")
    assert f"You marked 30 answers so far: {p} Pass, {30 - p} Fail." in flat(out), out + err
    more, again = _mark(here, lambda q: "fail" if q % 3 == 0 else "pass")
    given |= more
    assert repeats + again >= 1 and len(given) == 40
    ws = start_label.Workspace(here)
    assert marks.read(ws.marks).repeats  # repeats were saved, the other way
    said = _ok(capsys)
    p = sum(m == "pass" for m in given.values())
    assert f"You passed {p} of 40 answers." in said, said
    r = json.loads(ws.result_json.read_text(encoding="utf-8"))
    assert r["pass_rate"] == pytest.approx(p / 40)
    page = _session(here)
    split = no_grades.read_split(ws)
    assert sorted(split.hidden) == sorted(set(split.hidden))
    kept = {_q(page, i) for i in split.hidden}
    shown_fails = sorted(q for q, m in given.items() if m == "fail" and q not in kept)
    text = no_grades.failed_path(ws).read_text(encoding="utf-8")
    listed = sorted(int(x.split()[-1].rstrip("?")) for x in text.splitlines()
                    if x.startswith("What is question"))
    assert listed == shown_fails

    _write(here, "Second")  # a change: every answer new
    _ok(capsys)
    after, _ = _mark(here, lambda q: "pass")
    _ok(capsys)
    since = json.loads(ws.result_json.read_text(encoding="utf-8"))["since"]
    fixed = sum(1 for q in kept if given[q] == "fail" and after[q] == "pass")
    assert since["kept"] == len(kept)
    assert (since["fixed"], since["broke"], since["same"]) == (fixed, 0, len(kept) - fixed)
