"""The pure parts of fixing the judge that `judgekeeper fix` uses: the cell weights, the pass
mark that fits the marks best, and where that pass mark probably is in the person's files."""

from __future__ import annotations

import os

import pytest

from judgekeeper import start_fix, weighted


def _marks(cells):
    """Final marks from {(judge, final): n}."""
    out = []
    for (judge, final), n in cells.items():
        out += [{"id": f"{judge}-{final}-{i}", "judge": judge, "final": final}
                for i in range(n)]
    return out


def _tnr(items, weights):
    return weighted._table(items, weights)["tnr"]


def test_cell_weights_keep_the_set_aside_numbers_those_of_all_labels():
    # 900 passes and 100 fails in the pool. Labels: the judge's passes 24 agreed + 1 not,
    # its fails 20 agreed + 5 not. On all labels, weighted by group (900 / 25, 100 / 25):
    # TNR = 20 * 4 / (20 * 4 + 1 * 36) = 0.69.
    pool = {"pass": 900, "fail": 100}
    marks = _marks({("pass", "pass"): 24, ("pass", "fail"): 1, ("fail", "fail"): 20,
                    ("fail", "pass"): 5})
    every = _tnr([(m["judge"], m["final"], m["judge"]) for m in marks],
                 {"pass": 900 / 25, "fail": 100 / 25})
    assert every == pytest.approx(80 / 116)
    # The four-cell split with every cell rounded up (8, 1, 6 and 2 set aside) holds
    # proportionally more disagreements: weighted by group it reads 0.43.
    by_cell = {}
    for m in marks:
        by_cell.setdefault(start_fix.cell(m), []).append(m)
    aside = (by_cell[("pass", True)][:8] + by_cell[("pass", False)][:1]
             + by_cell[("fail", True)][:6] + by_cell[("fail", False)][:2])
    old = _tnr([(m["judge"], m["final"], m["judge"]) for m in aside],
               {"pass": 900 / 9, "fail": 100 / 8})
    assert old == pytest.approx(75 / 175)
    # Weighted by cell, the set-aside part reads the same as all labels.
    weights = start_fix.cell_weights(marks, aside, pool)
    assert _tnr([(start_fix.cell(m), m["final"], m["judge"]) for m in aside],
                weights) == pytest.approx(every)


def test_the_mark_choice_on_a_hand_worked_example():
    # Used answers (group, final mark, score). Pass mark 0.5.
    # 0.2 F/F, 0.4 F/F, 0.55 P/F, 0.6 P/F, 0.8 P/P, 0.9 P/P, 0.45 F/P
    # Candidates between neighbours: ... the gap (0.6, 0.8) gives TPR 2/3 (0.45 still
    # fails) and TNR 4/4; the current mark gives TPR 2/3 and TNR 2/4.
    items = [("fail", "fail", 0.2), ("fail", "fail", 0.4), ("pass", "fail", 0.55),
             ("pass", "fail", 0.6), ("pass", "pass", 0.8), ("pass", "pass", 0.9),
             ("fail", "pass", 0.45)]
    weights = {"pass": 1.0, "fail": 1.0}
    assert start_fix.choose_mark(items, 0.5, ">=", weights) == 0.7
    # Ties go to the mark nearest the current one; the current mark wins a tie.
    fits = [("fail", "fail", 0.2), ("pass", "pass", 0.8)]
    assert start_fix.choose_mark(fits, 0.5, ">=", weights) == 0.5
    lower = [("pass", "pass", 0.2), ("pass", "fail", 0.6), ("fail", "fail", 0.9)]
    assert start_fix.choose_mark(lower, 0.7, "<=", weights) == 0.4


def test_the_mark_is_the_shortest_number_inside_its_gap():
    assert start_fix.nice_mark(0.6, 0.8) == 0.7
    assert start_fix.nice_mark(0.62, 0.71) == 0.7
    assert start_fix.nice_mark(0.695, 0.705) == 0.7
    assert start_fix.nice_mark(0.7, 0.71) == 0.705


def test_the_hand_over_per_source():
    assert start_fix.where_lines({"source": "deepeval", "op": ">="}, 0.65)[0] == (
        "Set threshold=0.65 in your metric, e.g. GEval(..., threshold=0.65).")
    assert start_fix.where_lines({"source": "mapped", "op": ">="}, 0.65)[0] == (
        "Set pass_mark = 0.65 in judgekeeper.toml [start].")
    # Double quotes, which work in Windows cmd as well.
    assert start_fix.where_lines({"source": "pass_if", "op": ">=", "rule": "score>=0.5"},
                                 0.65)[0] == 'Use --pass-if "score>=0.65".'
    # promptfoo's: the assertion's threshold, never searched for (YAML has no `=`)
    assert start_fix.where_lines({"source": "promptfoo", "op": ">="}, 0.65) == [
        "Set threshold: 0.65 on the assertion in your promptfoo config."]
    assert start_fix.searched({"source": "promptfoo"}) is None
    # A pass mark kept with each verdict, read by another reader: record() or the toml.
    for source in ("table", "jsonl"):
        assert start_fix.where_lines({"source": source, "op": ">="}, 0.65) == [
            ("Set pass_mark=0.65 in your judgekeeper.record() line, or pass_mark = 0.65 in "
             "judgekeeper.toml [start].")]


def test_the_search_goes_on_past_a_file_it_cannot_look_at(tmp_path, monkeypatch):
    (tmp_path / "b.py").write_text("GEval(threshold=0.5)\n", encoding="utf-8")
    real = os.scandir

    class Gone:
        name, path = "a.py", str(tmp_path / "a.py")

        def is_symlink(self):
            return False

        def is_dir(self):
            return False

        def is_file(self):
            return True

        def stat(self):
            raise FileNotFoundError(self.path)

    monkeypatch.setattr(start_fix.os, "scandir",
                        lambda folder: [Gone(), *real(folder)])
    assert start_fix.locate(tmp_path, "threshold", 0.5) == ("b.py", 1, "GEval(threshold=0.5)")


def test_the_search_skips_virtual_environments_and_judgekeeper(tmp_path):
    for folder in (".venv", "venv", "node_modules", ".git", ".judgekeeper"):
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / "x.py").write_text("GEval(threshold=0.5)\n", encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.5) is None
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "t.py").write_text("x = 1\nm = GEval(threshold=.50)\n",
                                               encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.5) == ("a/b/t.py", 2,
                                                            "m = GEval(threshold=.50)")
    deep = tmp_path / "1" / "2" / "3" / "4" / "5"
    deep.mkdir(parents=True)
    (deep / "t.py").write_text("threshold=0.9\n", encoding="utf-8")
    assert start_fix.locate(tmp_path, "threshold", 0.9) is None
