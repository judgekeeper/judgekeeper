"""The files that ask a person to label only the few answers worth their time (ask.py)."""

import json
import xml.etree.ElementTree as ET

import pytest

from judgekeeper import ask


def _picks(n_pass=3, n_fail=2):
    out = [ask.Pick(f"p{k}", f"question p{k}", f"answer p{k}", "pass", 0.5) for k in range(n_pass)]
    out += [ask.Pick(f"f{k}", f"question f{k}", f"answer f{k}", "fail", 1.0)
            for k in range(n_fail)]
    return out


def test_label_these_is_label_studio_import_with_text_only():
    tasks = ask.label_these(_picks())
    assert [list(t) for t in tasks] == [["data"]] * 5
    assert tasks[0]["data"] == {"id": "p0", "input": "question p0", "output": "answer p0"}


def test_no_grade_group_chance_or_prediction_reaches_the_import_file():
    tasks = ask.label_these(_picks())
    assert all(set(t) == {"data"} for t in tasks)  # no "predictions", "annotations", "meta"
    assert all(set(t["data"]) == {"id", "input", "output"} for t in tasks)
    text = json.dumps(tasks)
    for word in ("group", "chance", "prediction", "verdict", "grade", "score"):
        assert word not in text


def test_label_config_is_xml_with_the_choices_and_a_reason():
    root = ET.fromstring(ask.LABEL_CONFIG)
    assert root.tag == "View"
    texts = {t.get("name"): t.get("value") for t in root.iter("Text")}
    assert texts == {"input": "$input", "output": "$output"}
    choices = root.find("Choices")
    assert choices.get("name") == "verdict" and choices.get("toName") == "output"
    assert choices.get("choice") == "single"
    assert [c.get("value") for c in choices.iter("Choice")] == ["Pass", "Fail"]
    area = root.find("TextArea")
    assert area.get("name") == "reason" and area.get("toName") == "output"


def test_write_makes_three_files_in_the_ask_folder(tmp_path):
    folder = tmp_path / ".judgekeeper" / "ask"
    paths = ask.write(folder, _picks())
    assert sorted(p.name for p in folder.iterdir()) == [
        "label-config.xml", "label-these.json", "picks.json"]
    assert paths == [folder / "label-these.json", folder / "label-config.xml"]
    assert len(json.loads((folder / "label-these.json").read_text(encoding="utf-8"))) == 5
    assert (folder / "label-config.xml").read_text(encoding="utf-8") == ask.LABEL_CONFIG


def test_each_picks_chance_is_kept_in_picks_json_not_in_the_import_file(tmp_path):
    folder = tmp_path / "ask"
    ask.write(folder, _picks())
    kept = json.loads((folder / "picks.json").read_text(encoding="utf-8"))
    assert kept[0] == {"id": "p0", "group": "pass", "chance": 0.5}
    assert [k["chance"] for k in kept] == [0.5, 0.5, 0.5, 1.0, 1.0]
    assert "question" not in json.dumps(kept)


def test_writing_again_replaces_the_files(tmp_path):
    folder = tmp_path / "ask"
    ask.write(folder, _picks())
    ask.write(folder, _picks(1, 0))
    assert len(json.loads((folder / "label-these.json").read_text(encoding="utf-8"))) == 1


def test_a_key_in_an_answer_is_scrubbed(tmp_path):
    folder = tmp_path / "ask"
    key = "sk-ant-api03-" + "a1B2c3D4" * 6
    ask.write(folder, [ask.Pick("a", "q", f"my key is {key}", "pass", 1.0)])
    assert key not in (folder / "label-these.json").read_text(encoding="utf-8")


def test_no_picks_writes_nothing(tmp_path):
    folder = tmp_path / "ask"
    assert ask.write(folder, []) == []
    assert not folder.exists()


def test_chance_is_how_many_were_picked_over_how_many_the_group_holds():
    chances = ask.chances({"pass": 4, "fail": 5}, {"pass": 100, "fail": 5})
    assert chances == {"pass": pytest.approx(0.04), "fail": 1.0}
    assert ask.chances({"pass": 0}, {"pass": 10}) == {"pass": 0.0}


def test_a_group_with_no_answers_has_chance_one_not_an_error():
    assert ask.chances({"fail": 0}, {"fail": 0}) == {"fail": 1.0}


def test_picks_from_the_queue_keep_the_order_and_their_group_chance():
    queue = [{"id": "a", "group": "pass"}, {"id": "b", "group": "fail"},
             {"id": "c", "group": "pass"}, {"id": "d", "group": "fail"}]
    text = {i: (f"q{i}", f"a{i}") for i in "abcd"}
    picks = ask.picks_from(queue, 3, text, {"pass": 10, "fail": 2})
    assert [p.id for p in picks] == ["a", "b", "c"]
    assert [p.chance for p in picks] == [pytest.approx(0.2), 0.5, pytest.approx(0.2)]
    assert picks[0].input == "qa" and picks[1].output == "ab"


def test_picks_from_asks_for_no_more_than_there_are():
    queue = [{"id": "a", "group": "pass"}]
    assert len(ask.picks_from(queue, 9, {"a": ("q", "a")}, {"pass": 1})) == 1


# Graders that disagree ------------------------------------------------------------------------

def test_answers_where_two_graders_differ():
    verdicts = {
        "judge-a": {"1": "pass", "2": "fail", "3": "pass", "4": "fail"},
        "judge-b": {"1": "pass", "2": "pass", "3": "fail", "5": "pass"},
    }
    assert ask.disagreeing(verdicts) == ["2", "3"]


def test_one_grader_never_disagrees_with_itself():
    assert ask.disagreeing({"judge-a": {"1": "pass", "2": "fail"}}) == []
    assert ask.disagreeing({}) == []


def test_three_graders_disagree_when_any_two_differ():
    verdicts = {"a": {"1": "pass", "2": "pass"}, "b": {"1": "pass", "2": "pass"},
                "c": {"1": "pass", "2": "fail"}}
    assert ask.disagreeing(verdicts) == ["2"]


def test_an_error_is_no_verdict_so_it_is_no_disagreement():
    verdicts = {"a": {"1": "pass"}, "b": {"1": "error"}}
    assert ask.disagreeing(verdicts) == []


def test_every_answer_is_in_one_group_and_disagreement_takes_precedence():
    groups = {"1": "pass", "2": "pass", "3": "fail"}
    assert ask.regroup(groups, ["2"]) == {"1": "pass", "2": ask.DISAGREE, "3": "fail"}
    assert ask.regroup(groups, []) == groups


def test_group_sizes_after_regrouping_add_up_to_the_pool():
    groups = {"1": "pass", "2": "pass", "3": "fail", "4": "fail"}
    sizes = ask.sizes(ask.regroup(groups, ["2", "3"]))
    assert sizes == {"pass": 1, "fail": 1, ask.DISAGREE: 2}
    assert sum(sizes.values()) == len(groups)
