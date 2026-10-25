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

    now = grid["corrected"]["levels"][str(level)]
    figures = [f"middle {level:.0%}", f"at least {pct(now['min_cell'])} times in 100",
               f"{pct(now['mean'])} on average",
               f"95% fell to {pct(grid['corrected']['levels']['0.95']['min_cell'])}"]
    reference = " ".join((root / "docs" / "reference.md").read_text(encoding="utf-8").split())
    for figure in figures:
        assert figure in reference, figure


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
    for figure in ("93.6", "96.2"):
        assert figure in md, figure
    assert "93.6" in readme  # the README's coverage figure
    for page in (readme, (root / "docs" / "reference.md").read_text(encoding="utf-8")):
        assert "examples/coverage" in page


def test_the_batch_grid_is_committed_and_holds_the_bar():
    """New answers join as batches: the ranges on 2 and 3 batches, run at today's level and
    committed, hold the true value as often as the level asks; the reference's figures come
    from there."""
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
    assert "## Batches" in (folder / "coverage.md").read_text(encoding="utf-8")
    reference = " ".join((root / "docs" / "reference.md").read_text(encoding="utf-8").split())
    for figure in (f"at least {start['min_cell'] * 100:.1f} times in 100",
                   f"{start['mean'] * 100:.1f} on average"):
        assert figure in reference, figure
