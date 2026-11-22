"""The Label Studio reader's side of "know your people": every person's label (not only the one
the marks use), the time a person took, and the labels a person replaced."""

from __future__ import annotations

import csv

from judgekeeper.readers.label_studio import read_label_studio
from judgekeeper.records import HUMAN
from tests.label_studio_projects import (
    EMAIL,
    FIXTURE_DIR,
    SEVERAL_PEOPLE,
    annotation,
    choice,
    task,
    write,
)


def humans(records):
    return [r for r in records if r.annotator_kind == HUMAN]


def test_ratings_hold_every_persons_label_where_two_or_more_people_labelled(tmp_path):
    path = write(tmp_path / "e.json", [
        task(1, [(2, "Pass"), (3, "Fail")]),  # they disagree: no mark, but both are ratings
        task(2, [(2, "Pass"), (3, "Pass")]),
        task(3, [(2, "Pass")]),  # one person: no rating
    ])
    records = read_label_studio(path)
    assert [(r.target_id, r.metadata["who"], r.label) for r in records.ratings] == [
        ("101", 2, "Pass"), ("101", 3, "Fail"), ("102", 2, "Pass"), ("102", 3, "Pass")]
    assert len(humans(records)) == 2  # the marks: tasks 2 and 3 only


def test_a_cancelled_annotation_is_no_rating(tmp_path):
    t = task(1, [(2, "Pass"), (3, "Fail")])
    t["annotations"][1]["was_cancelled"] = True
    t["annotations"][1]["result"] = []
    path = write(tmp_path / "e.json", [t])
    assert read_label_studio(path).ratings == []


def test_a_person_twice_is_one_rating_the_latest(tmp_path):
    path = write(tmp_path / "e.json", [task(1, [(2, "Pass"), (3, "Fail"), (2, "Fail")])])
    ratings = read_label_studio(path).ratings
    assert sorted((r.metadata["who"], r.label) for r in ratings) == [(2, "Fail"), (3, "Fail")]


def test_ratings_keep_a_number_never_a_name(tmp_path):
    t = task(1, [(2, "Pass"), (3, "Fail")])
    for a in t["annotations"]:
        a["completed_by"] = {"id": a["completed_by"], "email": EMAIL, "first_name": "Ada"}
    records = read_label_studio(write(tmp_path / "e.json", [t]))
    assert all(set(r.metadata) == {"who"} for r in records.ratings)
    assert EMAIL not in repr([r.__dict__ for r in records.ratings])


def test_the_time_a_person_took_and_their_annotation_are_kept(tmp_path):
    t = task(1, [(2, "Pass")])
    t["annotations"][0].update(lead_time=9.9, id=77)
    (mark,) = humans(read_label_studio(write(tmp_path / "e.json", [t])))
    assert mark.metadata == {"who": 2, "seconds": 9.9, "annotation": 77}


def test_a_lead_time_that_is_no_number_is_left_out(tmp_path):
    t = task(1, [(2, "Pass")])
    t["annotations"][0]["lead_time"] = "soon"
    (mark,) = humans(read_label_studio(write(tmp_path / "e.json", [t])))
    assert "seconds" not in mark.metadata


def test_a_replaced_label_is_kept_with_the_one_that_replaced_it(tmp_path):
    t = task(1, [])
    t["annotations"] = [
        annotation(11, 2, [choice("Pass", to="answer")], at="2026-11-10T10:00:00.000000Z",
                   seconds=5.0),
        annotation(12, 2, [choice("Fail", to="answer")], at="2026-11-11T10:00:00.000000Z",
                   seconds=7.0)]
    (mark,) = humans(read_label_studio(write(tmp_path / "e.json", [t])))
    assert mark.label == "Fail" and mark.metadata["annotation"] == 12
    assert mark.metadata["earlier"] == [{"word": "Pass", "at": "2026-11-10T10:00:00.000000Z",
                                         "seconds": 5.0, "annotation": 11}]


def test_a_replaced_label_read_after_the_newer_one_is_still_the_earlier(tmp_path):
    t = task(1, [])
    t["annotations"] = [
        annotation(12, 2, [choice("Fail", to="answer")], at="2026-11-11T10:00:00.000000Z"),
        annotation(11, 2, [choice("Pass", to="answer")], at="2026-11-10T10:00:00.000000Z")]
    (mark,) = humans(read_label_studio(write(tmp_path / "e.json", [t])))
    assert mark.label == "Fail" and [e["annotation"] for e in mark.metadata["earlier"]] == [11]


def test_a_label_nobody_replaced_has_no_earlier(tmp_path):
    (mark,) = humans(read_label_studio(write(tmp_path / "e.json", [task(1, [(2, "Pass")])])))
    assert "earlier" not in mark.metadata


def test_the_real_export_has_ratings_of_its_tasks_with_two_people():
    records = read_label_studio(SEVERAL_PEOPLE)
    by_task: dict[str, set] = {}
    for r in records.ratings:
        by_task.setdefault(r.target_id, set()).add(r.metadata["who"])
    assert by_task and all(len(people) >= 2 for people in by_task.values())


# The flat exports -------------------------------------------------------------------------

FLAT = [
    {"input": "Q1", "output": "A1", "id": 1, "verdict": "Pass", "annotator": 2,
     "annotation_id": 10, "created_at": "2026-11-10T10:00:00Z", "lead_time": 4.5},
    {"input": "Q1", "output": "A1", "id": 1, "verdict": "Fail", "annotator": 3,
     "annotation_id": 11, "created_at": "2026-11-10T10:01:00Z", "lead_time": 6.0},
    {"input": "Q2", "output": "A2", "id": 2, "verdict": "Pass", "annotator": 2,
     "annotation_id": 12, "created_at": "2026-11-10T10:02:00Z", "lead_time": 3.0},
]


def test_a_flat_json_export_has_ratings_and_seconds(tmp_path):
    records = read_label_studio(write(tmp_path / "min.json", FLAT))
    assert sorted((r.target_id, r.metadata["who"], r.label) for r in records.ratings) == [
        ("1", 2, "Pass"), ("1", 3, "Fail")]
    (mark,) = humans(records)  # task 2; task 1's people disagree
    assert mark.metadata == {"who": 2, "seconds": 3.0, "annotation": 12}


def test_a_csv_export_has_ratings_and_seconds(tmp_path):
    path = tmp_path / "answers.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(FLAT[0]))
        w.writeheader()
        w.writerows(FLAT)
    records = read_label_studio(path)
    assert len(records.ratings) == 2
    assert humans(records)[0].metadata["seconds"] == 3.0


def test_the_flat_fixture_has_ratings():
    records = read_label_studio(FIXTURE_DIR / "answers_JSON_MIN.json")
    assert records.ratings and all(r.metadata["who"] is not None for r in records.ratings)
