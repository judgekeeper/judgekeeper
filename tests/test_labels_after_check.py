"""After `check`, a labels import sorts labels as before it: plain `judgekeeper` reads the
newest results (the regraded marked answers only), but labels for answers the
LLM-as-a-judge graded error are still "for answers your LLM-as-a-judge didn't grade Pass or
Fail", not "don't match any answer in your results"."""

from __future__ import annotations

import csv

import pytest

from judgekeeper.cli import main
from judgekeeper.start_label import StartSession, Workspace
from tests.start_projects import answer, marked_rows, question, table_project
from tests.test_labels_import import flat, run

SKIPPED = ("Skipped 8 labels: 3 don't match any answer in your results (the answer text must "
           "be the same) 5 are for answers your LLM-as-a-judge didn't grade Pass or Fail")


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _labels(here, n_left, n_other=3):
    with (here / "mine.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["question", "answer", "label"])
        w.writerows([question(i), answer(i), "pass"] for i in range(60, 60 + n_left))
        w.writerows([f"Other {i}?", f"Not in the results {i}.", "pass"] for i in range(n_other))


def _checked(here, capsys):
    table_project(here, [True] * 30 + [False] * 30 + ["error"] * 5)
    run(capsys)
    main(["--stop"])
    s = StartSession(Workspace(here))
    for n, item in enumerate(s.items):
        group = s.groups[item["id"]]
        mark = ("fail" if group == "pass" else "pass") if n % 4 == 0 else group
        s.update({"id": item["id"], "label": mark, "seconds": 4})
    _labels(here, 5)
    code, before = run(capsys, "--labels", "mine.csv")
    assert code == 3 and SKIPPED in flat(before), before
    main(["--stop"])
    main(["fix"])
    marked = marked_rows((here / ".judgekeeper" / "fix" / "marked-answers.csv").open(
        encoding="utf-8", newline=""))
    with (here / "new.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "output", "verdict"])
        w.writerows([r["question"], r["answer"], "pass"] for r in marked)
    main(["check", "new.csv"])
    capsys.readouterr()


def test_labels_for_ungraded_answers_are_counted_as_before_check(here, capsys):
    _checked(here, capsys)
    code, after = run(capsys, "--labels", "mine.csv")
    assert code == 3 and SKIPPED in flat(after), after
