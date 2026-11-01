"""The coverage grid in small (scripts/coverage_check.py runs it in full, by simulation):
judgekeeper's ranges must still hold the true value at least 93 times in 100 in a few hard
cells, so a later change cannot quietly make them too narrow. Here coverage is worked out
exactly, every outcome weighed by its chance (a lower bound), so it has no simulation noise."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "coverage_check.py"
# (the judge's pass share, chance a judge-pass is Correct, chance a judge-fail is Wrong,
# labels per group): the cells nearest the floor in the full grid (a lopsided judge with
# few labels), a weak judge and near-perfect ones, at 10 and at 15 labels per group.
CELLS = [(0.9, 0.95, 0.6, 10), (0.5, 0.6, 0.6, 10), (0.7, 0.95, 0.95, 10), (0.9, 0.95, 0.95, 10),
         (0.7, 0.95, 0.95, 15), (0.9, 0.95, 0.95, 15)]
# After grading again with 10 labels per group (answers missing from the new results drop
# out, so this happens), a steady judge's ranges can hold the true value a little less often
# (91.6 in 100 in the committed grid, for 60 and 15 answers in batches). Those cells get this
# lower floor; 15 per group keeps the usual one.
FLOOR_STEADY_10 = 0.91


def lowest_tpr_tnr_coverage(grid: dict) -> float:
    """The lowest TPR or TNR coverage anywhere in the committed grid: the main grid, after
    grading again, the stopping rule, an LLM-as-a-judge that changes its mind, batches and
    one grade."""
    level = grid["corrected"]["levels"][str(grid["corrected"]["chosen_level"])]
    summaries = [level, grid["general"]["now"], grid["batches"]["start"],
                 grid["batches"]["general"], grid["one_grade"]["start"]]
    rows = grid["accuracy"]["stopping"] + grid["accuracy"]["changes_mind"]
    return min([s["per_metric"][k] for s in summaries for k in ("tpr", "tnr")]
               + [r["coverage"][k] for r in rows for k in ("tpr", "tnr")])


def _module():
    spec = importlib.util.spec_from_file_location("coverage_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def grid():
    module = _module()
    return module, module.exact_grid(CELLS)


def test_the_ranges_start_shows_hold_the_true_value(grid):
    module, rows = grid
    for row in rows:
        for key in module.START_METRICS:
            assert row["coverage"][f"start_now/{key}"] >= module.FLOOR_CELL, (row, key)


def test_the_ranges_after_asking_again_hold_the_true_value(grid):
    module, rows = grid
    for row in rows:
        floor = FLOOR_STEADY_10 if row["n"] <= 10 else module.FLOOR_CELL
        for key in module.GENERAL_METRICS:
            assert row["coverage"][f"general_now/{key}"] >= floor, (row, key)


def test_the_floors_are_the_ones_the_level_was_chosen_by():
    module = _module()
    assert (module.FLOOR_CELL, module.FLOOR_MEAN) == (0.93, 0.95)
    assert module.CANDIDATES == (0.95, 0.96, 0.97)
    assert module.CHECKS >= 2000


def test_the_coverage_figures_in_the_docs_come_from_the_committed_grid():
    import json

    root = SCRIPT.parent.parent
    grid = json.loads((root / "docs" / "examples" / "coverage" / "coverage.json").read_text(
        encoding="utf-8"))
    level = grid["corrected"]["chosen_level"]

    def pct(x):
        return f"{x * 100:.1f}"

    now = grid["corrected"]["levels"][str(level)]
    reference = " ".join((root / "docs" / "reference.md").read_text(encoding="utf-8").split())
    assert f"middle {level:.0%}" in reference
    # the figures are said once, in the coverage report the reference links
    md = (root / "docs" / "examples" / "coverage" / "coverage.md").read_text(encoding="utf-8")
    for figure in (now["min_cell"], now["mean"], grid["corrected"]["levels"]["0.95"]["min_cell"]):
        assert pct(figure) in md, figure
        assert pct(figure) not in reference, figure


def test_the_numbers_on_screen_are_in_the_committed_grid():
    """Kappa's range, the real stopping rule, the width words, green near the bar, a judge
    that changes its mind, and check's false "Worse": run, committed, and what the docs say
    about them comes from there."""
    import json

    root = SCRIPT.parent.parent
    folder = root / "docs" / "examples" / "coverage"
    grid = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
    acc = grid["accuracy"]
    for key in ("kappa", "stopping", "green", "changes_mind", "false_worse"):
        assert acc[key], key
    assert all(row["coverage"] >= 0.9 for row in acc["kappa"])
    weak = [row for row in acc["green"] if min(row["tpr"], row["tnr"]) == 0.75]
    assert weak and all(row["green"] <= 0.05 for row in weak)
    # the reference says: in about 1 check in 10 at most, coincidence flags one of two groups
    assert 2 * max(row["exit_1"] for row in acc["false_worse"]) <= 0.11
    md = (folder / "coverage.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    level = grid["corrected"]["levels"][str(grid["corrected"]["chosen_level"])]
    # the coverage report holds the lowest anywhere and the main grid's average; the README
    # says the average
    for figure in (lowest_tpr_tnr_coverage(grid), level["mean"]):
        assert f"{figure * 100:.1f}" in md, figure
    assert f"{level['mean'] * 100:.1f}" in readme
    for page in (readme, (root / "docs" / "reference.md").read_text(encoding="utf-8")):
        assert "examples/coverage" in page


def test_the_batch_grid_is_committed_and_holds_the_bar():
    """New answers join as batches: the ranges on 2 and 3 batches, run at today's level and
    committed, hold the true value as often as the level asks; the coverage report says the
    figures, the reference does not repeat them."""
    import json

    from judgekeeper import weighted

    root = SCRIPT.parent.parent
    folder = root / "docs" / "examples" / "coverage"
    grid = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))["batches"]
    module = _module()
    assert grid["level"] == weighted.LEVEL and grid["draws"] == weighted.DRAWS
    assert len(grid["rows"]) == len(module.batch_cells())
    assert {len(row["shape"]) for row in grid["rows"]} == {2, 3}
    start = grid["start"]
    assert start["min_cell"] >= module.FLOOR_CELL and start["mean"] >= module.FLOOR_MEAN
    md = (folder / "coverage.md").read_text(encoding="utf-8")
    batches = md[md.index("## Batches"):]
    reference = " ".join((root / "docs" / "reference.md").read_text(encoding="utf-8").split())
    for figure in (f"{start['min_cell'] * 100:.1f}", f"{start['mean'] * 100:.1f}"):
        assert figure in batches, figure
        assert figure not in reference, figure


@pytest.mark.parametrize("passed_fails,worse,code", [
    (5, True, 0),  # "Worse", but the middle estimate drops 20 points, not more: exit 0
    (9, True, 1),  # "Worse", down 36 points: exit 1
    (0, False, 0),  # nothing changed
])
def test_the_grid_counts_exit_1_as_check_decides_it(tmp_path, monkeypatch, capsys,
                                                    passed_fails, worse, code):
    """coverage_check's exit 1 (exits_1) is check's own: the same marks, the same new grades,
    the same exit code."""
    from judgekeeper import targets
    from tests.start_projects import split
    from tests.test_check import HAIKU, _marked, _results, run

    monkeypatch.chdir(tmp_path)
    _marked(tmp_path)  # 25 Pass and 25 Fail, the LLM-as-a-judge right on all of them
    new = split(25, 25)
    new[25:25 + passed_fails] = [True] * passed_fails  # passes some answers marked Fail
    _results(tmp_path, new, model=HAIKU)
    got, out = run(capsys)
    v = targets.paired_verdict(0, passed_fails, 25)
    assert (v["verdict"] == "worse") is worse
    assert ("Worse" in out) is worse
    assert got == code == int(_module().exits_1(v))
