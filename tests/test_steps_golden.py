"""A Label Studio export reads exactly as in 1.4.0: every line `judgekeeper steps EXPORT.json`
prints, and result.json, for a set of made-up projects, against a recording made on 1.4.0.
Synthetic data only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from judgekeeper import __version__, textio
from judgekeeper.cli import main
from tests.test_steps import FIXTURES, annotation, prediction, project, reviewer_first, save, task

GOLDEN = FIXTURES / "golden_export_1_4.json"

# 1.5.0's words for the 1.4.0 lines, in this order: the AI that checks an agent's steps is
# the agent-as-a-judge, and its default name ("reviewer") is never printed. Nothing else.
WORDS = [
    ('Reviewer "reviewer" against your people,', "Your agent-as-a-judge against the people marking,"),
    ('Reviewer "', 'Agent-as-a-judge "'),
    ("Kappa: none (your people or your reviewer gave",
     "Kappa: none (the people marking or your agent-as-a-judge gave"),
    ("your reviewer", "your agent-as-a-judge"),
    ("your people", "the people marking"),
    ("no reviewer guesses", "no agent-as-a-judge guesses"),
    ("no guess from this reviewer,", "no guess from this agent-as-a-judge,"),
    ("No reviewer named", "No agent-as-a-judge named"),
]


def in_new_words(line: str) -> str:
    for old, new in WORDS:
        line = line.replace(old, new)
    return line


def _guesses(here: Path, rows) -> None:
    (here / "g.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")


def _numbers(here):
    save(here, project())
    return ["export.json"]


def _too_few(here):
    save(here, project(n=10))
    return ["export.json"]


def _ids_only(here):
    shutil.copy(FIXTURES / "ls_export_ids_only.json", here / "export.json")
    return ["export.json"]


def _full_predictions(here):
    shutil.copy(FIXTURES / "ls_export_full_predictions.json", here / "export.json")
    return ["export.json"]


def _no_labels(here):
    save(here, [task(i, [], [prediction("rv", 1)], run_id=f"r{i}") for i in range(3)])
    return ["export.json"]


def _one_run(here):
    save(here, [task(0, [annotation(2, 0)], [prediction("rv", 0)], run_id="a")])
    return ["export.json"]


def _one_run_no_label(here):
    save(here, [task(0, [], [prediction("rv", 0)], run_id="a")])
    return ["export.json"]


def _disagreed_and_unusable(here):
    tasks = project()
    tasks[0]["annotations"] = [annotation(2, 1), annotation(3, 2)]
    tasks[1]["annotations"] = [annotation(2, 99)]
    tasks[2]["annotations"] = [annotation(2, 1.5)]
    save(here, tasks)
    return ["export.json"]


def _reviewer_file_left_out(here):
    save(here, project())
    rows = [{"id": f"r{i}", "first_wrong_step": reviewer_first(i), "model": "my-reviewer"}
            for i in range(3, 40)]
    rows[0]["first_wrong_step"] = 99
    rows += [{"id": "x1", "first_wrong_step": 1, "model": "my-reviewer"},
             {"id": "x2", "first_wrong_step": 0, "model": "my-reviewer"}]
    _guesses(here, rows)
    return ["export.json", "--reviewer", "g.jsonl"]


def _reviewer_file_one_stray(here):
    save(here, project())
    rows = [{"id": f"r{i}", "first_wrong_step": reviewer_first(i)} for i in range(40)]
    _guesses(here, rows + [{"id": "x1", "first_wrong_step": 1}])
    return ["export.json", "--reviewer", "g.jsonl"]


def _several_reviewers(here):
    tasks = project()
    for i, t in enumerate(tasks):
        t["predictions"].append(prediction("reviewer-b", 0 if i < 20 else 1 + i % 5))
    save(here, tasks)
    return ["export.json"]


def _model_picks_one(here):
    _several_reviewers(here)
    return ["export.json", "--model", "reviewer-b"]


def _no_guesses(here):
    tasks = project()
    for t in tasks:
        t["predictions"] = []
    save(here, tasks)
    return ["export.json"]


SCENARIOS = {f.__name__.lstrip("_"): f for f in (
    _numbers, _too_few, _ids_only, _full_predictions, _no_labels, _one_run, _one_run_no_label,
    _disagreed_and_unusable, _reviewer_file_left_out, _reviewer_file_one_stray,
    _several_reviewers, _model_picks_one, _no_guesses)}


def said(here: Path, capsys, name: str) -> dict:
    """What one scenario prints and saves, with the version and the program's name made
    plain and the time it was made left out."""
    argv = SCENARIOS[name](here)
    code = main(["steps", *argv])
    out, err = capsys.readouterr()

    def plain(text: str) -> list[str]:
        text = text.replace(f"judgekeeper {__version__}", "judgekeeper VERSION")
        return text.replace(f"`{textio.program()} ", "`PROGRAM ").splitlines()

    saved = json.loads((here / ".judgekeeper/steps/result.json").read_text(encoding="utf-8"))
    saved.pop("made_at")
    saved["judgekeeper"] = "VERSION"
    return {"code": code, "out": plain(out), "err": plain(err), "result": saved}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_an_export_reads_line_for_line_as_in_1_4(tmp_path, monkeypatch, capsys, name):
    monkeypatch.chdir(tmp_path)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))[name]
    for stream in ("out", "err"):
        golden[stream] = [in_new_words(line) for line in golden[stream]]
    assert said(tmp_path, capsys, name) == golden


def test_every_scenario_is_recorded():
    assert sorted(json.loads(GOLDEN.read_text(encoding="utf-8"))) == sorted(SCENARIOS)
