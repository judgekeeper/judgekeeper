"""Step marks in, numbers out: .judgekeeper/steps/marks.jsonl (the first wrong step a person
clicked for each run on the page) read against the runs file, and the same numbers as for a
Label Studio export. Synthetic data only; no test calls an AI."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from judgekeeper import metrics, steps
from judgekeeper.cli import main
from tests.test_steps import FIXTURES, people_first, reviewer_first

MARKS = Path(".judgekeeper") / "steps" / "marks.jsonl"
HEADER = {"step_marks": 1, "created_at": "2026-11-26T10:00:00Z",
          "judgekeeper_version": "1.5.0", "runs": "runs.jsonl", "runs_hash": "0" * 64}


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def result(here: Path) -> dict:
    return json.loads((here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8"))


def canonical_hash(run_steps) -> str:
    """The marks file's steps_hash, written out from its definition."""
    return hashlib.sha256(json.dumps(run_steps, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def write_runs(here: Path, n=40, n_steps=6) -> Path:
    rows = [{"id": f"r{i}", "steps": [{"role": "assistant" if k % 2 else "user",
                                       "content": f"made up step {k + 1} of run {i}"}
                                      for k in range(n_steps)]} for i in range(n)]
    path = here / "runs.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def mark(run_id, step, hashes, **more):
    return {"id": run_id, "first_wrong_step": step, "steps_hash": hashes.get(run_id, "f" * 64),
            "at": "2026-11-26T10:00:12Z", "seconds": 4.5, "by": "page", **more}


def write_marks(here: Path, lines, header=True) -> Path:
    path = here / MARKS
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ([json.dumps(HEADER)] if header else []) + [
        x if isinstance(x, str) else json.dumps(x) for x in lines]
    path.write_text("".join(x + "\n" for x in body), encoding="utf-8")
    return path


def raw_steps(runs_path: Path) -> dict[str, list]:
    """Each run's `steps` exactly as the runs file holds them."""
    rows = [json.loads(x) for x in runs_path.read_text(encoding="utf-8").splitlines() if x]
    return {str(row["id"]): row["steps"] for row in rows}


def hashes_of(runs_path: Path) -> dict[str, str]:
    return {run_id: canonical_hash(raw) for run_id, raw in raw_steps(runs_path).items()}


def marked_project(here: Path, n=40):
    """40 runs; the person marks each as the people did in test_steps.project; the reviewer
    guesses as there."""
    runs = write_runs(here, n)
    hashes = hashes_of(runs)
    write_marks(here, [mark(f"r{i}", people_first(i), hashes) for i in range(n)])
    (here / "g.jsonl").write_text("".join(
        json.dumps({"id": f"r{i}", "first_wrong_step": reviewer_first(i),
                    "model": "reviewer-a"}) + "\n" for i in range(n)), encoding="utf-8")
    return runs


# The marks file -> an Export ---------------------------------------------------------------

def test_the_fixture_reads_newest_wins_and_null_takes_back(here):
    runs = steps.read_runs(FIXTURES / "runs.jsonl")
    export = steps.read_marks(FIXTURES / "marks.jsonl", runs)
    assert isinstance(export, steps.Export)
    by_id = {t.id: t for t in export.tasks}
    assert list(by_id) == ["run-1", "run-2", "3"]
    assert (by_id["run-1"].state, by_id["run-1"].label) == ("label", 4)  # 2, then 4
    assert (by_id["run-2"].state, by_id["run-2"].label) == ("label", 0)
    assert (by_id["3"].state, by_id["3"].label) == ("no_label", None)  # 1, then taken back
    assert [t.n_steps for t in export.tasks] == [4, 2, 1]
    assert export.who == {} and export.guesses == {}
    assert export.stats["tasks"] == 3 and export.stats["labelled"] == 2
    assert export.stats["no_label"] == 1 and export.stats["changed"] == 0


def test_the_fixture_hashes_are_the_canonical_hash_of_the_steps_in_the_file():
    runs = steps.read_runs(FIXTURES / "runs.jsonl")
    raw = raw_steps(FIXTURES / "runs.jsonl")
    lines = (FIXTURES / "marks.jsonl").read_text(encoding="utf-8").splitlines()
    assert set(json.loads(lines[0])) == {"step_marks", "created_at", "judgekeeper_version",
                                         "runs", "runs_hash"}
    by_id = {r.id: r for r in runs}
    for line in lines[1:]:
        row = json.loads(line)
        assert set(row) - {"link"} == {"id", "first_wrong_step", "steps_hash", "at", "seconds",
                                       "by"}
        assert row["steps_hash"] == canonical_hash(raw[row["id"]])
        assert steps.steps_hash(raw[row["id"]]) == by_id[row["id"]].steps_hash == row["steps_hash"]
    links = {json.loads(line).get("link") for line in lines[1:]}
    assert {"printed", "browser-env"} <= links


def test_link_printed_or_browser_env_is_the_one_extra_field_a_mark_may_carry(here):
    runs_path = write_runs(here, 4)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 2, hashes, link="printed"), mark("r1", 1, hashes, link="x"),
                       mark("r2", 1, hashes, note="SECRET-TEXT"),
                       mark("r3", 3, hashes, link="browser-env")])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert [t.label for t in export.tasks] == [2, None, None, 3]
    assert export.stats["broken"] == [3, 4]


def test_a_run_whose_steps_changed_loses_its_mark_and_is_counted(here):
    runs_path = write_runs(here, 3)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 2, hashes), mark("r1", 1, {"r1": "a" * 64}),
                       mark("r2", 0, {"r2": "b" * 64})])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert [(t.id, t.label) for t in export.tasks] == [("r0", 2), ("r1", None), ("r2", None)]
    assert export.stats["changed"] == 2 and export.stats["labelled"] == 1


def test_a_mark_for_a_run_not_in_the_runs_is_counted(here):
    runs_path = write_runs(here, 2)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 1, hashes), mark("gone", 1, hashes), mark("gone2", 0, hashes),
                       mark("undone", 1, hashes), mark("undone", None, hashes)])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert export.stats["not_in_runs"] == 2  # a taken-back mark is no mark at all


def test_an_int_run_id_is_matched_as_its_string(here):
    path = here / "runs.jsonl"
    path.write_text('{"id": 7, "steps": [{"role": "user", "content": "x"},'
                    ' {"role": "assistant", "content": "y"}]}\n', encoding="utf-8")
    runs = steps.read_runs(path)
    write_marks(here, [mark("7", 2, hashes_of(path))])
    assert steps.read_marks(here / MARKS, runs).tasks[0].label == 2


def test_how_steps_are_shown_does_not_change_the_hash(here, monkeypatch):
    path = write_runs(here, 2)
    kept = {r.id: r.steps_hash for r in steps.read_runs(path)}
    assert kept == hashes_of(path)
    assert all(kept[r.id] != steps.steps_hash(r.steps) for r in steps.read_runs(path))
    monkeypatch.setattr(steps, "step_text", lambda step: "shown another way")
    shown = steps.read_runs(path)
    assert [r.steps[0]["content"] for r in shown] == ["shown another way"] * 2
    assert {r.id: r.steps_hash for r in shown} == kept


def test_numbers_from_marks_save_next_to_the_marks_never_in_the_current_folder(
        tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    runs = marked_project(project)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    lines, saved = steps.numbers_from_marks(runs, project / MARKS, project / "g.jsonl")
    assert list(elsewhere.iterdir()) == []
    assert result(project) == saved and saved["reviewers"][0]["name"] == "reviewer-a"
    assert lines[-1].startswith("Next: change your agent-as-a-judge")


def test_a_broken_line_is_said_by_number_never_quoted_and_skipped(here):
    runs_path = write_runs(here, 3)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 2, hashes), "not json SECRET-TEXT",
                       '{"id": "r0", "first_wrong_step": "SECRET-TEXT", "steps_hash": "x"}',
                       json.dumps(mark("r1", True, hashes)), json.dumps(mark("r1", -1, hashes)),
                       json.dumps(mark("r1", 1.5, hashes)), '["SECRET-TEXT"]',
                       json.dumps({"first_wrong_step": 1, "steps_hash": hashes["r2"]}),
                       json.dumps({"id": "r2", "first_wrong_step": 1}),
                       json.dumps({k: v for k, v in mark("r2", 1, hashes).items() if k != "at"}),
                       json.dumps(mark("r2", 1, hashes, by="SECRET-TEXT")),
                       json.dumps(mark(5, 1, hashes)), json.dumps(HEADER)])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert export.tasks[0].label == 2  # a broken line never undoes a mark
    assert export.stats["broken"] == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    assert export.stats["labelled"] == 1


def test_a_mark_past_the_last_step_is_unusable(here):
    runs_path = write_runs(here, 2, n_steps=3)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 4, hashes), mark("r1", 3, hashes)])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert [t.state for t in export.tasks] == ["unusable", "label"]
    assert export.stats["unusable"] == 1


def test_no_header_and_an_empty_file_read_as_no_marks(here):
    runs_path = write_runs(here, 2)
    hashes = hashes_of(runs_path)
    write_marks(here, [mark("r0", 1, hashes)], header=False)
    assert steps.read_marks(here / MARKS, steps.read_runs(runs_path)).stats["labelled"] == 1
    (here / MARKS).write_text("", encoding="utf-8")
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert export.stats["labelled"] == 0 and export.stats["broken"] == []


# Marks -> the numbers ------------------------------------------------------------------------

def test_numbers_from_marks_are_the_numbers_of_an_export(here):
    runs = marked_project(here)
    lines, saved = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    people = ["wrong" if people_first(i) else "fine" for i in range(40)]
    guess = ["wrong" if reviewer_first(i) else "fine" for i in range(40)]
    ag = metrics.agreement(people, guess, "wrong", "fine")
    reviewer = saved["reviewers"][0]
    assert reviewer["name"] == "reviewer-a"
    assert reviewer["run_level"]["tpr"]["p"] == ag["tpr"] == 15 / 20
    assert reviewer["run_level"]["tnr"]["p"] == ag["tnr"] == 16 / 20
    assert reviewer["run_level"]["kappa"] == pytest.approx(ag["kappa"])
    assert reviewer["step_level"]["same"] == metrics.wilson(9, 15)
    assert saved["source"] == {"marks": ".judgekeeper/steps/marks.jsonl", "runs": "runs.jsonl",
                               "reviewer_file": "g.jsonl"}
    assert saved["kind"] == "agent-steps" and "fingerprint" in reviewer
    assert result(here) == saved
    assert lines[0] == ("Read 40 runs from runs.jsonl and your marks from "
                        ".judgekeeper/steps/marks.jsonl: you marked 40 of them.")
    assert lines[-1].startswith("Next: change your agent-as-a-judge")
    assert not any("Label Studio" in line for line in lines)


def test_numbers_from_marks_with_no_reviewer_say_how_to_add_one(here):
    runs = marked_project(here)
    lines, saved = steps.numbers_from_marks(runs, here / MARKS, None)
    assert saved["reviewers"] == [] and saved["source"]["reviewer_file"] is None
    assert "There are no agent-as-a-judge picks to compare your marks with yet." in lines
    assert lines[-1] == ("Next: give your agent-as-a-judge's first wrong step for each run as a JSONL "
                         'file (one line per run: {"id": ..., "first_wrong_step": ..., '
                         '"model": ...}) and run `judgekeeper steps runs.jsonl --reviewer '
                         'PICKS.jsonl`.')


def test_no_marks_yet_says_click_on_the_page(here):
    runs = write_runs(here, 3)
    write_marks(here, [])
    lines, saved = steps.numbers_from_marks(runs, here / MARKS, None)
    assert lines[0] == ("Read 3 runs from runs.jsonl and your marks from "
                        ".judgekeeper/steps/marks.jsonl: you marked 0 of them.")
    assert "You have not marked a run yet." in lines
    assert lines[-1] == ("Next: click the first wrong step of each run on the page (or \"All "
                         "steps are fine\"): `judgekeeper steps runs.jsonl`.")
    assert saved["people"]["labelled"] == 0


def test_one_run_reads_it(here):
    runs = write_runs(here, 1)
    write_marks(here, [mark("r0", 1, hashes_of(runs))])
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, None)
    assert lines[0] == ("Read 1 run from runs.jsonl and your marks from "
                        ".judgekeeper/steps/marks.jsonl: you marked it.")
    write_marks(here, [])
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, None)
    assert lines[0].endswith(": you have not marked it.")


def test_too_few_marks_say_mark_more_on_the_page(here):
    runs = marked_project(here, n=12)
    write_marks(here, [mark(f"r{i}", 0, hashes_of(runs)) for i in range(10)])  # 2 not marked
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert lines[-1] == ("Next: mark more runs on the page: "
                         "`judgekeeper steps runs.jsonl --reviewer g.jsonl`.")


def test_left_out_marks_are_said_one_line_each(here):
    runs = write_runs(here, 4)
    hashes = hashes_of(runs)
    write_marks(here, [mark("r0", 1, hashes), mark("r1", 1, {}), mark("gone", 1, hashes),
                       "not json SECRET-TEXT", mark("r2", 99, hashes)])
    lines, saved = steps.numbers_from_marks(runs, here / MARKS, None)
    said = "\n".join(lines)
    assert ("1 mark is for a run whose steps changed after you marked it; it is left out "
            "(mark that run again).") in lines
    assert "1 mark is for a run that is not in runs.jsonl; it is left out." in lines
    assert ("Line 5 of .judgekeeper/steps/marks.jsonl is not a mark judgekeeper can read; it "
            "is left out.") in lines
    assert ("1 run had a number that is not a step of the run (a whole number from 0 to the "
            "last step); they are left out.") in lines
    assert "SECRET-TEXT" not in said and "People disagreed" not in said
    assert saved["people"]["changed"] == 1 and saved["people"]["not_in_runs"] == 1


def test_several_left_out_marks_are_said_in_the_plural(here):
    runs = write_runs(here, 4)
    hashes = hashes_of(runs)
    write_marks(here, [mark("r0", 1, {}), mark("r1", 1, {}), mark("x", 1, hashes),
                       mark("y", 1, hashes), "{", "[", "{", "[", "{", "[", "{"])
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, None)
    assert ("2 marks are for runs whose steps changed after you marked them; they are left "
            "out (mark those runs again).") in lines
    assert "2 marks are for runs that are not in runs.jsonl; they are left out." in lines
    assert ("Lines 6, 7, 8, 9, 10 and 2 more of .judgekeeper/steps/marks.jsonl are not marks "
            "judgekeeper can read; they are left out.") in lines


def test_guesses_for_runs_not_in_the_runs_file_name_the_runs_file(here):
    runs = marked_project(here)
    with (here / "g.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "x1", "first_wrong_step": 1, "model": "reviewer-a"}) + "\n")
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert "  Left out: 1 pick is for a run that is not in runs.jsonl." in lines


def _pick_again(here, *rows):
    with (here / "g.jsonl").open("a", encoding="utf-8") as f:
        for run_id, step in rows:
            f.write(json.dumps({"id": run_id, "first_wrong_step": step, "model": "reviewer-a"})
                    + "\n")


def test_a_run_picked_twice_is_said_and_the_later_pick_is_used(here):
    runs = marked_project(here)
    _pick_again(here, ("r3", 0))  # line 41; r3 was picked on line 4
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert "Line 41 of g.jsonl picks run r3 again; the later line is used." in lines
    assert steps.read_guesses(here / "g.jsonl")[0]["reviewer-a"]["r3"] == 0


def test_runs_picked_again_are_said_in_one_line(here):
    runs = marked_project(here)
    _pick_again(here, *[(f"r{i}", 0) for i in range(7)])
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert ("Lines 41, 42, 43, 44, 45 and 2 more of g.jsonl pick a run again; the later line "
            "is used for each.") in lines


def test_a_run_picked_again_is_not_named_when_its_id_looks_like_a_key(here):
    key = "sk-ant-api03-" + "Q" * 80
    runs = here / "runs.jsonl"
    runs.write_text(json.dumps({"id": key, "steps": [{"role": "user", "content": "x"}]})
                    + "\n", encoding="utf-8")
    write_marks(here, [mark(key, 1, hashes_of(runs))])
    (here / "g.jsonl").write_text("".join(json.dumps({"id": key, "first_wrong_step": s})
                                          + "\n" for s in (1, 0)), encoding="utf-8")
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert "Line 2 of g.jsonl picks a run again; the later line is used." in lines
    assert "Q" * 20 not in "\n".join(lines)


def test_one_run_picked_by_two_agents_as_a_judge_is_not_a_repeat(here):
    runs = marked_project(here)
    with (here / "g.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "r3", "first_wrong_step": 0, "model": "reviewer-b"}) + "\n")
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert not any("again; the later line" in x for x in lines)


# The command ---------------------------------------------------------------------------------

def test_steps_runs_with_marks_prints_the_numbers(here, capsys):
    marked_project(here)
    code, out, err = run(capsys, "steps", "runs.jsonl", "--reviewer", "g.jsonl")
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0].startswith("judgekeeper ")
    assert any(x.startswith("Wrote 40 runs for Label Studio") for x in lines)
    assert ("Read 40 runs from runs.jsonl and your marks from .judgekeeper/steps/marks.jsonl: "
            "you marked 40 of them.") in lines
    assert "  The same first wrong step: 60% (9 of 15; between 36% and 80%)." in lines
    assert sum(x.startswith("Next:") for x in lines) == 1
    assert lines[-1].startswith("Next: change your agent-as-a-judge")
    assert result(here)["source"]["marks"] == ".judgekeeper/steps/marks.jsonl"


def test_steps_runs_with_marks_and_no_reviewer_is_exit_3(here, capsys):
    marked_project(here)
    code, out, _ = run(capsys, "steps", "runs.jsonl")
    assert code == 3
    assert out.rstrip().splitlines()[-1].startswith("Next: give your agent-as-a-judge's first wrong")


def test_steps_runs_takes_the_model_option(here, capsys):
    marked_project(here)
    with (here / "g.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "r0", "first_wrong_step": 0, "model": "reviewer-b"}) + "\n")
    code, _, err = run(capsys, "steps", "runs.jsonl", "--reviewer", "g.jsonl",
                       "--model", "reviewer-a")
    assert code == 0, err
    assert [r["name"] for r in result(here)["reviewers"]] == ["reviewer-a"]


def test_a_bad_reviewer_file_stops_before_anything_is_written(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    (here / "g.jsonl").write_text('{"id": "run-1", "first_wrong_step": "SECRET-TEXT"}\n',
                                  encoding="utf-8")
    code, out, err = run(capsys, "steps", "runs.jsonl", "--reviewer", "g.jsonl")
    assert code == 2 and "Line 1 of g.jsonl" in err and "SECRET-TEXT" not in out + err
    assert not (here / ".judgekeeper/steps/label-these.json").exists()
    code, _, err = run(capsys, "steps", "runs.jsonl", "--reviewer", "none.jsonl")
    assert code == 2 and "Next:" in err


def test_steps_runs_with_a_reviewer_and_no_marks_writes_the_screen_as_before(here, capsys):
    shutil.copy(FIXTURES / "runs.jsonl", here / "runs.jsonl")
    (here / "g.jsonl").write_text('{"id": "run-1", "first_wrong_step": 1}\n', encoding="utf-8")
    code, out, err = run(capsys, "steps", "runs.jsonl", "--reviewer", "g.jsonl")
    assert code == 0, err
    lines = out.rstrip().splitlines()  # the page opens for marking, with how to import
    assert lines[-2] == 'Next: mark runs on the page, then click "See the numbers so far".'
    assert lines[-1].startswith("Label in Label Studio instead?")
    assert not (here / ".judgekeeper/steps/result.json").exists()


def test_say_numbers_from_marks_says_nothing_with_no_marks_file(here, capsys):
    runs = marked_project(here)
    assert steps.say_numbers_from_marks(runs, "runs.jsonl", "g.jsonl") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Read 40 runs from runs.jsonl and your marks")
    assert out[-1].startswith("Next: change your agent-as-a-judge")
    assert steps.marks_path(Path("runs.jsonl")).resolve() == (here / MARKS).resolve()
    (here / MARKS).unlink()
    assert steps.say_numbers_from_marks(runs, "runs.jsonl", "g.jsonl") is None
    assert capsys.readouterr().out == ""


def test_the_default_name_is_never_printed(here, capsys):
    runs = marked_project(here)
    (here / "g.jsonl").write_text("".join(
        json.dumps({"id": f"r{i}", "first_wrong_step": reviewer_first(i)}) + "\n"
        for i in range(40)), encoding="utf-8")
    lines, saved = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert saved["reviewers"][0]["name"] == steps.DEFAULT_REVIEWER == "reviewer"
    assert "Your agent-as-a-judge against your marks, on 40 runs both marked:" in lines
    assert not any("reviewer" in line.replace("--reviewer", "").lower() for line in lines)


def test_a_named_agent_as_a_judge_is_quoted(here):
    runs = marked_project(here)
    lines, _ = steps.numbers_from_marks(runs, here / MARKS, here / "g.jsonl")
    assert 'Agent-as-a-judge "reviewer-a" against your marks, on 40 runs both marked:' in lines
    assert ("  Runs you say went wrong: your agent-as-a-judge also says so for 75% (15 of 20; "
            "between 53% and 89%).") in lines
    assert any(x.startswith("  Runs you say were fine: your agent-as-a-judge") for x in lines)
    assert ("How often your agent-as-a-judge finds the same first wrong step as you, on the 15 "
            "runs you both say went wrong:") in lines
    assert not any("people" in line for line in lines)


def test_kappa_none_on_marks_says_you():
    numbers = steps.compare([steps.Task(f"r{i}", 6, 0 if i < 15 else 2, "label")
                             for i in range(30)], {f"r{i}": 2 for i in range(30)})
    numbers["run_level"]["kappa"] = None  # as when every answer is the same
    lines = steps._reviewer_lines("reviewer", numbers, marks=True)
    assert ("  Kappa: none (you or your agent-as-a-judge gave the same answer for every "
            "run).") in lines
    assert "(the people marking or" in " ".join(steps._reviewer_lines("reviewer", numbers))


def test_a_huge_whole_number_of_seconds_is_a_broken_line(here):
    runs_path = write_runs(here, 2)
    hashes = hashes_of(runs_path)
    huge = json.dumps(mark("r0", 1, hashes)).replace('"seconds": 4.5', '"seconds": ' + "9" * 400)
    write_marks(here, [mark("r1", 2, hashes), huge])
    export = steps.read_marks(here / MARKS, steps.read_runs(runs_path))
    assert export.stats["broken"] == [3] and [t.label for t in export.tasks] == [None, 2]


def test_a_lone_surrogate_in_a_run_is_said_by_line(here, capsys):
    (here / "runs.jsonl").write_text(
        '{"id": "a", "steps": [{"role": "user", "content": "x"}]}\n'
        '{"id": "b", "steps": [{"role": "user", "content": "SECRET-TEXT \\ud800"}]}\n',
        encoding="utf-8")
    with pytest.raises(steps.StepsError, match="Line 2 of runs.jsonl") as e:
        steps.read_runs(here / "runs.jsonl")
    assert "SECRET-TEXT" not in str(e.value)
    code, out, err = run(capsys, "steps", "runs.jsonl")
    assert code == 2 and "Line 2 of runs.jsonl" in err and "SECRET-TEXT" not in out + err


def test_numbers_from_marks_with_a_missing_file_is_a_steps_error(here):
    runs = marked_project(here)
    with pytest.raises(steps.StepsError, match="marks.jsonl"):
        steps.numbers_from_marks(runs, here / "none" / "marks.jsonl", None)
    with pytest.raises(steps.StepsError, match="gone.jsonl"):
        steps.numbers_from_marks(here / "gone.jsonl", here / MARKS, None)


# rc2: one undecodable line, or one holding a NUL or a control character, is one damaged line

@pytest.mark.parametrize("bad", [
    b'{"id": "r1\x00", "first_wrong_step": 1}',  # NUL: valid UTF-8, not JSON text
    b'{"id": "r1\xe9", "first_wrong_step": 1}',  # a Latin-1 byte: not UTF-8
    b'\x00\x00\x00',
], ids=["nul", "latin-1", "nul-only"])
def test_a_bad_byte_leaves_out_its_line_only(here, bad):
    """With a line holding a control character outside a JSON escape after it: one more
    damaged line, said with it."""
    runs = write_runs(here, 4)
    hashes = hashes_of(runs)
    path = write_marks(here, [mark(f"r{i}", 1, hashes) for i in range(4)])
    path.write_bytes(path.read_bytes() + bad + b'\n{"id": "r1\x01", "first_wrong_step": 1}\n')
    lines, saved = steps.numbers_from_marks(runs, path, None)
    assert ("Lines 6 and 7 of .judgekeeper/steps/marks.jsonl are not marks judgekeeper can "
            "read; they are left out.") in lines, lines
    assert not any("UTF-8" in x for x in lines), lines
    assert saved["people"]["labelled"] == 4


def test_the_page_reads_the_other_marks_past_a_bad_byte(here):
    from judgekeeper import steps_page
    from judgekeeper.start_label import Workspace

    runs = write_runs(here, 4)
    hashes = hashes_of(runs)
    path = write_marks(here, [mark(f"r{i}", 1, hashes) for i in range(3)])
    path.write_bytes(path.read_bytes() + b'{"id": "r3\xe9"}\n')
    session = steps_page.StepsSession(Workspace(here), runs)
    assert session.marked() == {"r0": 1, "r1": 1, "r2": 1}


def test_a_marks_file_that_is_not_utf8_at_all_still_says_so(here):
    runs = write_runs(here, 4)
    hashes = hashes_of(runs)
    path = write_marks(here, [mark(f"r{i}", 1, hashes) for i in range(4)])
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-16"))
    with pytest.raises(steps.StepsError, match="is not saved as UTF-8 text"):
        steps.numbers_from_marks(runs, path, None)
