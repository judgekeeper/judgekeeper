"""`judgekeeper start` reads `.judgekeeper/records/`, the files `judgekeeper.record()` writes.

All the files whose judge is the newest file's judge are used (one eval run can be many
processes, so many files); a newer file wins for a repeated answer. Several judge names:
`start` asks which, and `--metric` answers. `start --new` keeps `records/`. A last line cut
short (the program stopped while writing it) is left out; a file judgekeeper cannot read is
left out with how to see why.
"""

from __future__ import annotations

import json
import time

import pytest

from judgekeeper import again, find, start, start_again, start_label
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, records_project, split


@pytest.fixture(autouse=True)
def no_labeling(monkeypatch):
    calls = []

    def run_labeling(found, port, open_browser, say, command="judgekeeper start"):
        calls.append(found)
        say("(labeling page)")
        return 0

    monkeypatch.setattr("judgekeeper.start_label.run_labeling", run_labeling)
    return calls


def run(capsys, *argv):
    code = main(["start", *map(str, argv), "--yes"])
    out, err = capsys.readouterr()
    return code, out, err


NOW = time.time()


def two_processes(root, **kwargs):
    """One eval run in two processes: 20 answers in one file, 16 in the other."""
    records_project(root, split(12, 8), pid=4101, mtime=NOW - 60, **kwargs)
    records_project(root, split(8, 8), pid=4102, start=20, mtime=NOW - 30, **kwargs)


def test_start_finds_the_records_of_every_process(tmp_path, capsys, no_labeling):
    two_processes(tmp_path)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Your judge's saved records: 36 from judgekeeper.record() (2 files in " \
           ".judgekeeper/records/)" in out
    assert 'Your judge: Safe wording "Be polite." with claude-opus-5' in out
    assert "36 answers with a verdict: the judge passed 20 and failed 16" in out
    assert "older results" not in out
    (found,) = no_labeling
    assert found.tool == "records" and len(found.used) == 2


def test_the_search_sees_the_records_folder_only(tmp_path):
    records_project(tmp_path, split(2, 2))
    (tmp_path / ".judgekeeper" / "pool.jsonl").write_text("{}\n", encoding="utf-8")
    found = find.search(tmp_path)
    assert [r.rel for r in found.readable("records")] == [
        ".judgekeeper/records/Safe-wording-2026-10-05-4101.jsonl"]
    assert "table" not in found.results


def test_several_judges_ask_which_and_metric_answers(tmp_path, capsys):
    records_project(tmp_path, split(20, 16), name="Safe wording", pid=1)
    records_project(tmp_path, split(18, 18), name="Plain language", pid=1, tag=" plain")
    code, out, _ = run(capsys, tmp_path)
    assert code == start.EXIT_QUESTION
    assert "--metric 'Plain language'" in out or '--metric "Plain language"' in out
    code, out, _ = run(capsys, tmp_path, "--metric", "Plain language")
    assert code == 0
    assert "Your judge's saved records: 36 from judgekeeper.record() (1 file in " in out
    assert "Your judge: Plain language" in out


def test_a_changed_judge_leaves_the_older_records_out(tmp_path, capsys, no_labeling):
    records_project(tmp_path, split(20, 16), pid=1, rule="Be polite.", mtime=NOW - 600)
    records_project(tmp_path, split(20, 16), pid=2, rule="Be polite and brief.",
                    tag=" v2", mtime=NOW - 60)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "Your judge's saved records: 36 from judgekeeper.record() (1 file in " in out
    assert 'Your judge: Safe wording "Be polite and brief."' in out
    (found,) = no_labeling
    assert found.used == [".judgekeeper/records/Safe-wording-2026-10-05-2.jsonl"]


def test_a_newer_file_wins_for_the_same_answer(tmp_path, no_labeling, capsys):
    records_project(tmp_path, [True] * 36, pid=1, mtime=NOW - 600)
    records_project(tmp_path, [False] * 4, pid=2, mtime=NOW - 60)
    _, out, _ = run(capsys, tmp_path)
    (found,) = no_labeling
    assert found.pool.n_pass == 32 and found.pool.n_fail == 4
    assert "4 repeats of the same answer were merged." in out


def test_a_last_line_cut_short_is_left_out(tmp_path, capsys, no_labeling):
    path = records_project(tmp_path, split(20, 16))
    with path.open("a", encoding="utf-8") as f:
        f.write('{"schema_version": 2, "name": "Safe wording", "inp')
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "the last line of .judgekeeper/records/Safe-wording-2026-10-05-4101.jsonl was cut " \
           "short (the program stopped while writing it) and was left out" in out
    assert len(no_labeling[0].pool.answers) == 36


def test_a_file_it_cannot_read_is_left_out_with_how_to_see_why(tmp_path, capsys):
    two_processes(tmp_path)
    bad = records_project(tmp_path, [True], pid=9, mtime=NOW - 90)
    bad.write_text('{"label": "pass", "score": "high"}\n{"label": "fail"}\n',
                   encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ".judgekeeper/records/Safe-wording-2026-10-05-9.jsonl could not be read (line 1: " \
           "score 'high' is not a number), so it was left out. To see every problem: " \
           "judgekeeper import records .judgekeeper/records/Safe-wording-2026-10-05-9.jsonl " \
           "--check" in out
    assert "Your judge's saved records: 36 from judgekeeper.record()" in out


def test_records_and_another_tool_ask_which(tmp_path, capsys):
    two_processes(tmp_path)
    promptfoo_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, tmp_path)
    assert code == start.EXIT_QUESTION
    assert "--tool records" in out
    code, out, _ = run(capsys, tmp_path, "--tool", "records")
    assert code == 0 and "Your judge's saved records: 36" in out


def test_start_reads_one_records_file_named_on_the_command_line(tmp_path, capsys):
    path = records_project(tmp_path, split(20, 16))
    code, out, _ = run(capsys, path)
    assert code == 0
    assert "Your judge's saved records: 36 from judgekeeper.record() (1 file" in out


def test_more_answers_come_from_running_the_eval_again(tmp_path):
    records_project(tmp_path, split(3, 2))
    found = start.find_judge(tmp_path)
    assert start.more_answers(found) == [
        ("  Run your eval on more answers: each judgekeeper.record() call saves one more "
         "verdict."),
        "  Running your eval again makes model calls, so it costs money."]


def test_new_keeps_the_records(tmp_path, capsys):
    two_processes(tmp_path)
    start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    (tmp_path / ".judgekeeper" / "baseline.json").write_text("{}", encoding="utf-8")
    moved = start_again.move_to_previous(start_label.Workspace(tmp_path), lambda line: None)
    kept = sorted(p.name for p in (tmp_path / ".judgekeeper").iterdir())
    assert kept == ["baseline.json", moved.name, "records"]
    assert len(list((tmp_path / ".judgekeeper" / "records").glob("*.jsonl"))) == 2
    assert not (moved / "records").exists()


def test_asking_again_says_record_judges_cannot_be_run(tmp_path):
    two_processes(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    plan = again.make_plan(ws, dry=False)
    assert plan.status == again.CANT
    assert "saved by judgekeeper.record()" in plan.why
    assert "table" not in plan.why


def test_nothing_found_offers_the_record_line(tmp_path, capsys):
    (tmp_path / "requirements.txt").write_text("deepeval\n", encoding="utf-8")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert ("Or save your judge's verdicts from now on with one judgekeeper.record() line "
            "where it runs: www.judgekeeper.com/assistant.html#add-the-record-line has a "
            "prompt that asks your coding agent to add it.") in out


def test_records_reach_the_labeling_page_like_any_other_results(tmp_path):
    two_processes(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    data = ws.data()
    assert data["tool"] == "records" and data["metric"] == "Safe wording"
    assert data["rule"] == "Be polite."
    pool = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    assert len(pool) == 36


def test_asking_again_on_records_ends_with_the_judge_command_way(tmp_path, capsys):
    """Like every "can't": the last line says how to wrap the judge as a command."""
    from judgekeeper.start_label import StartSession, save_result

    two_processes(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    session = StartSession(ws)
    groups = {q["id"]: q["group"] for q in ws.data()["queue"]}
    for item in session.items:
        session.update({"id": item["id"], "label": groups[item["id"]]})
    save_result(ws, session, say=lambda line="": None)
    capsys.readouterr()
    assert main(["start", str(tmp_path), "--ask-again"]) == 0
    lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert any("saved by judgekeeper.record()" in line for line in lines)
    assert lines[-1] == again.WRAP
    assert lines[-1].startswith("To ask your judge again yourself, wrap it as a command: "
                                "judgekeeper start --ask-again --judge-command '...'")
