"""Reading a big results file says it is alive: after about 2 seconds, a line on stderr every
few seconds ("Reading results.json (100,000 answers so far)..."), so a person or a coding agent
sees the command is working. A quick read says nothing."""

from __future__ import annotations

import csv

import pytest

from judgekeeper import textio
from judgekeeper.cli import main
from tests.start_projects import promptfoo_project, split


@pytest.fixture
def slow(monkeypatch):
    """A clock that moves 1 s each time it is read: a big file takes long."""
    now = [0.0]

    def clock():
        now[0] += 1
        return now[0]

    monkeypatch.setattr(textio, "_clock", clock)


def _big_csv(path, n):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        w.writerows([f"q{i}", f"a{i}", "pass" if i % 2 else "fail"] for i in range(n))


def test_a_slow_table_says_how_far_it_got(tmp_path, capsys, slow):
    _big_csv(tmp_path / "results.csv", 3000)
    main([str(tmp_path / "results.csv"), "--yes"])
    err = capsys.readouterr().err
    lines = [x for x in err.splitlines() if x.startswith("Reading results.csv (")]
    assert lines and lines[0].endswith(" answers so far)...")
    assert len(lines) < 20  # every few seconds, not every row


def test_a_slow_promptfoo_file_says_it_too(tmp_path, capsys, slow):
    promptfoo_project(tmp_path, split(1500, 1500))
    main([str(tmp_path / "results.json"), "--yes"])
    assert "Reading results.json (" in capsys.readouterr().err


def test_a_quick_read_says_nothing(tmp_path, capsys):
    _big_csv(tmp_path / "results.csv", 3000)
    main([str(tmp_path / "results.csv"), "--yes"])
    assert "Reading " not in capsys.readouterr().err
