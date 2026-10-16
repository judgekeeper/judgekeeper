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

from judgekeeper import again, find, start, start_again, start_label
from tests.start_projects import records_project, split

NOW = time.time()


def two_processes(root, **kwargs):
    """One eval run in two processes: 20 answers in one file, 16 in the other."""
    records_project(root, split(12, 8), pid=4101, mtime=NOW - 60, **kwargs)
    records_project(root, split(8, 8), pid=4102, start=20, mtime=NOW - 30, **kwargs)


def test_the_search_sees_the_records_folder_only(tmp_path):
    records_project(tmp_path, split(2, 2))
    (tmp_path / ".judgekeeper" / "pool.jsonl").write_text("{}\n", encoding="utf-8")
    found = find.search(tmp_path)
    assert [r.rel for r in found.readable("records")] == [
        ".judgekeeper/records/Safe-wording-2026-10-05-4101.jsonl"]
    assert "table" not in found.results


def test_new_keeps_the_records(tmp_path, capsys):
    two_processes(tmp_path)
    start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    (tmp_path / ".judgekeeper" / "baseline.json").write_text("{}", encoding="utf-8")
    moved = start_again.move_to_previous(start_label.Workspace(tmp_path), lambda line: None)
    kept = sorted(p.name for p in (tmp_path / ".judgekeeper").iterdir())
    assert kept == [".gitignore", "baseline.json", moved.name, "records"]
    assert len(list((tmp_path / ".judgekeeper" / "records").glob("*.jsonl"))) == 2
    assert not (moved / "records").exists()


def test_asking_again_says_record_judges_cannot_be_run(tmp_path):
    two_processes(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    plan = again.make_plan(ws, dry=False)
    assert plan.status == again.CANT
    assert "saved by judgekeeper.record()" in plan.why
    assert "table" not in plan.why


def test_records_reach_the_labeling_page_like_any_other_results(tmp_path):
    two_processes(tmp_path)
    ws = start_label.prepare(start.find_judge(tmp_path), say=lambda line="": None)
    data = ws.data()
    assert data["tool"] == "records" and data["metric"] == "Safe wording"
    assert data["rule"] == "Be polite."
    pool = [json.loads(line) for line in ws.pool.read_text(encoding="utf-8").splitlines()]
    assert len(pool) == 36


