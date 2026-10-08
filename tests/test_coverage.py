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
# few labels), a weak judge and a near-perfect one.
CELLS = [(0.9, 0.95, 0.6, 10), (0.5, 0.6, 0.6, 10), (0.7, 0.95, 0.95, 10)]


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
        for key in module.GENERAL_METRICS:
            assert row["coverage"][f"general_now/{key}"] >= module.FLOOR_CELL, (row, key)


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

    now, before = grid["corrected"]["levels"][str(level)], grid["corrected"]["before"]
    figures = [f"middle {level:.0%}", f"at least {pct(now['min_cell'])} times in 100",
               f"{pct(now['mean'])} on average",
               f"95% fell to {pct(grid['corrected']['levels']['0.95']['min_cell'])}",
               f"{pct(before['mean'])} times in 100 on average",
               f"{pct(grid['corrected']['narrower']['mean'])}% narrower on average",
               f"as rarely as {pct(grid['general']['before']['min_cell'])} times in 100"]
    reference = " ".join((root / "docs" / "reference.md").read_text(encoding="utf-8").split())
    for figure in figures:
        assert figure in reference, figure
    changelog = " ".join((root / "CHANGELOG.md").read_text(encoding="utf-8").split())
    for figure in figures[1:2] + figures[5:]:
        assert figure in changelog, figure
