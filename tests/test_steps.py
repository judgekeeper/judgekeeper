"""`judgekeeper steps`: write a Label Studio screen for agent runs, then read the first wrong
steps people and a reviewer gave back. Synthetic data only; no test calls an AI."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from judgekeeper import __version__, metrics, targets
from judgekeeper.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "steps"
CONFIG_END = ('<Paragraphs name="steps" value="$steps" layout="dialogue" nameKey="role" '
              'textKey="content"/><Number name="first_wrong_step" toName="steps" min="0"/>'
              '</View>')


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def result(here: Path) -> dict:
    return json.loads((here / ".judgekeeper" / "steps" / "result.json").read_text(encoding="utf-8"))


# A made-up project of 40 runs: people say 20 are fine and 20 went wrong. The reviewer finds
# 15 of the 20 that went wrong (9 at the same step, 3 one step off, 3 further off) and says 16
# of the 20 fine ones are fine.
def region(number, name="first_wrong_step"):
    return {"from_name": name, "to_name": "steps", "type": "number",
            "value": {"number": number}}


def annotation(who, number, **more):
    return {"id": 1000 + (who if isinstance(who, int) else 0), "completed_by": who,
            "result": [] if number is None else [region(number)],
            "was_cancelled": more.pop("was_cancelled", False),
            "ground_truth": more.pop("ground_truth", False),
            "created_at": more.pop("created_at", "2026-11-22T05:19:21.059618Z"),
            "lead_time": 5.0, **more}


def prediction(model, number, **more):
    return {"id": 1, "model_version": model, "score": 0.8, "result": [region(number)], **more}


def task(i, people, predictions=(), n_steps=6, **data):
    steps = [{"role": "assistant" if k % 2 else "user", "content": f"made up step {k + 1}"}
             for k in range(n_steps)]
    return {"id": 100 + i, "data": {"steps": steps, **data}, "annotations": list(people),
            "predictions": list(predictions)}


def people_first(i):
    return 0 if i < 20 else 1 + i % 5


def reviewer_first(i):
    truth = people_first(i)
    if i < 20:
        return 0 if i < 16 else 2
    k = i - 20
    if k < 5:
        return 0
    if k < 14:
        return truth
    if k < 17:
        return min(truth + 1, 6)
    return min(truth + 3, 6) if truth < 4 else 1


def project(n=40, model="reviewer-a", ids=True):
    tasks = []
    for i in range(n):
        data = {"run_id": f"r{i}"} if ids else {}
        tasks.append(task(i, [annotation(2, people_first(i))],
                          [prediction(model, reviewer_first(i))], **data))
    return tasks


def save(here, tasks, name="export.json"):
    path = here / name
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


# The runs file -> the Label Studio screen --------------------------------------------------

def test_runs_make_the_import_file_the_screen_and_a_next_line(here, capsys):
    runs = shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    code, out, err = run(capsys, "steps", str(runs))
    assert code == 0, err
    folder = here / ".judgekeeper" / "steps"
    tasks = json.loads((folder / "label-these.json").read_text(encoding="utf-8"))
    assert [t["data"]["run_id"] for t in tasks] == ["run-1", "run-2", "3"]
    first = tasks[0]["data"]["steps"]
    assert len(first) == 4 and first[0]["content"] == "Book a table for two at Luma Cafe."
    assert [s["role"] for s in first] == ["1. user", "2. assistant", "3. tool", "4. assistant"]
    assert json.loads(tasks[2]["data"]["steps"][0]["content"]) == {"call": "calc",
                                                                   "args": [1, 2]}
    config = (folder / "label-config.xml").read_text(encoding="utf-8")
    flat = config.replace("\n", "").replace("  ", "")
    assert flat.startswith("<View>") and flat.endswith(CONFIG_END)
    assert "<Paragraphs" in flat and flat.index("<Header") < flat.index("<Paragraphs")
    assert "0" in config and "all fine" in config
    lines = out.rstrip().splitlines()  # the page opens; Label Studio is the other way
    assert lines[-2].startswith("Next: mark runs on the page")
    assert ".judgekeeper/steps/label-these.json" in lines[-1]
    assert "label-config.xml" in lines[-1] and "judgekeeper steps" in lines[-1]


def test_a_task_in_the_runs_is_shown_above_the_steps_and_step_n_is_the_nth(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    run(capsys, "steps", "runs.jsonl")
    folder = here / ".judgekeeper" / "steps"
    tasks = json.loads((folder / "label-these.json").read_text(encoding="utf-8"))
    assert [t["data"]["task"] for t in tasks] == ["Book a table for two at Luma Cafe.", "", ""]
    config = (folder / "label-config.xml").read_text(encoding="utf-8")
    assert '<Text name="task" value="$task"/>' in config
    assert config.index("$task") < config.index("<Paragraphs")
    assert tasks[0]["data"]["steps"][2]["role"].startswith("3. ")  # step 3 = steps[2]
    (here / "plain.jsonl").write_text(
        '{"id": "a", "steps": [{"role": "user", "content": "x"}]}\n', encoding="utf-8")
    run(capsys, "steps", "plain.jsonl")
    assert "task" not in (folder / "label-config.xml").read_text(encoding="utf-8").replace("Task", "")
    assert "task" not in json.loads((folder / "label-these.json").read_text(encoding="utf-8"))[0]["data"]


def test_an_export_with_data_task_and_steps_and_no_run_id_reads_by_task_id(here, capsys):
    tasks = project(ids=False)
    for t in tasks:
        t["data"]["task"] = "Made up request."
    export = save(here, tasks)
    guesses = "\n".join(json.dumps({"id": t["id"], "first_wrong_step": reviewer_first(i)})
                        for i, t in enumerate(tasks))
    (here / "g.jsonl").write_text(guesses, encoding="utf-8")
    code, _, err = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert code == 0, err
    assert result(here)["reviewers"][0]["run_level"]["tpr"]["p"] == 15 / 20
    assert "Made up request" not in (here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8")
    code, _, err = run(capsys, "steps", str(export))  # predictions matched by the task id too
    assert code == 0, err


def test_the_screen_header_says_zero_means_all_fine():
    from judgekeeper import steps

    assert "0" in steps.INSTRUCTIONS and "all fine" in steps.INSTRUCTIONS


@pytest.mark.parametrize("body, said", [
    ('{"steps": [{"role": "user", "content": "x"}]}\n', "no id"),
    ('{"id": "a", "steps": []}\n', "no steps"),
    ('{"id": "a", "steps": "x"}\n', "no steps"),
    (('{"id": "a", "steps": [{"role": "user", "content": "x"}]}\n'
      '{"id": "a", "steps": [{"role": "user", "content": "x"}]}\n'), "twice"),
    ('{"id": "a", "steps": [{"content": "x"}]}\n', "role"),
    ('{"id": "a", "steps": [{"role": "user", "content": "x"}]}\nnot json SECRET-TEXT\n',
     "Line 2"),
])
def test_a_bad_runs_file_is_said_by_line_and_never_quotes_it(here, capsys, body, said):
    (here / "runs.jsonl").write_text(body, encoding="utf-8")
    code, out, err = run(capsys, "steps", "runs.jsonl")
    assert code == 2
    assert said in err and "SECRET-TEXT" not in out + err
    assert err.strip().splitlines()[-1].startswith("Next:")
    assert not (here / ".judgekeeper" / "steps" / "label-these.json").exists()


def test_a_missing_path_is_a_usage_error(here, capsys):
    code, _, err = run(capsys, "steps", "nothing.jsonl")
    assert code == 2 and "Next:" in err


def test_a_folder_reads_its_runs_jsonl(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    code, _, err = run(capsys, "steps", str(here))
    assert code == 0, err
    assert (here / ".judgekeeper" / "steps" / "label-these.json").is_file()


@pytest.mark.skipif(os.name == "nt", reason="file modes")
def test_the_folder_is_private(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    run(capsys, "steps", "runs.jsonl")
    mode = stat.S_IMODE((here / ".judgekeeper" / "steps").stat().st_mode)
    assert mode & 0o077 == 0


# A Label Studio export -> the numbers ------------------------------------------------------

def test_the_numbers_with_ranges(here, capsys):
    export = save(here, project())
    code, out, err = run(capsys, "steps", str(export))
    assert code == 0, err
    people = [people_first(i) > 0 for i in range(40)]
    guess = [reviewer_first(i) > 0 for i in range(40)]
    ag = metrics.agreement(["wrong" if p else "fine" for p in people],
                           ["wrong" if g else "fine" for g in guess], "wrong", "fine")
    saved = result(here)["reviewers"][0]
    run_level = saved["run_level"]
    assert run_level["tpr"]["p"] == ag["tpr"] == 15 / 20
    assert run_level["tnr"]["p"] == ag["tnr"] == 16 / 20
    assert run_level["kappa"] == pytest.approx(ag["kappa"])
    lo, hi = run_level["kappa_interval"]
    assert lo < run_level["kappa"] < hi
    assert run_level["tpr"]["lo"] < 0.75 < run_level["tpr"]["hi"]
    step = saved["step_level"]
    assert step["same"] == metrics.wilson(9, 15)
    assert step["within_one"] == metrics.wilson(12, 15)
    assert "kappa" in out.lower() and "same first wrong step" in out
    assert "between" in out
    assert saved["name"] == "reviewer-a" and saved["fingerprint"]["model"] == "reviewer-a"
    assert saved["fingerprint"]["prompt_hash"] is None
    assert "prompt_hash" in saved["unknown_fields"]
    assert out.rstrip().splitlines()[-1].startswith("Next:")


def test_the_read_line_counts_runs_your_people_labelled_not_runs_that_went_wrong(here, capsys):
    _, out, _ = run(capsys, "steps", str(save(here, project())))  # 20 of 40 are "all fine"
    assert "Read 40 runs from export.json: the people marking labelled 40 of them." in out
    one = [task(0, [annotation(2, 0)], [prediction("rv", 0)], run_id="a")]
    _, out, _ = run(capsys, "steps", str(save(here, one, "one.json")))
    assert "Read 1 run from one.json: the people marking labelled it." in out


def test_never_a_raw_agreement_alone(here, capsys):
    export = save(here, project())
    _, out, _ = run(capsys, "steps", str(export))
    assert "accuracy" not in out.lower() and "agreement" not in out.lower()
    assert "accuracy" not in json.dumps(result(here))


def test_too_few_runs_say_so_and_give_no_number(here, capsys):
    export = save(here, project(n=10))
    code, out, _ = run(capsys, "steps", str(export))
    saved = result(here)["reviewers"][0]
    assert code == 3
    assert "Too few" in out and "%" not in out.split("Agent-as-a-judge")[-1].split("Saved")[0]
    assert saved["run_level"]["tpr"] is None and saved["run_level"]["kappa"] is None
    assert saved["step_level"]["same"] is None
    assert saved["run_level"]["too_few"] and str(targets.ROUGH) in out
    assert out.rstrip().splitlines()[-1].startswith("Next: label more runs")


def test_only_the_kind_with_enough_runs_gets_a_number(here, capsys):
    tasks = [task(i, [annotation(2, 1 + i % 5)], [prediction("rv", 1 + i % 5)], run_id=f"r{i}")
             for i in range(30)]
    code, _, _ = run(capsys, "steps", str(save(here, tasks)))
    saved = result(here)["reviewers"][0]
    assert code == 0
    assert saved["run_level"]["tpr"]["p"] == 1.0
    assert saved["run_level"]["tnr"] is None and saved["run_level"]["kappa"] is None
    assert saved["step_level"]["same"]["p"] == 1.0


def test_ids_only_predictions_need_the_reviewer_option(here, capsys):
    shutil.copy(FIXTURES / "ls_export_ids_only.json", here / "export.json")
    code, out, _ = run(capsys, "steps", "export.json")
    assert code == 3
    assert "ids" in out and "--reviewer" in out.rstrip().splitlines()[-1]
    assert out.rstrip().splitlines()[-1].startswith("Next:")
    saved = result(here)
    assert saved["people"]["labelled"] == 4 and saved["people"]["disagreed"] == 1
    assert saved["reviewers"] == []


def test_the_real_shape_with_full_predictions(here, capsys):
    shutil.copy(FIXTURES / "ls_export_full_predictions.json", here / "export.json")
    code, out, _ = run(capsys, "steps", "export.json")
    saved = result(here)
    assert code == 3  # 5 runs: too few for any number
    assert saved["people"]["tasks"] == 5
    assert [r["name"] for r in saved["reviewers"]] == ["reviewer-a"]
    assert saved["reviewers"][0]["fingerprint"]["model"] == "reviewer-a"
    assert saved["reviewers"][0]["fingerprint"]["created_at"] == "2026-11-22T05:19:21.171764Z" \
        or saved["reviewers"][0]["fingerprint"]["created_at"].startswith("2026-11-22T05:19:2")
    assert "Too few" in out


def test_reviewer_guesses_from_a_jsonl_file(here, capsys):
    tasks = project(ids=True)
    for t in tasks:
        t["predictions"] = [len(t["predictions"])]  # as an export holds them: ids only
    export = save(here, tasks)
    guesses = "\n".join(json.dumps({"id": f"r{i}", "first_wrong_step": reviewer_first(i),
                                    "model": "my-reviewer", "provider": "acme"})
                        for i in range(40))
    (here / "guesses.jsonl").write_text(guesses + "\n", encoding="utf-8")
    code, _, err = run(capsys, "steps", str(export), "--reviewer", "guesses.jsonl")
    assert code == 0, err
    saved = result(here)["reviewers"][0]
    assert saved["name"] == "my-reviewer"
    assert saved["fingerprint"]["model"] == "my-reviewer"
    assert saved["fingerprint"]["provider"] == "acme"
    assert saved["run_level"]["tpr"]["p"] == 15 / 20


def test_the_newest_time_in_the_reviewer_file_is_the_fingerprints(here, capsys):
    export = save(here, project())
    rows = []
    for i in range(40):
        row = {"id": f"r{i}", "first_wrong_step": reviewer_first(i), "model": "my-reviewer"}
        if i == 3:
            row["created_at"] = "2026-11-22T05:00:00Z"
        if i == 7:
            row["timestamp"] = "2026-11-22T07:30:00Z"
        if i == 9:
            row["created_at"] = "2026-11-21T01:00:00Z"
        rows.append(json.dumps(row))
    (here / "g.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    code, _, err = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert code == 0, err
    saved = result(here)["reviewers"][0]
    assert saved["fingerprint"]["created_at"] == "2026-11-22T07:30:00Z"
    assert "created_at" not in saved["unknown_fields"]


def test_no_time_in_the_reviewer_file_leaves_the_fingerprint_time_unknown(here, capsys):
    export = save(here, project())
    rows = [json.dumps({"id": f"r{i}", "first_wrong_step": reviewer_first(i)})
            for i in range(40)]
    (here / "g.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert result(here)["reviewers"][0]["fingerprint"]["created_at"] is None


def test_a_reviewer_file_matches_a_task_with_no_run_id_by_its_task_id(here, capsys):
    tasks = project(ids=False)
    export = save(here, tasks)
    guesses = "\n".join(json.dumps({"id": t["id"], "first_wrong_step": reviewer_first(i)})
                        for i, t in enumerate(tasks))
    (here / "g.jsonl").write_text(guesses, encoding="utf-8")
    code, _, err = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert code == 0, err
    assert result(here)["reviewers"][0]["name"] == "reviewer"


def test_a_bad_reviewer_file_is_said_by_line(here, capsys):
    export = save(here, project())
    (here / "g.jsonl").write_text('{"id": "r1", "first_wrong_step": "SECRET-TEXT"}\n',
                                  encoding="utf-8")
    code, out, err = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert code == 2 and "Line 1" in err and "SECRET-TEXT" not in out + err


def test_several_reviewers_each_get_numbers_and_model_picks_one(here, capsys):
    tasks = project()
    for i, t in enumerate(tasks):
        t["predictions"].append(prediction("reviewer-b", people_first(i)))
    export = save(here, tasks)
    code, out, _ = run(capsys, "steps", str(export))
    assert code == 0
    names = [r["name"] for r in result(here)["reviewers"]]
    assert names == ["reviewer-a", "reviewer-b"]
    assert out.count("Agent-as-a-judge ") == 2
    perfect = result(here)["reviewers"][1]
    assert perfect["run_level"]["tpr"]["p"] == 1.0 and perfect["step_level"]["same"]["p"] == 1.0
    code, out, _ = run(capsys, "steps", str(export), "--model", "reviewer-b")
    assert [r["name"] for r in result(here)["reviewers"]] == ["reviewer-b"]
    code, out, err = run(capsys, "steps", str(export), "--model", "nope")
    assert code == 2 and "reviewer-a" in err and "Next:" in err


def test_no_labels_yet_is_exit_3(here, capsys):
    tasks = [task(i, [], [prediction("rv", 1)], run_id=f"r{i}") for i in range(3)]
    code, out, _ = run(capsys, "steps", str(save(here, tasks)))
    assert code == 3
    last = out.rstrip().splitlines()[-1]
    assert "label" in last and last.startswith("Next:")


# Who counts as a person's label -----------------------------------------------------------

def test_cancelled_and_empty_annotations_are_not_labels(here, capsys):
    tasks = [task(0, [annotation(2, None, was_cancelled=True), annotation(3, None)],
                  [prediction("rv", 1)], run_id="a"),
             task(1, [annotation(2, 3, was_cancelled=True)], [prediction("rv", 1)], run_id="b")]
    run(capsys, "steps", str(save(here, tasks)))
    people = result(here)["people"]
    assert people["tasks"] == 2 and people["labelled"] == 0 and people["no_label"] == 2


def test_two_people_ground_truth_wins_agreement_stands_disagreement_is_left_out(here, capsys):
    tasks = [
        task(0, [annotation(2, 3), annotation(3, 4, ground_truth=True)], run_id="gt"),
        task(1, [annotation(2, 2), annotation(3, 2)], run_id="same"),
        task(2, [annotation(2, 0), annotation(3, 4)], run_id="differ"),
    ]
    _, out, _ = run(capsys, "steps", str(save(here, tasks)))
    people = result(here)["people"]
    assert people["labelled"] == 2 and people["disagreed"] == 1
    assert "People disagreed on 1 run; they are left out of these numbers." in out


def test_a_person_who_labelled_twice_counts_once_newest_wins(here, capsys):
    tasks = [task(0, [annotation(2, 1, created_at="2026-11-22T05:00:00Z"),
                      annotation(2, 3, created_at="2026-11-22T06:00:00Z")], run_id="a")]
    run(capsys, "steps", str(save(here, tasks)))
    assert result(here)["people"]["labelled"] == 1
    assert result(here)["people"]["disagreed"] == 0


def test_a_number_past_the_last_step_or_not_whole_is_left_out_and_counted(here, capsys):
    tasks = [task(0, [annotation(2, 9)], run_id="a"), task(1, [annotation(2, 2.5)], run_id="b"),
             task(2, [annotation(2, -1)], run_id="c"), task(3, [annotation(2, 3.0)], run_id="d")]
    run(capsys, "steps", str(save(here, tasks)))
    people = result(here)["people"]
    assert people["labelled"] == 1 and people["unusable"] == 3


def test_a_region_that_is_not_the_first_wrong_step_number_is_ignored(here, capsys):
    ann = annotation(2, None)
    ann["result"] = [{"from_name": "notes", "to_name": "steps", "type": "textarea",
                      "value": {"text": ["hm"]}}, region(2)]
    run(capsys, "steps", str(save(here, [task(0, [ann], run_id="a")])))
    assert result(here)["people"]["labelled"] == 1


# Privacy -------------------------------------------------------------------------------

def test_who_is_a_number_and_no_personal_field_is_kept(here, capsys):
    person = {"id": 7, "email": "ada.lovelace@example.com", "first_name": "Ada",
              "last_name": "Lovelace", "username": "adal"}
    tasks = [task(i, [annotation(person if i % 2 else 8, people_first(i))],
                  [prediction("reviewer-a", reviewer_first(i))], run_id=f"r{i}")
             for i in range(40)]
    export = save(here, tasks)
    code, out, err = run(capsys, "steps", str(export))
    assert code == 0, err
    everything = out + err + (here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8")
    for leak in ("ada.lovelace", "Ada", "Lovelace", "adal", "example.com"):
        assert leak not in everything
    assert sorted(result(here)["people"]["who"]) == ["7", "8"]


def test_an_object_with_no_id_is_no_who(here, capsys):
    person = {"email": "ada.lovelace@example.com"}
    run(capsys, "steps", str(save(here, [task(0, [annotation(person, 1)], run_id="a")])))
    assert result(here)["people"]["who"] == {}
    assert "ada.lovelace" not in (here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8")


def test_the_result_keeps_no_step_text(here, capsys):
    export = save(here, project())
    run(capsys, "steps", str(export))
    assert "made up step" not in (here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8")


def test_the_reviewer_name_in_a_line_is_one_clean_line(here, capsys):
    tasks = project(model="rv\nSECOND LINE\x1b[31m")
    _, out, _ = run(capsys, "steps", str(save(here, tasks)))
    assert "\x1b" not in out
    assert not any(line.startswith("SECOND LINE") for line in out.splitlines())


# What is not a steps export ----------------------------------------------------------------

def test_a_json_that_is_no_label_studio_export_is_said(here, capsys):
    (here / "x.json").write_text('{"a": 1}', encoding="utf-8")
    code, _, err = run(capsys, "steps", "x.json")
    assert code == 2 and "Label Studio" in err and err.strip().splitlines()[-1].startswith("Next:")


def test_an_export_of_answers_not_steps_is_said(here, capsys):
    tasks = [{"id": 1, "data": {"input": "q", "output": "a"}, "annotations": [],
              "predictions": []}]
    code, _, err = run(capsys, "steps", str(save(here, tasks)))
    assert code == 2 and "steps" in err


def test_the_first_line_is_the_version(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    _, out, _ = run(capsys, "steps", "runs.jsonl")
    assert out.splitlines()[0] == f"judgekeeper {__version__}"


# Tool calls ------------------------------------------------------------------------------

def _written_steps(here, capsys, steps):
    (here / "runs.jsonl").write_text(json.dumps({"id": "a", "steps": steps}) + "\n",
                                     encoding="utf-8")
    code, _, err = run(capsys, "steps", "runs.jsonl")
    assert code == 0, err
    out = json.loads((here / ".judgekeeper/steps/label-these.json").read_text(encoding="utf-8"))
    return [s["content"] for s in out[0]["data"]["steps"]]


def test_an_openai_tool_call_is_written_as_a_line(here, capsys):
    call = {"id": "c1", "type": "function",
            "function": {"name": "search", "arguments": '{"q": "x"}'}}
    shown = _written_steps(here, capsys, [
        {"role": "assistant", "content": "", "tool_calls": [call], "secret_key": "NOPE"},
        {"role": "assistant", "content": "Looking.", "tool_calls": [call, call]}])
    assert shown[0] == 'Tool call: search({"q": "x"})'
    assert shown[1] == 'Looking.\nTool call: search({"q": "x"})\nTool call: search({"q": "x"})'
    assert "NOPE" not in json.dumps(shown)


def test_anthropic_content_blocks_are_written_as_text_and_tool_lines(here, capsys):
    shown = _written_steps(here, capsys, [
        {"role": "assistant", "content": [
            {"type": "text", "text": "I will look it up."},
            {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "x"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "Found it."}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": "Found"}, {"type": "text", "text": "it."}]},
            {"type": "image", "source": "NOPE"}]}])
    assert shown[0] == 'I will look it up.\nTool call: search({"q": "x"})'
    assert shown[1] == "Tool result: Found it."
    assert shown[2] == "Tool result: Found\nit."
    assert "NOPE" not in json.dumps(shown)


def test_arguments_that_are_not_json_are_kept_as_text(here, capsys):
    shown = _written_steps(here, capsys, [{"role": "assistant", "content": None, "tool_calls": [
        {"function": {"name": "run", "arguments": "not json"}}]}])
    assert shown == ["Tool call: run(not json)"]


# Guesses for runs that are not there ---------------------------------------------------------

def test_guesses_for_runs_not_in_the_export_are_counted_and_said(here, capsys):
    export = save(here, project())
    rows = [{"id": f"r{i}", "first_wrong_step": reviewer_first(i)} for i in range(40)]
    rows += [{"id": "x1", "first_wrong_step": 1}, {"id": "x2", "first_wrong_step": 0}]
    (here / "g.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    code, out, err = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert code == 0, err
    assert "2 guesses are for runs that are not in export.json." in out
    assert result(here)["reviewers"][0]["left_out"]["not_in_export"] == 2
    rows = rows[:40] + rows[40:41]
    (here / "g.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    _, out, _ = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert "1 guess is for a run that is not in export.json." in out


def test_no_such_line_when_every_guess_is_a_run(here, capsys):
    export = save(here, project())
    rows = [{"id": f"r{i}", "first_wrong_step": reviewer_first(i)} for i in range(40)]
    (here / "g.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    _, out, _ = run(capsys, "steps", str(export), "--reviewer", "g.jsonl")
    assert "not in export.json" not in out


# Exports it does not read --------------------------------------------------------------------

LOOKS_LIKE = ("{name} looks like a Label Studio JSON_MIN (or CSV) export. judgekeeper steps "
              "reads the full JSON export: in Label Studio, export as JSON.")


def test_a_json_min_export_is_named(here, capsys):
    rows = [{"steps": [{"role": "user", "content": "x"}], "id": 13, "first_wrong_step": 2,
             "annotator": 2, "annotation_id": 21, "lead_time": 3.0}]
    code, _, err = run(capsys, "steps", str(save(here, rows, "steps_min.json")))
    assert code == 2 and LOOKS_LIKE.format(name="steps_min.json") in err
    assert err.strip().splitlines()[-1].startswith("Next:")


def test_a_csv_export_is_named_with_or_without_a_reviewer(here, capsys):
    (here / "steps_csv.csv").write_text("annotation_id,annotator,first_wrong_step,id,steps\n"
                                        "21,2,2,13,\"[{'role': 'user'}]\"\n", encoding="utf-8")
    (here / "g.jsonl").write_text('{"id": 13, "first_wrong_step": 1}\n', encoding="utf-8")
    for extra in ([], ["--reviewer", "g.jsonl"]):
        code, _, err = run(capsys, "steps", "steps_csv.csv", *extra)
        assert code == 2 and LOOKS_LIKE.format(name="steps_csv.csv") in err
