"""For a table, the file `fix` hands back holds the person's own column names, so grading it and
giving it back to `fix` works as it is; a table judgekeeper can't read is told its columns."""

from __future__ import annotations

import csv

import pytest

from tests.test_only_reads import person, project, run


@pytest.fixture
def here(tmp_path, monkeypatch):
    root = tmp_path / "support-bot"
    root.mkdir()
    monkeypatch.chdir(root)
    return root


def _rows(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_marked_answers_of_a_table_use_its_own_column_names(here, capsys, monkeypatch):
    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    code, out = run(capsys, "fix")
    assert code == 0, out
    assert _rows(ws.dir / "fix" / "marked-answers.csv")[0] == ["input", "output"]


def test_marked_answers_graded_again_go_back_to_fix_as_they_are(here, capsys, monkeypatch):
    from tests.start_projects import answer

    ws = project("jsonl", here, monkeypatch)
    capsys.readouterr()
    run(capsys, "fix")
    rows = _rows(ws.dir / "fix" / "marked-answers.csv")
    index = {answer(i): i for i in range(40)}
    with (here / "results-v2.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([*rows[0], "verdict"])  # the file as it was handed out, plus the grades
        for q, a in rows[1:]:
            w.writerow([q, a, "pass" if person(index[a]) else "fail"])
    code, out = run(capsys, "fix", "results-v2.csv")
    assert "not a results file" not in out, out
    assert code != 2, out


def test_a_table_judgekeeper_cannot_read_is_told_its_columns(here, capsys, monkeypatch):
    project("jsonl", here, monkeypatch)
    capsys.readouterr()
    (here / "results-v2.csv").write_text("question,answer,verdict\nq,a,pass\n", encoding="utf-8")
    code, out = run(capsys, "fix", "results-v2.csv")
    assert code == 2, out
    said = " ".join(out.split())
    assert "results-v2.csv is not a results file judgekeeper can read" in said, said
    assert ("Its columns are question, answer and verdict, so judgekeeper can't read it."
            in said), said
