"""Answers with no grades in a file with its own `id` column: an answer is the same answer only
when its text is the same, as with no id column. A new answer under an old id is new and
unmarked, and exact repeats count once with an id column or without."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import no_grades, start_label
from tests.test_answers_without_grades import _session, mark
from tests.test_front import flat, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(here, outs: dict[int, str], ids: bool = True, repeat: int = 0) -> None:
    rows = [{"id": f"r{i:02d}", "input": f"What is question {i}?", "output": out}
            for i, out in sorted(outs.items())]
    rows += [{**rows[i], "id": f"r{len(outs) + i:02d}"} for i in range(repeat)]
    fields = ["id", "input", "output"] if ids else ["input", "output"]
    with (here / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _ok(capsys) -> str:
    code, out, err = run(capsys, "--no-browser")
    assert code == 0, out + err
    return flat(out)


def test_a_changed_answer_under_its_old_id_is_new_and_unmarked(here, capsys, pages):
    outs = {i: f"First answer {i}." for i in range(20)}
    _write(here, outs)
    _ok(capsys)
    page = _session(here)
    for n, item in enumerate(page.items):
        page.update({"id": item["id"], "label": "fail" if n < 8 else "pass", "seconds": 3})
    _ok(capsys)
    ws = start_label.Workspace(here)
    shown = [page.raw[i["id"]]["input"] for i in page.items if i["label"] == "fail"
             and i["id"] not in no_grades.kept_aside(ws)]
    changed = [int(q.split()[-1].rstrip("?")) for q in shown[:2]]
    for i in changed:
        outs[i] = f"A better answer {i}."
    _write(here, outs)
    said = _ok(capsys)
    assert "Found 2 new answers" in said, said
    page = _session(here)
    new = [i for i in page.items if page.raw[i["id"]]["output"].startswith("A better")]
    assert len(new) == 2 and all(i["label"] is None for i in new)
    failed = no_grades.failed_path(ws)
    text = failed.read_text(encoding="utf-8") if failed.is_file() else ""
    assert "A better answer" not in text


@pytest.mark.parametrize("ids", [True, False])
def test_exact_repeats_count_once_with_an_id_column_or_without(here, capsys, pages, ids):
    _write(here, {i: f"Answer {i}." for i in range(12)}, ids=ids, repeat=3)
    said = _ok(capsys)
    assert len(_session(here).items) == 12
    assert "so each counts once." in said, said


def test_a_grade_column_added_later_keeps_the_marks_made_with_an_id_column(tmp_path,
                                                                          monkeypatch, capsys,
                                                                          pages):
    monkeypatch.chdir(tmp_path)
    rows = [{"id": f"case-{i}", "input": f"What is question {i}?", "output": f"Answer {i}."}
            for i in range(40)]

    def write(grades=None):
        with (tmp_path / "results.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[*rows[0], *(["verdict"] if grades else [])])
            w.writeheader()
            w.writerows({**r, **({"verdict": g} if grades else {})}
                        for r, g in zip(rows, grades or [None] * 40, strict=True))

    write()
    run(capsys, "--no-browser")
    mark(tmp_path, ["pass", "pass", "fail"] * 10)
    write(["pass", "fail"] * 20)
    code, out, err = run(capsys, "--no-browser")
    assert code in (0, 3), out + err
    assert "You marked 30 answers so far" in flat(out), out
    assert sum(1 for i in _session(tmp_path).items if i["label"]) == 30


def test_labels_by_id_and_answer_match_the_answers_whose_ids_come_from_their_text(
        tmp_path, monkeypatch, capsys, pages):
    """A label file with the id column and the answer (one with the id alone is refused when
    it is read, on every path): the answers' ids come from their text, and it still counts."""
    monkeypatch.chdir(tmp_path)
    with (tmp_path / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "input", "output"])
        w.writerows([f"case-{i}", f"What is question {i}?", f"Answer {i}."] for i in range(12))
    with (tmp_path / "mylabels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "output", "label"])
        w.writerows([f"case-{i}", f"Answer {i}.", "fail" if i % 3 == 0 else "pass"]
                    for i in range(11))
    code, out, err = run(capsys, "--labels", "mylabels.csv", "--no-browser")
    said = flat(out)
    assert code == 0, out + err
    assert "Added 11 marks from mylabels.csv (7 Pass, 4 Fail)." in said, said
