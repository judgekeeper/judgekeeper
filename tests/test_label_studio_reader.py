"""Label Studio: a project's JSON export read as records. People's labels are HUMAN lines,
the model's predictions the grader. Nothing here calls an LLM.
"""

from __future__ import annotations

import json

import pytest

from judgekeeper import find
from judgekeeper.readers.label_studio import (
    NeedsMetric,
    NoAnswerKey,
    read_label_studio,
)
from judgekeeper.records import CODE, HUMAN, Damaged, RecordsError
from tests.label_studio_projects import (
    EMAIL,
    ONE_PERSON,
    SEVERAL_PEOPLE,
    choice,
    task,
    write,
)


def humans(records):
    return [r for r in records if r.annotator_kind == HUMAN]


def graders(records):
    return [r for r in records if r.annotator_kind == CODE]


# Detection -------------------------------------------------------------------------------

def test_an_export_is_found_as_label_studio():
    assert find.classify_file(ONE_PERSON) == "label-studio"
    assert find.NAMES["label-studio"] == "Label Studio"
    assert "label-studio" in find.TOOLS


def test_a_list_of_tasks_with_predictions_only_is_found(tmp_path):
    only = [{"id": 1, "data": {"a": "b"}, "predictions": []}]
    assert find.classify_file(write(tmp_path / "p.json", only)) == "label-studio"


def test_other_json_lists_are_not_taken_for_an_export(tmp_path):
    assert find.classify_file(write(tmp_path / "a.json", [{"name": "x", "version": "1"}])) is None
    assert find.classify_file(write(tmp_path / "b.json", [{"data": [1, 2]}])) is None
    assert find.classify_file(write(tmp_path / "c.json", [1, 2, 3])) is None


def test_a_walk_finds_an_export(tmp_path):
    write(tmp_path / "export.json", [task(1, [(7, "Pass")], [("v1", "Pass")])])
    assert [r.rel for r in find.search(tmp_path).readable("label-studio")] == ["export.json"]


# Reading ---------------------------------------------------------------------------------

def test_people_are_the_human_lines_and_the_prediction_is_the_grader():
    records = read_label_studio(ONE_PERSON)
    assert len(humans(records)) == 4 and len(graders(records)) == 4
    first = humans(records)[0]
    assert (first.target_id, first.name, first.label) == ("101", "verdict", "Pass")
    assert first.input == "Question 1: how do I reset the widget?"
    assert first.output == "Answer 1: hold the button for five seconds."
    grader = graders(records)[1]
    assert (grader.target_id, grader.name, grader.label) == ("102", "verdict", "Pass")
    assert grader.evaluator == {"version": "judge-v1"}
    assert grader.input == "Question 2: how do I reset the widget?"


def test_the_task_id_is_the_target_id_and_names_the_case():
    records = read_label_studio(ONE_PERSON)
    assert [r.target_id for r in humans(records)] == ["101", "102", "103", "104"]
    assert records.ids_derived is False


def test_who_and_when_are_kept_as_a_number_and_a_time():
    first = humans(read_label_studio(ONE_PERSON))[0]
    assert first.metadata["who"] == 7
    assert first.created_at == "2026-11-10T10:00:00.000000Z"


def test_nothing_about_a_person_is_kept_but_their_number():
    records = read_label_studio(ONE_PERSON)
    text = json.dumps([r.to_dict() for r in records])
    for word in (EMAIL, "ada.lovelace", "Ada", "Lovelace", "first_name", "email"):
        assert word not in text
    assert {r.metadata["who"] for r in humans(records)} == {7}


def test_a_completed_by_with_only_an_email_keeps_no_one(tmp_path):
    t = task(1, [({"email": EMAIL}, "Pass")], [("v1", "Pass")])
    records = read_label_studio(write(tmp_path / "e.json", [t]))
    assert EMAIL not in json.dumps([r.to_dict() for r in records])
    assert "who" not in humans(records)[0].metadata


def test_several_people_one_ground_truth_or_all_agree_or_left_out():
    records = read_label_studio(SEVERAL_PEOPLE)
    by_id = {r.target_id: r.label for r in humans(records)}
    assert by_id == {"105": "Pass",  # both said Pass
                     "107": "Fail",  # they disagree: the ground truth one (the second person)
                     "108": "Fail"}  # the second one was cancelled: one person's label
    assert "106" not in by_id  # they disagree, no ground truth: left out
    assert "People disagreed on 1 answer; it is left out of this number." in records.notes


def test_disagreement_is_counted_in_the_notes_in_the_words_for_many(tmp_path):
    tasks = [task(i, [(7, "Pass"), (8, "Fail")], [("v1", "Pass")]) for i in range(1, 4)]
    records = read_label_studio(write(tmp_path / "d.json", tasks))
    assert humans(records) == []
    assert "People disagreed on 3 answers; they are left out of this number." in records.notes


def test_a_person_labelling_twice_counts_once_by_their_newest(tmp_path):
    t = task(1, [(7, "Fail"), (7, "Pass")], [("v1", "Pass")])
    records = read_label_studio(write(tmp_path / "t.json", [t]))
    assert [r.label for r in humans(records)] == ["Pass"]


def test_cancelled_annotations_are_not_labels(tmp_path):
    t = task(1, [(7, "Pass")], [("v1", "Pass")])
    t["annotations"][0]["was_cancelled"] = True
    records = read_label_studio(write(tmp_path / "t.json", [t]))
    assert humans(records) == [] and len(graders(records)) == 1


def test_a_reason_comes_from_a_textarea_named_like_one(tmp_path):
    t = task(1, [(7, "Fail")], [("v1", "Pass")])
    t["annotations"][0]["result"].append(
        {"from_name": "reason", "to_name": "answer", "type": "textarea",
         "value": {"text": ["It never says how long to hold."]}})
    t["annotations"][0]["result"].append(
        {"from_name": "scratch", "to_name": "answer", "type": "textarea",
         "value": {"text": ["not a reason"]}})
    records = read_label_studio(write(tmp_path / "t.json", [t]))
    assert humans(records)[0].explanation == "It never says how long to hold."


def test_other_kinds_of_region_are_left_out_and_counted_in_one_line(tmp_path):
    t = task(1, [(7, "Pass")], [("v1", "Pass")])
    t["annotations"][0]["result"].append(
        {"from_name": "stars", "to_name": "answer", "type": "rating", "value": {"rating": 4}})
    t["annotations"][0]["result"].append(
        {"from_name": "bad", "to_name": "answer", "type": "number", "value": {"number": 2}})
    records = read_label_studio(write(tmp_path / "t.json", [t]))
    assert len(humans(records)) == 1
    line = next(n for n in records.notes if "left out" in n and "rating" in n)
    assert "2" in line and "number" in line


def test_no_answer_key_names_the_data_keys_never_the_values(tmp_path):
    t = task(1, [(7, "Pass")], [("v1", "Pass")], data={"text": "SECRET-VALUE", "lang": "en"})
    with pytest.raises(NoAnswerKey) as e:
        read_label_studio(write(tmp_path / "t.json", [t]))
    assert e.value.keys == ["text", "lang"]
    assert "SECRET-VALUE" not in str(e.value)
    assert isinstance(e.value, RecordsError)


def test_two_questions_need_metric(tmp_path):
    t = task(1, [(7, "Pass")], [("v1", "Pass")])
    t["annotations"][0]["result"].append(choice("Safe", name="safety"))
    t["predictions"][0]["result"].append(choice("Safe", name="safety"))
    path = write(tmp_path / "t.json", [t])
    with pytest.raises(NeedsMetric) as e:
        read_label_studio(path)
    assert e.value.names == ["verdict", "safety"]
    records = read_label_studio(path, metric="safety")
    assert {r.name for r in records} == {"safety"}


def test_a_metric_that_is_no_question_says_the_names(tmp_path):
    path = write(tmp_path / "t.json", [task(1, [(7, "Pass")], [("v1", "Pass")])])
    with pytest.raises(NeedsMetric) as e:
        read_label_studio(path, metric="nothing")
    assert e.value.names == ["verdict"] and e.value.asked == "nothing"


def test_the_newest_version_is_the_grader_and_the_others_are_said(tmp_path):
    t1 = task(1, [(7, "Pass")], [("v1", "Fail"), ("v2", "Pass")])
    t2 = task(2, [(7, "Fail")], [("v1", "Fail"), ("v2", "Fail")])
    records = read_label_studio(write(tmp_path / "t.json", [t1, t2]))
    assert {r.evaluator["version"] for r in graders(records)} == {"v2"}
    assert any("v2" in n and "2 versions" in n for n in records.notes)
    older = read_label_studio(write(tmp_path / "t.json", [t1, t2]), metric="v1")
    assert {r.evaluator["version"] for r in graders(older)} == {"v1"}


def test_a_file_with_no_predictions_has_labels_and_no_grader(tmp_path):
    records = read_label_studio(write(tmp_path / "t.json", [task(1, [(7, "Pass")], [])]))
    assert len(humans(records)) == 1 and graders(records) == []


def test_a_task_that_is_no_task_is_left_out_and_counted(tmp_path):
    good = task(1, [(7, "Pass")], [("v1", "Pass")])
    records = read_label_studio(write(tmp_path / "t.json", [good, "nope", {"id": 3}]))
    assert len(humans(records)) == 1
    assert records.left_out == [2, 3]


def test_a_file_that_is_not_a_list_is_damaged(tmp_path):
    path = tmp_path / "t.json"
    path.write_text('{"tasks": []}', encoding="utf-8")
    with pytest.raises(Damaged):
        read_label_studio(path)


# The real exports (Label Studio 1.23.2, made-up data) ------------------------------------

REAL = ONE_PERSON.parent
FULL = REAL / "answers_JSON_snapshot_full_predictions.json"
BY_ID = REAL / "answers_JSON.json"
MIN = REAL / "answers_JSON_MIN.json"
CSV = REAL / "answers_CSV.csv"


def test_the_real_exports_are_all_label_studio():
    for path in (FULL, BY_ID, MIN, CSV):
        assert find.classify_file(path) == "label-studio", path.name


def test_a_csv_with_an_annotator_is_never_found_as_a_table_of_verdicts(tmp_path):
    (tmp_path / "labels.csv").write_text(CSV.read_text(encoding="utf-8"), encoding="utf-8")
    found = find.search(tmp_path)
    assert [r.rel for r in found.readable("label-studio")] == ["labels.csv"]
    assert found.readable("table") == []


def test_a_json_min_in_a_folder_is_label_studio_too(tmp_path):
    (tmp_path / "labels.json").write_text(MIN.read_text(encoding="utf-8"), encoding="utf-8")
    assert [r.rel for r in find.search(tmp_path).readable("label-studio")] == ["labels.json"]


def test_a_full_export_has_labels_and_two_graders_the_newest_is_read():
    records = read_label_studio(FULL)
    assert len({r.evaluator["version"] for r in graders(records)}) == 1
    assert any("2 versions" in n for n in records.notes)
    a = read_label_studio(FULL, metric="judge-a")
    assert len(graders(a)) == 12 and {r.evaluator["version"] for r in graders(a)} == {"judge-a"}


def test_the_real_export_labels_follow_the_rules_for_people():
    records = read_label_studio(FULL)
    by_id = {r.target_id: r.label for r in humans(records)}
    assert by_id["1"] == "Pass" and by_id["7"] == "Pass" and by_id["8"] == "Fail"
    assert by_id["12"] == "Fail"  # the third person cancelled
    assert "9" not in by_id and "10" not in by_id and "11" not in by_id  # they disagree
    assert any("3 answers" in n for n in records.notes)
    assert {r.metadata["who"] for r in humans(records)} <= {2, 3, 4}
    assert next(r for r in humans(records) if r.target_id == "1").explanation.startswith(
        "Matches")


def test_ground_truth_settles_a_task_in_the_real_export(tmp_path):
    tasks = json.loads(FULL.read_text(encoding="utf-8"))
    tasks[8]["annotations"][1]["ground_truth"] = True  # task 9: 2 says Pass, 3 says Fail
    records = read_label_studio(write(tmp_path / "t.json", tasks))
    assert {r.target_id: r.label for r in humans(records)}["9"] == "Fail"


def test_predictions_saved_as_ids_hold_no_grader():
    records = read_label_studio(BY_ID)
    assert graders(records) == [] and len(humans(records)) > 0
    assert records.prediction_ids > 0


def test_the_flat_exports_are_people_only_and_read_the_same_way():
    for path in (MIN, CSV):
        records = read_label_studio(path)
        assert graders(records) == []
        by_id = {r.target_id: r.label for r in humans(records)}
        assert by_id["1"] == "Pass" and by_id["8"] == "Fail"
        assert "9" not in by_id and "11" not in by_id  # people disagree
        assert any("answers" in n and "disagreed" in n for n in records.notes)
        assert {r.metadata["who"] for r in humans(records)} <= {2, 3, 4}
        assert next(r for r in humans(records) if r.target_id == "1").input == (
            "What is the capital of Zorvia?")


def test_a_flat_export_with_two_label_columns_needs_metric(tmp_path):
    rows = json.loads(MIN.read_text(encoding="utf-8"))
    for r in rows:
        r["safety"] = "Safe"
    path = write(tmp_path / "m.json", rows)
    with pytest.raises(NeedsMetric) as e:
        read_label_studio(path)
    assert e.value.names == ["verdict", "safety"]
    assert {r.name for r in read_label_studio(path, metric="safety")} == {"safety"}
