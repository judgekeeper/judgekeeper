"""After `check` on a results file, its Next line says to give the next change's new results
(`check <new results file>`), never the same file again."""

from __future__ import annotations

import csv
import json

import pytest

from judgekeeper import marks
from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import marked_rows, table_project
from tests.test_front import assert_one_next_at_the_end


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _regraded(here, as_marked: bool) -> None:
    """Every answer marked (a quarter against the grade), fix run, and the marked answers
    graded again into new.csv: as marked, or every one the other way."""
    table_project(here, [True] * 30 + [False] * 30)
    main(["--no-browser", "--port", "0"])
    main(["--stop"])
    s = StartSession(Workspace(here))
    for n, item in enumerate(s.items):
        group = s.groups[item["id"]]
        s.update({"id": item["id"], "seconds": 4,
                  "label": ("fail" if group == "pass" else "pass") if n % 4 == 0 else group})
    main(["fix"])
    ws = Workspace(here)
    ids = {json.loads(line)["output"]: json.loads(line)["id"]
           for line in ws.pool.read_text(encoding="utf-8").splitlines()}
    marked = marks.read(ws.marks).counted()
    with (ws.dir / "fix" / "marked-answers.csv").open(encoding="utf-8", newline="") as f:
        rows = marked_rows(csv.DictReader(f))
    with (here / "new.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        for r in rows:
            mark = marked[ids[r["answer"]]]
            w.writerow([r["question"], r["answer"],
                        mark if as_marked else ("fail" if mark == "pass" else "pass")])


def test_after_a_check_on_a_file_the_next_change_has_new_results(here, capsys):
    _regraded(here, as_marked=True)
    capsys.readouterr()
    main(["check", "new.csv"])
    out = capsys.readouterr().out
    assert assert_one_next_at_the_end(out) == (
        "Next: nothing to do. After you change your LLM-as-a-judge again, run "
        "`judgekeeper check <new results file>`.")


def test_after_worse_on_a_file_another_change_has_new_results(here, capsys):
    _regraded(here, as_marked=False)
    capsys.readouterr()
    main(["check", "new.csv"])
    out = capsys.readouterr().out
    line = assert_one_next_at_the_end(out)
    assert "check new.csv" not in line and "<new results file>" in line, line
